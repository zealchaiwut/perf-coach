"""Tests for issue #399: Explicit exception handling in strava_sync.py.

AC: The broad `except Exception` in sync_strava_activities must either be replaced
with specific exception types or have a comment documenting WHY broad catch is needed.
No bare `# noqa: BLE001` suppression.
"""
import ast
import urllib.error
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend.db import engine
from backend.utils.errors import RateLimited


def _make_user() -> str:
    name = f"ss399_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
            {"n": name},
        ).fetchone()
    return str(row.id)


def _drop_user(uid: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


def _latest_sync_job(uid: str):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT status, error_message FROM sync_jobs "
                "WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"
            ),
            {"uid": uid},
        ).fetchone()


# ── Structural: no noqa suppression ──────────────────────────────────────────

def test_no_noqa_ble001_in_strava_sync():
    """AC: The bare-except suppression comment `# noqa: BLE001` must not exist."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "backend" / "services" / "strava_sync.py"
    content = src.read_text()
    assert "noqa: BLE001" not in content, (
        "strava_sync.py still contains `# noqa: BLE001`. "
        "Remove it and document why broad except is needed, or use specific exception types."
    )


def test_except_exception_has_comment_or_uses_specific_types():
    """AC: The except clause is either specific types OR has a documented reason comment."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "backend" / "services" / "strava_sync.py"
    content = src.read_text()
    lines = content.splitlines()

    except_line_no = None
    for i, line in enumerate(lines):
        if "except Exception" in line:
            except_line_no = i
            break

    if except_line_no is None:
        # No bare except Exception — specific types used (fully acceptable)
        return

    # If bare except Exception exists, the surrounding block (±3 lines) must have a comment
    window = lines[max(0, except_line_no - 3): except_line_no + 4]
    has_comment = any("#" in l for l in window)
    assert has_comment, (
        f"Line {except_line_no + 1}: bare `except Exception` with no documenting comment. "
        "Add a comment explaining why all exceptions must be caught, or use specific types."
    )


# ── Behavioral: specific exception types are handled ─────────────────────────

def test_http_error_marks_job_failed_and_reraises():
    """AC: urllib.error.HTTPError from get_athlete_activities → job.status='failed', re-raises."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        def failing_get(user_id, after_epoch, before_epoch, **kwargs):
            raise urllib.error.HTTPError(
                url="https://strava.com/api/v3/athlete/activities",
                code=500,
                msg="Internal Server Error",
                hdrs=None,  # type: ignore[arg-type]
                fp=None,
            )

        with patch("backend.services.strava_sync.get_athlete_activities", side_effect=failing_get), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            with pytest.raises(urllib.error.HTTPError):
                sync_strava_activities(user_id=uid)

        row = _latest_sync_job(uid)
        assert row is not None
        assert row.status == "failed", f"Expected 'failed', got '{row.status}'"
        assert row.error_message is not None
    finally:
        _drop_user(uid)


def test_url_error_marks_job_failed_and_reraises():
    """AC: urllib.error.URLError (network failure) → job.status='failed', re-raises."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        def failing_get(user_id, after_epoch, before_epoch, **kwargs):
            raise urllib.error.URLError("Connection refused")

        with patch("backend.services.strava_sync.get_athlete_activities", side_effect=failing_get), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            with pytest.raises(urllib.error.URLError):
                sync_strava_activities(user_id=uid)

        row = _latest_sync_job(uid)
        assert row is not None
        assert row.status == "failed"
    finally:
        _drop_user(uid)


def test_rate_limited_marks_job_failed_and_reraises():
    """AC: RateLimited exception → job.status='failed', re-raises."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        def failing_get(user_id, after_epoch, before_epoch, **kwargs):
            raise RateLimited(
                user_message="Strava rate limit exceeded",
                details={"retry_after": 60},
            )

        with patch("backend.services.strava_sync.get_athlete_activities", side_effect=failing_get), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            with pytest.raises(RateLimited):
                sync_strava_activities(user_id=uid)

        row = _latest_sync_job(uid)
        assert row is not None
        assert row.status == "failed"
    finally:
        _drop_user(uid)


def test_value_error_marks_job_failed_and_reraises():
    """AC: ValueError (e.g. token refresh failure) → job.status='failed', re-raises."""
    from backend.services.strava_sync import sync_strava_activities

    uid = _make_user()
    try:
        def failing_get(user_id, after_epoch, before_epoch, **kwargs):
            raise ValueError("No Strava token found for user")

        with patch("backend.services.strava_sync.get_athlete_activities", side_effect=failing_get), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False):
            with pytest.raises(ValueError):
                sync_strava_activities(user_id=uid)

        row = _latest_sync_job(uid)
        assert row is not None
        assert row.status == "failed"
    finally:
        _drop_user(uid)
