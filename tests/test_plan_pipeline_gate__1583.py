"""Tests for issue #1583: gate plan draft refresh/regen on pipeline_enabled().

Acceptance Criteria:
  AC1 — enqueue_plan_draft returns None (no-op) when PLAN_PIPELINE=legacy
  AC2 — POST /api/plan/draft/refresh returns 4xx when pipeline is off
  AC3 — POST /api/plan/draft/ops/regen returns 4xx when pipeline is off
  AC4 — GET /api/plan/draft-status behavior unchanged (still returns pipeline_off flag)
"""
from __future__ import annotations

import uuid
import unittest.mock as mock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import resolve_user
from backend.models import User
from backend.services import plan_draft as pd


def _make_user():
    u = User(name="test-pipeline-gate-1583-" + uuid.uuid4().hex[:8])
    u.id = uuid.uuid4()
    return u


# ── AC1: enqueue_plan_draft is a no-op when pipeline disabled ────────────────

def test_enqueue_plan_draft_returns_none_when_pipeline_off(monkeypatch):
    """AC1: with PLAN_PIPELINE=legacy, enqueue_plan_draft must return None immediately
    without touching the job queue."""
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "legacy")
    called = []

    def _fake_enqueue(*args, **kwargs):
        called.append((args, kwargs))
        return "fake-job-id"

    with mock.patch("backend.services.job_queue.enqueue", _fake_enqueue):
        result = pd.enqueue_plan_draft(uuid.uuid4(), enqueued_by="test")

    assert result is None, f"Expected None when pipeline is off, got {result!r}"
    assert not called, "job_queue.enqueue must not be called when pipeline is off"


def test_enqueue_plan_draft_proceeds_when_pipeline_on(monkeypatch):
    """Inverse sanity: enqueue_plan_draft calls the queue when pipeline is enabled."""
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "skeleton_v2")
    called = []

    def _fake_enqueue(*args, **kwargs):
        called.append((args, kwargs))
        return "fake-job-id"

    with mock.patch("backend.services.job_queue.enqueue", _fake_enqueue):
        result = pd.enqueue_plan_draft(uuid.uuid4(), enqueued_by="test")

    assert result == "fake-job-id"
    assert called, "job_queue.enqueue should be called when pipeline is enabled"


# ── AC2: POST /api/plan/draft/refresh returns 4xx when pipeline off ──────────

def test_refresh_endpoint_400_when_pipeline_off(monkeypatch):
    """AC2: POST /api/plan/draft/refresh must return 4xx when PLAN_PIPELINE=legacy."""
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "legacy")
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        res = client.post("/api/plan/draft/refresh")
        assert res.status_code >= 400, (
            f"AC2 FAIL: expected 4xx when pipeline is off, got {res.status_code}: {res.text}"
        )
        assert res.status_code < 500, (
            f"AC2 FAIL: expected 4xx not 5xx, got {res.status_code}: {res.text}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_refresh_endpoint_202_when_pipeline_on(monkeypatch):
    """Inverse sanity: POST /api/plan/draft/refresh succeeds (202) when pipeline is on."""
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "skeleton_v2")
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with mock.patch("backend.services.plan_draft.enqueue_plan_draft", return_value="fake-job"):
            res = client.post("/api/plan/draft/refresh")
        assert res.status_code == 202, (
            f"Expected 202 when pipeline is on, got {res.status_code}: {res.text}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC3: POST /api/plan/draft/ops/regen returns 4xx when pipeline off ────────

def test_regen_endpoint_400_when_pipeline_off(monkeypatch):
    """AC3: POST /api/plan/draft/ops/regen must return 4xx when PLAN_PIPELINE=legacy."""
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "legacy")
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        res = client.post(
            "/api/plan/draft/ops/regen",
            json={"slot_id": "some-slot-id"},
        )
        assert res.status_code >= 400, (
            f"AC3 FAIL: expected 4xx when pipeline is off, got {res.status_code}: {res.text}"
        )
        assert res.status_code < 500, (
            f"AC3 FAIL: expected 4xx not 5xx, got {res.status_code}: {res.text}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC4: GET /api/plan/draft-status behavior unchanged ───────────────────────

def test_draft_status_returns_pipeline_off_flag_when_legacy(monkeypatch):
    """AC4: GET /api/plan/draft-status still returns pipeline_off:true when disabled."""
    monkeypatch.setattr(pd, "PLAN_PIPELINE", "legacy")
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        res = client.get("/api/plan/draft-status")
        assert res.status_code == 200, (
            f"AC4 FAIL: draft-status must still return 200 when pipeline off, got {res.status_code}"
        )
        data = res.json()
        assert data.get("ready") is False, f"AC4 FAIL: expected ready=False, got {data}"
        assert data.get("pipeline_off") is True, f"AC4 FAIL: expected pipeline_off=True, got {data}"
    finally:
        app.dependency_overrides.pop(resolve_user, None)
