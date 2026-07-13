"""Tests for issue #1366: Close the CTL/ATL calibration loop.

Acceptance criteria verified:
- AC1: resolve_user_ewma_days() is the single resolution helper — returns per-user
       ctl_days/atl_days from UserPreferences, defaulting to 42/7 when unset.
- AC2: Accepting calibration (POST /api/races/{id}/calibrate/accept) triggers a
       recompute/refresh of that user's training_load_snapshots.
- AC3: Snapshot rows record the constants used (ctl_days and atl_days columns).
- AC4: Users with no accepted calibration see byte-identical behavior to before
       (regression: default constants, snapshot cache still used).
- AC5: Tests — resolution helper, accept-triggers-recompute, default passthrough.
"""
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

from backend.services.training_load import (
    ATL_DAYS,
    CTL_DAYS,
    _FORMULA_VERSION,
    compute_load_curves,
    current_load,
    daily_update,
    resolve_user_ewma_days,
)

_USER_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_prefs(ctl_days=None, atl_days=None):
    p = MagicMock()
    p.ctl_days = ctl_days
    p.atl_days = atl_days
    return p


def _mock_session_with_prefs(prefs):
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.query.return_value.filter.return_value.first.return_value = prefs
    return sess


def _mock_session_no_snap():
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.query.return_value.filter.return_value.first.return_value = None
    return sess


def _make_series(n_days=50, tss=80):
    start = date(2024, 1, 1)
    return [(start + timedelta(days=i), tss) for i in range(n_days)]


# ---------------------------------------------------------------------------
# AC1 — resolve_user_ewma_days: single resolution helper
# ---------------------------------------------------------------------------

def test_resolve_returns_custom_ctl_atl_from_prefs():
    """AC1: resolve_user_ewma_days returns saved ctl_days/atl_days when set."""
    prefs = _mock_prefs(ctl_days=35, atl_days=5)
    with patch("backend.services.training_load.Session",
               return_value=_mock_session_with_prefs(prefs)):
        ctl, atl = resolve_user_ewma_days(_USER_ID)
    assert ctl == 35
    assert atl == 5


def test_resolve_defaults_when_no_prefs():
    """AC1: resolve_user_ewma_days returns (CTL_DAYS, ATL_DAYS) when prefs row is missing."""
    with patch("backend.services.training_load.Session",
               return_value=_mock_session_with_prefs(None)):
        ctl, atl = resolve_user_ewma_days(_USER_ID)
    assert (ctl, atl) == (CTL_DAYS, ATL_DAYS)


def test_resolve_defaults_when_prefs_columns_are_null():
    """AC1: resolve_user_ewma_days defaults when prefs exist but ctl_days/atl_days are NULL."""
    prefs = _mock_prefs(ctl_days=None, atl_days=None)
    with patch("backend.services.training_load.Session",
               return_value=_mock_session_with_prefs(prefs)):
        ctl, atl = resolve_user_ewma_days(_USER_ID)
    assert (ctl, atl) == (CTL_DAYS, ATL_DAYS)


# ---------------------------------------------------------------------------
# AC3 — Snapshot rows record ctl_days / atl_days
# ---------------------------------------------------------------------------

def _captured_upsert_row(mock_sess, engine_mock, series, ctl_days, atl_days):
    """Run daily_update and capture the dict passed to _pg_insert().values()."""
    import backend.services.training_load as tl_mod
    captured_rows = []

    original_pg_insert = tl_mod._pg_insert

    def _fake_pg_insert(model):
        stmt = MagicMock()
        stmt.excluded = MagicMock()

        def _values(rows):
            captured_rows.extend(rows)
            return stmt

        stmt.values = _values
        stmt.on_conflict_do_update = MagicMock(return_value=stmt)
        return stmt

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = series
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    engine_mock.connect.return_value = mock_conn

    with patch.object(tl_mod, "_pg_insert", _fake_pg_insert):
        daily_update(_USER_ID, target_date=date(2024, 1, 1) + timedelta(days=len(series) - 1),
                     ctl_days=ctl_days, atl_days=atl_days)

    return captured_rows


def test_daily_update_stores_ctl_atl_in_snapshot_row_custom():
    """AC3: daily_update writes ctl_days and atl_days into the snapshot row for custom constants."""
    series = _make_series(50, tss=80)
    mock_sess = _mock_session_no_snap()

    with (
        patch("backend.services.training_load.Session", return_value=mock_sess),
        patch("backend.services.training_load.engine") as mock_engine,
    ):
        rows = _captured_upsert_row(mock_sess, mock_engine, series, ctl_days=35, atl_days=5)

    assert rows, "daily_update must write a snapshot row even with custom calibration"
    row = rows[0]
    assert row["ctl_days"] == 35, f"Expected ctl_days=35, got {row.get('ctl_days')}"
    assert row["atl_days"] == 5, f"Expected atl_days=5, got {row.get('atl_days')}"


def test_daily_update_stores_ctl_atl_in_snapshot_row_default():
    """AC3/AC4: daily_update writes ctl_days and atl_days for default constants too."""
    series = _make_series(50, tss=80)
    mock_sess = _mock_session_no_snap()

    with (
        patch("backend.services.training_load.Session", return_value=mock_sess),
        patch("backend.services.training_load.engine") as mock_engine,
    ):
        rows = _captured_upsert_row(mock_sess, mock_engine, series, ctl_days=CTL_DAYS, atl_days=ATL_DAYS)

    assert rows
    row = rows[0]
    assert row["ctl_days"] == CTL_DAYS
    assert row["atl_days"] == ATL_DAYS


# ---------------------------------------------------------------------------
# AC4 — Default behavior unchanged
# ---------------------------------------------------------------------------

def test_current_load_uses_cache_when_constants_match_defaults():
    """AC4: current_load uses the snapshot cache for a user with default calibration (42/7)."""
    today = date(2024, 6, 1)
    snap = MagicMock()
    snap.snapshot_date = today
    snap.ctl = 55.5
    snap.atl = 40.2
    snap.tsb = 15.3
    snap.acwr = 1.1
    snap.formula_version = _FORMULA_VERSION
    snap.ctl_days = None   # NULL means defaults were used
    snap.atl_days = None

    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)
    mock_sess.query.return_value.filter.return_value.first.return_value = snap

    with (
        patch("backend.services.training_load.Session", return_value=mock_sess),
        patch("backend.services.training_load.resolve_user_ewma_days",
              return_value=(CTL_DAYS, ATL_DAYS)),
        patch("backend.services.training_load.daily_tss_series") as mock_series,
    ):
        result = current_load(_USER_ID, as_of=today)

    assert result == {"date": today, "ctl": 55.5, "atl": 40.2, "tsb": 15.3, "acwr": 1.1}
    mock_series.assert_not_called()


def test_current_load_bypasses_cache_when_ctl_days_mismatch():
    """AC1/AC3: current_load bypasses cache if snapshot ctl_days doesn't match user's calibration."""
    today = date(2024, 6, 1)
    # Snapshot was computed with old constants (42/7 stored as None)
    snap = MagicMock()
    snap.snapshot_date = today
    snap.ctl = 55.5
    snap.atl = 40.2
    snap.tsb = 15.3
    snap.acwr = 1.1
    snap.formula_version = _FORMULA_VERSION
    snap.ctl_days = None   # stored as defaults
    snap.atl_days = None

    # User now has custom calibration 35/7
    series = _make_series(50)

    mock_sess = _mock_session_no_snap()
    mock_sess.query.return_value.filter.return_value.first.return_value = snap

    with (
        patch("backend.services.training_load.Session", return_value=mock_sess),
        patch("backend.services.training_load.resolve_user_ewma_days",
              return_value=(35, 7)),
        patch("backend.services.training_load.daily_tss_series", return_value=series) as mock_series,
    ):
        result = current_load(_USER_ID, as_of=today)

    # Cache was bypassed — recomputed with 35-day EWMA, NOT the cached 55.5
    mock_series.assert_called()
    curves = compute_load_curves(series, ctl_days=35, atl_days=7)
    expected_ctl = curves[-1]["ctl"]
    assert abs(result["ctl"] - expected_ctl) < 0.01, (
        f"CTL should be recomputed with ctl_days=35, got {result['ctl']} vs expected {expected_ctl}"
    )
    assert result["ctl"] != 55.5, "Cache should not have been used"


def test_current_load_bypasses_cache_when_atl_days_mismatch():
    """AC1/AC3: current_load bypasses cache if snapshot atl_days doesn't match user's calibration."""
    today = date(2024, 6, 1)
    snap = MagicMock()
    snap.snapshot_date = today
    snap.ctl = 55.5
    snap.atl = 40.2
    snap.tsb = 15.3
    snap.acwr = 1.1
    snap.formula_version = _FORMULA_VERSION
    snap.ctl_days = 42   # stored correctly
    snap.atl_days = 7    # but user now has atl_days=5

    series = _make_series(50)
    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)
    mock_sess.query.return_value.filter.return_value.first.return_value = snap

    with (
        patch("backend.services.training_load.Session", return_value=mock_sess),
        patch("backend.services.training_load.resolve_user_ewma_days",
              return_value=(42, 5)),
        patch("backend.services.training_load.daily_tss_series", return_value=series) as mock_series,
    ):
        result = current_load(_USER_ID, as_of=today)

    mock_series.assert_called()
    assert result["ctl"] != 55.5, "Cache should not have been used when atl_days changed"


# ---------------------------------------------------------------------------
# AC2 — accept_calibration triggers recompute
# ---------------------------------------------------------------------------

def _make_authed_client(user_id_str):
    """Return (client, mock_user) with resolve_user overridden and CSRF set up."""
    import time
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user
    from backend.auth import create_session_cookie, COOKIE_NAME, CSRF_COOKIE_NAME, generate_csrf_token

    uid = uuid.UUID(user_id_str)
    mock_user = MagicMock()
    mock_user.id = uid

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    csrf_token = generate_csrf_token()
    session_token = create_session_cookie(user_id_str, time.time())
    client = TestClient(
        app,
        cookies={COOKIE_NAME: session_token, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return client, mock_user


def test_accept_calibration_calls_recompute_user_snapshots():
    """AC2: POST /api/races/{id}/calibrate/accept triggers recompute_user_snapshots."""
    from backend.main import app, resolve_user

    race_id = str(uuid.uuid4())
    user_id = uuid.UUID(_USER_ID)

    mock_race = MagicMock()
    mock_race.user_id = user_id

    mock_prefs = MagicMock()
    mock_prefs.ctl_days = 42
    mock_prefs.atl_days = 7

    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)
    mock_sess.get.return_value = mock_race
    mock_sess.query.return_value.filter.return_value.first.return_value = mock_prefs

    client, mock_user = _make_authed_client(_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch("backend.main.recompute_user_snapshots") as mock_recompute,
        ):
            mock_recompute.return_value = 42
            resp = client.post(
                f"/api/races/{race_id}/calibrate/accept",
                json={"ctl_days": 35, "atl_days": 5},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert resp.status_code == 200, f"Accept failed: {resp.text}"
    mock_recompute.assert_called_once_with(str(user_id))


def test_accept_calibration_response_includes_recomputed_count():
    """AC2: accept response reports how many snapshot rows were recomputed."""
    from backend.main import app, resolve_user

    race_id = str(uuid.uuid4())
    user_id = uuid.UUID(_USER_ID)

    mock_race = MagicMock()
    mock_race.user_id = user_id

    mock_prefs = MagicMock()
    mock_prefs.ctl_days = 35
    mock_prefs.atl_days = 5

    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)
    mock_sess.get.return_value = mock_race
    mock_sess.query.return_value.filter.return_value.first.return_value = mock_prefs

    client, mock_user = _make_authed_client(_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch("backend.main.recompute_user_snapshots", return_value=180),
        ):
            resp = client.post(
                f"/api/races/{race_id}/calibrate/accept",
                json={"ctl_days": 35, "atl_days": 5},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("snapshots_recomputed") == 180, (
        f"Expected snapshots_recomputed=180, got {body}"
    )


# ---------------------------------------------------------------------------
# AC5 — recompute_user_snapshots helper
# ---------------------------------------------------------------------------

def test_recompute_user_snapshots_queries_earliest_workout_date():
    """AC5: recompute_user_snapshots finds earliest TSS workout and calls get_snapshot_series."""
    from backend.services.training_load import recompute_user_snapshots

    earliest = date(2024, 1, 1)
    today = date.today()

    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.first.return_value = (earliest,)

    with (
        patch("backend.services.training_load.engine") as mock_engine,
        patch("backend.services.training_load.get_snapshot_series", return_value=list(range(90))) as mock_gss,
    ):
        mock_engine.connect.return_value = mock_conn
        count = recompute_user_snapshots(_USER_ID)

    mock_gss.assert_called_once_with(_USER_ID, earliest, today)
    assert count == 90


def test_recompute_user_snapshots_returns_zero_when_no_workouts():
    """AC5: recompute_user_snapshots returns 0 when user has no TSS workouts."""
    from backend.services.training_load import recompute_user_snapshots

    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.first.return_value = (None,)

    with (
        patch("backend.services.training_load.engine") as mock_engine,
        patch("backend.services.training_load.get_snapshot_series") as mock_gss,
    ):
        mock_engine.connect.return_value = mock_conn
        count = recompute_user_snapshots(_USER_ID)

    mock_gss.assert_not_called()
    assert count == 0
