"""The lean-mass guard can actually fire — issue #1598.

This guard has one job: notice when a deficit is eating muscle and pause it. It
could not do that job.

The old rule counted LEAN_MASS_FALL_WEEKS consecutive raw weekly readings, each
falling by more than a 0.15 kg dead-band. Measured against a simulated athlete
genuinely losing lean mass under realistic bioimpedance scatter, it had two
independent defects:

1. The dead-band was applied per STEP with a strict comparison, so a decline at
   or below 0.15 kg/week was invisible FOREVER — even with perfect measurements.
   That is roughly 0.6 kg of lean mass a month, silently.
2. Any flat or up week reset the run to zero. Against a genuine decline with
   ±1.0 point of body-fat scatter, it fired in about 4% of cases.

It now compares 4-week block means, which is how this module smooths every other
trend it reports. The guard was the one place reading raw consecutive values.

The threshold was chosen by simulation, not intuition — see
body_composition.LEAN_MASS_FALL_DELTA_KG for the measured trade-off table.
"""
from __future__ import annotations

import datetime
import random

import pytest

from backend.services.body_composition import (
    LEAN_MASS_FALL_DELTA_KG,
    LEAN_MASS_NOISE_KG,
    _count_falling_weeks,
    compute_composition_trend,
)

_START = datetime.date(2026, 1, 5)


def _readings(weeks: int, noise_pts: float, rate_kg_per_week: float, seed: int):
    """Weekly readings for an athlete losing lean mass at a known rate.

    Noise enters through the body-fat reading, as it does in reality — lean mass
    is derived, never measured.
    """
    random.seed(seed)
    weight, bf = 87.0, 20.0
    out = []
    for w in range(weeks):
        jitter = random.uniform(-noise_pts, noise_pts)
        lean_target = weight * (1 - bf / 100) - rate_kg_per_week * w
        eff_bf = (1 - lean_target / weight) * 100 + jitter
        out.append({
            "date": _START + datetime.timedelta(weeks=w),
            "weight_kg": weight,
            "body_fat_pct": round(eff_bf, 1),
        })
    return out


def _today(weeks: int) -> datetime.date:
    return _START + datetime.timedelta(weeks=weeks - 1)


def _fire_rate(rate, noise=1.0, trials=400, weeks=12):
    fired = 0
    for seed in range(trials):
        out = compute_composition_trend(_readings(weeks, noise, rate, seed), today=_today(weeks))
        if out.get("lean_mass_falling"):
            fired += 1
    return fired / trials


# ── The defect the old rule had ───────────────────────────────────────────────

def test_old_rule_could_not_see_a_decline_at_the_dead_band_rate():
    """Defect 1, pinned so it cannot come back.

    `newer < older - 0.15` requires the drop to EXCEED the dead band, so a clean
    0.15 kg/week decline — with no noise at all — counted as zero falling weeks
    forever.
    """
    perfect = [{"lean_mass_kg": round(70.0 - LEAN_MASS_NOISE_KG * i, 3)} for i in range(12)]
    assert _count_falling_weeks(perfect) == 0


def test_old_rule_is_reset_by_a_single_flat_week():
    """Defect 2. One wobble in an otherwise steady decline zeroes the run."""
    vals = [70.0, 69.6, 69.2, 69.2, 68.8, 68.4]  # one flat step in the middle
    rows = [{"lean_mass_kg": v} for v in vals]
    assert _count_falling_weeks(rows) < 3


# ── The new rule works ────────────────────────────────────────────────────────

def test_a_real_decline_is_detected():
    """0.25 kg/week is a serious loss — roughly a kilo of muscle a month."""
    assert _fire_rate(0.25) > 0.70


def test_a_slow_decline_is_detected_far_more_often_than_before():
    """0.15 kg/week was INVISIBLE to the old rule by construction. It is now
    caught about 40% of the time per weekly check — and the guard is evaluated
    every week, so a sustained decline gets many chances."""
    assert _fire_rate(0.15) > 0.25


def test_a_flat_athlete_is_rarely_paused():
    """A guard that cries wolf gets ignored, and an ignored guard protects
    nobody — the reason the threshold is not lower."""
    assert _fire_rate(0.0) < 0.08


def test_detection_beats_the_old_rule_at_every_rate():
    """The comparison that justifies the change."""
    for rate in (0.15, 0.25):
        old = 0
        for seed in range(400):
            rows = [
                {"lean_mass_kg": round(r["weight_kg"] * (1 - r["body_fat_pct"] / 100), 2)}
                for r in _readings(12, 1.0, rate, seed)
            ]
            if _count_falling_weeks(rows) >= 3:
                old += 1
        assert _fire_rate(rate) > old / 400, f"no improvement at {rate} kg/wk"


# ── Shape and wiring ──────────────────────────────────────────────────────────

def test_guard_reads_the_smoothed_signal_not_the_raw_count():
    import inspect

    from backend.services import deficit_guard

    src = inspect.getsource(deficit_guard.evaluate_deficit_guard) \
        if hasattr(deficit_guard, "evaluate_deficit_guard") else \
        (deficit_guard.__file__ and open(deficit_guard.__file__).read())
    assert "lean_mass_falling or lean_mass_falling_weeks" in src


def test_the_raw_count_is_still_reported():
    """Kept deliberately: it is readable and still surfaced. It just cannot
    carry the guard."""
    out = compute_composition_trend(_readings(12, 0.5, 0.25, 1), today=_today(12))
    assert "lean_mass_falling_weeks" in out
    assert "lean_mass_falling" in out


def test_falling_is_false_without_enough_data():
    """Two 4-week blocks are needed before there is anything to compare — and
    silence beats a confident answer built on three readings."""
    out = compute_composition_trend(_readings(3, 0.5, 0.5, 1), today=_today(3))
    assert out["lean_mass_falling"] is False


def test_empty_history_is_not_falling():
    out = compute_composition_trend([], today=_today(1))
    assert out["lean_mass_falling"] is False


def test_threshold_is_documented_with_its_measurements():
    """The number is a judgement call about a real trade-off; the evidence for
    it belongs next to it, not in a PR description nobody re-reads."""
    from pathlib import Path

    src = Path(
        __import__("backend.services.body_composition", fromlist=["x"]).__file__
    ).read_text()
    assert "false+" in src or "false positive" in src.lower()
    assert str(LEAN_MASS_FALL_DELTA_KG) in src
