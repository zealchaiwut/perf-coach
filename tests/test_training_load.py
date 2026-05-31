"""Tests for backend/services/training_load.py and /api/training-load endpoints."""

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.training_load import compute_load_curves, current_load, daily_tss_series

_client = TestClient(app)
_USER_ID = str(uuid.uuid4())


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


def test_current_load_returns_last_entry():
    start = date(2024, 1, 1)
    series = [(start + timedelta(days=i), 80) for i in range(50)]
    curves = compute_load_curves(series)
    last = curves[-1]

    with patch("backend.services.training_load.daily_tss_series") as mock_series:
        mock_series.return_value = series
        result = current_load("user-1", as_of=series[-1][0])

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

    with patch("backend.services.training_load.daily_tss_series", side_effect=fake_series):
        result_today = current_load("user-1", as_of=today)
        result_past = current_load("user-1", as_of=past)

    assert result_today["date"] == today
    assert result_past["date"] == past


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
    series = _make_series(30)
    curves = compute_load_curves(series)
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
    ):
        res = _client.get(f"/api/training-load?user_id={_USER_ID}")

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
    series = [(date(2025, 1, i), 50) for i in range(1, 11)]
    curves = compute_load_curves(series)
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
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


def test_api_training_load_current_tsb_neg15_is_overreached():
    load = {"date": date.today(), "ctl": 40.0, "atl": 55.0, "tsb": -15.0}
    with (
        patch("backend.main.Session", return_value=_mock_session_with_user()),
        patch("backend.main.current_load", return_value=load),
    ):
        res = _client.get(f"/api/training-load/current?user_id={_USER_ID}")

    assert res.status_code == 200
    assert res.json()["interpretation"] == "Overreached (high risk)"
