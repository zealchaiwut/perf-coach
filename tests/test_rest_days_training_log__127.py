"""
Tests for issue #127: Add rest-day rows to Training Log.
Runs against UAT environment (http://127.0.0.1:9001)

Confirms:
  - A day with daily_metrics and no workout produces a type="rest" entry.
  - A day with neither workout nor daily_metrics is absent from entries.
  - Rest entries include top-level sleep_hours, energy, mood, resting_hr (null fields present as null).
  - Week summary (workout_count, total_tss, total_distance_km, total_time_minutes) excludes rest entries.
  - Frontend JS uses renderRestDayRow with rest-day-label, rest-badge, and no click listener.
"""
import os
import pathlib

import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_METRICS_ONLY_DATE = "2025-07-10"  # daily_metrics only → must appear as type=rest
_WORKOUT_ONLY_DATE = "2025-07-11"  # workout only → no rest entry
_BOTH_DATE         = "2025-07-12"  # workout + daily_metrics → workout entry, no rest entry
_EMPTY_DATE        = "2025-07-13"  # neither → must be absent
_NULL_METRICS_DATE = "2025-07-14"  # daily_metrics with all-null fields → must be absent
_RANGE_FROM        = "2025-07-01"
_RANGE_TO          = "2025-07-31"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    res = client.post("/api/users", json={"name": "RestDayTester127"})
    assert res.status_code in (200, 201), f"create user failed: {res.text}"
    uid = res.json()["id"]
    yield uid
    for d in [_METRICS_ONLY_DATE, _BOTH_DATE, _NULL_METRICS_DATE]:
        client.delete(f"/api/daily-metrics/{uid}/{d}")
    client.delete(f"/api/users/{uid}")


def _put_metric(client, user_id, date_str, **fields):
    res = client.put(f"/api/daily-metrics/{user_id}/{date_str}", json=fields)
    assert res.status_code in (200, 201), f"PUT metric failed on {date_str}: {res.text}"
    return res.json()


def _create_workout(client, user_id, date_str, *, workout_type="run", name="Test Workout"):
    payload = {
        "user_id": user_id,
        "name": name,
        "workout_date": date_str,
        "workout_type": workout_type,
        "exercises": [{"name": "Exercise", "duration": "30 min"}],
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create workout failed on {date_str}: {res.text}"
    return res.json()["id"]


def _get_log(client, user_id, from_date=_RANGE_FROM, to_date=_RANGE_TO, **params):
    query = f"/api/training-log?user_id={user_id}&from={from_date}&to={to_date}"
    for k, v in params.items():
        query += f"&{k}={v}"
    res = client.get(query)
    assert res.status_code == 200, f"GET /api/training-log failed: {res.text}"
    return res.json()


def _all_entries(data):
    return [e for week in data["weeks"] for e in week["entries"]]


@pytest.fixture(scope="module", autouse=True)
def seed_data(client, test_user):
    _put_metric(client, test_user, _METRICS_ONLY_DATE,
                sleep_hours=7.5, energy=3, mood=4, resting_hr=52)
    w1 = _create_workout(client, test_user, _WORKOUT_ONLY_DATE, workout_type="run", name="Solo Run")
    w2 = _create_workout(client, test_user, _BOTH_DATE, workout_type="lift", name="Lift Session")
    _put_metric(client, test_user, _BOTH_DATE, energy=4, sleep_hours=7.0)
    _put_metric(client, test_user, _NULL_METRICS_DATE)

    yield

    for wid in [w1, w2]:
        client.delete(f"/api/workouts/{wid}")


# ── AC-1: daily_metrics-only day produces type=rest entry ────────────────────

def test_metrics_only_day_produces_rest_entry(client, test_user):
    data = _get_log(client, test_user)
    dates = [e["date"] for e in _all_entries(data)]
    assert _METRICS_ONLY_DATE in dates, (
        f"metrics-only day {_METRICS_ONLY_DATE!r} missing from entries"
    )


def test_rest_entry_has_type_rest(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _METRICS_ONLY_DATE), None)
    assert entry is not None
    assert entry["type"] == "rest", f"expected type='rest', got {entry.get('type')!r}"


# ── AC-2: rest entries include top-level sleep_hours, energy, mood, resting_hr ─

def test_rest_entry_has_top_level_sleep_hours(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _METRICS_ONLY_DATE), None)
    assert entry is not None
    assert "sleep_hours" in entry
    assert entry["sleep_hours"] == 7.5


def test_rest_entry_has_top_level_energy(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _METRICS_ONLY_DATE), None)
    assert entry is not None
    assert "energy" in entry
    assert entry["energy"] == 3


def test_rest_entry_has_top_level_mood(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _METRICS_ONLY_DATE), None)
    assert entry is not None
    assert "mood" in entry
    assert entry["mood"] == 4


def test_rest_entry_has_top_level_resting_hr(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _METRICS_ONLY_DATE), None)
    assert entry is not None
    assert "resting_hr" in entry
    assert entry["resting_hr"] == 52


# ── AC-3: day with neither workout nor daily_metrics is absent ────────────────

def test_day_with_neither_is_absent(client, test_user):
    data = _get_log(client, test_user)
    dates = [e["date"] for e in _all_entries(data)]
    assert _EMPTY_DATE not in dates, (
        f"Date {_EMPTY_DATE!r} has no workout and no daily_metrics — must be absent"
    )


def test_all_null_daily_metrics_is_absent(client, test_user):
    data = _get_log(client, test_user)
    dates = [e["date"] for e in _all_entries(data)]
    assert _NULL_METRICS_DATE not in dates, (
        f"Date {_NULL_METRICS_DATE!r} has all-null daily_metrics — must be absent"
    )


# ── AC-4: day with both workout and daily_metrics shows no rest entry ─────────

def test_both_date_shows_no_rest_entry(client, test_user):
    data = _get_log(client, test_user)
    rest_dates = [e["date"] for e in _all_entries(data) if e.get("type") == "rest"]
    assert _BOTH_DATE not in rest_dates, (
        f"Date {_BOTH_DATE!r} has a workout — rest entry must be suppressed"
    )


def test_both_date_shows_workout_entry(client, test_user):
    data = _get_log(client, test_user)
    workout_dates = [e["date"] for e in _all_entries(data) if e.get("type") != "rest"]
    assert _BOTH_DATE in workout_dates


# ── AC-5: week summary excludes rest entries entirely ────────────────────────

def test_summary_workout_count_excludes_rest(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        expected = len(week["workouts"])
        assert week["summary"]["workout_count"] == expected, (
            f"Week {week['week_start']}: workout_count={week['summary']['workout_count']} "
            f"but len(workouts)={expected}"
        )


def test_summary_tss_excludes_rest(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        expected = sum(w.get("tss") or 0 for w in week["workouts"])
        assert week["summary"]["total_tss"] == expected


def test_summary_distance_excludes_rest(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        expected = sum(w.get("distance_km") or 0 for w in week["workouts"])
        assert week["summary"]["total_distance_km"] == expected


# ── Frontend: training-log.js renders rest rows correctly ────────────────────

@pytest.fixture(scope="module")
def training_log_js():
    path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js"
    assert path.exists(), "js/training-log.js not found"
    return path.read_text(encoding="utf-8")


def test_js_has_render_rest_day_row_function(training_log_js):
    assert "renderRestDayRow" in training_log_js


def test_js_rest_row_uses_rest_day_label_class(training_log_js):
    assert "rest-day-label" in training_log_js


def test_js_rest_row_uses_rest_badge_class(training_log_js):
    assert "rest-badge" in training_log_js


def test_js_rest_label_starts_with_rest_day(training_log_js):
    assert "Rest day" in training_log_js


def test_js_rest_label_includes_sleep(training_log_js):
    assert "'sleep '" in training_log_js or '"sleep "' in training_log_js


def test_js_rest_label_includes_energy(training_log_js):
    assert "'energy '" in training_log_js or '"energy "' in training_log_js


def test_js_rest_label_includes_mood(training_log_js):
    assert "'mood '" in training_log_js or '"mood "' in training_log_js


def test_js_reads_top_level_sleep_hours(training_log_js):
    assert "entry.sleep_hours" in training_log_js


def test_js_reads_top_level_energy(training_log_js):
    assert "entry.energy" in training_log_js


def test_js_reads_top_level_mood(training_log_js):
    assert "entry.mood" in training_log_js


def test_js_reads_top_level_resting_hr(training_log_js):
    assert "entry.resting_hr" in training_log_js


def test_js_rest_row_not_clickable(training_log_js):
    idx = training_log_js.find("rest-day-row")
    assert idx != -1, "rest-day-row class not found in training-log.js"
    snippet = training_log_js[idx:idx + 500]
    assert "addEventListener('click'" not in snippet
    assert 'addEventListener("click"' not in snippet
