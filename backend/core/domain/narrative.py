"""
Transient Narrative Objects — NarrativeContext & LLMTemplateResponse.
======================================================================
These objects exist only during the narrative generation pipeline.
Neither is ever persisted — only the final NarrativeResult ORM model is.

LLD reference: §1 NarrativeContext, LLMTemplateResponse; §3 Sequence;
               §5 Grounding by Construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import AnalyticsReport, ReconciliationReport


@dataclass
class NarrativeContext:
    """
    LLD: NarrativeContext — the *only* thing the LLM ever sees.

    A flat key → display-string map built from the two report objects.
    Example entry: "total_billed" → "₹42,850"

    Design rules (LLD §1, §5):
      - The LLM never receives raw paise integers, only pre-formatted strings.
      - The LLM can only reference keys that exist in this map.  A metric
        like "profit" — never added here because cost price isn't in the
        schema — cannot be referenced, computed, or hallucinated.
      - build_from_reports() is the sole factory; nothing else constructs
        a NarrativeContext.
    """

    values: dict[str, str]

    @classmethod
    def build_from_reports(
        cls,
        recon: ReconciliationReport,
        analytics: AnalyticsReport,
    ) -> NarrativeContext:
        """
        LLD: buildFromReports() — Step A of Grounding by Construction.

        Selects only the fields we're willing to expose to the LLM and
        formats each one exactly as it should appear on screen
        (paise → "₹X,XXX", hour → "12pm–1pm", etc.).

        Implemented by context_builder service (LLD §6); this stub keeps
        the signature on the model so callers have a single import point.
        """
        raise NotImplementedError(
            "build_from_reports() is implemented in "
            "core.narrative.context_builder — import from there."
        )

    def has(self, key: str) -> bool:
        """LLD: has(key) — True when the key exists in the whitelist."""
        return key in self.values

    def get(self, key: str) -> str:
        """
        LLD: get(key) — returns the display string for a key.

        Raises KeyError if the key is not in the whitelist.  Callers
        (grounding service) must call has() first or catch KeyError.
        """
        return self.values[key]

    def keys(self) -> list[str]:
        """All whitelisted placeholder keys — useful for prompt construction."""
        return list(self.values.keys())

    def __len__(self) -> int:
        return len(self.values)

    def __repr__(self) -> str:
        return f"NarrativeContext({len(self.values)} keys)"


@dataclass(frozen=True)
class LLMTemplateResponse:
    """
    LLD: LLMTemplateResponse — the raw template string returned by the LLM.

    Single field: summary_template (LLD: summaryTemplate).

    The template must contain only {{placeholder}} tokens for any figures —
    no raw numbers.  The grounding service validates this before any
    substitution occurs.

    Example valid template:
      "Total billing for the day was {{total_billed}}, collected via
       {{top_payment_mode}}."

    Example invalid template (stray digit — will be rejected):
      "Total billing was ₹42850, collected via UPI."
    """

    # LLD: summaryTemplate
    summary_template: str

    def __repr__(self) -> str:
        preview = self.summary_template[:60].replace("\n", " ")
        return f"LLMTemplateResponse({preview!r}...)"
