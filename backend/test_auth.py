"""Unit tests for issue #274: stdlib-only auth primitives (no server or DB required)."""
import pytest

from backend.auth import (
    create_session_cookie,
    hash_password,
    read_session_cookie,
    verify_password,
)


def test_hash_round_trip():
    stored = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", stored)


def test_wrong_password_rejected():
    stored = hash_password("correct")
    assert not verify_password("wrong", stored)


def test_forged_cookie_rejected():
    with pytest.raises(ValueError):
        read_session_cookie("forged-payload.invalidsig")


def test_tampered_cookie_rejected():
    token = create_session_cookie("test-user-id", 1_700_000_000.0)
    payload, sig = token.rsplit(".", 1)
    tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    with pytest.raises(ValueError):
        read_session_cookie(f"{tampered}.{sig}")
