"""Auto-fill habit log entries from workout data (issue #389).

Provides recompute_autofill_for_week which deletes then reinserts
workout_autofill HabitLog rows for habits that have auto_fill_source set.
"""
import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Habit, HabitLog, Workout

_log = logging.getLogger(__name__)


def recompute_autofill_for_week(user_id: UUID, week_start: date) -> dict:
    """Delete and reinsert workout_autofill habit_log rows for the given week.

    Returns {"habits_recomputed": N, "logs_created": N, "logs_deleted": N}.
    Idempotent: safe to call multiple times with the same arguments.
    """
    week_end = week_start + timedelta(days=6)

    with Session(engine) as session:
        habits = (
            session.query(Habit)
            .filter(
                Habit.user_id == user_id,
                Habit.auto_fill_source.isnot(None),
                not Habit.is_archived,
            )
            .all()
        )

        if not habits:
            return {"habits_recomputed": 0, "logs_created": 0, "logs_deleted": 0}

        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date >= week_start,
                Workout.workout_date <= week_end,
            )
            .all()
        )

        logs_deleted = 0
        logs_created = 0

        for habit in habits:
            deleted = (
                session.query(HabitLog)
                .filter(
                    HabitLog.habit_id == habit.id,
                    HabitLog.log_week_start == week_start,
                    HabitLog.source == "workout_autofill",
                )
                .delete(synchronize_session=False)
            )
            logs_deleted += deleted
            session.flush()

            # Dates already occupied by non-autofill (manual) rows
            occupied = {
                row.log_date
                for row in session.query(HabitLog)
                .filter(
                    HabitLog.habit_id == habit.id,
                    HabitLog.log_week_start == week_start,
                )
                .all()
            }

            date_values = _compute_date_values(habit.auto_fill_source, workouts)

            for log_date, value in date_values.items():
                if log_date not in occupied:
                    session.add(
                        HabitLog(
                            habit_id=habit.id,
                            user_id=user_id,
                            log_date=log_date,
                            log_week_start=week_start,
                            value=value,
                            source="workout_autofill",
                        )
                    )
                    logs_created += 1

        session.commit()

    return {
        "habits_recomputed": len(habits),
        "logs_created": logs_created,
        "logs_deleted": logs_deleted,
    }


def _compute_date_values(auto_fill_source: str, workouts: list) -> dict:
    """Return {date: float_value} for the given source and workout list."""
    values: dict = {}

    if auto_fill_source == "workout.zone2_minutes":
        for w in workouts:
            if w.zone2_minutes is not None:
                values[w.workout_date] = values.get(w.workout_date, 0.0) + float(w.zone2_minutes)

    elif auto_fill_source == "workout.run_count":
        for w in workouts:
            if w.workout_type and "run" in w.workout_type.lower():
                values[w.workout_date] = values.get(w.workout_date, 0.0) + 1.0

    elif auto_fill_source == "workout.lift_count":
        for w in workouts:
            if w.workout_type and "lift" in w.workout_type.lower():
                values[w.workout_date] = values.get(w.workout_date, 0.0) + 1.0

    elif auto_fill_source == "workout.total_duration_minutes":
        for w in workouts:
            if w.duration_seconds is not None:
                values[w.workout_date] = (
                    values.get(w.workout_date, 0.0) + w.duration_seconds / 60.0
                )

    elif auto_fill_source == "workout.distance_km":
        for w in workouts:
            if w.distance_km is not None:
                values[w.workout_date] = values.get(w.workout_date, 0.0) + float(w.distance_km)

    return values
