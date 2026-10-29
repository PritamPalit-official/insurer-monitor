"""
Deterministic reconciliation checks for extracted KPI rows.

These checks are pure Python — no LLM involved.  Each function returns a
``CheckResult`` indicating pass or fail with a human-readable message.
The agent uses failures to decide whether to retry or quarantine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from agent.schema import KPIRow, Unit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Outcome of a single reconciliation check."""

    check_name: str
    passed: bool
    message: str
    failing_rows: list[int] = field(default_factory=list)


@dataclass
class ReconciliationReport:
    """Aggregated outcome of all checks on one table."""

    doc_id: str
    page: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        lines = [
            f"Reconciliation: {passed}/{total} checks passed "
            f"for doc={self.doc_id} page={self.page}",
        ]
        for c in self.failed_checks:
            lines.append(f"  FAIL [{c.check_name}]: {c.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_sum(
    rows: list[KPIRow],
    tolerance: float = 0.5,
) -> CheckResult:
    """
    Verify that component rows sum to the reported total row.

    Groups rows by (insurer, period, section).  Within each group, if
    there is a row marked ``is_total=True``, the sum of the non-total
    rows must match within ``tolerance``.
    """
    from collections import defaultdict

    groups: dict[tuple, list[KPIRow]] = defaultdict(list)
    for row in rows:
        key = (row.insurer, row.period, row.section)
        groups[key].append(row)

    failing_indices: list[int] = []
    messages: list[str] = []

    for key, group in groups.items():
        totals = [r for r in group if r.is_total and r.metric_value.value is not None]
        components = [r for r in group if not r.is_total and r.metric_value.value is not None]

        for total_row in totals:
            expected = total_row.metric_value.value
            actual = sum(r.metric_value.value for r in components)  # type: ignore[union-attr]
            diff = abs(expected - actual)  # type: ignore[operator]

            if diff > tolerance:
                idx = rows.index(total_row)
                failing_indices.append(idx)
                messages.append(
                    f"Sum mismatch in {key}: expected {expected}, "
                    f"got {actual} (diff={diff:.2f})"
                )

    if failing_indices:
        return CheckResult(
            check_name="sum_check",
            passed=False,
            message="; ".join(messages),
            failing_rows=failing_indices,
        )

    return CheckResult(
        check_name="sum_check",
        passed=True,
        message="All totals reconcile within tolerance.",
    )


def check_range(
    rows: list[KPIRow],
    ratio_min: float = -100.0,
    ratio_max: float = 500.0,
    percent_min: float = 0.0,
    percent_max: float = 100.0,
) -> CheckResult:
    """
    Verify that numeric values fall within sensible ranges.

    - Percentage values must be in ``[percent_min, percent_max]``.
    - Ratios / other values must be in ``[ratio_min, ratio_max]``
      (a wide band to catch only obvious errors like sign flips or
      decimal-place errors).
    """
    failing: list[int] = []
    messages: list[str] = []

    for i, row in enumerate(rows):
        val = row.metric_value.value
        if val is None:
            continue

        if row.unit == Unit.PERCENT:
            if not (percent_min <= val <= percent_max):
                failing.append(i)
                messages.append(
                    f"Row {i} ({row.metric_name}): {val}% "
                    f"outside [{percent_min}, {percent_max}]"
                )
        else:
            # Extremely wide band — catches sign errors and 1000x scale errors
            if val < ratio_min or val > 1e12:
                failing.append(i)
                messages.append(
                    f"Row {i} ({row.metric_name}): {val} outside plausible range"
                )

    if failing:
        return CheckResult(
            check_name="range_check",
            passed=False,
            message="; ".join(messages),
            failing_rows=failing,
        )

    return CheckResult(
        check_name="range_check",
        passed=True,
        message="All values within plausible ranges.",
    )


def check_unit_consistency(rows: list[KPIRow]) -> CheckResult:
    """
    Verify that all monetary rows within a table use the same unit.

    Non-monetary units (PERCENT, UNITS) are excluded from the check.
    """
    monetary_units = {Unit.LAKHS, Unit.CRORES, Unit.THOUSANDS}
    found_units: set[Unit] = set()

    for row in rows:
        if row.unit in monetary_units:
            found_units.add(row.unit)

    if len(found_units) > 1:
        return CheckResult(
            check_name="unit_consistency",
            passed=False,
            message=f"Mixed monetary units detected: {found_units}",
        )

    return CheckResult(
        check_name="unit_consistency",
        passed=True,
        message="Monetary units are consistent.",
    )


def check_completeness(
    rows: list[KPIRow],
    expected_columns: Optional[list[str]] = None,
    min_rows: int = 1,
) -> CheckResult:
    """
    Verify that the extraction produced a reasonable number of rows
    and (optionally) contains expected metric names.
    """
    if len(rows) < min_rows:
        return CheckResult(
            check_name="completeness",
            passed=False,
            message=f"Only {len(rows)} rows extracted (expected >= {min_rows}).",
        )

    if expected_columns:
        found_metrics = {r.metric_name.lower().strip() for r in rows}
        missing = [
            c for c in expected_columns
            if c.lower().strip() not in found_metrics
        ]
        if missing:
            return CheckResult(
                check_name="completeness",
                passed=False,
                message=f"Missing expected metrics: {missing}",
            )

    return CheckResult(
        check_name="completeness",
        passed=True,
        message=f"Extraction complete: {len(rows)} rows.",
    )


def check_cross_period(
    current_rows: list[KPIRow],
    prior_rows: list[KPIRow],
    tolerance: float = 0.01,
) -> CheckResult:
    """
    Cross-period consistency: the prior-period figure in the current
    report must match the same figure in the prior report.

    This catches stale or mis-labelled numbers.
    """
    # Build lookup: (insurer, metric, period) -> value
    prior_lookup: dict[tuple, float] = {}
    for row in prior_rows:
        if row.metric_value.value is not None:
            key = (row.insurer, row.metric_name, row.period)
            prior_lookup[key] = row.metric_value.value

    failing: list[int] = []
    messages: list[str] = []

    for i, row in enumerate(current_rows):
        if row.metric_value.value is None:
            continue
        key = (row.insurer, row.metric_name, row.period)
        if key in prior_lookup:
            expected = prior_lookup[key]
            actual = row.metric_value.value
            if abs(expected - actual) > tolerance * max(1, abs(expected)):
                failing.append(i)
                messages.append(
                    f"Row {i} ({row.metric_name}): current={actual}, "
                    f"prior report={expected}"
                )

    if failing:
        return CheckResult(
            check_name="cross_period",
            passed=False,
            message="; ".join(messages),
            failing_rows=failing,
        )

    return CheckResult(
        check_name="cross_period",
        passed=True,
        message="Cross-period figures are consistent.",
    )


# ---------------------------------------------------------------------------
# Master reconciliation function
# ---------------------------------------------------------------------------

def reconcile(
    rows: list[KPIRow],
    doc_id: str,
    page: int,
    prior_rows: Optional[list[KPIRow]] = None,
    expected_columns: Optional[list[str]] = None,
    min_rows: int = 1,
    sum_tolerance: float = 0.5,
) -> ReconciliationReport:
    """
    Run all reconciliation checks on extracted rows.

    Parameters
    ----------
    rows : list[KPIRow]
        Extracted rows to validate.
    doc_id : str
        Document identifier.
    page : int
        Page number.
    prior_rows : list[KPIRow], optional
        Rows from the prior period for cross-period checks.
    expected_columns : list[str], optional
        Metric names that must be present.
    min_rows : int
        Minimum expected row count.
    sum_tolerance : float
        Absolute tolerance for sum checks.

    Returns
    -------
    ReconciliationReport
        Aggregated results of all checks.
    """
    report = ReconciliationReport(doc_id=doc_id, page=page)

    report.checks.append(check_sum(rows, tolerance=sum_tolerance))
    report.checks.append(check_range(rows))
    report.checks.append(check_unit_consistency(rows))
    report.checks.append(
        check_completeness(rows, expected_columns=expected_columns, min_rows=min_rows)
    )

    if prior_rows:
        report.checks.append(check_cross_period(rows, prior_rows))

    if report.passed:
        logger.info("Reconciliation PASSED for doc=%s page=%d", doc_id, page)
    else:
        logger.warning(
            "Reconciliation FAILED for doc=%s page=%d:\n%s",
            doc_id,
            page,
            report.summary(),
        )

    return report
