"""Rule: cadence_drift (issue #1371, fixed #1463).

Fires when:
  - Easy-run cadence 28-day mean has dropped more than CADENCE_DRIFT_THRESHOLD_PCT
    below the user's long-baseline mean (last CADENCE_BASELINE_WINDOW_DAYS days,
    excluding the most-recent 28d)

Both windows are filtered to easy-run intensity (power within ±half of
CADENCE_EASY_POWER_BAND_WIDTH_W around the lower of the two windows' mean power),
anchoring the band to whichever window has the lighter effort mix. Runs without
power_w are excluded; the long baseline falls back to all-cadence runs when it
has no power data (e.g. Garmin-only imports).

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

CADENCE_EASY_POWER_BAND_WIDTH_W: float = 50.0
"""Width of the easy-run intensity control band (Watts). Only runs within ±half of
this around the recent window's mean power are included in both windows. Matches
the band width used in gct_lengthening."""

MIN_RUNS_PER_WINDOW: int = 3
"""Minimum runs required in EACH window after easy-run filtering before the rule
will fire. Fewer → return None."""


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def cadence_drift(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Return severity-1 finding when easy-run cadence has drifted below the long baseline.

    The recent window is filtered to easy-run efforts via a power band anchored to
    the lower-effort window.  Runs without power_w are excluded from any window that
    has powered runs; when the long baseline has no power data at all, it falls back
    to all cadence-valid runs (graceful degradation for imports without power).

    Returns None when:
    - form_metrics key is absent
    - Recent window has < MIN_RUNS_PER_WINDOW runs with valid cadence + power
    - After easy-run filtering, recent or baseline has < MIN_RUNS_PER_WINDOW runs
    - Cadence drop is at or below CADENCE_DRIFT_THRESHOLD_PCT
    """
    fm = inputs.get("form_metrics")
    if fm is None:
        return None

    recent_runs = fm.get("recent_runs", [])
    long_baseline_runs = fm.get("long_baseline_runs", [])

    def _powered(runs):
        return [
            (float(r["cadence_spm"]), float(r["power_w"]))
            for r in runs
            if r.get("cadence_spm") is not None and r.get("power_w") is not None
        ]

    recent_powered = _powered(recent_runs)
    baseline_powered = _powered(long_baseline_runs)

    # Recent MUST have powered runs to anchor the intensity band.
    if len(recent_powered) < MIN_RUNS_PER_WINDOW:
        return None

    # Band centre: anchor on the lighter-effort window so that an interval block
    # in either window cannot drag the band into hard-effort territory.
    recent_power_mean = _mean([pw for _, pw in recent_powered])
    if baseline_powered:
        baseline_power_mean = _mean([pw for _, pw in baseline_powered])
        band_center = min(recent_power_mean, baseline_power_mean)
    else:
        band_center = recent_power_mean

    half_band = CADENCE_EASY_POWER_BAND_WIDTH_W / 2.0
    lo = band_center - half_band
    hi = band_center + half_band

    recent_cad = [cad for cad, pw in recent_powered if lo <= pw <= hi]
    if len(recent_cad) < MIN_RUNS_PER_WINDOW:
        return None

    if baseline_powered:
        baseline_cad = [cad for cad, pw in baseline_powered if lo <= pw <= hi]
    else:
        # Fallback: no power data in baseline — include all cadence-valid runs.
        baseline_cad = [
            float(r["cadence_spm"])
            for r in long_baseline_runs
            if r.get("cadence_spm") is not None
        ]

    if len(baseline_cad) < MIN_RUNS_PER_WINDOW:
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
