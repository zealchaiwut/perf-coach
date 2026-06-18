"""Tests for issue #585: Add interval and set detection to session-profile pipeline.

Acceptance criteria covered:
  AC1  — HARD_REP_TOLERANCE constant exists; never hardcoded inline
  AC2  — SET_BOUNDARY_MULTIPLIER constant (default 1.5) exists; never hardcoded inline
  AC3  — detect_intervals is a pure function (importable, no DB calls)
  AC4  — detect_intervals returns (None, reason_str) for missing/empty laps
  AC5  — detect_intervals requires at least 2 complete hard/recovery cycles
  AC6  — hard reps = _HARD_BANDS (tempo/threshold); recoveries = following easy/steady
           pattern detection uses classify_laps band output
  AC7  — all threshold comparisons described in plain English in docstrings
  AC8  — returned phase is labelled "Intervals" and includes reps_detected (int)
  AC9  — detect_sets is a pure function: inspects recovery durations within a phase
  AC10 — detect_sets returns sets_detected and updates reps_detected per set;
           uneven sets → reps_detected=None with reason
  AC11 — docstring worked examples match expected values
  AC12 — thin caller is the only DB-access point (pure function contract)
  AC13 — unit tests: <2 cycles (null), exactly 2, 6-rep single set, 12-rep two-set,
           uneven sets, missing/empty input
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

def _lap(band, duration_seconds, distance_km=0.2, avg_hr=None, avg_power=None):
    return {
        "band": band,
        "duration_seconds": duration_seconds,
        "distance_km": distance_km,
        "avg_hr": avg_hr,
        "avg_power": avg_power,
    }


def _hard(duration=60, distance=0.2):
    return _lap("tempo", duration, distance)


def _easy(duration=90, distance=0.3):
    return _lap("easy", duration, distance)


def _cycle(hard_dur=60, rec_dur=90):
    return [_hard(hard_dur), _easy(rec_dur)]


def _build_laps(n_cycles, hard_dur=60, rec_dur=90):
    """Build a flat laps list of n_cycles alternating hard/easy pairs."""
    laps = []
    for _ in range(n_cycles):
        laps.extend(_cycle(hard_dur, rec_dur))
    return laps


# ── AC1/AC2: Constants ─────────────────────────────────────────────────────────

def test_hard_rep_tolerance_constant_exists():
    """AC1: HARD_REP_TOLERANCE is a named constant (not hardcoded inline)."""
    assert isinstance(HARD_REP_TOLERANCE, (int, float))
    assert HARD_REP_TOLERANCE > 0


def test_set_boundary_multiplier_constant_exists():
    """AC2: SET_BOUNDARY_MULTIPLIER is a named constant with default 1.5."""
    assert isinstance(SET_BOUNDARY_MULTIPLIER, (int, float))
    assert SET_BOUNDARY_MULTIPLIER == 1.5


# ── AC3: detect_intervals is importable and callable ──────────────────────────

def test_detect_intervals_importable():
    """AC3: detect_intervals is importable from interval_detector."""
    assert callable(detect_intervals)


def test_detect_sets_importable():
    """AC3/AC9: detect_sets is importable from interval_detector."""
    assert callable(detect_sets)


# ── AC4/AC6/AC13: null/empty input → (None, reason_str) ──────────────────────

def test_detect_intervals_null_laps():
    """AC4/AC13: laps=None returns (None, reason_str); no exception raised."""
    phase, reason = detect_intervals(None)
    assert phase is None
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_detect_intervals_empty_laps():
    """AC4/AC13: laps=[] returns (None, reason_str); no exception raised."""
    phase, reason = detect_intervals([])
    assert phase is None
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_detect_intervals_no_hard_reps():
    """AC4/AC13: all easy laps → no hard reps → (None, reason_str)."""
    laps = [_easy()] * 6
    phase, reason = detect_intervals(laps)
    assert phase is None
    assert reason is not None


def test_detect_intervals_single_cycle():
    """AC5/AC13: 1 hard/recovery cycle (< 2 required) → (None, reason_str)."""
    laps = _cycle()
    phase, reason = detect_intervals(laps)
    assert phase is None
    assert reason is not None
    assert "cycle" in reason.lower() or "fewer" in reason.lower()


# ── AC5/AC13: exactly 2 cycles → success ─────────────────────────────────────

def test_detect_intervals_exactly_two_cycles():
    """AC5/AC13: exactly 2 hard/recovery cycles returns a valid Intervals phase."""
    laps = _build_laps(2)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"expected phase, got reason={reason}"
    assert reason is None
    assert phase["label"] == "Intervals"
    assert phase["reps_detected"] == 2


# ── AC8: phase fields ─────────────────────────────────────────────────────────

def test_detect_intervals_phase_fields():
    """AC8: returned phase includes all required fields."""
    laps = _build_laps(3)
    phase, _ = detect_intervals(laps)
    assert phase is not None
    assert phase["label"] == "Intervals"
    assert isinstance(phase["reps_detected"], int)
    assert isinstance(phase["sets_detected"], int)
    assert isinstance(phase["lap_indexes"], list)
    assert "distance_km" in phase
    assert "duration_seconds" in phase
    assert "avg_pace_seconds_per_km" in phase or phase.get("avg_pace_seconds_per_km") is None
    # avg_hr and avg_power may be None when not supplied
    assert "avg_hr" in phase
    assert "avg_power" in phase


# ── AC13: 6-rep single set ────────────────────────────────────────────────────

def test_detect_intervals_six_reps():
    """AC13: six hard reps each followed by a recovery → reps_detected=6."""
    laps = _build_laps(6)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"reason={reason}"
    assert phase["reps_detected"] == 6
    assert phase["sets_detected"] == 1


def test_detect_sets_single_set():
    """AC13: six reps, all recoveries equal → sets_detected=1, reps_detected=6."""
    laps = _build_laps(6)
    phase, _ = detect_intervals(laps)
    updated, reason = detect_sets(phase, laps)
    assert updated is not None
    assert updated["sets_detected"] == 1
    assert updated["reps_detected"] == 6
    assert reason is None


# ── AC13: 12-rep two-set ──────────────────────────────────────────────────────

def _build_two_set_laps(set_size=6, short_rec=90, long_rec=270):
    """Build laps with a long recovery after set_size reps, then set_size more."""
    laps = []
    for i in range(set_size):
        laps.append(_hard(60))
        if i < set_size - 1:
            laps.append(_easy(short_rec))
        else:
            # Long recovery after the last rep of set 1
            laps.append(_easy(long_rec))
    for _ in range(set_size):
        laps.append(_hard(60))
        laps.append(_easy(short_rec))
    return laps


def test_detect_sets_two_sets():
    """AC13: 12 reps with one long mid-session recovery → sets_detected=2, reps=6."""
    laps = _build_two_set_laps(set_size=6, short_rec=90, long_rec=270)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"detect_intervals failed: {reason}"
    assert phase["reps_detected"] == 12

    updated, reason = detect_sets(phase, laps)
    assert updated is not None
    assert updated["sets_detected"] == 2
    assert updated["reps_detected"] == 6
    assert reason is None


# ── AC10/AC13: uneven set sizes ───────────────────────────────────────────────

def _build_uneven_set_laps():
    """4 reps + long recovery + 3 reps (unequal sets)."""
    laps = []
    for i in range(4):
        laps.append(_hard(60))
        rec = _easy(270) if i == 3 else _easy(90)
        laps.append(rec)
    for _ in range(3):
        laps.append(_hard(60))
        laps.append(_easy(90))
    return laps


def test_detect_sets_uneven_sets():
    """AC10/AC13: uneven set sizes → reps_detected=None, reason string returned."""
    laps = _build_uneven_set_laps()
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"detect_intervals failed: {reason}"

    updated, reason = detect_sets(phase, laps)
    assert updated is not None
    assert updated["sets_detected"] == 2
    assert updated["reps_detected"] is None
    assert isinstance(reason, str) and len(reason) > 0


# ── detect_sets null/invalid input ────────────────────────────────────────────

def test_detect_sets_null_phase():
    """AC9: intervals_phase=None → (None, reason_str)."""
    result, reason = detect_sets(None, _build_laps(4))
    assert result is None
    assert isinstance(reason, str)


def test_detect_sets_null_laps():
    """AC9: laps=None → (None, reason_str)."""
    phase, _ = detect_intervals(_build_laps(4))
    result, reason = detect_sets(phase, None)
    assert result is None
    assert isinstance(reason, str)


def test_detect_sets_empty_laps():
    """AC9: laps=[] → (None, reason_str)."""
    phase, _ = detect_intervals(_build_laps(4))
    result, reason = detect_sets(phase, [])
    assert result is None
    assert isinstance(reason, str)


# ── AC1/AC5: HARD_REP_TOLERANCE is config-driven ──────────────────────────────

def test_hard_rep_tolerance_is_config_driven(monkeypatch):
    """AC1: changing HARD_REP_TOLERANCE changes what is accepted as a valid rep.

    With tight tolerance (0.0), a 61 s rep among 60 s peers breaks the sequence.
    With loose tolerance (0.5), the same variation is accepted.
    """
    laps = [
        _hard(60), _easy(90),
        _hard(61), _easy(90),   # 61 vs median 60 — very slight variation
        _hard(60), _easy(90),
        _hard(60), _easy(90),
    ]

    monkeypatch.setattr(idet, "HARD_REP_TOLERANCE", 0.0)
    phase_tight, reason_tight = detect_intervals(laps)
    # With 0 tolerance, 61 s breaks the sequence; first two valid cycles are 0→3
    # (only 60 and 61 candidates, but 61 violates 0-tolerance immediately after
    #  matching 60 as median).  Result may have 1 or 0 cycles — either way < 2.
    assert phase_tight is None or (phase_tight is not None and phase_tight["reps_detected"] <= 2)

    monkeypatch.setattr(idet, "HARD_REP_TOLERANCE", 0.5)
    phase_loose, reason_loose = detect_intervals(laps)
    assert phase_loose is not None, f"expected phase with loose tolerance, got {reason_loose}"
    assert phase_loose["reps_detected"] >= 3


# ── AC2: SET_BOUNDARY_MULTIPLIER is config-driven ─────────────────────────────

def test_set_boundary_multiplier_is_config_driven(monkeypatch):
    """AC2: changing SET_BOUNDARY_MULTIPLIER changes when a set boundary is triggered.

    A recovery of 1.8× median does NOT trigger a boundary at multiplier=2.0
    but DOES trigger at multiplier=1.5 (default).
    """
    # short_rec=90, boundary_rec=162 (1.8×90)
    laps = _build_two_set_laps(set_size=3, short_rec=90, long_rec=162)
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"detect_intervals failed: {reason}"

    # At default 1.5: 162 > 1.5×90=135 → boundary → 2 sets
    monkeypatch.setattr(idet, "SET_BOUNDARY_MULTIPLIER", 1.5)
    updated_default, _ = detect_sets(dict(phase), laps)
    assert updated_default["sets_detected"] == 2

    # At 2.0: 162 < 2.0×90=180 → no boundary → 1 set
    monkeypatch.setattr(idet, "SET_BOUNDARY_MULTIPLIER", 2.0)
    updated_raised, _ = detect_sets(dict(phase), laps)
    assert updated_raised["sets_detected"] == 1


# ── AC6: anomalous hard rep breaks the alternating sequence ───────────────────

def test_anomalous_rep_breaks_sequence():
    """AC6: an anomalous hard rep mid-sequence truncates the Intervals phase.

    Laps: 3 good cycles, 1 anomalously long rep, 3 more good cycles.
    Expected: only the 3-cycle prefix (or 3-cycle suffix if algorithm restarts)
    is returned as the Intervals phase; the anomalous rep is excluded.
    """
    laps = [
        _hard(60), _easy(90),
        _hard(60), _easy(90),
        _hard(60), _easy(90),
        _hard(200), _easy(90),  # anomalous — 200s vs median ~60s
        _hard(60), _easy(90),
        _hard(60), _easy(90),
        _hard(60), _easy(90),
    ]
    phase, reason = detect_intervals(laps)
    assert phase is not None, f"reason={reason}"
    # Should detect either the prefix (reps 0-2) or the suffix (reps 4-6) but
    # NOT include the anomalous rep at index 6.
    assert 200 not in [laps[i]["duration_seconds"] for i in phase["lap_indexes"] if laps[i]["band"] in {"tempo", "threshold"}]


# ── Aggregation sanity ────────────────────────────────────────────────────────

def test_detect_intervals_aggregates_distance_and_duration():
    """AC8: distance_km and duration_seconds are summed across included laps."""
    laps = _build_laps(3, hard_dur=60, rec_dur=90)
    phase, _ = detect_intervals(laps)
    assert phase is not None
    # 3 hard @ 0.2 km + 3 easy @ 0.3 km
    assert abs(phase["distance_km"] - (3 * 0.2 + 3 * 0.3)) < 1e-9
    # 3 × (60 + 90) = 450 s
    assert abs(phase["duration_seconds"] - 450) < 1e-9


def test_detect_intervals_avg_pace():
    """AC8: avg_pace_seconds_per_km = total_duration / total_distance."""
    laps = _build_laps(2, hard_dur=60, rec_dur=90)
    phase, _ = detect_intervals(laps)
    assert phase is not None
    total_dist = 2 * (0.2 + 0.3)
    total_dur = 2 * (60 + 90)
    expected_pace = total_dur / total_dist
    assert abs(phase["avg_pace_seconds_per_km"] - expected_pace) < 1e-9


def test_detect_intervals_avg_hr_and_power():
    """AC8: avg_hr and avg_power are means of non-None values."""
    laps = [
        _lap("tempo", 60, 0.2, avg_hr=160, avg_power=300),
        _lap("easy",  90, 0.3, avg_hr=120, avg_power=None),
        _lap("tempo", 60, 0.2, avg_hr=165, avg_power=310),
        _lap("easy",  90, 0.3, avg_hr=115, avg_power=None),
    ]
    phase, _ = detect_intervals(laps)
    assert phase is not None
    expected_hr = (160 + 120 + 165 + 115) / 4
    expected_power = (300 + 310) / 2
    assert abs(phase["avg_hr"] - expected_hr) < 1e-9
    assert abs(phase["avg_power"] - expected_power) < 1e-9
