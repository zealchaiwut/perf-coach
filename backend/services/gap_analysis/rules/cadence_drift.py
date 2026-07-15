"""Rule: cadence_drift (issue #1371).

Fires when:
  - Easy-run cadence 28-day mean has dropped more than CADENCE_DRIFT_THRESHOLD_PCT
    below the user's long-baseline mean (last CADENCE_BASELINE_WINDOW_DAYS days,
    excluding the most-recent 28d)

Severity 1 (note). Returns None on insufficient data.
Thresholds documented in docs/calculations/gap-analysis.md.
"""
from __future__ import annotations

from typing import Optional

from backend.services.gap_analysis.schemas import GapAnalysisFinding

# ── Thresholds ────────────────────────────────────────────────────────────────

CADENCE_DRIFT_THRESHOLD_PCT: float = 2.0
"""Recent 28d cadence must be more than this % below the long baseline to fire."""

CADENCE_BASELINE_WINDOW_DAYS: int = 180
"""Length of the long baseline window (days) used to compute the reference cadence."""

MIN_RUNS_PER_WINDOW: int = 3
"""Minimum runs with valid cadence data required in EACH window (recent 28d and
long baseline) before the rule will fire. Fewer → return None."""


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def cadence_drift(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Return severity-1 finding when easy-run cadence has drifted below the long baseline.

    Returns None when:
    - form_metrics key is absent
    - Recent 28d window has < MIN_RUNS_PER_WINDOW runs with valid cadence
    - Long baseline window has < MIN_RUNS_PER_WINDOW runs with valid cadence
    - Cadence drop is at or below CADENCE_DRIFT_THRESHOLD_PCT
    """
    fm = inputs.get("form_metrics")
    if fm is None:
        return None

    recent_runs = fm.get("recent_runs", [])
    long_baseline_runs = fm.get("long_baseline_runs", [])

    recent_cad = [
        float(r["cadence_spm"])
        for r in recent_runs
        if r.get("cadence_spm") is not None
    ]
    baseline_cad = [
        float(r["cadence_spm"])
        for r in long_baseline_runs
        if r.get("cadence_spm") is not None
    ]

    if len(recent_cad) < MIN_RUNS_PER_WINDOW or len(baseline_cad) < MIN_RUNS_PER_WINDOW:
        return None

    recent_mean = _mean(recent_cad)
    baseline_mean = _mean(baseline_cad)

    if baseline_mean == 0:
        return None

    drop_pct = (baseline_mean - recent_mean) / baseline_mean * 100.0
    if drop_pct <= CADENCE_DRIFT_THRESHOLD_PCT:
        return None

    evidence = [
        {
            "metric": "cadence_recent_mean_spm",
            "value": round(recent_mean, 1),
            "threshold": None,
            "window": "28d",
        },
        {
            "metric": "cadence_baseline_mean_spm",
            "value": round(baseline_mean, 1),
            "threshold": None,
            "window": f"{CADENCE_BASELINE_WINDOW_DAYS}d_baseline",
        },
        {
            "metric": "cadence_drop_pct",
            "value": round(drop_pct, 2),
            "threshold": CADENCE_DRIFT_THRESHOLD_PCT,
            "window": "28d_vs_baseline",
        },
    ]

    return GapAnalysisFinding(
        code="cadence_drift",
        severity=1,
        recommendation=(
            "Running cadence has drifted below your long-run baseline — "
            "add cadence-focus blocks (e.g. metronome drills at target spm) "
            "during easy runs."
        ),
        evidence=evidence,
        target="run_form",
        week_start=inputs["week_start"],
    )
