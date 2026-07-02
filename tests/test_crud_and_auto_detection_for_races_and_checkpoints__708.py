"""Tests for issue #708: Add CRUD and Auto-Detection for Races and Checkpoints.

Acceptance criteria verified:
- AC-R1: POST /api/races creates a race (name, date, distance_km, priority, optional
         goal_time_seconds); returns 400 when date is invalid or distance_km <= 0.
- AC-R2: goal_pace_seconds_per_km computed when both goal_time_seconds and distance_km
         present; recomputed on update; never hardcoded.
- AC-R3: GET /api/races/:id returns the race for the authenticated user; 404 for another
         user's race.
- AC-R4: GET /api/races lists all races for the authenticated user.
- AC-R5: PATCH /api/races/:id updates any subset of mutable fields and recomputes pace.
- AC-R6: DELETE /api/races/:id removes the race and its associated checkpoints (cascade).
- AC-R7: B and C races stored in same races table, distinguished by priority column.
- AC-C1: POST /api/races/:race_id/checkpoints creates with name and at least one target
         field; returns 400 for missing/invalid fields; response has met=false,
         met_override=false.
- AC-C2: GET /api/races/:race_id/checkpoints/:id returns a single checkpoint.
- AC-C3: GET /api/races/:race_id/checkpoints lists all checkpoints for the race.
- AC-C4: PATCH /api/races/:race_id/checkpoints/:id updates mutable fields.
- AC-C5: DELETE /api/races/:race_id/checkpoints/:id removes the checkpoint.
- AC-C6: PATCH met=true/false sets met_override=true so auto-detection will not alter it.
- AC-D1: On ingest of a new run, every unmet non-overridden checkpoint is evaluated.
- AC-D2: Distance+pace checkpoint satisfied when run distance >= target AND pace faster
         than target within configurable tolerance.
- AC-D3: Duration checkpoint satisfied when elapsed time >= target_duration_seconds.
- AC-D4: When satisfied, met=True and met_workout_id = run's ID.
- AC-D5: met_override=True checkpoint never altered by auto-detection.
- AC-D6: Detection logic is a pure function with a worked example in its docstring.
- AC-D7: All threshold math uses named variables, never magic numbers.
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
from backend.models import Race as _Race, RaceCheckpoint as _RaceCheckpoint, User as _UserModel, Workout as _Workout
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "races708-test-pw"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    name = f"tester708_{uuid.uuid4().hex[:8]}"
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
def authed(user_id):
    """Authenticated httpx.Client for the primary test user."""
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        res = bare.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    session_cookie = res.cookies.get("session")
    csrf_token = res.cookies.get(CSRF_COOKIE_NAME)
    c = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield c
    c.close()


@pytest.fixture(scope="module")
def other_user_id(client):
    name = f"other708_{uuid.uuid4().hex[:8]}"
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
def other_authed(other_user_id):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(other_user_id))
        name = u.name
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        res = bare.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    session_cookie = res.cookies.get("session")
    csrf_token = res.cookies.get(CSRF_COOKIE_NAME)
    c = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield c
    c.close()


# ── AC-R1: POST /api/races creates race ──────────────────────────────────────

def test_ac_r1_create_race_with_date_field_returns_201(authed):
    """AC-R1: POST /api/races with date field creates a race and returns 201 (UAT Step 1)."""
    r = authed.post("/api/races", json={
        "name": "Boston",
        "date": "2027-04-19",
        "distance_km": 42.195,
        "priority": "A",
        "goal_time_seconds": 10800,
    })
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["name"] == "Boston"
    assert data["distance_km"] == pytest.approx(42.195, rel=1e-3)
    assert data["priority"] == "A"
    race_id = data["id"]
    # Clean up
    authed.delete(f"/api/races/{race_id}")


def test_ac_r1_invalid_date_returns_400(authed):
    """AC-R1: POST /api/races with invalid date returns 400 referencing 'date' (UAT Step 2)."""
    r = authed.post("/api/races", json={
        "name": "Bad Date Race",
        "date": "not-a-date",
        "distance_km": 5.0,
        "priority": "C",
    })
    assert r.status_code == 400, f"Expected 400 for invalid date, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "date" in str(detail).lower(), f"Error must reference 'date': {detail}"


def test_ac_r1_zero_distance_returns_400(authed):
    """AC-R1: POST /api/races with distance_km=0 returns 400."""
    r = authed.post("/api/races", json={
        "name": "Zero Distance",
        "date": "2027-06-01",
        "distance_km": 0,
        "priority": "B",
    })
    assert r.status_code == 400, f"Expected 400 for distance_km=0, got {r.status_code}: {r.text}"


def test_ac_r1_negative_distance_returns_400(authed):
    """AC-R1: POST /api/races with distance_km < 0 returns 400."""
    r = authed.post("/api/races", json={
        "name": "Negative Distance",
        "date": "2027-06-01",
        "distance_km": -1.0,
        "priority": "B",
    })
    assert r.status_code == 400, f"Expected 400 for negative distance, got {r.status_code}: {r.text}"


# ── AC-R2: goal_pace_seconds_per_km computed ─────────────────────────────────

def test_ac_r2_goal_pace_computed_on_create(authed):
    """AC-R2: goal_pace_seconds_per_km = goal_time_seconds / distance_km on create (UAT Step 1)."""
    r = authed.post("/api/races", json={
        "name": "Boston Pace Test",
        "date": "2027-04-19",
        "distance_km": 42.195,
        "priority": "A",
        "goal_time_seconds": 10800,
    })
    assert r.status_code == 201, r.text
    data = r.json()
    expected_pace = round(10800 / 42.195)  # ≈ 256
    assert data["goal_pace_seconds_per_km"] == expected_pace, (
        f"Expected pace ≈ {expected_pace}, got {data['goal_pace_seconds_per_km']}"
    )
    authed.delete(f"/api/races/{data['id']}")


def test_ac_r2_goal_pace_null_when_no_goal_time(authed):
    """AC-R2: goal_pace_seconds_per_km is null when goal_time_seconds is absent."""
    r = authed.post("/api/races", json={
        "name": "No Goal Time Race",
        "date": "2027-05-01",
        "distance_km": 21.1,
        "priority": "B",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["goal_pace_seconds_per_km"] is None, (
        f"Expected null pace when no goal_time_seconds, got {data['goal_pace_seconds_per_km']}"
    )
    authed.delete(f"/api/races/{data['id']}")


# ── AC-R3: GET /api/races/:id ─────────────────────────────────────────────────

def test_ac_r3_get_race_by_id_returns_own_race(authed):
    """AC-R3: GET /api/races/:id returns the race for its owner."""
    r = authed.post("/api/races", json={
        "name": "My Race",
        "date": "2028-01-01",
        "distance_km": 10.0,
        "priority": "C",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = authed.get(f"/api/races/{race_id}")
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == race_id

    authed.delete(f"/api/races/{race_id}")


def test_ac_r3_get_other_users_race_returns_404(authed, other_authed):
    """AC-R3: GET /api/races/:id returns 404 for another user's race."""
    r = other_authed.post("/api/races", json={
        "name": "Other's Race",
        "date": "2028-02-01",
        "distance_km": 5.0,
        "priority": "C",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = authed.get(f"/api/races/{race_id}")
    assert r2.status_code == 404, f"Expected 404 for another user's race, got {r2.status_code}"

    other_authed.delete(f"/api/races/{race_id}")


# ── AC-R4: GET /api/races lists all races ─────────────────────────────────────

def test_ac_r4_list_races_returns_only_own(authed, other_authed):
    """AC-R4: GET /api/races returns only the authenticated user's races."""
    r1 = authed.post("/api/races", json={"name": "Mine 1", "date": "2028-03-01", "distance_km": 5.0, "priority": "A"})
    r2 = authed.post("/api/races", json={"name": "Mine 2", "date": "2028-04-01", "distance_km": 10.0, "priority": "B"})
    r3 = other_authed.post("/api/races", json={"name": "Not Mine", "date": "2028-05-01", "distance_km": 5.0, "priority": "C"})
    assert r1.status_code == 201 and r2.status_code == 201 and r3.status_code == 201

    id1, id2, id3 = r1.json()["id"], r2.json()["id"], r3.json()["id"]

    rl = authed.get("/api/races")
    assert rl.status_code == 200
    ids = [r["id"] for r in rl.json()]
    assert id1 in ids
    assert id2 in ids
    assert id3 not in ids, "Another user's race must not appear in the list"

    authed.delete(f"/api/races/{id1}")
    authed.delete(f"/api/races/{id2}")
    other_authed.delete(f"/api/races/{id3}")


# ── AC-R5: PATCH /api/races/:id updates fields ────────────────────────────────

def test_ac_r5_patch_race_updates_fields(authed):
    """AC-R5: PATCH /api/races/:id updates mutable fields and returns updated record."""
    r = authed.post("/api/races", json={
        "name": "Patch Test Race",
        "date": "2028-06-01",
        "distance_km": 10.0,
        "priority": "C",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = authed.patch(f"/api/races/{race_id}", json={"name": "Updated Name", "priority": "B"})
    assert r2.status_code == 200, f"PATCH expected 200, got {r2.status_code}: {r2.text}"
    data = r2.json()
    assert data["name"] == "Updated Name"
    assert data["priority"] == "B"

    authed.delete(f"/api/races/{race_id}")


def test_ac_r5_patch_race_recomputes_pace(authed):
    """AC-R5: PATCH /api/races/:id recomputes goal_pace_seconds_per_km when relevant fields change."""
    r = authed.post("/api/races", json={
        "name": "Pace Recompute Race",
        "date": "2028-07-01",
        "distance_km": 42.195,
        "priority": "A",
        "goal_time_seconds": 12600,
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]
    original_pace = r.json()["goal_pace_seconds_per_km"]
    assert original_pace is not None

    r2 = authed.patch(f"/api/races/{race_id}", json={"goal_time_seconds": 10800})
    assert r2.status_code == 200, r2.text
    new_pace = r2.json()["goal_pace_seconds_per_km"]
    expected = round(10800 / 42.195)
    assert new_pace == expected, f"Expected pace {expected}, got {new_pace}"
    assert new_pace != original_pace

    authed.delete(f"/api/races/{race_id}")


# ── AC-R6: DELETE /api/races/:id cascades checkpoints ────────────────────────

def test_ac_r6_delete_race_cascades_checkpoints(authed):
    """AC-R6: DELETE /api/races/:id removes race and associated checkpoints (UAT Step 7)."""
    r = authed.post("/api/races", json={
        "name": "Cascade Delete Race",
        "date": "2028-08-01",
        "distance_km": 21.1,
        "priority": "B",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    # Create two checkpoints
    c1 = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Checkpoint Alpha",
        "target_distance_km": 10.0,
    })
    c2 = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Checkpoint Beta",
        "target_duration_seconds": 3600,
    })
    assert c1.status_code == 201, c1.text
    assert c2.status_code == 201, c2.text

    # Delete the race
    rd = authed.delete(f"/api/races/{race_id}")
    assert rd.status_code == 204, f"Expected 204, got {rd.status_code}: {rd.text}"

    # Race should be gone
    rg = authed.get(f"/api/races/{race_id}")
    assert rg.status_code == 404

    # Checkpoints should also be gone (cascade)
    cl = authed.get(f"/api/races/{race_id}/checkpoints")
    assert cl.status_code in (404, 200), cl.text
    if cl.status_code == 200:
        assert cl.json() == [], f"Checkpoints should be empty after race deletion: {cl.json()}"


# ── AC-R7: B and C races in same table ───────────────────────────────────────

def test_ac_r7_b_and_c_races_in_same_table(authed):
    """AC-R7: B and C priority races are stored in the same races table (UAT Step 6)."""
    rb = authed.post("/api/races", json={
        "name": "B Priority Race",
        "date": "2028-09-01",
        "distance_km": 21.1,
        "priority": "B",
    })
    rc = authed.post("/api/races", json={
        "name": "C Priority Race",
        "date": "2028-10-01",
        "distance_km": 5.0,
        "priority": "C",
    })
    assert rb.status_code == 201, rb.text
    assert rc.status_code == 201, rc.text
    bid, cid = rb.json()["id"], rc.json()["id"]

    rl = authed.get("/api/races")
    assert rl.status_code == 200
    priorities = {r["id"]: r["priority"] for r in rl.json()}
    assert priorities.get(bid) == "B", "B race must show priority=B"
    assert priorities.get(cid) == "C", "C race must show priority=C"

    authed.delete(f"/api/races/{bid}")
    authed.delete(f"/api/races/{cid}")


# ── AC-C1: POST /api/races/:race_id/checkpoints ──────────────────────────────

def test_ac_c1_create_checkpoint_returns_201(authed):
    """AC-C1: POST /api/races/:race_id/checkpoints creates checkpoint; met and met_override default false (UAT Step 3)."""
    r = authed.post("/api/races", json={
        "name": "Checkpoint Race",
        "date": "2029-01-01",
        "distance_km": 42.195,
        "priority": "A",
        "goal_time_seconds": 10800,
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "15 km at goal pace",
        "target_distance_km": 15,
        "target_pace_seconds_per_km": 256,
    })
    assert rc.status_code == 201, f"Expected 201, got {rc.status_code}: {rc.text}"
    data = rc.json()
    assert data["name"] == "15 km at goal pace"
    assert data["met"] is False, f"met must default to false: {data}"
    assert data["met_override"] is False, f"met_override must default to false: {data}"
    assert data["target_distance_km"] == pytest.approx(15.0, rel=1e-3)
    assert data["target_pace_seconds_per_km"] == 256

    authed.delete(f"/api/races/{race_id}")


def test_ac_c1_create_checkpoint_with_duration_only(authed):
    """AC-C1: Checkpoint with only target_duration_seconds is accepted."""
    r = authed.post("/api/races", json={
        "name": "Duration Race",
        "date": "2029-02-01",
        "distance_km": 21.1,
        "priority": "B",
    })
    race_id = r.json()["id"]

    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "60 min run",
        "target_duration_seconds": 3600,
    })
    assert rc.status_code == 201, f"Expected 201 for duration-only checkpoint: {rc.text}"

    authed.delete(f"/api/races/{race_id}")


def test_ac_c1_create_checkpoint_missing_all_targets_returns_400(authed):
    """AC-C1: POST checkpoint with no target fields returns 400."""
    r = authed.post("/api/races", json={
        "name": "Target Missing Race",
        "date": "2029-03-01",
        "distance_km": 5.0,
        "priority": "C",
    })
    race_id = r.json()["id"]

    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "No targets",
    })
    assert rc.status_code == 400, f"Expected 400 for missing targets, got {rc.status_code}: {rc.text}"

    authed.delete(f"/api/races/{race_id}")


def test_ac_c1_create_checkpoint_missing_name_returns_400(authed):
    """AC-C1: POST checkpoint without name returns 400."""
    r = authed.post("/api/races", json={
        "name": "Name Missing Race",
        "date": "2029-04-01",
        "distance_km": 5.0,
        "priority": "C",
    })
    race_id = r.json()["id"]

    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "target_distance_km": 5.0,
    })
    assert rc.status_code == 400, f"Expected 400 for missing name, got {rc.status_code}: {rc.text}"

    authed.delete(f"/api/races/{race_id}")


def test_ac_c1_create_checkpoint_for_unknown_race_returns_404(authed):
    """AC-C1: POST checkpoint to nonexistent race returns 404."""
    fake_id = str(uuid.uuid4())
    rc = authed.post(f"/api/races/{fake_id}/checkpoints", json={
        "name": "Ghost checkpoint",
        "target_distance_km": 5.0,
    })
    assert rc.status_code == 404, f"Expected 404 for unknown race, got {rc.status_code}"


# ── AC-C2: GET /api/races/:race_id/checkpoints/:id ───────────────────────────

def test_ac_c2_get_single_checkpoint(authed):
    """AC-C2: GET /api/races/:race_id/checkpoints/:id returns a single checkpoint."""
    r = authed.post("/api/races", json={
        "name": "Single CP Race",
        "date": "2029-05-01",
        "distance_km": 10.0,
        "priority": "C",
    })
    race_id = r.json()["id"]

    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Solo checkpoint",
        "target_duration_seconds": 1800,
    })
    cp_id = rc.json()["id"]

    rg = authed.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert rg.status_code == 200, f"Expected 200, got {rg.status_code}: {rg.text}"
    assert rg.json()["id"] == cp_id

    authed.delete(f"/api/races/{race_id}")


def test_ac_c2_get_nonexistent_checkpoint_returns_404(authed):
    """AC-C2: GET /api/races/:race_id/checkpoints/:id returns 404 for unknown checkpoint."""
    r = authed.post("/api/races", json={
        "name": "CP 404 Race",
        "date": "2029-06-01",
        "distance_km": 5.0,
        "priority": "C",
    })
    race_id = r.json()["id"]
    fake_cp = str(uuid.uuid4())

    rg = authed.get(f"/api/races/{race_id}/checkpoints/{fake_cp}")
    assert rg.status_code == 404, f"Expected 404, got {rg.status_code}"

    authed.delete(f"/api/races/{race_id}")


# ── AC-C3: GET /api/races/:race_id/checkpoints lists checkpoints ──────────────

def test_ac_c3_list_checkpoints(authed):
    """AC-C3: GET /api/races/:race_id/checkpoints lists all checkpoints for the race."""
    r = authed.post("/api/races", json={
        "name": "List CP Race",
        "date": "2029-07-01",
        "distance_km": 42.195,
        "priority": "A",
    })
    race_id = r.json()["id"]

    c1 = authed.post(f"/api/races/{race_id}/checkpoints", json={"name": "CP1", "target_distance_km": 10.0})
    c2 = authed.post(f"/api/races/{race_id}/checkpoints", json={"name": "CP2", "target_duration_seconds": 3600})
    assert c1.status_code == 201 and c2.status_code == 201

    rl = authed.get(f"/api/races/{race_id}/checkpoints")
    assert rl.status_code == 200, rl.text
    ids = [cp["id"] for cp in rl.json()]
    assert c1.json()["id"] in ids
    assert c2.json()["id"] in ids

    authed.delete(f"/api/races/{race_id}")


# ── AC-C4: PATCH /api/races/:race_id/checkpoints/:id updates fields ───────────

def test_ac_c4_patch_checkpoint_updates_fields(authed):
    """AC-C4: PATCH /api/races/:race_id/checkpoints/:id updates mutable fields."""
    r = authed.post("/api/races", json={
        "name": "Patch CP Race",
        "date": "2029-08-01",
        "distance_km": 10.0,
        "priority": "C",
    })
    race_id = r.json()["id"]
    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Old Name",
        "target_distance_km": 5.0,
    })
    cp_id = rc.json()["id"]

    rp = authed.patch(f"/api/races/{race_id}/checkpoints/{cp_id}", json={
        "name": "New Name",
        "target_distance_km": 8.0,
    })
    assert rp.status_code == 200, f"Expected 200, got {rp.status_code}: {rp.text}"
    data = rp.json()
    assert data["name"] == "New Name"
    assert data["target_distance_km"] == pytest.approx(8.0, rel=1e-3)

    authed.delete(f"/api/races/{race_id}")


# ── AC-C5: DELETE /api/races/:race_id/checkpoints/:id ────────────────────────

def test_ac_c5_delete_checkpoint(authed):
    """AC-C5: DELETE /api/races/:race_id/checkpoints/:id removes the checkpoint."""
    r = authed.post("/api/races", json={
        "name": "Delete CP Race",
        "date": "2029-09-01",
        "distance_km": 5.0,
        "priority": "C",
    })
    race_id = r.json()["id"]
    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "To be deleted",
        "target_duration_seconds": 900,
    })
    cp_id = rc.json()["id"]

    rd = authed.delete(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert rd.status_code == 204, f"Expected 204, got {rd.status_code}: {rd.text}"

    rg = authed.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert rg.status_code == 404, "Deleted checkpoint must return 404"

    authed.delete(f"/api/races/{race_id}")


# ── AC-C6: PATCH met sets met_override ───────────────────────────────────────

def test_ac_c6_manual_met_sets_override(authed):
    """AC-C6: PATCH met=true on a checkpoint sets met_override=True (UAT Step 5)."""
    r = authed.post("/api/races", json={
        "name": "Override Race",
        "date": "2029-10-01",
        "distance_km": 10.0,
        "priority": "C",
    })
    race_id = r.json()["id"]
    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Override CP",
        "target_distance_km": 5.0,
    })
    cp_id = rc.json()["id"]
    assert rc.json()["met_override"] is False

    rp = authed.patch(f"/api/races/{race_id}/checkpoints/{cp_id}", json={"met": True})
    assert rp.status_code == 200, rp.text
    data = rp.json()
    assert data["met"] is True
    assert data["met_override"] is True, (
        "Setting met manually must also set met_override=True"
    )

    authed.delete(f"/api/races/{race_id}")


def test_ac_c6_manual_unmet_sets_override(authed):
    """AC-C6: PATCH met=false on a checkpoint also sets met_override=True (UAT Step 5)."""
    r = authed.post("/api/races", json={
        "name": "Unmet Override Race",
        "date": "2029-11-01",
        "distance_km": 5.0,
        "priority": "C",
    })
    race_id = r.json()["id"]
    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Manual Unmet CP",
        "target_distance_km": 3.0,
    })
    cp_id = rc.json()["id"]

    rp = authed.patch(f"/api/races/{race_id}/checkpoints/{cp_id}", json={"met": False})
    assert rp.status_code == 200, rp.text
    data = rp.json()
    assert data["met"] is False
    assert data["met_override"] is True, "Setting met=False manually must set met_override=True"

    authed.delete(f"/api/races/{race_id}")


# ── AC-D1/D2/D4: auto-detection on run ingest ────────────────────────────────

def test_ac_d1_autodetection_on_run_ingest(authed, user_id):
    """AC-D1/D2/D4: Qualifying run flips checkpoint met=True and sets met_workout_id (UAT Step 4)."""
    r = authed.post("/api/races", json={
        "name": "Auto-detect Race",
        "date": "2030-01-01",
        "distance_km": 42.195,
        "priority": "A",
        "goal_time_seconds": 10800,
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "15 km at goal pace",
        "target_distance_km": 15.0,
        "target_pace_seconds_per_km": 256,
    })
    assert rc.status_code == 201, rc.text
    cp_id = rc.json()["id"]
    assert rc.json()["met"] is False

    # Ingest a qualifying run: 15.2 km at 254 s/km
    # 254 s/km over 15.2 km = 3860.8 seconds duration
    run_duration = round(254 * 15.2)
    rw = authed.post("/api/workouts", json={
        "name": "Test qualifying run",
        "workout_date": "2026-06-20",
        "workout_type": "run",
        "distance_km": 15.2,
        "duration_seconds": run_duration,
    })
    assert rw.status_code == 201, f"Failed to create workout: {rw.text}"
    workout_id = rw.json()["id"]

    # Verify checkpoint was auto-detected
    rg = authed.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert rg.status_code == 200, rg.text
    cp_data = rg.json()
    assert cp_data["met"] is True, f"Checkpoint must be met after qualifying run: {cp_data}"
    assert cp_data["met_workout_id"] == workout_id, (
        f"met_workout_id must equal the triggering workout id: {cp_data}"
    )

    authed.delete(f"/api/workouts/{workout_id}")
    authed.delete(f"/api/races/{race_id}")


# ── AC-D3: duration checkpoint auto-detection ─────────────────────────────────

def test_ac_d3_duration_checkpoint_autodetection(authed):
    """AC-D3: Duration checkpoint satisfied when run duration >= target_duration_seconds."""
    r = authed.post("/api/races", json={
        "name": "Duration Check Race",
        "date": "2030-02-01",
        "distance_km": 21.1,
        "priority": "B",
    })
    race_id = r.json()["id"]

    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Run 60 minutes",
        "target_duration_seconds": 3600,
    })
    cp_id = rc.json()["id"]
    assert rc.json()["met"] is False

    # Run for 3700 seconds (> 3600 target)
    rw = authed.post("/api/workouts", json={
        "name": "Long run",
        "workout_date": "2026-06-20",
        "workout_type": "run",
        "distance_km": 12.0,
        "duration_seconds": 3700,
    })
    assert rw.status_code == 201, rw.text
    workout_id = rw.json()["id"]

    rg = authed.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert rg.status_code == 200
    assert rg.json()["met"] is True, f"Duration checkpoint must be met: {rg.json()}"

    authed.delete(f"/api/workouts/{workout_id}")
    authed.delete(f"/api/races/{race_id}")


# ── AC-D5: met_override prevents auto-detection ────────────────────────────────

def test_ac_d5_met_override_prevents_autodetection(authed):
    """AC-D5: Checkpoint with met_override=True is not altered by auto-detection (UAT Step 5)."""
    r = authed.post("/api/races", json={
        "name": "Override Prevention Race",
        "date": "2030-03-01",
        "distance_km": 10.0,
        "priority": "C",
    })
    race_id = r.json()["id"]

    rc = authed.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Override protected CP",
        "target_distance_km": 5.0,
        "target_pace_seconds_per_km": 300,
    })
    cp_id = rc.json()["id"]

    # Manually set met=False (which also sets met_override=True)
    authed.patch(f"/api/races/{race_id}/checkpoints/{cp_id}", json={"met": False})

    # Verify met_override is True
    rg = authed.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert rg.json()["met_override"] is True

    # Ingest a qualifying run (>= 5km at pace <= 300 s/km)
    rw = authed.post("/api/workouts", json={
        "name": "Qualifying but overridden",
        "workout_date": "2026-06-20",
        "workout_type": "run",
        "distance_km": 6.0,
        "duration_seconds": 1680,  # 280 s/km — faster than 300
    })
    assert rw.status_code == 201, rw.text
    workout_id = rw.json()["id"]

    # Checkpoint must NOT be flipped to met=True
    rg2 = authed.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert rg2.json()["met"] is False, (
        f"Override-protected checkpoint must remain met=False: {rg2.json()}"
    )

    authed.delete(f"/api/workouts/{workout_id}")
    authed.delete(f"/api/races/{race_id}")


# ── AC-D6/D7: pure function unit tests ────────────────────────────────────────

def test_ac_d6_checkpoint_detector_is_importable():
    """AC-D6: checkpoint_detector module exists and exports evaluate_checkpoint."""
    from backend.services.checkpoint_detector import evaluate_checkpoint
    assert callable(evaluate_checkpoint)


def test_ac_d6_evaluate_checkpoint_has_docstring_with_worked_example():
    """AC-D6: evaluate_checkpoint docstring contains a worked example."""
    from backend.services.checkpoint_detector import evaluate_checkpoint
    doc = evaluate_checkpoint.__doc__ or ""
    assert len(doc) > 50, "evaluate_checkpoint must have a substantial docstring"
    # Verify the docstring describes a concrete example (numbers and outcome)
    assert any(char.isdigit() for char in doc), "Docstring must contain a worked numeric example"


def test_ac_d6_distance_pace_checkpoint_met_by_qualifying_run():
    """AC-D6: Pure function returns True for a qualifying distance+pace run."""
    from backend.services.checkpoint_detector import evaluate_checkpoint

    class FakeCheckpoint:
        met_override = False
        target_distance_km = 15.0
        target_pace_seconds_per_km = 256
        target_duration_seconds = None

    cp = FakeCheckpoint()
    # 15.2 km in 254 s/km → duration = 254 * 15.2 = 3860.8s
    run_duration = round(254 * 15.2)
    assert evaluate_checkpoint(cp, run_distance_km=15.2, run_duration_seconds=run_duration) is True


def test_ac_d6_distance_pace_checkpoint_not_met_insufficient_distance():
    """AC-D6: Pure function returns False when run distance is below target."""
    from backend.services.checkpoint_detector import evaluate_checkpoint

    class FakeCheckpoint:
        met_override = False
        target_distance_km = 15.0
        target_pace_seconds_per_km = 256
        target_duration_seconds = None

    cp = FakeCheckpoint()
    # Only 10 km but fast pace
    run_duration = round(250 * 10.0)
    assert evaluate_checkpoint(cp, run_distance_km=10.0, run_duration_seconds=run_duration) is False


def test_ac_d6_distance_pace_checkpoint_not_met_too_slow():
    """AC-D6: Pure function returns False when run pace is slower than target + tolerance."""
    from backend.services.checkpoint_detector import evaluate_checkpoint

    class FakeCheckpoint:
        met_override = False
        target_distance_km = 15.0
        target_pace_seconds_per_km = 256
        target_duration_seconds = None

    cp = FakeCheckpoint()
    # 15.2 km at 270 s/km — too slow (270 > 256 * 1.02 ≈ 261)
    run_duration = round(270 * 15.2)
    assert evaluate_checkpoint(cp, run_distance_km=15.2, run_duration_seconds=run_duration) is False


def test_ac_d6_met_override_returns_false():
    """AC-D6: evaluate_checkpoint returns False when met_override=True regardless of run."""
    from backend.services.checkpoint_detector import evaluate_checkpoint

    class FakeCheckpoint:
        met_override = True
        target_distance_km = 5.0
        target_pace_seconds_per_km = 300
        target_duration_seconds = None

    cp = FakeCheckpoint()
    assert evaluate_checkpoint(cp, run_distance_km=10.0, run_duration_seconds=2000) is False


def test_ac_d6_duration_checkpoint_met():
    """AC-D6: Pure function returns True for a qualifying duration run."""
    from backend.services.checkpoint_detector import evaluate_checkpoint

    class FakeCheckpoint:
        met_override = False
        target_distance_km = None
        target_pace_seconds_per_km = None
        target_duration_seconds = 3600

    cp = FakeCheckpoint()
    assert evaluate_checkpoint(cp, run_distance_km=12.0, run_duration_seconds=3700) is True


def test_ac_d6_duration_checkpoint_not_met():
    """AC-D6: Pure function returns False when run duration is below target."""
    from backend.services.checkpoint_detector import evaluate_checkpoint

    class FakeCheckpoint:
        met_override = False
        target_distance_km = None
        target_pace_seconds_per_km = None
        target_duration_seconds = 3600

    cp = FakeCheckpoint()
    assert evaluate_checkpoint(cp, run_distance_km=10.0, run_duration_seconds=3599) is False


def test_ac_d7_no_magic_numbers_in_detector():
    """AC-D7: checkpoint_detector module uses named constants, not bare magic numbers."""
    import ast, pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "backend/services/checkpoint_detector.py").read_text()
    tree = ast.parse(src)
    # Magic numbers are numeric literals that appear inside function bodies
    # (not at module level where they would be constant assignments)
    magic = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)):
                    # 0 and 1 are acceptable in comparisons (e.g. distance > 0, list len == 1)
                    if child.value not in (0, 1, -1, 2, 100):
                        magic.append(child.value)
    assert magic == [], (
        f"Magic numeric literals found inside functions: {magic}. "
        "Use named module-level constants instead."
    )
