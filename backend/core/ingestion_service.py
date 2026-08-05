"""
IngestionService — Ingestion & Validation Service.
===================================================
Implements LLD §2 "Ingestion & Validation Service" and the full
validation flow from LLD §4.

Public API
----------
    service = IngestionService()
    result  = service.parse_log(raw_rows, batch="billing_log_2026-07-27")

    result.valid_records   # list of unsaved BillingRecord instances
    result.errors          # list of unsaved ValidationError instances
    result.total_rows      # int — total rows seen (valid + invalid)

Design rules (LLD §4)
---------------------
- One bad row never aborts the batch.  parse_log() always returns both
  lists; the caller decides whether partial success is acceptable.
- Every paise field must be a plain Python int — floats are rejected.
- Refund records must carry a *negative* amount_paid_paise.
- Unsaved LineItem data is stored on BillingRecord._pending_line_items
  (list[dict]) so the orchestrator can bulk_create them after it has
  saved the parent record and obtained its PK.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.domain.parse_result import ParseResult
from core.models import BillingRecord, PaymentMode
from core.models import ValidationError as ValidationErrorModel

# ── constants ────────────────────────────────────────────────────────────────

_REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "clinic_id",
    "visit_id",
    "timestamp",
    "doctor_id",
    "line_items",
    "payment_mode",
    "amount_paid_paise",
    "discount_paise",
    "is_refund",
)

_PAISE_FIELDS: tuple[str, ...] = (
    "amount_paid_paise",
    "discount_paise",
)

_VALID_PAYMENT_MODES: frozenset[str] = frozenset(
    m.value for m in PaymentMode  # "CASH", "CARD", "UPI"
)

# ISO-8601 UTC: ends with Z or +00:00
_ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$"
)


# ── service ──────────────────────────────────────────────────────────────────


class IngestionService:
    """
    LLD: Ingestion & Validation Service.

    Stateless — safe to instantiate once and reuse across requests.
    """

    # ── public ───────────────────────────────────────────────────────────────

    def parse_log(
        self,
        raw_rows: list[dict[str, Any]],
        batch: str,
    ) -> ParseResult:
        """
        LLD: parseLog(rawRows) → ParseResult.

        Iterates every row, delegates to _validate_record, accumulates
        results.  Never raises — even a completely empty input is valid.

        Args:
            raw_rows: List of dicts parsed from the billing JSON file.
            batch:    Caller-supplied identifier grouping all errors from
                      this upload (e.g. the log filename stem).

        Returns:
            ParseResult with valid_records, errors, and total_rows set.
        """
        result = ParseResult(total_rows=len(raw_rows))

        for index, row in enumerate(raw_rows):
            row_ref = row.get("visit_id") or f"row_{index}"
            record, errors = self._validate_record(row, row_ref, batch)
            if errors:
                result.errors.extend(errors)
            else:
                result.valid_records.append(record)  # type: ignore[arg-type]

        return result

    # ── private ──────────────────────────────────────────────────────────────

    def _validate_record(
        self,
        row: dict[str, Any],
        row_ref: str,
        batch: str,
    ) -> tuple[BillingRecord | None, list[ValidationErrorModel]]:
        """
        LLD: validateRecord — run all checks in §4 order.

        Returns (BillingRecord, []) on success or (None, [errors]) on failure.
        A single row can produce multiple ValidationError objects but is
        excluded from valid_records as soon as the first check fails.
        """
        errors: list[ValidationErrorModel] = []

        # ── Check 1: required fields present & correctly typed ────────────
        for field_name in _REQUIRED_TOP_LEVEL:
            if field_name not in row:
                errors.append(
                    self._make_error(
                        batch=batch,
                        row_ref=row_ref,
                        field=field_name,
                        reason="missing or wrong type",
                        raw_value="",
                    )
                )

        # Missing any required field → stop; further checks are meaningless.
        if errors:
            return None, errors

        # ── Check 2: paise fields must be plain int (not float, not str) ──
        for field_name in _PAISE_FIELDS:
            val = row[field_name]
            if not isinstance(val, int) or isinstance(val, bool):
                errors.append(
                    self._make_error(
                        batch=batch,
                        row_ref=row_ref,
                        field=field_name,
                        reason="non-integer paise value",
                        raw_value=str(val),
                    )
                )

        # Also check unit_price_paise on every line item
        for i, item in enumerate(row["line_items"]):
            val = item.get("unit_price_paise")
            if val is not None and (not isinstance(val, int) or isinstance(val, bool)):
                errors.append(
                    self._make_error(
                        batch=batch,
                        row_ref=row_ref,
                        field=f"line_items[{i}].unit_price_paise",
                        reason="non-integer paise value",
                        raw_value=str(val),
                    )
                )

        if errors:
            return None, errors

        # ── Check 3: refund → amount_paid_paise must be negative ──────────
        is_refund = row["is_refund"]
        amount = row["amount_paid_paise"]
        if is_refund and amount >= 0:
            errors.append(
                self._make_error(
                    batch=batch,
                    row_ref=row_ref,
                    field="amount_paid_paise",
                    reason="refund must be a negative adjustment",
                    raw_value=str(amount),
                )
            )
            return None, errors

        # ── Check 4: timestamp is valid ISO 8601 UTC ──────────────────────
        ts_raw: str = row["timestamp"]
        parsed_ts: datetime | None = None
        if not isinstance(ts_raw, str) or not _ISO_UTC_RE.match(ts_raw):
            errors.append(
                self._make_error(
                    batch=batch,
                    row_ref=row_ref,
                    field="timestamp",
                    reason="invalid timestamp format",
                    raw_value=str(ts_raw),
                )
            )
        else:
            try:
                parsed_ts = datetime.fromisoformat(
                    ts_raw.replace("Z", "+00:00")
                )
            except ValueError:
                errors.append(
                    self._make_error(
                        batch=batch,
                        row_ref=row_ref,
                        field="timestamp",
                        reason="invalid timestamp format",
                        raw_value=ts_raw,
                    )
                )

        if errors:
            return None, errors

        # ── Check 5: line_items non-empty, every qty > 0 ──────────────────
        items: list[dict] = row["line_items"]
        if not isinstance(items, list) or len(items) == 0:
            errors.append(
                self._make_error(
                    batch=batch,
                    row_ref=row_ref,
                    field="line_items",
                    reason="invalid or empty line_items",
                    raw_value=str(items),
                )
            )
        else:
            for i, item in enumerate(items):
                qty = item.get("qty")
                if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                    errors.append(
                        self._make_error(
                            batch=batch,
                            row_ref=row_ref,
                            field=f"line_items[{i}].qty",
                            reason="invalid or empty line_items",
                            raw_value=str(qty),
                        )
                    )

        if errors:
            return None, errors

        # ── Check 6: payment_mode is cash / card / upi ────────────────────
        pm_raw: str = row["payment_mode"]
        pm_upper = pm_raw.upper() if isinstance(pm_raw, str) else ""
        if pm_upper not in _VALID_PAYMENT_MODES:
            errors.append(
                self._make_error(
                    batch=batch,
                    row_ref=row_ref,
                    field="payment_mode",
                    reason="invalid payment_mode",
                    raw_value=str(pm_raw),
                )
            )
            return None, errors

        # ── All checks passed — build unsaved ORM instances ───────────────
        record = BillingRecord(
            clinic_id=row["clinic_id"],
            visit_id=row["visit_id"],
            timestamp=parsed_ts,  # type: ignore[arg-type]
            doctor_id=row["doctor_id"],
            payment_mode=pm_upper,
            amount_paid_paise=row["amount_paid_paise"],
            discount_paise=row["discount_paise"],
            is_refund=row["is_refund"],
        )

        # Attach raw line-item dicts for the orchestrator to bulk_create
        # after the parent record has been saved and has a PK.
        record._pending_line_items: list[dict] = [  # type: ignore[attr-defined]
            {
                "drug_name": item["drug_name"],
                "qty": item["qty"],
                "unit_price_paise": item["unit_price_paise"],
            }
            for item in items
        ]

        return record, []

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_error(
        *,
        batch: str,
        row_ref: str,
        field: str,
        reason: str,
        raw_value: str,
    ) -> ValidationErrorModel:
        """Return an unsaved ValidationError ORM instance."""
        return ValidationErrorModel(
            upload_batch=batch,
            row_ref=row_ref,
            field=field,
            reason=reason,
            raw_value=raw_value,
        )
