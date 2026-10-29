# Design Decisions

This document records key design decisions, the alternatives considered,
and the reasoning behind each choice.

---

## D1: One Agent, Not Multi-Agent

**Decision**: Use a single agent loop, not a multi-agent framework.

**Alternatives considered**:
- CrewAI with separate extractor, validator, and reporter agents
- AutoGen with conversational agent coordination
- LangGraph with a state machine

**Reasoning**: The task has a clear linear pipeline (extract → validate →
write/quarantine → comment). Adding inter-agent communication overhead
produces no benefit. A single loop with tool calls is simpler to debug,
test, and explain in interviews. The plan explicitly warns against scope
creep here.

---

## D2: Deterministic Reconciliation Over LLM Validation

**Decision**: All reconciliation checks are pure Python — no LLM involved.

**Alternatives considered**:
- LLM-based validation ("does this look right?")
- Hybrid: LLM for ambiguous cases, deterministic for sums

**Reasoning**: Sum checks, range checks, and unit consistency are
mathematical facts. Delegating them to an LLM would add latency, cost,
and non-determinism with zero accuracy benefit. The LLM is used only where
human judgment is genuinely needed: parsing ambiguous table layouts and
writing commentary.

---

## D3: Null with Reason, Never a Guess

**Decision**: The `NullableValue` schema requires a `null_reason` whenever
the value is `None`.

**Alternatives considered**:
- Allow silent nulls
- Use a sentinel value like -999

**Reasoning**: In financial data, a missing value and a zero are very
different. Forcing a reason prevents the LLM from silently dropping
difficult values, and gives downstream consumers (and human reviewers)
the context to decide what to do.

---

## D4: Only Two Write Tools

**Decision**: Only `write_clean` and `quarantine` can write data. All
other tools are read-only.

**Reasoning**: This is a guardrail against uncontrolled side effects.
The agent can read pages and extract tables freely, but committing data
to the warehouse requires passing reconciliation first. The commentary
step never sees raw document text — it works only with validated JSON.

---

## D5: pdfplumber Over OCR

**Decision**: Use `pdfplumber` for table extraction, not Tesseract/OCR.

**Alternatives considered**:
- Tesseract + heuristic table reconstruction
- AWS Textract / Google Document AI
- Camelot

**Reasoning**: Indian insurer public disclosures (IRDAI quarterly forms)
are typically digitally generated PDFs with embedded text — not scanned
images. `pdfplumber` handles these well. If a source turns out to be
scanned, the Day 1-2 feasibility gate catches this before any code is
written.

---

## D6: Cache Page Text

**Decision**: Cache `read_page_text` results in memory to avoid re-reading
PDFs on retries.

**Reasoning**: The agent may re-read the same page when retrying with a
different strategy. Caching avoids redundant I/O and keeps token costs
predictable. In production, this cache would be Redis or a temp table.

---

## D7: Commentary Validator Tolerance

**Decision**: Use a relative tolerance of 0.5% for matching cited numbers
against source data.

**Reasoning**: LLMs sometimes round numbers slightly differently. A
tolerance of 0.5% catches hallucinated values while allowing minor
rounding differences. The tolerance was tuned by testing on deliberately
wrong sentences.

---

## D8: BigQuery as the Target Warehouse

**Decision**: Target BigQuery, not a local database.

**Alternatives considered**:
- SQLite for simplicity
- PostgreSQL

**Reasoning**: BigQuery aligns with the JD requirements for the target
roles (Razorpay, fintech analytics). The SQL schema and views are
designed for BigQuery syntax. For local development, the agent uses
in-memory Python lists with the same schema.
