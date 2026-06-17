"""Seed one realistic Strava + Stryd activity for the demo user and reconcile
them into a single unified workout. Idempotent: re-running replaces the prior
mock rows (fixed sentinel ids) rather than duplicating.

Usage:
    ENVIRONMENT=uat DATABASE_URL="$DATABASE_URL_UAT" \
      .venv/bin/python scripts/seed_mock_strava_stryd.py --user_id <UUID>
"""
import argparse
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import StravaActivity, StrydActivity, Workout
from backend.services.reconcile import reconcile_workouts

STRAVA_SENTINEL_ID = 9_000_000_001          # fake strava_activity_id
STRYD_SENTINEL_ID = "mock-stryd-0001"        # fake stryd_activity_id
START = datetime(2026, 6, 15, 6, 0, 0, tzinfo=timezone.utc)


def _streams():
    """~600 s of per-point series (1 pt / 10 s) — HR, pace, power, GPS, etc."""
    n = 60
    time, hr, watts, vel, alt, cad, dist, latlng, grade = ([] for _ in range(9))
    base_lat, base_lng = 13.7563, 100.5018  # Bangkok
    for i in range(n):
        t = i * 10
        d = i * 167  # ~10 km over 600 s
        time.append(t)
        dist.append(d)
        hr.append(round(150 + 18 * math.sin(i / 7)))
        watts.append(round(265 + 30 * math.sin(i / 5)))
        vel.append(round(3.3 + 0.3 * math.sin(i / 6), 2))  # m/s
        alt.append(round(8 + 4 * math.sin(i / 11), 1))
        cad.append(round(88 + 3 * math.sin(i / 4)))         # per-leg
        grade.append(round(2 * math.sin(i / 9), 1))
        latlng.append([round(base_lat + i * 0.0006, 6), round(base_lng + i * 0.0004, 6)])
    return {
        "time": {"type": "time", "data": time, "series_type": "time", "original_size": n, "resolution": "high"},
        "distance": {"type": "distance", "data": dist},
        "heartrate": {"type": "heartrate", "data": hr},
        "watts": {"type": "watts", "data": watts},
        "velocity_smooth": {"type": "velocity_smooth", "data": vel},
        "altitude": {"type": "altitude", "data": alt},
        "cadence": {"type": "cadence", "data": cad},
        "grade_smooth": {"type": "grade_smooth", "data": grade},
        "latlng": {"type": "latlng", "data": latlng},
        "moving": {"type": "moving", "data": [True] * n},
    }


def _detail():
    """Full /activities/{id} shape: laps, per-km splits, best efforts, map."""
    laps = []
    for i in range(3):
        laps.append({
            "id": 100 + i,
            "lap_index": i + 1,
            "name": f"Lap {i + 1}",
            "distance": 3333.0,
            "moving_time": 1000 + i * 10,
            "elapsed_time": 1000 + i * 10,
            "average_speed": round(3.33 - i * 0.05, 2),
            "max_speed": round(3.8 - i * 0.05, 2),
            "average_heartrate": 152 + i * 6,
            "max_heartrate": 165 + i * 5,
            "average_cadence": 88 + i,
            "average_watts": 262 + i * 8,
            "total_elevation_gain": 4 + i,
            "pace_zone": 3 + i,
            "split": i + 1,
        })
    splits_metric = []
    for km in range(10):
        splits_metric.append({
            "distance": 1000.0,
            "elapsed_time": 300 - km * 2,
            "moving_time": 300 - km * 2,
            "elevation_difference": round(1.5 * math.sin(km), 1),
            "split": km + 1,
            "average_speed": round(3.33 + km * 0.02, 2),
            "average_grade_adjusted_speed": round(3.4 + km * 0.02, 2),
            "average_heartrate": 148 + km,
            "pace_zone": 3,
        })
    return {
        "id": STRAVA_SENTINEL_ID,
        "name": "Tempo 10K",
        "type": "Run",
        "sport_type": "Run",
        "distance": 10000.0,
        "moving_time": 3000,
        "elapsed_time": 3050,
        "total_elevation_gain": 42,
        "calories": 712.0,
        "description": "Mock tempo run for union demo.",
        "device_name": "Garmin Forerunner 965",
        "gear": {"id": "g123", "name": "Saucony Endorphin Speed", "distance": 540000},
        "average_heartrate": 156.0,
        "max_heartrate": 178.0,
        "average_watts": 268.0,
        "max_watts": 410.0,
        "average_cadence": 88.5,
        "suffer_score": 112,
        "map": {"id": "a123", "polyline": "_p~iF~ps|U_ulLn", "summary_polyline": "_p~iF~ps|U_ulLn"},
        "laps": laps,
        "splits_metric": splits_metric,
        "best_efforts": [
            {"name": "1k", "distance": 1000, "elapsed_time": 285, "pr_rank": 2},
            {"name": "5k", "distance": 5000, "elapsed_time": 1490, "pr_rank": 1},
            {"name": "10k", "distance": 10000, "elapsed_time": 3000, "pr_rank": 1},
        ],
        "segment_efforts": [],
    }


def _summary():
    return {
        "id": STRAVA_SENTINEL_ID,
        "name": "Tempo 10K",
        "type": "Run",
        "sport_type": "Run",
        "distance": 10000.0,
        "moving_time": 3000,
        "elapsed_time": 3050,
        "total_elevation_gain": 42,
        "average_heartrate": 156.0,
        "max_heartrate": 178.0,
        "average_watts": 268.0,
        "max_watts": 410.0,
        "average_cadence": 88.5,
        "suffer_score": 112,
        "device_name": "Garmin Forerunner 965",
        "external_id": "garmin_push_1234",
        "start_date": START.isoformat().replace("+00:00", "Z"),
        "start_date_local": START.isoformat().replace("+00:00", "Z"),
        "map": {"summary_polyline": "_p~iF~ps|U_ulLn"},
    }


def _stryd_payload():
    return {
        "form_metrics": {
            "leg_spring_stiffness": 10.4,
            "ground_contact_time_ms": 224,
            "vertical_oscillation_cm": 7.1,
            "form_power_w": 58,
            "air_power_w": 4,
            "cadence_spm": 177,
        },
        "power_zones": {
            "z1": 120, "z2": 640, "z3": 1500, "z4": 620, "z5": 120,
            "critical_power_w": 295,
        },
        "splits": [
            {"km": k + 1, "avg_power_w": 262 + k, "avg_hr": 148 + k,
             "duration_seconds": 300 - k * 2, "stryd_rss": round(3.0 + k * 0.1, 1)}
            for k in range(10)
        ],
    }


def seed(user_id: str) -> None:
    with Session(engine) as s:
        # Idempotent: drop prior mock rows + any workout linked to them.
        old_sa = s.query(StravaActivity).filter(StravaActivity.strava_activity_id == STRAVA_SENTINEL_ID).all()
        old_sta = s.query(StrydActivity).filter(StrydActivity.stryd_activity_id == STRYD_SENTINEL_ID).all()
        old_pks = {a.id for a in old_sa} | {a.id for a in old_sta}
        if old_pks:
            for w in s.query(Workout).filter(
                (Workout.strava_activity_pk.in_({a.id for a in old_sa}))
                | (Workout.stryd_activity_pk.in_({a.id for a in old_sta}))
            ).all():
                s.delete(w)
            for a in old_sa + old_sta:
                s.delete(a)
            s.commit()

        sa = StravaActivity(
            user_id=user_id,
            strava_activity_id=STRAVA_SENTINEL_ID,
            start_time=START,
            activity_type="Run",
            name="Tempo 10K",
            distance_km=10.0,
            duration_seconds=3000,
            avg_hr=156,
            max_hr=178,
            elevation_m=42,
            avg_power_w=268,
            max_power_w=410,
            avg_cadence=88.5,
            suffer_score=112,
            device_name="Garmin Forerunner 965",
            external_id="garmin_push_1234",
            is_stryd_synced=True,
            raw_payload=_summary(),
            detail_payload=_detail(),
            streams_payload=_streams(),
            synced_at=datetime.now(tz=timezone.utc),
        )
        sta = StrydActivity(
            user_id=user_id,
            stryd_activity_id=STRYD_SENTINEL_ID,
            start_time=START,
            name="Tempo 10K",
            distance_km=10.0,
            duration_seconds=3000,
            avg_power_w=266,
            avg_hr=156,
            tss=78,
            form_metrics=_stryd_payload()["form_metrics"],
            power_zones=_stryd_payload()["power_zones"],
            splits=_stryd_payload()["splits"],
            raw_payload=_stryd_payload(),
            synced_at=datetime.now(tz=timezone.utc),
        )
        s.add(sa)
        s.add(sta)
        s.commit()

    reconcile_workouts(None, user_id)

    with Session(engine) as s:
        w = (
            s.query(Workout)
            .filter(Workout.user_id == user_id, Workout.start_time == START)
            .order_by(Workout.created_at.desc())
            .first()
        )
        if w:
            print(f"WORKOUT_ID={w.id}")
            print(f"source={w.source} strava_pk={w.strava_activity_pk} stryd_pk={w.stryd_activity_pk}")
        else:
            print("NO WORKOUT CREATED")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_id", required=True)
    args = ap.parse_args()
    seed(args.user_id)
