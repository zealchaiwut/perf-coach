"""Tests for issue #586: detect_session_profile with precedence and data-quality gate.

Acceptance criteria covered:
  AC1  — function signature is detect_session_profile(splits, prefs); exported from service layer;
          no direct DB calls inside
  AC2  — return value always contains exactly: phases, reps_detected, sets_detected,
          basis, confident, debug
  AC3  — all thresholds read exclusively from prefs; none hardcoded inside
  AC4  — precedence gate documented in docstring; function itself does not check
  AC5  — data-quality gate: auto splits → confident=false, flat phases, reps/sets=null,
          basis=none, debug.reason
  AC6  — missing threshold gate: threshold absent/null → confident=false, basis=none,
          flat phases, debug.reason = "set your threshold to detect session phases"
  AC7  — when both gates pass, delegates to classify_laps, phase-grouping, interval-detection;
          confident=true, correct basis
  AC8  — debug exposes each lap's ratio and band
  AC9  — every numeric comparison described in plain English in inline comment
  AC10 — missing/null splits or prefs → returns graceful dict (no exception)
  AC11 — worked example in docblock
  AC12 — unit tests: (a) auto-split early return, (b) missing threshold,
          (c) missing argument, (d) full happy-path, (e) interval detection with non-null
          reps_detected and sets_detected
"""

import types
import pytest

from backend.services.session_profile import detect_session_profile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lap(avg_power=None, avg_hr=None, duration_seconds=300, distance_km=1.0):
    """Build a lap namespace matching WorkoutSplit shape."""
    return types.SimpleNamespace(
        avg_power=avg_power,
        avg_hr=avg_hr,
        duration_seconds=duration_seconds,
        distance_km=distance_km,
        lap_id=None,
    )


def _splits(laps, lap_type="manual"):
    """Build a splits container dict."""
    return {"laps": laps, "lap_type": lap_type}


def _prefs(ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None):
    return {
        "ftp_w": ftp_w,
        "threshold_hr": threshold_hr,
        "threshold_pace_seconds_per_km": threshold_pace_seconds_per_km,
    }


# ── AC1: importable, callable ─────────────────────────────────────────────────

def test_importable():
    """AC1: detect_session_profile is importable and callable."""
    assert callable(detect_session_profile)


# ── AC2: return shape always present ─────────────────────────────────────────

def test_return_keys_always_present_auto_splits():
    """AC2: all required keys present even on early return (auto splits)."""
    splits = _splits([], lap_type="auto_1km")
    result = detect_session_profile(splits, _prefs(ftp_w=200))
    for key in ("phases", "reps_detected", "sets_detected", "basis", "confident", "debug"):
        assert key in result, f"missing key: {key}"


def test_return_keys_always_present_missing_threshold():
    """AC2: all required keys present when threshold gate fires."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), _prefs())
    for key in ("phases", "reps_detected", "sets_detected", "basis", "confident", "debug"):
        assert key in result, f"missing key: {key}"


def test_return_keys_always_present_happy_path():
    """AC2: all required keys present on full happy-path run."""
    laps = [
        _lap(avg_power=160, duration_seconds=300, distance_km=1.0),
        _lap(avg_power=200, duration_seconds=300, distance_km=1.0),
        _lap(avg_power=160, duration_seconds=300, distance_km=1.0),
    ]
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    for key in ("phases", "reps_detected", "sets_detected", "basis", "confident", "debug"):
        assert key in result, f"missing key: {key}"


# ── AC5: data-quality gate (auto splits) ─────────────────────────────────────

def test_auto_splits_early_return():
    """AC5(a): auto 1 km splits trigger early return with confident=False."""
    laps = [_lap(avg_power=200) for _ in range(5)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1km"), _prefs(ftp_w=200))
    assert result["confident"] is False
    assert result["basis"] == "none"
    assert result["reps_detected"] is None
    assert result["sets_detected"] is None
    assert isinstance(result["debug"].get("reason"), str)
    assert len(result["debug"]["reason"]) > 0


def test_auto_splits_returns_flat_phases():
    """AC5: auto splits → phases is a flat list (no phase grouping names)."""
    laps = [_lap(avg_power=200, duration_seconds=300, distance_km=1.0) for _ in range(3)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1km"), _prefs(ftp_w=200))
    assert isinstance(result["phases"], list)
    # phases list length matches laps count (one entry per lap) OR is empty
    # either way there are no phase-group labels (Warm-up/Cool-down/Tempo etc.)
    for phase in result["phases"]:
        assert phase.get("label") not in ("Warm-up", "Cool-down", "Tempo")


def test_auto_splits_debug_reason_describes_skip():
    """AC5: debug.reason contains human-readable description."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1km"), _prefs(ftp_w=200))
    reason = result["debug"]["reason"]
    assert "auto" in reason.lower() or "1 km" in reason.lower() or "skip" in reason.lower()


# ── AC6: no usable threshold gate ────────────────────────────────────────────

def test_missing_threshold_early_return():
    """AC6(b): all thresholds absent → confident=False, basis=none."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), _prefs())
    assert result["confident"] is False
    assert result["basis"] == "none"
    assert result["reps_detected"] is None
    assert result["sets_detected"] is None


def test_missing_threshold_debug_reason():
    """AC6: debug.reason = 'set your threshold to detect session phases'."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), _prefs())
    assert result["debug"]["reason"] == "set your threshold to detect session phases"


def test_null_threshold_values_trigger_gate():
    """AC6: explicit null values in prefs also trigger the gate."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    prefs = {"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
    result = detect_session_profile(_splits(laps), prefs)
    assert result["confident"] is False
    assert result["debug"]["reason"] == "set your threshold to detect session phases"


# ── AC10: missing/null arguments ─────────────────────────────────────────────

def test_null_splits_returns_gracefully():
    """AC10(c): splits=None → no exception; confident=False, debug.reason present."""
    result = detect_session_profile(None, _prefs(ftp_w=200))
    assert result["confident"] is False
    assert result["reps_detected"] is None
    assert result["sets_detected"] is None
    assert "missing input" in result["debug"]["reason"].lower()


def test_null_prefs_returns_gracefully():
    """AC10(c): prefs=None → no exception; confident=False, debug.reason present."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), None)
    assert result["confident"] is False
    assert result["reps_detected"] is None
    assert result["sets_detected"] is None
    assert "missing input" in result["debug"]["reason"].lower()


def test_null_splits_exact_shape():
    """AC10: null splits → returns the documented exact shape."""
    result = detect_session_profile(None, _prefs(ftp_w=200))
    assert result["phases"] == []
    assert result["reps_detected"] is None
    assert result["sets_detected"] is None
    assert result["basis"] == "none"
    assert result["confident"] is False
    assert "missing input" in result["debug"].get("reason", "").lower()


def test_null_prefs_exact_shape():
    """AC10: null prefs → returns the documented exact shape."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), None)
    assert result["phases"] == []
    assert result["reps_detected"] is None
    assert result["sets_detected"] is None
    assert result["basis"] == "none"
    assert result["confident"] is False
    assert "missing input" in result["debug"].get("reason", "").lower()


# ── AC7: full happy-path ──────────────────────────────────────────────────────

def test_happy_path_confident_true():
    """AC7(d): manual laps + valid ftp_w → confident=True."""
    # easy, tempo, easy → should produce phases
    laps = [
        _lap(avg_power=150, duration_seconds=360, distance_km=1.5),   # easy (ratio=0.75)
        _lap(avg_power=190, duration_seconds=600, distance_km=2.5),   # tempo (ratio=0.95)
        _lap(avg_power=150, duration_seconds=300, distance_km=1.0),   # easy (ratio=0.75)
    ]
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert result["confident"] is True
    assert result["basis"] == "power"
    assert isinstance(result["phases"], list)
    assert len(result["phases"]) >= 1


def test_happy_path_basis_power():
    """AC7: ftp_w present → basis='power'."""
    laps = [_lap(avg_power=180, duration_seconds=300, distance_km=1.0) for _ in range(3)]
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert result["basis"] == "power"


def test_happy_path_basis_pace():
    """AC7: no ftp_w, threshold_pace present → basis='pace'."""
    # pace = 300/1.0 = 300 s/km (exactly threshold)
    laps = [
        _lap(avg_power=None, avg_hr=None, duration_seconds=300, distance_km=1.0)
        for _ in range(3)
    ]
    result = detect_session_profile(_splits(laps), _prefs(threshold_pace_seconds_per_km=300))
    assert result["basis"] == "pace"


def test_happy_path_basis_hr():
    """AC7: no ftp_w or threshold_pace, threshold_hr present → basis='hr'."""
    laps = [
        _lap(avg_power=None, avg_hr=155, duration_seconds=None, distance_km=None)
        for _ in range(3)
    ]
    result = detect_session_profile(_splits(laps), _prefs(threshold_hr=165))
    assert result["basis"] == "hr"


# ── AC8: debug per-lap ratio and band ────────────────────────────────────────

def test_debug_exposes_per_lap_ratio_and_band():
    """AC8: debug contains per-lap entries with ratio and band."""
    laps = [
        _lap(avg_power=160, duration_seconds=300, distance_km=1.0),  # ratio=0.80
        _lap(avg_power=200, duration_seconds=300, distance_km=1.0),  # ratio=1.00
    ]
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert "laps" in result["debug"]
    lap_debug = result["debug"]["laps"]
    assert len(lap_debug) == 2
    for entry in lap_debug:
        assert "ratio" in entry
        assert "band" in entry


def test_debug_lap_ratio_values():
    """AC8: debug laps have correct ratios."""
    laps = [
        _lap(avg_power=180, duration_seconds=300, distance_km=1.0),  # ratio=0.90
    ]
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert result["confident"] is True
    lap_debug = result["debug"]["laps"]
    assert len(lap_debug) == 1
    assert abs(lap_debug[0]["ratio"] - 0.90) < 0.01


# ── AC7+AC12(e): interval detection produces non-null reps and sets ───────────

def _hard_lap(duration=60, distance=0.2):
    """A threshold-effort lap (ratio=1.01 with ftp_w=200) — counts as hard rep."""
    return _lap(avg_power=202, duration_seconds=duration, distance_km=distance)  # ratio=1.01


def _easy_lap(duration=90, distance=0.3):
    """An easy recovery lap (ratio=0.75 with ftp_w=200)."""
    return _lap(avg_power=150, duration_seconds=duration, distance_km=distance)  # ratio=0.75


def test_interval_detection_produces_non_null_reps():
    """AC12(e): alternating hard/easy pattern → reps_detected is non-null int."""
    laps = []
    for _ in range(4):
        laps.append(_hard_lap())
        laps.append(_easy_lap())
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert result["confident"] is True
    assert result["reps_detected"] is not None
    assert isinstance(result["reps_detected"], int)
    assert result["reps_detected"] >= 2


def test_interval_detection_produces_non_null_sets():
    """AC12(e): alternating hard/easy pattern → sets_detected is non-null int."""
    laps = []
    for _ in range(4):
        laps.append(_hard_lap())
        laps.append(_easy_lap())
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert result["sets_detected"] is not None
    assert isinstance(result["sets_detected"], int)
    assert result["sets_detected"] >= 1


def test_non_interval_session_has_null_reps():
    """AC7: non-interval session (no alternating pattern) → reps_detected=None."""
    laps = [
        _lap(avg_power=150, duration_seconds=360, distance_km=1.5),   # easy
        _lap(avg_power=190, duration_seconds=600, distance_km=2.5),   # tempo
        _lap(avg_power=150, duration_seconds=300, distance_km=1.0),   # easy
    ]
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert result["reps_detected"] is None


# ── AC1: no DB calls — no import of models inside ────────────────────────────

def test_no_db_import_in_module():
    """AC1: session_profile module does not import backend.models (no DB calls)."""
    import backend.services.session_profile as sp_module
    import sys
    # Check module's globals for DB-related imports
    assert "backend.models" not in sys.modules or (
        "session" not in dir(sp_module)
    )
    # Verify the module source doesn't import models
    import inspect
    src = inspect.getsource(sp_module)
    assert "from backend.models" not in src
    assert "import backend.models" not in src


# ── AC4: docstring documents precedence contract ────────────────────────────

def test_docstring_documents_precedence():
    """AC4: docstring mentions caller responsibility for builder structure check."""
    doc = detect_session_profile.__doc__ or ""
    doc_lower = doc.lower()
    assert "builder" in doc_lower or "declared" in doc_lower or "caller" in doc_lower, (
        "Docstring must document the builder structure precedence contract"
    )


# ── AC11: worked example in docblock ─────────────────────────────────────────

def test_docstring_has_worked_example():
    """AC11: docstring contains a worked example with concrete values."""
    doc = detect_session_profile.__doc__ or ""
    # A worked example should have some kind of input/output demonstration
    assert "example" in doc.lower() or "worked" in doc.lower(), (
        "Docstring must contain a worked example"
    )
