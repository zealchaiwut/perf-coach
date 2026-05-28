"""
Readiness score calculator using the HRV coefficient-of-variation (CV) approach.

See README.md in this directory for full methodology, weights, and edge-case handling.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# Component weights — must sum to 1.0
W_HRV = 0.40
W_RHR = 0.20
W_SLEEP = 0.20
W_ENERGY = 0.20

# Baseline window sizes (days preceding the target date)
HRV_WINDOW = 7
RHR_WINDOW = 30

# Minimum baseline days required before a signal contributes to the score
HRV_MIN_DAYS = 2
RHR_MIN_DAYS = 3

# Sensitivity: 1 standard deviation of normalized deviation → 20 score points.
# z = +2.5  →  score = 100; z = -2.5  →  score = 0.
ZSCORE_SCALE = 20.0


@dataclass
class ReadinessComponents:
    hrv_contribution: Optional[float]
    rhr_contribution: Optional[float]
    sleep_contribution: Optional[float]
    energy_contribution: Optional[float]


@dataclass
class ReadinessResult:
    score: float            # 0–100, rounded to 2 decimal places
    components: ReadinessComponents


def _population_stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))


def _deviation_score(
    today: float,
    baseline: list[float],
    higher_is_better: bool,
) -> float:
    """
    Map today's value relative to a baseline onto [0, 100].

    Uses CV-normalized deviation (z-score via coefficient of variation).
    When CV is very small (< 0.01) falls back to absolute population std.
    A value exactly at the mean returns 50 (neutral).
    """
    mean = sum(baseline) / len(baseline)
    if mean == 0:
        return 50.0
    std = _population_stdev(baseline)
    cv = std / abs(mean)
    # Denominator: CV * mean when variability is measurable, else raw std (floor 1)
    denom = (cv * abs(mean)) if cv >= 0.01 else max(1.0, std)
    if denom == 0:
        return 50.0
    z = (today - mean) / denom
    if not higher_is_better:
        z = -z
    return max(0.0, min(100.0, 50.0 + z * ZSCORE_SCALE))


def compute_readiness(
    hrv: Optional[float],
    resting_hr: Optional[float],
    sleep_quality: Optional[float],
    energy: Optional[float],
    hrv_baseline: list[float],
    rhr_baseline: list[float],
) -> Optional[ReadinessResult]:
    """
    Compute a daily readiness score in [0, 100].

    Parameters
    ----------
    hrv          : today's HRV measurement (ms). None if not recorded.
    resting_hr   : today's resting heart rate (bpm). None if not recorded.
    sleep_quality: today's sleep quality rating (1–5). None if not recorded.
    energy       : today's subjective energy rating (1–5). None if not recorded.
    hrv_baseline : HRV values from the preceding HRV_WINDOW days (excludes today).
    rhr_baseline : RHR values from the preceding RHR_WINDOW days (excludes today).

    Returns
    -------
    ReadinessResult with score and per-signal additive contributions, or None if
    no signal data is available at all.

    The function is deterministic: identical inputs always produce identical outputs.
    """
    raw: dict[str, float] = {}
    weights: dict[str, float] = {}

    # HRV component (weight W_HRV = 0.40)
    if hrv is not None and len(hrv_baseline) >= HRV_MIN_DAYS:
        raw["hrv"] = _deviation_score(hrv, hrv_baseline, higher_is_better=True)
        weights["hrv"] = W_HRV

    # RHR component (weight W_RHR = 0.20) — lower is better
    if resting_hr is not None and len(rhr_baseline) >= RHR_MIN_DAYS:
        raw["rhr"] = _deviation_score(resting_hr, rhr_baseline, higher_is_better=False)
        weights["rhr"] = W_RHR

    # Sleep quality component (weight W_SLEEP = 0.20) — linear 1–5 scale
    if sleep_quality is not None:
        raw["sleep"] = (sleep_quality - 1.0) / 4.0 * 100.0
        weights["sleep"] = W_SLEEP

    # Energy component (weight W_ENERGY = 0.20) — linear 1–5 scale
    if energy is not None:
        raw["energy"] = (energy - 1.0) / 4.0 * 100.0
        weights["energy"] = W_ENERGY

    if not raw:
        return None

    # Redistribute weights for missing signals (proportional renormalization)
    total_weight = sum(weights.values())

    # Each signal's additive share of the final score
    contributions = {k: (weights[k] / total_weight) * raw[k] for k in raw}
    final_score = sum(contributions.values())

    return ReadinessResult(
        score=round(final_score, 2),
        components=ReadinessComponents(
            hrv_contribution=round(contributions.get("hrv", 0.0), 4),
            rhr_contribution=round(contributions.get("rhr", 0.0), 4),
            sleep_contribution=round(contributions.get("sleep", 0.0), 4),
            energy_contribution=round(contributions.get("energy", 0.0), 4),
        ),
    )
