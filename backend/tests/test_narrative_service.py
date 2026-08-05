"""
Tests for NarrativeService.
===========================
Covers LLD §5 Grounding by Construction.
"""

import json
from unittest.mock import MagicMock
from datetime import date
from django.test import TestCase

from core.narrative_service import NarrativeService
from core.llm_provider import LLMProvider, LLMProviderError
from core.models.reconciliation import ReconciliationReport
from core.models.analytics import AnalyticsReport, HourlyRevenue, MedicineRankEntry
from core.models.narrative import NarrativeStatus


class NarrativeServiceTests(TestCase):
    def setUp(self):
        self.recon = ReconciliationReport.objects.create(
            clinic_id="CLN-001",
            report_date=date(2026, 7, 27),
            total_billed_paise=4285000,
            total_collected_paise=4000000,
            total_outstanding_paise=285000,
            total_refunds_paise=0,
            visit_count=10,
            refund_count=0
        )
        self.analytics = AnalyticsReport.objects.create(
            clinic_id="CLN-001",
            report_date=date(2026, 7, 27)
        )
        HourlyRevenue.objects.create(analytics_report=self.analytics, hour=12, revenue_paise=1500000)
        MedicineRankEntry.objects.create(
            analytics_report=self.analytics,
            rank_type=MedicineRankEntry.RANK_TYPE_QUANTITY,
            drug_name="PARACETAMOL",
            value=20,
            rank=1
        )
        MedicineRankEntry.objects.create(
            analytics_report=self.analytics,
            rank_type=MedicineRankEntry.RANK_TYPE_REVENUE,
            drug_name="AMOXICILLIN",
            value=800000,
            rank=1
        )
        
        self.llm_mock = MagicMock(spec=LLMProvider)
        self.service = NarrativeService(llm_provider=self.llm_mock)

    def test_build_context_formats_correctly(self):
        context = self.service.build_context(self.recon, self.analytics)
        self.assertEqual(context.get("total_billed"), "₹42,850")
        self.assertEqual(context.get("total_collected"), "₹40,000")
        self.assertEqual(context.get("total_outstanding"), "₹2,850")
        self.assertEqual(context.get("total_refunds"), "₹0")
        self.assertEqual(context.get("visit_count"), "10")
        self.assertEqual(context.get("peak_hour_revenue"), "₹15,000")
        self.assertEqual(context.get("peak_hour_time"), "12pm–1pm")
        self.assertEqual(context.get("top_medicine_by_qty_name"), "PARACETAMOL")
        self.assertEqual(context.get("top_medicine_by_qty_value"), "20")

    def test_grounding_success(self):
        # A valid template
        template = "Total billed was {{total_billed}}. Peak hour was {{peak_hour_time}}."
        self.llm_mock.request_template.return_value = json.dumps({"summaryTemplate": template})
        
        result = self.service.generate_narrative(self.recon, self.analytics)
        
        self.assertEqual(result.status, NarrativeStatus.SUCCESS)
        self.assertIn("Total billed was ₹42,850", result.text)
        self.assertIn("Peak hour was 12pm–1pm", result.text)
        
        # Verify traced figures
        figures = getattr(result, "_unsaved_figures", [])
        self.assertEqual(len(figures), 2)
        placeholders = [f.placeholder for f in figures]
        self.assertIn("total_billed", placeholders)
        self.assertIn("peak_hour_time", placeholders)

    def test_grounding_rejects_stray_digits(self):
        # A template with hardcoded digits
        template = "Total billed was ₹42850 instead of {{total_billed}}."
        self.llm_mock.request_template.return_value = json.dumps({"summaryTemplate": template})
        
        result = self.service.generate_narrative(self.recon, self.analytics)
        
        # Will retry once, get same response, and fallback
        self.assertEqual(result.status, NarrativeStatus.FAILED_FALLBACK)
        self.assertEqual(self.llm_mock.request_template.call_count, 2)
        
        # Assert fallback text
        self.assertIn("Total billing for the day was ₹42,850", result.text)

    def test_grounding_rejects_unknown_placeholder(self):
        # A template with hallucinated placeholder
        template = "Total profit was {{profit}}."
        self.llm_mock.request_template.return_value = json.dumps({"summaryTemplate": template})
        
        result = self.service.generate_narrative(self.recon, self.analytics)
        
        # Fallback
        self.assertEqual(result.status, NarrativeStatus.FAILED_FALLBACK)
        # Warning should contain "unknown placeholder keys"
        self.assertTrue(any("unknown placeholder keys: profit" in w for w in result.warnings))

    def test_orchestration_fallback_on_json_error(self):
        # LLM returns invalid JSON
        self.llm_mock.request_template.return_value = "Here is your summary: {malformed json"
        
        result = self.service.generate_narrative(self.recon, self.analytics)
        
        self.assertEqual(result.status, NarrativeStatus.FAILED_FALLBACK)
        self.assertEqual(self.llm_mock.request_template.call_count, 2)
        
    def test_retry_success(self):
        # First attempt fails with stray digit, second attempt succeeds
        bad_template = json.dumps({"summaryTemplate": "Total 123"})
        good_template = json.dumps({"summaryTemplate": "Total is {{total_billed}}"})
        
        self.llm_mock.request_template.side_effect = [bad_template, good_template]
        
        result = self.service.generate_narrative(self.recon, self.analytics)
        
        self.assertEqual(result.status, NarrativeStatus.SUCCESS)
        self.assertEqual(self.llm_mock.request_template.call_count, 2)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("Attempt 1 rejected: hardcoded number detected", result.warnings[0])
