"""Coach habit targets — Zone 2 + Daily stretch seeding and reads."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Habit, User
from backend.services.coach_habit_targets import (
    STRETCH_SOURCE,
    ZONE2_SOURCE,
    ensure_coach_tracked_habits,
    habit_targets_for_coach,
)


@pytest.fixture
def db_user():
    with Session(engine) as db:
        u = User(id=uuid.uuid4(), name=f"habit-target-{uuid.uuid4().hex[:8]}")
        db.add(u)
        db.commit()
        uid = u.id
        yield uid
        db.query(Habit).filter(Habit.user_id == uid).delete(synchronize_session=False)
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)
        db.commit()


def test_ensure_creates_zone2_and_stretch(db_user):
    with Session(engine) as db:
        rows = ensure_coach_tracked_habits(db, db_user)
        db.commit()
        assert rows["zone2"].auto_fill_source == ZONE2_SOURCE
        assert rows["stretch"].auto_fill_source == STRETCH_SOURCE
        assert float(rows["zone2"].weekly_target) == 150
        assert int(float(rows["stretch"].target_value)) == 10

        # Idempotent
        again = ensure_coach_tracked_habits(db, db_user)
        db.commit()
        assert again["zone2"].id == rows["zone2"].id
        assert again["stretch"].id == rows["stretch"].id

        ht = habit_targets_for_coach(db, db_user, ensure=False)
        assert ht["zone2_weekly_min"] == 150
        assert ht["stretch_daily_min"] == 10


def test_settings_html_no_weekly_zone2_target():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "frontend/pages/settings.html").read_text()
    assert 'id="thresholds-weekly-zone2-target"' not in html
    assert 'id="thresholds-provision-zone2-btn"' not in html
    assert "Zone 2 weekly minutes are tracked as a habit" in html


def test_plan_prefs_panel_markup():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "frontend/pages/training-log.html").read_text()
    assert 'id="plan-suggestions-prefs"' in html
    js = (Path(__file__).resolve().parents[1] / "frontend/js/training-plan.js").read_text()
    assert "pl-sug-strength-emphasis" in js
    assert "has-session" in js
    assert "is-past" in js
    assert "_saveTrainingPrefs" in js
    # Standalone Preferences button removed — merged into Suggest form
    assert 'id="pl-prefs"' not in js
    assert 'id="plan-prefs-panel"' not in html
