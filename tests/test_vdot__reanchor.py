"""Unit tests for the shared VDOT helper (score re-anchor, Section 1).

Anchors validated against Daniels/Gilbert VDOT tables.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services import vdot  # noqa: E402
from backend.services.vdot import (  # noqa: E402
    vdot_from_pace_duration,
    vdot_from_pace_seconds,
    rescale_to_score,
    decay_points,
)


# ── VDOT vs Daniels anchors ────────────────────────────────────────────────────

def test_5k_20min_vdot_daniels_anchor():
    # 5000 m in 20:00 → v = 250 m/min, t = 20 min → Daniels VDOT ≈ 49–50
    v = 5000.0 / 20.0
    got = vdot_from_pace_duration(v, 20.0)
    assert 49.0 <= got <= 50.5, f"5k 20:00 VDOT {got} not in Daniels band"


def test_marathon_3h30_vdot_daniels_anchor():
    # 42195 m in 210 min → Daniels VDOT ≈ 44–46
    v = 42195.0 / 210.0
    got = vdot_from_pace_duration(v, 210.0)
    assert 44.0 <= got <= 46.0, f"marathon 3:30 VDOT {got} not in Daniels band"


def test_pace_seconds_convenience_matches_velocity():
    # 5k in 20:00 = 240 s/km, t = 20 → same as the velocity form.
    a = vdot_from_pace_seconds(240.0, 20.0)
    b = vdot_from_pace_duration(5000.0 / 20.0, 20.0)
    assert abs(a - b) < 1e-6


def test_faster_effort_yields_higher_vdot():
    slow = vdot_from_pace_duration(200.0, 30.0)
    fast = vdot_from_pace_duration(280.0, 30.0)
    assert fast > slow


def test_non_positive_inputs_return_zero():
    assert vdot_from_pace_duration(0, 20) == 0.0
    assert vdot_from_pace_duration(250, 0) == 0.0
    assert vdot_from_pace_duration(-5, 20) == 0.0
    assert vdot_from_pace_seconds(0, 20) == 0.0


# ── Rescale endpoints ───────────────────────────────────────────────────────────

def test_rescale_endpoints():
    assert rescale_to_score(vdot.VDOT_FLOOR) == 0.0    # VDOT 30 → 0
    assert rescale_to_score(vdot.VDOT_CEIL) == 100.0   # VDOT 85 → 100


def test_rescale_midband():
    # VDOT 55 → (55-30)/55*100 ≈ 45.45
    assert abs(rescale_to_score(55.0) - 45.4545) < 0.01


def test_rescale_clamps_out_of_band():
    assert rescale_to_score(10.0) == 0.0
    assert rescale_to_score(120.0) == 100.0


# ── Decay grace behaviour ───────────────────────────────────────────────────────

def test_decay_zero_inside_grace():
    assert decay_points(0) == 0.0
    assert decay_points(7) == 0.0          # 1 week — inside 2-week grace
    assert decay_points(14) == 0.0         # exactly 2 weeks — still zero


def test_decay_after_grace_is_1_5_per_week():
    # 3 weeks: (3 − 2) × 1.5 = 1.5
    assert abs(decay_points(21) - 1.5) < 1e-9
    # 4 weeks: (4 − 2) × 1.5 = 3.0
    assert abs(decay_points(28) - 3.0) < 1e-9


def test_decay_monotonic_after_grace():
    assert decay_points(35) > decay_points(28) > decay_points(21) > 0
