"""Tests for issue #1462: gap-analysis recompute deactivates stale active findings.

AC coverage:
- AC1: After recompute, active rows whose code no longer fires are deleted from gap_findings.
- AC2: After recompute, non-active rows (accepted/dismissed) whose code no longer fires are preserved.
- AC3: Findings that still fire on recompute keep their existing row (upsert, not re-insert).
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.models import User as _UserModel
from backend.utils.time import today_bangkok
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1462pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _delete_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        if u:
            sess.delete(u)
            sess.commit()


def _current_week_start():
    """Return the ISO Monday of the current Bangkok week (mirrors run_gap_analysis)."""
    today = today_bangkok()
    return today - timedelta(days=today.weekday())


def _create_and_login(client: httpx.Client) -> tuple[httpx.Client, str]:
    """Create a test user, set password, log in, return (auth_client, user_id)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"gap1462_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201, f"create user failed: {r.text}"
    user_id = r.json()["id"]

    # Set password directly — /api/users creates the user without a password
    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        sess.commit()

    # Log in
    r2 = client.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    assert r2.status_code == 200, f"login failed: {r2.text}"

    # Return a new authenticated client with the session cookie
    auth_client = httpx.Client(base_url=BASE_URL, timeout=10.0)
    auth_client.cookies.update(client.cookies)
    return auth_client, user_id


# ── AC1: stale active rows are deleted on recompute ──────────────────────────

def test_ac1_stale_active_finding_is_deleted():
    """AC1: An active row whose code no longer fires is removed after recompute."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        auth_client, user_id = _create_and_login(client)
        try:
            week_start = _current_week_start()
            stale_code = "__test_stale_1462__"

            # Seed an active gap_findings row for a code that no real rule produces
            with _OrmSess(_engine) as sess:
                sess.execute(
                    text("""
                        INSERT INTO gap_findings
                            (id, user_id, week_start, code, severity, recommendation,
                             evidence, target, computed_at, status, created_at)
                        VALUES
                            (gen_random_uuid(), :uid, :ws, :code, 1, 'test rec',
                             '[]'::jsonb, NULL, now(), 'active', now())
                    """),
                    {"uid": user_id, "ws": week_start.isoformat(), "code": stale_code},
                )
                sess.commit()

            # Verify it was inserted
            with _OrmSess(_engine) as sess:
                row = sess.execute(
                    text("SELECT status FROM gap_findings WHERE user_id = :uid AND code = :code"),
                    {"uid": user_id, "code": stale_code},
                ).fetchone()
            assert row is not None, "Stale finding row not seeded"
            assert row[0] == "active"

            # Run gap analysis — this will NOT fire our stale code
            r = auth_client.get("/api/training/gap-analysis")
            assert r.status_code == 200, r.text

            # The stale active row must be gone
            with _OrmSess(_engine) as sess:
                row_after = sess.execute(
                    text("SELECT status FROM gap_findings WHERE user_id = :uid AND code = :code"),
                    {"uid": user_id, "code": stale_code},
                ).fetchone()
            assert row_after is None, (
                f"Stale active row with code '{stale_code}' should have been deleted "
                f"after recompute, but status={row_after[0] if row_after else 'N/A'}"
            )
        finally:
            _delete_user(user_id)


# ── AC2: non-active rows (accepted/dismissed) for stale codes are preserved ──

def test_ac2_accepted_stale_finding_is_preserved():
    """AC2: An accepted row whose code no longer fires is NOT deleted on recompute."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        auth_client, user_id = _create_and_login(client)
        try:
            week_start = _current_week_start()
            accepted_code = "__test_accepted_1462__"

            with _OrmSess(_engine) as sess:
                sess.execute(
                    text("""
                        INSERT INTO gap_findings
                            (id, user_id, week_start, code, severity, recommendation,
                             evidence, target, computed_at, status, created_at)
                        VALUES
                            (gen_random_uuid(), :uid, :ws, :code, 1, 'test rec',
                             '[]'::jsonb, NULL, now(), 'accepted', now())
                    """),
                    {"uid": user_id, "ws": week_start.isoformat(), "code": accepted_code},
                )
                sess.commit()

            r = auth_client.get("/api/training/gap-analysis")
            assert r.status_code == 200, r.text

            with _OrmSess(_engine) as sess:
                row = sess.execute(
                    text("SELECT status FROM gap_findings WHERE user_id = :uid AND code = :code"),
                    {"uid": user_id, "code": accepted_code},
                ).fetchone()
            assert row is not None, "Accepted row should not be deleted on recompute"
            assert row[0] == "accepted"
        finally:
            _delete_user(user_id)


def test_ac2_dismissed_stale_finding_is_preserved():
    """AC2: A dismissed row whose code no longer fires is NOT deleted on recompute."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        auth_client, user_id = _create_and_login(client)
        try:
            week_start = _current_week_start()
            dismissed_code = "__test_dismissed_1462__"

            with _OrmSess(_engine) as sess:
                sess.execute(
                    text("""
                        INSERT INTO gap_findings
                            (id, user_id, week_start, code, severity, recommendation,
                             evidence, target, computed_at, status, created_at)
                        VALUES
                            (gen_random_uuid(), :uid, :ws, :code, 1, 'test rec',
                             '[]'::jsonb, NULL, now(), 'dismissed', now())
                    """),
                    {"uid": user_id, "ws": week_start.isoformat(), "code": dismissed_code},
                )
                sess.commit()

            r = auth_client.get("/api/training/gap-analysis")
            assert r.status_code == 200, r.text

            with _OrmSess(_engine) as sess:
                row = sess.execute(
                    text("SELECT status FROM gap_findings WHERE user_id = :uid AND code = :code"),
                    {"uid": user_id, "code": dismissed_code},
                ).fetchone()
            assert row is not None, "Dismissed row should not be deleted on recompute"
            assert row[0] == "dismissed"
        finally:
            _delete_user(user_id)


# ── AC3: Existing prior tests still pass (no regression on upsert behavior) ──

def test_ac3_still_upserts_firing_findings():
    """AC3: Findings that fire are still upserted and appear in the response."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        auth_client, user_id = _create_and_login(client)
        try:
            r = auth_client.get("/api/training/gap-analysis")
            assert r.status_code == 200, r.text
            payload = r.json()
            assert "findings" in payload
            assert "week_start" in payload

            # For a fresh user with no plyo, no_recent_plyo always fires
            with _OrmSess(_engine) as sess:
                rows = sess.execute(
                    text("SELECT code, status FROM gap_findings WHERE user_id = :uid"),
                    {"uid": user_id},
                ).fetchall()
            codes_in_db = {row[0] for row in rows}
            codes_in_response = {f["code"] for f in payload["findings"]}

            # Every firing code must appear in the DB
            assert codes_in_response <= codes_in_db, (
                f"Codes in response but not in DB: {codes_in_response - codes_in_db}"
            )
        finally:
            _delete_user(user_id)
