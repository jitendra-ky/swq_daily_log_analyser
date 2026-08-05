"""
ParseResult — transient output of the Ingestion Service.
=========================================================
Lives only for the duration of one pipeline run.  The orchestrator
reads it and decides what to persist (valid_records → BillingRecord.save(),
errors → ValidationError.save()).  It is never stored directly.

LLD reference: §1 ParseResult, §4 Validation Flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Imported only for type hints — avoids a hard Django dependency
    # from inside the domain package.
    from core.models import BillingRecord, ValidationError


@dataclass
class ParseResult:
    """
    LLD: ParseResult

    Holds the two outputs of parseLog():
      valid_records — unsaved BillingRecord ORM instances that passed all
                      validation rules and are ready for bulk_create().
      errors        — unsaved ValidationError ORM instances, one per bad row.
      total_rows    — total number of raw rows seen (valid + invalid).

    Key design rule (LLD §4):
      One bad row never aborts the batch.  parseLog() always returns both
      lists — the caller decides whether partial success is acceptable.
    """

    valid_records: list[BillingRecord] = field(default_factory=list)
    errors: list[ValidationError] = field(default_factory=list)
    total_rows: int = 0

    def has_errors(self) -> bool:
        """LLD: hasErrors() — True when at least one row failed validation."""
        return len(self.errors) > 0

    @property
    def error_count(self) -> int:
        """Convenience: number of failed rows."""
        return len(self.errors)

    @property
    def valid_count(self) -> int:
        """Convenience: number of rows that passed validation."""
        return len(self.valid_records)
