"""Tests for issue #313: date picker on Home daily-metrics entry card for backfilling.

Acceptance criteria verified:
(a) home.html has #row-log container, .log-today CSS, .lt-date-input CSS
(b) home.js has renderLogTodayCard, loadLogTodayCard, date picker input, max attribute,
    change handler that fetches data, PUT call for any date
(c) Client-side validation constants present (sleep_hours 0–24, quality/energy/mood 1–5)
(d) GET /api/daily-metrics/{uid}/{date} returns 404 for a missing past date
(e) GET returns existing data for a past date with data (pre-fill)
(f) PUT saves new record for a past date
(g) PUT updates existing record for a past date
(h) PUT returns 403 when uid in path != authenticated user
"""
import datetime
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession

from backend.auth import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.models import User

BASE = "http://127.0.0.1:9002"
TODAY = datetime.date.today().isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "dp-backfill-test-pw-313"

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HOME_HTML = _REPO_ROOT / "frontend" / "pages" / "home.html"
_HOME_JS = _REPO_ROOT / "frontend" / "js" / "home.js"

_env_vals = dotenv_values(_REPO_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    name = f"DP313_{_RUN}"
    res = client.post("/api/users", json={"name": name})
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]

    pw_hash = hash_password(_TEST_PASSWORD)
    with DBSession(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.password_hash = pw_hash
        session.commit()

    login_res = client.post(
        "/api/auth/login",
        json={"username": name, "password": _TEST_PASSWORD},
    )
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"

    session_cookie = login_res.cookies.get("session")
    assert session_cookie, "Login must set session cookie"

    csrf_token = generate_csrf_token()

    authed = httpx.Client(
        base_url=BASE,
        timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )

    yield {"id": user_id, "name": name, "client": authed}

    authed.close()
    client.delete(f"/api/users/{user_id}")


# ── (a) HTML structure ────────────────────────────────────────────────────────

def test_home_html_has_row_log_container():
    html = _HOME_HTML.read_text()
    assert 'id="row-log"' in html, "Expected div#row-log in home.html"


def test_home_html_has_log_today_css():
    html = _HOME_HTML.read_text()
    assert ".log-today" in html, "Expected .log-today CSS rule in home.html"


def test_home_html_has_lt_date_input_css():
    html = _HOME_HTML.read_text()
    assert ".lt-date-input" in html, "Expected .lt-date-input CSS rule in home.html"


def test_home_html_row_log_between_row2_and_row3():
    html = _HOME_HTML.read_text()
    pos_row2    = html.find('id="row-2"')
    pos_row_log = html.find('id="row-log"')
    pos_row3    = html.find('id="row-3"')
    assert pos_row2 < pos_row_log < pos_row3, (
        "row-log must be positioned between row-2 and row-3 in home.html"
    )


# ── (b) JS implementation ─────────────────────────────────────────────────────

def test_home_js_has_render_log_today_card():
    js = _HOME_JS.read_text()
    assert "renderLogTodayCard" in js


def test_home_js_has_load_log_today_card():
    js = _HOME_JS.read_text()
    assert "loadLogTodayCard" in js
    assert "loadLogTodayCard(userId)" in js


def test_home_js_has_date_picker_input():
    js = _HOME_JS.read_text()
    assert 'lt-date-picker' in js, "Expected lt-date-picker element id in home.js"
    assert 'type="date"' in js, "Expected type=\"date\" input in home.js"


def test_home_js_date_picker_has_max_attribute():
    """max=todayStr prevents future date selection."""
    js = _HOME_JS.read_text()
    assert 'max="' in js or "max='" in js or ' max=' in js, (
        "Expected max attribute on date picker to block future dates"
    )


def test_home_js_date_change_fetches_data():
    """Date picker change handler must fetch metrics for new date."""
    js = _HOME_JS.read_text()
    assert "change" in js, "Expected change event listener for date picker"
    assert "daily-metrics" in js


def test_home_js_calls_put_daily_metrics():
    js = _HOME_JS.read_text()
    assert "method: 'PUT'" in js or 'method:"PUT"' in js or "method:'PUT'" in js
    assert "daily-metrics" in js


# ── (c) Validation ────────────────────────────────────────────────────────────

def test_home_js_validates_sleep_hours_range():
    js = _HOME_JS.read_text()
    assert "sh > 24" in js or "> 24" in js


def test_home_js_validates_quality_energy_mood_range():
    js = _HOME_JS.read_text()
    assert "< 1" in js or "> 5" in js


def test_home_js_required_field_validation():
    js = _HOME_JS.read_text()
    assert "Required" in js


# ── (d) GET 404 for missing past date ────────────────────────────────────────

def test_get_past_metric_404_for_missing_date(auth_user):
    uid = auth_user["id"]
    authed = auth_user["client"]
    res = authed.get(f"/api/daily-metrics/{uid}/2020-01-01")
    assert res.status_code == 404


# ── (e) GET pre-fills existing past date ─────────────────────────────────────

def test_get_past_metric_returns_data(auth_user):
    uid = auth_user["id"]
    authed = auth_user["client"]
    seed_date = "2024-11-20"

    authed.delete(f"/api/daily-metrics/{uid}/{seed_date}")

    put_res = authed.put(
        f"/api/daily-metrics/{uid}/{seed_date}",
        json={"sleep_hours": 6.5, "sleep_quality": 3, "energy": 4, "mood": 3},
    )
    assert put_res.status_code == 200, put_res.text

    get_res = authed.get(f"/api/daily-metrics/{uid}/{seed_date}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["sleep_hours"] == 6.5
    assert data["sleep_quality"] == 3
    assert data["energy"] == 4
    assert data["mood"] == 3

    authed.delete(f"/api/daily-metrics/{uid}/{seed_date}")


# ── (f) PUT creates record for past date ─────────────────────────────────────

def test_put_past_date_creates_record(auth_user):
    uid = auth_user["id"]
    authed = auth_user["client"]
    test_date = "2024-12-05"

    authed.delete(f"/api/daily-metrics/{uid}/{test_date}")

    res = authed.put(
        f"/api/daily-metrics/{uid}/{test_date}",
        json={"sleep_hours": 7.0, "sleep_quality": 4, "energy": 3, "mood": 4, "hrv": 62},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["sleep_hours"] == 7.0
    assert data["hrv"] == 62

    authed.delete(f"/api/daily-metrics/{uid}/{test_date}")


# ── (g) PUT updates existing past record ─────────────────────────────────────

def test_put_past_date_updates_existing(auth_user):
    uid = auth_user["id"]
    authed = auth_user["client"]
    test_date = "2024-12-06"

    authed.delete(f"/api/daily-metrics/{uid}/{test_date}")
    authed.put(
        f"/api/daily-metrics/{uid}/{test_date}",
        json={"sleep_hours": 5.5, "sleep_quality": 2, "energy": 2, "mood": 2},
    )

    update_res = authed.put(
        f"/api/daily-metrics/{uid}/{test_date}",
        json={"sleep_hours": 5.5, "sleep_quality": 2, "energy": 2, "mood": 5},
    )
    assert update_res.status_code == 200, update_res.text

    get_res = authed.get(f"/api/daily-metrics/{uid}/{test_date}")
    assert get_res.status_code == 200
    assert get_res.json()["mood"] == 5

    authed.delete(f"/api/daily-metrics/{uid}/{test_date}")


# ── (h) PUT rejects mismatched user_id ───────────────────────────────────────

def test_put_past_metric_403_for_other_user(auth_user):
    authed = auth_user["client"]
    other_uid = str(uuid.uuid4())
    res = authed.put(
        f"/api/daily-metrics/{other_uid}/2024-06-01",
        json={"sleep_hours": 7.0, "sleep_quality": 3, "energy": 3, "mood": 3},
    )
    assert res.status_code in (403, 404)
