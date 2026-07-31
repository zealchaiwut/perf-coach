"""Tests for issue #193: POST /api/stryd/connect and refresh_stryd_session_if_needed."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.stryd import refresh_stryd_session_if_needed

TEST_USER_ID = "00000000-0000-0000-0000-000000000193"

client = TestClient(app)


def _fernet_key(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STRYD_FERNET_KEY", key)
    return key


def _mock_user():
    user = MagicMock()
    user.id = TEST_USER_ID
    return user


def _fake_stryd_resp(token="stryd-session-token-abc", athlete_id=99):
    return {"token": token, "id": athlete_id, "email": "athlete@example.com"}


# ── 1. Successful connect returns 200 with correct shape ─────────────────────

def test_connect_success(monkeypatch):
    _fernet_key(monkeypatch)
    mock_resp = _fake_stryd_resp()

    with patch("backend.services.stryd._call_stryd_signin", return_value=mock_resp), \
         patch("backend.main._stryd_signin", return_value=mock_resp), \
         patch("backend.main._upsert_stryd_credentials") as mock_upsert, \
         patch("backend.main.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.order_by.return_value.first.return_value = _mock_user()
        mock_session_cls.return_value = mock_session

        res = client.post("/api/stryd/connect", json={
            "email": "athlete@example.com",
            "password": "correct-password",
        })

    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["athlete_id"] == 99
    assert body["stryd_user_email"] == "athlete@example.com"
    assert "session_token" not in body
    assert "password" not in body
    mock_upsert.assert_called_once()


# ── 2. Response never exposes session_token or password ──────────────────────

def test_connect_response_has_no_sensitive_fields(monkeypatch):
    _fernet_key(monkeypatch)
    mock_resp = _fake_stryd_resp()

    with patch("backend.main._stryd_signin", return_value=mock_resp), \
         patch("backend.main._upsert_stryd_credentials"), \
         patch("backend.main.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.order_by.return_value.first.return_value = _mock_user()
        mock_session_cls.return_value = mock_session

        res = client.post("/api/stryd/connect", json={
            "email": "athlete@example.com",
            "password": "secret",
        })

    assert res.status_code == 200
    body = res.json()
    assert "session_token" not in body
    assert "password" not in body
    assert "stryd_password_encrypted" not in body


# ── 3. Wrong credentials → 401 with prescribed message ───────────────────────

def test_call_stryd_signin_401_raises_http_exception():
    """_call_stryd_signin converts urllib 401 to HTTPException(401)."""
    import urllib.error
    from fastapi import HTTPException as _HTTPException
    from backend.services.stryd import _call_stryd_signin

    http_err = urllib.error.HTTPError(
        url="https://www.stryd.com/b/email/signin",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(_HTTPException) as exc_info:
            _call_stryd_signin("athlete@example.com", "wrong-password")

    assert exc_info.value.status_code == 401
    assert "Stryd authentication failed" in exc_info.value.detail


def test_connect_wrong_password_via_service(monkeypatch):
    _fernet_key(monkeypatch)
    from fastapi import HTTPException as _HTTPException

    with patch("backend.main._stryd_signin", side_effect=_HTTPException(
        status_code=401,
        detail="Stryd authentication failed — check email and password.",
    )):
        res = client.post("/api/stryd/connect", json={
            "email": "athlete@example.com",
            "password": "wrong-password",
        })

    assert res.status_code == 401
    assert "Stryd authentication failed" in res.json()["detail"]
    assert "check email and password" in res.json()["detail"]


# ── 4. Stryd 5xx → 502 ───────────────────────────────────────────────────────

def test_connect_stryd_5xx_returns_502(monkeypatch):
    _fernet_key(monkeypatch)
    from fastapi import HTTPException as _HTTPException

    with patch("backend.main._stryd_signin", side_effect=_HTTPException(
        status_code=502,
        detail="Stryd is unavailable, try again later.",
    )):
        res = client.post("/api/stryd/connect", json={
            "email": "athlete@example.com",
            "password": "any-password",
        })

    assert res.status_code == 502
    assert "Stryd is unavailable" in res.json()["detail"]


# ── 4b. Stryd unreachable (no HTTP response at all) → 502, not a bare 500 ────
# Found during the S1 UX review: a real connection failure (DNS, refused,
# timeout) raises urllib.error.URLError, not HTTPError — only HTTPError was
# caught, so this fell through as an unhandled exception and surfaced to the
# athlete as a bare "Internal Server Error" instead of the same friendly
# message already used for Stryd 5xx responses.

def test_call_stryd_signin_url_error_raises_502():
    """_call_stryd_signin converts a connection failure (URLError) to 502."""
    import urllib.error
    from fastapi import HTTPException as _HTTPException
    from backend.services.stryd import _call_stryd_signin

    url_err = urllib.error.URLError("Temporary failure in name resolution")
    with patch("urllib.request.urlopen", side_effect=url_err):
        with pytest.raises(_HTTPException) as exc_info:
            _call_stryd_signin("athlete@example.com", "any-password")

    assert exc_info.value.status_code == 502
    assert "Stryd is unavailable" in exc_info.value.detail


def test_connect_stryd_unreachable_via_service_returns_502(monkeypatch):
    _fernet_key(monkeypatch)
    from fastapi import HTTPException as _HTTPException

    with patch("backend.main._stryd_signin", side_effect=_HTTPException(
        status_code=502,
        detail="Stryd is unavailable, try again later.",
    )):
        res = client.post("/api/stryd/connect", json={
            "email": "athlete@example.com",
            "password": "any-password",
        })

    assert res.status_code == 502
    assert "Stryd is unavailable" in res.json()["detail"]


# ── 4c. Unknown email → Stryd itself returns 404, not 401/403 ────────────────
# Found live during the S1 UX review by hitting the real Stryd signin API
# with an unregistered email: it returns HTTP 404 with body "Account does not
# exist. Please sign up first." — a very plausible real mistake (mistyped
# email) that previously fell through the existing 401/403/5xx branches as an
# unhandled exception, surfacing as a bare "Internal Server Error".

def test_call_stryd_signin_404_raises_401_with_stryd_message():
    """_call_stryd_signin converts a Stryd 404 (unknown account) to a
    friendly 401, preferring Stryd's own response body when present."""
    import io
    import urllib.error
    from fastapi import HTTPException as _HTTPException
    from backend.services.stryd import _call_stryd_signin

    body = b"Account does not exist. Please sign up first."
    http_err = urllib.error.HTTPError(
        "https://www.stryd.com/b/email/signin",
        404,
        "Not Found",
        {},  # type: ignore[arg-type]
        io.BytesIO(body),  # type: ignore[arg-type]
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(_HTTPException) as exc_info:
            _call_stryd_signin("nobody@example.com", "any-password")

    assert exc_info.value.status_code == 401
    assert "Account does not exist" in exc_info.value.detail


def test_call_stryd_signin_404_falls_back_when_body_unreadable():
    """If Stryd's 404 body can't be read for any reason, fall back to the
    same generic message used for 401/403 rather than raising a raw 500."""
    import urllib.error
    from fastapi import HTTPException as _HTTPException
    from backend.services.stryd import _call_stryd_signin

    http_err = urllib.error.HTTPError(
        "https://www.stryd.com/b/email/signin",
        404,
        "Not Found",
        {},  # type: ignore[arg-type]
        None,  # type: ignore[arg-type] — no readable fp
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(_HTTPException) as exc_info:
            _call_stryd_signin("nobody@example.com", "any-password")

    assert exc_info.value.status_code == 401
    assert "Stryd authentication failed" in exc_info.value.detail


# ── 5. Invalid email → 422 ───────────────────────────────────────────────────

def test_connect_invalid_email_returns_422():
    res = client.post("/api/stryd/connect", json={
        "email": "notanemail",
        "password": "somepassword",
    })
    assert res.status_code == 422


# ── 6. Empty password → 422 ──────────────────────────────────────────────────

def test_connect_empty_password_returns_422():
    res = client.post("/api/stryd/connect", json={
        "email": "athlete@example.com",
        "password": "",
    })
    assert res.status_code == 422


# ── 7. Missing password field → 422 ─────────────────────────────────────────

def test_connect_missing_password_returns_422():
    res = client.post("/api/stryd/connect", json={"email": "athlete@example.com"})
    assert res.status_code == 422


# ── 8. Encrypted-at-rest: password stored encrypted, not plaintext ───────────

def test_connect_password_stored_encrypted(monkeypatch):
    """Mandatory: bytes in DB must differ from plaintext."""
    _fernet_key(monkeypatch)
    plaintext = "my-plaintext-password"
    mock_resp = _fake_stryd_resp()
    captured = {}

    def capture_upsert(**kwargs):
        captured.update(kwargs)

    with patch("backend.main._stryd_signin", return_value=mock_resp), \
         patch("backend.main._upsert_stryd_credentials", side_effect=lambda **kw: captured.update(kw)), \
         patch("backend.main.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.order_by.return_value.first.return_value = _mock_user()
        mock_session_cls.return_value = mock_session

        res = client.post("/api/stryd/connect", json={
            "email": "athlete@example.com",
            "password": plaintext,
        })

    assert res.status_code == 200
    assert "password_encrypted" in captured
    # Mandatory assertion: encrypted value must not equal plaintext
    assert captured["password_encrypted"] != plaintext
    assert len(captured["password_encrypted"]) > len(plaintext)


# ── 9. Idempotent upsert: repeated call → same single row ────────────────────

def test_connect_idempotent_upsert(monkeypatch):
    _fernet_key(monkeypatch)
    mock_resp = _fake_stryd_resp()
    upsert_calls = []

    with patch("backend.main._stryd_signin", return_value=mock_resp), \
         patch("backend.main._upsert_stryd_credentials", side_effect=lambda **kw: upsert_calls.append(kw)), \
         patch("backend.main.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.order_by.return_value.first.return_value = _mock_user()
        mock_session_cls.return_value = mock_session

        r1 = client.post("/api/stryd/connect", json={"email": "athlete@example.com", "password": "pw"})
        r2 = client.post("/api/stryd/connect", json={"email": "athlete@example.com", "password": "pw"})

    assert r1.status_code == 200
    assert r2.status_code == 200
    # Both calls go through _upsert_stryd_credentials which uses ON CONFLICT DO UPDATE
    assert len(upsert_calls) == 2
    assert upsert_calls[0]["user_id"] == upsert_calls[1]["user_id"]


# ── 10. session_token_expires_at set to ~25 days from now ────────────────────

def test_connect_sets_expiry_25_days(monkeypatch):
    _fernet_key(monkeypatch)
    mock_resp = _fake_stryd_resp()
    captured = {}

    with patch("backend.main._stryd_signin", return_value=mock_resp), \
         patch("backend.main._upsert_stryd_credentials", side_effect=lambda **kw: captured.update(kw)), \
         patch("backend.main.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.order_by.return_value.first.return_value = _mock_user()
        mock_session_cls.return_value = mock_session

        now_before = datetime.now(tz=timezone.utc)
        res = client.post("/api/stryd/connect", json={"email": "athlete@example.com", "password": "pw"})
        now_after = datetime.now(tz=timezone.utc)

    assert res.status_code == 200
    exp = captured["session_token_expires_at"]
    assert exp >= now_before + timedelta(days=24, hours=23)
    assert exp <= now_after + timedelta(days=25, seconds=5)


# ── 11. refresh_stryd_session_if_needed: stale token → re-authenticates ──────

def test_refresh_stale_token_reauthenticates(monkeypatch):
    monkeypatch.setenv("STRYD_FERNET_KEY", "")  # not needed since crypto is mocked
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STRYD_FERNET_KEY", key)

    now = datetime.now(tz=timezone.utc)
    stale_expires = now - timedelta(hours=1)

    mock_cred = MagicMock()
    mock_cred.session_token = "old-token"
    mock_cred.session_token_expires_at = stale_expires
    mock_cred.stryd_email = "athlete@example.com"
    mock_cred.stryd_password_encrypted = "encrypted-placeholder"

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one.return_value = mock_cred

    new_stryd_resp = {"token": "new-session-token", "id": 42}

    with patch("backend.services.stryd.Session", return_value=mock_session), \
         patch("backend.services.stryd._call_stryd_signin", return_value=new_stryd_resp) as mock_signin, \
         patch("backend.services.stryd.decrypt_value", return_value="plaintext-pw"):

        result = refresh_stryd_session_if_needed(TEST_USER_ID)

    assert result == "new-session-token"
    assert mock_cred.session_token == "new-session-token"
    mock_signin.assert_called_once_with("athlete@example.com", "plaintext-pw")
    mock_session.commit.assert_called_once()


# ── 12. refresh_stryd_session_if_needed: null token → re-authenticates ───────

def test_refresh_null_token_reauthenticates(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STRYD_FERNET_KEY", key)

    mock_cred = MagicMock()
    mock_cred.session_token = None
    mock_cred.session_token_expires_at = None
    mock_cred.stryd_email = "athlete@example.com"
    mock_cred.stryd_password_encrypted = "encrypted-placeholder"

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one.return_value = mock_cred

    new_stryd_resp = {"token": "fresh-token", "id": 42}

    with patch("backend.services.stryd.Session", return_value=mock_session), \
         patch("backend.services.stryd._call_stryd_signin", return_value=new_stryd_resp) as mock_signin, \
         patch("backend.services.stryd.decrypt_value", return_value="plaintext-pw"):

        result = refresh_stryd_session_if_needed(TEST_USER_ID)

    assert result == "fresh-token"
    mock_signin.assert_called_once()
    mock_session.commit.assert_called_once()


# ── 13. refresh_stryd_session_if_needed: fresh token → no re-auth ────────────

def test_refresh_fresh_token_skips_reauth(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STRYD_FERNET_KEY", key)

    now = datetime.now(tz=timezone.utc)
    fresh_expires = now + timedelta(days=20)

    mock_cred = MagicMock()
    mock_cred.session_token = "still-valid-token"
    mock_cred.session_token_expires_at = fresh_expires

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one.return_value = mock_cred

    with patch("backend.services.stryd.Session", return_value=mock_session), \
         patch("backend.services.stryd._call_stryd_signin") as mock_signin:

        result = refresh_stryd_session_if_needed(TEST_USER_ID)

    assert result == "still-valid-token"
    mock_signin.assert_not_called()
    mock_session.commit.assert_not_called()
