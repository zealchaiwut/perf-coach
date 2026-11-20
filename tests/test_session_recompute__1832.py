"""Issue #1832 — dry-run and training-load replay enqueue."""

import uuid
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import User, Workout
from backend.services.session_strength_save import dry_run_strength_session, enqueue_training_load_replay


def test_dry_run_does_not_persist():
    with Session(engine) as session:
        u = session.query(User).first()
        if u is None:
            pytest.skip("no user")
        before = session.query(Workout).filter(Workout.user_id == u.id).count()
        payload = dry_run_strength_session(
            session,
            u.id,
            workout_id=None,
            workout_date=date(2025, 3, 10),
            duration_seconds=52 * 60,
            session_effort=7,
            strength_tss_method="effort_time",
            exercises=[{"name": "Goblet squat", "sets": 3, "reps": 10, "kg": 24}],
        )
        after = session.query(Workout).filter(Workout.user_id == u.id).count()
        assert after == before
        assert payload.get("valid")
        assert payload.get("session_tss") == 42


def test_enqueue_dedupe_key():
    uid = uuid.uuid4()
    with patch("backend.services.session_strength_save.job_queue.enqueue") as enq:
        enq.return_value = "job-1"
        enqueue_training_load_replay(uid, [uid], date(2025, 1, 6))
        enq.assert_called_once()
        assert enq.call_args.kwargs.get("dedupe_key") == f"training_load_replay:{uid}"
