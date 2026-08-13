"""Tests for backend/services/training_load.py and /api/training-load endpoints."""

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.services.training_load import (
    ATL_DAYS,
    CTL_DAYS,
    compute_load_curves,
    current_load,
    daily_tss_series,
    daily_update,
)

_client = TestClient(app)
_USER_ID = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _auth_bypass():
    """Bypass resolve_user for all tests — API endpoint auth is tested separately."""
    fake_user = MagicMock()
    fake_user.id = uuid.UUID(_USER_ID)
    app.dependency_overrides[resolve_user] = lambda: fake_user
    yield
    app.dependency_overrides.pop(resolve_user, None)


@pytest.fixture(autouse=True)
def _default_calibration(monkeypatch):
    """These tests exercise snapshot-cache/upsert plumbing, not the calibration
    lookup added for fix-loopholes Task 5 (covered by
    tests/test_calibration_loop__loophole5.py). resolve_user_ewma_days opens
    its own Session(engine), which would otherwise collide with each test's
    ad-hoc Session mock and return MagicMocks in place of real ctl_days/atl_days.
    Pin it to the module defaults here."""
    monkeypatch.setattr(
        "backend.services.training_load.resolve_user_ewma_days",
        lambda user_id: (CTL_DAYS, ATL_DAYS),
    )


def _mock_session_smart(snap_list=None, seed_snap=None):
    """Session mock that returns different results for User vs TrainingLoadSnapshot queries."""
    from backend.models import User as _User

    fake_user = MagicMock()
    fake_user.id = uuid.UUID(_USER_ID)
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(model):
        m = MagicMock()
        if model is _User:
            m.filter.return_value.first.return_value = fake_user
        else:
            m.filter.return_value.first.return_value = seed_snap
            m.filter.return_value.order_by.return_value.all.return_value = snap_list or []
        return m

    mock_session.query.side_effect = _query_side_effect
    return mock_session


def _mock_session_with_user():
    fake_user = MagicMock()
    fake_user.id = uuid.UUID(_USER_ID)
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.first.return_value = fake_user
    return mock_session


def _mock_session_no_user():
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.first.return_value = None
    return mock_session


# ---------------------------------------------------------------------------
# (a) daily_tss_series fills zero-TSS days between two workout days
# ---------------------------------------------------------------------------


def test_daily_tss_series_fills_zero_days():
    day1 = date(2024, 1, 1)
    day3 = date(2024, 1, 3)

    fake_rows = [(day1, 100), (day3, 150)]

    mock_result = MagicMock()
    mock_result.fetchall.return_value = fake_rows
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_result
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("backend.services.training_load.engine") as mock_engine:
        mock_engine.connect.return_value = mock_conn
        series = daily_tss_series("user-1", day1, day3)

    assert len(series) == 3
    assert series[0] == (date(2024, 1, 1), 100)
    assert series[1] == (date(2024, 1, 2), 0)
    assert series[2] == (date(2024, 1, 3), 150)


# ---------------------------------------------------------------------------
# (b) flat TSS=100 for 100 days → CTL ≈ 100, ATL ≈ 100, TSB ≈ 0
# ---------------------------------------------------------------------------


def test_flat_tss_converges_to_tss_value():
    # CTL (42-day EWMA) needs ~5x the time constant to converge within 1.0 from
    # cold-start: 5 * 42 = 210 days. ATL (7-day) converges in ~35 days.
    start = date(2024, 1, 1)
    series = [(start + timedelta(days=i), 100) for i in range(210)]
    curves = compute_load_curves(series)
    last = curves[-1]
    assert abs(last["ctl"] - 100.0) < 1.0, f"CTL={last['ctl']} not near 100"
    assert abs(last["atl"] - 100.0) < 1.0, f"ATL={last['atl']} not near 100"
    assert abs(last["tsb"] - 0.0) < 1.0, f"TSB={last['tsb']} not near 0"


# ---------------------------------------------------------------------------
# (c) single-day TSS=200 spike → CTL and ATL peak on day 1 then decay
# ---------------------------------------------------------------------------


def test_single_spike_then_decay():
    start = date(2024, 1, 1)
    series = [(start, 200)] + [(start + timedelta(days=i), 0) for i in range(1, 30)]
    curves = compute_load_curves(series)

    # Peak is on day 1 (index 0)
    peak_ctl = curves[0]["ctl"]
    peak_atl = curves[0]["atl"]

    # Both CTL and ATL must monotonically decay after the spike
    for i in range(1, len(curves)):
        assert curves[i]["ctl"] < curves[i - 1]["ctl"], (
            f"CTL not decaying at index {i}: {curves[i]['ctl']} >= {curves[i-1]['ctl']}"
        )
        assert curves[i]["atl"] < curves[i - 1]["atl"], (
            f"ATL not decaying at index {i}: {curves[i]['atl']} >= {curves[i-1]['atl']}"
        )

    assert peak_ctl > 0
    assert peak_atl > 0


# ---------------------------------------------------------------------------
# (d) current_load returns last entry of series
# ---------------------------------------------------------------------------


def _mock_session_snapshot(snap=None):
    """Session mock for current_load's snapshot read (and daily_update's upsert)."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    q = mock_session.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = snap
    return mock_session


def test_current_load_returns_last_entry():
    start = date(2024, 1, 1)
    series = [(start + timedelta(days=i), 80) for i in range(50)]
    curves = compute_load_curves(series)
    last = curves[-1]

    mock_session = _mock_session_snapshot(None)

    with (
        patch("backend.services.training_load.Session", return_value=mock_session),
        patch("backend.services.training_load.daily_tss_series") as mock_series,
    ):
        mock_series.return_value = series
        result = current_load(_USER_ID, as_of=series[-1][0])

    assert result["date"] == last["date"]
    assert result["ctl"] == last["ctl"]
    assert result["atl"] == last["atl"]
    assert result["tsb"] == last["tsb"]


# ---------------------------------------------------------------------------
# (e) current_load(as_of=past_date) returns historical values
# ---------------------------------------------------------------------------


def test_current_load_as_of_past_date():
    today = date(2024, 6, 1)
    past = date(2024, 5, 15)

    start_today = today - timedelta(days=180)
    series_today = [(start_today + timedelta(days=i), 60) for i in range((today - start_today).days + 1)]

    start_past = past - timedelta(days=180)
    series_past = [(start_past + timedelta(days=i), 60) for i in range((past - start_past).days + 1)]

    def fake_series(user_id, from_date, to_date):
        if to_date == today:
            return series_today
        return series_past

    mock_session = _mock_session_snapshot(None)

    with (
        patch("backend.services.training_load.Session", return_value=mock_session),
        patch("backend.services.training_load.daily_tss_series", side_effect=fake_series),
    ):
        result_today = current_load(_USER_ID, as_of=today)
        result_past = current_load(_USER_ID, as_of=past)

    assert result_today["date"] == today
    assert result_past["date"] == past


# ---------------------------------------------------------------------------
# current_load() reads the training_load_snapshots cache (Task 1, perf/hot-paths)
# ---------------------------------------------------------------------------


def test_current_load_reads_snapshot_cache_single_query():
    """Cache hit: current_load must do exactly 1 query and skip the recompute."""
    from backend.services.training_load import _FORMULA_VERSION

    today = date(2024, 6, 1)
    snap = MagicMock()
    snap.snapshot_date = today
    snap.ctl = 55.5
    snap.atl = 40.2
    snap.tsb = 15.3
    snap.acwr = 1.1
    snap.formula_version = _FORMULA_VERSION
    # NULL means the snapshot was computed with the module defaults (CTL_DAYS/ATL_DAYS);
    # the _default_calibration fixture pins resolve_user_ewma_days to those same
    # defaults, so the staleness check passes and the cache is used.
    snap.ctl_days = None
    snap.atl_days = None

    mock_session = _mock_session_snapshot(snap)

    with (
        patch("backend.services.training_load.Session", return_value=mock_session),
        patch("backend.services.training_load.daily_tss_series") as mock_series,
    ):
        result = current_load(_USER_ID, as_of=today)

    assert result == {"date": today, "ctl": 55.5, "atl": 40.2, "tsb": 15.3, "acwr": 1.1}
    mock_series.assert_not_called()
    mock_session.query.assert_called_once()


def test_current_load_cache_miss_falls_back_and_upserts():
    """Cache miss: current_load recomputes via daily_update and upserts the row."""
    today = date(2024, 6, 1)
    start = today - timedelta(days=180)
    series = [(start + timedelta(days=i), 80) for i in range((today - start).days + 1)]
    curves = compute_load_curves(series)
    expected = curves[-1]

    mock_session = _mock_session_snapshot(None)

    with (
        patch("backend.services.training_load.Session", return_value=mock_session),
        patch("backend.services.training_load.daily_tss_series", return_value=series),
    ):
        result = current_load(_USER_ID, as_of=today)

    assert result["date"] == expected["date"]
    assert result["ctl"] == expected["ctl"]
    assert result["atl"] == expected["atl"]
    assert result["tsb"] == expected["tsb"]
    # daily_update's upsert ran on the same session used for the cache read
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


def test_current_load_identical_to_direct_recompute():
    """Values from the cache-miss fallback must match the plain recompute path."""
    today = date(2024, 6, 1)
    start = today - timedelta(days=180)
    series = [(start + timedelta(days=i), 65) for i in range((today - start).days + 1)]
    direct_curves = compute_load_curves(series)
    direct_last = direct_curves[-1]

    mock_session = _mock_session_snapshot(None)

    with (
        patch("backend.services.training_load.Session", return_value=mock_session),
        patch("backend.services.training_load.daily_tss_series", return_value=series),
    ):
        result = current_load(_USER_ID, as_of=today)

    assert result["ctl"] == direct_last["ctl"]
    assert result["atl"] == direct_last["atl"]
    assert result["tsb"] == direct_last["tsb"]


# ---------------------------------------------------------------------------
# (f) invalid inputs raise ValueError with descriptive messages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"ctl_days": 7, "atl_days": 7}, "ctl_days"),
        ({"ctl_days": 5, "atl_days": 7}, "ctl_days"),
        ({"ctl_days": 42, "atl_days": 0}, "atl_days"),
        ({"ctl_days": 42, "atl_days": -1}, "atl_days"),
    ],
)
def test_compute_load_curves_invalid_days(kwargs, match):
    series = [(date(2024, 1, 1), 100)]
    with pytest.raises(ValueError, match=match):
        compute_load_curves(series, **kwargs)


def test_daily_tss_series_from_date_after_to_date():
    with pytest.raises(ValueError, match="from_date"):
        daily_tss_series("user-1", date(2024, 2, 1), date(2024, 1, 1))


def test_daily_tss_series_future_from_date():
    future = date.today() + timedelta(days=10)
    with pytest.raises(ValueError, match="future"):
        daily_tss_series("user-1", future, future + timedelta(days=5))


# ---------------------------------------------------------------------------
# API endpoint tests (a)–(e)
# ---------------------------------------------------------------------------

def _make_series(n_days: int, tss: int = 80, end: date | None = None) -> list[tuple[date, int]]:
    end = end or date.today()
    start = end - timedelta(days=n_days - 1)
    return [(start + timedelta(days=i), tss) for i in range(n_days)]


# (a) GET /api/training-load returns correct response shape


def test_api_training_load_response_shape():
    today = date.today()
    from_str = (today - timedelta(days=29)).isoformat()
    to_str = today.isoformat()
    series = _make_series(30)
    fake_rows = [{"date": d, "tss": t, "ctl": 50.0, "atl": 48.0, "tsb": 2.0, "acwr": None} for d, t in series]
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.get_snapshot_series", return_value=fake_rows),
    ):
        res = _client.get(f"/api/training-load?user_id={_USER_ID}&from={from_str}&to={to_str}")

    assert res.status_code == 200
    body = res.json()
    assert "curves" in body
    assert "current" in body
    assert "as_of" in body
    assert isinstance(body["curves"], list)
    assert len(body["curves"]) == 30
    first = body["curves"][0]
    for key in ("date", "tss", "ctl", "atl", "tsb"):
        assert key in first
    assert body["current"] == body["curves"][-1]


# (b) from/to filter trims returned curves correctly


def test_api_training_load_date_range_filter():
    from_str = "2025-01-01"
    to_str = "2025-01-10"
    fake_rows = [{"date": date(2025, 1, i), "tss": 50, "ctl": 20.0, "atl": 18.0, "tsb": 2.0, "acwr": None} for i in range(1, 11)]
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.get_snapshot_series", return_value=fake_rows),
    ):
        res = _client.get(f"/api/training-load?user_id={_USER_ID}&from={from_str}&to={to_str}")

    assert res.status_code == 200
    body = res.json()
    assert body["as_of"] == to_str
    dates = [e["date"] for e in body["curves"]]
    assert dates[0] == from_str
    assert dates[-1] == to_str
    assert len(dates) == 10


# (c) Range > 365 days returns 422


def test_api_training_load_range_exceeds_365():
    res = _client.get(
        f"/api/training-load?user_id={_USER_ID}&from=2024-01-01&to=2025-06-01"
    )
    assert res.status_code == 422
    assert "365" in res.text


# (d) GET /api/training-load/current returns interpretation field


def test_api_training_load_current_has_interpretation():
    load = {"date": date.today(), "ctl": 50.0, "atl": 48.0, "tsb": 2.0}
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.current_load", return_value=load),
    ):
        res = _client.get(f"/api/training-load/current?user_id={_USER_ID}")

    assert res.status_code == 200
    body = res.json()
    for key in ("date", "ctl", "atl", "tsb", "interpretation"):
        assert key in body
    assert body["interpretation"] == "Neutral"


# (e) Boundary values: TSB = 5 → "Fresh", TSB = -15 → "Overreached (high risk)"


def test_api_training_load_current_tsb_5_is_fresh():
    load = {"date": date.today(), "ctl": 40.0, "atl": 35.0, "tsb": 5.0}
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.current_load", return_value=load),
    ):
        res = _client.get(f"/api/training-load/current?user_id={_USER_ID}")

    assert res.status_code == 200
    assert res.json()["interpretation"] == "Fresh"


def test_api_training_load_current_tsb_neg15_is_productive():
    load = {"date": date.today(), "ctl": 40.0, "atl": 55.0, "tsb": -15.0}
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.current_load", return_value=load),
    ):
        res = _client.get(f"/api/training-load/current?user_id={_USER_ID}")

    assert res.status_code == 200
    assert res.json()["interpretation"] == "Productive (high load)"


# ---------------------------------------------------------------------------
# Snapshot cache tests (issue #244): (a)–(e)
# ---------------------------------------------------------------------------


# (a)/(b) backfill row generation + idempotency — scripts/backfill_training_load.py
# used to hand-roll its own hardcoded-42/7 EWMA (_compute_backfill_rows, a pure
# function these tests exercised directly). That duplication is exactly the bug
# class this consolidation fixes: the script now delegates entirely to
# training_load.get_snapshot_series() (the single source of truth), so there is
# no separate pure function left to unit-test here — equivalent coverage (row
# count for a date range, idempotent re-run, ctl>0 for positive TSS, tss_for_day
# present) lives in tests/test_training_load_single_source__loadmetricfix1.py's
# get_snapshot_series tests instead.


# (c) GET reads from snapshots when all dates are cached


def test_api_get_reads_from_snapshots():
    from_str = "2024-01-01"
    to_str = "2024-01-05"
    fake_rows = [
        {"date": date(2024, 1, i + 1), "tss": 100, "ctl": round(5.0 + i * 0.5, 1), "atl": round(4.0 + i * 0.5, 1), "tsb": 1.0, "acwr": None}
        for i in range(5)
    ]
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.get_snapshot_series", return_value=fake_rows) as mock_gss,
    ):
        res = _client.get(f"/api/training-load?user_id={_USER_ID}&from={from_str}&to={to_str}")

    assert res.status_code == 200
    body = res.json()
    assert len(body["curves"]) == 5
    for i, entry in enumerate(body["curves"]):
        assert entry["tss"] == 100
        assert entry["ctl"] == round(5.0 + i * 0.5, 1)
    mock_gss.assert_called_once()


# (d) GET falls back to on-demand computation for dates missing from snapshots


def test_api_get_falls_back_for_missing_days():
    from_str = "2024-01-01"
    to_str = "2024-01-05"
    # get_snapshot_series handles cache misses internally and returns all 5 days
    fake_rows = [
        {"date": date(2024, 1, i + 1), "tss": 80, "ctl": 10.0 + i, "atl": 9.0 + i, "tsb": 1.0, "acwr": None}
        for i in range(5)
    ]
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.get_snapshot_series", return_value=fake_rows) as mock_gss,
    ):
        res = _client.get(f"/api/training-load?user_id={_USER_ID}&from={from_str}&to={to_str}")

    assert res.status_code == 200
    body = res.json()
    assert len(body["curves"]) == 5
    assert "2024-01-03" in [e["date"] for e in body["curves"]]
    mock_gss.assert_called_once()


# (e) recompute endpoint UPSERTs snapshot values and returns 200


def test_api_recompute_upserts_snapshots():
    today = date.today()
    today_str = today.isoformat()
    fake_rows = [{"date": today, "tss": 80, "ctl": 50.0, "atl": 48.0, "tsb": 2.0, "acwr": None}]

    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.get_snapshot_series", return_value=fake_rows) as mock_gss,
    ):
        res = _client.post(f"/api/training-load/recompute?user_id={_USER_ID}&from={today_str}")

    assert res.status_code == 200
    body = res.json()
    assert body["recomputed"] >= 1
    assert body["from"] == today_str
    mock_gss.assert_called_once()


# ---------------------------------------------------------------------------
# daily_update + workout hook tests (issue #245): (a)–(e)
# ---------------------------------------------------------------------------


def _make_du_session_mock():
    """Session mock for daily_update: handles execute + commit."""
    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)
    return mock_sess


def _make_engine_conn_mock(rows=None):
    """engine.connect() mock that returns given rows for daily_tss_series."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows or []
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_result
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


# (a) daily_update creates a snapshot row for today


def test_daily_update_creates_snapshot_for_today():
    today = date.today()
    mock_conn = _make_engine_conn_mock([(today, 80)])
    mock_sess = _make_du_session_mock()

    with (
        patch("backend.services.training_load.engine") as mock_engine,
        patch("backend.services.training_load.Session") as MockSession,
    ):
        mock_engine.connect.return_value = mock_conn
        MockSession.return_value = mock_sess
        result = daily_update(_USER_ID)

    assert result["date"] == today
    assert "ctl" in result and "atl" in result and "tsb" in result
    mock_sess.execute.assert_called_once()
    mock_sess.commit.assert_called_once()


# (b) re-running daily_update with same inputs produces identical values and no duplicate row


def test_daily_update_is_idempotent():
    today = date.today()
    mock_conn = _make_engine_conn_mock([(today, 80)])
    mock_sess = _make_du_session_mock()

    with (
        patch("backend.services.training_load.engine") as mock_engine,
        patch("backend.services.training_load.Session") as MockSession,
    ):
        mock_engine.connect.return_value = mock_conn
        MockSession.return_value = mock_sess
        result1 = daily_update(_USER_ID)
        result2 = daily_update(_USER_ID)

    assert result1["ctl"] == result2["ctl"]
    assert result1["atl"] == result2["atl"]
    assert result1["tsb"] == result2["tsb"]
    assert mock_sess.execute.call_count == 2


# (c) POST /api/workouts results in daily_update being called


def test_post_workout_calls_daily_update():
    today_str = date.today().isoformat()
    payload = {
        "user_id": _USER_ID,
        "name": "Test Run",
        "workout_date": today_str,
        "workout_type": "run",
        "tss": 50.0,
    }

    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.daily_update") as mock_du,
        patch("backend.main.compute_best_values", return_value={
            "best_distance_km": None, "best_duration_seconds": None,
            "best_avg_hr": None, "best_avg_power_w": None,
            "best_tss": 50.0, "best_name": "Test Run",
        }),
    ):
        res = _client.post("/api/workouts", json=payload)

    assert res.status_code == 201
    mock_du.assert_called_once()
    call_args = mock_du.call_args
    assert call_args[0][1] == date.today()


# (d) simulated daily_update failure does not cause workout creation to fail


def test_post_workout_succeeds_even_if_daily_update_fails():
    today_str = date.today().isoformat()
    payload = {
        "user_id": _USER_ID,
        "name": "Test Run",
        "workout_date": today_str,
        "workout_type": "run",
    }

    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.daily_update", side_effect=Exception("DB connection lost")),
        patch("backend.main.compute_best_values", return_value={
            "best_distance_km": None, "best_duration_seconds": None,
            "best_avg_hr": None, "best_avg_power_w": None,
            "best_tss": None, "best_name": "Test Run",
        }),
    ):
        res = _client.post("/api/workouts", json=payload)

    assert res.status_code == 201


# (e) backfill endpoint returns 2xx and populates expected snapshot rows


def test_backfill_endpoint_populates_snapshot_rows():
    from_str = "2026-01-01"
    from_d = date(2026, 1, 1)
    today = date.today()
    n_days = (today - from_d).days + 1

    fake_rows = [{"date": from_d + timedelta(days=i), "tss": 80, "ctl": 50.0, "atl": 48.0, "tsb": 2.0, "acwr": None} for i in range(n_days)]

    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.get_snapshot_series", return_value=fake_rows) as mock_gss,
    ):
        res = _client.post(f"/api/training-load/backfill?user_id={_USER_ID}&from={from_str}")

    assert res.status_code == 200
    body = res.json()
    assert body["backfilled"] == n_days
    assert body["from"] == from_str
    mock_gss.assert_called_once()
