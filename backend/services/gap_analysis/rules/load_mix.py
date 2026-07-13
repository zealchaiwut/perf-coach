"""Load-mix rules pack (issue #1372).

Three rules that diagnose *what kind* of running is missing:

  intensity_too_hard     — 4-week hard-zone share above the polarized target
  aerobic_durability_gap — long-run aerobic decoupling too high over 4 weeks
  speed_neglected        — speed score decayed while quality sessions are absent

All are pure functions.  Input data is gathered by the engine and supplied via
the inputs dict; no DB access inside these rules.

Guardrail compliance (AC4):
  When the current training verdict is "back_off", every rule in this pack
  that would recommend *adding* training emits severity 1 (note) with a
  "deferred while backing off" suffix instead of the usual severity 2
  (recommend), so the gap analyzer never contradicts the load guardrail.

Constants
---------
HIGH_TARGET_UPPER_BOUND_PCT   Upper bound for the high-intensity band (%).
                              Imported from polarized_split._DEFAULT_BOUNDS so
                              it is never redefined here.
LONG_RUN_MIN_SECONDS          Minimum run duration to count as a long run (s).
LONG_RUN_MIN_COUNT            Minimum long-run sample required to fire.
DECOUPLING_THRESHOLD_PCT      Avg aerobic decoupling % that triggers the rule.
SPEED_DECAY_THRESHOLD         Speed score drop (points) that triggers the rule.
QUALITY_SESSIONS_WINDOW_WEEKS Weeks over which quality sessions are counted.
QUALITY_SESSIONS_MIN_PER_WEEK Minimum quality sessions / week to suppress rule.
"""
from __future__ import annotations

from typing import Optional

from backend.services.gap_analysis.schemas import GapAnalysisFinding
from backend.services.polarized_split import (
    _DEFAULT_BOUNDS as _POLARIZED_BOUNDS,
    check_polarized_split,
)

# ── Intensity-distribution threshold ─────────────────────────────────────────
# Upper bound on the high-intensity band imported from polarized_split — not
# redefined here per AC1.
HIGH_TARGET_UPPER_BOUND_PCT: float = float(_POLARIZED_BOUNDS["high"][1])

# ── Aerobic decoupling thresholds ─────────────────────────────────────────────
# Minimum run duration (seconds) qualifying as a "long run" (mirrors
# endurance_signal._MIN_MOVING_SECONDS = 2400, i.e. 40 minutes).
LONG_RUN_MIN_SECONDS: int = 2400
# Minimum number of long runs with stored decoupling in the 4-week window
# before the rule fires (avoids single-outlier noise).
LONG_RUN_MIN_COUNT: int = 2
# Average aerobic decoupling % above which long-run fatigue is flagged.
DECOUPLING_THRESHOLD_PCT: float = 5.0

# ── Speed neglected thresholds ────────────────────────────────────────────────
# Speed score drop (points) over 8 weeks that constitutes meaningful decay.
SPEED_DECAY_THRESHOLD: float = 10.0
# Rolling window used to measure quality session frequency.
QUALITY_SESSIONS_WINDOW_WEEKS: int = 3
# Average quality sessions per week required to suppress the rule.
# "< 1 quality session/week in 3 weeks" = count < 3 total.
QUALITY_SESSIONS_MIN_PER_WEEK: float = 1.0

_BACK_OFF_SUFFIX = " (deferred while backing off)"


def _apply_verdict_deferral(
    severity: int,
    recommendation: str,
    inputs: dict,
) -> tuple[int, str]:
    """Return (severity, recommendation) adjusted for back_off guardrail."""
    verdict = inputs.get("training_verdict")
    if verdict == "back_off":
        return 1, recommendation + _BACK_OFF_SUFFIX
    return severity, recommendation


# ── Rule: intensity_too_hard ──────────────────────────────────────────────────

def intensity_too_hard(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Severity-2 finding when the 4-week hard-zone share exceeds the polarized target.

    Reuses check_polarized_split from polarized_split.py — thresholds are not
    redefined here.  Only fires when the *high* band is "above" its target
    upper bound; other deviations (e.g. grey-zone excess alone) are out of
    scope for this rule.

    Returns None when:
    - intensity_4w input is absent or any pct is None (insufficient data)
    - High band is not above its target upper bound
    """
    data = inputs.get("intensity_4w")
    if data is None:
        return None

    low_pct = data.get("low_pct")
    moderate_pct = data.get("moderate_pct")
    high_pct = data.get("high_pct")

    if low_pct is None or moderate_pct is None or high_pct is None:
        return None

    split_check = check_polarized_split(low_pct, moderate_pct, high_pct)

    if split_check["on_target"]:
        return None

    high_above = any(
        d["band"] == "high" and d["direction"] == "above"
        for d in split_check["deviations"]
    )
    if not high_above:
        return None

    rec = (
        "Shift more sessions to easy/aerobic effort to restore the 80/20 intensity split — "
        "aim for ≥80 % low-intensity time over the next four weeks."
    )
    severity, rec = _apply_verdict_deferral(2, rec, inputs)

    evidence = [
        {
            "metric": "high_pct_4w",
            "value": round(high_pct, 1),
            "threshold": HIGH_TARGET_UPPER_BOUND_PCT,
            "window": "4w",
        },
        {
            "metric": "low_pct_4w",
            "value": round(low_pct, 1),
            "threshold": float(_POLARIZED_BOUNDS["low"][0]),
            "window": "4w",
        },
        {
            "metric": "moderate_pct_4w",
            "value": round(moderate_pct, 1),
            "threshold": float(_POLARIZED_BOUNDS["moderate"][1]),
            "window": "4w",
        },
    ]

    return GapAnalysisFinding(
        code="intensity_too_hard",
        severity=severity,
        recommendation=rec,
        evidence=evidence,
        target="easy_volume",
        week_start=inputs["week_start"],
    )


# ── Rule: aerobic_durability_gap ──────────────────────────────────────────────

def aerobic_durability_gap(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Severity-2 finding when long-run aerobic decoupling averages above threshold.

    Requires at least LONG_RUN_MIN_COUNT long runs (> LONG_RUN_MIN_SECONDS) with
    stored decoupling_percent over the 4-week window.

    Returns None when:
    - long_run_decoupling_4w input is absent (insufficient data)
    - count < LONG_RUN_MIN_COUNT (too few long runs to be meaningful)
    - avg_decoupling_pct is None
    - avg_decoupling_pct <= DECOUPLING_THRESHOLD_PCT
    """
    data = inputs.get("long_run_decoupling_4w")
    if data is None:
        return None

    count = data.get("count", 0)
    avg_decoupling = data.get("avg_decoupling_pct")

    if count < LONG_RUN_MIN_COUNT or avg_decoupling is None:
        return None

    if avg_decoupling <= DECOUPLING_THRESHOLD_PCT:
        return None

    rec = (
        "Aerobic efficiency fades over long efforts — include one weekly easy "
        "long run with on-the-run fueling to build durability."
    )
    severity, rec = _apply_verdict_deferral(2, rec, inputs)

    evidence = [
        {
            "metric": "avg_decoupling_pct_4w",
            "value": round(avg_decoupling, 2),
            "threshold": DECOUPLING_THRESHOLD_PCT,
            "window": "4w",
        },
        {
            "metric": "long_run_count_4w",
            "value": count,
            "threshold": LONG_RUN_MIN_COUNT,
            "window": "4w",
        },
    ]

    return GapAnalysisFinding(
        code="aerobic_durability_gap",
        severity=severity,
        recommendation=rec,
        evidence=evidence,
        target="long_run",
        week_start=inputs["week_start"],
    )


# ── Rule: speed_neglected ─────────────────────────────────────────────────────

def speed_neglected(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Severity-2 finding when speed score has decayed while quality sessions are absent.

    Mirrors the pattern of base_neglected (for Endurance with volume evidence)
    but anchored to the Speed score from performance_score_history and the
    count of quality-session workouts (speed_signal IS NOT NULL) as the
    volume evidence.

    Returns None when:
    - speed_score_history_8w or quality_sessions_3w input is absent/None
    - Speed score decay <= SPEED_DECAY_THRESHOLD (not enough decay)
    - Quality sessions >= QUALITY_SESSIONS_MIN_PER_WEEK × QUALITY_SESSIONS_WINDOW_WEEKS
      (athlete is already doing enough quality work)
    """
    speed_hist = inputs.get("speed_score_history_8w")
    quality = inputs.get("quality_sessions_3w")

    if speed_hist is None or quality is None:
        return None

    oldest_speed = speed_hist.get("oldest_speed")
    newest_speed = speed_hist.get("newest_speed")

    if oldest_speed is None or newest_speed is None:
        return None

    decay = oldest_speed - newest_speed
    if decay <= SPEED_DECAY_THRESHOLD:
        return None

    quality_count = quality.get("count", 0)
    quality_min = QUALITY_SESSIONS_MIN_PER_WEEK * QUALITY_SESSIONS_WINDOW_WEEKS
    if quality_count >= quality_min:
        return None

    rec = (
        "Speed has dropped and quality sessions are rare — reintroduce one interval "
        "session per week (e.g. 6–8 × 400 m at 5 K effort) to rebuild top-end speed."
    )
    severity, rec = _apply_verdict_deferral(2, rec, inputs)

    evidence = [
        {
            "metric": "speed_score_decay_8w",
            "value": round(decay, 1),
            "threshold": SPEED_DECAY_THRESHOLD,
            "window": "8w",
        },
        {
            "metric": "speed_score_newest",
            "value": round(newest_speed, 1),
            "threshold": None,
            "window": "8w",
        },
        {
            "metric": "quality_sessions_3w",
            "value": quality_count,
            "threshold": int(quality_min),
            "window": f"{QUALITY_SESSIONS_WINDOW_WEEKS}w",
        },
    ]

    return GapAnalysisFinding(
        code="speed_neglected",
        severity=severity,
        recommendation=rec,
        evidence=evidence,
        target="speed",
        week_start=inputs["week_start"],
    )
