# Evaluation Results

> **Note**: These results are from the initial evaluation run.
> Small-sample caveats apply — see the gold label set size below.

## E1: Baseline vs. Agent

| Method | Cell Accuracy | Table Pass Rate |
|--------|--------------|-----------------|
| Single-shot LLM | [measure] | [measure] |
| Fixed pipeline (no retry) | [measure] | [measure] |
| **Full agent (with retries)** | **[measure]** | **[measure]** |

- **Gold set size**: 24 cells across 3 insurers, 6 pages
- **Held-out tables**: 3 (reported separately after final run)

## E2: Error Injection

- **Errors injected**: ~30 (digit swaps, wrong units, dropped rows)
- **Caught by reconciliation**: [measure]
- **False alarms on clean tables**: [measure]

## E3: Value of Retries

- **Tables failed first pass**: [measure]
- **Recovered by retries**: [measure]
- **Quarantined (unrecoverable)**: [measure]

## E4: Cost and Speed

| Metric | Per Table | Per Document |
|--------|-----------|--------------|
| Tokens | [measure] | [measure] |
| Seconds | [measure] | [measure] |
| Cost (USD) | [measure] | [measure] |

## E5: Commentary Grounding

- **Validator pass rate**: [measure] (out of 20 runs)
- **Unsupported claims (manual review)**: [measure]

## Failure Examples

These show real errors and what was changed — included to demonstrate engineering judgment.

| # | Table | Issue | Resolution |
|---|-------|-------|------------|
| 1 | *Fill after measuring* | | |
| 2 | | | |
| 3 | | | |

---

*All values in brackets must come from actual measurement. Do not claim accuracy beyond the test set.*
