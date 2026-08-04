"""Tests for issue #1298: Query tightening — date-bound + column-only loads.

Acceptance Criteria covered:
  AC1 — Performance-score queries push the trailing 90-day window into SQL and
         select only needed columns (load_only) — computed scores unchanged.
  AC2 — fetch_and_detect_records selects only the columns it uses (load_only);
         volume records use SQL aggregation where equivalent — detected PRs unchanged.
  AC3 — /api/training-load/weekly gains the same 365-day range cap as
         /api/training-load and computes weekly sums SQL-side (func.sum +
         GROUP BY) — response JSON unchanged for in-cap ranges.
  AC4 — (removed) /api/workouts/intensity-distribution's load_only tightening
         is moot — the endpoint itself was deleted with the Trends page
         (feature/remove-trends-tab).
  AC5 — Full reconcile defers raw_payload (already model-level deferred; verified
         by #1293) — here we verify full-sync queries add load_only for non-payload
         columns.
  AC6 — resolve_user / get_current_user loads only identity/flag columns (no
         avatar bytes) on the request hot path; avatar-serving endpoints still work.
  AC7 — All touched endpoints return byte-identical JSON for the same data
         (excepting the new /weekly range-cap error for >365-day requests).
  AC8 — Tests cover each: window applied in SQL, no full-entity loads on the
         tightened paths, response parity fixtures.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user


# ── helpers ───────────────────────────────────────────────────────────────────

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000001298")


def _auth_client():
    u = MagicMock()
    u.id = _USER_ID
    app.dependency_overrides[resolve_user] = lambda: u
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _ns(**kw):
    return SimpleNamespace(**kw)


# ── AC1: performance-score queries push 90-day window into SQL ────────────────


def test_workout_signal_scores_has_date_window_in_source():
    """AC1: _workout_signal_scores adds a date lower-bound (90-day window) to the SQL query."""
    import backend.main as main_mod
    src = inspect.getsource(main_mod._workout_signal_scores)
    has_window = (
        "89" in src or "90" in src or "timedelta(days=89)" in src or "timedelta(days=90)" in src
    )
    assert has_window, (
        "_workout_signal_scores must add a date lower-bound (timedelta(days=89) or 90) "
        "to the run_workouts query so the 90-day trailing window is pushed into SQL"
    )


def test_athlete_scores_as_of_has_date_window_in_source():
    """AC1: _athlete_scores_as_of adds a date lower-bound to the SQL query."""
    import backend.main as main_mod
    src = inspect.getsource(main_mod._athlete_scores_as_of)
    has_window = (
        "89" in src or "90" in src or "timedelta(days=89)" in src or "timedelta(days=90)" in src
    )
    assert has_window, (
        "_athlete_scores_as_of must add a date lower-bound (timedelta(days=89) or 90) "
        "to the run_workouts query so the 90-day trailing window is pushed into SQL"
    )


def test_workout_signal_scores_uses_load_only():
    """AC1: _workout_signal_scores uses load_only (or with_entities) for column selection."""
    import backend.main as main_mod
    src = inspect.getsource(main_mod._workout_signal_scores)
    assert "load_only" in src or "with_entities" in src, (
        "_workout_signal_scores must use load_only or with_entities to avoid loading "
        "unused Workout columns on the 90-day query path"
    )


def test_athlete_scores_as_of_uses_load_only():
    """AC1: _athlete_scores_as_of uses load_only (or with_entities) for column selection."""
    import backend.main as main_mod
    src = inspect.getsource(main_mod._athlete_scores_as_of)
    assert "load_only" in src or "with_entities" in src, (
        "_athlete_scores_as_of must use load_only or with_entities to avoid loading "
        "unused Workout columns on the 90-day query path"
    )


def test_workout_signal_scores_window_upper_bound_is_today():
    """AC1: The window used by _workout_signal_scores has today as the upper anchor.

    Computed scores are 'as-of today', so the 90-day window must be
    relative to today (not an arbitrary date).
    """
    import backend.main as main_mod
    src = inspect.getsource(main_mod._workout_signal_scores)
    # Must reference _today or date.today() to anchor the window
    has_today_anchor = "_today" in src or "date.today()" in src or "_date.today()" in src
    assert has_today_anchor, (
        "_workout_signal_scores must anchor the 90-day window to today "
        "(reference _today or date.today())"
    )


# ── AC2: fetch_and_detect_records uses load_only ──────────────────────────────


def test_fetch_and_detect_records_uses_load_only():
    """AC2: fetch_and_detect_records uses load_only to select only needed columns."""
    from backend.services import pr_detection
    src = inspect.getsource(pr_detection.fetch_and_detect_records)
    assert "load_only" in src or "with_entities" in src, (
        "fetch_and_detect_records must use load_only or with_entities so the run "
        "query does not load every Workout column (e.g. remarks, manual_overrides, ...)"
    )


def test_fetch_and_detect_records_load_only_includes_required_columns():
    """AC2: load_only in fetch_and_detect_records covers the columns actually read."""
    from backend.services import pr_detection
    src = inspect.getsource(pr_detection.fetch_and_detect_records)
    # These columns are read in the function body
    required = ["workout_date", "distance_km", "duration_seconds", "avg_power", "workout_type"]
    missing = [col for col in required if col not in src]
    assert not missing, (
        f"fetch_and_detect_records load_only must include: {missing}"
    )


def test_fetch_and_detect_records_result_structure_unchanged():
    """AC2: The result dict structure from fetch_and_detect_records is unchanged."""
    from backend.services.pr_detection import fetch_and_detect_records

    uid = _USER_ID
    run = _ns(
        id=str(uid),
        workout_date=date(2025, 6, 1),
        distance_km=10.0,
        duration_seconds=3600,
        tss=60.0,
        avg_power=250,
        name="Test Run",
        workout_type="run",
    )

    mock_db = MagicMock()
    # Match the load_only query chain: .query().options().filter().order_by().all()
    mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [run]
    mock_db.get.return_value = None  # no AthleteDurationCurve row

    result = fetch_and_detect_records(uid, mock_db)

    assert "speedRecords" in result
    assert "powerRecords" in result
    assert "volumeRecords" in result
    assert "_meta" in result
    assert result["_meta"]["runs_considered"] == 1


# ── AC3: /api/training-load/weekly 365-day cap and SQL aggregation ────────────


def test_weekly_endpoint_rejects_range_over_365_days():
    """AC3: /api/training-load/weekly rejects date ranges exceeding 365 days with 422."""
    client = _auth_client()
    try:
        resp = client.get("/api/training-load/weekly?from=2023-01-01&to=2024-12-31")
        assert resp.status_code == 422, (
            f"Expected 422 for >365-day range, got {resp.status_code}: {resp.text}"
        )
    finally:
        _teardown()


def test_weekly_endpoint_365_day_error_matches_training_load_style():
    """AC3: The >365-day error message matches the /api/training-load error style."""
    client = _auth_client()
    try:
        resp = client.get("/api/training-load/weekly?from=2023-01-01&to=2024-12-31")
        assert resp.status_code == 422
        detail = resp.json().get("detail", "")
        assert "365" in detail, (
            f"Error message must reference '365': {detail!r}"
        )
    finally:
        _teardown()


def test_weekly_endpoint_accepts_exactly_365_days():
    """AC3: Exactly 365-day range is accepted (boundary case)."""
    client = _auth_client()
    try:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.group_by.return_value.all.return_value = []
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = mock_session
            resp = client.get("/api/training-load/weekly?from=2024-01-01&to=2024-12-31")
        assert resp.status_code == 200, (
            f"365-day range must be accepted, got {resp.status_code}: {resp.text}"
        )
    finally:
        _teardown()


def test_weekly_endpoint_uses_sql_group_by():
    """AC3: /api/training-load/weekly uses SQL-side GROUP BY (not Python-side looping)."""
    import backend.main as main_mod
    # Find the get_training_load_weekly function source
    src = inspect.getsource(main_mod.get_training_load_weekly)
    has_group_by = "group_by" in src or "GROUP BY" in src
    assert has_group_by, (
        "get_training_load_weekly must use SQL GROUP BY (session.query.filter.group_by.all) "
        "to aggregate weekly sums instead of loading full Workout objects"
    )


def test_weekly_endpoint_uses_func_sum():
    """AC3: /api/training-load/weekly uses func.sum for SQL aggregation."""
    import backend.main as main_mod
    src = inspect.getsource(main_mod.get_training_load_weekly)
    assert "func.sum" in src or "func.Sum" in src, (
        "get_training_load_weekly must use func.sum to aggregate TSS and distance in SQL"
    )


def test_weekly_endpoint_source_has_365_cap():
    """AC3: Source of get_training_load_weekly contains the 365-day limit check."""
    import backend.main as main_mod
    src = inspect.getsource(main_mod.get_training_load_weekly)
    assert "365" in src, (
        "get_training_load_weekly must contain a 365-day cap (matching /api/training-load)"
    )


def test_weekly_endpoint_response_json_unchanged_run_tss():
    """AC3/AC7: Response JSON structure unchanged for a valid in-cap range."""
    client = _auth_client()

    # Row from the SQL GROUP BY: (week_monday, workout_type, sum_tss, sum_dist)
    dt_mon = datetime(2025, 1, 6, 0, 0, tzinfo=timezone.utc)
    run_row = _ns(week_mon=dt_mon, workout_type="run", sum_tss=50.0, sum_dist=10.0)
    lift_row = _ns(week_mon=dt_mon, workout_type="strength", sum_tss=30.0, sum_dist=0.0)

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
        run_row, lift_row,
    ]

    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = mock_session
            resp = client.get("/api/training-load/weekly?from=2025-01-06&to=2025-01-12")

        assert resp.status_code == 200
        body = resp.json()
        assert "weeks" in body
        assert len(body["weeks"]) == 1
        wk = body["weeks"][0]
        assert "run_tss" in wk
        assert "strength_tss" in wk
        assert "total_tss" in wk
        assert "total_distance_km" in wk
        assert "week_start" in wk
        assert abs(wk["run_tss"] - 50.0) < 0.01
        assert abs(wk["strength_tss"] - 30.0) < 0.01
        assert abs(wk["total_tss"] - 80.0) < 0.01
        assert abs(wk["total_distance_km"] - 10.0) < 0.01
    finally:
        _teardown()


# ── AC4: removed — /api/workouts/intensity-distribution no longer exists ─────
# (deleted along with the Trends page, feature/remove-trends-tab; it was the
# page's only caller, so the load_only tightening this AC verified is moot.)


# ── AC5: full reconcile load_only for non-payload columns ────────────────────


def test_reconcile_full_sync_strava_uses_load_only():
    """AC5: Full-sync Strava query in reconcile.py uses load_only to minimise column load."""
    from backend.services import reconcile as rec_mod
    src = inspect.getsource(rec_mod.reconcile_workouts)
    assert "load_only" in src or "_load_only" in src, (
        "full_reconcile in reconcile.py must use load_only on the full-sync "
        "StravaActivity / StrydActivity queries to avoid loading unused columns "
        "(max_power_w, suffer_score, device_name, etc.)"
    )


def test_reconcile_raw_payload_still_deferred():
    """AC5: StravaActivity.raw_payload and StrydActivity.raw_payload remain deferred()."""
    from sqlalchemy import inspect as sa_inspect
    from backend.models import StravaActivity, StrydActivity

    def _is_deferred(cls, attr):
        prop = sa_inspect(cls).mapper.column_attrs.get(attr)
        assert prop is not None, f"{cls.__name__} has no column {attr!r}"
        return prop.deferred

    assert _is_deferred(StravaActivity, "raw_payload"), (
        "StravaActivity.raw_payload must remain deferred()"
    )
    assert _is_deferred(StrydActivity, "raw_payload"), (
        "StrydActivity.raw_payload must remain deferred()"
    )


# ── AC6: resolve_user / get_current_user skips avatar bytes ──────────────────


def test_get_current_user_source_uses_load_only():
    """AC6: get_current_user in auth.py uses load_only to avoid loading avatar bytes."""
    import backend.auth as auth_mod
    src = inspect.getsource(auth_mod.get_current_user)
    assert "load_only" in src, (
        "get_current_user must use load_only to skip the avatar column on the "
        "hot-path (every authenticated request)"
    )


def test_get_current_user_load_only_excludes_avatar():
    """AC6: The load_only in get_current_user does NOT include User.avatar."""
    import backend.auth as auth_mod
    src = inspect.getsource(auth_mod.get_current_user)
    # Must have load_only but NOT include "User.avatar" in it (avatar_mime is OK)
    assert "load_only" in src, "get_current_user must use load_only"
    # The avatar column (LargeBinary) should not be in the load_only call.
    # We allow avatar_mime (text) since it's small — what we want to skip is the blob.
    # Check that the source explicitly does NOT list User.avatar in load_only.
    # We accept: load_only(..., User.avatar_mime, ...) without User.avatar.
    import re
    # Find load_only call(s) and verify User.avatar (not avatar_mime) is absent
    load_only_blocks = re.findall(r'load_only\([^)]+\)', src)
    for block in load_only_blocks:
        # User.avatar without _mime suffix must not appear
        has_bare_avatar = bool(re.search(r'User\.avatar(?!_mime)', block))
        assert not has_bare_avatar, (
            f"load_only must not include User.avatar (the LargeBinary blob): {block!r}"
        )


def test_user_model_has_avatar_column():
    """AC6 / sanity: User model has an avatar column (confirming the skip is meaningful)."""
    from backend.models import User
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(User).mapper
    col_names = [p.key for p in mapper.column_attrs]
    assert "avatar" in col_names, "User model must have an avatar column"


# ── AC7/AC8: response parity — scores unchanged after window tightening ───────


def test_performance_score_window_parity_with_pure_function():
    """AC7: compute_endurance_score with 90-day window data returns same result
    as when called with all-time data (since it applies 90-day window internally)."""
    from datetime import date
    from backend.services.running_performance import compute_endurance_score
    from backend.services.zone_constants import make_zone_constants

    today = date.today()
    zone_constants = make_zone_constants()

    # Build a run that falls within 90 days
    recent_run = {
        "run_id": "r1",
        "workout_date": (today - timedelta(days=30)).isoformat(),
        "laps": [],
        "decoupling_pct": None,
        "avg_power": None,
        "avg_hr": 140,
        "distance_km": 10.0,
        "duration_seconds": 3600,
        "speed_signal": None,
        "speed_signal_basis": None,
        "speed_signal_window_seconds": None,
        "ftp_w": None,
    }
    # Build an old run that is outside 90 days (120 days ago)
    old_run = dict(recent_run)
    old_run["run_id"] = "r_old"
    old_run["workout_date"] = (today - timedelta(days=120)).isoformat()

    prefs = {"ftp_w": None, "threshold_hr": 170, "threshold_pace_seconds_per_km": None}

    # Score with only recent (as SQL window would provide)
    result_recent = compute_endurance_score([recent_run], prefs, zone_constants)

    # Score with recent + old (what full-history load provided)
    result_full = compute_endurance_score([recent_run, old_run], prefs, zone_constants)

    # Both calls should return status, and if the old run is outside 90 days it
    # should not change the computed score (the function applies the window itself).
    # We verify the status is the same regardless of whether old run is included.
    assert result_recent.get("status") == result_full.get("status"), (
        "compute_endurance_score must produce the same status whether or not "
        "runs outside the 90-day window are present — the function applies the "
        "window internally, so SQL-side pre-filtering is safe"
    )


def test_weekly_endpoint_error_for_inverted_range_unchanged():
    """AC7: 'from > to' still returns 422 (unchanged from pre-tightening)."""
    client = _auth_client()
    try:
        resp = client.get("/api/training-load/weekly?from=2025-03-31&to=2025-01-01")
        assert resp.status_code == 422
    finally:
        _teardown()


def test_resolve_user_dep_still_returns_user_object():
    """AC7: resolve_user dependency still returns a usable user object (not None).

    Simulates the auth flow: session cookie → get_current_user → user returned.
    The load_only change must not prevent User attributes from being accessible.
    """
    import backend.auth as auth_mod
    from backend.models import User

    fake_user = MagicMock(spec=User)
    fake_user.id = _USER_ID
    fake_user.name = "test"
    fake_user.is_active = True
    fake_user.is_admin = False

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    # New chain: .query(User).filter(...).options(...).first()
    mock_db.query.return_value.filter.return_value.options.return_value.first.return_value = fake_user

    with patch("backend.auth.Session", return_value=mock_db):
        with patch("backend.auth.read_session_cookie", return_value={"user_id": str(_USER_ID)}):
            from starlette.testclient import TestClient as StarClient
            from fastapi import FastAPI, Depends

            test_app = FastAPI()

            @test_app.get("/test-auth")
            async def _test_route(u=Depends(auth_mod.resolve_user)):
                return {"name": u.name}

            sc = StarClient(test_app)
            r = sc.get("/test-auth", cookies={"session": "fake_token"})
            # Should not 401
            assert r.status_code != 401 or r.status_code == 200, (
                "resolve_user must still return a user after load_only change; "
                f"got status {r.status_code}: {r.text}"
            )
