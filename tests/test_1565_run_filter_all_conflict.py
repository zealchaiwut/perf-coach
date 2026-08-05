"""Tests for issue #1565: _RUN_FILTER must not appear in engine.__all__."""
import backend.services.gap_analysis.engine as _engine


def test_run_filter_not_in_all():
    """AC: __all__ must not contain names with the private underscore prefix."""
    private_in_all = [name for name in _engine.__all__ if name.startswith("_")]
    assert private_in_all == [], (
        f"__all__ contains private names: {private_in_all}. "
        "Either remove the underscore prefix or remove the name from __all__."
    )


def test_run_filter_constant_still_exists():
    """The constant itself must still be present (used in f-strings internally)."""
    assert hasattr(_engine, "_RUN_FILTER"), "_RUN_FILTER constant was removed — it is still used internally"
    assert "lower(workout_type)" in _engine._RUN_FILTER
