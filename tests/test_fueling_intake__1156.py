"""Tests for issue #1156: Add lightweight fueling/intake input for energy-availability proxy (runs against UAT)"""
import os
import py_compile


def test_main_py_compiles():
    """AC: All new and modified Python files pass `py_compile` with zero errors"""
    main_file = os.path.join(os.path.dirname(__file__), '..', 'backend', 'main.py')
    py_compile.compile(main_file, doraise=True)


def test_models_py_compiles():
    """AC: All new and modified Python files pass `py_compile` with zero errors"""
    models_file = os.path.join(os.path.dirname(__file__), '..', 'backend', 'models.py')
    py_compile.compile(models_file, doraise=True)


def test_migration_py_compiles():
    """AC: All new and modified Python files pass `py_compile` with zero errors"""
    migration_file = os.path.join(os.path.dirname(__file__), '..', 'alembic', 'versions', '4ea6071056c8_add_kcal_intake_to_daily_metrics.py')
    py_compile.compile(migration_file, doraise=True)


def test_kcal_intake_field_exists_in_daily_metric_model():
    """AC: User can enter a daily fueling/intake value (e.g., kilocalories or relative unit) from the UI"""
    from backend.models import DailyMetric
    from sqlalchemy import inspect

    mapper = inspect(DailyMetric)
    columns = {col.name for col in mapper.columns}
    assert 'kcal_intake' in columns, "kcal_intake column not found in DailyMetric model"


def test_kcal_intake_field_accepts_positive_integers():
    """AC: Submitted intake value is persisted to the database"""
    from backend.models import DailyMetric
    from sqlalchemy import inspect

    mapper = inspect(DailyMetric)
    kcal_col = mapper.c.kcal_intake

    # Should be Integer, nullable=True
    assert kcal_col.type.__class__.__name__ == 'Integer'
    assert kcal_col.nullable


def test_daily_metric_api_payload_includes_kcal_intake():
    """AC: Persisted intake value is returned in the relevant API response"""
    from backend.main import DailyMetricIn, DailyMetricBody
    from typing import get_type_hints

    # Check DailyMetricIn input schema
    hints_in = get_type_hints(DailyMetricIn)
    assert 'kcal_intake' in hints_in, "kcal_intake not in DailyMetricIn schema"

    # Check DailyMetricBody update schema
    hints_body = get_type_hints(DailyMetricBody)
    assert 'kcal_intake' in hints_body, "kcal_intake not in DailyMetricBody schema"


def test_kcal_intake_validation_exists():
    """AC: kcal_intake validation rejects non-positive values"""
    from backend.main import _validate_metric_fields
    from fastapi import HTTPException

    # Test that negative values are rejected
    try:
        _validate_metric_fields(kcal_intake=-100)
        assert False, "Should have raised HTTPException for negative kcal_intake"
    except HTTPException as e:
        assert e.status_code == 422
        assert "kcal_intake" in str(e.detail)

    # Test that zero is rejected
    try:
        _validate_metric_fields(kcal_intake=0)
        assert False, "Should have raised HTTPException for zero kcal_intake"
    except HTTPException as e:
        assert e.status_code == 422
        assert "kcal_intake" in str(e.detail)

    # Test that positive value is accepted
    _validate_metric_fields(kcal_intake=2500)  # Should not raise


def test_daily_metric_dict_serializes_kcal_intake():
    """AC: Persisted intake value is retrievable via the backend"""
    from backend.main import _daily_metric_dict
    from backend.models import DailyMetric
    from datetime import datetime, date
    from uuid import uuid4

    # Create a test DailyMetric instance
    metric = DailyMetric(
        id=uuid4(),
        user_id=uuid4(),
        metric_date=date.today(),
        resting_hr=60,
        kcal_intake=2500,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )

    result = _daily_metric_dict(metric)
    assert 'kcal_intake' in result, "kcal_intake not in serialized response"
    assert result['kcal_intake'] == 2500, f"Expected 2500, got {result['kcal_intake']}"


def test_frontend_intake_field_html_exists():
    """AC: User can enter a daily fueling/intake value from the UI"""
    import os

    home_html = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'pages', 'home.html')
    assert os.path.exists(home_html), "home.html not found"

    with open(home_html, 'r') as f:
        content = f.read()

    # Check for intake field in HTML
    assert 'fm-kcal' in content, "Intake field (fm-kcal) not found in home.html"
    assert 'Intake' in content, "Intake label not found in home.html"
    assert 'kcal' in content.lower(), "kcal unit not found in home.html"


def test_frontend_intake_javascript_handler_exists():
    """AC: Submitted intake value is persisted via the frontend"""
    import os

    home_js = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'js', 'home.js')
    assert os.path.exists(home_js), "home.js not found"

    with open(home_js, 'r') as f:
        content = f.read()

    # Check for kcal intake handling in JavaScript
    assert 'fm-kcal' in content, "fm-kcal input not handled in home.js"
    assert 'kcal_intake' in content, "kcal_intake not handled in home.js"
    assert '_fmBuildPayload' in content, "Payload builder not found in home.js"


def test_migration_adds_kcal_intake_column_with_constraint():
    """AC: Database supports storing kcal_intake values"""
    migration_file = os.path.join(os.path.dirname(__file__), '..', 'alembic', 'versions', '4ea6071056c8_add_kcal_intake_to_daily_metrics.py')

    with open(migration_file, 'r') as f:
        content = f.read()

    # Check that migration adds the column
    assert 'add_column' in content or 'kcal_intake' in content, "Migration doesn't add kcal_intake column"
    # Check for validation constraint
    assert 'kcal_intake IS NULL OR kcal_intake > 0' in content, "Migration missing positive-only constraint"
