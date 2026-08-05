"""Tests for issue #1590: remove redundant timeout resolution in worker_client delegate helpers.

AC coverage:
  AC1 - delegate_sync passes timeout=timeout directly to _post (no inline ternary)
  AC2 - delegate_backfill passes timeout=timeout directly to _post (no inline ternary)
  AC3 - _post retains its existing None → get_worker_timeout() fallback unchanged
  AC4 - No behavioral change: timeout=None resolves to get_worker_timeout() at _post layer
"""
import importlib
import inspect
from unittest.mock import MagicMock, patch

import backend.services.worker_client as worker_client

_TERNARY = "if timeout is not None else get_worker_timeout()"


# ── AC1: delegate_sync passes timeout directly ───────────────────────────────

def test_delegate_sync_no_ternary_in_source():
    """delegate_sync source must not contain the redundant ternary fallback."""
    importlib.reload(worker_client)
    src = inspect.getsource(worker_client.delegate_sync)
    assert _TERNARY not in src


def test_delegate_sync_passes_none_to_post_when_no_timeout(monkeypatch):
    """delegate_sync passes timeout=None to _post when called without a timeout."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    importlib.reload(worker_client)

    captured = {}

    def fake_post(path, payload, timeout=None):
        captured["timeout"] = timeout
        return {"started": True}

    with patch.object(worker_client, "_post", side_effect=fake_post):
        worker_client.delegate_sync("u1", ["strava"])

    assert captured["timeout"] is None


# ── AC2: delegate_backfill passes timeout directly ───────────────────────────

def test_delegate_backfill_no_ternary_in_source():
    """delegate_backfill source must not contain the redundant ternary fallback."""
    importlib.reload(worker_client)
    src = inspect.getsource(worker_client.delegate_backfill)
    assert _TERNARY not in src


def test_delegate_backfill_passes_none_to_post_when_no_timeout(monkeypatch):
    """delegate_backfill passes timeout=None to _post when called without a timeout."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    importlib.reload(worker_client)

    captured = {}

    def fake_post(path, payload, timeout=None):
        captured["timeout"] = timeout
        return {"started": True}

    with patch.object(worker_client, "_post", side_effect=fake_post):
        worker_client.delegate_backfill("u1")

    assert captured["timeout"] is None


# ── AC3: _post still resolves None → get_worker_timeout() ───────────────────

def test_post_resolves_none_timeout_to_env_var(monkeypatch):
    """_post resolves timeout=None to get_worker_timeout() before calling urlopen."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "33")
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
        worker_client._post("/internal/sync/run", {"user_id": "x"}, timeout=None)

    assert captured["timeout"] == 33


# ── AC4: end-to-end — delegates with timeout=None resolve at _post layer ─────

def test_delegate_sync_none_resolves_to_env_end_to_end(monkeypatch):
    """delegate_sync(timeout=None) produces env timeout at the urlopen layer."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "42")
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
        worker_client.delegate_sync("u1", ["strava"])

    assert captured["timeout"] == 42


def test_delegate_backfill_none_resolves_to_env_end_to_end(monkeypatch):
    """delegate_backfill(timeout=None) produces env timeout at the urlopen layer."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("WORKER_TIMEOUT_SECONDS", "38")
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
        worker_client.delegate_backfill("u1")

    assert captured["timeout"] == 38
