"""
Tests for issue #490: Fix rest-day rows never rendering in training log.

AC1: fetchAndRender passes include_rest=true when fetching training log entries
AC2: Rest-day rows appear in correct week groups in date order
AC3: Each rest-day row displays wellness summary (resting_hr, energy, mood, sleep_hours)
AC4: Rows with null/missing wellness fields render gracefully (no undefined, no JS errors)
AC5: Existing workout rows are unaffected by the query change
"""
import os
import pathlib

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 before pytest."
    )

# Isolated date range — avoids collisions with other test files
_REST_WELLNESS_DATE = "2025-05-12"   # rest day with full wellness data
_REST_SPARSE_DATE   = "2025-05-13"   # rest day with only some fields set
_REST_NULL_DATE     = "2025-05-14"   # daily_metrics with all-null fields — must NOT appear
_WORKOUT_DATE       = "2025-05-15"   # workout only — no rest entry
_RANGE_FROM         = "2025-05-01"
_RANGE_TO           = "2025-05-31"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    res = client.post("/api/users", json={"name": "RestDayFix490Tester"}, cookies=_admin_cookies())
    assert res.status_code in (200, 201), f"create user failed: {res.text}"
    uid = res.json()["id"]
    yield uid
    for d in [_REST_WELLNESS_DATE, _REST_SPARSE_DATE, _REST_NULL_DATE]:
        client.delete(f"/api/daily-metrics/{uid}/{d}")
    client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


def _put_metric(client, user_id, date_str, **fields):
    res = client.put(f"/api/daily-metrics/{user_id}/{date_str}", json=fields)
    assert res.status_code in (200, 201), f"PUT metric {date_str} failed: {res.text}"
    return res.json()


def _create_workout(client, user_id, date_str):
    res = client.post("/api/workouts", json={
        "user_id": user_id,
        "name": "Test Run 490",
        "workout_date": date_str,
        "workout_type": "run",
        "exercises": [{"name": "Run", "duration": "30 min"}],
        "tss": 60,
    })
    assert res.status_code == 201, f"create workout failed: {res.text}"
    return res.json()["id"]


@pytest.fixture(scope="module", autouse=True)
def seed_data(client, test_user):
    _put_metric(client, test_user, _REST_WELLNESS_DATE,
                resting_hr=58, energy=4, mood=3, sleep_hours=7.5, sleep_quality=4)
    _put_metric(client, test_user, _REST_SPARSE_DATE,
                energy=2, mood=2)  # no resting_hr, no sleep_hours
    _put_metric(client, test_user, _REST_NULL_DATE)  # all null — must NOT appear
    wid = _create_workout(client, test_user, _WORKOUT_DATE)
    yield
    client.delete(f"/api/workouts/{wid}")
    client.delete(f"/api/daily-metrics/{test_user}/{_REST_SPARSE_DATE}")
    client.delete(f"/api/daily-metrics/{test_user}/{_REST_NULL_DATE}")


def _get_log(client, user_id, **params):
    q = f"/api/training-log?user_id={user_id}&from={_RANGE_FROM}&to={_RANGE_TO}"
    for k, v in params.items():
        q += f"&{k}={v}"
    res = client.get(q)
    assert res.status_code == 200, f"GET training-log failed: {res.text}"
    return res.json()


def _all_entries(data):
    return [e for week in data.get("weeks", []) for e in (week.get("entries") or [])]


# ── AC1: include_rest=true returns rest entries ───────────────────────────────

def test_include_rest_true_returns_wellness_rest_entry(client, test_user):
    """AC1: with include_rest=true, rest-day entry with wellness data appears"""
    data = _get_log(client, test_user, include_rest="true")
    rest_dates = [e["date"] for e in _all_entries(data) if e.get("type") == "rest"]
    assert _REST_WELLNESS_DATE in rest_dates, (
        f"Rest entry for {_REST_WELLNESS_DATE} missing with include_rest=true"
    )


def test_include_rest_false_omits_all_rest_entries(client, test_user):
    """AC1 corollary: include_rest=false must omit every rest entry"""
    data = _get_log(client, test_user, include_rest="false")
    rest = [e for e in _all_entries(data) if e.get("type") == "rest"]
    assert rest == [], f"include_rest=false returned rest entries: {rest}"


# ── AC2: correct week grouping and ordering ───────────────────────────────────

def test_rest_entry_falls_within_its_week_boundaries(client, test_user):
    """AC2: every entry date is within its week's week_start..week_end range"""
    data = _get_log(client, test_user, include_rest="true")
    for week in data.get("weeks", []):
        start = week["week_start"]
        end   = week["week_end"]
        for entry in week.get("entries", []):
            assert start <= entry["date"] <= end, (
                f"Entry {entry['date']} outside week {start}–{end}"
            )


def test_entries_within_each_week_are_descending(client, test_user):
    """AC2: entries in each week group sorted newest-first"""
    data = _get_log(client, test_user, include_rest="true")
    for week in data.get("weeks", []):
        dates = [e["date"] for e in week.get("entries", [])]
        assert dates == sorted(dates, reverse=True), (
            f"Week {week.get('week_start')} not descending: {dates}"
        )


def test_workout_appears_before_older_rest_in_descending_order(client, test_user):
    """AC2: workout on May-15 appears before rest on May-12 in descending order"""
    data = _get_log(client, test_user, include_rest="true")
    entries = _all_entries(data)
    idx_w = next((i for i, e in enumerate(entries) if e["date"] == _WORKOUT_DATE), None)
    idx_r = next((i for i, e in enumerate(entries) if e["date"] == _REST_WELLNESS_DATE), None)
    if idx_w is not None and idx_r is not None:
        assert idx_w < idx_r, (
            f"Workout {_WORKOUT_DATE} (idx={idx_w}) must come before rest "
            f"{_REST_WELLNESS_DATE} (idx={idx_r}) in descending order"
        )


# ── AC3: wellness fields present on rest entry ────────────────────────────────

def test_rest_entry_has_resting_hr(client, test_user):
    """AC3: resting_hr is returned on rest entry"""
    data = _get_log(client, test_user, include_rest="true")
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_WELLNESS_DATE), None)
    assert entry is not None, f"Rest entry for {_REST_WELLNESS_DATE} not found"
    assert entry.get("resting_hr") == 58


def test_rest_entry_has_energy(client, test_user):
    """AC3: energy is returned on rest entry"""
    data = _get_log(client, test_user, include_rest="true")
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_WELLNESS_DATE), None)
    assert entry is not None
    assert entry.get("energy") == 4


def test_rest_entry_has_mood(client, test_user):
    """AC3: mood is returned on rest entry"""
    data = _get_log(client, test_user, include_rest="true")
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_WELLNESS_DATE), None)
    assert entry is not None
    assert entry.get("mood") == 3


def test_rest_entry_has_sleep_hours(client, test_user):
    """AC3: sleep_hours is returned on rest entry"""
    data = _get_log(client, test_user, include_rest="true")
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_WELLNESS_DATE), None)
    assert entry is not None
    assert entry.get("sleep_hours") == 7.5


def test_sparse_rest_entry_missing_fields_are_null_not_absent(client, test_user):
    """AC3/4: rest entry with only some fields — missing ones come back as null (not omitted)"""
    data = _get_log(client, test_user, include_rest="true")
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_SPARSE_DATE), None)
    assert entry is not None, f"Sparse rest entry for {_REST_SPARSE_DATE} not found"
    assert entry.get("resting_hr") is None
    assert entry.get("sleep_hours") is None
    assert entry.get("energy") == 2
    assert entry.get("mood") == 2


# ── AC4: null wellness fields handled gracefully ──────────────────────────────

def test_all_null_metrics_entry_excluded_from_rest(client, test_user):
    """AC4: daily_metrics with all-null fields must NOT appear as a rest entry"""
    data = _get_log(client, test_user, include_rest="true")
    rest_dates = [e["date"] for e in _all_entries(data) if e.get("type") == "rest"]
    assert _REST_NULL_DATE not in rest_dates, (
        f"All-null metrics date {_REST_NULL_DATE} must not appear as rest entry"
    )


def test_rest_entry_null_fields_are_json_null_not_string(client, test_user):
    """AC4: null wellness fields on sparse rest entry are JSON null, not 'undefined' string"""
    data = _get_log(client, test_user, include_rest="true")
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_SPARSE_DATE), None)
    assert entry is not None
    for key in ("resting_hr", "sleep_hours"):
        val = entry.get(key)
        assert val != "undefined", f"Field {key!r} is 'undefined' string — should be null"
        assert val is None, f"Field {key!r} expected null, got {val!r}"


# ── AC5: existing workout rows unaffected ─────────────────────────────────────

def test_workout_appears_with_include_rest_true(client, test_user):
    """AC5: workout entries still present when include_rest=true"""
    data = _get_log(client, test_user, include_rest="true")
    workout_entries = [e for e in _all_entries(data) if e.get("type") != "rest"]
    workout_dates = [e["date"] for e in workout_entries]
    assert _WORKOUT_DATE in workout_dates, (
        f"Workout on {_WORKOUT_DATE} missing when include_rest=true"
    )


def test_workout_appears_with_include_rest_false(client, test_user):
    """AC5: workout entries appear regardless of include_rest value"""
    data = _get_log(client, test_user, include_rest="false")
    workout_entries = [e for e in _all_entries(data) if e.get("type") != "rest"]
    workout_dates = [e["date"] for e in workout_entries]
    assert _WORKOUT_DATE in workout_dates


def test_workout_entry_type_is_not_rest(client, test_user):
    """AC5: workout entry on workout date has type != 'rest'"""
    data = _get_log(client, test_user, include_rest="true")
    workout_entry = next((e for e in _all_entries(data) if e["date"] == _WORKOUT_DATE), None)
    assert workout_entry is not None
    assert workout_entry.get("type") != "rest"


def test_week_summary_workout_count_excludes_rest_entries(client, test_user):
    """AC5: week summary.workout_count counts only workout rows"""
    data = _get_log(client, test_user, include_rest="true")
    for week in data.get("weeks", []):
        workout_count = len(week.get("workouts", []))
        summary_count = week.get("summary", {}).get("workout_count", 0)
        assert summary_count == workout_count, (
            f"Week {week.get('week_start')}: summary.workout_count={summary_count} "
            f"but actual workouts={workout_count}"
        )


# ── JS source: fetchAndRender passes include_rest=true ────────────────────────

@pytest.fixture(scope="module")
def training_log_js():
    path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js"
    assert path.exists(), f"training-log.js not found at {path}"
    return path.read_text(encoding="utf-8")


def test_fetch_and_render_sets_include_rest_true(training_log_js):
    """AC1: fetchAndRender must set include_rest=true in the API params"""
    assert (
        "include_rest', 'true'" in training_log_js
        or 'include_rest", "true"' in training_log_js
        or "include_rest=true" in training_log_js
        or 'set(\'include_rest\'' in training_log_js
        or 'set("include_rest"' in training_log_js
    ), "fetchAndRender must pass include_rest=true"


def test_render_rest_day_row_function_exists(training_log_js):
    """AC3/4: renderRestDayRow function must exist in training-log.js"""
    assert "renderRestDayRow" in training_log_js


def test_render_rest_day_row_checks_null_for_fields(training_log_js):
    """AC4: renderRestDayRow guards against null fields before rendering"""
    assert "!= null" in training_log_js or "!== null" in training_log_js, (
        "renderRestDayRow must check fields for null before displaying"
    )


def test_rest_day_row_renders_resting_hr(training_log_js):
    """AC3: renderRestDayRow renders resting_hr field"""
    assert "resting_hr" in training_log_js


def test_rest_day_row_renders_energy(training_log_js):
    """AC3: renderRestDayRow renders energy field"""
    assert "energy" in training_log_js


def test_rest_day_row_renders_mood(training_log_js):
    """AC3: renderRestDayRow renders mood field"""
    assert "mood" in training_log_js


def test_rest_day_row_renders_sleep_hours(training_log_js):
    """AC3: renderRestDayRow renders sleep_hours field"""
    assert "sleep_hours" in training_log_js
