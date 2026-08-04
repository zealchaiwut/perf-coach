"""Tests for the training_load_snapshots workout-signature invalidation fix.

Found live on the real account: training_load_snapshots.tss_for_day was 0 or
heavily undercounted for 3 of the last 4 weeks, while CTL/ATL/TSB are read
exclusively from this cached table (no independent recompute anywhere else).
Root cause: get_snapshot_series()'s cache-hit check only treated a row as
stale on a formula_version or EWMA-calibration mismatch -- never when the
underlying workout data for that date changed after the row was cached. A
snapshot computed before that day's workout was synced/logged just sat there
wrong indefinitely.

Fix mirrors backend/main.py's _SUMMARY_CACHE signature-invalidation pattern
(count/max(created_at)/max(updated_at)), scoped per snapshot-date instead of
globally since CTL/ATL/TSB are keyed by date.

In-memory SQLite harness, same shims as tests/test_1604_schema_consolidation.py
(JSONB compiled to JSON, now()/gen_random_uuid() registered as SQL functions).
Not auto-marked integration -- no live server, no backend.db import.
"""
from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as _OrmSess
from sqlalchemy.pool import StaticPool

try:  # pragma: no cover - registration is idempotent per process
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json_on_sqlite(type_, compiler, **kw):  # noqa: D401
        return "JSON"
except Exception:  # pragma: no cover - already registered by another module
    pass

from backend.models import Base, TrainingLoadSnapshot, User, Workout  # noqa: E402
from backend.services.training_load import (  # noqa: E402
    _NO_WORKOUTS_SIGNATURE,
    _day_workout_signature,
    _workout_signatures_for_range,
)

_UTC = datetime.timezone.utc


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_pg_functions(dbapi_conn, _record):  # pragma: no cover - plumbing
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(_UTC).isoformat(sep=" ")
        )
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    Base.metadata.create_all(
        engine,
        tables=[User.__table__, Workout.__table__, TrainingLoadSnapshot.__table__],
    )
    return engine


@pytest.fixture
def session_user(db_engine):
    with _OrmSess(db_engine) as session:
        user = User(
            id=uuid.uuid4(), name="load-sig-test", is_admin=False, is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(user)
        session.commit()
        yield session, user.id


def _add_workout(session, uid, d, tss=100.0):
    w = Workout(
        id=uuid.uuid4(), user_id=uid, workout_date=d, name="run",
        workout_type="run", tss=tss,
        created_at=datetime.datetime.now(_UTC),
    )
    session.add(w)
    session.commit()
    return w


# ── _day_workout_signature ───────────────────────────────────────────────────

def test_no_workouts_returns_the_shared_default_signature(session_user):
    session, uid = session_user
    d = datetime.date(2026, 7, 1)
    assert _day_workout_signature(session, uid, d) == _NO_WORKOUTS_SIGNATURE


def test_adding_a_workout_changes_the_signature(session_user):
    session, uid = session_user
    d = datetime.date(2026, 7, 1)
    before = _day_workout_signature(session, uid, d)
    _add_workout(session, uid, d)
    after = _day_workout_signature(session, uid, d)
    assert before != after
    assert before == _NO_WORKOUTS_SIGNATURE


def test_signature_only_reflects_the_target_date(session_user):
    """A workout logged on a DIFFERENT date must not change today's
    signature -- this check is deliberately per-day, not per-window (see
    _day_workout_signature's docstring for why)."""
    session, uid = session_user
    d = datetime.date(2026, 7, 1)
    other_day = datetime.date(2026, 7, 2)
    before = _day_workout_signature(session, uid, d)
    _add_workout(session, uid, other_day)
    after = _day_workout_signature(session, uid, d)
    assert before == after


def test_two_workouts_same_day_produce_a_count_of_two(session_user):
    session, uid = session_user
    d = datetime.date(2026, 7, 1)
    _add_workout(session, uid, d)
    _add_workout(session, uid, d)
    sig = _day_workout_signature(session, uid, d)
    assert sig.startswith("2|")


# ── _workout_signatures_for_range ────────────────────────────────────────────

def test_range_signature_matches_per_day_signature(session_user):
    """The batched range lookup and the single-day lookup must never
    disagree -- get_snapshot_series relies on exactly that equivalence."""
    session, uid = session_user
    d1 = datetime.date(2026, 7, 1)
    d2 = datetime.date(2026, 7, 3)
    _add_workout(session, uid, d1)

    range_sigs = _workout_signatures_for_range(session, uid, d1, d2)
    assert range_sigs[d1] == _day_workout_signature(session, uid, d1)
    assert range_sigs[d2] == _day_workout_signature(session, uid, d2)
    assert range_sigs[d2] == _NO_WORKOUTS_SIGNATURE


def test_range_signature_fills_every_date_including_rest_days(session_user):
    session, uid = session_user
    d1 = datetime.date(2026, 7, 1)
    d2 = datetime.date(2026, 7, 5)
    _add_workout(session, uid, d1)

    range_sigs = _workout_signatures_for_range(session, uid, d1, d2)
    assert set(range_sigs.keys()) == {
        d1, datetime.date(2026, 7, 2), datetime.date(2026, 7, 3),
        datetime.date(2026, 7, 4), d2,
    }
    for d in (datetime.date(2026, 7, 2), datetime.date(2026, 7, 3),
              datetime.date(2026, 7, 4), d2):
        assert range_sigs[d] == _NO_WORKOUTS_SIGNATURE


# ── The actual bug this exists to close ──────────────────────────────────────

def test_stale_row_has_a_mismatched_signature_after_a_late_workout(session_user):
    """Reproduces the live failure directly: a snapshot cached before that
    date's workout existed must be detectable as stale once the workout
    shows up, purely by comparing signatures -- this is the exact check
    get_snapshot_series performs before deciding whether to recompute."""
    session, uid = session_user
    d = datetime.date(2026, 7, 15)

    # Snapshot computed when the day had no workouts yet (the bug's
    # precondition -- e.g. a cron ran before the evening run was logged).
    stale_signature = _day_workout_signature(session, uid, d)
    snap = TrainingLoadSnapshot(
        id=uuid.uuid4(), user_id=uid, snapshot_date=d, tss_for_day=0,
        ctl=10.0, atl=10.0, tsb=0.0, formula_version="v1",
        workout_signature=stale_signature,
        computed_at=datetime.datetime.now(_UTC),
    )
    session.add(snap)
    session.commit()

    # The workout shows up later -- this is what actually happened live.
    _add_workout(session, uid, d, tss=176.0)

    current_signature = _day_workout_signature(session, uid, d)
    assert current_signature != snap.workout_signature, (
        "a snapshot cached before its date's workout existed must be "
        "detectable as stale once the workout is logged"
    )


def test_row_with_no_stored_signature_is_treated_as_stale(session_user):
    """Existing rows from before this column existed have workout_signature
    = NULL. get_snapshot_series's `existing[d].workout_signature != ...`
    check must treat None as never matching any real signature, so old rows
    self-heal on next read instead of needing a one-time bulk backfill."""
    session, uid = session_user
    d = datetime.date(2026, 7, 20)
    snap = TrainingLoadSnapshot(
        id=uuid.uuid4(), user_id=uid, snapshot_date=d, tss_for_day=50,
        ctl=10.0, atl=10.0, tsb=0.0, formula_version="v1",
        workout_signature=None,
        computed_at=datetime.datetime.now(_UTC),
    )
    session.add(snap)
    session.commit()

    current = _workout_signatures_for_range(session, uid, d, d)[d]
    assert snap.workout_signature != current
