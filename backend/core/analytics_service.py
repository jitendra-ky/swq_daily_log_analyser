"""
AnalyticsService — Analytics Service.
======================================
Implements LLD §2 "Analytics Service" methods computeRevenueByHour,
rankByQuantity, and rankByRevenue.

Public API
----------
    service = AnalyticsService()
    report, hourly_rows, rank_rows = service.compute(valid_records, clinic_id)

    report       # unsaved AnalyticsReport ORM instance
    hourly_rows  # list of unsaved HourlyRevenue ORM instances
    rank_rows    # list of unsaved MedicineRankEntry ORM instances
                 # (rank_type "qty" and "revenue" entries combined)

Design rules
------------
- Stateless — safe to instantiate once and reuse across requests.
- Never persists anything — the orchestrator calls .save() / bulk_create()
  on the returned objects after saving the parent AnalyticsReport and
  obtaining its PK.
- Accepts valid_records from two contexts:
    • Already-saved BillingRecord instances (production path): line items
      are fetched via record.line_items.all().
    • Unsaved BillingRecord instances carrying record._pending_line_items
      (list[dict]) set by IngestionService (test path): no DB query needed.
  The private _get_line_items() helper abstracts this dual-path.
- report_date is inferred from min(r.timestamp).date() over the records.
  On empty input, report_date defaults to datetime.date.today().
- Refund records (is_refund=True) are excluded from all three computations:
  they represent goods returned, not sold, and full exclusion is the
  simpler, more auditable approach.
- Hourly revenue = amount_paid_paise (collected) for non-refund records,
  consistent with ReconciliationService.total_collected_paise.
- Per-drug revenue in rankByRevenue = qty × unit_price_paise per line item
  (gross line-item revenue), avoiding discount-proration across drugs and
  the float math that would introduce.
- TOP_N controls the maximum number of entries in each ranked list.
  Ties within TOP_N are broken alphabetically by drug_name (deterministic).
- Hours with zero revenue are omitted; only hours that appear in the input
  produce a HourlyRevenue row (mirrors PaymentModeBreakdown omit-if-absent).
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from core.models import BillingRecord
from core.models.analytics import AnalyticsReport, HourlyRevenue, MedicineRankEntry


# ── constants ────────────────────────────────────────────────────────────────

# Maximum entries returned per ranked list (rankByQuantity, rankByRevenue).
TOP_N: int = 5


# ── service ──────────────────────────────────────────────────────────────────


class AnalyticsService:
    """
    LLD: Analytics Service.

    Stateless — safe to instantiate once and reuse across requests.
    """

    # ── public ───────────────────────────────────────────────────────────────

    def compute(
        self,
        valid_records: list[BillingRecord],
        clinic_id: str,
    ) -> tuple[AnalyticsReport, list[HourlyRevenue], list[MedicineRankEntry]]:
        """
        LLD: computeRevenueByHour + rankByQuantity + rankByRevenue → AnalyticsReport.

        Accepts a list of BillingRecord instances (saved or unsaved — see module
        docstring for the dual-path rule).  Returns an unsaved AnalyticsReport and
        two flat lists of unsaved child ORM instances ready for the orchestrator
        to persist.

        Args:
            valid_records: BillingRecord instances that passed IngestionService
                           validation.  May be saved (have PKs) or unsaved (carry
                           _pending_line_items).
            clinic_id:     Clinic identifier to stamp on the report.

        Returns:
            A 3-tuple of:
              • AnalyticsReport (unsaved)
              • list[HourlyRevenue] (unsaved, analytics_report FK not yet set)
              • list[MedicineRankEntry] (unsaved, analytics_report FK not yet set),
                combining both rank_type="qty" and rank_type="revenue" entries.
        """
        report_date = self._infer_report_date(valid_records)
        report = AnalyticsReport(clinic_id=clinic_id, report_date=report_date)

        hourly_rows = self._compute_revenue_by_hour(valid_records)
        qty_rows = self._rank_by_quantity(valid_records)
        rev_rows = self._rank_by_revenue(valid_records)

        rank_rows = qty_rows + rev_rows
        return report, hourly_rows, rank_rows

    # ── private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _infer_report_date(
        valid_records: list[BillingRecord],
    ) -> datetime.date:
        """
        Infer the report date from the earliest record timestamp.

        Falls back to today when valid_records is empty (empty-input edge case).
        Mirrors ReconciliationService._infer_report_date exactly.
        """
        if not valid_records:
            return datetime.date.today()
        return min(r.timestamp for r in valid_records).date()

    @staticmethod
    def _get_line_items(record: BillingRecord) -> list[dict]:
        """
        Return line items for a record regardless of whether it has been saved.

        Dual-path (see module docstring):
          • Unsaved path: record._pending_line_items is a list[dict] set by
            IngestionService.  Used during testing so no DB query is needed.
          • Saved path: record.line_items.all() is a queryset.  Normalised into
            the same list[dict] shape as the unsaved path for uniform handling.
        """
        if hasattr(record, "_pending_line_items"):
            return record._pending_line_items  # type: ignore[attr-defined]
        return [
            {
                "drug_name": li.drug_name,
                "qty": li.qty,
                "unit_price_paise": li.unit_price_paise,
            }
            for li in record.line_items.all()
        ]

    def _compute_revenue_by_hour(
        self,
        valid_records: list[BillingRecord],
    ) -> list[HourlyRevenue]:
        """
        LLD: computeRevenueByHour — bucket collected revenue by UTC hour.

        Revenue = amount_paid_paise for non-refund records (collected amount,
        consistent with ReconciliationService.total_collected_paise).
        Refund records are excluded entirely.
        Hours with no revenue are omitted from the output.

        Returns:
            list[HourlyRevenue] ordered by hour (0–23), with analytics_report
            FK not yet set.
        """
        totals: dict[int, int] = defaultdict(int)

        for record in valid_records:
            if record.is_refund:
                continue
            hour = record.timestamp.hour
            totals[hour] += record.amount_paid_paise

        return [
            HourlyRevenue(hour=hour, revenue_paise=revenue)
            for hour, revenue in sorted(totals.items())
        ]

    def _rank_by_quantity(
        self,
        valid_records: list[BillingRecord],
    ) -> list[MedicineRankEntry]:
        """
        LLD: rankByQuantity — top TOP_N drugs by total units dispensed.

        Aggregates qty per drug_name across all line items of non-refund records.
        Ties broken alphabetically by drug_name (deterministic for tests).

        Returns:
            list[MedicineRankEntry] with rank_type="qty", length ≤ TOP_N,
            analytics_report FK not yet set.
        """
        qty_totals: dict[str, int] = defaultdict(int)

        for record in valid_records:
            if record.is_refund:
                continue
            for item in self._get_line_items(record):
                qty_totals[item["drug_name"]] += item["qty"]

        return self._build_rank_entries(
            totals=qty_totals,
            rank_type=MedicineRankEntry.RANK_TYPE_QUANTITY,
        )

    def _rank_by_revenue(
        self,
        valid_records: list[BillingRecord],
    ) -> list[MedicineRankEntry]:
        """
        LLD: rankByRevenue — top TOP_N drugs by gross line-item revenue.

        Revenue per line item = qty × unit_price_paise.  This is gross revenue
        before any record-level discount, which cannot be attributed per-drug
        without proration (and the float math that entails).
        Non-refund records only.
        Ties broken alphabetically by drug_name.

        Returns:
            list[MedicineRankEntry] with rank_type="revenue", length ≤ TOP_N,
            analytics_report FK not yet set.
        """
        rev_totals: dict[str, int] = defaultdict(int)

        for record in valid_records:
            if record.is_refund:
                continue
            for item in self._get_line_items(record):
                rev_totals[item["drug_name"]] += item["qty"] * item["unit_price_paise"]

        return self._build_rank_entries(
            totals=rev_totals,
            rank_type=MedicineRankEntry.RANK_TYPE_REVENUE,
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_rank_entries(
        totals: dict[str, int],
        rank_type: str,
    ) -> list[MedicineRankEntry]:
        """
        Convert a {drug_name: total_value} dict into a ranked list of
        MedicineRankEntry ORM instances.

        Sort order: descending value, then ascending drug_name for ties.
        Capped at TOP_N entries.  Ranks are 1-based.
        """
        sorted_drugs = sorted(
            totals.items(),
            key=lambda kv: (-kv[1], kv[0]),  # (−value DESC, name ASC for ties)
        )[:TOP_N]

        return [
            MedicineRankEntry(
                rank_type=rank_type,
                drug_name=drug_name,
                value=value,
                rank=rank,
            )
            for rank, (drug_name, value) in enumerate(sorted_drugs, start=1)
        ]
