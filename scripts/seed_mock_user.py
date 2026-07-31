#!/usr/bin/env python3
"""Create a disposable mock athlete with synthetic-but-realistic history.

Purely additive: it reads no other user's data and touches no other user's
rows. Used to drive the app in a browser for UX review without going near a
real account.

Generates, for one new user:
  - ~20 weeks of runs (easy / tempo / intervals / long) with TSS, HR, pace
  - daily wellness metrics (RHR, HRV, sleep, energy, mood)
  - weight entries on a gentle downward trend, plus an active weight target
  - five habits with logs
  - fuel settings

Usage:
    ENVIRONMENT=uat python scripts/seed_mock_user.py --name uxmock
    ENVIRONMENT=uat python scripts/seed_mock_user.py --name uxmock --drop
"""
import argparse
import math
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import engine, environment
from backend.utils.time import now_utc, today_bangkok
from backend.models import (
    DailyMetric,
    FuelSettings,
    Habit,
    HabitLog,
    User,
    WeightEntry,
    WeightTarget,
    Workout,
)

WEEKS = 20
RNG = random.Random(20260801)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _marker(name: str) -> str:
    """Stamp identifying a user this script created. `.invalid` is reserved by
    RFC 2606, so it can never collide with a real address."""
    return f"{name}@mock.invalid"


# weekday -> (name, type, subtype, minutes, tss, km) ; None = rest
WEEK_PLAN = {
    0: None,
    1: ("Intervals", "run", "intervals", 52, 78, 10.5),
    2: ("Easy run", "run", "easy", 45, 42, 8.0),
    3: ("Tempo", "run", "tempo", 55, 72, 11.0),
    4: ("Strength", "strength", None, 45, 30, None),
    5: ("Long run", "run", "long", 105, 118, 21.0),
    6: ("Recovery jog", "run", "easy", 35, 28, 6.0),
}


def build_workouts(user_id, today):
    out = []
    start = _monday(today) - timedelta(weeks=WEEKS - 1)
    for i in range((today - start).days + 1):
        d = start + timedelta(days=i)
        spec = WEEK_PLAN[d.weekday()]
        if spec is None:
            continue
        # skip ~8% of sessions so adherence isn't a perfect 100%
        if RNG.random() < 0.08:
            continue
        name, wtype, sub, mins, tss, km = spec
        # a gentle build with a down week every 4th
        week_i = (d - start).days // 7
        block = 0.88 if week_i % 4 == 3 else 1.0 + week_i * 0.006
        jitter = RNG.uniform(0.92, 1.08)
        f = block * jitter
        dur = int(mins * 60 * f)
        w = Workout(
            id=uuid.uuid4(),
            user_id=user_id,
            workout_date=d,
            name=name,
            workout_type=wtype,
            run_subtype=sub,
            tss=round(tss * f, 1),
            tss_source="hr",
            tss_method="hr",
            source="manual",
            duration_seconds=dur,
            start_time=datetime.combine(d, time(6, 15)),
            created_at=datetime.combine(d, time(7, 30)),
            updated_at=datetime.combine(d, time(7, 30)),
        )
        if km:
            w.distance_km = round(km * f, 2)
            w.avg_hr = int({"easy": 138, "long": 146, "tempo": 162, "intervals": 168}[sub] * RNG.uniform(0.98, 1.02))
            w.max_hr = w.avg_hr + RNG.randint(8, 22)
            w.elevation_m = RNG.randint(20, 140)
            w.avg_cadence_spm = RNG.randint(84, 90)
            w.avg_power = RNG.randint(240, 290)
            w.zone2_minutes = int(dur / 60 * (0.8 if sub in ("easy", "long") else 0.35))
        out.append(w)
    return out


def build_metrics(user_id, today):
    out = []
    for i in range(120):
        d = today - timedelta(days=i)
        # a couple of gaps, as in real life
        if i in (3, 17, 18, 41):
            continue
        phase = math.sin(i / 9)
        out.append(DailyMetric(
            id=uuid.uuid4(),
            user_id=user_id,
            metric_date=d,
            resting_hr=int(48 + 3 * phase + RNG.uniform(-1.5, 1.5)),
            hrv=int(68 + 8 * phase + RNG.uniform(-5, 5)),
            sleep_hours=round(7.1 + 0.8 * phase + RNG.uniform(-0.6, 0.6), 1),
            sleep_quality=max(1, min(5, round(3.6 + phase))),
            energy=max(1, min(5, round(3.6 + phase * 0.8))),
            mood=max(1, min(5, round(3.8 + phase * 0.6))),
            created_at=datetime.combine(d, time(7, 0)),
            updated_at=datetime.combine(d, time(7, 0)),
        ))
    return out


def build_weights(user_id, today):
    out = []
    start_kg = 79.4
    for i in range(0, 126):
        d = today - timedelta(days=i)
        if d.weekday() not in (0, 3, 5):  # ~3 weigh-ins a week
            continue
        if RNG.random() < 0.12:
            continue
        trend = start_kg - (126 - i) * 0.0265
        out.append(WeightEntry(
            id=uuid.uuid4(),
            user_id=user_id,
            entry_date=d,
            entry_time=time(6, 40),
            weight_kg=round(trend + RNG.uniform(-0.45, 0.45), 2),
            source="manual",
            created_at=datetime.combine(d, time(6, 45)),
            updated_at=datetime.combine(d, time(6, 45)),
        ))
    return out


HABITS = [
    ("Zone 2 minutes", "weekly_minutes", 180, "training", "workout.zone2_minutes"),
    ("Strength sessions", "weekly_count", 2, "training", "workout.lift_count"),
    ("Mobility / stretch", "daily_checkmark", None, "training", None),
    ("Protein target", "daily_checkmark", None, "general", None),
    ("Lights out by 22:30", "daily_checkmark", None, "general", None),
]


def build_habits(user_id, today):
    habits, logs = [], []
    for order, (name, tracking, target, section, auto) in enumerate(HABITS):
        h = Habit(
            id=uuid.uuid4(),
            user_id=user_id,
            name=name,
            tracking_type=tracking,
            habit_type="count" if tracking != "daily_checkmark" else "binary",
            schedule_type="daily" if tracking == "daily_checkmark" else "weekly",
            weekly_target=target,
            section=section,
            auto_fill_source=auto,
            active=True,
            display_order=order,
            sort_order=order,
            created_at=datetime.combine(today - timedelta(days=120), time(9, 0)),
        )
        habits.append(h)
        for i in range(70):
            d = today - timedelta(days=i)
            if tracking == "daily_checkmark":
                if RNG.random() < 0.72:
                    logs.append(HabitLog(
                        id=uuid.uuid4(), habit_id=h.id, user_id=user_id,
                        log_date=d, log_week_start=_monday(d), value=1,
                        source="manual",
                    ))
            elif d.weekday() == 6:  # weekly rollup logged on Sunday
                logs.append(HabitLog(
                    id=uuid.uuid4(), habit_id=h.id, user_id=user_id,
                    log_date=d, log_week_start=_monday(d),
                    value=round(float(target) * RNG.uniform(0.6, 1.15), 1),
                    source="manual",
                ))
    return habits, logs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="uxmock")
    ap.add_argument("--drop", action="store_true",
                    help="delete this mock user first (only ever the mock user)")
    args = ap.parse_args()
    today = today_bangkok()

    with Session(engine) as s:
        existing = s.execute(
            select(User).where(User.name == args.name)
        ).scalar_one_or_none()
        if existing and not args.drop:
            print(f"[{environment}] {args.name} already exists: {existing.id}")
            return 0
        if existing:
            # --drop deletes cascade-wide, so it may only ever touch a user this
            # script created. The marker is the reserved-TLD email it stamps on;
            # matching on the name alone would let a typo take out a real account.
            if (existing.email or "") != _marker(args.name):
                print(
                    f"refusing to drop '{args.name}': not created by this script "
                    f"(expected email {_marker(args.name)}, found "
                    f"{existing.email!r}). Delete it by hand if you meant to.",
                    file=sys.stderr,
                )
                return 1
            s.delete(existing)
            s.commit()
            print(f"[{environment}] dropped previous {args.name}")

        uid = uuid.uuid4()
        s.add(User(
            id=uid, name=args.name, email=_marker(args.name),
            is_admin=False, is_active=True,
            height_cm=178, birth_date=date(1989, 4, 12),
            athlete_context="Recreational runner, 3 yrs consistent. "
                            "Target: sub-1:35 half in November.",
            created_at=now_utc(),
        ))
        s.flush()

        workouts = build_workouts(uid, today)
        metrics = build_metrics(uid, today)
        weights = build_weights(uid, today)
        habits, logs = build_habits(uid, today)

        s.add_all(workouts)
        s.add_all(metrics)
        s.add_all(weights)
        s.add_all(habits)
        s.flush()
        s.add_all(logs)

        s.add(WeightTarget(
            id=uuid.uuid4(), user_id=uid,
            start_weight_kg=79.4, start_date=today - timedelta(days=126),
            target_weight_kg=74.0, target_date=today + timedelta(days=56),
            status="active",
            created_at=now_utc(), updated_at=now_utc(),
        ))
        s.add(FuelSettings(
            id=uuid.uuid4(), user_id=uid,
            weight_kg=76.0, base_kcal=2450, maintenance_source="estimated",
            deficit_kcal=350, protein_g_per_kg=1.8, fat_g=70,
            ea_floor=30, run_kcal_per_kg_per_km=1.0, auto_periodize=True,
            created_at=now_utc(), updated_at=now_utc(),
        ))
        s.commit()

    print(f"[{environment}] created {args.name} = {uid}")
    print(f"  workouts {len(workouts)}  metrics {len(metrics)} "
          f" weights {len(weights)}  habits {len(habits)}  habit_logs {len(logs)}")
    print(f"\nNext: ENVIRONMENT={environment.lower()} "
          f"python scripts/set_user_password.py {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
