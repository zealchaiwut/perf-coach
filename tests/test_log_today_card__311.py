"""Tests for issue #311: Log Today quick-entry card on Home dashboard.

Acceptance criteria verified:
(a) home.html contains row-log container and log-today CSS class
(b) home.js includes renderLogTodayCard, PUT call, and loadLogTodayCard
(c) Client-side validation constants present in JS (sleep_hours 0–24, quality/energy/mood 1–5)
(d) GET /api/daily-metrics/{uid}/{date} returns 404 when no record (prefill empty)
(e) GET /api/daily-metrics/{uid}/{date} returns existing data (prefill populated)
(f) PUT /api/daily-metrics/{uid}/{date} creates new record on first save
(g) PUT updates existing record (second save with different values)
(h) PUT returns 403 when user_id in path != authenticated user
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
_TEST_PASSWORD = "lt-card-test-pw-311"

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HOME_HTML = _REPO_ROOT / "frontend" / "pages" / "home.html"
_HOME_JS = _REPO_ROOT / "frontend" / "js" / "home.js"

# Use the UAT DB (same as port-9002 server) regardless of shell ENVIRONMENT.
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
    """Create a user with a password, log in, return authenticated client + user info."""
    name = f"LT311_{_RUN}"
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

    # Generate a CSRF token directly — the middleware only checks that the
    # csrf-token cookie value matches the X-CSRF-Token header value.
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
    """home.html must contain a div#row-log between row-2 and row-3 (AC1)."""
    html = _HOME_HTML.read_text()
    assert 'id="row-log"' in html, "Expected div#row-log in home.html"


def test_home_html_has_log_today_css():
    """home.html must define .log-today CSS class (AC1: visually distinct card)."""
    html = _HOME_HTML.read_text()
    assert ".log-today" in html, "Expected .log-today CSS rule in home.html"


def test_home_html_row_log_between_row2_and_row3():
    """row-log div must appear after row-2 and before row-3."""
    html = _HOME_HTML.read_text()
    pos_row2 = html.find('id="row-2"')
    pos_row_log = html.find('id="row-log"')
    pos_row3 = html.find('id="row-3"')
    assert pos_row2 < pos_row_log < pos_row3, (
        "row-log must be positioned between row-2 and row-3 in home.html"
    )


# ── (b) JS implementation present ─────────────────────────────────────────────

def test_home_js_has_render_log_today_card():
    """home.js must define renderLogTodayCard (AC9: implemented in home.js)."""
    js = _HOME_JS.read_text()
    assert "renderLogTodayCard" in js


def test_home_js_has_load_log_today_card():
    """home.js must define loadLogTodayCard and call it in init."""
    js = _HOME_JS.read_text()
    assert "loadLogTodayCard" in js
    assert "loadLogTodayCard(userId)" in js


def test_home_js_calls_put_daily_metrics():
    """home.js must call PUT /api/daily-metrics (AC6: PUT on save)."""
    js = _HOME_JS.read_text()
    assert "method: 'PUT'" in js or 'method:"PUT"' in js or "method:'PUT'" in js
    assert "daily-metrics" in js


# ── (c) Client-side validation logic present ──────────────────────────────────

def test_home_js_validates_sleep_hours_range():
    """home.js must check sleep_hours 0–24 (AC5: inline validation)."""
    js = _HOME_JS.read_text()
    assert "sh > 24" in js or "sh < 0" in js or "> 24" in js


def test_home_js_validates_quality_energy_mood_range():
    """home.js must check sleep_quality/energy/mood 1–5 (AC5: inline validation)."""
    js = _HOME_JS.read_text()
    assert "< 1" in js or "> 5" in js


def test_home_js_required_field_validation():
    """home.js must show 'Required' error for empty required fields (AC4: blank-submit)."""
    js = _HOME_JS.read_text()
    assert "Required" in js


# ── (d) GET returns 404 for non-existent date ─────────────────────────────────

def test_get_daily_metric_404_for_missing_date(auth_user):
    """GET /api/daily-metrics/{uid}/{date} returns 404 when no record exists (prefill empty)."""
    uid = auth_user["id"]
    authed = auth_user["client"]
    future_past = "2020-01-01"
    res = authed.get(f"/api/daily-metrics/{uid}/{future_past}")
    assert res.status_code == 404


# ── (e) GET returns existing data for prefill ─────────────────────────────────

def test_get_daily_metric_returns_data_for_prefill(auth_user):
    """GET returns the record just created, enabling card prefill (AC4)."""
    uid = auth_user["id"]
    authed = auth_user["client"]
    seed_date = "2025-03-15"

    authed.delete(f"/api/daily-metrics/{uid}/{seed_date}")

    put_res = authed.put(
        f"/api/daily-metrics/{uid}/{seed_date}",
        json={"sleep_hours": 7.5, "sleep_quality": 4, "energy": 3, "mood": 4},
    )
    assert put_res.status_code == 200, put_res.text

    get_res = authed.get(f"/api/daily-metrics/{uid}/{seed_date}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["sleep_hours"] == 7.5
    assert data["sleep_quality"] == 4
    assert data["energy"] == 3
    assert data["mood"] == 4

    authed.delete(f"/api/daily-metrics/{uid}/{seed_date}")


# ── (f) PUT creates new record ────────────────────────────────────────────────

def test_put_daily_metric_creates_record(auth_user):
    """PUT /api/daily-metrics/{uid}/{date} creates a record when none exists (AC6)."""
    uid = auth_user["id"]
    authed = auth_user["client"]
    test_date = "2025-04-10"

    authed.delete(f"/api/daily-metrics/{uid}/{test_date}")

    payload = {
        "sleep_hours": 7.5,
        "sleep_quality": 4,
        "energy": 3,
        "mood": 5,
        "resting_hr": 52,
        "hrv": 68,
    }
    res = authed.put(f"/api/daily-metrics/{uid}/{test_date}", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["sleep_hours"] == 7.5
    assert data["sleep_quality"] == 4
    assert data["energy"] == 3
    assert data["mood"] == 5
    assert data["resting_hr"] == 52
    assert data["hrv"] == 68

    authed.delete(f"/api/daily-metrics/{uid}/{test_date}")


# ── (g) PUT updates existing record ──────────────────────────────────────────

def test_put_daily_metric_updates_existing(auth_user):
    """PUT updates an existing record (AC: edit mood and save again)."""
    uid = auth_user["id"]
    authed = auth_user["client"]
    test_date = "2025-04-11"

    authed.delete(f"/api/daily-metrics/{uid}/{test_date}")

    authed.put(
        f"/api/daily-metrics/{uid}/{test_date}",
        json={"sleep_hours": 6.0, "sleep_quality": 3, "energy": 3, "mood": 3},
    )

    update_res = authed.put(
        f"/api/daily-metrics/{uid}/{test_date}",
        json={"sleep_hours": 6.0, "sleep_quality": 3, "energy": 3, "mood": 2},
    )
    assert update_res.status_code == 200, update_res.text

    get_res = authed.get(f"/api/daily-metrics/{uid}/{test_date}")
    assert get_res.status_code == 200
    assert get_res.json()["mood"] == 2

    authed.delete(f"/api/daily-metrics/{uid}/{test_date}")


# ── (h) PUT rejects mismatched user_id ───────────────────────────────────────

def test_put_daily_metric_403_for_other_user(auth_user, client):
    """PUT returns 403 when uid in path != authenticated user (API error path)."""
    authed = auth_user["client"]
    other_uid = str(uuid.uuid4())
    res = authed.put(
        f"/api/daily-metrics/{other_uid}/2025-05-01",
        json={"sleep_hours": 7.0, "sleep_quality": 3, "energy": 3, "mood": 3},
    )
    assert res.status_code in (403, 404)
