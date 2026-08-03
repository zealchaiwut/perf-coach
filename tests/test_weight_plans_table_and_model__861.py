"""Tests for issue #861: Add weight_plans table — migration and SQLAlchemy model."""
import decimal
from backend.models import WeightPlan, validate_weight_plan_required


# --- ORM model attribute tests ---

def test_weight_plan_has_all_columns():
    """WeightPlan model has all required columns from the AC."""
    for attr in (
        "id", "user_id", "start_date", "start_weight_kg", "goal_weight_kg",
        "goal_date", "target_rate_kg_per_week", "phase", "active",
        "created_at", "updated_at",
    ):
        assert hasattr(WeightPlan, attr), f"WeightPlan missing attribute: {attr}"


def test_weight_plan_tablename():
    """WeightPlan maps to the weight_plans table."""
    assert WeightPlan.__tablename__ == "weight_plans"


def test_weight_plan_numeric_columns_use_numeric_type():
    """All numeric columns use Numeric (not Float) to avoid precision loss."""
    from sqlalchemy import Numeric
    numeric_cols = ("start_weight_kg", "goal_weight_kg", "target_rate_kg_per_week")
    for col_name in numeric_cols:
        col = WeightPlan.__table__.c[col_name]
        assert isinstance(col.type, Numeric), (
            f"{col_name} must use Numeric, got {type(col.type).__name__}"
        )


def test_weight_plan_nullable_columns():
    """goal_date and target_rate_kg_per_week are nullable."""
    assert WeightPlan.__table__.c["goal_date"].nullable is True
    assert WeightPlan.__table__.c["target_rate_kg_per_week"].nullable is True


def test_weight_plan_required_columns_not_nullable():
    """start_date, start_weight_kg, goal_weight_kg are not nullable."""
    for col_name in ("start_date", "start_weight_kg", "goal_weight_kg"):
        assert WeightPlan.__table__.c[col_name].nullable is False, (
            f"{col_name} should be NOT NULL"
        )


def test_weight_plan_phase_default():
    """phase column has a server default of 'cut' and is not nullable."""
    col = WeightPlan.__table__.c["phase"]
    assert col.nullable is False
    # server_default text should include 'cut'
    assert "cut" in str(col.server_default.arg)


def test_weight_plan_active_default():
    """active column has a server default of true and is not nullable."""
    col = WeightPlan.__table__.c["active"]
    assert col.nullable is False
    assert "true" in str(col.server_default.arg).lower()


def test_weight_plan_user_id_has_foreign_key():
    """user_id has a foreign key to users table."""
    fks = list(WeightPlan.__table__.c["user_id"].foreign_keys)
    assert len(fks) == 1
    fk = next(iter(fks))
    assert fk.column.table.name == "users"


def test_weight_plan_has_user_id_index():
    """weight_plans table has an index on user_id."""
    indexes = WeightPlan.__table__.indexes
    indexed_cols = [
        frozenset(c.name for c in idx.columns)
        for idx in indexes
    ]
    assert frozenset(["user_id"]) in indexed_cols or any(
        "user_id" in cols for cols in indexed_cols
    ), "Expected an index covering user_id"


def test_weight_plan_instantiation_with_required_fields():
    """WeightPlan can be instantiated with required fields without error."""
    plan = WeightPlan(
        user_id="00000000-0000-0000-0000-000000000001",
        start_date="2026-01-01",
        start_weight_kg=decimal.Decimal("85.00"),
        goal_weight_kg=decimal.Decimal("80.00"),
    )
    assert plan.start_weight_kg == decimal.Decimal("85.00")
    assert plan.goal_weight_kg == decimal.Decimal("80.00")


def test_weight_plan_optional_fields_accept_none():
    """WeightPlan instantiation with nullable fields set to None does not raise."""
    plan = WeightPlan(
        user_id="00000000-0000-0000-0000-000000000002",
        start_date="2026-01-01",
        start_weight_kg=decimal.Decimal("90.00"),
        goal_weight_kg=decimal.Decimal("85.00"),
        goal_date=None,
        target_rate_kg_per_week=None,
    )
    assert plan.goal_date is None
    assert plan.target_rate_kg_per_week is None


def test_weight_plan_phase_bulk_and_active_false():
    """WeightPlan accepts phase='bulk' and active=False."""
    plan = WeightPlan(
        user_id="00000000-0000-0000-0000-000000000003",
        start_date="2026-02-01",
        start_weight_kg=decimal.Decimal("75.00"),
        goal_weight_kg=decimal.Decimal("80.00"),
        phase="bulk",
        active=False,
    )
    assert plan.phase == "bulk"
    assert plan.active is False


# --- validate_weight_plan_required helper tests (AC: missing required -> (None, reason)) ---

def test_validate_missing_start_weight_returns_none_with_reason():
    """validate_weight_plan_required returns (None, reason) when start_weight_kg is None."""
    result, reason = validate_weight_plan_required(
        start_weight_kg=None,
        goal_weight_kg=decimal.Decimal("80.00"),
        start_date="2026-01-01",
    )
    assert result is None
    assert isinstance(reason, str) and len(reason) > 0


def test_validate_missing_goal_weight_returns_none_with_reason():
    """validate_weight_plan_required returns (None, reason) when goal_weight_kg is None."""
    result, reason = validate_weight_plan_required(
        start_weight_kg=decimal.Decimal("85.00"),
        goal_weight_kg=None,
        start_date="2026-01-01",
    )
    assert result is None
    assert isinstance(reason, str) and len(reason) > 0


def test_validate_all_required_present_returns_true():
    """validate_weight_plan_required returns (True, None) when all required fields present."""
    result, reason = validate_weight_plan_required(
        start_weight_kg=decimal.Decimal("85.00"),
        goal_weight_kg=decimal.Decimal("80.00"),
        start_date="2026-01-01",
    )
    assert result is True
    assert reason is None


def test_validate_both_missing_returns_none_with_reason():
    """validate_weight_plan_required returns (None, reason) when both required are None."""
    result, reason = validate_weight_plan_required(
        start_weight_kg=None,
        goal_weight_kg=None,
        start_date="2026-01-01",
    )
    assert result is None
    assert isinstance(reason, str) and len(reason) > 0
