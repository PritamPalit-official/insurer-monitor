"""
Commentary generation from validated KPI data.

Feeds only validated (reconciled) JSON to the LLM.  The model never sees
raw PDF text — it works exclusively with structured, validated numbers.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def compute_changes(
    current: list[dict[str, Any]],
    prior: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """
    Compute period-over-period changes from validated KPI rows.

    Returns a list of change records with absolute and percentage deltas.
    Only computes changes when both current and prior values exist.
    """
    if not prior:
        return []

    # Build lookup: (insurer, metric_name) -> value
    prior_lookup: dict[tuple[str, str], float] = {}
    for row in prior:
        val = row.get("metric_value", {}).get("value")
        if val is not None:
            key = (row["insurer"], row["metric_name"])
            prior_lookup[key] = val

    changes = []
    for row in current:
        val = row.get("metric_value", {}).get("value")
        if val is None:
            continue

        key = (row["insurer"], row["metric_name"])
        if key in prior_lookup:
            prev = prior_lookup[key]
            abs_change = val - prev
            pct_change = (abs_change / prev * 100) if prev != 0 else None

            changes.append({
                "insurer": row["insurer"],
                "metric_name": row["metric_name"],
                "period": row["period"],
                "current_value": val,
                "prior_value": prev,
                "absolute_change": round(abs_change, 2),
                "percent_change": round(pct_change, 2) if pct_change is not None else None,
                "unit": row.get("unit", "unknown"),
            })

    return changes


def build_commentary_prompt(
    kpi_rows: list[dict[str, Any]],
    changes: list[dict[str, Any]],
) -> str:
    """
    Build the commentary prompt from validated data.

    This is the input to the LLM — no raw PDF text is included.
    """
    from agent.prompts import COMMENTARY_USER

    return COMMENTARY_USER.format(
        kpi_json=json.dumps(kpi_rows, indent=2, default=str),
        changes_json=json.dumps(changes, indent=2, default=str),
    )


def generate_commentary(
    kpi_rows: list[dict[str, Any]],
    prior_rows: Optional[list[dict[str, Any]]] = None,
    model: str = "gemini-2.0-flash",
) -> str:
    """
    Generate commentary from validated KPI data using an LLM.

    Requires a ``GOOGLE_API_KEY`` or ``OPENAI_API_KEY`` in the environment.
    Falls back to a placeholder if no API key is available.

    Parameters
    ----------
    kpi_rows : list[dict]
        Validated KPI rows (already reconciled).
    prior_rows : list[dict], optional
        Prior-period rows for computing changes.
    model : str
        Model identifier.

    Returns
    -------
    str
        Generated commentary text.
    """
    changes = compute_changes(kpi_rows, prior_rows)
    prompt = build_commentary_prompt(kpi_rows, changes)

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")

    if not api_key:
        logger.warning(
            "No API key found. Returning placeholder commentary. "
            "Set GOOGLE_API_KEY or OPENAI_API_KEY in .env."
        )
        return _placeholder_commentary(kpi_rows, changes)

    # --- Google Gemini path ---
    if os.getenv("GOOGLE_API_KEY"):
        try:
            import google.generativeai as genai

            genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
            from agent.prompts import COMMENTARY_SYSTEM

            gen_model = genai.GenerativeModel(
                model_name=model,
                system_instruction=COMMENTARY_SYSTEM,
            )
            response = gen_model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error("Gemini API error: %s", e)
            return _placeholder_commentary(kpi_rows, changes)

    # --- OpenAI path ---
    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        from agent.prompts import COMMENTARY_SYSTEM

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": COMMENTARY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error("OpenAI API error: %s", e)
        return _placeholder_commentary(kpi_rows, changes)


def _placeholder_commentary(
    kpi_rows: list[dict[str, Any]],
    changes: list[dict[str, Any]],
) -> str:
    """Generate a simple rule-based commentary when no LLM is available."""
    lines = ["## KPI Commentary (auto-generated placeholder)\n"]

    if not kpi_rows:
        return "No validated KPI data available for commentary."

    # Summarize row count
    insurers = {r.get("insurer", "Unknown") for r in kpi_rows}
    lines.append(
        f"- Analyzed {len(kpi_rows)} KPIs across {len(insurers)} insurer(s)."
    )

    # Report top changes
    if changes:
        sorted_changes = sorted(
            [c for c in changes if c.get("percent_change") is not None],
            key=lambda c: abs(c["percent_change"]),
            reverse=True,
        )
        for c in sorted_changes[:3]:
            direction = "increased" if c["absolute_change"] > 0 else "decreased"
            lines.append(
                f"- {c['insurer']} — {c['metric_name']} {direction} by "
                f"{abs(c['percent_change']):.1f}% "
                f"(from {c['prior_value']} to {c['current_value']} {c['unit']})."
            )

    lines.append(
        "\n*Note: This is placeholder commentary. "
        "Set an API key for LLM-generated insights.*"
    )
    return "\n".join(lines)
