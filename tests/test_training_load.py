"""Tests for backend/services/training_load.py"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.services.training_load import compute_load_curves, current_load, daily_tss_series


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
