"""
Agent loop — the core agentic extraction pipeline.

Implements the plan → call-tool → observe → decide cycle from the
architecture diagram.  The agent chooses among extraction strategies
and retry approaches based on what failed.

Guardrails:
- Maximum steps per table (default 5)
- Cost cap per run
- Only ``write_clean`` and ``quarantine`` can write
- Every step is logged
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from agent.schema import (
    ExtractionResult,
    ExtractionStrategy,
    KPIRow,
    NullableValue,
    RunLog,
    Unit,
    ValidationStatus,
)
from agent.tools import (
    clear_stores,
    export_run_log,
    extract_tables,
    list_documents,
    log_step,
    quarantine,
    read_page_text,
    write_clean,
)
from checks.reconcile import reconcile, ReconciliationReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_STEPS = 5
DEFAULT_COST_CAP_USD = 1.0
STRATEGIES_IN_ORDER = [
    ExtractionStrategy.RULED,
    ExtractionStrategy.TEXT_ALIGN,
    ExtractionStrategy.HYBRID,
]


# ---------------------------------------------------------------------------
# Table-to-rows parsing (deterministic fallback when no LLM is available)
# ---------------------------------------------------------------------------

def parse_table_to_rows(
    table: list[list[Optional[str]]],
    doc_id: str,
    page: int,
    insurer: str,
    period: str,
    strategy: ExtractionStrategy,
) -> list[KPIRow]:
    """
    Convert raw ``pdfplumber`` table cells into ``KPIRow`` objects.

    This is the deterministic baseline parser.  In production, the LLM
    ``propose_rows`` tool replaces this for ambiguous tables.
    """
    if not table or len(table) < 2:
        return []

    header = [str(cell or "").strip() for cell in table[0]]

    # Try to detect the unit from the header
    header_text = " ".join(header).lower()
    unit = Unit.UNKNOWN
    for u in [Unit.CRORES, Unit.LAKHS, Unit.THOUSANDS]:
        if u.value in header_text:
            unit = u
            break

    rows: list[KPIRow] = []
    for row_idx, row_data in enumerate(table[1:], start=1):
        cells = [str(cell or "").strip() for cell in row_data]
        if not cells or not cells[0]:
            continue

        metric_name = cells[0]
        is_total = any(
            kw in metric_name.lower()
            for kw in ("total", "sub-total", "subtotal", "grand total")
        )

        # Take the last non-empty numeric cell as the value
        value = None
        null_reason = None
        for cell in reversed(cells[1:]):
            cleaned = cell.replace(",", "").replace("(", "-").replace(")", "").strip()
            if cleaned and cleaned not in ("-", "", "N/A", "n/a", "NA"):
                try:
                    value = float(cleaned)
                    break
                except ValueError:
                    continue

        if value is None:
            null_reason = "No numeric value found in row cells."

        rows.append(
            KPIRow(
                insurer=insurer,
                period=period,
                section=f"Page {page}",
                metric_name=metric_name,
                metric_value=NullableValue(value=value, null_reason=null_reason),
                unit=unit,
                is_total=is_total,
                source_doc_id=doc_id,
                source_page=page,
            )
        )

    return rows


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent(
    pdf_path: str,
    doc_id: str,
    insurer: str,
    period: str,
    pages: Optional[list[int]] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    cost_cap_usd: float = DEFAULT_COST_CAP_USD,
    prior_rows: Optional[list[KPIRow]] = None,
) -> dict[str, Any]:
    """
    Run the agentic extraction pipeline on a single PDF document.

    The loop:
    1. Read page text (cached)
    2. Extract tables using the first strategy
    3. Parse rows into KPIRow schema
    4. Run reconciliation checks
    5. If checks pass → write_clean
    6. If checks fail → retry with alternate strategy
    7. After max retries → quarantine with reason

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.
    doc_id : str
        Document identifier.
    insurer, period : str
        Metadata for the extracted rows.
    pages : list[int], optional
        Pages to process (1-based). If None, processes all pages.
    max_steps : int
        Maximum extraction attempts per table.
    cost_cap_usd : float
        Cost cap (placeholder for token-cost tracking).

    Returns
    -------
    dict
        Summary with counts of validated, quarantined, and total rows.
    """
    import pdfplumber

    run_log = RunLog(
        run_id=f"{doc_id}_{int(time.time())}",
        doc_id=doc_id,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    # Determine pages to process
    if pages is None:
        with pdfplumber.open(pdf_path) as pdf:
            pages = list(range(1, len(pdf.pages) + 1))

    total_validated = 0
    total_quarantined = 0
    total_rows = 0
    step_counter = 0

    for page in pages:
        logger.info("Processing doc=%s page=%d", doc_id, page)

        # Step 1: Read page text
        step_counter += 1
        t0 = time.time()
        try:
            page_text = read_page_text(doc_id, page, pdf_path)
        except Exception as e:
            logger.error("Failed to read page %d: %s", page, e)
            log_step(step_counter, "read_page_text",
                     {"doc_id": doc_id, "page": page},
                     f"ERROR: {e}")
            continue

        log_step(step_counter, "read_page_text",
                 {"doc_id": doc_id, "page": page},
                 f"OK: {len(page_text)} chars",
                 duration_seconds=round(time.time() - t0, 3))

        if not page_text.strip():
            logger.info("Page %d is empty, skipping.", page)
            continue

        # Step 2-6: Try extraction strategies with retries
        page_validated = False

        for strategy_idx, strategy in enumerate(STRATEGIES_IN_ORDER):
            if strategy_idx >= max_steps:
                break

            step_counter += 1
            t0 = time.time()

            # Extract tables
            try:
                tables = extract_tables(doc_id, page, pdf_path, strategy=strategy)
            except Exception as e:
                logger.error("extract_tables failed (strategy=%s): %s", strategy, e)
                log_step(step_counter, "extract_tables",
                         {"doc_id": doc_id, "page": page, "strategy": strategy.value},
                         f"ERROR: {e}",
                         duration_seconds=round(time.time() - t0, 3))
                continue

            if not tables:
                log_step(step_counter, "extract_tables",
                         {"doc_id": doc_id, "page": page, "strategy": strategy.value},
                         "No tables found.",
                         duration_seconds=round(time.time() - t0, 3))
                continue

            # Parse each table
            all_rows: list[KPIRow] = []
            for table in tables:
                rows = parse_table_to_rows(
                    table, doc_id, page, insurer, period, strategy
                )
                all_rows.extend(rows)

            if not all_rows:
                log_step(step_counter, "parse_table_to_rows",
                         {"doc_id": doc_id, "page": page, "strategy": strategy.value},
                         "No rows parsed from tables.",
                         duration_seconds=round(time.time() - t0, 3))
                continue

            log_step(step_counter, "extract_tables",
                     {"doc_id": doc_id, "page": page, "strategy": strategy.value},
                     f"OK: {len(tables)} table(s), {len(all_rows)} row(s)",
                     duration_seconds=round(time.time() - t0, 3))

            # Step: Reconcile
            step_counter += 1
            t0 = time.time()
            report = reconcile(
                all_rows,
                doc_id=doc_id,
                page=page,
                prior_rows=prior_rows,
            )

            log_step(step_counter, "reconcile",
                     {"doc_id": doc_id, "page": page},
                     report.summary(),
                     duration_seconds=round(time.time() - t0, 3))

            if report.passed:
                # Write validated rows
                step_counter += 1
                count = write_clean(all_rows)
                log_step(step_counter, "write_clean",
                         {"doc_id": doc_id, "page": page},
                         f"Wrote {count} validated rows.")
                total_validated += count
                total_rows += count
                page_validated = True
                break
            else:
                logger.info(
                    "Strategy %s failed reconciliation for page %d. "
                    "Trying next strategy...",
                    strategy.value, page,
                )

        # Step 7: Quarantine if all strategies failed
        if not page_validated and 'all_rows' in dir() and all_rows:
            step_counter += 1
            failed_summary = (
                report.summary() if 'report' in dir()
                else "All extraction strategies exhausted."
            )
            count = quarantine(all_rows, reason=failed_summary)
            log_step(step_counter, "quarantine",
                     {"doc_id": doc_id, "page": page},
                     f"Quarantined {count} rows: {failed_summary}")
            total_quarantined += count
            total_rows += count

    # Finalize run log
    run_log.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run_log.outcome = (
        "success" if total_quarantined == 0 and total_validated > 0
        else "partial" if total_validated > 0
        else "failed"
    )

    export_run_log()

    summary = {
        "doc_id": doc_id,
        "insurer": insurer,
        "period": period,
        "pages_processed": len(pages),
        "total_rows": total_rows,
        "validated": total_validated,
        "quarantined": total_quarantined,
        "outcome": run_log.outcome,
        "steps": step_counter,
    }

    logger.info("Agent run complete: %s", json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the agent on all documents in the data directory."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Insurer Disclosure Extraction Agent"
    )
    parser.add_argument(
        "--data-dir", default="data/sample",
        help="Directory containing PDF files (default: data/sample)",
    )
    parser.add_argument(
        "--max-steps", type=int, default=DEFAULT_MAX_STEPS,
        help=f"Max extraction attempts per table (default: {DEFAULT_MAX_STEPS})",
    )
    parser.add_argument(
        "--cost-cap", type=float, default=DEFAULT_COST_CAP_USD,
        help=f"Cost cap in USD (default: {DEFAULT_COST_CAP_USD})",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    docs = list_documents(args.data_dir)
    if not docs:
        logger.warning("No PDF files found in %s", args.data_dir)
        return

    logger.info("Found %d document(s) to process.", len(docs))

    results = []
    for doc in docs:
        result = run_agent(
            pdf_path=doc["path"],
            doc_id=doc["doc_id"],
            insurer=doc["insurer"],
            period=doc["period"],
            max_steps=args.max_steps,
            cost_cap_usd=args.cost_cap,
        )
        results.append(result)

    # Print summary
    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)
    for r in results:
        status = "✓" if r["outcome"] == "success" else "⚠" if r["outcome"] == "partial" else "✗"
        print(
            f"  {status} {r['insurer']} ({r['period']}): "
            f"{r['validated']} validated, {r['quarantined']} quarantined"
        )
    print("=" * 60)


if __name__ == "__main__":
    main()
