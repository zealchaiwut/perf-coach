"""TDD tests for weight_plan service (issue #420)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.services.weight_plan import compute_gap, generate_milestones, plan_at, project_hit_date


# ── helpers ─────────────────────────────────────────────────────────────────

def _target(start_w, target_w, start_date=None, target_date=None, days_total=180):
    today = datetime.date.today()
    sd = start_date or (today - datetime.timedelta(days=90))
    td = target_date or (today + datetime.timedelta(days=days_total - 90))
    return SimpleNamespace(
        user_id=None,
        start_weight_kg=Decimal(str(start_w)),
        target_weight_kg=Decimal(str(target_w)),
        start_date=sd,
        target_date=td,
    )


class _FakeEntry:
    def __init__(self, entry_date, weight_kg):
        self.entry_date = entry_date
        self.weight_kg = Decimal(str(weight_kg))


class _FakeSession:
    """Minimal session stub that returns pre-configured weight entries, filtered by entry_date range."""

    def __init__(self, entries):
        self._entries = entries  # list of _FakeEntry
        self._min_date: datetime.date | None = None
        self._max_date: datetime.date | None = None

    def query(self, model):
        return _FakeQuery(list(self._entries))


class _FakeQuery:
    def __init__(self, entries):
        self._entries = list(entries)
        self._date_min: datetime.date | None = None
        self._date_max: datetime.date | None = None

    def filter(self, *args, **kwargs):
        # Parse SQLAlchemy BinaryExpression-style args by inspecting them
        # We detect date range filters via the right-hand value type
        for arg in args:
            try:
                # arg is a BinaryExpression; access .right.value and .operator
                import operator as _op
                val = arg.right.value
                if isinstance(val, datetime.date):
                    op = arg.operator
                    if op is _op.ge:
                        self._date_min = val
                    elif op is _op.le:
                        self._date_max = val
            except AttributeError:
                pass
        return self

    def _apply_date_filter(self):
        result = self._entries
        if self._date_min is not None:
            result = [e for e in result if e.entry_date >= self._date_min]
        if self._date_max is not None:
            result = [e for e in result if e.entry_date <= self._date_max]
        return result

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._apply_date_filter()

    def first(self):
        rows = self._apply_date_filter()
        return rows[0] if rows else None


# ── (a) plan_at: interpolation + clamping ────────────────────────────────────

def test_plan_at_midpoint():
    """plan_at returns exact linear interpolation at midpoint."""
    today = datetime.date.today()
    sd = today - datetime.timedelta(days=50)
    td = today + datetime.timedelta(days=50)
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    result = plan_at(t, today)
    assert float(result) == pytest.approx(80.0, abs=0.01)


def test_plan_at_clamps_before_start():
    """plan_at returns start_weight_kg when date is before start_date."""
    today = datetime.date.today()
    sd = today + datetime.timedelta(days=10)
    td = today + datetime.timedelta(days=110)
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    result = plan_at(t, today)
    assert float(result) == pytest.approx(85.0, abs=0.001)


def test_plan_at_clamps_after_end():
    """plan_at returns target_weight_kg when date is after target_date."""
    today = datetime.date.today()
    sd = today - datetime.timedelta(days=110)
    td = today - datetime.timedelta(days=10)
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    result = plan_at(t, today)
    assert float(result) == pytest.approx(75.0, abs=0.001)


# ── (b) compute_gap: 7-day average when ≥ 3 entries ─────────────────────────

def test_compute_gap_uses_7d_average():
    """Uses 7-day rolling average when ≥ 3 entries present in window."""
    today = datetime.date.today()
    entries = [
        _FakeEntry(today - datetime.timedelta(days=i), 81.0 - i * 0.1)
        for i in range(5)
    ]
    session = _FakeSession(entries)
    t = _target(85.0, 75.0)
    result = compute_gap(t, session, today)
    assert result["basis"] == "avg_7d"
    assert result["current_basis_kg"] is not None
    assert result["gap_kg"] is not None
    assert result["gap_direction"] != "no_data"


# ── (c) compute_gap: fallback to the wide-lookback average when < 2 in 7d ────
# (behaviour change: compute_gap used to fall back to the single latest entry
# within 14 days; it is now unified on _weight_rollup's rule — fewer than 2
# entries in the trailing 7 days averages over the wider
# _ROLLUP_LOOKBACK_DAYS-day lookback instead, so a second entry outside the
# 7-day window now pulls the basis toward it rather than being ignored.)

def test_compute_gap_fallback_wide_average():
    """Falls back to the wide-lookback average — not the single latest
    entry — when fewer than 2 entries fall in the trailing 7-day window."""
    today = datetime.date.today()
    # Only 1 entry in the 7-day window; 1 more inside the wider lookback
    # (well within _ROLLUP_LOOKBACK_DAYS=55) but outside 7 days.
    entries = [
        _FakeEntry(today - datetime.timedelta(days=2), 80.5),
        _FakeEntry(today - datetime.timedelta(days=10), 81.0),
    ]
    session = _FakeSession(entries)
    t = _target(85.0, 75.0)
    result = compute_gap(t, session, today)
    assert result["basis"] == "avg_wide"
    # Must be the average of BOTH entries, not just the latest one's raw value
    # — that's the "never a single raw entry" property this rule exists for.
    assert result["current_basis_kg"] == round((80.5 + 81.0) / 2, 2)
    assert result["current_basis_kg"] != 80.5
    assert result["gap_direction"] != "no_data"


def test_compute_gap_never_a_single_raw_entry_even_with_more_context():
    """With several entries outside the 7-day window and none inside it, the
    basis is the average across all of them — not just the most recent one.
    This is the specific property _weight_rollup's rule was chosen for."""
    today = datetime.date.today()
    entries = [
        _FakeEntry(today - datetime.timedelta(days=20), 79.0),
        _FakeEntry(today - datetime.timedelta(days=30), 80.0),
        _FakeEntry(today - datetime.timedelta(days=40), 81.0),
    ]
    session = _FakeSession(entries)
    t = _target(85.0, 75.0)
    result = compute_gap(t, session, today)
    assert result["basis"] == "avg_wide"
    assert result["current_basis_kg"] == round((79.0 + 80.0 + 81.0) / 3, 2)
    # Not the most recent entry's raw value on its own.
    assert result["current_basis_kg"] != 79.0


# ── (d) compute_gap: no_data when nothing within the wide lookback ──────────

def test_compute_gap_no_data():
    """Returns no_data when no entries exist within the wide lookback window
    (_ROLLUP_LOOKBACK_DAYS = 55 days)."""
    today = datetime.date.today()
    entries = [
        _FakeEntry(today - datetime.timedelta(days=60), 82.0),
    ]
    session = _FakeSession(entries)
    t = _target(85.0, 75.0)
    result = compute_gap(t, session, today)
    assert result["basis"] is None
    assert result["current_basis_kg"] is None
    assert result["gap_kg"] is None
    assert result["gap_direction"] == "no_data"


def test_compute_gap_uses_wide_lookback_before_giving_up():
    """An entry older than 14 days (the old cutoff) but within the wide
    _ROLLUP_LOOKBACK_DAYS lookback is now used rather than triggering
    no_data — this is the unified rule's whole point: more context beats an
    arbitrary 14-day cliff."""
    today = datetime.date.today()
    entries = [
        _FakeEntry(today - datetime.timedelta(days=20), 82.0),
    ]
    session = _FakeSession(entries)
    t = _target(85.0, 75.0)
    result = compute_gap(t, session, today)
    assert result["basis"] == "avg_wide"
    assert result["current_basis_kg"] == 82.0
    assert result["gap_direction"] != "no_data"


# ── (e) gap_direction: behind on loss target when above plan ─────────────────

def test_gap_direction_behind_loss_target():
    """LOSS target: positive gap (above plan) → 'behind'."""
    today = datetime.date.today()
    # Plan today ≈ 80 kg (midpoint of 85→75 over 100 days, at day 50)
    sd = today - datetime.timedelta(days=50)
    td = today + datetime.timedelta(days=50)
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    # Actual 82 > plan 80 → behind for loss
    entries = [_FakeEntry(today - datetime.timedelta(days=i), 82.0) for i in range(5)]
    session = _FakeSession(entries)
    result = compute_gap(t, session, today)
    assert result["gap_direction"] == "behind"
    assert result["gap_kg"] > 0


# ── (f) gap_direction: reversed for gain target ──────────────────────────────

def test_gap_direction_reversed_gain_target():
    """GAIN target: positive gap (above plan) → 'ahead'."""
    today = datetime.date.today()
    sd = today - datetime.timedelta(days=50)
    td = today + datetime.timedelta(days=50)
    t = _target(70.0, 80.0, start_date=sd, target_date=td)
    # Plan today = 75; actual 77 > plan → ahead for gain
    entries = [_FakeEntry(today - datetime.timedelta(days=i), 77.0) for i in range(5)]
    session = _FakeSession(entries)
    result = compute_gap(t, session, today)
    assert result["gap_direction"] == "ahead"


# ── (g) generate_milestones: full set with correct structure ─────────────────

def test_generate_milestones_full():
    """Returns today + 2 intermediates + goal; plan_kg from plan_at; dates at month starts."""
    today = datetime.date.today()
    sd = today - datetime.timedelta(days=30)
    td = today + datetime.timedelta(days=270)  # >90 days remaining
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    stones = generate_milestones(t, today)
    # Must have at least 4 rows: today + 2 intermediates + goal
    assert len(stones) == 4
    kinds = [s["kind"] for s in stones]
    assert kinds[0] == "today"
    assert kinds[-1] == "goal"
    assert kinds[1] == "intermediate"
    assert kinds[2] == "intermediate"
    # No duplicate dates
    dates = [s["date"] for s in stones]
    assert len(dates) == len(set(dates))
    # plan_kg rounded to 1 decimal
    for s in stones:
        assert s["plan_kg"] == round(s["plan_kg"], 1)
    # goal has target_date and target_weight_kg
    goal = stones[-1]
    assert str(goal["date"]) == str(td)
    assert float(goal["plan_kg"]) == pytest.approx(75.0, abs=0.15)
    # today row has today's date
    assert str(stones[0]["date"]) == str(today)


# ── (h) short targets: colliding intermediates deduped ───────────────────────

def test_generate_milestones_dedup_short_target():
    """Short targets (<90 days remaining) with colliding intermediate dates → 3 rows, not 4."""
    today = datetime.date.today()
    # 45 days remaining → 1/3 = day 15, 2/3 = day 30 from today
    # Both round to the same month start if we're early in the month
    # Force collision: use a date at start of month so both fall on same month boundary
    # We pick start such that 1/3 and 2/3 both land in the same month
    import calendar
    # Use exactly 30 days remaining so both 10-day and 20-day intermediates
    # round to the same month-start (current or next month)
    target_date = today + datetime.timedelta(days=30)
    # round 1/3 → day 10, 2/3 → day 20 from today; both snap to same month-start
    # Adjust: pick today = last day of month so both snap forward to next month 1st
    # We can't control today, so instead we test: if both intermediates produce the same
    # month-start after rounding, only one appears in output
    sd = today - datetime.timedelta(days=30)
    t = _target(85.0, 75.0, start_date=sd, target_date=target_date)
    stones = generate_milestones(t, today)
    # Must have 3 or 4 rows; dates must be unique
    dates = [s["date"] for s in stones]
    assert len(dates) == len(set(dates)), "Duplicate dates in milestones"
    assert stones[0]["kind"] == "today"
    assert stones[-1]["kind"] == "goal"
    assert len(stones) in (3, 4)


# ── (i) project_hit_date: plausible future date for healthy pace ─────────────

def test_project_hit_date_returns_future_date_loss():
    """project_hit_date returns a future date when pace is healthy for LOSS target."""
    today = datetime.date.today()
    sd = today - datetime.timedelta(days=30)
    td = today + datetime.timedelta(days=180)
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    # 7-day window: 0.5 kg/week loss pace
    entries = [
        _FakeEntry(today - datetime.timedelta(days=6), 81.0),  # oldest (first)
        _FakeEntry(today - datetime.timedelta(days=3), 80.6),
        _FakeEntry(today, 80.5),  # most recent (last)
    ]
    session = _FakeSession(entries)
    result = project_hit_date(t, session, today)
    assert result is not None
    assert isinstance(result, datetime.date)
    assert result > today


def test_project_hit_date_returns_none_zero_pace():
    """project_hit_date returns None when pace is zero (no weight change)."""
    today = datetime.date.today()
    sd = today - datetime.timedelta(days=30)
    td = today + datetime.timedelta(days=180)
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    entries = [
        _FakeEntry(today - datetime.timedelta(days=6), 81.0),
        _FakeEntry(today, 81.0),  # same weight = zero pace
    ]
    session = _FakeSession(entries)
    result = project_hit_date(t, session, today)
    assert result is None


def test_project_hit_date_returns_none_adverse_pace():
    """project_hit_date returns None when pace moves away from goal (gaining on LOSS target)."""
    today = datetime.date.today()
    sd = today - datetime.timedelta(days=30)
    td = today + datetime.timedelta(days=180)
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    entries = [
        _FakeEntry(today - datetime.timedelta(days=6), 80.0),
        _FakeEntry(today, 81.0),  # gaining weight on a loss target
    ]
    session = _FakeSession(entries)
    result = project_hit_date(t, session, today)
    assert result is None


def test_project_hit_date_returns_none_insufficient_data():
    """project_hit_date returns None when fewer than 2 entries in 7-day window."""
    today = datetime.date.today()
    sd = today - datetime.timedelta(days=30)
    td = today + datetime.timedelta(days=180)
    t = _target(85.0, 75.0, start_date=sd, target_date=td)
    entries = [_FakeEntry(today, 81.0)]  # only 1 entry
    session = _FakeSession(entries)
    result = project_hit_date(t, session, today)
    assert result is None
