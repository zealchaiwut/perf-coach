"""P5-11 revamp cutover redirects and legacy hatch."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend.auth import COOKIE_NAME, create_session_cookie
from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize(
    "legacy,expected_status",
    [("/home", 302), ("/log", 302), ("/training", 302)],
)
def test_revamp_redirects_without_legacy(client, legacy, expected_status, monkeypatch):
    monkeypatch.setenv("REVAMP_UI", "1")
    uid = "00000000-0000-0000-0000-000000001873"
    client.cookies.set(COOKIE_NAME, create_session_cookie(uid, time.time()))
    r = client.get(legacy, follow_redirects=False)
    assert r.status_code == expected_status
    assert "/v2/" in r.headers["location"]


def test_legacy_escape_serves_old_home(client, monkeypatch):
    monkeypatch.setenv("REVAMP_UI", "1")
    monkeypatch.setenv("REVAMP_LEGACY_DEADLINE", "2099-12-31")
    uid = "00000000-0000-0000-0000-000000001873"
    client.cookies.set(COOKIE_NAME, create_session_cookie(uid, time.time()))
    r = client.get("/home?legacy=1")
    assert r.status_code == 200
    assert "home" in r.text.lower() or "Welcome" in r.text


def test_cleanup_doc_exists():
    from pathlib import Path

    text = Path("docs/revamp/CLEANUP.md").read_text(encoding="utf-8")
    assert "training-log.html" in text
    assert "/v2/home" in text