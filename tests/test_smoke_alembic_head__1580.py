"""
Smoke probes for issue #1580: alembic-head and feature-route checks.

Run against UAT:
    BASE_URL=https://perf-coach-uat.onrender.com pytest tests/test_smoke_alembic_head__1580.py -v

Run against local server (default):
    pytest tests/test_smoke_alembic_head__1580.py -v
"""
import os

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:9001").rstrip("/")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


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
