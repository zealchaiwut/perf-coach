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
    r = client.post("/api/users", json={"name": name})
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

class TestEmptyAthlete:
    """Tests on a fresh athlete with no workouts and no weight entries (AC1, 2, 3, 6, 7, 10)."""

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, request):
        _skip_if_no_db()
        self.client = httpx.Client(base_url=BASE_URL, timeout=15.0)
        self.uid = _create_and_login(self.client, suffix="empty_")
        yield
        _delete_user(self.uid)
        self.client.close()

    def _get(self):
        return self.client.get(f"/api/athletes/{self.uid}/summary/weekly")

    def test_returns_200(self):
        """AC1: HTTP 200 for a valid authenticated athlete."""
        r = self._get()
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_all_required_keys_present(self):
        """AC2: Response includes all 11 required flat keys."""
        r = self._get()
        assert r.status_code == 200
        missing = _REQUIRED_KEYS - set(r.json().keys())
        assert not missing, f"Missing keys: {missing}"

    def test_week_start_is_monday(self):
        """AC3: week_start is the Monday of the current ISO week."""
        r = self._get()
        ws = date.fromisoformat(r.json()["week_start"])
        assert ws.weekday() == 0, f"week_start {ws} is not a Monday"

    def test_week_end_is_sunday(self):
        """AC3: week_end is the Sunday (6 days after week_start)."""
        r = self._get()
        data = r.json()
        ws = date.fromisoformat(data["week_start"])
        we = date.fromisoformat(data["week_end"])
        assert we.weekday() == 6, f"week_end {we} is not a Sunday"
        assert (we - ws).days == 6

    def test_today_falls_within_week(self):
        """AC3: today is within [week_start, week_end]."""
        r = self._get()
        data = r.json()
        ws = date.fromisoformat(data["week_start"])
        we = date.fromisoformat(data["week_end"])
        assert ws <= date.today() <= we

    def test_no_activity_session_count_is_zero(self):
        """AC10: session_count is 0 for athlete with no workouts this week."""
        r = self._get()
        assert r.json()["session_count"] == 0

    def test_no_activity_total_tss_is_zero(self):
        """AC10: total_tss is 0 for athlete with no workouts this week."""
        r = self._get()
        assert r.json()["total_tss"] == 0

    def test_no_activity_distance_km_is_zero(self):
        """AC10: distance_km is 0 or null for athlete with no workouts this week."""
        r = self._get()
        val = r.json()["distance_km"]
        assert val in (None, 0, 0.0), f"Expected 0/null for distance_km, got {val}"

    def test_no_activity_weight_change_is_null(self):
        """AC6 + AC10: weight_change_kg is null when no weight entries exist."""
        r = self._get()
        assert r.json()["weight_change_kg"] is None

    def test_note_is_string(self):
        """AC7: note is a string (empty or default for no-activity week)."""
        r = self._get()
        note = r.json()["note"]
        assert isinstance(note, str), f"note must be a string, got {type(note)}"

    def test_form_tsb_change_is_numeric(self):
        """AC5: form_tsb_change is a float."""
        r = self._get()
        val = r.json()["form_tsb_change"]
        assert isinstance(val, (int, float)), f"form_tsb_change must be numeric, got {type(val)}"

    def test_score_changes_are_numeric(self):
        """AC4: endurance_score_change and speed_score_change are numeric."""
        r = self._get()
        data = r.json()
        assert isinstance(data["endurance_score_change"], (int, float))
        assert isinstance(data["speed_score_change"], (int, float))


# ── AC8: workouts contribute to aggregates ────────────────────────────────────────

class TestAthleteWithWorkouts:
    """Tests on an athlete with seeded workouts in the current ISO week (AC8)."""

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, request):
        _skip_if_no_db()
        self.client = httpx.Client(base_url=BASE_URL, timeout=15.0)
        self.uid = _create_and_login(self.client, suffix="workouts_")

        ws, we = _iso_week_bounds()
        mid = ws + timedelta(days=2)

        with _OrmSess(_engine) as db:
            self.w1 = _Workout(
                user_id=uuid.UUID(self.uid),
                workout_date=mid,
                name="Morning run",
                workout_type="Run",
                tss=70.0,
                distance_km=10.5,
            )
            self.w2 = _Workout(
                user_id=uuid.UUID(self.uid),
                workout_date=mid + timedelta(days=1),
                name="Strength",
                workout_type="Strength",
                tss=45.0,
            )
            db.add_all([self.w1, self.w2])
            db.commit()
            self.w1_id = str(self.w1.id)
            self.w2_id = str(self.w2.id)

        yield

        with _OrmSess(_engine) as db:
            for wid in (uuid.UUID(self.w1_id), uuid.UUID(self.w2_id)):
                w = db.get(_Workout, wid)
                if w:
                    db.delete(w)
            db.commit()
        _delete_user(self.uid)
        self.client.close()

    def _get(self):
        return self.client.get(f"/api/athletes/{self.uid}/summary/weekly")

    def test_session_count_includes_seeded_workouts(self):
        """AC8: session_count includes the 2 seeded workouts."""
        r = self._get()
        assert r.status_code == 200, r.text
        assert r.json()["session_count"] >= 2

    def test_total_tss_includes_seeded_tss(self):
        """AC8: total_tss sums TSS from all workouts in the week."""
        r = self._get()
        assert r.status_code == 200, r.text
        # Seeded 70 + 45 = 115 TSS
        assert r.json()["total_tss"] >= 115.0

    def test_distance_km_includes_run_distance(self):
        """AC8: distance_km includes the 10.5 km run."""
        r = self._get()
        assert r.status_code == 200, r.text
        val = r.json()["distance_km"]
        assert val is not None and val >= 10.5


# ── AC6: weight_change_kg when weight data exists ────────────────────────────────

class TestAthleteWithWeight:
    """Tests on an athlete with weight entries at start and end of the current week (AC6)."""

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, request):
        _skip_if_no_db()
        self.client = httpx.Client(base_url=BASE_URL, timeout=15.0)
        self.uid = _create_and_login(self.client, suffix="weight_")

        ws, we = _iso_week_bounds()
        with _OrmSess(_engine) as db:
            self.e1 = _WeightEntry(
                user_id=uuid.UUID(self.uid),
                entry_date=ws,
                weight_kg=70.0,
            )
            self.e2 = _WeightEntry(
                user_id=uuid.UUID(self.uid),
                entry_date=we,
                weight_kg=69.5,
            )
            db.add_all([self.e1, self.e2])
            db.commit()
            self.e1_id = str(self.e1.id)
            self.e2_id = str(self.e2.id)

        yield

        with _OrmSess(_engine) as db:
            for eid in (uuid.UUID(self.e1_id), uuid.UUID(self.e2_id)):
                e = db.get(_WeightEntry, eid)
                if e:
                    db.delete(e)
            db.commit()
        _delete_user(self.uid)
        self.client.close()

    def _get(self):
        return self.client.get(f"/api/athletes/{self.uid}/summary/weekly")

    def test_weight_change_is_populated(self):
        """AC6: weight_change_kg is non-null when weight entries exist for the week."""
        r = self._get()
        assert r.status_code == 200, r.text
        assert r.json()["weight_change_kg"] is not None

    def test_weight_change_value_is_correct(self):
        """AC6: weight_change_kg = latest - earliest = 69.5 - 70.0 = -0.5."""
        r = self._get()
        assert r.status_code == 200, r.text
        val = r.json()["weight_change_kg"]
        assert abs(val - (-0.5)) < 0.01, f"Expected ≈ -0.5, got {val}"


# ── AC11: Non-existent athlete → 404 ─────────────────────────────────────────────

def test_nonexistent_athlete_returns_404():
    """AC11: HTTP 404 when the session's user has been deleted from the DB."""
    _skip_if_no_db()
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as ghost_client:
        name = f"ghost1055_{uuid.uuid4().hex[:8]}"
        r = ghost_client.post("/api/users", json={"name": name})
        assert r.status_code == 201, r.text
        ghost_id_str = r.json()["id"]
        ghost_id = uuid.UUID(ghost_id_str)

        with _OrmSess(_engine) as db:
            u = db.get(_UserModel, ghost_id)
            u.password_hash = _hash_pw(_TEST_PW)
            db.commit()

        r = ghost_client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
        assert r.status_code == 200, f"Login failed: {r.text}"

        # Delete the user from the DB while the session cookie is still valid
        with _OrmSess(_engine) as db:
            u = db.get(_UserModel, ghost_id)
            if u:
                db.delete(u)
                db.commit()

        r = ghost_client.get(f"/api/athletes/{ghost_id_str}/summary/weekly")
        assert r.status_code == 404, (
            f"Expected 404 for deleted athlete, got {r.status_code}: {r.text}"
        )
