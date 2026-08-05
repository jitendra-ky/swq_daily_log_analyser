"""
Report Orchestrator.
====================
Implements LLD §2 & §3 Report Orchestrator logic.
Coordinates ingestion, reconciliation, analytics, and narrative services.
"""

from typing import Any

from django.db import transaction
from django.conf import settings

from core.ingestion_service import IngestionService
from core.reconciliation_service import ReconciliationService
from core.analytics_service import AnalyticsService
from core.narrative_service import NarrativeService
from core.llm_provider import LLMProvider

from core.models import BillingRecord, LineItem, ValidationError
from core.models.reconciliation import ReconciliationReport, PaymentModeBreakdown
from core.models.analytics import AnalyticsReport, HourlyRevenue, MedicineRankEntry
from core.models.narrative import TracedFigure


class ReportOrchestrator:
    """
    LLD: Report Orchestrator.
    
    Stateless — safe to instantiate once and reuse across requests.
    """

    def __init__(self, llm_provider: LLMProvider | None = None):
        self.ingestion = IngestionService()
        self.reconciliation = ReconciliationService()
        self.analytics = AnalyticsService()
        # Allows dependency injection for tests
        self.narrative = NarrativeService(llm_provider=llm_provider or LLMProvider(api_key=settings.GROQ_API_KEY))

    def generate_daily_report(self, clinic_id: str, raw_rows: list[dict[str, Any]], batch: str) -> dict[str, Any]:
        """
        Orchestrates the end-to-end report generation pipeline.
        
        Args:
            clinic_id: The clinic identifier.
            raw_rows: Raw parsed JSON billing rows.
            batch: An identifier for this upload batch.
            
        Returns:
            A dictionary containing the generated/saved models.
        """
        # 1. Ingestion & Validation
        parse_result = self.ingestion.parse_log(raw_rows, batch)
        
        # 2. Persistence (Ingestion)
        # Using atomic to ensure partial data isn't saved.
        with transaction.atomic():
            # Clean the whole database as per user request
            BillingRecord.objects.all().delete()
            ValidationError.objects.all().delete()
            ReconciliationReport.objects.all().delete()
            AnalyticsReport.objects.all().delete()
            
            if parse_result.errors:
                ValidationError.objects.bulk_create(parse_result.errors)
                
            if parse_result.valid_records:
                BillingRecord.objects.bulk_create(parse_result.valid_records)
                
                # Bulk create line items for the newly saved records
                line_items_to_create = []
                for record in parse_result.valid_records:
                    # record is now saved, so we can use its pk
                    pending = getattr(record, "_pending_line_items", [])
                    for item in pending:
                        line_items_to_create.append(LineItem(
                            billing_record=record,
                            drug_name=item["drug_name"],
                            qty=item["qty"],
                            unit_price_paise=item["unit_price_paise"],
                        ))
                
                if line_items_to_create:
                    LineItem.objects.bulk_create(line_items_to_create)

        # Base response
        response: dict[str, Any] = {
            "errors": parse_result.errors,
            "total_rows_processed": parse_result.total_rows,
            "valid_records_count": len(parse_result.valid_records),
            "recon_report": None,
            "analytics_report": None,
            "narrative_result": None,
        }

        # If no valid records, we don't proceed with generating reports for this payload.
        if not parse_result.valid_records:
            return response

        # 3. Compute Reports
        recon_report, breakdowns = self.reconciliation.compute(parse_result.valid_records, clinic_id)
        analytics_report, hourly_rows, rank_rows = self.analytics.compute(parse_result.valid_records, clinic_id)

        # 4. Persistence (Reports)
        with transaction.atomic():
            # Delete any existing reports for this clinic & date for idempotency
            ReconciliationReport.objects.filter(clinic_id=clinic_id, report_date=recon_report.report_date).delete()
            AnalyticsReport.objects.filter(clinic_id=clinic_id, report_date=analytics_report.report_date).delete()

            # Save Reconciliation
            recon_report.save()
            for bd in breakdowns:
                bd.report = recon_report
            if breakdowns:
                PaymentModeBreakdown.objects.bulk_create(breakdowns)

            # Save Analytics
            analytics_report.save()
            for hr in hourly_rows:
                hr.analytics_report = analytics_report
            if hourly_rows:
                HourlyRevenue.objects.bulk_create(hourly_rows)
                
            for rr in rank_rows:
                rr.analytics_report = analytics_report
            if rank_rows:
                MedicineRankEntry.objects.bulk_create(rank_rows)

        # 5. Generate Narrative (Outside transaction to prevent external network call locks)
        narrative_result = self.narrative.generate_narrative(recon_report, analytics_report)

        # 6. Persistence (Narrative)
        with transaction.atomic():
            narrative_result.save()
            unsaved_figures = getattr(narrative_result, "_unsaved_figures", [])
            for fig in unsaved_figures:
                fig.narrative_result = narrative_result
            if unsaved_figures:
                TracedFigure.objects.bulk_create(unsaved_figures)

        response["recon_report"] = recon_report
        response["analytics_report"] = analytics_report
        response["narrative_result"] = narrative_result
        
        return response
