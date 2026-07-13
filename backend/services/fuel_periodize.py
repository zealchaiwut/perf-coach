"""Deficit periodization: weekly training phase modulates the fuel deficit.

Pure functions only — no DB, no network. The DB-backed resolver that feeds
these lives in ``backend.services.fuel`` as ``resolve_week_phase_from_db``.

Phase precedence (race > taper > ramp > base):
  race  — A or B race within the next 7 days → maintenance (0 deficit)
  taper — current date is inside the load plan's taper window → maintenance
  ramp  — current-week target TSS >= 1.1 × trailing-28d weekly average → half deficit
  base  — none of the above → full configured deficit

See docs/calculations/fuel.md § "Deficit periodization".
"""
from __future__ import annotations

from typing import Optional

# Multiplier that classifies this week as a "ramp" week: target TSS at least
# 10% above the trailing chronic-load average.
RAMP_THRESHOLD_MULT: float = 1.1


# ── Phase resolver (pure) ──────────────────────────────────────────────────

def resolve_week_phase(
    race_within_7d: bool,
    in_taper_window: bool,
    trailing_28d_weekly_avg: Optional[float],
    current_week_target_tss: Optional[float],
) -> tuple[str, str]:
    """Return (phase, reason) for the current training week.

    Args:
        race_within_7d:           True if an A- or B-priority planned race
                                  falls within the next 7 calendar days.
        in_taper_window:          True if today is on or after the taper-start
                                  date computed from the A-race and training plan.
        trailing_28d_weekly_avg:  28-day TSS sum ÷ 4 (weekly average). None when
                                  no history is available.
        current_week_target_tss:  Load-plan's target TSS for the current week.
                                  None when there is no load plan or no A race.

    Returns:
        (phase, reason) where phase ∈ {"race", "taper", "ramp", "base"} and
        reason is a human-readable string for the UI chip.
    """
    if race_within_7d:
        return "race", "Race week — maintenance"
    if in_taper_window:
        return "taper", "Taper week — maintenance"
    if (
        trailing_28d_weekly_avg is not None
        and trailing_28d_weekly_avg > 0
        and current_week_target_tss is not None
        and current_week_target_tss >= RAMP_THRESHOLD_MULT * trailing_28d_weekly_avg
    ):
        return "ramp", "Ramp week — half deficit"
    return "base", "Base week — full deficit"


# ── Effective deficit (pure) ───────────────────────────────────────────────

def effective_deficit_for_phase(configured_deficit_kcal: int, phase: str) -> int:
    """Effective deficit in kcal for the given phase.

    race / taper → 0 (maintenance)
    ramp         → 50 % of configured, rounded to nearest 10
    base         → 100 % (configured unchanged)
    """
    if phase in ("race", "taper"):
        return 0
    if phase == "ramp":
        return round(configured_deficit_kcal * 0.5 / 10) * 10
    return configured_deficit_kcal
