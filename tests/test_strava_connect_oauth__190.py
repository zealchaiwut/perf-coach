"""Tests for issue #190: GET /api/strava/connect OAuth flow endpoint"""
import os
import time
import urllib.parse

import httpx
import pytest

from backend.main import _make_strava_state_token, _verify_strava_state_token

BASE_URL = os.environ.get("BASE_URL", "http://localhost:9001")
_TEST_SECRET = "test-secret-key-for-unit-tests"


# ── State token unit tests (no server needed) ─────────────────────────────────

def test_state_token_round_trip():
    token = _make_strava_state_token("user-123", _TEST_SECRET)
    payload = _verify_strava_state_token(token, _TEST_SECRET)
    assert payload["user_id"] == "user-123"
    assert "ts" in payload
    assert "nonce" in payload


def test_state_token_has_all_fields():
    token = _make_strava_state_token("user-abc", _TEST_SECRET)
    payload = _verify_strava_state_token(token, _TEST_SECRET)
    assert set(payload.keys()) >= {"user_id", "ts", "nonce"}


def test_state_token_nonce_unique():
    t1 = _make_strava_state_token("u", _TEST_SECRET)
    t2 = _make_strava_state_token("u", _TEST_SECRET)
    assert t1 != t2


def test_state_token_wrong_secret_rejected():
    token = _make_strava_state_token("user-x", _TEST_SECRET)
    with pytest.raises(ValueError, match="Invalid signature"):
        _verify_strava_state_token(token, "wrong-secret")


def test_state_token_tampered_payload_rejected():
    token = _make_strava_state_token("user-x", _TEST_SECRET)
    payload_b64, sig_b64 = token.split(".", 1)
    # Append a char to corrupt payload
    tampered = payload_b64 + "X" + "." + sig_b64
    with pytest.raises(ValueError):
        _verify_strava_state_token(tampered, _TEST_SECRET)


def test_state_token_expired():
    token = _make_strava_state_token("user-x", _TEST_SECRET)
    # Verify with max_age=0 forces immediate expiry
    with pytest.raises(ValueError, match="expired"):
        _verify_strava_state_token(token, _TEST_SECRET, max_age=0)


def test_state_token_just_within_expiry():
    token = _make_strava_state_token("user-x", _TEST_SECRET)
    # Should pass with generous max_age
    payload = _verify_strava_state_token(token, _TEST_SECRET, max_age=600)
    assert payload["user_id"] == "user-x"


# ── Integration tests (require running server + env vars) ─────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


def test_strava_connect_default_scope(client):
    res = client.get("/api/strava/connect")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "authorize_url" in body
    url = body["authorize_url"]
    assert url.startswith("https://www.strava.com/oauth/authorize")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["scope"] == ["activity:read_all"]
    assert qs["response_type"] == ["code"]
    assert qs["approval_prompt"] == ["auto"]
    assert "client_id" in qs
    assert "redirect_uri" in qs
    assert "state" in qs


def test_strava_connect_explicit_scope_read(client):
    res = client.get("/api/strava/connect", params={"scope": "read"})
    assert res.status_code == 200, res.text
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(res.json()["authorize_url"]).query)
    assert qs["scope"] == ["read"]


def test_strava_connect_explicit_scope_activity_read(client):
    res = client.get("/api/strava/connect", params={"scope": "activity:read"})
    assert res.status_code == 200, res.text
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(res.json()["authorize_url"]).query)
    assert qs["scope"] == ["activity:read"]


def test_strava_connect_invalid_scope(client):
    res = client.get("/api/strava/connect", params={"scope": "bad_scope"})
    assert res.status_code == 422
    body = res.json()
    assert "detail" in body
    assert "bad_scope" in body["detail"] or "scope" in body["detail"].lower()


def test_strava_connect_state_verifiable(client):
    """State from authorize_url must decode and verify against STRAVA_STATE_SECRET."""
    secret = os.environ.get("STRAVA_STATE_SECRET")
    if not secret:
        pytest.skip("STRAVA_STATE_SECRET not set")
    res = client.get("/api/strava/connect")
    assert res.status_code == 200
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(res.json()["authorize_url"]).query)
    state = qs["state"][0]
    payload = _verify_strava_state_token(state, secret)
    assert "user_id" in payload
    assert "ts" in payload
    assert "nonce" in payload
    assert abs(time.time() - payload["ts"]) < 60
