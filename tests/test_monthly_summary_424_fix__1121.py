"""Tests for issue #1121: Monthly summary 424 trigger mismatches AC description.

AC coverage:
- AC1: Docstring for the 424 case describes "no training sessions found for the
       requested month" not "no weekly aggregation data".
- AC2: HTTP 424 is returned when there are no workout/training session records
       for the queried month, independent of weekly aggregation state.
- AC3: Monthly endpoint does not depend on or call the weekly summary endpoint;
       its 424 logic is self-contained.
- AC4: 424 response body includes a message referencing "training sessions" /
       "no training sessions" and NOT "weekly aggregation data".
- AC5: Months with at least one training session return 200.
"""

import inspect
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

TODAY = date.today()
MONTH_START = TODAY.replace(day=1)


# ── Helpers shared with #1056 tests ──────────────────────────────────────────

def _make_user(uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    return u


def _make_workout(user_id, workout_date, tss=60.0, distance_km=10.0):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.user_id = user_id
    w.workout_date = workout_date
    w.tss = tss
    w.distance_km = distance_km
    w.endurance_signal = None
    w.speed_signal = None
    return w


def _make_fitness_series(tsb_end=5.0, ctl_start=35.0, ctl_end=42.0, days=30):
    result = []
    for i in range(days):
        day = MONTH_START + timedelta(days=i)
        ctl = ctl_start + (ctl_end - ctl_start) * i / max(days - 1, 1)
        tsb = tsb_end - (days - 1 - i) * 2.0
        atl = ctl - tsb
        result.append({"date": day, "tss": 60, "ctl": round(ctl, 2),
                        "atl": round(atl, 2), "tsb": round(tsb, 2)})
    return result


def _empty_db_mock(user):
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    athlete = MagicMock()
    athlete.id = user.id
    mock_db.get.return_value = athlete

    empty_query = MagicMock()
    empty_query.filter.return_value = empty_query
    empty_query.order_by.return_value = empty_query
    empty_query.all.return_value = []
    mock_db.query.return_value = empty_query
    return mock_db


def _workout_db_mock(user, workouts):
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    athlete = MagicMock()
    athlete.id = user.id
    mock_db.get.return_value = athlete

    def _query_side_effect(*args):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        model_name = getattr(args[0], "__name__", str(args[0])) if args else ""
        if "Workout" in model_name:
            q.all.return_value = workouts
        else:
            q.all.return_value = []
        return q

    mock_db.query.side_effect = _query_side_effect
    return mock_db


# ── AC1: docstring describes correct trigger ──────────────────────────────────

def test_docstring_does_not_mention_weekly_aggregation():
    """AC1: Docstring no longer says 'weekly aggregation data'."""
    from backend.main import get_athlete_monthly_summary
    doc = inspect.getdoc(get_athlete_monthly_summary) or ""
    assert "weekly aggregation" not in doc.lower(), (
        "Docstring must not reference 'weekly aggregation' as the 424 trigger"
    )


def test_docstring_mentions_training_sessions_for_424():
    """AC1: Docstring for 424 case mentions training sessions."""
    from backend.main import get_athlete_monthly_summary
    doc = inspect.getdoc(get_athlete_monthly_summary) or ""
    assert "training session" in doc.lower() or "no training" in doc.lower(), (
        "Docstring must describe the 424 trigger as 'no training sessions found'"
    )


# ── AC2: 424 triggered by empty workouts, independent of weekly endpoint ──────

def test_424_returned_when_no_workouts():
    """AC2: HTTP 424 is returned when there are no workout records for the month."""
    from fastapi import HTTPException
    from backend.main import get_athlete_monthly_summary

    user = _make_user()
    mock_db = _empty_db_mock(user)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.get_snapshot_series", return_value=[]),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._summary_cache_get", return_value=None),
        patch("backend.main._summary_cache_get_latest", return_value=None),
        patch("backend.main._summary_signature", return_value="sig"),
    ):
        MockSession.return_value = mock_db
        with pytest.raises(HTTPException) as exc:
            get_athlete_monthly_summary(str(user.id), user, "2025-01")

    assert exc.value.status_code == 424


# ── AC3: monthly endpoint does not call weekly summary endpoint ───────────────

def test_monthly_endpoint_does_not_call_weekly_summary():
    """AC3: The monthly endpoint's 424 path does not invoke get_athlete_weekly_summary."""
    from backend.main import get_athlete_monthly_summary, get_athlete_weekly_summary
    import backend.main as main_module

    user = _make_user()
    mock_db = _empty_db_mock(user)

    weekly_called = []

    original_weekly = get_athlete_weekly_summary
    def spy_weekly(*args, **kwargs):
        weekly_called.append(True)
        return original_weekly(*args, **kwargs)

    from fastapi import HTTPException

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.get_snapshot_series", return_value=[]),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._summary_cache_get", return_value=None),
        patch("backend.main._summary_cache_get_latest", return_value=None),
        patch("backend.main._summary_signature", return_value="sig"),
        patch.object(main_module, "get_athlete_weekly_summary", side_effect=spy_weekly),
    ):
        MockSession.return_value = mock_db
        try:
            get_athlete_monthly_summary(str(user.id), user, "2025-01")
        except HTTPException:
            pass

    assert not weekly_called, "Monthly endpoint must not call get_athlete_weekly_summary"


# ── AC4: 424 response body references training sessions, not weekly aggregation

def test_424_detail_does_not_mention_weekly_aggregation():
    """AC4: 424 error body does not say 'weekly aggregation data'."""
    from fastapi import HTTPException
    from backend.main import get_athlete_monthly_summary

    user = _make_user()
    mock_db = _empty_db_mock(user)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.get_snapshot_series", return_value=[]),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._summary_cache_get", return_value=None),
        patch("backend.main._summary_cache_get_latest", return_value=None),
        patch("backend.main._summary_signature", return_value="sig"),
    ):
        MockSession.return_value = mock_db
        with pytest.raises(HTTPException) as exc:
            get_athlete_monthly_summary(str(user.id), user, "2025-01")

    detail = exc.value.detail
    detail_str = detail if isinstance(detail, str) else str(detail)
    assert "weekly aggregation" not in detail_str.lower(), (
        "424 detail must not mention 'weekly aggregation data'"
    )


def test_424_detail_mentions_training_sessions():
    """AC4: 424 error body references 'training sessions'."""
    from fastapi import HTTPException
    from backend.main import get_athlete_monthly_summary

    user = _make_user()
    mock_db = _empty_db_mock(user)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.get_snapshot_series", return_value=[]),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._summary_cache_get", return_value=None),
        patch("backend.main._summary_cache_get_latest", return_value=None),
        patch("backend.main._summary_signature", return_value="sig"),
    ):
        MockSession.return_value = mock_db
        with pytest.raises(HTTPException) as exc:
            get_athlete_monthly_summary(str(user.id), user, "2025-01")

    detail = exc.value.detail
    detail_str = detail if isinstance(detail, str) else str(detail)
    assert "training session" in detail_str.lower() or "no training" in detail_str.lower(), (
        "424 detail must reference 'training sessions' to describe the trigger"
    )


# ── AC5: 200 returned when at least one workout exists ───────────────────────

def test_200_returned_when_workouts_exist():
    """AC5: Months with at least one training session return HTTP 200."""
    import json
    from fastapi.responses import JSONResponse
    from backend.main import get_athlete_monthly_summary

    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=5))]
    mock_db = _workout_db_mock(user, workouts)
    fitness = _make_fitness_series()

    _default_guardrail = {"guardrail_state": "ok", "guardrail_message": ""}

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.get_snapshot_series", return_value=fitness),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main.get_guardrail_result", return_value=_default_guardrail),
    ):
        MockSession.return_value = mock_db
        result = get_athlete_monthly_summary(str(user.id), user, None)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 200
    body = json.loads(result.body)
    assert "session_count" in body
    assert body["session_count"] >= 1
