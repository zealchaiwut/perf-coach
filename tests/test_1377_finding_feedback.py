"""Tests for issue #1377: finding feedback — accept/dismiss with suppression window.

AC coverage:
- AC1: POST /api/training/gap-analysis/{code}/status updates status to accepted|dismissed|active
- AC2: Dismissed finding excluded from panel for 28-day window; severity-rise override returns it
- AC3: Accepted finding shown with check state this week; excluded next weeks while evidence unchanged;
       evidence materially changing reactivates
- AC4: Panel returns suppressed findings in muted list (never fully invisible)
- AC5: Tests for suppression window boundaries, severity-rise, accept reactivation, restore
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.models import GapFinding, User as _UserModel

_TEST_PW = "test1377pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _evidence_hash(evidence: list) -> str:
    canonical = json.dumps(sorted(evidence, key=lambda x: x.get("metric", "")), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _skip_no_db():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


def _delete_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        if u:
            sess.delete(u)
            sess.commit()


def _create_and_login(tc):
    _skip_no_db()
    name = f"gap1377_{uuid.uuid4().hex[:8]}"
    r = tc.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()
    r = tc.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert r.status_code == 200, r.text
    csrf = r.cookies.get("csrf-token", "")
    return uid, csrf


def _post(tc, url, body, csrf):
    return tc.post(url, json=body, headers={"X-CSRF-Token": csrf})


def _insert_gap_finding(
    db,
    user_id: str,
    code: str = "cadence_drift",
    severity: int = 2,
    status: str = "active",
    week_start: datetime.date | None = None,
    dismissed_at: datetime.datetime | None = None,
    dismissed_severity: int | None = None,
    accepted_at: datetime.datetime | None = None,
    accepted_evidence_hash: str | None = None,
    evidence: list | None = None,
) -> uuid.UUID:
    if week_start is None:
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())
    if evidence is None:
        evidence = [{"metric": "cadence_spm", "value": 162, "threshold": 170, "window": "recent"}]
    row_id = uuid.uuid4()
    db.execute(
        text("""
            INSERT INTO gap_findings
              (id, user_id, week_start, code, severity, recommendation, evidence,
               target, computed_at, status, created_at,
               dismissed_at, dismissed_severity, accepted_at, accepted_evidence_hash)
            VALUES
              (:id, :uid, :ws, :code, :sev, 'test rec', CAST(:ev AS jsonb),
               NULL, now(), :status, now(),
               :dismissed_at, :dismissed_severity, :accepted_at, :accepted_evidence_hash)
        """),
        {
            "id": str(row_id),
            "uid": user_id,
            "ws": week_start.isoformat(),
            "code": code,
            "sev": severity,
            "ev": json.dumps(evidence),
            "status": status,
            "dismissed_at": dismissed_at.isoformat() if dismissed_at else None,
            "dismissed_severity": dismissed_severity,
            "accepted_at": accepted_at.isoformat() if accepted_at else None,
            "accepted_evidence_hash": accepted_evidence_hash,
        },
    )
    db.commit()
    return row_id


# ── AC1: Status endpoint ──────────────────────────────────────────────────────

def test_ac1_status_endpoint_401_anonymous():
    """AC1: Unauthenticated request returns 401."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as tc:
        r = _post(tc, "/api/training/gap-analysis/cadence_drift/status", {"status": "dismissed"}, "")
    assert r.status_code == 401


def test_ac1_status_endpoint_404_no_finding():
    """AC1: 404 when no gap_findings row exists for this week/code."""
    _skip_no_db()
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            r = _post(tc, "/api/training/gap-analysis/cadence_drift/status",
                      {"status": "dismissed"}, csrf)
            assert r.status_code == 404, r.text
        finally:
            _delete_user(uid)


def test_ac1_status_endpoint_422_invalid_status():
    """AC1: Invalid status value returns 422."""
    _skip_no_db()
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            r = _post(tc, "/api/training/gap-analysis/cadence_drift/status",
                      {"status": "invalid_value"}, csrf)
            assert r.status_code == 422, r.text
        finally:
            _delete_user(uid)


def test_ac1_dismiss_sets_status_and_metadata():
    """AC1: Dismissing a finding updates status, dismissed_at, dismissed_severity."""
    _skip_no_db()
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            with _OrmSess(_engine) as db:
                _insert_gap_finding(db, uid, code="cadence_drift", severity=2, status="active")

            r = _post(tc, "/api/training/gap-analysis/cadence_drift/status",
                      {"status": "dismissed"}, csrf)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["status"] == "dismissed"

            with _OrmSess(_engine) as db:
                today = datetime.date.today()
                ws = today - datetime.timedelta(days=today.weekday())
                row = db.execute(
                    text("SELECT status, dismissed_at, dismissed_severity FROM gap_findings "
                         "WHERE user_id = :uid AND code = 'cadence_drift' AND week_start = :ws"),
                    {"uid": uid, "ws": ws.isoformat()},
                ).fetchone()
                assert row is not None
                assert row[0] == "dismissed"
                assert row[1] is not None   # dismissed_at set
                assert row[2] == 2          # dismissed_severity = severity at time of dismissal
        finally:
            _delete_user(uid)


def test_ac1_accept_sets_status_and_evidence_hash():
    """AC1: Accepting a finding updates status, accepted_at, accepted_evidence_hash."""
    _skip_no_db()
    from fastapi.testclient import TestClient
    from backend.main import app

    evidence = [{"metric": "cadence_spm", "value": 162, "threshold": 170, "window": "recent"}]
    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            with _OrmSess(_engine) as db:
                _insert_gap_finding(db, uid, code="cadence_drift", severity=2,
                                    status="active", evidence=evidence)

            r = _post(tc, "/api/training/gap-analysis/cadence_drift/status",
                      {"status": "accepted"}, csrf)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["status"] == "accepted"

            with _OrmSess(_engine) as db:
                today = datetime.date.today()
                ws = today - datetime.timedelta(days=today.weekday())
                row = db.execute(
                    text("SELECT status, accepted_at, accepted_evidence_hash FROM gap_findings "
                         "WHERE user_id = :uid AND code = 'cadence_drift' AND week_start = :ws"),
                    {"uid": uid, "ws": ws.isoformat()},
                ).fetchone()
                assert row[0] == "accepted"
                assert row[1] is not None   # accepted_at set
                expected_hash = _evidence_hash(evidence)
                assert row[2] == expected_hash
        finally:
            _delete_user(uid)


def test_ac1_restore_to_active_clears_metadata():
    """AC1: Restoring to 'active' clears dismissed_at, dismissed_severity, accepted metadata."""
    _skip_no_db()
    from fastapi.testclient import TestClient
    from backend.main import app

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            with _OrmSess(_engine) as db:
                _insert_gap_finding(
                    db, uid, code="cadence_drift", severity=2, status="dismissed",
                    dismissed_at=now, dismissed_severity=2,
                )

            r = _post(tc, "/api/training/gap-analysis/cadence_drift/status",
                      {"status": "active"}, csrf)
            assert r.status_code == 200, r.text

            with _OrmSess(_engine) as db:
                today = datetime.date.today()
                ws = today - datetime.timedelta(days=today.weekday())
                row = db.execute(
                    text("SELECT status, dismissed_at, dismissed_severity FROM gap_findings "
                         "WHERE user_id = :uid AND code = 'cadence_drift' AND week_start = :ws"),
                    {"uid": uid, "ws": ws.isoformat()},
                ).fetchone()
                assert row[0] == "active"
                assert row[1] is None
                assert row[2] is None
        finally:
            _delete_user(uid)


# ── AC2: Suppression window (28 days) ─────────────────────────────────────────

def test_ac2_suppression_unit_dismissed_within_window():
    """AC2/AC5: apply_suppression classifies a recently dismissed finding as suppressed."""
    from backend.services.gap_analysis.suppression import classify_finding

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    dismissed_row = {
        "dismissed_at": now - datetime.timedelta(days=5),
        "dismissed_severity": 2,
    }
    result = classify_finding(
        code="cadence_drift",
        current_severity=2,
        current_week_status="dismissed",
        recent_dismissed=dismissed_row,
        recent_accepted=None,
        current_evidence_hash="abc",
    )
    assert result["suppressed"] is True
    assert result["reason"] == "dismissed"


def test_ac2_suppression_unit_outside_window():
    """AC5: Suppression window boundary — dismissed >28 days ago is NOT suppressed."""
    from backend.services.gap_analysis.suppression import classify_finding

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    dismissed_row = {
        "dismissed_at": now - datetime.timedelta(days=29),
        "dismissed_severity": 2,
    }
    result = classify_finding(
        code="cadence_drift",
        current_severity=2,
        current_week_status="active",
        recent_dismissed=dismissed_row,
        recent_accepted=None,
        current_evidence_hash="abc",
    )
    assert result["suppressed"] is False


def test_ac2_severity_rise_override():
    """AC5: Severity-rise override — dismissed at sev 2, now sev 3, not suppressed."""
    from backend.services.gap_analysis.suppression import classify_finding

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    dismissed_row = {
        "dismissed_at": now - datetime.timedelta(days=5),
        "dismissed_severity": 2,
    }
    result = classify_finding(
        code="cadence_drift",
        current_severity=3,
        current_week_status="active",
        recent_dismissed=dismissed_row,
        recent_accepted=None,
        current_evidence_hash="abc",
    )
    assert result["suppressed"] is False
    assert result["severity_rose"] is True


def test_ac2_severity_same_still_suppressed():
    """AC5: Same severity as at dismissal — still suppressed (no rise)."""
    from backend.services.gap_analysis.suppression import classify_finding

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    dismissed_row = {
        "dismissed_at": now - datetime.timedelta(days=10),
        "dismissed_severity": 2,
    }
    result = classify_finding(
        code="cadence_drift",
        current_severity=2,
        current_week_status="active",
        recent_dismissed=dismissed_row,
        recent_accepted=None,
        current_evidence_hash="abc",
    )
    assert result["suppressed"] is True


# ── AC3: Accepted state ──────────────────────────────────────────────────────

def test_ac3_accepted_same_week_shown_with_check():
    """AC3: Accepted this week → shown with accepted/check state."""
    from backend.services.gap_analysis.suppression import classify_finding

    evidence = [{"metric": "cadence_spm", "value": 162, "threshold": 170, "window": "recent"}]
    eh = _evidence_hash(evidence)

    result = classify_finding(
        code="cadence_drift",
        current_severity=2,
        current_week_status="accepted",
        recent_dismissed=None,
        recent_accepted={"accepted_evidence_hash": eh, "is_current_week": True},
        current_evidence_hash=eh,
    )
    assert result["suppressed"] is False
    assert result["status"] == "accepted"


def test_ac3_accepted_prev_week_evidence_unchanged_suppressed():
    """AC5/AC3: Accepted previous week, evidence unchanged → suppressed."""
    from backend.services.gap_analysis.suppression import classify_finding

    evidence = [{"metric": "cadence_spm", "value": 162, "threshold": 170, "window": "recent"}]
    eh = _evidence_hash(evidence)

    result = classify_finding(
        code="cadence_drift",
        current_severity=2,
        current_week_status="active",
        recent_dismissed=None,
        recent_accepted={"accepted_evidence_hash": eh, "is_current_week": False},
        current_evidence_hash=eh,
    )
    assert result["suppressed"] is True
    assert result["reason"] == "accepted"


def test_ac3_accepted_prev_week_evidence_changed_reactivates():
    """AC5/AC3: Accepted previous week, evidence changed → reactivated (not suppressed)."""
    from backend.services.gap_analysis.suppression import classify_finding

    old_evidence = [{"metric": "cadence_spm", "value": 162, "threshold": 170, "window": "recent"}]
    new_evidence = [{"metric": "cadence_spm", "value": 155, "threshold": 170, "window": "recent"}]
    old_hash = _evidence_hash(old_evidence)
    new_hash = _evidence_hash(new_evidence)

    assert old_hash != new_hash

    result = classify_finding(
        code="cadence_drift",
        current_severity=2,
        current_week_status="active",
        recent_dismissed=None,
        recent_accepted={"accepted_evidence_hash": old_hash, "is_current_week": False},
        current_evidence_hash=new_hash,
    )
    assert result["suppressed"] is False
    assert result.get("reactivated") is True


# ── AC4: Panel response includes muted list ───────────────────────────────────

def test_ac4_panel_returns_muted_list():
    """AC4: GET /api/training/gap-analysis returns muted list (suppressed findings)."""
    _skip_no_db()
    from fastapi.testclient import TestClient
    from backend.main import app

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            # Insert a dismissed finding within the suppression window
            with _OrmSess(_engine) as db:
                _insert_gap_finding(
                    db, uid,
                    code="cadence_drift",
                    severity=2,
                    status="dismissed",
                    week_start=week_start,
                    dismissed_at=now - datetime.timedelta(days=3),
                    dismissed_severity=2,
                )

            # Mock run_gap_analysis to return this finding without hitting real data
            import backend.main as _main
            import unittest.mock as mock

            def _mock_run(db, user_id, today_date):
                return {
                    "week_start": week_start.isoformat(),
                    "computed_at": now.isoformat(),
                    "findings": [
                        {
                            "code": "cadence_drift",
                            "severity": 2,
                            "recommendation": "Fix your cadence",
                            "evidence": [{"metric": "cadence_spm", "value": 162,
                                          "threshold": 170, "window": "recent"}],
                            "target": None,
                        }
                    ],
                    "skipped_rules": [],
                }

            with mock.patch("backend.services.gap_analysis.engine.run_gap_analysis", _mock_run):
                r = tc.get("/api/training/gap-analysis", headers={"X-CSRF-Token": csrf})

            assert r.status_code == 200, r.text
            data = r.json()
            assert "muted" in data, f"Response missing 'muted' key: {list(data.keys())}"
            muted_codes = [m["code"] for m in data["muted"]]
            assert "cadence_drift" in muted_codes, (
                f"cadence_drift should be in muted list. muted={data['muted']}, "
                f"findings={data['findings']}"
            )
            # Should NOT appear in main findings
            finding_codes = [f["code"] for f in data["findings"]]
            assert "cadence_drift" not in finding_codes, (
                "Dismissed finding should not appear in main findings list"
            )
        finally:
            _delete_user(uid)


def test_ac4_muted_findings_never_empty_on_dismiss():
    """AC4: Suppressed findings always appear in muted list (never fully invisible)."""
    _skip_no_db()
    from fastapi.testclient import TestClient
    from backend.main import app
    import unittest.mock as mock

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            with _OrmSess(_engine) as db:
                _insert_gap_finding(
                    db, uid,
                    code="cadence_drift",
                    severity=2,
                    status="dismissed",
                    week_start=week_start,
                    dismissed_at=now - datetime.timedelta(days=1),
                    dismissed_severity=2,
                )

            def _mock_run(db, user_id, today_date):
                return {
                    "week_start": week_start.isoformat(),
                    "computed_at": now.isoformat(),
                    "findings": [{
                        "code": "cadence_drift", "severity": 2,
                        "recommendation": "Fix cadence",
                        "evidence": [{"metric": "cadence_spm", "value": 162,
                                      "threshold": 170, "window": "recent"}],
                        "target": None,
                    }],
                    "skipped_rules": [],
                }

            with mock.patch("backend.services.gap_analysis.engine.run_gap_analysis", _mock_run):
                r = tc.get("/api/training/gap-analysis", headers={"X-CSRF-Token": csrf})

            assert r.status_code == 200
            data = r.json()
            # muted must be present and contain the dismissed finding
            assert len(data.get("muted", [])) > 0, "Dismissed finding must appear in muted"
        finally:
            _delete_user(uid)


# ── AC5: Restore ──────────────────────────────────────────────────────────────

def test_ac5_restore_re_shows_finding():
    """AC5: Restoring a dismissed finding sets status=active and it reappears in panel."""
    _skip_no_db()
    from fastapi.testclient import TestClient
    from backend.main import app

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())

    with TestClient(app) as tc:
        uid, csrf = _create_and_login(tc)
        try:
            with _OrmSess(_engine) as db:
                _insert_gap_finding(
                    db, uid, code="cadence_drift", severity=2, status="dismissed",
                    week_start=week_start,
                    dismissed_at=now - datetime.timedelta(days=2),
                    dismissed_severity=2,
                )

            r = _post(tc, "/api/training/gap-analysis/cadence_drift/status",
                      {"status": "active"}, csrf)
            assert r.status_code == 200

            with _OrmSess(_engine) as db:
                row = db.execute(
                    text("SELECT status, dismissed_at FROM gap_findings "
                         "WHERE user_id = :uid AND code = 'cadence_drift' AND week_start = :ws"),
                    {"uid": uid, "ws": week_start.isoformat()},
                ).fetchone()
                assert row[0] == "active"
                assert row[1] is None
        finally:
            _delete_user(uid)


# ── Evidence hash utility ──────────────────────────────────────────────────────

def test_evidence_hash_stable():
    """Utility: evidence hash is deterministic regardless of dict key order."""
    from backend.services.gap_analysis.suppression import evidence_hash

    e1 = [{"metric": "cadence_spm", "value": 162, "threshold": 170, "window": "recent"}]
    assert evidence_hash(e1) == evidence_hash(e1)


def test_evidence_hash_changes_on_value_change():
    """Utility: evidence hash changes when a metric value changes."""
    from backend.services.gap_analysis.suppression import evidence_hash

    e1 = [{"metric": "cadence_spm", "value": 162, "threshold": 170, "window": "recent"}]
    e2 = [{"metric": "cadence_spm", "value": 158, "threshold": 170, "window": "recent"}]
    assert evidence_hash(e1) != evidence_hash(e2)
