"""P6-12 (#1886) — weekly check-in model and week snapshot."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.services import weekly_checkin as wc

TODAY = date(2026, 11, 8)  # Sunday
UID = uuid.uuid4()


def test_target_week_on_sunday_and_monday():
    assert wc.target_checkin_week_start(TODAY) == date(2026, 11, 2)
    assert wc.target_checkin_week_start(date(2026, 11, 9)) == date(2026, 11, 2)


def test_available_from_sunday_only():
    ws = date(2026, 11, 2)
    assert wc.checkin_open_for_week(date(2026, 11, 7), ws) is False
    assert wc.checkin_open_for_week(date(2026, 11, 8), ws) is True


def test_na_val_never_zero():
    assert wc.na_val(None)["status"] == wc.NA
    assert wc.na_val(0)["value"] == 0


def test_parse_carried_from_decision():
    raw = "CHANGES TO APPLY\ngoal: pace 6:05\nskeleton: move long run to Sunday\n"
    items = wc._parse_change_items(raw, decision_id="abc")
    assert len(items) == 2
    assert items[0]["change_type"] == "goal"
    assert items[0]["status"] == "not_yet"


def test_save_carried_statuses():
    row = SimpleNamespace(
        carried_changes=[{"id": "a", "text": "x", "status": "not_yet"}],
        updated_at=None,
    )
    wc.save_carried_statuses(MagicMock(), row, [{"id": "a", "status": "partly"}])
    assert row.carried_changes[0]["status"] == "partly"


def test_snapshot_uses_rollup_not_zero(monkeypatch):
    session = MagicMock()
    ws = date(2026, 11, 2)
    monkeypatch.setattr(
        wc,
        "weekly_rollup",
        lambda *a, **kw: {
            "session_count": 0,
            "runs": 0,
            "tss_total": 0,
            "counts": {},
        },
    )
    monkeypatch.setattr(wc, "_weight_block", lambda *a, **kw: {
        "avg_7d_kg": wc.na_val(None),
        "weekly_rate_kg": wc.na_val(None),
    })
    monkeypatch.setattr(wc, "_longest_run", lambda *a, **kw: {
        "longest_run_seconds": wc.na_val(None),
        "longest_run_target_seconds": wc.na_val(None),
    })
    monkeypatch.setattr(wc, "_fuel_rehearsals", lambda *a, **kw: {
        "fuel_rehearsals_done": wc.na_val(None),
        "fuel_rehearsals_due": wc.na_val(None),
    })
    monkeypatch.setattr(wc, "_foot_blocks", lambda *a, **kw: {
        "foot_blocks_done": wc.na_val(None),
        "runs_in_week": wc.na_val(0),
    })
    monkeypatch.setattr(wc, "_races_in_week", lambda *a, **kw: [])
    session.query.return_value.filter.return_value.count.return_value = 0
    snap = wc.build_week_snapshot(session, UID, ws, TODAY)
    assert snap["week_tss"]["status"] == "ok"
    assert snap["lunch_rule_yes_count"]["status"] == wc.NA


@pytest.mark.parametrize(
    "field,body,status",
    [
        ("feet", {"feet": 4}, 422),
        ("motivation", {"motivation": "meh"}, 422),
    ],
)
def test_patch_validation(field, body, status):
    from backend.auth import resolve_user
    from backend.main import app
    from backend.models import User
    from fastapi.testclient import TestClient

    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    with patch("backend.services.weekly_checkin.get_or_create_checkin") as g:
        row = SimpleNamespace(
            id=uuid.uuid4(),
            snapshot={},
            carried_changes=[],
            feet=None,
            bed_bucket=None,
            motivation=None,
            note=None,
            completed_at=None,
        )
        g.return_value = (row, {"week_start": "2026-11-02", "available": True, "completed": False})
        r = TestClient(app).patch("/api/weekly-check-in", json=body)
    app.dependency_overrides.pop(resolve_user, None)
    assert r.status_code == status


def test_get_requires_session():
    from backend.main import app
    from fastapi.testclient import TestClient

    assert TestClient(app).get("/api/weekly-check-in").status_code == 401