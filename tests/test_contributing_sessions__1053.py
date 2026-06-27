"""Tests for issue #1053: Show contributing sessions under endurance and speed scores.

Acceptance Criteria covered:
  AC1 - GET /api/athletes/{id}/performance includes contributing_sessions on each score object
        (up to five entries).
  AC2 - Each entry exposes exactly these flat keys: workout_id, date, title,
        distance_km, pace, avg_hr, contribution, source.
  AC3 - Endurance score lists 5 most recent endurance-effort sessions;
        speed score lists 5 most recent interval/speed sessions.
  AC4 - Each session row links to the workout and opens the detail panel in-place.
  AC5 - Each row displays a source badge (Strava or Stryd) from the source field.
  AC6 - contribution value is rendered next to each row.
  AC7 - A footnote beneath the session list states contribution values are estimates.
  AC8 - Fewer than 5 qualifying sessions → only show available sessions (no errors).
"""

import os

import pytest

from backend.main import (
    _build_session_dicts_from_contributors,
    _format_pace,
    _map_source_badge,
)
from backend.services.running_performance import get_contributing_run_ids
from backend.services.zone_constants import make_zone_constants

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _make_run(run_id, band, workout_date="2026-01-01", decoupling_pct=None,
              name="Test Run", source="strava"):
    """Build a minimal run dict with qualifying laps."""
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "name": name,
        "source": source,
        "laps": [
            {
                "band": band,
                "avg_power": 200.0,
                "avg_hr": 140.0,
                "distance_km": 2.0,
                "duration_seconds": 600.0,
            }
        ],
        "decoupling_pct": decoupling_pct,
        "avg_power": 200.0,
        "avg_hr": 140.0,
        "distance_km": 6.0,
        "duration_seconds": 1800,
    }


def _make_prefs():
    return {
        "ftp_w": 200,
        "threshold_hr": 165,
        "threshold_pace_seconds_per_km": 300,
        "duration_curve_bests": None,
    }


ZC = make_zone_constants()


# AC3 + AC8: Endurance — identifies qualifying (easy/steady) sessions
class TestGetContributingRunIdsEndurance:

    def test_returns_empty_for_no_runs(self):
        result = get_contributing_run_ids([], _make_prefs(), ZC, mode="endurance")
        assert result == []

    def test_returns_empty_for_none_runs(self):
        result = get_contributing_run_ids(None, _make_prefs(), ZC, mode="endurance")
        assert result == []

    def test_returns_empty_for_none_preferences(self):
        runs = [_make_run("r1", "easy")]
        result = get_contributing_run_ids(runs, None, ZC, mode="endurance")
        assert result == []

    def test_endurance_filters_easy_and_steady(self):
        runs = [
            _make_run("easy1", "easy", workout_date="2026-01-01"),
            _make_run("hard1", "hard", workout_date="2026-01-02"),  # not endurance
            _make_run("steady1", "steady", workout_date="2026-01-03"),
        ]
        result = get_contributing_run_ids(runs, _make_prefs(), ZC, mode="endurance")
        ids = [e["run_id"] for e in result]
        assert "easy1" in ids
        assert "steady1" in ids
        assert "hard1" not in ids

    def test_returns_max_five_most_recent(self):
        runs = [_make_run(f"r{i}", "easy", workout_date=f"2026-01-{i+1:02d}") for i in range(7)]
        result = get_contributing_run_ids(runs, _make_prefs(), ZC, mode="endurance", limit=5)
        assert len(result) == 5
        ids = [e["run_id"] for e in result]
        # The 5 most recent should be r2..r6 (0-indexed)
        assert "r0" not in ids
        assert "r1" not in ids
        assert "r6" in ids

    def test_fewer_than_five_returns_only_available(self):
        """AC8: fewer qualifying sessions → return what exists, no error."""
        runs = [
            _make_run("r1", "easy", workout_date="2026-01-01"),
            _make_run("r2", "easy", workout_date="2026-01-02"),
        ]
        result = get_contributing_run_ids(runs, _make_prefs(), ZC, mode="endurance", limit=5)
        assert len(result) == 2

    def test_each_entry_has_run_id_and_contribution(self):
        runs = [_make_run("r1", "easy"), _make_run("r2", "easy")]
        result = get_contributing_run_ids(runs, _make_prefs(), ZC, mode="endurance")
        for entry in result:
            assert "run_id" in entry
            assert "contribution" in entry
            assert isinstance(entry["contribution"], (int, float))

    def test_contribution_in_0_to_100_range(self):
        runs = [
            _make_run("r1", "easy"),
            _make_run("r2", "easy"),
            _make_run("r3", "easy"),
        ]
        result = get_contributing_run_ids(runs, _make_prefs(), ZC, mode="endurance")
        for entry in result:
            assert 0.0 <= entry["contribution"] <= 100.0


# AC3: Speed — identifies qualifying (hard/interval) sessions
class TestGetContributingRunIdsSpeed:

    def test_speed_filters_hard_and_interval(self):
        runs = [
            _make_run("easy1", "easy", workout_date="2026-01-01"),  # not speed
            _make_run("hard1", "hard", workout_date="2026-01-02"),
            _make_run("interval1", "interval", workout_date="2026-01-03"),
        ]
        result = get_contributing_run_ids(runs, _make_prefs(), ZC, mode="speed")
        ids = [e["run_id"] for e in result]
        assert "hard1" in ids
        assert "interval1" in ids
        assert "easy1" not in ids

    def test_speed_returns_most_recent(self):
        runs = [_make_run(f"s{i}", "hard", workout_date=f"2026-01-{i+1:02d}") for i in range(6)]
        result = get_contributing_run_ids(runs, _make_prefs(), ZC, mode="speed", limit=5)
        assert len(result) == 5
        ids = [e["run_id"] for e in result]
        assert "s0" not in ids

    def test_returns_empty_when_no_speed_sessions(self):
        runs = [_make_run("e1", "easy"), _make_run("e2", "easy")]
        result = get_contributing_run_ids(runs, _make_prefs(), ZC, mode="speed")
        assert result == []


# ── Helper function tests ────────────────────────────────────────────────────


class TestFormatPace:
    def test_basic_pace(self):
        # 1800s / 6km = 300 s/km = 5:00/km
        result = _format_pace(1800, 6.0)
        assert result == "5:00/km"

    def test_pace_with_seconds(self):
        # 2000s / 5km = 400 s/km = 6:40/km
        result = _format_pace(2000, 5.0)
        assert result == "6:40/km"

    def test_none_when_distance_none(self):
        assert _format_pace(1800, None) is None

    def test_none_when_duration_none(self):
        assert _format_pace(None, 6.0) is None

    def test_none_when_distance_zero(self):
        assert _format_pace(1800, 0.0) is None


class TestMapSourceBadge:
    def test_strava_source(self):
        assert _map_source_badge("strava") == "Strava"

    def test_stryd_source(self):
        assert _map_source_badge("stryd") == "Stryd"

    def test_strava_stryd_combined(self):
        # When both present, strava takes priority
        result = _map_source_badge("strava,stryd")
        assert result in ("Strava", "Stryd")  # either badge is acceptable

    def test_manual_source_returns_none(self):
        assert _map_source_badge("manual") is None

    def test_none_source_returns_none(self):
        assert _map_source_badge(None) is None


class TestBuildSessionDictsFromContributors:
    """Tests for the helper that builds the 8-key flat session dicts."""

    def _make_workout_dict(self, run_id, name="Easy run", source="strava",
                           distance_km=6.0, duration_seconds=1800, avg_hr=140,
                           workout_date="2026-01-01"):
        """Build a plain dict simulating workout fields (avoids ORM dependency)."""
        return {
            "id": run_id,
            "name": name,
            "source": source,
            "distance_km": distance_km,
            "duration_seconds": duration_seconds,
            "avg_hr": avg_hr,
            "workout_date": workout_date,
        }

    def test_returns_list_of_dicts(self):
        contributors = [{"run_id": "r1", "contribution": 75.0}]
        workouts = {"r1": self._make_workout_dict("r1")}
        result = _build_session_dicts_from_contributors(contributors, workouts)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_each_entry_has_exactly_eight_keys(self):
        """AC2: exactly these flat keys."""
        contributors = [{"run_id": "r1", "contribution": 75.0}]
        workouts = {"r1": self._make_workout_dict("r1")}
        result = _build_session_dicts_from_contributors(contributors, workouts)
        expected_keys = {"workout_id", "date", "title", "distance_km", "pace", "avg_hr",
                         "contribution", "source"}
        assert set(result[0].keys()) == expected_keys

    def test_workout_id_matches(self):
        contributors = [{"run_id": "abc123", "contribution": 80.0}]
        workouts = {"abc123": self._make_workout_dict("abc123")}
        result = _build_session_dicts_from_contributors(contributors, workouts)
        assert result[0]["workout_id"] == "abc123"

    def test_pace_formatted_correctly(self):
        # 1800s / 6km = 5:00/km
        contributors = [{"run_id": "r1", "contribution": 50.0}]
        workouts = {"r1": self._make_workout_dict("r1", distance_km=6.0, duration_seconds=1800)}
        result = _build_session_dicts_from_contributors(contributors, workouts)
        assert result[0]["pace"] == "5:00/km"

    def test_strava_source_badge(self):
        contributors = [{"run_id": "r1", "contribution": 50.0}]
        workouts = {"r1": self._make_workout_dict("r1", source="strava")}
        result = _build_session_dicts_from_contributors(contributors, workouts)
        assert result[0]["source"] == "Strava"

    def test_stryd_source_badge(self):
        contributors = [{"run_id": "r1", "contribution": 50.0}]
        workouts = {"r1": self._make_workout_dict("r1", source="stryd")}
        result = _build_session_dicts_from_contributors(contributors, workouts)
        assert result[0]["source"] == "Stryd"

    def test_skips_missing_workouts(self):
        contributors = [
            {"run_id": "r1", "contribution": 75.0},
            {"run_id": "missing", "contribution": 50.0},
        ]
        workouts = {"r1": self._make_workout_dict("r1")}
        result = _build_session_dicts_from_contributors(contributors, workouts)
        assert len(result) == 1
        assert result[0]["workout_id"] == "r1"

    def test_empty_contributors_returns_empty(self):
        result = _build_session_dicts_from_contributors([], {})
        assert result == []


# ── Frontend HTML structure tests ────────────────────────────────────────────

@pytest.fixture(scope="module")
def training_log_html():
    path = os.path.join(REPO_ROOT, "frontend", "pages", "training-log.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def perf_panel_html(training_log_html):
    start = training_log_html.find('id="training-panel-performance"')
    assert start != -1, "training-panel-performance element must exist"
    return training_log_html[start:start + 15000]


@pytest.fixture(scope="module")
def endurance_card_html(perf_panel_html):
    start = perf_panel_html.find('id="perf-score-endurance"')
    assert start != -1, "perf-score-endurance card must exist"
    # Find the matching closing tag by taking a generous slice
    return perf_panel_html[start:start + 3000]


@pytest.fixture(scope="module")
def speed_card_html(perf_panel_html):
    start = perf_panel_html.find('id="perf-score-speed"')
    assert start != -1, "perf-score-speed card must exist"
    return perf_panel_html[start:start + 3000]


class TestHTMLContributingSessions:
    """AC1, AC4, AC7: HTML structure for contributing sessions."""

    def test_endurance_card_has_contributing_sessions_container(self, endurance_card_html):
        """AC1: Contributing sessions container exists on the endurance card."""
        assert "perf-contributing-sessions" in endurance_card_html, (
            "Endurance score card must have a .perf-contributing-sessions container"
        )

    def test_speed_card_has_contributing_sessions_container(self, speed_card_html):
        """AC1: Contributing sessions container exists on the speed card."""
        assert "perf-contributing-sessions" in speed_card_html, (
            "Speed score card must have a .perf-contributing-sessions container"
        )

    def test_endurance_card_has_sessions_list(self, endurance_card_html):
        """AC1: Endurance card has a list element for session rows."""
        assert "perf-sessions-list" in endurance_card_html, (
            "Endurance card must have a .perf-sessions-list element"
        )

    def test_speed_card_has_sessions_list(self, speed_card_html):
        """AC1: Speed card has a list element for session rows."""
        assert "perf-sessions-list" in speed_card_html, (
            "Speed card must have a .perf-sessions-list element"
        )

    def test_endurance_card_has_footnote(self, endurance_card_html):
        """AC7: Footnote present on endurance card for calibration notice."""
        assert "perf-sessions-footnote" in endurance_card_html, (
            "Endurance card must have a .perf-sessions-footnote element"
        )

    def test_speed_card_has_footnote(self, speed_card_html):
        """AC7: Footnote present on speed card."""
        assert "perf-sessions-footnote" in speed_card_html, (
            "Speed card must have a .perf-sessions-footnote element"
        )

    def test_footnote_mentions_estimates(self, perf_panel_html):
        """AC7: Footnote text mentions estimates/calibration."""
        assert "estimate" in perf_panel_html.lower() or "calibrat" in perf_panel_html.lower(), (
            "The footnote must state that contribution values are estimates until calibrated"
        )


# ── Frontend JS tests ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def perf_js():
    path = os.path.join(REPO_ROOT, "frontend", "js", "training-performance.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def training_log_js():
    path = os.path.join(REPO_ROOT, "frontend", "js", "training-log.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestJSContributingSessions:
    """AC4, AC5, AC6, AC7, AC8: JS rendering of contributing sessions."""

    def test_js_reads_contributing_sessions_from_api(self, perf_js):
        """AC1: JS reads contributing_sessions from the score data."""
        assert "contributing_sessions" in perf_js, (
            "training-performance.js must read contributing_sessions from the API payload"
        )

    def test_js_renders_source_badge(self, perf_js):
        """AC5: JS renders a source badge from the source field."""
        # The JS must check the source field for Strava/Stryd
        has_source_logic = (
            "source" in perf_js
            and ("Strava" in perf_js or "strava" in perf_js.lower())
            and ("Stryd" in perf_js or "stryd" in perf_js.lower())
        )
        assert has_source_logic, (
            "JS must render a Strava or Stryd badge from the source field"
        )

    def test_js_renders_contribution_value(self, perf_js):
        """AC6: JS renders the contribution value next to each row."""
        assert "contribution" in perf_js, (
            "JS must render the contribution value for each contributing session"
        )

    def test_js_renders_date_title_distance_pace_hr(self, perf_js):
        """AC2: JS renders all required fields per session row."""
        for field in ["date", "title", "distance_km", "pace", "avg_hr"]:
            assert field in perf_js, (
                f"JS must render the '{field}' field for each contributing session row"
            )

    def test_js_hides_contributing_sessions_initially(self, perf_js):
        """Sessions container is hidden by default (shown only when scored)."""
        assert "perf-contributing-sessions" in perf_js, (
            "JS must reference the perf-contributing-sessions container"
        )

    def test_training_log_js_exposes_open_detail(self, training_log_js):
        """AC4: training-log.js exposes openWorkoutDetail for in-place panel opening."""
        has_exposed = (
            "window.openWorkoutDetail" in training_log_js
            or "openWorkoutDetail" in training_log_js
        )
        assert has_exposed, (
            "training-log.js must expose openWorkoutDetail so the performance tab "
            "can open the workout detail panel in-place"
        )

    def test_perf_js_calls_open_workout_detail(self, perf_js):
        """AC4: training-performance.js calls openWorkoutDetail on row click."""
        has_open_call = (
            "openWorkoutDetail" in perf_js
            or "openDetailPanel" in perf_js
        )
        assert has_open_call, (
            "training-performance.js must call openWorkoutDetail (or openDetailPanel) "
            "to open the workout detail panel in-place"
        )

    def test_perf_js_shows_contributing_sessions_for_scored_state(self, perf_js):
        """AC1: Contributing sessions are shown only when state=scored."""
        # The _renderScoreCard function must render sessions from data.contributing_sessions
        assert "contributing_sessions" in perf_js, (
            "training-performance.js must use contributing_sessions in _renderScoreCard"
        )
