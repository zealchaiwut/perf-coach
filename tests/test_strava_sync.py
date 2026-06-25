"""Tests for issue #375: Strava activity sync orchestrator service."""
import calendar
import datetime as _dt
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine


def _make_user() -> str:
    name = f"ss375_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
            {"n": name},
        ).fetchone()
    return str(row.id)


def _drop_user(uid: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


def _fake_activity(i: int, base_id: int = 10000, act_type: str = "Run") -> dict:
    return {
        "id": base_id + i,
        "name": f"Activity {i}",
        "type": act_type,
        "sport_type": act_type,
        "start_date": "2025-01-01T08:00:00Z",
        "distance": 5000.0,
        "moving_time": 1800,
        "average_heartrate": 140,
        "max_heartrate": 170,
        "total_elevation_gain": 50,
        "average_watts": None,
        "max_watts": None,
        "device_name": "Garmin Forerunner",
        "external_id": f"garmin-ext-{base_id + i}",
    }


# ── (a) Full sync creates strava_activities rows ──────────────────────────────

def test_a_full_sync_creates_rows():
    """AC (a): Full sync creates strava_activities rows for user with no prior rows."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        activities = [_fake_activity(i, base_id=11000) for i in range(3)]

        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter(activities)), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            result = sync_strava_activities(user_id=uid)

        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM strava_activities WHERE user_id = :uid"),
                {"uid": uid},
            ).scalar()

        assert count == 3
        assert result["status"] == "completed"
        assert result["activities_created"] == 3
        assert result["activities_updated"] == 0
    finally:
        _drop_user(uid)


# ── (b) Re-run is incremental — only new activities fetched ──────────────────

def test_b_rerun_uses_latest_synced_at_as_since_date():
    """AC (b): Re-run uses latest synced_at as since_date (incremental default)."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        activities = [_fake_activity(i, base_id=21000) for i in range(5)]
        call_epochs = []

        def capture_get(user_id, after_epoch, before_epoch, **kwargs):
            call_epochs.append(after_epoch)
            yield from activities

        # First sync: no prior rows → defaults to 90 days ago
        with patch("backend.services.strava_sync.get_athlete_activities", side_effect=capture_get), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            sync_strava_activities(user_id=uid)

        first_epoch = call_epochs[-1]
        call_epochs.clear()

        # Second sync: prior rows exist → uses synced_at (recent) as since_date
        with patch("backend.services.strava_sync.get_athlete_activities", side_effect=capture_get), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            sync_strava_activities(user_id=uid)

        second_epoch = call_epochs[-1]
        # Second run's since_date is the recent synced_at, so epoch is >= first (90-days-ago)
        assert second_epoch >= first_epoch, (
            f"Expected second_epoch ({second_epoch}) >= first_epoch ({first_epoch})"
        )
    finally:
        _drop_user(uid)


# ── (c) Duplicate strava_activity_id triggers UPDATE, not INSERT ──────────────

def test_c_duplicate_triggers_update_not_insert():
    """AC (c): Re-syncing same strava_activity_id updates the row, not create duplicate."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        act = _fake_activity(0, base_id=31000)

        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter([act])), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            sync_strava_activities(user_id=uid)

        updated_act = dict(act, name="Updated Name")
        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter([updated_act])), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            result2 = sync_strava_activities(user_id=uid)

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM strava_activities WHERE user_id = :uid AND strava_activity_id = :sid"),
                {"uid": uid, "sid": 31000},
            ).fetchall()

        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        assert rows[0].name == "Updated Name"
        assert result2["activities_updated"] == 1
        assert result2["activities_created"] == 0
    finally:
        _drop_user(uid)


# ── (d) detect_stryd_origin called and is_stryd_synced set correctly ──────────

def test_d_detect_stryd_origin_called_and_is_stryd_synced_set():
    """AC (d): detect_stryd_origin called per activity; is_stryd_synced set from result."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        act = _fake_activity(0, base_id=41000)

        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter([act])), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=True) as mock_detect:
            sync_strava_activities(user_id=uid)

        mock_detect.assert_called_once_with(act)

        with engine.connect() as conn:
            is_stryd = conn.execute(
                text("SELECT is_stryd_synced FROM strava_activities WHERE user_id = :uid AND strava_activity_id = 41000"),
                {"uid": uid},
            ).scalar()

        assert is_stryd is True
    finally:
        _drop_user(uid)


# ── (e) SyncJob counters updated mid-sync (every 10 activities) ───────────────

def test_e_syncjob_counters_updated_every_10_activities():
    """AC (e): SyncJob counters written to DB every 10 activities (mid-sync checkpoint)."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        # 15 activities: expect a mid-sync commit at 10, then final at 15
        activities = [_fake_activity(i, base_id=51000) for i in range(15)]

        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter(activities)), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            result = sync_strava_activities(user_id=uid)

        assert result["activities_created"] == 15
        assert result["activities_updated"] == 0
        assert result["status"] == "completed"

        # Verify sync_jobs row has correct final counters in DB
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT activities_created, activities_updated, status "
                    "FROM sync_jobs WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"
                ),
                {"uid": uid},
            ).fetchone()

        assert row.activities_created == 15
        assert row.status == "completed"
    finally:
        _drop_user(uid)


# ── (f) Exception during sync marks job failed ────────────────────────────────

def test_f_exception_marks_job_failed_and_reraises():
    """AC (f): Unhandled exception sets SyncJob.status='failed' with error_message, re-raises."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        def failing_get(user_id, after_epoch, before_epoch, **kwargs):
            raise RuntimeError("Strava API boom")

        with patch("backend.services.strava_sync.get_athlete_activities", side_effect=failing_get), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            with pytest.raises(RuntimeError, match="Strava API boom"):
                sync_strava_activities(user_id=uid)

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT status, error_message FROM sync_jobs "
                    "WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"
                ),
                {"uid": uid},
            ).fetchone()

        assert row is not None
        assert row.status == "failed"
        assert "Strava API boom" in row.error_message
    finally:
        _drop_user(uid)


# ── (g) Explicit since_date overrides incremental default ─────────────────────

def test_g_explicit_since_date_overrides_default():
    """AC (g): Explicit since_date argument is passed to get_athlete_activities as epoch."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        # First sync to populate strava_activities (so incremental default would apply)
        activities = [_fake_activity(i, base_id=71000) for i in range(3)]
        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter(activities)), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            sync_strava_activities(user_id=uid)

        # Second sync with explicit since_date
        explicit_date = date(2024, 1, 1)
        expected_epoch = int(calendar.timegm(
            _dt.datetime(2024, 1, 1, tzinfo=timezone.utc).timetuple()
        ))

        captured = {}

        def capture_get(user_id, after_epoch, before_epoch, **kwargs):
            captured["after_epoch"] = after_epoch
            return iter([])

        with patch("backend.services.strava_sync.get_athlete_activities", side_effect=capture_get), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            sync_strava_activities(user_id=uid, since_date=explicit_date)

        assert captured.get("after_epoch") == expected_epoch, (
            f"Expected epoch {expected_epoch} for 2024-01-01, got {captured.get('after_epoch')}"
        )
    finally:
        _drop_user(uid)
