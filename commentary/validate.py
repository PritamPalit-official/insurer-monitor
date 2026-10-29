"""
Commentary number-grounding validator.

Ensures that every numeric value cited in LLM-generated commentary
actually exists in the validated KPI data.  This catches hallucinated
numbers before they reach the final report.

Design from project plan Section 5:
    ``validate_commentary(text, kpi_json, tol=0.005)``
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_numbers(text: str) -> list[float]:
    """
    Extract all numeric values from commentary text.

    Ignores:
    - Year references (4-digit numbers starting with 19 or 20)
    - Period labels like Q1, Q2, FY2024
    - Section numbers like NL-1, NL-2

    Handles:
    - Integers and decimals
    - Negative numbers
    - Percentages (extracts the numeric part)
    - Comma-separated numbers (e.g. 1,234.56)
    """
    # Remove period labels to avoid false matches
    cleaned = re.sub(
        r"\b(?:Q[1-4]|FY\s*\d{4}(?:-\d{2,4})?|NL-\d+|H[12])\b",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Find all numeric patterns
    patterns = [
        r"-?[\d,]+\.?\d*",  # integers and decimals with optional commas
    ]

    numbers = []
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned):
            raw = match.group().replace(",", "")
            try:
                val = float(raw)
                # Skip years (4-digit numbers 1900-2099)
                if val == int(val) and 1900 <= val <= 2099:
                    continue
                # Skip very small integers likely to be noise (0, 1, 2...)
                # but keep them if they appear as percentages in context
                numbers.append(val)
            except ValueError:
                continue

    return numbers


def collect_numbers(kpi_json: list[dict[str, Any]]) -> list[float]:
    """
    Collect all numeric values from validated KPI data.

    Includes raw values, computed deltas, ranks, and percentages.
    """
    numbers: list[float] = []

    for row in kpi_json:
        # Direct metric value
        val = row.get("metric_value", {}).get("value")
        if val is not None:
            numbers.append(float(val))

        # Computed changes (if present)
        for key in ("absolute_change", "percent_change", "current_value", "prior_value"):
            v = row.get(key)
            if v is not None:
                numbers.append(float(v))

    return numbers


def validate_commentary(
    text: str,
    kpi_json: list[dict[str, Any]],
    tol: float = 0.005,
) -> tuple[bool, list[float]]:
    """
    Validate that every number cited in the commentary exists in the KPI data.

    Parameters
    ----------
    text : str
        LLM-generated commentary.
    kpi_json : list[dict]
        Validated KPI rows and computed changes.
    tol : float
        Relative tolerance for matching (default 0.5%).

    Returns
    -------
    tuple[bool, list[float]]
        (passed, unsupported_numbers).
        ``passed`` is True if all cited numbers are found in the data.
        ``unsupported_numbers`` lists values not found.
    """
    cited = extract_numbers(text)
    allowed = collect_numbers(kpi_json)

    if not cited:
        logger.info("No numbers found in commentary — passing vacuously.")
        return True, []

    unsupported = []
    for n in cited:
        found = any(
            abs(n - a) <= tol * max(1, abs(a))
            for a in allowed
        )
        if not found:
            unsupported.append(n)

    if unsupported:
        logger.warning(
            "Commentary validation FAILED: %d unsupported number(s): %s",
            len(unsupported),
            unsupported,
        )
        return False, unsupported

    logger.info("Commentary validation PASSED: all %d numbers grounded.", len(cited))
    return True, []
