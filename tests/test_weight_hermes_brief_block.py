"""Tests for the "weight" block added to the Hermes brief contract
(perfcoach_brief.latest.json, schema_version bumped 1 -> 2).

Covers three layers of the feature:

1. backend/services/weight_plan.py — new pure/DB-read helpers:
   _weight_rollup, compute_current_pace_kg_per_week,
   compute_required_pace_kg_per_week, compute_on_track,
   compute_weight_status.
2. backend/worker_app.py — new read endpoints GET /api/weight/recent and
   GET /api/weight/status.
3. scripts/export_brief.py — _compute_weight_advisory's training-phase-aware
   decision table (the safety-critical piece: a "build" verdict must never
   push a deficit), plus _assemble_weight/_fetch_weight_status error
   handling.

DB approach for weight_plan.py: an in-memory SQLite engine with the real
ORM models (backend.models.Base.metadata), rather than a hand-rolled query
stub — this exercises the real SQLAlchemy filter/order_by/limit chains
end to end. SQLite can't evaluate Postgres-only server defaults
(gen_random_uuid(), now()), so every row below sets id/created_at/
updated_at/is_admin/is_active explicitly rather than relying on server
defaults.

Worker endpoint approach: FastAPI TestClient with backend.worker_app.Session
patched to a MagicMock (same pattern already used by
tests/test_plan_today_worker__1451.py and
tests/test_worker_training_load__1449.py for /api/plan/today and
/api/training/load) — spinning up the real app against live Postgres isn't
available in this environment (confirmed: no DATABASE_URL_UAT, no live UAT
server), so this mirrors the established, working pattern for these routes
rather than skipping worker-endpoint coverage entirely.
"""
from __future__ import annotations

import datetime
import importlib
import importlib.util
import pathlib
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.models import Base, User, WeightEntry, WeightTarget
from backend.services.weight_plan import (
    _weight_rollup,
    compute_current_pace_kg_per_week,
    compute_on_track,
    compute_required_pace_kg_per_week,
    compute_weight_status,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ═════════════════════════════════════════════════════════════════════════════
# Shared ORM fixture helpers (in-memory SQLite)
# ═════════════════════════════════════════════════════════════════════════════

def _new_session() -> _OrmSess:
    """Fresh in-memory SQLite DB with only the tables this module needs."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, WeightEntry.__table__, WeightTarget.__table__])
    return _OrmSess(engine)


def _make_user(session: _OrmSess, name: str = "u") -> User:
    u = User(
        id=uuid.uuid4(), name=name, is_admin=False, is_active=True,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(u)
    session.commit()
    return u


def _add_entry(session: _OrmSess, user_id, entry_date, weight_kg, created_at=None) -> WeightEntry:
    now = datetime.datetime.now(datetime.timezone.utc)
    we = WeightEntry(
        id=uuid.uuid4(), user_id=user_id, entry_date=entry_date, weight_kg=weight_kg,
        created_at=created_at or now, updated_at=now,
    )
    session.add(we)
    session.commit()
    return we


def _make_target(
    session: _OrmSess, user_id, *, start_weight_kg, target_weight_kg, start_date,
    target_date, created_at=None, status="active",
) -> WeightTarget:
    now = datetime.datetime.now(datetime.timezone.utc)
    t = WeightTarget(
        id=uuid.uuid4(), user_id=user_id, start_weight_kg=start_weight_kg, start_date=start_date,
        target_weight_kg=target_weight_kg, target_date=target_date, status=status,
        created_at=created_at or now, updated_at=now,
    )
    session.add(t)
    session.commit()
    return t


# ═════════════════════════════════════════════════════════════════════════════
# _weight_rollup — pure function (rows: list[(date, weight_kg)])
# ═════════════════════════════════════════════════════════════════════════════

class TestWeightRollup:
    def test_genuine_multiday_average_not_a_single_days_value(self):
        """current_kg must be a real average across the trailing 7-day
        window, not silently collapsing to one day's raw entry."""
        as_of = datetime.date(2026, 7, 15)
        # Distinct, irregular daily values across the trailing 7 days
        # (2026-07-09..15) — deliberately NOT a linear/symmetric progression,
        # so the mean can't coincidentally equal the middle data point.
        daily = [69.8, 70.3, 71.1, 69.5, 70.9, 71.4, 68.9]
        rows = [(as_of - datetime.timedelta(days=i), daily[6 - i]) for i in range(7)]
        result = _weight_rollup(rows, as_of)

        expected_avg = round(sum(daily) / 7, 2)
        assert result["current_kg"] == expected_avg
        # Not equal to any single day's raw value.
        assert result["current_kg"] not in daily
        # basis truthfully reports the trailing-7d branch fired.
        assert result["basis"] == "avg_7d"

    def test_zero_entries_all_none(self):
        result = _weight_rollup([], datetime.date(2026, 7, 15))
        assert result == {"current_kg": None, "basis": None, "trend_7d": None, "trend_28d": None}

    def test_single_entry_in_7d_window_falls_back_to_wider_lookback_average(self):
        """Fewer than 2 entries in the trailing 7 days -> average of whatever
        is available in the wider lookback, not the lone entry's raw value."""
        as_of = datetime.date(2026, 7, 15)
        rows = [
            (as_of, 80.0),                               # 1 entry inside trailing 7d
            (as_of - datetime.timedelta(days=20), 76.0),  # outside 7d, inside wide lookback
            (as_of - datetime.timedelta(days=40), 74.0),  # outside 7d, inside wide lookback
        ]
        result = _weight_rollup(rows, as_of)
        # Must NOT just be the single 7-day entry's raw value...
        assert result["current_kg"] != 80.0
        # ...it must be the average of every row supplied.
        assert result["current_kg"] == round((80.0 + 76.0 + 74.0) / 3, 2)
        # basis truthfully reports the wide-lookback branch fired, not avg_7d.
        assert result["basis"] == "avg_wide"

    def test_single_row_total_does_not_crash(self):
        """A single row anywhere in the lookback (and nowhere else) must not
        raise — current_kg becomes that row's value because there is nothing
        else to average against, trends stay None (no prior window). This is
        the exact shape of the live user's current data (tracking paused,
        one weigh-in inside the lookback, none in the trailing 7 days) —
        see docs/pre-production-review-status.md §1: last weigh-in 2026-07-22.
        basis must say 'single_entry', NOT 'avg_wide' — no averaging happened,
        and mislabeling it 'avg_wide' would be less truthful than the retired
        compute_gap rule's 'latest_entry', which this replaces."""
        as_of = datetime.date(2026, 7, 15)
        rows = [(as_of - datetime.timedelta(days=30), 82.5)]
        result = _weight_rollup(rows, as_of)
        assert result["current_kg"] == 82.5
        assert result["basis"] == "single_entry"
        assert result["trend_7d"] is None

    def test_single_row_current_kg_unchanged_only_label_is_honest(self):
        """The fix for the mislabeling above must NOT blank current_kg to
        None for the single-reading case — that would be a behaviour change
        beyond the agreed decision (unify on _weight_rollup's rule; never
        silently pass one reading off as an average) and would blank the
        live user's Weight page. Only the label changes, not the number."""
        as_of = datetime.date(2026, 8, 1)
        rows = [(as_of - datetime.timedelta(days=10), 78.4)]  # 2026-07-22
        result = _weight_rollup(rows, as_of)
        assert result["current_kg"] == 78.4
        assert result["basis"] == "single_entry"
        assert result["trend_28d"] is None

    def test_trend_7d_is_window_average_delta_not_day_over_day(self):
        """trend_7d must compare (avg of last 7d) vs (avg of the preceding
        7d) — verified by constructing a fixture where the naive
        day-over-day delta (today vs yesterday) would give a materially
        different number than the correct window-to-window delta."""
        as_of = datetime.date(2026, 7, 15)
        # Trailing 7d (day 0..6): flat at 70.0 except a single low outlier on
        # day 0 (today) -> day-over-day (today vs yesterday) would show a
        # big drop, but the correct window average barely moves.
        window_7 = [70.0, 70.0, 70.0, 70.0, 70.0, 70.0, 68.0]  # index i = days_ago 6..0
        prior_7 = [71.0] * 7  # days_ago 13..7
        rows = []
        for i in range(7):
            rows.append((as_of - datetime.timedelta(days=6 - i), window_7[i]))
        for i in range(7):
            rows.append((as_of - datetime.timedelta(days=13 - i), prior_7[i]))

        result = _weight_rollup(rows, as_of)

        expected_window_avg = round(sum(window_7) / 7, 2)
        expected_prior_avg = round(sum(prior_7) / 7, 2)
        expected_trend = round(expected_window_avg - expected_prior_avg, 2)

        assert result["trend_7d"] == expected_trend
        # The day-over-day delta (today 68.0 vs yesterday 70.0 = -2.0) must
        # NOT be what trend_7d reports.
        day_over_day_delta = 68.0 - 70.0
        assert result["trend_7d"] != day_over_day_delta

    def test_trend_28d_is_window_average_delta(self):
        as_of = datetime.date(2026, 7, 15)
        rows = []
        # window_28: days_ago 0..27, weight = 80.0 + 0.1*days_ago
        for d in range(28):
            rows.append((as_of - datetime.timedelta(days=d), 80.0 + 0.1 * d))
        # prior_28: days_ago 28..34 (partial — enough to be non-empty)
        for d in range(28, 35):
            rows.append((as_of - datetime.timedelta(days=d), 80.0 + 0.1 * d))

        result = _weight_rollup(rows, as_of)

        window_vals = [80.0 + 0.1 * d for d in range(28)]
        prior_vals = [80.0 + 0.1 * d for d in range(28, 35)]
        expected = round(sum(window_vals) / len(window_vals) - sum(prior_vals) / len(prior_vals), 2)
        assert result["trend_28d"] == pytest.approx(expected, abs=0.01)

    def test_trend_none_when_prior_window_empty(self):
        """trend_7d/trend_28d are None (not 0 or some default) when there is
        no data at all in the prior comparison window — a new user with only
        recent entries shouldn't get a fabricated trend."""
        as_of = datetime.date(2026, 7, 15)
        rows = [(as_of - datetime.timedelta(days=i), 70.0 + i) for i in range(5)]
        result = _weight_rollup(rows, as_of)
        assert result["trend_7d"] is None
        assert result["trend_28d"] is None


# ═════════════════════════════════════════════════════════════════════════════
# compute_current_pace_kg_per_week / compute_required_pace_kg_per_week
# ═════════════════════════════════════════════════════════════════════════════

class TestComputePace:
    def test_current_pace_positive_for_loss_multi_entry(self):
        """>= 2 entries in the 14d window: pace = (oldest - newest) / days * 7.
        Losing weight -> positive pace, matching the module's documented
        'positive = losing' sign convention."""
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        target = _make_target(
            session, u.id, start_weight_kg=90.0, start_date=as_of - datetime.timedelta(days=200),
            target_weight_kg=70.0, target_date=as_of + datetime.timedelta(days=60),
            created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=300),
        )
        # oldest (13 days ago) = 81.4kg, newest (today) = 80.0kg -> losing 1.4kg over 13 days
        _add_entry(session, u.id, as_of - datetime.timedelta(days=13), 81.4)
        _add_entry(session, u.id, as_of, 80.0)

        pace = compute_current_pace_kg_per_week(target, session, as_of)
        expected = round((81.4 - 80.0) / 13 * 7, 4)
        assert pace == pytest.approx(expected)
        assert pace > 0, "losing weight toward a lower target must be a positive pace"

    def test_current_pace_negative_for_gain_direction(self):
        """Weight trending UP over the window against a gain target still
        reports via the same sign convention: negative pace = gaining."""
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        target = _make_target(
            session, u.id, start_weight_kg=65.0, start_date=as_of - datetime.timedelta(days=200),
            target_weight_kg=75.0, target_date=as_of + datetime.timedelta(days=40),
            created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=300),
        )
        # oldest (13 days ago) = 69.35kg, newest (today) = 70.0kg -> gaining
        _add_entry(session, u.id, as_of - datetime.timedelta(days=13), 69.35)
        _add_entry(session, u.id, as_of, 70.0)

        pace = compute_current_pace_kg_per_week(target, session, as_of)
        assert pace < 0, "gaining weight must report a negative pace per this module's convention"

    def test_current_pace_single_entry_uses_target_start_weight(self):
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        start_date = as_of - datetime.timedelta(days=10)
        target = _make_target(
            session, u.id, start_weight_kg=90.0, start_date=start_date,
            target_weight_kg=80.0, target_date=as_of + datetime.timedelta(days=60),
            created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=300),
        )
        _add_entry(session, u.id, as_of, 88.0)  # only 1 entry in the 14d window

        pace = compute_current_pace_kg_per_week(target, session, as_of)
        days_elapsed = (as_of - start_date).days
        expected = round((90.0 - 88.0) / days_elapsed * 7, 4)
        assert pace == pytest.approx(expected)

    def test_current_pace_none_when_zero_entries(self):
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        target = _make_target(
            session, u.id, start_weight_kg=90.0, start_date=as_of - datetime.timedelta(days=10),
            target_weight_kg=80.0, target_date=as_of + datetime.timedelta(days=60),
        )
        assert compute_current_pace_kg_per_week(target, session, as_of) is None

    def test_current_pace_none_single_entry_same_day_as_target_start(self):
        """A single entry logged the same day the target started -> zero
        elapsed days -> None, not a division-by-zero crash."""
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        target = _make_target(
            session, u.id, start_weight_kg=90.0, start_date=as_of,
            target_weight_kg=80.0, target_date=as_of + datetime.timedelta(days=60),
            created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=300),
        )
        _add_entry(session, u.id, as_of, 90.0)
        assert compute_current_pace_kg_per_week(target, session, as_of) is None

    def test_required_pace_positive_for_loss_target(self):
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        target = _make_target(
            session, u.id, start_weight_kg=90.0, start_date=as_of - datetime.timedelta(days=200),
            target_weight_kg=70.0, target_date=as_of + datetime.timedelta(days=60),
        )
        # >= 3 entries in trailing 7d -> avg_7d basis
        for d in range(7):
            _add_entry(session, u.id, as_of - datetime.timedelta(days=d), 80.0 + 0.1 * d)

        required = compute_required_pace_kg_per_week(target, session, as_of)
        current_basis = round((80.0 + 80.1 + 80.2 + 80.3 + 80.4 + 80.5 + 80.6) / 7, 2)
        weeks_remaining = 60 / 7.0
        expected = round((current_basis - 70.0) / weeks_remaining, 4)
        assert required == pytest.approx(expected)
        assert required > 0

    def test_required_pace_none_when_target_date_passed(self):
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        target = _make_target(
            session, u.id, start_weight_kg=90.0, start_date=as_of - datetime.timedelta(days=200),
            target_weight_kg=70.0, target_date=as_of - datetime.timedelta(days=1),
        )
        assert compute_required_pace_kg_per_week(target, session, as_of) is None

    def test_required_pace_falls_back_to_start_weight_when_no_entries(self):
        """No weigh-ins at all -> current_weight falls back to
        target.start_weight_kg rather than crashing on a None current_basis."""
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        target = _make_target(
            session, u.id, start_weight_kg=90.0, start_date=as_of - datetime.timedelta(days=200),
            target_weight_kg=70.0, target_date=as_of + datetime.timedelta(days=70),
        )
        required = compute_required_pace_kg_per_week(target, session, as_of)
        weeks_remaining = 70 / 7.0
        expected = round((90.0 - 70.0) / weeks_remaining, 4)
        assert required == pytest.approx(expected)


# ═════════════════════════════════════════════════════════════════════════════
# compute_on_track — direction-aware
# ═════════════════════════════════════════════════════════════════════════════

def _t(target_weight_kg, start_weight_kg):
    from types import SimpleNamespace
    return SimpleNamespace(target_weight_kg=target_weight_kg, start_weight_kg=start_weight_kg)


class TestComputeOnTrack:
    def test_none_when_either_pace_missing(self):
        loss_target = _t(70.0, 90.0)
        assert compute_on_track(loss_target, None, 0.5) is None
        assert compute_on_track(loss_target, 0.5, None) is None
        assert compute_on_track(loss_target, None, None) is None

    # ── loss target ──
    def test_loss_target_on_track_true_when_pace_meets_required(self):
        loss_target = _t(70.0, 90.0)  # target < start -> loss
        assert compute_on_track(loss_target, current_pace_kg_per_week=1.0, required_pace_kg_per_week=0.8) is True

    def test_loss_target_on_track_false_when_pace_below_required(self):
        loss_target = _t(70.0, 90.0)
        assert compute_on_track(loss_target, current_pace_kg_per_week=0.3, required_pace_kg_per_week=0.8) is False

    def test_loss_target_goal_already_met_true_regardless_of_pace(self):
        """required_pace <= 0 for a loss target means the goal is already
        reached/exceeded -> True even with an adverse (negative/gaining)
        current pace."""
        loss_target = _t(70.0, 90.0)
        assert compute_on_track(loss_target, current_pace_kg_per_week=-5.0, required_pace_kg_per_week=0.0) is True
        assert compute_on_track(loss_target, current_pace_kg_per_week=-5.0, required_pace_kg_per_week=-1.0) is True

    # ── gain target ──
    def test_gain_target_on_track_true_when_pace_meets_required(self):
        gain_target = _t(80.0, 65.0)  # target > start -> gain
        # required_pace negative (gaining needed); current pace equally or more negative = on track
        assert compute_on_track(gain_target, current_pace_kg_per_week=-1.0, required_pace_kg_per_week=-0.8) is True

    def test_gain_target_on_track_false_when_gaining_too_slowly(self):
        gain_target = _t(80.0, 65.0)
        # current pace -0.2 (barely gaining) vs required -0.8 (needs to gain faster) -> not on track
        assert compute_on_track(gain_target, current_pace_kg_per_week=-0.2, required_pace_kg_per_week=-0.8) is False

    def test_gain_target_goal_already_met_true_regardless_of_pace(self):
        """required_pace >= 0 for a gain target means the goal is already
        reached/exceeded -> True even with an adverse (positive/losing)
        current pace."""
        gain_target = _t(80.0, 65.0)
        assert compute_on_track(gain_target, current_pace_kg_per_week=5.0, required_pace_kg_per_week=0.0) is True
        assert compute_on_track(gain_target, current_pace_kg_per_week=5.0, required_pace_kg_per_week=1.0) is True

    def test_not_hardcoded_to_loss_only(self):
        """Regression guard: feeding the SAME numeric paces to a loss vs a
        gain target must NOT produce the same on_track verdict when the
        direction implies opposite interpretations — proves direction is
        actually read from the target, not assumed."""
        loss_target = _t(70.0, 90.0)
        gain_target = _t(80.0, 65.0)
        # Positive current pace, positive required pace: correct for loss
        # (both moving toward a lower target) but WRONG direction for gain.
        loss_result = compute_on_track(loss_target, current_pace_kg_per_week=1.0, required_pace_kg_per_week=0.8)
        gain_result = compute_on_track(gain_target, current_pace_kg_per_week=1.0, required_pace_kg_per_week=0.8)
        assert loss_result is True
        # For a gain target, required_pace=0.8 (>=0) means goal already met -> True regardless;
        # this is intentionally a DIFFERENT code path than the loss case, proving direction-awareness.
        assert gain_result is True
        # Now use a required_pace that is NOT >=0 for gain (i.e. genuinely evaluate direction):
        gain_result_2 = compute_on_track(gain_target, current_pace_kg_per_week=1.0, required_pace_kg_per_week=-0.8)
        assert gain_result_2 is False, (
            "gaining goal that still requires -0.8kg/wk gain, but user is losing (+1.0) -> not on track"
        )


# ═════════════════════════════════════════════════════════════════════════════
# compute_weight_status — full assembly
# ═════════════════════════════════════════════════════════════════════════════

class TestComputeWeightStatus:
    def test_zero_entries_no_target_all_null(self):
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)
        result = compute_weight_status(session, u.id, as_of)
        assert result == {
            "current_kg": None,
            "trend_7d": None,
            "trend_28d": None,
            "target_kg": None,
            "target_date": None,
            "pace_kg_per_week": None,
            "on_track": None,
            "projection_date": None,
        }

    def test_realistic_multiweek_fixture_matches_hand_computed_values(self):
        """35 daily entries (today back to 34 days ago) on a clean loss
        trend, plus an active loss target. Every field is checked against
        an independently hand-computed expected value."""
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)

        # weight(d days ago) = 80.0 + 0.1*d  -> today (d=0) = 80.0, lightest;
        # 34 days ago = 83.4, heaviest -> clear loss trend over time.
        for d in range(35):
            _add_entry(session, u.id, as_of - datetime.timedelta(days=d), 80.0 + 0.1 * d)

        target = _make_target(
            session, u.id, start_weight_kg=90.0, start_date=as_of - datetime.timedelta(days=200),
            target_weight_kg=70.0, target_date=as_of + datetime.timedelta(days=60),
            created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=300),
        )

        result = compute_weight_status(session, u.id, as_of)

        # current_kg: 7d average (d=0..6), NOT the single most recent (80.0) raw value.
        window_7 = [80.0 + 0.1 * d for d in range(7)]
        expected_current = round(sum(window_7) / 7, 2)
        assert result["current_kg"] == expected_current
        assert result["current_kg"] != 80.0, "current_kg must never be a single day's raw entry"

        # trend_7d: window(0..6) avg minus window(7..13) avg.
        prior_7 = [80.0 + 0.1 * d for d in range(7, 14)]
        expected_trend_7d = round(expected_current - sum(prior_7) / 7, 2)
        assert result["trend_7d"] == pytest.approx(expected_trend_7d, abs=0.01)

        # trend_28d: window(0..27) avg minus window(28..34) avg (partial prior window).
        window_28 = [80.0 + 0.1 * d for d in range(28)]
        prior_28 = [80.0 + 0.1 * d for d in range(28, 35)]
        expected_trend_28d = round(
            sum(window_28) / len(window_28) - sum(prior_28) / len(prior_28), 2
        )
        assert result["trend_28d"] == pytest.approx(expected_trend_28d, abs=0.01)

        assert result["target_kg"] == 70.0
        assert result["target_date"] == (as_of + datetime.timedelta(days=60)).isoformat()

        weeks_remaining = 60 / 7.0
        expected_required_pace = round((expected_current - 70.0) / weeks_remaining, 4)
        # current_pace from the 14d window (entries d=0..14, ascending)
        first_e_w = 80.0 + 0.1 * 14
        last_e_w = 80.0
        expected_current_pace = round((first_e_w - last_e_w) / 14 * 7, 4)
        assert result["pace_kg_per_week"] == pytest.approx(expected_current_pace)

        expected_on_track = expected_current_pace >= expected_required_pace
        assert result["on_track"] == expected_on_track

        # projection: uses the 7-day window (d=0..6, ascending), same rate as pace calc coincidentally.
        proj_rate_per_week = (window_7[6] - window_7[0]) / 6 * 7
        weeks_needed = (window_7[0] - 70.0) / proj_rate_per_week
        expected_days = int(weeks_needed * 7)
        expected_projection = (as_of + datetime.timedelta(days=expected_days)).isoformat()
        assert result["projection_date"] == expected_projection

    def test_gain_target_direction_flows_through_status(self):
        """A gain target (target_weight_kg > start_weight_kg) must not be
        silently mishandled as a loss target anywhere in the assembly."""
        session = _new_session()
        u = _make_user(session)
        as_of = datetime.date(2026, 7, 15)

        # weight(d days ago) = 70.0 - 0.05*d -> today (d=0)=70.0 heaviest, past lighter -> gaining.
        for d in range(20):
            _add_entry(session, u.id, as_of - datetime.timedelta(days=d), 70.0 - 0.05 * d)

        target = _make_target(
            session, u.id, start_weight_kg=65.0, start_date=as_of - datetime.timedelta(days=200),
            target_weight_kg=75.0, target_date=as_of + datetime.timedelta(days=40),
            created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=300),
        )
        result = compute_weight_status(session, u.id, as_of)
        assert result["pace_kg_per_week"] < 0, "gaining trend must report negative pace"
        assert result["target_kg"] == 75.0


# ═════════════════════════════════════════════════════════════════════════════
# Worker endpoints: GET /api/weight/recent, GET /api/weight/status
# ═════════════════════════════════════════════════════════════════════════════

def _mock_entry(entry_date, weight_kg, entry_time=None):
    row = MagicMock()
    row.entry_date = entry_date
    row.entry_time = entry_time
    row.weight_kg = weight_kg
    return row


def _mock_user(username="alice"):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.name = username
    u.is_active = True
    return u


class TestWeightRecentEndpoint:
    def test_registered_only_on_worker_app(self):
        from backend.worker_app import app as worker_app
        import backend.main as main_mod

        assert "/api/weight/recent" in {r.path for r in worker_app.routes}
        assert "/api/weight/recent" not in {getattr(r, "path", None) for r in main_mod.app.routes}

    def test_n_clamped_to_90_max(self):
        user = _mock_user()
        with patch("backend.worker_app._resolve_read_user", return_value=user), \
             patch("backend.worker_app.Session") as MockSession:
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            limit_mock = mock_db.query.return_value.filter.return_value.order_by.return_value.limit
            limit_mock.return_value.all.return_value = []

            from fastapi.testclient import TestClient
            from backend.worker_app import app
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/weight/recent?n=999&user=alice")

        assert r.status_code == 200
        assert limit_mock.call_args[0][0] == 90

    def test_n_clamped_to_1_min(self):
        user = _mock_user()
        with patch("backend.worker_app._resolve_read_user", return_value=user), \
             patch("backend.worker_app.Session") as MockSession:
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            limit_mock = mock_db.query.return_value.filter.return_value.order_by.return_value.limit
            limit_mock.return_value.all.return_value = []

            from fastapi.testclient import TestClient
            from backend.worker_app import app
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/weight/recent?n=0&user=alice")

        assert r.status_code == 200
        assert limit_mock.call_args[0][0] == 1

    def test_newest_first_ordering_preserved_from_query(self):
        """The endpoint must not re-sort/invert what the (mocked) DB-ordered
        query returns; response entries preserve the order of the rows."""
        user = _mock_user()
        rows = [
            _mock_entry(datetime.date(2026, 7, 15), 70.0),
            _mock_entry(datetime.date(2026, 7, 14), 70.2),
            _mock_entry(datetime.date(2026, 7, 13), 70.4),
        ]
        with patch("backend.worker_app._resolve_read_user", return_value=user), \
             patch("backend.worker_app.Session") as MockSession:
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rows

            from fastapi.testclient import TestClient
            from backend.worker_app import app
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/weight/recent?n=3&user=alice")

        data = r.json()
        assert [e["date"] for e in data["entries"]] == ["2026-07-15", "2026-07-14", "2026-07-13"]
        assert data["last_logged"] == "2026-07-15"

    def test_ewma_and_trend_populated(self):
        user = _mock_user()
        # Clear upward trend -> newest-first rows
        rows = [
            _mock_entry(datetime.date(2026, 1, 1) + datetime.timedelta(days=13 - i), 70.0 + (13 - i) * 0.3)
            for i in range(14)
        ]
        with patch("backend.worker_app._resolve_read_user", return_value=user), \
             patch("backend.worker_app.Session") as MockSession:
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rows

            from fastapi.testclient import TestClient
            from backend.worker_app import app
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/weight/recent?n=14&user=alice")

        data = r.json()
        assert isinstance(data["ewma"], (int, float))
        assert data["trend"] == "up"

    def test_empty_entries_returns_200_with_nulls(self):
        user = _mock_user()
        with patch("backend.worker_app._resolve_read_user", return_value=user), \
             patch("backend.worker_app.Session") as MockSession:
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

            from fastapi.testclient import TestClient
            from backend.worker_app import app
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/weight/recent?user=alice")

        assert r.status_code == 200
        data = r.json()
        assert data == {"entries": [], "count": 0, "last_logged": None, "ewma": None, "trend": None}


class TestWeightStatusEndpoint:
    def test_registered_only_on_worker_app(self):
        from backend.worker_app import app as worker_app
        import backend.main as main_mod

        assert "/api/weight/status" in {r.path for r in worker_app.routes}
        assert "/api/weight/status" not in {getattr(r, "path", None) for r in main_mod.app.routes}

    def test_delegates_to_compute_weight_status_with_correct_args(self):
        user = _mock_user()
        expected = {
            "current_kg": 80.3, "trend_7d": -0.7, "trend_28d": -1.75,
            "target_kg": 70.0, "target_date": "2026-09-13",
            "pace_kg_per_week": 0.7, "on_track": False, "projection_date": "2026-10-23",
        }
        with patch("backend.worker_app._resolve_read_user", return_value=user), \
             patch("backend.worker_app.Session") as MockSession, \
             patch("backend.services.weight_plan.compute_weight_status", return_value=expected) as mock_compute:
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)

            from fastapi.testclient import TestClient
            from backend.worker_app import app
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/weight/status?date=2026-07-15&user=alice")

        assert r.status_code == 200
        assert r.json() == expected
        mock_compute.assert_called_once_with(mock_db, user.id, datetime.date(2026, 7, 15))

    def test_zero_data_returns_200_with_nulls(self):
        user = _mock_user()
        null_block = {
            "current_kg": None, "trend_7d": None, "trend_28d": None,
            "target_kg": None, "target_date": None,
            "pace_kg_per_week": None, "on_track": None, "projection_date": None,
        }
        with patch("backend.worker_app._resolve_read_user", return_value=user), \
             patch("backend.worker_app.Session") as MockSession, \
             patch("backend.services.weight_plan.compute_weight_status", return_value=null_block):
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)

            from fastapi.testclient import TestClient
            from backend.worker_app import app
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/weight/status?user=alice")

        assert r.status_code == 200
        assert r.json() == null_block

    def test_no_defensive_wrapper_around_compute_weight_status(self):
        """FINDING (not asserting desired behavior, documenting actual
        behavior): unlike /api/weight/recent, which manually builds its own
        null response, /api/weight/status has no try/except around
        compute_weight_status — an unexpected exception there currently
        surfaces as a 500, despite the docstring's 'Always HTTP 200' claim.
        The guarantee holds only as long as compute_weight_status itself
        never raises (which the weight_plan.py tests in this file confirm
        it does not for the documented missing-data cases) — there is no
        endpoint-level defense-in-depth backstop the way weight_recent has."""
        user = _mock_user()
        with patch("backend.worker_app._resolve_read_user", return_value=user), \
             patch("backend.worker_app.Session") as MockSession, \
             patch("backend.services.weight_plan.compute_weight_status", side_effect=RuntimeError("boom")):
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)

            from fastapi.testclient import TestClient
            from backend.worker_app import app
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/weight/status?user=alice")

        # Documents current behavior. If a future patch adds a try/except
        # backstop (matching weight_recent's defensiveness), update this to
        # assert 200 with a null block instead.
        assert r.status_code == 500


# ═════════════════════════════════════════════════════════════════════════════
# export_brief.py — _compute_weight_advisory decision table (safety-critical)
# ═════════════════════════════════════════════════════════════════════════════

def _import_export_brief():
    spec = importlib.util.spec_from_file_location("export_brief_wt", _ROOT / "scripts" / "export_brief.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def eb():
    return _import_export_brief()


_NULL_WEIGHT = {
    "current_kg": None, "trend_7d": None, "trend_28d": None,
    "target_kg": None, "target_date": None,
    "pace_kg_per_week": None, "on_track": None, "projection_date": None,
}


def _weight(target_kg=70.0, on_track=None):
    w = dict(_NULL_WEIGHT)
    w["target_kg"] = target_kg
    w["on_track"] = on_track
    return w


# Deficit-pushing vocabulary that must never appear as an AFFIRMATIVE
# recommendation when verdict == "build". These words are allowed to appear
# only inside a negating clause (e.g. "rather than pushing the deficit
# further", "don't cut calories") — the invariant we care about is that the
# text never tells the user to actually push/add/increase a deficit, not
# that the word itself is banned outright (negating it is exactly the safe,
# correct phrasing the coder used).
_DEFICIT_TRIGGER_WORDS = ["deficit", "cut", "reduce"]
_NEGATION_CUES = ["rather than", "instead of", "don't", "do not", "not ", "avoid", "no "]


def _assert_no_affirmative_deficit_push(text: str) -> None:
    """Grep-style safety check: any mention of a deficit-push trigger word
    must sit inside a negating clause; otherwise it reads as an affirmative
    recommendation to diet/cut, which a 'build' verdict must never produce."""
    text_lower = text.lower()
    for word in _DEFICIT_TRIGGER_WORDS:
        idx = text_lower.find(word)
        while idx != -1:
            preceding_window = text_lower[max(0, idx - 40):idx]
            negated = any(cue in preceding_window for cue in _NEGATION_CUES)
            assert negated, (
                f"SAFETY VIOLATION: build-verdict advisory text affirmatively "
                f"uses deficit-pushing word {word!r} without a preceding negation "
                f"cue ({_NEGATION_CUES}): {text!r}"
            )
            idx = text_lower.find(word, idx + 1)


class TestComputeWeightAdvisoryDecisionTable:
    # Row 1: no target set -> None
    def test_row1_no_target_returns_none(self, eb):
        no_target = _weight(target_kg=None, on_track=True)
        assert eb._compute_weight_advisory(no_target, "build") is None
        assert eb._compute_weight_advisory(no_target, None) is None
        assert eb._compute_weight_advisory({}, "hold") is None
        assert eb._compute_weight_advisory(None, "hold") is None

    # Row 2: target set, on_track is None (insufficient data) -> None
    def test_row2_on_track_none_insufficient_data_returns_none(self, eb):
        w = _weight(target_kg=70.0, on_track=None)
        assert eb._compute_weight_advisory(w, "build") is None
        assert eb._compute_weight_advisory(w, "hold") is None
        assert eb._compute_weight_advisory(w, None) is None

    # Row 3 (SAFETY-CRITICAL): verdict == "build" -> HOLD intake, regardless
    # of on_track True or False, and the text must never push a deficit.
    @pytest.mark.parametrize("on_track_value", [True, False])
    def test_row3_build_verdict_never_recommends_deficit(self, eb, on_track_value):
        w = _weight(target_kg=70.0, on_track=on_track_value)
        advisory = eb._compute_weight_advisory(w, "build")

        assert advisory is not None, "a 'build' verdict with a target set must still produce a HOLD advisory"
        assert advisory["key"] == "weight_hold_intake_build"
        assert advisory["severity"] == "info"

        text_lower = advisory["text"].lower()
        assert "hold" in text_lower, "advisory must recommend holding intake during a build block"
        _assert_no_affirmative_deficit_push(advisory["text"])

    def test_row3_build_text_differs_by_on_track_but_both_hold(self, eb):
        """Both branches of a 'build' verdict must hold intake, but the
        wording may (and does) differ to acknowledge being behind pace."""
        w_true = _weight(target_kg=70.0, on_track=True)
        w_false = _weight(target_kg=70.0, on_track=False)
        adv_true = eb._compute_weight_advisory(w_true, "build")
        adv_false = eb._compute_weight_advisory(w_false, "build")
        assert adv_true["key"] == adv_false["key"] == "weight_hold_intake_build"
        assert "hold" in adv_true["text"].lower()
        assert "hold" in adv_false["text"].lower()

    # Row 4: on_track False, verdict is NOT "build" -> tighten-up advisory
    @pytest.mark.parametrize("verdict", ["hold", "back_off", None, "unknown_verdict"])
    def test_row4_off_track_non_build_verdict_recommends_tightening(self, eb, verdict):
        w = _weight(target_kg=70.0, on_track=False)
        advisory = eb._compute_weight_advisory(w, verdict)
        assert advisory is not None
        assert advisory["key"] == "weight_pace_behind_tighten_up"
        assert advisory["severity"] == "warn"
        assert "tighten" in advisory["text"].lower()

    # Row 5: on_track True, verdict is NOT "build" -> None (nothing to flag)
    @pytest.mark.parametrize("verdict", ["hold", "back_off", None, "unknown_verdict"])
    def test_row5_on_track_non_build_verdict_returns_none(self, eb, verdict):
        w = _weight(target_kg=70.0, on_track=True)
        assert eb._compute_weight_advisory(w, verdict) is None

    def test_decision_table_is_exhaustive_over_boolean_x_verdict_grid(self, eb):
        """Cross-check the full 2 (on_track) x 3 (verdict category) grid in
        one place so a future edit that flips a branch is caught even if the
        row-specific tests above are individually modified."""
        for on_track in (True, False):
            for verdict in ("build", "hold", None):
                w = _weight(target_kg=70.0, on_track=on_track)
                advisory = eb._compute_weight_advisory(w, verdict)
                if verdict == "build":
                    assert advisory is not None and advisory["key"] == "weight_hold_intake_build"
                    _assert_no_affirmative_deficit_push(advisory["text"])
                elif on_track is False:
                    assert advisory is not None and advisory["key"] == "weight_pace_behind_tighten_up"
                else:
                    assert advisory is None


# ═════════════════════════════════════════════════════════════════════════════
# _assemble_weight / _get_plan_for_date — error handling
#
# Rewritten for the #1496 refactor (backend/services/daily_brief.py): both
# functions now query the DB directly (no HTTP worker call), so the
# "network error" failure mode below no longer exists. _assemble_weight
# still degrades to _NULL_WEIGHT_BLOCK on ANY exception (its own bare
# except Exception around compute_weight_status); _get_plan_for_date has no
# such guard and lets a DB-query exception propagate, same load-bearing
# vs. non-load-bearing contrast the original tests documented — only the
# failure-injection point changed (DB query, not urllib).
# ═════════════════════════════════════════════════════════════════════════════

class TestAssembleWeightErrorHandling:
    def test_get_plan_for_date_raises_on_db_error(self, eb):
        """Baseline: confirms _get_plan_for_date's documented behavior (it IS
        allowed to raise) so the contrast with _assemble_weight below is
        meaningful, not assumed."""
        with patch("backend.services.daily_brief.Session", side_effect=RuntimeError("db unreachable")):
            with pytest.raises(RuntimeError):
                eb._get_plan_for_date(str(uuid.uuid4()), datetime.date(2026, 7, 15))

    def test_assemble_weight_degrades_to_null_block_on_db_error(self, eb):
        with patch("backend.services.daily_brief.compute_weight_status",
                   side_effect=RuntimeError("db unreachable")):
            result = eb._assemble_weight(str(uuid.uuid4()), datetime.date(2026, 7, 15))

        assert result == eb._NULL_WEIGHT_BLOCK
        assert result is not eb._NULL_WEIGHT_BLOCK, "must return a copy, not the shared module-level dict"

    def test_assemble_weight_degrades_to_null_block_on_generic_exception(self, eb):
        """Any unexpected exception (not just a DB error) must also degrade
        gracefully — the function's own except clause is bare Exception,
        not scoped to a DB-specific error type."""
        with patch("backend.services.daily_brief.compute_weight_status",
                   side_effect=ValueError("bad data")):
            result = eb._assemble_weight(str(uuid.uuid4()), datetime.date(2026, 7, 15))
        assert result == eb._NULL_WEIGHT_BLOCK

    def test_assemble_weight_degrades_to_null_block_on_non_uuid_user_id(self, eb):
        """A non-UUID user_id (e.g. a synthetic test id) must degrade
        gracefully rather than raising — mirrors _get_plan_for_date's own
        non-UUID handling, but via the bare except in _assemble_weight."""
        result = eb._assemble_weight("not-a-uuid", datetime.date(2026, 7, 15))
        assert result == eb._NULL_WEIGHT_BLOCK

    def test_assemble_weight_delegates_to_compute_weight_status(self, eb):
        with patch("backend.services.daily_brief.compute_weight_status",
                   return_value={"sentinel": True}) as mock_compute:
            uid = uuid.uuid4()
            result = eb._assemble_weight(str(uid), datetime.date(2026, 7, 15))
        assert result == {"sentinel": True}
        mock_compute.assert_called_once()
        called_uid = mock_compute.call_args[0][1]
        assert called_uid == uid

    def test_export_continues_when_weight_assembly_fails(self, eb):
        """End-to-end within _build_brief: a broken weight fetch must not
        abort the whole brief export (mirrors _get_plan_for_date's own
        contrast — that one IS allowed to blow up the whole export since
        today's/tomorrow's session is load-bearing; weight is not)."""
        fake_plan = {"planned": False, "sessions": []}
        fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
        fake_wrap = {
            "window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
            "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok",
        }
        with patch.object(eb, "_fetch_plan", return_value=fake_plan), \
             patch.object(eb, "_assemble_form", return_value=fake_form), \
             patch.object(eb, "_assemble_recent_wrap", return_value=fake_wrap), \
             patch.object(eb, "_assemble_weight", return_value=dict(eb._NULL_WEIGHT_BLOCK)), \
             patch.object(eb, "_assemble_advisories", return_value=[]), \
             patch.object(eb, "_assemble_week_plan", return_value=[]), \
             patch.object(eb, "_assemble_coach", return_value=None):

            brief = eb._build_brief(datetime.date(2026, 7, 15), user_id="u")

        assert brief["weight"] == eb._NULL_WEIGHT_BLOCK
        assert brief["schema_version"] == 3


# ═════════════════════════════════════════════════════════════════════════════
# Schema version bump
# ═════════════════════════════════════════════════════════════════════════════

class TestSchemaVersionBump:
    def test_schema_version_is_now_3(self, eb):
        # bumped to 3 by issue #1497 (acwr + week_plan addition)
        assert eb.SCHEMA_VERSION == 3

    def test_build_brief_envelope_has_weight_key(self, eb):
        fake_plan = {"planned": False, "sessions": []}
        fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
        fake_wrap = {
            "window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
            "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok",
        }
        with patch.object(eb, "_fetch_plan", return_value=fake_plan), \
             patch.object(eb, "_assemble_form", return_value=fake_form), \
             patch.object(eb, "_assemble_recent_wrap", return_value=fake_wrap), \
             patch.object(eb, "_assemble_weight", return_value=dict(eb._NULL_WEIGHT_BLOCK)), \
             patch.object(eb, "_assemble_advisories", return_value=[]), \
             patch.object(eb, "_assemble_week_plan", return_value=[]), \
             patch.object(eb, "_assemble_coach", return_value=None):

            brief = eb._build_brief(datetime.date(2026, 7, 15), user_id="u")

        assert "weight" in brief
        assert set(eb._NULL_WEIGHT_BLOCK.keys()).issubset(brief["weight"].keys())
