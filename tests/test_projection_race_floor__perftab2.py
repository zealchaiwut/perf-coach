"""Tests for the projection fixes (Performance tab, unit 2):

1. Riegel floor — the time-curve estimate must never predict SLOWER than the
   Riegel equivalent of a race the athlete actually finished in the last 90
   days. Reported live: projected half 2:38:03 while the athlete ran 2:19:26
   ten weeks earlier with LOWER scores.
2. Race-day sample — the per-race "estimated" figure uses the LAST projection
   sample (race day, after build+taper), not proj[0] (~tomorrow).

Live-server + direct-DB seed (same pattern as
tests/test_training_load_single_source__loadmetricfix1.py): requires a
running UAT server (UAT_BASE_URL / UAT_PORT).
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.db import engine
from backend.models import Race, User, UserPreferences, Workout
from backend.services.riegel import riegel_project

BASE_URL = os.environ.get("UAT_BASE_URL") or (
    "http://127.0.0.1:" + os.environ.get("UAT_PORT", "9001")
)

_HALF_KM = 21.1
_ACTUAL_SECONDS = 2 * 3600 + 19 * 60 + 26  # 2:19:26 — the reported real result


@pytest.fixture()
def seeded_athlete():
    """User with threshold prefs, 10 weeks of run history, a DONE half 40
    days ago (2:19:26), and an UPCOMING half in 8 weeks."""
    pwd = "perftab2pass!"
    uid = uuid.uuid4()
    uname = f"perftab2_{uid.hex[:8]}"
    today = date.today()
    with Session(engine) as db:
        db.add(User(id=uid, name=uname, password_hash=hash_password(pwd),
                    is_admin=False, is_active=True))
        db.add(UserPreferences(user_id=uid, threshold_hr=172,
                               threshold_pace_seconds_per_km=330))
        # 10 weeks of easy runs, 3/week — enough TSS history to clear
        # building_baseline (needs >= 8 weeks).
        for i in range(70):
            if i % 2 == 0:
                db.add(Workout(
                    user_id=uid, workout_date=today - timedelta(days=i),
                    name=f"run {i}", workout_type="run", tss=45,
                    distance_km=8, duration_seconds=8 * 400, avg_hr=145,
                ))
        done = Race(
            user_id=uid, name="Demonstrated Half",
            race_date=today - timedelta(days=40), distance_km=_HALF_KM,
            status="done", actual_time_seconds=_ACTUAL_SECONDS,
            priority="B", race_type="race",
        )
        upcoming = Race(
            user_id=uid, name="Target Half",
            race_date=today + timedelta(weeks=8), distance_km=_HALF_KM,
            goal_time_seconds=2 * 3600 + 5 * 60,
            priority="A", race_type="race", status="planned",
        )
        db.add(done)
        db.add(upcoming)
        db.commit()
        upcoming_id = str(upcoming.id)

    client = httpx.Client(base_url=BASE_URL, timeout=60.0)
    r = client.post("/api/auth/login", json={"username": uname, "password": pwd})
    assert r.status_code == 200, r.text

    yield client, upcoming_id

    client.close()
    with Session(engine) as db:
        db.query(Workout).filter(Workout.user_id == uid).delete()
        db.query(Race).filter(Race.user_id == uid).delete()
        db.query(UserPreferences).filter(UserPreferences.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_projection_never_slower_than_demonstrated_race(seeded_athlete):
    client, upcoming_id = seeded_athlete
    r = client.get(f"/api/races/{upcoming_id}/readiness")
    assert r.status_code == 200, r.text
    tc = r.json().get("time_curve") or {}
    floor = riegel_project(_ACTUAL_SECONDS, _HALF_KM, _HALF_KM)  # same distance → == actual
    assert floor == _ACTUAL_SECONDS

    assert tc.get("riegel_floor_seconds") == floor

    proj = tc.get("projection") or []
    assert proj, "expected a projection series for an 8-weeks-out race"
    for sample in proj:
        assert sample["estimated_finish_seconds"] <= floor, (
            f"{sample['date']} predicts {sample['estimated_finish_seconds']}s, "
            f"slower than the demonstrated {floor}s"
        )

    # History samples from the demonstrated race's date forward are capped too.
    done_date = (date.today() - timedelta(days=40)).isoformat()
    for sample in tc.get("history") or []:
        if sample["date"] >= done_date:
            assert sample["estimated_finish_seconds"] <= floor


def test_bundle_estimate_uses_race_day_sample(seeded_athlete):
    client, upcoming_id = seeded_athlete
    # Self-heal calibrations FIRST so the readiness call and the bundle call
    # below both see the same calibrated state — the bundle lazily creates
    # calibration rows for done races, which would otherwise change the
    # correction between the two requests.
    assert client.get("/api/calibration/status").status_code == 200
    readiness = client.get(f"/api/races/{upcoming_id}/readiness")
    assert readiness.status_code == 200
    proj = (readiness.json().get("time_curve") or {}).get("projection") or []
    assert proj

    bundle = client.get("/api/plan/computed")
    assert bundle.status_code == 200, bundle.text
    races = bundle.json().get("races") or []
    target = next((x for x in races if x.get("id") == upcoming_id), None)
    assert target is not None
    est = (target.get("computed") or {}).get("estimate") or {}
    assert est.get("est") == proj[-1]["estimated_finish_seconds"], (
        "bundle estimate must be the race-day (last) projection sample, "
        f"got {est.get('est')} vs race-day {proj[-1]['estimated_finish_seconds']} "
        f"(day-1 was {proj[0]['estimated_finish_seconds']})"
    )
