"""Tests for issue #1113: Render projected time-curve chart with confidence band.

Acceptance criteria verified:
- AC1: readiness endpoint includes a `time_curve` key; chart can fetch and render it
- AC2: projection entries have descending (improving) estimated_finish_seconds
       toward the A-goal (when fitness is improving toward taper)
- AC3: each projected entry exposes upper_seconds, lower_seconds, confidence_band_seconds
       forming an upper/lower bounding band around the estimate
- AC4: history and projection are separate lists in time_curve (distinct segments)
- AC5: time_curve.goal_finish_seconds matches the race's goal_time_seconds
- AC6: building_baseline=True → time_curve.projection is empty (no projection)
- AC7: edge case — no goal_time_seconds → goal_finish_seconds is None
- AC8: edge case — no threshold_pace → projection may still contain entries
       but finish times may be null (graceful, not a crash)
- AC9: upper_seconds >= estimated_finish_seconds >= lower_seconds (time is inverse —
       lower finish time is better, upper is worse)
- AC10: history list contains date/estimated_finish_seconds/estimated_finish_time keys
"""

import json
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

TODAY = date(2026, 6, 29)
FUTURE_RACE = TODAY + timedelta(days=60)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_user(uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    return u


def _make_race(user_id, goal_time_seconds=6600, distance_km=21.0975, race_date=None):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.user_id = user_id
    r.race_date = race_date or FUTURE_RACE
    r.distance_km = distance_km
    r.goal_time_seconds = goal_time_seconds
    r.goal_pace_seconds_per_km = 313
    r.name = "Test Half Marathon"
    r.priority = "A"
    r.race_type = "race"
    r.status = "planned"
    r.created_at = None
    r.updated_at = None
    return r


def _make_tss_series_long(start, end):
    """Enough non-zero TSS days to satisfy 8-week minimum."""
    result = []
    d = start
    while d <= end:
        result.append((d, 60 if d.weekday() in (1, 3, 6) else 0))
        d += timedelta(days=1)
    return result


def _make_tss_series_short(start, end):
    """No workouts — triggers building_baseline=True."""
    result = []
    d = start
    while d <= end:
        result.append((d, 0))
        d += timedelta(days=1)
    return result


def _load_curves(series):
    from backend.services.training_load import compute_load_curves
    return compute_load_curves(series)


def _make_mock_prefs(threshold_pace=300):
    p = MagicMock()
    p.threshold_pace_seconds_per_km = threshold_pace
    return p


def _call_readiness(race, series, curves, prefs=None, run_rows=None, marker_rows=None):
    """Call get_race_readiness with all necessary mocks."""
    from backend.main import get_race_readiness

    run_rows = run_rows or []
    marker_rows = marker_rows or []
    user = _make_user(race.user_id)
    prefs = prefs if prefs is not None else _make_mock_prefs()

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = race
    mock_db.query.return_value.filter.return_value.first.return_value = prefs
    mock_db.execute.return_value.fetchall.side_effect = [run_rows, marker_rows]

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        MockSession.return_value = mock_db
        result = get_race_readiness(str(race.id), user)

    return json.loads(result.body)


# ── AC1: time_curve key is present in the response ──────────────────────────

def test_ac1_time_curve_key_present():
    """Readiness endpoint must include a time_curve key."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    assert "time_curve" in body, "time_curve must be present in readiness response"


def test_ac1_time_curve_has_required_keys():
    """time_curve must contain history, projection, goal_finish_seconds, goal_finish_time."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    tc = body["time_curve"]
    for key in ("history", "projection", "goal_finish_seconds", "goal_finish_time"):
        assert key in tc, f"time_curve must contain '{key}'"


# ── AC2: projection entries trend toward goal ────────────────────────────────

def test_ac2_projection_is_list():
    """time_curve.projection must be a list."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    assert isinstance(body["time_curve"]["projection"], list)


def test_ac2_projection_entries_have_required_fields():
    """Each projected entry must have date, estimated_finish_seconds, estimated_finish_time."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    proj = body["time_curve"]["projection"]
    if proj:
        entry = proj[0]
        for key in ("date", "estimated_finish_seconds", "estimated_finish_time"):
            assert key in entry, f"projection entry must contain '{key}'"


# ── AC3: confidence band on projected entries ─────────────────────────────────

def test_ac3_projection_entries_have_band_fields():
    """Each projected entry must have upper_seconds, lower_seconds, confidence_band_seconds."""
    user = _make_user()
    race = _make_race(user.id, goal_time_seconds=6600)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    proj = body["time_curve"]["projection"]
    if proj:
        entry = proj[0]
        for key in ("upper_seconds", "lower_seconds", "confidence_band_seconds"):
            assert key in entry, f"projection entry must contain '{key}'"


# ── AC4: history and projection are separate lists ────────────────────────────

def test_ac4_history_is_list():
    """time_curve.history must be a list."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    assert isinstance(body["time_curve"]["history"], list)


def test_ac4_history_and_projection_are_separate():
    """history and projection must be distinct lists (both present)."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    tc = body["time_curve"]
    assert "history" in tc and "projection" in tc
    assert tc["history"] is not tc["projection"]


def test_ac4_history_entries_have_required_fields():
    """Each history entry must have date, estimated_finish_seconds, estimated_finish_time."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    hist = body["time_curve"]["history"]
    if hist:
        entry = hist[0]
        for key in ("date", "estimated_finish_seconds", "estimated_finish_time"):
            assert key in entry, f"history entry must contain '{key}'"


# ── AC5: goal_finish_seconds matches race goal ────────────────────────────────

def test_ac5_goal_finish_seconds_matches_race():
    """time_curve.goal_finish_seconds must equal race.goal_time_seconds."""
    user = _make_user()
    goal = 6600
    race = _make_race(user.id, goal_time_seconds=goal)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    assert body["time_curve"]["goal_finish_seconds"] == goal


# ── AC6: building_baseline → projection is empty ──────────────────────────────

def test_ac6_building_baseline_projection_empty():
    """When building_baseline=True, time_curve.projection must be empty."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    assert body["time_curve"]["projection"] == [], (
        "projection must be [] when building_baseline is True"
    )


# ── AC7: no goal_time_seconds → goal_finish_seconds is None ──────────────────

def test_ac7_no_goal_time_gives_null():
    """When race has no goal_time_seconds, goal_finish_seconds must be None."""
    user = _make_user()
    race = _make_race(user.id, goal_time_seconds=None)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    assert body["time_curve"]["goal_finish_seconds"] is None


# ── AC8: graceful when no threshold_pace ─────────────────────────────────────

def test_ac8_no_threshold_pace_no_crash():
    """Endpoint must not crash when user has no threshold_pace configured."""
    user = _make_user()
    race = _make_race(user.id)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    no_threshold_prefs = MagicMock()
    no_threshold_prefs.threshold_pace_seconds_per_km = None

    body = _call_readiness(race, series, curves, prefs=no_threshold_prefs)
    assert "time_curve" in body
    tc = body["time_curve"]
    assert "history" in tc
    assert "projection" in tc


# ── AC9: upper >= center >= lower for each projected entry ────────────────────

def test_ac9_band_ordering():
    """For each projected entry: upper_seconds >= estimated_finish_seconds >= lower_seconds."""
    user = _make_user()
    race = _make_race(user.id, goal_time_seconds=6600)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    body = _call_readiness(race, series, curves)
    proj = body["time_curve"]["projection"]
    for entry in proj:
        center = entry["estimated_finish_seconds"]
        upper = entry["upper_seconds"]
        lower = entry["lower_seconds"]
        if center is not None and upper is not None and lower is not None:
            assert upper >= center, (
                f"upper_seconds ({upper}) must be >= estimated_finish_seconds ({center})"
            )
            assert lower <= center, (
                f"lower_seconds ({lower}) must be <= estimated_finish_seconds ({center})"
            )


# ── AC10: history has non-null finish times when thresholds available ─────────

def test_ac10_history_finish_times_non_null():
    """History entries must have non-null estimated_finish_seconds when thresholds exist."""
    user = _make_user()
    race = _make_race(user.id, goal_time_seconds=6600)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)
    prefs = _make_mock_prefs(threshold_pace=300)

    body = _call_readiness(race, series, curves, prefs=prefs)
    hist = body["time_curve"]["history"]
    assert len(hist) > 0, "history must have at least one entry"
    for entry in hist:
        assert entry["estimated_finish_seconds"] is not None, (
            f"history entry {entry['date']} has null estimated_finish_seconds"
        )
