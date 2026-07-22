"""Tests for issue #1376: gap-analysis add-to-plan endpoint.

AC coverage:
- AC1: Template registry completeness — every severity>=2 rule code has a template or
       explicit None; no KeyError for any known code.
- AC2: POST /api/training/gap-analysis/{code}/add-to-plan creates a planned session;
       409 if an identical gap-generated session exists that week.
- AC3: Created sessions are tagged as analyzer-originated (structure._gap_code).
- AC5: Verdict guard — 409 with back_off detail when verdict is back_off and template
       is load-adding.
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
from backend.models import PlannedSession, User as _UserModel
from backend.services.gap_analysis.templates import get_template, is_load_adding

_TEST_PW = "test1376pw!"

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


def _tc_create_and_login(tc):
    """Create a test user, log in, and return (user_id, csrf_token)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    user_name = f"gap1376_{uuid.uuid4().hex[:8]}"
    r = tc.post("/api/users", json={"name": user_name})
    assert r.status_code == 201, f"create user failed: {r.text}"
    user_id = r.json()["id"]
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()
    r = tc.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    assert r.status_code == 200, f"login failed: {r.text}"
    csrf_token = r.cookies.get("csrf-token", "")
    return user_id, csrf_token


# ── AC1: Template registry completeness ──────────────────────────────────────

# All severity>=2 rule codes that exist in the gap-analysis rule files.
# Any new rule added in the future must be reflected here.
_SEVERITY_GE2_EXACT_CODES = [
    "plyo_deficit",          # sev 2
    "gct_lengthening",       # sev 2
    "aerobic_durability_gap",# sev 2
    "speed_neglected",       # sev 2
    "undertrained_area_under_ramp",  # sev 2
    "recurrent_niggle_area", # sev 3
    "intensity_too_hard",    # sev 2
]

_SEVERITY_GE2_PREFIX_CODES = [
    "muscle_overused.calf",     # sev 2 or 3
    "muscle_untrained.calf",    # sev 2
    "muscle_untrained.hamstring",
    "muscle_untrained.glute",
]


def test_ac1_severity_ge2_exact_codes_have_template_or_none():
    """AC1: Every known severity>=2 exact code resolves without KeyError."""
    for code in _SEVERITY_GE2_EXACT_CODES:
        try:
            result = get_template(code)
            # result is a dict or None — both are valid
            assert result is None or isinstance(result, dict), (
                f"code={code!r}: expected dict or None, got {type(result)}"
            )
        except KeyError:
            pytest.fail(f"get_template({code!r}) raised KeyError — must return dict or None")


def test_ac1_severity_ge2_prefix_codes_have_template_or_none():
    """AC1: Dynamic prefix codes (muscle_overused.*, muscle_untrained.*) resolve without KeyError."""
    for code in _SEVERITY_GE2_PREFIX_CODES:
        try:
            result = get_template(code)
            assert result is None or isinstance(result, dict), (
                f"code={code!r}: expected dict or None, got {type(result)}"
            )
        except KeyError:
            pytest.fail(f"get_template({code!r}) raised KeyError — must return dict or None")


def test_ac1_unknown_code_raises_key_error():
    """AC1 / error guard: get_template raises KeyError for unrecognised codes."""
    with pytest.raises(KeyError):
        get_template("completely_unknown_xyz_code")


def test_ac1_load_adding_templates_are_flagged():
    """AC1: All non-None templates that add training load have load_adding=True."""
    load_adding_codes = [
        "plyo_deficit", "no_recent_plyo", "gct_lengthening", "cadence_drift",
        "aerobic_durability_gap", "speed_neglected", "strength_lapsed",
        "undertrained_area_under_ramp",
        "muscle_untrained.calf",
        "muscle_detraining.hamstring",
    ]
    for code in load_adding_codes:
        assert is_load_adding(code), f"Expected {code!r} to be load-adding"


def test_ac1_reduction_codes_not_load_adding():
    """AC1: Overuse and reduction codes return None (not load-adding)."""
    non_load_codes = [
        "intensity_too_hard", "recurrent_niggle_area",
        "muscle_overused.calf", "muscle_overused.hamstring",
    ]
    for code in non_load_codes:
        tmpl = get_template(code)
        assert tmpl is None, f"Expected {code!r} to return None (no load-adding action)"


def test_ac1_template_required_fields():
    """AC1: Every non-None template has session_type, name, notes, load_adding."""
    for code in ["plyo_deficit", "gct_lengthening", "aerobic_durability_gap",
                 "speed_neglected", "strength_lapsed", "muscle_untrained.calf"]:
        tmpl = get_template(code)
        assert tmpl is not None, f"{code!r} should have a template"
        for field in ("session_type", "name", "notes", "load_adding"):
            assert field in tmpl, f"{code!r} template missing field {field!r}"


# ── AC2: Endpoint create + 409 ────────────────────────────────────────────────

def test_ac2_endpoint_401_anonymous():
    """AC2: POST without auth returns 401."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as tc:
        r = tc.post(
            "/api/training/gap-analysis/plyo_deficit/add-to-plan",
            json={"date": "2026-07-17"},
        )
    assert r.status_code == 401


def _csrf_post(tc, url, json_body, csrf_token):
    """POST with CSRF token header."""
    return tc.post(url, json=json_body, headers={"X-CSRF-Token": csrf_token})


def test_ac2_endpoint_404_for_unknown_code():
    """AC2: Unknown rule code returns 404."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as tc:
        user_id, csrf = _tc_create_and_login(tc)
        try:
            r = _csrf_post(tc, "/api/training/gap-analysis/nonexistent_rule_xyz/add-to-plan",
                           {"date": "2026-07-17"}, csrf)
            assert r.status_code == 404, r.text
        finally:
            _delete_user(user_id)


def test_ac2_endpoint_404_for_no_template_code():
    """AC2: A known code with no template (intensity_too_hard) returns 404."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as tc:
        user_id, csrf = _tc_create_and_login(tc)
        try:
            r = _csrf_post(tc, "/api/training/gap-analysis/intensity_too_hard/add-to-plan",
                           {"date": "2026-07-17"}, csrf)
            assert r.status_code == 404, r.text
        finally:
            _delete_user(user_id)


def test_ac2_create_planned_session():
    """AC2: Valid request adds a draft slot and returns it (201)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app

    target_date = "2026-07-17"

    with TestClient(app) as tc:
        user_id, csrf = _tc_create_and_login(tc)
        try:
            r = _csrf_post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                           {"date": target_date}, csrf)
            assert r.status_code == 201, r.text
            data = r.json()
            assert data["planned_date"] == target_date
            assert data["session_type"] == "plyo"
            assert data.get("draft") is True
            assert data.get("slot_id")
        finally:
            _delete_user(user_id)


def test_ac3_created_session_tagged_with_origin():
    """AC3: Draft session has _gap_code set in structure (origin tag)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app

    target_date = "2026-07-17"

    with TestClient(app) as tc:
        user_id, csrf = _tc_create_and_login(tc)
        try:
            r = _csrf_post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                           {"date": target_date}, csrf)
            assert r.status_code == 201, r.text
            data = r.json()
            structure = data.get("structure") or (data.get("session") or {}).get("structure") or {}
            assert structure.get("_gap_code") == "plyo_deficit" or data.get("session", {}).get("_gap_code") == "plyo_deficit", (
                f"Expected _gap_code='plyo_deficit', got data={data!r}"
            )
        finally:
            _delete_user(user_id)


def test_ac2_409_duplicate_same_week():
    """AC2: Adding the same gap session twice in the same week returns 409."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app

    target_date = "2026-07-17"

    with TestClient(app) as tc:
        user_id, csrf = _tc_create_and_login(tc)
        try:
            r1 = _csrf_post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                            {"date": target_date}, csrf)
            assert r1.status_code == 201, r1.text

            # Same code, same week (different day) → 409
            r2 = _csrf_post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                            {"date": "2026-07-18"}, csrf)  # same week as 2026-07-17 (Mon)
            assert r2.status_code == 409, r2.text
            detail = r2.json().get("detail") or {}
            assert detail.get("code") == "already_planned_this_week"
        finally:
            _delete_user(user_id)


def test_upgrade_hollow_stub_same_week():
    """Existing planned gap session still blocks (draft path does not upgrade stubs)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    import uuid as _uuid
    from datetime import date as _date
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.models import PlannedSession as _PS

    with TestClient(app) as tc:
        user_id, csrf = _tc_create_and_login(tc)
        try:
            with _OrmSess(_engine) as db:
                row = _PS(
                    user_id=_uuid.UUID(user_id),
                    planned_date=_date(2026, 7, 21),
                    session_type="run",
                    name="Aerobic long run",
                    notes="stub",
                    structure={"_gap_code": "aerobic_durability_gap"},
                    status="planned",
                )
                db.add(row)
                db.commit()

            r = _csrf_post(
                tc,
                "/api/training/gap-analysis/aerobic_durability_gap/add-to-plan",
                {"date": "2026-07-23"},
                csrf,
            )
            assert r.status_code == 409, r.text
            detail = r.json().get("detail") or {}
            assert detail.get("code") == "already_planned_this_week"
        finally:
            _delete_user(user_id)


def test_ac2_different_code_same_week_allowed():
    """AC2: Two different gap codes in the same week are both allowed (no false 409)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as tc:
        user_id, csrf = _tc_create_and_login(tc)
        try:
            r1 = _csrf_post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                            {"date": "2026-07-17"}, csrf)
            assert r1.status_code == 201, r1.text

            r2 = _csrf_post(tc, "/api/training/gap-analysis/aerobic_durability_gap/add-to-plan",
                            {"date": "2026-07-18"}, csrf)
            assert r2.status_code == 201, r2.text
        finally:
            _delete_user(user_id)


# ── AC5: Verdict guard ───────────────────────────────────────────────────────

def test_ac5_verdict_guard_endpoint_rejects_when_back_off(monkeypatch):
    """AC5: When training verdict is back_off, load-adding add-to-plan returns 409."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as _main_mod

    monkeypatch.setattr(
        _main_mod, "_gap_get_verdict_for_user",
        lambda user_id, today: "back_off",
    )

    with TestClient(app) as tc:
        user_id, csrf = _tc_create_and_login(tc)
        try:
            r = _csrf_post(tc, "/api/training/gap-analysis/plyo_deficit/add-to-plan",
                           {"date": "2026-07-17"}, csrf)
            assert r.status_code == 409, r.text
            detail = r.json().get("detail", "")
            assert "back_off" in str(detail).lower(), (
                f"Expected 'back_off' in detail, got: {detail!r}"
            )
        finally:
            _delete_user(user_id)


def test_ac5_verdict_guard_client_flag_is_load_adding():
    """AC5: is_load_adding returns False for reduction codes (no guard trigger)."""
    assert not is_load_adding("recurrent_niggle_area")
    assert not is_load_adding("intensity_too_hard")
    assert not is_load_adding("muscle_overused.calf")
    # Unknown code → False
    assert not is_load_adding("unknown_code_xyz")
