"""Tests for issue #1369: Plyo and strength dose stats.

Acceptance criteria covered:
  AC1 — GET /api/training/structural-dose?weeks=N returns per-week plyo + strength counts,
        last_plyo_days_ago, last_strength_days_ago, foot_contact_trend direction
  AC2 — Strength counted from both strength_sessions and strength-type workouts, no double-count
  AC3 — Pure aggregation helpers unit-tested: trend direction boundaries, empty weeks, no-data
  AC4 — Payload shape documented in endpoint docstring
"""
from __future__ import annotations

import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

# ── Pure-function imports ─────────────────────────────────────────────────────
from backend.services.structural_dose import (
    FC_TREND_THRESHOLD,
    foot_contact_trend,
    dominant_phase,
    build_weekly_buckets,
)

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1369pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _create_and_login(client: httpx.Client) -> tuple[httpx.Client, str]:
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"sd_test_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201, f"create user failed: {r.text}"
    user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    bare.close()
    assert r.status_code == 200, f"login failed: {r.text}"

    session_cookie = r.cookies.get("session")
    csrf_token = r.cookies.get(CSRF_COOKIE_NAME)
    auth = httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return auth, user_id


def _delete_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        if u:
            sess.delete(u)
            sess.commit()


def _insert_plyo(user_id: str, session_date: datetime.date, foot_contacts: int, phase: str) -> None:
    with _OrmSess(_engine) as db:
        db.execute(
            text("""
                INSERT INTO plyo_sessions (id, user_id, session_date, foot_contacts, plyo_phase)
                VALUES (gen_random_uuid(), :uid, :d, :fc, :ph)
            """),
            {"uid": user_id, "d": session_date, "fc": foot_contacts, "ph": phase},
        )
        db.commit()


def _insert_strength_session(user_id: str, session_date: datetime.date) -> None:
    with _OrmSess(_engine) as db:
        db.execute(
            text("""
                INSERT INTO strength_sessions (id, user_id, session_date, sets, reps)
                VALUES (gen_random_uuid(), :uid, :d, 3, 8)
            """),
            {"uid": user_id, "d": session_date},
        )
        db.commit()


def _insert_strength_workout(user_id: str, workout_date: datetime.date) -> None:
    with _OrmSess(_engine) as db:
        db.execute(
            text("""
                INSERT INTO workouts (id, user_id, workout_date, name, workout_type)
                VALUES (gen_random_uuid(), :uid, :d, 'Strength', 'strength')
            """),
            {"uid": user_id, "d": workout_date},
        )
        db.commit()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC3: Pure function unit tests ─────────────────────────────────────────────

class TestFootContactTrend:
    """AC3: foot_contact_trend boundaries and edge cases."""

    def test_rising_when_recent_well_above_threshold(self):
        # recent 2 weeks avg = 100, prev 2 weeks avg = 20 → delta = 80 > threshold
        weekly_fc = [20, 20, 100, 100]  # oldest → newest
        assert foot_contact_trend(weekly_fc) == "rising"

    def test_falling_when_recent_well_below_threshold(self):
        weekly_fc = [100, 100, 20, 20]  # oldest → newest
        assert foot_contact_trend(weekly_fc) == "falling"

    def test_flat_when_delta_within_threshold(self):
        # small difference — within threshold
        t = FC_TREND_THRESHOLD
        weekly_fc = [50, 50, 50 + t - 1, 50 + t - 1]
        assert foot_contact_trend(weekly_fc) == "flat"

    def test_flat_on_zero_data(self):
        weekly_fc = [0, 0, 0, 0]
        assert foot_contact_trend(weekly_fc) == "flat"

    def test_flat_on_empty(self):
        assert foot_contact_trend([]) == "flat"

    def test_flat_on_fewer_than_four_weeks(self):
        # only 2 weeks — can't split into two halves of 2
        assert foot_contact_trend([100]) == "flat"

    def test_exactly_at_threshold_is_flat(self):
        t = FC_TREND_THRESHOLD
        weekly_fc = [50, 50, 50 + t, 50 + t]
        # delta == threshold → still flat (not strictly above)
        assert foot_contact_trend(weekly_fc) == "flat"

    def test_one_above_threshold_is_rising(self):
        t = FC_TREND_THRESHOLD
        weekly_fc = [50, 50, 50 + t + 1, 50 + t + 1]
        assert foot_contact_trend(weekly_fc) == "rising"


class TestDominantPhase:
    """AC3: dominant_phase helper."""

    def test_returns_most_common_phase(self):
        sessions = [("intro",), ("build",), ("build",), ("maintain",)]
        assert dominant_phase(sessions) == "build"

    def test_returns_none_on_empty(self):
        assert dominant_phase([]) is None

    def test_single_phase(self):
        assert dominant_phase([("maintain",)]) == "maintain"


class TestBuildWeeklyBuckets:
    """AC3: build_weekly_buckets produces correct empty structure for no-data user."""

    def test_empty_produces_n_zero_buckets(self):
        today = datetime.date(2026, 7, 13)  # Monday
        buckets = build_weekly_buckets(today, weeks=4)
        assert len(buckets) == 4
        for b in buckets:
            assert b["plyo_sessions"] == 0
            assert b["foot_contacts"] == 0
            assert b["dominant_plyo_phase"] is None
            assert b["strength_days"] == 0

    def test_week_starts_are_mondays(self):
        today = datetime.date(2026, 7, 13)  # Monday
        buckets = build_weekly_buckets(today, weeks=3)
        for b in buckets:
            d = datetime.date.fromisoformat(b["week_start"])
            assert d.weekday() == 0, f"week_start {b['week_start']} is not a Monday"

    def test_weeks_param_controls_count(self):
        today = datetime.date(2026, 7, 13)
        assert len(build_weekly_buckets(today, weeks=8)) == 8
        assert len(build_weekly_buckets(today, weeks=1)) == 1

    def test_bucket_dates_are_consecutive_mondays(self):
        today = datetime.date(2026, 7, 13)
        buckets = build_weekly_buckets(today, weeks=4)
        dates = [datetime.date.fromisoformat(b["week_start"]) for b in buckets]
        for i in range(1, len(dates)):
            assert (dates[i] - dates[i - 1]).days == 7


# ── AC1: Endpoint shape tests (live server) ──────────────────────────────────

def test_ac1_unauthenticated_returns_401(client):
    """AC1: Unauthenticated request returns 401."""
    r = client.get("/api/training/structural-dose")
    assert r.status_code == 401


def test_ac1_default_weeks_is_8(client):
    """AC1: Default weeks=8 returns 8 weekly buckets."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/training/structural-dose")
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["weekly"]) == 8
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac1_weeks_param_controls_bucket_count(client):
    """AC1: ?weeks=4 returns 4 weekly buckets."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/training/structural-dose", params={"weeks": 4})
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["weekly"]) == 4
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac1_no_data_user_returns_zeros_and_null_recency(client):
    """AC1 + UAT step 2: User with no data gets zeros and null recency, no errors."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/training/structural-dose", params={"weeks": 4})
        assert r.status_code == 200, r.text
        data = r.json()

        # All weekly buckets have zeros
        for week in data["weekly"]:
            assert week["plyo_sessions"] == 0
            assert week["foot_contacts"] == 0
            assert week["dominant_plyo_phase"] is None
            assert week["strength_days"] == 0

        assert data["last_plyo_days_ago"] is None
        assert data["last_strength_days_ago"] is None
        assert data["foot_contact_trend"] in ("rising", "flat", "falling")
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac1_response_has_required_top_level_keys(client):
    """AC1: Response payload has all documented top-level keys."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/training/structural-dose")
        assert r.status_code == 200, r.text
        data = r.json()
        required = {"weeks", "window_start", "window_end", "weekly", "last_plyo_days_ago",
                    "last_strength_days_ago", "foot_contact_trend"}
        assert required <= set(data.keys()), f"Missing keys: {required - set(data.keys())}"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac1_weekly_bucket_has_required_keys(client):
    """AC1: Each weekly bucket has the documented sub-keys."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/training/structural-dose")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["weekly"], "Expected at least one weekly bucket"
        bucket = data["weekly"][0]
        required = {"week_start", "plyo_sessions", "foot_contacts", "dominant_plyo_phase", "strength_days"}
        assert required <= set(bucket.keys()), f"Missing bucket keys: {required - set(bucket.keys())}"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac1_plyo_counts_match_inserted_sessions(client):
    """AC1 + UAT step 1: Weekly plyo counts match inserted sessions."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        # Insert 2 plyo sessions in the current week
        monday = today - datetime.timedelta(days=today.weekday())
        _insert_plyo(user_id, monday, 100, "build")
        _insert_plyo(user_id, monday, 50, "build")

        r = auth.get("/api/training/structural-dose", params={"weeks": 2})
        assert r.status_code == 200, r.text
        data = r.json()

        # Find the current week bucket
        current_week = next(
            (b for b in data["weekly"] if b["week_start"] == monday.isoformat()),
            None,
        )
        assert current_week is not None, f"Current week not found in {[b['week_start'] for b in data['weekly']]}"
        assert current_week["plyo_sessions"] == 2
        assert current_week["foot_contacts"] == 150
        assert current_week["dominant_plyo_phase"] == "build"

        assert data["last_plyo_days_ago"] is not None
        assert data["last_plyo_days_ago"] <= (today - monday).days
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac1_foot_contact_trend_direction_present(client):
    """AC1: foot_contact_trend is one of rising/flat/falling."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/training/structural-dose", params={"weeks": 8})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["foot_contact_trend"] in ("rising", "flat", "falling")
    finally:
        auth.close()
        _delete_user(user_id)


# ── AC2: Strength double-count prevention ─────────────────────────────────────

def test_ac2_strength_counts_both_tables(client):
    """AC2: strength_days counts sessions from strength_sessions table."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        _insert_strength_session(user_id, monday)

        r = auth.get("/api/training/structural-dose", params={"weeks": 2})
        assert r.status_code == 200, r.text
        data = r.json()

        current_week = next(
            (b for b in data["weekly"] if b["week_start"] == monday.isoformat()),
            None,
        )
        assert current_week is not None
        assert current_week["strength_days"] >= 1
        assert data["last_strength_days_ago"] is not None
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac2_strength_workout_type_counted(client):
    """AC2: strength_days also counts strength-type workouts."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        _insert_strength_workout(user_id, monday)

        r = auth.get("/api/training/structural-dose", params={"weeks": 2})
        assert r.status_code == 200, r.text
        data = r.json()

        current_week = next(
            (b for b in data["weekly"] if b["week_start"] == monday.isoformat()),
            None,
        )
        assert current_week is not None
        assert current_week["strength_days"] >= 1
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac2_no_double_count_same_day_both_tables(client):
    """AC2: Same day in both strength_sessions and workouts counts as 1 strength day."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        # Both a strength_sessions row AND a strength workout on the same date
        _insert_strength_session(user_id, monday)
        _insert_strength_workout(user_id, monday)

        r = auth.get("/api/training/structural-dose", params={"weeks": 2})
        assert r.status_code == 200, r.text
        data = r.json()

        current_week = next(
            (b for b in data["weekly"] if b["week_start"] == monday.isoformat()),
            None,
        )
        assert current_week is not None
        # Must be 1, not 2 — no double-count
        assert current_week["strength_days"] == 1
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac2_user_isolation(client):
    """AC2: One user's data never appears in another user's dose response."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth_a, user_id_a = _create_and_login(client)
    auth_b, user_id_b = _create_and_login(client)
    try:
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        # User B has plyo sessions; User A has none
        _insert_plyo(user_id_b, monday, 200, "maintain")

        r = auth_a.get("/api/training/structural-dose", params={"weeks": 2})
        assert r.status_code == 200, r.text
        data = r.json()

        # User A must see zeros
        for week in data["weekly"]:
            assert week["plyo_sessions"] == 0
            assert week["foot_contacts"] == 0
        assert data["last_plyo_days_ago"] is None
    finally:
        auth_a.close()
        auth_b.close()
        _delete_user(user_id_a)
        _delete_user(user_id_b)
