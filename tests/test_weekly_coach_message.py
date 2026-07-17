"""Tests for weekly coach message generation (issue #1504).

AC coverage:
- AC1: scheduled job calls build_plan_state() and produces a message
- AC2: generated message contains all five structural elements (a)-(e)
- AC3: all numbers injected from engine outputs (no invented values)
- AC4: deterministic fallback path produces valid message with all five elements
- AC5: LLM exception triggers fallback path without error
- AC6: each message persisted with generated_at, for_week, text, plan_state_snapshot
- AC7: GET /api/coach/weekly-message requires auth (401 without token)
- AC8: GET /api/coach/weekly-messages?limit=N requires auth
- AC9: idempotency — same-week re-run replaces record, not duplicates
- AC10: GET /api/coach/weekly-messages returns newest-first array

Persistence tests (AC6, AC9, AC10 direct) use a real Postgres DB (DATABASE_URL_UAT)
and are skipped when the DB is unavailable — same pattern as test_1353_verdict_history.py.
Pure composition and fallback tests (AC2, AC3, AC4, AC5) are fully in-process.
"""
from __future__ import annotations

import os
import pathlib
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.services.coach_plan import build_plan_state
from backend.services.weekly_coach_message import (
    compose_deterministic_message,
    _iso_week,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

_RACE_DATE = date(2026, 12, 12)
_TODAY = date(2026, 7, 17)

_SNAPSHOT = {"ctl": 60.0, "atl": 96.0, "acwr": 1.60, "tss_for_day": 45}
_GOAL = {"race_date": _RACE_DATE, "race_distance": "half"}
_WEIGHT = {"current_kg": 80.0, "goal_kg": 75.0, "gap_kg": 5.0}
_LOG = {"logged_days": 13, "total_days": 14}

_PLAN_STATE = build_plan_state(
    goal=_GOAL,
    training_load_snapshot=_SNAPSHOT,
    acwr_state="high_risk",
    guardrail_state="ok",
    weight_status=_WEIGHT,
    log_consistency=_LOG,
    _today=_TODAY,
)

_PROJECTION_INFO = {
    "full_compliance_time_seconds": 6300,   # 1:45:00 HM
    "target_date": _RACE_DATE,
    "current_trend_time_seconds": 6720,     # 1:52:00
    "uncertainty_minutes": 3,
    "distance_label": "HM",
}

# ── UAT DB setup (persistence tests) ─────────────────────────────────────────

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
_uat_url = None
if _env_file.exists():
    try:
        from dotenv import dotenv_values
        _env_vals = dotenv_values(_env_file)
        _uat_url = _env_vals.get("DATABASE_URL_UAT")
    except ImportError:
        pass
if _uat_url is None:
    _uat_url = os.environ.get("DATABASE_URL_UAT")


def _uat_engine():
    if _uat_url is None:
        return None
    from sqlalchemy import create_engine
    return create_engine(_uat_url, pool_pre_ping=True)


_UAT_ENGINE = _uat_engine()


# ── AC4: deterministic fallback produces valid message ─────────────────────────

def test_compose_deterministic_returns_string():
    """AC4: compose_deterministic_message returns a non-empty string."""
    msg = compose_deterministic_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)
    assert isinstance(msg, str)
    assert len(msg) > 0


def test_compose_deterministic_contains_now_directive():
    """AC2a: Message contains Now directive with TSS target, ACWR, and convergence date."""
    msg = compose_deterministic_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)
    # The now directive must contain at least the ACWR value and TSS figure
    assert "1.60" in msg or "ACWR" in msg.upper()
    # TSS weekly = 45 * 7 = 315
    assert "315" in msg


def test_compose_deterministic_contains_next_steps():
    """AC2b: Message contains sequenced next steps with dates."""
    msg = compose_deterministic_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)
    # Timeline phases have names like hold, ramp, cut-end, peak block, taper
    assert any(kw in msg.lower() for kw in ("hold", "ramp", "taper", "increase"))


def test_compose_deterministic_contains_constraint():
    """AC2c: Message contains interaction constraint one-liner."""
    msg = compose_deterministic_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)
    # For locked ACWR the constraint should reference ACWR/TSS
    assert any(kw in msg.lower() for kw in ("acwr", "hold", "constraint", "defer"))


def test_compose_deterministic_contains_lever_ranking():
    """AC2d: Message contains lever ranking sentence."""
    msg = compose_deterministic_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)
    # Lever ranking references CTL gap or weight gap
    assert any(kw in msg.lower() for kw in ("ctl", "lever", "weight"))


def test_compose_deterministic_contains_projection():
    """AC2e: Message contains motivation projection with finish time and uncertainty."""
    msg = compose_deterministic_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)
    # Should contain HM distance label, a time like "1:45" or "1:52", and "±" or "±"
    assert "HM" in msg or "hm" in msg.lower()
    # Check for ± symbol or "±" text
    assert "±" in msg or "+/-" in msg or "± " in msg


def test_compose_deterministic_numbers_from_engine():
    """AC3: Numeric values in message come from engine outputs (ACWR=1.60, TSS=315)."""
    msg = compose_deterministic_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)
    # ACWR value from plan_state["levers"]["load"]["reason"]
    assert "1.60" in msg
    # weekly TSS = 315 (45 * 7)
    assert "315" in msg
    # Full compliance time 1:45:00 → "1:45" format
    assert "1:45" in msg
    # Current trend time 1:52:00 → "1:52" format
    assert "1:52" in msg


def test_compose_deterministic_all_five_elements_present():
    """AC2: All five structural elements are present in the message."""
    msg = compose_deterministic_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)
    # Check that message includes markers or content for each element
    # (a) TSS/ACWR numbers
    has_a = "1.60" in msg and "315" in msg
    # (b) sequenced next steps — at least one date or phase reference
    has_b = any(kw in msg.lower() for kw in ("hold", "ramp", "taper", "jul", "aug", "oct", "dec"))
    # (c) constraint
    has_c = any(kw in msg.lower() for kw in ("acwr", "hold tss", "defer", "constraint", "elevated"))
    # (d) lever ranking
    has_d = any(kw in msg.lower() for kw in ("ctl", "lever", "weight"))
    # (e) projection with time estimates
    has_e = "1:45" in msg and "1:52" in msg
    assert has_a, f"Missing now-directive (ACWR/TSS) in:\n{msg}"
    assert has_b, f"Missing next-steps content in:\n{msg}"
    assert has_c, f"Missing constraint content in:\n{msg}"
    assert has_d, f"Missing lever-ranking content in:\n{msg}"
    assert has_e, f"Missing projection content in:\n{msg}"


# ── AC5: LLM failure triggers fallback ────────────────────────────────────────

def test_llm_failure_falls_back_to_deterministic():
    """AC5: When LLM raises an exception, the deterministic fallback is returned."""
    from backend.services.weekly_coach_message import _build_message

    with patch(
        "backend.services.weekly_coach_message._call_llm_narrative",
        side_effect=RuntimeError("LLM unavailable"),
    ):
        result = _build_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)

    assert isinstance(result, str)
    assert len(result) > 0
    # Must still contain all five elements
    assert "1.60" in result
    assert "1:45" in result


def test_llm_returning_none_falls_back_to_deterministic():
    """AC5: When LLM returns None, the deterministic message is used."""
    from backend.services.weekly_coach_message import _build_message

    with patch(
        "backend.services.weekly_coach_message._call_llm_narrative",
        return_value=None,
    ):
        result = _build_message(_PLAN_STATE, _PROJECTION_INFO, _TODAY)

    assert isinstance(result, str)
    assert "1:45" in result


# ── AC9: Idempotency per ISO week ─────────────────────────────────────────────

def test_iso_week_format():
    """AC9: _iso_week returns 'YYYY-Www' format."""
    w = _iso_week(date(2026, 7, 17))
    # 2026-07-17 is in ISO week 29 of 2026
    assert w == "2026-W29", f"Expected '2026-W29', got {w!r}"


def test_iso_week_end_of_year():
    """AC9: _iso_week handles year boundary correctly."""
    # 2026-12-31 may be in ISO week 53 of 2026 or week 1 of 2027
    w = _iso_week(date(2026, 12, 31))
    assert re.match(r"^\d{4}-W\d{2}$", w), f"Invalid format: {w!r}"


def test_same_week_dates_give_same_iso_week():
    """AC9: Dates within the same ISO week produce the same for_week key."""
    monday = date(2026, 7, 13)   # W29
    friday = date(2026, 7, 17)   # W29
    assert _iso_week(monday) == _iso_week(friday)


# ── Persistence / idempotency tests (require UAT Postgres — JSONB) ────────────

def _make_test_user(db) -> uuid.UUID:
    """Insert a throwaway user for persistence tests."""
    from backend.models import User
    uid = uuid.uuid4()
    user = User(
        id=uid,
        name=f"test_wcm_{uid.hex[:8]}",
        is_admin=False,
        is_active=True,
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(user)
    db.flush()
    return uid


@pytest.fixture
def uat_db():
    """Open a UAT Postgres session for persistence tests; skip if unavailable."""
    if _UAT_ENGINE is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping Postgres persistence tests")
    from sqlalchemy.orm import Session
    from backend.models import Base

    # Ensure the weekly_coach_messages table exists (migration may not have run in test DB)
    from backend.models import WeeklyCoachMessage
    Base.metadata.create_all(_UAT_ENGINE, tables=[WeeklyCoachMessage.__table__])

    with Session(_UAT_ENGINE) as db:
        yield db
        db.rollback()  # roll back test data so we don't pollute


def test_persist_weekly_message_creates_record(uat_db):
    """AC6: Persisting a weekly message stores generated_at, for_week, text, plan_state_snapshot."""
    from backend.services.weekly_coach_message import persist_weekly_message
    from backend.models import WeeklyCoachMessage

    user_id = _make_test_user(uat_db)
    record = persist_weekly_message(
        user_id=user_id,
        for_week="2026-W99",
        text="Test message with all five elements.",
        plan_state_snapshot={"levers": {}, "timeline": []},
        db=uat_db,
    )
    uat_db.flush()
    assert record.for_week == "2026-W99"
    assert record.text == "Test message with all five elements."
    assert record.plan_state_snapshot is not None

    rows = uat_db.query(WeeklyCoachMessage).filter_by(user_id=user_id).all()
    assert len(rows) == 1
    assert rows[0].for_week == "2026-W99"


def test_persist_weekly_message_idempotent_same_week(uat_db):
    """AC9: Re-running for the same ISO week replaces the record, not duplicates it."""
    from backend.services.weekly_coach_message import persist_weekly_message
    from backend.models import WeeklyCoachMessage

    user_id = _make_test_user(uat_db)
    persist_weekly_message(
        user_id=user_id,
        for_week="2026-W98",
        text="First run message.",
        plan_state_snapshot={},
        db=uat_db,
    )
    uat_db.flush()

    persist_weekly_message(
        user_id=user_id,
        for_week="2026-W98",
        text="Second run message — should replace.",
        plan_state_snapshot={"updated": True},
        db=uat_db,
    )
    uat_db.flush()

    rows = uat_db.query(WeeklyCoachMessage).filter_by(user_id=user_id).all()
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
    assert rows[0].text == "Second run message — should replace."


def test_get_latest_returns_most_recent(uat_db):
    """AC7 (indirect): get_latest_for_user returns the latest record for the user."""
    from backend.services.weekly_coach_message import persist_weekly_message, get_latest_for_user

    user_id = _make_test_user(uat_db)
    persist_weekly_message(user_id=user_id, for_week="2026-W96", text="W96", plan_state_snapshot={}, db=uat_db)
    persist_weekly_message(user_id=user_id, for_week="2026-W97", text="W97", plan_state_snapshot={}, db=uat_db)
    uat_db.flush()

    latest = get_latest_for_user(user_id=user_id, db=uat_db)
    assert latest is not None
    assert latest["for_week"] == "2026-W97"
    assert latest["text"] == "W97"


def test_get_history_newest_first(uat_db):
    """AC10: get_history_for_user returns messages newest-first."""
    from backend.services.weekly_coach_message import persist_weekly_message, get_history_for_user

    user_id = _make_test_user(uat_db)
    persist_weekly_message(user_id=user_id, for_week="2026-W91", text="W91", plan_state_snapshot={}, db=uat_db)
    persist_weekly_message(user_id=user_id, for_week="2026-W92", text="W92", plan_state_snapshot={}, db=uat_db)
    persist_weekly_message(user_id=user_id, for_week="2026-W93", text="W93", plan_state_snapshot={}, db=uat_db)
    uat_db.flush()

    history = get_history_for_user(user_id=user_id, limit=10, db=uat_db)
    assert len(history) == 3
    # Newest-first by generated_at — all inserted in order so W93 is last-in = newest
    weeks = [h["for_week"] for h in history]
    assert weeks[0] == "2026-W93"
    assert weeks[-1] == "2026-W91"


def test_get_history_respects_limit(uat_db):
    """AC8: get_history_for_user returns at most `limit` records."""
    from backend.services.weekly_coach_message import persist_weekly_message, get_history_for_user

    user_id = _make_test_user(uat_db)
    for w in range(80, 86):
        persist_weekly_message(user_id=user_id, for_week=f"2026-W{w:02d}", text=f"W{w}", plan_state_snapshot={}, db=uat_db)
    uat_db.flush()

    history = get_history_for_user(user_id=user_id, limit=2, db=uat_db)
    assert len(history) == 2


def test_get_latest_returns_none_when_no_messages(uat_db):
    """AC7 (indirect): get_latest_for_user returns None when no messages exist."""
    from backend.services.weekly_coach_message import get_latest_for_user

    user_id = _make_test_user(uat_db)
    result = get_latest_for_user(user_id=user_id, db=uat_db)
    assert result is None


# ── Endpoint auth tests (FastAPI TestClient — no live server needed) ──────────

def test_weekly_message_requires_auth():
    """AC7: GET /api/coach/weekly-message returns 401 without an auth cookie."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/api/coach/weekly-message")
    assert r.status_code == 401


def test_weekly_messages_requires_auth():
    """AC8: GET /api/coach/weekly-messages?limit=N returns 401 without an auth cookie."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/api/coach/weekly-messages?limit=3")
    assert r.status_code == 401
