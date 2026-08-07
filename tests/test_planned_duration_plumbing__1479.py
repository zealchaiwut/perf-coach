"""Tests for issue #1479: plumb planned_duration_seconds into run dicts.

The plan-relative guard in running_performance.compute_endurance_score reads
``planned_duration_seconds`` from each run dict, but none of the run dict
builders in main.py populated that key (issue #1479). This file tests the
helper ``_planned_duration_map`` added to fix the inert branch.

Acceptance criteria derived from the issue:
  AC1: ``_planned_duration_map(session, workout_ids)`` returns a dict mapping
       workout_id → planned_duration_seconds for workouts that have a matched
       PlannedSession with a parseable block structure.
  AC2: Returns an empty dict when workout_ids is empty.
  AC3: Workouts not matched to any PlannedSession are absent from the result.
  AC4: Workouts matched to a PlannedSession with no parseable blocks (no
       ``duration_min`` in any block) are absent from the result.
  AC5: End-to-end: when a workout is matched to a PlannedSession and the run
       dict is built via ``_planned_duration_map``, the plan-relative guard in
       ``compute_endurance_score`` correctly excludes a session cut materially
       short of the plan.
"""
import datetime
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as _OrmSess

_UTC = datetime.timezone.utc

# SQLite cannot render JSONB (PlannedSession.structure).  Map it to JSON for
# the sqlite dialect only so create_all works; Postgres is untouched.
try:
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json_on_sqlite(type_, compiler, **kw):
        return "JSON"
except Exception:
    pass

from backend.main import _planned_duration_map  # noqa: E402
from backend.models import Base, PlannedSession, User, Workout  # noqa: E402
from backend.services.running_performance import (  # noqa: E402
    compute_endurance_score,
    MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS,
    PLAN_SHORT_CUT_RATIO,
)
from backend.services.zone_constants import make_zone_constants  # noqa: E402

# ── In-memory SQLite DB for unit-level helper tests ──────────────────────────

_SQLITE_TABLES = (User, Workout, PlannedSession)

_TEST_STRUCTURE_60MIN = {
    "blocks": [{"duration_min": 60}]
}  # 3600 s

_TEST_STRUCTURE_NO_DURATION = {
    "blocks": [{"name": "warm-up"}]
}


@pytest.fixture(scope="module")
def sqlite_engine():
    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _register_pg_functions(dbapi_conn, _record):
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(_UTC).isoformat(sep=" ")
        )
        dbapi_conn.create_function(
            "gen_random_uuid", 0, lambda: str(uuid.uuid4())
        )

    Base.metadata.create_all(eng, tables=[t.__table__ for t in _SQLITE_TABLES])
    yield eng
    eng.dispose()


@pytest.fixture()
def db(sqlite_engine):
    with _OrmSess(sqlite_engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def test_user(db):
    u = User(
        id=uuid.uuid4(),
        name=f"pdm-test-{uuid.uuid4().hex[:8]}",
        is_active=True,
        created_at=datetime.datetime.now(_UTC),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ── AC2: empty workout_ids → empty result ─────────────────────────────────────

def test_empty_workout_ids_returns_empty_dict(db):
    """AC2: _planned_duration_map returns {} when workout_ids is empty."""
    result = _planned_duration_map(db, [])
    assert result == {}


# ── AC3: workout with no matched PlannedSession → absent from result ──────────

def _new_workout(test_user, **kwargs):
    """Create a Workout with an explicit UUID so SQLite refresh works."""
    return Workout(id=uuid.uuid4(), user_id=test_user.id, **kwargs)


def _new_planned_session(test_user, **kwargs):
    """Create a PlannedSession with an explicit UUID."""
    return PlannedSession(id=uuid.uuid4(), user_id=test_user.id, **kwargs)


def test_unmatched_workout_absent_from_result(db, test_user):
    """AC3: workout not matched to any PlannedSession produces no entry."""
    wk = _new_workout(test_user,
                      workout_date=date.today(),
                      name="Unmatched run",
                      workout_type="run",
                      duration_seconds=3600)
    db.add(wk)
    db.commit()

    result = _planned_duration_map(db, [wk.id])
    assert wk.id not in result


# ── AC4: matched PlannedSession with no parseable blocks → absent ─────────────

def test_matched_session_with_no_parseable_blocks_absent(db, test_user):
    """AC4: matched PlannedSession whose structure has no duration_min → absent."""
    wk = _new_workout(test_user,
                      workout_date=date.today() - timedelta(days=3),
                      name="Paired but unstructured run",
                      workout_type="run",
                      duration_seconds=3600)
    db.add(wk)
    db.commit()

    ps = _new_planned_session(test_user,
                               planned_date=date.today() - timedelta(days=3),
                               session_type="run",
                               structure=_TEST_STRUCTURE_NO_DURATION,
                               status="done_auto",
                               matched_workout_id=wk.id)
    db.add(ps)
    db.commit()

    result = _planned_duration_map(db, [wk.id])
    assert wk.id not in result, (
        "PlannedSession with no parseable duration should not produce an entry"
    )


# ── AC1: matched PlannedSession with parseable blocks → correct duration ──────

def test_matched_session_with_blocks_returns_correct_duration(db, test_user):
    """AC1: matched PlannedSession with duration_min blocks → correct seconds."""
    wk = _new_workout(test_user,
                      workout_date=date.today() - timedelta(days=5),
                      name="Planned easy run",
                      workout_type="run",
                      duration_seconds=3600)
    db.add(wk)
    db.commit()

    ps = _new_planned_session(test_user,
                               planned_date=date.today() - timedelta(days=5),
                               session_type="run",
                               structure=_TEST_STRUCTURE_60MIN,
                               status="done_auto",
                               matched_workout_id=wk.id)
    db.add(ps)
    db.commit()

    result = _planned_duration_map(db, [wk.id])
    assert wk.id in result, "Matched PlannedSession should produce an entry"
    assert result[wk.id] == 3600, (
        f"Expected 3600 s (60 min), got {result[wk.id]}"
    )


def test_multiple_workouts_correct_entries(db, test_user):
    """AC1 + AC3: map is correct when some workouts are matched and some are not."""
    wk_matched = _new_workout(test_user,
                               workout_date=date.today() - timedelta(days=6),
                               name="Matched run",
                               workout_type="run",
                               duration_seconds=3600)
    wk_unmatched = _new_workout(test_user,
                                 workout_date=date.today() - timedelta(days=7),
                                 name="Unmatched run",
                                 workout_type="run",
                                 duration_seconds=2700)
    db.add_all([wk_matched, wk_unmatched])
    db.commit()

    ps = _new_planned_session(test_user,
                               planned_date=date.today() - timedelta(days=6),
                               session_type="run",
                               structure={"blocks": [{"duration_min": 90}]},
                               status="done_auto",
                               matched_workout_id=wk_matched.id)
    db.add(ps)
    db.commit()

    result = _planned_duration_map(db, [wk_matched.id, wk_unmatched.id])
    assert wk_matched.id in result
    assert result[wk_matched.id] == 5400
    assert wk_unmatched.id not in result


def test_repeat_blocks_sum_correctly(db, test_user):
    """AC1: repeat × duration_min is summed correctly (matches _planned_duration_seconds)."""
    wk = _new_workout(test_user,
                      workout_date=date.today() - timedelta(days=8),
                      name="Interval run",
                      workout_type="run",
                      duration_seconds=4200)
    db.add(wk)
    db.commit()

    # 10 min warm-up + 5 × 6 min intervals + 4 × 1 min rest + 10 min cool-down
    # = 10 + 5*6 + 4*1 + 10 = 10 + 30 + 4 + 10 = 54 min = 3240 s
    structure = {
        "blocks": [
            {"duration_min": 10},
            {"duration_min": 6, "repeat": 5, "rest_min": 1},
            {"duration_min": 10},
        ]
    }
    ps = _new_planned_session(test_user,
                               planned_date=date.today() - timedelta(days=8),
                               session_type="run",
                               structure=structure,
                               status="done_auto",
                               matched_workout_id=wk.id)
    db.add(ps)
    db.commit()

    result = _planned_duration_map(db, [wk.id])
    assert wk.id in result
    assert result[wk.id] == 3240, f"Expected 3240 s, got {result[wk.id]}"


# ── AC5: End-to-end plan-relative guard fires when planned duration is plumbed ─

_TODAY = date.today()
_THRESHOLD_HR = 165.0


def _prefs():
    return {
        "ftp_w": 200,
        "threshold_hr": _THRESHOLD_HR,
        "threshold_pace_seconds_per_km": 300,
        "duration_curve_bests": None,
        "aerobic_decoupling_threshold": 8.0,
    }


def _easy_run(run_id: str, days_ago: int, total_s: float,
              planned_s: float | None = None) -> dict:
    dist = total_s / 360.0
    d = (_TODAY - timedelta(days=days_ago)).isoformat()
    run = {
        "run_id": run_id,
        "workout_date": d,
        "laps": [{"band": "easy", "avg_power": 170.0, "avg_hr": 140.0,
                  "distance_km": dist, "duration_seconds": total_s}],
        "decoupling_pct": 5.0,
        "avg_power": 170.0,
        "avg_hr": 140.0,
        "distance_km": dist,
        "duration_seconds": total_s,
    }
    if planned_s is not None:
        run["planned_duration_seconds"] = planned_s
    return run


def _baseline():
    return [_easy_run(f"base{i}", days_ago=10 + i * 7, total_s=3000.0) for i in range(3)]


def test_plan_short_run_excluded_when_planned_duration_plumbed():
    """AC5: plan-relative guard excludes run cut to 70% of plan when key is set.

    This test mirrors the pattern of test_endurance_plan_short_guard__1433.py
    but confirms that a run dict where planned_duration_seconds is populated
    via _planned_duration_map (simulated by setting the key directly) produces
    the same guard behaviour — i.e., that the guard is no longer inert once
    the key is plumbed.
    """
    baseline = _baseline()
    planned_s = 4000.0
    actual_s = 2800.0  # 70% of plan — below PLAN_SHORT_CUT_RATIO (75%)
    assert actual_s > MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS, (
        "Test setup: actual must exceed absolute threshold to isolate plan guard"
    )
    assert actual_s < PLAN_SHORT_CUT_RATIO * planned_s

    # Simulate what _planned_duration_map would populate in the run dict
    run_with_plan = _easy_run("plan-short", days_ago=1,
                              total_s=actual_s, planned_s=planned_s)

    result = compute_endurance_score(baseline + [run_with_plan], _prefs(),
                                     make_zone_constants())
    assert "plan-short" not in result.get("run_contributions", {}), (
        "Run cut to 70% of plan must be excluded when planned_duration_seconds is set"
    )


def test_run_without_planned_duration_still_admitted_above_absolute():
    """AC5 fallback: a run without planned_duration_seconds is still admitted
    when it exceeds MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS — the absolute
    guard is unchanged (issue #1433 AC3 contract preserved).
    """
    baseline = _baseline()
    run_no_plan = _easy_run("no-plan", days_ago=1, total_s=3000.0)
    assert "planned_duration_seconds" not in run_no_plan

    result = compute_endurance_score(baseline + [run_no_plan], _prefs(),
                                     make_zone_constants())
    assert "no-plan" in result.get("run_contributions", {}), (
        "Run without planned_duration_seconds that exceeds absolute threshold must be admitted"
    )
