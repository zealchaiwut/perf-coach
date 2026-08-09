"""Log-calendar hotfix (2026-07-09): estimated TSS/distance for still-open
planned sessions, so the week progress bar reflects "what's coming" too, not
just what's already logged. Pure formula (the athlete's own historical
pace/TSS-per-minute), no LLM — see training_load.estimate_historical_pace_and_tss
/ estimate_planned_session_metrics.

Real-Postgres for the history-dependent baseline; pure unit tests for the
per-session estimate given a baseline.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.main import _planned_session_dict
from backend.models import PlannedSession, User, Workout
from backend.services import training_load as tl


@pytest.fixture()
def estimate_user():
    with Session(engine) as s:
        u = User(name=f"plan-estimate-{uuid.uuid4().hex[:8]}", is_active=True)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    yield uid
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        s.commit()


# ── estimate_historical_pace_and_tss: buckets by duration ────────────────────

def test_baseline_buckets_run_pace_by_duration(estimate_user):
    day = date.today() - timedelta(days=3)
    with Session(engine) as s:
        # "long" bucket: 100min / 14km -> ~7.14 min/km
        s.add(Workout(user_id=estimate_user, workout_date=day, name="Long run",
                       workout_type="run", duration_seconds=100 * 60, distance_km=14, tss=100))
        # "short" bucket: 30min / 5km -> 6 min/km (a different, faster pace)
        s.add(Workout(user_id=estimate_user, workout_date=day, name="Intervals",
                       workout_type="run", duration_seconds=30 * 60, distance_km=5, tss=60))
        s.commit()

    with Session(engine) as s:
        baseline = tl.estimate_historical_pace_and_tss(estimate_user, s)

    assert baseline["run_pace_min_per_km"]["long"] == pytest.approx(100 / 14, rel=0.01)
    assert baseline["run_pace_min_per_km"]["short"] == pytest.approx(30 / 5, rel=0.01)
    assert baseline["run_pace_min_per_km"]["moderate"] is None
    assert baseline["run_tss_per_min"] == pytest.approx(160 / 130, rel=0.01)


def test_baseline_strength_tss_per_min(estimate_user):
    day = date.today() - timedelta(days=3)
    with Session(engine) as s:
        s.add(Workout(user_id=estimate_user, workout_date=day, name="Leg day",
                       workout_type="strength", duration_seconds=45 * 60, tss=45))
        s.commit()

    with Session(engine) as s:
        baseline = tl.estimate_historical_pace_and_tss(estimate_user, s)
    assert baseline["strength_tss_per_min"] == pytest.approx(1.0, rel=0.01)


def test_baseline_ignores_workouts_outside_lookback_window(estimate_user):
    stale = date.today() - timedelta(days=tl._PLANNED_ESTIMATE_LOOKBACK_DAYS + 5)
    with Session(engine) as s:
        s.add(Workout(user_id=estimate_user, workout_date=stale, name="Old run",
                       workout_type="run", duration_seconds=60 * 60, distance_km=10, tss=80))
        s.commit()

    with Session(engine) as s:
        baseline = tl.estimate_historical_pace_and_tss(estimate_user, s)
    assert all(v is None for v in baseline["run_pace_min_per_km"].values())
    assert baseline["run_tss_per_min"] is None


def test_baseline_with_no_history_returns_all_none(estimate_user):
    with Session(engine) as s:
        baseline = tl.estimate_historical_pace_and_tss(estimate_user, s)
    assert all(v is None for v in baseline["run_pace_min_per_km"].values())
    assert baseline["run_tss_per_min"] is None
    assert baseline["strength_tss_per_min"] is None


# ── estimate_planned_session_metrics: apply baseline to one session ─────────

_BASELINE = {
    "run_pace_min_per_km": {"short": 6.0, "moderate": 7.5, "long": 7.14},
    "run_tss_per_min": 1.2,
    "strength_tss_per_min": 0.8,
}


def test_run_estimate_uses_matching_duration_bucket():
    structure = {"blocks": [
        {"phase": "warmup", "duration_min": 10},
        {"phase": "main", "duration_min": 70},
        {"phase": "cooldown", "duration_min": 10},
    ]}  # 90min total -> "long" bucket
    out = tl.estimate_planned_session_metrics(_BASELINE, "run", structure)
    assert out["estimated_distance_km"] == pytest.approx(90 / 7.14, rel=0.02)
    assert out["estimated_tss"] == round(90 * 1.2)


def test_run_estimate_falls_back_when_bucket_has_no_data():
    baseline = {"run_pace_min_per_km": {"short": None, "moderate": None, "long": 7.0},
                "run_tss_per_min": None, "strength_tss_per_min": None}
    structure = {"blocks": [{"phase": "main", "duration_min": 20}]}  # "short", no data
    out = tl.estimate_planned_session_metrics(baseline, "run", structure)
    # Falls back to the one bucket that DOES have data (7.0) rather than giving up.
    assert out["estimated_distance_km"] == pytest.approx(20 / 7.0, rel=0.02)
    assert out["estimated_tss"] is None  # no run_tss_per_min at all


def test_strength_estimate_uses_exercise_count_proxy_duration():
    structure = {"exercises": [{"name": "Squat"}, {"name": "Row"}, {"name": "Press"}]}
    out = tl.estimate_planned_session_metrics(_BASELINE, "strength", structure)
    expected_dur = 3 * tl._STRENGTH_MIN_PER_EXERCISE
    assert out["estimated_tss"] == round(expected_dur * 0.8)
    assert out["estimated_distance_km"] is None


def test_run_estimate_prefers_target_tss_pin():
    # Blocks alone would yield 90 * 1.2 = 108; pin must win for week-badge path.
    structure = {
        "target_tss": 70,
        "duration_minutes": 60,
        "blocks": [
            {"phase": "warmup", "duration_min": 10},
            {"phase": "main", "duration_min": 70},
            {"phase": "cooldown", "duration_min": 10},
        ],
    }
    out = tl.estimate_planned_session_metrics(_BASELINE, "run", structure)
    assert out["estimated_tss"] == 70
    # duration_minutes pin drives distance (moderate bucket @ 7.5 min/km)
    assert out["estimated_distance_km"] == pytest.approx(60 / 7.5, rel=0.02)


def test_run_estimate_no_pin_still_uses_historical():
    structure = {"blocks": [{"phase": "main", "duration_min": 60}]}
    out = tl.estimate_planned_session_metrics(_BASELINE, "run", structure)
    assert out["estimated_tss"] == round(60 * 1.2)
    assert out["estimated_distance_km"] == pytest.approx(60 / 7.5, rel=0.02)


def test_strength_estimate_prefers_target_tss_pin_when_pending():
    # Pending exercises → no actual spend; without pin would be n×5×0.8.
    structure = {
        "target_tss": 40,
        "exercises": [
            {"name": "Squat", "state": "pending"},
            {"name": "Row", "state": "pending"},
        ],
    }
    out = tl.estimate_planned_session_metrics(_BASELINE, "strength", structure)
    assert out["estimated_tss"] == 40
    assert out["estimated_tss"] != round(2 * tl._STRENGTH_MIN_PER_EXERCISE * 0.8)


def test_planned_duration_prefers_duration_minutes_pin():
    structure = {
        "duration_minutes": 55,
        "blocks": [{"phase": "main", "duration_min": 90}],
    }
    assert tl._planned_duration_minutes("run", structure) == 55.0


def test_no_structure_returns_no_estimate():
    assert tl.estimate_planned_session_metrics(_BASELINE, "run", None) == {
        "estimated_tss": None, "estimated_distance_km": None,
    }
    assert tl.estimate_planned_session_metrics(_BASELINE, "strength", {}) == {
        "estimated_tss": None, "estimated_distance_km": None,
    }


def test_rest_type_never_estimated():
    structure = {"blocks": [{"phase": "main", "duration_min": 30}]}
    assert tl.estimate_planned_session_metrics(_BASELINE, "rest", structure) == {
        "estimated_tss": None, "estimated_distance_km": None,
    }


# ── _planned_session_dict: no estimate for past or missed sessions ──────────
# "we won't be able to make it" — a session whose date has already gone by
# (whether or not the reconcile sweep has flipped it to status=missed yet)
# can't still happen, so it shouldn't inflate "TSS still coming this week".

_RUN_STRUCTURE = {"blocks": [{"phase": "main", "duration_min": 60}]}


def test_no_estimate_for_past_unmatched_session(estimate_user):
    past = date.today() - timedelta(days=2)
    with Session(engine) as s:
        p = PlannedSession(user_id=estimate_user, planned_date=past, session_type="run",
                            name="Missed run", status="planned", structure=_RUN_STRUCTURE)
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id

    baseline = {"run_pace_min_per_km": {"short": None, "moderate": 6.0, "long": None},
                "run_tss_per_min": 1.0, "strength_tss_per_min": None}
    with Session(engine) as s:
        p = s.get(PlannedSession, pid)
        d = _planned_session_dict(p, None, baseline)
    assert d["estimated_tss"] is None
    assert d["estimated_distance_km"] is None


def test_no_estimate_for_explicitly_missed_session(estimate_user):
    today = date.today()
    with Session(engine) as s:
        p = PlannedSession(user_id=estimate_user, planned_date=today, session_type="run",
                            name="Missed run", status="missed", structure=_RUN_STRUCTURE)
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id

    baseline = {"run_pace_min_per_km": {"short": None, "moderate": 6.0, "long": None},
                "run_tss_per_min": 1.0, "strength_tss_per_min": None}
    with Session(engine) as s:
        p = s.get(PlannedSession, pid)
        d = _planned_session_dict(p, None, baseline)
    assert d["estimated_tss"] is None
    assert d["estimated_distance_km"] is None


def test_estimate_present_for_todays_and_future_planned_sessions(estimate_user):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    with Session(engine) as s:
        p1 = PlannedSession(user_id=estimate_user, planned_date=today, session_type="run",
                             name="Today's run", status="planned", structure=_RUN_STRUCTURE)
        p2 = PlannedSession(user_id=estimate_user, planned_date=tomorrow, session_type="run",
                             name="Tomorrow's run", status="planned", structure=_RUN_STRUCTURE)
        s.add_all([p1, p2]); s.commit()
        ids = [p1.id, p2.id]

    baseline = {"run_pace_min_per_km": {"short": None, "moderate": 6.0, "long": None},
                "run_tss_per_min": 1.0, "strength_tss_per_min": None}
    with Session(engine) as s:
        for pid in ids:
            p = s.get(PlannedSession, pid)
            d = _planned_session_dict(p, None, baseline)
            assert d["estimated_tss"] == 60
            assert d["estimated_distance_km"] == 10.0
