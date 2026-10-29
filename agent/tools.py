"""
Agent tools for PDF extraction and data management.

Each tool is a pure function that the agent loop can call.  Only two tools
(``write_clean`` and ``quarantine``) perform writes; all others are read-only.
Every invocation is logged via ``log_step``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import pdfplumber

from agent.schema import (
    ExtractionResult,
    ExtractionStrategy,
    KPIRow,
    RunLogEntry,
    ValidationStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory stores (swap for BigQuery in production)
# ---------------------------------------------------------------------------

_page_cache: dict[str, str] = {}       # (doc_id, page) -> text
_clean_store: list[dict] = []          # validated rows
_quarantine_store: list[dict] = []     # quarantined rows
_run_log: list[RunLogEntry] = []       # execution trace


def _cache_key(doc_id: str, page: int) -> str:
    return f"{doc_id}::{page}"


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------

def list_documents(data_dir: str = "data/sample") -> list[dict[str, str]]:
    """
    List available disclosure PDFs.

    Returns a list of dicts with keys: doc_id, filename, insurer, period.
    The insurer and period are inferred from the filename convention:
    ``<INSURER>_<PERIOD>.pdf``
    """
    docs = []
    data_path = Path(data_dir)

    if not data_path.exists():
        logger.warning("Data directory %s does not exist.", data_dir)
        return docs

    for pdf_file in sorted(data_path.glob("*.pdf")):
        stem = pdf_file.stem
        parts = stem.rsplit("_", maxsplit=1)
        insurer = parts[0].replace("_", " ") if len(parts) >= 1 else "Unknown"
        period = parts[1] if len(parts) >= 2 else "Unknown"
        doc_id = hashlib.md5(pdf_file.name.encode()).hexdigest()[:12]

        docs.append({
            "doc_id": doc_id,
            "filename": pdf_file.name,
            "insurer": insurer,
            "period": period,
            "path": str(pdf_file),
        })

    return docs


def read_page_text(doc_id: str, page: int, pdf_path: str) -> str:
    """
    Extract raw text from a single page.  Results are cached.

    Parameters
    ----------
    doc_id : str
        Document identifier.
    page : int
        1-based page number.
    pdf_path : str
        Filesystem path to the PDF.

    Returns
    -------
    str
        Page text.
    """
    key = _cache_key(doc_id, page)
    if key in _page_cache:
        logger.debug("Cache hit for %s", key)
        return _page_cache[key]

    with pdfplumber.open(pdf_path) as pdf:
        if page < 1 or page > len(pdf.pages):
            raise ValueError(
                f"Page {page} out of range (1–{len(pdf.pages)}) for {pdf_path}"
            )
        text = pdf.pages[page - 1].extract_text() or ""

    _page_cache[key] = text
    return text


def extract_tables(
    doc_id: str,
    page: int,
    pdf_path: str,
    strategy: ExtractionStrategy = ExtractionStrategy.RULED,
) -> list[list[list[Optional[str]]]]:
    """
    Extract raw table cells from a PDF page using ``pdfplumber``.

    Parameters
    ----------
    strategy : ExtractionStrategy
        ``ruled`` uses ruled-line detection; ``text_align`` uses text
        alignment heuristics; ``hybrid`` tries ruled first, then
        falls back to text_align.

    Returns
    -------
    list[list[list[str | None]]]
        A list of tables, each a list of rows, each a list of cell values.
    """
    settings_ruled = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
    }
    settings_text = {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
    }

    with pdfplumber.open(pdf_path) as pdf:
        if page < 1 or page > len(pdf.pages):
            raise ValueError(
                f"Page {page} out of range (1–{len(pdf.pages)}) for {pdf_path}"
            )
        pg = pdf.pages[page - 1]

        if strategy == ExtractionStrategy.RULED:
            settings = settings_ruled
        elif strategy == ExtractionStrategy.TEXT_ALIGN:
            settings = settings_text
        else:  # hybrid
            settings = settings_ruled

        tables = pg.extract_tables(settings) or []

        # Hybrid fallback
        if strategy == ExtractionStrategy.HYBRID and not tables:
            logger.info("Hybrid fallback to text_align for page %d", page)
            tables = pg.extract_tables(settings_text) or []

    return tables


# ---------------------------------------------------------------------------
# Write tools (only two — enforced by design)
# ---------------------------------------------------------------------------

def write_clean(rows: list[KPIRow]) -> int:
    """
    Write validated rows to the clean store (BigQuery in production).

    Only callable after reconciliation passes.  Sets each row's
    ``validation_status`` to ``validated``.

    Returns
    -------
    int
        Number of rows written.
    """
    for row in rows:
        row.validation_status = ValidationStatus.VALIDATED
        _clean_store.append(row.model_dump())

    logger.info("Wrote %d validated rows to clean store.", len(rows))
    return len(rows)


def quarantine(rows: list[KPIRow], reason: str) -> int:
    """
    Quarantine rows that failed reconciliation after retries.

    Preserves source document and page for human review.

    Returns
    -------
    int
        Number of rows quarantined.
    """
    for row in rows:
        row.validation_status = ValidationStatus.QUARANTINED
        row.quarantine_reason = reason
        _quarantine_store.append(row.model_dump())

    logger.warning(
        "Quarantined %d rows (reason: %s).", len(rows), reason
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Logging tool
# ---------------------------------------------------------------------------

def log_step(
    step_number: int,
    tool_name: str,
    tool_args: dict[str, Any],
    result_summary: str,
    tokens_used: int = 0,
    duration_seconds: float = 0.0,
) -> None:
    """Record one step in the agent execution trace."""
    entry = RunLogEntry(
        step_number=step_number,
        tool_name=tool_name,
        tool_args=tool_args,
        result_summary=result_summary,
        tokens_used=tokens_used,
        duration_seconds=duration_seconds,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    _run_log.append(entry)


# ---------------------------------------------------------------------------
# Store accessors (for evaluation and export)
# ---------------------------------------------------------------------------

def get_clean_rows() -> list[dict]:
    """Return all validated rows."""
    return list(_clean_store)


def get_quarantined_rows() -> list[dict]:
    """Return all quarantined rows."""
    return list(_quarantine_store)


def get_run_log() -> list[dict]:
    """Return the full execution trace."""
    return [entry.model_dump() for entry in _run_log]


def export_run_log(output_path: str = "eval/run_log.json") -> str:
    """Write the run log to a JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(get_run_log(), f, indent=2, default=str)
    return str(path)


def clear_stores() -> None:
    """Reset all in-memory stores (for testing)."""
    _page_cache.clear()
    _clean_store.clear()
    _quarantine_store.clear()
    _run_log.clear()
