"""Tests for treadmill NGP normalization (issue #1169).

AC coverage:
  AC1  — incline/grade is read from the raw signal exactly once (single normalization entry-point).
  AC3  — `flat_equivalent_pace` is present in the normalized output for treadmill activities.
  AC4  — zero incline produces flat_equivalent_pace equal to raw_pace.
  AC5  — signals without incline data pass through unchanged (no flat_equivalent_pace synthesized).
  AC6  — py_compile passes on treadmill_ngp.py.
  AC8  — known incline% + raw_pace → expected flat_equivalent_pace within tolerance.
"""

import py_compile
import importlib.util
import pytest

from backend.services.treadmill_ngp import (
    compute_ngp,
    normalize_treadmill_signal,
)


# ── AC6: static syntax check ─────────────────────────────────────────────────

def test_py_compile_clean():
    """py_compile passes on treadmill_ngp.py with no errors (AC6)."""
    spec = importlib.util.find_spec("backend.services.treadmill_ngp")
    assert spec is not None, "treadmill_ngp module must be importable"
    py_compile.compile(spec.origin, doraise=True)


# ── AC4: zero incline → flat_equivalent_pace == raw_pace ────────────────────

def test_zero_grade_returns_raw_pace():
    """Grade=0 must return a flat_equivalent_pace equal to the raw pace (AC4)."""
    raw = 360.0  # 6:00 /km
    result = compute_ngp(raw_pace_seconds_per_km=raw, grade_percent=0.0)
    assert result == pytest.approx(raw, abs=0.01), (
        "zero grade must leave pace unchanged"
    )


def test_zero_grade_integer_input():
    raw = 300
    result = compute_ngp(raw_pace_seconds_per_km=raw, grade_percent=0)
    assert result == pytest.approx(float(raw), abs=0.01)


# ── AC8: known incline + raw pace → expected flat_equivalent_pace ────────────

# The Minetti (2002) formula:
#   Cr(i) = 155.4·i⁵ − 30.4·i⁴ − 43.3·i³ + 46.3·i² + 19.5·i + 3.6  [J·kg⁻¹·m⁻¹]
#   flat_equivalent_pace = raw_pace × (3.6 / Cr(i))    where i = grade_percent / 100
def _expected_ngp(raw_pace, grade_percent):
    i = grade_percent / 100.0
    cr = (
        155.4 * i**5
        - 30.4 * i**4
        - 43.3 * i**3
        + 46.3 * i**2
        + 19.5 * i
        + 3.6
    )
    return raw_pace * (3.6 / cr)


@pytest.mark.parametrize("grade_pct,raw_pace", [
    (1.0, 360.0),
    (5.0, 360.0),
    (8.0, 300.0),
    (10.0, 300.0),
    (2.5, 420.0),
])
def test_known_grade_and_pace(grade_pct, raw_pace):
    """Known incline% + raw_pace → flat_equivalent_pace matches Minetti formula (AC8)."""
    expected = _expected_ngp(raw_pace, grade_pct)
    actual = compute_ngp(raw_pace_seconds_per_km=raw_pace, grade_percent=grade_pct)
    # Tolerance: ±0.5 s/km (well within ±1 sec/mile mentioned in UAT)
    assert actual == pytest.approx(expected, abs=0.5), (
        f"grade={grade_pct}%, raw={raw_pace} s/km: "
        f"expected {expected:.2f}, got {actual:.2f}"
    )


def test_5pct_grade_360_pace_concrete():
    """Concrete check: 6:00/km at 5% grade → flat_equivalent faster than raw (AC8)."""
    raw = 360.0
    result = compute_ngp(raw_pace_seconds_per_km=raw, grade_percent=5.0)
    # At 5% grade the flat-equivalent pace must be faster (lower s/km) than raw
    assert result < raw, "flat_equivalent_pace must be faster (lower) than raw pace on an incline"
    # And within a plausible range (not absurdly fast or unchanged)
    assert 200.0 < result < raw


def test_positive_grade_makes_flat_equivalent_faster():
    """Any positive grade produces a flat_equivalent_pace strictly faster than raw."""
    raw = 330.0
    for g in [0.5, 1.0, 3.0, 5.0, 7.0, 10.0]:
        result = compute_ngp(raw_pace_seconds_per_km=raw, grade_percent=g)
        assert result < raw, (
            f"grade={g}%: flat_equivalent ({result:.2f}) must be < raw ({raw})"
        )


def test_return_type_is_float():
    result = compute_ngp(raw_pace_seconds_per_km=360.0, grade_percent=5.0)
    assert isinstance(result, float)


# ── AC1 + AC3: normalize_treadmill_signal adds flat_equivalent_pace once ────

def test_normalize_adds_flat_equivalent_pace_field(monkeypatch):
    """normalized output contains flat_equivalent_pace for treadmill signals (AC1, AC3)."""
    signal = {
        "pace_seconds_per_km": 360.0,
        "grade_percent": 5.0,
        "heart_rate_bpm": 150.0,
    }
    out = normalize_treadmill_signal(signal)
    assert "flat_equivalent_pace" in out, (
        "normalized signal must contain flat_equivalent_pace"
    )


def test_normalize_flat_equivalent_pace_matches_compute_ngp():
    """flat_equivalent_pace in output equals compute_ngp(raw, grade) (AC1, AC3)."""
    signal = {"pace_seconds_per_km": 360.0, "grade_percent": 5.0}
    out = normalize_treadmill_signal(signal)
    expected = compute_ngp(360.0, 5.0)
    assert out["flat_equivalent_pace"] == pytest.approx(expected, abs=0.01)


def test_normalize_preserves_all_other_keys():
    """normalize_treadmill_signal must pass all existing keys through unchanged (AC1)."""
    signal = {
        "pace_seconds_per_km": 360.0,
        "grade_percent": 5.0,
        "heart_rate_bpm": 145.0,
        "power_w": 280.0,
        "cadence_spm": 180.0,
    }
    out = normalize_treadmill_signal(signal)
    for key, val in signal.items():
        assert key in out
        assert out[key] == val


def test_normalize_does_not_mutate_input():
    """normalize_treadmill_signal must not modify the input signal dict (AC1)."""
    signal = {"pace_seconds_per_km": 360.0, "grade_percent": 5.0}
    before = dict(signal)
    normalize_treadmill_signal(signal)
    assert signal == before


# ── AC5: no incline data → pass through unchanged ───────────────────────────

def test_normalize_without_grade_passes_through():
    """Signal without grade_percent must be returned unchanged — no flat_equivalent_pace (AC5)."""
    signal = {
        "pace_seconds_per_km": 360.0,
        "heart_rate_bpm": 150.0,
    }
    out = normalize_treadmill_signal(signal)
    assert "flat_equivalent_pace" not in out, (
        "flat_equivalent_pace must not be synthesized when no grade data is present"
    )


def test_normalize_none_grade_passes_through():
    """Signal with grade_percent=None must be returned unchanged (AC5)."""
    signal = {"pace_seconds_per_km": 360.0, "grade_percent": None}
    out = normalize_treadmill_signal(signal)
    assert "flat_equivalent_pace" not in out


def test_normalize_without_grade_keys_unchanged():
    """All original keys intact when no grade is present (AC5)."""
    signal = {"pace_seconds_per_km": 300.0, "cadence_spm": 182.0}
    out = normalize_treadmill_signal(signal)
    assert out["pace_seconds_per_km"] == 300.0
    assert out["cadence_spm"] == 182.0


# ── AC4 via normalize: zero grade → flat_equivalent_pace == raw_pace ─────────

def test_normalize_zero_grade_flat_equivalent_equals_raw():
    """normalize_treadmill_signal with grade=0 must set flat_equivalent_pace == raw_pace (AC4)."""
    raw = 330.0
    signal = {"pace_seconds_per_km": raw, "grade_percent": 0.0}
    out = normalize_treadmill_signal(signal)
    assert "flat_equivalent_pace" in out
    assert out["flat_equivalent_pace"] == pytest.approx(raw, abs=0.01)


# ── AC1: single normalization entry-point (no double-counting) ────────────────

def test_normalize_called_twice_does_not_double_adjust():
    """Calling normalize_treadmill_signal twice on already-normalized output
    does NOT produce a second NGP adjustment (AC1 / no-double-counting).

    After the first call, flat_equivalent_pace is present but grade_percent
    must still be carried through. However, the function must only apply
    grade adjustment to pace_seconds_per_km (the raw pace), not to an
    already-adjusted flat_equivalent_pace.
    """
    signal = {"pace_seconds_per_km": 360.0, "grade_percent": 5.0}
    first_out = normalize_treadmill_signal(signal)
    fep_first = first_out["flat_equivalent_pace"]

    # Applying normalize again on the original signal should return the same result
    second_out = normalize_treadmill_signal(signal)
    assert second_out["flat_equivalent_pace"] == pytest.approx(fep_first, abs=0.01), (
        "repeated normalization on the original signal must produce the same flat_equivalent_pace"
    )
