"""Tests for issue #1698: 'This wk' and 'This mo' weight-rate pills must use the
same rate methodology.

Acceptance Criteria:
  AC1: When OLS-on-EWMA rate is readable, stats.delta_30d_kg equals
       weekly_rate_ewma_kg × 4 (not the raw two-point 30-day delta).
  AC2: When OLS-on-EWMA rate is unreadable (insufficient coverage), stats.delta_30d_kg
       falls back to the raw 30-day two-point delta, as it always has.
  AC3: When readable, stats.delta_30d_kg / stats.delta_7d_kg ≈ 4, confirming both
       pills are derived from the same OLS weekly rate.
"""
from __future__ import annotations

import datetime
import unittest.mock as mock
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import Session as OrmSession

from backend.main import app, resolve_user
from backend.models import Base, User, WeightEntry, WeightTarget

_TODAY = datetime.date.today()
_TABLES = [User.__table__, WeightEntry.__table__, WeightTarget.__table__]


def _mem_engine():
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(e, tables=_TABLES)
    return e


class _Stub:
    """Minimal auth stub returned by the resolve_user dependency override."""
    def __init__(self, uid):
        self.id = uid
        self.name = "pill1698"
        self.is_admin = False
        self.is_active = True


def _add_user(session):
    """Seed a User row in the DB; return a detachment-safe auth stub."""
    uid = uuid.uuid4()
    session.add(User(
        id=uid,
        name="pill1698_" + uuid.uuid4().hex[:6],
        is_admin=False,
        is_active=True,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    ))
    session.commit()
    return _Stub(uid)


def _seed_entries(session, user_id, *, n=31, start_kg=80.0, rate=-0.04):
    """One entry per day for n days ending on _TODAY (linear decline)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    for i in range(n):
        d = _TODAY - datetime.timedelta(days=n - 1 - i)
        session.add(WeightEntry(
            id=uuid.uuid4(),
            user_id=user_id,
            entry_date=d,
            weight_kg=round(start_kg + rate * i, 2),
            source="manual",
            created_at=now,
            updated_at=now,
        ))
    session.commit()


def _mock_rate_dict(*, readable, rate_kg_wk=None):
    return {
        "readable": readable,
        "rate_kg_wk": rate_kg_wk,
        "trend_kg": 79.5,
        "ci_kg_wk": 0.05 if readable else None,
        "state": "losing" if readable else "unknown",
        "gated": False,
        "gate_reason": None,
        "days_needed": 0,
        "coverage_pct": 95.0 if readable else 25.0,
        "needed_rate_kg_wk": None,
    }


def _chart_stats(engine, user, *, readable, rate_kg_wk):
    """Hit GET /api/weight-chart and return stats dict, with patched engine and auth."""
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        rate_dict = _mock_rate_dict(readable=readable, rate_kg_wk=rate_kg_wk)
        with (
            mock.patch("backend.main.engine", engine),
            mock.patch("backend.db.engine", engine),
            mock.patch("backend.main._weight_stats", return_value=rate_dict),
            mock.patch("backend.main._today_bkk", return_value=_TODAY),
        ):
            tc = TestClient(app, raise_server_exceptions=True)
            resp = tc.get("/api/weight-chart", params={"range": "30D", "include_target": "false"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        return resp.json()["stats"]
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC1 ──────────────────────────────────────────────────────────────────────

def test_ac1_delta_30d_kg_equals_ols_rate_times_four_when_readable():
    """AC1: delta_30d_kg = weekly_rate_ewma_kg × 4 when rate is readable."""
    e = _mem_engine()
    with OrmSession(e) as s:
        user = _add_user(s)
        _seed_entries(s, user.id)

    ols_weekly = -0.5
    stats = _chart_stats(e, user, readable=True, rate_kg_wk=ols_weekly)

    expected = round(ols_weekly * 4, 2)
    actual = stats["delta_30d_kg"]
    assert actual == expected, (
        f"AC1 FAIL: delta_30d_kg should be {expected} (weekly_rate × 4), "
        f"got {actual!r}. The 'This mo' pill must use the OLS rate, "
        f"not the raw two-point 30-day delta."
    )


def test_ac1_delta_7d_kg_equals_ols_weekly_rate_when_readable():
    """AC1 (sanity): delta_7d_kg is still the OLS weekly rate when readable."""
    e = _mem_engine()
    with OrmSession(e) as s:
        user = _add_user(s)
        _seed_entries(s, user.id)

    ols_weekly = -0.35
    stats = _chart_stats(e, user, readable=True, rate_kg_wk=ols_weekly)

    assert stats["delta_7d_kg"] == ols_weekly, (
        f"AC1 sanity FAIL: delta_7d_kg should be {ols_weekly}, got {stats['delta_7d_kg']!r}"
    )


# ── AC2 ──────────────────────────────────────────────────────────────────────

def test_ac2_delta_30d_kg_falls_back_to_raw_delta_when_unreadable():
    """AC2: delta_30d_kg is the raw two-point delta when OLS rate is unreadable."""
    e = _mem_engine()
    with OrmSession(e) as s:
        user = _add_user(s)
        # 31 entries: day 0 = 80.0, day 30 = 78.8 → raw 30d delta ≈ -1.2
        _seed_entries(s, user.id, n=31, start_kg=80.0, rate=-0.04)

    stats = _chart_stats(e, user, readable=False, rate_kg_wk=None)

    assert stats["delta_30d_kg"] is not None, "AC2 FAIL: raw fallback must not be None"
    # Raw delta for 30-day window (day 0 weight = 80.0, day 30 ≈ 78.8): ≈ -1.2
    # It must NOT be the OLS-derived value (which would be None * 4, hence None or 0).
    # Just verify it's a plausible raw delta (small magnitude).
    assert abs(stats["delta_30d_kg"]) < 3.0, (
        f"AC2 FAIL: unreadable fallback delta_30d_kg={stats['delta_30d_kg']!r} "
        f"looks too large — expected a ~1 kg raw two-point delta"
    )
    # Confirm it's not a rate-times-4 artifact (rate_kg_wk=None → would be None)
    # By definition: raw delta ≠ 0 * 4 = 0 when there is actual weight change
    assert stats["delta_30d_kg"] != 0.0, "AC2 FAIL: raw delta should not be exactly zero"


# ── AC3 ──────────────────────────────────────────────────────────────────────

def test_ac3_month_pill_is_four_times_week_pill_when_readable():
    """AC3: delta_30d_kg / delta_7d_kg == 4 exactly when both come from OLS rate."""
    e = _mem_engine()
    with OrmSession(e) as s:
        user = _add_user(s)
        _seed_entries(s, user.id)

    ols_weekly = -0.28
    stats = _chart_stats(e, user, readable=True, rate_kg_wk=ols_weekly)

    w = stats["delta_7d_kg"]
    m = stats["delta_30d_kg"]
    assert w is not None and m is not None, (
        f"AC3 FAIL: both pills must be non-None when readable; got week={w!r}, month={m!r}"
    )
    ratio = m / w
    assert abs(ratio - 4.0) < 0.01, (
        f"AC3 FAIL: delta_30d / delta_7d = {ratio:.4f}, expected 4.0. "
        f"'This mo' must be exactly 4× 'This wk' when both use the same OLS rate."
    )
