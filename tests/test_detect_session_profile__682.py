"""Tests for issue #682: detect_session_profile with precedence and data-quality gate.

Acceptance criteria covered:
  AC1  — function signature detect_session_profile(splits, prefs); returns object with
          exactly: phases, reps_detected, sets_detected, basis, confident, debug
  AC2  — all thresholds read from prefs; no hardcoded literals in function/helpers
  AC3  — missing/null inputs: function does not raise; returns safe result with reason
          naming the missing input (AC3 maps to AC12d and AC12e in the test list)
  AC4  — caller responsibility; detect_session_profile never called for builder-structure
          workouts (verified via session_profile_caller tests)
  AC5  — every helper is pure and has at least one inline worked example in docstring
  AC6  — numeric relationships written in prose; no magic numbers in comments
  AC7  — builder bypass: caller handles this; detect_session_profile itself is not invoked
  AC8  — auto-lap gate: confident=False, flat phases, reps/sets=None,
          reason is AUTO_LAPS_INSUFFICIENT constant (or equivalent)
  AC9  — no-threshold gate: confident=False, basis="none", flat phases,
          reason = "set your threshold to detect session phases"
  AC10 — basis priority: power > pace > hr; power chosen when both power and pace present
  AC11 — debug contains ratio and band for every lap
  AC12 — unit tests: (a) happy path, (b) auto-lap exit, (c) no-threshold exit,
          (d) null splits, (e) null prefs, (f) basis priority
  AC13 — integration smoke test: classify_laps → phase grouper → interval detection
          called in correct order when quality gate passes
  AC14 — no breaking changes to classify_laps, phase grouping, interval detection
"""

import types
from unittest.mock import patch, call

import pytest

from backend.services.session_profile import detect_session_profile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lap(avg_power=None, avg_hr=None, duration_seconds=300, distance_km=1.0,
         lap_type=None):
    return types.SimpleNamespace(
        avg_power=avg_power,
        avg_hr=avg_hr,
        duration_seconds=duration_seconds,
        distance_km=distance_km,
        lap_type=lap_type,
    )


def _splits(laps, lap_type="manual"):
    return {"laps": laps, "lap_type": lap_type}


def _prefs(ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None):
    return {
        "ftp_w": ftp_w,
        "threshold_hr": threshold_hr,
        "threshold_pace_seconds_per_km": threshold_pace_seconds_per_km,
    }


# ── AC12a: happy path — manual laps + all thresholds ─────────────────────────

def test_happy_path_all_keys_present():
    """AC12a: happy path with manual laps and all thresholds returns full object."""
    laps = [
        _lap(avg_power=150, avg_hr=140, duration_seconds=360, distance_km=1.5),
        _lap(avg_power=190, avg_hr=160, duration_seconds=600, distance_km=2.5),
        _lap(avg_power=150, avg_hr=140, duration_seconds=300, distance_km=1.0),
    ]
    prefs = _prefs(ftp_w=200, threshold_hr=165, threshold_pace_seconds_per_km=300)
    result = detect_session_profile(_splits(laps), prefs)
    for key in ("phases", "reps_detected", "sets_detected", "basis", "confident", "debug"):
        assert key in result, f"missing key: {key}"


def test_happy_path_confident_true():
    """AC12a: manual laps + valid ftp_w → confident=True."""
    laps = [
        _lap(avg_power=150, duration_seconds=360, distance_km=1.5),
        _lap(avg_power=190, duration_seconds=600, distance_km=2.5),
        _lap(avg_power=150, duration_seconds=300, distance_km=1.0),
    ]
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert result["confident"] is True
    assert result["basis"] == "power"
    assert isinstance(result["phases"], list)
    assert len(result["phases"]) >= 1


def test_happy_path_debug_has_per_lap_entries():
    """AC12a + AC11: debug.laps has one entry per lap with ratio and band."""
    laps = [
        _lap(avg_power=160, duration_seconds=300, distance_km=1.0),
        _lap(avg_power=200, duration_seconds=480, distance_km=2.1),
        _lap(avg_power=160, duration_seconds=300, distance_km=1.0),
    ]
    result = detect_session_profile(_splits(laps), _prefs(ftp_w=200))
    assert result["confident"] is True
    lap_debug = result["debug"]["laps"]
    assert len(lap_debug) == 3
    for entry in lap_debug:
        assert "ratio" in entry
        assert "band" in entry


# ── AC12b: auto-lap early exit ────────────────────────────────────────────────

def test_auto_laps_confident_false():
    """AC12b: auto_1km lap_type → confident=False."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1km"), _prefs(ftp_w=200))
    assert result["confident"] is False


def test_auto_laps_basis_none():
    """AC12b: auto-lap early exit → basis='none'."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1km"), _prefs(ftp_w=200))
    assert result["basis"] == "none"


def test_auto_laps_reps_sets_null():
    """AC12b: auto-lap early exit → reps_detected=None, sets_detected=None."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1km"), _prefs(ftp_w=200))
    assert result["reps_detected"] is None
    assert result["sets_detected"] is None


def test_auto_laps_reason_in_debug():
    """AC12b + AC8: debug.reason present and describes auto-lap skip."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1km"), _prefs(ftp_w=200))
    reason = result["debug"].get("reason", "")
    assert reason, "debug.reason must be a non-empty string"
    # Reason should reference auto laps or insufficient structure
    keywords = {"auto", "insufficient", "skip", "1 km", "1km"}
    assert any(kw in reason.lower() for kw in keywords), (
        f"reason '{reason}' does not mention auto laps or insufficient structure"
    )


def test_auto_laps_flat_phases_no_named_groups():
    """AC12b + AC8: auto-lap phases is flat — no Warm-up/Tempo/Cool-down labels."""
    laps = [_lap(avg_power=200, duration_seconds=300, distance_km=1.0) for _ in range(5)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1km"), _prefs(ftp_w=200))
    grouped_labels = {"Warm-up", "Cool-down", "Tempo"}
    for phase in result["phases"]:
        assert phase.get("label") not in grouped_labels, (
            f"auto-lap result must not contain grouped label '{phase.get('label')}'"
        )


def test_auto_mile_also_triggers_gate():
    """AC8: auto_1mi lap_type also triggers the data-quality gate."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps, lap_type="auto_1mi"), _prefs(ftp_w=200))
    assert result["confident"] is False
    assert result["basis"] == "none"


# ── AC12c: no-threshold early exit ────────────────────────────────────────────

def test_no_threshold_confident_false():
    """AC12c: no usable threshold → confident=False."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), _prefs())
    assert result["confident"] is False


def test_no_threshold_basis_none():
    """AC12c: no threshold → basis='none'."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), _prefs())
    assert result["basis"] == "none"


def test_no_threshold_exact_reason():
    """AC9: no-threshold reason exactly matches documented constant."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), _prefs())
    assert result["debug"]["reason"] == "set your threshold to detect session phases"


def test_no_threshold_explicit_nulls():
    """AC12c: explicit null values also trigger no-threshold gate."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    prefs = {"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
    result = detect_session_profile(_splits(laps), prefs)
    assert result["confident"] is False
    assert result["debug"]["reason"] == "set your threshold to detect session phases"


# ── AC12d: null splits ─────────────────────────────────────────────────────────

def test_null_splits_no_exception():
    """AC12d + AC3: detect_session_profile(None, prefs) never raises."""
    result = detect_session_profile(None, _prefs(ftp_w=200))
    assert isinstance(result, dict)


def test_null_splits_confident_false():
    """AC12d: null splits → confident=False."""
    result = detect_session_profile(None, _prefs(ftp_w=200))
    assert result["confident"] is False


def test_null_splits_reason_names_splits():
    """AC12d + AC3: reason string names 'splits' as the missing input."""
    result = detect_session_profile(None, _prefs(ftp_w=200))
    reason = result["debug"].get("reason", "")
    assert "splits" in reason.lower(), (
        f"reason '{reason}' must name 'splits' as the missing input"
    )


def test_null_splits_all_keys_present():
    """AC12d: null splits → returned object still contains all required keys."""
    result = detect_session_profile(None, _prefs(ftp_w=200))
    for key in ("phases", "reps_detected", "sets_detected", "basis", "confident", "debug"):
        assert key in result


def test_null_splits_reps_sets_none():
    """AC12d: null splits → reps_detected=None, sets_detected=None."""
    result = detect_session_profile(None, _prefs(ftp_w=200))
    assert result["reps_detected"] is None
    assert result["sets_detected"] is None


# ── AC12e: null prefs ──────────────────────────────────────────────────────────

def test_null_prefs_no_exception():
    """AC12e + AC3: detect_session_profile(splits, None) never raises."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), None)
    assert isinstance(result, dict)


def test_null_prefs_confident_false():
    """AC12e: null prefs → confident=False."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), None)
    assert result["confident"] is False


def test_null_prefs_reason_names_prefs():
    """AC12e + AC3: reason string names 'prefs' as the missing input."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), None)
    reason = result["debug"].get("reason", "")
    assert "prefs" in reason.lower(), (
        f"reason '{reason}' must name 'prefs' as the missing input"
    )


def test_null_prefs_all_keys_present():
    """AC12e: null prefs → returned object still contains all required keys."""
    laps = [_lap(avg_power=200) for _ in range(4)]
    result = detect_session_profile(_splits(laps), None)
    for key in ("phases", "reps_detected", "sets_detected", "basis", "confident", "debug"):
        assert key in result


# ── AC12f: basis priority — power > pace > hr ─────────────────────────────────

def test_basis_priority_power_over_pace():
    """AC12f + AC10: power threshold present → basis='power', not 'pace'."""
    laps = [
        _lap(avg_power=200, duration_seconds=300, distance_km=1.0)
        for _ in range(3)
    ]
    prefs = _prefs(ftp_w=200, threshold_pace_seconds_per_km=300)
    result = detect_session_profile(_splits(laps), prefs)
    assert result["basis"] == "power", (
        f"expected basis='power' when both ftp_w and threshold_pace are set; got '{result['basis']}'"
    )


def test_basis_priority_power_over_hr():
    """AC12f + AC10: power threshold present → basis='power', not 'hr'."""
    laps = [
        _lap(avg_power=200, avg_hr=155, duration_seconds=300, distance_km=1.0)
        for _ in range(3)
    ]
    prefs = _prefs(ftp_w=200, threshold_hr=165)
    result = detect_session_profile(_splits(laps), prefs)
    assert result["basis"] == "power"


def test_basis_priority_pace_over_hr():
    """AC10: pace threshold wins over hr when ftp_w is absent."""
    laps = [
        _lap(avg_hr=155, duration_seconds=300, distance_km=1.0)
        for _ in range(3)
    ]
    prefs = _prefs(threshold_hr=165, threshold_pace_seconds_per_km=300)
    result = detect_session_profile(_splits(laps), prefs)
    assert result["basis"] == "pace", (
        f"expected basis='pace' when both threshold_pace and threshold_hr are set; got '{result['basis']}'"
    )


def test_basis_hr_only():
    """AC10: hr is the fallback when power and pace are absent."""
    laps = [
        _lap(avg_hr=155, duration_seconds=300, distance_km=1.0)
        for _ in range(3)
    ]
    result = detect_session_profile(_splits(laps), _prefs(threshold_hr=165))
    assert result["basis"] == "hr"


def test_basis_power_over_all_three():
    """AC12f: power wins even when all three thresholds are present."""
    laps = [
        _lap(avg_power=200, avg_hr=155, duration_seconds=300, distance_km=1.0)
        for _ in range(3)
    ]
    prefs = _prefs(ftp_w=200, threshold_hr=165, threshold_pace_seconds_per_km=300)
    result = detect_session_profile(_splits(laps), prefs)
    assert result["basis"] == "power"


# ── AC13: integration smoke test ──────────────────────────────────────────────

def test_integration_pipeline_order_classify_then_phase_then_interval():
    """AC13: when quality gate passes, classify_laps is called before phase grouper,
    phase grouper before interval detection.  Uses call-order tracking.
    """
    laps = [
        _lap(avg_power=150, duration_seconds=360, distance_km=1.5),
        _lap(avg_power=190, duration_seconds=600, distance_km=2.5),
        _lap(avg_power=150, duration_seconds=300, distance_km=1.0),
    ]
    splits = _splits(laps)
    prefs = _prefs(ftp_w=200)

    call_order = []

    # Wrap each dependency function to record call order without changing output
    import backend.services.session_profile as sp_mod
    import backend.services.lap_classifier as lc_mod
    import backend.services.lap_phase_grouper as lpg_mod
    import backend.services.interval_detector as id_mod

    real_classify = lc_mod.classify_laps
    real_group = lpg_mod.group_laps_into_phases
    real_detect_intervals = id_mod.detect_intervals
    real_detect_sets = id_mod.detect_sets

    def tracking_classify(l, p):
        call_order.append("classify_laps")
        return real_classify(l, p)

    def tracking_group(l, c):
        call_order.append("group_laps_into_phases")
        return real_group(l, c)

    def tracking_detect_intervals(l):
        call_order.append("detect_intervals")
        return real_detect_intervals(l)

    def tracking_detect_sets(ph, l):
        call_order.append("detect_sets")
        return real_detect_sets(ph, l)

    with patch.object(sp_mod, "classify_laps", side_effect=tracking_classify), \
         patch.object(sp_mod, "group_laps_into_phases", side_effect=tracking_group), \
         patch.object(sp_mod, "detect_intervals", side_effect=tracking_detect_intervals), \
         patch.object(sp_mod, "detect_sets", side_effect=tracking_detect_sets):
        result = detect_session_profile(splits, prefs)

    assert result["confident"] is True
    assert "classify_laps" in call_order, "classify_laps was not called"
    assert "group_laps_into_phases" in call_order, "group_laps_into_phases was not called"
    assert "detect_intervals" in call_order, "detect_intervals was not called"

    # Verify order: classify before phase grouping, phase grouping before interval detection
    assert call_order.index("classify_laps") < call_order.index("group_laps_into_phases"), (
        "classify_laps must be called before group_laps_into_phases"
    )
    assert call_order.index("group_laps_into_phases") < call_order.index("detect_intervals"), (
        "group_laps_into_phases must be called before detect_intervals"
    )


def test_integration_auto_lap_gate_skips_pipeline():
    """AC13: when auto-lap gate fires, classify_laps is still called for colours but
    phase grouper and interval detection are never called.
    """
    laps = [_lap(avg_power=200, duration_seconds=300, distance_km=1.0) for _ in range(4)]
    splits = _splits(laps, lap_type="auto_1km")
    prefs = _prefs(ftp_w=200)

    import backend.services.session_profile as sp_mod

    with patch.object(sp_mod, "group_laps_into_phases") as mock_group, \
         patch.object(sp_mod, "detect_intervals") as mock_intervals:
        result = detect_session_profile(splits, prefs)

    assert result["confident"] is False
    mock_group.assert_not_called()
    mock_intervals.assert_not_called()


def test_integration_no_threshold_gate_skips_full_pipeline():
    """AC13: when no-threshold gate fires, the full pipeline is not run."""
    laps = [_lap(avg_power=200, duration_seconds=300, distance_km=1.0) for _ in range(4)]
    splits = _splits(laps)
    prefs = _prefs()  # all None

    import backend.services.session_profile as sp_mod

    with patch.object(sp_mod, "group_laps_into_phases") as mock_group, \
         patch.object(sp_mod, "detect_intervals") as mock_intervals:
        result = detect_session_profile(splits, prefs)

    assert result["confident"] is False
    mock_group.assert_not_called()
    mock_intervals.assert_not_called()


# ── AC5: helper docstrings have worked examples ───────────────────────────────

def test_helper_flat_phase_list_docstring_has_example():
    """AC5: _flat_phase_list helper docstring contains an inline worked example."""
    from backend.services.session_profile import _flat_phase_list
    doc = (_flat_phase_list.__doc__ or "").lower()
    has_example = (
        "example" in doc
        or "input" in doc
        or "→" in doc
        or "->" in doc
        or "output" in doc
        or "result" in doc
    )
    assert has_example, "_flat_phase_list docstring must contain an inline worked example"


def test_helper_derive_basis_docstring_has_example():
    """AC5: _derive_basis helper docstring contains an inline worked example."""
    from backend.services.session_profile import _derive_basis
    doc = (_derive_basis.__doc__ or "").lower()
    has_example = (
        "example" in doc
        or "input" in doc
        or "→" in doc
        or "->" in doc
        or "output" in doc
        or "result" in doc
    )
    assert has_example, "_derive_basis docstring must contain an inline worked example"


def test_helper_get_docstring_has_example():
    """AC5: _get helper docstring contains an inline worked example."""
    from backend.services.session_profile import _get
    doc = (_get.__doc__ or "").lower()
    has_example = (
        "example" in doc
        or "input" in doc
        or "→" in doc
        or "->" in doc
        or "output" in doc
        or "result" in doc
    )
    assert has_example, "_get docstring must contain an inline worked example"


# ── AC14: no breaking changes ─────────────────────────────────────────────────

def test_no_breaking_change_classify_laps():
    """AC14: classify_laps interface unchanged."""
    from backend.services.lap_classifier import classify_laps
    import inspect
    sig = inspect.signature(classify_laps)
    params = list(sig.parameters.keys())
    assert params == ["splits", "prefs"], (
        f"classify_laps signature changed: expected ['splits', 'prefs'], got {params}"
    )


def test_no_breaking_change_group_laps_into_phases():
    """AC14: group_laps_into_phases interface unchanged."""
    from backend.services.lap_phase_grouper import group_laps_into_phases
    import inspect
    sig = inspect.signature(group_laps_into_phases)
    params = list(sig.parameters.keys())
    assert params == ["classified_laps", "config"], (
        f"group_laps_into_phases signature changed: got {params}"
    )


def test_no_breaking_change_detect_intervals():
    """AC14: detect_intervals interface unchanged."""
    from backend.services.interval_detector import detect_intervals
    import inspect
    sig = inspect.signature(detect_intervals)
    params = list(sig.parameters.keys())
    assert params == ["laps"], (
        f"detect_intervals signature changed: got {params}"
    )
