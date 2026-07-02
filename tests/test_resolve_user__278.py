"""Tests for issue #278 / fix-loopholes Task 3: resolve_user dependency.

The legacy ?user_id query-param impersonation shim (LEGACY_USER_ID_SHIM_ENABLED)
has been removed entirely — resolve_user only ever trusts the signed session
cookie. These tests assert a query-param user_id can never authenticate a
request, with or without a session cookie.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import backend.main as main_mod
from backend.models import User


def _make_user(uid=None):
    user = MagicMock(spec=User)
    user.id = uid or uuid.uuid4()
    user.name = "test-user"
    return user


def _request_with_cookie(value):
    request = MagicMock()
    request.cookies.get.return_value = value
    return request


# ── session path ─────────────────────────────────────────────────────────────

def test_resolve_user_session_path():
    """Valid session cookie: resolve_user delegates to get_current_user."""
    mock_user = _make_user()
    request = _request_with_cookie("some-token")

    with patch.object(main_mod, "get_current_user", new=AsyncMock(return_value=mock_user)):
        result = asyncio.get_event_loop().run_until_complete(
            main_mod.resolve_user(request)
        )

    assert result is mock_user


# ── no session: always 401, regardless of any query param ─────────────────────

def test_resolve_user_no_session_raises_401():
    """No session cookie: raises HTTP 401."""
    request = _request_with_cookie(None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(
            main_mod.resolve_user(request)
        )

    assert exc_info.value.status_code == 401


def test_resolve_user_has_no_user_id_param():
    """The legacy ?user_id shim param no longer exists on resolve_user's signature."""
    import inspect
    sig = inspect.signature(main_mod.resolve_user)
    assert "user_id" not in sig.parameters


def test_legacy_shim_flag_removed():
    """LEGACY_USER_ID_SHIM_ENABLED module attribute no longer exists."""
    assert not hasattr(main_mod, "LEGACY_USER_ID_SHIM_ENABLED")
