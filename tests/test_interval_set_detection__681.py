"""Tests for issue #681: Add interval and set detection to session-profile.

Acceptance criteria covered:
  AC1  — detect_intervals is pure; returns (None, reason_str) for null/empty laps
  AC2  — alternating sequence requires at least 2 cycles; hard reps shorter than recoveries
  AC3  — HARD_REP_TOLERANCE (or equivalent) defined at module scope; never inline
  AC4  — phase labelled "Intervals" with reps_detected int
  AC5  — detect_sets subdivides by SET_BOUNDARY_MULTIPLIER (default 1.5)
  AC6  — detect_sets returns sets_detected (int ≥ 1) and reps_per_set (list of ints)
  AC7  — median computed in plain arithmetic (no unexplained statistics import)
  AC8  — DB access only in thin caller; pure functions use plain data
  AC9  — docstrings have 2 worked examples: 6-rep single-set, 12-rep two-set
  AC10 — unit tests: <2 cycles, exactly 2, tolerance boundary inside/outside,
          single-set, two-set, missing/null input
  AC11 — no bare numeric literals in detection logic
"""

import pytest

import backend.services.interval_detector as idet
from backend.services.interval_detector import (
    detect_intervals,
    detect_sets,
    HARD_REP_TOLERANCE,
    SET_BOUNDARY_MULTIPLIER,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _lap(band, duration_seconds, distance_km=0.2):
    return {"band": band, "duration_seconds": duration_seconds, "distance_km": distance_km}


def _hard(duration=60):
    return _lap("tempo", duration, 0.2)


def _easy(duration=90):
    return _lap("easy", duration, 0.3)


def _uniform_laps(n_cycles, hard_dur=60, rec_dur=90):
    """n_cycles alternating hard/easy pairs with uniform durations."""
    laps = []
    for _ in range(n_cycles):
        laps.append(_hard(hard_dur))
        laps.append(_easy(rec_dur))
    return laps


def _two_set_laps(set_size=6, short_rec=90, long_rec=270):
    """set_size reps + long recovery + set_size more reps."""
    laps = []
    for i in range(set_size):
        laps.append(_hard(60))
        laps.append(_easy(long_rec if i == set_size - 1 else short_rec))
    for _ in range(set_size):
        laps.append(_hard(60))
        laps.append(_easy(short_rec))
    return laps


# ── AC1/AC10: null and empty input ────────────────────────────────────────────

def test_detect_intervals_null_input():
    """AC1/AC10: None input returns (None, reason_str); no exception raised."""
    phase, reason = detect_intervals(None)
    assert phase is None
    assert isinstance(reason, str) and len(reason) > 0


def test_detect_intervals_empty_input():
    """AC1/AC10: empty list returns (None, reason_str); no exception raised."""
    phase, reason = detect_intervals([])
    assert phase is None
    assert isinstance(reason, str) and len(reason) > 0


# ── AC2/AC10: fewer than 2 cycles → null ─────────────────────────────────────

def test_detect_intervals_zero_cycles():
    """AC10: all easy laps → no cycles → (None, reason)."""
    phase, reason = detect_intervals([_easy()] * 6)
    assert phase is None
    assert reason is not None


def test_detect_intervals_one_cycle():
    """AC10: single hard/easy pair (< 2 cycles required) → (None, reason)."""
    phase, reason = detect_intervals([_hard(), _easy()])
    assert phase is None
    assert isinstance(reason, str)
    # reason should be human-readable
    assert len(reason) > 0


# ── AC2/AC10: exactly 2 cycles → success ──────────────────────────────────────

def test_detect_intervals_exactly_two_cycles():
    """AC10: exactly 2 cycles is the minimum; should succeed."""
    laps = _uniform_laps(2)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"expected success, got reason: {reason}"
    assert reason is None
    assert phase["label"] == "Intervals"
    assert phase["reps_detected"] == 2


# ── AC3: tolerance constants at module scope ───────────────────────────────────

def test_hard_rep_tolerance_defined_at_module_scope():
    """AC3: HARD_REP_TOLERANCE is a named numeric constant."""
    assert isinstance(HARD_REP_TOLERANCE, (int, float))
    assert HARD_REP_TOLERANCE > 0


def test_set_boundary_multiplier_defined_at_module_scope():
    """AC5: SET_BOUNDARY_MULTIPLIER is a named numeric constant defaulting to 1.5."""
    assert isinstance(SET_BOUNDARY_MULTIPLIER, (int, float))
    assert SET_BOUNDARY_MULTIPLIER == 1.5


# ── AC4: phase shape ──────────────────────────────────────────────────────────

def test_detect_intervals_phase_label_and_reps_detected():
    """AC4: phase is labelled 'Intervals' and reps_detected is an int."""
    phase, _ = detect_intervals(_uniform_laps(3))
    assert phase is not None
    assert phase["label"] == "Intervals"
    assert isinstance(phase["reps_detected"], int)
    assert phase["reps_detected"] == 3


# ── AC6: detect_sets always returns reps_per_set list ─────────────────────────

def test_detect_sets_returns_reps_per_set_single_set():
    """AC6: single-set case returns reps_per_set=[total_reps]; sets_detected=1."""
    laps = _uniform_laps(6)
    phase, _ = detect_intervals(laps)
    assert phase is not None
    updated, reason = detect_sets(phase, laps)
    assert updated is not None
    assert updated["sets_detected"] == 1
    assert "reps_per_set" in updated
    assert updated["reps_per_set"] == [6]
    assert reason is None


def test_detect_sets_returns_reps_per_set_two_sets():
    """AC6: two-set case returns reps_per_set=[6, 6]; sets_detected=2."""
    laps = _two_set_laps(set_size=6, short_rec=90, long_rec=270)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"detect_intervals failed: {reason}"
    updated, reason = detect_sets(phase, laps)
    assert updated is not None
    assert updated["sets_detected"] == 2
    assert "reps_per_set" in updated
    assert updated["reps_per_set"] == [6, 6]
    assert reason is None


def test_detect_sets_reps_per_set_present_for_uneven_sets():
    """AC6: reps_per_set is present even when sets are uneven."""
    laps = []
    for i in range(4):
        laps.append(_hard(60))
        laps.append(_easy(270 if i == 3 else 90))
    for _ in range(3):
        laps.append(_hard(60))
        laps.append(_easy(90))
    phase, _ = detect_intervals(laps)
    assert phase is not None
    updated, reason = detect_sets(phase, laps)
    assert updated is not None
    assert "reps_per_set" in updated
    assert isinstance(updated["reps_per_set"], list)
    assert len(updated["reps_per_set"]) == 2


def test_detect_sets_reps_per_set_type():
    """AC6: reps_per_set entries are integers."""
    laps = _uniform_laps(6)
    phase, _ = detect_intervals(laps)
    updated, _ = detect_sets(phase, laps)
    assert updated is not None
    for entry in updated["reps_per_set"]:
        assert isinstance(entry, int)


# ── AC6: UAT worked examples ───────────────────────────────────────────────────

def test_uat_step1_six_reps_single_set():
    """AC9/UAT-1: 6 reps, uniform recoveries → sets_detected=1, reps_per_set=[6]."""
    laps = _uniform_laps(6, hard_dur=60, rec_dur=90)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"reason: {reason}"
    updated, reason = detect_sets(phase, laps)
    assert updated is not None
    assert updated["label"] == "Intervals"
    assert updated["reps_detected"] == 6
    assert updated["sets_detected"] == 1
    assert updated["reps_per_set"] == [6]
    assert reason is None


def test_uat_step2_twelve_reps_two_sets():
    """AC9/UAT-2: 12 reps, long mid-recovery → sets_detected=2, reps_per_set=[6,6]."""
    laps = _two_set_laps(set_size=6, short_rec=90, long_rec=270)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"reason: {reason}"
    assert phase["reps_detected"] == 12
    updated, reason = detect_sets(phase, laps)
    assert updated is not None
    assert updated["sets_detected"] == 2
    assert updated["reps_detected"] == 6
    assert updated["reps_per_set"] == [6, 6]
    assert reason is None


# ── AC10: tolerance boundary ───────────────────────────────────────────────────

def test_tolerance_boundary_just_inside():
    """AC10: rep whose duration is just inside HARD_REP_TOLERANCE is included.

    With HARD_REP_TOLERANCE=0.25 and median=60 s, the threshold is 15 s.
    A rep at 45 s (exactly on the boundary: abs(45-60)=15, 15 > 15 is False)
    is included.
    """
    tolerance = HARD_REP_TOLERANCE  # 0.25
    median_dur = 60.0
    threshold = tolerance * median_dur  # 15.0
    inside_dur = median_dur - threshold  # 45.0 — on the boundary, included

    laps = [
        _hard(inside_dur), _easy(90),
        _hard(60), _easy(90),
        _hard(60), _easy(90),
        _hard(60), _easy(90),
    ]
    phase, reason = detect_intervals(laps)
    # The first rep (45 s) is inside/on the boundary; all 4 cycles should succeed.
    assert phase is not None, f"expected success, got: {reason}"
    # The 45 s rep should be represented in the detected phase.
    hard_durs = [
        laps[idx]["duration_seconds"]
        for idx in phase["lap_indexes"]
        if laps[idx]["band"] in {"tempo", "threshold"}
    ]
    assert inside_dur in hard_durs


def test_tolerance_boundary_just_outside():
    """AC10: rep whose duration is just outside HARD_REP_TOLERANCE is excluded.

    With HARD_REP_TOLERANCE=0.25 and median=60 s, a rep at 44 s (delta=16 > 15)
    is anomalous and breaks the sequence at that point.  The algorithm restarts
    from the next hard rep; the prefix before the anomalous rep may still satisfy
    the 2-cycle minimum.
    """
    tolerance = HARD_REP_TOLERANCE  # 0.25
    median_dur = 60.0
    threshold = tolerance * median_dur  # 15.0
    outside_dur = median_dur - threshold - 1.0  # 44.0 — strictly outside

    laps = [
        _hard(outside_dur), _easy(90),  # anomalous rep
        _hard(60), _easy(90),
        _hard(60), _easy(90),
        _hard(60), _easy(90),
    ]
    phase, _ = detect_intervals(laps)
    # The 44 s rep must not appear in the detected phase
    if phase is not None:
        hard_durs = [
            laps[idx]["duration_seconds"]
            for idx in phase["lap_indexes"]
            if laps[idx]["band"] in {"tempo", "threshold"}
        ]
        assert outside_dur not in hard_durs


# ── AC5/AC10: detect_sets null/invalid inputs ─────────────────────────────────

def test_detect_sets_null_phase():
    """AC10: intervals_phase=None → (None, reason_str)."""
    result, reason = detect_sets(None, _uniform_laps(4))
    assert result is None
    assert isinstance(reason, str)


def test_detect_sets_null_laps():
    """AC10: laps=None → (None, reason_str)."""
    phase, _ = detect_intervals(_uniform_laps(4))
    result, reason = detect_sets(phase, None)
    assert result is None
    assert isinstance(reason, str)


def test_detect_sets_empty_laps():
    """AC10: laps=[] → (None, reason_str)."""
    phase, _ = detect_intervals(_uniform_laps(4))
    result, reason = detect_sets(phase, [])
    assert result is None
    assert isinstance(reason, str)


# ── AC7: plain arithmetic median ──────────────────────────────────────────────

def test_median_computed_without_statistics_library():
    """AC7: detect_sets returns correct results consistent with plain arithmetic median.

    Median of [90, 90, 90, 90, 270] (5 values) = 90 (the 3rd sorted value).
    With SET_BOUNDARY_MULTIPLIER=1.5, threshold = 90 * 1.5 = 135.
    The 270 s recovery > 135 → set boundary detected → sets_detected == 2.
    """
    # 4 short recoveries (90s) + 1 long (270s) at cycle-4 boundary
    laps = _two_set_laps(set_size=4, short_rec=90, long_rec=270)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"reason: {reason}"
    updated, _ = detect_sets(phase, laps)
    assert updated is not None
    assert updated["sets_detected"] == 2
    assert updated["reps_per_set"] == [4, 4]


def test_median_even_count_uses_average():
    """AC7: median of even-length list averages the two middle values.

    Recoveries: [90, 90, 180, 180] → sorted = [90, 90, 180, 180]
    Median = (90 + 180) / 2 = 135.
    With SET_BOUNDARY_MULTIPLIER=1.5, threshold = 135 * 1.5 = 202.5.
    A 200 s recovery (< 202.5) should NOT trigger a boundary → sets_detected=1.
    A 210 s recovery (> 202.5) should trigger a boundary → sets_detected=2.
    """
    def build_mixed_laps(long_rec):
        # 2 cycles with 90 s rec, then 2 cycles with 180 s rec (set-1 done),
        # then a boundary recovery of long_rec, then 2+2 more cycles
        laps = []
        for _ in range(2):
            laps.append(_hard(60))
            laps.append(_easy(90))
        for i in range(2):
            laps.append(_hard(60))
            laps.append(_easy(long_rec if i == 1 else 180))
        for _ in range(2):
            laps.append(_hard(60))
            laps.append(_easy(90))
        for _ in range(2):
            laps.append(_hard(60))
            laps.append(_easy(180))
        return laps

    laps_no_boundary = build_mixed_laps(200)
    phase, reason = detect_intervals(laps_no_boundary)
    assert phase is not None, f"reason: {reason}"
    updated_no, _ = detect_sets(phase, laps_no_boundary)
    assert updated_no is not None
    assert updated_no["sets_detected"] == 1

    laps_boundary = build_mixed_laps(210)
    phase2, reason2 = detect_intervals(laps_boundary)
    assert phase2 is not None, f"reason: {reason2}"
    updated_yes, _ = detect_sets(phase2, laps_boundary)
    assert updated_yes is not None
    assert updated_yes["sets_detected"] == 2


# ── AC5: SET_BOUNDARY_MULTIPLIER is config-driven (UAT step 6) ────────────────

def test_set_boundary_multiplier_at_2_0_suppresses_boundary(monkeypatch):
    """AC5/UAT-6: raising SET_BOUNDARY_MULTIPLIER to 2.0 suppresses the boundary.

    With short_rec=90 and long_rec=162 (1.8× median):
      default 1.5: 162 > 1.5*90=135 → 2 sets
      raised  2.0: 162 < 2.0*90=180 → 1 set
    """
    laps = _two_set_laps(set_size=3, short_rec=90, long_rec=162)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"reason: {reason}"

    monkeypatch.setattr(idet, "SET_BOUNDARY_MULTIPLIER", 1.5)
    updated_15, _ = detect_sets(dict(phase), laps)
    assert updated_15["sets_detected"] == 2

    monkeypatch.setattr(idet, "SET_BOUNDARY_MULTIPLIER", 2.0)
    updated_20, _ = detect_sets(dict(phase), laps)
    assert updated_20["sets_detected"] == 1
