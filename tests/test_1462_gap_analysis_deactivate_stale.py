"""Tests for issue #1462: gap-analysis recompute deactivates stale active findings.

AC coverage:
- AC1: After recompute, active rows whose code no longer fires are deleted from gap_findings.
- AC2: After recompute, non-active rows (accepted/dismissed) whose code no longer fires are preserved.
- AC3: Findings that still fire on recompute keep their existing row (upsert, not re-insert).

Triggers recompute via ``run_gap_analysis`` (the Plan-tab HTTP surface was removed).
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.models import User as _UserModel
from backend.services.gap_analysis.engine import run_gap_analysis
from backend.utils.time import today_bangkok
from tests._admin_helpers import admin_cookies as _admin_cookies

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
    today = today_bangkok()
    return today - timedelta(days=today.weekday())


def _create_user() -> str:
    """Create a test user via admin API; return user_id."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    import httpx

    base = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
    user_name = f"gap1462_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=base, timeout=10.0) as client:
        r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = r.json()["id"]

    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        sess.commit()
    return user_id


def _recompute(user_id: str) -> dict:
    with _OrmSess(_engine) as db:
        return run_gap_analysis(db, uuid.UUID(user_id), today_bangkok())


def test_ac1_stale_active_finding_is_deleted():
    """AC1: An active row whose code no longer fires is removed after recompute."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_id = _create_user()
    try:
        week_start = _current_week_start()
        stale_code = "__test_stale_1462__"

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

        with _OrmSess(_engine) as sess:
            row = sess.execute(
                text("SELECT status FROM gap_findings WHERE user_id = :uid AND code = :code"),
                {"uid": user_id, "code": stale_code},
            ).fetchone()
        assert row is not None and row[0] == "active"

        _recompute(user_id)

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


def test_ac2_accepted_stale_finding_is_preserved():
    """AC2: An accepted row whose code no longer fires is NOT deleted on recompute."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_id = _create_user()
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

        _recompute(user_id)

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

    user_id = _create_user()
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

        _recompute(user_id)

        with _OrmSess(_engine) as sess:
            row = sess.execute(
                text("SELECT status FROM gap_findings WHERE user_id = :uid AND code = :code"),
                {"uid": user_id, "code": dismissed_code},
            ).fetchone()
        assert row is not None, "Dismissed row should not be deleted on recompute"
        assert row[0] == "dismissed"
    finally:
        _delete_user(user_id)


def test_ac3_still_upserts_firing_findings():
    """AC3: Findings that fire are still upserted into gap_findings."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_id = _create_user()
    try:
        result = _recompute(user_id)
        assert "findings" in result
        assert "week_start" in result

        with _OrmSess(_engine) as sess:
            rows = sess.execute(
                text("SELECT code, status FROM gap_findings WHERE user_id = :uid"),
                {"uid": user_id},
            ).fetchall()
        codes_in_db = {row[0] for row in rows}
        codes_in_result = {f["code"] for f in result["findings"]}

        assert codes_in_result <= codes_in_db, (
            f"Codes in result but not in DB: {codes_in_result - codes_in_db}"
        )
    finally:
        _delete_user(user_id)
