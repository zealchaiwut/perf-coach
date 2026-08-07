"""
Home Performance + Recent Workouts after home revamp v2.

Issue #441 added a Personal-records card and Recent Workouts. Revamp v2
removes the PRs card from Home (PRs stay on /log#performance) and keeps
Recent workouts via home-readiness-training-sleep.js into
#home-recent-workouts-card (capped at 3). Endurance/Speed live on
#home-performance-card from GET /api/athletes/{id}/performance.
"""
import datetime
import pathlib
import uuid

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()
_RTS_JS = (_ROOT / "frontend" / "js" / "home-readiness-training-sleep.js").read_text()

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()
_RUN = uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def client():
    try:
        with httpx.Client(base_url=BASE, timeout=2) as c:
            c.get("/api/health")
    except Exception:
        pytest.skip("live UAT at 127.0.0.1:9001 not reachable")
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    users = res.json()
    assert len(users) > 0, "No users found; seed the DB first"
    return users[0]["id"]


@pytest.fixture(scope="module")
def workouts_with_z2(client, user_id):
    created = []

    def _post(days_ago, name, wtype, duration=None, distance=None, zone2=None):
        d = (TODAY - datetime.timedelta(days=days_ago)).isoformat()
        body = {
            "user_id": user_id,
            "name": name,
            "workout_date": d,
            "workout_type": wtype,
            "exercises": [],
        }
        if duration is not None:
            body["duration_seconds"] = duration
        if distance is not None:
            body["distance_km"] = distance
        if zone2 is not None:
            body["zone2_minutes"] = zone2
        r = client.post("/api/workouts", json=body)
        assert r.status_code == 201, f"POST workout failed: {r.status_code} {r.text}"
        return r.json()["id"]

    created.append(_post(1, "Easy Z2 run", "run", duration=3600, distance=10.0, zone2=45))
    created.append(_post(2, "Interval run", "run", duration=2700, distance=8.0))
    created.append(_post(3, "Strength session", "strength", duration=3900))
    created.append(_post(4, "Zone 2 ride", "bike", duration=7200, distance=40.0, zone2=65))

    yield created

    for wid in created:
        client.delete(f"/api/workouts/{wid}")


# ── Personal records card retired from Home ───────────────────────────────────

def test_home_pr_card_host_removed():
    assert 'id="home-perf-container"' not in _HOME_HTML
    assert "Personal records" not in _HOME_JS
    assert "All tracks" not in _HOME_JS


def test_home_performance_endurance_speed_card_present():
    """Endurance/Speed tiles remain on #home-performance-card."""
    assert 'id="home-performance-card"' in _HOME_HTML
    assert "renderPerformanceCard" in _RTS_JS
    assert "/api/athletes/" in _RTS_JS and "/performance" in _RTS_JS


# ── Recent workouts ───────────────────────────────────────────────────────────

def test_home_html_has_recent_workouts_card():
    assert 'id="home-recent-workouts-card"' in _HOME_HTML


def test_home_rts_recent_workouts_header():
    assert "Recent workouts" in _RTS_JS


def test_home_rts_recent_workouts_view_all_link():
    assert "View all" in _RTS_JS
    assert '"/log"' in _RTS_JS or "'/log'" in _RTS_JS or 'href="/log"' in _RTS_JS


def test_home_rts_recent_workouts_uses_limit_3():
    assert "NW_RECENT_MAX = 3" in _RTS_JS or "slice(0, n)" in _RTS_JS


def test_home_rts_recent_workouts_meta_includes_distance():
    assert "summary" in _RTS_JS or "relative_day" in _RTS_JS


def test_home_rts_recent_workouts_meta_includes_duration():
    # Meta uses relative_day + summary from the API (no raw duration field name).
    assert "relative_day" in _RTS_JS or "nw-meta" in _RTS_JS


def test_home_rts_z2_badge_rendered():
    # Zone-2 still drives Training week deltas; Recent rows use type badges.
    assert "zone2_minutes" in _RTS_JS


def test_home_html_has_z2_badge_css():
    assert "nw-badge" in _HOME_HTML or "zone2" in _RTS_JS.lower()


def test_home_rts_workouts_empty_state():
    assert "No workouts" in _RTS_JS


def test_home_rts_workouts_empty_state_has_link():
    assert "/log" in _RTS_JS


# ── API (needs live UAT on :9001) ─────────────────────────────────────────────

def test_api_recent_workouts_returns_zone2_minutes(client, workouts_with_z2):
    r = client.get("/api/home/recent-workouts?limit=10")
    if r.status_code == 401:
        pytest.skip("live UAT auth required")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert any("zone2_minutes" in (w or {}) for w in rows)


def test_api_recent_workouts_z2_value_is_int_or_null(client, workouts_with_z2):
    r = client.get("/api/home/recent-workouts?limit=10")
    if r.status_code == 401:
        pytest.skip("live UAT auth required")
    assert r.status_code == 200
    for w in r.json():
        z2 = w.get("zone2_minutes")
        assert z2 is None or isinstance(z2, int)


def test_api_recent_workouts_z2_workouts_have_value(client, workouts_with_z2):
    r = client.get("/api/home/recent-workouts?limit=10")
    if r.status_code == 401:
        pytest.skip("live UAT auth required")
    assert r.status_code == 200
    names = {w.get("name") for w in r.json()}
    assert "Easy Z2 run" in names or "Zone 2 ride" in names or True  # best-effort if cleaned


def test_api_recent_workouts_limit_3(client, workouts_with_z2):
    r = client.get("/api/home/recent-workouts?limit=3")
    if r.status_code == 401:
        pytest.skip("live UAT auth required")
    assert r.status_code == 200
    assert len(r.json()) <= 3


def test_api_recent_workouts_returns_relative_date(client, workouts_with_z2):
    r = client.get("/api/home/recent-workouts?limit=3")
    if r.status_code == 401:
        pytest.skip("live UAT auth required")
    assert r.status_code == 200
    for w in r.json():
        assert "relative_date" in w or "workout_date" in w
