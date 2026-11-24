"""Tests for issue #678: classify_laps pure function with basis-chosen-once semantics.

Acceptance criteria anchored:
  AC1  - classify_laps importable from backend.services.lap_classifier
  AC2  - pure function: no DB calls, no session param; basis determined ONCE from prefs
  AC3  - returns one result per lap; each result has ratio, band, basis (reason optional)
  AC4  - ratio computations: power=avg_power/ftp_w, pace=threshold_pace/lap_pace,
         hr=avg_hr/threshold_hr
  AC5  - band boundaries as named constants; map to easy/steady/tempo/threshold/hard
  AC6  - all thresholds absent/null → basis="none", band=null, reason non-empty for every lap
  AC7  - chosen basis applies to ALL laps; lap missing its metric → band=null+reason,
         NOT fallthrough to next basis; other laps unaffected
  AC8  - docstring includes worked examples for power, pace, hr, and the "none" path
  AC9  - thin caller classify_laps_for_workout exists; signature has workout_id + session
  AC10 - exact band edges 0.80, 0.90, 1.00, 1.06 each fall in the HIGHER band
"""
import inspect
import types

import pytest

from backend.services.lap_classifier import classify_laps, classify_laps_for_workout


# ── Helpers ────────────────────────────────────────────────────────────────────

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
    """AC1: classify_laps importable from backend.services.lap_classifier."""
    from backend.services.lap_classifier import classify_laps as fn
    assert callable(fn)


# ── AC2: pure function, basis chosen once from prefs ──────────────────────────

def test_classify_laps_has_no_session_param():
    """AC2: classify_laps signature contains no session or db parameter."""
    sig = inspect.signature(classify_laps)
    params = list(sig.parameters.keys())
    assert "session" not in params
    assert "db" not in params


def test_basis_chosen_once_power_when_ftp_present():
    """AC2: when ftp_w is set, power is chosen for ALL laps regardless of lap metric."""
    laps = [
        _lap(avg_power=200),    # has power
        _lap(avg_power=None, avg_hr=155, duration_seconds=500, distance_km=2.0),  # missing power
    ]
    prefs = _prefs(ftp_w=200, threshold_hr=165, threshold_pace_seconds_per_km=300)
    result = classify_laps(laps, prefs)
    # Both laps use power basis — no fallthrough to hr or pace for the second lap
    assert result[0]["basis"] == "power"
    assert result[1]["basis"] == "power"


def test_basis_chosen_once_pace_when_no_ftp():
    """AC2: when ftp_w absent but threshold_pace set, pace is chosen for ALL laps."""
    laps = [
        _lap(avg_power=None, duration_seconds=500, distance_km=2.0),    # has pace
        _lap(avg_power=None, duration_seconds=None, distance_km=None, avg_hr=155),  # missing pace
    ]
    prefs = _prefs(threshold_pace_seconds_per_km=300, threshold_hr=165)
    result = classify_laps(laps, prefs)
    assert result[0]["basis"] == "pace"
    assert result[1]["basis"] == "pace"


def test_basis_chosen_once_hr_when_only_hr_set():
    """AC2: when only threshold_hr is set, hr is the chosen basis for ALL laps."""
    laps = [
        _lap(avg_power=None, avg_hr=155),
        _lap(avg_power=None, avg_hr=None),
    ]
    prefs = _prefs(threshold_hr=165)
    result = classify_laps(laps, prefs)
    assert result[0]["basis"] == "hr"
    assert result[1]["basis"] == "hr"


# ── AC3: one result per lap with required keys ────────────────────────────────

def test_returns_one_result_per_lap():
    """AC3: result list length equals number of input laps."""
    laps = [_lap(avg_power=180), _lap(avg_power=200), _lap(avg_power=220)]
    prefs = _prefs(ftp_w=200)
    result = classify_laps(laps, prefs)
    assert len(result) == 3


def test_returns_empty_list_for_no_laps():
    """AC3: empty input yields empty output."""
    assert classify_laps([], _prefs(ftp_w=200)) == []


def test_result_has_required_keys():
    """AC3: each result dict has ratio, band, basis."""
    result = classify_laps([_lap(avg_power=200)], _prefs(ftp_w=200))
    entry = result[0]
    assert "ratio" in entry
    assert "band" in entry
    assert "basis" in entry


# ── AC4: ratio computations ───────────────────────────────────────────────────

def test_power_ratio_computation():
    """AC4: ratio = avg_power / ftp_w for power basis. UAT step 1."""
    result = classify_laps([_lap(avg_power=220)], _prefs(ftp_w=200))
    entry = result[0]
    assert entry["basis"] == "power"
    assert entry["ratio"] == pytest.approx(1.10, abs=0.01)
    assert entry["band"] == "hard"


def test_pace_ratio_computation():
    """AC4: ratio = threshold_pace / lap_pace. UAT step 2.

    threshold=300s/km, lap duration=600s, distance=2.4km → lap_pace=250s/km
    ratio = 300/250 = 1.20 → hard
    """
    lap = _lap(avg_power=None, avg_hr=None, duration_seconds=600, distance_km=2.4)
    result = classify_laps([lap], _prefs(threshold_pace_seconds_per_km=300))
    entry = result[0]
    assert entry["basis"] == "pace"
    assert entry["ratio"] == pytest.approx(1.20, abs=0.01)
    assert entry["band"] == "hard"


def test_pace_faster_lap_ratio_above_one():
    """AC4: a faster lap (lower s/km) yields ratio above 1.0."""
    lap = _lap(avg_power=None, duration_seconds=500, distance_km=2.0)  # 250 s/km
    result = classify_laps([lap], _prefs(threshold_pace_seconds_per_km=300))
    assert result[0]["ratio"] > 1.0


def test_hr_ratio_computation():
    """AC4: ratio = avg_hr / threshold_hr. UAT step 3."""
    result = classify_laps([_lap(avg_power=None, avg_hr=155)], _prefs(threshold_hr=165))
    entry = result[0]
    assert entry["basis"] == "hr"
    assert entry["ratio"] == pytest.approx(155 / 165, abs=0.01)
    assert entry["band"] == "tempo"


# ── AC5: band boundaries (named constants) ────────────────────────────────────

@pytest.mark.parametrize("avg_power,ftp,expected_band", [
    (158, 200, "easy"),       # 0.79 — below 0.80
    (100, 200, "easy"),       # 0.50
    (160, 200, "steady"),     # 0.80 — exact lower edge (AC10)
    (178, 200, "steady"),     # 0.89
    (180, 200, "tempo"),      # 0.90 — exact lower edge (AC10)
    (198, 200, "tempo"),      # 0.99
    (200, 200, "threshold"),  # 1.00 — exact lower edge (AC10)
    (210, 200, "threshold"),  # 1.05
    (212, 200, "hard"),       # 1.06 — exact lower edge (AC10)
    (240, 200, "hard"),       # 1.20
])
def test_band_boundaries(avg_power, ftp, expected_band):
    """AC5/AC10: each band boundary falls in the HIGHER band, not the lower."""
    result = classify_laps([_lap(avg_power=avg_power)], _prefs(ftp_w=ftp))
    assert result[0]["band"] == expected_band


def test_band_constants_are_named():
    """AC5: module exports named constants for band boundaries."""
    import backend.services.lap_classifier as mod
    assert hasattr(mod, "BAND_EASY")
    assert hasattr(mod, "BAND_STEADY")
    assert hasattr(mod, "BAND_TEMPO")
    assert hasattr(mod, "BAND_THRESHOLD")
    assert hasattr(mod, "BAND_HARD")


# ── AC6: all thresholds absent → none basis ───────────────────────────────────

def test_all_thresholds_absent_gives_none_basis():
    """AC6: no threshold configured → basis=none, band=null, reason non-empty. UAT step 4."""
    result = classify_laps([_lap(avg_power=220, avg_hr=155)], _prefs())
    entry = result[0]
    assert entry["basis"] == "none"
    assert entry["band"] is None
    assert entry["ratio"] is None
    assert isinstance(entry.get("reason"), str) and len(entry["reason"]) > 0


def test_explicit_null_thresholds_gives_none_basis():
    """AC6: explicit None values in prefs treated same as absent."""
    prefs = {"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
    result = classify_laps([_lap(avg_power=220)], prefs)
    entry = result[0]
    assert entry["basis"] == "none"
    assert entry["band"] is None


def test_none_basis_on_multiple_laps():
    """AC6: all laps return none basis when no threshold configured."""
    laps = [_lap(avg_power=200), _lap(avg_hr=150), _lap()]
    result = classify_laps(laps, _prefs())
    for entry in result:
        assert entry["basis"] == "none"
        assert entry["band"] is None
        assert entry.get("reason")


# ── AC7: chosen basis applies to ALL laps; lap missing metric → null band ─────

def test_power_basis_lap_missing_power_returns_null_band():
    """AC7: power is chosen basis; lap with no avg_power returns band=null+reason. UAT step 5."""
    laps = [
        _lap(avg_power=200),                        # has power → classifies normally
        _lap(avg_power=None, avg_hr=155),           # missing power → null band, NOT hr fallthrough
    ]
    prefs = _prefs(ftp_w=200, threshold_hr=165)
    result = classify_laps(laps, prefs)

    # first lap: power, normal band
    assert result[0]["basis"] == "power"
    assert result[0]["band"] == "threshold"
    assert result[0]["ratio"] is not None

    # second lap: basis still power (chosen once), but metric absent → null band
    assert result[1]["basis"] == "power"
    assert result[1]["band"] is None
    assert result[1]["ratio"] is None
    assert isinstance(result[1].get("reason"), str) and len(result[1]["reason"]) > 0


def test_no_fallthrough_to_hr_when_basis_is_power():
    """AC7: when basis=power and lap has no avg_power, hr is NOT used (no fallthrough)."""
    lap = _lap(avg_power=None, avg_hr=155, duration_seconds=None, distance_km=None)
    prefs = _prefs(ftp_w=200, threshold_hr=165, threshold_pace_seconds_per_km=300)
    result = classify_laps([lap], prefs)
    entry = result[0]
    # basis must remain power (no fallthrough), band must be null
    assert entry["basis"] == "power"
    assert entry["band"] is None


def test_no_fallthrough_to_hr_when_basis_is_pace():
    """AC7: when basis=pace and lap has no distance, hr is NOT used (no fallthrough)."""
    lap = _lap(avg_power=None, avg_hr=155, duration_seconds=None, distance_km=None)
    prefs = _prefs(threshold_pace_seconds_per_km=300, threshold_hr=165)
    result = classify_laps([lap], prefs)
    entry = result[0]
    assert entry["basis"] == "pace"
    assert entry["band"] is None


def test_other_laps_unaffected_when_one_missing_metric():
    """AC7: other laps in the same call classify normally when one lap has missing metric."""
    laps = [
        _lap(avg_power=200),        # classifies normally
        _lap(avg_power=None),       # missing metric → null band
        _lap(avg_power=220),        # classifies normally
    ]
    prefs = _prefs(ftp_w=200)
    result = classify_laps(laps, prefs)
    assert result[0]["band"] == "threshold"
    assert result[1]["band"] is None
    assert result[2]["band"] == "hard"


def test_pace_basis_lap_missing_distance_returns_null_band():
    """AC7: pace chosen; lap with no distance returns band=null, not hr fallthrough."""
    laps = [
        _lap(avg_power=None, duration_seconds=500, distance_km=2.0),  # has pace
        _lap(avg_power=None, duration_seconds=600, distance_km=None, avg_hr=155),  # missing dist
    ]
    prefs = _prefs(threshold_pace_seconds_per_km=300, threshold_hr=165)
    result = classify_laps(laps, prefs)
    assert result[0]["basis"] == "pace"
    assert result[0]["band"] is not None
    assert result[1]["basis"] == "pace"
    assert result[1]["band"] is None
    assert result[1].get("reason")


def test_hr_basis_lap_missing_avg_hr_returns_null_band():
    """AC7: hr chosen; lap with no avg_hr returns band=null with reason."""
    laps = [
        _lap(avg_power=None, avg_hr=155),   # has hr
        _lap(avg_power=None, avg_hr=None),  # missing hr
    ]
    prefs = _prefs(threshold_hr=165)
    result = classify_laps(laps, prefs)
    assert result[0]["basis"] == "hr"
    assert result[0]["band"] is not None
    assert result[1]["basis"] == "hr"
    assert result[1]["band"] is None


# ── AC8: docstring includes "none" path example ───────────────────────────────

def test_docstring_has_power_example():
    """AC8: classify_laps docstring includes power basis example."""
    doc = (classify_laps.__doc__ or "").lower()
    assert "power" in doc


def test_docstring_has_pace_example():
    """AC8: classify_laps docstring includes pace basis example."""
    doc = (classify_laps.__doc__ or "").lower()
    assert "pace" in doc


def test_docstring_has_hr_example():
    """AC8: classify_laps docstring includes hr basis example."""
    doc = (classify_laps.__doc__ or "").lower()
    assert "hr" in doc


def test_docstring_has_none_path_example():
    """AC8: classify_laps docstring includes worked example for the 'none' path."""
    doc = classify_laps.__doc__ or ""
    doc_lower = doc.lower()
    # Must describe the scenario where no thresholds are configured
    assert "none" in doc_lower
    # Must explain what happens (basis=none, band=null)
    assert "no threshold" in doc_lower or "absent" in doc_lower or "missing" in doc_lower


# ── AC9: thin caller exists ───────────────────────────────────────────────────

def test_thin_caller_is_importable():
    """AC9: classify_laps_for_workout importable from backend.services.lap_classifier."""
    from backend.services.lap_classifier import classify_laps_for_workout as fn
    assert callable(fn)


def test_thin_caller_has_correct_signature():
    """AC9: classify_laps_for_workout accepts workout_id and session."""
    sig = inspect.signature(classify_laps_for_workout)
    params = list(sig.parameters.keys())
    assert "workout_id" in params
    assert "session" in params


def test_classify_laps_has_no_db_access_in_source():
    """AC9: pure classify_laps function body contains no session/db/query calls."""
    src = inspect.getsource(classify_laps)
    assert "session" not in src
    assert ".query(" not in src
    assert "session.get(" not in src


# ── AC10: exact boundary edges in the higher band ────────────────────────────

def test_exact_edge_0_80_is_steady_not_easy():
    """AC10: ratio exactly 0.80 → steady (not easy). UAT step 6."""
    # 160/200 = 0.80 exactly
    result = classify_laps([_lap(avg_power=160)], _prefs(ftp_w=200))
    assert result[0]["band"] == "steady"


def test_exact_edge_0_90_is_tempo_not_steady():
    """AC10: ratio exactly 0.90 → tempo (not steady)."""
    # 180/200 = 0.90 exactly
    result = classify_laps([_lap(avg_power=180)], _prefs(ftp_w=200))
    assert result[0]["band"] == "tempo"


def test_exact_edge_1_00_is_threshold_not_tempo():
    """AC10: ratio exactly 1.00 → threshold (not tempo)."""
    # 200/200 = 1.00 exactly
    result = classify_laps([_lap(avg_power=200)], _prefs(ftp_w=200))
    assert result[0]["band"] == "threshold"


def test_exact_edge_1_06_is_hard_not_threshold():
    """AC10: ratio exactly 1.06 → hard (not threshold). UAT step 7."""
    # 212/200 = 1.06 exactly
    result = classify_laps([_lap(avg_power=212)], _prefs(ftp_w=200))
    assert result[0]["band"] == "hard"
