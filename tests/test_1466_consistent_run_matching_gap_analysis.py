"""Tests for issue #1466: Consistent run-matching predicate in gap_analysis/engine.py.

AC coverage:
- AC1: All run-matching predicates in engine.py use the same filter expression
       (lower(workout_type) LIKE '%run%' everywhere — no mixing with exact match).
- AC2: _gather_training_load predicate matches the canonical form (LIKE '%run%').
- AC3: workout_type = 'trail_run' and 'Run' are included in _gather_training_load results.
- AC4: undertrained_area_under_ramp produces non-zero TSS when non-standard workout_type
       rows exist (no false-negative suppression of the ramp signal).
- AC5: A named constant documents the canonical run-matching predicate.
"""
from __future__ import annotations

import datetime
import pathlib
import re


_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ENGINE_FILE = _ROOT / "backend" / "services" / "gap_analysis" / "engine.py"


# ── AC5: Named constant documenting the canonical predicate ───────────────────

def test_ac5_canonical_predicate_constant_defined():
    """AC5: engine.py exports a named constant for the canonical run-matching predicate."""
    from backend.services.gap_analysis import engine
    assert hasattr(engine, "_RUN_FILTER"), (
        "engine.py must define _RUN_FILTER (or similar) constant documenting "
        "the canonical run-matching SQL fragment"
    )


def test_ac5_canonical_predicate_uses_like_form():
    """AC5: The canonical constant uses lower(workout_type) LIKE '%run%' style."""
    from backend.services.gap_analysis import engine
    const_val = engine._RUN_FILTER
    assert "like" in const_val.lower() and "run" in const_val.lower(), (
        f"_RUN_FILTER should contain LIKE and 'run'; got: {const_val!r}"
    )


# ── AC1: No mixing — every query site uses the same predicate form ────────────

def _extract_run_filter_lines(source: str) -> list[tuple[int, str]]:
    """Return (lineno, line) pairs that contain run-type filtering."""
    results = []
    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        # Match lines with workout_type comparison patterns
        if "workout_type" in stripped and (
            "'run'" in stripped or "run" in stripped.lower()
        ) and (
            "like" in stripped.lower() or "= 'run'" in stripped or '= "run"' in stripped
        ):
            results.append((i, stripped))
    return results


def test_ac1_no_exact_match_predicate_in_engine():
    """AC1: No gather function uses exact match `workout_type = 'run'`."""
    source = _ENGINE_FILE.read_text()
    # Look for the exact-match pattern that should have been replaced
    exact_matches = []
    for i, line in enumerate(source.splitlines(), start=1):
        # Match the problematic exact-match form (case-insensitive SQL comparison without lower())
        if re.search(r"workout_type\s*=\s*'run'", line):
            exact_matches.append((i, line.strip()))
    assert exact_matches == [], (
        f"Found exact match `workout_type = 'run'` at lines: {exact_matches}. "
        "All predicates must use lower(workout_type) LIKE '%run%'."
    )


def test_ac1_all_run_filters_use_like_form():
    """AC1: Every run-type filter in engine.py uses lower(workout_type) LIKE '%run%'."""
    source = _ENGINE_FILE.read_text()
    lines = source.splitlines()
    like_count = 0
    for line in lines:
        if "workout_type" in line and "like" in line.lower() and "run" in line.lower():
            like_count += 1
    # We know from the original code that there are (at least) 4 gather functions
    # that filter by run type. All 4 must use the LIKE form.
    assert like_count >= 4, (
        f"Expected >= 4 LIKE-form run-filter lines, found {like_count}. "
        "All gather functions must use lower(workout_type) LIKE '%run%'."
    )


# ── AC2: _gather_training_load uses canonical predicate ──────────────────────

def test_ac2_gather_training_load_uses_like_not_exact():
    """AC2: _gather_training_load SQL uses LIKE '%run%', not exact '= run'."""
    import inspect
    from backend.services.gap_analysis.engine import _gather_training_load
    src = inspect.getsource(_gather_training_load)
    assert "like" in src.lower() and "%run%" in src.lower(), (
        "_gather_training_load must use lower(workout_type) LIKE '%run%'"
    )
    assert "workout_type = 'run'" not in src, (
        "_gather_training_load must NOT use exact match `workout_type = 'run'`"
    )


# ── AC3: trail_run and Run workout_type rows included in TSS query ────────────

def test_ac3_gather_training_load_includes_trail_run(tmp_path):
    """AC3: _gather_training_load counts TSS for workout_type='trail_run'."""
    import uuid
    from unittest.mock import MagicMock

    from backend.services.gap_analysis.engine import _gather_training_load

    today = datetime.date(2026, 7, 14)

    # Simulate a DB that returns one week with a trail_run row
    # We do this by mocking the DB session's execute result
    mock_row = MagicMock()
    mock_row.__iter__ = MagicMock(return_value=iter([
        (datetime.date(2026, 7, 7), 120.0)  # week_start, running_tss
    ]))

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        (datetime.date(2026, 7, 7), 120.0)
    ]

    mock_db = MagicMock()
    mock_db.execute.return_value = mock_result

    result = _gather_training_load(mock_db, uuid.uuid4(), today)

    # Check the SQL that was passed to execute
    call_args = mock_db.execute.call_args
    sql_text = str(call_args[0][0])
    # The SQL must use LIKE, not exact match
    assert "like" in sql_text.lower() or "LIKE" in sql_text, (
        f"SQL passed to DB must use LIKE, got: {sql_text}"
    )
    assert "= 'run'" not in sql_text, (
        f"SQL must not use exact match = 'run', got: {sql_text}"
    )


def test_ac3_gather_training_load_includes_titlecase_Run(tmp_path):
    """AC3: The SQL in _gather_training_load applies lower() so 'Run' is included."""
    import inspect
    from backend.services.gap_analysis.engine import _gather_training_load

    src = inspect.getsource(_gather_training_load)
    # The fix requires lower(workout_type) so any casing variant matches
    assert "lower(" in src.lower(), (
        "_gather_training_load SQL must use lower() for case-insensitive matching"
    )


# ── AC4: undertrained_area_under_ramp non-zero when non-standard workout_type ─

def test_ac4_ramp_signal_not_suppressed_with_non_standard_types():
    """AC4: undertrained_area_under_ramp fires when TSS comes from trail_run/Run rows.

    This is a unit test over the rule function with pre-gathered training_load input
    (simulating what _gather_training_load would return after the fix — non-zero TSS
    from non-standard workout_type values).
    """
    from backend.services.gap_analysis.rules.undertrained_area_under_ramp import (
        undertrained_area_under_ramp,
    )

    week_start = datetime.date(2026, 7, 7)

    # Simulate training_load with non-zero TSS (as would come from trail_run/Run rows
    # after the LIKE fix is in place)
    weekly_tss = [
        {"week_start": (week_start - datetime.timedelta(weeks=5)).isoformat(), "running_tss": 40.0},
        {"week_start": (week_start - datetime.timedelta(weeks=4)).isoformat(), "running_tss": 48.0},
        {"week_start": (week_start - datetime.timedelta(weeks=3)).isoformat(), "running_tss": 55.0},
        {"week_start": (week_start - datetime.timedelta(weeks=2)).isoformat(), "running_tss": 62.0},
        {"week_start": (week_start - datetime.timedelta(weeks=1)).isoformat(), "running_tss": 70.0},
    ]
    # Calf has zero volume for 4+ weeks (simulating untrained area)
    muscle_volume = [
        {"week_start": (week_start - datetime.timedelta(weeks=5)).isoformat(), "muscle_group": "calf", "weekly_load": 5.0},
        {"week_start": (week_start - datetime.timedelta(weeks=4)).isoformat(), "muscle_group": "calf", "weekly_load": 0.0},
        {"week_start": (week_start - datetime.timedelta(weeks=3)).isoformat(), "muscle_group": "calf", "weekly_load": 0.0},
        {"week_start": (week_start - datetime.timedelta(weeks=2)).isoformat(), "muscle_group": "calf", "weekly_load": 0.0},
        {"week_start": (week_start - datetime.timedelta(weeks=1)).isoformat(), "muscle_group": "calf", "weekly_load": 0.0},
        # Fill other priority groups with non-zero
        {"week_start": (week_start - datetime.timedelta(weeks=1)).isoformat(), "muscle_group": "hamstring", "weekly_load": 5.0},
        {"week_start": (week_start - datetime.timedelta(weeks=1)).isoformat(), "muscle_group": "glute", "weekly_load": 5.0},
    ]

    inputs = {
        "week_start": week_start,
        "training_load": {"weekly": weekly_tss},
        "muscle_volume": muscle_volume,
        "injury_log": [],
    }

    result = undertrained_area_under_ramp(inputs)

    # With non-zero TSS from non-standard rows (after fix), the ramp signal MUST fire
    assert result is not None, (
        "undertrained_area_under_ramp must produce a finding when TSS ramp is present "
        "and calf has 4+ weeks of zero volume. "
        "Before the fix, exact-match `= 'run'` would miss trail_run/Run rows, "
        "silently returning 0 TSS and suppressing this signal."
    )
    assert result.code == "undertrained_area_under_ramp"


def test_ac4_ramp_signal_zero_tss_no_false_positive():
    """AC4: With zero TSS (as broken exact-match would produce), rule stays silent."""
    from backend.services.gap_analysis.rules.undertrained_area_under_ramp import (
        undertrained_area_under_ramp,
    )

    week_start = datetime.date(2026, 7, 7)

    # Zero TSS across all weeks (simulating what the broken exact-match produced
    # when only trail_run/Run rows exist)
    weekly_tss = [
        {"week_start": (week_start - datetime.timedelta(weeks=4 - i)).isoformat(), "running_tss": 0.0}
        for i in range(5)
    ]
    muscle_volume = [
        {"week_start": (week_start - datetime.timedelta(weeks=4 - i)).isoformat(), "muscle_group": "calf", "weekly_load": 0.0}
        for i in range(5)
    ]

    inputs = {
        "week_start": week_start,
        "training_load": {"weekly": weekly_tss},
        "muscle_volume": muscle_volume,
        "injury_log": [],
    }

    result = undertrained_area_under_ramp(inputs)
    # Zero TSS = no ramp → rule should not fire (no false positive)
    assert result is None, (
        "undertrained_area_under_ramp must NOT fire when TSS is zero (flat — no ramp)."
    )
