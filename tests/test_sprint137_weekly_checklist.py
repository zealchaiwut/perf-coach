"""Sprint 137 — checklist read model + UI (WC-14..WC-20)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.checklist_week import (
    _session_role,
    _session_state,
    build_checklist_week,
)


def test_session_state_skipped_and_missed():
    ps = SimpleNamespace(status="skipped", planned_date=date(2026, 9, 20), session_type="mobility")
    assert _session_state(ps, date(2026, 9, 28)) == "skipped"
    ps2 = SimpleNamespace(status="planned", planned_date=date(2026, 9, 20), session_type="run")
    assert _session_state(ps2, date(2026, 9, 28)) == "missed"
    ps3 = SimpleNamespace(status="planned", planned_date=date(2026, 9, 20), session_type="mobility")
    assert _session_state(ps3, date(2026, 9, 28)) == "pending"


def test_session_role_mobility_optional():
    assert _session_role(SimpleNamespace(session_type="mobility")) == "optional"
    assert _session_role(SimpleNamespace(session_type="run")) == "core"


def test_checklist_endpoint_requires_auth():
    client = TestClient(app)
    assert client.get("/api/checklist/week").status_code == 401


def test_checklist_redirect_to_habits():
    client = TestClient(app)
    r = client.get("/checklist", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/habits"


def test_wc15_session_url_param_in_training_plan():
    src = open("frontend/js/training-plan.js", encoding="utf-8").read()
    assert "_urlFlag('session')" in src
    assert "_pendingOpenId" in src


def test_checklist_ui_module_exists():
    src = open("frontend/js/checklist-ui.js", encoding="utf-8").read()
    assert "fetchWeek" in src
    assert "renderHabitsPage" in src
    assert "renderWhatMoves" in src


def test_skip_endpoint_rejects_non_mobility(as_user):
    as_user(uuid4())
    client = TestClient(app)
    r = client.post(f"/api/planned-sessions/{uuid4()}/skip")
    assert r.status_code in (404, 422)


def test_build_checklist_week_shape(monkeypatch):
    """Minimal DB mock — verifies days[] + score fields exist."""
    from backend.services import checklist_week as cw

    class _Q:
        def __init__(self, rows=None):
            self._rows = rows or []

        def filter(self, *a, **kw):
            return self

        def order_by(self, *a, **kw):
            return self

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    db = MagicMock()
    db.query.return_value = _Q([])

    monkeypatch.setattr(cw, "today_bangkok", lambda: date(2026, 9, 28))
    monkeypatch.setattr(
        "backend.services.checklist_habits.ensure_sleep_habit",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "backend.services.habit_autofill.recompute_autofill_for_week",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "backend.services.training_prefs.active_dict",
        lambda *a, **kw: {"payload": {"weekly_checklist_enabled": True}},
    )
    monkeypatch.setattr(
        "backend.services.fuel.get_week_payload",
        lambda *a, **kw: {"days": [], "week_phase": "maintenance"},
    )
    monkeypatch.setattr(
        "backend.services.plan_build_status.plan_build_status",
        lambda *a, **kw: {"status": "up_to_date"},
    )
    monkeypatch.setattr(
        "backend.services.habit_evidence.build_user_evidence",
        lambda *a, **kw: [],
    )

    out = build_checklist_week(db, uuid4(), date(2026, 9, 28), today=date(2026, 9, 28))
    assert out["week_start"] == "2026-09-28"
    assert out["is_current_week"] is True
    assert len(out["days"]) == 7
    assert "score" in out["days"][0]
    assert "items" in out["days"][0]
