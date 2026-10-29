"""
Test suite for reconciliation checks.

Covers all five check types with passing and failing scenarios.
These tests are deterministic — no LLM or PDF required.
"""

from __future__ import annotations

import pytest

from agent.schema import KPIRow, NullableValue, Unit
from checks.reconcile import (
    CheckResult,
    check_completeness,
    check_cross_period,
    check_range,
    check_sum,
    check_unit_consistency,
    reconcile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_row(
    metric: str = "Premium",
    value: float | None = 100.0,
    unit: Unit = Unit.CRORES,
    is_total: bool = False,
    insurer: str = "HDFC ERGO",
    period: str = "Q2 FY2024",
    section: str = "NL-1",
    null_reason: str | None = None,
) -> KPIRow:
    """Helper to create a KPIRow for testing."""
    if value is None and null_reason is None:
        null_reason = "Test null"
    return KPIRow(
        insurer=insurer,
        period=period,
        section=section,
        metric_name=metric,
        metric_value=NullableValue(value=value, null_reason=null_reason),
        unit=unit,
        is_total=is_total,
        source_doc_id="test_doc",
        source_page=1,
    )


# ---------------------------------------------------------------------------
# Sum check tests
# ---------------------------------------------------------------------------

class TestSumCheck:
    def test_sum_passes_when_components_match_total(self):
        rows = [
            _make_row(metric="Fire", value=40.0),
            _make_row(metric="Marine", value=60.0),
            _make_row(metric="Total", value=100.0, is_total=True),
        ]
        result = check_sum(rows)
        assert result.passed is True

    def test_sum_passes_within_tolerance(self):
        rows = [
            _make_row(metric="Fire", value=40.0),
            _make_row(metric="Marine", value=60.2),
            _make_row(metric="Total", value=100.0, is_total=True),
        ]
        result = check_sum(rows, tolerance=0.5)
        assert result.passed is True

    def test_sum_fails_outside_tolerance(self):
        rows = [
            _make_row(metric="Fire", value=40.0),
            _make_row(metric="Marine", value=55.0),
            _make_row(metric="Total", value=100.0, is_total=True),
        ]
        result = check_sum(rows, tolerance=0.5)
        assert result.passed is False
        assert "Sum mismatch" in result.message

    def test_sum_skips_null_values(self):
        rows = [
            _make_row(metric="Fire", value=40.0),
            _make_row(metric="Marine", value=None, null_reason="Unreadable"),
            _make_row(metric="Total", value=40.0, is_total=True),
        ]
        result = check_sum(rows)
        assert result.passed is True

    def test_sum_passes_with_no_total_row(self):
        rows = [
            _make_row(metric="Fire", value=40.0),
            _make_row(metric="Marine", value=60.0),
        ]
        result = check_sum(rows)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Range check tests
# ---------------------------------------------------------------------------

class TestRangeCheck:
    def test_range_passes_normal_values(self):
        rows = [
            _make_row(value=100.0),
            _make_row(value=5000.0),
        ]
        result = check_range(rows)
        assert result.passed is True

    def test_range_fails_negative_value(self):
        rows = [
            _make_row(value=-200.0),
        ]
        result = check_range(rows, ratio_min=0.0)
        assert result.passed is False

    def test_range_fails_percentage_over_100(self):
        rows = [
            _make_row(value=150.0, unit=Unit.PERCENT),
        ]
        result = check_range(rows)
        assert result.passed is False
        assert "outside" in result.message

    def test_range_passes_valid_percentage(self):
        rows = [
            _make_row(value=65.5, unit=Unit.PERCENT),
        ]
        result = check_range(rows)
        assert result.passed is True

    def test_range_skips_null_values(self):
        rows = [
            _make_row(value=None, null_reason="Missing"),
        ]
        result = check_range(rows)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Unit consistency tests
# ---------------------------------------------------------------------------

class TestUnitConsistency:
    def test_consistent_units_pass(self):
        rows = [
            _make_row(unit=Unit.CRORES),
            _make_row(unit=Unit.CRORES),
        ]
        result = check_unit_consistency(rows)
        assert result.passed is True

    def test_mixed_monetary_units_fail(self):
        rows = [
            _make_row(unit=Unit.CRORES),
            _make_row(unit=Unit.LAKHS),
        ]
        result = check_unit_consistency(rows)
        assert result.passed is False
        assert "Mixed" in result.message

    def test_non_monetary_units_ignored(self):
        rows = [
            _make_row(unit=Unit.CRORES),
            _make_row(unit=Unit.PERCENT),
            _make_row(unit=Unit.UNITS),
        ]
        result = check_unit_consistency(rows)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Completeness tests
# ---------------------------------------------------------------------------

class TestCompleteness:
    def test_enough_rows_pass(self):
        rows = [_make_row() for _ in range(5)]
        result = check_completeness(rows, min_rows=3)
        assert result.passed is True

    def test_too_few_rows_fail(self):
        rows = [_make_row()]
        result = check_completeness(rows, min_rows=5)
        assert result.passed is False

    def test_expected_columns_present(self):
        rows = [
            _make_row(metric="Premium"),
            _make_row(metric="Claims"),
        ]
        result = check_completeness(rows, expected_columns=["Premium", "Claims"])
        assert result.passed is True

    def test_expected_columns_missing(self):
        rows = [
            _make_row(metric="Premium"),
        ]
        result = check_completeness(rows, expected_columns=["Premium", "Claims"])
        assert result.passed is False
        assert "Claims" in result.message


# ---------------------------------------------------------------------------
# Cross-period check tests
# ---------------------------------------------------------------------------

class TestCrossPeriod:
    def test_matching_prior_period_passes(self):
        current = [_make_row(metric="Premium", value=100.0, period="Q2 FY2024")]
        prior = [_make_row(metric="Premium", value=100.0, period="Q2 FY2024")]
        result = check_cross_period(current, prior)
        assert result.passed is True

    def test_mismatched_prior_period_fails(self):
        current = [_make_row(metric="Premium", value=100.0, period="Q2 FY2024")]
        prior = [_make_row(metric="Premium", value=200.0, period="Q2 FY2024")]
        result = check_cross_period(current, prior)
        assert result.passed is False

    def test_no_overlap_passes(self):
        current = [_make_row(metric="Premium", value=100.0, period="Q2 FY2024")]
        prior = [_make_row(metric="Claims", value=200.0, period="Q1 FY2024")]
        result = check_cross_period(current, prior)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Full reconciliation tests
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_full_reconcile_passes_clean_data(self):
        rows = [
            _make_row(metric="Fire", value=40.0),
            _make_row(metric="Marine", value=60.0),
            _make_row(metric="Total", value=100.0, is_total=True),
        ]
        report = reconcile(rows, doc_id="test", page=1)
        assert report.passed is True

    def test_full_reconcile_catches_sum_error(self):
        rows = [
            _make_row(metric="Fire", value=40.0),
            _make_row(metric="Marine", value=50.0),
            _make_row(metric="Total", value=100.0, is_total=True),
        ]
        report = reconcile(rows, doc_id="test", page=1)
        assert report.passed is False
        assert any(c.check_name == "sum_check" for c in report.failed_checks)

    def test_reconcile_summary_format(self):
        rows = [_make_row(metric="Premium", value=100.0)]
        report = reconcile(rows, doc_id="test", page=1)
        summary = report.summary()
        assert "Reconciliation" in summary
        assert "test" in summary
