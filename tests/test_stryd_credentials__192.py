"""Tests for issue #192: Stryd credentials table with encrypted password storage"""
import os
import pytest


# ── crypto unit tests (no server needed) ──────────────────────────────────────

def _set_fernet_key(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STRYD_FERNET_KEY", key)
    return key


def test_encrypt_decrypt_round_trip(monkeypatch):
    _set_fernet_key(monkeypatch)
    from backend.services.crypto import decrypt_value, encrypt_value
    plaintext = "super-secret-password-123"
    assert decrypt_value(encrypt_value(plaintext)) == plaintext


def test_ciphertext_differs_from_plaintext(monkeypatch):
    _set_fernet_key(monkeypatch)
    from backend.services.crypto import encrypt_value
    plaintext = "my-password"
    assert encrypt_value(plaintext) != plaintext


def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("STRYD_FERNET_KEY", raising=False)
    # Force reimport so cached module state doesn't hide the missing key
    import importlib
    import backend.services.crypto as crypto_mod
    importlib.reload(crypto_mod)
    with pytest.raises(RuntimeError, match="STRYD_FERNET_KEY"):
        crypto_mod.encrypt_value("anything")
