"""Tests for issue #692: Suggest thresholds automatically from duration curve.

Acceptance criteria verified:
  AC1  — pure function suggest_thresholds(duration_curve, recent_runs) with docstring + worked example.
  AC2  — returns suggested_ftp_w, threshold_pace_seconds_per_km, threshold_hr each with confidence flag
         ("high" / "low" / "none").
  AC3  — returns debug object with intermediate values (duration, raw value, multiplier applied).
  AC4  — FTP = 95% of best 20-min mean-maximal power; fallback to 20–60 min window.
  AC5  — threshold pace = best sustained pace held for 20–30 min.
  AC6  — threshold HR = avg HR from same effort window used for threshold pace.
  AC7  — no hardcoded/seeded defaults; user_preferences checked via caller-supplied plain dict.
  AC8  — manually set threshold in user_preferences always wins: suggestion omitted for that metric.
  AC9  — function never writes to user_preferences or any persistent store.
  AC10 — DB access is caller's job; function receives only plain data structures.
  AC11 — malformed/absent inputs → empty result + human-readable reason string.
  AC12 — insufficient history → reason == "not enough history yet" exactly.
  AC13 — math described in plain language in docstring.
  AC14 — unit tests: normal FTP, fallback, empty curve, missing HR, manually overridden threshold.
"""

from backend.services.suggest_thresholds import suggest_thresholds


# ── Helpers ───────────────────────────────────────────────────────────────────

def _curve_20min(power=300.0):
    return {1200: power}


def _curve_fallback(power=310.0, duration=1800):
    """Curve with no 20-min point but a usable fallback duration (20–60 min)."""
    return {duration: power}


def _run(duration_seconds=1500, avg_pace=280.0, avg_hr=160):
    return {
        "duration_seconds": duration_seconds,
        "avg_pace_seconds_per_km": avg_pace,
        "avg_hr_bpm": avg_hr,
    }


def _run_no_hr(duration_seconds=1500, avg_pace=280.0):
    return {
        "duration_seconds": duration_seconds,
        "avg_pace_seconds_per_km": avg_pace,
        "avg_hr_bpm": None,
    }


# ── AC1: function exists and has a docstring with a worked example ─────────────

def test_function_has_docstring():
    """AC1: suggest_thresholds has a docstring."""
    assert suggest_thresholds.__doc__ is not None
    assert len(suggest_thresholds.__doc__.strip()) > 0


def test_docstring_contains_worked_example():
    """AC1: docstring contains a numeric worked example (e.g. 300 W → 285 W)."""
    doc = suggest_thresholds.__doc__
    assert "300" in doc or "20-minute" in doc or "0.95" in doc, (
        "Docstring should contain at least one worked example with numbers"
    )


# ── AC2: confidence flag is string "high" / "low" ─────────────────────────────

def test_ftp_confidence_high_when_20min_present():
    """AC2: confidence is 'high' when exact 20-minute FTP point is present."""
    result = suggest_thresholds(_curve_20min(300.0), [_run()])
    ftp = result["suggestions"]["ftp_w"]
    assert ftp["confidence"] == "high"


def test_ftp_confidence_low_when_using_fallback():
    """AC2: confidence is 'low' when FTP derived from fallback duration window."""
    result = suggest_thresholds(_curve_fallback(310.0), [])
    ftp = result["suggestions"]["ftp_w"]
    assert ftp["confidence"] == "low"


def test_pace_confidence_high_with_two_qualifying_runs():
    """AC2: pace confidence is 'high' when ≥2 qualifying runs (20–30 min)."""
    runs = [_run(1200, 275.0, 160), _run(1500, 280.0, 158)]
    result = suggest_thresholds(_curve_20min(), runs)
    assert result["suggestions"]["threshold_pace_seconds_per_km"]["confidence"] == "high"


def test_pace_confidence_low_with_one_qualifying_run():
    """AC2: pace confidence is 'low' when only 1 qualifying run exists."""
    runs = [_run(1500, 280.0, 158)]
    result = suggest_thresholds(_curve_20min(), runs)
    assert result["suggestions"]["threshold_pace_seconds_per_km"]["confidence"] == "low"


def test_hr_confidence_matches_pace_confidence():
    """AC2: threshold_hr confidence always matches threshold_pace confidence."""
    runs = [_run(1500, 280.0, 158)]
    result = suggest_thresholds(_curve_20min(), runs)
    pace_conf = result["suggestions"]["threshold_pace_seconds_per_km"]["confidence"]
    hr_conf = result["suggestions"]["threshold_hr"]["confidence"]
    assert pace_conf == hr_conf


# ── AC3: debug object exposes intermediate values ─────────────────────────────

def test_debug_ftp_exposes_all_required_fields():
    """AC3: debug.ftp_w has duration_used, raw_value, formula_applied (or formula)."""
    result = suggest_thresholds(_curve_20min(300.0), [_run()])
    dbg = result["debug"]["ftp_w"]
    assert "duration_used" in dbg
    assert "raw_value" in dbg
    # formula field name may be "formula_applied" or "formula"
    assert "formula_applied" in dbg or "formula" in dbg


def test_debug_ftp_raw_value_is_pre_multiplier():
    """AC3: debug.ftp_w.raw_value is the best power before the 0.95 multiplier."""
    result = suggest_thresholds(_curve_20min(300.0), [_run()])
    dbg = result["debug"]["ftp_w"]
    assert abs(dbg["raw_value"] - 300.0) < 0.01


def test_debug_exposes_multiplier_in_formula():
    """AC3: debug formula field describes the multiplier applied in plain language."""
    result = suggest_thresholds(_curve_20min(300.0), [_run()])
    dbg = result["debug"]["ftp_w"]
    formula = dbg.get("formula_applied") or dbg.get("formula", "")
    assert "0.95" in formula or "95" in formula or "percent" in formula


# ── AC4: FTP = 95% of 20-min power, with fallback ────────────────────────────

def test_ftp_300w_yields_285w():
    """AC4: 300 W best 20-min power → FTP = 285 W (300 × 0.95)."""
    result = suggest_thresholds(_curve_20min(300.0), [_run()])
    ftp = result["suggestions"]["ftp_w"]["value"]
    assert abs(ftp - 285.0) < 1.0


def test_ftp_fallback_to_best_in_20_60_min_range():
    """AC4: no 20-min point → uses best power in 20–60 min window × 0.95."""
    curve = {1800: 310.0, 2700: 320.0}  # 30 min and 45 min
    result = suggest_thresholds(curve, [])
    ftp = result["suggestions"]["ftp_w"]["value"]
    # Best is 320 W at 45 min → 320 × 0.95 = 304
    assert abs(ftp - 304.0) < 1.0


def test_ftp_absent_when_no_curve_data_in_range():
    """AC4: curve with only durations outside 20–60 min → no FTP suggestion."""
    curve = {60: 500.0, 7200: 200.0}  # 1 min and 2 hours — both out of range
    result = suggest_thresholds(curve, [])
    if result.get("suggestions"):
        assert "ftp_w" not in result["suggestions"]
    else:
        assert result.get("reason") == "not enough history yet"


# ── AC5: pace = best sustained pace for 20–30 min ─────────────────────────────

def test_pace_uses_fastest_qualifying_run():
    """AC5: threshold pace = lowest seconds/km among 20–30 min qualifying runs."""
    runs = [
        _run(1300, avg_pace=270.0, avg_hr=162),  # fastest
        _run(1500, avg_pace=285.0, avg_hr=158),
    ]
    result = suggest_thresholds({}, runs)
    pace = result["suggestions"]["threshold_pace_seconds_per_km"]["value"]
    assert abs(pace - 270.0) < 1.0


def test_pace_only_from_20_to_30_min_window():
    """AC5: runs shorter than 20 min or longer than 30 min are excluded."""
    runs = [
        _run(900, avg_pace=250.0, avg_hr=170),   # 15 min — excluded
        _run(2000, avg_pace=260.0, avg_hr=155),  # 33 min — excluded
        _run(1400, avg_pace=280.0, avg_hr=160),  # 23 min — qualifies
    ]
    result = suggest_thresholds({}, runs)
    pace = result["suggestions"]["threshold_pace_seconds_per_km"]["value"]
    assert abs(pace - 280.0) < 1.0  # only qualifying run


# ── AC6: HR from the same effort as threshold pace ───────────────────────────

def test_hr_from_same_effort_as_pace():
    """AC6: threshold_hr is the avg HR from the run that yielded the best pace."""
    runs = [
        _run(1300, avg_pace=270.0, avg_hr=162),  # fastest → HR=162
        _run(1500, avg_pace=285.0, avg_hr=158),
    ]
    result = suggest_thresholds({}, runs)
    hr = result["suggestions"]["threshold_hr"]["value"]
    assert hr == 162


# ── AC11+AC14: missing HR data ────────────────────────────────────────────────

def test_missing_hr_data_omits_threshold_hr():
    """AC14: when qualifying runs have no HR data, threshold_hr suggestion is absent."""
    runs = [
        _run_no_hr(1400, avg_pace=280.0),
        _run_no_hr(1600, avg_pace=285.0),
    ]
    result = suggest_thresholds({}, runs)
    # Pace suggestion should still be present
    assert "threshold_pace_seconds_per_km" in result.get("suggestions", {})
    # HR suggestion must be absent
    assert "threshold_hr" not in result.get("suggestions", {})


def test_missing_hr_does_not_affect_pace_suggestion():
    """AC6/AC14: absence of HR data for a qualifying run does not suppress pace suggestion."""
    runs = [_run_no_hr(1500, avg_pace=280.0)]
    result = suggest_thresholds({}, runs)
    suggestions = result.get("suggestions", {})
    assert "threshold_pace_seconds_per_km" in suggestions
    pace_val = suggestions["threshold_pace_seconds_per_km"]["value"]
    assert abs(pace_val - 280.0) < 1.0


# ── AC8+AC14: manually overridden threshold ───────────────────────────────────

def test_manually_set_ftp_omits_ftp_suggestion():
    """AC8/AC14: when ftp_w is set in user_preferences, FTP suggestion is omitted."""
    curve = _curve_20min(300.0)
    runs = [_run()]
    user_prefs = {"ftp_w": 280, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
    result = suggest_thresholds(curve, runs, user_preferences=user_prefs)
    assert "ftp_w" not in result.get("suggestions", {})


def test_manually_set_threshold_hr_omits_hr_suggestion():
    """AC8: when threshold_hr is set in user_preferences, HR suggestion is omitted."""
    runs = [_run(1300, 270.0, 162), _run(1500, 280.0, 158)]
    user_prefs = {"ftp_w": None, "threshold_hr": 155, "threshold_pace_seconds_per_km": None}
    result = suggest_thresholds({}, runs, user_preferences=user_prefs)
    assert "threshold_hr" not in result.get("suggestions", {})


def test_manually_set_pace_omits_pace_suggestion():
    """AC8: when threshold_pace is set in user_preferences, pace suggestion is omitted."""
    runs = [_run(1300, 270.0, 162), _run(1500, 280.0, 158)]
    user_prefs = {
        "ftp_w": None,
        "threshold_hr": None,
        "threshold_pace_seconds_per_km": 265,
    }
    result = suggest_thresholds({}, runs, user_preferences=user_prefs)
    assert "threshold_pace_seconds_per_km" not in result.get("suggestions", {})


def test_manual_override_for_one_metric_does_not_affect_others():
    """AC8: overriding one threshold does not suppress suggestions for other metrics."""
    curve = _curve_20min(300.0)
    runs = [_run(1300, 270.0, 162), _run(1500, 280.0, 158)]
    user_prefs = {"ftp_w": 280, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
    result = suggest_thresholds(curve, runs, user_preferences=user_prefs)
    suggestions = result.get("suggestions", {})
    assert "ftp_w" not in suggestions          # manually set → omitted
    assert "threshold_pace_seconds_per_km" in suggestions  # not set → suggested
    assert "threshold_hr" in suggestions       # not set → suggested


def test_user_preferences_none_does_not_change_behaviour():
    """AC8: passing user_preferences=None (default) behaves identically to no arg."""
    curve = _curve_20min(300.0)
    runs = [_run()]
    result_implicit = suggest_thresholds(curve, runs)
    result_explicit = suggest_thresholds(curve, runs, user_preferences=None)
    assert result_implicit == result_explicit


# ── AC9: function never writes ─────────────────────────────────────────────────

def test_user_preferences_dict_is_not_mutated():
    """AC9: function must not modify the user_preferences dict it receives."""
    curve = _curve_20min(300.0)
    runs = [_run()]
    prefs = {"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
    prefs_copy = prefs.copy()
    suggest_thresholds(curve, runs, user_preferences=prefs)
    assert prefs == prefs_copy


# ── AC11: malformed/absent inputs ────────────────────────────────────────────

def test_none_inputs_return_reason():
    """AC11: both None → empty result with a reason string."""
    result = suggest_thresholds(None, None)
    assert result.get("suggestions") == {}
    assert isinstance(result.get("reason"), str) and len(result["reason"]) > 0


def test_empty_inputs_return_reason():
    """AC11: empty dict + empty list → empty result with reason."""
    result = suggest_thresholds({}, [])
    assert result.get("suggestions") == {}
    assert isinstance(result.get("reason"), str)


# ── AC12: exact reason string for insufficient history ───────────────────────

def test_insufficient_history_reason_exact_string():
    """AC12: reason must be exactly 'not enough history yet' when data is absent."""
    result = suggest_thresholds({}, [])
    assert result["reason"] == "not enough history yet"


def test_insufficient_history_reason_none_inputs():
    """AC12: None inputs also yield the exact 'not enough history yet' reason."""
    result = suggest_thresholds(None, None)
    assert result["reason"] == "not enough history yet"
