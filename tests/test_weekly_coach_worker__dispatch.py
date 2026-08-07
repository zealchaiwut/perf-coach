"""Weekly coach job is registered on the compute worker, not the webapp."""

from __future__ import annotations


def test_weekly_coach_in_worker_dispatch():
    from backend import worker_app

    assert "daily_coach" in worker_app._DISPATCH
    assert callable(worker_app._DISPATCH["daily_coach"])
    # Compat alias
    assert "weekly_coach" in worker_app._DISPATCH
    assert callable(worker_app._DISPATCH["weekly_coach"])
