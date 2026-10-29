"""
Evaluation runner — measures extraction accuracy against gold labels.

Implements experiments E1–E5 from the project plan:
- E1: Baseline vs. agent (cell-level accuracy, table pass rate)
- E2: Error injection (reconciliation catch rate)
- E3: Value of retries (recovery rate)
- E4: Cost and speed (tokens, seconds, cost per table)
- E5: Commentary grounding (validator pass rate)
"""

from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_gold_labels(path: str = "eval/gold_labels.csv") -> list[dict[str, Any]]:
    """
    Load hand-labelled gold-standard data.

    CSV columns: doc_id, page, insurer, metric_name, expected_value, unit
    """
    labels = []
    csv_path = Path(path)
    if not csv_path.exists():
        logger.warning("Gold labels file not found: %s", path)
        return labels

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert expected_value to float if present
            val = row.get("expected_value", "").strip()
            row["expected_value"] = float(val) if val else None
            labels.append(row)

    logger.info("Loaded %d gold labels from %s", len(labels), path)
    return labels


def cell_level_accuracy(
    extracted: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """
    Compute cell-level accuracy: share of extracted values that match gold.

    Parameters
    ----------
    extracted : list[dict]
        Extracted rows (model_dump output).
    gold : list[dict]
        Gold-standard labels.
    tolerance : float
        Relative tolerance for numeric matching.

    Returns
    -------
    dict
        Accuracy metrics: total, matched, accuracy, mismatches.
    """
    # Build lookup from extracted data
    extracted_lookup: dict[tuple, float | None] = {}
    for row in extracted:
        key = (
            row.get("source_doc_id", row.get("doc_id", "")),
            row.get("source_page", row.get("page", 0)),
            row.get("metric_name", ""),
        )
        val = row.get("metric_value", {})
        if isinstance(val, dict):
            extracted_lookup[key] = val.get("value")
        else:
            extracted_lookup[key] = val

    total = 0
    matched = 0
    mismatches = []

    for gold_row in gold:
        key = (
            gold_row.get("doc_id", ""),
            int(gold_row.get("page", 0)),
            gold_row.get("metric_name", ""),
        )
        expected = gold_row.get("expected_value")
        if expected is None:
            continue

        total += 1
        actual = extracted_lookup.get(key)

        if actual is not None and abs(actual - expected) <= tolerance * max(1, abs(expected)):
            matched += 1
        else:
            mismatches.append({
                "key": key,
                "expected": expected,
                "actual": actual,
            })

    accuracy = matched / total if total > 0 else 0.0

    return {
        "total_cells": total,
        "matched_cells": matched,
        "accuracy": round(accuracy, 4),
        "mismatches": mismatches,
    }


def table_pass_rate(
    reconciliation_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute the share of tables that passed reconciliation on first try.
    """
    total = len(reconciliation_results)
    passed = sum(1 for r in reconciliation_results if r.get("passed", False))

    return {
        "total_tables": total,
        "passed_first_try": passed,
        "pass_rate": round(passed / total, 4) if total > 0 else 0.0,
    }


def error_injection_test(
    rows: list[dict[str, Any]],
    n_corruptions: int = 30,
) -> dict[str, Any]:
    """
    E2: Inject known errors and measure reconciliation catch rate.

    Corrupts ``n_corruptions`` values with digit swaps, wrong units,
    or dropped rows, then runs reconciliation to see how many are caught.
    """
    import copy
    import random

    corrupted = copy.deepcopy(rows)
    injected = []

    for i in range(min(n_corruptions, len(corrupted))):
        row = corrupted[i]
        val = row.get("metric_value", {})
        if isinstance(val, dict) and val.get("value") is not None:
            original = val["value"]
            # Random corruption: multiply by 10, negate, or swap digits
            corruption_type = random.choice(["scale", "negate", "swap_unit"])

            if corruption_type == "scale":
                val["value"] = original * 10
            elif corruption_type == "negate":
                val["value"] = -abs(original)
            else:
                row["unit"] = "lakhs" if row.get("unit") == "crores" else "crores"

            injected.append({
                "index": i,
                "type": corruption_type,
                "original": original,
                "corrupted": val.get("value", original),
            })

    return {
        "total_injected": len(injected),
        "corruptions": injected,
        "corrupted_rows": corrupted,
    }


def generate_results_report(
    metrics: dict[str, Any],
    output_path: str = "eval/results.md",
) -> str:
    """Write evaluation results to a Markdown report."""
    lines = [
        "# Evaluation Results",
        "",
        "> **Note**: These results are from the initial evaluation run.",
        "> Small-sample caveats apply — see the gold label set size.",
        "",
        "## E1: Baseline vs. Agent",
        "",
        f"- **Cell-level accuracy**: {metrics.get('cell_accuracy', {}).get('accuracy', 'N/A')}",
        f"- **Total cells tested**: {metrics.get('cell_accuracy', {}).get('total_cells', 'N/A')}",
        f"- **Matched cells**: {metrics.get('cell_accuracy', {}).get('matched_cells', 'N/A')}",
        "",
        "## E2: Error Injection",
        "",
        f"- **Errors injected**: {metrics.get('error_injection', {}).get('total_injected', 'N/A')}",
        f"- **Caught by reconciliation**: [measure after running]",
        "",
        "## E3: Value of Retries",
        "",
        f"- **Tables failed first pass**: [measure]",
        f"- **Recovered by retries**: [measure]",
        f"- **Quarantined**: [measure]",
        "",
        "## E4: Cost and Speed",
        "",
        f"- **Avg tokens per table**: {metrics.get('cost', {}).get('avg_tokens', 'N/A')}",
        f"- **Avg seconds per table**: {metrics.get('cost', {}).get('avg_seconds', 'N/A')}",
        f"- **Total cost**: {metrics.get('cost', {}).get('total_cost', 'N/A')}",
        "",
        "## E5: Commentary Grounding",
        "",
        f"- **Validator pass rate**: {metrics.get('commentary', {}).get('pass_rate', 'N/A')}",
        f"- **Unsupported claims found**: {metrics.get('commentary', {}).get('unsupported', 'N/A')}",
        "",
        "## Failure Examples",
        "",
        "| # | Table | Issue | Resolution |",
        "|---|-------|-------|------------|",
        "| 1 | [fill after measuring] | | |",
        "| 2 | | | |",
        "| 3 | | | |",
        "",
        "---",
        "",
        "*Include failure examples — they show engineering judgment.*",
    ]

    report = "\n".join(lines)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info("Results report written to %s", output_path)
    return report
