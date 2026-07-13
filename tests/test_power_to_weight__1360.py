"""Unit + integration tests for issue #1360: GET /api/weight/power-to-weight.

AC coverage:
- AC1: series returns date / power_w / weight_kg / w_per_kg; current stat block
- AC2: missing power → available: false; series is empty; card hidden
- AC3: range tokens (7D, 30D, ALL) resolve to expected series lengths
- AC4: power_basis field present in every available response
- AC5: series math is correct (w_per_kg = power_w / weight_kg)
"""
from __future__ import annotations

import datetime
import os
import uuid

import pytest

from backend.services.power_to_weight import compute_power_to_weight_series

# ── Helpers ──────────────────────────────────────────────────────────────────

def _ewma_entry(date_str: str, weight_kg: float) -> dict:
    return {"date": datetime.date.fromisoformat(date_str), "weight_kg": weight_kg}


def _date_range(start: str, n: int) -> list[datetime.date]:
    d0 = datetime.date.fromisoformat(start)
    return [d0 + datetime.timedelta(days=i) for i in range(n)]


# ── AC5: series math ─────────────────────────────────────────────────────────

class TestSeriesMath:
    """AC5 – w_per_kg = power_w / weight_kg for every point that has both."""

    def test_single_point_math(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 1)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        assert result["available"] is True
        pt = result["series"][0]
        assert pt["power_w"] == 280
        assert pt["weight_kg"] == 80.0
        assert abs(pt["w_per_kg"] - 280 / 80.0) < 0.001

    def test_multi_point_math(self):
        entries = [
            _ewma_entry("2026-01-01", 80.0),
            _ewma_entry("2026-01-02", 79.5),
            _ewma_entry("2026-01-03", 79.0),
        ]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 3)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        for pt in result["series"]:
            expected = round(280 / pt["weight_kg"], 3)
            assert abs(pt["w_per_kg"] - expected) < 0.001

    def test_series_length_matches_range(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 7)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        assert len(result["series"]) == 7

    def test_weight_carried_forward_on_gap_days(self):
        # Only entry on day 1 → days 2-3 carry forward the same EWMA weight.
        entries = [_ewma_entry("2026-01-01", 80.0)]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 3)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        assert all(p["weight_kg"] == 80.0 for p in result["series"])
        assert all(p["w_per_kg"] is not None for p in result["series"])

    def test_null_weight_before_first_entry(self):
        # from_d is before the first entry → leading points have null weight.
        entries = [_ewma_entry("2026-01-03", 80.0)]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 3)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        assert result["series"][0]["weight_kg"] is None
        assert result["series"][0]["w_per_kg"] is None
        assert result["series"][-1]["weight_kg"] == 80.0

    def test_power_w_present_on_every_point(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 3)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        assert all(p["power_w"] == 280 for p in result["series"])

    def test_date_strings_are_iso(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 1)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        assert result["series"][0]["date"] == "2026-01-01"


# ── AC2: missing-power path ───────────────────────────────────────────────────

class TestMissingPower:
    """AC2 – no power data → available: false; series empty."""

    def test_none_power_returns_unavailable(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        result = compute_power_to_weight_series(
            entries, None, datetime.date(2026, 1, 1), datetime.date(2026, 1, 7)
        )
        assert result["available"] is False
        assert result["series"] == []
        assert result["current"] is None

    def test_zero_power_returns_unavailable(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        result = compute_power_to_weight_series(
            entries, 0, datetime.date(2026, 1, 1), datetime.date(2026, 1, 7)
        )
        assert result["available"] is False

    def test_power_basis_is_none_when_unavailable(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        result = compute_power_to_weight_series(
            entries, None, datetime.date(2026, 1, 1), datetime.date(2026, 1, 7)
        )
        assert result["power_basis"] is None


# ── AC4: power_basis field ────────────────────────────────────────────────────

class TestPowerBasis:
    """AC4 – power_basis is 'flat_current' when available."""

    def test_power_basis_flat_current(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        result = compute_power_to_weight_series(
            entries, 280, datetime.date(2026, 1, 1), datetime.date(2026, 1, 1)
        )
        assert result["power_basis"] == "flat_current"


# ── AC1: current stat block ───────────────────────────────────────────────────

class TestCurrentStatBlock:
    """AC1 – current block has w_per_kg, power_w, weight_kg, delta_30d."""

    def test_current_keys_present(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        result = compute_power_to_weight_series(
            entries, 280, datetime.date(2026, 1, 1), datetime.date(2026, 1, 1)
        )
        assert result["current"] is not None
        for key in ("w_per_kg", "power_w", "weight_kg", "delta_30d"):
            assert key in result["current"]

    def test_current_wkg_matches_latest_series_point(self):
        entries = [
            _ewma_entry("2026-01-01", 80.0),
            _ewma_entry("2026-01-10", 79.0),
        ]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 10)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        expected = round(280 / 79.0, 3)
        assert abs(result["current"]["w_per_kg"] - expected) < 0.001

    def test_delta_30d_is_none_when_range_shorter_than_30d(self):
        entries = [_ewma_entry("2026-01-01", 80.0)]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 1, 7)  # only 7 days → no 30-day baseline
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        assert result["current"]["delta_30d"] is None

    def test_delta_30d_computed_when_range_has_31_days(self):
        # 31-day range: first point is 30 days before last.
        entries = [
            _ewma_entry("2026-01-01", 80.0),
            _ewma_entry("2026-02-01", 78.0),
        ]
        from_d = datetime.date(2026, 1, 1)
        to_d = datetime.date(2026, 2, 1)
        result = compute_power_to_weight_series(entries, 280, from_d, to_d)
        expected_now = round(280 / 78.0, 3)
        expected_30d = round(280 / 80.0, 3)
        assert result["current"]["delta_30d"] == round(expected_now - expected_30d, 3)

    def test_current_is_none_when_no_weight_entries(self):
        result = compute_power_to_weight_series(
            [], 280, datetime.date(2026, 1, 1), datetime.date(2026, 1, 7)
        )
        assert result["current"] is None


# ── AC3: range handling via integration endpoint ─────────────────────────────

try:
    import httpx
    _BASE_URL = os.environ.get("UAT_BASE_URL") or (
        "http://localhost:" + os.environ.get("UAT_PORT", "9001")
    )
    _HAS_SERVER = True
except ImportError:
    _HAS_SERVER = False

_P2W_PW = "p2w1360test"


def _create_and_login(client) -> tuple[str, str]:
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import hash_password as _hash_pw
    from backend.db import engine as _engine
    from backend.models import User as _UserModel
    from tests._admin_helpers import admin_cookies as _admin_cookies

    name = f"p2w1360_{uuid.uuid4().hex[:6]}"
    r = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_P2W_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    lr = client.post("/api/auth/login", json={"username": name, "password": _P2W_PW})
    assert lr.status_code == 200, lr.text
    cookie = lr.cookies.get("session")
    return uid, cookie


def _delete_user(client, uid: str):
    from tests._admin_helpers import admin_cookies as _admin_cookies
    client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


def _set_ftp(client, cookie: str, ftp_w: int):
    r = client.patch("/api/user-preferences", json={"ftp_w": ftp_w}, cookies={"session": cookie})
    assert r.status_code == 200, r.text


def _log_weight(client, cookie: str, date_str: str, kg: float):
    r = client.post("/api/weight-entries", json={"entry_date": date_str, "weight_kg": kg},
                    cookies={"session": cookie})
    assert r.status_code in (201, 409), r.text


@pytest.fixture(scope="module")
def p2w_client_session():
    if not _HAS_SERVER:
        pytest.skip("httpx not available")
    if not _BASE_URL.startswith("http"):
        pytest.skip("UAT_BASE_URL not set")
    if os.getenv("ENVIRONMENT") != "uat":
        pytest.skip("integration test requires ENVIRONMENT=uat (Postgres-backed server)")

    with httpx.Client(base_url=_BASE_URL, timeout=10.0) as client:
        uid, cookie = _create_and_login(client)
        today = datetime.date.today()
        # Log 35 days of weight entries so 30D range has data + 30-day delta
        for i in range(35):
            d = today - datetime.timedelta(days=34 - i)
            _log_weight(client, cookie, d.isoformat(), 80.0 - i * 0.05)
        _set_ftp(client, cookie, 280)
        yield client, cookie, uid
        _delete_user(client, uid)


@pytest.mark.skipif(not _HAS_SERVER, reason="requires httpx")
class TestRangeHandling:
    """AC3 – range tokens resolve to expected series lengths and payload keys."""

    def test_default_range_returns_payload(self, p2w_client_session):
        client, cookie, _ = p2w_client_session
        r = client.get("/api/weight/power-to-weight", cookies={"session": cookie})
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        assert "series" in data
        assert "current" in data
        assert "power_basis" in data

    def test_30d_range(self, p2w_client_session):
        client, cookie, _ = p2w_client_session
        r = client.get("/api/weight/power-to-weight?range=30D", cookies={"session": cookie})
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        assert len(data["series"]) == 30

    def test_7d_range(self, p2w_client_session):
        client, cookie, _ = p2w_client_session
        r = client.get("/api/weight/power-to-weight?range=7D", cookies={"session": cookie})
        assert r.status_code == 200
        assert len(r.json()["series"]) == 7

    def test_invalid_range_returns_422(self, p2w_client_session):
        client, cookie, _ = p2w_client_session
        r = client.get("/api/weight/power-to-weight?range=BADRANGE", cookies={"session": cookie})
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self, p2w_client_session):
        client, _, _ = p2w_client_session
        r = client.get("/api/weight/power-to-weight")
        assert r.status_code == 401


@pytest.mark.skipif(not _HAS_SERVER, reason="requires httpx")
class TestMissingPowerIntegration:
    """AC2 – user without ftp_w set → available: false."""

    def test_no_ftp_returns_unavailable(self, p2w_client_session):
        client, _, _ = p2w_client_session
        # Create a fresh user with no ftp_w
        uid2, cookie2 = _create_and_login(client)
        try:
            today = datetime.date.today()
            _log_weight(client, cookie2, today.isoformat(), 80.0)
            r = client.get("/api/weight/power-to-weight", cookies={"session": cookie2})
            assert r.status_code == 200
            data = r.json()
            assert data["available"] is False
            assert data["series"] == []
        finally:
            _delete_user(client, uid2)
