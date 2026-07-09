"""Tests for GET /api/plan/week-load (Plan tab revamp, Part 2).

Covers:
  AC1 - No A race -> 204
  AC2 - target_tss matches the SAME week's entry in GET /api/plan/load-plan
        (never recomputed independently)
  AC3 - baseline_tss (actual) vs baseline_planned_tss (estimated from what was
        planned) are distinct — the argument for ramping off actuals
  AC4 - projected_tss = logged_tss + planned_tss
  AC5 - state classifies under/on_track/over via a +-5% band around target_tss
  AC6 - clamped mirrors the matching week's clamped flag from load-plan
  AC7 - week_start navigates to an arbitrary week in the series
  AC8 - GET /api/plan/week-load requires authentication
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date, timedelta

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "weekload2!"

try:
    from dotenv import dotenv_values
    _env = dotenv_values(_ROOT / ".env")
    _uat_url = _env.get("DATABASE_URL_UAT")
except ImportError:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

if _uat_url:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import hash_password as _hash_pw
    from backend.models import User as _UserModel
    _engine = create_engine(_uat_url, pool_pre_ping=True)
else:
    _engine = None


def _skip_if_no_db():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


def _make_client():
    uname = f"weekload2_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname}, cookies=_admin_cookies())
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
        assert r.status_code == 200, f"login failed: {r.text}"
        session_cookie = r.cookies.get("session")
        csrf_token = r.cookies.get("csrf-token")

    client = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, "csrf-token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return client, user_id


def _cleanup_user(user_id):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture()
def bare_client():
    _skip_if_no_db()
    client, user_id = _make_client()
    yield client, user_id
    client.close()
    _cleanup_user(user_id)


def _monday_of(d):
    return d - timedelta(days=d.weekday())


def _race_date_in_week(n):
    this_monday = _monday_of(date.today())
    return this_monday + timedelta(weeks=n - 1, days=2)


def _add_workout(client, workout_date, tss, duration_seconds=1800, workout_type="run"):
    r = client.post("/api/workouts", json={
        "name": "Test run", "workout_type": workout_type,
        "workout_date": workout_date.isoformat(), "tss": tss,
        "duration_seconds": duration_seconds,
    })
    assert r.status_code == 201, f"create workout failed: {r.text}"
    return r.json()


def _add_planned(client, planned_date, duration_min=30, session_type="run"):
    structure = {"blocks": [{"duration_min": duration_min}]} if session_type == "run" else \
        {"exercises": [{"name": "Squat"}]}
    r = client.post("/api/planned-sessions", json={
        "planned_date": planned_date.isoformat(), "session_type": session_type,
        "name": "Test planned", "structure": structure,
    })
    assert r.status_code == 201, f"create planned session failed: {r.text}"
    return r.json()


def _add_a_race(client, race_date):
    r = client.post("/api/races", json={
        "date": race_date.isoformat(), "distance_km": 42.2, "name": "Test A Race",
        "priority": "A", "status": "planned", "race_type": "race",
    })
    assert r.status_code == 201, f"create race failed: {r.text}"
    return r.json()


def _seed_pace_history(client):
    """A few past run workouts so estimate_historical_pace_and_tss() has
    something to derive run_tss_per_min from — otherwise estimated_tss is
    always None and baseline_planned_tss/planned_tss are always 0. Kept at
    20-40 days ago, outside both "this week" and "last week" (0-13 days ago)
    so it never leaks into baseline_tss/logged_tss assertions."""
    today = date.today()
    for i in range(20, 41, 4):
        _add_workout(client, today - timedelta(days=i), tss=30, duration_seconds=1800)


# ── AC1: no A race -> 204 ────────────────────────────────────────────────────

def test_no_a_race_returns_204(bare_client):
    client, user_id = bare_client
    r = client.get("/api/plan/week-load")
    assert r.status_code == 204, f"expected 204, got {r.status_code}: {r.text}"


# ── AC2: target_tss matches load-plan's week 1 entry ─────────────────────────

def test_target_matches_load_plan_week_one(bare_client):
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))

    r1 = client.get("/api/plan/load-plan")
    assert r1.status_code == 200, r1.text
    load_plan = r1.json()

    r2 = client.get("/api/plan/week-load")
    assert r2.status_code == 200, r2.text
    week_load = r2.json()

    week1 = load_plan["weeks"][0]
    assert week1["week_index"] == 1
    assert week_load["target_tss"] == pytest.approx(week1["target_tss"])
    assert week_load["clamped"] == week1["clamped"]
    assert week_load["week_start"] == week1["week_start"]


# ── AC3: baseline_tss (actual) vs baseline_planned_tss (estimated planned) ──

def test_baseline_actual_vs_planned_are_distinct(bare_client):
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))
    _seed_pace_history(client)

    today = date.today()
    this_monday = _monday_of(today)
    last_monday = this_monday - timedelta(days=7)

    # Actual: only 150 TSS logged last week...
    _add_workout(client, last_monday + timedelta(days=1), tss=150, duration_seconds=1800)
    # ...but 60 minutes was PLANNED that week (never logged/matched) — this
    # is the "planned 340 (proxy: nonzero) vs logged 316" gap the UI shows.
    _add_planned(client, last_monday + timedelta(days=3), duration_min=60)

    r = client.get("/api/plan/week-load")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["baseline_tss"] == pytest.approx(150.0, abs=0.1)
    assert body["baseline_planned_tss"] > 0, "planned TSS estimate should be nonzero given seeded history"
    assert body["baseline_planned_tss"] != body["baseline_tss"]


def test_baseline_planned_ignores_matched_or_missed_sessions(bare_client):
    """A planned session that's already been matched to a real workout, or
    marked missed, must not double-count toward baseline_planned_tss."""
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))
    _seed_pace_history(client)

    today = date.today()
    last_monday = _monday_of(today) - timedelta(days=7)
    planned = _add_planned(client, last_monday + timedelta(days=2), duration_min=45)

    r = client.post(f"/api/planned-sessions/{planned['id']}/miss")
    assert r.status_code == 200, r.text

    r2 = client.get("/api/plan/week-load")
    assert r2.status_code == 200, r2.text
    assert r2.json()["baseline_planned_tss"] == 0.0


# ── AC4: projected_tss = logged_tss + planned_tss ────────────────────────────

def test_projected_equals_logged_plus_planned(bare_client):
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))
    _seed_pace_history(client)

    today = date.today()
    this_monday = _monday_of(today)
    if today.weekday() >= 5:
        pytest.skip("need at least one future day left in the current week to plan a session")

    _add_workout(client, today, tss=80, duration_seconds=1800)
    future_day = today + timedelta(days=1)
    if future_day > this_monday + timedelta(days=6):
        pytest.skip("no room left in the current week")
    _add_planned(client, future_day, duration_min=40)

    r = client.get("/api/plan/week-load")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["projected_tss"] == pytest.approx(body["logged_tss"] + body["planned_tss"], abs=0.1)
    assert body["logged_tss"] == pytest.approx(80.0, abs=0.1)


# ── AC5: state classification ────────────────────────────────────────────────

def test_state_on_track_within_band(bare_client):
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))

    today = date.today()
    this_monday = _monday_of(today)
    last_monday = this_monday - timedelta(days=7)
    # baseline 300 -> default ramp_rate 0.05 -> week-1 target = 300*1.05 = 315.
    # Seed a generous trailing-28d floor (days 15/18/21 ago — inside the 28-day
    # ACWR window, outside "this week"/"last week") so the ACWR ceiling
    # (1.3 * trailing_28d_avg) stays well above 315 regardless of whatever
    # gets logged today — otherwise adding today's own "hit target" workout
    # shifts trailing_28d_avg (today is IN that same rolling window), which
    # shifts the ceiling, which can silently reclamp the target out from
    # under this test.
    _add_workout(client, last_monday + timedelta(days=1), tss=300, duration_seconds=1800)
    for i in (15, 18, 21):
        _add_workout(client, today - timedelta(days=i), tss=400, duration_seconds=3600)

    r1 = client.get("/api/plan/load-plan")
    target = r1.json()["weeks"][0]["target_tss"]

    if today.weekday() < 6:
        _add_workout(client, today, tss=round(target), duration_seconds=1800)

    r2 = client.get("/api/plan/week-load")
    body = r2.json()
    assert body["target_tss"] == pytest.approx(target)
    if today.weekday() < 6:
        assert body["state"] == "on_track"


def test_state_under_below_band(bare_client):
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))

    today = date.today()
    last_monday = _monday_of(today) - timedelta(days=7)
    _add_workout(client, last_monday + timedelta(days=1), tss=300, duration_seconds=1800)

    r = client.get("/api/plan/week-load")
    body = r.json()
    # nothing logged/planned yet this week -> projected 0, well under any positive target
    assert body["target_tss"] > 0
    assert body["state"] == "under"


def test_state_over_above_band(bare_client):
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))

    today = date.today()
    last_monday = _monday_of(today) - timedelta(days=7)
    _add_workout(client, last_monday + timedelta(days=1), tss=200, duration_seconds=1800)

    r1 = client.get("/api/plan/load-plan")
    target = r1.json()["weeks"][0]["target_tss"]
    _add_workout(client, today, tss=round(target * 2), duration_seconds=3600)

    r2 = client.get("/api/plan/week-load")
    assert r2.json()["state"] == "over"


# ── AC7: week_start navigation ───────────────────────────────────────────────

def test_week_start_navigates_to_future_week(bare_client):
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))

    r1 = client.get("/api/plan/load-plan")
    load_plan = r1.json()
    week3 = next(w for w in load_plan["weeks"] if w["week_index"] == 3)

    r2 = client.get("/api/plan/week-load", params={"week_start": week3["week_start"]})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["week_start"] == week3["week_start"]
    assert body["target_tss"] == pytest.approx(week3["target_tss"])


def test_week_start_rejects_bad_format(bare_client):
    client, user_id = bare_client
    _add_a_race(client, _race_date_in_week(19))
    r = client.get("/api/plan/week-load", params={"week_start": "not-a-date"})
    assert r.status_code == 422


# ── AC8: auth required ───────────────────────────────────────────────────────

def test_week_load_requires_auth():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as anon:
        r = anon.get("/api/plan/week-load")
        assert r.status_code in (401, 403), f"expected auth-gated, got {r.status_code}"
