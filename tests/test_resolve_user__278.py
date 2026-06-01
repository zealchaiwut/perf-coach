"""Tests for issue #278: resolve_user dependency with legacy query param shim."""
import asyncio
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import backend.main as main_mod
from backend.auth import COOKIE_NAME
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
            main_mod.resolve_user(request, user_id=None)
        )

    assert result is mock_user


def test_resolve_user_session_ignores_user_id_param():
    """Session cookie present: shim user_id param is never consulted."""
    mock_user = _make_user()
    request = _request_with_cookie("some-token")

    with patch.object(main_mod, "get_current_user", new=AsyncMock(return_value=mock_user)):
        result = asyncio.get_event_loop().run_until_complete(
            main_mod.resolve_user(request, user_id=str(uuid.uuid4()))
        )

    assert result is mock_user


# ── shim-enabled path ─────────────────────────────────────────────────────────

def test_resolve_user_shim_enabled_resolves_via_query_param(caplog):
    """Shim on, no session cookie, valid ?user_id: resolves user and logs deprecation."""
    uid = uuid.uuid4()
    mock_user = _make_user(uid)
    request = _request_with_cookie(None)

    original = main_mod.LEGACY_USER_ID_SHIM_ENABLED
    main_mod.LEGACY_USER_ID_SHIM_ENABLED = True
    try:
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_db.get.return_value = mock_user

        with patch("backend.main.Session", return_value=mock_db):
            with caplog.at_level(logging.WARNING, logger="backend.main"):
                result = asyncio.get_event_loop().run_until_complete(
                    main_mod.resolve_user(request, user_id=str(uid))
                )
    finally:
        main_mod.LEGACY_USER_ID_SHIM_ENABLED = original

    assert result is mock_user
    assert any("Deprecated" in r.message for r in caplog.records), (
        "Expected deprecation warning when resolving via ?user_id shim"
    )


def test_resolve_user_shim_enabled_no_user_id_raises_401():
    """Shim on, no session, no ?user_id: raises HTTP 401."""
    request = _request_with_cookie(None)

    original = main_mod.LEGACY_USER_ID_SHIM_ENABLED
    main_mod.LEGACY_USER_ID_SHIM_ENABLED = True
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                main_mod.resolve_user(request, user_id=None)
            )
    finally:
        main_mod.LEGACY_USER_ID_SHIM_ENABLED = original

    assert exc_info.value.status_code == 401


# ── shim-disabled path ────────────────────────────────────────────────────────

def test_resolve_user_shim_disabled_rejects_query_param_with_401():
    """Shim off, no session: raises HTTP 401 even when ?user_id is provided."""
    request = _request_with_cookie(None)

    original = main_mod.LEGACY_USER_ID_SHIM_ENABLED
    main_mod.LEGACY_USER_ID_SHIM_ENABLED = False
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                main_mod.resolve_user(request, user_id=str(uuid.uuid4()))
            )
    finally:
        main_mod.LEGACY_USER_ID_SHIM_ENABLED = original

    assert exc_info.value.status_code == 401


def test_resolve_user_shim_disabled_no_warning_logged(caplog):
    """Shim off: no deprecation warning even when ?user_id is provided."""
    request = _request_with_cookie(None)

    original = main_mod.LEGACY_USER_ID_SHIM_ENABLED
    main_mod.LEGACY_USER_ID_SHIM_ENABLED = False
    try:
        with caplog.at_level(logging.WARNING, logger="backend.main"):
            with pytest.raises(HTTPException):
                asyncio.get_event_loop().run_until_complete(
                    main_mod.resolve_user(request, user_id=str(uuid.uuid4()))
                )
    finally:
        main_mod.LEGACY_USER_ID_SHIM_ENABLED = original

    assert not any("Deprecated" in r.message for r in caplog.records)
