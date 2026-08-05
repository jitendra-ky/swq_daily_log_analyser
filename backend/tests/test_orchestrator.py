"""
Tests for ReportOrchestrator.
=============================
Covers end-to-end report generation pipeline from LLD §2 & §3.
"""

import json
from pathlib import Path
from unittest.mock import Mock

from django.test import TestCase

from core.report_orchestrator import ReportOrchestrator
from core.models import BillingRecord, LineItem, ValidationError
from core.models.reconciliation import ReconciliationReport, PaymentModeBreakdown
from core.models.analytics import AnalyticsReport, HourlyRevenue, MedicineRankEntry
from core.models.narrative import NarrativeResult, TracedFigure, NarrativeStatus


class TestReportOrchestrator(TestCase):
    def setUp(self):
        fixture_path = Path(__file__).parent / "fixtures" / "sample_valid.json"
        with open(fixture_path) as f:
            self.sample_valid_rows = json.load(f)

        self.mock_llm = Mock()
        self.mock_llm.request_template.return_value = json.dumps({
            "summaryTemplate": "Total billed was {{total_billed}} and collected was {{total_collected}}."
        })
        self.orchestrator = ReportOrchestrator(llm_provider=self.mock_llm)

    def test_orchestrator_end_to_end(self):
        clinic_id = "CLN-TEST-001"
        batch = "batch-2026-07-27"
        
        response = self.orchestrator.generate_daily_report(
            clinic_id=clinic_id,
            raw_rows=self.sample_valid_rows,
            batch=batch
        )
        
        # Assert return values
        self.assertEqual(response["total_rows_processed"], 3)
        self.assertEqual(response["valid_records_count"], 3)
        self.assertEqual(len(response["errors"]), 0)
        
        self.assertIsNotNone(response["recon_report"])
        self.assertIsNotNone(response["analytics_report"])
        self.assertIsNotNone(response["narrative_result"])
        
        # Assert Ingestion layer persistence
        self.assertEqual(BillingRecord.objects.count(), 3)
        self.assertEqual(LineItem.objects.count(), 4)
        self.assertEqual(ValidationError.objects.count(), 0)
        
        # Assert Reconciliation persistence
        recon_report = ReconciliationReport.objects.first()
        self.assertIsNotNone(recon_report)
        self.assertEqual(recon_report.clinic_id, clinic_id)
        self.assertEqual(PaymentModeBreakdown.objects.filter(report=recon_report).count(), 3)
        
        # Assert Analytics persistence
        analytics_report = AnalyticsReport.objects.first()
        self.assertIsNotNone(analytics_report)
        self.assertEqual(analytics_report.clinic_id, clinic_id)
        self.assertEqual(HourlyRevenue.objects.filter(analytics_report=analytics_report).count(), 3)
        # ranks: paracetamol, amoxicillin, omeprazole, metformin = 4 drugs
        self.assertGreater(MedicineRankEntry.objects.filter(analytics_report=analytics_report).count(), 0)
        
        # Assert Narrative persistence
        narrative_result = NarrativeResult.objects.first()
        self.assertIsNotNone(narrative_result)
        self.assertEqual(narrative_result.status, NarrativeStatus.SUCCESS)
        self.assertEqual(TracedFigure.objects.filter(narrative_result=narrative_result).count(), 2)

    def test_orchestrator_idempotency(self):
        clinic_id = "CLN-TEST-001"
        batch = "batch-1"
        
        # Run once
        self.orchestrator.generate_daily_report(clinic_id, self.sample_valid_rows, batch)
        
        # Assert initial counts
        recon_count = ReconciliationReport.objects.count()
        analytics_count = AnalyticsReport.objects.count()
        narrative_count = NarrativeResult.objects.count()
        self.assertEqual(recon_count, 1)
        self.assertEqual(analytics_count, 1)
        self.assertEqual(narrative_count, 1)
        
        # We need unique visit IDs for Ingestion or else it fails on DB level (unique constraint)
        # Let's modify visit IDs
        for i, row in enumerate(self.sample_valid_rows):
            row["visit_id"] = f"V-VALID-NEW-{i}"
        
        # Run again (second run)
        self.orchestrator.generate_daily_report(clinic_id, self.sample_valid_rows, "batch-2")
        
        # Assert counts haven't duplicated because the previous reports for same clinic and date were deleted
        self.assertEqual(ReconciliationReport.objects.count(), recon_count)
        self.assertEqual(AnalyticsReport.objects.count(), analytics_count)
        self.assertEqual(NarrativeResult.objects.count(), narrative_count)
