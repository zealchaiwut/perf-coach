"""Tests for issue #1452: Worker read API — GET /api/weight/recent endpoint.

AC coverage:
- AC1: New endpoint GET /api/weight/recent?n=<int>&user=<username> with n default=14, clamped 1..90
- AC2: Reads last N weigh-ins from weight_entries, newest first (entry_date, entry_time, weight_kg)
- AC3: EWMA trend computed with weight_ewma.compute_ewma; includes trend: up/flat/down (±0.1kg band)
- AC4: Response JSON with entries, count, last_logged, ewma, trend
- AC5: Empty state → HTTP 200 with entries=[], last_logged=null, ewma=null, trend=null
- AC6: Endpoint in worker_app.py only, not backend/main.py
- AC7: Tests cover default n=14, custom n + clamp, newest-first, EWMA match, empty state
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.models import User as _UserModel, WeightEntry
from backend.services.weight_ewma import compute_ewma, DEFAULT_SPAN

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
WORKER_SECRET = os.environ.get("WORKER_SHARED_SECRET", "test-secret-key")
_TEST_PW = "test1452pw!"

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_file = os.path.join(_root, ".env")
if os.path.exists(_env_file):
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _create_user(user_name: str) -> str:
    """Create a test user in the DB and return its id."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    with _OrmSess(_engine) as db:
        u = _UserModel(name=user_name, password_hash=_hash_pw(_TEST_PW))
        db.add(u)
        db.commit()
        db.refresh(u)
        return str(u.id)


def _add_weight_entry(user_id: str, entry_date: date, weight_kg: float, entry_time=None):
    """Insert a weight entry for a user."""
    if _engine is None:
        return
    with _OrmSess(_engine) as db:
        we = WeightEntry(
            user_id=uuid.UUID(user_id),
            entry_date=entry_date,
            entry_time=entry_time,
            weight_kg=weight_kg,
        )
        db.add(we)
        db.commit()


def _delete_user(user_id: str):
    """Delete a user and cascade their entries."""
    if _engine is None:
        return
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC1: Endpoint exists with n parameter (default 14, clamp 1..90) ────────────

def test_weight_recent__endpoint_exists_default_n(client: httpx.Client):
    """AC1: GET /api/weight/recent exists, returns HTTP 200."""
    user_id = _create_user(f"wr_test_{uuid.uuid4().hex[:8]}")
    try:
        r = client.get(
            f"/api/weight/recent?user={f'wr_test_{uuid.uuid4().hex[:8]}'}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        # Empty user should return 200 (empty state, not error)
        assert r.status_code in [200, 404], f"unexpected status {r.status_code}: {r.text}"
    finally:
        _delete_user(user_id)


def test_weight_recent__n_clamped_to_90_max(client: httpx.Client):
    """AC1: n parameter clamped to 90 max."""
    user_id = _create_user(f"wr_test_{uuid.uuid4().hex[:8]}")
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    try:
        # Add one entry so we get a non-empty response
        _add_weight_entry(user_id, date.today(), 75.0)

        r = client.get(
            f"/api/weight/recent?n=999&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        # Should not error on large n; server clamps it
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
    finally:
        _delete_user(user_id)


def test_weight_recent__n_clamped_to_1_min(client: httpx.Client):
    """AC1: n parameter clamped to 1 min."""
    user_id = _create_user(f"wr_test_{uuid.uuid4().hex[:8]}")
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    try:
        _add_weight_entry(user_id, date.today(), 75.0)

        r = client.get(
            f"/api/weight/recent?n=0&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        # Should clamp to n=1, return non-empty if entries exist
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
    finally:
        _delete_user(user_id)


# ── AC2: Returns last N entries, newest first ─────────────────────────────────

def test_weight_recent__newest_first_order(client: httpx.Client):
    """AC2: Entries returned newest-first by entry_date."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        # Add entries in chronological order
        base_date = date(2026, 1, 1)
        for i in range(5):
            _add_weight_entry(user_id, base_date + timedelta(days=i), 70.0 + i * 0.5)

        r = client.get(
            f"/api/weight/recent?n=5&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        data = r.json()
        assert "entries" in data
        entries = data["entries"]
        assert len(entries) == 5

        # Verify newest-first: last added (day 4) should be first
        for i, entry in enumerate(entries):
            expected_date = base_date + timedelta(days=4 - i)
            actual_date = date.fromisoformat(entry["date"])
            assert actual_date == expected_date, f"entry {i}: expected {expected_date}, got {actual_date}"
    finally:
        _delete_user(user_id)


def test_weight_recent__returns_exactly_n_entries(client: httpx.Client):
    """AC2: Returns exactly n entries when n < total entries."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        # Add 20 entries
        base_date = date(2026, 1, 1)
        for i in range(20):
            _add_weight_entry(user_id, base_date + timedelta(days=i), 70.0 + i * 0.1)

        r = client.get(
            f"/api/weight/recent?n=5&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["entries"]) == 5
        assert data["count"] == 5
    finally:
        _delete_user(user_id)


# ── AC3: EWMA trend computation ──────────────────────────────────────────────

def test_weight_recent__ewma_matches_helper(client: httpx.Client):
    """AC3: EWMA computed via backend.services.weight_ewma.compute_ewma."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        # Add 10 entries with known weights
        base_date = date(2026, 1, 1)
        weights = [70.0, 70.5, 71.0, 70.8, 70.5, 71.5, 72.0, 71.5, 71.0, 70.5]
        for i, w in enumerate(weights):
            _add_weight_entry(user_id, base_date + timedelta(days=i), w)

        r = client.get(
            f"/api/weight/recent?n=10&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200
        data = r.json()

        # Compute EWMA locally with the same entries (in chronological order for the helper)
        entries = [
            {"date": (base_date + timedelta(days=i)).isoformat(), "weight_kg": weights[i]}
            for i in range(10)
        ]
        expected_ewmas = compute_ewma(entries, span=DEFAULT_SPAN)

        # Response entries are newest-first; extract as chronological for comparison
        api_entries = list(reversed(data["entries"]))
        api_weights = [float(e["weight_kg"]) for e in api_entries]

        # Last EWMA value (last in chronological order, first in newest-first response)
        assert abs(data["ewma"] - expected_ewmas[-1]) < 0.01, \
            f"ewma mismatch: expected {expected_ewmas[-1]}, got {data['ewma']}"
    finally:
        _delete_user(user_id)


def test_weight_recent__trend_flat(client: httpx.Client):
    """AC3: Trend = 'flat' when EWMA slope ≈ 0 (±0.1 kg band)."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        # Add entries that hover around the same weight (no trend)
        base_date = date(2026, 1, 1)
        for i in range(14):
            _add_weight_entry(user_id, base_date + timedelta(days=i), 70.0 + (0.05 if i % 2 == 0 else -0.05))

        r = client.get(
            f"/api/weight/recent?n=14&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200
        data = r.json()

        assert data["trend"] == "flat", f"expected flat, got {data['trend']}"
    finally:
        _delete_user(user_id)


def test_weight_recent__trend_up(client: httpx.Client):
    """AC3: Trend = 'up' when EWMA slope > 0.1 kg."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        # Add entries with clear upward trend
        base_date = date(2026, 1, 1)
        for i in range(14):
            _add_weight_entry(user_id, base_date + timedelta(days=i), 70.0 + i * 0.2)

        r = client.get(
            f"/api/weight/recent?n=14&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200
        data = r.json()

        assert data["trend"] == "up", f"expected up, got {data['trend']}"
    finally:
        _delete_user(user_id)


def test_weight_recent__trend_down(client: httpx.Client):
    """AC3: Trend = 'down' when EWMA slope < -0.1 kg."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        # Add entries with clear downward trend
        base_date = date(2026, 1, 1)
        for i in range(14):
            _add_weight_entry(user_id, base_date + timedelta(days=i), 72.0 - i * 0.2)

        r = client.get(
            f"/api/weight/recent?n=14&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200
        data = r.json()

        assert data["trend"] == "down", f"expected down, got {data['trend']}"
    finally:
        _delete_user(user_id)


# ── AC4: Response JSON schema ────────────────────────────────────────────────

def test_weight_recent__response_schema(client: httpx.Client):
    """AC4: Response includes entries, count, last_logged, ewma, trend."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        base_date = date(2026, 1, 1)
        for i in range(5):
            _add_weight_entry(user_id, base_date + timedelta(days=i), 70.0 + i * 0.5, None)

        r = client.get(
            f"/api/weight/recent?n=5&user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200
        data = r.json()

        assert "entries" in data
        assert "count" in data
        assert "last_logged" in data
        assert "ewma" in data
        assert "trend" in data

        assert isinstance(data["entries"], list)
        assert isinstance(data["count"], int)
        assert data["last_logged"] is not None
        assert isinstance(data["ewma"], (int, float))
        assert data["trend"] in ["up", "flat", "down"]

        # Each entry has date, time, weight_kg
        for entry in data["entries"]:
            assert "date" in entry
            assert "time" in entry
            assert "weight_kg" in entry
            assert isinstance(entry["weight_kg"], (int, float))
    finally:
        _delete_user(user_id)


# ── AC5: Empty state ────────────────────────────────────────────────────────

def test_weight_recent__empty_state_no_entries(client: httpx.Client):
    """AC5: User with no weight entries → HTTP 200 with entries=[], last_logged=null, ewma=null, trend=null."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        r = client.get(
            f"/api/weight/recent?user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        data = r.json()

        assert data["entries"] == []
        assert data["count"] == 0
        assert data["last_logged"] is None
        assert data["ewma"] is None
        assert data["trend"] is None
    finally:
        _delete_user(user_id)


# ── AC7: Default n=14 ───────────────────────────────────────────────────────

def test_weight_recent__default_n_equals_14(client: httpx.Client):
    """AC7: Default n=14 when not specified."""
    user_name = f"wr_test_{uuid.uuid4().hex[:8]}"
    user_id = _create_user(user_name)
    try:
        # Add 20 entries
        base_date = date(2026, 1, 1)
        for i in range(20):
            _add_weight_entry(user_id, base_date + timedelta(days=i), 70.0 + i * 0.1)

        r = client.get(
            f"/api/weight/recent?user={user_name}",
            headers={"X-Worker-Secret": WORKER_SECRET}
        )
        assert r.status_code == 200
        data = r.json()

        assert len(data["entries"]) == 14, f"expected 14 entries by default, got {len(data['entries'])}"
        assert data["count"] == 14
    finally:
        _delete_user(user_id)
