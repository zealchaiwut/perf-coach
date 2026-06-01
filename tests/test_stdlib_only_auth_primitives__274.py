"""Tests for issue #274: stdlib-only auth primitives for FastAPI backend."""
import importlib
import importlib.util
import inspect
import pathlib
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

_AUTH_PATH = pathlib.Path(__file__).parent.parent.parent / "coder/backend/auth.py"
_CODER_ROOT = _AUTH_PATH.parent.parent


def _load_auth():
    spec = importlib.util.spec_from_file_location("backend.auth", _AUTH_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def auth():
    return _load_auth()


# ── File & import checks ─────────────────────────────────────────────────────

def test_auth_module_exists():
    assert _AUTH_PATH.exists(), f"backend/auth.py not found at {_AUTH_PATH}"


def test_auth_imports_only_stdlib_and_approved_libs(auth):
    src = inspect.getsource(auth)
    forbidden = ["bcrypt", "passlib", "authlib", "itsdangerous", "jwt", "jose"]
    for lib in forbidden:
        assert lib not in src, f"auth.py imports forbidden third-party auth lib: {lib!r}"


# ── hash_password ────────────────────────────────────────────────────────────

def test_hash_password_uses_scrypt_format(auth):
    h = auth.hash_password("password")
    parts = h.split("$")
    assert len(parts) == 5, "expected format: N$r$p$salt_hex$hash_hex"
    n, r, p, salt_hex, hash_hex = parts
    assert int(n) > 0
    assert int(r) > 0
    assert int(p) > 0
    assert len(bytes.fromhex(salt_hex)) == 16
    assert len(bytes.fromhex(hash_hex)) == 32


def test_hash_password_random_salt(auth):
    h1 = auth.hash_password("same-password")
    h2 = auth.hash_password("same-password")
    assert h1 != h2, "same password should produce different hashes (random salt)"


# ── verify_password ──────────────────────────────────────────────────────────

def test_verify_password_correct(auth):
    stored = auth.hash_password("correct-horse-battery-staple")
    assert auth.verify_password("correct-horse-battery-staple", stored) is True


def test_verify_password_wrong(auth):
    stored = auth.hash_password("correct")
    assert auth.verify_password("wrong", stored) is False


def test_verify_password_uses_compare_digest(auth):
    src = inspect.getsource(auth.verify_password)
    assert "compare_digest" in src


# ── create_session_cookie / read_session_cookie ──────────────────────────────

def test_create_session_cookie_two_part_structure(auth):
    token = auth.create_session_cookie("user-123", time.time())
    parts = token.rsplit(".", 1)
    assert len(parts) == 2, "token should be payload.signature"


def test_read_session_cookie_returns_dict(auth):
    token = auth.create_session_cookie("user-abc", 1_700_000_000.0)
    data = auth.read_session_cookie(token)
    assert isinstance(data, dict)
    assert "user_id" in data
    assert "issued_at" in data
    assert data["user_id"] == "user-abc"
    assert data["issued_at"] == 1_700_000_000.0


def test_read_session_cookie_forged_rejected(auth):
    with pytest.raises(ValueError):
        auth.read_session_cookie("totally-forged.invalidsig")


def test_read_session_cookie_tampered_payload_rejected(auth):
    token = auth.create_session_cookie("user-xyz", 1_700_000_000.0)
    payload, sig = token.rsplit(".", 1)
    tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    with pytest.raises(ValueError):
        auth.read_session_cookie(f"{tampered}.{sig}")


def test_read_session_cookie_missing_dot_rejected(auth):
    with pytest.raises(ValueError):
        auth.read_session_cookie("nodothere")


# ── set_session / clear_session ──────────────────────────────────────────────

def test_set_session_sets_httponly_lax_cookie(auth):
    response = MagicMock()
    auth.set_session(response, "user-123")
    response.set_cookie.assert_called_once()
    call_kwargs = response.set_cookie.call_args
    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
    args = call_kwargs.args if call_kwargs.args else ()
    assert kwargs.get("httponly") is True or True in args
    samesite = kwargs.get("samesite", "")
    assert samesite.lower() == "lax"


def test_clear_session_deletes_cookie(auth):
    response = MagicMock()
    auth.clear_session(response)
    response.delete_cookie.assert_called_once()
    call_kwargs = response.delete_cookie.call_args
    assert auth.COOKIE_NAME in str(call_kwargs)


# ── get_current_user ─────────────────────────────────────────────────────────

def test_get_current_user_is_async(auth):
    import asyncio
    assert asyncio.iscoroutinefunction(auth.get_current_user), (
        "get_current_user must be an async function (FastAPI dependency)"
    )


def test_get_current_user_raises_401_without_cookie(auth):
    import asyncio
    request = MagicMock()
    request.cookies.get.return_value = None
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(auth.get_current_user(request))
    assert exc_info.value.status_code == 401


def test_get_current_user_raises_401_for_invalid_cookie(auth):
    import asyncio
    request = MagicMock()
    request.cookies.get.return_value = "bad.cookie.value"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(auth.get_current_user(request))
    assert exc_info.value.status_code == 401


# ── SESSION_SECRET fallback ──────────────────────────────────────────────────

def test_session_secret_warning_when_unset(caplog):
    import importlib
    import logging
    env_patch = {"SESSION_SECRET": ""}
    with patch.dict("os.environ", env_patch, clear=False):
        import os
        os.environ.pop("SESSION_SECRET", None)
        with caplog.at_level(logging.WARNING, logger="backend.auth"):
            spec = importlib.util.spec_from_file_location(
                "backend.auth_test_secret", _AUTH_PATH
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("SESSION_SECRET" in m for m in warning_msgs), (
        "Expected WARNING about missing SESSION_SECRET"
    )


def test_session_secret_ephemeral_when_unset():
    import os
    env_copy = os.environ.copy()
    env_copy.pop("SESSION_SECRET", None)
    spec = importlib.util.spec_from_file_location(
        "backend.auth_no_secret", _AUTH_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", {}, clear=True):
        spec.loader.exec_module(mod)
    assert isinstance(mod.SESSION_SECRET, bytes)
    assert len(mod.SESSION_SECRET) == 32


# ── Backend unit tests pass ──────────────────────────────────────────────────

def test_backend_auth_unit_tests_pass():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/test_auth.py", "-v", "--tb=short"],
        cwd=str(_CODER_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"backend/test_auth.py failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "4 passed" in result.stdout
