"""Tests for issue #1717: SESSION_SECRET fails closed when unset in non-local envs.

When SESSION_SECRET is not set and ENVIRONMENT is 'uat' or 'prd', the app must
raise RuntimeError at startup instead of silently falling back to an ephemeral
random secret. For 'local' and 'test' environments the ephemeral fallback is
still allowed (with a warning).
"""
import importlib.util
import pathlib
import sys
from unittest.mock import patch

import pytest

_AUTH_PATH = pathlib.Path(__file__).parent.parent / "backend" / "auth.py"


def _load_auth_with_env(env_vars: dict) -> "module":
    """Load backend/auth.py fresh with the given env vars, using clear=True."""
    spec = importlib.util.spec_from_file_location("backend.auth_1717_test", _AUTH_PATH)
    mod = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", env_vars, clear=True):
        spec.loader.exec_module(mod)
    return mod


# ── fail-closed in non-local environments ───────────────────────────────────

def test_raises_on_missing_secret_in_uat():
    """AC: unset SESSION_SECRET with ENVIRONMENT=uat must raise RuntimeError at startup."""
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        _load_auth_with_env({"ENVIRONMENT": "uat"})


def test_raises_on_missing_secret_in_prd():
    """AC: unset SESSION_SECRET with ENVIRONMENT=prd must raise RuntimeError at startup."""
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        _load_auth_with_env({"ENVIRONMENT": "prd"})


def test_raises_on_missing_secret_in_staging():
    """AC: any non-local/non-test environment string also fails closed."""
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        _load_auth_with_env({"ENVIRONMENT": "staging"})


# ── ephemeral fallback still allowed for local / test ────────────────────────

def test_ephemeral_fallback_allowed_in_local():
    """AC: ENVIRONMENT=local with no SESSION_SECRET should NOT raise."""
    mod = _load_auth_with_env({"ENVIRONMENT": "local",
                                "DATABASE_URL": "sqlite:///./test.db"})
    assert isinstance(mod.SESSION_SECRET, bytes)
    assert len(mod.SESSION_SECRET) == 32


def test_ephemeral_fallback_allowed_when_env_unset():
    """AC: ENVIRONMENT absent (defaults to local) should NOT raise."""
    mod = _load_auth_with_env({"DATABASE_URL": "sqlite:///./test.db"})
    assert isinstance(mod.SESSION_SECRET, bytes)
    assert len(mod.SESSION_SECRET) == 32


def test_ephemeral_fallback_allowed_in_test():
    """AC: ENVIRONMENT=test with no SESSION_SECRET should NOT raise."""
    mod = _load_auth_with_env({"ENVIRONMENT": "test",
                                "DATABASE_URL": "sqlite:///./test.db"})
    assert isinstance(mod.SESSION_SECRET, bytes)
    assert len(mod.SESSION_SECRET) == 32


# ── set secret always works ──────────────────────────────────────────────────

def test_set_secret_works_in_uat():
    """AC: SESSION_SECRET provided — no error in any environment."""
    mod = _load_auth_with_env({
        "ENVIRONMENT": "uat",
        "SESSION_SECRET": "a-valid-secret-value",
        "DATABASE_URL": "sqlite:///./test.db",
    })
    assert mod.SESSION_SECRET == b"a-valid-secret-value"


def test_set_secret_works_in_prd():
    """AC: SESSION_SECRET provided — no error in prd environment."""
    mod = _load_auth_with_env({
        "ENVIRONMENT": "prd",
        "SESSION_SECRET": "another-valid-secret",
        "DATABASE_URL": "sqlite:///./test.db",
    })
    assert mod.SESSION_SECRET == b"another-valid-secret"


def test_set_secret_works_in_local():
    """AC: SESSION_SECRET provided — works in local too."""
    mod = _load_auth_with_env({
        "ENVIRONMENT": "local",
        "SESSION_SECRET": "local-secret",
        "DATABASE_URL": "sqlite:///./test.db",
    })
    assert mod.SESSION_SECRET == b"local-secret"


# ── error message is actionable ──────────────────────────────────────────────

def test_error_message_names_environment():
    """AC: RuntimeError message should name the environment so ops knows what's wrong."""
    with pytest.raises(RuntimeError) as exc_info:
        _load_auth_with_env({"ENVIRONMENT": "prd"})
    assert "prd" in str(exc_info.value)
