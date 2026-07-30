"""Coach export — internal consistency and canonical parity (spec §7).

What is real here and what is stubbed, and why
----------------------------------------------
The rows (workouts, planned sessions, weigh-ins, races, habits) live in an
in-memory SQLite DB with the real ORM models, and the blocks derived FROM those
rows — sessions, weekly rollups, skipped-planned, weigh-ins, habits, the plan
week — are assembled by the real code against real queries. That is what makes
"sum(rollups.tss) == sum(sessions.tss)" a genuine assertion rather than two
copies of the same fixture: ``training.sessions`` is built by iterating Workout
rows, while ``training.weekly_rollups`` goes through
``training_load.get_weekly_volume``, which runs its own aggregate query.

The CANONICAL numbers (CTL/ATL/TSB/ACWR, the performance scores and their
breakdown, race readiness, the fuel budget) are stubbed at their owning service
with fixture values. Those services are covered by their own tests; what needs
proving here is that the export COPIES them rather than recomputing them. A
stubbed canonical value makes that visible: if the export ever re-derived a
score, the stub and the output would diverge and these tests would fail.
"""
from __future__ import annotations

import datetime
import json
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as _OrmSess

# SQLite cannot render JSONB (PlannedSession.structure, Workout.manual_overrides).
# Map it to JSON for the sqlite dialect only so create_all works; Postgres is
# untouched. Registered at import time, before any create_all below.
try:  # pragma: no cover - registration is idempotent per process
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json_on_sqlite(type_, compiler, **kw):  # noqa: D401
        return "JSON"
except Exception:  # pragma: no cover - already registered by another module
    pass

from backend.models import (  # noqa: E402
    Base,
    Decision,
    Habit,
    HabitLog,
    PerformanceGoal,
    PlannedSession,
    Race,
    RaceCheckpoint,
    TrainingPlan,
    User,
    UserPreferences,
    WeightEntry,
    WeightTarget,
    Workout,
    WorkoutExercise,
)
from backend.services import coach_export as ce  # noqa: E402

TODAY = datetime.date(2026, 7, 30)  # a Thursday
WEEK_START = datetime.date(2026, 7, 27)  # Monday of TODAY's week
WINDOW = 90

_TABLES = (
    User, UserPreferences, Workout, WorkoutExercise, PlannedSession, WeightEntry,
    WeightTarget, Race, RaceCheckpoint, Habit, HabitLog, PerformanceGoal, TrainingPlan,
    Decision,
)

_UTC = datetime.timezone.utc


# ═════════════════════════════════════════════════════════════════════════════
# Canonical stubs — fixture values the export must copy verbatim
# ═════════════════════════════════════════════════════════════════════════════

CANONICAL_LOAD = {"ctl": 52.31, "atl": 61.04, "tsb": -8.73, "acwr": 1.1742}

# Endurance breakdown that sums exactly: 41.10 + (-3.40) + 5.90 + 1.20 = 44.80
ENDURANCE = {
    "score": 44.8,
    "direction": "improving",
    "breakdown": {
        "window_days": 28,
        "score_then": 41.10,
        "decay": -3.40,
        "efforts": 5.90,
        "consistency": 1.20,
        "score_now": 44.80,
        "delta": 3.70,
        "residual": 0.0,
        # run_id is filled with the real seeded workout ids in the fixture, so
        # the export resolves titles by id (the path that matters when two
        # sessions share a date) rather than falling back to date matching.
        "anchors": [
            {"run_id": None, "date": "2026-07-25", "raw_score": 48.0,
             "age_weeks": 0.7, "decay_applied": -1.0, "current_contribution": 47.0,
             "is_stale": False},
            {"run_id": None, "date": "2026-07-22", "raw_score": 46.0,
             "age_weeks": 1.7, "decay_applied": -2.4, "current_contribution": 43.6,
             "is_stale": False},
            {"run_id": None, "date": "2026-07-18", "raw_score": 45.0,
             "age_weeks": 3.7, "decay_applied": -5.2, "current_contribution": 39.8,
             "is_stale": False},
            {"run_id": None, "date": "2026-06-20", "raw_score": 44.0,
             "age_weeks": 5.7, "decay_applied": -8.0, "current_contribution": 36.0,
             "is_stale": True},
        ],
        "non_anchors": [],
    },
}
# Speed breakdown that sums exactly: 50.00 + (-2.00) + 0.00 + 0.50 = 48.50
SPEED = {
    "score": 48.5,
    "direction": "flat",
    "breakdown": {
        "window_days": 28,
        "score_then": 50.00,
        "decay": -2.00,
        "efforts": 0.00,
        "consistency": 0.50,
        "score_now": 48.50,
        "delta": -1.50,
        "residual": 0.0,
        "anchors": [
            {"run_id": "s1", "date": "2026-07-22", "raw_score": 52.0,
             "age_weeks": 1.1, "decay_applied": -1.5, "current_contribution": 50.5,
             "is_stale": False},
        ],
        "non_anchors": [],
    },
}

RACE_ESTIMATE_SECONDS = 6552  # 1:49:12
RACE_BAND_SECONDS = 204  # 3.4 min

GAP_FINDINGS = {
    "findings": [
        {
            "code": "no_recent_plyo",
            "severity": 2,
            "recommendation": "Add one plyo session this week.",
            "evidence_text": "0 plyo sessions in the last 21 days (target 1/week).",
            "load_adding": True,
        }
    ],
    # Muted findings must NOT reach the payload — the app decided not to show
    # them, and a daily message is the wrong place to relitigate that.
    "muted": [
        {
            "code": "long_run_short",
            "severity": 1,
            "recommendation": "Extend the long run.",
            "evidence_text": "muted: dismissed 4 days ago.",
            "load_adding": True,
        }
    ],
}

FUEL_SETTINGS = {
    "base_kcal": 2200,
    "deficit_kcal": 400,
    "lean_mass_kg": 60.0,
    "ea_floor": 30.0,
    "weight_kg": 78.0,
    "protein_g_per_kg": 1.8,
    "fat_g": 70,
}

PLAN_PREFS = {
    "preferred_rest_days": [2, 6],  # Wed + Sun
    "strength_emphasis": "same",
    "notes": "",
}


class _FakeResponse:
    """Stands in for the JSONResponse the canonical endpoint functions return."""

    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload).encode("utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def db_engine():
    """In-memory SQLite with the real ORM models.

    The models carry Postgres server defaults (``now()``, ``gen_random_uuid()``)
    which SQLite has no such functions for; registering them on connect is much
    less noise than setting every timestamp column by hand on every fixture row,
    and it keeps the fixtures readable.
    """
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_pg_functions(dbapi_conn, _record):  # pragma: no cover - plumbing
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(_UTC).isoformat(sep=" ")
        )
        dbapi_conn.create_function(
            "gen_random_uuid", 0, lambda: str(uuid.uuid4())
        )

    Base.metadata.create_all(engine, tables=[m.__table__ for m in _TABLES])
    return engine


def _add_user(session: _OrmSess) -> User:
    user = User(
        id=uuid.uuid4(),
        name="test-athlete",
        is_admin=False,
        is_active=True,
        created_at=datetime.datetime.now(_UTC),
        height_cm=178.0,
        birth_date=datetime.date(1988, 4, 12),
        athlete_context="6 years running, returning from a calf strain",
        last_coach_export_at=datetime.datetime(2026, 7, 27, 7, 0, tzinfo=_UTC),
    )
    session.add(user)
    session.commit()
    return user


def _add_workout(
    session: _OrmSess,
    user: User,
    on: datetime.date,
    *,
    name: str,
    workout_type: str = "run",
    tss: float = 60.0,
    distance_km: float | None = 10.0,
    duration_seconds: int | None = 3600,
    avg_hr: int | None = 145,
    zone2_minutes: int | None = None,
    exercises: int = 0,
) -> Workout:
    w = Workout(
        id=uuid.uuid4(),
        user_id=user.id,
        workout_date=on,
        name=name,
        workout_type=workout_type,
        tss=tss,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        avg_hr=avg_hr,
        zone2_minutes=zone2_minutes,
        created_at=datetime.datetime.now(_UTC),
    )
    session.add(w)
    session.flush()
    for i in range(exercises):
        session.add(
            WorkoutExercise(
                id=uuid.uuid4(),
                workout_id=w.id,
                name=f"lift-{i}",
                display_order=i,
                created_at=datetime.datetime.now(_UTC),
            )
        )
    session.commit()
    return w


ANCHOR_SESSIONS = (
    (datetime.date(2026, 7, 25), "Half-pace 8 k"),
    (datetime.date(2026, 7, 22), "5x1k @ threshold"),
    (datetime.date(2026, 7, 18), "Tempo 10 k"),
)


def _seed(session: _OrmSess) -> tuple[User, dict]:
    """A realistic-enough athlete: 12 weeks of running, a race, a cut, habits.

    Returns the user and ``{workout_id: name}`` for the three anchor sessions, so
    the stubbed performance breakdown can reference the real rows.
    """
    user = _add_user(session)

    # Workouts: one long run + one strength session per week for 12 weeks, plus
    # the anchor dates the stubbed performance breakdown names.
    for weeks_ago in range(12):
        monday = WEEK_START - datetime.timedelta(weeks=weeks_ago)
        _add_workout(
            session, user, monday + datetime.timedelta(days=5),
            name=f"Long run w-{weeks_ago}", tss=97.0, distance_km=15.1,
            duration_seconds=7080, avg_hr=146, zone2_minutes=118,
        )
        _add_workout(
            session, user, monday,
            name=f"Lower body w-{weeks_ago}", workout_type="strength", tss=30.0,
            distance_km=None, duration_seconds=2760, avg_hr=None, exercises=6,
        )
    anchor_ids: dict = {}
    for anchor_date, title in ANCHOR_SESSIONS:
        anchor = _add_workout(
            session, user, anchor_date, name=title, tss=75.0, distance_km=12.0,
            duration_seconds=3900, avg_hr=158,
        )
        anchor_ids[str(anchor.id)] = title

    # Plan: this week, Mon/Tue/Thu/Fri/Sat planned; Wed + Sun are the rest days.
    plan_days = {
        0: ("strength", "Lower body", "done_manual"),
        1: ("run", "Easy 8 k", "done_auto"),
        3: ("run", "Threshold 5x1k", "planned"),
        4: ("run", "Easy 6 k", "planned"),
        5: ("run", "Long run 18 k", "planned"),
    }
    for offset, (stype, sname, status) in plan_days.items():
        session.add(
            PlannedSession(
                id=uuid.uuid4(),
                user_id=user.id,
                planned_date=WEEK_START + datetime.timedelta(days=offset),
                session_type=stype,
                name=sname,
                status=status,
                structure={"blocks": [{"phase": "main", "duration_min": 45}]},
                created_at=datetime.datetime.now(_UTC),
            )
        )
    # Two skipped sessions inside the window, before today.
    for days_ago, status in ((10, "missed_auto"), (17, "missed_manual")):
        session.add(
            PlannedSession(
                id=uuid.uuid4(),
                user_id=user.id,
                planned_date=TODAY - datetime.timedelta(days=days_ago),
                session_type="run",
                name="Missed tempo",
                status=status,
                structure=None,
                created_at=datetime.datetime.now(_UTC),
            )
        )

    # Weigh-ins: daily for 60 days, a clean cut.
    for i in range(60):
        d = TODAY - datetime.timedelta(days=59 - i)
        session.add(
            WeightEntry(
                id=uuid.uuid4(),
                user_id=user.id,
                entry_date=d,
                weight_kg=79.5 - 0.02 * i,
                created_at=datetime.datetime.now(_UTC),
            )
        )
    session.add(
        WeightTarget(
            id=uuid.uuid4(),
            user_id=user.id,
            start_weight_kg=79.5,
            target_weight_kg=74.0,
            start_date=TODAY - datetime.timedelta(days=60),
            target_date=TODAY + datetime.timedelta(days=90),
            status="active",
            created_at=datetime.datetime.now(_UTC),
        )
    )

    # Goal race + a checkpoint, and one finished race in the past.
    race = Race(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Chiang Mai Half",
        race_date=datetime.date(2026, 11, 15),
        distance_km=21.0975,
        goal_time_seconds=6300,
        priority="A",
        status="planned",
        race_type="race",
        created_at=datetime.datetime.now(_UTC),
        updated_at=datetime.datetime.now(_UTC),
    )
    session.add(race)
    session.add(
        Race(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Bangkok 10K",
            race_date=datetime.date(2026, 5, 10),
            distance_km=10.0,
            goal_time_seconds=2700,
            actual_time_seconds=2748,
            priority="B",
            status="done",
            race_type="race",
            created_at=datetime.datetime.now(_UTC),
            updated_at=datetime.datetime.now(_UTC),
        )
    )
    session.flush()
    session.add(
        RaceCheckpoint(
            id=uuid.uuid4(),
            race_id=race.id,
            user_id=user.id,
            label="18 k at goal pace + 20s",
            target_date=datetime.date(2026, 10, 11),
            target_distance_km=18.0,
            target_pace_seconds_per_km=318,
            met=False,
            met_override=False,
            created_at=datetime.datetime.now(_UTC),
            updated_at=datetime.datetime.now(_UTC),
        )
    )
    session.add(
        PerformanceGoal(
            id=uuid.uuid4(),
            user_id=user.id,
            race_distance="half",
            target_time=6300,
            race_date=datetime.date(2026, 11, 15),
            active=True,
            created_at=datetime.datetime.now(_UTC),
        )
    )

    # Habits: one daily habit logged most days.
    habit = Habit(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Daily stretch",
        habit_type="binary",
        schedule_type="daily",
        active=True,
        is_archived=False,
        sort_order=0,
        display_order=0,
        tracking_type="daily_checkmark",
        section="training",
        created_at=datetime.datetime.now(_UTC),
    )
    session.add(habit)
    session.flush()
    for i in range(28):
        d = TODAY - datetime.timedelta(days=i)
        if i % 5 == 0:
            continue  # a few misses so adherence isn't a trivial 100%
        session.add(
            HabitLog(
                id=uuid.uuid4(),
                habit_id=habit.id,
                user_id=user.id,
                log_date=d,
                value=1,
                log_week_start=d - datetime.timedelta(days=d.weekday()),
                source="manual",
                created_at=datetime.datetime.now(_UTC),
            )
        )

    session.add(
        TrainingPlan(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Half build",
            ramp_rate=0.05,
            taper_length=3,
            hold_weeks=4,
            deload_enabled=False,
            deload_start_week=4,
            created_at=datetime.datetime.now(_UTC),
            updated_at=datetime.datetime.now(_UTC),
        )
    )
    session.commit()
    return user, anchor_ids


def _snapshot_series(from_date, to_date, *, acwr_from_day: int = 28) -> list[dict]:
    """Daily snapshots with a REAL cold start: acwr is None until a full 28-day
    chronic window exists inside the series, exactly as the snapshot layer
    returns it."""
    out = []
    day = from_date
    index = 0
    while day <= to_date:
        out.append({
            "date": day,
            "tss": 20.0,
            "ctl": 40.0 + index * 0.05,
            "atl": 45.0 + index * 0.05,
            "tsb": -5.0,
            "acwr": None if index < acwr_from_day else 1.15,
        })
        day += datetime.timedelta(days=1)
        index += 1
    return out


@pytest.fixture
def export(db_engine, monkeypatch):
    """A fully built export against seeded rows and stubbed canonical services."""
    from backend.main import _athlete_scores_as_of  # noqa: F401  (patched below)
    from backend.services import fuel as fuel_svc
    from backend.services import plan_prefs_accessor, training_load
    import backend.main as main_mod

    with _OrmSess(db_engine) as session:
        user, anchor_ids = _seed(session)
        user_id = user.id

    # Point the first three endurance anchors at the real seeded workouts.
    endurance = json.loads(json.dumps(ENDURANCE))
    for anchor, run_id in zip(endurance["breakdown"]["anchors"], anchor_ids):
        anchor["run_id"] = run_id

    monkeypatch.setattr(ce, "engine", db_engine)
    monkeypatch.setattr(training_load, "engine", db_engine)

    monkeypatch.setattr(
        training_load, "current_load", lambda *a, **k: dict(CANONICAL_LOAD)
    )
    monkeypatch.setattr(
        training_load,
        "get_snapshot_series",
        lambda uid, f, t, *a, **k: _snapshot_series(f, t),
    )
    monkeypatch.setattr(
        training_load,
        "estimate_historical_pace_and_tss",
        lambda *a, **k: {"run_tss_per_min": 1.0, "strength_tss_per_min": 0.5,
                         "run_pace_min_per_km": {"moderate": 6.0}},
    )
    monkeypatch.setattr(
        training_load,
        "estimate_planned_session_metrics",
        lambda baseline, wt, structure: {"estimated_tss": 45, "estimated_distance_km": 7.5},
    )

    monkeypatch.setattr(
        main_mod,
        "get_athlete_performance",
        lambda athlete_id, user=None: _FakeResponse({
            "state": "scored",
            "endurance": endurance,
            "speed": SPEED,
            "generated_at": "2026-07-30T00:00:00+00:00",
        }),
    )
    monkeypatch.setattr(
        main_mod, "get_gap_analysis", lambda user=None: _FakeResponse(GAP_FINDINGS)
    )
    monkeypatch.setattr(
        main_mod,
        "_race_readiness_impl",
        lambda race_id, user, *a, **k: _FakeResponse({
            "time_curve": {
                "projection": [
                    {
                        "date": "2026-11-15",
                        "estimated_finish_seconds": RACE_ESTIMATE_SECONDS,
                        "confidence_band_seconds": RACE_BAND_SECONDS,
                    }
                ]
            }
        }),
    )
    monkeypatch.setattr(
        main_mod,
        "_athlete_scores_as_of",
        lambda session, uid, as_of: {"endurance": 44.8, "speed": 48.5},
    )

    monkeypatch.setattr(
        plan_prefs_accessor, "get_plan_prefs", lambda **kw: dict(PLAN_PREFS)
    )

    monkeypatch.setattr(fuel_svc, "get_or_create_settings", lambda uid, db=None: object())
    monkeypatch.setattr(fuel_svc, "settings_to_dict", lambda row: dict(FUEL_SETTINGS))
    monkeypatch.setattr(
        fuel_svc,
        "_fetch_lean_mass",
        lambda uid, row, db: {"lean_mass_kg": 60.0, "source": "estimated"},
    )

    result = ce.build_export(user_id, window_days=WINDOW, today=TODAY)
    result["_user_id"] = user_id
    return result


# ═════════════════════════════════════════════════════════════════════════════
# The export builds at all
# ═════════════════════════════════════════════════════════════════════════════

def test_export_builds_with_no_degraded_blocks(export):
    """A degraded block means an assembly path raised — the fixture covers every
    block, so anything here is a real defect, not a missing stub."""
    assert export["meta"]["degraded"] == []


def test_all_top_level_blocks_present(export):
    expected = {
        "meta", "athlete", "goal", "constraints", "fitness", "performance",
        "body", "training", "races", "habits", "plan", "findings",
    }
    assert expected <= set(export)


# ═════════════════════════════════════════════════════════════════════════════
# Self-consistency (spec §7)
# ═════════════════════════════════════════════════════════════════════════════

def test_rollup_tss_matches_session_tss(export):
    """Two independent paths over the same rows: the session list iterates
    Workout objects, the rollups go through get_weekly_volume's aggregate."""
    rollups = export["training"]["weekly_rollups"]
    rollup_start = datetime.date.fromisoformat(rollups[0]["week_start"])

    sessions_in_span = [
        s for s in export["training"]["sessions"]
        if datetime.date.fromisoformat(s["date"]) >= rollup_start
    ]
    assert sum(s["tss"] for s in sessions_in_span) == pytest.approx(
        sum(r["tss"] for r in rollups), abs=0.05
    )


def test_rollup_session_counts_match_session_rows(export):
    rollups = export["training"]["weekly_rollups"]
    for rollup in rollups:
        ws = datetime.date.fromisoformat(rollup["week_start"])
        we = ws + datetime.timedelta(days=6)
        counted = sum(
            1 for s in export["training"]["sessions"]
            if ws <= datetime.date.fromisoformat(s["date"]) <= we
        )
        assert counted == rollup["sessions"], f"week {rollup['week_start']} disagrees"


def test_week_logged_tss_equals_the_current_week_rollup(export):
    current = next(
        r for r in export["training"]["weekly_rollups"]
        if r["week_start"] == WEEK_START.isoformat()
    )
    assert export["plan"]["week_logged_tss_so_far"] == pytest.approx(
        current["tss"], abs=0.05
    )


def test_every_anchor_is_titled_from_the_session_that_produced_it(export):
    """An anchor row without the session's own name is a number the athlete
    can't place. The title must come from the anchor's OWN workout — 2026-07-25
    holds two sessions, so date-only matching would pick the wrong one."""
    on_anchor_date = [
        s["name"] for s in export["training"]["sessions"] if s["date"] == "2026-07-25"
    ]
    assert len(on_anchor_date) == 2, "fixture should have two sessions on the anchor date"

    titles = [a["title"] for a in export["performance"]["endurance"]["anchors"]]
    assert titles == [name for _, name in ANCHOR_SESSIONS]


def test_anchor_run_ids_are_not_exported(export):
    """The id resolves the title server-side; it has no use in a coach message."""
    for metric in ("endurance", "speed"):
        for anchor in export["performance"][metric]["anchors"]:
            assert "run_id" not in anchor


def test_title_anchors_prefers_run_id_over_date():
    performance = {
        "endurance": {
            "anchors": [
                {"run_id": "w-evening", "date": "2026-07-25", "title": None},
                {"run_id": None, "date": "2026-07-25", "title": None},
            ]
        },
        "speed": {"anchors": []},
    }
    ce._title_anchors(
        performance,
        {"w-evening": "5x1k @ threshold"},
        {"2026-07-25": "Morning long run"},
    )
    anchors = performance["endurance"]["anchors"]
    assert anchors[0]["title"] == "5x1k @ threshold"
    # No run_id (the race anchor point) falls back to the date.
    assert anchors[1]["title"] == "Morning long run"


def test_only_top_three_anchors_are_exported(export):
    """The breakdown carries four; the payload keeps the top K."""
    assert len(ENDURANCE["breakdown"]["anchors"]) == 4
    assert len(export["performance"]["endurance"]["anchors"]) == ce.ANCHOR_ROWS


def test_sessions_are_ordered_oldest_first(export):
    dates = [s["date"] for s in export["training"]["sessions"]]
    assert dates == sorted(dates)


def test_sessions_stay_inside_the_window(export):
    window_start = TODAY - datetime.timedelta(days=WINDOW - 1)
    for s in export["training"]["sessions"]:
        assert window_start <= datetime.date.fromisoformat(s["date"]) <= TODAY


# ═════════════════════════════════════════════════════════════════════════════
# Decomposition invariant (spec §7)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("metric", ["endurance", "speed"])
def test_decomposition_sums_to_score_now(export, metric):
    d = export["performance"][metric]["decomposition"]
    assert d is not None, f"{metric} decomposition missing"
    total = d["score_then"] + d["decay"] + d["efforts"] + d["consistency"]
    assert total == pytest.approx(d["score_now"], abs=0.05)


@pytest.mark.parametrize("metric", ["endurance", "speed"])
def test_delta_28d_equals_score_now_minus_score_then(export, metric):
    block = export["performance"][metric]
    d = block["decomposition"]
    assert block["delta_28d"] == pytest.approx(d["score_now"] - d["score_then"], abs=0.05)


def test_a_residual_breakdown_is_dropped_not_exported():
    """The canonical compute refuses a decomposition that doesn't sum; the export
    must not resurrect it. A block of numbers that looks authoritative and is
    wrong is worse than no block."""
    block = ce._score_block({"score": 44.8, "breakdown": {"error": "residual", "residual": 0.9}})
    assert block["score"] == 44.8
    assert block["decomposition"] is None
    assert block["anchors"] == []


def test_missing_breakdown_still_reports_the_score():
    block = ce._score_block({"score": 44.8, "direction": "flat", "breakdown": None})
    assert block["score"] == 44.8
    assert block["decomposition"] is None
    assert block["delta_28d"] is None


# ═════════════════════════════════════════════════════════════════════════════
# Canonical parity — the export copies, it never recomputes (spec §7)
# ═════════════════════════════════════════════════════════════════════════════

def test_fitness_matches_the_canonical_load_snapshot(export):
    f = export["fitness"]
    assert f["ctl"] == pytest.approx(CANONICAL_LOAD["ctl"], abs=0.005)
    assert f["atl"] == pytest.approx(CANONICAL_LOAD["atl"], abs=0.005)
    assert f["tsb"] == pytest.approx(CANONICAL_LOAD["tsb"], abs=0.005)
    assert f["acwr"] == pytest.approx(CANONICAL_LOAD["acwr"], abs=0.0005)
    assert f["as_of"] == TODAY.isoformat()


@pytest.mark.parametrize(
    "metric,expected", [("endurance", ENDURANCE), ("speed", SPEED)]
)
def test_scores_match_the_canonical_performance_compute(export, metric, expected):
    assert export["performance"][metric]["score"] == pytest.approx(
        expected["score"], abs=0.05
    )
    assert export["performance"][metric]["direction"] == expected["direction"]


def test_performance_state_is_carried_through(export):
    assert export["performance"]["state"] == "scored"


def test_unscored_performance_is_reported_not_faked(db_engine, monkeypatch):
    import backend.main as main_mod

    monkeypatch.setattr(
        main_mod,
        "get_athlete_performance",
        lambda athlete_id, user=None: _FakeResponse({
            "state": "building_baseline", "endurance": None, "speed": None,
            "generated_at": "2026-07-30T00:00:00+00:00",
        }),
    )
    with _OrmSess(db_engine) as session:
        user = _add_user(session)
        perf = ce._assemble_performance(user)
    assert perf["state"] == "building_baseline"
    assert perf["endurance"]["score"] is None


def test_race_estimate_comes_from_the_readiness_projection(export):
    race = export["goal"]["race"]
    assert race["current_estimate"] == "1:49:12"
    assert race["estimate_band_min"] == pytest.approx(RACE_BAND_SECONDS / 60.0, abs=0.05)
    assert race["estimate_source"] == "race_readiness_projection"


def test_goal_time_is_formatted_from_the_stored_seconds(export):
    assert export["goal"]["race"]["goal_time"] == "1:45:00"


def test_ctl_target_and_gap_come_from_the_shared_target_table(export):
    from backend.services.coach_plan import _TARGET_CTL

    f = export["fitness"]
    assert f["ctl_target_for_goal"] == _TARGET_CTL["half"]
    assert f["ctl_gap"] == pytest.approx(_TARGET_CTL["half"] - f["ctl"], abs=0.05)


# ═════════════════════════════════════════════════════════════════════════════
# ACWR cold start (spec §7)
# ═════════════════════════════════════════════════════════════════════════════

def test_acwr_is_null_for_the_first_weeks_not_a_ratio(export):
    """A partial chronic window yields ratios like 4.0 that read as a spike that
    never happened. Null is the only honest value."""
    series = export["fitness"]["weekly_series"]
    assert series[0]["acwr_end"] is None
    assert series[1]["acwr_end"] is None
    assert series[2]["acwr_end"] is None
    assert series[-1]["acwr_end"] is not None


def test_acwr_null_note_is_carried_in_meta(export):
    note = export["meta"]["acwr_null_note"]
    assert "28-day" in note
    assert "null" in note


def test_weekly_series_covers_the_rollup_span(export):
    series = export["fitness"]["weekly_series"]
    assert len(series) == ce.ROLLUP_WEEKS
    assert series[-1]["week_start"] == WEEK_START.isoformat()


# ═════════════════════════════════════════════════════════════════════════════
# Constraints
# ═════════════════════════════════════════════════════════════════════════════

def test_acwr_ceiling_is_the_chronic_baseline_times_the_load_plan_multiplier(export):
    from backend.services.load_plan import ACWR_CEILING_MULT

    chronic = export["fitness"]["chronic_weekly_tss"]
    assert chronic is not None
    assert export["constraints"]["acwr_ceiling_weekly_tss"] == pytest.approx(
        ACWR_CEILING_MULT * chronic, abs=0.15
    )


def test_verdict_and_reason_come_from_training_verdict(export):
    from backend.services.training_verdict import compute_verdict

    expected = compute_verdict(
        dict(CANONICAL_LOAD),
        chronic_weekly=export["fitness"]["chronic_weekly_tss"],
        today=TODAY,
    )
    assert export["constraints"]["current_verdict"] == expected["verdict"]
    assert export["constraints"]["verdict_reason"] == expected["reason"]


def test_ea_floor_is_the_rest_day_floor_from_fuel(export):
    """EA floor with zero training burn: ea_floor × lean mass."""
    expected = round(FUEL_SETTINGS["ea_floor"] * FUEL_SETTINGS["lean_mass_kg"])
    assert export["constraints"]["ea_floor_kcal_rest_day"] == expected


def test_protein_and_deficit_bounds_come_from_fuel_constants(export):
    from backend.services.fuel import DEFICIT_KCAL_MAX

    assert export["constraints"]["max_deficit_kcal_per_day"] == DEFICIT_KCAL_MAX
    assert export["constraints"]["protein_g_per_day"] > 0


def test_taper_window_and_ramp_come_from_the_plan_row(export):
    c = export["constraints"]
    assert c["taper_window_days"] == 21  # taper_length 3 weeks
    assert c["max_weekly_ramp_pct"] == pytest.approx(5.0, abs=0.05)


def test_preferred_rest_days_are_named_not_indexed(export):
    assert export["constraints"]["preferred_rest_days"] == ["Wed", "Sun"]


def test_constraints_note_states_the_bounds_are_hard(export):
    assert "hard bounds" in export["constraints"]["note"]


@pytest.mark.parametrize(
    "rest_days,expected",
    [
        ([], None),          # no stored preference → no bound to report
        ([2, 6], 3),         # Wed + Sun → Thu-Fri-Sat is the longest run
        ([6], 6),            # Sunday only → six straight days
        ([0, 1, 2, 3, 4, 5, 6], 0),
        ([1, 3, 5], 2),   # Tue/Thu/Sat rest → Sun+Mon is the longest run
    ],
)
def test_max_consecutive_training_days_follows_the_rest_day_pref(rest_days, expected):
    assert ce._max_consecutive_training_days(rest_days) == expected


# ═════════════════════════════════════════════════════════════════════════════
# Findings
# ═════════════════════════════════════════════════════════════════════════════

def test_only_visible_findings_are_exported(export):
    codes = [f["code"] for f in export["findings"]]
    assert codes == ["no_recent_plyo"]
    assert "long_run_short" not in codes


def test_findings_carry_evidence_and_the_load_adding_flag(export):
    finding = export["findings"][0]
    assert finding["severity"] == 2
    assert finding["load_adding"] is True
    assert "plyo sessions" in finding["evidence"]


# ═════════════════════════════════════════════════════════════════════════════
# Athlete / body / plan / training details
# ═════════════════════════════════════════════════════════════════════════════

def test_athlete_mass_is_the_trend_not_the_last_weigh_in(export):
    """"I weighed 79.0 this morning" is noise; the trend is the body mass."""
    weigh_ins = export["body"]["weigh_ins"]
    assert export["athlete"]["mass_kg"] == export["body"]["trend_kg"]
    assert export["athlete"]["mass_kg"] != weigh_ins[-1]["kg"]
    assert export["athlete"]["mass_source"] == "weight_trend_ewma"


def test_athlete_age_is_derived_from_the_stored_birth_date(export):
    assert export["athlete"]["age"] == 38  # born 1988-04-12, as of 2026-07-30


def test_athlete_weekly_hours_come_from_logged_sessions(export):
    """Aspiration ("I train 5-7 h/week") is not data; this is measured."""
    hours = export["athlete"]["weekly_hours_recent"]
    assert hours > 0
    assert hours < 20


def test_athlete_context_is_the_stored_free_text(export):
    assert export["athlete"]["context"].startswith("6 years running")


def test_body_block_reports_a_readable_cut(export):
    body = export["body"]
    assert body["state"] == "losing"
    assert body["readable"] is True
    assert body["needed_rate_kg_per_week"] is not None


def test_body_weigh_ins_are_clipped_to_the_export_window(export):
    window_start = TODAY - datetime.timedelta(days=WINDOW - 1)
    for w in export["body"]["weigh_ins"]:
        assert window_start <= datetime.date.fromisoformat(w["date"]) <= TODAY


def test_goal_body_target_is_carried_with_the_needed_rate(export):
    goal_body = export["goal"]["body"]
    assert goal_body["target_kg"] == pytest.approx(74.0, abs=0.05)
    assert goal_body["intent"] == "lose"
    assert goal_body["needed_rate_kg_per_week"] == export["body"]["needed_rate_kg_per_week"]


def test_plan_week_has_one_entry_per_day_including_rest(export):
    week = export["plan"]["week"]
    dates = {row["date"] for row in week}
    assert len(dates) == 7
    unplanned = [row for row in week if row["status"] == "unplanned"]
    assert {row["dow"] for row in unplanned} == {"Wed", "Sun"}


def test_plan_today_is_this_thursdays_session(export):
    today_row = export["plan"]["today"]
    assert today_row is not None
    assert today_row["date"] == TODAY.isoformat()
    assert today_row["name"] == "Threshold 5x1k"


def test_plan_planned_tss_is_positive_when_sessions_are_planned(export):
    assert export["plan"]["week_planned_tss"] > 0


def test_skipped_planned_lists_the_missed_statuses_only(export):
    skipped = export["training"]["skipped_planned"]
    assert len(skipped) == 2
    assert {s["status"] for s in skipped} == {"missed_auto", "missed_manual"}
    for s in skipped:
        assert datetime.date.fromisoformat(s["date"]) < TODAY


def test_run_rows_carry_pace_and_strength_rows_carry_exercise_counts(export):
    runs = [s for s in export["training"]["sessions"] if s["type"] == "run"]
    strength = [s for s in export["training"]["sessions"] if s["type"] == "strength"]
    assert runs and strength
    assert all(r.get("avg_pace_per_km") for r in runs)
    assert all("distance_km" not in s or s["distance_km"] is None for s in strength)
    assert all(s.get("exercises") == 6 for s in strength)


def test_no_session_row_carries_a_structure_blob(export):
    """The structure blob triples the payload and adds nothing a coach message
    can use."""
    for s in export["training"]["sessions"]:
        assert "structure" not in s
        assert "blocks" not in s


def test_races_are_split_into_past_and_upcoming(export):
    races = export["races"]
    assert [r["name"] for r in races["past"]] == ["Bangkok 10K"]
    assert [r["name"] for r in races["upcoming"]] == ["Chiang Mai Half"]
    assert races["past"][0]["actual_time"] == "0:45:48"
    assert races["upcoming"][0]["weeks_out"] > 0


def test_checkpoints_are_carried_for_the_goal_race(export):
    checkpoints = export["goal"]["checkpoints"]
    assert len(checkpoints) == 1
    assert checkpoints[0]["label"] == "18 k at goal pace + 20s"
    assert checkpoints[0]["target_pace_per_km"] == "5:18"
    assert checkpoints[0]["met"] is False


def test_habits_report_adherence_from_the_habit_service(export):
    habits = export["habits"]
    assert habits["week_start"] == WEEK_START.isoformat()
    assert [h["name"] for h in habits["items"]] == ["Daily stretch"]
    assert habits["items"][0]["adherence_pct"] is not None


def test_meta_reports_freshness_and_the_previous_export(export):
    meta = export["meta"]
    assert meta["window_days"] == WINDOW
    assert meta["previous_export_date"] == "2026-07-27"
    assert meta["data_freshness"]["last_workout_date"] is not None
    assert meta["data_freshness"]["last_weigh_in"] == TODAY.isoformat()
    assert meta["timezone"] == "Asia/Bangkok"


# ═════════════════════════════════════════════════════════════════════════════
# The blob built from a real export
# ═════════════════════════════════════════════════════════════════════════════

def test_real_export_round_trips_through_the_blob(export):
    payload = {k: v for k, v in export.items() if not k.startswith("_")}
    blob = ce.build_paste_blob(payload)
    body = blob.split("```json", 1)[1].rsplit("```", 1)[0]
    assert json.loads(body) == payload


def test_real_blob_stays_within_a_pasteable_size(export):
    """~30k chars is the design point; revisit the payload only past ~60k."""
    payload = {k: v for k, v in export.items() if not k.startswith("_")}
    blob = ce.build_paste_blob(payload)
    assert len(blob) < 60_000, f"blob grew to {len(blob)} chars"


# ═════════════════════════════════════════════════════════════════════════════
# Window validation
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("window", [0, 6, 366, -1])
def test_out_of_range_window_is_rejected(db_engine, monkeypatch, window):
    monkeypatch.setattr(ce, "engine", db_engine)
    with _OrmSess(db_engine) as session:
        user_id = _add_user(session).id
    with pytest.raises(ValueError, match="window_days must be between"):
        ce.build_export(user_id, window_days=window)


def test_unknown_user_is_rejected(db_engine, monkeypatch):
    monkeypatch.setattr(ce, "engine", db_engine)
    with pytest.raises(ValueError, match="not found"):
        ce.build_export(uuid.uuid4())
