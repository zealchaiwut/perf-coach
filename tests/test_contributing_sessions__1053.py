"""Deterministic, server-independent tests for issue #1053.

Show contributing sessions under endurance and speed scores.

Each test below is anchored to a specific acceptance criterion and exercises the
real implementation (the pure functions that the
``GET /api/athletes/{id}/performance`` endpoint uses to build the
``contributing_sessions`` payload, plus the rendered frontend assets). These
tests do NOT depend on a live UAT server or on any particular athlete being
seeded — they construct the inputs directly and assert the implementation
satisfies the AC. That makes them reliable in CI regardless of UAT data state.
"""
import os
from pathlib import Path

# A parseable (never-connected) DATABASE_URL lets us import ``backend.main`` to
# reach the response-shaping helpers without requiring a live database. The
# SQLAlchemy engine is created lazily, so no connection is ever opened.
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/dummy")
os.environ.setdefault("ENVIRONMENT", "local")

from backend.services.running_performance import get_contributing_run_ids  # noqa: E402
from backend.services.zone_constants import make_zone_constants  # noqa: E402
from backend.main import (  # noqa: E402
    _build_session_dicts_from_contributors,
    _format_pace,
    _map_source_badge,
)

# The exact flat key contract the AC mandates for every contributing session.
REQUIRED_KEYS = {
    "workout_id",
    "date",
    "title",
    "distance_km",
    "pace",
    "avg_hr",
    "contribution",
    "source",
}

ZC = make_zone_constants()
PREFS = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 270}


# --- Test data builders -------------------------------------------------------


def _lap(band, power, hr=150, dist=1.0, dur=300):
    return {
        "band": band,
        "avg_power": power,
        "avg_hr": hr,
        "distance_km": dist,
        "duration_seconds": dur,
    }


def _run(run_id, band, date, power=180, source="strava", n_laps=6):
    """Build a run dict in the shape the performance endpoint assembles."""
    return {
        "run_id": run_id,
        "workout_date": date,
        "laps": [_lap(band, power) for _ in range(n_laps)],
        "decoupling_pct": 5.0,
        "avg_power": power,
        "avg_hr": 150,
        "distance_km": 10.0,
        "duration_seconds": 3000,
        "name": f"Run {run_id}",
        "source": source,
        "workout_date_str": date,
        "speed_signal": None,
    }


def _endurance_runs(n, source="strava"):
    # 'steady' is an endurance band (easy/steady); vary power so contributions spread.
    return [
        _run(f"e{i}", "steady", f"2026-06-{i + 1:02d}", power=160 + i, source=source)
        for i in range(n)
    ]


def _speed_runs(n, source="stryd"):
    # 'hard' is a speed band (hard/interval); ratio > 1.06 in real classification.
    return [
        _run(f"s{i}", "hard", f"2026-06-{i + 1:02d}", power=240 + i, source=source)
        for i in range(n)
    ]


def _sessions_for(runs, mode):
    contributors = get_contributing_run_ids(runs, PREFS, ZC, mode=mode)
    run_map = {r["run_id"]: r for r in runs}
    return _build_session_dicts_from_contributors(contributors, run_map)


# --- AC1: contributing_sessions is a list of up to five entries ---------------


def test_contributing_sessions_is_a_list():
    sessions = _sessions_for(_endurance_runs(5), "endurance")
    assert isinstance(sessions, list)


def test_contributing_sessions_capped_at_five():
    # AC: the list contains up to five entries — even when more qualify.
    sessions = _sessions_for(_endurance_runs(8), "endurance")
    assert len(sessions) == 5
    speed_sessions = _sessions_for(_speed_runs(7), "speed")
    assert len(speed_sessions) == 5


# --- AC2: each entry exposes exactly the eight flat keys ----------------------


def test_each_entry_has_exactly_eight_flat_keys():
    for mode, runs in (("endurance", _endurance_runs(5)), ("speed", _speed_runs(5))):
        sessions = _sessions_for(runs, mode)
        assert sessions, f"expected {mode} sessions to be produced"
        for i, s in enumerate(sessions):
            assert set(s.keys()) == REQUIRED_KEYS, (
                f"{mode} session [{i}] keys {set(s.keys())} != {REQUIRED_KEYS}"
            )


def test_session_values_are_flat_scalars_not_nested():
    # AC: no extra nested objects — every value must be a scalar (or None).
    sessions = _sessions_for(_endurance_runs(5), "endurance")
    for s in sessions:
        for key, value in s.items():
            assert not isinstance(value, (dict, list)), (
                f"key {key!r} carries a nested {type(value).__name__}, expected a scalar"
            )


# --- AC3: five most recent qualifying sessions per score ----------------------


def test_endurance_lists_five_most_recent_qualifying():
    # Seven qualifying endurance runs in chronological (oldest-first) order;
    # only the five most recent (e2..e6) must be reported.
    runs = _endurance_runs(7)
    contributors = get_contributing_run_ids(runs, PREFS, ZC, mode="endurance")
    returned_ids = [c["run_id"] for c in contributors]
    assert returned_ids == ["e2", "e3", "e4", "e5", "e6"]


def test_speed_lists_only_qualifying_speed_sessions():
    # Endurance-band runs must not appear in the speed list and vice-versa.
    mixed = _endurance_runs(3) + _speed_runs(3)
    speed = get_contributing_run_ids(mixed, PREFS, ZC, mode="speed")
    speed_ids = {c["run_id"] for c in speed}
    assert speed_ids == {"s0", "s1", "s2"}

    endurance = get_contributing_run_ids(mixed, PREFS, ZC, mode="endurance")
    endurance_ids = {c["run_id"] for c in endurance}
    assert endurance_ids == {"e0", "e1", "e2"}


# --- AC5: source badge derived from the source field -------------------------


def test_map_source_badge_values():
    assert _map_source_badge("strava") == "Strava"
    assert _map_source_badge("strava_api") == "Strava"
    assert _map_source_badge("stryd") == "Stryd"
    assert _map_source_badge("manual") is None
    assert _map_source_badge(None) is None


def test_session_source_reflects_badge():
    strava_sessions = _sessions_for(_endurance_runs(3, source="strava"), "endurance")
    assert strava_sessions and all(s["source"] == "Strava" for s in strava_sessions)
    stryd_sessions = _sessions_for(_speed_runs(3, source="stryd"), "speed")
    assert stryd_sessions and all(s["source"] == "Stryd" for s in stryd_sessions)


# --- AC6: contribution value present on every row ----------------------------


def test_each_row_has_numeric_contribution():
    sessions = _sessions_for(_endurance_runs(5), "endurance")
    assert sessions
    for s in sessions:
        assert isinstance(s["contribution"], (int, float)) and not isinstance(
            s["contribution"], bool
        )


# --- AC8: fewer than five qualifying sessions -> only the available ones ------


def test_fewer_than_five_returns_only_available():
    sessions = _sessions_for(_endurance_runs(3), "endurance")
    assert len(sessions) == 3
    for s in sessions:
        assert set(s.keys()) == REQUIRED_KEYS


def test_no_qualifying_runs_returns_empty_list():
    # Runs whose laps fall outside the endurance bands qualify for nothing.
    non_qualifying = [_run("x0", "tempo", "2026-06-01")]
    assert get_contributing_run_ids(non_qualifying, PREFS, ZC, mode="endurance") == []


def test_empty_and_missing_inputs_return_empty_list():
    assert get_contributing_run_ids([], PREFS, ZC, mode="endurance") == []
    assert get_contributing_run_ids(None, PREFS, ZC, mode="endurance") == []
    assert get_contributing_run_ids(_endurance_runs(5), None, ZC, mode="endurance") == []


def test_build_skips_contributors_without_matching_workout():
    # A contributor whose run_id is absent from the map is dropped cleanly.
    contributors = [{"run_id": "missing", "contribution": 42.0}]
    assert _build_session_dicts_from_contributors(contributors, {}) == []


# --- pace formatting used to populate the flat `pace` key --------------------


def test_format_pace():
    assert _format_pace(3000, 10.0) == "5:00/km"
    assert _format_pace(330, 1.0) == "5:30/km"
    assert _format_pace(None, 10.0) is None
    assert _format_pace(3000, 0) is None
    assert _format_pace(3000, None) is None


# --- Frontend ACs verified against the deployed assets -----------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TRAINING_LOG_HTML = (_REPO_ROOT / "frontend" / "pages" / "training-log.html").read_text()
_PERFORMANCE_JS = (_REPO_ROOT / "frontend" / "js" / "training-performance.js").read_text()


def test_footnote_states_contribution_values_are_estimates():
    # AC7: a footnote beneath the session list states the values are estimates
    # until the model is fully calibrated.
    normalized = " ".join(_TRAINING_LOG_HTML.split())
    assert "contribution values are estimates" in normalized.lower()
    assert "calibrated" in normalized.lower()
    assert "perf-sessions-footnote" in _TRAINING_LOG_HTML


def test_rows_deep_link_in_place_via_open_workout_detail():
    # AC4: clicking a row opens the workout detail panel in-place (no navigation).
    assert "contributing_sessions" in _PERFORMANCE_JS
    assert "window.openWorkoutDetail" in _PERFORMANCE_JS
    # The deep link is wired to the row's workout_id, not a page navigation.
    assert "s.workout_id" in _PERFORMANCE_JS


def test_frontend_renders_source_badge():
    # AC5: each row displays a Strava or Stryd source badge.
    assert "source-badge" in _PERFORMANCE_JS
    assert '"Strava"' in _PERFORMANCE_JS and '"Stryd"' in _PERFORMANCE_JS


def test_frontend_renders_contribution_value():
    # AC6: the contribution value is rendered next to each row.
    assert "perf-sess-contrib" in _PERFORMANCE_JS
    assert "s.contribution" in _PERFORMANCE_JS
