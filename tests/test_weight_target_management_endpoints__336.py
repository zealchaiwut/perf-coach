"""Tests for issue #336: Add weight target management endpoints with state transitions (runs against UAT)
Updated for issue #488: endpoints now require session auth, no client user_id.
"""
import os
import uuid
import datetime
import pytest
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

TODAY = datetime.date.today().isoformat()
START_DATE = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
TARGET_DATE = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()
_WM336_PW = "wt336-test-pw"


def _create_user(client: httpx.Client) -> tuple[str, str]:
    name = f"wt336_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, f"Failed to create test user: {r.text}"
    uid = r.json()["id"]
    pw_hash = _hash_pw(_WM336_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    login_r = client.post("/api/auth/login", json={"username": name, "password": _WM336_PW})
    assert login_r.status_code == 200, f"Login failed: {login_r.text}"
    cookie = login_r.cookies.get("session")
    return uid, cookie


def _delete_user(client: httpx.Client, user_id: str) -> None:
    client.delete(f"/api/users/{user_id}")


def _create_target(client: httpx.Client, cookie: str, **overrides) -> dict:
    payload = {
        "start_weight_kg": 85.0,
        "start_date": START_DATE,
        "target_weight_kg": 75.0,
        "target_date": TARGET_DATE,
    }
    payload.update(overrides)
    r = client.post("/api/weight-targets", json=payload, cookies={"session": cookie})
    assert r.status_code == 201, f"Failed to create target: {r.text}"
    return r.json()


def _log_weight(client: httpx.Client, cookie: str, weight_kg: float, entry_date: str, entry_time: str = None) -> None:
    payload = {"entry_date": entry_date, "weight_kg": weight_kg}
    if entry_time:
        payload["entry_time"] = entry_time
    r = client.post("/api/weight-entries", json=payload, cookies={"session": cookie})
    assert r.status_code in (201, 409), f"Failed to log weight: {r.text}"


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- (a) POST creates target successfully ---

def test_weight_target_management_endpoints__post_creates_target_successfully(client):
    # AC: POST /api/weight-targets → 201 with status="active"
    uid, cookie = _create_user(client)
    try:
        r = client.post("/api/weight-targets", json={
            "start_weight_kg": 85.0,
            "start_date": START_DATE,
            "target_weight_kg": 75.0,
            "target_date": TARGET_DATE,
        }, cookies={"session": cookie})
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "active"
        assert data["start_weight_kg"] == 85.0
        assert data["target_weight_kg"] == 75.0
        assert "id" in data
    finally:
        _delete_user(client, uid)


# --- (b) POST with existing active target returns 409 with active_id ---

def test_weight_target_management_endpoints__post_returns_409_with_active_id(client):
    # AC: duplicate POST → 409 {"error_code": "active_target_exists", "active_id": "<uuid>"}
    uid, cookie = _create_user(client)
    try:
        first = _create_target(client, cookie)
        r = client.post("/api/weight-targets", json={
            "start_weight_kg": 85.0,
            "start_date": START_DATE,
            "target_weight_kg": 72.0,
            "target_date": TARGET_DATE,
        }, cookies={"session": cookie})
        assert r.status_code == 409
        data = r.json()
        assert data["error_code"] == "active_target_exists"
        assert data["active_id"] == first["id"]
        assert "message" in data
    finally:
        _delete_user(client, uid)


# --- (c) GET /active returns {"target": null} when no target ---

def test_weight_target_management_endpoints__get_active_returns_target_null(client):
    # AC: GET /active for user with no active target → 200 {"target": null}
    uid, cookie = _create_user(client)
    try:
        r = client.get("/api/weight-targets/active", cookies={"session": cookie})
        assert r.status_code == 200
        assert r.json() == {"target": None}
    finally:
        _delete_user(client, uid)


# --- (d) GET /active returns all computed fields when target exists ---

def test_weight_target_management_endpoints__get_active_returns_computed_fields(client):
    # AC: GET /active with weight entries → all computed fields present
    uid, cookie = _create_user(client)
    try:
        _create_target(client, cookie)
        # Log two weight entries in last 14 days to enable pace computation
        date1 = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        date2 = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        _log_weight(client, cookie, 84.0, date1, "07:00")
        _log_weight(client, cookie, 83.0, date2, "07:00")

        r = client.get("/api/weight-targets/active", cookies={"session": cookie})
        assert r.status_code == 200
        target = r.json()["target"]
        assert target is not None
        required_fields = [
            "progress_pct", "kg_to_go", "days_remaining",
            "required_pace_kg_per_week", "current_pace_kg_per_week",
            "projected_end_date", "status_label",
        ]
        for field in required_fields:
            assert field in target, f"Missing field: {field}"
        assert target["status_label"] in ("on_track", "behind", "ahead")
        assert 0 <= target["progress_pct"] <= 100
    finally:
        _delete_user(client, uid)


# --- (e) progress_pct is correct for partial weight loss ---

def test_weight_target_management_endpoints__progress_pct_correct(client):
    # AC: progress_pct = kg_lost / total_kg_to_lose * 100 (capped 0-100)
    uid, cookie = _create_user(client)
    try:
        # target: 85 → 75 kg = 10 kg total. After losing 5 kg (now 80), pct = 50%
        _create_target(client, cookie, start_weight_kg=85.0, target_weight_kg=75.0)
        today = datetime.date.today().isoformat()
        _log_weight(client, cookie, 80.0, today, "06:00")

        r = client.get("/api/weight-targets/active", cookies={"session": cookie})
        assert r.status_code == 200
        pct = r.json()["target"]["progress_pct"]
        assert abs(pct - 50.0) < 0.1, f"Expected ~50%, got {pct}"
    finally:
        _delete_user(client, uid)


# --- (f) GET /history returns ended targets sorted by ended_at DESC ---

def test_weight_target_management_endpoints__get_history_returns_sorted(client):
    # AC: GET /history sorted by ended_at DESC, includes achieved_weight_kg, achieved_pct, duration_days
    uid, cookie = _create_user(client)
    try:
        # Create and end first target
        t1 = _create_target(client, cookie)
        today = datetime.date.today().isoformat()
        _log_weight(client, cookie, 83.0, today, "06:30")
        client.post(f"/api/weight-targets/{t1['id']}/end", json={"status": "abandoned"},
                    cookies={"session": cookie})

        # Create and end second target
        t2 = _create_target(client, cookie)
        _log_weight(client, cookie, 82.5, today, "07:00")
        client.post(f"/api/weight-targets/{t2['id']}/end", json={"status": "achieved"},
                    cookies={"session": cookie})

        r = client.get("/api/weight-targets/history", cookies={"session": cookie})
        assert r.status_code == 200
        targets = r.json()["targets"]
        assert len(targets) >= 2
        # Most recent ended_at first
        for t in targets:
            assert "achieved_weight_kg" in t
            assert "achieved_pct" in t
            assert "duration_days" in t
        # Verify descending order
        ended_ats = [t["ended_at"] for t in targets if t["ended_at"]]
        assert ended_ats == sorted(ended_ats, reverse=True)
    finally:
        _delete_user(client, uid)


# --- (g) PATCH on active target succeeds ---

def test_weight_target_management_endpoints__patch_active_target_succeeds(client):
    # AC: PATCH active target with target_weight_kg, target_date, notes → 200 with updated values
    uid, cookie = _create_user(client)
    try:
        t = _create_target(client, cookie)
        new_target_date = (datetime.date.today() + datetime.timedelta(days=200)).isoformat()
        r = client.patch(f"/api/weight-targets/{t['id']}", json={
            "target_weight_kg": 77.0,
            "target_date": new_target_date,
            "notes": "updated note",
        }, cookies={"session": cookie})
        assert r.status_code == 200
        data = r.json()
        assert data["target_weight_kg"] == 77.0
        assert data["target_date"] == new_target_date
        assert data["notes"] == "updated note"
    finally:
        _delete_user(client, uid)


# --- (h) PATCH on non-active target returns 422 ---

def test_weight_target_management_endpoints__patch_non_active_returns_422(client):
    # AC: PATCH target that is not active → 422
    uid, cookie = _create_user(client)
    try:
        t = _create_target(client, cookie)
        today = datetime.date.today().isoformat()
        _log_weight(client, cookie, 83.0, today, "08:00")
        # End the target first
        client.post(f"/api/weight-targets/{t['id']}/end", json={"status": "abandoned"},
                    cookies={"session": cookie})
        # Now PATCH should fail
        r = client.patch(f"/api/weight-targets/{t['id']}", json={"target_weight_kg": 70.0},
                         cookies={"session": cookie})
        assert r.status_code == 422
    finally:
        _delete_user(client, uid)


# --- (i) POST /end transitions target to achieved ---

def test_weight_target_management_endpoints__post_end_transitions_to_achieved(client):
    # AC: POST /end with {"status": "achieved"} → 200, target.status="achieved", end_weight_kg set, ended_at set
    uid, cookie = _create_user(client)
    try:
        t = _create_target(client, cookie)
        today = datetime.date.today().isoformat()
        _log_weight(client, cookie, 81.5, today, "09:00")

        r = client.post(f"/api/weight-targets/{t['id']}/end", json={"status": "achieved"},
                        cookies={"session": cookie})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "achieved"
        assert data["end_weight_kg"] == 81.5
        assert data["ended_at"] is not None
    finally:
        _delete_user(client, uid)


# --- (j) After ending, a new POST /api/weight-targets succeeds ---

def test_weight_target_management_endpoints__new_target_after_end_succeeds(client):
    # AC: after ending a target, creating a new one returns 201 (no 409)
    uid, cookie = _create_user(client)
    try:
        t = _create_target(client, cookie)
        today = datetime.date.today().isoformat()
        _log_weight(client, cookie, 82.0, today, "10:00")
        client.post(f"/api/weight-targets/{t['id']}/end", json={"status": "abandoned"},
                    cookies={"session": cookie})

        r = client.post("/api/weight-targets", json={
            "start_weight_kg": 82.0,
            "start_date": START_DATE,
            "target_weight_kg": 72.0,
            "target_date": TARGET_DATE,
        }, cookies={"session": cookie})
        assert r.status_code == 201
        assert r.json()["status"] == "active"
    finally:
        _delete_user(client, uid)


# --- (k) POST /end with no recent weight entry returns 422 ---

def test_weight_target_management_endpoints__post_end_no_recent_weight_returns_422(client):
    # AC: POST /end when no weight logged in last 7 days → 422 with specific message
    uid, cookie = _create_user(client)
    try:
        t = _create_target(client, cookie)
        # Explicitly do NOT log any recent weight entry

        r = client.post(f"/api/weight-targets/{t['id']}/end", json={"status": "achieved"},
                        cookies={"session": cookie})
        assert r.status_code == 422
        assert "Log a recent weight before ending the target" in r.json().get("detail", "")
    finally:
        _delete_user(client, uid)
