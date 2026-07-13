"""Rule: gct_lengthening (issue #1371).

Fires when:
  - Ground Contact Time (GCT) 28-day mean rises > GCT_RISE_THRESHOLD_MS vs prior 28d
  - Comparison is made at comparable easy-run intensity (power within ±half of
    GCT_EASY_POWER_BAND_WIDTH_W around the recent window's mean power)
  - Both filtered windows have at least MIN_RUNS_PER_WINDOW runs

Severity 2 (recommend). Returns None on insufficient data or incompatible power bands.
Thresholds documented in docs/calculations/gap-analysis.md.
"""
from __future__ import annotations

from typing import Optional

from backend.services.gap_analysis.schemas import GapAnalysisFinding

# ── Thresholds ────────────────────────────────────────────────────────────────

GCT_RISE_THRESHOLD_MS: float = 5.0
"""GCT must rise by more than this (ms) in the recent window vs prior to fire."""

GCT_EASY_POWER_BAND_WIDTH_W: float = 50.0
"""Width of the intensity control band (Watts). Only runs within ±half of this
around the recent window's mean power are included in both windows for comparison."""

MIN_RUNS_PER_WINDOW: int = 3
"""Minimum runs with valid GCT AND power data in each filtered window to proceed."""


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def gct_lengthening(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Return severity-2 finding when GCT is trending longer at matched intensity.

    Pace/power band control: filters both windows to runs whose power is within
    ±(GCT_EASY_POWER_BAND_WIDTH_W / 2) of the recent window's mean power. This
    prevents slow recovery runs (lower power → naturally longer GCT) from
    false-triggering the finding.

    Returns None when:
    - form_metrics key is absent
    - Either window has < MIN_RUNS_PER_WINDOW runs with valid GCT + power
    - After band filtering, either window has < MIN_RUNS_PER_WINDOW runs
    - GCT change is at or below GCT_RISE_THRESHOLD_MS
    """
    fm = inputs.get("form_metrics")
    if fm is None:
        return None

    recent_runs = fm.get("recent_runs", [])
    prior_runs = fm.get("prior_runs", [])

    # Extract (gct_ms, power_w) pairs with both values present
    def _extract(runs):
        return [
            (float(r["gct_ms"]), float(r["power_w"]))
            for r in runs
            if r.get("gct_ms") is not None and r.get("power_w") is not None
        ]

    recent_pairs = _extract(recent_runs)
    prior_pairs = _extract(prior_runs)

    if len(recent_pairs) < MIN_RUNS_PER_WINDOW or len(prior_pairs) < MIN_RUNS_PER_WINDOW:
        return None

    # Power band centred on recent window's mean power
    recent_power_mean = _mean([p for _, p in recent_pairs])
    half_band = GCT_EASY_POWER_BAND_WIDTH_W / 2.0
    lo = recent_power_mean - half_band
    hi = recent_power_mean + half_band

    recent_filtered = [gct for gct, pw in recent_pairs if lo <= pw <= hi]
    prior_filtered = [gct for gct, pw in prior_pairs if lo <= pw <= hi]

    if len(recent_filtered) < MIN_RUNS_PER_WINDOW or len(prior_filtered) < MIN_RUNS_PER_WINDOW:
        return None

    recent_gct_mean = _mean(recent_filtered)
    prior_gct_mean = _mean(prior_filtered)
    delta_ms = recent_gct_mean - prior_gct_mean

    if delta_ms <= GCT_RISE_THRESHOLD_MS:
        return None

    evidence = [
        {
            "metric": "gct_recent_mean_ms",
            "value": round(recent_gct_mean, 1),
            "threshold": None,
            "window": "28d",
        },
        {
            "metric": "gct_prior_mean_ms",
            "value": round(prior_gct_mean, 1),
            "threshold": None,
            "window": "28d_prior",
        },
        {
            "metric": "gct_rise_ms",
            "value": round(delta_ms, 1),
            "threshold": GCT_RISE_THRESHOLD_MS,
            "window": "28d_vs_prior_28d",
        },
        {
            "metric": "power_band_center_w",
            "value": round(recent_power_mean, 1),
            "threshold": GCT_EASY_POWER_BAND_WIDTH_W,
            "window": "28d",
        },
    ]

    return GapAnalysisFinding(
        code="gct_lengthening",
        severity=2,
        recommendation=(
            "Ground contact time is lengthening — add plyometrics or strides "
            "to restore reactive stiffness."
        ),
        evidence=evidence,
        target="plyo",
        week_start=inputs["week_start"],
    )
