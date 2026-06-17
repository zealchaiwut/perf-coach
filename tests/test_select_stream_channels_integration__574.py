"""
Integration tests for issue #574: Select stream channels when merging workout sources.

These tests verify the end-to-end behavior of the channel selection feature,
including the pure select_channels function and the apply_channel_selection caller.

Runs against UAT environment at UAT_BASE_URL.
"""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Workout, StravaActivity, StrydActivity, ActivityStream
from backend.services.channel_select import apply_channel_selection


# Resolve UAT database connection
DATABASE_URL = os.environ.get("DATABASE_URL_UAT") or os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL_UAT or DATABASE_URL not set. "
        "Set env vars before running integration tests."
    )

engine = create_engine(DATABASE_URL)
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:9001"


# ─────────────────────────────────────────────────────────────────────────────
# AC2, AC3, AC4, AC5, AC6: Pure function unit tests (already covered in test_select_stream_channels__574.py)
# These integration tests focus on:
# - AC8: apply_channel_selection persists merged channels + attribution
# - AC10: Feature only runs when both source streams exist
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_channel_selection_with_both_sources_present():
    """AC8/AC10: apply_channel_selection reads both sources, merges, and persists."""
    with Session(engine) as session:
        # Create a minimal user (assuming one exists; real test would seed)
        from backend.models import User
        user = session.query(User).filter(User.is_active).first()
        if not user:
            pytest.skip("No active user in UAT database for integration test")

        # Create a Strava activity with streams payload
        strava_act = StravaActivity(
            strava_id=999001,
            user_id=user.id,
            activity_date="2026-06-18",
            activity_type="Run",
            name="Test Strava Run",
            streams_payload={
                "time_offset_seconds": [0, 1, 2, 3],
                "heart_rate_bpm": [140.0, 142.0, 141.0, 143.0],
                "latitude": [1.23, 1.2301, 1.2302, 1.2303],
                "longitude": [103.8, 103.8001, 103.8002, 103.8003],
                "altitude_m": [50.0, 51.0, 52.0, 51.0],
            },
        )
        session.add(strava_act)
        session.flush()

        # Create a Stryd activity with streams payload
        stryd_act = StrydActivity(
            stryd_id=999002,
            user_id=user.id,
            activity_date="2026-06-18",
            activity_type="Run",
            name="Test Stryd Run",
            streams_payload={
                "time_offset_seconds": [0, 1, 2],
                "heart_rate_bpm": [139.0, 141.0, 140.0],
                "power_w": [250.0, 255.0, 252.0],
                "cadence_spm": [178.0, 180.0, 179.0],
            },
        )
        session.add(stryd_act)
        session.flush()

        # Create a Workout linked to both sources
        workout = Workout(
            user_id=user.id,
            workout_date="2026-06-18",
            name="Merged Test Workout",
            workout_type="Run",
            strava_activity_pk=strava_act.id,
            stryd_activity_pk=stryd_act.id,
        )
        session.add(workout)
        session.commit()

        # Run apply_channel_selection
        success, reason = apply_channel_selection(workout.id, session)
        assert success, f"apply_channel_selection failed: {reason}"

        # Verify the merged stream was persisted
        merged_stream = (
            session.query(ActivityStream)
            .filter(
                ActivityStream.workout_id == workout.id,
                ActivityStream.source == "merged",
            )
            .first()
        )
        assert merged_stream is not None, "Merged stream not persisted"

        # Verify the merged stream has expected channels and attribution
        assert "power_w" in merged_stream.data_dict
        assert merged_stream.data_dict["power_w"] == [250.0, 255.0, 252.0]

        assert "latitude" in merged_stream.data_dict
        assert "longitude" in merged_stream.data_dict
        assert merged_stream.data_dict["latitude"] == [1.23, 1.2301, 1.2302, 1.2303]

        # Verify channel_attribution map
        assert merged_stream.channel_attribution is not None
        assert merged_stream.channel_attribution["power_w"] == "stryd"
        assert merged_stream.channel_attribution["latitude"] == "strava"
        assert merged_stream.channel_attribution["longitude"] == "strava"

        session.rollback()  # Clean up


def test_apply_channel_selection_fails_when_one_source_missing():
    """AC10: apply_channel_selection returns (False, reason) when a source is missing."""
    with Session(engine) as session:
        from backend.models import User
        user = session.query(User).filter(User.is_active).first()
        if not user:
            pytest.skip("No active user in UAT database for integration test")

        # Create only a Strava activity (no Stryd)
        strava_act = StravaActivity(
            strava_id=999003,
            user_id=user.id,
            activity_date="2026-06-18",
            activity_type="Run",
            name="Strava Only",
            streams_payload={
                "time_offset_seconds": [0, 1, 2],
                "heart_rate_bpm": [140.0, 142.0, 141.0],
            },
        )
        session.add(strava_act)
        session.flush()

        # Create workout with only Strava source
        workout = Workout(
            user_id=user.id,
            workout_date="2026-06-18",
            name="Strava Only Workout",
            workout_type="Run",
            strava_activity_pk=strava_act.id,
            stryd_activity_pk=None,  # No Stryd
        )
        session.add(workout)
        session.commit()

        # Run apply_channel_selection — should fail
        success, reason = apply_channel_selection(workout.id, session)
        assert not success, "apply_channel_selection should fail when a source is missing"
        assert reason is not None
        assert len(reason) > 0

        session.rollback()


def test_apply_channel_selection_fails_when_streams_payload_missing():
    """AC10: apply_channel_selection returns (False, reason) when streams payload is empty."""
    with Session(engine) as session:
        from backend.models import User
        user = session.query(User).filter(User.is_active).first()
        if not user:
            pytest.skip("No active user in UAT database for integration test")

        # Create activities but without streams_payload
        strava_act = StravaActivity(
            strava_id=999004,
            user_id=user.id,
            activity_date="2026-06-18",
            activity_type="Run",
            name="Strava No Streams",
            streams_payload=None,  # No streams
        )
        session.add(strava_act)
        session.flush()

        stryd_act = StrydActivity(
            stryd_id=999005,
            user_id=user.id,
            activity_date="2026-06-18",
            activity_type="Run",
            name="Stryd With Streams",
            streams_payload={
                "time_offset_seconds": [0, 1],
                "power_w": [250.0, 255.0],
            },
        )
        session.add(stryd_act)
        session.flush()

        # Create workout linked to both
        workout = Workout(
            user_id=user.id,
            workout_date="2026-06-18",
            name="Missing Streams Workout",
            workout_type="Run",
            strava_activity_pk=strava_act.id,
            stryd_activity_pk=stryd_act.id,
        )
        session.add(workout)
        session.commit()

        # Run apply_channel_selection — should fail (Strava streams missing)
        success, reason = apply_channel_selection(workout.id, session)
        assert not success, "apply_channel_selection should fail when streams payload is missing"
        assert reason is not None

        session.rollback()
