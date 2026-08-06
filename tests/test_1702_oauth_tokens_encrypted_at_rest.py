"""Tests for issue #1702: Strava/Google OAuth tokens must be encrypted at rest.

Acceptance criteria:
- StravaToken.access_token_encrypted and refresh_token_encrypted store Fernet ciphertext
- GoogleOAuthCredentials.access_token_encrypted and refresh_token_encrypted store Fernet ciphertext
- A dedicated OAUTH_FERNET_KEY env var is used (separate from STRYD_FERNET_KEY)
- encrypt_oauth_token / decrypt_oauth_token round-trip correctly
- strava.refresh_token_if_needed returns plaintext access token
- google.refresh_token_if_needed returns plaintext access token
- strava_disconnect uses plaintext access token for Strava deauth call
- OAUTH_FERNET_KEY missing → RuntimeError, not silent failure
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

_TEST_KEY = "3ttWJuuQgVohOaEfabmb4WkB7VKPkh9z5zELJUyeFjY="


# ── crypto layer ──────────────────────────────────────────────────────────────

def test_encrypt_decrypt_oauth_token_round_trip(monkeypatch):
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token, decrypt_oauth_token
    plaintext = "live-strava-bearer-token-abc123"
    ciphertext = encrypt_oauth_token(plaintext)
    assert ciphertext != plaintext
    assert decrypt_oauth_token(ciphertext) == plaintext


def test_encrypt_oauth_token_produces_valid_fernet_token(monkeypatch):
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token
    fernet = Fernet(_TEST_KEY.encode())
    ciphertext = encrypt_oauth_token("my-secret-token")
    # Fernet tokens from a known key must be decodable with that key
    assert fernet.decrypt(ciphertext.encode()) == b"my-secret-token"


def test_encrypt_oauth_token_is_not_deterministic(monkeypatch):
    """Each call produces unique ciphertext (Fernet uses random IV)."""
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token
    ct1 = encrypt_oauth_token("same-plaintext")
    ct2 = encrypt_oauth_token("same-plaintext")
    assert ct1 != ct2  # Fernet includes random IV


def test_encrypt_oauth_token_raises_without_key(monkeypatch):
    monkeypatch.delenv("OAUTH_FERNET_KEY", raising=False)
    from backend.services import crypto as _crypto_mod
    # Re-exercise _get_oauth_fernet directly via the public function
    with pytest.raises(RuntimeError, match="OAUTH_FERNET_KEY"):
        _crypto_mod._get_oauth_fernet()


def test_oauth_fernet_key_validation_rejects_invalid_base64(monkeypatch):
    """Invalid base64 key is caught at module-load / validation time."""
    monkeypatch.setenv("OAUTH_FERNET_KEY", "!!!not-valid-base64!!!")
    import importlib
    from backend.services import crypto as _crypto_mod
    with pytest.raises(RuntimeError, match="OAUTH_FERNET_KEY"):
        _crypto_mod._validate_oauth_fernet_key()


def test_oauth_fernet_key_uses_different_key_from_stryd(monkeypatch):
    """Tokens encrypted with OAUTH_FERNET_KEY cannot be decrypted with STRYD_FERNET_KEY."""
    stryd_key = Fernet.generate_key().decode()
    oauth_key = Fernet.generate_key().decode()
    monkeypatch.setenv("STRYD_FERNET_KEY", stryd_key)
    monkeypatch.setenv("OAUTH_FERNET_KEY", oauth_key)
    from backend.services.crypto import encrypt_oauth_token, decrypt_value
    ciphertext = encrypt_oauth_token("my-strava-token")
    with pytest.raises(Exception):
        decrypt_value(ciphertext)


# ── strava service ────────────────────────────────────────────────────────────

def _make_strava_session(token_row):
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = token_row
    return mock_session


def test_strava_refresh_returns_plaintext_when_fresh(monkeypatch):
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token
    from backend.services.strava import refresh_token_if_needed

    now = datetime.now(tz=timezone.utc)
    mock_token = MagicMock()
    mock_token.expires_at = now + timedelta(minutes=10)
    mock_token.access_token_encrypted = encrypt_oauth_token("valid-access-token")

    with patch("backend.services.strava.Session", return_value=_make_strava_session(mock_token)):
        result = refresh_token_if_needed("user-123")

    assert result == "valid-access-token"


def test_strava_refresh_decrypts_refresh_token_for_strava_api(monkeypatch):
    """When token is expired, refresh_token must be decrypted before sending to Strava."""
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token, decrypt_oauth_token
    from backend.services.strava import refresh_token_if_needed

    now = datetime.now(tz=timezone.utc)
    mock_token = MagicMock()
    mock_token.expires_at = now - timedelta(minutes=5)
    mock_token.access_token_encrypted = encrypt_oauth_token("old-at")
    mock_token.refresh_token_encrypted = encrypt_oauth_token("old-rt")

    new_expires = int((now + timedelta(hours=6)).timestamp())
    strava_resp = {
        "access_token": "new-at",
        "refresh_token": "new-rt",
        "expires_at": new_expires,
    }

    captured_refresh_call = {}

    def fake_call_refresh(client_id, client_secret, refresh_token):
        captured_refresh_call["refresh_token"] = refresh_token
        return strava_resp

    with patch("backend.services.strava.Session", return_value=_make_strava_session(mock_token)), \
         patch("backend.services.strava._call_strava_refresh", side_effect=fake_call_refresh):
        result = refresh_token_if_needed("user-123")

    # The plaintext refresh token was sent to Strava (not ciphertext)
    assert captured_refresh_call["refresh_token"] == "old-rt"
    # The returned access token is plaintext
    assert result == "new-at"
    # The stored values are encrypted
    assert decrypt_oauth_token(mock_token.access_token_encrypted) == "new-at"
    assert decrypt_oauth_token(mock_token.refresh_token_encrypted) == "new-rt"


def test_strava_refresh_stores_new_tokens_encrypted(monkeypatch):
    """After refresh, new tokens are stored encrypted, not plaintext."""
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token, decrypt_oauth_token
    from backend.services.strava import refresh_token_if_needed

    now = datetime.now(tz=timezone.utc)
    mock_token = MagicMock()
    mock_token.expires_at = now - timedelta(minutes=5)
    mock_token.access_token_encrypted = encrypt_oauth_token("old-at")
    mock_token.refresh_token_encrypted = encrypt_oauth_token("old-rt")

    new_at = "brand-new-access-token"
    new_rt = "brand-new-refresh-token"
    new_expires = int((now + timedelta(hours=6)).timestamp())

    strava_resp = {"access_token": new_at, "refresh_token": new_rt, "expires_at": new_expires}

    with patch("backend.services.strava.Session", return_value=_make_strava_session(mock_token)), \
         patch("backend.services.strava._call_strava_refresh", return_value=strava_resp):
        refresh_token_if_needed("user-123")

    # Stored value must NOT be plaintext
    assert mock_token.access_token_encrypted != new_at
    assert mock_token.refresh_token_encrypted != new_rt
    # But must decrypt to correct plaintext
    assert decrypt_oauth_token(mock_token.access_token_encrypted) == new_at
    assert decrypt_oauth_token(mock_token.refresh_token_encrypted) == new_rt


def test_strava_upsert_stores_tokens_encrypted(monkeypatch):
    """_upsert_strava_token encrypts tokens before writing to DB."""
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import decrypt_oauth_token
    from backend.main import _upsert_strava_token

    captured_insert = {}

    def fake_execute(stmt):
        # Inspect the compiled insert statement's values
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        captured_insert["stmt"] = stmt

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    plaintext_at = "strava-access-token-plaintext"
    plaintext_rt = "strava-refresh-token-plaintext"

    stored_at = []
    stored_rt = []

    original_values = {}

    def capture_values(stmt):
        # Dig into the ON CONFLICT INSERT values
        try:
            for col, val in stmt.inserted.items():
                original_values[col.key] = val
        except Exception:
            pass

    with patch("backend.main.Session", return_value=mock_session) as mock_sess_cls, \
         patch("backend.main._pg_insert") as mock_insert:

        mock_insert_result = MagicMock()
        mock_insert.return_value = mock_insert_result
        mock_insert_result.values.return_value = mock_insert_result
        mock_insert_result.on_conflict_do_update.return_value = mock_insert_result

        stored_kwargs = {}

        def fake_values(**kwargs):
            stored_kwargs.update(kwargs)
            return mock_insert_result

        mock_insert_result.values = MagicMock(side_effect=fake_values)

        _upsert_strava_token(
            user_id="user-999",
            athlete_id=12345,
            access_token=plaintext_at,
            refresh_token=plaintext_rt,
            expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=6),
            scope="activity:read_all",
            athlete_data={},
        )

    # Stored values are NOT plaintext
    assert stored_kwargs.get("access_token_encrypted") != plaintext_at
    assert stored_kwargs.get("refresh_token_encrypted") != plaintext_rt
    # Stored values decrypt to the correct plaintext
    assert decrypt_oauth_token(stored_kwargs["access_token_encrypted"]) == plaintext_at
    assert decrypt_oauth_token(stored_kwargs["refresh_token_encrypted"]) == plaintext_rt
    # The OLD plaintext column names must NOT be used
    assert "access_token" not in stored_kwargs
    assert "refresh_token" not in stored_kwargs


# ── google service ────────────────────────────────────────────────────────────

def _make_google_session(cred_row):
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = cred_row
    return mock_session


def test_google_refresh_returns_plaintext_when_fresh(monkeypatch):
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token
    from backend.services.google import refresh_token_if_needed

    now = datetime.now(tz=timezone.utc)
    mock_cred = MagicMock()
    mock_cred.expires_at = now + timedelta(minutes=10)
    mock_cred.access_token_encrypted = encrypt_oauth_token("google-access-token")

    with patch("backend.services.google.Session", return_value=_make_google_session(mock_cred)):
        result = refresh_token_if_needed("user-456")

    assert result == "google-access-token"


def test_google_refresh_decrypts_refresh_token_for_google_api(monkeypatch):
    """When token is expired, refresh_token must be decrypted before sending to Google."""
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token, decrypt_oauth_token
    from backend.services.google import refresh_token_if_needed

    now = datetime.now(tz=timezone.utc)
    mock_cred = MagicMock()
    mock_cred.expires_at = now - timedelta(minutes=5)
    mock_cred.access_token_encrypted = encrypt_oauth_token("old-google-at")
    mock_cred.refresh_token_encrypted = encrypt_oauth_token("old-google-rt")

    captured_post_data = {}

    def fake_post(url, data=None, **kwargs):
        captured_post_data.update(data or {})
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"access_token": "new-google-at", "expires_in": 3600}
        return mock_resp

    with patch("backend.services.google.Session", return_value=_make_google_session(mock_cred)), \
         patch("backend.services.google._requests.post", side_effect=fake_post):
        result = refresh_token_if_needed("user-456")

    # Plaintext refresh token sent to Google
    assert captured_post_data.get("refresh_token") == "old-google-rt"
    # Returned plaintext access token
    assert result == "new-google-at"
    # New access token stored encrypted
    assert decrypt_oauth_token(mock_cred.access_token_encrypted) == "new-google-at"


def test_google_refresh_stores_new_tokens_encrypted(monkeypatch):
    """After refresh, new access token is stored encrypted."""
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.crypto import encrypt_oauth_token, decrypt_oauth_token
    from backend.services.google import refresh_token_if_needed

    now = datetime.now(tz=timezone.utc)
    mock_cred = MagicMock()
    mock_cred.expires_at = now - timedelta(minutes=5)
    mock_cred.access_token_encrypted = encrypt_oauth_token("old-at")
    mock_cred.refresh_token_encrypted = encrypt_oauth_token("old-rt")

    new_at = "shiny-new-google-access-token"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"access_token": new_at, "expires_in": 3600}

    with patch("backend.services.google.Session", return_value=_make_google_session(mock_cred)), \
         patch("backend.services.google._requests.post", return_value=mock_resp):
        refresh_token_if_needed("user-456")

    assert mock_cred.access_token_encrypted != new_at
    assert decrypt_oauth_token(mock_cred.access_token_encrypted) == new_at


def test_google_refresh_raises_when_refresh_token_is_null(monkeypatch):
    """When refresh_token_encrypted is NULL, ExternalServiceError is raised."""
    monkeypatch.setenv("OAUTH_FERNET_KEY", _TEST_KEY)
    from backend.services.google import refresh_token_if_needed
    from backend.utils.errors import ExternalServiceError

    now = datetime.now(tz=timezone.utc)
    mock_cred = MagicMock()
    mock_cred.expires_at = now - timedelta(minutes=5)
    mock_cred.refresh_token_encrypted = None

    with patch("backend.services.google.Session", return_value=_make_google_session(mock_cred)):
        with pytest.raises(ExternalServiceError, match="refresh token is missing"):
            refresh_token_if_needed("user-456")


# ── model column names ────────────────────────────────────────────────────────

def test_strava_token_model_has_encrypted_column_names():
    """StravaToken ORM model uses _encrypted suffix, not plaintext names."""
    from backend.models import StravaToken
    cols = {c.key for c in StravaToken.__table__.columns}
    assert "access_token_encrypted" in cols
    assert "refresh_token_encrypted" in cols
    assert "access_token" not in cols
    assert "refresh_token" not in cols


def test_google_oauth_credentials_model_has_encrypted_column_names():
    """GoogleOAuthCredentials ORM model uses _encrypted suffix, not plaintext names."""
    from backend.models import GoogleOAuthCredentials
    cols = {c.key for c in GoogleOAuthCredentials.__table__.columns}
    assert "access_token_encrypted" in cols
    assert "refresh_token_encrypted" in cols
    assert "access_token" not in cols
    assert "refresh_token" not in cols
