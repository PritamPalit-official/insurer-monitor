# Insurer Monitor — Validating Extraction Agent

> **Agentic AI** | LLM-driven extraction with deterministic reconciliation for Indian insurer disclosure PDFs

[![CI](https://github.com/PritamPalit-official/insurer-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/PritamPalit-official/insurer-monitor/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## The Project in One Paragraph

An LLM-driven loop reads insurer disclosure PDFs, extracts tables into a **strict Pydantic schema**, checks them with **deterministic reconciliation tools** (sum, range, unit, cross-period, completeness), retries or quarantines failures, and only then lets validated rows into the BigQuery warehouse that feeds the Power BI dashboard. A second step writes commentary from validated numbers, and a **number-grounding validator** rejects any cited figure not present in the source data.

> **On "agentic"**: This earns the label only where the model *chooses* among tools and retry strategies based on what failed. The evaluation includes a fixed-pipeline baseline (E1) to prove the agent adds value beyond a simple script.

---

## Architecture

```
PDF disclosure
   │
   ▼
[ Agent loop: plan → call tool → observe → decide ]
   ├── read_page_text / extract_tables      (pdfplumber)
   ├── propose_rows                         (LLM, strict schema)
   ├── reconcile                            (deterministic Python checks)
   │        pass → write_clean → BigQuery   (validation_status = validated)
   │        fail → retry (alternate strategy / re-read failing rows)
   │                 still fails → quarantine (with reason)
   ▼
Validated KPIs → commentary (LLM) → number validator → report
                                      fail → regenerate → flag for review
```

### Tools the Agent Can Call

| Tool | Input | Output | Notes |
|------|-------|--------|-------|
| `list_documents` | none | doc IDs, insurer, period | Read-only |
| `read_page_text` | doc_id, page | page text | **Cached** |
| `extract_tables` | doc_id, page, strategy | raw table cells | Strategies: ruled, text_align, hybrid |
| `propose_rows` | raw table, schema | rows as JSON | Validated with Pydantic |
| `reconcile` | rows | pass/fail + details | **Deterministic**, no LLM |
| `write_clean` | rows | row count | Only after reconcile passes |
| `quarantine` | rows, reason | row count | Preserves source for review |
| `log_step` | step details | none | Every call is logged |

> **Only two tools can write** (`write_clean`, `quarantine`). Everything else is read-only.

---

## Reconciliation Checks (Core of the Project)

| Check | Example | Catches |
|-------|---------|---------|
| **Sum check** | Components add up to the reported total (±0.5) | Misaligned columns, missed rows |
| **Range check** | Ratios in [0, 100]; values within plausible bands | Decimal and unit errors |
| **Unit check** | All monetary amounts normalised to one unit | Mixed lakhs/crores |
| **Cross-period** | Same prior-period figure agrees across reports | Wrong period, stale numbers |
| **Completeness** | Expected rows and columns are present | Dropped rows |

---

## Guardrails

- ⏱️ **Step cap**: Max 5 extraction attempts per table
- 💰 **Cost cap**: Configurable per-run spending limit
- 🔒 **Strict schema**: Unknown values → `null` with mandatory `reason` (never a guess)
- ✍️ **Write restriction**: Only `write_clean` and `quarantine` can write
- 📝 **Run log**: Every tool call logged with arguments, result, tokens, and duration
- 🔍 **Commentary isolation**: The commentary step never sees raw PDF text

---

## Commentary & Number Validator

```python
def validate_commentary(text, kpi_json, tol=0.005):
    cited = extract_numbers(text)        # numbers from the commentary
    allowed = collect_numbers(kpi_json)   # values from validated data
    unsupported = [n for n in cited
                   if not any(abs(n - a) <= tol * max(1, abs(a)) for a in allowed)]
    return len(unsupported) == 0, unsupported
```

If validation fails → regenerate once → flag for human review.

---

## Evaluation Plan

| Experiment | Compare | Measure |
|-----------|---------|---------|
| **E1. Baseline vs. Agent** | Single-shot LLM; fixed pipeline; full agent | Cell accuracy, table pass rate (24+ gold-labelled cells) |
| **E2. Error Injection** | ~30 corrupted values (digit swaps, wrong units) | Reconciliation catch rate; false alarms |
| **E3. Value of Retries** | Tables failed on first pass | Recovery rate vs. quarantined |
| **E4. Cost & Speed** | Per table and per document | Tokens, seconds, USD cost |
| **E5. Commentary Grounding** | 20 runs + manual review | Validator pass rate; unsupported claims |

> See [`eval/results.md`](eval/results.md) for measured results (fill in after running).

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/PritamPalit-official/insurer-monitor.git
cd insurer-monitor
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY or OPENAI_API_KEY
```

### 3. Add Sample PDFs

Place insurer disclosure PDFs in `data/sample/`:
```
data/sample/HDFC_ERGO_Q2_FY2024.pdf
data/sample/ICICI_Lombard_Q2_FY2024.pdf
```

### 4. Run the Agent

```bash
python -m agent.loop --data-dir data/sample --verbose
```

### 5. Run Tests

```bash
python -m pytest checks/tests/ -v
```

---

## Project Structure

```
insurer-monitor/
├── agent/                  # Core extraction agent
│   ├── loop.py             # Agent loop (plan → tool → observe → decide)
│   ├── tools.py            # Tool implementations (read/write/log)
│   ├── schema.py           # Pydantic schemas (KPIRow, NullableValue)
│   └── prompts.py          # LLM prompt templates
├── checks/                 # Deterministic validation
│   ├── reconcile.py        # Sum, range, unit, cross-period, completeness
│   └── tests/              # Pytest suite (28 tests)
│       ├── test_reconcile.py
│       ├── test_schema.py
│       └── conftest.py
├── commentary/             # LLM-generated insights
│   ├── generate.py         # Commentary from validated KPIs
│   └── validate.py         # Number-grounding validator
├── sql/                    # BigQuery warehouse
│   ├── schema.sql          # Table definitions (partitioned, clustered)
│   └── views.sql           # Analytical views for Power BI
├── eval/                   # Evaluation framework
│   ├── gold_labels.csv     # Hand-labelled test data (24 cells, 3 insurers)
│   ├── run_eval.py         # E1–E5 experiment runner
│   └── results.md          # Measured results (fill after running)
├── docs/
│   └── DECISIONS.md        # 8 design decisions with alternatives & reasoning
├── data/sample/            # Sample disclosure PDFs (not committed)
├── .github/workflows/ci.yml
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── LICENSE
└── README.md
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| PDF Extraction | `pdfplumber` | Handles digitally-generated Indian insurer PDFs (no OCR needed) |
| Schema Validation | `pydantic` v2 | Strict types, null-with-reason enforcement |
| LLM | Google Gemini / OpenAI | Structured JSON output for ambiguous tables |
| Reconciliation | Pure Python | Deterministic, testable, no LLM dependency |
| Warehouse | BigQuery | Partitioned by date, clustered by insurer & period |
| Dashboard | Power BI | Consumes BigQuery views (companion project) |
| CI/CD | GitHub Actions | Pytest across Python 3.10–3.12 |

---

## Design Decisions

See [`docs/DECISIONS.md`](docs/DECISIONS.md) for detailed reasoning on:

1. **One agent, not multi-agent** — simpler, faster, easier to debug
2. **Deterministic reconciliation** — math checks don't need an LLM
3. **Null with reason** — prevents silent value drops
4. **Two write tools only** — guardrail against uncontrolled side effects
5. **pdfplumber over OCR** — Indian disclosures are digitally generated
6. **Page text caching** — avoids redundant I/O on retries
7. **0.5% commentary tolerance** — catches hallucination, allows rounding
8. **BigQuery target** — aligns with fintech JD requirements

---

## License

MIT — see [LICENSE](LICENSE).

---

*Built by [Pritam Palit](https://github.com/PritamPalit-official) as a portfolio project for Data Analyst / MIS Analyst / Business Analyst roles.*
