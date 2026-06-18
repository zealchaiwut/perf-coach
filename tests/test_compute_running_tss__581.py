"""Tests for issue #581: compute_running_tss with priority-based method selection.

Each test anchored to a specific acceptance criterion.

Acceptance criteria:
  AC1  - function exists and is exported from backend.services.tss
  AC2  - return value has exactly four keys: tss, method, partial, debug
  AC3  - tss is integer when computable, null otherwise
  AC4  - method is "power"|"pace"|"hr"|"none"; "none" only when tss is null
  AC5  - partial is True when method succeeded from incomplete data; False otherwise
  AC6  - debug lists every method attempted with human-readable skip reason for each skipped method
  AC7  - priority is strictly power→pace→hr; stops at first success
  AC8  - all thresholds read from prefs; no hardcoded values
  AC9  - missing/invalid inputs → {tss: null, method: "none", partial: false, debug: {...}}; never throws
  AC10 - no database calls
  AC11 - docstring includes 3-4 worked examples spanning at least 3 method values
  AC12 - all arithmetic has plain-language comments alongside code
  AC13 - unit tests: power path, pace path, hr path, all-inputs-missing, partial-data, prefs-missing-threshold
"""
import inspect
import types

import pytest

from backend.services.tss import compute_running_tss


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workout(np=None, avg_hr=None, distance_km=None, duration_seconds=3600):
    return types.SimpleNamespace(
        np=np,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
    )


def _split(duration_seconds, distance_km=None, avg_hr=None):
    return types.SimpleNamespace(
        duration_seconds=duration_seconds,
        distance_km=distance_km,
        avg_hr=avg_hr,
    )


def _prefs(ftp_w=None, threshold_pace_seconds_per_km=None, threshold_hr=None):
    return types.SimpleNamespace(
        ftp_w=ftp_w,
        threshold_pace_seconds_per_km=threshold_pace_seconds_per_km,
        threshold_hr=threshold_hr,
    )


# ── AC1: function exported from the module ────────────────────────────────────

def test_function_is_importable():
    """AC1: compute_running_tss exists and is importable from backend.services.tss."""
    from backend.services.tss import compute_running_tss as fn
    assert callable(fn)


# ── AC2: return value has exactly four keys ───────────────────────────────────

def test_return_has_exactly_four_keys_on_success():
    """AC2: success result has exactly tss, method, partial, debug."""
    w = _workout(np=280, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(ftp_w=280))
    assert set(result.keys()) == {"tss", "method", "partial", "debug"}


def test_return_has_exactly_four_keys_on_failure():
    """AC2: failure result also has exactly four keys."""
    w = _workout()
    result = compute_running_tss(w, [], _prefs())
    assert set(result.keys()) == {"tss", "method", "partial", "debug"}


def test_return_has_exactly_four_keys_on_pace():
    """AC2: pace-method result has exactly four keys."""
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert set(result.keys()) == {"tss", "method", "partial", "debug"}


def test_return_has_exactly_four_keys_on_hr():
    """AC2: hr-method result has exactly four keys."""
    w = _workout(avg_hr=170, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(threshold_hr=170))
    assert set(result.keys()) == {"tss", "method", "partial", "debug"}


# ── AC3: tss is integer or null ───────────────────────────────────────────────

def test_tss_is_integer_on_power_path():
    """AC3: tss is int (not float) when power method succeeds."""
    w = _workout(np=280, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(ftp_w=280))
    assert isinstance(result["tss"], int)


def test_tss_is_integer_on_pace_path():
    """AC3: tss is int (not float) when pace method succeeds."""
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert isinstance(result["tss"], int)


def test_tss_is_integer_on_hr_path():
    """AC3: tss is int (not float) when hr method succeeds."""
    w = _workout(avg_hr=170, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(threshold_hr=170))
    assert isinstance(result["tss"], int)


def test_tss_is_none_when_no_method_succeeds():
    """AC3: tss is None when no method can compute."""
    w = _workout()
    result = compute_running_tss(w, [], _prefs())
    assert result["tss"] is None


# ── AC4: method string values ─────────────────────────────────────────────────

def test_method_is_power_string():
    """AC4: method is "power" when power path is used."""
    w = _workout(np=280, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(ftp_w=280))
    assert result["method"] == "power"


def test_method_is_pace_string():
    """AC4: method is "pace" when pace path is used."""
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert result["method"] == "pace"


def test_method_is_hr_string():
    """AC4: method is "hr" when hr path is used."""
    w = _workout(avg_hr=170, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(threshold_hr=170))
    assert result["method"] == "hr"


def test_method_is_none_when_all_fail():
    """AC4: method is "none" when no method succeeds."""
    w = _workout()
    result = compute_running_tss(w, [], _prefs())
    assert result["method"] == "none"


def test_method_none_only_when_tss_null():
    """AC4: method is "none" if and only if tss is null."""
    for scenario in [
        (_workout(np=280, duration_seconds=3600), [], _prefs(ftp_w=280)),
        (_workout(duration_seconds=3600, distance_km=12), [_split(3600, 12.0)], _prefs(threshold_pace_seconds_per_km=300)),
        (_workout(avg_hr=170, duration_seconds=3600), [], _prefs(threshold_hr=170)),
        (_workout(), [], _prefs()),
    ]:
        result = compute_running_tss(*scenario)
        if result["method"] == "none":
            assert result["tss"] is None
        else:
            assert result["tss"] is not None


# ── AC5: partial flag ─────────────────────────────────────────────────────────

def test_partial_false_when_full_splits_cover_duration():
    """AC5: partial=False when valid per-lap splits cover full workout duration."""
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert result["partial"] is False


def test_partial_true_when_no_splits_pace_fallback():
    """AC5: partial=True when pace uses whole-workout avg pace (no splits)."""
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, [], _prefs(threshold_pace_seconds_per_km=300))
    assert result["partial"] is True


def test_partial_true_when_splits_cover_less_than_full_duration():
    """AC5: partial=True when splits cover < 95% of workout duration (GPS dropout)."""
    # Splits cover 60% of duration: 2160 of 3600 s
    splits = [_split(duration_seconds=2160, distance_km=7.2)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert result["partial"] is True
    assert result["method"] == "pace"


def test_partial_false_on_power_path():
    """AC5: partial=False when power method is used."""
    w = _workout(np=280, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(ftp_w=280))
    assert result["partial"] is False


def test_partial_true_when_hr_uses_workout_avg():
    """AC5: partial=True when hr uses workout-level avg_hr (no per-lap HR)."""
    w = _workout(avg_hr=170, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(threshold_hr=170))
    assert result["partial"] is True


def test_partial_false_when_hr_uses_per_lap():
    """AC5: partial=False when all splits have avg_hr."""
    splits = [
        _split(duration_seconds=1800, distance_km=6.0, avg_hr=170),
        _split(duration_seconds=1800, distance_km=6.0, avg_hr=170),
    ]
    w = _workout(avg_hr=170, duration_seconds=3600)
    result = compute_running_tss(w, splits, _prefs(threshold_hr=170))
    assert result["partial"] is False


# ── AC6: debug field lists attempted methods with skip reasons ─────────────────

def test_debug_is_dict():
    """AC6: debug is always a dict."""
    w = _workout(np=280, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(ftp_w=280))
    assert isinstance(result["debug"], dict)


def test_debug_skipped_power_has_human_readable_reason():
    """AC6: when power is skipped, debug contains a human-readable reason for it."""
    # No ftp_w → power skipped
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert result["method"] == "pace"
    # Power must be mentioned in debug with a skip reason
    debug = result["debug"]
    power_info = debug.get("power", "")
    assert power_info, "debug must mention power method"
    assert isinstance(power_info, str)
    assert len(power_info) > 5, "skip reason must be a non-trivial string"


def test_debug_skipped_pace_has_human_readable_reason():
    """AC6: when pace is skipped (no threshold_pace), debug contains a reason."""
    w = _workout(avg_hr=170, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(threshold_hr=170))
    assert result["method"] == "hr"
    debug = result["debug"]
    pace_info = debug.get("pace", "")
    assert pace_info, "debug must mention pace method"
    assert isinstance(pace_info, str)
    assert len(pace_info) > 5


def test_debug_shows_pace_and_hr_not_attempted_when_power_used():
    """AC6 / UAT-1: when power succeeds, debug shows pace and hr as not attempted."""
    w = _workout(np=280, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(ftp_w=280))
    assert result["method"] == "power"
    debug = result["debug"]
    # pace and hr were never reached
    pace_info = debug.get("pace", "")
    hr_info = debug.get("hr", "")
    assert "not attempted" in str(pace_info).lower() or "not_attempted" in str(pace_info).lower()
    assert "not attempted" in str(hr_info).lower() or "not_attempted" in str(hr_info).lower()


def test_debug_power_skipped_reason_when_pace_used():
    """AC6 / UAT-2: when pace is used, debug mentions power was skipped with a reason."""
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert result["method"] == "pace"
    power_info = str(result["debug"].get("power", "")).lower()
    assert "skipped" in power_info or "missing" in power_info or "not set" in power_info


def test_debug_all_methods_skipped_with_reasons_when_none():
    """AC6: when no method succeeds, debug has a reason for every method."""
    w = _workout()
    result = compute_running_tss(w, [], _prefs())
    assert result["method"] == "none"
    debug = result["debug"]
    for method in ("power", "pace", "hr"):
        info = str(debug.get(method, ""))
        assert info, f"debug must include info for {method}"
        assert len(info) > 3, f"debug[{method}] must be a non-empty description"


# ── AC7: priority order power → pace → hr ────────────────────────────────────

def test_power_wins_when_all_available():
    """AC7: when all inputs present, power is chosen."""
    splits = [_split(duration_seconds=3600, distance_km=12.0, avg_hr=170)]
    w = _workout(np=280, avg_hr=170, distance_km=12.0, duration_seconds=3600)
    prefs = _prefs(ftp_w=280, threshold_pace_seconds_per_km=300, threshold_hr=170)
    result = compute_running_tss(w, splits, prefs)
    assert result["method"] == "power"


def test_pace_used_when_power_prefs_missing():
    """AC7: no ftp_w → skips power, tries pace."""
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(np=280, distance_km=12.0, duration_seconds=3600)
    prefs = _prefs(threshold_pace_seconds_per_km=300, threshold_hr=170)
    result = compute_running_tss(w, splits, prefs)
    assert result["method"] == "pace"


def test_hr_used_when_power_and_pace_prefs_missing():
    """AC7: no ftp_w or threshold_pace → skips both, tries hr."""
    w = _workout(np=280, avg_hr=170, distance_km=12.0, duration_seconds=3600)
    prefs = _prefs(threshold_hr=170)
    result = compute_running_tss(w, [], prefs)
    assert result["method"] == "hr"


def test_none_when_all_prefs_missing():
    """AC7: all prefs missing → none."""
    w = _workout(np=280, avg_hr=170, distance_km=12.0, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs())
    assert result["method"] == "none"
    assert result["tss"] is None


# ── AC8: all thresholds from prefs, no hardcoded values ──────────────────────

def test_different_ftp_values_produce_different_tss():
    """AC8: ftp_w comes from prefs; different prefs produce different results."""
    w = _workout(np=280, duration_seconds=3600)
    r1 = compute_running_tss(w, [], _prefs(ftp_w=280))
    r2 = compute_running_tss(w, [], _prefs(ftp_w=350))
    assert r1["tss"] != r2["tss"]


def test_different_threshold_pace_produces_different_tss():
    """AC8: threshold_pace_seconds_per_km comes from prefs."""
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    r1 = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    r2 = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=240))
    assert r1["tss"] != r2["tss"]


def test_different_threshold_hr_produces_different_tss():
    """AC8: threshold_hr comes from prefs."""
    w = _workout(avg_hr=160, duration_seconds=3600)
    r1 = compute_running_tss(w, [], _prefs(threshold_hr=170))
    r2 = compute_running_tss(w, [], _prefs(threshold_hr=150))
    assert r1["tss"] != r2["tss"]


# ── AC9: never throws, always returns correct shape ───────────────────────────

@pytest.mark.parametrize("workout,splits,prefs", [
    (_workout(), [], _prefs()),
    (_workout(duration_seconds=0), [], _prefs()),
    (_workout(duration_seconds=None), [], _prefs()),
    (_workout(np=None, avg_hr=None, distance_km=None, duration_seconds=3600), [], _prefs()),
    (_workout(np=280, duration_seconds=3600), [], _prefs(ftp_w=0)),
    ({"np": None, "avg_hr": None, "distance_km": None, "duration_seconds": 3600}, [], {"ftp_w": None, "threshold_pace_seconds_per_km": None, "threshold_hr": None}),
])
def test_never_throws_returns_four_keys(workout, splits, prefs):
    """AC9: every edge-case input returns a dict with four keys, never raises."""
    result = compute_running_tss(workout, splits, prefs)
    assert set(result.keys()) == {"tss", "method", "partial", "debug"}


def test_returns_none_when_all_inputs_missing():
    """AC9 / AC13 all-inputs-missing path: no data → null tss, none method."""
    w = _workout()
    result = compute_running_tss(w, [], _prefs())
    assert result["tss"] is None
    assert result["method"] == "none"
    assert result["partial"] is False


# ── AC10: no database calls ───────────────────────────────────────────────────

def test_no_db_calls_in_compute_running_tss():
    """AC10: compute_running_tss source has no ORM or DB identifiers."""
    src = inspect.getsource(compute_running_tss)
    for forbidden in ("db.", "session.", "execute(", "fetchone(", "fetchall(", "query("):
        assert forbidden not in src, f"DB access found: {forbidden!r}"


# ── AC11: docstring with worked examples ─────────────────────────────────────

def test_docstring_has_worked_examples():
    """AC11: docstring contains at least three worked examples."""
    doc = compute_running_tss.__doc__ or ""
    # Must cover at least 3 of the 4 method values
    count = sum(1 for word in ("power", "pace", "hr", "none") if word.lower() in doc.lower())
    assert count >= 3, f"docstring only covers {count} method(s); need at least 3"


def test_docstring_includes_tss_100_example():
    """AC11: docstring includes at least one worked example resulting in tss=100."""
    doc = compute_running_tss.__doc__ or ""
    assert "100" in doc, "docstring must include a worked example with tss=100"


# ── AC12: plain-language arithmetic comments ─────────────────────────────────

def test_arithmetic_has_plain_language_comments():
    """AC12: source code of compute_running_tss includes prose comments near arithmetic."""
    src = inspect.getsource(compute_running_tss)
    comment_lines = [l.strip() for l in src.splitlines() if l.strip().startswith("#")]
    # Should have at least a few plain-language comments explaining the math
    assert len(comment_lines) >= 3, (
        f"Only {len(comment_lines)} comment lines found; arithmetic must be annotated in plain English"
    )


# ── AC13 power path happy path ────────────────────────────────────────────────

def test_power_happy_path_60min_at_ftp():
    """AC13 power path: 60 min at exactly FTP → tss=100, method='power', partial=False."""
    w = _workout(np=280, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(ftp_w=280))
    assert result["tss"] == 100
    assert result["method"] == "power"
    assert result["partial"] is False


# ── AC13 pace path happy path ─────────────────────────────────────────────────

def test_pace_happy_path_60min_at_threshold():
    """AC13 pace path: 60 min at exactly threshold pace (12 km) → tss=100, partial=False."""
    # threshold=300 s/km, 12 km in 3600 s → avg pace 300 s/km → IF=1.0 → tss=100
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert result["tss"] == 100
    assert result["method"] == "pace"
    assert result["partial"] is False


# ── AC13 hr path happy path ───────────────────────────────────────────────────

def test_hr_happy_path_60min_at_threshold():
    """AC13 hr path: 60 min at exactly threshold HR → tss=100, partial=True (no per-lap HR)."""
    w = _workout(avg_hr=170, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs(threshold_hr=170))
    assert result["tss"] == 100
    assert result["method"] == "hr"
    assert result["partial"] is True


# ── AC13 all-inputs-missing path ──────────────────────────────────────────────

def test_all_inputs_missing_returns_none():
    """AC13 all-inputs-missing: no prefs, no workout data → null tss, method none."""
    w = _workout()
    result = compute_running_tss(w, [], _prefs())
    assert result["tss"] is None
    assert result["method"] == "none"
    assert result["partial"] is False
    assert isinstance(result["debug"], dict)


# ── AC13 partial-data path ────────────────────────────────────────────────────

def test_partial_data_path_splits_cover_partial_duration():
    """AC13 partial-data: splits cover ~60% of duration → tss computed, partial=True."""
    # 2160 of 3600 s covered by splits (60%)
    splits = [_split(duration_seconds=2160, distance_km=7.2)]
    w = _workout(duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert result["tss"] is not None
    assert isinstance(result["tss"], int)
    assert result["method"] == "pace"
    assert result["partial"] is True


# ── AC13 prefs-missing-threshold path ────────────────────────────────────────

def test_prefs_missing_ftp_w_falls_through_to_pace():
    """AC13 prefs-missing-threshold: missing ftp_w → power skipped → tries pace."""
    splits = [_split(duration_seconds=3600, distance_km=12.0)]
    w = _workout(np=280, duration_seconds=3600, distance_km=12.0)
    result = compute_running_tss(w, splits, _prefs(threshold_pace_seconds_per_km=300))
    assert result["method"] == "pace"
    assert result["tss"] is not None


def test_prefs_missing_all_thresholds_returns_none():
    """AC13 prefs-missing-threshold: all thresholds absent → debug shows all skipped."""
    w = _workout(np=280, avg_hr=170, distance_km=12.0, duration_seconds=3600)
    result = compute_running_tss(w, [], _prefs())
    assert result["tss"] is None
    assert result["method"] == "none"
    debug = result["debug"]
    # Each method must be mentioned with a skip reason
    for method in ("power", "pace", "hr"):
        assert method in debug, f"debug missing {method}"
        assert debug[method], f"debug[{method}] must be non-empty"
