from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import date

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Workout, WorkoutFeel

logger = logging.getLogger(__name__)


def auto_link_feel_entries(user_id: _uuid_mod.UUID, feel_date: date) -> int:
    """Link unlinked feel entries to the sole workout for user/date.

    Returns the number of entries updated (0 if skipped or nothing to link).
    """
    with Session(engine) as session:
        workouts = (
            session.query(Workout)
            .filter(Workout.user_id == user_id, Workout.workout_date == feel_date)
            .all()
        )

        if len(workouts) != 1:
            return 0

        workout = workouts[0]

        unlinked = (
            session.query(WorkoutFeel)
            .filter(
                WorkoutFeel.user_id == user_id,
                WorkoutFeel.feel_date == feel_date,
                WorkoutFeel.workout_id.is_(None),
            )
            .all()
        )

        for entry in unlinked:
            entry.workout_id = workout.id

        session.commit()
        return len(unlinked)
