"""Issue #1697 — window-proportional min_entries in weight_stats().

Before the fix, weight_stats() always passed min_entries=21 regardless of
window_days.  A 7-day window can never hold 21 entries so readable was
permanently False, making consecutive_weeks_behind stuck at 0 in cut_review.py
and the "recalibrate_maintenance" branch unreachable.
"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from backend.models import Base, FuelEntry, User, WeightEntry, WeightTarget
from backend.services.cut_review import get_weekly_review
from backend.services.weight_stats import (
    COVERAGE_THRESHOLD,
    MIN_N_DAYS,
    weight_stats,
)

AS_OF = datetime.date(2026, 7, 30)


# ── helpers ───────────────────────────────────────────────────────────────────


def _new_session(*, with_fuel: bool = False) -> OrmSession:
    tables = [User.__table__, WeightEntry.__table__, WeightTarget.__table__]
    if with_fuel:
        tables.append(FuelEntry.__table__)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=tables)
    return OrmSession(engine)


def _make_user(session: OrmSession) -> User:
    u = User(
        id=uuid.uuid4(),
        name="u",
        is_admin=False,
        is_active=True,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(u)
    session.commit()
    return u


def _add_entry(
    session: OrmSession,
    user_id,
    entry_date: datetime.date,
    weight_kg: float,
) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    session.add(WeightEntry(
        id=uuid.uuid4(),
        user_id=user_id,
        entry_date=entry_date,
        weight_kg=weight_kg,
        created_at=now,
        updated_at=now,
    ))
    session.commit()


def _seed_decline(
    session: OrmSession,
    user_id,
    *,
    days: int,
    weigh_ins: int,
    start_kg: float = 80.0,
    per_day: float = -0.03,
) -> None:
    if weigh_ins <= 0:
        return
    step = max(1, days // weigh_ins)
    for i in range(weigh_ins):
        d = AS_OF - datetime.timedelta(days=(weigh_ins - 1 - i) * step)
        _add_entry(session, user_id, d, round(start_kg + per_day * i, 2))


# ── AC tests ─────────────────────────────────────────────────────────────────


def test_7day_window_with_5_entries_is_readable():
    """7-day window with 5 entries (~71% coverage) is readable after fix."""
    session = _new_session()
    user = _make_user(session)
    for i in range(5):
        _add_entry(session, user.id, AS_OF - datetime.timedelta(days=i), 80.0 - i * 0.05)
    stats = weight_stats(session, user.id, window_days=7, as_of=AS_OF)
    assert stats["readable"] is True, (
        f"Expected readable with 5 entries in 7-day window; got {stats}"
    )
    assert stats["rate_kg_wk"] is not None


def test_7day_window_with_2_entries_is_not_readable():
    """2 entries in a 7-day window is below the proportional floor (~5)."""
    session = _new_session()
    user = _make_user(session)
    _add_entry(session, user.id, AS_OF, 80.0)
    _add_entry(session, user.id, AS_OF - datetime.timedelta(days=6), 80.3)
    stats = weight_stats(session, user.id, window_days=7, as_of=AS_OF)
    assert stats["readable"] is False


def test_30day_window_still_requires_21_entries():
    """Regression: 30-day window keeps the full 21-entry gate."""
    session = _new_session()
    user = _make_user(session)
    _seed_decline(session, user.id, days=30, weigh_ins=20)
    stats = weight_stats(session, user.id, window_days=30, as_of=AS_OF)
    assert stats["entries_used"] == 20
    assert stats["readable"] is False


def test_days_needed_reflects_short_window_minimum():
    """days_needed counts against the proportional window minimum, not global 21."""
    session = _new_session()
    user = _make_user(session)
    for i in range(3):
        _add_entry(session, user.id, AS_OF - datetime.timedelta(days=i * 2), 80.0 - i * 0.05)
    stats = weight_stats(session, user.id, window_days=7, as_of=AS_OF)
    assert stats["readable"] is False
    assert stats["days_needed"] <= 5, (
        f"days_needed={stats['days_needed']} should reflect 7-day window minimum, not 21"
    )


@patch("backend.services.weight_stats.today_bangkok", return_value=AS_OF)
@patch("backend.services.cut_review.today_bangkok", return_value=AS_OF)
def test_consecutive_weeks_behind_reaches_recalibrate_maintenance(_cut_today, _stats_today):
    """recalibrate_maintenance is reachable via the real DB path after the fix.

    Before the fix, weight_stats(window_days=7) was always unreadable so
    consecutive_weeks_behind stayed 0 and the recalibrate branch was dead code.
    """
    session = _new_session(with_fuel=True)
    user = _make_user(session)

    # 21 daily entries; actual rate ~-0.21 kg/wk vs plan -0.35 kg/wk → behind
    for i in range(21):
        day = AS_OF - datetime.timedelta(days=20 - i)
        _add_entry(session, user.id, day, round(80.0 - i * 0.03, 3))

    plan = WeightTarget(
        id=uuid.uuid4(),
        user_id=user.id,
        start_weight_kg=80.0,
        start_date=AS_OF - datetime.timedelta(days=30),
        target_weight_kg=75.0,
        target_date=AS_OF + datetime.timedelta(days=90),
        status="active",
        target_rate_kg_per_week=-0.35,
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(plan)
    session.commit()

    with patch("backend.services.cut_review.get_or_create_settings") as mock_settings:
        mock_settings.return_value = type("S", (), {"deficit_kcal": 300})()
        with patch("backend.services.cut_review.settings_to_dict", return_value={
            "deficit_kcal": 300,
            "weight_kg": 80.0,
            "run_kcal_per_kg_per_km": 1.0,
        }):
            real_execute = session.execute

            def _stub_execute(statement, params=None, **kwargs):
                if "daily_metrics" in str(statement):
                    return MagicMock(fetchall=lambda: [])
                return real_execute(statement, params, **kwargs)

            with patch.object(session, "execute", side_effect=_stub_execute):
                review = get_weekly_review(user.id, as_of_date=AS_OF, db=session)

    assert review["recommendation"] == "recalibrate_maintenance", (
        f"Expected recalibrate_maintenance but got '{review['recommendation']}'. "
        f"Full review: {review}"
    )
