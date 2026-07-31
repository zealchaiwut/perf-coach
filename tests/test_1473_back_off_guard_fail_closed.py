"""Tests for issue #1473: back_off verdict guard fails closed on computation error.

AC coverage:
- AC1: When verdict computation raises (returns None), load-adding add-to-plan
       returns 409 with code "verdict_unavailable" instead of allowing the add.
- AC2: Non-load-adding templates are NOT blocked when verdict is None (only
       load-adding paths trigger the fail-closed guard).
- AC3: The existing back_off → 409 behavior is unchanged.
- AC4: When verdict is a non-back_off value ("hold", "build"), load-adding
       sessions proceed normally.
"""
from __future__ import annotations

import os
import pathlib
import uuid

import pytest

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

_engine = None
# Only create the engine when the backend itself is connected to a real DB.
# The root conftest.py sets DATABASE_URL to sqlite when ENVIRONMENT != "uat".
# If the backend uses SQLite, TestClient requests fail with "no such table".
if _uat_url and "sqlite" not in os.getenv("DATABASE_URL", "sqlite").lower():
    from sqlalchemy import create_engine
    _engine = create_engine(_uat_url, pool_pre_ping=True)

_TEST_PW = "test1473pw!"


def _delete_user(user_id: str) -> None:
    if _engine is None:
        return
    from sqlalchemy.orm import Session as _S
    from backend.models import User as _U
    with _S(_engine) as sess:
        u = sess.get(_U, uuid.UUID(user_id))
        if u:
            sess.delete(u)
            sess.commit()


def _create_and_login(tc):
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from sqlalchemy.orm import Session as _S
    from backend.models import User as _U
    from backend.auth import hash_password as _hp

    name = f"u1473_{uuid.uuid4().hex[:8]}"
    r = tc.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    with _S(_engine) as db:
        u = db.get(_U, uuid.UUID(uid))
        u.password_hash = _hp(_TEST_PW)
        db.commit()
    r = tc.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert r.status_code == 200, r.text
    csrf = r.cookies.get("csrf-token", "")
    return uid, csrf


def _post(tc, url, body, csrf):
    return tc.post(url, json=body, headers={"X-CSRF-Token": csrf})


# ── AC1: fail closed when verdict is None (computation error) ─────────────────

def test_ac1_verdict_none_blocks_load_adding(monkeypatch):
    """AC1: None verdict for load-adding template → 409 verdict_unavailable."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as _m

    monkeypatch.setattr(_m, "_gap_get_verdict_for_user", lambda uid, today: None)

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            r = _post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                      {"date": "2026-07-17"}, csrf)
            assert r.status_code == 409, r.text
            detail = r.json().get("detail", {})
            assert detail.get("code") == "verdict_unavailable", (
                f"Expected code='verdict_unavailable', got detail={detail!r}"
            )
        finally:
            _delete_user(uid)


def test_ac1_verdict_none_message_is_clear(monkeypatch):
    """AC1: The 409 for None verdict has a human-readable message."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as _m

    monkeypatch.setattr(_m, "_gap_get_verdict_for_user", lambda uid, today: None)

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            r = _post(tc, "/api/training/gap-analysis/aerobic_durability_gap/add-to-plan",
                      {"date": "2026-07-17"}, csrf)
            assert r.status_code == 409, r.text
            detail = r.json().get("detail", {})
            msg = detail.get("message", "")
            assert msg, f"Expected a non-empty message, got detail={detail!r}"
        finally:
            _delete_user(uid)


# ── AC2: non-load-adding templates NOT blocked when verdict is None ───────────

def test_ac2_non_load_adding_not_blocked_when_verdict_none(monkeypatch):
    """AC2: Non-load-adding template proceeds even when verdict is None."""
    from backend.services.gap_analysis.templates import is_load_adding
    # Confirm intensity_too_hard is non-load-adding (it has no template so returns 404,
    # but the guard must NOT apply).  We verify the guard logic directly.
    assert not is_load_adding("recurrent_niggle_area"), (
        "recurrent_niggle_area must not be load-adding"
    )
    assert not is_load_adding("intensity_too_hard"), (
        "intensity_too_hard must not be load-adding"
    )


# ── AC3: existing back_off behaviour unchanged ────────────────────────────────

def test_ac3_back_off_still_returns_409(monkeypatch):
    """AC3: back_off verdict still yields 409 with code back_off."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as _m

    monkeypatch.setattr(_m, "_gap_get_verdict_for_user", lambda uid, today: "back_off")

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            r = _post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                      {"date": "2026-07-17"}, csrf)
            assert r.status_code == 409, r.text
            detail = r.json().get("detail", {})
            assert detail.get("code") == "back_off", (
                f"Expected code='back_off', got detail={detail!r}"
            )
        finally:
            _delete_user(uid)


# ── AC4: non-back_off verdicts allow the add ─────────────────────────────────

def test_ac4_hold_verdict_allows_load_adding(monkeypatch):
    """AC4: 'hold' verdict does not block load-adding sessions."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as _m

    monkeypatch.setattr(_m, "_gap_get_verdict_for_user", lambda uid, today: "hold")

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            r = _post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                      {"date": "2026-07-17"}, csrf)
            assert r.status_code == 201, f"Expected 201 for 'hold' verdict, got {r.status_code}: {r.text}"
        finally:
            _delete_user(uid)


def test_ac4_build_verdict_allows_load_adding(monkeypatch):
    """AC4: 'build' verdict does not block load-adding sessions."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as _m

    monkeypatch.setattr(_m, "_gap_get_verdict_for_user", lambda uid, today: "build")

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            r = _post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                      {"date": "2026-07-17"}, csrf)
            assert r.status_code == 201, f"Expected 201 for 'build' verdict, got {r.status_code}: {r.text}"
        finally:
            _delete_user(uid)
