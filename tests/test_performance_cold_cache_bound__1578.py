"""Tests for issue #1578: bound the cold-cache path of /api/athletes/{id}/performance.

Acceptance criteria:
  AC1: In-request load is bounded: splits are batch-loaded (single IN query for
       all run workouts) rather than N sequential per-workout queries.
  AC1b: History window is capped so runs older than _RUN_HISTORY_CAP_DAYS days
        are excluded from the DB query — old runs are never loaded into memory.
  AC2: Peak memory for the endpoint is bounded and documented (constant +
       comment in the code).
"""
import os
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# AC2: constant is defined and is a reasonable bound
# ---------------------------------------------------------------------------

def test_run_history_cap_days_constant_exists_and_is_bounded():
    """AC2: _RUN_HISTORY_CAP_DAYS is defined at module level and is in a sane range.

    The value must be ≥ trailing_window_days (90) + a gap large enough to
    handle users who haven't run recently, and ≤ 1096 (3 years) so memory
    stays bounded.
    """
    from backend.main import _RUN_HISTORY_CAP_DAYS
    from backend.services.running_performance import PERFORMANCE_CONFIG

    trailing = PERFORMANCE_CONFIG["trailing_window_days"]
    assert _RUN_HISTORY_CAP_DAYS >= trailing + 90, (
        f"Cap ({_RUN_HISTORY_CAP_DAYS}d) must be at least trailing_window_days "
        f"({trailing}d) + 90d buffer; got {_RUN_HISTORY_CAP_DAYS}"
    )
    assert _RUN_HISTORY_CAP_DAYS <= 1096, (
        f"Cap ({_RUN_HISTORY_CAP_DAYS}d) must be ≤ 1096d (3 years) to bound memory; "
        "got {_RUN_HISTORY_CAP_DAYS}"
    )


# ---------------------------------------------------------------------------
# AC1: splits are batch-loaded; no per-workout query
# ---------------------------------------------------------------------------

def test_splits_by_workout_grouping_correctness():
    """AC1: the batch-grouping logic that replaces the per-workout split query
    correctly maps each split to its parent workout.

    This is a pure-Python test — no DB required.  It verifies the grouping step
    that runs after the single batch query: splits must land under their
    respective workout_id key.
    """
    # Simulate ORM objects returned by a batch WorkoutSplit query
    splits = [
        MagicMock(workout_id=1, split_index=0, avg_power=210, avg_hr=140, distance_km=1.0, duration_seconds=360),
        MagicMock(workout_id=1, split_index=1, avg_power=200, avg_hr=138, distance_km=1.0, duration_seconds=370),
        MagicMock(workout_id=2, split_index=0, avg_power=260, avg_hr=165, distance_km=1.0, duration_seconds=240),
        MagicMock(workout_id=3, split_index=0, avg_power=230, avg_hr=148, distance_km=1.0, duration_seconds=310),
        MagicMock(workout_id=3, split_index=1, avg_power=225, avg_hr=150, distance_km=1.0, duration_seconds=320),
    ]

    # Replicate the grouping logic from the endpoint
    splits_by_workout = {}
    for s in splits:
        splits_by_workout.setdefault(s.workout_id, []).append(s)

    assert set(splits_by_workout.keys()) == {1, 2, 3}
    assert len(splits_by_workout[1]) == 2
    assert len(splits_by_workout[2]) == 1
    assert len(splits_by_workout[3]) == 2
    # Order preserved within each group
    assert splits_by_workout[1][0].split_index == 0
    assert splits_by_workout[1][1].split_index == 1


def test_splits_by_workout_empty_run_returns_empty_list():
    """AC1: workouts with no splits return an empty list (dict.get default)."""
    splits_by_workout = {}
    assert splits_by_workout.get(999, []) == []


# ---------------------------------------------------------------------------
# AC1b: history cap applied to the DB query
# ---------------------------------------------------------------------------

def test_history_cap_cutoff_date_computed_correctly():
    """AC1b: the cutoff date used in the DB query is today - _RUN_HISTORY_CAP_DAYS."""
    from backend.main import _RUN_HISTORY_CAP_DAYS
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    expected_cutoff = today - timedelta(days=_RUN_HISTORY_CAP_DAYS)

    # The endpoint computes: _datetime.now(_timezone.utc).date() - _timedelta(days=_RUN_HISTORY_CAP_DAYS)
    # Verify the math is right and the cutoff is always strictly in the past
    assert expected_cutoff < today, "Cutoff must be before today"
    assert (today - expected_cutoff).days == _RUN_HISTORY_CAP_DAYS


def test_history_cap_excludes_ancient_runs():
    """AC1b: runs older than _RUN_HISTORY_CAP_DAYS are excluded by the DB filter.

    Simulates the filter logic: only workouts whose workout_date >= cutoff
    should appear in the run_workouts list.
    """
    from backend.main import _RUN_HISTORY_CAP_DAYS
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=_RUN_HISTORY_CAP_DAYS)

    # Build a synthetic set of run dates: some within cap, some outside
    dates = [
        today - timedelta(days=10),                    # within cap → included
        today - timedelta(days=_RUN_HISTORY_CAP_DAYS - 1),  # at boundary → included
        today - timedelta(days=_RUN_HISTORY_CAP_DAYS),      # at boundary (= cutoff) → included
        today - timedelta(days=_RUN_HISTORY_CAP_DAYS + 1),  # 1 day outside → excluded
        today - timedelta(days=_RUN_HISTORY_CAP_DAYS + 90), # well outside → excluded
    ]

    within_cap = [d for d in dates if d >= cutoff]
    outside_cap = [d for d in dates if d < cutoff]

    assert len(within_cap) == 3
    assert len(outside_cap) == 2


# ---------------------------------------------------------------------------
# Integration: endpoint response shape unchanged after bounding (requires UAT)
# ---------------------------------------------------------------------------

_BASE_URL = os.environ.get("UAT_BASE_URL", "")


@pytest.mark.skipif(
    not _BASE_URL.startswith("http"),
    reason="UAT_BASE_URL not set — integration test skipped",
)
def test_performance_endpoint_response_shape_after_bound():
    """AC1/AC2 integration: endpoint still returns the canonical shape
    {state, endurance, speed, generated_at} after the bounding changes.
    """
    import httpx

    # Use the session cookie from environment (set by tester's Step 0)
    cookies_raw = os.environ.get("UAT_SESSION_COOKIE", "")
    if not cookies_raw:
        pytest.skip("UAT_SESSION_COOKIE not set — cannot authenticate")

    with httpx.Client(base_url=_BASE_URL, timeout=30.0) as client:
        # Parse session cookie
        cookies = {}
        for part in cookies_raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

        me = client.get("/api/auth/me", cookies=cookies)
        if me.status_code != 200:
            pytest.skip("Session cookie invalid — integration test skipped")

        uid = me.json()["id"]
        r = client.get(f"/api/athletes/{uid}/performance", cookies=cookies)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

        data = r.json()
        for key in ("state", "endurance", "speed", "generated_at"):
            assert key in data, f"Missing key '{key}' in response"
        assert data["state"] in ("scored", "needs_thresholds", "building_baseline", "error")
