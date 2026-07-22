"""Tests for issue #1525 — persist_daily_message must use ON CONFLICT upsert.

AC1: persist_daily_message uses INSERT … ON CONFLICT (user_id, for_date) DO UPDATE
     instead of the old select-then-insert pattern that races under concurrency.
AC2: A second concurrent writer for the same (user_id, for_date) converges
     without raising an IntegrityError.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date, datetime, timezone

import pytest

# ── Engine setup (mirrors test_weekly_coach_message.py) ───────────────────────

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
_uat_url = None
if _env_file.exists():
    try:
        from dotenv import dotenv_values
        _uat_url = dotenv_values(_env_file).get("DATABASE_URL_UAT")
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


@pytest.fixture
def uat_db():
    """Postgres session that rolls back after each test."""
    if _UAT_ENGINE is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping Postgres persistence tests")
    from sqlalchemy.orm import Session
    from backend.models import Base, WeeklyCoachMessage
    Base.metadata.create_all(_UAT_ENGINE, tables=[WeeklyCoachMessage.__table__])
    with Session(_UAT_ENGINE) as db:
        yield db
        try:
            db.rollback()
        except Exception:
            pass


# ── AC1: source-level guarantee that ON CONFLICT is used ──────────────────────

def test_persist_daily_message_uses_on_conflict_do_update():
    """AC1: persist_daily_message must call on_conflict_do_update, not select-then-insert."""
    import inspect
    from backend.services import weekly_coach_message as wcm

    source = inspect.getsource(wcm.persist_daily_message)

    assert "on_conflict_do_update" in source, (
        "persist_daily_message must use on_conflict_do_update to be race-safe"
    )
    # The old select-first guard must no longer exist
    assert "filter_by(user_id=user_id, for_date=for_date)" not in source, (
        "persist_daily_message must not query before inserting (select-then-insert anti-pattern)"
    )


# ── AC2: second writer after first committed does not raise ───────────────────

def test_persist_daily_message_second_writer_no_integrity_error(uat_db):
    """AC2: When a row was committed by another session, a subsequent persist_daily_message
    call converges via ON CONFLICT without raising IntegrityError."""
    from sqlalchemy.orm import Session
    from sqlalchemy import text as sa_text
    from backend.models import User, WeeklyCoachMessage
    from backend.services.weekly_coach_message import persist_daily_message

    user_id = uuid.uuid4()
    target_date = date(2026, 3, 14)

    # Commit both user and first row in a separate session (the "winning" writer)
    with Session(_UAT_ENGINE) as s:
        s.add(User(
            id=user_id,
            name=f"race_{user_id.hex[:8]}",
            is_admin=False,
            is_active=True,
            created_at=datetime.now(tz=timezone.utc),
        ))
        s.flush()
        s.add(WeeklyCoachMessage(
            user_id=user_id,
            for_week="2026-W11",
            for_date=target_date,
            text="First writer",
            generated_at=datetime.now(tz=timezone.utc),
        ))
        s.commit()

    try:
        # uat_db is a fresh session — it has no knowledge of the committed row above.
        # Old code: SELECT finds the row → UPDATE (works sequentially but races
        #   when two sessions both SELECT before either inserts).
        # New code: ON CONFLICT DO UPDATE → race-safe regardless of ordering.
        result = persist_daily_message(
            user_id=user_id,
            for_date=target_date,
            text="Second writer via ON CONFLICT",
            plan_state_snapshot=None,
            db=uat_db,
        )
        uat_db.flush()

        assert result is not None
        assert result.text == "Second writer via ON CONFLICT"

        rows = uat_db.query(WeeklyCoachMessage).filter_by(user_id=user_id).all()
        assert len(rows) == 1, f"Expected 1 row after upsert, got {len(rows)}"

    finally:
        # Remove committed rows so they don't leak across test runs
        with Session(_UAT_ENGINE) as cleanup:
            cleanup.execute(
                sa_text("DELETE FROM weekly_coach_messages WHERE user_id = :uid"),
                {"uid": user_id},
            )
            cleanup.execute(
                sa_text("DELETE FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
            cleanup.commit()
