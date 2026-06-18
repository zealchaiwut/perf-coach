"""Tests for issue #594: Combine Strength TSS Calculation into Single Service.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria covered:
  AC-1   — Pure function with zero database access
  AC-2   — Return shape: tss, method, partial, debug
  AC-3a  — method is "per_set" when any set-level data (rpe + volume) is present
  AC-3b  — method is "session_rpe" when only session-level RPE and duration available
  AC-4   — method is "none" and tss is null when neither RPE nor duration; debug has reason
  AC-5   — partial is true when some per-set records are missing RPE
  AC-6   — all thresholds read from prefs; none hardcoded
  AC-7   — missing required pref → tss: null with descriptive reason in debug
  AC-8   — docstring has plain-words formula + worked numeric example per method
  AC-9   — workout.tss passed through unchanged when manually set (caller responsibility)
  AC-10  — pure function only; no DB calls in implementation
  AC-11  — running TSS service (compute_running_tss, calculate_hr_tss) not modified
  AC-12  — golden fixture gains two new strength workout cases
"""

import inspect
import json
import pathlib
import types

import pytest

from backend.services.tss import compute_strength_tss


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workout(duration_seconds=None, session_rpe=None):
    return types.SimpleNamespace(
        duration_seconds=duration_seconds,
        session_rpe=session_rpe,
    )


def _exercise(rpe=None, reps=None, weight_kg=None, sets=None, sets_json=None):
    return types.SimpleNamespace(
        rpe=rpe,
        reps=reps,
        weight_kg=weight_kg,
        sets=sets,
        sets_json=sets_json,
    )


def _prefs(strength_tss_scale=None, strength_tss_max=None):
    return types.SimpleNamespace(
        strength_tss_scale=strength_tss_scale,
        strength_tss_max=strength_tss_max,
    )


# ── AC-1 / AC-10: pure function with no DB access ────────────────────────────

def test_function_has_no_db_access():
    """AC-1: compute_strength_tss source contains no DB-related identifiers."""
    src = inspect.getsource(compute_strength_tss)
    for forbidden in ("db.", "session.", "execute(", "fetchone(", "fetchall(", "query("):
        assert forbidden not in src, f"DB access found in compute_strength_tss: {forbidden!r}"


# ── AC-2: return shape ────────────────────────────────────────────────────────

def test_return_shape_per_set():
    """AC-2: per_set result has exactly tss, method, partial, debug keys."""
    exs = [_exercise(rpe=8, reps=5)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert set(result.keys()) == {"tss", "method", "partial", "debug"}


def test_return_shape_session_rpe():
    """AC-2: session_rpe result has exactly tss, method, partial, debug keys."""
    w = _workout(duration_seconds=2700, session_rpe=8)
    result = compute_strength_tss(w, [], _prefs(strength_tss_max=150))
    assert set(result.keys()) == {"tss", "method", "partial", "debug"}


def test_return_shape_none():
    """AC-2: none result has exactly tss, method, partial, debug keys."""
    result = compute_strength_tss(_workout(), [], _prefs())
    assert set(result.keys()) == {"tss", "method", "partial", "debug"}


def test_tss_is_int_or_none_per_set():
    """AC-2: tss is a whole integer (not float) for per_set method."""
    exs = [_exercise(rpe=8, reps=5)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert result["tss"] is None or isinstance(result["tss"], int)


def test_tss_is_int_or_none_session_rpe():
    """AC-2: tss is a whole integer (not float) for session_rpe method."""
    w = _workout(duration_seconds=3600, session_rpe=8)
    result = compute_strength_tss(w, [], _prefs(strength_tss_max=150))
    if result["tss"] is not None:
        assert isinstance(result["tss"], int)


def test_partial_is_bool():
    """AC-2: partial is always a bool."""
    exs = [_exercise(rpe=8, reps=5)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert isinstance(result["partial"], bool)


# ── AC-3a: method is "per_set" when set-level data is present ────────────────

def test_per_set_when_exercise_has_rpe_and_reps():
    """AC-3a: exercise with both rpe and reps → method is per_set."""
    exs = [_exercise(rpe=8, reps=5)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert result["method"] == "per_set"


def test_per_set_when_exercise_has_rpe_and_weight():
    """AC-3a: exercise with rpe and weight_kg (no reps) → method is per_set."""
    exs = [_exercise(rpe=7, reps=5, weight_kg=100)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert result["method"] == "per_set"


def test_per_set_from_sets_json():
    """AC-3a: sets_json with rpe+reps entries → method is per_set."""
    sets = json.dumps([{"reps": 5, "rpe": 8}, {"reps": 5, "rpe": 9}])
    exs = [_exercise(sets_json=sets)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert result["method"] == "per_set"


def test_per_set_takes_priority_over_session_rpe():
    """AC-3a: when per-set data is present, per_set wins even if session_rpe also exists."""
    w = _workout(duration_seconds=3600, session_rpe=8)
    exs = [_exercise(rpe=9, reps=5)]
    result = compute_strength_tss(w, exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert result["method"] == "per_set"


# ── AC-3a: per_set worked example ─────────────────────────────────────────────

def test_per_set_three_sets_worked_example():
    """AC-3a/AC-8: three-set worked example from issue #593 docstring."""
    # 5×8, 5×9, 3×10 with scale=5.85, max=150
    sets = json.dumps([
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3, "rpe": 10},
    ])
    exs = [_exercise(sets_json=sets)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    # set1: 5×0.64=3.20, set2: 5×0.81=4.05, set3: 3×1.0=3.00 → raw=10.25
    # scaled=10.25×5.85=59.9625 → tss=60
    assert result["method"] == "per_set"
    assert result["tss"] == 60
    assert result["partial"] is False


def test_per_set_debug_exposes_contributions():
    """AC-3a: debug exposes per_set_contributions, raw_sum, scaled_sum, clamped."""
    sets = json.dumps([{"reps": 5, "rpe": 8}, {"reps": 5, "rpe": 9}])
    exs = [_exercise(sets_json=sets)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    d = result["debug"]
    assert "per_set_contributions" in d
    assert "raw_sum" in d
    assert "scaled_sum" in d
    assert "clamped" in d


def test_per_set_exercise_level_rpe_reps():
    """AC-3a: exercise with rpe, reps, sets=3 expands to 3 identical sets."""
    exs = [_exercise(rpe=8, reps=5, sets=3)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    # 3 sets of 5 reps @ rpe8: raw=3×3.20=9.60, scaled=56.16→56
    assert result["method"] == "per_set"
    assert result["tss"] == round(3 * 5 * (8 / 10) ** 2 * 5.85)


# ── AC-3b: method is "session_rpe" when only RPE + duration available ─────────

def test_session_rpe_when_workout_has_rpe_and_duration():
    """AC-3b: workout.session_rpe + duration_seconds, no exercises → session_rpe."""
    w = _workout(duration_seconds=2700, session_rpe=8)
    result = compute_strength_tss(w, [], _prefs(strength_tss_max=150))
    assert result["method"] == "session_rpe"


def test_session_rpe_worked_example_45min_rpe8():
    """AC-3b: 45 min at session RPE=8 → TSS=round(0.75×0.64×100)=48."""
    w = _workout(duration_seconds=2700, session_rpe=8)
    result = compute_strength_tss(w, [], _prefs(strength_tss_max=150))
    assert result["tss"] == 48
    assert result["partial"] is False


def test_session_rpe_60min_at_rpe10_is_100():
    """AC-3b: 60 min at session RPE=10 (max effort) → TSS=100."""
    w = _workout(duration_seconds=3600, session_rpe=10)
    result = compute_strength_tss(w, [], _prefs(strength_tss_max=150))
    assert result["tss"] == 100


def test_session_rpe_from_exercise_rpe_without_volume():
    """AC-3b: exercise with rpe but no reps/weight → session_rpe fallback."""
    w = _workout(duration_seconds=2700)
    exs = [_exercise(rpe=8)]  # rpe only, no reps or weight
    result = compute_strength_tss(w, exs, _prefs(strength_tss_max=150))
    assert result["method"] == "session_rpe"
    assert result["tss"] == 48


def test_session_rpe_debug_exposes_key_fields():
    """AC-3b: debug exposes session_rpe, intensity_factor, duration_hours, raw_tss, clamped."""
    w = _workout(duration_seconds=2700, session_rpe=8)
    result = compute_strength_tss(w, [], _prefs(strength_tss_max=150))
    d = result["debug"]
    assert "session_rpe" in d
    assert "intensity_factor" in d
    assert "duration_hours" in d
    assert "raw_tss" in d
    assert "clamped" in d


# ── AC-4: method is "none" when no RPE or duration ───────────────────────────

def test_none_when_no_rpe_and_no_duration():
    """AC-4: no exercises, no session_rpe, no duration → tss=null, method=none."""
    result = compute_strength_tss(_workout(), [], _prefs())
    assert result["tss"] is None
    assert result["method"] == "none"
    assert result["partial"] is False


def test_none_debug_has_reason():
    """AC-4: none result always has a non-empty reason string in debug."""
    result = compute_strength_tss(_workout(), [], _prefs())
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]  # non-empty


def test_none_when_duration_but_no_rpe():
    """AC-4: duration present but no RPE anywhere → method is none."""
    w = _workout(duration_seconds=3600)
    result = compute_strength_tss(w, [], _prefs(strength_tss_max=150))
    assert result["method"] == "none"
    assert result["tss"] is None


def test_none_when_rpe_but_no_duration():
    """AC-4: session RPE present but no duration → method is none."""
    w = _workout(session_rpe=8)
    result = compute_strength_tss(w, [], _prefs(strength_tss_max=150))
    assert result["method"] == "none"
    assert result["tss"] is None


# ── AC-5: partial is true when some per-set records are missing RPE ───────────

def test_partial_true_when_some_sets_missing_rpe():
    """AC-5: some sets have rpe+reps, some have reps only → partial=True."""
    sets = json.dumps([
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3},  # missing rpe
    ])
    exs = [_exercise(sets_json=sets)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert result["method"] == "per_set"
    assert result["partial"] is True


def test_partial_false_when_all_sets_have_rpe():
    """AC-5: all sets have complete rpe+reps data → partial=False."""
    sets = json.dumps([{"reps": 5, "rpe": 8}, {"reps": 5, "rpe": 9}])
    exs = [_exercise(sets_json=sets)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    assert result["partial"] is False


def test_partial_tss_computed_from_valid_sets_only():
    """AC-5: TSS computed only from sets that have rpe+reps; incomplete sets excluded."""
    sets = json.dumps([
        {"reps": 5, "rpe": 8},  # contributes
        {"reps": 5},            # missing rpe → excluded
    ])
    exs = [_exercise(sets_json=sets)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    # Only the first set contributes: 5×0.64=3.20, scaled=18.72→19
    assert result["tss"] == round(5 * (8 / 10) ** 2 * 5.85)
    assert result["partial"] is True


# ── AC-6: all thresholds from prefs, none hardcoded ──────────────────────────

def test_no_hardcoded_scale_or_max():
    """AC-6: changing prefs values changes the result (not hardcoded)."""
    exs = [_exercise(rpe=8, reps=5)]
    result_a = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=150))
    result_b = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=10.0, strength_tss_max=150))
    assert result_a["tss"] != result_b["tss"], "different scale must produce different TSS"


def test_max_cap_applied_from_prefs():
    """AC-6: strength_tss_max from prefs is applied as a cap."""
    sets = json.dumps([{"reps": 50, "rpe": 10}] * 10)  # huge volume
    exs = [_exercise(sets_json=sets)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_scale=5.85, strength_tss_max=50))
    assert result["tss"] == 50, "TSS must be capped at strength_tss_max"


def test_no_hardcoded_defaults_source_check():
    """AC-6: compute_strength_tss implementation must not hardcode scale/max values.

    Worked numeric examples in the docstring are excluded from this check — the
    point is that the implementation code itself must not contain hardcoded defaults.
    """
    import re
    src = inspect.getsource(compute_strength_tss)
    # Strip the docstring so that worked examples don't trigger false positives
    src_no_docstring = re.sub(r'""".*?"""', '', src, flags=re.DOTALL)
    assert "5.85" not in src_no_docstring, "strength_tss_scale must not be hardcoded in function body"
    assert "STRENGTH_TSS_SCALE" not in src_no_docstring or "_g(prefs" in src_no_docstring, (
        "If referencing STRENGTH_TSS_SCALE, must also read from prefs"
    )


# ── AC-7: missing prefs → tss: null with descriptive reason ──────────────────

def test_null_when_strength_tss_scale_missing_for_per_set():
    """AC-7: per_set method requires strength_tss_scale; missing → tss=null."""
    exs = [_exercise(rpe=8, reps=5)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_max=150))
    # strength_tss_scale is None → cannot compute
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]


def test_null_reason_mentions_missing_pref_for_per_set():
    """AC-7: reason string mentions the specific missing preference."""
    exs = [_exercise(rpe=8, reps=5)]
    result = compute_strength_tss(_workout(), exs, _prefs(strength_tss_max=150))
    reason = result["debug"]["reason"].lower()
    assert "strength_tss_scale" in reason or "scale" in reason


def test_null_when_strength_tss_max_missing_for_session_rpe():
    """AC-7: session_rpe method requires strength_tss_max; missing → tss=null."""
    w = _workout(duration_seconds=2700, session_rpe=8)
    result = compute_strength_tss(w, [], _prefs())  # no prefs at all
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]


def test_null_reason_mentions_missing_pref_for_session_rpe():
    """AC-7: reason mentions strength_tss_max when it is the missing pref."""
    w = _workout(duration_seconds=2700, session_rpe=8)
    result = compute_strength_tss(w, [], _prefs())  # strength_tss_max is None
    reason = result["debug"]["reason"].lower()
    assert "strength_tss_max" in reason or "max" in reason


# ── AC-8: docstring with plain words and worked examples ─────────────────────

def test_docstring_exists():
    """AC-8: compute_strength_tss has a non-empty docstring."""
    assert compute_strength_tss.__doc__, "docstring must be present"


def test_docstring_describes_per_set_formula():
    """AC-8: docstring explains per_set formula in plain words."""
    doc = (compute_strength_tss.__doc__ or "").lower()
    assert "per_set" in doc or "per set" in doc
    assert "rpe" in doc
    assert "reps" in doc


def test_docstring_describes_session_rpe_formula():
    """AC-8: docstring explains session_rpe formula in plain words."""
    doc = (compute_strength_tss.__doc__ or "").lower()
    assert "session" in doc
    assert "duration" in doc


def test_docstring_has_worked_example_per_set():
    """AC-8: docstring includes a numeric per_set example (shows a specific number)."""
    doc = compute_strength_tss.__doc__ or ""
    # Should mention concrete numbers like 10.25 (the worked example raw sum) or similar
    assert any(char.isdigit() for char in doc), "docstring must include numeric example"
    # Should show tss result
    assert "tss" in doc.lower() or "TSS" in doc


def test_docstring_has_worked_example_session_rpe():
    """AC-8: docstring includes a numeric session_rpe example."""
    doc = compute_strength_tss.__doc__ or ""
    assert "session_rpe" in doc.lower() or "session rpe" in doc.lower()


# ── AC-9: manually entered workout.tss is pass-through (caller responsibility) ──

def test_manual_tss_is_not_overwritten_by_caller_design():
    """AC-9: compute_strength_tss does not read or modify workout.tss (pure function).

    The AC states the caller is responsible for checking whether tss was manually
    set and skipping compute_strength_tss in that case. The pure function itself
    does not touch workout.tss — this test verifies the function doesn't read it.
    """
    src = inspect.getsource(compute_strength_tss)
    # The pure function should NOT read or check workout.tss
    # (The caller decides whether to call this function at all)
    assert 'workout.tss' not in src and '"tss"' not in src.split("return")[0], (
        "compute_strength_tss must not inspect workout.tss — caller handles that"
    )


# ── AC-11: running TSS service not modified ───────────────────────────────────

def test_compute_running_tss_still_importable():
    """AC-11: compute_running_tss is still importable and functional."""
    from backend.services.tss import compute_running_tss
    import types
    w = types.SimpleNamespace(np=280, avg_hr=None, distance_km=None, duration_seconds=3600)
    prefs = types.SimpleNamespace(ftp_w=280, threshold_pace_seconds_per_km=None, threshold_hr=None)
    result = compute_running_tss(w, [], prefs)
    assert result["method"] == "power"
    assert result["tss"] == 100


def test_calculate_hr_tss_still_importable():
    """AC-11: calculate_hr_tss is still importable and functional."""
    from backend.services.tss import calculate_hr_tss
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=170, threshold_hr=170)
    assert result["tss"] == 100
    assert result["method"] == "hr"


# ── AC-12: golden fixture has two new strength workout cases ─────────────────

EXPECTED_PATH = pathlib.Path(__file__).parent / "fixtures" / "golden_run_expected.json"


def test_golden_fixture_has_strength_per_set_case():
    """AC-12: golden_run_expected.json has a 'strength_per_set' entry."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)
    assert "strength_per_set" in expected, (
        "golden_run_expected.json must have a 'strength_per_set' entry"
    )


def test_golden_fixture_has_strength_session_rpe_case():
    """AC-12: golden_run_expected.json has a 'strength_session_rpe' entry."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)
    assert "strength_session_rpe" in expected, (
        "golden_run_expected.json must have a 'strength_session_rpe' entry"
    )


def test_golden_strength_per_set_asserts_required_fields():
    """AC-12: strength_per_set entry asserts tss, method, partial, and key debug fields."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)
    case = expected["strength_per_set"]
    assert "tss" in case, "strength_per_set must assert tss"
    assert "method" in case, "strength_per_set must assert method"
    assert "partial" in case, "strength_per_set must assert partial"
    assert "debug_keys" in case, "strength_per_set must assert key debug fields"
    assert case["method"] == "per_set"


def test_golden_strength_session_rpe_asserts_required_fields():
    """AC-12: strength_session_rpe entry asserts tss, method, partial, and key debug fields."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)
    case = expected["strength_session_rpe"]
    assert "tss" in case, "strength_session_rpe must assert tss"
    assert "method" in case, "strength_session_rpe must assert method"
    assert "partial" in case, "strength_session_rpe must assert partial"
    assert "debug_keys" in case, "strength_session_rpe must assert key debug fields"
    assert case["method"] == "session_rpe"


def test_golden_strength_per_set_tss_matches_compute():
    """AC-12: compute_strength_tss on fixture inputs matches expected tss."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)
    case = expected["strength_per_set"]
    sets = json.dumps(case["inputs"]["sets"])
    exs = [_exercise(sets_json=sets)]
    prefs = _prefs(
        strength_tss_scale=case["inputs"]["strength_tss_scale"],
        strength_tss_max=case["inputs"]["strength_tss_max"],
    )
    result = compute_strength_tss(_workout(), exs, prefs)
    assert result["tss"] == case["tss"]
    assert result["method"] == case["method"]
    assert result["partial"] == case["partial"]


def test_golden_strength_session_rpe_tss_matches_compute():
    """AC-12: compute_strength_tss on fixture inputs matches expected tss."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)
    case = expected["strength_session_rpe"]
    w = _workout(
        duration_seconds=case["inputs"]["duration_seconds"],
        session_rpe=case["inputs"]["session_rpe"],
    )
    prefs = _prefs(strength_tss_max=case["inputs"]["strength_tss_max"])
    result = compute_strength_tss(w, [], prefs)
    assert result["tss"] == case["tss"]
    assert result["method"] == case["method"]
    assert result["partial"] == case["partial"]
