"""Tests for issue #202: validate STRYD_FERNET_KEY at module import time."""
import importlib
import pytest


def _reload_crypto(monkeypatch, key_value):
    if key_value is None:
        monkeypatch.delenv("STRYD_FERNET_KEY", raising=False)
    else:
        monkeypatch.setenv("STRYD_FERNET_KEY", key_value)
    import backend.services.crypto as crypto_mod
    importlib.reload(crypto_mod)
    return crypto_mod


def test_valid_key_loads_without_error(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    _reload_crypto(monkeypatch, key)  # must not raise


def test_missing_key_loads_without_error(monkeypatch):
    _reload_crypto(monkeypatch, None)  # must not raise at import


def test_invalid_base64_raises_at_import(monkeypatch):
    monkeypatch.setenv("STRYD_FERNET_KEY", "not-valid-base64!!!")
    import backend.services.crypto as crypto_mod
    with pytest.raises(RuntimeError, match="not valid URL-safe base64"):
        importlib.reload(crypto_mod)


def test_wrong_length_key_raises_at_import(monkeypatch):
    import base64
    # 16 bytes → valid base64 but wrong length for Fernet
    short_key = base64.urlsafe_b64encode(b"a" * 16).decode()
    monkeypatch.setenv("STRYD_FERNET_KEY", short_key)
    import backend.services.crypto as crypto_mod
    with pytest.raises(RuntimeError, match="decoded to 16 bytes; Fernet requires exactly 32"):
        importlib.reload(crypto_mod)


def test_error_message_includes_generate_command(monkeypatch):
    monkeypatch.setenv("STRYD_FERNET_KEY", "bad!!!")
    import backend.services.crypto as crypto_mod
    with pytest.raises(RuntimeError, match="Fernet.generate_key"):
        importlib.reload(crypto_mod)
