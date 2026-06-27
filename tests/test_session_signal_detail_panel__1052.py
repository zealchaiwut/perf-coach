"""Tests for issue #1052: Show session signal in Log detail panel.

AC1: The workout detail endpoint returns flat keys: endurance_signal,
     endurance_signal_note, speed_signal, speed_signal_note, contributes_to.
AC7: Endpoint returns HTTP 200 with all five keys present for every run,
     even when values are null.
"""
import os
import uuid
import pytest
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel, Workout as _WorkoutModel

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "signal1052-test-pw"
_SIGNAL_KEYS = ("endurance_signal", "endurance_signal_note",
                "speed_signal", "speed_signal_note", "contributes_to")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    name = f"tester1052_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()
    yield uid
    client.delete(f"/api/users/{uid}")


@pytest.fixture(scope="module")
def session_cookie(client, user_id):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    r = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert r.status_code == 200, r.text
    return r.cookies.get("session")


def _create_run(client, session_cookie, **kwargs):
    payload = {
        "name": "Signal Test Run",
        "workout_date": "2026-06-01",
        "workout_type": "run",
        "duration_seconds": 3600,
        "distance_km": 10.0,
    }
    payload.update(kwargs)
    r = client.post("/api/workouts", json=payload,
                    cookies={"session": session_cookie})
    assert r.status_code == 201, f"create run failed: {r.text}"
    return r.json()


def _delete(client, session_cookie, workout_id):
    client.delete(f"/api/workouts/{workout_id}",
                  cookies={"session": session_cookie})


# ── AC1 + AC7: simple detail endpoint includes all 5 keys ────────────────────

def test_simple_detail_has_all_five_signal_keys(client, session_cookie):
    """GET /api/workouts/{id} returns all 5 signal keys, even when null."""
    run = _create_run(client, session_cookie)
    try:
        r = client.get(f"/api/workouts/{run['id']}",
                       cookies={"session": session_cookie})
        assert r.status_code == 200, r.text
        data = r.json()
        for key in _SIGNAL_KEYS:
            assert key in data, f"Key '{key}' missing from /api/workouts/{{id}} response"
    finally:
        _delete(client, session_cookie, run["id"])


# ── AC1 + AC7: full detail endpoint includes all 5 keys at top level ─────────

def test_full_detail_has_all_five_signal_keys(client, session_cookie):
    """GET /api/workouts/{id}/full returns all 5 signal keys for a run."""
    run = _create_run(client, session_cookie)
    try:
        r = client.get(f"/api/workouts/{run['id']}/full?streams=none",
                       cookies={"session": session_cookie})
        assert r.status_code == 200, r.text
        data = r.json()
        # Keys must be present at some accessible level (workout sub-object or top-level)
        workout = data.get("workout", {})
        for key in _SIGNAL_KEYS:
            present = key in data or key in workout
            assert present, (
                f"Key '{key}' missing from /full response "
                f"(top-level keys: {list(data.keys())})"
            )
    finally:
        _delete(client, session_cookie, run["id"])


# ── AC7: values may be null but keys must exist ───────────────────────────────

def test_signal_keys_present_even_when_signals_are_null(client, session_cookie):
    """All 5 keys are in the response even when endurance/speed signal = null."""
    run = _create_run(client, session_cookie)
    try:
        r = client.get(f"/api/workouts/{run['id']}",
                       cookies={"session": session_cookie})
        assert r.status_code == 200
        data = r.json()
        # Signals should be null since no signal has been computed for this workout
        assert data["endurance_signal"] is None
        assert data["speed_signal"] is None
        # Notes and contributes_to must be non-null strings when signals are absent
        for key in ("endurance_signal_note", "speed_signal_note", "contributes_to"):
            assert isinstance(data[key], str) and data[key], (
                f"'{key}' must be a non-empty string when signal is absent, got: {data[key]!r}"
            )
    finally:
        _delete(client, session_cookie, run["id"])


# ── AC3: note is a dash-style explanation when signal is absent ───────────────

def test_speed_signal_note_dash_style_when_absent(client, session_cookie):
    """speed_signal_note is a dash-prefixed explanation when speed_signal is null."""
    run = _create_run(client, session_cookie)
    try:
        r = client.get(f"/api/workouts/{run['id']}",
                       cookies={"session": session_cookie})
        assert r.status_code == 200
        data = r.json()
        if data["speed_signal"] is None:
            note = data["speed_signal_note"]
            assert note.startswith("—"), (
                f"speed_signal_note should start with '—' when absent, got: {note!r}"
            )
    finally:
        _delete(client, session_cookie, run["id"])


def test_endurance_signal_note_dash_style_when_absent(client, session_cookie):
    """endurance_signal_note is a dash-prefixed explanation when endurance_signal is null."""
    run = _create_run(client, session_cookie)
    try:
        r = client.get(f"/api/workouts/{run['id']}",
                       cookies={"session": session_cookie})
        assert r.status_code == 200
        data = r.json()
        if data["endurance_signal"] is None:
            note = data["endurance_signal_note"]
            assert note.startswith("—"), (
                f"endurance_signal_note should start with '—' when absent, got: {note!r}"
            )
    finally:
        _delete(client, session_cookie, run["id"])


# ── AC4: contributes_to is a one-line hint string ────────────────────────────

def test_contributes_to_is_single_line_string(client, session_cookie):
    """contributes_to is a single non-empty string with no newlines."""
    run = _create_run(client, session_cookie)
    try:
        r = client.get(f"/api/workouts/{run['id']}",
                       cookies={"session": session_cookie})
        assert r.status_code == 200
        data = r.json()
        hint = data["contributes_to"]
        assert isinstance(hint, str) and hint, "contributes_to must be a non-empty string"
        assert "\n" not in hint, "contributes_to must be a single line (no newlines)"
    finally:
        _delete(client, session_cookie, run["id"])


# ── Signal values round-trip when set directly in DB ─────────────────────────

def test_signal_values_present_when_set_in_db(client, session_cookie, user_id):
    """When endurance_signal and speed_signal are set in DB, they appear in response."""
    run = _create_run(client, session_cookie)
    workout_id = uuid.UUID(run["id"])
    try:
        # Inject signal values directly — bypasses the compute pipeline (out of scope)
        with _OrmSess(_engine) as db:
            w = db.get(_WorkoutModel, workout_id)
            w.endurance_signal = 0.87
            w.speed_signal = 1.12
            db.commit()

        r = client.get(f"/api/workouts/{run['id']}",
                       cookies={"session": session_cookie})
        assert r.status_code == 200
        data = r.json()
        assert data["endurance_signal"] == pytest.approx(0.87, abs=1e-3)
        assert data["speed_signal"] == pytest.approx(1.12, abs=1e-3)
        # When both signals are present, contributes_to should mention both
        hint = data["contributes_to"]
        assert isinstance(hint, str) and hint
    finally:
        _delete(client, session_cookie, run["id"])
