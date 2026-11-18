"""Issue #1825 — /v2 shell routes behind REVAMP_UI."""
import time

import pytest
from fastapi.testclient import TestClient

from backend.auth import COOKIE_NAME, create_session_cookie
from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/v2/home",
        "/v2/training/plan",
        "/v2/training/log",
        "/v2/training/trends",
        "/v2/performance",
    ],
)
def test_v2_routes_404_when_flag_off(client, path, monkeypatch):
    monkeypatch.delenv("REVAMP_UI", raising=False)
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 404


def test_v2_training_redirect_when_flag_on(client, monkeypatch):
    monkeypatch.setenv("REVAMP_UI", "1")
    uid = "00000000-0000-0000-0000-000000001825"
    client.cookies.set(COOKIE_NAME, create_session_cookie(uid, time.time()))
    resp = client.get("/v2/training", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/v2/training/plan")


def test_revamp_api_reports_flag(monkeypatch, client):
    monkeypatch.setenv("REVAMP_UI", "1")
    assert client.get("/api/revamp-ui").json()["enabled"] is True
    monkeypatch.delenv("REVAMP_UI", raising=False)
    assert client.get("/api/revamp-ui").json()["enabled"] is False