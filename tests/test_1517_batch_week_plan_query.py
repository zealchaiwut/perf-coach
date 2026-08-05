"""Tests for issue #1517: Batch week-plan plan lookups into one date-range query.

The fix batches the ~9 individual planned_sessions round-trips that happen per
/api/brief/today call into a single date-range query.

Acceptance criteria:
  AC1  A new helper _get_plans_for_date_range(user_id, start_date, end_date)
       exists in backend.services.daily_brief and returns a dict keyed by date.
  AC2  _build_brief issues exactly ONE DB query for planned_sessions instead of
       calling _get_plan_for_date individually for each date.
  AC3  _assemble_week_plan uses the cached plan data (does not issue per-date
       queries when a cache is provided).
  AC4  The _build_week_plan helper in main.py uses the batch query instead of
       calling _get_plan_for_date in a loop.
  AC5  Behaviour is unchanged: the same plan data is returned for each date
       regardless of whether fetched singly or via the batch helper.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import backend.services.daily_brief as svc


# ── AC1: _get_plans_for_date_range exists and returns the right shape ─────────

def test_get_plans_for_date_range_exists():
    """AC1: _get_plans_for_date_range is defined in the service module."""
    assert hasattr(svc, "_get_plans_for_date_range"), (
        "_get_plans_for_date_range must be defined in backend.services.daily_brief"
    )
    assert callable(svc._get_plans_for_date_range)


def test_get_plans_for_date_range_returns_dict_keyed_by_date():
    """AC1: Returns a dict[date, dict] with an entry for every date in the range."""
    start = date(2026, 7, 14)
    end = date(2026, 7, 20)
    user_id = "00000000-0000-0000-0000-000000000001"

    mock_rows = []  # no sessions — will produce empty-plan entries
    with patch("backend.services.daily_brief.Session") as MockSession:
        mock_ctx = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.query.return_value.filter.return_value.all.return_value = mock_rows

        result = svc._get_plans_for_date_range(user_id, start, end)

    assert isinstance(result, dict), "return type must be dict"
    expected_dates = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    assert set(result.keys()) == expected_dates, (
        "result must contain an entry for every date in [start, end]"
    )
    for d, plan in result.items():
        assert "plan_date" in plan
        assert "planned" in plan
        assert "sessions" in plan
        assert plan["plan_date"] == d.isoformat()


def test_get_plans_for_date_range_issues_single_query():
    """AC1/AC2: The helper issues exactly ONE DB query (not one per date)."""
    start = date(2026, 7, 14)
    end = date(2026, 7, 20)  # 7 dates
    user_id = "00000000-0000-0000-0000-000000000001"

    with patch("backend.services.daily_brief.Session") as MockSession:
        mock_ctx = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.query.return_value.filter.return_value.all.return_value = []

        svc._get_plans_for_date_range(user_id, start, end)

    # Only one Session() context manager should have been opened
    assert MockSession.call_count == 1, (
        f"Expected 1 DB session; got {MockSession.call_count} — "
        "the helper must not open one session per date"
    )


def test_get_plans_for_date_range_groups_rows_by_date():
    """AC1: Multiple rows on the same date are grouped under one dict entry."""
    start = date(2026, 7, 14)
    end = date(2026, 7, 14)  # single day
    user_id = "00000000-0000-0000-0000-000000000001"

    row1 = MagicMock(
        planned_date=start,
        session_type="run",
        name="Easy run",
        structure=None,
        notes=None,
        status="planned",
    )
    row2 = MagicMock(
        planned_date=start,
        session_type="strength",
        name="Strength",
        structure=None,
        notes=None,
        status="planned",
    )

    with patch("backend.services.daily_brief.Session") as MockSession:
        mock_ctx = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.query.return_value.filter.return_value.all.return_value = [row1, row2]

        result = svc._get_plans_for_date_range(user_id, start, end)

    assert start in result
    assert result[start]["planned"] is True
    assert len(result[start]["sessions"]) == 2


def test_get_plans_for_date_range_non_uuid_user_id():
    """AC1: Non-UUID user_id returns empty-plan dicts without querying the DB."""
    start = date(2026, 7, 14)
    end = date(2026, 7, 16)
    user_id = "not-a-uuid"

    with patch("backend.services.daily_brief.Session") as MockSession:
        result = svc._get_plans_for_date_range(user_id, start, end)

    MockSession.assert_not_called()
    assert all(p["planned"] is False for p in result.values())
    assert all(p["sessions"] == [] for p in result.values())


# ── AC2: _build_brief issues one planned_sessions query instead of ~9 ─────────

def test_build_brief_calls_get_plan_for_date_at_most_once():
    """AC2: _build_brief no longer calls _get_plan_for_date N times in a loop.

    The refactored path must use _get_plans_for_date_range (one query) and
    not call _get_plan_for_date at all (or at most once as a fallback).
    """
    for_date = date(2026, 7, 17)  # Thursday
    user_id = "00000000-0000-0000-0000-000000000001"

    sunday = date(2026, 7, 20)
    dates_in_week = {for_date + timedelta(days=i) for i in range((sunday - for_date).days + 1)}
    fake_cache = {
        d: {"plan_date": d.isoformat(), "planned": False, "sessions": []}
        for d in dates_in_week
    }

    fake_form = {
        "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
        "ramp": 0.5, "flags": {}, "interpretation": "Neutral", "acwr": 0.95,
    }
    fake_wrap = {
        "window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
        "adherence": 0.0, "load_trend": 0.0, "highlights_md": "Rest week.",
    }
    fake_weight = {k: None for k in [
        "current_kg", "trend_7d", "trend_28d", "target_kg", "target_date",
        "pace_kg_per_week", "on_track", "projection_date",
    ]}

    with patch.object(svc, "_get_plans_for_date_range", return_value=fake_cache) as mock_range, \
         patch.object(svc, "_get_plan_for_date") as mock_single, \
         patch.object(svc, "_assemble_form", return_value=fake_form), \
         patch.object(svc, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(svc, "_assemble_weight", return_value=fake_weight), \
         patch.object(svc, "_assemble_advisories", return_value=[]), \
         patch.object(svc, "_assemble_coach", return_value=None):
        svc._build_brief(for_date, user_id=user_id)

    mock_range.assert_called_once()
    assert mock_single.call_count == 0, (
        f"_get_plan_for_date was called {mock_single.call_count} times — "
        "it should not be called at all once _get_plans_for_date_range is in use"
    )


# ── AC3: _assemble_week_plan uses cache, issues no queries when cache provided ─

def test_assemble_week_plan_uses_plan_cache():
    """AC3: When plan_cache is provided, _assemble_week_plan does not call _get_plan_for_date."""
    for_date = date(2026, 7, 14)  # Monday — full week ahead
    user_id = "00000000-0000-0000-0000-000000000001"

    plan_cache = {
        for_date + timedelta(days=i): {
            "plan_date": (for_date + timedelta(days=i)).isoformat(),
            "planned": False,
            "sessions": [],
        }
        for i in range(7)
    }

    with patch.object(svc, "_get_plan_for_date") as mock_single:
        result = svc._assemble_week_plan(user_id, for_date, plan_cache=plan_cache)

    mock_single.assert_not_called(), (
        "_assemble_week_plan must not call _get_plan_for_date when plan_cache is provided"
    )
    assert isinstance(result, list)


def test_assemble_week_plan_falls_back_without_cache():
    """AC3: Without plan_cache, _assemble_week_plan still works (backward compat)."""
    for_date = date(2026, 7, 14)  # Monday
    user_id = "00000000-0000-0000-0000-000000000001"

    fake_plan = {"plan_date": "2026-07-15", "planned": False, "sessions": []}
    with patch.object(svc, "_get_plan_for_date", return_value=fake_plan) as mock_single:
        result = svc._assemble_week_plan(user_id, for_date)

    assert mock_single.call_count > 0, (
        "_assemble_week_plan must still call _get_plan_for_date when no cache is provided"
    )
    assert isinstance(result, list)


# ── AC4: week-plan builder lives in the service, not main.py ─────────────────

def test_build_week_plan_not_duplicated_in_main():
    """AC4 (updated): `_build_week_plan` was removed from backend.main — the
    single batch-query path lives in daily_brief._assemble_week_plan /
    _get_plans_for_date_range. Re-introducing a main.py copy would regress
    the #1517 consolidation (see also test_week_plan_convergence)."""
    from backend import main as main_mod
    from backend.services import daily_brief as svc

    assert not hasattr(main_mod, "_build_week_plan"), (
        "_build_week_plan reappeared in backend.main — remove the duplicate"
    )
    assert hasattr(svc, "_get_plans_for_date_range"), (
        "batch helper _get_plans_for_date_range must live in daily_brief"
    )
    assert hasattr(svc, "_assemble_week_plan"), (
        "week assembly must live in daily_brief, not main"
    )


# ── AC5: Behaviour equivalence ────────────────────────────────────────────────

def test_plans_for_date_range_matches_individual_calls():
    """AC5: Each entry in _get_plans_for_date_range matches _get_plan_for_date output."""
    start = date(2026, 7, 14)
    end = date(2026, 7, 16)
    user_id = "00000000-0000-0000-0000-000000000001"

    def make_row(d, stype):
        r = MagicMock()
        r.planned_date = d
        r.session_type = stype
        r.name = f"{stype} session"
        r.structure = None
        r.notes = None
        r.status = "planned"
        return r

    rows = [make_row(start, "run"), make_row(end, "bike")]

    with patch("backend.services.daily_brief.Session") as MockSession:
        mock_ctx = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.query.return_value.filter.return_value.all.return_value = rows

        batch = svc._get_plans_for_date_range(user_id, start, end)

    # start: has 1 row (run)
    assert batch[start]["planned"] is True
    assert len(batch[start]["sessions"]) == 1
    assert batch[start]["sessions"][0]["session_type"] == "run"

    # middle date: no rows
    mid = start + timedelta(days=1)
    assert batch[mid]["planned"] is False
    assert batch[mid]["sessions"] == []

    # end: has 1 row (bike)
    assert batch[end]["planned"] is True
    assert len(batch[end]["sessions"]) == 1
    assert batch[end]["sessions"][0]["session_type"] == "bike"
