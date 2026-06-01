"""Tests for issue #215: GET /api/google/connect OAuth entry point"""
import os
import time
import urllib.parse

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import (
    _GOOGLE_SCOPE_DEFAULT,
    _GOOGLE_SCOPE_FITNESS,
    _make_google_state_token,
    _verify_google_state_token,
    app,
)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:9001")
_TEST_SECRET = "test-secret-key-for-google-unit-tests"


# ── State token unit tests (no server needed) ─────────────────────────────────

def test_state_token_round_trip():
    token = _make_google_state_token("user-123", _TEST_SECRET)
    payload = _verify_google_state_token(token, _TEST_SECRET)
    assert payload["user_id"] == "user-123"
    assert "ts" in payload
    assert "nonce" in payload


def test_state_token_has_all_fields():
    token = _make_google_state_token("user-abc", _TEST_SECRET)
    payload = _verify_google_state_token(token, _TEST_SECRET)
    assert set(payload.keys()) >= {"user_id", "ts", "nonce"}


def test_state_token_nonce_unique():
    t1 = _make_google_state_token("u", _TEST_SECRET)
    t2 = _make_google_state_token("u", _TEST_SECRET)
    assert t1 != t2


def test_state_token_wrong_secret_rejected():
    token = _make_google_state_token("user-x", _TEST_SECRET)
    with pytest.raises(ValueError, match="Invalid signature"):
        _verify_google_state_token(token, "wrong-secret")


def test_state_token_tampered_payload_rejected():
    token = _make_google_state_token("user-x", _TEST_SECRET)
    payload_b64, sig_b64 = token.split(".", 1)
    tampered = payload_b64 + "X" + "." + sig_b64
    with pytest.raises(ValueError):
        _verify_google_state_token(tampered, _TEST_SECRET)


def test_state_token_expired():
    token = _make_google_state_token("user-x", _TEST_SECRET)
    with pytest.raises(ValueError, match="expired"):
        _verify_google_state_token(token, _TEST_SECRET, max_age=0)


def test_state_token_just_within_expiry():
    token = _make_google_state_token("user-x", _TEST_SECRET)
    payload = _verify_google_state_token(token, _TEST_SECRET, max_age=600)
    assert payload["user_id"] == "user-x"


# ── Integration tests (require running server + env vars) ─────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


def test_google_connect_default_scope(client):
    res = client.get("/api/google/connect")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "authorize_url" in body
    url = body["authorize_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["scope"] == [_GOOGLE_SCOPE_DEFAULT]
    assert qs["response_type"] == ["code"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert "client_id" in qs
    assert "redirect_uri" in qs
    assert "state" in qs
    assert qs["state"][0]  # non-empty


def test_google_connect_fitness_scope(client):
    res = client.get("/api/google/connect", params={"scope": _GOOGLE_SCOPE_FITNESS})
    assert res.status_code == 200, res.text
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(res.json()["authorize_url"]).query)
    assert qs["scope"] == [_GOOGLE_SCOPE_FITNESS]


def test_google_connect_invalid_scope(client):
    res = client.get("/api/google/connect", params={"scope": "https://www.googleapis.com/auth/calendar"})
    assert res.status_code == 422
    body = res.json()
    assert "detail" in body
    detail_lower = body["detail"].lower()
    assert "scope" in detail_lower or "invalid" in detail_lower


def test_google_connect_state_verifiable(client):
    """State from authorize_url must decode and verify against GOOGLE_STATE_SECRET."""
    secret = os.environ.get("GOOGLE_STATE_SECRET")
    if not secret:
        pytest.skip("GOOGLE_STATE_SECRET not set")
    res = client.get("/api/google/connect")
    assert res.status_code == 200
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(res.json()["authorize_url"]).query)
    state = qs["state"][0]
    payload = _verify_google_state_token(state, secret)
    assert "user_id" in payload
    assert "ts" in payload
    assert "nonce" in payload
    assert abs(time.time() - payload["ts"]) < 60


def test_google_connect_missing_client_id(monkeypatch):
    # monkeypatch affects the in-process app; must use TestClient, not the live httpx client
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    with TestClient(app) as tc:
        res = tc.get("/api/google/connect")
    assert res.status_code == 500
    assert "GOOGLE_CLIENT_ID" in res.json()["detail"]


def test_google_connect_missing_client_secret(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "fake-id")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with TestClient(app) as tc:
        res = tc.get("/api/google/connect")
    assert res.status_code == 500
    assert "GOOGLE_CLIENT_SECRET" in res.json()["detail"]


def test_google_connect_missing_state_secret(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "fake-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "fake-secret")
    monkeypatch.delenv("GOOGLE_STATE_SECRET", raising=False)
    with TestClient(app) as tc:
        res = tc.get("/api/google/connect")
    assert res.status_code == 500
    assert "GOOGLE_STATE_SECRET" in res.json()["detail"]
