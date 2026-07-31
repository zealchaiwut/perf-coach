"""Tests for issue #1359: lean-mass protein target and cut guard.

AC1 — current_lean_mass_kg(): three fallback paths
        measured: bf% within 60d → ewma_weight × (1 − bf%)
        setting: FuelSettings.lean_mass_kg when no recent bf%
        estimated: weight × 0.76 when neither
AC2 — protein target computed from lean mass when measured; total weight otherwise
      fuel payload exposes lean_mass_kg + lean_mass_source
AC4 — docs/calculations/fuel.md mentions lean-mass derivation (checked separately)

AC3 is gone — see below.

## Where AC3 went

AC3 covered ``cut_review.compute_losing_lean_mass_flag`` and the
``losing_lean_mass`` key on the cut-review payload: two body-fat readings ≥14
days apart, lean mass fell >0.3 kg, and weight also fell.

That function was added by #1359 on 2026-07-13 and deleted the same day by
#1355's rewrite of ``cut_review.py`` — a merge collision, not a decision
(#1355's branch predated #1359 landing, and its wholesale rewrite of the file
did not carry the addition forward). Nothing has imported ``losing_lean_mass``
since; this module's own import of it is why the whole file stopped collecting,
taking the nine still-valid AC1/AC2 tests with it.

The capability returned on 2026-07-30 with the lean program (#1594) as
``deficit_guard.lean_mass_falling``, driven by
``body_composition.lean_mass_falling_weeks`` and covered by
tests/test_lean_program__deficit_guards.py. Its semantics are different —
3 consecutive falling weekly readings rather than 2 readings ≥14 days apart —
and whether that is sensitive enough is under review in #1598.

The AC3 tests were removed rather than repaired: they asserted a deleted
function, and reviving it would leave two lean-mass guards with different
thresholds answering the same question. Do not re-add it here; #1598 is where
that guard's behaviour is being decided.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.services import fuel


# ─────────────────────────────────────────────────────────────────────────────
# AC1: current_lean_mass_kg() — three fallback paths
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSettings:
    lean_mass_kg = None


class _FakeBFReading:
    def __init__(self, *, body_fat_pct, measure_date):
        self.body_fat_pct = body_fat_pct
        self.measure_date = measure_date


def test_lean_mass_source_measured_when_bf_pct_within_60_days():
    """AC1: bf% within 60 days → source='measured', lean = ewma_weight × (1 − bf%)."""
    settings = _FakeSettings()
    settings.lean_mass_kg = None
    bf_readings = [_FakeBFReading(body_fat_pct=20.0, measure_date=date.today() - timedelta(days=5))]
    ewma_weight = 80.0

    result = fuel.current_lean_mass_kg(bf_readings, settings=settings, ewma_weight=ewma_weight)

    assert result["source"] == "measured"
    assert result["lean_mass_kg"] == pytest.approx(64.0, abs=0.05)


def test_lean_mass_source_measured_at_exactly_60_days():
    """AC1: bf% exactly 60 days old is still within the window."""
    settings = _FakeSettings()
    bf_readings = [
        _FakeBFReading(body_fat_pct=25.0, measure_date=date.today() - timedelta(days=60))
    ]
    ewma_weight = 80.0

    result = fuel.current_lean_mass_kg(bf_readings, settings=settings, ewma_weight=ewma_weight)

    assert result["source"] == "measured"
    assert result["lean_mass_kg"] == pytest.approx(60.0, abs=0.05)


def test_lean_mass_source_setting_when_no_recent_bf_pct():
    """AC1: no bf% within 60d + FuelSettings.lean_mass_kg set → source='setting'."""
    settings = _FakeSettings()
    settings.lean_mass_kg = 62.0
    # bf% reading older than 60 days
    bf_readings = [
        _FakeBFReading(body_fat_pct=22.0, measure_date=date.today() - timedelta(days=61))
    ]
    ewma_weight = 80.0

    result = fuel.current_lean_mass_kg(bf_readings, settings=settings, ewma_weight=ewma_weight)

    assert result["source"] == "setting"
    assert result["lean_mass_kg"] == pytest.approx(62.0, abs=0.01)


def test_lean_mass_source_estimated_when_no_bf_and_no_setting():
    """AC1: no bf% and no FuelSettings.lean_mass_kg → source='estimated', lean = weight × 0.76."""
    settings = _FakeSettings()
    settings.lean_mass_kg = None
    bf_readings = []
    ewma_weight = 80.0

    result = fuel.current_lean_mass_kg(bf_readings, settings=settings, ewma_weight=ewma_weight)

    assert result["source"] == "estimated"
    assert result["lean_mass_kg"] == pytest.approx(60.8, abs=0.05)


def test_lean_mass_uses_most_recent_bf_reading_within_window():
    """AC1: the most-recent bf% within 60d is used, not the oldest."""
    settings = _FakeSettings()
    settings.lean_mass_kg = None
    bf_readings = [
        _FakeBFReading(body_fat_pct=25.0, measure_date=date.today() - timedelta(days=30)),
        _FakeBFReading(body_fat_pct=20.0, measure_date=date.today() - timedelta(days=5)),  # newest
    ]
    ewma_weight = 80.0

    result = fuel.current_lean_mass_kg(bf_readings, settings=settings, ewma_weight=ewma_weight)

    assert result["source"] == "measured"
    # 20% bf → 64 kg lean (not 25% bf → 60 kg)
    assert result["lean_mass_kg"] == pytest.approx(64.0, abs=0.05)


# ─────────────────────────────────────────────────────────────────────────────
# AC2: protein target — measured uses lean mass, non-measured uses total weight
# ─────────────────────────────────────────────────────────────────────────────

def test_protein_target_uses_lean_mass_when_source_measured():
    """AC2: source='measured' → protein = protein_g_per_kg × lean_mass_kg."""
    settings = {"weight_kg": 80.0, "protein_g_per_kg": 2.0, "fat_g": 70}
    targets = fuel.compute_targets(
        settings, budget=2400, lean_mass_kg=64.0, lean_mass_source="measured")

    # 2.0 × 64.0 = 128 g protein (not 2.0 × 80 = 160 g)
    assert targets["protein_g"] == 128


def test_protein_target_uses_total_weight_when_source_estimated():
    """AC2: source='estimated' → protein = protein_g_per_kg × weight_kg (existing behavior)."""
    settings = {"weight_kg": 80.0, "protein_g_per_kg": 2.0, "fat_g": 70}
    targets = fuel.compute_targets(
        settings, budget=2400, lean_mass_kg=60.8, lean_mass_source="estimated")

    # 2.0 × 80.0 = 160 g protein (legacy behavior preserved)
    assert targets["protein_g"] == 160


def test_protein_target_uses_total_weight_when_source_setting():
    """AC2: source='setting' → protein = protein_g_per_kg × weight_kg (existing behavior)."""
    settings = {"weight_kg": 80.0, "protein_g_per_kg": 2.0, "fat_g": 70}
    targets = fuel.compute_targets(
        settings, budget=2400, lean_mass_kg=62.0, lean_mass_source="setting")

    # 2.0 × 80.0 = 160 g protein
    assert targets["protein_g"] == 160


def test_compute_targets_backward_compat_no_lean_mass_args():
    """AC2: compute_targets without lean mass args preserves existing behavior."""
    settings = {"weight_kg": 70.0, "protein_g_per_kg": 2.0, "fat_g": 70}
    targets = fuel.compute_targets(settings, budget=1700)

    assert targets["protein_g"] == 140  # 70 × 2.0
