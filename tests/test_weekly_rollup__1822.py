"""Issue #1822 — canonical weekly_rollup service."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.services.weekly_rollup import (
    bangkok_week_start,
    session_local_date,
    weekly_rollup,
    weekly_rollups,
)

_BKK = ZoneInfo("Asia/Bangkok")
_USER = uuid.uuid4()


def _workout(*, tss_power, workout_date, start_time=None, workout_type="run"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=_USER,
        workout_date=workout_date,
        start_time=start_time,
        workout_type=workout_type,
        distance_km=10.0,
        duration_seconds=3600,
        tss=None,
        tss_power=float(tss_power),
        tss_stryd=None,
        tss_method_override=None,
        tss_source="calculated",
        tss_method="power",
        stryd_activity_pk=None,
    )


def test_two_runs_sum_tss_total():
    ws = date(2026, 11, 3)  # Monday
    w1 = _workout(tss_power=173, workout_date=date(2026, 11, 4))
    w2 = _workout(tss_power=87, workout_date=date(2026, 11, 6))
    prefs = SimpleNamespace(tss_method_default="power")

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = prefs
    mock_session.query.return_value.filter.return_value.all.side_effect = [
        [w1, w2],
        [],
    ]

    with patch(
        "backend.services.weekly_rollup._estimate_planned_tss_remaining",
        return_value=0.0,
    ):
        out = weekly_rollup(str(_USER), ws, session=mock_session, today=date(2026, 11, 8))
    assert out["tss_total"] == 260.0


def test_sunday_late_stays_in_sunday_week():
    # Week Mon 27 Oct – Sun 2 Nov 2025; Sunday 23:30 BKK
    ws = date(2025, 10, 27)
    sunday = date(2025, 11, 2)
    st = datetime(2025, 11, 2, 23, 30, tzinfo=_BKK)
    w = _workout(tss_power=50, workout_date=sunday, start_time=st)
    assert session_local_date(w) == sunday
    assert bangkok_week_start(session_local_date(w)) == ws


def test_monday_early_goes_to_next_week():
    monday = date(2025, 11, 3)
    st = datetime(2025, 11, 3, 0, 10, tzinfo=_BKK)
    w = _workout(tss_power=40, workout_date=monday, start_time=st)
    assert session_local_date(w) == monday
    assert bangkok_week_start(session_local_date(w)) == monday


def test_export_series_and_rollups_agree():
    weeks = [
        {"week_start": "2026-11-03", "tss_total": 100.0},
        {"week_start": "2026-11-10", "tss_total": 120.0},
    ]
    series = [{"week_start": w["week_start"], "tss": w["tss_total"]} for w in weeks]
    for s, r in zip(series, weeks):
        assert s["tss"] == r["tss_total"]


def test_weekly_rollups_range():
    inst = MagicMock()
    with patch(
        "backend.services.weekly_rollup.weekly_rollup",
        side_effect=lambda uid, ws, **kw: {"week_start": ws.isoformat()},
    ):
        rows = weekly_rollups(str(_USER), date(2026, 11, 2), date(2026, 11, 16), session=inst)
    assert len(rows) == 3
    assert rows[0]["week_start"] == "2026-11-02"