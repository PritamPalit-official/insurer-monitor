"""
Test suite for Pydantic schemas and the commentary validator.
"""

from __future__ import annotations

import pytest

from agent.schema import KPIRow, NullableValue, Unit, ValidationStatus
from commentary.validate import (
    collect_numbers,
    extract_numbers,
    validate_commentary,
)


# ---------------------------------------------------------------------------
# NullableValue tests
# ---------------------------------------------------------------------------

class TestNullableValue:
    def test_valid_value(self):
        nv = NullableValue(value=42.0)
        assert nv.value == 42.0
        assert nv.null_reason is None

    def test_null_with_reason(self):
        nv = NullableValue(value=None, null_reason="Value obscured by watermark")
        assert nv.value is None
        assert nv.null_reason == "Value obscured by watermark"

    def test_null_without_reason_raises(self):
        with pytest.raises(ValueError, match="null_reason is required"):
            NullableValue(value=None)


# ---------------------------------------------------------------------------
# extract_numbers tests
# ---------------------------------------------------------------------------

class TestExtractNumbers:
    def test_extracts_integers(self):
        nums = extract_numbers("The premium was 1500 crores.")
        assert 1500.0 in nums

    def test_extracts_decimals(self):
        nums = extract_numbers("Growth rate was 12.5% year-over-year.")
        assert 12.5 in nums

    def test_extracts_negative_numbers(self):
        nums = extract_numbers("The change was -3.2 crores.")
        assert -3.2 in nums

    def test_extracts_comma_separated(self):
        nums = extract_numbers("Revenue of 1,234.56 lakhs.")
        assert 1234.56 in nums

    def test_ignores_years(self):
        nums = extract_numbers("In FY2024, premium was 500 crores.")
        assert 500.0 in nums
        assert 2024.0 not in nums

    def test_ignores_period_labels(self):
        nums = extract_numbers("Q2 FY2024 results show 100 crores.")
        assert 100.0 in nums


# ---------------------------------------------------------------------------
# validate_commentary tests
# ---------------------------------------------------------------------------

class TestValidateCommentary:
    def test_passes_when_all_numbers_grounded(self):
        text = "Premium increased to 500 crores from 400 crores."
        kpi = [
            {"metric_value": {"value": 500.0}},
            {"metric_value": {"value": 400.0}},
        ]
        passed, unsupported = validate_commentary(text, kpi)
        assert passed is True
        assert unsupported == []

    def test_fails_on_hallucinated_number(self):
        text = "Premium reached 999 crores, a record high."
        kpi = [
            {"metric_value": {"value": 500.0}},
        ]
        passed, unsupported = validate_commentary(text, kpi)
        assert passed is False
        assert 999.0 in unsupported

    def test_passes_with_tolerance(self):
        text = "Premium was approximately 500.2 crores."
        kpi = [
            {"metric_value": {"value": 500.0}},
        ]
        passed, _ = validate_commentary(text, kpi, tol=0.005)
        assert passed is True

    def test_passes_with_no_numbers(self):
        text = "The insurer showed steady performance."
        kpi = [{"metric_value": {"value": 100.0}}]
        passed, _ = validate_commentary(text, kpi)
        assert passed is True

    def test_validates_against_changes(self):
        text = "Growth was 25.0 percent, from 400 to 500."
        kpi = [
            {"metric_value": {"value": 500.0}, "absolute_change": 100.0,
             "percent_change": 25.0, "prior_value": 400.0,
             "current_value": 500.0},
        ]
        passed, _ = validate_commentary(text, kpi)
        assert passed is True
