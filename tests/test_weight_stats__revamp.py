"""Pass 1 — canonical weight_stats rate shared by chart stats and cut review."""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from backend.models import Base, FuelEntry, User, WeightEntry, WeightTarget
from backend.services.body_composition import compute_composition_trend
from backend.services.cut_review import compute_cut_recommendation
from backend.services.cut_review import get_weekly_review
from backend.services.weight_stats import (
    COVERAGE_THRESHOLD,
    MIN_N_DAYS,
    weight_stats,
)

AS_OF = datetime.date(2026, 7, 30)


def _new_session(*, with_fuel: bool = False) -> OrmSession:
    tables = [User.__table__, WeightEntry.__table__, WeightTarget.__table__]
    if with_fuel:
        tables.append(FuelEntry.__table__)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=tables)
    return OrmSession(engine)


def _make_user(session: OrmSession, name: str = "u") -> User:
    u = User(
        id=uuid.uuid4(),
        name=name,
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
    *,
    body_fat_pct: float | None = None,
) -> WeightEntry:
    now = datetime.datetime.now(datetime.timezone.utc)
    we = WeightEntry(
        id=uuid.uuid4(),
        user_id=user_id,
        entry_date=entry_date,
        weight_kg=weight_kg,
        body_fat_pct=body_fat_pct,
        created_at=now,
        updated_at=now,
    )
    session.add(we)
    session.commit()
    return we


def _seed_decline(
    session: OrmSession,
    user_id,
    *,
    days: int,
    weigh_ins: int,
    start_kg: float = 80.0,
    per_day: float = -0.03,
    as_of: datetime.date = AS_OF,
) -> None:
    """Spread ``weigh_ins`` entries evenly across ``days`` ending on ``as_of``."""
    if weigh_ins <= 0:
        return
    step = max(1, days // weigh_ins)
    for i in range(weigh_ins):
        d = as_of - datetime.timedelta(days=(weigh_ins - 1 - i) * step)
        _add_entry(session, user_id, d, round(start_kg + per_day * i, 2))


def _reading(days_ago: int, weight_kg: float, body_fat_pct: float) -> dict:
    return {
        "date": AS_OF - datetime.timedelta(days=days_ago),
        "weight_kg": weight_kg,
        "body_fat_pct": body_fat_pct,
    }


# ── weight_stats readability ──────────────────────────────────────────────────


def test_readable_false_at_low_coverage():
    session = _new_session()
    user = _make_user(session)
    _seed_decline(session, user.id, days=30, weigh_ins=9)  # 30% coverage
    stats = weight_stats(session, user.id, window_days=30, as_of=AS_OF)
    assert stats["coverage_pct"] < COVERAGE_THRESHOLD
    assert stats["readable"] is False


def test_readable_true_at_high_coverage_with_enough_days():
    session = _new_session()
    user = _make_user(session)
    _seed_decline(session, user.id, days=30, weigh_ins=26)  # ~87% coverage
    stats = weight_stats(session, user.id, window_days=30, as_of=AS_OF)
    assert stats["coverage_pct"] >= 86.0
    assert stats["entries_used"] >= MIN_N_DAYS
    assert stats["readable"] is True
    assert stats["rate_kg_wk"] is not None


def test_ci_including_zero_yields_flat_state():
    session = _new_session()
    user = _make_user(session)
    # Constant weight — EWMA stays flat; OLS slope is zero with CI including zero.
    for i in range(26):
        _add_entry(
            session,
            user.id,
            AS_OF - datetime.timedelta(days=25 - i),
            78.0,
        )
    stats = weight_stats(session, user.id, window_days=30, as_of=AS_OF)
    assert stats["readable"] is True
    assert stats["state"] == "flat"
    assert stats["rate_kg_wk"] is not None
    assert stats["ci_kg_wk"] is not None
    lower = stats["rate_kg_wk"] - stats["ci_kg_wk"]
    upper = stats["rate_kg_wk"] + stats["ci_kg_wk"]
    assert lower <= 0.0 <= upper


# ── one rate across consumers ─────────────────────────────────────────────────


@patch("backend.services.weight_stats.today_bangkok", return_value=AS_OF)
@patch("backend.services.cut_review.today_bangkok", return_value=AS_OF)
def test_one_rate_matches_chart_stats_and_cut_review(_cut_today, _stats_today):
    session = _new_session(with_fuel=True)
    user = _make_user(session)
    _seed_decline(session, user.id, days=21, weigh_ins=21)

    chart_rate = weight_stats(session, user.id, window_days=21, as_of=AS_OF)

    with patch("backend.services.cut_review.get_or_create_settings") as mock_settings:
        mock_settings.return_value = type("S", (), {"deficit_kcal": 300})()
        with patch("backend.services.cut_review.settings_to_dict", return_value={
            "deficit_kcal": 300,
            "weight_kg": 80.0,
            "run_kcal_per_kg_per_km": 1.0,
        }):
            real_execute = session.execute

            def _execute(statement, params=None, **kwargs):
                if "daily_metrics" in str(statement):
                    return MagicMock(fetchall=lambda: [])
                return real_execute(statement, params, **kwargs)

            with patch.object(session, "execute", side_effect=_execute):
                review = get_weekly_review(user.id, as_of_date=AS_OF, db=session)

    assert review["actual_rate_kg_per_week"] == pytest.approx(
        chart_rate["rate_kg_wk"], abs=1e-3
    )


# ── cut_review re-gate ───────────────────────────────────────────────────────


_BEHIND = dict(
    weigh_in_count_14d=12,
    has_active_plan=True,
    actual_rate_kg_per_week=-0.05,
    plan_rate_kg_per_week=-0.35,
    weekly_pct_bw_rate=-0.06,
    ea_proxy=1.0,
    logging_adherence_pct=0.0,
    avg_intake_vs_budget_kcal=0.0,
    consecutive_weeks_behind=1,
    pct_logged_days_at_or_under_budget=0.0,
    current_deficit_kcal=300,
)


def test_cut_review_zero_fuel_logs_still_recommends_when_coverage_ok():
    result = compute_cut_recommendation(**_BEHIND)
    assert result["recommendation"] not in (
        "insufficient_data",
        "insufficient_coverage",
        "check_logging",
    )


@patch("backend.services.cut_review.today_bangkok", return_value=AS_OF)
def test_cut_review_below_coverage_returns_insufficient_coverage(_today):
    session = _new_session()
    user = _make_user(session)
    _seed_decline(session, user.id, days=21, weigh_ins=6)

    with patch("backend.services.cut_review.get_or_create_settings") as mock_settings:
        mock_settings.return_value = type("S", (), {"deficit_kcal": 300})()
        with patch("backend.services.cut_review.settings_to_dict", return_value={
            "deficit_kcal": 300,
            "weight_kg": 80.0,
            "run_kcal_per_kg_per_km": 1.0,
        }):
            review = get_weekly_review(user.id, as_of_date=AS_OF, db=session)

    assert review["recommendation"] == "insufficient_coverage"
    assert review["gated"] is True
    assert review["actual_rate_kg_per_week"] is None
    assert review["action"] is None
    assert review["coverage_pct"] is not None
    assert review["days_needed"] is not None


# ── composition on weight-chart payload shape ────────────────────────────────


def test_composition_not_readable_with_three_bf_readings():
    readings = [_reading(i * 7, 80.0, 20.0) for i in range(3)]
    result = compute_composition_trend(readings, AS_OF)
    assert result["readable"] is False
    assert result["lean_mass_4wk_delta"] is None
    assert result["fat_mass_4wk_delta"] is None


def test_composition_deltas_present_with_four_bf_readings():
    readings = [_reading(i * 7, 80.0 - i * 0.2, 22.0 - i * 0.3) for i in range(8)]
    result = compute_composition_trend(readings, AS_OF)
    assert result["readable"] is True
    assert result["lean_mass_4wk_delta"] is not None
    assert result["fat_mass_4wk_delta"] is not None
    assert result["lean_mass_kg_trend"] is not None
    assert result["fat_mass_kg_trend"] is not None


def test_composition_emits_no_target_keys():
    readings = [_reading(i * 7, 80.0, 20.0) for i in range(5)]
    result = compute_composition_trend(readings, AS_OF)
    forbidden = {
        "target",
        "goal",
        "target_kg",
        "goal_line",
        "on_track",
        "target_body_fat_pct",
        "lean_mass_target",
        "fat_mass_target",
    }
    assert forbidden.isdisjoint(result.keys())
    for item in result.get("readings", []):
        assert forbidden.isdisjoint(item.keys())
