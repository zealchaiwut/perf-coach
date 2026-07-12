"""Tests for deficit periodization — issue #1357.

Covers AC items:
  AC1 — resolve_week_phase(): precedence + each phase (race/taper/ramp/base)
  AC2 — effective_deficit_for_phase(): math for each phase including ramp 50%
  AC3 — auto_periodize toggle: when off, effective deficit == configured deficit
  AC4 — payload includes week_phase and effective_deficit_kcal
  AC5 — FuelSettings.auto_periodize boolean exists with default True
"""
from __future__ import annotations

import pytest

from backend.services.fuel_periodize import (
    RAMP_THRESHOLD_MULT,
    effective_deficit_for_phase,
    resolve_week_phase,
)


# ── AC1: Phase resolver — each phase and precedence ───────────────────────

def test_resolver_base_when_no_race_and_no_plan():
    phase, reason = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=False,
        trailing_28d_weekly_avg=None,
        current_week_target_tss=None,
    )
    assert phase == "base"
    assert "base" in reason.lower() or "full" in reason.lower()


def test_resolver_base_when_target_below_ramp_threshold():
    # target < 1.1x avg → not a ramp
    phase, reason = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=False,
        trailing_28d_weekly_avg=300.0,
        current_week_target_tss=320.0,  # 320 < 330 (1.1 * 300)
    )
    assert phase == "base"


def test_resolver_race_when_ab_race_within_7d():
    phase, reason = resolve_week_phase(
        race_within_7d=True,
        in_taper_window=False,
        trailing_28d_weekly_avg=300.0,
        current_week_target_tss=315.0,
    )
    assert phase == "race"
    assert "race" in reason.lower()


def test_resolver_taper_when_in_taper_window():
    phase, reason = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=True,
        trailing_28d_weekly_avg=300.0,
        current_week_target_tss=250.0,
    )
    assert phase == "taper"
    assert "taper" in reason.lower()


def test_resolver_ramp_when_target_meets_threshold_exactly():
    avg = 300.0
    target = RAMP_THRESHOLD_MULT * avg  # exactly 330
    phase, reason = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=False,
        trailing_28d_weekly_avg=avg,
        current_week_target_tss=target,
    )
    assert phase == "ramp"
    assert "ramp" in reason.lower()


def test_resolver_ramp_when_target_exceeds_threshold():
    phase, _ = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=False,
        trailing_28d_weekly_avg=300.0,
        current_week_target_tss=400.0,
    )
    assert phase == "ramp"


# ── AC1: Precedence (race > taper > ramp > base) ─────────────────────────

def test_resolver_race_beats_taper():
    phase, _ = resolve_week_phase(
        race_within_7d=True,
        in_taper_window=True,
        trailing_28d_weekly_avg=None,
        current_week_target_tss=None,
    )
    assert phase == "race"


def test_resolver_race_beats_ramp():
    phase, _ = resolve_week_phase(
        race_within_7d=True,
        in_taper_window=False,
        trailing_28d_weekly_avg=300.0,
        current_week_target_tss=400.0,
    )
    assert phase == "race"


def test_resolver_taper_beats_ramp():
    phase, _ = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=True,
        trailing_28d_weekly_avg=300.0,
        current_week_target_tss=400.0,
    )
    assert phase == "taper"


def test_resolver_ramp_beats_base():
    phase, _ = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=False,
        trailing_28d_weekly_avg=300.0,
        current_week_target_tss=400.0,
    )
    assert phase == "ramp"


def test_resolver_no_ramp_when_avg_is_none():
    # no trailing average available → can't classify as ramp
    phase, _ = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=False,
        trailing_28d_weekly_avg=None,
        current_week_target_tss=500.0,
    )
    assert phase == "base"


def test_resolver_no_ramp_when_target_is_none():
    # no load plan → no target TSS → not ramp
    phase, _ = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=False,
        trailing_28d_weekly_avg=300.0,
        current_week_target_tss=None,
    )
    assert phase == "base"


def test_resolver_no_ramp_when_avg_is_zero():
    # zero trailing avg → guard against division → not ramp
    phase, _ = resolve_week_phase(
        race_within_7d=False,
        in_taper_window=False,
        trailing_28d_weekly_avg=0.0,
        current_week_target_tss=300.0,
    )
    assert phase == "base"


# ── AC2: Effective deficit math ────────────────────────────────────────────

def test_effective_deficit_race_is_zero():
    assert effective_deficit_for_phase(300, "race") == 0


def test_effective_deficit_taper_is_zero():
    assert effective_deficit_for_phase(300, "taper") == 0


def test_effective_deficit_base_unchanged():
    assert effective_deficit_for_phase(300, "base") == 300


def test_effective_deficit_ramp_50pct_rounded_to_10():
    # 300 * 0.5 = 150, round(150/10)*10 = 150
    assert effective_deficit_for_phase(300, "ramp") == 150


def test_effective_deficit_ramp_400():
    # 400 * 0.5 = 200
    assert effective_deficit_for_phase(400, "ramp") == 200


def test_effective_deficit_ramp_odd_configured():
    # 500 * 0.5 = 250, round(250/10)*10 = round(25)*10 = 250
    assert effective_deficit_for_phase(500, "ramp") == 250


def test_effective_deficit_ramp_zero_configured():
    assert effective_deficit_for_phase(0, "ramp") == 0


def test_effective_deficit_ramp_rounds_to_nearest_10():
    # 270 * 0.5 = 135, round(135/10)*10 = round(13.5)*10 = 14*10 = 140
    assert effective_deficit_for_phase(270, "ramp") == 140


# ── AC3: auto_periodize toggle off → passthrough ──────────────────────────

def test_auto_periodize_off_returns_configured_deficit():
    """When auto_periodize=False, effective deficit must equal configured deficit."""
    from backend.services.fuel import compute_effective_deficit
    configured = 300
    result = compute_effective_deficit(
        auto_periodize=False,
        configured_deficit_kcal=configured,
        week_phase="race",  # would normally give 0 if periodize were on
        effective_deficit_override=None,
    )
    assert result == configured


def test_auto_periodize_on_race_gives_zero():
    from backend.services.fuel import compute_effective_deficit
    result = compute_effective_deficit(
        auto_periodize=True,
        configured_deficit_kcal=300,
        week_phase="race",
        effective_deficit_override=None,
    )
    assert result == 0


def test_auto_periodize_on_base_gives_configured():
    from backend.services.fuel import compute_effective_deficit
    result = compute_effective_deficit(
        auto_periodize=True,
        configured_deficit_kcal=300,
        week_phase="base",
        effective_deficit_override=None,
    )
    assert result == 300


def test_auto_periodize_on_ramp_gives_half():
    from backend.services.fuel import compute_effective_deficit
    result = compute_effective_deficit(
        auto_periodize=True,
        configured_deficit_kcal=400,
        week_phase="ramp",
        effective_deficit_override=None,
    )
    assert result == 200


# ── AC4: Payload fields ────────────────────────────────────────────────────

def test_compute_budget_accepts_effective_deficit():
    """compute_budget with effective_deficit_kcal overrides the settings deficit."""
    from backend.services.fuel import compute_budget
    settings = {"base_kcal": 2000, "deficit_kcal": 300, "lean_mass_kg": 60.0, "ea_floor": 30.0}
    result = compute_budget(settings, burn=0.0, effective_deficit_kcal=0)
    # effective deficit 0 → budget = base_kcal + 0 - 0 = 2000
    assert result["budget"] == 2000
    assert result["deficit_applied"] == 0
    assert result["effective_deficit_kcal"] == 0


def test_compute_budget_effective_deficit_kcal_in_result():
    """Result dict always includes effective_deficit_kcal key."""
    from backend.services.fuel import compute_budget
    settings = {"base_kcal": 2000, "deficit_kcal": 300, "lean_mass_kg": 60.0, "ea_floor": 30.0}
    result = compute_budget(settings, burn=0.0)
    assert "effective_deficit_kcal" in result


def test_compute_budget_without_override_uses_settings_deficit():
    """Without override, effective_deficit_kcal should match deficit_kcal from settings."""
    from backend.services.fuel import compute_budget
    settings = {"base_kcal": 2000, "deficit_kcal": 300, "lean_mass_kg": 60.0, "ea_floor": 30.0}
    result = compute_budget(settings, burn=0.0)
    assert result["effective_deficit_kcal"] == 300


# ── AC5: FuelSettings.auto_periodize column ───────────────────────────────

def test_fuel_settings_has_auto_periodize_attribute():
    """FuelSettings model must have an auto_periodize boolean column."""
    from backend.models import FuelSettings
    col_names = [c.key for c in FuelSettings.__table__.columns]
    assert "auto_periodize" in col_names


def test_fuel_settings_auto_periodize_default_is_true():
    """Default value for auto_periodize must be True (server_default)."""
    from backend.models import FuelSettings
    col = FuelSettings.__table__.c["auto_periodize"]
    # Server default is 'true'; check it's not nullable or explicitly false
    assert str(col.server_default.arg).lower() in ("true", "'true'")
