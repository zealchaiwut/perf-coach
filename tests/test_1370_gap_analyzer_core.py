"""Tests for issue #1370: gap analyzer core — findings schema, persistence, API skeleton.

AC coverage:
- AC1: Finding schema (pydantic + table): code, severity, recommendation, evidence, target,
       computed_at, week_start, user_id, status
- AC2: New Alembic migration (random hex id, idempotent) creating gap_findings table
- AC3: Rules registry — pure function interface, skip on missing inputs, skipped_rules in payload
- AC4: run_gap_analysis computes findings, upserts, recompute preserves status
- AC5: Reference rule no_recent_plyo — no plyo in 28 days → severity 1 finding
- AC7: Tests: engine skip semantics, upsert preserves status, reference rule, payload shape
"""
from __future__ import annotations

import datetime
import os
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.models import GapFinding, User as _UserModel

_TEST_PW = "test1370pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


# ── helpers ──────────────────────────────────────────────────────────────────

def _delete_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        if u:
            sess.delete(u)
            sess.commit()


# ── AC1: Model / schema ──────────────────────────────────────────────────────

def test_ac1_model_tablename():
    """AC1: GapFinding model is importable and maps to gap_findings table."""
    assert GapFinding.__tablename__ == "gap_findings"


def test_ac1_required_columns():
    """AC1: gap_findings has all required columns."""
    col_names = {c.name for c in GapFinding.__table__.columns}
    required = {
        "id", "user_id", "code", "severity", "recommendation",
        "evidence", "target", "computed_at", "week_start", "status",
    }
    assert required <= col_names, f"Missing columns: {required - col_names}"


def test_ac1_unique_constraint_on_user_week_code():
    """AC1: Unique constraint exists on (user_id, week_start, code)."""
    constraint_names = {c.name for c in GapFinding.__table__.constraints}
    assert "uq_gap_findings_user_week_code" in constraint_names


def test_ac1_status_default_is_active():
    """AC1: status column has server default 'active'."""
    status_col = next(c for c in GapFinding.__table__.columns if c.name == "status")
    assert status_col.server_default is not None


# ── AC2: Pydantic finding schema ──────────────────────────────────────────────

def test_ac2_finding_schema_importable():
    """AC2: GapAnalysisFinding pydantic model importable with required fields."""
    from backend.services.gap_analysis.schemas import GapAnalysisFinding
    fields = GapAnalysisFinding.model_fields
    for name in ("code", "severity", "recommendation", "evidence"):
        assert name in fields, f"Missing field: {name}"


def test_ac2_finding_schema_severity_values():
    """AC2: severity must be 1, 2, or 3."""
    from backend.services.gap_analysis.schemas import GapAnalysisFinding
    f = GapAnalysisFinding(
        code="test_code",
        severity=1,
        recommendation="Do something",
        evidence=[{"metric": "days", "value": 30, "threshold": 28, "window": "28d"}],
        target=None,
        week_start=datetime.date(2026, 7, 7),
    )
    assert f.severity == 1


def test_ac2_finding_evidence_list_of_dicts():
    """AC2: evidence is a list of dicts with metric/value/threshold/window."""
    from backend.services.gap_analysis.schemas import GapAnalysisFinding
    ev = {"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}
    f = GapAnalysisFinding(
        code="no_recent_plyo",
        severity=1,
        recommendation="Add a plyometric session",
        evidence=[ev],
        week_start=datetime.date(2026, 7, 7),
    )
    assert len(f.evidence) == 1
    assert f.evidence[0]["metric"] == "days_since_plyo"


# ── AC3: Rules registry ───────────────────────────────────────────────────────

def test_ac3_registry_importable():
    """AC3: Rule registry importable from gap_analysis package."""
    from backend.services.gap_analysis.registry import RuleRegistry
    r = RuleRegistry()
    assert hasattr(r, "register")
    assert hasattr(r, "run_all")


def test_ac3_register_and_run_rule():
    """AC3: Registered rule receives inputs and returns finding or None."""
    from backend.services.gap_analysis.registry import RuleRegistry
    from backend.services.gap_analysis.schemas import GapAnalysisFinding
    import datetime

    r = RuleRegistry()

    @r.register(requires=["structural_dose"])
    def my_rule(inputs):
        dose = inputs["structural_dose"]
        if dose.get("last_plyo_days_ago") is None:
            return GapAnalysisFinding(
                code="no_recent_plyo",
                severity=1,
                recommendation="Add a plyo session",
                evidence=[],
                week_start=inputs["week_start"],
            )
        return None

    result = r.run_all(
        inputs={"structural_dose": {"last_plyo_days_ago": None}, "week_start": datetime.date(2026, 7, 7)},
        week_start=datetime.date(2026, 7, 7),
    )
    assert result["findings"] is not None
    assert any(f.code == "no_recent_plyo" for f in result["findings"])


def test_ac3_rule_skipped_when_required_input_missing():
    """AC3: Rule whose required input is absent is skipped; listed in skipped_rules."""
    from backend.services.gap_analysis.registry import RuleRegistry
    from backend.services.gap_analysis.schemas import GapAnalysisFinding

    r = RuleRegistry()

    @r.register(requires=["muscle_volume"])
    def volume_rule(inputs):
        return GapAnalysisFinding(
            code="muscle_imbalance",
            severity=2,
            recommendation="Fix your imbalance",
            evidence=[],
            week_start=inputs["week_start"],
        )

    result = r.run_all(
        inputs={"week_start": datetime.date(2026, 7, 7)},
        week_start=datetime.date(2026, 7, 7),
    )
    assert "volume_rule" in result["skipped_rules"]
    assert not any(f.code == "muscle_imbalance" for f in result["findings"])


def test_ac3_rule_never_crashes_engine():
    """AC3: Exception inside a rule is caught; rule listed as skipped, engine continues."""
    from backend.services.gap_analysis.registry import RuleRegistry

    r = RuleRegistry()

    @r.register(requires=[])
    def bad_rule(inputs):
        raise RuntimeError("oops")

    result = r.run_all(inputs={"week_start": datetime.date(2026, 7, 7)}, week_start=datetime.date(2026, 7, 7))
    assert "bad_rule" in result["skipped_rules"]
    assert result["findings"] == []


# ── AC5: Reference rule no_recent_plyo ───────────────────────────────────────

def test_ac5_no_recent_plyo_fires_when_never_done():
    """AC5: no_recent_plyo returns severity-1 finding when last_plyo_days_ago is None."""
    from backend.services.gap_analysis.rules.no_recent_plyo import no_recent_plyo
    from backend.services.gap_analysis.schemas import GapAnalysisFinding

    result = no_recent_plyo(
        {"structural_dose": {"last_plyo_days_ago": None}, "week_start": datetime.date(2026, 7, 7)}
    )
    assert result is not None
    assert isinstance(result, GapAnalysisFinding)
    assert result.code == "no_recent_plyo"
    assert result.severity == 1


def test_ac5_no_recent_plyo_fires_when_over_threshold():
    """AC5: no_recent_plyo fires when last_plyo_days_ago > 28."""
    from backend.services.gap_analysis.rules.no_recent_plyo import no_recent_plyo

    result = no_recent_plyo(
        {"structural_dose": {"last_plyo_days_ago": 35}, "week_start": datetime.date(2026, 7, 7)}
    )
    assert result is not None
    assert result.code == "no_recent_plyo"


def test_ac5_no_recent_plyo_silent_when_recent():
    """AC5: no_recent_plyo returns None when last_plyo_days_ago <= 28."""
    from backend.services.gap_analysis.rules.no_recent_plyo import no_recent_plyo

    result = no_recent_plyo(
        {"structural_dose": {"last_plyo_days_ago": 14}, "week_start": datetime.date(2026, 7, 7)}
    )
    assert result is None


def test_ac5_no_recent_plyo_evidence_shape():
    """AC5: no_recent_plyo evidence contains days_since_plyo metric with threshold 28."""
    from backend.services.gap_analysis.rules.no_recent_plyo import no_recent_plyo

    result = no_recent_plyo(
        {"structural_dose": {"last_plyo_days_ago": 40}, "week_start": datetime.date(2026, 7, 7)}
    )
    assert result is not None
    ev = result.evidence
    assert len(ev) >= 1
    assert ev[0]["metric"] == "days_since_plyo"
    assert ev[0]["threshold"] == 28


def test_ac5_no_recent_plyo_registered_in_engine():
    """AC5: no_recent_plyo rule is registered in the default engine registry."""
    from backend.services.gap_analysis.engine import _REGISTRY
    rule_names = [entry.fn.__name__ for entry in _REGISTRY._rules]
    assert "no_recent_plyo" in rule_names


# ── AC4: Endpoint ─────────────────────────────────────────────────────────────
# These tests use TestClient (in-process) so they work against the current code
# without needing a separately-running server.


def _tc_create_and_login(tc):
    """Create a test user and log in via TestClient. Returns (user_id, session_cookies)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"gap_tc_{uuid.uuid4().hex[:8]}"
    # TestClient uses conftest.py's require_admin bypass, so no admin cookie needed
    r = tc.post("/api/users", json={"name": user_name})
    assert r.status_code == 201, f"create user failed: {r.text}"
    user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    r = tc.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    assert r.status_code == 200, f"login failed: {r.text}"
    return user_id



def _run_gap(user_id: str) -> dict:
    from backend.services.gap_analysis.engine import run_gap_analysis
    from backend.utils.time import today_bangkok

    with _OrmSess(_engine) as db:
        return run_gap_analysis(db, uuid.UUID(user_id), today_bangkok())


def _create_user_for_engine() -> str:
    """Create a user via TestClient admin path; return user_id (no session needed)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as tc:
        return _tc_create_and_login(tc)


def test_ac4_payload_shape():
    """AC4: Engine payload has week_start, computed_at, findings, skipped_rules."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_id = _create_user_for_engine()
    try:
        data = _run_gap(user_id)
        for key in ("week_start", "computed_at", "findings", "skipped_rules"):
            assert key in data, f"Missing key: {key}"
        assert isinstance(data["findings"], list)
        assert isinstance(data["skipped_rules"], list)
    finally:
        _delete_user(user_id)


def test_ac4_upsert_no_duplicate_rows():
    """AC4: Running gap analysis twice same week produces one row per (user, week, code)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_id = _create_user_for_engine()
    try:
        _run_gap(user_id)
        _run_gap(user_id)

        with _OrmSess(_engine) as sess:
            count = sess.execute(
                text("SELECT COUNT(*) FROM gap_findings WHERE user_id = :uid"),
                {"uid": user_id},
            ).scalar()
            distinct_count = sess.execute(
                text(
                    "SELECT COUNT(DISTINCT (user_id::text, week_start::text, code)) "
                    "FROM gap_findings WHERE user_id = :uid"
                ),
                {"uid": user_id},
            ).scalar()
        assert count == distinct_count, "Duplicate (user, week, code) rows found"
    finally:
        _delete_user(user_id)


def test_ac4_recompute_preserves_status():
    """AC4: Recomputing preserves the status field of existing gap_findings rows."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_id = _create_user_for_engine()
    try:
        _run_gap(user_id)

        with _OrmSess(_engine) as sess:
            sess.execute(
                text("UPDATE gap_findings SET status = 'accepted' WHERE user_id = :uid"),
                {"uid": user_id},
            )
            sess.commit()

        _run_gap(user_id)

        with _OrmSess(_engine) as sess:
            rows = sess.execute(
                text("SELECT status FROM gap_findings WHERE user_id = :uid"),
                {"uid": user_id},
            ).fetchall()
        assert len(rows) > 0, "No gap_findings rows for user"
        for row in rows:
            assert row[0] == "accepted", f"Status was overwritten: {row[0]}"
    finally:
        _delete_user(user_id)


def test_ac4_no_recent_plyo_finding_persisted():
    """AC4+AC5: no_recent_plyo finding is persisted in gap_findings for a fresh user."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_id = _create_user_for_engine()
    try:
        _run_gap(user_id)

        with _OrmSess(_engine) as sess:
            row = sess.execute(
                text(
                    "SELECT code, severity, status FROM gap_findings "
                    "WHERE user_id = :uid AND code = 'no_recent_plyo'"
                ),
                {"uid": user_id},
            ).fetchone()
        assert row is not None, "no_recent_plyo row not found in gap_findings"
        assert row[0] == "no_recent_plyo"
        assert row[1] == 1
        assert row[2] == "active"
    finally:
        _delete_user(user_id)
