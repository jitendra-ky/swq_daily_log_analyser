"""
Tests for ReconciliationService.
===================================
All fixtures live in tests/fixtures/ (recon_*.json).
No dependency on private_file/.

Run with:
    cd backend
    python -m pytest tests/test_reconciliation.py -v

Design notes
------------
- Records must be saved before calling ReconciliationService.compute()
  because BillingRecord.gross_billed_paise() queries line_items via the DB
  reverse FK.  Each TestCase is wrapped in a transaction that rolls back
  after the test, so saves are isolated automatically.
- _build_and_save_records() is the shared helper that converts the fixture
  JSON (same shape as the raw billing log) into saved ORM instances.
- Expected totals for each fixture are documented both in the fixture files
  (as _comment fields) and as inline constants here.
"""

import datetime
import json
import os
from pathlib import Path

import django
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models.billing import BillingRecord, LineItem  # noqa: E402
from core.reconciliation_service import ReconciliationService  # noqa: E402

# ── fixture helpers ──────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CLINIC_ID = "CLN-RECON-001"


def _load(filename: str) -> list[dict]:
    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


def _parse_ts(raw: str) -> datetime.datetime:
    """Parse an ISO-8601 UTC timestamp string into an aware datetime."""
    return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _build_and_save_records(rows: list[dict]) -> list[BillingRecord]:
    """
    Convert raw fixture rows into saved BillingRecord + LineItem ORM instances.

    Matches the shape written by IngestionService (after the orchestrator has
    persisted the unsaved records it produced).  payment_mode is uppercased to
    match what IngestionService stores.  Timestamps are parsed to aware
    datetime objects so that r.timestamp.date() works in the service.
    """
    records: list[BillingRecord] = []
    for row in rows:
        record = BillingRecord.objects.create(
            clinic_id=row["clinic_id"],
            visit_id=row["visit_id"],
            timestamp=_parse_ts(row["timestamp"]),
            doctor_id=row["doctor_id"],
            payment_mode=row["payment_mode"].upper(),
            amount_paid_paise=row["amount_paid_paise"],
            discount_paise=row["discount_paise"],
            is_refund=row["is_refund"],
        )
        LineItem.objects.bulk_create([
            LineItem(
                billing_record=record,
                drug_name=item["drug_name"],
                qty=item["qty"],
                unit_price_paise=item["unit_price_paise"],
            )
            for item in row["line_items"]
        ])
        records.append(record)
    return records


# ── test cases ───────────────────────────────────────────────────────────────


class TestReconciliationHappyPath(TestCase):
    """
    Fixture: recon_happy_path.json
    3 non-refund records (CASH, CARD, UPI), one CARD record with a 1000-paise discount.

    Pre-computed expected values:
      V-HP-001  CASH  gross=2×2000=4000   collected=4000   outstanding=0
      V-HP-002  CARD  gross=3×6000+1×4000=22000  collected=21000  outstanding=1000
      V-HP-003  UPI   gross=1×3000=3000   collected=3000   outstanding=0
      ─────────────────────────────────────────────────────────────────
      total_billed      = 4000+22000+3000 = 29000
      total_collected   = 4000+21000+3000 = 28000
      total_outstanding = 29000-28000     = 1000
      total_refunds     = 0
      visit_count       = 3
      refund_count      = 0
    """

    EXPECTED_BILLED = 29000
    EXPECTED_COLLECTED = 28000
    EXPECTED_OUTSTANDING = 1000
    EXPECTED_REFUNDS = 0
    EXPECTED_VISITS = 3
    EXPECTED_REFUND_COUNT = 0

    def setUp(self):
        self.service = ReconciliationService()
        self.records = _build_and_save_records(_load("recon_happy_path.json"))
        self.report, self.breakdowns = self.service.compute(self.records, CLINIC_ID)

    # ── scalar totals ────────────────────────────────────────────────────────

    def test_total_billed(self):
        """total_billed_paise sums gross_billed_paise() of non-refund records."""
        self.assertEqual(self.report.total_billed_paise, self.EXPECTED_BILLED)

    def test_total_collected(self):
        """total_collected_paise sums amount_paid_paise of non-refund records."""
        self.assertEqual(self.report.total_collected_paise, self.EXPECTED_COLLECTED)

    def test_total_outstanding(self):
        """total_outstanding_paise = billed − collected."""
        self.assertEqual(self.report.total_outstanding_paise, self.EXPECTED_OUTSTANDING)

    def test_total_refunds_zero(self):
        """No refund records → total_refunds_paise = 0."""
        self.assertEqual(self.report.total_refunds_paise, self.EXPECTED_REFUNDS)

    def test_visit_count(self):
        """visit_count counts non-refund records only."""
        self.assertEqual(self.report.visit_count, self.EXPECTED_VISITS)

    def test_refund_count_zero(self):
        """No refund records → refund_count = 0."""
        self.assertEqual(self.report.refund_count, self.EXPECTED_REFUND_COUNT)

    def test_clinic_id_stamped(self):
        """clinic_id on the report matches the argument."""
        self.assertEqual(self.report.clinic_id, CLINIC_ID)

    def test_report_date_inferred(self):
        """report_date is inferred from the earliest record timestamp (2026-07-27)."""
        import datetime
        self.assertEqual(self.report.report_date, datetime.date(2026, 7, 27))

    # ── payment-mode breakdowns ──────────────────────────────────────────────

    def test_three_breakdowns_produced(self):
        """One breakdown per mode — CASH, CARD, UPI all present."""
        modes = {b.mode for b in self.breakdowns}
        self.assertEqual(modes, {"CASH", "CARD", "UPI"})

    def test_cash_breakdown(self):
        """CASH breakdown: billed=4000, collected=4000, outstanding=0, refunds=0."""
        cash = next(b for b in self.breakdowns if b.mode == "CASH")
        self.assertEqual(cash.billed_paise, 4000)
        self.assertEqual(cash.collected_paise, 4000)
        self.assertEqual(cash.outstanding_paise, 0)
        self.assertEqual(cash.refunds_paise, 0)

    def test_card_breakdown_with_outstanding(self):
        """CARD breakdown reflects the 1000-paise discount as outstanding."""
        card = next(b for b in self.breakdowns if b.mode == "CARD")
        self.assertEqual(card.billed_paise, 22000)
        self.assertEqual(card.collected_paise, 21000)
        self.assertEqual(card.outstanding_paise, 1000)
        self.assertEqual(card.refunds_paise, 0)

    def test_upi_breakdown(self):
        """UPI breakdown: billed=3000, collected=3000, outstanding=0, refunds=0."""
        upi = next(b for b in self.breakdowns if b.mode == "UPI")
        self.assertEqual(upi.billed_paise, 3000)
        self.assertEqual(upi.collected_paise, 3000)
        self.assertEqual(upi.outstanding_paise, 0)
        self.assertEqual(upi.refunds_paise, 0)

    # ── persistence contract ─────────────────────────────────────────────────

    def test_report_is_unsaved(self):
        """compute() returns an unsaved report (pk is None)."""
        self.assertIsNone(self.report.pk)

    def test_breakdowns_are_unsaved(self):
        """compute() returns unsaved breakdown instances (pk is None for all)."""
        for b in self.breakdowns:
            self.assertIsNone(b.pk)


class TestReconciliationEdgeCases(TestCase):
    """Edge cases: all-refunds, mixed, empty input, single payment mode."""

    def setUp(self):
        self.service = ReconciliationService()

    # ── all-refund records ───────────────────────────────────────────────────

    def test_all_refunds_billed_zero(self):
        """All-refund input → total_billed_paise = 0."""
        records = _build_and_save_records(_load("recon_all_refunds.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.total_billed_paise, 0)

    def test_all_refunds_collected_zero(self):
        """All-refund input → total_collected_paise = 0."""
        records = _build_and_save_records(_load("recon_all_refunds.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.total_collected_paise, 0)

    def test_all_refunds_outstanding_zero(self):
        """All-refund input → total_outstanding_paise = 0."""
        records = _build_and_save_records(_load("recon_all_refunds.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.total_outstanding_paise, 0)

    def test_all_refunds_total_refunds_paise(self):
        """
        All-refund input: total_refunds_paise = abs(-24000)+abs(-22000)+abs(-3000)
        = 49000 (stored positive in the report).
        """
        records = _build_and_save_records(_load("recon_all_refunds.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.total_refunds_paise, 49000)

    def test_all_refunds_visit_count_zero(self):
        """All-refund input → visit_count = 0."""
        records = _build_and_save_records(_load("recon_all_refunds.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.visit_count, 0)

    def test_all_refunds_refund_count(self):
        """All-refund input → refund_count = 3."""
        records = _build_and_save_records(_load("recon_all_refunds.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.refund_count, 3)

    def test_all_refunds_breakdown_refunds_paise(self):
        """
        All-refund breakdown: CARD refunds=24000, UPI refunds=22000+3000=25000.
        billed/collected/outstanding are all 0.
        """
        records = _build_and_save_records(_load("recon_all_refunds.json"))
        _, breakdowns = self.service.compute(records, CLINIC_ID)
        modes = {b.mode: b for b in breakdowns}

        self.assertIn("CARD", modes)
        self.assertEqual(modes["CARD"].refunds_paise, 24000)
        self.assertEqual(modes["CARD"].billed_paise, 0)

        self.assertIn("UPI", modes)
        self.assertEqual(modes["UPI"].refunds_paise, 25000)
        self.assertEqual(modes["UPI"].billed_paise, 0)

    # ── mixed normal + refund ────────────────────────────────────────────────

    def test_mixed_refund_does_not_inflate_billed(self):
        """
        recon_mixed.json:  CASH normal (gross=6000) + UPI normal (gross=4000) +
                           UPI normal (gross=12000) + CASH refund (-6000).
        total_billed = 6000+4000+12000 = 22000  (refund must NOT add to billed).
        """
        records = _build_and_save_records(_load("recon_mixed.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.total_billed_paise, 22000)

    def test_mixed_outstanding_with_discount(self):
        """
        V-MIX-002 (UPI) has discount_paise=500 → collected=3500, billed=4000.
        total_outstanding = 22000 − 21500 = 500.
        """
        records = _build_and_save_records(_load("recon_mixed.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.total_collected_paise, 21500)
        self.assertEqual(report.total_outstanding_paise, 500)

    def test_mixed_refunds_paise(self):
        """CASH refund of 6000 → total_refunds_paise = 6000."""
        records = _build_and_save_records(_load("recon_mixed.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.total_refunds_paise, 6000)

    def test_mixed_visit_and_refund_counts(self):
        """3 normal + 1 refund → visit_count=3, refund_count=1."""
        records = _build_and_save_records(_load("recon_mixed.json"))
        report, _ = self.service.compute(records, CLINIC_ID)
        self.assertEqual(report.visit_count, 3)
        self.assertEqual(report.refund_count, 1)

    def test_mixed_cash_breakdown_includes_refund(self):
        """CASH breakdown: billed=6000 (normal only), refunds=6000 (from refund record)."""
        records = _build_and_save_records(_load("recon_mixed.json"))
        _, breakdowns = self.service.compute(records, CLINIC_ID)
        cash = next(b for b in breakdowns if b.mode == "CASH")
        self.assertEqual(cash.billed_paise, 6000)
        self.assertEqual(cash.refunds_paise, 6000)

    # ── empty input ──────────────────────────────────────────────────────────

    def test_empty_input_all_zeros(self):
        """Empty valid_records list → all scalar fields = 0."""
        report, breakdowns = self.service.compute([], CLINIC_ID)
        self.assertEqual(report.total_billed_paise, 0)
        self.assertEqual(report.total_collected_paise, 0)
        self.assertEqual(report.total_outstanding_paise, 0)
        self.assertEqual(report.total_refunds_paise, 0)
        self.assertEqual(report.visit_count, 0)
        self.assertEqual(report.refund_count, 0)

    def test_empty_input_no_breakdowns(self):
        """Empty valid_records list → empty breakdowns list."""
        _, breakdowns = self.service.compute([], CLINIC_ID)
        self.assertEqual(breakdowns, [])

    def test_empty_input_report_date_is_today(self):
        """Empty input → report_date falls back to datetime.date.today()."""
        import datetime
        report, _ = self.service.compute([], CLINIC_ID)
        self.assertEqual(report.report_date, datetime.date.today())

    # ── single payment mode ──────────────────────────────────────────────────

    def test_single_mode_exactly_one_breakdown(self):
        """All UPI records → exactly one PaymentModeBreakdown, mode=UPI."""
        records = _build_and_save_records(_load("recon_single_mode.json"))
        _, breakdowns = self.service.compute(records, CLINIC_ID)
        self.assertEqual(len(breakdowns), 1)
        self.assertEqual(breakdowns[0].mode, "UPI")

    def test_single_mode_upi_totals(self):
        """
        recon_single_mode.json: 2 UPI records.
        V-UPI-001: gross=3×2000=6000, collected=6000.
        V-UPI-002: gross=1×3000=3000, collected=3000.
        UPI breakdown: billed=9000, collected=9000, outstanding=0, refunds=0.
        """
        records = _build_and_save_records(_load("recon_single_mode.json"))
        _, breakdowns = self.service.compute(records, CLINIC_ID)
        upi = breakdowns[0]
        self.assertEqual(upi.billed_paise, 9000)
        self.assertEqual(upi.collected_paise, 9000)
        self.assertEqual(upi.outstanding_paise, 0)
        self.assertEqual(upi.refunds_paise, 0)
