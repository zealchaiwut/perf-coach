import pytest
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

from backend.utils.time import (
    now_utc,
    now_bangkok,
    today_bangkok,
    to_bangkok,
    to_utc,
    format_iso,
    parse_iso,
)

_UTC = timezone.utc
_BKK = ZoneInfo("Asia/Bangkok")


# a) now_utc returns aware datetime with UTC tzinfo
def test_now_utc_is_aware_utc():
    dt = now_utc()
    assert isinstance(dt, datetime)
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


# b) now_bangkok returns aware datetime with Bangkok tzinfo
def test_now_bangkok_is_aware_bangkok():
    dt = now_bangkok()
    assert isinstance(dt, datetime)
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 7 * 3600


# c) today_bangkok returns a date, not datetime
def test_today_bangkok_returns_date():
    result = today_bangkok()
    assert type(result) is date


# d) to_bangkok raises ValueError on naive input
def test_to_bangkok_raises_on_naive():
    with pytest.raises(ValueError):
        to_bangkok(datetime(2026, 5, 30, 12, 0, 0))


# e) to_utc raises ValueError on naive input
def test_to_utc_raises_on_naive():
    with pytest.raises(ValueError):
        to_utc(datetime(2026, 5, 30, 12, 0, 0))


# f) to_utc / to_bangkok round-trip: Bangkok → UTC → Bangkok yields identical datetime
def test_round_trip_bangkok_utc_bangkok():
    dt_bkk = datetime(2026, 5, 30, 19, 0, 0, tzinfo=_BKK)
    assert to_bangkok(to_utc(dt_bkk)) == dt_bkk


# g) format_iso outputs ISO 8601 with explicit offset
def test_format_iso_has_offset():
    dt = datetime(2026, 5, 30, 14, 32, 0, tzinfo=_BKK)
    result = format_iso(dt)
    assert "+07:00" in result


# h) parse_iso raises ValueError on malformed input
def test_parse_iso_raises_on_malformed():
    with pytest.raises(ValueError):
        parse_iso("not-a-date")


# i) parse_iso round-trips with format_iso
def test_parse_iso_round_trip():
    dt = datetime(2026, 5, 30, 14, 32, 0, tzinfo=_BKK)
    assert parse_iso(format_iso(dt)) == dt
