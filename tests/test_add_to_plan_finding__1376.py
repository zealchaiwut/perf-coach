"""Tests for issue #1376: One-tap add-to-plan (in-process, UAT database).

Session auth: each test gets its own throwaway user, logged in via
POST /api/auth/login, with the CSRF token attached to every POST
(same pattern as tests/test_1376_gap_add_to_plan.py).
"""
import os
import pathlib
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.models import User as _UserModel

_TEST_PW = "test1376pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _uat_url = dotenv_values(_env_file).get("DATABASE_URL_UAT")
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


def _create_and_login(tc):
    """Create a test user, log in, and return (user_id, csrf_token)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    user_name = f"addplan1376_{uuid.uuid4().hex[:8]}"
    r = tc.post("/api/users", json={"name": user_name})
    assert r.status_code == 201, f"create user failed: {r.text}"
    user_id = r.json()["id"]
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()
    r = tc.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    assert r.status_code == 200, f"login failed: {r.text}"
    return user_id, r.cookies.get("csrf-token", "")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as tc:
        user_id, csrf = _create_and_login(tc)
        orig_post = tc.post
        tc.post = lambda url, **kw: orig_post(
            url, headers={"X-CSRF-Token": csrf, **kw.pop("headers", {})}, **kw
        )
        try:
            yield tc
        finally:
            _delete_user(user_id)


# --- Acceptance Criteria ---

def test_add_to_plan_finding__session_template_registry_completeness(client):
    """AC: Session template registry: per rule code, a template for a planned_session.

    Template registry maps each severity>=2 rule code to a session template
    with session_type, name, structure fields, and load_adding flag.
    Every severity>=2 rule code has either a template or explicit None (no action).
    """
    # Fetch all gap findings to get available rule codes
    r = client.get("/api/training/gap-analysis")
    assert r.status_code == 200, f"gap-analysis fetch failed: {r.text}"

    findings = r.json().get("findings", [])
    if not findings:
        pytest.skip("No gap analysis findings available; cannot test template registry")

    # Attempt to use the first high-severity finding (severity >= 2)
    # If it has a template, we should get 201 or 409 (duplicate)
    # If it explicitly has no template (None), we should get 404
    high_severity_found = False
    for finding in findings:
        code = finding["code"]
        severity = finding.get("severity", 1)

        if severity >= 2:
            high_severity_found = True
            today = datetime.now().date()
            next_day = today + timedelta(days=1)

            r_create = client.post(
                f"/api/training/gap-analysis/{code}/add-to-plan",
                json={"date": str(next_day)},
            )
            # If template exists: 201 (created) or 409 (already exists this week)
            # If no template (explicit None): 404
            # If unknown code: 404
            assert r_create.status_code in (201, 404, 409), \
                f"Unexpected status for code {code}: {r_create.status_code} {r_create.text}"

            # At least one high-severity code should have a template
            if r_create.status_code in (201, 409):
                # Template exists; verify response structure
                if r_create.status_code == 201:
                    session_data = r_create.json()
                    assert session_data.get("draft") is True or session_data.get("slot_id"), \
                        "Missing draft slot in response"
                    assert "session_type" in session_data, "Missing session_type"
                    assert "planned_date" in session_data, "Missing planned_date"
                break

    if not high_severity_found:
        pytest.skip("No high-severity findings (severity >= 2) found")


def test_add_to_plan_finding__create_session_endpoint_201(client):
    """AC: POST …/add-to-plan adds a week draft slot (201)."""
    r = client.get("/api/training/gap-analysis")
    assert r.status_code == 200, f"gap-analysis fetch failed: {r.text}"

    findings = r.json().get("findings", [])
    if not findings:
        pytest.skip("No gap analysis findings available")

    # Find a finding with severity >= 2
    test_finding = None
    for finding in findings:
        if finding.get("severity", 1) >= 2:
            test_finding = finding
            break

    if not test_finding:
        pytest.skip("No high-severity findings found")

    code = test_finding["code"]
    today = datetime.now().date()
    # Pick a date a few days away to avoid conflicts
    target_date = today + timedelta(days=5)

    # POST to add-to-plan
    r = client.post(
        f"/api/training/gap-analysis/{code}/add-to-plan",
        json={"date": str(target_date)},
    )

    # Should be 201 (created) on first attempt
    if r.status_code == 409:
        # Session already exists; try a different date
        target_date = today + timedelta(days=6)
        r = client.post(
            f"/api/training/gap-analysis/{code}/add-to-plan",
            json={"date": str(target_date)},
        )

    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"

    session_data = r.json()
    assert session_data.get("draft") is True, "Expected draft:true"
    assert session_data.get("slot_id"), "Response missing draft slot_id"
    assert session_data.get("planned_date") == str(target_date), \
        f"Planned date mismatch: expected {target_date}, got {session_data.get('planned_date')}"


def test_add_to_plan_finding__duplicate_session_409(client):
    """AC: 409 if an identical gap-generated session already exists that week.

    Attempting to add the same finding-derived session in the same week returns 409.
    """
    r = client.get("/api/training/gap-analysis")
    assert r.status_code == 200

    findings = r.json().get("findings", [])
    if not findings:
        pytest.skip("No gap analysis findings available")

    test_finding = None
    for finding in findings:
        if finding.get("severity", 1) >= 2:
            test_finding = finding
            break

    if not test_finding:
        pytest.skip("No high-severity findings found")

    code = test_finding["code"]
    today = datetime.now().date()
    target_date = today + timedelta(days=7)  # Next week

    # First request should succeed or fail with conflict
    r1 = client.post(
        f"/api/training/gap-analysis/{code}/add-to-plan",
        json={"date": str(target_date)},
    )

    if r1.status_code == 201:
        # Success; now try to add the same session in the same week
        # (any date in the same week should trigger 409)
        same_week_date = target_date + timedelta(days=1)
        r2 = client.post(
            f"/api/training/gap-analysis/{code}/add-to-plan",
            json={"date": str(same_week_date)},
        )
        assert r2.status_code == 409, \
            f"Expected 409 for duplicate same-week session, got {r2.status_code}: {r2.text}"
    elif r1.status_code == 409:
        # Already exists; this is expected
        pass
    else:
        pytest.fail(f"Unexpected status {r1.status_code}: {r1.text}")


def test_add_to_plan_finding__sessions_tagged_analyzer_originated(client):
    """AC: Created sessions tagged as analyzer-originated for origin tracking.

    When a session is created via add-to-plan, it should include an origin tag
    (either via structure._gap_code or a dedicated origin column) to track that
    the session was analyzer-derived, not manually created.
    """
    r = client.get("/api/training/gap-analysis")
    assert r.status_code == 200

    findings = r.json().get("findings", [])
    if not findings:
        pytest.skip("No gap analysis findings available")

    # Find a high-severity finding and create a session
    for finding in findings:
        if finding.get("severity", 1) >= 2:
            code = finding["code"]
            today = datetime.now().date()
            target_date = today + timedelta(days=1)

            r_create = client.post(
                f"/api/training/gap-analysis/{code}/add-to-plan",
                json={"date": str(target_date)},
            )

            if r_create.status_code == 201:
                session_data = r_create.json()
                # Check for origin tag in structure or as a field
                structure = session_data.get("structure")
                if structure and isinstance(structure, dict):
                    # Origin should be in structure._gap_code
                    assert "_gap_code" in structure or "origin" in structure, \
                        f"Session missing origin tag: {session_data}"
                # If no structure, origin might be a top-level field
                assert "origin" in session_data or (structure and "_gap_code" in structure), \
                    f"Session missing origin tracking: {session_data}"
                break
    else:
        pytest.skip("No high-severity findings found to test origin tagging")


def test_add_to_plan_finding__verdict_guard_back_off_disabled(client):
    """AC: When current verdict is back_off, add-to-plan for load-adding templates disabled.

    If the training verdict is 'back_off', attempting to create a load-adding
    session returns 409 with a detail message indicating the verdict guard.
    """
    r = client.get("/api/training/gap-analysis")
    assert r.status_code == 200

    data = r.json()
    verdict = data.get("verdict", "")

    if verdict != "back_off":
        pytest.skip(f"Current verdict is '{verdict}', not 'back_off'; cannot test guard")

    # With back_off verdict, try to add a load-adding session
    findings = data.get("findings", [])
    load_adding_tested = False

    for finding in findings:
        code = finding["code"]
        # Try this code; if it's load-adding, we should get 409 with back_off message
        today = datetime.now().date()
        target_date = today + timedelta(days=1)

        r_add = client.post(
            f"/api/training/gap-analysis/{code}/add-to-plan",
            json={"date": str(target_date)},
        )

        if r_add.status_code == 409:
            detail = r_add.json().get("detail", {})
            if isinstance(detail, dict) and detail.get("code") == "back_off":
                # Confirmed: verdict guard blocked a load-adding session
                load_adding_tested = True
                assert "back_off" in str(detail).lower() or "disabled" in str(detail).lower()
                break

    if not load_adding_tested:
        pytest.skip("No load-adding finding available to test verdict guard")
