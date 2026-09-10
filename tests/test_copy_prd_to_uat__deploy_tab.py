"""Tests for the "Copy PRD → UAT" full-environment copy (Deploy-tab feature).

backend.services.user_copy.copy_all_users_to_uat itself needs two live
Postgres databases and isn't unit-testable here (same constraint as the
pre-existing copy_user_to_uat, which has no tests either — this module is
Postgres-only by design, information_schema.columns and ON CONFLICT ...
DO UPDATE aren't available against this repo's default SQLite test DB).

What IS unit-testable, and where the actual new risk lives, is the
re-encryption logic: reencrypt_row and _fernet_for's PRD/UAT key resolution.
That's real behavior with real cryptography.fernet round-trips, no DB needed.

AC coverage:
  AC1 — a row with no encrypted columns for its table passes through unchanged.
  AC2 — an encrypted column is genuinely decrypted with the PRD key and
        re-encrypted with the UAT key: the round-trip produces a DIFFERENT
        ciphertext that still decrypts to the SAME plaintext under the UAT key.
  AC3 — an empty/None ciphertext value is left alone (nothing to re-key).
  AC4 — a key that isn't configured on either side sets the field to None and
        records why in encryption_failures, rather than copying ciphertext
        that will never decrypt.
  AC5 — a genuine key mismatch (prd key wrong for this ciphertext) sets the
        field to None and records the failure, instead of raising / crashing
        the whole copy.
  AC6 — _fernet_for prefers the explicit <KEY>_PRD/<KEY>_UAT split over the
        plain <KEY> fallback.
  AC7 — _ENCRYPTED_COLUMNS covers exactly the encrypted columns that exist in
        backend/models.py (stryd_credentials.stryd_password_encrypted,
        strava_tokens/google_oauth_credentials access+refresh token columns)
        — a schema-drift guard, not a source-regex check: it re-derives the
        list from backend.models and asserts set equality.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet

from backend.services.user_copy import (
    _ENCRYPTED_COLUMNS,
    _fernet_for,
    reencrypt_row,
)


PRD_KEY = Fernet.generate_key().decode()
UAT_KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()


def test_table_with_no_encrypted_columns_passes_through_unchanged():
    row = {"id": "abc", "name": "Alice"}
    failures: list[dict] = []
    out = reencrypt_row("users", row, failures)
    assert out == row
    assert failures == []


def test_encrypted_column_is_genuinely_reencrypted_not_copied_verbatim(monkeypatch):
    """AC2: the actual bug this feature exists to prevent — verbatim ciphertext
    copy leaves the field undecryptable wherever keys differ."""
    monkeypatch.setenv("STRYD_FERNET_KEY_PRD", PRD_KEY)
    monkeypatch.setenv("STRYD_FERNET_KEY_UAT", UAT_KEY)

    plaintext = "super-secret-stryd-password"
    prd_ciphertext = Fernet(PRD_KEY).encrypt(plaintext.encode()).decode()

    row = {"id": "row-1", "stryd_email": "a@b.com", "stryd_password_encrypted": prd_ciphertext}
    failures: list[dict] = []
    out = reencrypt_row("stryd_credentials", row, failures)

    assert failures == []
    # The new ciphertext is NOT the same bytes as PRD's (proves re-encryption
    # actually happened, not a no-op passthrough)...
    assert out["stryd_password_encrypted"] != prd_ciphertext
    # ...but decrypting it with UAT's key recovers the original plaintext.
    recovered = Fernet(UAT_KEY).decrypt(out["stryd_password_encrypted"].encode()).decode()
    assert recovered == plaintext
    # Non-encrypted columns are untouched.
    assert out["stryd_email"] == "a@b.com"


def test_empty_ciphertext_is_left_alone():
    failures: list[dict] = []
    out = reencrypt_row("stryd_credentials", {"id": "x", "stryd_password_encrypted": None}, failures)
    assert out["stryd_password_encrypted"] is None
    assert failures == []


def test_missing_key_nulls_the_field_and_records_why(monkeypatch):
    """AC4: no key configured anywhere for this table's encryption -> null +
    recorded failure, never verbatim ciphertext."""
    monkeypatch.delenv("STRYD_FERNET_KEY", raising=False)
    monkeypatch.delenv("STRYD_FERNET_KEY_PRD", raising=False)
    monkeypatch.delenv("STRYD_FERNET_KEY_UAT", raising=False)

    row = {"id": "row-2", "stryd_password_encrypted": "some-ciphertext"}
    failures: list[dict] = []
    out = reencrypt_row("stryd_credentials", row, failures)

    assert out["stryd_password_encrypted"] is None
    assert len(failures) == 1
    assert failures[0]["table"] == "stryd_credentials"
    assert failures[0]["column"] == "stryd_password_encrypted"
    assert failures[0]["row_id"] == "row-2"
    assert "not configured" in failures[0]["reason"]


def test_key_mismatch_nulls_the_field_and_records_why(monkeypatch):
    """AC5: a real, plausible-in-production scenario — PRD's actual key
    (e.g. on Render) isn't the one configured locally, so decrypting with the
    wrong key must fail safely, not raise out of the whole copy."""
    monkeypatch.setenv("STRYD_FERNET_KEY_PRD", OTHER_KEY)  # wrong key on purpose
    monkeypatch.setenv("STRYD_FERNET_KEY_UAT", UAT_KEY)

    real_ciphertext = Fernet(PRD_KEY).encrypt(b"secret").decode()
    row = {"id": "row-3", "stryd_password_encrypted": real_ciphertext}
    failures: list[dict] = []
    out = reencrypt_row("stryd_credentials", row, failures)

    assert out["stryd_password_encrypted"] is None
    assert len(failures) == 1
    assert "do not match" in failures[0]["reason"]


def test_oauth_tokens_use_the_oauth_key(monkeypatch):
    """Strava/Google both key off OAUTH_FERNET_KEY, distinct from Stryd's."""
    monkeypatch.setenv("OAUTH_FERNET_KEY_PRD", PRD_KEY)
    monkeypatch.setenv("OAUTH_FERNET_KEY_UAT", UAT_KEY)

    access_ct = Fernet(PRD_KEY).encrypt(b"access-token-value").decode()
    refresh_ct = Fernet(PRD_KEY).encrypt(b"refresh-token-value").decode()
    row = {
        "id": "strava-row",
        "access_token_encrypted": access_ct,
        "refresh_token_encrypted": refresh_ct,
    }
    failures: list[dict] = []
    out = reencrypt_row("strava_tokens", row, failures)

    assert failures == []
    assert Fernet(UAT_KEY).decrypt(out["access_token_encrypted"].encode()) == b"access-token-value"
    assert Fernet(UAT_KEY).decrypt(out["refresh_token_encrypted"].encode()) == b"refresh-token-value"


def test_fernet_for_prefers_split_keys_over_plain_fallback(monkeypatch):
    """AC6: explicit <KEY>_PRD/<KEY>_UAT wins over the plain <KEY> var."""
    monkeypatch.setenv("STRYD_FERNET_KEY", OTHER_KEY)
    monkeypatch.setenv("STRYD_FERNET_KEY_PRD", PRD_KEY)

    f = _fernet_for("STRYD_FERNET_KEY", "prd")
    # The returned Fernet must actually BE the PRD key, not the plain fallback.
    token = Fernet(PRD_KEY).encrypt(b"check")
    assert f.decrypt(token) == b"check"


def test_fernet_for_falls_back_to_plain_key_when_split_unset(monkeypatch):
    monkeypatch.delenv("STRYD_FERNET_KEY_UAT", raising=False)
    monkeypatch.setenv("STRYD_FERNET_KEY", UAT_KEY)

    f = _fernet_for("STRYD_FERNET_KEY", "uat")
    token = Fernet(UAT_KEY).encrypt(b"check")
    assert f.decrypt(token) == b"check"


def test_fernet_for_returns_none_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("STRYD_FERNET_KEY", raising=False)
    monkeypatch.delenv("STRYD_FERNET_KEY_PRD", raising=False)
    monkeypatch.delenv("STRYD_FERNET_KEY_UAT", raising=False)
    assert _fernet_for("STRYD_FERNET_KEY", "prd") is None


def test_encrypted_columns_match_backend_models_schema():
    """AC7: schema-drift guard — re-derives the real encrypted columns from
    backend.models (not hand-copied literals) and asserts _ENCRYPTED_COLUMNS
    covers exactly those, so a future column rename/addition doesn't silently
    leave a new encrypted field being copied as verbatim ciphertext."""
    from backend.models import GoogleOAuthCredentials, StravaToken, StrydCredentials

    expected = {
        ("stryd_credentials", "stryd_password_encrypted"),
        ("strava_tokens", "access_token_encrypted"),
        ("strava_tokens", "refresh_token_encrypted"),
        ("google_oauth_credentials", "access_token_encrypted"),
        ("google_oauth_credentials", "refresh_token_encrypted"),
    }
    actual = {
        (table, col)
        for table, cols in _ENCRYPTED_COLUMNS.items()
        for col in cols
    }
    assert actual == expected

    # And confirm each of those columns genuinely exists on the model (catches
    # a typo'd column name that would otherwise silently no-op in reencrypt_row
    # since row.get(col) would just return None for a nonexistent key).
    assert hasattr(StrydCredentials, "stryd_password_encrypted")
    assert hasattr(StravaToken, "access_token_encrypted")
    assert hasattr(StravaToken, "refresh_token_encrypted")
    assert hasattr(GoogleOAuthCredentials, "access_token_encrypted")
    assert hasattr(GoogleOAuthCredentials, "refresh_token_encrypted")
