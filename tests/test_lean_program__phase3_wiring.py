"""Phase 3 loose ends — the wiring that made the built pieces actually reachable.

Three things were built in Phase 3 but not connected:

1. ``plan_extras.apply_prefs_extras`` existed and was tested, but **nothing in
   the live plan pipeline called it** — so stretch and plyo never reached a real
   week.
2. The stretch habit was still being created, so D5 ("stretch moves out of
   habits into the plan") was only half done: it lived in both places.
3. ``habits.evidence[]`` was hard-coded to an empty list, so the correlation
   renderer never saw real data.

These tests pin the connections, not the components — the components have their
own suites.
"""
from __future__ import annotations

import datetime
import inspect
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

from backend.models import (  # noqa: E402
    Base, Habit, HabitLog, User, UserPreferences, Workout,
)
from backend.services import coach_habit_targets, plan_draft, pref_catalog  # noqa: E402
from backend.services.goal_habits import (  # noqa: E402
    LONG_RUN_FUEL_SOURCE,
    ensure_goal_habits,
)
from backend.services.habit_evidence import (  # noqa: E402
    build_user_evidence,
    long_run_fuel_pairs,
)

TODAY = datetime.date(2026, 7, 30)
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
        tables=[
            User.__table__, Habit.__table__, HabitLog.__table__,
            Workout.__table__, UserPreferences.__table__,
        ],
    )
    return engine


@pytest.fixture
def session_user(db_engine):
    with _OrmSess(db_engine) as session:
        user = User(
            id=uuid.uuid4(), name="lean", is_admin=False, is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(user)
        session.commit()
        yield session, user.id


# ═════════════════════════════════════════════════════════════════════════════
# 1. The plan pipeline actually calls the decorator
# ═════════════════════════════════════════════════════════════════════════════

def test_plan_draft_imports_the_extras_decorator():
    assert hasattr(plan_draft, "apply_prefs_extras")


def test_every_build_skeleton_call_is_followed_by_the_decorator():
    """A skeleton built and not decorated is a week where stretch and plyo
    silently vanish — which is exactly the state this fixed."""
    source = inspect.getsource(plan_draft)
    assert source.count("build_skeleton(") >= 2
    # One decorator call per skeleton construction.
    assert source.count("apply_prefs_extras(") == source.count("sk = build_skeleton(")


def test_the_decorator_receives_the_prefs_and_the_week():
    source = inspect.getsource(plan_draft)
    for fragment in ("prefs=prefs", "week_start=week_start", "rest_days="):
        assert fragment in source.split("apply_prefs_extras(")[1]


# ═════════════════════════════════════════════════════════════════════════════
# 2. Stretch lives in prefs now, not in habits
# ═════════════════════════════════════════════════════════════════════════════

def test_stretch_is_a_catalog_preference():
    meta = pref_catalog.field_meta("stretch_daily_min")
    assert meta is not None
    assert meta["type"] == "int"
    assert meta["default"] == 0


def test_stretch_preference_is_bounded():
    payload = pref_catalog.default_payload()
    payload["stretch_daily_min"] = 20
    assert pref_catalog.validate_payload(payload) == {}
    payload["stretch_daily_min"] = 90
    assert "stretch_daily_min" in pref_catalog.validate_payload(payload)


def test_legacy_zone2_key_is_still_tolerated():
    """zone2 still lives on Habits; a payload carrying it must not be rejected."""
    assert pref_catalog.validate_payload({"zone2_weekly_min": 120}) == {}


def test_the_stretch_habit_is_no_longer_created(session_user):
    """D5: it moved into the plan. A new athlete gets no stretch habit."""
    session, uid = session_user
    rows = coach_habit_targets.ensure_coach_tracked_habits(session, uid)
    session.commit()
    assert rows["stretch"] is None
    names = [h.name for h in session.query(Habit).filter(Habit.user_id == uid).all()]
    assert "Daily stretch" not in names


def test_zone2_is_still_created(session_user):
    """Only stretch moved — zone2 was never in scope for D5."""
    session, uid = session_user
    rows = coach_habit_targets.ensure_coach_tracked_habits(session, uid)
    session.commit()
    assert rows["zone2"] is not None
    assert rows["zone2"].name == "Zone 2"


def test_an_existing_stretch_habit_is_still_adopted(session_user):
    """Nobody's history or target disappears — it is just never created again."""
    session, uid = session_user
    legacy = Habit(
        id=uuid.uuid4(), user_id=uid, name="Daily stretch", habit_type="duration",
        schedule_type="daily", target_value=12, unit="min",
        tracking_type="daily_checkmark", auto_fill_source="coach.stretch_daily",
        section="training", active=True, is_archived=False,
        sort_order=0, display_order=0, created_at=datetime.datetime.now(_UTC),
    )
    session.add(legacy)
    session.commit()

    rows = coach_habit_targets.ensure_coach_tracked_habits(session, uid)
    session.commit()
    assert rows["stretch"] is not None
    targets = coach_habit_targets.habit_targets_for_coach(session, uid, ensure=False)
    assert targets["stretch_daily_min"] == 12


def test_targets_report_zero_stretch_when_no_habit_exists(session_user):
    session, uid = session_user
    targets = coach_habit_targets.habit_targets_for_coach(session, uid, ensure=False)
    assert targets["stretch_daily_min"] == 0
    assert targets["stretch_habit_id"] is None


def test_the_pref_wins_over_a_legacy_habit_value():
    """The fallback is a migration aid, not a competing source of truth."""
    source = inspect.getsource(
        __import__("backend.services.training_prefs", fromlist=["x"]).prefs_for_assemble_facts
    )
    # The habit is only consulted when the pref is falsy.
    assert 'if not out["stretch_daily_min"]' in source


# ═════════════════════════════════════════════════════════════════════════════
# 3. Evidence is fed real data
# ═════════════════════════════════════════════════════════════════════════════

def _add_long_run(session, uid, day, *, drift, minutes=110):
    session.add(
        Workout(
            id=uuid.uuid4(), user_id=uid, workout_date=day, name="Long run",
            workout_type="run", duration_seconds=int(minutes * 60),
            decoupling_percent=drift, created_at=datetime.datetime.now(_UTC),
        )
    )


def _tick_fuel_habit(session, uid, habit_id, day):
    session.add(
        HabitLog(
            id=uuid.uuid4(), habit_id=habit_id, user_id=uid, log_date=day,
            value=1, log_week_start=day - datetime.timedelta(days=day.weekday()),
            source="workout_autofill", created_at=datetime.datetime.now(_UTC),
        )
    )


def _seed_weeks(session, uid, habit_id, *, fuelled_drifts, unfuelled_drifts):
    """One long run per week, alternating fuelled and not."""
    week = 0
    for drift in fuelled_drifts:
        day = TODAY - datetime.timedelta(weeks=week)
        _add_long_run(session, uid, day, drift=drift)
        _tick_fuel_habit(session, uid, habit_id, day)
        week += 1
    for drift in unfuelled_drifts:
        day = TODAY - datetime.timedelta(weeks=week)
        _add_long_run(session, uid, day, drift=drift)
        week += 1
    session.commit()


def test_pairs_are_weekly_not_daily(session_user):
    """The claim is "weeks you fuelled the long run" — a long run happens once a
    week, so daily alignment would compare a Tuesday tick to a Tuesday with no
    long run in it."""
    session, uid = session_user
    habits = ensure_goal_habits(session, uid)
    session.commit()
    _seed_weeks(
        session, uid, habits["long_run_fuel"].id,
        fuelled_drifts=[3.0, 3.2], unfuelled_drifts=[6.5, 7.0],
    )
    pairs = long_run_fuel_pairs(session, uid, TODAY)
    assert len(pairs) == 4
    assert {p["habit_value"] for p in pairs} == {True, False}


def test_weeks_without_a_long_run_are_dropped(session_user):
    """No long run means nothing to fuel — the week is evidence of neither."""
    session, uid = session_user
    habits = ensure_goal_habits(session, uid)
    session.commit()
    _add_long_run(session, uid, TODAY, drift=4.0)
    session.commit()
    assert len(long_run_fuel_pairs(session, uid, TODAY)) == 1


def test_short_runs_do_not_count_as_long_runs(session_user):
    session, uid = session_user
    ensure_goal_habits(session, uid)
    session.commit()
    _add_long_run(session, uid, TODAY, drift=4.0, minutes=40)
    session.commit()
    assert long_run_fuel_pairs(session, uid, TODAY) == []


def test_no_pairs_without_the_habit(session_user):
    session, uid = session_user
    _add_long_run(session, uid, TODAY, drift=4.0)
    session.commit()
    assert long_run_fuel_pairs(session, uid, TODAY) == []


def test_evidence_renders_a_sentence_from_real_rows(session_user):
    """The end-to-end path the export now uses."""
    session, uid = session_user
    habits = ensure_goal_habits(session, uid)
    session.commit()
    _seed_weeks(
        session, uid, habits["long_run_fuel"].id,
        fuelled_drifts=[3.0, 3.2, 3.1, 2.9],
        unfuelled_drifts=[6.5, 7.1, 6.8],
    )
    evidence = build_user_evidence(session, uid, TODAY)
    assert len(evidence) == 1
    assert evidence[0]["habit"] == "long_run_fuel"
    assert "HR drift averaged" in evidence[0]["sentence"]
    assert evidence[0]["better"] == "with"


def test_evidence_is_silent_with_too_few_weeks(session_user):
    """Saying "not enough data yet" is worse than saying nothing."""
    session, uid = session_user
    habits = ensure_goal_habits(session, uid)
    session.commit()
    _seed_weeks(
        session, uid, habits["long_run_fuel"].id,
        fuelled_drifts=[3.0], unfuelled_drifts=[6.5],
    )
    assert build_user_evidence(session, uid, TODAY) == []


def test_evidence_never_takes_the_export_down(session_user, monkeypatch):
    """It is decoration; a failure must not cost the athlete the export."""
    session, uid = session_user
    import backend.services.habit_evidence as he

    monkeypatch.setattr(
        he, "long_run_fuel_pairs",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert he.build_user_evidence(session, uid, TODAY) == []


def test_the_export_calls_the_real_builder():
    """The field was hard-coded to [] before this."""
    import backend.services.coach_export as ce

    source = inspect.getsource(ce._assemble_habits)
    assert "build_user_evidence(db, user.id, today)" in source
    assert '"evidence": []' not in source.split("goal_habits")[-1]
