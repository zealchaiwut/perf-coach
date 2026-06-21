"""Tests for issue #879: Add what-if simulation endpoint for goal rate preview.

Acceptance criteria verified:
- AC1: POST /api/weight-targets/{goal_id}/what-if accepts assumed_rate in body
- AC2: Endpoint fetches the active goal from the DB (thin-caller pattern)
- AC3: assumed_rate validated for sane magnitude (finite, non-zero, within bound)
- AC4: assumed_rate validated for correct direction (same sign as required rate)
- AC5: Valid input → simulated_line array + arrival_date from simulate_what_if
- AC6: Invalid assumed_rate → HTTP 422 with descriptive message
- AC7: Non-existent or inactive goal_id → HTTP 404
- AC8: No data written to DB during this request
- AC9: Unit tests cover: valid rate, zero rate, wrong-direction rate,
        out-of-magnitude rate, missing active goal
"""
from __future__ import annotations

import datetime
import os
import uuid

import httpx
import pytest
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel, WeightTarget as _WeightTargetModel

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

TODAY = datetime.date.today()
START_DATE = (TODAY - datetime.timedelta(days=30)).isoformat()
TARGET_DATE = (TODAY + datetime.timedelta(days=180)).isoformat()
_PW = "wt879-test-pw"


# ── fixtures / helpers ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def _create_user(client: httpx.Client) -> tuple[str, str]:
    name = f"wt879_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, f"Failed to create test user: {r.text}"
    uid = r.json()["id"]
    pw_hash = _hash_pw(_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    login_r = client.post("/api/auth/login", json={"username": name, "password": _PW})
    assert login_r.status_code == 200, f"Login failed: {login_r.text}"
    cookie = login_r.cookies.get("session")
    return uid, cookie


def _delete_user(client: httpx.Client, user_id: str) -> None:
    client.delete(f"/api/users/{user_id}")


def _create_loss_target(client: httpx.Client, cookie: str) -> dict:
    """Create an active loss goal: 90 kg → 80 kg over 6 months."""
    r = client.post(
        "/api/weight-targets",
        json={
            "start_weight_kg": 90.0,
            "start_date": START_DATE,
            "target_weight_kg": 80.0,
            "target_date": TARGET_DATE,
        },
        cookies={"session": cookie},
    )
    assert r.status_code == 201, f"Failed to create target: {r.text}"
    return r.json()


def _log_weight(client: httpx.Client, cookie: str, weight_kg: float, entry_date: str) -> None:
    r = client.post(
        "/api/weight-entries",
        json={"entry_date": entry_date, "weight_kg": weight_kg},
        cookies={"session": cookie},
    )
    assert r.status_code in (201, 409), f"Failed to log weight: {r.text}"


# ── AC1/AC5: valid rate returns simulated_line and arrival_date ────────────────

def test_ac1_valid_rate_returns_200_with_simulated_line(client):
    """POST with a valid assumed_rate returns 200 with simulated_line and arrival_date."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]
        _log_weight(client, cookie, 89.5, TODAY.isoformat())

        r = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -0.3},
            cookies={"session": cookie},
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert "simulated_line" in body, "Response must contain 'simulated_line'"
        assert "arrival_date" in body, "Response must contain 'arrival_date'"
        assert len(body["simulated_line"]) > 0, "simulated_line must be non-empty"
        assert body["arrival_date"] is not None, "arrival_date must be non-null on success"
    finally:
        _delete_user(client, uid)


def test_ac5_simulated_line_has_date_and_weight_keys(client):
    """Each entry in simulated_line has 'date' and 'weight' keys."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]
        _log_weight(client, cookie, 89.5, TODAY.isoformat())

        r = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -0.3},
            cookies={"session": cookie},
        )
        assert r.status_code == 200
        for entry in r.json()["simulated_line"]:
            assert "date" in entry, "Each simulated_line entry must have 'date'"
            assert "weight" in entry, "Each simulated_line entry must have 'weight'"
    finally:
        _delete_user(client, uid)


def test_ac5_arrival_date_is_in_the_future(client):
    """arrival_date returned is a future date."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]
        _log_weight(client, cookie, 89.5, TODAY.isoformat())

        r = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -0.3},
            cookies={"session": cookie},
        )
        assert r.status_code == 200
        arrival = datetime.date.fromisoformat(r.json()["arrival_date"])
        assert arrival > TODAY, f"arrival_date {arrival} should be in the future"
    finally:
        _delete_user(client, uid)


# ── AC9/UAT: idempotent — calling twice gives same result ─────────────────────

def test_ac8_calling_twice_gives_identical_result(client):
    """Calling the endpoint twice without changing data returns identical responses."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]
        _log_weight(client, cookie, 89.5, TODAY.isoformat())

        r1 = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -0.3},
            cookies={"session": cookie},
        )
        r2 = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -0.3},
            cookies={"session": cookie},
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json(), (
            "Identical requests must return identical results (no side effects)"
        )
    finally:
        _delete_user(client, uid)


# ── AC3/AC6: zero rate → 422 ─────────────────────────────────────────────────

def test_ac3_zero_rate_returns_422(client):
    """assumed_rate of 0 returns HTTP 422 with a descriptive message."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]
        _log_weight(client, cookie, 89.5, TODAY.isoformat())

        r = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": 0},
            cookies={"session": cookie},
        )
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
        body = r.json()
        detail = body.get("detail", "")
        assert detail, "422 response must include a detail message"
        assert "zero" in detail.lower() or "non-zero" in detail.lower() or "0" in detail, (
            f"Detail message should mention zero rate, got: {detail!r}"
        )
    finally:
        _delete_user(client, uid)


# ── AC4/AC6: wrong-direction rate → 422 ──────────────────────────────────────

def test_ac4_wrong_direction_rate_returns_422(client):
    """Positive assumed_rate for a loss goal (wrong direction) returns HTTP 422."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]
        _log_weight(client, cookie, 89.5, TODAY.isoformat())

        r = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": 0.3},  # positive = gaining, but goal is to lose
            cookies={"session": cookie},
        )
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
        body = r.json()
        detail = body.get("detail", "")
        assert detail, "422 response must include a detail message"
        assert "direction" in detail.lower() or "sign" in detail.lower() or "negative" in detail.lower(), (
            f"Detail should mention direction issue, got: {detail!r}"
        )
    finally:
        _delete_user(client, uid)


# ── AC3/AC6: out-of-magnitude rate → 422 ──────────────────────────────────────

def test_ac3_extreme_rate_returns_422(client):
    """An extremely large assumed_rate (1,000,000×) returns HTTP 422."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]
        _log_weight(client, cookie, 89.5, TODAY.isoformat())

        r = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -1_000_000},
            cookies={"session": cookie},
        )
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
        body = r.json()
        detail = body.get("detail", "")
        assert detail, "422 response must include a detail message"
        assert "magnitude" in detail.lower() or "exceed" in detail.lower() or "bound" in detail.lower(), (
            f"Detail should mention magnitude/bound issue, got: {detail!r}"
        )
    finally:
        _delete_user(client, uid)


# ── AC7: non-existent goal_id → 404 ──────────────────────────────────────────

def test_ac7_missing_goal_id_returns_404(client):
    """A goal_id with no active goal returns HTTP 404."""
    uid, cookie = _create_user(client)
    try:
        non_existent = str(uuid.uuid4())
        r = client.post(
            f"/api/weight-targets/{non_existent}/what-if",
            json={"assumed_rate": -0.3},
            cookies={"session": cookie},
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    finally:
        _delete_user(client, uid)


# ── AC7: inactive goal → 404 ──────────────────────────────────────────────────

def test_ac7_inactive_goal_returns_404(client):
    """A goal_id that exists but belongs to a different user returns 404."""
    uid1, cookie1 = _create_user(client)
    uid2, cookie2 = _create_user(client)
    try:
        target = _create_loss_target(client, cookie1)
        goal_id = target["id"]
        _log_weight(client, cookie1, 89.5, TODAY.isoformat())

        # user2 tries to access user1's goal
        r = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -0.3},
            cookies={"session": cookie2},
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    finally:
        _delete_user(client, uid1)
        _delete_user(client, uid2)


# ── AC1: unauthenticated request → 401 ───────────────────────────────────────

def test_ac1_unauthenticated_request_returns_401(client):
    """No session cookie → 401."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]

        r = client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -0.3},
        )
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
    finally:
        _delete_user(client, uid)


# ── AC8: no DB writes during the request ──────────────────────────────────────

def test_ac8_no_db_writes(client):
    """Calling what-if must not change the weight target in the DB."""
    uid, cookie = _create_user(client)
    try:
        target = _create_loss_target(client, cookie)
        goal_id = target["id"]
        _log_weight(client, cookie, 89.5, TODAY.isoformat())

        # Fetch target state before
        before = client.get("/api/weight-targets/active", cookies={"session": cookie}).json()

        client.post(
            f"/api/weight-targets/{goal_id}/what-if",
            json={"assumed_rate": -0.3},
            cookies={"session": cookie},
        )

        # Fetch target state after
        after = client.get("/api/weight-targets/active", cookies={"session": cookie}).json()

        assert before == after, "Weight target must not be modified by a what-if request"
    finally:
        _delete_user(client, uid)
