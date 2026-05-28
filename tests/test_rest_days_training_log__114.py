"""
Tests for issue #114: Show rest-day rows in Training Log for metric-only days.
Runs against UAT environment (http://127.0.0.1:9001)

Covers acceptance criteria that extend or differ from issue #57:
  - API exposes top-level sleep_hours, energy, mood, resting_hr on rest entries
  - Frontend label format: "Rest day - sleep Xh, energy Y, mood Z"
  - Italic muted styling (.rest-day-label) in log.html
  - Rest rows are not clickable (no click handler wired)
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

_REST_DATE    = "2025-04-10"
_WORKOUT_DATE = "2025-04-11"
_BOTH_DATE    = "2025-04-12"
_RANGE_FROM   = "2025-04-01"
_RANGE_TO     = "2025-04-30"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    res = client.post("/api/users", json={"name": "RestDayTester114"})
    assert res.status_code in (200, 201), f"Failed to create test user: {res.text}"
    uid = res.json()["id"]
    yield uid
    for d in [_REST_DATE, _BOTH_DATE]:
        client.delete(f"/api/daily-metrics/{uid}/{d}")
    client.delete(f"/api/users/{uid}")


def _put_metric(client, user_id, date_str, **fields):
    res = client.put(f"/api/daily-metrics/{user_id}/{date_str}", json=fields)
    assert res.status_code in (200, 201), f"PUT metric failed on {date_str}: {res.status_code} {res.text}"
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
    assert res.status_code == 201, f"Failed to create workout on {date_str}: {res.text}"
    return res.json()["id"]


def _get_log(client, user_id, from_date=_RANGE_FROM, to_date=_RANGE_TO, **params):
    query = f"/api/training-log?user_id={user_id}&from={from_date}&to={to_date}"
    for k, v in params.items():
        query += f"&{k}={v}"
    res = client.get(query)
    assert res.status_code == 200, f"GET /api/training-log failed: {res.status_code} {res.text}"
    return res.json()


def _all_entries(data):
    return [e for week in data["weeks"] for e in week["entries"]]


@pytest.fixture(scope="module", autouse=True)
def seed_data(client, test_user):
    _put_metric(client, test_user, _REST_DATE,
                energy=3, sleep_hours=7.4, mood=4, resting_hr=52, hrv=65)

    w1 = _create_workout(client, test_user, _WORKOUT_DATE, workout_type="run", name="Morning Run")

    w2 = _create_workout(client, test_user, _BOTH_DATE, workout_type="lift", name="Lift Session")
    _put_metric(client, test_user, _BOTH_DATE, energy=4, sleep_hours=7.0)

    yield

    for wid in [w1, w2]:
        client.delete(f"/api/workouts/{wid}")
    client.delete(f"/api/daily-metrics/{test_user}/{_REST_DATE}")
    client.delete(f"/api/daily-metrics/{test_user}/{_BOTH_DATE}")


# ── AC-1: rest entry has top-level sleep_hours ────────────────────────────────

def test_rest_entry_has_top_level_sleep_hours(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_DATE and e["type"] == "rest"), None)
    assert entry is not None, f"No rest entry found for {_REST_DATE}"
    assert "sleep_hours" in entry, "rest entry must have top-level 'sleep_hours'"
    assert entry["sleep_hours"] == 7.4


def test_rest_entry_has_top_level_energy(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_DATE and e["type"] == "rest"), None)
    assert entry is not None
    assert "energy" in entry, "rest entry must have top-level 'energy'"
    assert entry["energy"] == 3


def test_rest_entry_has_top_level_mood(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_DATE and e["type"] == "rest"), None)
    assert entry is not None
    assert "mood" in entry, "rest entry must have top-level 'mood'"
    assert entry["mood"] == 4


def test_rest_entry_has_top_level_resting_hr(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_DATE and e["type"] == "rest"), None)
    assert entry is not None
    assert "resting_hr" in entry, "rest entry must have top-level 'resting_hr'"
    assert entry["resting_hr"] == 52


# ── AC-2: rest entry has no workout-specific top-level keys ───────────────────

def test_rest_entry_has_no_workout_top_level_keys(client, test_user):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e["date"] == _REST_DATE and e["type"] == "rest"), None)
    assert entry is not None
    for key in ("id", "title", "tss", "duration_minutes", "distance_km", "avg_hr", "source"):
        assert key not in entry, f"rest entry must not have workout key '{key}'"


# ── AC-3: day with both workout and daily_metrics → workout only, no rest ─────

def test_both_date_rest_entry_suppressed(client, test_user):
    data = _get_log(client, test_user)
    rest_entries = [e for e in _all_entries(data) if e["type"] == "rest"]
    rest_dates = [e["date"] for e in rest_entries]
    assert _BOTH_DATE not in rest_dates, (
        f"Date {_BOTH_DATE!r} has a workout — rest entry must be suppressed"
    )


# ── AC-4: week summary excludes rest-day top-level fields ─────────────────────

def test_week_summary_workout_count_excludes_rest_entries(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        workout_count = len(week["workouts"])
        assert week["summary"]["workout_count"] == workout_count


def test_week_summary_tss_excludes_rest_entries(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        expected = sum(w.get("tss") or 0 for w in week["workouts"])
        assert week["summary"]["total_tss"] == expected


# ── Frontend: log.html has rest-day-label CSS class ───────────────────────────

@pytest.fixture(scope="module")
def log_html():
    path = pathlib.Path(__file__).parent.parent / "log.html"
    assert path.exists(), "log.html not found at repo root"
    return path.read_text(encoding="utf-8")


def test_log_html_has_rest_day_label_css_class(log_html):
    assert "rest-day-label" in log_html, "log.html must define .rest-day-label CSS class"


def test_log_html_rest_day_row_has_cursor_default(log_html):
    assert "cursor: default" in log_html or "cursor:default" in log_html, (
        "log.html .rest-day-row must set cursor: default so rows are not clickable"
    )


# ── Frontend: training-log.js renders the correct label format ────────────────

@pytest.fixture(scope="module")
def training_log_js():
    path = pathlib.Path(__file__).parent.parent / "js" / "training-log.js"
    assert path.exists(), "js/training-log.js not found"
    return path.read_text(encoding="utf-8")


def test_training_log_js_uses_rest_day_label_class(training_log_js):
    assert "rest-day-label" in training_log_js, (
        "training-log.js must render an element with class 'rest-day-label'"
    )


def test_training_log_js_label_includes_rest_day_prefix(training_log_js):
    assert "Rest day" in training_log_js, (
        "training-log.js label must start with 'Rest day'"
    )


def test_training_log_js_label_includes_sleep(training_log_js):
    assert "'sleep '" in training_log_js or '"sleep "' in training_log_js, (
        "training-log.js rest-day label must include 'sleep' metric"
    )


def test_training_log_js_label_includes_energy(training_log_js):
    assert "'energy '" in training_log_js or '"energy "' in training_log_js, (
        "training-log.js rest-day label must include 'energy' metric"
    )


def test_training_log_js_label_includes_mood(training_log_js):
    assert "'mood '" in training_log_js or '"mood "' in training_log_js, (
        "training-log.js rest-day label must include 'mood' metric"
    )


def test_training_log_js_reads_top_level_sleep_hours(training_log_js):
    assert "entry.sleep_hours" in training_log_js, (
        "training-log.js must read sleep_hours from top-level entry fields"
    )


def test_training_log_js_reads_top_level_energy(training_log_js):
    assert "entry.energy" in training_log_js, (
        "training-log.js must read energy from top-level entry fields"
    )


def test_training_log_js_reads_top_level_mood(training_log_js):
    assert "entry.mood" in training_log_js, (
        "training-log.js must read mood from top-level entry fields"
    )


def test_training_log_js_reads_top_level_resting_hr(training_log_js):
    assert "entry.resting_hr" in training_log_js, (
        "training-log.js must read resting_hr from top-level entry fields"
    )


def test_training_log_js_rest_row_has_no_click_listener(training_log_js):
    rest_day_row_idx = training_log_js.find("rest-day-row")
    assert rest_day_row_idx != -1
    snippet = training_log_js[rest_day_row_idx:rest_day_row_idx + 500]
    assert "addEventListener('click'" not in snippet and 'addEventListener("click"' not in snippet, (
        "rest-day-row must not wire a click event listener"
    )


# ── Mock data: MOCK_REST_DAYS has top-level fields ────────────────────────────

@pytest.fixture(scope="module")
def mock_data_js():
    path = pathlib.Path(__file__).parent.parent / "js" / "mock-data.js"
    assert path.exists(), "js/mock-data.js not found"
    return path.read_text(encoding="utf-8")


def test_mock_rest_days_have_top_level_sleep_hours(mock_data_js):
    import re
    rest_block = re.search(r"const MOCK_REST_DAYS\s*=\s*\[.*?\];", mock_data_js, re.DOTALL)
    assert rest_block, "MOCK_REST_DAYS not found in mock-data.js"
    block = rest_block.group(0)
    assert "sleep_hours:" in block, "MOCK_REST_DAYS entries must have top-level sleep_hours"


def test_mock_rest_days_have_top_level_energy(mock_data_js):
    import re
    rest_block = re.search(r"const MOCK_REST_DAYS\s*=\s*\[.*?\];", mock_data_js, re.DOTALL)
    assert rest_block
    block = rest_block.group(0)
    assert "energy:" in block, "MOCK_REST_DAYS entries must have top-level energy"


def test_mock_rest_days_have_top_level_mood(mock_data_js):
    import re
    rest_block = re.search(r"const MOCK_REST_DAYS\s*=\s*\[.*?\];", mock_data_js, re.DOTALL)
    assert rest_block
    block = rest_block.group(0)
    assert "mood:" in block, "MOCK_REST_DAYS entries must have top-level mood"
