"""
Tests for issue #156: Add health check and environment metadata endpoints.
One test per Acceptance Criterion.
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


def test_health_returns_200(client):
    res = client.get("/api/health")
    assert res.status_code == 200


def test_health_response_shape(client):
    res = client.get("/api/health")
    body = res.json()
    assert "status" in body
    assert "environment" in body
    assert "version" in body
    assert "db" in body
    assert "uptime_seconds" in body


def test_health_status_ok(client):
    res = client.get("/api/health")
    assert res.json()["status"] == "ok"


def test_health_db_field_valid(client):
    res = client.get("/api/health")
    assert res.json()["db"] in ("ok", "error")


def test_health_uptime_is_positive(client):
    res = client.get("/api/health")
    assert res.json()["uptime_seconds"] >= 0


def test_health_uptime_increases(client):
    first = client.get("/api/health").json()["uptime_seconds"]
    time.sleep(2)
    second = client.get("/api/health").json()["uptime_seconds"]
    assert second > first


def test_health_no_auth_required(client):
    """Health endpoint must return 200 without any auth header."""
    res = httpx.get(f"{BASE}/api/health", timeout=10)
    assert res.status_code == 200


def test_env_returns_200(client):
    res = client.get("/api/env")
    assert res.status_code == 200


def test_env_response_shape(client):
    res = client.get("/api/env")
    body = res.json()
    assert "environment" in body
    assert isinstance(body["environment"], str)


def test_env_no_auth_required(client):
    """Env endpoint must return 200 without any auth header."""
    res = httpx.get(f"{BASE}/api/env", timeout=10)
    assert res.status_code == 200


def test_health_version_field_is_string(client):
    res = client.get("/api/health")
    assert isinstance(res.json()["version"], str)


def test_health_environment_field_is_string(client):
    res = client.get("/api/health")
    assert isinstance(res.json()["environment"], str)
