"""
Prompt templates for the extraction agent.

Prompt design principles (from project plan):
- Use only values visible in the table text.
- Record the unit stated in the header.
- If a value is missing or unclear, return null and a reason.
- Do not infer or compute totals.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = """\
You are a precise data-extraction assistant for Indian insurance-industry \
disclosure tables. Your job is to convert one table into structured JSON rows.

Rules:
1. Use ONLY values visible in the table text. Do NOT infer, estimate, or \
   compute any values — especially totals.
2. Record the unit exactly as stated in the table header (lakhs, crores, etc.).
3. If a value is missing, unclear, or unreadable, return null for the value \
   and provide a clear reason in null_reason.
4. Preserve the insurer name and metric labels exactly as printed.
5. Mark total / subtotal rows with is_total = true.
6. Output valid JSON matching the KPIRow schema.
"""

EXTRACTION_USER = """\
Convert the following table from an insurer disclosure into rows matching \
the KPIRow schema.

Document: {doc_id}
Page: {page}
Table header / context:
{table_header}

Raw table text:
{table_text}

Return a JSON array of KPIRow objects. Use only values visible in the table \
text. Record the unit stated in the header. If a value is missing or unclear, \
return null and a reason. Do not infer or compute totals.
"""


# ---------------------------------------------------------------------------
# Commentary prompt
# ---------------------------------------------------------------------------

COMMENTARY_SYSTEM = """\
You are a financial-commentary writer. You write concise, factual \
observations about insurance industry KPIs.

Rules:
1. Use ONLY numbers present in the provided JSON data.
2. Describe changes; do NOT claim causes.
3. If a comparison is not supported by the data, explicitly say so.
4. Write 3 to 5 observations.
5. Each observation must cite at least one specific number from the data.
"""

COMMENTARY_USER = """\
Write 3 to 5 observations from the following validated KPI data.

KPI JSON:
{kpi_json}

Computed period-over-period changes:
{changes_json}

Use only numbers present in the JSON. Describe changes; do not claim causes. \
If a comparison is not supported by the data, say so.
"""


# ---------------------------------------------------------------------------
# Retry prompt (used when reconciliation fails)
# ---------------------------------------------------------------------------

RETRY_SYSTEM = """\
You are re-extracting a table that failed reconciliation checks. The previous \
extraction had errors identified by deterministic validation.

Focus on the specific issues reported and re-read the problematic rows \
carefully.
"""

RETRY_USER = """\
The previous extraction of this table failed the following checks:
{failed_checks}

Original table text (re-read carefully):
{table_text}

Previous extraction attempt:
{previous_rows}

Please re-extract the failing rows. Pay special attention to:
- Column alignment (values may have shifted)
- Unit consistency (the header states: {header_unit})
- Row completeness (check for missed rows)

Return corrected KPIRow JSON for the failing rows only.
"""
