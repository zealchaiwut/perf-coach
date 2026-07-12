"""Tests for issue #1359: lean-mass protein target and cut guard.

AC1 — current_lean_mass_kg(): three fallback paths
        measured: bf% within 60d → ewma_weight × (1 − bf%)
        setting: FuelSettings.lean_mass_kg when no recent bf%
        estimated: weight × 0.76 when neither
AC2 — protein target computed from lean mass when measured; total weight otherwise
      fuel payload exposes lean_mass_kg + lean_mass_source
AC3 — losing_lean_mass guard in weekly cut review payload
      two bf readings ≥14d apart, lean mass fell >0.3 kg, weight also fell
AC4 — docs/calculations/fuel.md mentions lean-mass derivation (checked separately)
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.services import fuel
from backend.services.cut_review import (
    compute_losing_lean_mass_flag,
    compute_cut_recommendation,
)


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
    bf_readings = [_FakeBFReading(body_fat_pct=25.0, measure_date=date.today() - timedelta(days=60))]
    ewma_weight = 80.0

    result = fuel.current_lean_mass_kg(bf_readings, settings=settings, ewma_weight=ewma_weight)

    assert result["source"] == "measured"
    assert result["lean_mass_kg"] == pytest.approx(60.0, abs=0.05)


def test_lean_mass_source_setting_when_no_recent_bf_pct():
    """AC1: no bf% within 60d + FuelSettings.lean_mass_kg set → source='setting'."""
    settings = _FakeSettings()
    settings.lean_mass_kg = 62.0
    # bf% reading older than 60 days
    bf_readings = [_FakeBFReading(body_fat_pct=22.0, measure_date=date.today() - timedelta(days=61))]
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
        _FakeBFReading(body_fat_pct=20.0, measure_date=date.today() - timedelta(days=5)),  # most recent
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
    targets = fuel.compute_targets(settings, budget=2400, lean_mass_kg=64.0, lean_mass_source="measured")

    # 2.0 × 64.0 = 128 g protein (not 2.0 × 80 = 160 g)
    assert targets["protein_g"] == 128


def test_protein_target_uses_total_weight_when_source_estimated():
    """AC2: source='estimated' → protein = protein_g_per_kg × weight_kg (existing behavior)."""
    settings = {"weight_kg": 80.0, "protein_g_per_kg": 2.0, "fat_g": 70}
    targets = fuel.compute_targets(settings, budget=2400, lean_mass_kg=60.8, lean_mass_source="estimated")

    # 2.0 × 80.0 = 160 g protein (legacy behavior preserved)
    assert targets["protein_g"] == 160


def test_protein_target_uses_total_weight_when_source_setting():
    """AC2: source='setting' → protein = protein_g_per_kg × weight_kg (existing behavior)."""
    settings = {"weight_kg": 80.0, "protein_g_per_kg": 2.0, "fat_g": 70}
    targets = fuel.compute_targets(settings, budget=2400, lean_mass_kg=62.0, lean_mass_source="setting")

    # 2.0 × 80.0 = 160 g protein
    assert targets["protein_g"] == 160


def test_compute_targets_backward_compat_no_lean_mass_args():
    """AC2: compute_targets without lean mass args preserves existing behavior."""
    settings = {"weight_kg": 70.0, "protein_g_per_kg": 2.0, "fat_g": 70}
    targets = fuel.compute_targets(settings, budget=1700)

    assert targets["protein_g"] == 140  # 70 × 2.0


# ─────────────────────────────────────────────────────────────────────────────
# AC3: losing_lean_mass guard
# ─────────────────────────────────────────────────────────────────────────────

def test_losing_lean_mass_flag_true_when_lean_fell_and_weight_fell():
    """AC3: two bf readings ≥14d apart, lean fell >0.3 kg, weight also fell → True."""
    today = date(2026, 7, 12)
    older_reading = {"date": today - timedelta(days=21), "body_fat_pct": 20.0, "weight_kg": 80.0}
    newer_reading = {"date": today - timedelta(days=0), "body_fat_pct": 22.0, "weight_kg": 78.0}

    # older lean: 80 × 0.80 = 64 kg; newer lean: 78 × 0.78 = 60.84 kg → fell >0.3 kg ✓
    # weight fell: 80 → 78 ✓
    assert compute_losing_lean_mass_flag([older_reading, newer_reading]) is True


def test_losing_lean_mass_flag_false_when_lean_fell_less_than_threshold():
    """AC3: lean fell only ~0.12 kg (below 0.3 threshold) → False."""
    today = date(2026, 7, 12)
    # older lean: 80 * 0.80 = 64.0
    # newer lean: 79.95 * (1 - 0.201) = 79.95 * 0.799 = 63.88 → fell 0.12 kg < 0.3
    older_reading = {"date": today - timedelta(days=21), "body_fat_pct": 20.0, "weight_kg": 80.0}
    newer_reading = {"date": today - timedelta(days=0), "body_fat_pct": 20.1, "weight_kg": 79.95}

    assert compute_losing_lean_mass_flag([older_reading, newer_reading]) is False


def test_losing_lean_mass_flag_false_when_weight_did_not_fall():
    """AC3: lean mass fell >0.3 kg but total weight rose → guard doesn't fire."""
    today = date(2026, 7, 12)
    older_reading = {"date": today - timedelta(days=21), "body_fat_pct": 20.0, "weight_kg": 80.0}
    newer_reading = {"date": today - timedelta(days=0), "body_fat_pct": 25.0, "weight_kg": 82.0}

    # older lean: 64.0; newer lean: 82 × 0.75 = 61.5 → fell 2.5 kg
    # weight ROSE: 80 → 82 → guard should NOT fire
    assert compute_losing_lean_mass_flag([older_reading, newer_reading]) is False


def test_losing_lean_mass_flag_false_when_less_than_2_readings():
    """AC3: fewer than two readings → cannot compute, returns False."""
    today = date(2026, 7, 12)
    reading = {"date": today, "body_fat_pct": 20.0, "weight_kg": 80.0}

    assert compute_losing_lean_mass_flag([]) is False
    assert compute_losing_lean_mass_flag([reading]) is False


def test_losing_lean_mass_flag_false_when_readings_less_than_14d_apart():
    """AC3: two readings but only 10 days apart → not enough separation, returns False."""
    today = date(2026, 7, 12)
    older_reading = {"date": today - timedelta(days=10), "body_fat_pct": 20.0, "weight_kg": 80.0}
    newer_reading = {"date": today - timedelta(days=0), "body_fat_pct": 25.0, "weight_kg": 77.0}

    assert compute_losing_lean_mass_flag([older_reading, newer_reading]) is False


def test_losing_lean_mass_flag_false_when_lean_mass_rose():
    """AC3: lean mass rose (good outcome) → False."""
    today = date(2026, 7, 12)
    older_reading = {"date": today - timedelta(days=21), "body_fat_pct": 22.0, "weight_kg": 80.0}
    newer_reading = {"date": today - timedelta(days=0), "body_fat_pct": 18.0, "weight_kg": 79.0}

    # older lean: 80 × 0.78 = 62.4; newer lean: 79 × 0.82 = 64.78 → lean ROSE
    assert compute_losing_lean_mass_flag([older_reading, newer_reading]) is False


def test_losing_lean_mass_exactly_at_boundary():
    """AC3: lean mass fell exactly 0.3 kg → boundary is EXCLUSIVE (>0.3), so False."""
    today = date(2026, 7, 12)
    # Design reading pair where lean_old - lean_new = exactly 0.3:
    # older: 80.0 kg, 20% bf → lean = 64.0
    # newer: ? kg, ? bf → lean = 63.7
    # Use 79.6 kg @ 20% → lean = 63.68 (≈0.32 difference, use approx)
    # For exactly 0.3: need lean_new = 63.7
    # Use 79.625 kg @ 20% bf → 79.625 * 0.80 = 63.7 ✓
    older_reading = {"date": today - timedelta(days=21), "body_fat_pct": 20.0, "weight_kg": 80.0}
    newer_reading = {"date": today - timedelta(days=0), "body_fat_pct": 20.0, "weight_kg": 79.625}

    # lean fell: 64.0 - 63.7 = 0.3 exactly → NOT > 0.3 → False
    assert compute_losing_lean_mass_flag([older_reading, newer_reading]) is False


def test_compute_cut_recommendation_includes_losing_lean_mass_flag():
    """AC3: losing_lean_mass is present in the recommendation output dict."""
    result = compute_cut_recommendation(
        weigh_in_count_14d=8,
        has_active_plan=True,
        actual_rate_kg_per_week=-0.5,
        plan_rate_kg_per_week=-0.5,
        weekly_pct_bw_rate=-0.625,
        ea_proxy=0.8,
        logging_adherence_pct=80.0,
        avg_intake_vs_budget_kcal=-50.0,
        consecutive_weeks_behind=0,
        pct_logged_days_at_or_under_budget=80.0,
        current_deficit_kcal=350,
        losing_lean_mass=False,
    )
    assert "losing_lean_mass" in result
    assert result["losing_lean_mass"] is False


def test_compute_cut_recommendation_propagates_losing_lean_mass_true():
    """AC3: losing_lean_mass=True is propagated to the output payload."""
    result = compute_cut_recommendation(
        weigh_in_count_14d=8,
        has_active_plan=True,
        actual_rate_kg_per_week=-0.5,
        plan_rate_kg_per_week=-0.5,
        weekly_pct_bw_rate=-0.625,
        ea_proxy=0.8,
        logging_adherence_pct=80.0,
        avg_intake_vs_budget_kcal=-50.0,
        consecutive_weeks_behind=0,
        pct_logged_days_at_or_under_budget=80.0,
        current_deficit_kcal=350,
        losing_lean_mass=True,
    )
    assert result["losing_lean_mass"] is True
