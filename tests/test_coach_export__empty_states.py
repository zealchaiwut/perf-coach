"""Coach export — empty states and graceful degradation (spec §7).

A brand-new user, a user with no race, no weigh-ins, no findings, no plan: the
export must still BUILD and the blob must still be valid. The failure mode this
guards against is worse than an empty section — it is an export that either 500s
on the athlete's first day or, worse, fills the holes with plausible numbers.

Also covered: a block whose source raises is recorded in ``meta.degraded`` rather
than taking the whole export down or silently looking like real data.
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

TODAY = datetime.date(2026, 7, 30)
_UTC = datetime.timezone.utc

_TABLES = (
    User, UserPreferences, Workout, WorkoutExercise, PlannedSession, WeightEntry,
    WeightTarget, Race, RaceCheckpoint, Habit, HabitLog, PerformanceGoal, TrainingPlan,
    Decision,
)

FUEL_SETTINGS = {
    "base_kcal": 2000,
    "deficit_kcal": 300,
    "lean_mass_kg": 55.0,
    "ea_floor": 30.0,
    "weight_kg": 70.0,
    "protein_g_per_kg": 1.8,
    "fat_g": 60,
}


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload).encode("utf-8")


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_pg_functions(dbapi_conn, _record):  # pragma: no cover - plumbing
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(_UTC).isoformat(sep=" ")
        )
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    Base.metadata.create_all(engine, tables=[m.__table__ for m in _TABLES])
    return engine


@pytest.fixture
def blank_user_id(db_engine):
    """A user created seconds ago: no workouts, no weigh-ins, no goal, no plan."""
    with _OrmSess(db_engine) as session:
        user = User(
            id=uuid.uuid4(),
            name="brand-new",
            is_admin=False,
            is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(user)
        session.commit()
        return user.id


@pytest.fixture
def stub_services(db_engine, monkeypatch):
    """Stub the canonical services with their own empty/no-data shapes."""
    import backend.main as main_mod
    from backend.services import fuel as fuel_svc
    from backend.services import plan_prefs_accessor, training_load

    monkeypatch.setattr(ce, "engine", db_engine)
    monkeypatch.setattr(training_load, "engine", db_engine)
    monkeypatch.setattr(
        training_load,
        "current_load",
        lambda *a, **k: {"ctl": 0.0, "atl": 0.0, "tsb": 0.0, "acwr": None},
    )
    monkeypatch.setattr(training_load, "get_snapshot_series", lambda *a, **k: [])
    monkeypatch.setattr(
        training_load,
        "estimate_historical_pace_and_tss",
        lambda *a, **k: {"run_pace_min_per_km": {}},
    )
    monkeypatch.setattr(
        training_load,
        "estimate_planned_session_metrics",
        lambda *a, **k: {"estimated_tss": None, "estimated_distance_km": None},
    )
    monkeypatch.setattr(
        main_mod,
        "get_athlete_performance",
        lambda athlete_id, user=None: _FakeResponse({
            "state": "building_baseline",
            "endurance": {"state": "building_baseline", "reason": "no qualifying runs"},
            "speed": {"state": "building_baseline", "reason": "no qualifying runs"},
            "generated_at": "2026-07-30T00:00:00+00:00",
        }),
    )
    monkeypatch.setattr(
        main_mod,
        "get_gap_analysis",
        lambda user=None: _FakeResponse({"findings": [], "muted": []}),
    )
    monkeypatch.setattr(
        main_mod, "_athlete_scores_as_of", lambda s, uid, d: {"endurance": None, "speed": None}
    )
    monkeypatch.setattr(
        plan_prefs_accessor, "get_plan_prefs", lambda **kw: {"preferred_rest_days": []}
    )
    monkeypatch.setattr(fuel_svc, "get_or_create_settings", lambda uid, db=None: object())
    monkeypatch.setattr(fuel_svc, "settings_to_dict", lambda row: dict(FUEL_SETTINGS))
    monkeypatch.setattr(
        fuel_svc,
        "_fetch_lean_mass",
        lambda uid, row, db: {"lean_mass_kg": 55.0, "source": "estimated"},
    )
    return monkeypatch


@pytest.fixture
def blank_export(blank_user_id, stub_services):
    return ce.build_export(blank_user_id, today=TODAY)


# ── The export builds ────────────────────────────────────────────────────────

def test_brand_new_user_export_builds(blank_export):
    assert blank_export["meta"]["degraded"] == []
    assert blank_export["meta"]["schema_version"] == ce.SCHEMA_VERSION


def test_blob_is_still_valid_for_a_brand_new_user(blank_export):
    blob = ce.build_paste_blob(blank_export)
    body = blob.split("```json", 1)[1].rsplit("```", 1)[0]
    assert json.loads(body) == blank_export
    assert blob.index("## Rules") < blob.index("```json")


# ── Each empty block is empty, not invented ──────────────────────────────────

def test_no_race_means_a_null_race_block(blank_export):
    assert blank_export["goal"]["race"] is None
    assert blank_export["goal"]["body"] is None
    assert blank_export["goal"]["checkpoints"] == []


def test_no_goal_means_no_ctl_target_rather_than_a_default(blank_export):
    """A CTL target invented for an athlete with no race would drive advice
    toward a distance they never chose."""
    assert blank_export["fitness"]["ctl_target_for_goal"] is None
    assert blank_export["fitness"]["ctl_gap"] is None


def test_no_weigh_ins_means_an_unreadable_body_block(blank_export):
    body = blank_export["body"]
    assert body["weigh_ins"] == []
    assert body["trend_kg"] is None
    assert body["rate_kg_per_week"] is None
    assert body["state"] == "unknown"
    assert body["readable"] is False


def test_no_weigh_ins_means_no_athlete_mass(blank_export):
    assert blank_export["athlete"]["mass_kg"] is None
    assert blank_export["athlete"]["mass_source"] is None


def test_no_birth_date_means_no_age(blank_export):
    assert blank_export["athlete"]["age"] is None
    assert blank_export["athlete"]["height_cm"] is None
    assert blank_export["athlete"]["context"] is None


def test_no_workouts_means_zero_hours_not_null(blank_export):
    """Zero is a measurement here — the athlete has logged nothing — where mass
    with no weigh-in is genuinely unknown."""
    assert blank_export["athlete"]["weekly_hours_recent"] == 0.0


def test_no_workouts_means_empty_training_block(blank_export):
    training = blank_export["training"]
    assert training["sessions"] == []
    assert training["skipped_planned"] == []
    assert all(r["sessions"] == 0 for r in training["weekly_rollups"])


def test_no_findings_means_an_empty_list(blank_export):
    assert blank_export["findings"] == []


def test_no_habits_means_no_adherence_number(blank_export):
    habits = blank_export["habits"]
    assert habits["items"] == []
    assert habits["adherence_4w_pct"] is None
    assert habits["week_start"] is not None


def test_no_races_means_both_lists_empty(blank_export):
    assert blank_export["races"] == {"past": [], "upcoming": []}


def test_unscored_performance_reports_its_state(blank_export):
    perf = blank_export["performance"]
    assert perf["state"] == "building_baseline"
    assert perf["endurance"]["score"] is None
    assert perf["endurance"]["decomposition"] is None
    assert perf["endurance"]["anchors"] == []


def test_empty_plan_week_still_has_seven_days(blank_export):
    plan = blank_export["plan"]
    assert plan["today"] is None
    assert len(plan["week"]) == 7
    assert all(row["status"] == "unplanned" for row in plan["week"])
    assert plan["week_planned_tss"] == 0.0
    assert plan["week_logged_tss_so_far"] == 0.0


def test_no_snapshots_means_an_empty_fitness_series(blank_export):
    """No history → no weekly series rows to report, and chronic TSS is unknown
    rather than zero (zero would read as "trained nothing", which is a claim)."""
    assert blank_export["fitness"]["chronic_weekly_tss"] is None
    assert all(w["ctl_end"] is None for w in blank_export["fitness"]["weekly_series"])


def test_no_rest_day_pref_means_no_consecutive_day_bound(blank_export):
    c = blank_export["constraints"]
    assert c["preferred_rest_days"] == []
    assert c["max_consecutive_training_days"] is None


def test_no_training_plan_falls_back_to_the_load_plan_taper_length(blank_export):
    from backend.services.load_plan import TAPER_CURVE

    assert blank_export["constraints"]["taper_window_days"] == len(TAPER_CURVE) * 7
    assert blank_export["constraints"]["max_weekly_ramp_pct"] is None


def test_no_chronic_baseline_means_no_acwr_ceiling(blank_export):
    """A ceiling derived from no history is a made-up limit."""
    assert blank_export["constraints"]["acwr_ceiling_weekly_tss"] is None


def test_meta_freshness_is_null_when_nothing_has_been_logged(blank_export):
    freshness = blank_export["meta"]["data_freshness"]
    assert freshness["last_workout_date"] is None
    assert freshness["last_weigh_in"] is None
    assert freshness["workout_days_stale"] is None


def test_no_previous_export_is_null(blank_export):
    assert blank_export["meta"]["previous_export_date"] is None


# ── Degradation ──────────────────────────────────────────────────────────────

def test_a_failing_block_is_recorded_and_the_export_survives(
    blank_user_id, stub_services, monkeypatch
):
    """A raising source must not 500 the export — but it must not look like real
    data either."""
    def _boom(*_a, **_k):
        raise RuntimeError("snapshot table unavailable")

    from backend.services import training_load

    monkeypatch.setattr(training_load, "current_load", _boom)
    export = ce.build_export(blank_user_id, today=TODAY)

    assert any(entry.startswith("fitness:") for entry in export["meta"]["degraded"])
    assert export["fitness"]["ctl"] is None
    # Unrelated blocks are untouched.
    assert export["training"]["sessions"] == []


def test_a_failing_block_leaves_a_valid_pasteable_blob(
    blank_user_id, stub_services, monkeypatch
):
    from backend.services import training_load

    monkeypatch.setattr(
        training_load, "get_weekly_volume", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("aggregate failed")
        )
    )
    export = ce.build_export(blank_user_id, today=TODAY)
    blob = ce.build_paste_blob(export)
    body = blob.split("```json", 1)[1].rsplit("```", 1)[0]
    assert json.loads(body) == export
    assert export["meta"]["degraded"], "the failure should be surfaced"


def test_degraded_list_is_empty_not_absent_on_a_clean_build(blank_export):
    assert "degraded" in blank_export["meta"]
    assert blank_export["meta"]["degraded"] == []


# ── Formatting helpers never fabricate ───────────────────────────────────────

@pytest.mark.parametrize(
    "distance,duration", [(None, 3600), (10.0, None), (0, 3600), (10.0, 0)]
)
def test_pace_is_null_when_either_input_is_missing(distance, duration):
    assert ce._pace_per_km(distance, duration) is None


def test_pace_formats_as_minutes_and_seconds():
    assert ce._pace_per_km(10.0, 3000) == "5:00"
    # 7080 s over 15.1 km is 468.9 s/km — rounded to the second, not truncated.
    assert ce._pace_per_km(15.1, 7080) == "7:49"


@pytest.mark.parametrize("seconds", [None, 0, -5])
def test_finish_time_is_null_for_missing_or_impossible_durations(seconds):
    assert ce._hhmmss(seconds) is None
    assert ce._mmss(seconds) is None


def test_age_handles_a_birthday_that_has_not_happened_yet():
    assert ce._age_from_birth_date(datetime.date(1988, 12, 31), TODAY) == 37
    assert ce._age_from_birth_date(datetime.date(1988, 1, 1), TODAY) == 38
    assert ce._age_from_birth_date(datetime.date(1988, 7, 30), TODAY) == 38
    assert ce._age_from_birth_date(None, TODAY) is None
