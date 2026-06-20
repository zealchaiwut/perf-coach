"""Tests for issue #714: Add post-race calibration of personal fitness constants.

Acceptance criteria verified:
- AC1: compute_calibration_suggestions(race_id, actual_time_seconds, user_constants,
       population_constants) is a pure function performing no DB writes.
- AC2: The function docstring includes a worked example with concrete numbers.
- AC3: A thin caller (endpoint) handles DB writes: status='done' + actual_time_seconds,
       calls the pure function, and returns suggestions without writing constants.
- AC4: Constants remain unchanged until user explicitly accepts; suggestions are
       surfaced to the user with a clear accept action.
- AC5: Comparison logic derives peak timing and level from both predicted model
       output and actual result.
- AC6: If actual_time_seconds is None or race has no target, the function returns
       a descriptive error rather than a no-op result.
- AC7: No constant value is hardcoded inside the calibration logic; all defaults
       come from the population_constants argument.
- AC8: Unit tests cover early peak (shorter fitness constant suggested), late peak
       (longer fitness constant suggested), on-target peak (no adjustment), and
       missing data error path.
"""
import ast
import inspect
import textwrap
import os

import pytest

from backend.services.training_load import compute_calibration_suggestions

# ── Shared fixtures ────────────────────────────────────────────────────────────

def _population():
    """Return minimal valid population constants (no hardcoded values in function)."""
    from backend.services.training_load import (
        CTL_DAYS,
        ATL_DAYS,
        TIMING_TOLERANCE_WEEKS,
        CTL_ADJUSTMENT_DAYS_PER_WEEK,
        MIN_CTL_DAYS,
        MAX_CTL_DAYS,
    )
    return {
        "ctl_days": CTL_DAYS,
        "atl_days": ATL_DAYS,
        "timing_tolerance_weeks": TIMING_TOLERANCE_WEEKS,
        "ctl_adjustment_days_per_week": CTL_ADJUSTMENT_DAYS_PER_WEEK,
        "min_ctl_days": MIN_CTL_DAYS,
        "max_ctl_days": MAX_CTL_DAYS,
    }


def _user_on_target():
    """User constants where actual_peak_week == predicted_peak_week."""
    return {
        "ctl_days": 42,
        "atl_days": 7,
        "predicted_peak_week": 12,
        "actual_peak_week": 12,
        "goal_time_seconds": 3600,
    }


def _user_early_peak(weeks_early=2):
    """User constants where athlete peaked earlier than predicted."""
    return {
        "ctl_days": 42,
        "atl_days": 7,
        "predicted_peak_week": 12,
        "actual_peak_week": 12 - weeks_early,
        "goal_time_seconds": 3600,
    }


def _user_late_peak(weeks_late=2):
    """User constants where athlete peaked later than predicted."""
    return {
        "ctl_days": 42,
        "atl_days": 7,
        "predicted_peak_week": 12,
        "actual_peak_week": 12 + weeks_late,
        "goal_time_seconds": 3600,
    }


# ── AC1: pure function, importable, no DB writes ───────────────────────────────

def test_ac1_function_importable():
    """compute_calibration_suggestions is importable from training_load."""
    assert callable(compute_calibration_suggestions)


def test_ac1_no_db_write_in_source():
    """compute_calibration_suggestions must contain no DB write operations."""
    src = inspect.getsource(compute_calibration_suggestions)
    for forbidden in ("session.add", "session.commit", "session.flush",
                       "engine", ".execute(", "INSERT", "UPDATE"):
        assert forbidden not in src, (
            f"compute_calibration_suggestions must not contain '{forbidden}' (no DB writes)"
        )


def test_ac1_returns_dict():
    """compute_calibration_suggestions returns a dict on valid input."""
    result = compute_calibration_suggestions(
        "race-123",
        3500,
        _user_on_target(),
        _population(),
    )
    assert isinstance(result, dict)


# ── AC2: docstring with worked example ────────────────────────────────────────

def test_ac2_docstring_has_worked_example():
    """Docstring includes a worked example with concrete numeric values."""
    doc = compute_calibration_suggestions.__doc__ or ""
    assert any(char.isdigit() for char in doc), (
        "Docstring must include a worked example with concrete numbers"
    )


def test_ac2_docstring_mentions_fitness_constant():
    """Docstring mentions 'fitness' and 'time constant'."""
    doc = (compute_calibration_suggestions.__doc__ or "").lower()
    assert "fitness" in doc, "Docstring must mention 'fitness'"
    assert "constant" in doc, "Docstring must mention 'constant'"


def test_ac2_docstring_has_example_with_week_numbers():
    """Docstring example mentions 'week' and shows peak-week comparison."""
    doc = (compute_calibration_suggestions.__doc__ or "").lower()
    assert "week" in doc, "Docstring must reference week numbers in its worked example"


# ── AC5: peak timing and level both derived ────────────────────────────────────

def test_ac5_result_includes_timing_delta():
    """Return value includes timing_delta_weeks (peak timing comparison)."""
    result = compute_calibration_suggestions(
        "race-123",
        3500,
        _user_on_target(),
        _population(),
    )
    assert "timing_delta_weeks" in result, "Result must include 'timing_delta_weeks'"


def test_ac5_result_includes_peak_level_delta():
    """Return value includes peak_level_delta_pct (performance level comparison)."""
    result = compute_calibration_suggestions(
        "race-123",
        3500,
        _user_on_target(),
        _population(),
    )
    assert "peak_level_delta_pct" in result, "Result must include 'peak_level_delta_pct'"


def test_ac5_timing_delta_correct_early_peak():
    """timing_delta_weeks is negative for an early peak."""
    result = compute_calibration_suggestions(
        "race-123",
        3700,
        _user_early_peak(weeks_early=2),
        _population(),
    )
    assert result["timing_delta_weeks"] == -2, (
        f"Early peak (actual=10, predicted=12) should give timing_delta=-2, "
        f"got {result['timing_delta_weeks']}"
    )


def test_ac5_timing_delta_correct_late_peak():
    """timing_delta_weeks is positive for a late peak."""
    result = compute_calibration_suggestions(
        "race-123",
        3700,
        _user_late_peak(weeks_late=3),
        _population(),
    )
    assert result["timing_delta_weeks"] == 3, (
        f"Late peak (actual=15, predicted=12) should give timing_delta=+3, "
        f"got {result['timing_delta_weeks']}"
    )


def test_ac5_level_delta_positive_when_beat_goal():
    """peak_level_delta_pct is positive when athlete finished faster than goal."""
    result = compute_calibration_suggestions(
        "race-123",
        3420,  # 3 minutes faster than 3600 s goal
        _user_on_target(),
        _population(),
    )
    # (3600 - 3420) / 3600 * 100 = 5%
    assert result["peak_level_delta_pct"] > 0, (
        "Finishing faster than goal should produce a positive level delta"
    )


def test_ac5_level_delta_negative_when_missed_goal():
    """peak_level_delta_pct is negative when athlete finished slower than goal."""
    result = compute_calibration_suggestions(
        "race-123",
        3780,  # 3 minutes slower than 3600 s goal
        _user_on_target(),
        _population(),
    )
    assert result["peak_level_delta_pct"] < 0, (
        "Finishing slower than goal should produce a negative level delta"
    )


# ── AC6: missing data → descriptive error ─────────────────────────────────────

def test_ac6_null_actual_time_returns_error():
    """actual_time_seconds=None returns a descriptive error string, not a no-op."""
    result = compute_calibration_suggestions(
        "race-123",
        None,
        _user_on_target(),
        _population(),
    )
    assert result.get("reason"), (
        "actual_time_seconds=None must produce a non-empty 'reason' error string"
    )
    assert result.get("suggested_ctl_days") is None, (
        "No suggestion should be produced when actual_time_seconds is None"
    )


def test_ac6_no_goal_time_returns_error():
    """Missing goal_time_seconds in user_constants returns a descriptive error."""
    constants_no_goal = {
        "ctl_days": 42,
        "atl_days": 7,
        "predicted_peak_week": 12,
        "actual_peak_week": 10,
    }
    result = compute_calibration_suggestions(
        "race-123",
        3500,
        constants_no_goal,
        _population(),
    )
    assert result.get("reason"), (
        "Missing goal_time_seconds must produce a non-empty 'reason' error string"
    )


def test_ac6_null_user_constants_returns_error():
    """user_constants=None with no goal_time also produces a descriptive error."""
    result = compute_calibration_suggestions(
        "race-123",
        3500,
        None,
        _population(),
    )
    assert result.get("reason"), "None user_constants must produce a reason error"


def test_ac6_error_does_not_raise_exception():
    """Invalid inputs never raise an exception — always return a dict."""
    for bad_args in [
        ("race-123", None, None, None),
        ("race-123", None, {}, {}),
        ("race-123", -1, {"goal_time_seconds": None}, {}),
    ]:
        try:
            result = compute_calibration_suggestions(*bad_args)
            assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        except Exception as exc:
            pytest.fail(
                f"compute_calibration_suggestions({bad_args!r}) raised "
                f"{type(exc).__name__}: {exc}"
            )


# ── AC7: no hardcoded constants in function body ───────────────────────────────

def test_ac7_no_bare_numeric_threshold_literals():
    """The calibration function must not contain bare numeric threshold literals.

    All thresholds and defaults must come from population_constants.
    Module-level named constant REFERENCES are acceptable; bare 42, 7, 1, 2 etc. are not.
    """
    src = inspect.getsource(compute_calibration_suggestions)
    tree = ast.parse(textwrap.dedent(src))
    func_body = tree.body[0].body
    # Skip docstring
    if func_body and isinstance(func_body[0], ast.Expr) and isinstance(func_body[0].value, ast.Constant):
        func_body = func_body[1:]

    numeric_literals = [
        node.value
        for node in ast.walk(ast.Module(body=func_body, type_ignores=[]))
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
    ]
    # Only 0 is acceptable (e.g., comparisons with zero); all domain values must be constants
    forbidden = [v for v in numeric_literals if v not in (0, 0.0, 100, 100.0)]
    assert forbidden == [], (
        f"compute_calibration_suggestions contains bare numeric literals {forbidden}; "
        "use named constants from population_constants or module-level constants instead"
    )


def test_ac7_population_constants_supplies_defaults():
    """Passing different population_constants changes the tolerance behaviour."""

    # With default tolerance (e.g., 1 week), a 1-week early peak = on target
    pop_tight = dict(_population(), timing_tolerance_weeks=0)  # zero tolerance
    pop_loose = dict(_population(), timing_tolerance_weeks=5)  # very loose tolerance

    user_1_week_early = dict(_user_early_peak(weeks_early=1))

    result_tight = compute_calibration_suggestions("r", 3600, user_1_week_early, pop_tight)
    result_loose = compute_calibration_suggestions("r", 3600, user_1_week_early, pop_loose)

    assert result_tight.get("adjustment_direction") in ("shorten",), (
        "Tight tolerance should flag a 1-week early peak as 'shorten'"
    )
    assert result_loose.get("adjustment_direction") == "none", (
        "Loose tolerance (5 weeks) should flag a 1-week early peak as 'none'"
    )


# ── AC8: four unit-test cases ─────────────────────────────────────────────────

def test_ac8_early_peak_suggests_shorter_ctl():
    """Early peak (actual < predicted week): suggest shorter fitness constant."""
    result = compute_calibration_suggestions(
        "race-123",
        3700,
        _user_early_peak(weeks_early=2),
        _population(),
    )
    assert result.get("reason") == "", f"Unexpected error: {result.get('reason')}"
    assert result.get("adjustment_direction") == "shorten", (
        f"Early peak should suggest 'shorten', got {result.get('adjustment_direction')!r}"
    )
    # Suggested constant must be shorter than current 42 days
    assert result["suggested_ctl_days"] < 42, (
        f"Suggested ctl_days {result['suggested_ctl_days']} must be less than 42 for early peak"
    )
    # Explanation must mention the word 'earlier' or 'shorter'
    explanation = (result.get("explanation") or "").lower()
    assert "earlier" in explanation or "shorter" in explanation or "short" in explanation, (
        f"Explanation must mention shortening; got: {result.get('explanation')!r}"
    )


def test_ac8_late_peak_suggests_longer_ctl():
    """Late peak (actual > predicted week): suggest longer fitness constant."""
    result = compute_calibration_suggestions(
        "race-123",
        3700,
        _user_late_peak(weeks_late=2),
        _population(),
    )
    assert result.get("reason") == "", f"Unexpected error: {result.get('reason')}"
    assert result.get("adjustment_direction") == "lengthen", (
        f"Late peak should suggest 'lengthen', got {result.get('adjustment_direction')!r}"
    )
    # Suggested constant must be longer than current 42 days
    assert result["suggested_ctl_days"] > 42, (
        f"Suggested ctl_days {result['suggested_ctl_days']} must be more than 42 for late peak"
    )
    # Explanation must mention the word 'later' or 'longer'
    explanation = (result.get("explanation") or "").lower()
    assert "later" in explanation or "longer" in explanation or "long" in explanation, (
        f"Explanation must mention lengthening; got: {result.get('explanation')!r}"
    )


def test_ac8_on_target_peak_no_adjustment():
    """On-target peak (actual == predicted week): no adjustment suggested."""
    result = compute_calibration_suggestions(
        "race-123",
        3600,
        _user_on_target(),
        _population(),
    )
    assert result.get("reason") == "", f"Unexpected error: {result.get('reason')}"
    assert result.get("adjustment_direction") == "none", (
        f"On-target peak should suggest 'none', got {result.get('adjustment_direction')!r}"
    )
    assert result["suggested_ctl_days"] == 42, (
        f"On-target peak: suggested_ctl_days should stay at 42, got {result['suggested_ctl_days']}"
    )


def test_ac8_missing_data_error_path():
    """Missing data (None actual_time_seconds): return descriptive error, no result."""
    result = compute_calibration_suggestions(
        "race-123",
        None,
        _user_on_target(),
        _population(),
    )
    assert result.get("reason"), "Missing actual_time_seconds must produce a non-empty reason"
    assert result.get("suggested_ctl_days") is None, (
        "No suggestion should be produced for missing data"
    )
    assert result.get("suggested_atl_days") is None


# ── AC8 additional: result shape ─────────────────────────────────────────────

def test_result_has_required_keys_on_success():
    """On success, result has all expected keys."""
    result = compute_calibration_suggestions(
        "race-abc",
        3600,
        _user_on_target(),
        _population(),
    )
    for key in ("suggested_ctl_days", "suggested_atl_days", "timing_delta_weeks",
                 "peak_level_delta_pct", "explanation", "adjustment_direction", "reason"):
        assert key in result, f"Result missing key '{key}'"


def test_result_explanation_is_string():
    """explanation field is always a non-empty string on success."""
    result = compute_calibration_suggestions(
        "race-abc",
        3600,
        _user_on_target(),
        _population(),
    )
    assert isinstance(result.get("explanation"), str), "explanation must be a string"
    assert result["explanation"], "explanation must not be empty on success"


def test_suggested_ctl_days_within_bounds():
    """suggested_ctl_days is always within min/max bounds from population_constants."""
    from backend.services.training_load import MIN_CTL_DAYS, MAX_CTL_DAYS

    # Extreme early peak (many weeks early) should not go below min
    extreme_early = dict(_user_early_peak(weeks_early=20))
    result = compute_calibration_suggestions("r", 3600, extreme_early, _population())
    if result.get("reason") == "":
        assert result["suggested_ctl_days"] >= MIN_CTL_DAYS, (
            f"suggested_ctl_days must not go below MIN_CTL_DAYS={MIN_CTL_DAYS}"
        )

    # Extreme late peak (many weeks late) should not exceed max
    extreme_late = dict(_user_late_peak(weeks_late=20))
    result = compute_calibration_suggestions("r", 3600, extreme_late, _population())
    if result.get("reason") == "":
        assert result["suggested_ctl_days"] <= MAX_CTL_DAYS, (
            f"suggested_ctl_days must not exceed MAX_CTL_DAYS={MAX_CTL_DAYS}"
        )


# ── Integration tests (require running UAT server) ────────────────────────────

try:
    import importlib.util
    _SERVER_AVAILABLE = (
        importlib.util.find_spec("httpx") is not None
        and bool(os.environ.get("UAT_BASE_URL") or os.environ.get("UAT_PORT"))
    )
    _BASE_URL = (
        os.environ.get("UAT_BASE_URL")
        or ("http://localhost:" + os.environ.get("UAT_PORT", ""))
    ) if _SERVER_AVAILABLE else ""
except Exception:
    _SERVER_AVAILABLE = False
    _BASE_URL = ""


def _skip_no_server():
    if not _SERVER_AVAILABLE:
        pytest.skip("UAT server not configured (UAT_BASE_URL or UAT_PORT required)")


@pytest.fixture
def live_client():
    _skip_no_server()
    import httpx
    with httpx.Client(base_url=_BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def authed_live_client(live_client):
    """Login as testuser and return authenticated client."""
    resp = live_client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    if resp.status_code == 401:
        pytest.skip("testuser not available")
    assert resp.status_code == 200
    return live_client


@pytest.fixture
def calibratable_race(authed_live_client):
    """Create a race with a goal_time for calibration tests."""
    resp = authed_live_client.post(
        "/api/races",
        json={
            "name": "Calibration Test Race",
            "race_date": "2025-01-15",
            "distance_km": 42.195,
            "priority": "A",
            "goal_time_seconds": 10800,
            "status": "planned",
        },
    )
    assert resp.status_code == 201, f"Race creation failed: {resp.text}"
    race = resp.json()
    yield race
    # Cleanup
    authed_live_client.delete(f"/api/races/{race['id']}")


# AC3: thin caller writes status='done' + actual_time_seconds, returns suggestions

def test_ac3_calibrate_endpoint_writes_status_done(authed_live_client, calibratable_race):
    """POST /api/races/{id}/calibrate writes status='done' to the race row."""
    _skip_no_server()
    race_id = calibratable_race["id"]
    resp = authed_live_client.post(
        f"/api/races/{race_id}/calibrate",
        json={"actual_time_seconds": 11400},
    )
    assert resp.status_code == 200, f"Calibrate failed: {resp.text}"
    body = resp.json()
    assert body["race"]["status"] == "done", (
        f"Expected status='done' after calibrate, got {body['race']['status']!r}"
    )


def test_ac3_calibrate_endpoint_writes_actual_time(authed_live_client, calibratable_race):
    """POST /api/races/{id}/calibrate writes actual_time_seconds to the race row."""
    _skip_no_server()
    race_id = calibratable_race["id"]
    resp = authed_live_client.post(
        f"/api/races/{race_id}/calibrate",
        json={"actual_time_seconds": 11400},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["race"]["actual_time_seconds"] == 11400, (
        f"Expected actual_time_seconds=11400, got {body['race'].get('actual_time_seconds')}"
    )


def test_ac3_calibrate_endpoint_returns_suggestions(authed_live_client, calibratable_race):
    """POST /api/races/{id}/calibrate returns suggestions with ctl/atl hints."""
    _skip_no_server()
    race_id = calibratable_race["id"]
    resp = authed_live_client.post(
        f"/api/races/{race_id}/calibrate",
        json={"actual_time_seconds": 11400},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "suggestions" in body, "Response must include 'suggestions'"
    s = body["suggestions"]
    assert "suggested_ctl_days" in s
    assert "explanation" in s
    assert "adjustment_direction" in s


# AC3: caller does NOT write constants to user record

def test_ac3_calibrate_does_not_overwrite_user_constants(authed_live_client, calibratable_race):
    """POST /api/races/{id}/calibrate does not modify user preferences."""
    _skip_no_server()
    prefs_before = authed_live_client.get("/api/user-preferences").json().get("row", {})
    ctl_before = prefs_before.get("ctl_days")

    race_id = calibratable_race["id"]
    authed_live_client.post(
        f"/api/races/{race_id}/calibrate",
        json={"actual_time_seconds": 11400},
    )

    prefs_after = authed_live_client.get("/api/user-preferences").json().get("row", {})
    assert prefs_after.get("ctl_days") == ctl_before, (
        "calibrate must not automatically overwrite user ctl_days in preferences"
    )


# AC4: explicit accept action writes constants

def test_ac4_accept_calibration_updates_user_constants(authed_live_client, calibratable_race):
    """POST /api/races/{id}/calibrate/accept updates user preferences."""
    _skip_no_server()
    race_id = calibratable_race["id"]
    # First calibrate
    cal_resp = authed_live_client.post(
        f"/api/races/{race_id}/calibrate",
        json={"actual_time_seconds": 11400},
    )
    assert cal_resp.status_code == 200
    suggestions = cal_resp.json()["suggestions"]
    suggested_ctl = suggestions["suggested_ctl_days"]

    # Then accept
    accept_resp = authed_live_client.post(
        f"/api/races/{race_id}/calibrate/accept",
        json={
            "ctl_days": suggested_ctl,
            "atl_days": suggestions.get("suggested_atl_days"),
        },
    )
    assert accept_resp.status_code == 200, f"Accept failed: {accept_resp.text}"

    prefs_after = authed_live_client.get("/api/user-preferences").json().get("row", {})
    assert prefs_after.get("ctl_days") == suggested_ctl, (
        f"After accept, ctl_days should be {suggested_ctl}, got {prefs_after.get('ctl_days')}"
    )


# AC6: null actual_time_seconds via endpoint returns 422

def test_ac6_calibrate_null_actual_time_returns_error(authed_live_client, calibratable_race):
    """POST /api/races/{id}/calibrate with null actual_time_seconds returns 422."""
    _skip_no_server()
    race_id = calibratable_race["id"]
    resp = authed_live_client.post(
        f"/api/races/{race_id}/calibrate",
        json={"actual_time_seconds": None},
    )
    assert resp.status_code == 422, (
        f"Expected 422 for null actual_time_seconds, got {resp.status_code}"
    )


def test_ac6_calibrate_race_with_no_goal_returns_error(authed_live_client):
    """POST /api/races/{id}/calibrate on a race with no goal returns 422."""
    _skip_no_server()
    resp = authed_live_client.post(
        "/api/races",
        json={
            "name": "No-Goal Race",
            "race_date": "2025-02-01",
            "distance_km": 21.0,
            "priority": "B",
            "status": "planned",
        },
    )
    assert resp.status_code == 201
    no_goal_race_id = resp.json()["id"]
    try:
        cal_resp = authed_live_client.post(
            f"/api/races/{no_goal_race_id}/calibrate",
            json={"actual_time_seconds": 5400},
        )
        assert cal_resp.status_code == 422, (
            f"Expected 422 for race with no goal, got {cal_resp.status_code}"
        )
    finally:
        authed_live_client.delete(f"/api/races/{no_goal_race_id}")
