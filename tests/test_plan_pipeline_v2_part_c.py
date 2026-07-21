"""Plan pipeline v2 Part C — apply, notify window, pipeline status."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.services import plan_draft as pd


BKK = ZoneInfo("Asia/Bangkok")


def test_pipeline_status_defaults_legacy(monkeypatch):
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "legacy")
    st = pd.pipeline_status()
    assert st["mode"] == "legacy"
    assert st["enabled"] is False
    assert st["ui_default"] is False


def test_pipeline_status_shadow(monkeypatch):
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "shadow")
    st = pd.pipeline_status()
    assert st["enabled"] is True
    assert st["shadow"] is True
    assert st["ui_default"] is False


def test_pipeline_status_v2_ui_default(monkeypatch):
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "skeleton_v2")
    st = pd.pipeline_status()
    assert st["ui_default"] is True


def test_session_to_planned_body_skips_rest():
    ws = date(2026, 7, 20)
    assert pd._session_to_planned_body(ws, {"day_offset": 0, "workout_type": "rest"}) is None


def test_session_to_planned_body_maps_run():
    ws = date(2026, 7, 20)  # Monday
    body = pd._session_to_planned_body(
        ws,
        {
            "day_offset": 2,
            "workout_type": "run",
            "intent": "Easy aerobic",
            "target_tss": 45,
            "duration_minutes": 50,
            "blocks": [{"phase": "main", "duration_min": 40}],
        },
    )
    assert body["planned_date"] == "2026-07-22"
    assert body["session_type"] == "run"
    assert body["name"] == "Easy aerobic"
    assert body["structure"]["blocks"]


class _FakeDraft:
    def __init__(self, payload, status="fresh"):
        self.id = "d1"
        self.payload = payload
        self.status = status
        self.week_start = date(2026, 7, 20)
        self.updated_at = None


class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._row


class _FakeDb:
    def __init__(self, row):
        self._row = row
        self.flushed = False

    def query(self, model):
        return _FakeQuery(self._row)

    def flush(self):
        self.flushed = True


def test_hermes_notify_outside_window_not_deliverable():
    payload = {"sessions": [{"workout_type": "run"}], "notify_pending": True}
    db = _FakeDb(_FakeDraft(payload))
    now = datetime(2026, 7, 20, 14, 0, tzinfo=BKK)  # 2pm — outside 7–9
    out = pd.hermes_draft_notify(db, "u1", now=now)
    assert out["ready"] is True
    assert out["deliver_now"] is False
    assert out["in_morning_window"] is False


def test_hermes_notify_morning_window_deliverable():
    payload = {"sessions": [{"workout_type": "run"}, {"workout_type": "rest"}], "notify_pending": True}
    db = _FakeDb(_FakeDraft(payload))
    now = datetime(2026, 7, 20, 8, 15, tzinfo=BKK)
    out = pd.hermes_draft_notify(db, "u1", now=now)
    assert out["deliver_now"] is True
    assert "week draft is ready" in out["message"].lower()
    assert out["combine_with_prefs_reconfirm"] is False  # Monday


def test_hermes_notify_sunday_prefs_flag():
    payload = {"sessions": [], "notify_pending": True}
    db = _FakeDb(_FakeDraft(payload))
    now = datetime(2026, 7, 26, 7, 30, tzinfo=BKK)  # Sunday
    out = pd.hermes_draft_notify(db, "u1", now=now)
    assert out["combine_with_prefs_reconfirm"] is True


def test_hermes_notify_ack_clears_pending():
    payload = {"sessions": [{"workout_type": "run"}], "notify_pending": True}
    row = _FakeDraft(payload)
    db = _FakeDb(row)
    now = datetime(2026, 7, 20, 8, 0, tzinfo=BKK)
    out = pd.hermes_draft_notify(db, "u1", now=now, ack=True)
    assert out["deliver_now"] is False
    assert out["pending"] is False
    assert row.payload.get("notified_at")
    assert row.payload.get("notify_pending") is False
