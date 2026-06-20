"""Tests for issue #683: Expose detected session profile on full workout endpoint.

Acceptance criteria covered:
  AC1  — thin caller function is responsible for all DB access (loading splits
          and user preferences); detection logic lives in detect_session_profile
          and is not duplicated in the caller
  AC2  — caller invokes detect_session_profile ONLY when the workout record
          contains no declared builder structure; if declared structure exists,
          that structure is returned as the profile and detection is skipped
  AC3  — resolved profile (detected or declared) is attached to
          GET /api/workouts/{id}/full under the key 'detected_profile'
  AC4  — no threshold values are hardcoded in the caller; all thresholds are
          sourced from configuration or user preferences loaded at runtime
  AC5  — all numeric comparisons within the caller are in named variables or
          constants — no bare magic numbers
  AC6  — golden fixture file expected-outputs includes 'detected_profile' value
  AC7  — existing golden fixture assertions continue to pass (checked in
          test_golden_metrics__577.py; this file guards the structure)
  AC8a — unit test: workout with declared structure returns declared profile
          and does NOT call detect_session_profile
  AC8b — unit test: workout without declared structure calls
          detect_session_profile and returns its result
  AC9  — endpoint returns 404 (not 500) when the workout ID does not exist
"""

import json
import pathlib
import types
import unittest.mock as mock
import uuid

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CALLER_SRC = _ROOT / "backend" / "services" / "session_profile_caller.py"
_MAIN_SRC = _ROOT / "backend" / "main.py"
_GOLDEN_EXPECTED = _ROOT / "tests" / "fixtures" / "golden_run_expected.json"


# ── AC1: thin caller — DB access happens in the caller, not in detect ──────────


def test_ac1_caller_module_importable():
    """AC1: session_profile_caller module must exist and export get_session_profile_for_workout."""
    from backend.services.session_profile_caller import get_session_profile_for_workout
    assert callable(get_session_profile_for_workout)


def test_ac1_caller_does_not_import_session_engine():
    """AC1: caller must not import the DB engine (no direct DB access inside it)."""
    code = _CALLER_SRC.read_text()
    assert "from backend.db import" not in code, (
        "session_profile_caller must not import the DB engine — "
        "DB access is the endpoint's responsibility"
    )
    assert "from backend.models import" not in code, (
        "session_profile_caller must not import ORM models — "
        "the caller receives already-loaded objects from the endpoint"
    )


def test_ac1_caller_delegates_detection_to_detect_session_profile():
    """AC1: detection logic lives in detect_session_profile, not duplicated in the caller."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides={})
    split_rows = []
    prefs = types.SimpleNamespace(ftp_w=200, threshold_hr=None, threshold_pace_seconds_per_km=None)

    sentinel = {"phases": [], "basis": "power", "confident": True, "sentinel": True}
    with mock.patch.object(session_profile_caller, "detect_session_profile", return_value=sentinel) as m:
        result = session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)

    assert m.called, "caller must delegate detection to detect_session_profile"
    assert result is sentinel, "caller must return detect_session_profile result unchanged"


# ── AC2: precedence — declared builder structure skips detection ───────────────


def test_ac2_no_declared_structure_calls_detect():
    """AC2: when no session_profile key in manual_overrides, detect_session_profile is called."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides={})
    prefs = types.SimpleNamespace(ftp_w=200, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as m:
        m.return_value = {"phases": [], "basis": "none", "confident": False}
        session_profile_caller.get_session_profile_for_workout(workout, [], prefs)

    assert m.called, "detect_session_profile must be called when no declared builder structure"


def test_ac2_none_manual_overrides_calls_detect():
    """AC2: manual_overrides=None (missing column) also triggers detection."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides=None)
    prefs = types.SimpleNamespace(ftp_w=200, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as m:
        m.return_value = {"phases": [], "basis": "none", "confident": False}
        session_profile_caller.get_session_profile_for_workout(workout, [], prefs)

    assert m.called, "detect_session_profile must be called when manual_overrides is None"


def test_ac2_declared_structure_skips_detect():
    """AC2: when session_profile key exists in manual_overrides, detect is never called."""
    from backend.services import session_profile_caller

    declared = {"phases": [{"label": "Builder Phase"}], "confident": True, "basis": "manual"}
    workout = types.SimpleNamespace(manual_overrides={"session_profile": declared})
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as m:
        result = session_profile_caller.get_session_profile_for_workout(workout, [], prefs)

    assert not m.called, (
        "detect_session_profile must NOT be called when a declared builder structure exists"
    )
    assert result is declared, "caller must return the declared structure directly"


def test_ac2_declared_structure_wins_over_nonempty_splits():
    """AC2: declared structure takes precedence even when split_rows is non-empty."""
    from backend.services import session_profile_caller

    declared = {"phases": [{"label": "Declared"}], "confident": True}
    workout = types.SimpleNamespace(manual_overrides={"session_profile": declared})
    split_rows = [
        types.SimpleNamespace(
            avg_power=200, duration_seconds=300, distance_km=1.0, avg_hr=150, lap_type="manual"
        )
    ]
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as m:
        result = session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)

    assert not m.called
    assert result is declared


# ── AC3: detected_profile key on GET /api/workouts/{id}/full ──────────────────


def test_ac3_full_endpoint_includes_detected_profile_key():
    """AC3: GET /api/workouts/{id}/full JSONResponse must include 'detected_profile'."""
    code = _MAIN_SRC.read_text()
    func_start = code.find("def get_workout_full")
    assert func_start >= 0, "get_workout_full function must exist in main.py"
    func_body = code[func_start:func_start + 8000]
    assert '"detected_profile"' in func_body, (
        "get_workout_full JSONResponse dict must include 'detected_profile' key"
    )


def test_ac3_full_endpoint_calls_session_profile_caller():
    """AC3: main.py endpoint must call get_session_profile_for_workout (or its alias)."""
    code = _MAIN_SRC.read_text()
    has_import = "session_profile_caller" in code
    has_alias = "_get_session_profile" in code
    assert has_import or has_alias, (
        "main.py must import from session_profile_caller to get the session profile"
    )
    func_start = code.find("def get_workout_full")
    func_body = code[func_start:func_start + 8000]
    uses_caller = "_get_session_profile" in func_body or "get_session_profile_for_workout" in func_body
    assert uses_caller, (
        "get_workout_full must call the session profile caller to populate detected_profile"
    )


def test_ac3_full_endpoint_existing_keys_preserved():
    """AC3 / AC7: detected_profile must not displace any existing response keys."""
    code = _MAIN_SRC.read_text()
    func_start = code.find("def get_workout_full")
    func_body = code[func_start:func_start + 8000]
    required = [
        '"workout"', '"splits"', '"sources"', '"unified"', '"computed"',
        '"field_coverage"', '"tss"', '"tss_method"', '"tss_partial"',
        '"computed_tss"', '"detected_profile"',
    ]
    for key in required:
        assert key in func_body, (
            f"get_workout_full response must include key {key!r}"
        )


# ── AC4: no hardcoded threshold values in the caller ──────────────────────────


def test_ac4_caller_has_no_hardcoded_threshold_literals():
    """AC4: caller source must not contain numeric threshold literals."""
    code = _CALLER_SRC.read_text()
    banned = ["0.80", "0.90", "1.00", "1.06", "0.75", "0.95", "480", "2.0"]
    for literal in banned:
        assert literal not in code, (
            f"session_profile_caller.py must not hardcode threshold literal {literal!r}; "
            "all thresholds must come from user preferences or configuration"
        )


def test_ac4_caller_reads_prefs_from_object():
    """AC4: caller extracts threshold fields from the prefs object, not from constants."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides={})
    prefs = types.SimpleNamespace(ftp_w=310, threshold_hr=175, threshold_pace_seconds_per_km=280)
    captured = {}

    def fake_detect(splits, prefs_dict):
        captured["prefs"] = prefs_dict
        return {"phases": [], "basis": "power", "confident": False}

    with mock.patch.object(session_profile_caller, "detect_session_profile", side_effect=fake_detect):
        session_profile_caller.get_session_profile_for_workout(workout, [], prefs)

    assert captured["prefs"]["ftp_w"] == 310, "ftp_w must be sourced from prefs object"
    assert captured["prefs"]["threshold_hr"] == 175, "threshold_hr must be sourced from prefs object"
    assert captured["prefs"]["threshold_pace_seconds_per_km"] == 280, (
        "threshold_pace must be sourced from prefs object"
    )


# ── AC5: no bare magic numbers in the caller ──────────────────────────────────


def test_ac5_caller_has_no_bare_numeric_comparisons():
    """AC5: caller source must not contain bare numeric comparisons (magic numbers)."""
    import ast

    code = _CALLER_SRC.read_text()
    tree = ast.parse(code)
    numeric_literals_in_comparisons = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for comp in node.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, (int, float)):
                    numeric_literals_in_comparisons.append(comp.value)
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, (int, float)):
                numeric_literals_in_comparisons.append(node.left.value)
    assert numeric_literals_in_comparisons == [], (
        f"caller must not use bare numeric literals in comparisons; "
        f"found: {numeric_literals_in_comparisons}"
    )


# ── AC6: golden fixture includes detected_profile ─────────────────────────────


def test_ac6_golden_fixture_has_detected_profile():
    """AC6: golden_run_expected.json must contain a 'detected_profile' key."""
    expected = json.loads(_GOLDEN_EXPECTED.read_text())
    assert "detected_profile" in expected, (
        "golden_run_expected.json must have a 'detected_profile' entry (AC6)"
    )


def test_ac6_golden_fixture_detected_profile_has_required_fields():
    """AC6: golden detected_profile entry must have all required profile fields."""
    expected = json.loads(_GOLDEN_EXPECTED.read_text())
    profile = expected["detected_profile"]
    required_fields = ["phases", "basis", "confident", "reps_detected", "sets_detected"]
    for field in required_fields:
        assert field in profile, (
            f"golden_run_expected.json detected_profile must have field {field!r}"
        )
    assert isinstance(profile["phases"], list), "detected_profile.phases must be a list"
    assert isinstance(profile["confident"], bool), "detected_profile.confident must be a bool"


def test_ac6_golden_fixture_detected_profile_phases_have_structure():
    """AC6: each phase in the golden detected_profile must have label, band, lap_indexes."""
    expected = json.loads(_GOLDEN_EXPECTED.read_text())
    phases = expected["detected_profile"]["phases"]
    assert len(phases) > 0, "golden detected_profile must have at least one phase"
    for i, phase in enumerate(phases):
        assert "label" in phase, f"phase {i} must have 'label'"
        assert "band" in phase, f"phase {i} must have 'band'"
        assert "lap_indexes" in phase, f"phase {i} must have 'lap_indexes'"


# ── AC7: existing golden assertions still pass ────────────────────────────────


def test_ac7_golden_fixture_has_all_original_sections():
    """AC7: adding detected_profile must not remove any original golden sections."""
    expected = json.loads(_GOLDEN_EXPECTED.read_text())
    original_sections = ["normalized_power", "tss", "detected_profile"]
    for section in original_sections:
        assert section in expected, (
            f"golden_run_expected.json must still have original section {section!r}"
        )


# ── AC8a: declared structure → profile returned, detect not called ─────────────


def test_ac8a_declared_structure_returned_directly():
    """AC8a: workout with declared builder structure returns it as-is, detection skipped."""
    from backend.services.session_profile_caller import get_session_profile_for_workout
    from backend.services import session_profile_caller

    declared = {
        "phases": [{"label": "Warm-up"}, {"label": "Tempo"}, {"label": "Cool-down"}],
        "reps_detected": None,
        "sets_detected": None,
        "basis": "manual",
        "confident": True,
    }
    workout = types.SimpleNamespace(manual_overrides={"session_profile": declared})
    split_rows = [
        types.SimpleNamespace(
            avg_power=220, duration_seconds=600, distance_km=2.5, avg_hr=145, lap_type="manual"
        ),
    ]
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=170, threshold_pace_seconds_per_km=300)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as m:
        result = get_session_profile_for_workout(workout, split_rows, prefs)

    assert not m.called, (
        "AC8a: detect_session_profile must NOT be called when a declared structure is present"
    )
    assert result == declared, (
        "AC8a: declared structure must be returned unchanged"
    )


def test_ac8a_empty_declared_structure_also_returned_directly():
    """AC8a: even an empty declared structure is returned directly, not re-detected."""
    from backend.services import session_profile_caller

    declared = {}
    workout = types.SimpleNamespace(manual_overrides={"session_profile": declared})
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as m:
        result = session_profile_caller.get_session_profile_for_workout(workout, [], prefs)

    assert not m.called, "empty declared structure must also skip detection"
    assert result == declared


# ── AC8b: no declared structure → detect_session_profile called, result returned


def test_ac8b_no_declared_structure_calls_detect_and_returns_result():
    """AC8b: workout without declared structure calls detect and returns its result."""
    from backend.services import session_profile_caller

    detected = {
        "phases": [{"label": "Warm-up", "band": "steady"}],
        "reps_detected": None,
        "sets_detected": None,
        "basis": "power",
        "confident": True,
    }
    workout = types.SimpleNamespace(manual_overrides={})
    split_rows = [
        types.SimpleNamespace(
            avg_power=200, duration_seconds=600, distance_km=2.0, avg_hr=140, lap_type="manual"
        ),
    ]
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile", return_value=detected) as m:
        result = session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)

    assert m.called, (
        "AC8b: detect_session_profile must be called when no declared builder structure"
    )
    assert result is detected, (
        "AC8b: caller must return detect_session_profile result unchanged"
    )


def test_ac8b_none_prefs_handled_gracefully():
    """AC8b: caller handles prefs=None by passing all-None prefs dict to detect."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides={})
    captured = {}

    def fake_detect(splits, prefs_dict):
        captured["prefs"] = prefs_dict
        return {"phases": [], "basis": "none", "confident": False}

    with mock.patch.object(session_profile_caller, "detect_session_profile", side_effect=fake_detect):
        session_profile_caller.get_session_profile_for_workout(workout, [], None)

    assert captured["prefs"]["ftp_w"] is None
    assert captured["prefs"]["threshold_hr"] is None
    assert captured["prefs"]["threshold_pace_seconds_per_km"] is None


# ── AC9: endpoint returns 404 when workout ID does not exist ──────────────────


def test_ac9_get_workout_full_returns_404_for_missing_workout():
    """AC9: GET /api/workouts/{id}/full must raise 404 (not 500) when workout is missing."""
    code = _MAIN_SRC.read_text()
    func_start = code.find("def get_workout_full")
    assert func_start >= 0, "get_workout_full must exist in main.py"
    func_body = code[func_start:func_start + 8000]

    # The endpoint must check for None workout and raise 404
    has_none_check = "is None" in func_body or "one_or_none" in func_body
    assert has_none_check, (
        "get_workout_full must check if workout is None and return 404"
    )
    assert "status_code=404" in func_body, (
        "get_workout_full must explicitly raise HTTPException(status_code=404) "
        "when the workout is not found"
    )


def test_ac9_get_workout_full_not_found_uses_404_not_500():
    """AC9: verify the 404 is not swallowed by a bare except that might return 500."""
    code = _MAIN_SRC.read_text()
    func_start = code.find("def get_workout_full")
    func_body = code[func_start:func_start + 8000]

    # The function must not have a bare except that would catch HTTPException
    has_bare_except = "except:" in func_body and "except Exception:" not in func_body
    # Only flag truly bare excepts, not well-typed ones
    has_unguarded_except = "except:\n" in func_body
    assert not has_unguarded_except, (
        "get_workout_full must not have a bare except that could mask 404 as 500"
    )


def test_ac9_full_endpoint_uses_one_or_none_for_404_behaviour():
    """AC9: endpoint must use one_or_none() so missing rows yield None (not NoResultFound)."""
    code = _MAIN_SRC.read_text()
    func_start = code.find("def get_workout_full")
    func_body = code[func_start:func_start + 8000]
    assert "one_or_none" in func_body, (
        "get_workout_full must use .one_or_none() to safely handle missing workouts "
        "and return 404 instead of raising an ORM exception"
    )


# ── End-to-end unit test: full detection pipeline on manual splits ─────────────


def test_e2e_detection_on_manual_splits_returns_valid_profile():
    """Integration: detect_session_profile returns valid profile for realistic manual laps."""
    from backend.services.session_profile import detect_session_profile

    laps = [
        types.SimpleNamespace(avg_power=210, duration_seconds=600, distance_km=2.5, avg_hr=135),
        types.SimpleNamespace(avg_power=265, duration_seconds=900, distance_km=4.0, avg_hr=162),
        types.SimpleNamespace(avg_power=195, duration_seconds=300, distance_km=1.2, avg_hr=128),
    ]
    splits_container = types.SimpleNamespace(laps=laps, lap_type="manual")
    prefs = {"ftp_w": 280, "threshold_hr": None, "threshold_pace_seconds_per_km": None}

    result = detect_session_profile(splits_container, prefs)

    assert "phases" in result
    assert "basis" in result
    assert "confident" in result
    assert "reps_detected" in result
    assert "sets_detected" in result
    assert isinstance(result["phases"], list)
    assert result["basis"] in ("power", "pace", "hr", "none")


def test_e2e_caller_full_pipeline_without_declared_structure():
    """Integration: get_session_profile_for_workout runs full detection when no declared structure."""
    from backend.services.session_profile_caller import get_session_profile_for_workout

    split_rows = [
        types.SimpleNamespace(
            avg_power=210, duration_seconds=600, distance_km=2.5, avg_hr=135, lap_type="manual"
        ),
        types.SimpleNamespace(
            avg_power=265, duration_seconds=900, distance_km=4.0, avg_hr=162, lap_type="manual"
        ),
        types.SimpleNamespace(
            avg_power=195, duration_seconds=300, distance_km=1.2, avg_hr=128, lap_type="manual"
        ),
    ]
    workout = types.SimpleNamespace(manual_overrides={})
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=170, threshold_pace_seconds_per_km=300)

    result = get_session_profile_for_workout(workout, split_rows, prefs)

    assert isinstance(result, dict)
    assert "phases" in result
    assert "confident" in result
    assert "basis" in result
