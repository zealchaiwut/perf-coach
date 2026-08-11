"""Coach export — the two endpoints (spec §5).

- ``GET /api/coach/export`` serves the payload alone (inspection, Hermes, tests).
- ``GET /api/coach/export/paste`` serves the complete blob as text/plain: one
  request, one clipboard write, so a partially-assembled blob can never be
  pasted as if it were whole.

Both are identity-scoped via ``resolve_user`` — anonymous requests get 401, never
a fallback user's data. Serving the paste blob also stamps
``users.last_coach_export_at``, which the next export reports as
``meta.previous_export_date``.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.services import coach_export as ce

EXPORT_URL = "/api/coach/export"
PASTE_URL = "/api/coach/export/paste"

_FAKE_EXPORT = {
    "meta": {
        "schema_version": ce.SCHEMA_VERSION,
        "prompt_version": ce.PROMPT_VERSION,
        "window_days": 90,
        "degraded": [],
    },
    "training": {"sessions": [{"date": "2026-07-25", "type": "run", "tss": 97}]},
    "findings": [],
}


class _StubUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.name = "endpoint-test"


@pytest.fixture
def stub_user(monkeypatch):
    # Inline GET export is for local/debug; queue mode fails those closed (Phase C).
    monkeypatch.setenv("COACH_EXPORT_VIA_QUEUE", "0")
    user = _StubUser()
    app.dependency_overrides[resolve_user] = lambda: user
    yield user
    app.dependency_overrides.pop(resolve_user, None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def stub_build(monkeypatch):
    """Replace build_export; these tests are about the HTTP contract, and
    assembly has its own suite."""
    calls: list[dict] = []

    def _build(user_id, window_days=ce.DEFAULT_WINDOW_DAYS, today=None):
        calls.append({"user_id": user_id, "window_days": window_days})
        payload = json.loads(json.dumps(_FAKE_EXPORT))
        payload["meta"]["window_days"] = window_days
        return payload

    monkeypatch.setattr(ce, "build_export", _build)
    return calls


@pytest.fixture
def stub_stamp(monkeypatch):
    """No DB in this environment — record the stamp attempt instead."""
    import backend.routers.coach as coach_router

    stamped: list = []

    class _FakeQuery:
        def filter(self, *_a, **_k):
            return self

        def update(self, values):
            stamped.append(values)
            return 1

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def query(self, *_a, **_k):
            return _FakeQuery()

        def commit(self):
            pass

    monkeypatch.setattr(coach_router, "Session", lambda *_a, **_k: _FakeSession())
    return stamped


# ── GET /api/coach/export ────────────────────────────────────────────────────

def test_export_returns_the_payload_as_json(client, stub_user, stub_build):
    res = client.get(EXPORT_URL)
    assert res.status_code == 200
    assert res.json()["meta"]["schema_version"] == ce.SCHEMA_VERSION


def test_export_defaults_to_the_ninety_day_window(client, stub_user, stub_build):
    client.get(EXPORT_URL)
    assert stub_build[0]["window_days"] == ce.DEFAULT_WINDOW_DAYS == 90


def test_export_honours_an_explicit_window(client, stub_user, stub_build):
    res = client.get(f"{EXPORT_URL}?window=30")
    assert res.status_code == 200
    assert stub_build[0]["window_days"] == 30
    assert res.json()["meta"]["window_days"] == 30


def test_export_is_scoped_to_the_session_user(client, stub_user, stub_build):
    client.get(EXPORT_URL)
    assert stub_build[0]["user_id"] == stub_user.id


@pytest.mark.parametrize("window", [0, 1000])
def test_export_rejects_an_out_of_range_window_with_422(
    client, stub_user, monkeypatch, window
):
    def _raise(user_id, window_days=90, today=None):
        raise ValueError(f"window_days must be between 7 and 365, got {window_days}")

    monkeypatch.setattr(ce, "build_export", _raise)
    res = client.get(f"{EXPORT_URL}?window={window}")
    assert res.status_code == 422
    assert "window" in res.json()["detail"]


def test_export_rejects_a_non_numeric_window(client, stub_user, stub_build):
    res = client.get(f"{EXPORT_URL}?window=ninety")
    assert res.status_code == 422


# ── GET /api/coach/export/paste ──────────────────────────────────────────────

def test_paste_returns_plain_text(client, stub_user, stub_build, stub_stamp):
    res = client.get(PASTE_URL)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")


def test_paste_returns_template_then_payload(client, stub_user, stub_build, stub_stamp):
    body = client.get(PASTE_URL).text
    assert body.startswith("# Daily coach message")
    assert body.index("## Rules") < body.index("```json")
    payload = json.loads(body.split("```json", 1)[1].rsplit("```", 1)[0])
    assert payload["meta"]["prompt_version"] == ce.PROMPT_VERSION


def test_paste_is_a_single_request_no_client_assembly(
    client, stub_user, stub_build, stub_stamp
):
    """The client must never have to join two responses — a half-fetched blob
    would be pasted as if it were whole."""
    client.get(PASTE_URL)
    assert len(stub_build) == 1


def test_paste_honours_the_window_param(client, stub_user, stub_build, stub_stamp):
    client.get(f"{PASTE_URL}?window=45")
    assert stub_build[0]["window_days"] == 45


def test_paste_stamps_the_export_timestamp(client, stub_user, stub_build, stub_stamp):
    client.get(PASTE_URL)
    assert len(stub_stamp) == 1
    assert "last_coach_export_at" in stub_stamp[0]


def test_paste_does_not_stamp_when_the_export_fails(client, stub_user, monkeypatch, stub_stamp):
    """A failed export must not consume the "nothing moved since last time"
    signal — the athlete never saw a message."""
    def _raise(user_id, window_days=90, today=None):
        raise ValueError("window_days must be between 7 and 365, got 1")

    monkeypatch.setattr(ce, "build_export", _raise)
    res = client.get(f"{PASTE_URL}?window=1")
    assert res.status_code == 422
    assert stub_stamp == []


def test_paste_still_serves_the_blob_when_stamping_fails(
    client, stub_user, stub_build, monkeypatch
):
    """The stamp is a convenience; losing it must not cost the athlete the copy."""
    import backend.routers.coach as coach_router

    def _boom(*_a, **_k):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(coach_router, "Session", _boom)
    res = client.get(PASTE_URL)
    assert res.status_code == 200
    assert res.text.startswith("# Daily coach message")


# ── Identity scoping ─────────────────────────────────────────────────────────

def test_both_endpoints_require_a_session(client):
    """No dependency override here: an anonymous request must not get data."""
    app.dependency_overrides.pop(resolve_user, None)
    for url in (EXPORT_URL, PASTE_URL):
        res = client.get(url)
        assert res.status_code in (401, 403), f"{url} served an anonymous request"


def test_inline_export_fails_closed_when_queue_enabled(client, stub_user, monkeypatch):
    """Phase C: queue mode must not serve heavy inline GET paste/export."""
    monkeypatch.setenv("COACH_EXPORT_VIA_QUEUE", "1")
    for url in (EXPORT_URL, PASTE_URL):
        res = client.get(url)
        assert res.status_code == 503, f"{url} expected 503 in queue mode, got {res.status_code}"
        assert "queue" in (res.json().get("detail") or "").lower()
