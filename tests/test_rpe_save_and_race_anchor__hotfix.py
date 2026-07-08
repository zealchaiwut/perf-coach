"""Hotfix tests — PRD feedback: RPE not saving + Endurance stuck at 25.

Covers the three fixes on feature/prd-feedback-rpe-endurance:
1. PATCH /api/workouts/{id} accepts `exercises` and persists per-exercise rpe
   (was: WorkoutPatch had no exercises field → pydantic silently dropped it).
2. _performance_signature includes the races table + vdot-v5 token (was: adding
   a race never busted the performance cache).
3. _latest_race_perf anchors on the most recently RUN race (race_date DESC),
   not the most recently edited row (updated_at DESC).

Real-Postgres: rows are created under a throwaway user and deleted after each
test. Run against UAT:
    set -a; source .env; set +a
    export ENVIRONMENT=UAT DATABASE_URL=$DATABASE_URL_UAT
    .venv/bin/python -m pytest tests/test_rpe_save_and_race_anchor__hotfix.py -q
"""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.main import app, resolve_user, _latest_race_perf, _performance_signature
from backend.models import Race, User, Workout, WorkoutExercise

client = TestClient(app)


@pytest.fixture()
def test_user():
    """Throwaway DB user; resolve_user overridden to return it. Cascade delete
    cleans workouts/exercises/races."""
    with Session(engine) as s:
        u = User(name=f"hotfix-test-{uuid.uuid4().hex[:8]}", is_active=True)
        s.add(u)
        s.commit()
        s.refresh(u)
        uid = u.id

    class _U:  # what resolve_user yields
        id = uid
        name = "hotfix-test"
        is_admin = False

    app.dependency_overrides[resolve_user] = lambda: _U()
    yield uid
    app.dependency_overrides.pop(resolve_user, None)
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        s.commit()


def _mk_workout(uid, *, wtype="lift", exercises=()):
    with Session(engine) as s:
        w = Workout(user_id=uid, workout_date=date.today(), name="Leg day", workout_type=wtype)
        s.add(w)
        s.flush()
        for i, (name, rpe) in enumerate(exercises):
            s.add(WorkoutExercise(workout_id=w.id, display_order=i, name=name, sets=3, reps=10, rpe=rpe))
        s.commit()
        return str(w.id)


def _exercise_rpes(wid):
    with Session(engine) as s:
        rows = s.execute(
            text("SELECT name, rpe FROM workout_exercises WHERE workout_id = :w ORDER BY display_order"),
            {"w": wid},
        ).all()
    return [(r[0], r[1]) for r in rows]


# ── Fix 1: PATCH persists exercises + rpe ────────────────────────────────────

def test_patch_workout_persists_exercise_rpe(test_user):
    wid = _mk_workout(test_user, exercises=[("Back squat", None), ("Plank", None)])

    resp = client.patch(f"/api/workouts/{wid}", json={
        "exercises": [
            {"name": "Back squat", "sets": 4, "reps": 8, "rpe": 8},
            {"name": "Plank", "sets": 3, "reps": 40, "rpe": 6},
        ],
    })
    assert resp.status_code == 200, resp.text
    # response reflects the new exercises
    body = resp.json()
    assert [e["rpe"] for e in body["exercises"]] == [8, 6]
    # and the DB actually has them (the original bug: 200 but nothing written)
    assert _exercise_rpes(wid) == [("Back squat", 8), ("Plank", 6)]


def test_patch_workout_without_exercises_leaves_them_untouched(test_user):
    wid = _mk_workout(test_user, exercises=[("Back squat", 7)])
    resp = client.patch(f"/api/workouts/{wid}", json={"name": "Leg day (renamed)"})
    assert resp.status_code == 200
    assert _exercise_rpes(wid) == [("Back squat", 7)]  # None field ≠ clear


def test_patch_workout_invalid_rpe_422_and_no_partial_write(test_user):
    wid = _mk_workout(test_user, exercises=[("Back squat", 7)])
    resp = client.patch(f"/api/workouts/{wid}", json={
        "name": "should not stick",
        "exercises": [{"name": "Back squat", "rpe": 11}],
    })
    assert resp.status_code == 422
    # validated before any mutation: name unchanged, exercises unchanged
    assert _exercise_rpes(wid) == [("Back squat", 7)]
    with Session(engine) as s:
        name = s.execute(text("SELECT name FROM workouts WHERE id = :i"), {"i": wid}).scalar_one()
    assert name == "Leg day"


# ── Fix 3: race anchor picks latest race_date, not latest edit ───────────────

def _mk_race(uid, *, race_date, distance_km, secs):
    with Session(engine) as s:
        r = Race(
            user_id=uid, name=f"race-{race_date}", race_date=race_date,
            distance_km=distance_km, status="done", actual_time_seconds=secs,
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return str(r.id)


def test_latest_race_perf_orders_by_race_date(test_user):
    newer = date.today() - timedelta(days=30)
    older = date.today() - timedelta(days=120)
    # Insert the NEWER-dated race FIRST, then the older one — so the older race
    # has the more recent updated_at/created_at. The old ordering (updated_at)
    # would pick it; the fix must pick the newer race_date.
    _mk_race(test_user, race_date=newer, distance_km=21.45, secs=8366)   # half, faster perf
    _mk_race(test_user, race_date=older, distance_km=16.64, secs=6664)  # entered later

    with Session(engine) as s:
        perf = _latest_race_perf(s, test_user)
    assert perf is not None
    assert perf["date"] == newer.isoformat(), (
        f"anchor must be the most recently RUN race ({newer}), got {perf['date']}"
    )


def test_latest_race_perf_as_of_still_filters(test_user):
    newer = date.today() - timedelta(days=30)
    older = date.today() - timedelta(days=120)
    _mk_race(test_user, race_date=newer, distance_km=21.45, secs=8366)
    _mk_race(test_user, race_date=older, distance_km=16.64, secs=6664)
    with Session(engine) as s:
        perf = _latest_race_perf(s, test_user, as_of=older + timedelta(days=1))
    assert perf["date"] == older.isoformat()


# ── Fix 2: signature includes races + v5 ─────────────────────────────────────

def test_performance_signature_busts_on_new_race(test_user):
    with Session(engine) as s:
        sig_before = _performance_signature(s, test_user, None)
    assert sig_before.endswith("vdot-v5"), "formula token must be v5"

    _mk_race(test_user, race_date=date.today() - timedelta(days=7),
             distance_km=10.0, secs=3300)

    with Session(engine) as s:
        sig_after = _performance_signature(s, test_user, None)
    assert sig_after != sig_before, (
        "adding a finished race must change the performance cache signature "
        "(the PRD bug: scores served from a cache written before the race existed)"
    )
