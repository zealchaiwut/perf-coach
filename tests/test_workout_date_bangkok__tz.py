"""Workout dates are Bangkok-local, not UTC (PRD report: eb26e86f — a Sunday
06:36 BKK run was filed under Saturday because reconcile took the UTC date).

Unit-level: exercises the same expression reconcile.py uses to derive
`workout_date` from an activity's UTC start_time, plus the helpers themselves.
The full reconcile flow is covered by the existing reconcile tests; the date
math is what regressed, so it gets its own pinned cases here.
"""
from datetime import datetime, timezone

from backend.utils.time import to_bangkok, today_bangkok


def _wdate(start_time_utc):
    """Mirror of reconcile.py's derivation: BKK-local date of the start."""
    return to_bangkok(start_time_utc).date()


def test_early_morning_bkk_run_lands_on_bkk_date():
    # The reported row: 2026-06-20 23:36:48 UTC == Sunday 2026-06-21 06:36 BKK.
    st = datetime(2026, 6, 20, 23, 36, 48, tzinfo=timezone.utc)
    assert _wdate(st).isoformat() == "2026-06-21", (
        "pre-07:00 BKK workouts must take the BKK date, not the UTC date"
    )


def test_late_evening_bkk_run_keeps_same_date():
    # 22:30 BKK == 15:30 UTC same day — no shift either way.
    st = datetime(2026, 6, 21, 15, 30, 0, tzinfo=timezone.utc)
    assert _wdate(st).isoformat() == "2026-06-21"


def test_exact_bkk_midnight_boundary():
    # 17:00 UTC == 00:00 BKK next day.
    st = datetime(2026, 6, 20, 17, 0, 0, tzinfo=timezone.utc)
    assert _wdate(st).isoformat() == "2026-06-21"
    st2 = datetime(2026, 6, 20, 16, 59, 59, tzinfo=timezone.utc)
    assert _wdate(st2).isoformat() == "2026-06-20"


def test_reconcile_uses_bkk_derivation():
    """Source-level pin: reconcile.py must derive wdate via to_bangkok and must
    not regress to astimezone(timezone.utc).date()."""
    import inspect
    import backend.services.reconcile as rec
    src = inspect.getsource(rec)
    assert "to_bangkok(act.start_time).date()" in src
    assert "astimezone(timezone.utc).date()" not in src


def test_today_bangkok_is_a_date():
    assert today_bangkok().isoformat()  # smoke: helper exists and returns a date
