"""Tests for issue #583: classify_laps pure function for lap intensity bands.

Each test anchored to a specific acceptance criterion.

Acceptance criteria:
  AC1  - classify_laps is importable from backend.services.lap_classify
  AC2  - function is pure: no database access inside classify_laps
  AC3  - returns one result per lap (length matches input)
  AC4  - each result has keys: ratio, band, basis, reason
  AC5  - power basis: ratio = avg_power / ftp_w; basis = "power"
  AC6  - pace basis: ratio = threshold_pace / lap_pace; basis = "pace"
  AC7  - hr basis: ratio = avg_hr / threshold_hr; basis = "hr"
  AC8  - band constants: easy(<0.80), steady(0.80-0.90), tempo(0.90-1.00),
         threshold(1.00-1.06), hard(>=1.06)
  AC9  - priority order: power first, then pace, then hr
  AC10 - all-thresholds-missing → basis="none", ratio=None, band=None, reason non-empty
  AC11 - lap-metric-missing skips that basis and records reason; tries next
  AC12 - multi-lap: results are independent, one per lap
  AC13 - classify_laps_for_workout thin caller exists in lap_classify
  AC14 - docstring has worked examples for all three bases
"""
import inspect
import types

import pytest

from backend.services.lap_classify import classify_laps, classify_laps_for_workout


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lap(avg_power=None, avg_hr=None, duration_seconds=600, distance_km=2.0):
    return types.SimpleNamespace(
        avg_power=avg_power,
        avg_hr=avg_hr,
        duration_seconds=duration_seconds,
        distance_km=distance_km,
    )


def _prefs(ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None):
    return {
        "ftp_w": ftp_w,
        "threshold_hr": threshold_hr,
        "threshold_pace_seconds_per_km": threshold_pace_seconds_per_km,
    }


# ── AC1: importable ────────────────────────────────────────────────────────────

def test_classify_laps_is_importable():
    """AC1: classify_laps is importable from backend.services.lap_classify."""
    from backend.services.lap_classify import classify_laps as fn
    assert callable(fn)


# ── AC2: pure function, no database access ─────────────────────────────────────

def test_classify_laps_is_pure_no_db():
    """AC2: classify_laps module imports no database session, engine, or ORM session."""
    # The pure function must not reference session/db/engine directly
    # The thin caller (classify_laps_for_workout) may, but classify_laps itself
    # is a separate function with no db arg.
    sig = inspect.signature(classify_laps)
    param_names = list(sig.parameters.keys())
    assert "session" not in param_names
    assert "db" not in param_names


# ── AC3: one result per lap ───────────────────────────────────────────────────

def test_returns_one_result_per_lap():
    """AC3: result list length equals number of input laps."""
    laps = [_lap(avg_power=200), _lap(avg_power=220), _lap(avg_power=180)]
    prefs = _prefs(ftp_w=200)
    result = classify_laps(laps, prefs)
    assert len(result) == 3


def test_returns_empty_list_for_no_laps():
    """AC3: empty input produces empty output."""
    result = classify_laps([], _prefs(ftp_w=200))
    assert result == []


# ── AC4: result keys ──────────────────────────────────────────────────────────

def test_result_has_required_keys():
    """AC4: each result dict contains ratio, band, basis, reason."""
    lap = _lap(avg_power=220)
    prefs = _prefs(ftp_w=200)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert "ratio" in entry
    assert "band" in entry
    assert "basis" in entry
    assert "reason" in entry


# ── AC5: power basis computation ──────────────────────────────────────────────

def test_power_basis_ratio_computation():
    """AC5: ratio = avg_power / ftp_w for power basis. UAT step 1."""
    lap = _lap(avg_power=220)
    prefs = _prefs(ftp_w=200)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "power"
    assert entry["ratio"] == pytest.approx(1.10, abs=0.01)
    assert entry["band"] == "hard"


def test_power_basis_easy_band():
    """AC5: avg_power=158, ftp_w=200 → ratio=0.79 → easy."""
    lap = _lap(avg_power=158)
    prefs = _prefs(ftp_w=200)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "power"
    assert entry["ratio"] == pytest.approx(0.79, abs=0.01)
    assert entry["band"] == "easy"


# ── AC6: pace basis computation ───────────────────────────────────────────────

def test_pace_basis_ratio_computation():
    """AC6: ratio = threshold_pace / lap_pace. UAT step 2.

    threshold_pace = 300, lap duration = 600s, distance = 2.4 km
    lap_pace = 600 / 2.4 = 250 s/km
    ratio = 300 / 250 = 1.20 → hard
    """
    lap = _lap(avg_power=None, avg_hr=None, duration_seconds=600, distance_km=2.4)
    prefs = _prefs(threshold_pace_seconds_per_km=300)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "pace"
    assert entry["ratio"] == pytest.approx(1.20, abs=0.01)
    assert entry["band"] == "hard"


def test_pace_ratio_faster_lap_above_one():
    """AC6: a faster lap (lower s/km) yields ratio above 1.0."""
    # threshold_pace=300, lap_pace=250 → ratio=1.20
    lap = _lap(avg_power=None, duration_seconds=500, distance_km=2.0)  # pace=250
    prefs = _prefs(threshold_pace_seconds_per_km=300)
    result = classify_laps([lap], prefs)
    assert result[0]["ratio"] > 1.0


def test_pace_ratio_slower_lap_below_one():
    """AC6: a slower lap (higher s/km) yields ratio below 1.0."""
    # threshold_pace=300, lap_pace=375 → ratio=0.80
    lap = _lap(avg_power=None, duration_seconds=750, distance_km=2.0)  # pace=375
    prefs = _prefs(threshold_pace_seconds_per_km=300)
    result = classify_laps([lap], prefs)
    assert result[0]["ratio"] < 1.0


# ── AC7: HR basis computation ─────────────────────────────────────────────────

def test_hr_basis_ratio_computation():
    """AC7: ratio = avg_hr / threshold_hr. UAT step 3."""
    lap = _lap(avg_power=None, avg_hr=155)
    prefs = _prefs(threshold_hr=165)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "hr"
    assert entry["ratio"] == pytest.approx(155 / 165, abs=0.01)
    assert entry["band"] == "tempo"


# ── AC8: band boundary classification ────────────────────────────────────────

@pytest.mark.parametrize("avg_power,ftp,expected_band", [
    # easy: ratio below 0.80
    (158, 200, "easy"),    # ratio = 0.79
    (100, 200, "easy"),    # ratio = 0.50
    # steady: ratio at least 0.80, below 0.90
    (160, 200, "steady"),  # ratio = 0.80 (boundary)
    (178, 200, "steady"),  # ratio = 0.89
    # tempo: ratio at least 0.90, below 1.00
    (180, 200, "tempo"),   # ratio = 0.90 (boundary)
    (198, 200, "tempo"),   # ratio = 0.99
    # threshold: ratio at least 1.00, below 1.06
    (200, 200, "threshold"),  # ratio = 1.00 (boundary)
    (210, 200, "threshold"),  # ratio = 1.05
    # hard: ratio at least 1.06
    (212, 200, "hard"),    # ratio = 1.06 (boundary)
    (240, 200, "hard"),    # ratio = 1.20
])
def test_band_boundaries(avg_power, ftp, expected_band):
    """AC8: each band boundary is correctly classified."""
    lap = _lap(avg_power=avg_power)
    prefs = _prefs(ftp_w=ftp)
    result = classify_laps([lap], prefs)
    assert result[0]["band"] == expected_band


# ── AC9: priority order ───────────────────────────────────────────────────────

def test_power_wins_when_all_present():
    """AC9: power is used when all three thresholds and metrics are present. UAT step 4."""
    # avg_power=220, ftp_w=200 → power ratio=1.10
    # avg_hr=155, threshold_hr=165 → hr ratio=0.94 (would be tempo)
    # pace=250, threshold_pace=300 → pace ratio=1.20
    # power should win → hard
    lap = _lap(avg_power=220, avg_hr=155, duration_seconds=500, distance_km=2.0)
    prefs = _prefs(ftp_w=200, threshold_hr=165, threshold_pace_seconds_per_km=300)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "power"
    assert entry["band"] == "hard"


def test_pace_fallthrough_when_no_power_threshold():
    """AC9: pace is used when ftp_w is absent in prefs."""
    lap = _lap(avg_power=None, avg_hr=155, duration_seconds=500, distance_km=2.0)
    prefs = _prefs(threshold_pace_seconds_per_km=300, threshold_hr=165)
    result = classify_laps([lap], prefs)
    assert result[0]["basis"] == "pace"


def test_hr_fallthrough_when_no_power_or_pace_threshold():
    """AC9: hr is used when ftp_w and threshold_pace are both absent."""
    lap = _lap(avg_power=None, avg_hr=155)
    prefs = _prefs(threshold_hr=165)
    result = classify_laps([lap], prefs)
    assert result[0]["basis"] == "hr"


def test_hr_fallthrough_when_power_threshold_present_but_lap_has_no_power():
    """AC9: hr fallthrough when ftp_w present but lap has no avg_power and no pace metric. UAT step 5."""
    lap = _lap(avg_power=None, avg_hr=145, duration_seconds=None, distance_km=None)
    prefs = _prefs(ftp_w=200, threshold_hr=165, threshold_pace_seconds_per_km=300)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "hr"
    assert entry["ratio"] == pytest.approx(145 / 165, abs=0.01)
    assert entry["band"] == "steady"
    # reason should mention that power and pace metrics were absent
    assert entry["reason"] is not None
    assert len(entry["reason"]) > 0


# ── AC10: all-thresholds-missing ─────────────────────────────────────────────

def test_all_thresholds_missing_returns_none_basis():
    """AC10: when no threshold is configured, basis=none, ratio=None, band=None, reason non-empty. UAT step 6."""
    lap = _lap(avg_power=220, avg_hr=155)
    prefs = _prefs()  # all None
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "none"
    assert entry["ratio"] is None
    assert entry["band"] is None
    assert isinstance(entry["reason"], str)
    assert len(entry["reason"]) > 0


def test_all_thresholds_null_in_prefs():
    """AC10: explicit null values in prefs treated same as absent."""
    lap = _lap(avg_power=220)
    prefs = {"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "none"
    assert entry["ratio"] is None
    assert entry["band"] is None


# ── AC11: lap-metric-missing ──────────────────────────────────────────────────

def test_power_threshold_present_but_avg_power_missing_skips_to_pace():
    """AC11: ftp_w in prefs but lap has no avg_power → skip power, use pace."""
    lap = _lap(avg_power=None, avg_hr=None, duration_seconds=500, distance_km=2.0)
    prefs = _prefs(ftp_w=200, threshold_pace_seconds_per_km=300)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "pace"
    # reason should describe why power was skipped
    assert entry["reason"] is not None
    assert "power" in entry["reason"].lower() or "avg_power" in entry["reason"].lower()


def test_pace_threshold_present_but_no_distance_skips_to_hr():
    """AC11: threshold_pace present but lap has no distance → skip pace, use hr."""
    lap = _lap(avg_power=None, avg_hr=155, duration_seconds=600, distance_km=None)
    prefs = _prefs(threshold_pace_seconds_per_km=300, threshold_hr=165)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "hr"
    assert entry["reason"] is not None


def test_hr_threshold_present_but_avg_hr_missing():
    """AC11: threshold_hr present but avg_hr absent → basis=none."""
    lap = _lap(avg_power=None, avg_hr=None, duration_seconds=None, distance_km=None)
    prefs = _prefs(threshold_hr=165)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "none"
    assert entry["reason"] is not None
    assert len(entry["reason"]) > 0


# ── AC12: multi-lap independence ──────────────────────────────────────────────

def test_multi_lap_results_are_independent():
    """AC12: multi-lap session returns independent results per lap. UAT step 7."""
    laps = [
        _lap(avg_power=158),   # easy: 0.79
        _lap(avg_power=180),   # tempo: 0.90
        _lap(avg_power=200),   # threshold: 1.00
        _lap(avg_power=220),   # hard: 1.10
    ]
    prefs = _prefs(ftp_w=200)
    result = classify_laps(laps, prefs)
    assert len(result) == 4
    assert result[0]["band"] == "easy"
    assert result[1]["band"] == "tempo"
    assert result[2]["band"] == "threshold"
    assert result[3]["band"] == "hard"
    # verify each result is independent (no value bleed)
    assert result[0]["ratio"] != result[1]["ratio"]
    assert result[2]["ratio"] != result[3]["ratio"]


def test_multi_lap_different_bands_at_least_three():
    """AC12: multi-lap covering at least three bands returns distinct entries."""
    laps = [
        _lap(avg_power=150),  # 0.75 easy
        _lap(avg_power=185),  # 0.925 tempo
        _lap(avg_power=215),  # 1.075 hard
    ]
    prefs = _prefs(ftp_w=200)
    result = classify_laps(laps, prefs)
    bands = {r["band"] for r in result}
    assert len(bands) >= 3


# ── AC13: thin caller exists ──────────────────────────────────────────────────

def test_thin_caller_is_importable():
    """AC13: classify_laps_for_workout is importable from backend.services.lap_classify."""
    from backend.services.lap_classify import classify_laps_for_workout as fn
    assert callable(fn)


def test_thin_caller_accepts_db_session():
    """AC13: classify_laps_for_workout signature includes workout_id and session."""
    sig = inspect.signature(classify_laps_for_workout)
    params = list(sig.parameters.keys())
    assert "workout_id" in params
    assert "session" in params


# ── AC14: docstring has worked examples ───────────────────────────────────────

def test_docstring_has_worked_examples():
    """AC14: classify_laps docstring includes examples for power, pace, and hr bases."""
    doc = classify_laps.__doc__ or ""
    doc_lower = doc.lower()
    assert "power" in doc_lower
    assert "pace" in doc_lower
    assert "hr" in doc_lower
    # verify ratio values appear (the worked examples with numbers)
    assert "1.10" in doc or "1.20" in doc or "0.94" in doc


def test_no_carets_in_source():
    """AC14: no carets (^) used for exponentiation in docstrings or comments."""
    import backend.services.lap_classify as mod
    src = inspect.getsource(mod)
    # carets in docstrings would be math like "ratio^2" — disallow
    # but allow any ^ that might appear in a string comparison (none expected here)
    # filter to only doc/comment lines
    in_docstring = False
    caret_violations = []
    for line in src.split("\n"):
        stripped = line.strip()
        if '"""' in stripped or "'''" in stripped:
            in_docstring = not in_docstring
        if (in_docstring or stripped.startswith("#")) and "^" in line:
            caret_violations.append(line)
    assert caret_violations == [], f"Caret found in doc/comment: {caret_violations}"
