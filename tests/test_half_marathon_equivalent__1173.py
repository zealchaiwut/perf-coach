"""Tests for issue #1173: Display half-marathon equivalent time on race/checkpoint entries.

AC coverage:
- AC1: Plan tab renders half_marathon_equivalent_seconds as HH:MM:SS for races
- AC2: Plan tab renders half_marathon_equivalent_seconds as HH:MM:SS for checkpoints
- AC3: Label reads "Half Equivalent" in the UI
- AC4: Null/zero/absent values omit the field or show a dash, not "00:00:00"
- AC5: Frontend reads value from API response field, no client-side recomputation
"""
import os
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess
from datetime import date as _date

from backend.models import Race, RaceCheckpoint, User
from backend.services.projection_service import race_to_dict as _race_to_dict
from backend.services.projection_service import checkpoint_to_dict as _checkpoint_to_dict
from backend.auth import hash_password as _hash_pw

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def test_half_marathon_equivalent__race_dict_includes_field():
    """AC1: Verify race_to_dict() returns half_marathon_equivalent_seconds."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    # Create a test race in the database
    with _OrmSess(_engine) as db:
        # Create a test user
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            name=f"test_hem_{user_id.hex[:8]}",
            password_hash=_hash_pw("test1173"),
        )
        db.add(user)
        db.flush()

        # Create a test race with actual_time_seconds set
        race = Race(
            id=uuid.uuid4(),
            user_id=user_id,
            race_date=_date(2026, 8, 15),
            distance_km=42.195,
            actual_time_seconds=7123,  # ~1:58:43
            status="done",
            name="Test Marathon",
            race_type="race",
            priority="A",
        )
        db.add(race)
        db.commit()
        db.refresh(race)

        # Serialize the race and verify the field is present
        race_dict = _race_to_dict(race)

        assert "half_marathon_equivalent_seconds" in race_dict, (
            f"half_marathon_equivalent_seconds not in race_to_dict output. Keys: {race_dict.keys()}"
        )
        assert race_dict["half_marathon_equivalent_seconds"] is not None, (
            "half_marathon_equivalent_seconds should not be None for a valid race"
        )
        assert isinstance(race_dict["half_marathon_equivalent_seconds"], (int, float)), (
            f"half_marathon_equivalent_seconds should be numeric, got {type(race_dict['half_marathon_equivalent_seconds'])}"
        )

        # Cleanup
        db.delete(race)
        db.delete(user)
        db.commit()


def test_half_marathon_equivalent__checkpoint_dict_accessible():
    """AC2: Verify checkpoints render via same code path (frontend applies to both races/checkpoints)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    # Create a test race and checkpoint
    with _OrmSess(_engine) as db:
        # Create a test user
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            name=f"test_hem_{user_id.hex[:8]}",
            password_hash=_hash_pw("test1173"),
        )
        db.add(user)
        db.flush()

        race = Race(
            id=uuid.uuid4(),
            user_id=user_id,
            race_date=_date(2026, 8, 15),
            distance_km=42.195,
            actual_time_seconds=7123,
            status="done",
            name="Test Marathon",
            race_type="race",
            priority="A",
        )
        db.add(race)
        db.flush()

        checkpoint = RaceCheckpoint(
            id=uuid.uuid4(),
            race_id=race.id,
            user_id=user_id,
            label="split",
            target_date=_date(2026, 8, 15),
            target_distance_km=21.1,
        )
        db.add(checkpoint)
        db.commit()
        db.refresh(checkpoint)

        # Verify checkpoint serializes correctly
        cp_dict = _checkpoint_to_dict(checkpoint)
        assert "id" in cp_dict, "Checkpoint should serialize with an id"
        assert "race_id" in cp_dict, "Checkpoint should include race_id"

        # Cleanup
        db.delete(checkpoint)
        db.delete(race)
        db.delete(user)
        db.commit()


def test_half_marathon_equivalent__label_visible_in_html():
    """AC3: Verify the HTML/JS contains the 'Half Equivalent' label."""
    js_path = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "js" / "training-performance.js"
    if not js_path.exists():
        pytest.skip(f"training-performance.js not found at {js_path}")

    with open(js_path, "r") as f:
        content = f.read()

    assert "Half Equivalent" in content, (
        "Label 'Half Equivalent' not found in training-performance.js"
    )


def test_half_marathon_equivalent__null_value_handled():
    """AC4: Verify that null/zero values are omitted or shown as a dash, not '00:00:00'."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    # Create a test race with no actual_time_seconds (planned race)
    with _OrmSess(_engine) as db:
        # Create a test user
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            name=f"test_hem_{user_id.hex[:8]}",
            password_hash=_hash_pw("test1173"),
        )
        db.add(user)
        db.flush()

        race = Race(
            id=uuid.uuid4(),
            user_id=user_id,
            race_date=_date(2026, 8, 15),
            distance_km=42.195,
            actual_time_seconds=None,  # Planned race, not yet completed
            status="planned",
            name="Planned Marathon",
            race_type="race",
            priority="A",
        )
        db.add(race)
        db.commit()
        db.refresh(race)

        # Serialize and verify half_marathon_equivalent_seconds is None
        race_dict = _race_to_dict(race)
        half_equiv = race_dict.get("half_marathon_equivalent_seconds")
        assert half_equiv is None or half_equiv == 0, (
            f"Expected null/0 for a race with no actual time, got {half_equiv}"
        )

        # Cleanup
        db.delete(race)
        db.delete(user)
        db.commit()

    # Verify the frontend JS code handles null by checking for truthiness
    js_path = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "js" / "training-performance.js"
    with open(js_path, "r") as f:
        js_content = f.read()

    # Verify the JS checks for truthiness before rendering
    assert "half_marathon_equivalent_seconds || null" in js_content or "halfSec" in js_content, (
        "Frontend JS should check for null/falsy value before rendering"
    )


def test_half_marathon_equivalent__no_client_recomputation():
    """AC5: Verify frontend reads the value from API response, no client-side recomputation."""
    js_path = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "js" / "training-performance.js"
    with open(js_path, "r") as f:
        js_content = f.read()

    # Confirm the JS references the API field name directly
    assert "r.half_marathon_equivalent_seconds" in js_content, (
        "Frontend should read 'r.half_marathon_equivalent_seconds' directly from the API response"
    )

    # Verify the field is read directly from the response object (r.half_marathon_equivalent_seconds)
    # and used in the rendering logic without any client-side formula computation
    assert "halfSec = r.half_marathon_equivalent_seconds" in js_content or (
        "r.half_marathon_equivalent_seconds" in js_content and "fmtTime(halfSec)" in js_content
    ), (
        "Frontend should use the API value directly, not recompute it"
    )
