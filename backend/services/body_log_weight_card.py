"""Revamp Home weight card (P6-10): rate chip, target line, eat-more guard, maintenance."""
from __future__ import annotations

import datetime as _dt
import uuid
from statistics import median
from typing import Any, Optional, Sequence

from sqlalchemy.orm import Session

from backend.models import Race, WeightTarget, Workout
from backend.services.body_log import seven_day_avg, sparkline_six_weeks, weekly_rate_kg
from backend.utils.time import today_bangkok


RATE_IN_RANGE_LO = -0.5
RATE_IN_RANGE_HI = -0.25
RATE_TOO_FAST = -0.75
EFFICIENCY_RATIO = 0.97


def rate_chip_state(weekly_rate: Optional[float]) -> str:
    """in_range | slow | too_fast | unknown — for a weight-loss goal (negative = losing)."""
    if weekly_rate is None:
        return "unknown"
    if weekly_rate < RATE_TOO_FAST:
        return "too_fast"
    if RATE_IN_RANGE_LO <= weekly_rate <= RATE_IN_RANGE_HI:
        return "in_range"
    if weekly_rate > RATE_IN_RANGE_HI:
        return "slow"
    # between -0.75 and -0.5: still fast but not eat-more tier; treat as slow/neutral
    return "slow"


def maintenance_window(
    session: Session,
    user_id: uuid.UUID,
    today: _dt.date,
) -> tuple[bool, Optional[_dt.date]]:
    """True from 21 days before an A race through 7 days after it."""
    rows = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.priority == "A",
        )
        .all()
    )
    for race in rows:
        start = race.race_date - _dt.timedelta(days=21)
        end = race.race_date + _dt.timedelta(days=7)
        if start <= today <= end:
            return True, race.race_date
    return False, None


def _easy_run_efficiencies(session: Session, user_id: uuid.UUID, today: _dt.date) -> list[tuple[_dt.date, float]]:
    lookback = today - _dt.timedelta(days=28)
    rows = (
        session.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= lookback,
            Workout.workout_date <= today,
            Workout.run_subtype == "easy",
        )
        .order_by(Workout.workout_date.asc())
        .all()
    )
    out: list[tuple[_dt.date, float]] = []
    for w in rows:
        if w.avg_power and w.avg_hr and w.avg_hr > 0:
            out.append((w.workout_date, float(w.avg_power) / float(w.avg_hr)))
    return out


def easy_run_efficiency_flag(efficiencies: Sequence[tuple[_dt.date, float]], today: _dt.date) -> bool:
    """7-day median efficiency under 0.97 × 28-day median."""
    if not efficiencies:
        return False
    recent = [e for d, e in efficiencies if today - _dt.timedelta(days=6) <= d <= today]
    baseline = [e for d, e in efficiencies]
    if len(recent) < 1 or len(baseline) < 2:
        return False
    med7 = median(recent)
    med28 = median(baseline)
    if med28 <= 0:
        return False
    return med7 < EFFICIENCY_RATIO * med28


def target_line_points(
    *,
    today: _dt.date,
    seven_avg: Optional[float],
    target_weight_kg: float,
    target_date: _dt.date,
) -> list[dict[str, Any]]:
    """Dotted projection from today's 7d avg to target weight on target date."""
    if seven_avg is None or target_date <= today:
        return []
    days = (target_date - today).days
    if days <= 0:
        return []
    step = (target_weight_kg - seven_avg) / days
    points: list[dict[str, Any]] = []
    for i in range(0, days + 1, max(1, days // 12)):
        d = today + _dt.timedelta(days=i)
        val = round(seven_avg + step * i, 2)
        points.append({"date": d.isoformat(), "value": val})
    if points[-1]["date"] != target_date.isoformat():
        points.append({"date": target_date.isoformat(), "value": round(target_weight_kg, 2)})
    return points


def weight_card_payload(
    session: Session,
    user_id: uuid.UUID,
    *,
    weight_rows: Sequence[tuple[_dt.date, float]],
    today: Optional[_dt.date] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    avg = seven_day_avg(weight_rows, today)
    rate = weekly_rate_kg(weight_rows, today)
    chip = rate_chip_state(rate)
    in_maint, race_date = maintenance_window(session, user_id, today)

    eff_rows = _easy_run_efficiencies(session, user_id, today)
    eff_flag = easy_run_efficiency_flag(eff_rows, today)
    rate_fast = rate is not None and rate < RATE_TOO_FAST
    eat_more = bool(rate_fast or eff_flag)

    target = (
        session.query(WeightTarget)
        .filter(WeightTarget.user_id == user_id, WeightTarget.status == "active")
        .order_by(WeightTarget.created_at.desc())
        .first()
    )

    target_weight = float(target.target_weight_kg) if target else 80.0
    target_date = (
        target.target_date
        if target
        else _dt.date(2027, 8, 29)
    )
    if not isinstance(target_date, _dt.date):
        target_date = _dt.date.fromisoformat(str(target_date))

    phase = "Maintenance" if in_maint else "Deficit"
    show_target_line = not in_maint and avg is not None

    return {
        "seven_day_avg_kg": avg,
        "weekly_rate_kg": rate,
        "rate_chip": chip,
        "sparkline_6w": sparkline_six_weeks(weight_rows, today),
        "target_weight_kg": target_weight,
        "target_date": target_date.isoformat(),
        "target_line": target_line_points(
            today=today,
            seven_avg=avg,
            target_weight_kg=target_weight,
            target_date=target_date,
        )
        if show_target_line
        else [],
        "show_target_line": show_target_line,
        "eat_more_flag": eat_more,
        "eat_more_reasons": {
            "rate_too_fast": rate_fast,
            "easy_efficiency_low": eff_flag,
        },
        "phase_label": phase,
        "maintenance_window": in_maint,
        "maintenance_race_date": race_date.isoformat() if race_date else None,
        "has_active_target": target is not None,
    }