"""Rule: plyo_deficit (issue #1371).

Fires when:
  - LSS 28-day mean improved by less than LSS_IMPROVEMENT_THRESHOLD_PCT vs prior 28d
    (i.e., flat or falling)
  AND
  - Plyo dose < PLYO_SESSIONS_PER_WEEK_MIN sessions/week over the last PLYO_DOSE_WINDOW_WEEKS

Severity 2 (recommend). Returns None on insufficient data.
Thresholds documented in docs/calculations/gap-analysis.md.
"""
from __future__ import annotations

from typing import Optional

from backend.services.gap_analysis.schemas import GapAnalysisFinding

# ── Thresholds ────────────────────────────────────────────────────────────────

LSS_IMPROVEMENT_THRESHOLD_PCT: float = 1.0
"""Minimum LSS improvement (%) vs prior 28d for athlete to be considered 'improving'.
Below this → LSS is flat or falling and the first condition is met."""

PLYO_SESSIONS_PER_WEEK_MIN: float = 1.0
"""Minimum average plyo sessions per week over the dose window to be considered adequate."""

PLYO_DOSE_WINDOW_WEEKS: int = 4
"""Number of trailing weeks used to compute plyo dose frequency."""

MIN_RUNS_PER_WINDOW: int = 3
"""Minimum number of runs with valid LSS data required in each window (recent and prior)
before the rule will fire. Fewer → return None (insufficient data)."""

_DEFAULT_PLYO_PHASE = "intro"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def plyo_deficit(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Return severity-2 finding when LSS is flat/falling AND plyo dose is inadequate.

    Returns None when:
    - form_metrics key is absent
    - Either 28d window has < MIN_RUNS_PER_WINDOW runs with valid LSS data
    - LSS has improved by >= LSS_IMPROVEMENT_THRESHOLD_PCT (athlete is progressing)
    - Plyo dose meets or exceeds PLYO_SESSIONS_PER_WEEK_MIN
    """
    fm = inputs.get("form_metrics")
    if fm is None:
        return None

    recent_runs = fm.get("recent_runs", [])
    prior_runs = fm.get("prior_runs", [])

    recent_lss = [r["lss_kn_m"] for r in recent_runs if r.get("lss_kn_m") is not None]
    prior_lss = [r["lss_kn_m"] for r in prior_runs if r.get("lss_kn_m") is not None]

    if len(recent_lss) < MIN_RUNS_PER_WINDOW or len(prior_lss) < MIN_RUNS_PER_WINDOW:
        return None

    recent_mean = _mean(recent_lss)
    prior_mean = _mean(prior_lss)

    # Fire only when improvement is strictly below threshold
    improvement_pct = (recent_mean - prior_mean) / prior_mean * 100.0 if prior_mean else 0.0
    if improvement_pct >= LSS_IMPROVEMENT_THRESHOLD_PCT:
        return None

    # Check plyo dose over last PLYO_DOSE_WINDOW_WEEKS
    dose = inputs.get("structural_dose", {})
    weekly = dose.get("weekly", [])
    dose_window = weekly[-PLYO_DOSE_WINDOW_WEEKS:] if len(weekly) >= PLYO_DOSE_WINDOW_WEEKS else weekly
    if not dose_window:
        avg_sessions_per_week = 0.0
        last_phase: Optional[str] = None
    else:
        avg_sessions_per_week = sum(w.get("plyo_sessions", 0) for w in dose_window) / len(dose_window)
        # Last logged plyo phase from most-recent week that has one
        last_phase = None
        for w in reversed(dose_window):
            ph = w.get("dominant_plyo_phase")
            if ph:
                last_phase = ph
                break

    if avg_sessions_per_week >= PLYO_SESSIONS_PER_WEEK_MIN:
        return None

    phase = last_phase or _DEFAULT_PLYO_PHASE

    evidence = [
        {
            "metric": "lss_recent_mean",
            "value": round(recent_mean, 4),
            "threshold": None,
            "window": "28d",
        },
        {
            "metric": "lss_prior_mean",
            "value": round(prior_mean, 4),
            "threshold": None,
            "window": "28d_prior",
        },
        {
            "metric": "lss_improvement_pct",
            "value": round(improvement_pct, 2),
            "threshold": LSS_IMPROVEMENT_THRESHOLD_PCT,
            "window": "28d_vs_prior_28d",
        },
        {
            "metric": "plyo_sessions_per_week",
            "value": round(avg_sessions_per_week, 2),
            "threshold": PLYO_SESSIONS_PER_WEEK_MIN,
            "window": f"{PLYO_DOSE_WINDOW_WEEKS}w",
        },
    ]

    return GapAnalysisFinding(
        code="plyo_deficit",
        severity=2,
        recommendation=(
            f"Leg-spring stiffness is flat — reintroduce plyometrics at {phase} phase "
            "to rebuild reactive strength."
        ),
        evidence=evidence,
        target="plyo",
        week_start=inputs["week_start"],
    )
