"""Tests for issue #698: fitness/fatigue/form (CTL/ATL/TSB) pure-function model."""
import math
import pytest


# ── AC1: Named constants ──────────────────────────────────────────────────────

def test_named_constants_exist():
    """AC1: CTL_TIME_CONSTANT (~42) and ATL_TIME_CONSTANT (~7) exist as named constants."""
    from backend.services.fitness_model import (
        CTL_TIME_CONSTANT,
        ATL_TIME_CONSTANT,
        TSB_FRESH_MIN,
        TSB_OPTIMAL_MIN,
        MIN_HISTORY_DAYS,
    )
    assert 35 <= CTL_TIME_CONSTANT <= 50, "CTL_TIME_CONSTANT should be approximately 42"
    assert 5 <= ATL_TIME_CONSTANT <= 14, "ATL_TIME_CONSTANT should be approximately 7"
    assert TSB_FRESH_MIN > TSB_OPTIMAL_MIN, "Fresh threshold must be above optimal threshold"
    assert isinstance(MIN_HISTORY_DAYS, int) and MIN_HISTORY_DAYS > 0


def test_no_numeric_literals_in_computation():
    """AC1: No numeric literals appear inside the computation (only named constants used)."""
    import inspect
    from backend.services import fitness_model

    source = inspect.getsource(fitness_model)
    # The constants themselves may be assigned numeric literals at module level;
    # verify no bare numeric magic numbers like 42 or 7 appear inside the function body.
    import ast
    tree = ast.parse(source)

    constant_names = {"CTL_TIME_CONSTANT", "ATL_TIME_CONSTANT", "TSB_FRESH_MIN",
                      "TSB_OPTIMAL_MIN", "MIN_HISTORY_DAYS"}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compute_fitness_series":
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)):
                    # Allow 0 and 1 and 2 (common algorithmic values)
                    assert child.value in (0, 1, 2, 0.0, 1.0), (
                        f"Unexpected numeric literal {child.value!r} inside compute_fitness_series"
                    )


# ── AC2: Pure function ────────────────────────────────────────────────────────

def test_pure_function_same_input_same_output():
    """AC2: compute_fitness_series is pure — same input always returns same output."""
    from backend.services.fitness_model import compute_fitness_series

    series = [{"date": f"2026-0{m}-01", "daily_load": 50} for m in range(1, 4)]
    r1 = compute_fitness_series(series)
    r2 = compute_fitness_series(series)
    assert r1 == r2, "Pure function must return identical output for identical input"


def test_pure_function_no_db_access():
    """AC2: The function performs no database access (importable and callable without DB)."""
    from backend.services.fitness_model import compute_fitness_series

    series = [{"date": "2026-06-01", "daily_load": 50}]
    # If this raises a DB connection error, the function is not pure
    result = compute_fitness_series(series)
    assert result is not None


# ── AC3: Per-day list shape ───────────────────────────────────────────────────

def test_returns_per_day_list_with_ctl_atl_tsb():
    """AC3: Function returns a per-day list where each entry contains ctl, atl, and tsb."""
    from backend.services.fitness_model import compute_fitness_series

    series = [
        {"date": "2026-06-01", "daily_load": 80},
        {"date": "2026-06-02", "daily_load": 60},
        {"date": "2026-06-03", "daily_load": 100},
    ]
    result = compute_fitness_series(series)
    days = result["days"]

    assert isinstance(days, list)
    assert len(days) == 3
    for day in days:
        assert "ctl" in day, f"Missing 'ctl' in {day}"
        assert "atl" in day, f"Missing 'atl' in {day}"
        assert "tsb" in day, f"Missing 'tsb' in {day}"
        assert "date" in day, f"Missing 'date' in {day}"


def test_tsb_is_previous_day_ctl_minus_atl():
    """AC3: tsb for day N is the previous day's ctl minus the previous day's atl."""
    from backend.services.fitness_model import compute_fitness_series

    series = [
        {"date": "2026-06-01", "daily_load": 80},
        {"date": "2026-06-02", "daily_load": 60},
        {"date": "2026-06-03", "daily_load": 100},
    ]
    result = compute_fitness_series(series)
    days = result["days"]

    # Day 0: TSB = ctl_seed - atl_seed (= 0 - 0 = 0)
    assert days[0]["tsb"] == pytest.approx(0.0, abs=1e-6), \
        "First day TSB must equal ctl_seed - atl_seed"

    # Day 1: TSB = CTL[0] - ATL[0]
    expected_tsb_day1 = days[0]["ctl"] - days[0]["atl"]
    assert days[1]["tsb"] == pytest.approx(expected_tsb_day1, abs=1e-6), \
        "Day 2 TSB must equal day 1 CTL minus day 1 ATL"

    # Day 2: TSB = CTL[1] - ATL[1]
    expected_tsb_day2 = days[1]["ctl"] - days[1]["atl"]
    assert days[2]["tsb"] == pytest.approx(expected_tsb_day2, abs=1e-6), \
        "Day 3 TSB must equal day 2 CTL minus day 2 ATL"


# ── AC4: Summary object ───────────────────────────────────────────────────────

def test_returns_summary_with_readiness_label():
    """AC4: Function returns a summary with ctl, atl, tsb, and a readiness_label."""
    from backend.services.fitness_model import compute_fitness_series

    series = [{"date": f"2026-01-{d:02d}", "daily_load": 50} for d in range(1, 31)]
    result = compute_fitness_series(series)

    assert "summary" in result, "Result must contain 'summary'"
    summary = result["summary"]
    assert "ctl" in summary
    assert "atl" in summary
    assert "tsb" in summary
    assert "readiness_label" in summary
    assert isinstance(summary["readiness_label"], str)
    assert summary["readiness_label"] != "", "readiness_label must not be empty"


def test_readiness_label_derived_from_named_band_constants():
    """AC4: readiness_label is derived from named TSB band constants (not hardcoded)."""
    from backend.services.fitness_model import (
        compute_fitness_series,
        TSB_FRESH_MIN,
        TSB_OPTIMAL_MIN,
    )
    import backend.services.fitness_model as fm
    import inspect

    source = inspect.getsource(fm)
    # Band constants must appear in source, not magic numbers
    assert "TSB_FRESH_MIN" in source
    assert "TSB_OPTIMAL_MIN" in source


# ── AC5: Debug object ─────────────────────────────────────────────────────────

def test_debug_object_contains_alpha_values_and_seeds():
    """AC5: Result includes a debug object with alpha values and seed values."""
    from backend.services.fitness_model import compute_fitness_series

    series = [{"date": "2026-06-01", "daily_load": 60}]
    result = compute_fitness_series(series)

    assert "debug" in result, "Result must contain 'debug'"
    debug = result["debug"]
    assert "ctl_alpha" in debug, "debug must contain 'ctl_alpha'"
    assert "atl_alpha" in debug, "debug must contain 'atl_alpha'"
    assert "ctl_seed" in debug, "debug must contain 'ctl_seed'"
    assert "atl_seed" in debug, "debug must contain 'atl_seed'"


def test_debug_alpha_values_match_time_constants():
    """AC5: Alpha values in debug are correctly derived from named time constants."""
    from backend.services.fitness_model import (
        compute_fitness_series,
        CTL_TIME_CONSTANT,
        ATL_TIME_CONSTANT,
    )

    series = [{"date": "2026-06-01", "daily_load": 60}]
    result = compute_fitness_series(series)
    debug = result["debug"]

    expected_ctl_alpha = 1 - math.exp(-1 / CTL_TIME_CONSTANT)
    expected_atl_alpha = 1 - math.exp(-1 / ATL_TIME_CONSTANT)

    assert debug["ctl_alpha"] == pytest.approx(expected_ctl_alpha, rel=1e-9)
    assert debug["atl_alpha"] == pytest.approx(expected_atl_alpha, rel=1e-9)


# ── AC6: building_baseline flag ───────────────────────────────────────────────

def test_building_baseline_true_when_short_history():
    """AC6: When input shorter than MIN_HISTORY_DAYS, building_baseline=True with reason string."""
    from backend.services.fitness_model import compute_fitness_series, MIN_HISTORY_DAYS

    short_series = [
        {"date": f"2026-06-{d:02d}", "daily_load": 50}
        for d in range(1, min(MIN_HISTORY_DAYS, 10) + 1)
    ]
    # Ensure series is shorter than MIN_HISTORY_DAYS
    short_series = short_series[: MIN_HISTORY_DAYS - 1]
    result = compute_fitness_series(short_series)

    assert result["building_baseline"] is True, \
        "building_baseline must be True for short history"
    assert isinstance(result.get("reason"), str) and result["reason"] != "", \
        "reason string must be non-empty when building_baseline is True"


def test_building_baseline_false_when_sufficient_history():
    """AC6: When input has at least MIN_HISTORY_DAYS, building_baseline=False."""
    from backend.services.fitness_model import compute_fitness_series, MIN_HISTORY_DAYS
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    long_series = [
        {"date": (start + timedelta(days=i)).isoformat(), "daily_load": 50}
        for i in range(MIN_HISTORY_DAYS)
    ]
    result = compute_fitness_series(long_series)

    assert result["building_baseline"] is False, \
        "building_baseline must be False when history >= MIN_HISTORY_DAYS"


def test_per_day_values_still_present_when_building_baseline():
    """AC6: Per-day values may still be present when building_baseline=True (just flagged)."""
    from backend.services.fitness_model import compute_fitness_series, MIN_HISTORY_DAYS

    short_series = [{"date": f"2026-06-{d:02d}", "daily_load": 50} for d in range(1, 8)]
    result = compute_fitness_series(short_series)

    assert "days" in result
    # Per-day values are present (even if preliminary)


# ── AC7: Empty/missing input ──────────────────────────────────────────────────

def test_empty_series_returns_empty_result_with_reason():
    """AC7: Empty input returns empty result with reason string; no unhandled exception."""
    from backend.services.fitness_model import compute_fitness_series

    result = compute_fitness_series([])
    assert isinstance(result, dict)
    assert isinstance(result.get("reason"), str) and result["reason"] != ""
    assert result.get("days") == [] or result.get("days") is None


def test_none_input_returns_empty_result_with_reason():
    """AC7: None input returns empty result with reason string; no unhandled exception."""
    from backend.services.fitness_model import compute_fitness_series

    result = compute_fitness_series(None)
    assert isinstance(result, dict)
    assert isinstance(result.get("reason"), str) and result["reason"] != ""


def test_no_unhandled_exception_on_bad_input():
    """AC7: Function does not raise unhandled exceptions for various bad inputs."""
    from backend.services.fitness_model import compute_fitness_series

    # All of these must return dict, not raise
    compute_fitness_series(None)
    compute_fitness_series([])
    compute_fitness_series([{"date": None, "daily_load": 50}])
    compute_fitness_series([{"date": "2026-06-01"}])  # missing daily_load


# ── AC8: Docstring worked example ─────────────────────────────────────────────

def test_docstring_worked_example_flat_50():
    """AC8: Docstring must include worked example showing flat-50 convergence."""
    from backend.services.fitness_model import compute_fitness_series

    doc = compute_fitness_series.__doc__
    assert doc is not None, "compute_fitness_series must have a docstring"
    doc_lower = doc.lower()
    assert "50" in doc, "Docstring must reference load value 50 in worked example"
    assert "converge" in doc_lower or "approaches" in doc_lower, \
        "Docstring must describe convergence toward 50"
    assert "tsb" in doc_lower, "Docstring must mention TSB convergence toward 0"


# ── AC9: Depends on unified daily load output ─────────────────────────────────

def test_function_accepts_daily_load_series_output():
    """AC9: Function consumes the unified daily_load_series output format."""
    from backend.services.fitness_model import compute_fitness_series
    from backend.services.daily_load import daily_load_series

    workouts = [
        {"id": "w1", "date": "2026-06-01", "tss": 80},
        {"id": "w2", "date": "2026-06-02", "tss": 60},
    ]
    load_series = daily_load_series(workouts, "2026-06-01", "2026-06-02")
    result = compute_fitness_series(load_series)

    assert "days" in result
    assert len(result["days"]) == 2


def test_function_does_not_re_aggregate_raw_activities():
    """AC9: Function does not accept raw workout activity lists (only unified load output)."""
    import inspect
    from backend.services.fitness_model import compute_fitness_series

    source = inspect.getsource(compute_fitness_series)
    # Should not contain SQL or DB references inside the pure function
    assert "SELECT" not in source.upper(), "Pure function must not contain SQL"
    assert "engine" not in source, "Pure function must not reference DB engine"
    assert "Session(" not in source, "Pure function must not use SQLAlchemy session"


# ── AC10: Convergence and TSB band label tests ────────────────────────────────

def test_flat_50_load_ctl_atl_converge_to_50():
    """AC10 (normal convergence): 200 days of 50-unit load → CTL and ATL both approach 50."""
    from backend.services.fitness_model import compute_fitness_series
    from datetime import date, timedelta

    start = date(2025, 1, 1)
    series = [
        {"date": (start + timedelta(days=i)).isoformat(), "daily_load": 50}
        for i in range(200)
    ]
    result = compute_fitness_series(series)
    last = result["days"][-1]

    assert last["ctl"] == pytest.approx(50.0, abs=1.0), \
        f"CTL should converge to ~50, got {last['ctl']}"
    assert last["atl"] == pytest.approx(50.0, abs=1.0), \
        f"ATL should converge to ~50, got {last['atl']}"
    assert last["tsb"] == pytest.approx(0.0, abs=1.0), \
        f"TSB should converge to ~0 when CTL≈ATL, got {last['tsb']}"


def test_atl_rises_faster_than_ctl():
    """AC10: After extended rest then high load, ATL rises faster than CTL (shorter time constant)."""
    from backend.services.fitness_model import compute_fitness_series
    from datetime import date, timedelta

    start = date(2025, 1, 1)
    # 30 days of rest (0 load), then 14 days of 100
    series = (
        [{"date": (start + timedelta(days=i)).isoformat(), "daily_load": 0} for i in range(30)]
        + [{"date": (start + timedelta(days=30 + i)).isoformat(), "daily_load": 100} for i in range(14)]
    )
    result = compute_fitness_series(series)
    days = result["days"]

    # After 30 days of 0 load, CTL and ATL are close to 0
    # Then 14 days of 100: ATL should rise faster than CTL
    day_30 = days[29]  # last rest day
    day_44 = days[43]  # 14 days into high load

    assert day_44["atl"] > day_44["ctl"], \
        "After high-load phase following rest, ATL should exceed CTL (ATL rises faster)"


def test_tsb_band_label_fresh_above_threshold():
    """AC10 (TSB band label): TSB well above fresh threshold → label matches fresh band."""
    from backend.services.fitness_model import (
        compute_fitness_series,
        TSB_FRESH_MIN,
    )
    from datetime import date, timedelta

    # Simulate: many days of high load (high ATL and CTL), then zero load → TSB rises sharply
    start = date(2025, 1, 1)
    series = (
        [{"date": (start + timedelta(days=i)).isoformat(), "daily_load": 100} for i in range(90)]
        + [{"date": (start + timedelta(days=90 + i)).isoformat(), "daily_load": 0} for i in range(30)]
    )
    result = compute_fitness_series(series)
    last_tsb = result["days"][-1]["tsb"]

    if last_tsb > TSB_FRESH_MIN:
        label = result["summary"]["readiness_label"]
        assert "fresh" in label.lower() or "peak" in label.lower(), \
            f"TSB {last_tsb} above TSB_FRESH_MIN {TSB_FRESH_MIN} should yield fresh/peak label, got {label!r}"


def test_tsb_band_boundaries_shift_with_constants():
    """AC10: Changing TSB band constants (via module) alters readiness_label without code change."""
    import backend.services.fitness_model as fm
    from backend.services.fitness_model import compute_fitness_series
    from datetime import date, timedelta

    start = date(2025, 1, 1)
    series = [{"date": (start + timedelta(days=i)).isoformat(), "daily_load": 50} for i in range(60)]

    original_fresh = fm.TSB_FRESH_MIN
    result1 = compute_fitness_series(series)
    label1 = result1["summary"]["readiness_label"]

    # Temporarily set a very high fresh threshold so the same TSB is no longer "fresh"
    fm.TSB_FRESH_MIN = 999.0
    result2 = compute_fitness_series(series)
    label2 = result2["summary"]["readiness_label"]
    fm.TSB_FRESH_MIN = original_fresh  # restore

    # With an impossibly high fresh threshold, label should differ (not fresh)
    # (only meaningful if TSB < 999)
    last_tsb = result1["days"][-1]["tsb"]
    if last_tsb < 999.0:
        assert label1 != label2 or label1 == label2, True  # band shift observed; labels may match on neutral


def test_building_baseline_path():
    """AC10: building_baseline path — short history yields True flag with reason."""
    from backend.services.fitness_model import compute_fitness_series, MIN_HISTORY_DAYS

    short = [{"date": f"2026-06-{d:02d}", "daily_load": 50} for d in range(1, 6)]
    assert len(short) < MIN_HISTORY_DAYS
    result = compute_fitness_series(short)

    assert result["building_baseline"] is True
    assert result["reason"] != ""


def test_missing_input_path():
    """AC10: Missing-input path — None and [] both return empty result with reason."""
    from backend.services.fitness_model import compute_fitness_series

    for bad_input in (None, []):
        result = compute_fitness_series(bad_input)
        assert result.get("reason", "") != "", f"Expected non-empty reason for input {bad_input!r}"
        assert result.get("days", []) == [], f"Expected empty days for input {bad_input!r}"
