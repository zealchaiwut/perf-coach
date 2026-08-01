"""Tests for issue #1604 — S5 schema consolidation.

Three independent things, matching the ticket's scope:

1. ``habit_type`` is derived from ``tracking_type`` at write time rather than
   independently settable (Section A: pure; Section B: DB-backed).
2. ``weight_plans`` was merged onto ``weight_targets`` (``phase``,
   ``target_rate_kg_per_week``); WeightPlan no longer exists (Section A).
3. ``ensure_goal_habits``' check-then-insert race is closed by two partial
   unique indexes on ``habits`` plus a SAVEPOINT-protected insert-or-recover
   (Section B).

Section A runs everywhere (no DB). Section B uses the same in-memory-SQLite
harness as tests/test_lean_program__habits.py — JSONB compiled down to JSON,
now()/gen_random_uuid() registered as SQL functions, and only the tables each
test actually needs created via Base.metadata.create_all(tables=[...]) — so it
does not hit the "JSONB/UUID break SQLite" wall the rest of the suite avoids
by requiring real Postgres (see pytest.ini and tests/conftest.py). It does not
import backend.db or reference a live server, so it is NOT auto-marked
``integration`` and runs in CI.
"""
from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as _OrmSess
from sqlalchemy.pool import StaticPool

try:  # pragma: no cover - registration is idempotent per process
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json_on_sqlite(type_, compiler, **kw):  # noqa: D401
        return "JSON"
except Exception:  # pragma: no cover - already registered by another module
    pass

from backend.models import Base, Habit, User, UserPreferences, WeightTarget  # noqa: E402
from backend.services import goal_habits  # noqa: E402
from backend.services.goal_habits import (  # noqa: E402
    WEIGH_IN_SOURCE,
    ensure_goal_habits,
)
from backend.services.habits_repo import create_habit, derive_habit_type  # noqa: E402
from backend.services import coach_habit_targets  # noqa: E402
from backend.services.coach_habit_targets import (  # noqa: E402
    ZONE2_SOURCE,
    ensure_coach_tracked_habits,
)

# habits_repo.create_habit() relies on Habit.id's server_default
# (gen_random_uuid()) rather than setting it in Python — correct against real
# Postgres, which SQLAlchemy can postfetch via RETURNING. SQLite has no
# rowid-based postfetch path for a non-integer primary key, so without this,
# session.refresh() inside create_habit() can't find the row it just inserted.
# Assigning the id client-side before INSERT (mirroring what Postgres's
# server-side default effectively achieves) sidesteps that SQLite-only gap
# without touching the production code path.
from sqlalchemy import event as _sa_event  # noqa: E402


@_sa_event.listens_for(Habit, "before_insert")
def _assign_habit_id_for_sqlite(mapper, connection, target):  # pragma: no cover - plumbing
    if target.id is None:
        target.id = uuid.uuid4()

_UTC = datetime.timezone.utc


# ═════════════════════════════════════════════════════════════════════════════
# Section A — pure, no DB
# ═════════════════════════════════════════════════════════════════════════════

def test_derive_habit_type_daily_checkmark_is_binary():
    assert derive_habit_type("daily_checkmark") == "binary"


def test_derive_habit_type_weekly_minutes_is_duration():
    assert derive_habit_type("weekly_minutes") == "duration"


def test_derive_habit_type_weekly_count_is_count():
    assert derive_habit_type("weekly_count") == "count"


def test_derive_habit_type_weekly_quantity_is_count():
    assert derive_habit_type("weekly_quantity") == "count"


def test_derive_habit_type_none_returns_none():
    """No tracking_type -> nothing to derive; caller keeps its own fallback."""
    assert derive_habit_type(None) is None


def test_derive_habit_type_unknown_value_returns_none():
    assert derive_habit_type("not_a_real_tracking_type") is None


def test_weight_plan_model_no_longer_exists():
    """Regression pin: weight_plans was merged onto weight_targets (#1604)."""
    import backend.models as models
    assert not hasattr(models, "WeightPlan")
    assert not hasattr(models, "validate_weight_plan_required")


def test_weight_target_has_phase_and_rate_columns():
    for attr in ("phase", "target_rate_kg_per_week"):
        assert hasattr(WeightTarget, attr), f"WeightTarget missing attribute: {attr}"


def test_weight_target_phase_default_and_not_nullable():
    col = WeightTarget.__table__.c["phase"]
    assert col.nullable is False
    assert "cut" in str(col.server_default.arg)


def test_weight_target_rate_column_nullable():
    col = WeightTarget.__table__.c["target_rate_kg_per_week"]
    assert col.nullable is True


def test_weight_target_phase_check_constraint_present():
    names = {c.name for c in WeightTarget.__table__.constraints}
    assert "ck_weight_targets_phase_values" in names


# ═════════════════════════════════════════════════════════════════════════════
# Section B — DB-backed (in-memory SQLite)
# ═════════════════════════════════════════════════════════════════════════════

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
        engine, tables=[User.__table__, Habit.__table__, UserPreferences.__table__]
    )
    return engine


@pytest.fixture
def session_user(db_engine):
    with _OrmSess(db_engine) as session:
        user = User(
            id=uuid.uuid4(), name="s1604", is_admin=False, is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(user)
        session.commit()
        yield session, user.id


# ── 1. create_habit derives habit_type from tracking_type ───────────────────

def test_create_habit_derives_habit_type_from_tracking_type(session_user):
    """Real frontend flow: tracking_type is sent, habit_type is not."""
    session, uid = session_user
    habit = create_habit(session, uid, {
        "name": "Zone 2-ish",
        "tracking_type": "weekly_minutes",
    })
    assert habit.habit_type == "duration"


def test_create_habit_tracking_type_overrides_mismatched_habit_type(session_user):
    """tracking_type is the survivor column — it wins even if both are sent."""
    session, uid = session_user
    habit = create_habit(session, uid, {
        "name": "Mismatched",
        "tracking_type": "daily_checkmark",
        "habit_type": "count",  # would be wrong for daily_checkmark
    })
    assert habit.habit_type == "binary"


def test_create_habit_honors_explicit_habit_type_when_no_tracking_type(session_user):
    """The older v2-only creation path (habit_type + schedule_type, no
    tracking_type) has nothing to derive from — habit_type is still honored
    as given. Pins tests/test_825_ac_verification.py::
    test_ac10_no_hardcoded_habit_type_default's contract.
    """
    session, uid = session_user
    habit = create_habit(session, uid, {
        "name": "V2 only",
        "habit_type": "count",
        "schedule_type": "weekly",
    })
    assert habit.habit_type == "count"


# ── 5. ensure_goal_habits' race condition ────────────────────────────────────

def test_concurrent_insert_of_same_named_habit_is_rejected_at_the_db(session_user):
    """Sanity check that the partial unique index is actually live: two active
    habits with the same (user_id, name) cannot both exist.
    """
    session, uid = session_user
    session.add(Habit(
        id=uuid.uuid4(), user_id=uid, name="Dup", habit_type="binary",
        schedule_type="daily", tracking_type="daily_checkmark", active=True,
        is_archived=False, sort_order=0, display_order=0, section="general",
        created_at=datetime.datetime.now(_UTC),
    ))
    session.commit()

    session.add(Habit(
        id=uuid.uuid4(), user_id=uid, name="Dup", habit_type="binary",
        schedule_type="daily", tracking_type="daily_checkmark", active=True,
        is_archived=False, sort_order=1, display_order=1, section="general",
        created_at=datetime.datetime.now(_UTC),
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_race_lost_falls_back_to_the_winners_row(session_user, monkeypatch):
    """The exact race from the ticket: a concurrent request already inserted
    "Morning weigh-in" between our pre-check and our own insert attempt.
    ensure_goal_habits must not 500, must not create a second row, and must
    return the row the other request created.
    """
    session, uid = session_user

    winner = Habit(
        id=uuid.uuid4(), user_id=uid, name="Morning weigh-in", habit_type="binary",
        schedule_type="daily", tracking_type="daily_checkmark",
        auto_fill_source=WEIGH_IN_SOURCE, active=True, is_archived=False,
        sort_order=0, display_order=0, section="training",
        created_at=datetime.datetime.now(_UTC),
    )
    session.add(winner)
    session.commit()

    # Force our own pre-check to report "not found" for weigh_in specifically,
    # reproducing a transaction whose read happened before the winner's
    # commit became visible to it — the actual race condition (both requests'
    # SELECTs return nothing, both proceed to insert).
    real_find = goal_habits._find
    seen = {"weigh_in": 0}

    def _stale_find(db, user_id, *, source, name):
        if name == "Morning weigh-in" and seen["weigh_in"] == 0:
            seen["weigh_in"] += 1
            return None
        return real_find(db, user_id, source=source, name=name)

    monkeypatch.setattr(goal_habits, "_find", _stale_find)

    result = ensure_goal_habits(session, uid)
    session.commit()

    assert str(result["weigh_in"].id) == str(winner.id)
    rows = (
        session.query(Habit)
        .filter(
            Habit.user_id == uid,
            Habit.name == "Morning weigh-in",
            Habit.is_archived.is_(False),
        )
        .all()
    )
    assert len(rows) == 1, "the race must yield one row, not two"


def test_ensure_goal_habits_still_creates_all_three_after_a_lost_race(session_user, monkeypatch):
    """The other two goal habits are unaffected by protein_first losing its race."""
    session, uid = session_user

    winner = Habit(
        id=uuid.uuid4(), user_id=uid, name="Protein first", habit_type="binary",
        schedule_type="daily", tracking_type="daily_checkmark",
        auto_fill_source=None, active=True, is_archived=False,
        sort_order=0, display_order=0, section="training",
        created_at=datetime.datetime.now(_UTC),
    )
    session.add(winner)
    session.commit()

    real_find = goal_habits._find
    seen = {"n": 0}

    def _stale_find(db, user_id, *, source, name):
        if name == "Protein first" and seen["n"] == 0:
            seen["n"] += 1
            return None
        return real_find(db, user_id, source=source, name=name)

    monkeypatch.setattr(goal_habits, "_find", _stale_find)

    result = ensure_goal_habits(session, uid)
    session.commit()

    assert set(result.keys()) == {"weigh_in", "protein_first", "long_run_fuel"}
    assert str(result["protein_first"].id) == str(winner.id)
    assert session.query(Habit).filter(Habit.user_id == uid).count() == 3


def test_ensure_coach_tracked_habits_race_lost_falls_back_to_the_winners_row(session_user, monkeypatch):
    """Found during the pre-master-merge review: ensure_coach_tracked_habits
    (the Zone 2 habit) had the identical check-then-insert race as
    ensure_goal_habits, but wasn't given the same SAVEPOINT-protected fix
    when the partial unique indexes were added — so a two-tab race on
    GET /api/habits or GET /api/preferences would have raised an unhandled
    IntegrityError/500 instead of the pre-migration silent duplicate. This
    pins the fix the same way test_race_lost_falls_back_to_the_winners_row
    pins ensure_goal_habits'.
    """
    session, uid = session_user

    winner = Habit(
        id=uuid.uuid4(), user_id=uid, name="Zone 2", habit_type="duration",
        schedule_type="weekly", tracking_type="weekly_minutes",
        auto_fill_source=ZONE2_SOURCE, active=True, is_archived=False,
        sort_order=0, display_order=0, section="training",
        created_at=datetime.datetime.now(_UTC),
    )
    session.add(winner)
    session.commit()

    real_find = coach_habit_targets._find_by_source
    seen = {"n": 0}

    def _stale_find(db, user_id, source):
        if source == ZONE2_SOURCE and seen["n"] == 0:
            seen["n"] += 1
            return None
        return real_find(db, user_id, source)

    monkeypatch.setattr(coach_habit_targets, "_find_by_source", _stale_find)

    result = ensure_coach_tracked_habits(session, uid)
    session.commit()

    assert str(result["zone2"].id) == str(winner.id)
    rows = (
        session.query(Habit)
        .filter(
            Habit.user_id == uid,
            Habit.auto_fill_source == ZONE2_SOURCE,
            Habit.is_archived.is_(False),
        )
        .all()
    )
    assert len(rows) == 1, "the race must yield one row, not two"
