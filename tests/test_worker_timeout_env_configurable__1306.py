"""Tests for issue #1306: make worker HTTP timeout env-configurable.

AC coverage:
  AC1 - get_worker_timeout() reads WORKER_TIMEOUT_SECONDS env var (default 10)
  AC2 - _post passes the configured timeout to urlopen
  AC3 - delegate_sync accepts a per-call timeout kwarg that overrides the env var
  AC4 - delegate_backfill accepts a per-call timeout kwarg that overrides the env var
  AC5 - WORKER_TIMEOUT_SECONDS is documented in the module docstring
"""
import json
import uuid
from unittest.mock import MagicMock, patch
import importlib

import pytest
import backend.services.worker_client as worker_client


# ── AC1: get_worker_timeout reads env var ────────────────────────────────────

def test_get_worker_timeout_default(monkeypatch):
    """Default timeout is 10 when WORKER_TIMEOUT_SECONDS is unset."""
    monkeypatch.delenv("WORKER_TIMEOUT_SECONDS", raising=False)
    importlib.reload(worker_client)
    assert worker_client.get_worker_timeout() == 10


def test_get_worker_timeout_from_env(monkeypatch):
    """WORKER_TIMEOUT_SECONDS env var overrides the default timeout."""
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "30")
    importlib.reload(worker_client)
    assert worker_client.get_worker_timeout() == 30


def test_get_worker_timeout_env_invalid_falls_back_to_default(monkeypatch):
    """Non-integer WORKER_TIMEOUT_SECONDS falls back to 10."""
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "notanumber")
    importlib.reload(worker_client)
    assert worker_client.get_worker_timeout() == 10


# ── AC2: _post passes configured timeout to urlopen ─────────────────────────

def test_post_uses_env_timeout(monkeypatch):
    """_post(path, payload) passes WORKER_TIMEOUT_SECONDS to urlopen."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "25")
    importlib.reload(worker_client)

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        ctx = MagicMock()
        ctx.__enter__ = lambda s: s
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.read = MagicMock(return_value=b'{"ok": true}')
        return ctx

    with patch("backend.services.worker_client._urllib_request.urlopen", side_effect=fake_urlopen):
        worker_client._post("/internal/sync/run", {"user_id": "x"})

    assert captured["timeout"] == 25


def test_post_explicit_timeout_overrides_env(monkeypatch):
    """_post(path, payload, timeout=N) uses N regardless of env var."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "25")
    importlib.reload(worker_client)

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        ctx = MagicMock()
        ctx.__enter__ = lambda s: s
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.read = MagicMock(return_value=b'{"ok": true}')
        return ctx

    with patch("backend.services.worker_client._urllib_request.urlopen", side_effect=fake_urlopen):
        worker_client._post("/internal/sync/run", {"user_id": "x"}, timeout=5)

    assert captured["timeout"] == 5


# ── AC3: delegate_sync per-call timeout ──────────────────────────────────────

def test_delegate_sync_accepts_timeout_kwarg(monkeypatch):
    """delegate_sync(timeout=N) passes N to the underlying _post call."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "10")
    importlib.reload(worker_client)

    captured = {}

    def fake_post(path, payload, timeout=None):
        captured["timeout"] = timeout
        return {"started": True}

    user_id = str(uuid.uuid4())
    with patch.object(worker_client, "_post", side_effect=fake_post):
        worker_client.delegate_sync(user_id, ["strava"], full=True, timeout=60)

    assert captured["timeout"] == 60


def test_delegate_sync_uses_env_timeout_by_default(monkeypatch):
    """delegate_sync without explicit timeout uses WORKER_TIMEOUT_SECONDS."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "45")
    importlib.reload(worker_client)

    captured = {}

    def fake_post(path, payload, timeout=None):
        captured["timeout"] = timeout
        return {"started": True}

    user_id = str(uuid.uuid4())
    with patch.object(worker_client, "_post", side_effect=fake_post):
        worker_client.delegate_sync(user_id, ["strava"], full=True)

    assert captured["timeout"] == 45


# ── AC4: delegate_backfill per-call timeout ───────────────────────────────────

def test_delegate_backfill_accepts_timeout_kwarg(monkeypatch):
    """delegate_backfill(timeout=N) passes N to the underlying _post call."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "10")
    importlib.reload(worker_client)

    captured = {}

    def fake_post(path, payload, timeout=None):
        captured["timeout"] = timeout
        return {"started": True}

    user_id = str(uuid.uuid4())
    with patch.object(worker_client, "_post", side_effect=fake_post):
        worker_client.delegate_backfill(user_id, timeout=90)

    assert captured["timeout"] == 90


def test_delegate_backfill_uses_env_timeout_by_default(monkeypatch):
    """delegate_backfill without explicit timeout uses WORKER_TIMEOUT_SECONDS."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "55")
    importlib.reload(worker_client)

    captured = {}

    def fake_post(path, payload, timeout=None):
        captured["timeout"] = timeout
        return {"started": True}

    user_id = str(uuid.uuid4())
    with patch.object(worker_client, "_post", side_effect=fake_post):
        worker_client.delegate_backfill(user_id)

    assert captured["timeout"] == 55


# ── AC5: WORKER_TIMEOUT_SECONDS documented in module docstring ───────────────

def test_worker_timeout_env_var_documented():
    """WORKER_TIMEOUT_SECONDS appears in worker_client module docstring."""
    importlib.reload(worker_client)
    assert "WORKER_TIMEOUT_SECONDS" in (worker_client.__doc__ or "")
