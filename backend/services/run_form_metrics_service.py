"""Upsert run_form_metrics rows from stryd_activities.

Used by both the incremental sync path (sync_runner.py) and the backfill
worker handler (worker_app.py).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date, timezone, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import RunFormMetrics, StrydActivity, Workout
from backend.services.form_metrics_extractor import extract_form_metrics_row

logger = logging.getLogger(__name__)


def upsert_form_metrics_for_activity(
    session: Session,
    activity: StrydActivity,
) -> bool:
    """Upsert one run_form_metrics row from a StrydActivity ORM instance.

    Returns True if a row was written, False if the payload had no metrics.
    The activity's form_metrics column must already be loaded (not deferred).
    """
    form_metrics = activity.form_metrics
    if form_metrics is None:
        form_metrics = {}

    run_date: date | None = None
    if activity.start_time is not None:
        try:
            run_date = activity.start_time.date()
        except AttributeError:
            run_date = None
    if run_date is None:
        return False

    workout_id = _resolve_workout_id(session, activity.id)

    row = extract_form_metrics_row(
        user_id=str(activity.user_id),
        stryd_activity_pk=str(activity.id),
        run_date=run_date,
        form_metrics=form_metrics,
        avg_power_w=activity.avg_power_w,
        workout_id=str(workout_id) if workout_id else None,
    )
    if row is None:
        return False

    stmt = (
        _pg_insert(RunFormMetrics)
        .values(**row)
        .on_conflict_do_update(
            constraint="uq_run_form_metrics_stryd_activity_pk",
            set_={
                "gct_ms": row["gct_ms"],
                "lss_kn_m": row["lss_kn_m"],
                "vertical_oscillation_cm": row["vertical_oscillation_cm"],
                "cadence_spm": row["cadence_spm"],
                "power_w": row["power_w"],
                "workout_id": row["workout_id"],
            },
        )
    )
    session.execute(stmt)
    return True


def _resolve_workout_id(session: Session, stryd_activity_pk) -> _uuid.UUID | None:
    """Return the workouts.id linked to this stryd_activity_pk, or None."""
    row = session.execute(
        select(Workout.id).where(Workout.stryd_activity_pk == stryd_activity_pk)
    ).scalar()
    return row


def upsert_form_metrics_for_user(user_id: str) -> dict:
    """Backfill all stryd_activities for user_id — open session internally.

    Returns {"processed": N, "written": M, "skipped": K}.
    """
    uid = _uuid.UUID(user_id)
    processed = written = skipped = 0

    with Session(engine) as session:
        rows = session.execute(
            select(StrydActivity)
            .where(StrydActivity.user_id == uid)
            .order_by(StrydActivity.start_time.asc())
        ).scalars().all()

        for activity in rows:
            processed += 1
            try:
                # Explicitly load the deferred form_metrics column.
                session.refresh(activity, attribute_names=["form_metrics"])
                did_write = upsert_form_metrics_for_activity(session, activity)
                if did_write:
                    written += 1
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "form_metrics upsert skipped for activity %s: %s",
                    activity.stryd_activity_id, exc,
                )
                skipped += 1

        session.commit()

    return {"processed": processed, "written": written, "skipped": skipped}
