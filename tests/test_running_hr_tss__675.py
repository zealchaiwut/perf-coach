"""Tests for issue #675: Add pure HR-based TSS calculation function.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria covered:
  AC-1  — Pure function: no side effects, no DB access (static analysis)
  AC-2  — threshold_hr comes from caller; no hardcoded defaults
  AC-3  — Per-lap sum-of-contributions used when laps carry avg_hr
  AC-4  — intensity_factor = avg_hr / threshold_hr
  AC-5  — tss = (duration_seconds / 3600) × IF² × 100
  AC-6  — Returned tss is a whole integer
  AC-7  — Null + reason when threshold_hr or avg_hr is missing OR ZERO
  AC-8  — Return shape: { tss, method, debug: { intensity_factor, avg_hr_used,
           threshold_hr, duration_seconds } }
  AC-9  — method is "hr" on success, "none" on null
  AC-10 — Docstring includes 60-min-at-threshold worked example → TSS = 100
  AC-11 — Unit tests: (a) 60-min at threshold → 100, (b) missing threshold_hr,
           (c) missing avg_hr, (d) per-lap avg_hr used, (e) result is integer
"""
import inspect
import types

import pytest

from backend.services.tss import calculate_hr_tss


# ── AC-11a / AC-10: 60-minute at exactly threshold HR → tss=100 ──────────────

def test_60_min_at_threshold_yields_100():
    """AC-11a, AC-10: docstring worked example — 60 min at threshold HR, TSS = 100."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=160)
    assert result["tss"] == 100
    assert result["method"] == "hr"
    assert isinstance(result["tss"], int)


def test_60_min_at_threshold_yields_100_canonical():
    """AC-11a: worked example with threshold_hr=160 explicit in issue body."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=160)
    assert result["tss"] == 100


# ── AC-11b: missing threshold_hr → null + reason ─────────────────────────────

def test_null_when_threshold_hr_missing():
    """AC-11b: threshold_hr=None → tss=None, method='none', reason in debug."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=None)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]


# ── AC-7 (zero threshold_hr): null + reason for zero ────────────────────────

def test_null_when_threshold_hr_is_zero():
    """AC-7: threshold_hr=0 is treated as missing — must return null, not divide by zero."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=0)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]


# ── AC-11c: missing avg_hr → null + reason ────────────────────────────────────

def test_null_when_avg_hr_missing():
    """AC-11c: avg_hr=None and no per-lap HR → tss=None, method='none', reason in debug."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=None, threshold_hr=160)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]


# ── AC-7 (zero avg_hr): null + reason for zero avg_hr ────────────────────────

def test_null_when_avg_hr_is_zero():
    """AC-7: avg_hr=0 is treated as missing — must return null, not produce tss=0."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=0, threshold_hr=160)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]


# ── AC-11d: per-lap avg_hr used when laps are present ────────────────────────

def test_per_lap_avg_hr_used_when_laps_present():
    """AC-11d: all laps have avg_hr → per-lap contributions are used, not workout-level avg_hr."""
    # Workout avg_hr is a deliberately wrong sentinel; per-lap values are the truth.
    laps = [
        types.SimpleNamespace(duration_seconds=1800, avg_hr=160),
        types.SimpleNamespace(duration_seconds=1800, avg_hr=160),
    ]
    result = calculate_hr_tss(
        duration_seconds=3600, avg_hr=999, threshold_hr=160, laps=laps
    )
    # Each lap: (1800/3600) × (160/160)² × 100 = 50; sum = 100
    assert result["tss"] == 100
    assert result["method"] == "hr"


def test_per_lap_contributions_summed_not_weighted_avg():
    """AC-3: per-lap TSS is summed, not computed from a single weighted-avg HR.

    With asymmetric laps the two approaches can differ when IF is non-linear
    (squared). Verify the sum-of-contributions path is used.
    """
    threshold = 160
    # Lap 1: 900s at 120bpm (low effort)
    # Lap 2: 2700s at 180bpm (high effort)
    laps = [
        types.SimpleNamespace(duration_seconds=900, avg_hr=120),
        types.SimpleNamespace(duration_seconds=2700, avg_hr=180),
    ]
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=0, threshold_hr=threshold, laps=laps)

    # Per-lap sum-of-contributions:
    #   lap1: (900/3600) × (120/160)² × 100 = 0.25 × 0.5625 × 100 = 14.0625
    #   lap2: (2700/3600) × (180/160)² × 100 = 0.75 × 1.265625 × 100 = 94.921875
    #   sum = 108.984375 → round = 109
    expected = round(
        (900 / 3600) * (120 / 160) ** 2 * 100
        + (2700 / 3600) * (180 / 160) ** 2 * 100
    )
    assert result["tss"] == expected
    assert result["method"] == "hr"


# ── AC-11e: result is a whole integer ─────────────────────────────────────────

def test_result_is_integer():
    """AC-11e: tss is always an int, never a float."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=160)
    assert isinstance(result["tss"], int)


def test_result_is_integer_fractional_case():
    """AC-6, AC-11e: non-round TSS is returned as int (rounded)."""
    # 30 min at 80% of threshold → tss = 0.5 × 0.64 × 100 = 32.0 (exact)
    result = calculate_hr_tss(duration_seconds=1800, avg_hr=128, threshold_hr=160)
    assert isinstance(result["tss"], int)
    assert result["tss"] == 32


# ── AC-4: intensity_factor = avg_hr / threshold_hr ───────────────────────────

def test_intensity_factor_formula():
    """AC-4: intensity_factor reported in debug equals avg_hr / threshold_hr."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=144, threshold_hr=160)
    assert result["debug"]["intensity_factor"] == pytest.approx(144 / 160)


# ── AC-5: TSS formula ─────────────────────────────────────────────────────────

def test_tss_formula_correctness():
    """AC-5: tss = (duration_seconds / 3600) × IF² × 100, rounded to int."""
    duration = 5400  # 90 minutes
    avg_hr = 152
    threshold_hr = 160
    if_val = avg_hr / threshold_hr
    expected = round((duration / 3600) * if_val ** 2 * 100)
    result = calculate_hr_tss(duration_seconds=duration, avg_hr=avg_hr, threshold_hr=threshold_hr)
    assert result["tss"] == expected


# ── AC-8: return shape ────────────────────────────────────────────────────────

def test_debug_has_avg_hr_used_key():
    """AC-8: debug contains avg_hr_used on success."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=160)
    assert "avg_hr_used" in result["debug"]


def test_debug_has_threshold_hr_key():
    """AC-8: debug contains threshold_hr on success."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=160)
    assert "threshold_hr" in result["debug"]
    assert result["debug"]["threshold_hr"] == 160


def test_debug_has_duration_seconds_key():
    """AC-8: debug contains duration_seconds on success."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=160)
    assert "duration_seconds" in result["debug"]
    assert result["debug"]["duration_seconds"] == 3600


def test_debug_has_intensity_factor_key():
    """AC-8: debug contains intensity_factor on success."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=160)
    assert "intensity_factor" in result["debug"]


def test_debug_shape_on_null_result():
    """AC-8: debug keys also present on null results."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=None)
    assert "intensity_factor" in result["debug"]
    assert "duration_seconds" in result["debug"]


# ── AC-9: method values ───────────────────────────────────────────────────────

def test_method_is_hr_on_success():
    """AC-9: method = 'hr' when TSS is computed."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=160)
    assert result["method"] == "hr"


def test_method_is_none_when_threshold_missing():
    """AC-9: method = 'none' when threshold_hr is absent."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=None)
    assert result["method"] == "none"


def test_method_is_none_when_avg_hr_missing():
    """AC-9: method = 'none' when avg_hr is absent."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=None, threshold_hr=160)
    assert result["method"] == "none"


# ── AC-1: pure function (static analysis) ────────────────────────────────────

def test_function_has_no_db_access():
    """AC-1: calculate_hr_tss source contains no DB-related identifiers."""
    src = inspect.getsource(calculate_hr_tss)
    for forbidden in ("db.", "session.", "execute(", "fetchone(", "fetchall(", "query("):
        assert forbidden not in src, f"DB access found: {forbidden!r}"


# ── AC-2: no hardcoded threshold_hr defaults ─────────────────────────────────

def test_no_hardcoded_threshold_hr_default():
    """AC-2: when threshold_hr=None, function returns null — no internal default applied."""
    result = calculate_hr_tss(duration_seconds=3600, avg_hr=160, threshold_hr=None)
    assert result["tss"] is None, "Must not fall back to a hardcoded threshold_hr value"


# ── AC-10: docstring worked example ──────────────────────────────────────────

def test_docstring_contains_60_min_at_threshold_example():
    """AC-10: docstring includes the 60-minute-at-threshold worked example (→ TSS = 100)."""
    doc = calculate_hr_tss.__doc__ or ""
    assert "60" in doc and "100" in doc
    assert "1.0" in doc or "threshold" in doc.lower()
