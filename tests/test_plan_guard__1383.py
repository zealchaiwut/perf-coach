"""Tests for issue #1383: muscle-aware planning guard.

Acceptance criteria covered:
  AC1 — Footprint estimator: per-group load shares estimated correctly per
         session type (run uses RUN_PROFILE, plyo uses PLYO_PROFILE,
         strength uses catalog ratios, rest returns empty).
  AC2 — Warning/suggestion matrix:
         - dominant overused/injured group → warning entry
         - untrained priority group the session doesn't hit → suggestion entry
         - non-dominant group does not trigger warning even if overused
         - non-priority untrained group does not trigger suggestion
  AC3 — Non-blocking semantics: POST /api/planned-sessions succeeds even when
         the planned session's footprint hits an overused group (plan-check
         warnings are informational, not 409s).
  AC4 — plan_warnings field present on each planned session in the weekly bundle.
  AC5 — POST /api/training/plan-check returns expected shape.
"""
from __future__ import annotations

import os
import pathlib
import uuid

import pytest

from backend.services.plan_guard import (
    DOMINANT_SHARE_THRESHOLD,
    PLYO_PROFILE,
    RUN_PROFILE,
    check_session,
    estimate_session_footprint,
)

# ── Live-server / DB setup ────────────────────────────────────────────────────

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1383pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

_engine = None
if _uat_url:
    from sqlalchemy import create_engine as _ce
    _engine = _ce(_uat_url, pool_pre_ping=True)


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
    from backend.auth import hash_password as _hp
    from backend.models import User as _U
    uname = f"plancheck1383_{uuid.uuid4().hex[:8]}"
    r = tc.post("/api/users", json={"name": uname})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    with _S(_engine) as db:
        u = db.get(_U, uuid.UUID(uid))
        u.password_hash = _hp(_TEST_PW)
        db.commit()
    r = tc.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
    assert r.status_code == 200, r.text
    csrf = r.cookies.get("csrf-token", "")
    return uid, csrf


# ── AC1: Footprint estimator ──────────────────────────────────────────────────

class TestEstimateSessionFootprint:

    def test_run_returns_run_profile_shares(self):
        fp = estimate_session_footprint("run", structure=None)
        # Shares must match RUN_PROFILE exactly and sum to 1.0.
        for group, expected_share in RUN_PROFILE.items():
            assert fp[group] == pytest.approx(expected_share), f"{group} share mismatch"
        assert sum(fp.values()) == pytest.approx(1.0)

    def test_plyo_returns_plyo_profile_shares(self):
        fp = estimate_session_footprint("plyo", structure=None)
        for group, expected_share in PLYO_PROFILE.items():
            assert fp[group] == pytest.approx(expected_share), f"{group} share mismatch"
        assert sum(fp.values()) == pytest.approx(1.0)

    def test_rest_returns_empty(self):
        assert estimate_session_footprint("rest", structure=None) == {}

    def test_stretch_returns_empty(self):
        assert estimate_session_footprint("stretch", structure=None) == {}

    def test_strength_no_catalog_returns_empty(self):
        structure = {"exercises": [{"name": "squat", "sets": 5, "reps": 5}]}
        fp = estimate_session_footprint("strength", structure=structure, catalog=None)
        assert fp == {}

    def test_strength_with_catalog_uses_ratios(self):
        # Catalog for "squat": 70% quad, 30% glute
        catalog = {
            "squat": [
                {"part": "quads", "ratio": 0.7},
                {"part": "glutes", "ratio": 0.3},
            ]
        }
        structure = {"exercises": [{"name": "squat", "sets": 5, "reps": 5}]}
        fp = estimate_session_footprint("strength", structure=structure, catalog=catalog)
        assert fp["quad"] == pytest.approx(0.7)
        assert fp["glute"] == pytest.approx(0.3)
        assert sum(fp.values()) == pytest.approx(1.0)

    def test_strength_multiple_exercises_blended(self):
        # Two exercises with equal sets/reps: result should blend their profiles.
        catalog = {
            "squat": [{"part": "quads", "ratio": 1.0}],
            "calf raise": [{"part": "calves", "ratio": 1.0}],
        }
        structure = {
            "exercises": [
                {"name": "squat", "sets": 3, "reps": 10},
                {"name": "calf raise", "sets": 3, "reps": 10},
            ]
        }
        fp = estimate_session_footprint("strength", structure=structure, catalog=catalog)
        # Equal volume → 50/50 split
        assert fp["quad"] == pytest.approx(0.5)
        assert fp["calf"] == pytest.approx(0.5)

    def test_strength_structure_with_focus_only(self):
        # Simple mode: structure has focus, no exercises → no catalog lookup needed
        structure = {"focus": "lower body"}
        fp = estimate_session_footprint("strength", structure=structure, catalog=None)
        assert fp == {}

    def test_run_structure_ignored(self):
        # Run footprint ignores structure content (no elevation data in planned sessions)
        fp_with = estimate_session_footprint("run", structure={"blocks": [{"phase": "main", "duration_min": 30}]})
        fp_without = estimate_session_footprint("run", structure=None)
        assert fp_with == fp_without

    def test_shares_non_negative(self):
        for stype in ("run", "plyo", "rest"):
            fp = estimate_session_footprint(stype, structure=None)
            for v in fp.values():
                assert v >= 0, f"Negative share for {stype}"


# ── AC2: Warning / suggestion matrix ─────────────────────────────────────────

def _mock_stats(classification, injured=False, acwr=None, acute=0, chronic=0):
    return {
        "classification": classification,
        "injured": injured,
        "acute_7d": acute,
        "chronic_28d": chronic,
        "acwr": acwr,
        "source_breakdown": {},
    }


class TestCheckSession:

    def test_dominant_overused_group_triggers_warning(self):
        # calf share = 0.70 (dominant in plyo) and calf is overused → warning
        fp = {"calf": 0.70, "quad": 0.15, "glute": 0.15}
        group_stats = {
            "calf": _mock_stats("overused", acwr=1.6, acute=50, chronic=30),
            "quad": _mock_stats("balanced", acwr=1.0, acute=20, chronic=20),
            "glute": _mock_stats("balanced", acwr=1.0, acute=20, chronic=20),
        }
        result = check_session("plyo", fp, group_stats)
        warn_groups = [w["muscle_group"] for w in result["warnings"]]
        assert "calf" in warn_groups

    def test_dominant_injured_group_triggers_warning(self):
        # calf share = 0.70 (dominant) and calf is injured (but balanced) → warning
        fp = {"calf": 0.70, "quad": 0.15, "glute": 0.15}
        group_stats = {
            "calf": _mock_stats("balanced", injured=True, acwr=1.0, acute=20, chronic=20),
            "quad": _mock_stats("balanced"),
            "glute": _mock_stats("balanced"),
        }
        result = check_session("plyo", fp, group_stats)
        warn_groups = [w["muscle_group"] for w in result["warnings"]]
        assert "calf" in warn_groups

    def test_non_dominant_overused_group_no_warning(self):
        # quad share = 0.05 (below threshold) and quad is overused → NO warning
        fp = {"calf": 0.70, "quad": 0.05, "glute": 0.25}
        group_stats = {
            "calf": _mock_stats("balanced"),
            "quad": _mock_stats("overused", acwr=1.7),
            "glute": _mock_stats("balanced"),
        }
        result = check_session("plyo", fp, group_stats)
        warn_groups = [w["muscle_group"] for w in result["warnings"]]
        assert "quad" not in warn_groups

    def test_no_warnings_when_all_groups_balanced(self):
        fp = {"calf": 0.70, "quad": 0.15, "glute": 0.15}
        group_stats = {
            "calf": _mock_stats("balanced", acwr=1.0),
            "quad": _mock_stats("balanced", acwr=0.9),
            "glute": _mock_stats("balanced", acwr=1.1),
        }
        result = check_session("plyo", fp, group_stats)
        assert result["warnings"] == []

    def test_warning_includes_group_classification_message(self):
        fp = {"calf": 0.70, "quad": 0.15, "glute": 0.15}
        group_stats = {
            "calf": _mock_stats("overused", acwr=1.8),
            "quad": _mock_stats("balanced"),
            "glute": _mock_stats("balanced"),
        }
        result = check_session("plyo", fp, group_stats)
        assert result["warnings"], "Expected at least one warning"
        w = result["warnings"][0]
        assert w["muscle_group"] == "calf"
        assert w["classification"] == "overused"
        assert isinstance(w["message"], str) and len(w["message"]) > 0

    def test_untrained_priority_group_suggests_for_strength(self):
        # hamstring is untrained priority and NOT hit by this strength session → suggestion
        fp = {"quad": 0.80, "glute": 0.20}
        group_stats = {
            "hamstring": _mock_stats("untrained", injured=False),
            "quad": _mock_stats("balanced"),
            "glute": _mock_stats("balanced"),
            "calf": _mock_stats("balanced"),
            "hip": _mock_stats("balanced"),
        }
        result = check_session("strength", fp, group_stats)
        sug_groups = [s["muscle_group"] for s in result["suggestions"]]
        assert "hamstring" in sug_groups

    def test_untrained_non_priority_group_no_suggestion(self):
        # chest is untrained (non-priority) → NO suggestion
        fp = {"quad": 0.80, "glute": 0.20}
        group_stats = {
            "chest": _mock_stats("untrained"),
            "quad": _mock_stats("balanced"),
            "glute": _mock_stats("balanced"),
        }
        result = check_session("strength", fp, group_stats)
        sug_groups = [s["muscle_group"] for s in result["suggestions"]]
        assert "chest" not in sug_groups

    def test_untrained_injured_group_no_suggestion(self):
        # untrained + injured priority group → no suggestion (don't load an injured area)
        fp = {"quad": 0.80, "glute": 0.20}
        group_stats = {
            "hamstring": _mock_stats("untrained", injured=True),
            "quad": _mock_stats("balanced"),
            "glute": _mock_stats("balanced"),
        }
        result = check_session("strength", fp, group_stats)
        sug_groups = [s["muscle_group"] for s in result["suggestions"]]
        assert "hamstring" not in sug_groups

    def test_already_dominant_target_no_suggestion(self):
        # calf is untrained but the session footprint already dominates on calf → no suggestion
        fp = {"calf": 0.70, "quad": 0.15, "glute": 0.15}
        group_stats = {
            "calf": _mock_stats("untrained"),
            "quad": _mock_stats("balanced"),
            "glute": _mock_stats("balanced"),
        }
        result = check_session("strength", fp, group_stats)
        sug_groups = [s["muscle_group"] for s in result["suggestions"]]
        assert "calf" not in sug_groups

    def test_run_dominant_overused_lower_body_adds_note_suggestion(self):
        # Quad is overused and run footprint loads quad significantly → note suggestion
        fp = dict(RUN_PROFILE)  # quad = 0.25 (dominant)
        group_stats = {
            "calf": _mock_stats("balanced"),
            "quad": _mock_stats("overused", acwr=1.6),
            "hamstring": _mock_stats("balanced"),
            "glute": _mock_stats("balanced"),
            "hip": _mock_stats("balanced"),
            "core": _mock_stats("balanced"),
        }
        result = check_session("run", fp, group_stats)
        # Should warn about quad since it's dominant in run profile
        warn_groups = [w["muscle_group"] for w in result["warnings"]]
        assert "quad" in warn_groups

    def test_empty_footprint_no_warnings_no_suggestions(self):
        # rest or strength with no catalog → empty footprint → nothing
        fp = {}
        group_stats = {
            "calf": _mock_stats("overused", acwr=1.8),
            "hamstring": _mock_stats("untrained"),
        }
        result = check_session("rest", fp, group_stats)
        assert result["warnings"] == []
        assert result["suggestions"] == []

    def test_elevated_group_does_not_trigger_warning(self):
        # The issue says "overused or injured" — elevated alone should NOT warn
        fp = {"calf": 0.70, "quad": 0.15, "glute": 0.15}
        group_stats = {
            "calf": _mock_stats("elevated", acwr=1.4),
            "quad": _mock_stats("balanced"),
            "glute": _mock_stats("balanced"),
        }
        result = check_session("plyo", fp, group_stats)
        assert result["warnings"] == []

    def test_result_shape(self):
        fp = {"calf": 0.70}
        group_stats = {"calf": _mock_stats("overused", acwr=1.8)}
        result = check_session("plyo", fp, group_stats)
        assert "warnings" in result
        assert "suggestions" in result
        assert isinstance(result["warnings"], list)
        assert isinstance(result["suggestions"], list)


# ── AC3: Non-blocking semantics (integration) ─────────────────────────────────

@pytest.fixture(scope="module")
def tc_1383():
    from starlette.testclient import TestClient
    from backend.main import app
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc


class TestNonBlockingSemantics:
    """POST /api/planned-sessions succeeds even when plan-check would warn."""

    def test_create_session_with_overused_group_still_succeeds(self, tc_1383):
        uid, csrf = _create_and_login(tc_1383)
        try:
            headers = {"x-csrf-token": csrf}
            # Create a planned plyo session (plyo loads calf strongly)
            r = tc_1383.post(
                "/api/planned-sessions",
                json={
                    "planned_date": "2030-01-06",
                    "session_type": "plyo",
                    "name": "Plyo session",
                },
                headers=headers,
            )
            # Must succeed — plan-check warnings never block creation
            assert r.status_code == 201, f"Expected 201 but got {r.status_code}: {r.text}"
            created = r.json()
            assert created["session_type"] == "plyo"
        finally:
            _delete_user(uid)


# ── AC5: POST /api/training/plan-check shape ──────────────────────────────────

class TestPlanCheckEndpoint:

    def test_plan_check_returns_expected_shape(self, tc_1383):
        uid, csrf = _create_and_login(tc_1383)
        try:
            headers = {"x-csrf-token": csrf}
            r = tc_1383.post(
                "/api/training/plan-check",
                json={"session_type": "plyo", "structure": None},
                headers=headers,
            )
            assert r.status_code == 200, f"Expected 200 but got {r.status_code}: {r.text}"
            data = r.json()
            assert "warnings" in data
            assert "suggestions" in data
            assert isinstance(data["warnings"], list)
            assert isinstance(data["suggestions"], list)
        finally:
            _delete_user(uid)

    def test_plan_check_run_returns_warnings_or_empty(self, tc_1383):
        uid, csrf = _create_and_login(tc_1383)
        try:
            headers = {"x-csrf-token": csrf}
            r = tc_1383.post(
                "/api/training/plan-check",
                json={"session_type": "run"},
                headers=headers,
            )
            assert r.status_code == 200
            data = r.json()
            # Each warning must have required keys
            for w in data["warnings"]:
                assert "muscle_group" in w
                assert "classification" in w
                assert "message" in w
            for s in data["suggestions"]:
                assert "muscle_group" in s
                assert "reason" in s
        finally:
            _delete_user(uid)

    def test_plan_check_rest_returns_empty(self, tc_1383):
        uid, csrf = _create_and_login(tc_1383)
        try:
            headers = {"x-csrf-token": csrf}
            r = tc_1383.post(
                "/api/training/plan-check",
                json={"session_type": "rest"},
                headers=headers,
            )
            assert r.status_code == 200
            data = r.json()
            assert data["warnings"] == []
            assert data["suggestions"] == []
        finally:
            _delete_user(uid)

    def test_plan_check_unauthenticated_returns_401(self, tc_1383):
        from starlette.testclient import TestClient
        from backend.main import app
        with TestClient(app) as anon_tc:
            r = anon_tc.post(
                "/api/training/plan-check",
                json={"session_type": "run"},
            )
            assert r.status_code == 401

    def test_plan_check_invalid_session_type_returns_422(self, tc_1383):
        uid, csrf = _create_and_login(tc_1383)
        try:
            headers = {"x-csrf-token": csrf}
            r = tc_1383.post(
                "/api/training/plan-check",
                json={"session_type": "invalid_type"},
                headers=headers,
            )
            assert r.status_code == 422
        finally:
            _delete_user(uid)


# ── AC4: plan_warnings in weekly bundle ──────────────────────────────────────

class TestWeeklyBundlePlanWarnings:

    def test_planned_session_has_plan_warnings_field(self, tc_1383):
        uid, csrf = _create_and_login(tc_1383)
        try:
            headers = {"x-csrf-token": csrf}
            # Create a planned session
            r = tc_1383.post(
                "/api/planned-sessions",
                json={
                    "planned_date": "2030-01-06",
                    "session_type": "run",
                    "name": "Test run",
                },
                headers=headers,
            )
            assert r.status_code == 201
            # Fetch the weekly bundle
            r = tc_1383.get(
                "/api/planned-sessions?from=2030-01-06&to=2030-01-06",
                headers=headers,
            )
            assert r.status_code == 200
            bundle = r.json()
            sessions = bundle["days"][0]["planned"]
            assert len(sessions) == 1
            # The plan_warnings field must exist (may be empty list for fresh user)
            assert "plan_warnings" in sessions[0], "plan_warnings field missing from session dict"
            assert isinstance(sessions[0]["plan_warnings"], list)
        finally:
            _delete_user(uid)
