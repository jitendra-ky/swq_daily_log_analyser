"""
ReconciliationService — Reconciliation Service.
=================================================
Implements LLD §2 "Reconciliation Service" methods computeTotals and
computeByPaymentMode.

Public API
----------
    service = ReconciliationService()
    report, breakdowns = service.compute(valid_records, clinic_id)

    report       # unsaved ReconciliationReport ORM instance
    breakdowns   # list of unsaved PaymentModeBreakdown ORM instances

Design rules
------------
- Stateless — safe to instantiate once and reuse across requests.
- Never persists anything — the orchestrator calls .save() / bulk_create()
  on the returned objects.
- Assumes valid_records are already saved to the DB (BillingRecord.pk is set,
  line_items is queryable via the reverse FK).  This is Option A as confirmed
  in the implementation plan: the orchestrator saves records first, then calls
  this service.
- report_date is inferred from min(r.timestamp).date() over the records.
  On empty input, report_date defaults to datetime.date.today().
- Duplicate-report guard is the orchestrator's responsibility — this service
  always produces a fresh unsaved instance.
- Only payment modes that appear in the input produce a PaymentModeBreakdown
  row.  Modes with no records are omitted entirely.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import TYPE_CHECKING

from core.models.billing import BillingRecord
from core.models.reconciliation import PaymentModeBreakdown, ReconciliationReport

if TYPE_CHECKING:
    pass  # kept for future type-only imports


# ── service ──────────────────────────────────────────────────────────────────


class ReconciliationService:
    """
    LLD: Reconciliation Service.

    Stateless — safe to instantiate once and reuse across requests.
    """

    # ── public ───────────────────────────────────────────────────────────────

    def compute(
        self,
        valid_records: list[BillingRecord],
        clinic_id: str,
    ) -> tuple[ReconciliationReport, list[PaymentModeBreakdown]]:
        """
        LLD: computeTotals + computeByPaymentMode → ReconciliationReport.

        Accepts a list of already-saved BillingRecord instances (with PKs set
        and line_items queryable).  Returns an unsaved ReconciliationReport and
        a list of unsaved PaymentModeBreakdown instances ready for the
        orchestrator to persist.

        Args:
            valid_records: List of saved BillingRecord ORM instances that
                           passed IngestionService validation.
            clinic_id:     Clinic identifier to stamp on the report.

        Returns:
            A 2-tuple of (ReconciliationReport, list[PaymentModeBreakdown]).
            Neither object is saved — the orchestrator handles persistence.
        """
        report_date = self._infer_report_date(valid_records)
        report = self._compute_totals(valid_records, clinic_id, report_date)
        breakdowns = self._compute_by_payment_mode(valid_records)
        return report, breakdowns

    # ── private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _infer_report_date(
        valid_records: list[BillingRecord],
    ) -> datetime.date:
        """
        Infer the report date from the earliest record timestamp.

        Falls back to today when valid_records is empty (empty-input edge case).
        """
        if not valid_records:
            return datetime.date.today()
        return min(r.timestamp for r in valid_records).date()

    def _compute_totals(
        self,
        valid_records: list[BillingRecord],
        clinic_id: str,
        report_date: datetime.date,
    ) -> ReconciliationReport:
        """
        LLD: computeTotals — produce the six scalar summary fields.

        Iterates valid_records once.  Non-refund records contribute to billed /
        collected / outstanding / visit_count.  Refund records contribute to
        total_refunds_paise / refund_count.

        Field derivations (LLD §1 design notes):
          total_billed_paise      = sum gross_billed_paise() for non-refunds
          total_collected_paise   = sum amount_paid_paise     for non-refunds
          total_outstanding_paise = total_billed − total_collected
          total_refunds_paise     = sum abs(amount_paid_paise) for refunds
                                    (stored positive in the report)
          visit_count             = count of non-refund records
          refund_count            = count of refund records
        """
        total_billed = 0
        total_collected = 0
        total_refunds = 0
        visit_count = 0
        refund_count = 0

        for record in valid_records:
            if record.is_refund:
                # amount_paid_paise is negative for refunds (LLD §1 design note);
                # store the absolute value in the report.
                total_refunds += abs(record.amount_paid_paise)
                refund_count += 1
            else:
                total_billed += record.gross_billed_paise()
                total_collected += record.amount_paid_paise
                visit_count += 1

        total_outstanding = total_billed - total_collected

        return ReconciliationReport(
            clinic_id=clinic_id,
            report_date=report_date,
            total_billed_paise=total_billed,
            total_collected_paise=total_collected,
            total_outstanding_paise=total_outstanding,
            total_refunds_paise=total_refunds,
            visit_count=visit_count,
            refund_count=refund_count,
        )

    def _compute_by_payment_mode(
        self,
        valid_records: list[BillingRecord],
    ) -> list[PaymentModeBreakdown]:
        """
        LLD: computeByPaymentMode — one PaymentModeBreakdown per mode present.

        Groups valid_records by payment_mode, then applies the same billed /
        collected / outstanding / refunds derivations as _compute_totals but
        scoped to each group.

        Only modes that appear in the input produce a breakdown row.
        """
        # Accumulate per-mode totals in a plain dict to avoid repeated scans.
        # Structure: {mode: {"billed": int, "collected": int, "refunds": int}}
        totals: dict[str, dict[str, int]] = defaultdict(
            lambda: {"billed": 0, "collected": 0, "refunds": 0}
        )

        for record in valid_records:
            mode = record.payment_mode  # already uppercased by IngestionService
            if record.is_refund:
                totals[mode]["refunds"] += abs(record.amount_paid_paise)
            else:
                totals[mode]["billed"] += record.gross_billed_paise()
                totals[mode]["collected"] += record.amount_paid_paise

        breakdowns: list[PaymentModeBreakdown] = []
        for mode, sums in totals.items():
            outstanding = sums["billed"] - sums["collected"]
            breakdowns.append(
                PaymentModeBreakdown(
                    mode=mode,
                    billed_paise=sums["billed"],
                    collected_paise=sums["collected"],
                    outstanding_paise=outstanding,
                    refunds_paise=sums["refunds"],
                )
            )

        return breakdowns
