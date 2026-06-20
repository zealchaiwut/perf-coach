"""
Unit tests for issue #712: Add peak-tracking and race-specificity progress functions.

Acceptance Criteria verified:
- AC1-4:  peak_tracking(current_form, projected_form) returns dict with status + gap
- AC3:    "on track" band controlled by named tolerance parameter
- AC4:    returns null result with reason when input is missing or non-numeric
- AC5-10: specificity_progress(race, recent_runs) is a pure function
- AC6:    returns four metrics as {current, target}
- AC7:    "at or near goal pace" uses named pace-tolerance parameter
- AC8:    targets derived from race record, never hardcoded
- AC9:    runs flagged as B-race results are excluded from all specificity calculations
- AC10:   returns empty result with reason when race/goal-pace/runs are missing
- AC11:   both functions have docstrings with worked numeric examples
- AC12:   all DB access stays in caller; pure functions accept plain data structures
- AC13:   all arithmetic has plain-language inline comments
- AC14:   unit tests cover on-track/ahead/behind, exact boundary, missing input,
          B-race exclusion, and empty-runs edge case
"""
import inspect
import types

from backend.services.training_load import PEAK_TRACKING_TOLERANCE, peak_tracking
from backend.services.specificity_progress import (
    specificity_progress,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

HALF_MARATHON_KM = 21.0975
SUB_1_50_SECONDS = 110 * 60  # 6600 s


def _race(distance_km=HALF_MARATHON_KM, goal_time_seconds=SUB_1_50_SECONDS):
    gp = round(goal_time_seconds / distance_km)
    return types.SimpleNamespace(
        distance_km=distance_km,
        goal_time_seconds=goal_time_seconds,
        goal_pace_seconds_per_km=gp,
    )


def _run(distance_km, duration_seconds, is_b_race=False):
    return types.SimpleNamespace(
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        is_b_race=is_b_race,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# peak_tracking — AC1-4
# ═══════════════════════════════════════════════════════════════════════════════

# ─── AC2: returns dict with status and gap ────────────────────────────────────

def test_peak_tracking_returns_dict():
    result = peak_tracking(85.0, 70.0)
    assert isinstance(result, dict), "peak_tracking must return a dict"
    assert "status" in result, "result must have 'status' key"
    assert "gap" in result, "result must have 'gap' key"


def test_peak_tracking_gap_is_current_minus_projected():
    # gap = current_form minus projected_form_for_today_from_plan
    result = peak_tracking(85.0, 70.0)
    assert result["gap"] == 15.0, "gap must equal current minus projected: 85 - 70 = 15"


def test_peak_tracking_gap_negative_when_behind():
    result = peak_tracking(55.0, 70.0)
    assert result["gap"] == -15.0, "gap must equal 55 - 70 = -15 when behind"


# ─── AC2: status values ───────────────────────────────────────────────────────

def test_peak_tracking_ahead():
    # current (85) > projected (70) + tolerance (5) → ahead
    result = peak_tracking(85.0, 70.0)
    assert result["status"] == "ahead", f"Expected 'ahead', got '{result['status']}'"


def test_peak_tracking_behind():
    # current (55) < projected (70) - tolerance (5) → behind
    result = peak_tracking(55.0, 70.0)
    assert result["status"] == "behind", f"Expected 'behind', got '{result['status']}'"


def test_peak_tracking_on_track_within_band():
    # current (72) is within tolerance (5) of projected (70) → on track
    result = peak_tracking(72.0, 70.0)
    assert result["status"] == "on track", f"Expected 'on track', got '{result['status']}'"
    assert result["gap"] == 2.0


def test_peak_tracking_on_track_exact_match():
    # current == projected → gap = 0 → on track
    result = peak_tracking(70.0, 70.0)
    assert result["status"] == "on track"
    assert result["gap"] == 0.0


# ─── AC3: exact boundary of the tolerance band ───────────────────────────────

def test_peak_tracking_on_track_at_upper_boundary():
    # current = projected + tolerance → still on track (inclusive boundary)
    tol = PEAK_TRACKING_TOLERANCE
    result = peak_tracking(70.0 + tol, 70.0)
    assert result["status"] == "on track", (
        f"At upper boundary (70 + {tol}), status must be 'on track', got '{result['status']}'"
    )


def test_peak_tracking_on_track_at_lower_boundary():
    # current = projected - tolerance → still on track (inclusive boundary)
    tol = PEAK_TRACKING_TOLERANCE
    result = peak_tracking(70.0 - tol, 70.0)
    assert result["status"] == "on track", (
        f"At lower boundary (70 - {tol}), status must be 'on track', got '{result['status']}'"
    )


def test_peak_tracking_ahead_just_above_upper_boundary():
    # current = projected + tolerance + epsilon → ahead
    tol = PEAK_TRACKING_TOLERANCE
    result = peak_tracking(70.0 + tol + 0.01, 70.0)
    assert result["status"] == "ahead", "Just above upper boundary must be 'ahead'"


def test_peak_tracking_behind_just_below_lower_boundary():
    # current = projected - tolerance - epsilon → behind
    tol = PEAK_TRACKING_TOLERANCE
    result = peak_tracking(70.0 - tol - 0.01, 70.0)
    assert result["status"] == "behind", "Just below lower boundary must be 'behind'"


# ─── AC3: named tolerance parameter ──────────────────────────────────────────

def test_peak_tracking_tolerance_is_named_module_constant():
    assert isinstance(PEAK_TRACKING_TOLERANCE, (int, float)), (
        "PEAK_TRACKING_TOLERANCE must be a numeric module-level constant"
    )
    assert PEAK_TRACKING_TOLERANCE > 0


def test_peak_tracking_custom_tolerance_overrides_default():
    # With tight tolerance (1.0), gap of 2 is "ahead", not "on track"
    result = peak_tracking(72.0, 70.0, tolerance=1.0)
    assert result["status"] == "ahead", (
        "With tolerance=1.0, gap=2 must be 'ahead' (outside tight band)"
    )


# ─── AC4: missing / non-numeric inputs return null with reason ────────────────

def test_peak_tracking_none_current_form_returns_null_with_reason():
    result = peak_tracking(None, 70.0)
    assert result["status"] is None, "status must be None when current_form is missing"
    assert "reason" in result and result["reason"], "reason must be non-empty string"
    assert "current" in result["reason"].lower(), (
        f"reason must mention 'current_form', got: {result['reason']}"
    )


def test_peak_tracking_none_projected_form_returns_null_with_reason():
    result = peak_tracking(70.0, None)
    assert result["status"] is None, "status must be None when projected_form is missing"
    assert "reason" in result and result["reason"]
    assert "projected" in result["reason"].lower(), (
        f"reason must mention projected_form, got: {result['reason']}"
    )


def test_peak_tracking_non_numeric_current_form_returns_null():
    result = peak_tracking("not-a-number", 70.0)
    assert result["status"] is None, "Non-numeric current_form must yield null status"
    assert result["reason"]


def test_peak_tracking_non_numeric_projected_returns_null():
    result = peak_tracking(70.0, "bad")
    assert result["status"] is None
    assert result["reason"]


# ─── AC11: docstring has worked numeric examples ──────────────────────────────

def test_peak_tracking_docstring_has_numeric_example():
    doc = peak_tracking.__doc__ or ""
    doc_lower = doc.lower()
    assert "ahead" in doc_lower, "docstring must include 'ahead' example"
    assert "on track" in doc_lower, "docstring must include 'on track' example"
    assert "behind" in doc_lower, "docstring must include 'behind' example"
    # at least one numeric value referenced
    assert any(c.isdigit() for c in doc), "docstring must contain at least one numeric worked example"


# ═══════════════════════════════════════════════════════════════════════════════
# specificity_progress — AC5-10
# ═══════════════════════════════════════════════════════════════════════════════

# ─── AC9: B-race exclusion ────────────────────────────────────────────────────

def test_b_race_run_excluded_from_volume_at_pace():
    """A run flagged as B-race must not contribute to volume_at_pace."""
    race = _race()
    goal_pace = race.goal_pace_seconds_per_km
    b_run = _run(distance_km=15.0, duration_seconds=int(15.0 * goal_pace), is_b_race=True)
    result = specificity_progress(race, [b_run])
    assert result["volume_at_pace"]["current"] == 0.0, (
        "B-race run must be excluded — volume_at_pace must be 0"
    )


def test_b_race_run_excluded_from_longest_pace_effort():
    """A B-race run at goal pace must not appear in longest_pace_effort."""
    race = _race()
    goal_pace = race.goal_pace_seconds_per_km
    b_run = _run(distance_km=15.0, duration_seconds=int(15.0 * goal_pace), is_b_race=True)
    result = specificity_progress(race, [b_run])
    assert result["longest_pace_effort"]["current"] == 0.0, (
        "B-race run must be excluded from longest_pace_effort"
    )


def test_b_race_run_excluded_from_longest_run_by_distance():
    """A B-race run must not appear in longest_run_by_distance."""
    race = _race()
    b_run = _run(distance_km=20.0, duration_seconds=7200, is_b_race=True)
    result = specificity_progress(race, [b_run])
    assert result["longest_run_by_distance"]["current"] == 0.0, (
        "B-race run must be excluded from longest_run_by_distance"
    )


def test_b_race_run_excluded_from_longest_run_by_duration():
    """A B-race run must not appear in longest_run_by_duration."""
    race = _race()
    b_run = _run(distance_km=20.0, duration_seconds=7200, is_b_race=True)
    result = specificity_progress(race, [b_run])
    assert result["longest_run_by_duration"]["current"] == 0, (
        "B-race run must be excluded from longest_run_by_duration"
    )


def test_b_race_exclusion_partial_mixed_list():
    """Non-B-race runs still count; only the B-race run is dropped."""
    race = _race()
    goal_pace = race.goal_pace_seconds_per_km
    normal_run = _run(distance_km=10.0, duration_seconds=int(10.0 * goal_pace), is_b_race=False)
    b_run = _run(distance_km=15.0, duration_seconds=int(15.0 * goal_pace), is_b_race=True)
    result = specificity_progress(race, [normal_run, b_run])
    # Only normal_run (10 km) should count
    assert abs(result["volume_at_pace"]["current"] - 10.0) < 0.1, (
        "After excluding B-race (15 km), only normal run (10 km) must appear"
    )
    assert abs(result["longest_run_by_distance"]["current"] - 10.0) < 0.1, (
        "longest_run_by_distance must equal 10 km after B-race exclusion"
    )


def test_b_race_docstring_explains_exclusion():
    """specificity_progress docstring must explain B-race exclusion with an example."""
    doc = specificity_progress.__doc__ or ""
    doc_lower = doc.lower()
    assert "b-race" in doc_lower or "b race" in doc_lower or "b_race" in doc_lower, (
        "docstring must mention B-race exclusion"
    )
    # Must explain what it means (example or description)
    has_example = "example" in doc_lower or "e.g." in doc_lower or "i.e." in doc_lower or "excluded" in doc_lower
    assert has_example, "docstring must explain the B-race exclusion rationale or give an example"


# ─── AC10: empty / missing runs ───────────────────────────────────────────────

def test_specificity_empty_runs_returns_zeroed_with_reason():
    race = _race()
    result = specificity_progress(race, [])
    for key in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        assert result[key]["current"] == 0 or result[key]["current"] == 0.0
    assert "reason" in result and result["reason"]


def test_specificity_none_runs_returns_zeroed_with_reason():
    race = _race()
    result = specificity_progress(race, None)
    for key in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        assert result[key]["current"] == 0 or result[key]["current"] == 0.0
    assert "reason" in result and result["reason"]


def test_specificity_missing_race_returns_reason():
    result = specificity_progress(None, [])
    assert "reason" in result and result["reason"]
    assert "status" not in result or result.get("status") is None


def test_specificity_no_goal_pace_returns_reason():
    no_pace_race = types.SimpleNamespace(
        distance_km=HALF_MARATHON_KM,
        goal_time_seconds=None,
        goal_pace_seconds_per_km=None,
    )
    result = specificity_progress(no_pace_race, [_run(10.0, 3600)])
    assert "reason" in result and result["reason"]


# ─── AC6: all four metrics present with current and target ────────────────────

def test_specificity_returns_four_metrics():
    race = _race()
    run = _run(distance_km=15.0, duration_seconds=int(15.0 * race.goal_pace_seconds_per_km))
    result = specificity_progress(race, [run])
    for key in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        assert key in result, f"result must contain '{key}'"
        assert "current" in result[key], f"{key} must have 'current'"
        assert "target" in result[key], f"{key} must have 'target'"


# ─── AC7: named pace-tolerance parameter ─────────────────────────────────────

def test_specificity_pace_tolerance_is_named_parameter():
    sig = inspect.signature(specificity_progress)
    assert "pace_tolerance_seconds_per_km" in sig.parameters, (
        "specificity_progress must accept pace_tolerance_seconds_per_km as a named parameter"
    )


def test_specificity_pace_tolerance_changes_in_band_boundary():
    """A run just outside the default band is included when tolerance is widened."""
    race = _race()
    goal_pace = race.goal_pace_seconds_per_km
    # Run 20 s/km slower than goal pace — outside default tolerance (15), inside wide tolerance (25)
    slow_pace = goal_pace + 20
    run = _run(distance_km=10.0, duration_seconds=int(10.0 * slow_pace))
    narrow = specificity_progress(race, [run], pace_tolerance_seconds_per_km=15)
    wide = specificity_progress(race, [run], pace_tolerance_seconds_per_km=25)
    assert narrow["volume_at_pace"]["current"] == 0.0, (
        "Run at pace+20 must be out of band with tolerance=15"
    )
    assert wide["volume_at_pace"]["current"] > 0.0, (
        "Run at pace+20 must be in band with tolerance=25"
    )


# ─── AC8: targets derived from race, not hardcoded ───────────────────────────

def test_specificity_targets_scale_with_race_distance():
    race_hm = _race(distance_km=HALF_MARATHON_KM)
    race_marathon = _race(distance_km=42.195, goal_time_seconds=3 * 3600 + 40 * 60)
    r_hm = specificity_progress(race_hm, [])
    r_marathon = specificity_progress(race_marathon, [])
    assert r_marathon["longest_run_by_distance"]["target"] > r_hm["longest_run_by_distance"]["target"], (
        "Marathon target distance must be larger than half-marathon target"
    )


# ─── AC12: pure function — no DB access ──────────────────────────────────────

def test_specificity_is_pure_no_db_access():
    src = inspect.getsource(specificity_progress)
    for token in ("Session", "session", "db.execute", "query(", ".commit("):
        assert token not in src, f"specificity_progress must be pure (found '{token}')"


# ─── AC11: docstring with worked numeric example ─────────────────────────────

def test_specificity_docstring_has_numeric_example():
    doc = specificity_progress.__doc__ or ""
    # Must reference the sub-1:50 half-marathon scenario or explicit numbers
    has_numbers = any(c.isdigit() for c in doc)
    assert has_numbers, "docstring must contain numeric worked examples"
    assert len(doc.strip()) > 100, "docstring must be non-trivial"
