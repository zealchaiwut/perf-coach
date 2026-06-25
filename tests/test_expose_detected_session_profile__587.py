"""Tests for issue #587: Expose detected session profile on full workout endpoint.

Acceptance criteria covered:
  AC1  — thin caller function delegates to detect_session_profile; no detection
          logic or hardcoded thresholds in the caller
  AC2  — GET /api/workouts/{id}/full includes a top-level detected_profile field
  AC3  — when no declared builder structure, detected_profile is the result of
          detect_session_profile
  AC4  — when a declared builder structure exists, detected_profile is that
          structure and detect_session_profile is NOT called
  AC5  — golden fixture updated (verified in test_golden_metrics__577.py)
  AC6  — all existing tests for GET /api/workouts/{id}/full continue to pass
  AC7  — no threshold literals in new code
"""

import pathlib
import types
import unittest.mock as mock

import pytest


# ── AC1: thin caller contains no detection logic and no literal thresholds ────


def test_caller_module_exists():
    """AC1: session_profile_caller module must exist and export get_session_profile_for_workout."""
    from backend.services.session_profile_caller import get_session_profile_for_workout
    assert callable(get_session_profile_for_workout)


def test_caller_delegates_to_detect_session_profile():
    """AC1: caller invokes detect_session_profile and returns its result unchanged."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides={})
    split_rows = []
    prefs = types.SimpleNamespace(ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None)

    sentinel = {"phases": [], "basis": "none", "confident": False, "sentinel": True}
    with mock.patch.object(session_profile_caller, "detect_session_profile", return_value=sentinel) as patched:
        result = session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)
    assert patched.called, "get_session_profile_for_workout must call detect_session_profile"
    assert result is sentinel, "caller must return detect_session_profile result unchanged"


def test_caller_has_no_threshold_literals():
    """AC7: caller module source must not contain numeric threshold literals."""
    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "backend" / "services" / "session_profile_caller.py"
    )
    code = src.read_text()
    # Banned literal forms — thresholds that belong in configuration
    banned = ["0.80", "0.90", "1.00", "1.06", "480", "2.0"]
    for literal in banned:
        assert literal not in code, (
            f"session_profile_caller.py contains hardcoded threshold literal {literal!r}; "
            "threshold values must be referenced by name from configuration"
        )


# ── AC2: detected_profile key present in full workout response ─────────────────


def test_full_endpoint_source_includes_detected_profile():
    """AC2: main.py get_workout_full response dict must include detected_profile."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()
    func_start = code.find("def get_workout_full")
    func_body = code[func_start:func_start + 8000]
    assert '"detected_profile"' in func_body, (
        "get_workout_full must include 'detected_profile' in its JSONResponse dict"
    )


def test_full_endpoint_calls_session_profile_caller():
    """AC2: main.py must import and call get_session_profile_for_workout (or alias)."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()
    assert "session_profile_caller" in code or "_get_session_profile" in code, (
        "main.py must import from session_profile_caller"
    )
    func_start = code.find("def get_workout_full")
    func_body = code[func_start:func_start + 8000]
    assert "_get_session_profile" in func_body or "get_session_profile_for_workout" in func_body, (
        "get_workout_full must call the session profile caller"
    )


# ── AC3: no declared builder structure → detect_session_profile is called ─────


def test_caller_runs_detection_when_no_builder_structure():
    """AC3: when manual_overrides has no session_profile, detection runs."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides=None)
    split_rows = []
    prefs = types.SimpleNamespace(ftp_w=200, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as patched:
        patched.return_value = {"phases": [], "basis": "none", "confident": False}
        session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)

    assert patched.called, (
        "detect_session_profile must be called when no declared builder structure exists"
    )


def test_caller_runs_detection_with_empty_manual_overrides():
    """AC3: manual_overrides={} (no session_profile key) also triggers detection."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides={})
    split_rows = []
    prefs = types.SimpleNamespace(ftp_w=200, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as patched:
        patched.return_value = {"phases": [], "basis": "none", "confident": False}
        session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)

    assert patched.called, (
        "detect_session_profile must be called when manual_overrides has no session_profile key"
    )


def test_caller_passes_prefs_fields_to_detect():
    """AC3: caller extracts ftp_w, threshold_hr, threshold_pace from prefs object."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides={})
    split_rows = []
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=170, threshold_pace_seconds_per_km=300)

    captured = {}
    def fake_detect(splits, prefs_dict):
        captured["prefs"] = prefs_dict
        return {"phases": [], "basis": "power", "confident": False}

    with mock.patch.object(session_profile_caller, "detect_session_profile", side_effect=fake_detect):
        session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)

    assert captured["prefs"]["ftp_w"] == 280
    assert captured["prefs"]["threshold_hr"] == 170
    assert captured["prefs"]["threshold_pace_seconds_per_km"] == 300


def test_caller_handles_none_prefs():
    """AC3: caller handles prefs=None by passing all-None prefs dict to detect."""
    from backend.services import session_profile_caller

    workout = types.SimpleNamespace(manual_overrides={})
    split_rows = []

    captured = {}
    def fake_detect(splits, prefs_dict):
        captured["prefs"] = prefs_dict
        return {"phases": [], "basis": "none", "confident": False}

    with mock.patch.object(session_profile_caller, "detect_session_profile", side_effect=fake_detect):
        session_profile_caller.get_session_profile_for_workout(workout, split_rows, None)

    assert captured["prefs"]["ftp_w"] is None
    assert captured["prefs"]["threshold_hr"] is None
    assert captured["prefs"]["threshold_pace_seconds_per_km"] is None


# ── AC4: declared builder structure → returned directly, detection skipped ─────


def test_caller_returns_declared_structure_directly():
    """AC4: when manual_overrides contains session_profile, caller returns it directly."""
    from backend.services import session_profile_caller

    declared = {"phases": [{"label": "Custom Phase"}], "basis": "manual", "confident": True}
    workout = types.SimpleNamespace(manual_overrides={"session_profile": declared})
    split_rows = []
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as patched:
        result = session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)

    assert not patched.called, (
        "detect_session_profile must NOT be called when a declared builder structure exists"
    )
    assert result is declared, (
        "caller must return the declared builder structure unchanged"
    )


def test_caller_builder_structure_wins_over_splits():
    """AC4: declared structure is returned even when split_rows is non-empty."""
    from backend.services import session_profile_caller

    declared = {"phases": [{"label": "Builder Phase"}], "confident": True}
    workout = types.SimpleNamespace(manual_overrides={"session_profile": declared})

    split_rows = [
        types.SimpleNamespace(
            avg_power=200, duration_seconds=300, distance_km=1.0, avg_hr=150, lap_type="manual"
        )
    ]
    prefs = types.SimpleNamespace(ftp_w=280, threshold_hr=None, threshold_pace_seconds_per_km=None)

    with mock.patch.object(session_profile_caller, "detect_session_profile") as patched:
        result = session_profile_caller.get_session_profile_for_workout(workout, split_rows, prefs)

    assert not patched.called
    assert result is declared


# ── AC6: existing full endpoint behaviour unchanged ────────────────────────────


def test_full_endpoint_still_has_existing_fields():
    """AC6: adding detected_profile must not remove existing response keys."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()
    func_start = code.find("def get_workout_full")
    func_body = code[func_start:func_start + 8000]

    required_keys = ['"workout"', '"splits"', '"sources"', '"unified"', '"computed"',
                     '"field_coverage"', '"tss"', '"tss_method"', '"tss_partial"',
                     '"computed_tss"', '"detected_profile"']
    for key in required_keys:
        assert key in func_body, (
            f"get_workout_full response must still include key {key}"
        )


# ── Integration: detect_session_profile produces correct output on split data ──


def test_detection_runs_end_to_end_on_manual_splits():
    """AC3: detect_session_profile returns a valid profile dict for manual laps."""
    from backend.services.session_profile import detect_session_profile

    laps = [
        types.SimpleNamespace(avg_power=150, duration_seconds=600, distance_km=2.0, avg_hr=130),
        types.SimpleNamespace(avg_power=260, duration_seconds=600, distance_km=2.5, avg_hr=155),
        types.SimpleNamespace(avg_power=145, duration_seconds=300, distance_km=1.0, avg_hr=125),
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


def test_detection_skipped_for_auto_splits():
    """AC3: detect_session_profile returns confident=False for auto_1km lap_type."""
    from backend.services.session_profile import detect_session_profile

    laps = [
        types.SimpleNamespace(avg_power=200, duration_seconds=360, distance_km=1.0, avg_hr=145),
        types.SimpleNamespace(avg_power=200, duration_seconds=360, distance_km=1.0, avg_hr=145),
    ]
    splits_container = types.SimpleNamespace(laps=laps, lap_type="auto_1km")
    prefs = {"ftp_w": 280, "threshold_hr": None, "threshold_pace_seconds_per_km": None}

    result = detect_session_profile(splits_container, prefs)

    assert result["confident"] is False
    assert result["basis"] == "none"


def test_detected_profile_phases_are_json_serializable_with_decimal_splits():
    """Regression: Numeric split distances must not break GET /full JSON encoding."""
    import json
    from decimal import Decimal

    from backend.services.lap_phase_grouper import LapPhaseConfig, group_laps_into_phases

    laps = [
        {
            "band": "steady",
            "distance_km": Decimal("0.998"),
            "duration_seconds": 341,
            "avg_hr": 147,
            "avg_power": 274,
        },
        {
            "band": "tempo",
            "distance_km": Decimal("0.999"),
            "duration_seconds": 359,
            "avg_hr": 167,
            "avg_power": 277,
        },
    ]
    phases, reason = group_laps_into_phases(laps, LapPhaseConfig())
    assert reason is None
    profile = {"phases": phases, "confident": True, "basis": "power"}
    json.dumps(profile)  # must not raise TypeError
    assert isinstance(phases[0]["distance_km"], float)
    assert isinstance(phases[0]["avg_pace_seconds_per_km"], float)
