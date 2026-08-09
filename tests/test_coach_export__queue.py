"""Coach export queue endpoints (worker-backed build)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app


class _StubUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


@pytest.fixture
def stub_user():
    user = _StubUser()
    app.dependency_overrides[resolve_user] = lambda: user
    yield user
    app.dependency_overrides.pop(resolve_user, None)


@pytest.fixture
def client():
    return TestClient(app)


def test_post_coach_export_job_enqueues(client, stub_user, monkeypatch):
    monkeypatch.setenv("COACH_EXPORT_VIA_QUEUE", "1")
    captured = {}

    def _delegate(user_id, *, kind, window):
        captured.update({"user_id": user_id, "kind": kind, "window": window})
        return {"queued": True, "job_id": "job-1"}

    monkeypatch.setattr(
        "backend.services.worker_client.delegate_coach_export", _delegate
    )

    res = client.post("/api/coach/export/jobs", json={"kind": "consult"})
    assert res.status_code == 202
    body = res.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == "queued"
    assert captured["kind"] == "consult"
    assert captured["user_id"] == str(stub_user.id)


def test_get_coach_export_job_status(client, stub_user, monkeypatch):
    job_id = str(uuid.uuid4())

    def _get_owned(job_id_arg, user_id, *, job_type=None):
        assert job_type == "coach_export"
        return {
            "id": job_id_arg,
            "status": "done",
            "result": {
                "kind": "consult",
                "char_count": 12000,
                "built_at": "2026-08-09T00:00:00+00:00",
                "degraded": [],
                "blob": "hello",
            },
            "error": None,
            "created_at": None,
            "started_at": None,
            "finished_at": None,
        }

    monkeypatch.setattr("backend.services.job_queue.get_owned_job", _get_owned)

    res = client.get(f"/api/coach/export/jobs/{job_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "done"
    assert body["char_count"] == 12000
    assert "blob" not in body


def test_get_coach_export_job_blob(client, stub_user, monkeypatch):
    job_id = str(uuid.uuid4())

    monkeypatch.setattr(
        "backend.services.job_queue.get_owned_job",
        lambda jid, uid, job_type=None: {
            "id": jid,
            "status": "done",
            "result": {"blob": "paste-blob"},
            "error": None,
        },
    )

    res = client.get(f"/api/coach/export/jobs/{job_id}/blob")
    assert res.status_code == 200
    assert res.text == "paste-blob"


def test_assemble_performance_does_not_import_main():
    import ast
    from pathlib import Path

    src = Path("backend/services/coach_export.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_assemble_performance":
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.ImportFrom) and child.module == "backend.main":
                raise AssertionError("_assemble_performance must not import backend.main")
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if alias.name == "backend.main":
                        raise AssertionError("_assemble_performance must not import backend.main")
        return
    raise AssertionError("_assemble_performance not found")
