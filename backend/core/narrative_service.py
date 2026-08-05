"""
Narrative Service.
==================
Implements LLD §5 "Grounding by Construction".
Handles context building, LLM orchestration, and placeholder substitution/validation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from core.domain.narrative import NarrativeContext, LLMTemplateResponse
from core.models.narrative import NarrativeResult, NarrativeStatus, TracedFigure
from core.models.reconciliation import ReconciliationReport
from core.models.analytics import AnalyticsReport, HourlyRevenue, MedicineRankEntry
from core.llm_provider import LLMProvider, LLMProviderError

logger = logging.getLogger(__name__)

class NarrativeService:
    """
    LLD: Narrative Service + Grounding Service + Context Builder.
    Consolidated into a single class.
    """

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider

    def build_context(self, recon: ReconciliationReport, analytics: AnalyticsReport) -> NarrativeContext:
        """
        Builds the whitelist context from report objects.
        Formats paise and hours to display strings.
        """
        values = {}
        
        # Reconciliation metrics
        values["total_billed"] = self._format_paise(recon.total_billed_paise)
        values["total_collected"] = self._format_paise(recon.total_collected_paise)
        values["total_outstanding"] = self._format_paise(recon.total_outstanding_paise)
        values["total_refunds"] = self._format_paise(recon.total_refunds_paise)
        values["visit_count"] = str(recon.visit_count)
        values["refund_count"] = str(recon.refund_count)
        
        # Analytics metrics (only query if analytics has been saved / has PK)
        if analytics.pk:
            peak_hour = analytics.revenue_by_hour.order_by("-revenue_paise").first()
            if peak_hour:
                values["peak_hour_revenue"] = self._format_paise(peak_hour.revenue_paise)
                values["peak_hour_time"] = self._format_hour(peak_hour.hour)

            top_qty = analytics.medicine_ranks.filter(rank_type=MedicineRankEntry.RANK_TYPE_QUANTITY).order_by("rank").first()
            if top_qty:
                values["top_medicine_by_qty_name"] = top_qty.drug_name
                values["top_medicine_by_qty_value"] = str(top_qty.value)

            top_rev = analytics.medicine_ranks.filter(rank_type=MedicineRankEntry.RANK_TYPE_REVENUE).order_by("rank").first()
            if top_rev:
                values["top_medicine_by_rev_name"] = top_rev.drug_name
                values["top_medicine_by_rev_value"] = self._format_paise(top_rev.value)
                
        return NarrativeContext(values=values)

    def generate_narrative(self, recon_report: ReconciliationReport, analytics_report: AnalyticsReport) -> NarrativeResult:
        """
        Orchestrates LLM call and grounding validation.
        Retries once if REJECTED_RETRY. Falls back on FAILED_FALLBACK.
        """
        context = self.build_context(recon_report, analytics_report)
        
        rejection_reason = None
        warnings = []
        
        for attempt in range(2):
            system_prompt, user_prompt = self._build_prompt(context, rejection_reason)
            
            try:
                response_text = self.llm.request_template(system_prompt, user_prompt)
                parsed = json.loads(response_text)
                if "summaryTemplate" not in parsed:
                    raise ValueError("JSON missing 'summaryTemplate' key")
                
                template = parsed["summaryTemplate"]
                llm_response = LLMTemplateResponse(summary_template=template)
                
                # Grounding validation
                result = self._validate_and_substitute(llm_response.summary_template, context, recon_report)
                
                if result.status == NarrativeStatus.SUCCESS:
                    result.warnings = warnings
                    return result
                else:
                    rejection_reason = result.text  # text holds the rejection reason on failure
                    warnings.append(f"Attempt {attempt + 1} rejected: {rejection_reason}")
                    
            except (LLMProviderError, ValueError, json.JSONDecodeError) as e:
                rejection_reason = f"Provider or JSON error: {str(e)}"
                warnings.append(f"Attempt {attempt + 1} failed: {rejection_reason}")
        
        # Fallback
        warnings.append("Max retries exceeded, using fallback.")
        fallback_text = self._build_fallback_text(context)
        return NarrativeResult(
            recon_report=recon_report,
            text=fallback_text,
            status=NarrativeStatus.FAILED_FALLBACK,
            warnings=warnings
        )

    def _build_prompt(self, context: NarrativeContext, rejection_reason: str | None = None) -> tuple[str, str]:
        system_prompt = (
            "You are a narrative generator for a daily billing report. "
            "Respond in JSON format with a single key 'summaryTemplate'. "
            "You MUST NOT write any raw numbers or metrics in the template. "
            "Instead, you must use EXACTLY the following {{placeholder}} tags for all figures:\n"
            f"{json.dumps(context.keys(), indent=2)}\n\n"
            "Do not invent placeholders. Do not use any digits outside the placeholders."
        )
        
        user_prompt = "Generate the summary template."
        if rejection_reason:
            user_prompt += f"\n\nWARNING: Your previous response was rejected due to: {rejection_reason}. Please fix this."
            
        return system_prompt, user_prompt

    def _validate_and_substitute(self, template: str, context: NarrativeContext, recon: ReconciliationReport) -> NarrativeResult:
        if not self._check_no_stray_digits(template):
            return NarrativeResult(
                recon_report=recon,
                text="hardcoded number detected",
                status=NarrativeStatus.REJECTED_RETRY
            )
            
        unknown_keys = self._check_placeholders_known(template, context)
        if unknown_keys:
            return NarrativeResult(
                recon_report=recon,
                text=f"unknown placeholder keys: {', '.join(unknown_keys)}",
                status=NarrativeStatus.REJECTED_RETRY
            )
            
        final_text, traced_figures = self._substitute_placeholders(template, context)
        
        # Check if any leftovers
        if re.search(r"\{\{.*?\}\}", final_text):
            return NarrativeResult(
                recon_report=recon,
                text="unresolved placeholder remains",
                status=NarrativeStatus.REJECTED_RETRY
            )
            
        # Add profit note if not using fallback
        final_text += "\nNote: cost data wasn't available today, so this is revenue, not profit."

        result = NarrativeResult(
            recon_report=recon,
            text=final_text.strip(),
            status=NarrativeStatus.SUCCESS
        )
        # Store for orchestrator to save
        result._unsaved_figures = traced_figures
        return result

    def _check_no_stray_digits(self, template: str) -> bool:
        """Strips placeholders and checks if any digits are left."""
        stripped = re.sub(r"\{\{.*?\}\}", "", template)
        return not bool(re.search(r"\d", stripped))

    def _check_placeholders_known(self, template: str, context: NarrativeContext) -> list[str]:
        found_keys = re.findall(r"\{\{(.*?)\}\}", template)
        return [k for k in found_keys if not context.has(k)]

    def _substitute_placeholders(self, template: str, context: NarrativeContext) -> tuple[str, list[TracedFigure]]:
        text = template
        figures = []
        found_keys = set(re.findall(r"\{\{(.*?)\}\}", template))
        for key in found_keys:
            if context.has(key):
                val = context.get(key)
                text = text.replace(f"{{{{{key}}}}}", val)
                figures.append(TracedFigure(
                    placeholder=key,
                    display_value=val,
                    source_field=f"NarrativeContext.{key}"
                ))
        return text, figures

    def _build_fallback_text(self, context: NarrativeContext) -> str:
        billed = context.values.get('total_billed', 'N/A')
        collected = context.values.get('total_collected', 'N/A')
        return f"Total billing for the day was {billed}, and total collected was {collected}."

    @staticmethod
    def _format_paise(paise: int) -> str:
        rupees = paise / 100
        if rupees.is_integer():
            return f"₹{int(rupees):,}"
        return f"₹{rupees:,.2f}"

    @staticmethod
    def _format_hour(hour: int) -> str:
        start_period = "am" if hour < 12 else "pm"
        end_period = "am" if (hour + 1) % 24 < 12 else "pm"
        
        start_h = hour if hour <= 12 else hour - 12
        start_h = 12 if start_h == 0 else start_h
        
        end_h = (hour + 1) if (hour + 1) <= 12 else (hour + 1) - 12
        end_h = 12 if end_h == 0 else end_h
        
        return f"{start_h}{start_period}–{end_h}{end_period}"
