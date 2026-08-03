"""
Smoke test for issue #158: verify a live deploy at BASE_URL responds correctly.

Run against UAT:
    BASE_URL=https://perf-coach-uat.onrender.com pytest tests/test_smoke_deploy.py -v

Run against PRD:
    BASE_URL=https://perf-coach.onrender.com EXPECTED_ENVIRONMENT=prd pytest tests/test_smoke_deploy.py -v

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


# AC1 (issue #1580): Smoke suite asserts DB schema is at the repo's alembic head.
def test_schema_at_alembic_head(client):
    res = client.get("/api/health/schema")
    assert res.status_code == 200, f"Expected 200 from /api/health/schema, got {res.status_code}"
    body = res.json()
    assert "repo_head" in body, "response must include repo_head"
    assert "db_head" in body, "response must include db_head"
    assert body["db_head"] is not None, "db_head is None — alembic_version table may be empty"
    assert body["db_head"] == body["repo_head"], (
        f"DB schema is stale: DB is at {body['db_head']!r} but repo expects {body['repo_head']!r}"
    )


# AC2 (issue #1580): Auth-gated feature route returns 401 (route exists), not 500.
def test_daily_metrics_requires_auth(client):
    res = client.get("/api/daily-metrics")
    assert res.status_code == 401, (
        f"Expected 401 from auth-gated /api/daily-metrics, got {res.status_code}"
    )
