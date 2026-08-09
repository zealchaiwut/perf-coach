"""Quiet worker poll configuration."""
from __future__ import annotations

import importlib


def test_worker_dispatch_includes_coach_export():
    import backend.worker_app as w

    assert "coach_export" in w._DISPATCH


def test_idle_poll_interval_default(monkeypatch):
    monkeypatch.delenv("QUEUE_POLL_IDLE_INTERVAL_SECONDS", raising=False)
    import backend.worker_app as w

    importlib.reload(w)
    assert w.QUEUE_POLL_IDLE_INTERVAL_SECONDS == 300


def test_idle_poll_interval_override(monkeypatch):
    monkeypatch.setenv("QUEUE_POLL_IDLE_INTERVAL_SECONDS", "120")
    import backend.worker_app as w

    importlib.reload(w)
    assert w.QUEUE_POLL_IDLE_INTERVAL_SECONDS == 120
