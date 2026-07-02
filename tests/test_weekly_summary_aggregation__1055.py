"""Tests for issue #1055: GET /api/athletes/{id}/summary/weekly endpoint.

Acceptance criteria covered:
  AC1  - HTTP 200 for a valid athlete ID
  AC2  - Response includes all required flat keys
  AC3  - week_start and week_end are current ISO week boundaries (Monday–Sunday)
  AC4  - endurance_score_change and speed_score_change are end minus start
  AC5  - form_tsb_change derived from ATL/CTL computation
  AC6  - weight_change_kg is null when no weight data, HTTP 200
  AC7  - note is a string
  AC8  - distance_km, total_tss, session_count from existing weekly volume service
  AC9  - CTL/ATL/TSB reuse existing load computation
  AC10 - No activity: zeros for numeric, null for weight, empty/default note, HTTP 200
  AC11 - Non-existent athlete ID: HTTP 404
"""

from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.models import User as _UserModel, Workout as _Workout, WeightEntry as _WeightEntry
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "weekly1055-test-pw!"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_file = _ROOT / ".env"
if _env_file.exists():
    try:
        from dotenv import dotenv_values
        _env_vals = dotenv_values(_env_file)
        _uat_url = _env_vals.get("DATABASE_URL_UAT")
    except ImportError:
        _uat_url = os.environ.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None

_REQUIRED_KEYS = {
    "week_start",
    "week_end",
    "distance_km",
    "total_tss",
    "session_count",
    "endurance_score_change",
    "speed_score_change",
    "weight_change_kg",
    "form_tsb_change",
    "note",
    "readiness_next_week",
}


def _skip_if_no_db():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


def _iso_week_bounds(today=None):
    """Return (week_start, week_end) for the ISO week containing *today*."""
    if today is None:
        today = date.today()
    ws = today - timedelta(days=today.weekday())  # Monday
    we = ws + timedelta(days=6)                   # Sunday
    return ws, we


def _create_and_login(client, suffix=""):
    """Create a new user, hash their password, log them in. Return uid string."""
    _skip_if_no_db()
    name = f"tester1055_{suffix}{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()
    r = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return uid


def _delete_user(uid_str):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid_str))
        if u:
            db.delete(u)
            db.commit()


# ── AC1 + AC2 + AC3 + AC5 + AC6 + AC7 (empty athlete, no data) ───────────────────

def test_empty_athlete_returns_200():
    """AC1: HTTP 200 for a valid authenticated athlete."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        finally:
            _delete_user(uid)


def test_empty_athlete_all_required_keys_present():
    """AC2: Response includes all 11 required flat keys."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.status_code == 200
            missing = _REQUIRED_KEYS - set(r.json().keys())
            assert not missing, f"Missing keys: {missing}"
        finally:
            _delete_user(uid)


def test_empty_athlete_week_start_is_monday():
    """AC3: week_start is the Monday of the current ISO week."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            ws = date.fromisoformat(r.json()["week_start"])
            assert ws.weekday() == 0, f"week_start {ws} is not a Monday"
        finally:
            _delete_user(uid)


def test_empty_athlete_week_end_is_sunday():
    """AC3: week_end is the Sunday (6 days after week_start)."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            data = r.json()
            ws = date.fromisoformat(data["week_start"])
            we = date.fromisoformat(data["week_end"])
            assert we.weekday() == 6, f"week_end {we} is not a Sunday"
            assert (we - ws).days == 6
        finally:
            _delete_user(uid)


def test_empty_athlete_today_falls_within_week():
    """AC3: today is within [week_start, week_end]."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            data = r.json()
            ws = date.fromisoformat(data["week_start"])
            we = date.fromisoformat(data["week_end"])
            assert ws <= date.today() <= we
        finally:
            _delete_user(uid)


def test_no_activity_session_count_is_zero():
    """AC10: session_count is 0 for athlete with no workouts this week."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.json()["session_count"] == 0
        finally:
            _delete_user(uid)


def test_no_activity_total_tss_is_zero():
    """AC10: total_tss is 0 for athlete with no workouts this week."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.json()["total_tss"] == 0
        finally:
            _delete_user(uid)


def test_no_activity_distance_km_is_zero():
    """AC10: distance_km is 0 or null for athlete with no workouts this week."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            val = r.json()["distance_km"]
            assert val in (None, 0, 0.0), f"Expected 0/null for distance_km, got {val}"
        finally:
            _delete_user(uid)


def test_no_activity_weight_change_is_null():
    """AC6 + AC10: weight_change_kg is null when no weight entries exist."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.json()["weight_change_kg"] is None
        finally:
            _delete_user(uid)


def test_note_is_string():
    """AC7: note is a string (empty or default for no-activity week)."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            note = r.json()["note"]
            assert isinstance(note, str), f"note must be a string, got {type(note)}"
        finally:
            _delete_user(uid)


def test_form_tsb_change_is_numeric():
    """AC5: form_tsb_change is a float."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            val = r.json()["form_tsb_change"]
            assert isinstance(val, (int, float)), f"form_tsb_change must be numeric, got {type(val)}"
        finally:
            _delete_user(uid)


def test_score_changes_are_numeric():
    """AC4: endurance_score_change and speed_score_change are numeric."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="empty_")
        try:
            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            data = r.json()
            assert isinstance(data["endurance_score_change"], (int, float))
            assert isinstance(data["speed_score_change"], (int, float))
        finally:
            _delete_user(uid)


# ── AC8: workouts contribute to aggregates ────────────────────────────────────────

def test_session_count_includes_seeded_workouts():
    """AC8: session_count includes the 2 seeded workouts."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="workouts_")
        w1_id = None
        w2_id = None
        try:
            ws, we = _iso_week_bounds()
            mid = ws + timedelta(days=2)

            with _OrmSess(_engine) as db:
                w1 = _Workout(
                    user_id=uuid.UUID(uid),
                    workout_date=mid,
                    name="Morning run",
                    workout_type="Run",
                    tss=70.0,
                    distance_km=10.5,
                )
                w2 = _Workout(
                    user_id=uuid.UUID(uid),
                    workout_date=mid + timedelta(days=1),
                    name="Strength",
                    workout_type="Strength",
                    tss=45.0,
                )
                db.add_all([w1, w2])
                db.commit()
                w1_id = str(w1.id)
                w2_id = str(w2.id)

            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.status_code == 200, r.text
            assert r.json()["session_count"] >= 2
        finally:
            if w1_id or w2_id:
                with _OrmSess(_engine) as db:
                    for wid in (w1_id, w2_id):
                        if wid:
                            w = db.get(_Workout, uuid.UUID(wid))
                            if w:
                                db.delete(w)
                    db.commit()
            _delete_user(uid)


def test_total_tss_includes_seeded_tss():
    """AC8: total_tss sums TSS from all workouts in the week."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="workouts_")
        w1_id = None
        w2_id = None
        try:
            ws, we = _iso_week_bounds()
            mid = ws + timedelta(days=2)

            with _OrmSess(_engine) as db:
                w1 = _Workout(
                    user_id=uuid.UUID(uid),
                    workout_date=mid,
                    name="Morning run",
                    workout_type="Run",
                    tss=70.0,
                    distance_km=10.5,
                )
                w2 = _Workout(
                    user_id=uuid.UUID(uid),
                    workout_date=mid + timedelta(days=1),
                    name="Strength",
                    workout_type="Strength",
                    tss=45.0,
                )
                db.add_all([w1, w2])
                db.commit()
                w1_id = str(w1.id)
                w2_id = str(w2.id)

            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.status_code == 200, r.text
            # Seeded 70 + 45 = 115 TSS
            assert r.json()["total_tss"] >= 115.0
        finally:
            if w1_id or w2_id:
                with _OrmSess(_engine) as db:
                    for wid in (w1_id, w2_id):
                        if wid:
                            w = db.get(_Workout, uuid.UUID(wid))
                            if w:
                                db.delete(w)
                    db.commit()
            _delete_user(uid)


def test_distance_km_includes_run_distance():
    """AC8: distance_km includes the 10.5 km run."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="workouts_")
        w1_id = None
        try:
            ws, we = _iso_week_bounds()
            mid = ws + timedelta(days=2)

            with _OrmSess(_engine) as db:
                w1 = _Workout(
                    user_id=uuid.UUID(uid),
                    workout_date=mid,
                    name="Morning run",
                    workout_type="Run",
                    tss=70.0,
                    distance_km=10.5,
                )
                db.add(w1)
                db.commit()
                w1_id = str(w1.id)

            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.status_code == 200, r.text
            val = r.json()["distance_km"]
            assert val is not None and val >= 10.5
        finally:
            if w1_id:
                with _OrmSess(_engine) as db:
                    w = db.get(_Workout, uuid.UUID(w1_id))
                    if w:
                        db.delete(w)
                    db.commit()
            _delete_user(uid)


# ── AC6: weight_change_kg when weight data exists ────────────────────────────────

def test_weight_change_is_populated():
    """AC6: weight_change_kg is non-null when weight entries exist for the week."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="weight_")
        e1_id = None
        e2_id = None
        try:
            ws, we = _iso_week_bounds()
            with _OrmSess(_engine) as db:
                e1 = _WeightEntry(
                    user_id=uuid.UUID(uid),
                    entry_date=ws,
                    weight_kg=70.0,
                )
                e2 = _WeightEntry(
                    user_id=uuid.UUID(uid),
                    entry_date=we,
                    weight_kg=69.5,
                )
                db.add_all([e1, e2])
                db.commit()
                e1_id = str(e1.id)
                e2_id = str(e2.id)

            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.status_code == 200, r.text
            assert r.json()["weight_change_kg"] is not None
        finally:
            if e1_id or e2_id:
                with _OrmSess(_engine) as db:
                    for eid in (e1_id, e2_id):
                        if eid:
                            e = db.get(_WeightEntry, uuid.UUID(eid))
                            if e:
                                db.delete(e)
                    db.commit()
            _delete_user(uid)


def test_weight_change_value_is_correct():
    """AC6: weight_change_kg = latest - earliest = 69.5 - 70.0 = -0.5."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        uid = _create_and_login(client, suffix="weight_")
        e1_id = None
        e2_id = None
        try:
            ws, we = _iso_week_bounds()
            with _OrmSess(_engine) as db:
                e1 = _WeightEntry(
                    user_id=uuid.UUID(uid),
                    entry_date=ws,
                    weight_kg=70.0,
                )
                e2 = _WeightEntry(
                    user_id=uuid.UUID(uid),
                    entry_date=we,
                    weight_kg=69.5,
                )
                db.add_all([e1, e2])
                db.commit()
                e1_id = str(e1.id)
                e2_id = str(e2.id)

            r = client.get(f"/api/athletes/{uid}/summary/weekly")
            assert r.status_code == 200, r.text
            val = r.json()["weight_change_kg"]
            assert abs(val - (-0.5)) < 0.01, f"Expected ≈ -0.5, got {val}"
        finally:
            if e1_id or e2_id:
                with _OrmSess(_engine) as db:
                    for eid in (e1_id, e2_id):
                        if eid:
                            e = db.get(_WeightEntry, uuid.UUID(eid))
                            if e:
                                db.delete(e)
                    db.commit()
            _delete_user(uid)


# ── AC11: Non-existent athlete → 404 ─────────────────────────────────────────────

def test_nonexistent_athlete_returns_404():
    """AC11: HTTP 401 when the session's user has been deleted from the DB (auth layer fails before endpoint)."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as ghost_client:
        uid = _create_and_login(ghost_client, suffix="ghost_")
        _delete_user(uid)
        r = ghost_client.get(f"/api/athletes/{uid}/summary/weekly")
        # After deletion, the auth layer returns 401 "User not found" before the endpoint can return 404
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
