"""
Tests for issue #180: health check and environment badge endpoints.
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
    assert client.get("/api/health").status_code == 200


def test_health_response_shape(client):
    body = client.get("/api/health").json()
    assert set(body.keys()) >= {"status", "environment", "version", "db", "uptime_seconds"}


def test_health_status_always_ok(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_health_db_field_values(client):
    assert client.get("/api/health").json()["db"] in ("ok", "error")


def test_health_uptime_is_non_negative_int(client):
    val = client.get("/api/health").json()["uptime_seconds"]
    assert isinstance(val, int) and val >= 0


def test_health_uptime_increases(client):
    first = client.get("/api/health").json()["uptime_seconds"]
    time.sleep(2)
    second = client.get("/api/health").json()["uptime_seconds"]
    assert second >= first + 1


def test_health_environment_is_non_empty_string(client):
    val = client.get("/api/health").json()["environment"]
    assert isinstance(val, str) and len(val) > 0


def test_health_version_is_non_empty_string(client):
    val = client.get("/api/health").json()["version"]
    assert isinstance(val, str) and len(val) > 0


def test_health_no_auth_required(client):
    res = client.get("/api/health")
    assert res.status_code not in (401, 403)


def test_health_no_user_id_required(client):
    assert client.get("/api/health").status_code == 200


# ── GET /api/env ─────────────────────────────────────────────────────────────

def test_env_returns_200(client):
    assert client.get("/api/env").status_code == 200


def test_env_response_shape(client):
    body = client.get("/api/env").json()
    assert "environment" in body
    assert isinstance(body["environment"], str) and len(body["environment"]) > 0


def test_env_no_auth_required(client):
    res = client.get("/api/env")
    assert res.status_code not in (401, 403)


def test_env_no_user_id_required(client):
    assert client.get("/api/env").status_code == 200


def test_env_matches_health_environment(client):
    assert client.get("/api/env").json()["environment"] == \
        client.get("/api/health").json()["environment"]


# ── Static assets ────────────────────────────────────────────────────────────

def test_env_js_is_served(client):
    res = client.get("/js/env.js")
    assert res.status_code == 200
    assert "api/env" in res.text
    assert "data-env" in res.text


def test_styles_css_has_env_badge_selectors(client):
    res = client.get("/css/styles.css")
    assert res.status_code == 200
    css = res.text
    assert '[data-env="prd"]' in css
    assert '[data-env="uat"]' in css
    assert '[data-env="local"]' in css
