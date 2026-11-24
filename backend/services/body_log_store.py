"""DB helpers for body log read/write."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.models import DailyMetric, WeightEntry
from backend.services.body_log import (
    seven_day_avg,
    weekly_body_rollup,
    weekly_rate_kg,
)
from backend.services.weekly_rollup import normalize_week_start


def _weight_rows(session: Session, user_id: uuid.UUID, from_d: date, to_d: date) -> list[tuple[date, float]]:
    rows = (
        session.query(WeightEntry.entry_date, WeightEntry.weight_kg)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= from_d,
            WeightEntry.entry_date <= to_d,
        )
        .all()
    )
    out: list[tuple[date, float]] = []
    for d, w in rows:
        if w is not None:
            out.append((d if isinstance(d, date) else date.fromisoformat(str(d)), float(w)))
    return out


def _daily_row(session: Session, user_id: uuid.UUID, metric_date: date) -> Optional[DailyMetric]:
    return (
        session.query(DailyMetric)
        .filter(DailyMetric.user_id == user_id, DailyMetric.metric_date == metric_date)
        .first()
    )


def _weight_for_date(session: Session, user_id: uuid.UUID, metric_date: date) -> Optional[float]:
    row = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date == metric_date,
            WeightEntry.entry_time.is_(None),
        )
        .first()
    )
    if row is None:
        any_row = (
            session.query(WeightEntry)
            .filter(WeightEntry.user_id == user_id, WeightEntry.entry_date == metric_date)
            .order_by(WeightEntry.created_at.desc())
            .first()
        )
        row = any_row
    return round(float(row.weight_kg), 2) if row else None


def body_log_day_payload(session: Session, user_id: uuid.UUID, metric_date: date) -> dict[str, Any]:
    dm = _daily_row(session, user_id, metric_date)
    lookback_start = metric_date - timedelta(days=120)
    wrows = _weight_rows(session, user_id, lookback_start, metric_date)
    return {
        "date": metric_date.isoformat(),
        "weight_kg": _weight_for_date(session, user_id, metric_date),
        "lunch_rule": dm.lunch_rule if dm else None,
        "feet": dm.feet if dm else None,
        "steps": dm.steps if dm else None,
        "steps_source": dm.steps_source if dm else None,
        "stats": {
            "seven_day_avg_kg": seven_day_avg(wrows, metric_date),
            "weekly_rate_kg": weekly_rate_kg(wrows, metric_date),
        },
    }


def patch_body_log(
    session: Session,
    user_id: uuid.UUID,
    metric_date: date,
    *,
    weight_kg: Optional[float] = None,
    lunch_rule: Optional[bool] = None,
    feet: Optional[int] = None,
    steps: Optional[int] = None,
) -> dict[str, Any]:
    if weight_kg is not None:
        stmt = (
            pg_insert(WeightEntry)
            .values(
                user_id=user_id,
                entry_date=metric_date,
                entry_time=None,
                weight_kg=weight_kg,
                source="manual",
            )
            .on_conflict_do_update(
                index_elements=["user_id", "entry_date"],
                index_where=WeightEntry.entry_time.is_(None),
                set_={
                    "weight_kg": weight_kg,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
        )
        session.execute(stmt)

    patch_fields: dict[str, Any] = {}
    if lunch_rule is not None:
        patch_fields["lunch_rule"] = lunch_rule
    if feet is not None:
        patch_fields["feet"] = feet
    if steps is not None:
        patch_fields["steps"] = steps
        patch_fields["steps_source"] = "manual"

    if patch_fields:
        patch_fields["updated_at"] = datetime.now(timezone.utc)
        stmt = (
            pg_insert(DailyMetric)
            .values(user_id=user_id, metric_date=metric_date, **patch_fields)
            .on_conflict_do_update(
                index_elements=["user_id", "metric_date"],
                set_=patch_fields,
            )
        )
        session.execute(stmt)

    session.commit()
    return body_log_day_payload(session, user_id, metric_date)


def body_log_week_rollup(session: Session, user_id: uuid.UUID, week_start: date) -> dict[str, Any]:
    ws = normalize_week_start(week_start)
    we = ws + timedelta(days=6)
    dm_rows = (
        session.query(DailyMetric)
        .filter(
            DailyMetric.user_id == user_id,
            DailyMetric.metric_date >= ws,
            DailyMetric.metric_date <= we,
        )
        .all()
    )
    lunch: dict[date, Optional[bool]] = {r.metric_date: r.lunch_rule for r in dm_rows}
    steps: dict[date, Optional[int]] = {r.metric_date: r.steps for r in dm_rows}
    feet: dict[date, Optional[int]] = {r.metric_date: r.feet for r in dm_rows}
    return weekly_body_rollup(
        week_start=ws,
        week_end=we,
        lunch_by_date=lunch,
        steps_by_date=steps,
        feet_by_date=feet,
    )