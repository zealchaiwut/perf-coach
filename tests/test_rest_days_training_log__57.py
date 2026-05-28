"""
Tests for issue #57: Show rest days in Training Log with daily_metrics data
Runs against UAT environment (http://127.0.0.1:9001)
"""
import os
import pathlib
import re

import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

# Dates chosen to be well outside normal seed data ranges so tests stay isolated.
_REST_ONLY_DATE   = "2025-03-10"   # has daily_metrics only — should appear as rest
_WORKOUT_DATE     = "2025-03-11"   # has workout only — no rest entry
_BOTH_DATE        = "2025-03-12"   # has both workout and daily_metrics — should show workout only
_ALL_NULL_DATE    = "2025-03-13"   # daily_metrics with all-null fields — must NOT appear
_NOTES_DATE       = "2025-03-14"   # daily_metrics with a long notes field
_RANGE_FROM       = "2025-03-01"
_RANGE_TO         = "2025-03-31"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    res = client.post("/api/users", json={"name": "RestDayTester57"})
    assert res.status_code in (200, 201), f"Failed to create test user: {res.text}"
    uid = res.json()["id"]
    yield uid
    # Cleanup: delete all test metrics and workouts, then user
    for d in [_REST_ONLY_DATE, _BOTH_DATE, _ALL_NULL_DATE, _NOTES_DATE]:
        client.delete(f"/api/daily-metrics/{uid}/{d}")
    client.delete(f"/api/users/{uid}")


def _put_metric(client, user_id, date_str, **fields):
    res = client.put(f"/api/daily-metrics/{user_id}/{date_str}", json=fields)
    assert res.status_code in (200, 201), f"PUT metric failed on {date_str}: {res.status_code} {res.text}"
    return res.json()


def _create_workout(client, user_id, date_str, *, workout_type="run", name="Test Workout", tss=None):
    payload = {
        "user_id": user_id,
        "name": name,
        "workout_date": date_str,
        "workout_type": workout_type,
        "exercises": [{"name": "Exercise", "duration": "30 min"}],
    }
    if tss is not None:
        payload["tss"] = tss
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout on {date_str}: {res.text}"
    return res.json()["id"]


def _get_log(client, user_id, from_date=_RANGE_FROM, to_date=_RANGE_TO, **params):
    query = f"/training_log?user_id={user_id}&from={from_date}&to={to_date}"
    for k, v in params.items():
        query += f"&{k}={v}"
    res = client.get(query)
    assert res.status_code == 200, f"GET /training_log failed: {res.status_code} {res.text}"
    return res.json()


def _all_entries(data):
    return [e for week in data["weeks"] for e in week["entries"]]


def _all_workouts(data):
    return [w for week in data["weeks"] for w in week["workouts"]]


# ── Seed helper ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def seed_data(client, test_user):
    """Create all test fixtures up front; yield; delete workouts (metrics cleaned in test_user)."""
    # Rest-only date: has daily_metrics, no workout
    _put_metric(client, test_user, _REST_ONLY_DATE, energy=3, sleep_quality=4,
                sleep_hours=7.5, resting_hr=52, hrv=65, mood=3)

    # Workout-only date: workout but NO daily_metrics
    w1 = _create_workout(client, test_user, _WORKOUT_DATE, workout_type="run",
                         name="Solo Run", tss=55)

    # Both date: workout + daily_metrics → rest entry must be suppressed
    w2 = _create_workout(client, test_user, _BOTH_DATE, workout_type="lift",
                         name="Lift Session", tss=40)
    _put_metric(client, test_user, _BOTH_DATE, energy=4, sleep_hours=7.0)

    # All-null date: daily_metrics with every field null → must NOT appear as rest
    _put_metric(client, test_user, _ALL_NULL_DATE)   # PUT with no body → all nulls

    # Notes date: long notes (>80 chars) for truncation check
    long_note = "A" * 100
    _put_metric(client, test_user, _NOTES_DATE, energy=5, notes=long_note)

    yield

    # Teardown workouts (metrics are cleaned in test_user fixture)
    for wid in [w1, w2]:
        client.delete(f"/api/workouts/{wid}")
    client.delete(f"/api/daily-metrics/{test_user}/{_NOTES_DATE}")


# ── AC-1: rest-only date appears as type=rest ─────────────────────────────────

def test_rest_only_date_appears_in_entries(client, test_user):
    data = _get_log(client, test_user)
    dates = [e["date"] for e in _all_entries(data)]
    assert _REST_ONLY_DATE in dates, f"Rest-only date {_REST_ONLY_DATE!r} missing from entries"


def test_rest_entry_has_type_rest(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_ONLY_DATE), None)
    assert entry is not None
    assert entry["type"] == "rest"


# ── AC-2/3: rest entry schema has metrics object ──────────────────────────────

def test_rest_entry_has_metrics_key(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_ONLY_DATE), None)
    assert entry is not None
    assert "metrics" in entry, "rest entry must have a 'metrics' key"


def test_rest_entry_metrics_contain_seeded_values(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_ONLY_DATE), None)
    m = entry["metrics"]
    assert m["energy"]        == 3
    assert m["sleep_quality"] == 4
    assert m["sleep_hours"]   == 7.5
    assert m["resting_hr"]    == 52
    assert m["hrv"]           == 65
    assert m["mood"]          == 3


def test_rest_entry_metrics_has_all_expected_keys(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_ONLY_DATE), None)
    m = entry["metrics"]
    for key in ("energy", "mood", "sleep_quality", "sleep_hours", "resting_hr", "hrv", "notes"):
        assert key in m, f"metrics missing key {key!r}"


# ── AC-5: day with both workout and daily_metrics shows workout only ───────────

def test_workout_date_not_in_rest_entries(client, test_user):
    data = _get_log(client, test_user)
    rest_entries = [e for e in _all_entries(data) if e["type"] == "rest"]
    rest_dates = [e["date"] for e in rest_entries]
    assert _BOTH_DATE not in rest_dates, (
        f"Date {_BOTH_DATE!r} has a workout — rest entry should be suppressed"
    )


def test_both_date_shows_workout_entry(client, test_user):
    data = _get_log(client, test_user)
    workout_entries = [e for e in _all_entries(data) if e.get("type") != "rest"]
    workout_dates = [e["date"] for e in workout_entries]
    assert _BOTH_DATE in workout_dates


# ── AC-6: include_rest param ──────────────────────────────────────────────────

def test_include_rest_true_includes_rest_entries(client, test_user):
    data = _get_log(client, test_user, include_rest="true")
    rest_entries = [e for e in _all_entries(data) if e["type"] == "rest"]
    assert len(rest_entries) > 0


def test_include_rest_false_omits_rest_entries(client, test_user):
    data = _get_log(client, test_user, include_rest="false")
    rest_entries = [e for e in _all_entries(data) if e["type"] == "rest"]
    assert rest_entries == [], "include_rest=false must return no rest entries"


def test_include_rest_defaults_to_true(client, test_user):
    """Calling without include_rest param should behave like include_rest=true."""
    data_default = _get_log(client, test_user)
    data_true    = _get_log(client, test_user, include_rest="true")
    default_rests = [e for e in _all_entries(data_default) if e["type"] == "rest"]
    true_rests    = [e for e in _all_entries(data_true)    if e["type"] == "rest"]
    assert len(default_rests) == len(true_rests)


# ── AC-7: type filter hides rest days ─────────────────────────────────────────

def test_type_filter_run_hides_rest_entries(client, test_user):
    data = _get_log(client, test_user, types="run")
    rest_entries = [e for e in _all_entries(data) if e["type"] == "rest"]
    assert rest_entries == [], "type filter != all must hide rest entries"


def test_type_filter_lift_hides_rest_entries(client, test_user):
    data = _get_log(client, test_user, types="lift")
    rest_entries = [e for e in _all_entries(data) if e["type"] == "rest"]
    assert rest_entries == []


def test_type_filter_all_shows_rest_entries(client, test_user):
    data = _get_log(client, test_user, types="all")
    rest_entries = [e for e in _all_entries(data) if e["type"] == "rest"]
    assert len(rest_entries) > 0, "types=all must show rest entries"


# ── AC-8: empty state ─────────────────────────────────────────────────────────

def test_empty_range_returns_empty_weeks(client, test_user):
    data = _get_log(client, test_user, from_date="2020-01-01", to_date="2020-01-31")
    assert data["weeks"] == []


def test_type_filter_with_no_matching_workouts_returns_empty(client, test_user):
    # No wod workouts seeded for this user in the test range
    data = _get_log(client, test_user, types="wod")
    assert data["weeks"] == []


# ── AC-9: week summary excludes rest days ─────────────────────────────────────

def test_week_summary_workout_count_excludes_rest_days(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        rest_count = sum(1 for e in week["entries"] if e["type"] == "rest")
        workout_count = len(week["workouts"])
        assert week["summary"]["workout_count"] == workout_count, (
            f"Week {week['week_start']}: summary.workout_count should be {workout_count}, "
            f"not {week['summary']['workout_count']} (rest_count={rest_count})"
        )


def test_week_summary_tss_excludes_rest_days(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        expected_tss = sum(w.get("tss") or 0 for w in week["workouts"])
        assert week["summary"]["total_tss"] == expected_tss


def test_week_summary_distance_excludes_rest_days(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        expected_dist = sum(w.get("distance_km") or 0 for w in week["workouts"])
        assert week["summary"]["total_distance_km"] == expected_dist


# ── AC-4: chronological order ─────────────────────────────────────────────────

def test_entries_within_week_are_in_descending_date_order(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        dates = [e["date"] for e in week["entries"]]
        assert dates == sorted(dates, reverse=True), (
            f"Week {week['week_start']} entries not in descending date order: {dates}"
        )


def test_rest_entry_interleaved_with_workouts_in_correct_position(client, test_user):
    """Workout on Mar-11 and rest day on Mar-10 — rest day must come after in desc order."""
    data = _get_log(client, test_user)
    entries = _all_entries(data)
    mar10 = next((i for i, e in enumerate(entries) if e["date"] == _REST_ONLY_DATE), None)
    mar11 = next((i for i, e in enumerate(entries) if e["date"] == _WORKOUT_DATE), None)
    if mar10 is not None and mar11 is not None:
        assert mar11 < mar10, (
            f"Workout {_WORKOUT_DATE!r} (idx={mar11}) should appear before rest {_REST_ONLY_DATE!r} "
            f"(idx={mar10}) in descending order"
        )


# ── All-null metrics must not appear ─────────────────────────────────────────

def test_all_null_daily_metrics_not_a_rest_entry(client, test_user):
    data = _get_log(client, test_user)
    rest_dates = [e["date"] for e in _all_entries(data) if e["type"] == "rest"]
    assert _ALL_NULL_DATE not in rest_dates, (
        f"Date {_ALL_NULL_DATE!r} has all-null daily_metrics and must NOT appear as rest"
    )


# ── REST entry must not have workout-only keys ─────────────────────────────────

def test_rest_entry_has_no_workout_keys(client, test_user):
    data = _get_log(client, test_user)
    rest_entry = next((e for e in _all_entries(data) if e["type"] == "rest"), None)
    assert rest_entry is not None
    for key in ("id", "title", "tss", "duration_minutes", "distance_km", "avg_hr", "source"):
        assert key not in rest_entry, f"rest entry must not have workout key {key!r}"


# ── Frontend: log.html has required elements ──────────────────────────────────

@pytest.fixture(scope="module")
def log_html():
    path = pathlib.Path(__file__).parent.parent / "log.html"
    assert path.exists(), "log.html not found at repo root"
    return path.read_text(encoding="utf-8")


def test_log_html_has_rest_day_row_css_class(log_html):
    assert "rest-day-row" in log_html


def test_log_html_has_rest_badge_css_class(log_html):
    assert "rest-badge" in log_html


def test_log_html_has_rest_metrics_css_class(log_html):
    assert "rest-metrics" in log_html


def test_log_html_loads_mock_data_js(log_html):
    assert "mock-data.js" in log_html


def test_log_html_loads_training_log_js(log_html):
    assert "training-log.js" in log_html


def test_log_html_has_empty_state_message(training_log_js):
    assert "No workouts in this range" in training_log_js


# ── Frontend: training-log.js renders rest days ───────────────────────────────

@pytest.fixture(scope="module")
def training_log_js():
    path = pathlib.Path(__file__).parent.parent / "js" / "training-log.js"
    assert path.exists(), "js/training-log.js not found"
    return path.read_text(encoding="utf-8")


def test_training_log_js_renders_rest_day_row(training_log_js):
    assert "renderRestDayRow" in training_log_js


def test_training_log_js_uses_rest_badge(training_log_js):
    assert "rest-badge" in training_log_js


def test_training_log_js_shows_energy_metric(training_log_js):
    assert "energy" in training_log_js.lower()


def test_training_log_js_shows_rhr_metric(training_log_js):
    assert "resting_hr" in training_log_js or "RHR" in training_log_js


def test_training_log_js_shows_hrv_metric(training_log_js):
    assert "hrv" in training_log_js.lower()


def test_training_log_js_truncates_notes_at_80_chars(training_log_js):
    assert "80" in training_log_js


def test_training_log_js_hides_rest_when_type_filter_active(training_log_js):
    # mockFetch should filter out rest days when types != all
    assert "all" in training_log_js and "filteredRest" in training_log_js or (
        "types" in training_log_js and "rest" in training_log_js
    )


def test_training_log_js_type_is_rest_check(training_log_js):
    assert "=== 'rest'" in training_log_js or '=== "rest"' in training_log_js


def test_training_log_js_week_summary_uses_workouts_not_entries(training_log_js):
    # Summary aggregates must iterate workouts, not entries
    assert "week.workouts" in training_log_js or "ws.length" in training_log_js or \
           "workouts.length" in training_log_js


# ── mock-data.js has MOCK_REST_DAYS ──────────────────────────────────────────

@pytest.fixture(scope="module")
def mock_data_js():
    path = pathlib.Path(__file__).parent.parent / "js" / "mock-data.js"
    assert path.exists(), "js/mock-data.js not found"
    return path.read_text(encoding="utf-8")


def test_mock_data_js_has_mock_rest_days(mock_data_js):
    assert "MOCK_REST_DAYS" in mock_data_js


def test_mock_rest_days_have_type_rest(mock_data_js):
    assert '"type": "rest"' in mock_data_js or "type: 'rest'" in mock_data_js


def test_mock_rest_days_dates_do_not_overlap_workouts(mock_data_js):
    """Basic sanity: rest day dates and workout dates should be disjoint in mock data."""
    rest_dates = re.findall(r"MOCK_REST_DAYS.*?(?=const\s|\Z)", mock_data_js, re.DOTALL)
    workout_dates = re.findall(r"MOCK_WORKOUTS.*?(?=const\s|\Z)", mock_data_js, re.DOTALL)
    if rest_dates and workout_dates:
        rest_iso = set(re.findall(r"date:\s*'(\d{4}-\d{2}-\d{2})'", rest_dates[0]))
        workout_iso = set(re.findall(r"date:\s*'(\d{4}-\d{2}-\d{2})'", workout_dates[0]))
        overlap = rest_iso & workout_iso
        assert not overlap, f"MOCK_REST_DAYS and MOCK_WORKOUTS share dates: {overlap}"


# ── /training_log route must exist ────────────────────────────────────────────

def test_training_log_route_exists(client, test_user):
    res = client.get(f"/training_log?user_id={test_user}&from=2025-03-01&to=2025-03-31")
    assert res.status_code == 200


def test_training_log_returns_weeks_key(client, test_user):
    data = _get_log(client, test_user)
    assert "weeks" in data


def test_training_log_invalid_user_returns_400(client):
    res = client.get("/training_log?user_id=not-a-uuid&from=2025-03-01&to=2025-03-31")
    assert res.status_code == 400


def test_training_log_invalid_date_returns_400(client, test_user):
    res = client.get(f"/training_log?user_id={test_user}&from=bad-date&to=2025-03-31")
    assert res.status_code == 400
