"""PUT /api/fuel/settings must echo `auto_periodize` in its response (#1676).

Regression guard for the #1414 fix. The PUT handler responds with
`fuel.get_today_payload(...)` rather than the settings dict, and that payload
once omitted `auto_periodize` — so the Weight tab's toggle appeared to snap
back after every save. #1414 added the field at the serialization site in
`backend/services/fuel.py` (the `"auto_periodize": settings["auto_periodize"]`
entry of the returned dict) but landed without a committed test; the only
assertion lived in `tests/test_deficit_periodization_http__1357.py`, which
needs a live UAT server and so never runs in CI (#1674 review).

This file runs fully in-process through the real FastAPI app:

  * the real `put_fuel_settings` route (`backend/routers/fuel.py`)
  * the real `fuel.update_settings` (validation + attribute writes)
  * the real `fuel.get_today_payload` (the serializer under test)

Only the storage boundary is faked: the router's session factory becomes a
no-op context manager, and the leaf helpers that read the database
(`get_or_create_settings`, `_resolve_week_phase_from_db`, `_fetch_lean_mass`,
`training_burn_kcal`, `get_entry`, and the weight-plan lookup behind
GET /api/fuel/settings) are stubbed to return deterministic values. A future refactor that drops the field from the today payload — or
that starts returning the request body instead of persisted state — fails
here without any live service.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import FuelSettings
from backend.routers import fuel as fuel_router
from backend.services import fuel as fuel_svc

_UID = uuid.UUID("00000000-0000-0000-0000-00000000a414")


class _NoOpSession:
    """Stands in for the SQLAlchemy Session the router opens per request.

    `update_settings` calls `commit()` and `refresh(row)` on it; with a real
    Session, `refresh` on a transient row raises. Here both are no-ops so the
    in-memory row IS the persisted state the response must reflect.
    """

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass

    def refresh(self, _row):
        pass

    def close(self):
        pass


@pytest.fixture
def fuel_row(monkeypatch):
    """One in-memory FuelSettings row shared by every service call in a request.

    Returned so tests can assert the response reflects what was actually
    written to the row, not merely what the request asked for.
    """
    row = FuelSettings(**fuel_svc._default_settings_dict(_UID))
    row.auto_periodize = True

    monkeypatch.setattr(fuel_router, "Session", lambda _engine: _NoOpSession())
    monkeypatch.setattr(fuel_svc, "get_or_create_settings", lambda user_id, db=None: row)
    monkeypatch.setattr(
        fuel_svc, "_resolve_week_phase_from_db",
        lambda user_id, target_date, db: ("base", "Base week — full deficit", None),
    )
    monkeypatch.setattr(
        fuel_svc, "_fetch_lean_mass",
        lambda user_id, settings_row, db: {"lean_mass_kg": 53.2, "source": "estimated"},
    )
    monkeypatch.setattr(
        fuel_svc, "training_burn_kcal",
        lambda *a, **kw: {"burn": 0, "day_type": "rest", "session_status": None, "is_actual": False},
    )
    monkeypatch.setattr(fuel_svc, "get_entry", lambda user_id, entry_date, db=None: None)
    # GET /api/fuel/settings also looks up the active weight plan for the
    # plan-linkage fields; no plan is the simplest deterministic answer.
    monkeypatch.setattr(fuel_router._weight_plan_svc, "get_active_target", lambda db, user_id: None)
    return row


@pytest.fixture
def client(as_user, fuel_row):
    as_user(_UID)
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.parametrize("toggle", [False, True], ids=["off", "on"])
def test_put_settings_response_carries_auto_periodize(client, fuel_row, toggle):
    """The #1414 behaviour, both directions.

    Start from the opposite state so a response that merely echoes the
    pre-existing value (or the default True) cannot pass by accident.
    """
    fuel_row.auto_periodize = not toggle

    r = client.put("/api/fuel/settings", json={"auto_periodize": toggle})

    assert r.status_code == 200, r.text
    body = r.json()
    assert "auto_periodize" in body, (
        "PUT /api/fuel/settings response dropped `auto_periodize` — "
        "get_today_payload() must include it (regression of #1414)"
    )
    assert body["auto_periodize"] is toggle
    # The response reflects the persisted row, not just the request body.
    assert fuel_row.auto_periodize is toggle


def test_put_without_auto_periodize_still_reports_current_value(client, fuel_row):
    """Saving an unrelated setting must not make the field vanish or flip.

    The Weight tab re-renders its toggle from every PUT response, so the field
    has to be present on every save, not only when the toggle itself changed.
    """
    fuel_row.auto_periodize = False

    r = client.put("/api/fuel/settings", json={"deficit_kcal": 250})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["auto_periodize"] is False
    assert body["deficit_target"] == 250
    assert fuel_row.auto_periodize is False


def test_put_response_matches_settings_read_back(client, fuel_row):
    """The PUT response and GET /api/fuel/settings agree on auto_periodize.

    Both derive from the same row; disagreement would mean one of the two
    payload builders had dropped or reinterpreted the field.
    """
    put = client.put("/api/fuel/settings", json={"auto_periodize": False})
    assert put.status_code == 200, put.text

    get = client.get("/api/fuel/settings")
    assert get.status_code == 200, get.text

    assert put.json()["auto_periodize"] is False
    assert get.json()["auto_periodize"] is False
