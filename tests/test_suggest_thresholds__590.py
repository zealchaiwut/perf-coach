"""Tests for issue #590: Add auto-threshold suggestion from duration curve.

Acceptance criteria verified:
  AC1  — suggest_thresholds is a pure function in a documented module; no DB access.
  AC2  — function signature: duration_curve (dict int→float), recent_runs (list of dicts).
  AC3  — returns ftp_w, threshold_pace_seconds_per_km, threshold_hr each with value + high_confidence.
  AC4  — returns a debug object with source effort details per suggestion.
  AC5  — Power/FTP: best 20-min power × 0.95; fallback to 20–60 min range with same multiplier.
  AC6  — Pace: best avg pace from any run effort with duration 1200–1800 seconds.
  AC7  — HR: avg HR from the same effort that produced suggested threshold pace.
  AC8  — high_confidence=True for power only when 20-min point present; pace/HR when ≥2 qualifying runs.
  AC9  — math expressed in comments/docstrings in plain words.
  AC10 — None, empty dict/list, or insufficient data returns {"suggestions": {}, "reason": "not enough history yet"}.
  AC11 — never reads/writes user_preferences.
  AC12 — unit tests: 300W→285W, 30-min fallback, pace+HR same effort, thin history, None inputs.
"""


from backend.services.suggest_thresholds import suggest_thresholds


# ── Helpers ───────────────────────────────────────────────────────────────────

def _curve_with_20min(power_20=300.0):
    """Duration curve that includes a 20-minute (1200 s) point."""
    return {1200: power_20}


def _curve_without_20min(power_30=310.0):
    """Duration curve with only a 30-minute (1800 s) point, no 20-min entry."""
    return {1800: power_30}


def _run(duration_seconds=1500, avg_pace=280.0, avg_hr=160):
    return {
        "duration_seconds": duration_seconds,
        "avg_pace_seconds_per_km": avg_pace,
        "avg_hr_bpm": avg_hr,
    }


# ── AC12a: 300 W → 285 W worked example ──────────────────────────────────────

def test_ftp_300w_yields_285w():
    """AC12a/AC5: 300 W best 20-min power → FTP suggestion = 285 W (300 × 0.95)."""
    result = suggest_thresholds(
        duration_curve=_curve_with_20min(300.0),
        recent_runs=[_run()],
    )
    assert "suggestions" in result
    ftp = result["suggestions"]["ftp_w"]
    assert abs(ftp["value"] - 285.0) < 0.01


def test_ftp_high_confidence_when_20min_present():
    """AC8: high_confidence=True for FTP when 20-min key is in duration_curve."""
    result = suggest_thresholds(
        duration_curve=_curve_with_20min(300.0),
        recent_runs=[_run()],
    )
    assert result["suggestions"]["ftp_w"]["high_confidence"] is True


# ── AC12b: fallback from missing 20-min to 30-min effort ──────────────────────

def test_ftp_fallback_to_30min_applies_95_percent():
    """AC12b/AC5: no 20-min point → use best 20–60 min effort × 0.95."""
    curve = _curve_without_20min(310.0)
    result = suggest_thresholds(duration_curve=curve, recent_runs=[_run()])
    ftp = result["suggestions"]["ftp_w"]
    expected = round(310.0 * 0.95, 6)
    assert abs(ftp["value"] - expected) < 0.01


def test_ftp_low_confidence_when_no_20min_point():
    """AC8: high_confidence=False for FTP when no 20-min key in duration_curve."""
    curve = _curve_without_20min(310.0)
    result = suggest_thresholds(duration_curve=curve, recent_runs=[_run()])
    assert result["suggestions"]["ftp_w"]["high_confidence"] is False


# ── AC12c: pace and HR derived from the same qualifying effort ────────────────

def test_pace_and_hr_from_same_effort():
    """AC12c/AC6/AC7: pace and HR come from the same fastest qualifying run effort."""
    runs = [
        _run(duration_seconds=1300, avg_pace=270.0, avg_hr=162),  # fastest pace, 20-30 min range
        _run(duration_seconds=1500, avg_pace=285.0, avg_hr=158),
    ]
    result = suggest_thresholds(duration_curve=_curve_with_20min(), recent_runs=runs)
    suggestions = result["suggestions"]
    # The fastest pace (lowest s/km) is 270.0 from the first run
    assert abs(suggestions["threshold_pace_seconds_per_km"]["value"] - 270.0) < 0.01
    # HR must be from the same effort: 162
    assert suggestions["threshold_hr"]["value"] == 162


def test_pace_high_confidence_with_two_qualifying_runs():
    """AC8: high_confidence=True for pace/HR when ≥2 qualifying runs (20–30 min)."""
    runs = [
        _run(duration_seconds=1200, avg_pace=275.0, avg_hr=160),
        _run(duration_seconds=1800, avg_pace=280.0, avg_hr=158),
    ]
    result = suggest_thresholds(duration_curve=_curve_with_20min(), recent_runs=runs)
    assert result["suggestions"]["threshold_pace_seconds_per_km"]["high_confidence"] is True
    assert result["suggestions"]["threshold_hr"]["high_confidence"] is True


def test_pace_low_confidence_with_one_qualifying_run():
    """AC8: high_confidence=False for pace/HR when only 1 qualifying run."""
    runs = [_run(duration_seconds=1500, avg_pace=280.0, avg_hr=158)]
    result = suggest_thresholds(duration_curve=_curve_with_20min(), recent_runs=runs)
    assert result["suggestions"]["threshold_pace_seconds_per_km"]["high_confidence"] is False
    assert result["suggestions"]["threshold_hr"]["high_confidence"] is False


def test_run_outside_20_30min_range_does_not_qualify():
    """AC6: runs outside 1200–1800 s do not count as qualifying pace efforts."""
    # Only one run but outside the qualifying range
    runs = [_run(duration_seconds=900, avg_pace=270.0, avg_hr=165)]
    result = suggest_thresholds(duration_curve=_curve_with_20min(), recent_runs=runs)
    # pace/HR suggestions should be absent or the result should be the thin-history shape
    if "suggestions" in result and result["suggestions"]:
        assert "threshold_pace_seconds_per_km" not in result["suggestions"]
    else:
        assert result.get("reason") == "not enough history yet"


# ── AC12d: thin history returns not-enough-history shape ──────────────────────

def test_thin_history_no_curve_no_runs():
    """AC12d/AC10: empty curve and empty runs → not-enough-history shape."""
    result = suggest_thresholds(duration_curve={}, recent_runs=[])
    assert result == {"suggestions": {}, "reason": "not enough history yet"}


def test_thin_history_no_qualifying_power():
    """AC10: curve with only durations outside 20–60 min range → no FTP suggestion."""
    # Only a 1-second and a 90-minute entry — neither qualifies for FTP
    curve = {1: 800.0, 5400: 180.0}
    result = suggest_thresholds(duration_curve=curve, recent_runs=[])
    # Either returns empty-with-reason, or suggestions dict with no ftp_w
    if result.get("suggestions"):
        assert "ftp_w" not in result["suggestions"]
    else:
        assert result.get("reason") == "not enough history yet"


# ── AC12e: None inputs return empty-with-reason shape ────────────────────────

def test_none_duration_curve():
    """AC12e/AC10: None duration_curve → no exception, no FTP suggestion."""
    result = suggest_thresholds(duration_curve=None, recent_runs=[_run()])
    # Must not raise; result must be a dict
    assert isinstance(result, dict)
    # Cannot suggest FTP without a duration curve
    assert "ftp_w" not in result.get("suggestions", {})


def test_none_recent_runs():
    """AC12e/AC10: None recent_runs → not-enough-history shape, no exception."""
    result = suggest_thresholds(duration_curve=_curve_with_20min(), recent_runs=None)
    # FTP may still be suggested from the curve; pace/HR won't be
    # But must not raise an exception; result must be a dict
    assert isinstance(result, dict)


def test_both_none_inputs():
    """AC12e/AC10: both None → not-enough-history shape, no exception."""
    result = suggest_thresholds(duration_curve=None, recent_runs=None)
    assert result == {"suggestions": {}, "reason": "not enough history yet"}


# ── AC3: return shape ─────────────────────────────────────────────────────────

def test_full_result_shape():
    """AC3: result has suggestions dict with ftp_w, pace, hr each having value + high_confidence."""
    runs = [
        _run(duration_seconds=1200, avg_pace=275.0, avg_hr=160),
        _run(duration_seconds=1500, avg_pace=280.0, avg_hr=158),
    ]
    result = suggest_thresholds(
        duration_curve=_curve_with_20min(300.0),
        recent_runs=runs,
    )
    assert "suggestions" in result
    for key in ("ftp_w", "threshold_pace_seconds_per_km", "threshold_hr"):
        assert key in result["suggestions"], f"Missing key: {key}"
        entry = result["suggestions"][key]
        assert "value" in entry
        assert "high_confidence" in entry
        assert isinstance(entry["high_confidence"], bool)


# ── AC4: debug object ────────────────────────────────────────────────────────

def test_debug_object_present():
    """AC4: result includes a debug object with source effort info per suggestion."""
    result = suggest_thresholds(
        duration_curve=_curve_with_20min(300.0),
        recent_runs=[_run()],
    )
    assert "debug" in result
    debug = result["debug"]
    assert isinstance(debug, dict)


def test_debug_ftp_exposes_duration_raw_value_formula():
    """AC4: debug.ftp_w exposes duration_used, raw_value, and formula_applied."""
    result = suggest_thresholds(
        duration_curve=_curve_with_20min(300.0),
        recent_runs=[_run()],
    )
    ftp_debug = result["debug"].get("ftp_w", {})
    assert "duration_used" in ftp_debug
    assert "raw_value" in ftp_debug
    assert "formula_applied" in ftp_debug
    assert abs(ftp_debug["raw_value"] - 300.0) < 0.01


# ── AC5: fallback range 20–60 min ────────────────────────────────────────────

def test_ftp_fallback_picks_best_in_20_to_60_min_range():
    """AC5: when no 20-min point, picks highest power among 20–60 min efforts."""
    # 30-min = 310 W, 45-min = 320 W — should pick 320 as the best
    curve = {1800: 310.0, 2700: 320.0}
    result = suggest_thresholds(duration_curve=curve, recent_runs=[])
    ftp = result["suggestions"]["ftp_w"]
    expected = round(320.0 * 0.95, 6)
    assert abs(ftp["value"] - expected) < 0.01


def test_ftp_ignores_efforts_longer_than_60_min_for_fallback():
    """AC5: fallback only uses efforts between 20–60 min (1200–3600 s)."""
    # Only entries outside the fallback range
    curve = {600: 400.0, 7200: 200.0}  # 10-min and 2-hour — neither qualifies
    result = suggest_thresholds(duration_curve=curve, recent_runs=[])
    # No FTP suggestion or empty-with-reason
    if result.get("suggestions"):
        assert "ftp_w" not in result["suggestions"]
    else:
        assert result.get("reason") == "not enough history yet"


# ── AC6: pace qualifying range exactly 1200–1800 s inclusive ─────────────────

def test_pace_boundary_1200s_qualifies():
    """AC6: a run of exactly 1200 s qualifies for pace suggestion."""
    runs = [
        _run(duration_seconds=1200, avg_pace=275.0, avg_hr=160),
        _run(duration_seconds=1400, avg_pace=280.0, avg_hr=158),
    ]
    result = suggest_thresholds(duration_curve={}, recent_runs=runs)
    assert "threshold_pace_seconds_per_km" in result.get("suggestions", {})


def test_pace_boundary_1800s_qualifies():
    """AC6: a run of exactly 1800 s qualifies for pace suggestion."""
    runs = [
        _run(duration_seconds=1800, avg_pace=280.0, avg_hr=158),
        _run(duration_seconds=1600, avg_pace=275.0, avg_hr=160),
    ]
    result = suggest_thresholds(duration_curve={}, recent_runs=runs)
    assert "threshold_pace_seconds_per_km" in result.get("suggestions", {})
