"""Tests for the real recalibrate-from-race loop (Performance tab, unit 4).

Pure tests for the weighting/blend math; live-DB tests for the backcast +
self-healing calibration + corrected estimates (live UAT server on
UAT_BASE_URL/UAT_PORT, same pattern as test_projection_race_floor__perftab2).
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
from backend.models import Race, RaceCalibration, RacePrediction, User, UserPreferences, Workout
from backend.services.race_calibration import (
    CORRECTION_CLAMP,
    calibration_weight,
    combined_correction,
)

BASE_URL = os.environ.get("UAT_BASE_URL") or (
    "http://127.0.0.1:" + os.environ.get("UAT_PORT", "9001")
)

_TODAY = date(2026, 7, 10)


# ── Pure: weighting + blend ──────────────────────────────────────────────────

def test_weight_same_distance_today_is_one():
    w = calibration_weight(_TODAY, 21.1, 21.1, _TODAY)
    assert w == pytest.approx(1.0)


def test_weight_halves_at_recency_half_life():
    w = calibration_weight(_TODAY - timedelta(days=180), 21.1, 21.1, _TODAY)
    assert w == pytest.approx(0.5, abs=0.01)


def test_weight_halves_at_double_or_half_distance():
    w2 = calibration_weight(_TODAY, 42.2, 21.1, _TODAY)
    w_half = calibration_weight(_TODAY, 10.55, 21.1, _TODAY)
    assert w2 == pytest.approx(0.5, abs=0.01)
    assert w_half == pytest.approx(0.5, abs=0.01)


def test_combined_correction_no_data_is_neutral():
    assert combined_correction([], 21.1, today=_TODAY) == {
        "correction": 1.0, "n": 0, "raw_correction": None,
    }


def test_combined_correction_single_race_clamped():
    # A race 30% slower than predicted must not shift estimates 30% — clamp.
    cals = [{"race_date": _TODAY - timedelta(days=10), "distance_km": 21.1, "correction": 1.30}]
    out = combined_correction(cals, 21.1, today=_TODAY)
    assert out["correction"] == CORRECTION_CLAMP[1]
    assert out["raw_correction"] == pytest.approx(1.30, abs=0.01)


def test_combined_correction_geometric_mean_of_opposites_is_neutral():
    cals = [
        {"race_date": _TODAY - timedelta(days=10), "distance_km": 21.1, "correction": 0.8},
        {"race_date": _TODAY - timedelta(days=10), "distance_km": 21.1, "correction": 1.25},
    ]
    out = combined_correction(cals, 21.1, today=_TODAY)
    assert out["correction"] == pytest.approx(1.0, abs=0.01)


def test_combined_correction_weights_similar_distance_higher():
    # Target = half. A same-distance race says 5% slow, a marathon says 5%
    # fast; the half should dominate → blended correction > 1.0.
    cals = [
        {"race_date": _TODAY - timedelta(days=10), "distance_km": 21.1, "correction": 1.05},
        {"race_date": _TODAY - timedelta(days=10), "distance_km": 42.2, "correction": 0.95},
    ]
    out = combined_correction(cals, 21.1, today=_TODAY)
    assert out["correction"] > 1.0


def test_combined_correction_weights_recent_higher():
    cals = [
        {"race_date": _TODAY - timedelta(days=5), "distance_km": 21.1, "correction": 1.05},
        {"race_date": _TODAY - timedelta(days=360), "distance_km": 21.1, "correction": 0.95},
    ]
    out = combined_correction(cals, 21.1, today=_TODAY)
    assert out["correction"] > 1.0


# ── Live-DB: backcast + self-heal + corrected estimates ──────────────────────

@pytest.fixture()
def calibrated_athlete():
    pwd = "perftab3pass!"
    uid = uuid.uuid4()
    uname = f"perftab3_{uid.hex[:8]}"
    today = date.today()
    with Session(engine) as db:
        db.add(User(id=uid, name=uname, password_hash=hash_password(pwd),
                    is_admin=False, is_active=True))
        db.add(UserPreferences(user_id=uid, threshold_hr=172,
                               threshold_pace_seconds_per_km=330))
        # ~7 months of run history so the backcast (race eve − 180d warmup)
        # has real data on both sides of the done race.
        for i in range(210):
            if i % 2 == 0:
                db.add(Workout(
                    user_id=uid, workout_date=today - timedelta(days=i),
                    name=f"run {i}", workout_type="run", tss=45,
                    distance_km=8, duration_seconds=8 * 400, avg_hr=145,
                ))
        done = Race(
            user_id=uid, name="Done Half",
            race_date=today - timedelta(days=40), distance_km=21.1,
            status="done", actual_time_seconds=2 * 3600 + 19 * 60 + 26,
            priority="B", race_type="race",
        )
        upcoming = Race(
            user_id=uid, name="Target Half",
            race_date=today + timedelta(weeks=8), distance_km=21.1,
            goal_time_seconds=2 * 3600 + 5 * 60,
            priority="A", race_type="race", status="planned",
        )
        db.add(done)
        db.add(upcoming)
        db.commit()
        done_id, upcoming_id = str(done.id), str(upcoming.id)

    client = httpx.Client(base_url=BASE_URL, timeout=120.0)
    r = client.post("/api/auth/login", json={"username": uname, "password": pwd})
    assert r.status_code == 200, r.text

    yield client, uid, done_id, upcoming_id

    client.close()
    with Session(engine) as db:
        db.query(RaceCalibration).filter(RaceCalibration.user_id == uid).delete()
        db.query(RacePrediction).filter(RacePrediction.user_id == uid).delete()
        db.query(Workout).filter(Workout.user_id == uid).delete()
        db.query(Race).filter(Race.user_id == uid).delete()
        db.query(UserPreferences).filter(UserPreferences.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_calibration_status_self_heals_and_reports_real_row(calibrated_athlete):
    client, uid, done_id, _ = calibrated_athlete
    r = client.get("/api/calibration/status")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["calibrated"] is True
    assert data["n_calibrations"] >= 1
    assert data["correction"] is not None
    assert CORRECTION_CLAMP[0] <= data["correction"] <= CORRECTION_CLAMP[1]
    # last_calibration_date = the calibrated race's date, not updated_at noise
    assert data["last_calibration_date"] == (date.today() - timedelta(days=40)).isoformat()

    with Session(engine) as db:
        row = db.query(RaceCalibration).filter(RaceCalibration.race_id == uuid.UUID(done_id)).first()
        assert row is not None
        assert row.predicted_seconds > 0
        assert row.actual_seconds == 2 * 3600 + 19 * 60 + 26
        assert float(row.correction) == pytest.approx(row.actual_seconds / row.predicted_seconds, abs=0.001)


def test_readiness_exposes_and_applies_correction(calibrated_athlete):
    client, uid, done_id, upcoming_id = calibrated_athlete
    # Ensure the calibration row exists (status endpoint self-heals).
    assert client.get("/api/calibration/status").status_code == 200

    r = client.get(f"/api/races/{upcoming_id}/readiness")
    assert r.status_code == 200, r.text
    tc = r.json().get("time_curve") or {}
    assert tc.get("calibration_n_races", 0) >= 1
    corr = tc.get("calibration_correction")
    assert corr is not None
    assert CORRECTION_CLAMP[0] <= corr <= CORRECTION_CLAMP[1]
    # Riegel floor still the hard bound after correction.
    floor = tc.get("riegel_floor_seconds")
    assert floor is not None
    for sample in tc.get("projection") or []:
        assert sample["estimated_finish_seconds"] <= floor


def test_bundle_persists_race_day_prediction(calibrated_athlete):
    client, uid, done_id, upcoming_id = calibrated_athlete
    r = client.get("/api/plan/computed")
    assert r.status_code == 200, r.text
    races = r.json().get("races") or []
    target = next((x for x in races if x.get("id") == upcoming_id), None)
    assert target is not None
    est = (target.get("computed") or {}).get("estimate") or {}
    assert est.get("est") is not None

    with Session(engine) as db:
        row = (
            db.query(RacePrediction)
            .filter(RacePrediction.race_id == uuid.UUID(upcoming_id),
                    RacePrediction.prediction_date == date.today())
            .first()
        )
        assert row is not None
        assert row.predicted_seconds == est["est"]
