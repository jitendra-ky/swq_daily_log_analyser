"""
Narrative layer models — NarrativeResult, TracedFigure.

Cross-layer FK to ReconciliationReport uses a string reference
("core.ReconciliationReport") to avoid circular imports.

LLD reference: §1 Data Models (narrative cluster).
"""

from django.db import models


class NarrativeStatus(models.TextChoices):
    """LLD: NarrativeStatus enumeration — outcome of the grounding step."""

    SUCCESS = "SUCCESS", "Success"
    REJECTED_RETRY = "REJECTED_RETRY", "Rejected — retry"
    FAILED_FALLBACK = "FAILED_FALLBACK", "Failed — fallback"


class NarrativeResult(models.Model):
    """
    LLD: NarrativeResult — the stored outcome of one LLM narrative generation.

    Linked one-to-one with a ReconciliationReport so you can always find
    the narrative for a given day's report.

    Fields map to LLD:
      text     → text
      status   → status (NarrativeStatus)
      warnings → warnings
    """

    # String ref avoids importing ReconciliationReport and creating a
    # cross-file circular dependency.
    recon_report = models.OneToOneField(
        "core.ReconciliationReport",
        on_delete=models.CASCADE,
        related_name="narrative_result",
    )
    text = models.TextField()
    status = models.CharField(max_length=20, choices=NarrativeStatus)
    # list of warning strings, e.g. ["retried once — stray digit detected"]
    warnings = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"NarrativeResult(status={self.status}, report={self.recon_report_id})"


class TracedFigure(models.Model):
    """
    LLD: TracedFigure — one substituted placeholder from the LLM template.

    Provides a full audit trail of every number that appeared in the
    narrative text and exactly where it came from.

    Fields map to LLD:
      placeholder   → placeholder   (e.g. "total_billed")
      display_value → displayValue  (e.g. "₹42,850")
      source_field  → sourceField   (e.g. "ReconciliationReport.total_billed_paise")
    """

    narrative_result = models.ForeignKey(
        NarrativeResult,
        on_delete=models.CASCADE,
        related_name="traced_figures",
    )
    placeholder = models.CharField(max_length=100)
    display_value = models.CharField(max_length=200)
    source_field = models.CharField(max_length=200)

    class Meta:
        ordering = ["placeholder"]

    def __str__(self) -> str:
        return f"TracedFigure({{{{{self.placeholder}}}}} → {self.display_value})"
