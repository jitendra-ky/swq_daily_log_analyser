"""
Tests for IngestionService.
============================
All fixtures live in tests/fixtures/

Run with:
    cd backend
    python -m pytest tests/test_ingestion.py -v
"""

import json
import os
from pathlib import Path

import django
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.ingestion_service import IngestionService  # noqa: E402

# ── fixture helpers ──────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(filename: str) -> list[dict]:
    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


# ── test cases ───────────────────────────────────────────────────────────────


class TestIngestionServiceHappyPath(TestCase):
    """Valid inputs — no errors expected."""

    def setUp(self):
        self.service = IngestionService()

    def test_happy_path_all_valid(self):
        """3 valid rows → 3 valid_records, 0 errors."""
        rows = _load("sample_valid.json")
        result = self.service.parse_log(rows, batch="test-valid")

        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.valid_count, 3)
        self.assertEqual(result.error_count, 0)
        self.assertFalse(result.has_errors())

    def test_all_refunds_valid(self):
        """3 refund rows with negative amount_paid_paise all pass."""
        rows = _load("sample_refunds.json")
        result = self.service.parse_log(rows, batch="test-refunds")

        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.valid_count, 3)
        self.assertEqual(result.error_count, 0)

    def test_empty_log(self):
        """Empty array → ParseResult with all zeros, no errors."""
        rows = _load("sample_empty.json")
        result = self.service.parse_log(rows, batch="test-empty")

        self.assertEqual(result.total_rows, 0)
        self.assertEqual(result.valid_count, 0)
        self.assertEqual(result.error_count, 0)
        self.assertFalse(result.has_errors())

    def test_total_rows_count(self):
        """total_rows always reflects the full input size."""
        rows = _load("sample_mixed_errors.json")
        result = self.service.parse_log(rows, batch="test-total")

        # 9 rows in sample_mixed_errors.json (2 valid + 7 bad)
        self.assertEqual(result.total_rows, 9)

    def test_pending_line_items_attached(self):
        """Valid records carry _pending_line_items for the orchestrator."""
        rows = _load("sample_valid.json")
        result = self.service.parse_log(rows, batch="test-items")

        for record in result.valid_records:
            self.assertTrue(hasattr(record, "_pending_line_items"))
            self.assertGreater(len(record._pending_line_items), 0)

    def test_payment_mode_uppercased(self):
        """payment_mode from log (lowercase) is stored uppercased on the record."""
        rows = _load("sample_valid.json")
        result = self.service.parse_log(rows, batch="test-pm")

        modes = {r.payment_mode for r in result.valid_records}
        self.assertTrue(modes.issubset({"CASH", "CARD", "UPI"}))


class TestIngestionServiceValidationErrors(TestCase):
    """Each bad-row scenario produces the correct ValidationError."""

    def setUp(self):
        self.service = IngestionService()

    # ── individual error type tests ──────────────────────────────────────────

    def test_missing_required_field(self):
        """Row missing payment_mode → error with field='payment_mode'."""
        row = {
            "clinic_id": "CLN-X",
            "visit_id": "V-MISS-PM",
            "timestamp": "2026-07-27T09:00:00Z",
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 1, "unit_price_paise": 1000}],
            # payment_mode intentionally absent
            "amount_paid_paise": 1000,
            "discount_paise": 0,
            "is_refund": False,
        }
        result = self.service.parse_log([row], batch="test-missing")

        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.valid_count, 0)
        err = result.errors[0]
        self.assertEqual(err.field, "payment_mode")
        self.assertEqual(err.reason, "missing or wrong type")

    def test_refund_positive_amount(self):
        """is_refund=True with positive amount_paid_paise → error."""
        row = {
            "clinic_id": "CLN-X",
            "visit_id": "V-REF-POS",
            "timestamp": "2026-07-27T09:00:00Z",
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 1, "unit_price_paise": 1000}],
            "payment_mode": "cash",
            "amount_paid_paise": 1000,  # positive — wrong for refund
            "discount_paise": 0,
            "is_refund": True,
        }
        result = self.service.parse_log([row], batch="test-refund-pos")

        self.assertEqual(result.error_count, 1)
        err = result.errors[0]
        self.assertEqual(err.field, "amount_paid_paise")
        self.assertIn("negative", err.reason)

    def test_non_integer_paise(self):
        """Float amount_paid_paise → non-integer paise error."""
        row = {
            "clinic_id": "CLN-X",
            "visit_id": "V-FLOAT",
            "timestamp": "2026-07-27T09:00:00Z",
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 1, "unit_price_paise": 1000}],
            "payment_mode": "upi",
            "amount_paid_paise": 1000.50,  # float — rejected
            "discount_paise": 0,
            "is_refund": False,
        }
        result = self.service.parse_log([row], batch="test-float")

        self.assertEqual(result.error_count, 1)
        err = result.errors[0]
        self.assertEqual(err.field, "amount_paid_paise")
        self.assertIn("non-integer", err.reason)

    def test_invalid_timestamp(self):
        """Malformed timestamp → invalid timestamp format error."""
        row = {
            "clinic_id": "CLN-X",
            "visit_id": "V-BAD-TS",
            "timestamp": "27-07-2026 09:00",  # not ISO 8601
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 1, "unit_price_paise": 1000}],
            "payment_mode": "cash",
            "amount_paid_paise": 1000,
            "discount_paise": 0,
            "is_refund": False,
        }
        result = self.service.parse_log([row], batch="test-ts")

        self.assertEqual(result.error_count, 1)
        err = result.errors[0]
        self.assertEqual(err.field, "timestamp")
        self.assertIn("invalid timestamp", err.reason)

    def test_empty_line_items(self):
        """Empty line_items list → error."""
        row = {
            "clinic_id": "CLN-X",
            "visit_id": "V-EMPTY-ITEMS",
            "timestamp": "2026-07-27T09:00:00Z",
            "doctor_id": "DOC-X",
            "line_items": [],
            "payment_mode": "cash",
            "amount_paid_paise": 0,
            "discount_paise": 0,
            "is_refund": False,
        }
        result = self.service.parse_log([row], batch="test-empty-items")

        self.assertEqual(result.error_count, 1)
        err = result.errors[0]
        self.assertEqual(err.field, "line_items")
        self.assertIn("invalid or empty line_items", err.reason)

    def test_zero_qty_in_line_item(self):
        """qty=0 in a line item → error."""
        row = {
            "clinic_id": "CLN-X",
            "visit_id": "V-ZERO-QTY",
            "timestamp": "2026-07-27T09:00:00Z",
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 0, "unit_price_paise": 1000}],
            "payment_mode": "upi",
            "amount_paid_paise": 0,
            "discount_paise": 0,
            "is_refund": False,
        }
        result = self.service.parse_log([row], batch="test-zero-qty")

        self.assertEqual(result.error_count, 1)
        err = result.errors[0]
        self.assertIn("line_items", err.field)

    def test_invalid_payment_mode_value(self):
        """Unrecognised payment_mode (e.g. 'cheque') → error."""
        row = {
            "clinic_id": "CLN-X",
            "visit_id": "V-BAD-PM",
            "timestamp": "2026-07-27T09:00:00Z",
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 1, "unit_price_paise": 1000}],
            "payment_mode": "cheque",
            "amount_paid_paise": 1000,
            "discount_paise": 0,
            "is_refund": False,
        }
        result = self.service.parse_log([row], batch="test-bad-pm")

        self.assertEqual(result.error_count, 1)
        err = result.errors[0]
        self.assertEqual(err.field, "payment_mode")
        self.assertIn("invalid payment_mode", err.reason)

    # ── batch-level behaviour ────────────────────────────────────────────────

    def test_bad_row_does_not_abort_batch(self):
        """1 bad row embedded between 2 good rows → valid=2, errors=1."""
        good = {
            "clinic_id": "CLN-X",
            "visit_id": "V-GOOD",
            "timestamp": "2026-07-27T09:00:00Z",
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 1, "unit_price_paise": 1000}],
            "payment_mode": "cash",
            "amount_paid_paise": 1000,
            "discount_paise": 0,
            "is_refund": False,
        }
        bad = {
            "clinic_id": "CLN-X",
            "visit_id": "V-BAD",
            "timestamp": "not-a-date",
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 1, "unit_price_paise": 1000}],
            "payment_mode": "cash",
            "amount_paid_paise": 1000,
            "discount_paise": 0,
            "is_refund": False,
        }
        good2 = {**good, "visit_id": "V-GOOD-2"}

        result = self.service.parse_log([good, bad, good2], batch="test-no-abort")

        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.valid_count, 2)
        self.assertEqual(result.error_count, 1)
        self.assertTrue(result.has_errors())

    def test_row_ref_falls_back_to_index(self):
        """Row without visit_id gets row_ref='row_0'."""
        row = {
            "clinic_id": "CLN-X",
            # no visit_id
            "timestamp": "2026-07-27T09:00:00Z",
            "doctor_id": "DOC-X",
            "line_items": [],  # will fail
            "payment_mode": "cash",
            "amount_paid_paise": 0,
            "discount_paise": 0,
            "is_refund": False,
        }
        result = self.service.parse_log([row], batch="test-rowref")

        self.assertEqual(result.error_count, 1)
        # row_ref is "row_0" (fell back from missing visit_id)
        # note: missing visit_id is also caught as a field error first
        err = result.errors[0]
        self.assertEqual(err.row_ref, "row_0")

    def test_error_batch_tag(self):
        """ValidationError.upload_batch matches the batch arg."""
        row = {
            "clinic_id": "CLN-X",
            "visit_id": "V-TAG",
            "timestamp": "bad-ts",
            "doctor_id": "DOC-X",
            "line_items": [{"drug_name": "DRUG", "qty": 1, "unit_price_paise": 1000}],
            "payment_mode": "cash",
            "amount_paid_paise": 1000,
            "discount_paise": 0,
            "is_refund": False,
        }
        result = self.service.parse_log([row], batch="billing_log_2026-07-27")

        self.assertEqual(result.errors[0].upload_batch, "billing_log_2026-07-27")

    # ── fixture-driven tests ─────────────────────────────────────────────────

    def test_mixed_errors_fixture(self):
        """sample_mixed_errors.json: 2 valid + 7 bad rows."""
        rows = _load("sample_mixed_errors.json")
        result = self.service.parse_log(rows, batch="test-mixed")

        self.assertEqual(result.total_rows, 9)
        self.assertEqual(result.valid_count, 2)
        self.assertEqual(result.error_count, 7)
