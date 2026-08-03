"""
Smoke test for issue #158: verify a live deploy at BASE_URL responds correctly.

Run against UAT:
    BASE_URL=https://perf-coach-uat.onrender.com pytest tests/test_smoke_deploy.py -v

Run against local server (default):
    pytest tests/test_smoke_deploy.py -v
"""
import os

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:9001").rstrip("/")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


def test_health_returns_200(client):
    res = client.get("/api/health")
    assert res.status_code == 200


def test_health_json_shape(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert isinstance(body["environment"], str) and len(body["environment"]) > 0
    assert isinstance(body["version"], str)
    assert body["db"] in ("ok", "error")
    assert isinstance(body["uptime_seconds"], int) and body["uptime_seconds"] >= 0


def test_health_environment_matches_expected(client):
    expected = os.environ.get("EXPECTED_ENVIRONMENT")
    if not expected:
        pytest.skip("EXPECTED_ENVIRONMENT not set — skipping environment assertion")
    body = client.get("/api/health").json()
    assert body["environment"] == expected.lower()
