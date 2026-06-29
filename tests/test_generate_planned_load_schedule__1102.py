"""TDD tests for generate_planned_load_schedule (issue #1102).

Each test is anchored to a specific acceptance criterion:
- AC1: One record per calendar date from today (inclusive) through race_date (inclusive)
- AC2: Ramp phase correctly increases daily TSS
- AC3: Taper window reduces daily TSS for the N days before A-race
- AC4: Calling twice with identical inputs produces identical planned_load records
- AC5: Function does not perform fitness projection (no CTL/ATL/TSB)
- AC6: All records persisted to planned_load table with correct date keys
- AC7: py_compile reports no syntax errors on modified files
- AC8: Existing planned_load entries outside the generated range are not modified
"""
from __future__ import annotations

import datetime
import os
import pathlib
import py_compile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Load DB URL for persistence tests
try:
    from dotenv import dotenv_values
    _env = dotenv_values(_ROOT / ".env")
    _uat_url = _env.get("DATABASE_URL_UAT")
except ImportError:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

if _uat_url:
    from sqlalchemy import create_engine, text as _text
    _engine = create_engine(_uat_url, pool_pre_ping=True)
else:
    _engine = None

from backend.services.plan_service import generate_planned_load_schedule


# ── helpers ──────────────────────────────────────────────────────────────────

_TODAY = datetime.date(2026, 6, 30)


def _race(days_out: int) -> datetime.date:
    return _TODAY + datetime.timedelta(days=days_out)


# ── AC1: Series length ────────────────────────────────────────────────────────

def test_ac1_series_length_30_days():
    """AC1: 30-day window → 30 records (today + 29 days)."""
    race = _race(29)  # race is 29 days out → 30 total days
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=7,
    )
    assert len(result) == 30


def test_ac1_series_length_race_tomorrow():
    """AC1: A-race tomorrow → exactly 2 records (today and tomorrow)."""
    race = _race(1)
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=2,
    )
    assert len(result) == 2


def test_ac1_series_length_race_today():
    """AC1: A-race today → exactly 1 record."""
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=_TODAY,
        base_tss=50.0, ramp_rate=1.0, taper_length=1,
    )
    assert len(result) == 1


def test_ac1_series_dates_are_consecutive():
    """AC1: Dates in the series are consecutive calendar days, no gaps."""
    race = _race(9)
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=3,
    )
    dates = [r["date"] for r in result]
    for i in range(1, len(dates)):
        assert dates[i] - dates[i - 1] == datetime.timedelta(days=1)


def test_ac1_series_starts_on_today():
    """AC1: First record is for today."""
    race = _race(5)
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=2,
    )
    assert result[0]["date"] == _TODAY


def test_ac1_series_ends_on_race_date():
    """AC1: Last record is for the A-race date."""
    race = _race(14)
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=3,
    )
    assert result[-1]["date"] == race


# ── AC2: Ramp phase increases TSS ────────────────────────────────────────────

def test_ac2_ramp_tss_increases():
    """AC2: During the ramp phase each day's TSS is greater than the previous."""
    race = _race(29)  # 30 days total
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=2.0, taper_length=7,
    )
    ramp_entries = result[: len(result) - 7]  # first 23 days are ramp
    for i in range(1, len(ramp_entries)):
        assert ramp_entries[i]["planned_tss"] > ramp_entries[i - 1]["planned_tss"], (
            f"TSS did not increase on ramp day {i}: "
            f"{ramp_entries[i-1]['planned_tss']} -> {ramp_entries[i]['planned_tss']}"
        )


def test_ac2_ramp_first_day_equals_base_tss():
    """AC2: First day (today) TSS equals base_tss."""
    race = _race(10)
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=60.0, ramp_rate=3.0, taper_length=3,
    )
    assert result[0]["planned_tss"] == pytest.approx(60.0, abs=0.01)


def test_ac2_no_taper_all_ramp():
    """AC2: With taper_length=0, all days are ramp phase and TSS monotonically increases."""
    race = _race(9)  # 10 days
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=40.0, ramp_rate=5.0, taper_length=0,
    )
    assert len(result) == 10
    for i in range(1, len(result)):
        assert result[i]["planned_tss"] > result[i - 1]["planned_tss"]


# ── AC3: Taper phase reduces TSS ──────────────────────────────────────────────

def test_ac3_taper_reduces_tss_linear():
    """AC3 linear: TSS in the taper window is lower than peak TSS."""
    race = _race(14)  # 15 days total, last 5 are taper
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=2.0, taper_length=5,
        taper_shape="linear",
    )
    peak_tss = result[9]["planned_tss"]  # last ramp day (index 9)
    taper_entries = result[10:]
    for entry in taper_entries:
        assert entry["planned_tss"] < peak_tss, (
            f"Taper TSS {entry['planned_tss']} not less than peak {peak_tss}"
        )


def test_ac3_taper_reduces_tss_step():
    """AC3 step: TSS drops on taper entry and stays reduced."""
    race = _race(9)  # 10 days total, last 3 are taper
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=2.0, taper_length=3,
        taper_shape="step",
    )
    peak_tss = result[6]["planned_tss"]  # last ramp day
    taper_entries = result[7:]
    for entry in taper_entries:
        assert entry["planned_tss"] < peak_tss


def test_ac3_taper_reduces_tss_exponential():
    """AC3 exponential: TSS decreases exponentially in the taper window."""
    race = _race(9)  # 10 days, last 4 are taper
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=2.0, taper_length=4,
        taper_shape="exponential",
    )
    peak_tss = result[5]["planned_tss"]  # last ramp day
    taper_entries = result[6:]
    for entry in taper_entries:
        assert entry["planned_tss"] < peak_tss


def test_ac3_taper_window_is_n_days_before_race():
    """AC3: Exactly taper_length days before (and including) race are in taper window."""
    taper_length = 5
    n_days = 15
    race = _race(n_days - 1)
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=2.0, taper_length=taper_length,
        taper_shape="linear",
    )
    ramp_entries = result[: n_days - taper_length]
    taper_entries = result[n_days - taper_length :]
    assert len(taper_entries) == taper_length
    assert len(ramp_entries) == n_days - taper_length


# ── AC4: Determinism ──────────────────────────────────────────────────────────

def test_ac4_identical_inputs_produce_identical_outputs():
    """AC4: Calling with same inputs twice returns byte-for-byte identical results."""
    race = _race(20)
    kwargs = dict(
        today=_TODAY, race_date=race,
        base_tss=55.0, ramp_rate=1.5, taper_length=5, taper_shape="linear",
    )
    result1 = generate_planned_load_schedule(**kwargs)
    result2 = generate_planned_load_schedule(**kwargs)
    assert result1 == result2


def test_ac4_determinism_across_shapes():
    """AC4: All three taper shapes produce deterministic output."""
    race = _race(15)
    for shape in ("linear", "step", "exponential"):
        kwargs = dict(
            today=_TODAY, race_date=race,
            base_tss=50.0, ramp_rate=2.0, taper_length=5, taper_shape=shape,
        )
        r1 = generate_planned_load_schedule(**kwargs)
        r2 = generate_planned_load_schedule(**kwargs)
        assert r1 == r2, f"Non-deterministic output for taper_shape={shape!r}"


# ── AC5: No fitness projection ────────────────────────────────────────────────

def test_ac5_no_ctl_in_output():
    """AC5: Result records do not contain CTL/ATL/TSB keys."""
    race = _race(10)
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=3,
    )
    for entry in result:
        assert "ctl" not in entry
        assert "atl" not in entry
        assert "tsb" not in entry


def test_ac5_output_has_only_date_and_planned_tss_keys():
    """AC5: Each entry has exactly 'date' and 'planned_tss' keys."""
    race = _race(5)
    result = generate_planned_load_schedule(
        today=_TODAY, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=2,
    )
    for entry in result:
        assert set(entry.keys()) == {"date", "planned_tss"}


# ── AC6 & AC8: DB persistence ─────────────────────────────────────────────────

def _skip_no_db():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


@pytest.fixture(autouse=False)
def cleanup_test_dates():
    """Remove any planned_load rows inserted during the test."""
    inserted = []
    yield inserted
    if _engine and inserted:
        with _engine.begin() as conn:
            for d in inserted:
                conn.execute(_text("DELETE FROM planned_load WHERE date = :d"), {"d": d})


def test_ac6_records_persisted_to_planned_load_table(cleanup_test_dates):
    """AC6: After calling, planned_load table contains one row per generated date."""
    _skip_no_db()
    # Use far-future dates to avoid conflicts with real data
    today = datetime.date(2099, 1, 1)
    race = datetime.date(2099, 1, 10)  # 10 days
    cleanup_test_dates.extend(
        today + datetime.timedelta(days=i) for i in range(10)
    )

    from backend.services.plan_service import persist_planned_load_schedule
    schedule = generate_planned_load_schedule(
        today=today, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=3,
    )
    persist_planned_load_schedule(schedule)

    with _engine.connect() as conn:
        rows = conn.execute(
            _text(
                "SELECT date, planned_tss FROM planned_load "
                "WHERE date >= :start AND date <= :end ORDER BY date"
            ),
            {"start": today, "end": race},
        ).fetchall()

    assert len(rows) == 10
    for i, row in enumerate(rows):
        expected_date = today + datetime.timedelta(days=i)
        assert row[0] == expected_date


def test_ac6_persisted_values_match_generated_values(cleanup_test_dates):
    """AC6: planned_tss values stored in DB match the generated schedule."""
    _skip_no_db()
    today = datetime.date(2099, 2, 1)
    race = datetime.date(2099, 2, 5)  # 5 days

    cleanup_test_dates.extend(
        today + datetime.timedelta(days=i) for i in range(5)
    )

    from backend.services.plan_service import persist_planned_load_schedule
    schedule = generate_planned_load_schedule(
        today=today, race_date=race,
        base_tss=40.0, ramp_rate=2.0, taper_length=2,
        taper_shape="linear",
    )
    persist_planned_load_schedule(schedule)

    with _engine.connect() as conn:
        rows = conn.execute(
            _text(
                "SELECT date, planned_tss FROM planned_load "
                "WHERE date >= :start AND date <= :end ORDER BY date"
            ),
            {"start": today, "end": race},
        ).fetchall()

    assert len(rows) == len(schedule)
    for row, entry in zip(rows, schedule):
        assert float(row[1]) == pytest.approx(entry["planned_tss"], abs=0.01)


def test_ac4_second_call_does_not_create_duplicates(cleanup_test_dates):
    """AC4: Calling persist twice with identical inputs does not create duplicate rows."""
    _skip_no_db()
    today = datetime.date(2099, 3, 1)
    race = datetime.date(2099, 3, 4)  # 4 days

    cleanup_test_dates.extend(
        today + datetime.timedelta(days=i) for i in range(4)
    )

    from backend.services.plan_service import persist_planned_load_schedule
    kwargs = dict(
        today=today, race_date=race,
        base_tss=50.0, ramp_rate=1.5, taper_length=2, taper_shape="step",
    )
    persist_planned_load_schedule(generate_planned_load_schedule(**kwargs))
    persist_planned_load_schedule(generate_planned_load_schedule(**kwargs))

    with _engine.connect() as conn:
        count = conn.execute(
            _text(
                "SELECT COUNT(*) FROM planned_load "
                "WHERE date >= :start AND date <= :end"
            ),
            {"start": today, "end": race},
        ).scalar()

    assert count == 4  # no duplicates


def test_ac8_records_outside_range_not_modified(cleanup_test_dates):
    """AC8: Rows outside the generated date range are left unchanged."""
    _skip_no_db()
    # Insert a sentinel row outside the schedule's range
    sentinel_date = datetime.date(2099, 4, 30)
    sentinel_tss = 999.99
    cleanup_test_dates.append(sentinel_date)

    with _engine.begin() as conn:
        conn.execute(
            _text(
                "INSERT INTO planned_load (date, planned_tss) "
                "VALUES (:d, :tss) "
                "ON CONFLICT (date) DO UPDATE SET planned_tss = EXCLUDED.planned_tss"
            ),
            {"d": sentinel_date, "tss": sentinel_tss},
        )

    # Generate a schedule that does NOT include the sentinel date
    today = datetime.date(2099, 5, 1)
    race = datetime.date(2099, 5, 5)  # 5 days, all in May
    cleanup_test_dates.extend(
        today + datetime.timedelta(days=i) for i in range(5)
    )

    from backend.services.plan_service import persist_planned_load_schedule
    schedule = generate_planned_load_schedule(
        today=today, race_date=race,
        base_tss=50.0, ramp_rate=1.0, taper_length=2,
    )
    persist_planned_load_schedule(schedule)

    with _engine.connect() as conn:
        row = conn.execute(
            _text("SELECT planned_tss FROM planned_load WHERE date = :d"),
            {"d": sentinel_date},
        ).fetchone()

    assert row is not None
    assert float(row[0]) == pytest.approx(sentinel_tss, abs=0.01)


# ── AC7: py_compile ───────────────────────────────────────────────────────────

def test_ac7_plan_service_compiles():
    """AC7: backend/services/plan_service.py has no syntax errors."""
    py_compile.compile(
        str(_ROOT / "backend" / "services" / "plan_service.py"), doraise=True
    )


def test_ac7_models_compiles():
    """AC7: backend/models.py has no syntax errors."""
    py_compile.compile(str(_ROOT / "backend" / "models.py"), doraise=True)
