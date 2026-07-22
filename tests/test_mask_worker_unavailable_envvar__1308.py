"""Tests for issue #1308: mask env-var name from WorkerUnavailable 503 detail body.

AC coverage:
  AC1 - WorkerUnavailable raised when WORKER_BASE_URL is missing uses a generic
        message (no env-var name in the exception text)
  AC2 - WorkerUnavailable raised when WORKER_SHARED_SECRET is missing uses a
        generic message (no env-var name in the exception text)
  AC3 - The specific env-var name is logged at WARNING level server-side (not
        surfaced in the exception message)
"""
import importlib
import logging
from unittest.mock import patch
import uuid
import pytest

import backend.services.worker_client as worker_client


# ── AC1: missing WORKER_BASE_URL → generic exception message ─────────────────

def test_missing_base_url_raises_generic_message(monkeypatch):
    """WorkerUnavailable for missing WORKER_BASE_URL must NOT contain the env-var name."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.delenv("WORKER_BASE_URL", raising=False)
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    with pytest.raises(worker_client.WorkerUnavailable) as exc_info:
        worker_client._post("/internal/sync/run", {})

    msg = str(exc_info.value)
    assert "WORKER_BASE_URL" not in msg, (
        f"env-var name leaked into exception message: {msg!r}"
    )


# ── AC2: missing WORKER_SHARED_SECRET → generic exception message ─────────────

def test_missing_shared_secret_raises_generic_message(monkeypatch):
    """WorkerUnavailable for missing WORKER_SHARED_SECRET must NOT contain the env-var name."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.delenv("WORKER_SHARED_SECRET", raising=False)

    with pytest.raises(worker_client.WorkerUnavailable) as exc_info:
        worker_client._post("/internal/sync/run", {})

    msg = str(exc_info.value)
    assert "WORKER_SHARED_SECRET" not in msg, (
        f"env-var name leaked into exception message: {msg!r}"
    )


# ── AC3: env-var name logged at WARNING level ─────────────────────────────────

def test_missing_base_url_logs_warning_with_envvar_name(monkeypatch, caplog):
    """Missing WORKER_BASE_URL must be logged at WARNING with the env-var name."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.delenv("WORKER_BASE_URL", raising=False)
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    with caplog.at_level(logging.WARNING, logger="backend.services.worker_client"):
        with pytest.raises(worker_client.WorkerUnavailable):
            worker_client._post("/internal/sync/run", {})

    assert any(
        "WORKER_BASE_URL" in record.message and record.levelno == logging.WARNING
        for record in caplog.records
    ), f"Expected WARNING log containing 'WORKER_BASE_URL', got: {caplog.records}"


def test_missing_shared_secret_logs_warning_with_envvar_name(monkeypatch, caplog):
    """Missing WORKER_SHARED_SECRET must be logged at WARNING with the env-var name."""
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.delenv("WORKER_SHARED_SECRET", raising=False)

    with caplog.at_level(logging.WARNING, logger="backend.services.worker_client"):
        with pytest.raises(worker_client.WorkerUnavailable):
            worker_client._post("/internal/sync/run", {})

    assert any(
        "WORKER_SHARED_SECRET" in record.message and record.levelno == logging.WARNING
        for record in caplog.records
    ), f"Expected WARNING log containing 'WORKER_SHARED_SECRET', got: {caplog.records}"
