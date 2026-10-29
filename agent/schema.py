"""
Pydantic schemas for insurer disclosure KPI extraction.

Every extracted row must conform to these schemas before entering the
reconciliation pipeline.  Unknown or unclear values are recorded as
``None`` with a mandatory ``reason`` string — the agent is never allowed
to guess.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Unit(str, Enum):
    """Monetary unit as stated in the table header."""
    LAKHS = "lakhs"
    CRORES = "crores"
    THOUSANDS = "thousands"
    UNITS = "units"          # for counts (policies, claims)
    PERCENT = "percent"
    UNKNOWN = "unknown"


class ValidationStatus(str, Enum):
    """Row-level validation outcome."""
    PENDING = "pending"
    VALIDATED = "validated"
    QUARANTINED = "quarantined"


class ExtractionStrategy(str, Enum):
    """Table extraction strategy used by ``pdfplumber``."""
    RULED = "ruled"          # detect ruled lines
    TEXT_ALIGN = "text_align"  # infer columns from text alignment
    HYBRID = "hybrid"        # try ruled first, fall back to text_align


# ---------------------------------------------------------------------------
# Row-level schemas
# ---------------------------------------------------------------------------

class NullableValue(BaseModel):
    """
    A numeric value that is allowed to be null.

    When ``value`` is ``None``, ``null_reason`` **must** be provided.
    This prevents the LLM from silently dropping values.
    """
    value: Optional[float] = Field(
        default=None,
        description="Extracted numeric value, or null if missing/unclear.",
    )
    null_reason: Optional[str] = Field(
        default=None,
        description="Required when value is null — why the value could not be read.",
    )

    @model_validator(mode="after")
    def _require_reason_when_null(self) -> "NullableValue":
        if self.value is None and not self.null_reason:
            raise ValueError(
                "null_reason is required when value is None. "
                "Do not drop values silently."
            )
        return self


class KPIRow(BaseModel):
    """
    One key-performance-indicator row extracted from a disclosure table.

    Maps to a single cell or metric in the original PDF table.
    """
    insurer: str = Field(
        ...,
        description="Insurer name exactly as printed in the PDF.",
    )
    period: str = Field(
        ...,
        description="Reporting period, e.g. 'Q2 FY2024' or '2023-24'.",
    )
    section: str = Field(
        ...,
        description="Table section or form number, e.g. 'NL-1', 'Revenue Account'.",
    )
    metric_name: str = Field(
        ...,
        description="Metric label exactly as in the table header.",
    )
    metric_value: NullableValue = Field(
        ...,
        description="Extracted value with optional null reason.",
    )
    unit: Unit = Field(
        ...,
        description="Unit as stated in the table header.",
    )
    is_total: bool = Field(
        default=False,
        description="True if this row is a total / subtotal line.",
    )
    source_doc_id: str = Field(
        ...,
        description="Document identifier for traceability.",
    )
    source_page: int = Field(
        ...,
        ge=1,
        description="1-based page number in the PDF.",
    )
    validation_status: ValidationStatus = Field(
        default=ValidationStatus.PENDING,
        description="Set by reconciliation; not by the LLM.",
    )
    quarantine_reason: Optional[str] = Field(
        default=None,
        description="Reason for quarantine, if applicable.",
    )


class ExtractionResult(BaseModel):
    """Complete extraction output for one table."""
    doc_id: str
    page: int
    strategy_used: ExtractionStrategy
    rows: list[KPIRow]
    raw_header_unit: Optional[str] = Field(
        default=None,
        description="Unit string as printed in the table header.",
    )
    extraction_notes: Optional[str] = Field(
        default=None,
        description="Any anomalies noticed during extraction.",
    )


# ---------------------------------------------------------------------------
# Run-log schema
# ---------------------------------------------------------------------------

class RunLogEntry(BaseModel):
    """One step in the agent's execution trace."""
    step_number: int
    tool_name: str
    tool_args: dict
    result_summary: str
    tokens_used: int = 0
    duration_seconds: float = 0.0
    timestamp: str = ""


class RunLog(BaseModel):
    """Full execution log for one agent run."""
    run_id: str
    doc_id: str
    started_at: str
    finished_at: Optional[str] = None
    steps: list[RunLogEntry] = Field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    outcome: str = "in_progress"  # "success", "partial", "failed"
