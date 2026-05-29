"""
Tests for issue #156: health check and environment metadata endpoints
Server under test: http://127.0.0.1:9001
"""
import time

import httpx
import pytest

BASE = "http://127.0.0.1:9001"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── GET /api/health ──────────────────────────────────────────────────────────

def test_health_returns_200(client):
    res = client.get("/api/health")
    assert res.status_code == 200


def test_health_json_shape(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "environment" in body
    assert "version" in body
    assert body["db"] in ("ok", "error")
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0


def test_health_no_auth_required(client):
    res = client.get("/api/health")
    assert res.status_code not in (401, 403)


def test_health_uptime_increases(client):
    first = client.get("/api/health").json()["uptime_seconds"]
    time.sleep(2)
    second = client.get("/api/health").json()["uptime_seconds"]
    assert second >= first + 1


def test_health_environment_field(client):
    body = client.get("/api/health").json()
    assert isinstance(body["environment"], str)
    assert len(body["environment"]) > 0


def test_health_version_field(client):
    body = client.get("/api/health").json()
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0


# ── GET /api/env ─────────────────────────────────────────────────────────────

def test_env_returns_200(client):
    res = client.get("/api/env")
    assert res.status_code == 200


def test_env_json_shape(client):
    body = client.get("/api/env").json()
    assert "environment" in body
    assert isinstance(body["environment"], str)
    assert len(body["environment"]) > 0


def test_env_no_auth_required(client):
    res = client.get("/api/env")
    assert res.status_code not in (401, 403)


def test_env_no_user_id_required(client):
    res = client.get("/api/env")
    assert res.status_code == 200


def test_env_matches_health_environment(client):
    env_body = client.get("/api/env").json()
    health_body = client.get("/api/health").json()
    assert env_body["environment"] == health_body["environment"]
