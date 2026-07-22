"""TDD tests for issue #894: validate_weight_plan_required must guard start_date."""
import decimal
import pytest
from backend.models import validate_weight_plan_required


def test_missing_start_date_returns_none_with_reason():
    """validate_weight_plan_required returns (None, reason) when start_date is None."""
    result, reason = validate_weight_plan_required(
        start_date=None,
        start_weight_kg=decimal.Decimal("85.00"),
        goal_weight_kg=decimal.Decimal("80.00"),
    )
    assert result is None
    assert isinstance(reason, str) and "start_date" in reason


def test_missing_start_date_reason_is_descriptive():
    """The reason string specifically mentions start_date."""
    _, reason = validate_weight_plan_required(
        start_date=None,
        start_weight_kg=decimal.Decimal("85.00"),
        goal_weight_kg=decimal.Decimal("80.00"),
    )
    assert reason == "start_date is required"


def test_all_required_fields_present_returns_true():
    """validate_weight_plan_required returns (True, None) when all three required fields are present."""
    result, reason = validate_weight_plan_required(
        start_date="2026-01-01",
        start_weight_kg=decimal.Decimal("85.00"),
        goal_weight_kg=decimal.Decimal("80.00"),
    )
    assert result is True
    assert reason is None


def test_start_date_check_runs_after_weight_checks():
    """start_weight_kg missing is caught before start_date check (early exit order preserved)."""
    result, reason = validate_weight_plan_required(
        start_date=None,
        start_weight_kg=None,
        goal_weight_kg=decimal.Decimal("80.00"),
    )
    assert result is None
    assert "start_weight_kg" in reason


def test_start_date_checked_when_weights_are_valid():
    """start_date None is caught after weights pass validation."""
    result, reason = validate_weight_plan_required(
        start_date=None,
        start_weight_kg=decimal.Decimal("85.00"),
        goal_weight_kg=decimal.Decimal("80.00"),
    )
    assert result is None
    assert reason == "start_date is required"
