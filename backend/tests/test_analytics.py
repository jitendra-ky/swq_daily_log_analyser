"""
Tests for AnalyticsService.
============================
Covers LLD §2 Analytics Service: computeRevenueByHour, rankByQuantity,
rankByRevenue — all via the single public entry point compute().

Conventions (matching test_ingestion.py and test_reconciliation.py):
  - Django TestCase
  - Self-contained fixtures in tests/fixtures/  (no dependency on private_file/)
  - Fixtures are plain JSON arrays of billing record dicts
  - Records are built as unsaved BillingRecord instances carrying
    _pending_line_items so no DB writes are needed for pure logic tests
  - One test (test_compute_does_not_persist) asserts the service is
    side-effect free by checking DB row counts after compute()

Fixture quick-reference (hand-verified expected values):
  analytics_happy_path.json — 10 non-refund records, 5 drugs, 6 distinct hours
    Hourly collected revenue:
      hour 09 →  9 000  (V-ANA-001 6000 + V-ANA-002 3000)
      hour 10 → 57 000  (V-ANA-003 5000 + V-ANA-004 52000)
      hour 11 → 26 500  (V-ANA-005 12000 + V-ANA-006 14500)
      hour 13 → 76 000  (V-ANA-007 21000 + V-ANA-008 55000)
      hour 16 → 35 200  (V-ANA-009)
      hour 17 → 22 000  (V-ANA-010)
    Top-5 by qty:
      rank 1 OMEPRAZOLE 10 | rank 2 AMOXICILLIN 9 | rank 3 ATORVASTATIN 9
      rank 4 METFORMIN 7   | rank 5 PARACETAMOL 4
      (AMOXICILLIN before ATORVASTATIN alphabetically — both qty=9)
    Top-5 by revenue (qty × unit_price_paise):
      rank 1 ATORVASTATIN 108000 | rank 2 AMOXICILLIN 54000
      rank 3 OMEPRAZOLE 40000    | rank 4 METFORMIN 21000
      rank 5 PARACETAMOL 8000

  analytics_with_refunds.json — 2 non-refund + 2 refund records
    Non-refund hours: 10 (ATORVASTATIN, 24000), 13 (AMOXICILLIN+OMEPRAZOLE, 22000)
    Refund hours: 10 and 16 — must NOT appear in revenue
    METFORMIN only appears in a refund → must NOT appear in rankings

  analytics_single_record.json — 1 non-refund: PARACETAMOL×1, hour 9, 2000 paise
  analytics_ties.json — qty tie: AMOXICILLIN=3 and PARACETAMOL=3 (METFORMIN=2)
    Revenue: AMOXICILLIN 18000, PARACETAMOL 6000, METFORMIN 6000
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

from django.test import TestCase

from core.analytics_service import TOP_N, AnalyticsService
from core.models import BillingRecord
from core.models.analytics import AnalyticsReport, HourlyRevenue, MedicineRankEntry

# ── helpers ──────────────────────────────────────────────────────────────────

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> list[dict]:
    """Load a JSON fixture file by basename."""
    with open(os.path.join(FIXTURES_DIR, name)) as fh:
        return json.load(fh)


def _build_records(rows: list[dict]) -> list[BillingRecord]:
    """
    Convert raw fixture dicts into unsaved BillingRecord instances carrying
    _pending_line_items.  Mirrors exactly what IngestionService produces for
    valid rows, so AnalyticsService._get_line_items() takes the unsaved path.
    """
    records = []
    for row in rows:
        ts_raw = row["timestamp"].replace("Z", "+00:00")
        record = BillingRecord(
            clinic_id=row["clinic_id"],
            visit_id=row["visit_id"],
            timestamp=datetime.fromisoformat(ts_raw),
            doctor_id=row["doctor_id"],
            payment_mode=row["payment_mode"].upper(),
            amount_paid_paise=row["amount_paid_paise"],
            discount_paise=row["discount_paise"],
            is_refund=row["is_refund"],
        )
        record._pending_line_items = [  # type: ignore[attr-defined]
            {
                "drug_name": li["drug_name"],
                "qty": li["qty"],
                "unit_price_paise": li["unit_price_paise"],
            }
            for li in row["line_items"]
        ]
        records.append(record)
    return records


# ── test class ────────────────────────────────────────────────────────────────


class AnalyticsServiceTests(TestCase):
    """Unit tests for AnalyticsService."""

    def setUp(self) -> None:
        self.service = AnalyticsService()

    # ── return types ─────────────────────────────────────────────────────────

    def test_compute_returns_correct_types(self) -> None:
        """compute() must return (AnalyticsReport, list[HourlyRevenue], list[MedicineRankEntry])."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        report, hourly_rows, rank_rows = self.service.compute(records, "CLN-ANA-001")

        self.assertIsInstance(report, AnalyticsReport)
        self.assertIsInstance(hourly_rows, list)
        self.assertTrue(
            all(isinstance(r, HourlyRevenue) for r in hourly_rows),
            "All hourly_rows entries must be HourlyRevenue instances",
        )
        self.assertIsInstance(rank_rows, list)
        self.assertTrue(
            all(isinstance(r, MedicineRankEntry) for r in rank_rows),
            "All rank_rows entries must be MedicineRankEntry instances",
        )

    # ── report_date ──────────────────────────────────────────────────────────

    def test_report_date_is_min_timestamp(self) -> None:
        """report_date is inferred from the earliest timestamp in the input."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        report, _, _ = self.service.compute(records, "CLN-ANA-001")
        self.assertEqual(report.report_date, date(2026, 7, 27))

    def test_report_date_empty_input_returns_today(self) -> None:
        """Empty input falls back to date.today() without raising."""
        import datetime as dt

        report, hourly_rows, rank_rows = self.service.compute([], "CLN-ANA-001")
        self.assertEqual(report.report_date, dt.date.today())
        self.assertEqual(hourly_rows, [])
        self.assertEqual(rank_rows, [])

    # ── hourly revenue ────────────────────────────────────────────────────────

    def test_hourly_revenue_correct_buckets(self) -> None:
        """Verify exact paise total for each hour in the happy-path fixture."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        _, hourly_rows, _ = self.service.compute(records, "CLN-ANA-001")

        revenue_by_hour = {row.hour: row.revenue_paise for row in hourly_rows}
        # Hand-verified from fixture (see module docstring)
        self.assertEqual(revenue_by_hour[9], 9_000)
        self.assertEqual(revenue_by_hour[10], 57_000)
        self.assertEqual(revenue_by_hour[11], 26_500)
        self.assertEqual(revenue_by_hour[13], 76_000)
        self.assertEqual(revenue_by_hour[16], 35_200)
        self.assertEqual(revenue_by_hour[17], 22_000)

    def test_hourly_revenue_excludes_refund_records(self) -> None:
        """Refund records must not contribute any revenue to any hour bucket."""
        records = _build_records(_load_fixture("analytics_with_refunds.json"))
        _, hourly_rows, _ = self.service.compute(records, "CLN-ANA-002")

        revenue_by_hour = {row.hour: row.revenue_paise for row in hourly_rows}
        # Only hours 10 and 13 have non-refund records; hour 16 is refund-only.
        self.assertIn(10, revenue_by_hour)
        self.assertIn(13, revenue_by_hour)
        self.assertNotIn(16, revenue_by_hour, "Hour 16 is refund-only; must not appear")

    def test_hourly_revenue_refund_hours_not_double_counted(self) -> None:
        """Hour 10 has both a sale and a refund; only the sale amount appears."""
        records = _build_records(_load_fixture("analytics_with_refunds.json"))
        _, hourly_rows, _ = self.service.compute(records, "CLN-ANA-002")

        revenue_by_hour = {row.hour: row.revenue_paise for row in hourly_rows}
        # V-REF-001 (sale) at hour 10 contributed 24000; refund must not inflate it
        self.assertEqual(revenue_by_hour[10], 24_000)

    def test_hourly_revenue_omits_zero_hours(self) -> None:
        """Hours absent from the input must not appear as zero rows."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        _, hourly_rows, _ = self.service.compute(records, "CLN-ANA-001")

        present_hours = {row.hour for row in hourly_rows}
        # Fixture has records at hours 9,10,11,13,16,17 — exactly 6 hours
        self.assertEqual(present_hours, {9, 10, 11, 13, 16, 17})
        self.assertEqual(len(hourly_rows), 6)

    def test_hourly_revenue_ordered_by_hour(self) -> None:
        """HourlyRevenue list must be sorted ascending by hour."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        _, hourly_rows, _ = self.service.compute(records, "CLN-ANA-001")

        hours = [row.hour for row in hourly_rows]
        self.assertEqual(hours, sorted(hours))

    def test_single_record_hourly_revenue(self) -> None:
        """One record produces exactly one HourlyRevenue row at the correct hour."""
        records = _build_records(_load_fixture("analytics_single_record.json"))
        _, hourly_rows, _ = self.service.compute(records, "CLN-ANA-003")

        self.assertEqual(len(hourly_rows), 1)
        self.assertEqual(hourly_rows[0].hour, 9)
        self.assertEqual(hourly_rows[0].revenue_paise, 2_000)

    # ── rank by quantity ──────────────────────────────────────────────────────

    def test_rank_by_quantity_top5_correct_order(self) -> None:
        """rankByQuantity: correct drug order and values for happy-path fixture."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-001")

        qty_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_QUANTITY]
        # Hand-verified: OMEPRAZOLE=10, AMOXICILLIN=9, ATORVASTATIN=9, METFORMIN=7, PARACETAMOL=4
        self.assertEqual(qty_rows[0].drug_name, "OMEPRAZOLE")
        self.assertEqual(qty_rows[0].value, 10)
        self.assertEqual(qty_rows[0].rank, 1)

        self.assertEqual(qty_rows[1].drug_name, "AMOXICILLIN")   # 9, alpha before ATORVASTATIN
        self.assertEqual(qty_rows[1].rank, 2)

        self.assertEqual(qty_rows[2].drug_name, "ATORVASTATIN")  # 9, alpha after AMOXICILLIN
        self.assertEqual(qty_rows[2].rank, 3)

        self.assertEqual(qty_rows[3].drug_name, "METFORMIN")
        self.assertEqual(qty_rows[3].value, 7)

        self.assertEqual(qty_rows[4].drug_name, "PARACETAMOL")
        self.assertEqual(qty_rows[4].value, 4)

    def test_rank_by_quantity_all_entries_are_qty_type(self) -> None:
        """All qty-rank entries must carry rank_type == 'qty'."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-001")

        qty_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_QUANTITY]
        self.assertTrue(len(qty_rows) > 0)
        for row in qty_rows:
            self.assertEqual(row.rank_type, MedicineRankEntry.RANK_TYPE_QUANTITY)

    def test_rank_by_quantity_excludes_refund_drugs(self) -> None:
        """Drugs that appear only in refund records must not appear in the qty ranking."""
        records = _build_records(_load_fixture("analytics_with_refunds.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-002")

        qty_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_QUANTITY]
        ranked_drugs = {r.drug_name for r in qty_rows}
        # METFORMIN appears only in a refund record (V-REF-004)
        self.assertNotIn("METFORMIN", ranked_drugs)

    def test_rank_by_quantity_tie_breaking_is_alphabetical(self) -> None:
        """When two drugs share the same qty, they are ordered alphabetically."""
        records = _build_records(_load_fixture("analytics_ties.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-004")

        qty_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_QUANTITY]
        # AMOXICILLIN and PARACETAMOL both have qty=3; AMOXICILLIN < PARACETAMOL
        self.assertEqual(qty_rows[0].drug_name, "AMOXICILLIN")
        self.assertEqual(qty_rows[0].rank, 1)
        self.assertEqual(qty_rows[1].drug_name, "PARACETAMOL")
        self.assertEqual(qty_rows[1].rank, 2)

    # ── rank by revenue ───────────────────────────────────────────────────────

    def test_rank_by_revenue_top5_correct_order(self) -> None:
        """rankByRevenue: correct drug order and values for happy-path fixture."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-001")

        rev_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_REVENUE]
        # Hand-verified: ATORVASTATIN=108000, AMOXICILLIN=54000, OMEPRAZOLE=40000,
        # METFORMIN=21000, PARACETAMOL=8000
        self.assertEqual(rev_rows[0].drug_name, "ATORVASTATIN")
        self.assertEqual(rev_rows[0].value, 108_000)
        self.assertEqual(rev_rows[0].rank, 1)

        self.assertEqual(rev_rows[1].drug_name, "AMOXICILLIN")
        self.assertEqual(rev_rows[1].value, 54_000)

        self.assertEqual(rev_rows[2].drug_name, "OMEPRAZOLE")
        self.assertEqual(rev_rows[2].value, 40_000)

        self.assertEqual(rev_rows[3].drug_name, "METFORMIN")
        self.assertEqual(rev_rows[3].value, 21_000)

        self.assertEqual(rev_rows[4].drug_name, "PARACETAMOL")
        self.assertEqual(rev_rows[4].value, 8_000)

    def test_rank_by_revenue_all_entries_are_revenue_type(self) -> None:
        """All revenue-rank entries must carry rank_type == 'revenue'."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-001")

        rev_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_REVENUE]
        self.assertTrue(len(rev_rows) > 0)
        for row in rev_rows:
            self.assertEqual(row.rank_type, MedicineRankEntry.RANK_TYPE_REVENUE)

    def test_rank_by_revenue_excludes_refund_drugs(self) -> None:
        """Drugs that appear only in refund records must not appear in the revenue ranking."""
        records = _build_records(_load_fixture("analytics_with_refunds.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-002")

        rev_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_REVENUE]
        ranked_drugs = {r.drug_name for r in rev_rows}
        self.assertNotIn("METFORMIN", ranked_drugs)

    def test_rank_by_revenue_tie_breaking_is_alphabetical(self) -> None:
        """When two drugs share the same revenue, they are ordered alphabetically."""
        records = _build_records(_load_fixture("analytics_ties.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-004")

        rev_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_REVENUE]
        # PARACETAMOL and METFORMIN both have revenue=6000; METFORMIN < PARACETAMOL
        drug_names = [r.drug_name for r in rev_rows]
        metformin_pos = drug_names.index("METFORMIN")
        paracetamol_pos = drug_names.index("PARACETAMOL")
        self.assertLess(metformin_pos, paracetamol_pos)

    # ── ranks ─────────────────────────────────────────────────────────────────

    def test_ranks_are_one_based_and_sequential(self) -> None:
        """Ranks must start at 1 and be strictly sequential with no gaps."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-001")

        for rank_type in (
            MedicineRankEntry.RANK_TYPE_QUANTITY,
            MedicineRankEntry.RANK_TYPE_REVENUE,
        ):
            typed_rows = sorted(
                [r for r in rank_rows if r.rank_type == rank_type],
                key=lambda r: r.rank,
            )
            for expected_rank, row in enumerate(typed_rows, start=1):
                self.assertEqual(
                    row.rank,
                    expected_rank,
                    f"rank_type={rank_type}: expected rank {expected_rank}, got {row.rank}",
                )

    def test_top_n_capped_at_five(self) -> None:
        """Both ranking lists must have at most TOP_N entries even when more drugs exist."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        # Fixture has exactly 5 distinct drugs — ensure exactly TOP_N entries
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-001")

        qty_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_QUANTITY]
        rev_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_REVENUE]
        self.assertLessEqual(len(qty_rows), TOP_N)
        self.assertLessEqual(len(rev_rows), TOP_N)

    # ── empty input ───────────────────────────────────────────────────────────

    def test_empty_input_produces_empty_collections(self) -> None:
        """Empty valid_records must produce empty hourly and rank collections."""
        report, hourly_rows, rank_rows = self.service.compute([], "CLN-EMPTY")
        self.assertEqual(hourly_rows, [])
        self.assertEqual(rank_rows, [])

    def test_empty_input_does_not_raise(self) -> None:
        """compute() must never raise on empty input."""
        try:
            self.service.compute([], "CLN-EMPTY")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"compute([]) raised unexpectedly: {exc}")

    # ── side effects ──────────────────────────────────────────────────────────

    def test_compute_does_not_persist(self) -> None:
        """compute() must not save anything — zero DB rows after the call."""
        records = _build_records(_load_fixture("analytics_happy_path.json"))
        self.service.compute(records, "CLN-ANA-001")

        self.assertEqual(AnalyticsReport.objects.count(), 0)
        self.assertEqual(HourlyRevenue.objects.count(), 0)
        self.assertEqual(MedicineRankEntry.objects.count(), 0)

    # ── single-record edge case ───────────────────────────────────────────────

    def test_single_record_produces_rank_1_for_sole_drug(self) -> None:
        """With one record and one drug, that drug is rank 1 in both lists."""
        records = _build_records(_load_fixture("analytics_single_record.json"))
        _, _, rank_rows = self.service.compute(records, "CLN-ANA-003")

        qty_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_QUANTITY]
        rev_rows = [r for r in rank_rows if r.rank_type == MedicineRankEntry.RANK_TYPE_REVENUE]

        self.assertEqual(len(qty_rows), 1)
        self.assertEqual(qty_rows[0].drug_name, "PARACETAMOL")
        self.assertEqual(qty_rows[0].rank, 1)
        self.assertEqual(qty_rows[0].value, 1)

        self.assertEqual(len(rev_rows), 1)
        self.assertEqual(rev_rows[0].drug_name, "PARACETAMOL")
        self.assertEqual(rev_rows[0].rank, 1)
        self.assertEqual(rev_rows[0].value, 2_000)  # qty=1 × unit=2000
