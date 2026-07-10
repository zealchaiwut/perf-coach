"""Tests for GET /api/plan/load-plan and PUT /api/plan/rules (Plan tab revamp, Part 1).

Covers:
  AC1 - No A race -> 204
  AC2 - With an A race, returns the race-anchored week series (ramp/hold/taper/race
        phases), weeks_to_race, peak, and the prior 4 weeks of actual TSS
  AC3 - baseline_tss comes from actual logged Workout TSS, not any planned figure
  AC4 - PUT /api/plan/rules updates the existing TrainingPlan row, never creates a second
  AC5 - PUT /api/plan/rules validates ramp_rate/hold_weeks/taper_weeks ranges
  AC6 - GET /api/plan/load-plan requires authentication
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
_TEST_PW = "loadplan1!"

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
    """Create a fresh test user, log in, return (client, user_id) — caller must close/cleanup."""
    uname = f"loadplan1_{uuid.uuid4().hex[:8]}"
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
    """A race date guaranteed to fall in week_index n (this week = 1),
    regardless of what weekday today is — Monday of week n, plus 2 days so
    it's never the Monday boundary itself."""
    this_monday = _monday_of(date.today())
    return this_monday + timedelta(weeks=n - 1, days=2)


def _add_workout(client, workout_date, tss, workout_type="run"):
    r = client.post("/api/workouts", json={
        "name": "Test run",
        "workout_type": workout_type,
        "workout_date": workout_date.isoformat(),
        "tss": tss,
    })
    assert r.status_code == 201, f"create workout failed: {r.text}"
    return r.json()


def _add_a_race(client, race_date):
    r = client.post("/api/races", json={
        "date": race_date.isoformat(),
        "distance_km": 42.2,
        "name": "Test A Race",
        "priority": "A",
        "status": "planned",
        "race_type": "race",
    })
    assert r.status_code == 201, f"create race failed: {r.text}"
    return r.json()


# ── AC1: no A race -> 204 ────────────────────────────────────────────────────

def test_no_a_race_returns_204(bare_client):
    client, user_id = bare_client
    r = client.get("/api/plan/load-plan")
    assert r.status_code == 204, f"expected 204 with no A race, got {r.status_code}: {r.text}"


def test_past_a_race_does_not_count(bare_client):
    """A race in the past must not be resolved — can't ramp toward a race that already happened."""
    client, user_id = bare_client
    past = date.today() - timedelta(days=10)
    _add_a_race(client, past)
    r = client.get("/api/plan/load-plan")
    assert r.status_code == 204


def test_b_priority_race_does_not_count(bare_client):
    client, user_id = bare_client
    future = date.today() + timedelta(weeks=12)
    r = client.post("/api/races", json={
        "date": future.isoformat(), "distance_km": 21.1, "name": "B race",
        "priority": "B", "status": "planned", "race_type": "race",
    })
    assert r.status_code == 201
    r = client.get("/api/plan/load-plan")
    assert r.status_code == 204


# ── AC2: full happy-path shape ───────────────────────────────────────────────

def test_load_plan_returns_race_anchored_series(bare_client):
    client, user_id = bare_client
    today = date.today()
    race_date = _race_date_in_week(19)
    _add_a_race(client, race_date)

    # Log some actual TSS in the last completed week (baseline source).
    this_monday = _monday_of(today)
    last_monday = this_monday - timedelta(days=7)
    _add_workout(client, last_monday, 100)
    _add_workout(client, last_monday + timedelta(days=3), 216)

    r = client.get("/api/plan/load-plan")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["race"]["name"] == "Test A Race"
    assert body["weeks_to_race"] == 19
    assert body["baseline_tss"] == pytest.approx(316.0, abs=0.1)
    assert len(body["prior_weeks"]) == 4
    assert len(body["weeks"]) == 19

    phases = [w["phase"] for w in body["weeks"]]
    assert phases.count("ramp") == body["ramp_weeks"]
    assert phases[-1] == "race"
    assert "hold" in phases

    # every week has a week_start date string and a numeric target
    for w in body["weeks"]:
        assert "week_start" in w
        assert isinstance(w["target_tss"], (int, float))


def test_load_plan_default_rules_match_migration_backfill(bare_client):
    """A brand-new plan (no explicit PUT /api/plan/rules yet) uses the
    migration-backfilled defaults: ramp_rate 0.05, hold_weeks 4, taper_weeks 3,
    deload_enabled False."""
    client, user_id = bare_client
    race_date = _race_date_in_week(19)
    _add_a_race(client, race_date)
    r = client.get("/api/plan/load-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ramp_rate"] == pytest.approx(0.05)
    assert body["hold_weeks"] == 4
    assert body["taper_weeks"] == pytest.approx(3.0)
    assert body["deload_enabled"] is False
    assert all("deload" in w and "ceiling" in w for w in body["weeks"])


# ── deload toggle roundtrip + moving ceiling on the live endpoint ───────────

def test_put_plan_rules_roundtrips_deload_enabled(bare_client):
    client, user_id = bare_client
    r = client.put("/api/plan/rules", json={"deload_enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["deload_enabled"] is True

    r = client.get("/api/plans")
    assert len(r.json()) == 1, "PUT /api/plan/rules must not create a second plan row"

    r = client.put("/api/plan/rules", json={"ramp_rate": 0.06})
    assert r.status_code == 200, r.text
    assert r.json()["deload_enabled"] is True, "unrelated PUT must not reset deload_enabled"


def test_load_plan_reflects_deload_enabled(bare_client):
    client, user_id = bare_client
    race_date = _race_date_in_week(19)
    _add_a_race(client, race_date)
    client.put("/api/plan/rules", json={"deload_enabled": True})

    this_monday = _monday_of(date.today())
    last_monday = this_monday - timedelta(days=7)
    _add_workout(client, last_monday, 316)

    r = client.get("/api/plan/load-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deload_enabled"] is True
    week4 = next(w for w in body["weeks"] if w["week_index"] == 4)
    assert week4["deload"] is True


def test_ceiling_moves_instead_of_flatlining_on_the_live_endpoint(bare_client):
    client, user_id = bare_client
    race_date = _race_date_in_week(19)
    _add_a_race(client, race_date)
    # A large ramp so several weeks clamp — trailing_28d_avg will end up low
    # since only a couple of workouts are seeded.
    client.put("/api/plan/rules", json={"ramp_rate": 0.09})
    this_monday = _monday_of(date.today())
    last_monday = this_monday - timedelta(days=7)
    _add_workout(client, last_monday, 300)

    r = client.get("/api/plan/load-plan")
    assert r.status_code == 200, r.text
    weeks = r.json()["weeks"]
    clamped = [w["target_tss"] for w in weeks if w["clamped"]]
    if len(clamped) >= 2:
        assert len(set(clamped)) > 1, "clamped weeks must not flatline to one static ceiling"


# ── AC3: baseline uses actual TSS, not planned ──────────────────────────────

def test_baseline_ignores_planned_sessions(bare_client):
    client, user_id = bare_client
    race_date = _race_date_in_week(19)
    _add_a_race(client, race_date)

    this_monday = _monday_of(date.today())
    last_monday = this_monday - timedelta(days=7)
    _add_workout(client, last_monday, 150)

    # A planned session for the SAME week with a very different TSS must not
    # leak into baseline_tss — get_weekly_volume only reads Workout rows.
    r = client.post("/api/planned-sessions", json={
        "date": (last_monday + timedelta(days=2)).isoformat(),
        "workout_type": "run",
        "target_tss": 9999,
    })
    # Endpoint may reject a past-dated planned session (422) or accept it —
    # either way, baseline must reflect only the logged 150 TSS.
    r2 = client.get("/api/plan/load-plan")
    assert r2.status_code == 200, r2.text
    assert r2.json()["baseline_tss"] == pytest.approx(150.0, abs=0.1)


# ── AC4/AC5: PUT /api/plan/rules ─────────────────────────────────────────────

def test_put_plan_rules_updates_existing_row(bare_client):
    client, user_id = bare_client
    # A brand-new user has zero TrainingPlan rows until something get-or-creates
    # one — the first PUT is expected to create exactly one.
    r = client.get("/api/plans")
    assert r.status_code == 200
    assert len(r.json()) == 0

    r = client.put("/api/plan/rules", json={"ramp_rate": 0.06, "hold_weeks": 3, "taper_weeks": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ramp_rate"] == pytest.approx(0.06)
    assert body["hold_weeks"] == 3
    assert body["taper_weeks"] == pytest.approx(2.0)

    r = client.get("/api/plans")
    after_first_put = len(r.json())
    assert after_first_put == 1, "first PUT /api/plan/rules must create exactly one plan row"

    r = client.put("/api/plan/rules", json={"ramp_rate": 0.07})
    assert r.status_code == 200, r.text
    assert r.json()["ramp_rate"] == pytest.approx(0.07)
    # hold_weeks/taper_weeks from the first PUT must persist unchanged
    assert r.json()["hold_weeks"] == 3

    r = client.get("/api/plans")
    after_second_put = len(r.json())
    assert after_second_put == after_first_put, "PUT /api/plan/rules must not create a second plan row"


def test_put_plan_rules_rejects_ramp_rate_out_of_range(bare_client):
    client, user_id = bare_client
    r = client.put("/api/plan/rules", json={"ramp_rate": 0.5})
    assert r.status_code == 422, r.text
    r = client.put("/api/plan/rules", json={"ramp_rate": -0.01})
    assert r.status_code == 422, r.text


def test_put_plan_rules_rejects_negative_hold_or_taper(bare_client):
    client, user_id = bare_client
    r = client.put("/api/plan/rules", json={"hold_weeks": -1})
    assert r.status_code == 422, r.text
    r = client.put("/api/plan/rules", json={"taper_weeks": -1})
    assert r.status_code == 422, r.text


def test_load_plan_reflects_updated_rules(bare_client):
    client, user_id = bare_client
    race_date = _race_date_in_week(19)
    _add_a_race(client, race_date)
    client.put("/api/plan/rules", json={"ramp_rate": 0.08, "hold_weeks": 2, "taper_weeks": 3})

    r = client.get("/api/plan/load-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ramp_rate"] == pytest.approx(0.08)
    assert body["hold_weeks"] == 2


# ── AC6: auth required ───────────────────────────────────────────────────────

def test_load_plan_requires_auth():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as anon:
        r = anon.get("/api/plan/load-plan")
        assert r.status_code in (401, 403), f"expected auth-gated, got {r.status_code}"


def test_put_plan_rules_requires_auth():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as anon:
        r = anon.put("/api/plan/rules", json={"ramp_rate": 0.05})
        assert r.status_code in (401, 403), f"expected auth-gated, got {r.status_code}"
