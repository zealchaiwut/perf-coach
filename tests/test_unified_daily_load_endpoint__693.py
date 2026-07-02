"""Tests for issue #693: GET /api/athletes/{id}/daily-load endpoint.

Acceptance criteria covered:
  AC-9:  GET /api/athletes/{id}/daily-load exists; path param, start_date + end_date
         query params; delegates to daily_load_series; returns list as JSON.
  AC-10: 400 for missing start_date, missing end_date, or start_date after end_date.
  AC-11: 404 when the athlete id does not exist in the database.
  AC-12: TSS from running and strength workouts both included in aggregation.
  AC-13: debug field present in every per-day object in a successful response.
"""
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel, Workout as _Workout
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_FAKE_UUID = str(uuid.uuid4())  # random; guaranteed not in DB

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None

_TEST_PW = "dailyload693-test-pw"


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def athlete_id(client):
    """Create a test user; yield their UUID string; clean up after module."""
    name = f"tester693_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture(scope="module")
def athlete_with_workouts(athlete_id):
    """Seed a run (TSS 65) and a strength session (TSS 40) on 2026-06-15."""
    with _OrmSess(_engine) as db:
        run = _Workout(
            user_id=uuid.UUID(athlete_id),
            workout_date="2026-06-15",
            name="Morning run",
            workout_type="run",
            tss=65.0,
        )
        strength = _Workout(
            user_id=uuid.UUID(athlete_id),
            workout_date="2026-06-15",
            name="Gym session",
            workout_type="strength",
            tss=40.0,
        )
        db.add_all([run, strength])
        db.commit()
        run_id = str(run.id)
        strength_id = str(strength.id)
    yield {"athlete_id": athlete_id, "run_id": run_id, "strength_id": strength_id}
    with _OrmSess(_engine) as db:
        for wid in (uuid.UUID(run_id), uuid.UUID(strength_id)):
            w = db.get(_Workout, wid)
            if w:
                db.delete(w)
        db.commit()


# ── AC-10: 400 for missing or malformed date params ───────────────────────────

def test_missing_start_date_returns_400(client):
    """AC-10: omitting start_date yields HTTP 400."""
    r = client.get(
        f"/api/athletes/{_FAKE_UUID}/daily-load",
        params={"end_date": "2026-06-20"},
    )
    assert r.status_code == 400, r.text


def test_missing_end_date_returns_400(client):
    """AC-10: omitting end_date yields HTTP 400."""
    r = client.get(
        f"/api/athletes/{_FAKE_UUID}/daily-load",
        params={"start_date": "2026-06-01"},
    )
    assert r.status_code == 400, r.text


def test_missing_both_dates_returns_400(client):
    """AC-10: omitting both date params yields HTTP 400."""
    r = client.get(f"/api/athletes/{_FAKE_UUID}/daily-load")
    assert r.status_code == 400, r.text


def test_malformed_start_date_returns_400(client):
    """AC-10: a non-ISO-8601 start_date yields HTTP 400."""
    r = client.get(
        f"/api/athletes/{_FAKE_UUID}/daily-load",
        params={"start_date": "not-a-date", "end_date": "2026-06-20"},
    )
    assert r.status_code == 400, r.text


def test_malformed_end_date_returns_400(client):
    """AC-10: a non-ISO-8601 end_date yields HTTP 400."""
    r = client.get(
        f"/api/athletes/{_FAKE_UUID}/daily-load",
        params={"start_date": "2026-06-01", "end_date": "tomorrow"},
    )
    assert r.status_code == 400, r.text


def test_start_after_end_returns_400(client):
    """AC-10: start_date after end_date yields HTTP 400."""
    r = client.get(
        f"/api/athletes/{_FAKE_UUID}/daily-load",
        params={"start_date": "2026-06-20", "end_date": "2026-06-01"},
    )
    assert r.status_code == 400, r.text


def test_400_response_contains_error_description(client):
    """AC-10: 400 response body contains a descriptive error message."""
    r = client.get(
        f"/api/athletes/{_FAKE_UUID}/daily-load",
        params={"start_date": "2026-06-20", "end_date": "2026-06-01"},
    )
    body = r.json()
    has_message = "detail" in body or "error" in body or "reason" in body
    assert has_message, f"No error description in body: {body}"


# ── AC-11: 404 when athlete does not exist ────────────────────────────────────

def test_nonexistent_athlete_returns_404(client):
    """AC-11: a valid UUID that has no matching user returns HTTP 404."""
    r = client.get(
        f"/api/athletes/{_FAKE_UUID}/daily-load",
        params={"start_date": "2026-06-01", "end_date": "2026-06-07"},
    )
    assert r.status_code == 404, r.text


# ── AC-9: endpoint exists and returns list ────────────────────────────────────

def test_valid_request_returns_200(athlete_with_workouts, client):
    """AC-9: a valid request returns HTTP 200."""
    aid = athlete_with_workouts["athlete_id"]
    r = client.get(
        f"/api/athletes/{aid}/daily-load",
        params={"start_date": "2026-06-15", "end_date": "2026-06-15"},
    )
    assert r.status_code == 200, r.text


def test_valid_request_returns_list(athlete_with_workouts, client):
    """AC-9: response body is a JSON list."""
    aid = athlete_with_workouts["athlete_id"]
    r = client.get(
        f"/api/athletes/{aid}/daily-load",
        params={"start_date": "2026-06-15", "end_date": "2026-06-15"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list), f"Expected list, got: {type(data)}"


def test_response_covers_full_date_range(athlete_with_workouts, client):
    """AC-9: every calendar day in the range appears in the response."""
    aid = athlete_with_workouts["athlete_id"]
    r = client.get(
        f"/api/athletes/{aid}/daily-load",
        params={"start_date": "2026-06-14", "end_date": "2026-06-16"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 3, f"Expected 3 days, got {len(data)}: {data}"
    dates = [d["date"] for d in data]
    assert "2026-06-14" in dates
    assert "2026-06-15" in dates
    assert "2026-06-16" in dates


def test_response_sorted_ascending(athlete_with_workouts, client):
    """AC-9: days are returned in ascending date order."""
    aid = athlete_with_workouts["athlete_id"]
    r = client.get(
        f"/api/athletes/{aid}/daily-load",
        params={"start_date": "2026-06-13", "end_date": "2026-06-17"},
    )
    assert r.status_code == 200
    dates = [d["date"] for d in r.json()]
    assert dates == sorted(dates), f"Dates not sorted: {dates}"


# ── AC-12: running and strength TSS both aggregated ──────────────────────────

def test_run_and_strength_tss_summed(athlete_with_workouts, client):
    """AC-12: daily_load is the sum of run TSS (65) + strength TSS (40) = 105."""
    aid = athlete_with_workouts["athlete_id"]
    r = client.get(
        f"/api/athletes/{aid}/daily-load",
        params={"start_date": "2026-06-15", "end_date": "2026-06-15"},
    )
    assert r.status_code == 200, r.text
    day = r.json()[0]
    assert day["daily_load"] == 105.0, f"Expected 105, got {day['daily_load']}"
    assert day["workout_count"] == 2, f"Expected 2 workouts, got {day['workout_count']}"
    assert day["has_unscored"] is False


def test_workout_ids_in_debug(athlete_with_workouts, client):
    """AC-12/AC-13: debug.contributing_workouts contains both workout IDs."""
    aid = athlete_with_workouts["athlete_id"]
    r = client.get(
        f"/api/athletes/{aid}/daily-load",
        params={"start_date": "2026-06-15", "end_date": "2026-06-15"},
    )
    assert r.status_code == 200, r.text
    day = r.json()[0]
    cw_ids = {entry["id"] for entry in day["debug"]["contributing_workouts"]}
    assert athlete_with_workouts["run_id"] in cw_ids
    assert athlete_with_workouts["strength_id"] in cw_ids


# ── AC-13: debug field present in every per-day object ────────────────────────

def test_debug_field_present_on_every_day(athlete_with_workouts, client):
    """AC-13: debug.contributing_workouts key exists on every day including empty ones."""
    aid = athlete_with_workouts["athlete_id"]
    r = client.get(
        f"/api/athletes/{aid}/daily-load",
        params={"start_date": "2026-06-13", "end_date": "2026-06-17"},
    )
    assert r.status_code == 200, r.text
    for day in r.json():
        assert "debug" in day, f"Missing debug on {day['date']}"
        assert "contributing_workouts" in day["debug"], (
            f"Missing contributing_workouts on {day['date']}"
        )


def test_empty_days_have_empty_debug(athlete_with_workouts, client):
    """AC-13: days with no workouts have an empty contributing_workouts list."""
    aid = athlete_with_workouts["athlete_id"]
    r = client.get(
        f"/api/athletes/{aid}/daily-load",
        params={"start_date": "2026-06-14", "end_date": "2026-06-14"},
    )
    assert r.status_code == 200, r.text
    day = r.json()[0]
    assert day["daily_load"] == 0
    assert day["workout_count"] == 0
    assert day["debug"]["contributing_workouts"] == []
