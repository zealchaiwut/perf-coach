"""
Session Load Plan — race-anchored weekly TSS target model.

This module provides a single pure function, ``compute_load_plan``, that turns
a ramp/hold/taper rule into a per-week target-TSS series counting up to an A
race. All database work (resolving the A race, reading last week's actual
TSS, reading the trailing 28-day average) belongs to the calling layer; this
module contains no SQL, file access, or network calls. Every consumer of the
season chart, the weekly target card, and Suggest-sessions must read from
this one function — do not reimplement the ramp/taper math anywhere else.

Math
----
::

    build_weeks = weeks_to_race - taper_weeks
    ramp_weeks  = build_weeks - hold_weeks
    peak        = baseline * (1 + ramp_rate) ** (ramp_weeks + 1)

    target(w) for w in 1..ramp_weeks              = baseline * (1 + ramp_rate) ** w   # strictly < peak
    target(w) for w in ramp_weeks+1 .. build_weeks = peak                             # exactly hold_weeks weeks
    target(w) for taper week i (0-indexed)         = peak * TAPER_CURVE[i]

    target(w) = min(target(w), ACWR_CEILING_MULT * trailing_28d_avg)   # ACWR ceiling always wins

The ``+ 1`` exponent on ``peak`` is deliberate. The naive version
(``baseline * (1 + ramp_rate) ** ramp_weeks``) makes the ramp's last week
*equal* peak, so a 4-week hold would render five bars at peak. With the
``+ 1``, the ramp tops out strictly below peak and the hold block is exactly
``hold_weeks`` long.

Worked example (baseline 316, ramp_rate 0.05, hold_weeks 4, taper_weeks 3,
weeks_to_race 19)::

    build_weeks = 19 - 3 = 16
    ramp_weeks  = 16 - 4 = 12
    peak        = 316 * 1.05 ** 13 ≈ 596

    Ramp w1-12:  332, 348, 366, 384, 403, 424, 445, 467, 490, 515, 540, 568
    Hold w13-16: 596, 596, 596, 596
    Taper w17-19: 447, 358, 238 (peak * 0.75, 0.60, 0.40)

Counterintuitive note (surface as a tooltip on the peak-hold field in the
UI): raising ``hold_weeks`` *lowers* peak, because it shortens the ramp for a
fixed ``weeks_to_race``.
"""

from __future__ import annotations

from typing import List, Optional, TypedDict

# ── Taper shape ────────────────────────────────────────────────────────────
# Fraction of peak TSS assigned to each taper week, for the default 3-week
# taper. A documented constant, not a magic number — no equivalent existed
# in the old settings before this module. TODO: make this configurable per
# athlete/plan; today every plan uses this one curve, interpolated (see
# _taper_fractions) when taper_weeks != len(TAPER_CURVE).
TAPER_CURVE: List[float] = [0.75, 0.60, 0.40]

# Multiplier applied to trailing_28d_avg to get the ACWR ceiling a week's
# target may never exceed, regardless of what the ramp/hold/taper math wants.
# Matches backend/services/plan_suggestions.py's ACWR_HIGH_BOUND (itself a
# mirror of acwr.UPPER_BOUND, not acwr.HIGH_BOUND — see
# docs/calculations/load-plan.md "Known weaknesses" for the discrepancy this
# name inherits).
ACWR_CEILING_MULT: float = 1.3


class WeekTarget(TypedDict):
    week_index: int  # 1-based, 1..weeks_to_race
    target_tss: float
    phase: str  # "ramp" | "hold" | "taper" | "race"
    clamped: bool


class LoadPlanResult(TypedDict):
    weeks: List[WeekTarget]
    peak: float
    ramp_weeks: int
    hold_weeks: int
    taper_weeks: int
    build_weeks: int
    weeks_to_race: int
    warning: Optional[str]


def _taper_fractions(taper_weeks: int) -> List[float]:
    """Fractions of peak for each taper week, interpolated from TAPER_CURVE.

    Returns exactly `taper_weeks` values. When taper_weeks == len(TAPER_CURVE)
    (the common case, 3), returns TAPER_CURVE unchanged. Otherwise linearly
    interpolates across the same curve so a 2-week or 5-week taper still
    tapers smoothly from ~0.75 down to ~0.40 of peak.
    """
    src = TAPER_CURVE
    src_n = len(src)
    if taper_weeks <= 0:
        return []
    if taper_weeks == src_n:
        return list(src)
    if taper_weeks == 1:
        return [src[-1]]

    out: List[float] = []
    for i in range(taper_weeks):
        pos = i * (src_n - 1) / (taper_weeks - 1)
        lo = int(pos)
        hi = min(lo + 1, src_n - 1)
        frac = pos - lo
        out.append(src[lo] * (1 - frac) + src[hi] * frac)
    return out


def compute_load_plan(
    baseline: float,
    ramp_rate: float,
    hold_weeks: int,
    taper_weeks: int,
    weeks_to_race: int,
    trailing_28d_avg: Optional[float] = None,
) -> LoadPlanResult:
    """Compute the per-week target-TSS series from now to an A race.

    Args:
        baseline: last completed week's ACTUAL TSS (never planned TSS — a
            missed week must lower future targets, not silently inflate them).
        ramp_rate: fractional weekly increase, e.g. 0.05 for 5%/week.
        hold_weeks: length of the peak-hold plateau, in weeks.
        taper_weeks: length of the taper, in weeks.
        weeks_to_race: total weeks counted in the series (build + taper).
        trailing_28d_avg: trailing 28-day average weekly TSS, used for the
            ACWR ceiling (`ACWR_CEILING_MULT * trailing_28d_avg`). Ceiling is
            skipped when this is None or 0 (not enough history yet).

    Returns:
        LoadPlanResult — see the module docstring for the math.
    """
    baseline = max(0.0, float(baseline))
    ramp_rate = float(ramp_rate)
    hold_weeks = max(0, int(hold_weeks))
    taper_weeks = max(0, int(taper_weeks))
    weeks_to_race = max(0, int(weeks_to_race))

    build_weeks = weeks_to_race - taper_weeks
    ramp_weeks = build_weeks - hold_weeks
    warning: Optional[str] = None

    if ramp_weeks < 1:
        # hold + taper >= weeks_to_race: no room for a ramp. Clamp rather
        # than emit negative ramp weeks; the plan degenerates to "hold at
        # baseline" (or whatever fits) for the remaining weeks.
        ramp_weeks = 0
        original_hold, original_taper = hold_weeks, taper_weeks
        # Cap so ramp + hold + taper always equals weeks_to_race, even in
        # this degenerate case — taper first (it's what actually matters
        # right before the race), then whatever's left over goes to hold.
        taper_weeks = min(taper_weeks, weeks_to_race)
        hold_weeks = max(0, weeks_to_race - taper_weeks)
        peak = baseline
        warning = (
            "Peak hold + taper window leaves no room for a ramp "
            f"({original_hold + original_taper} of {weeks_to_race} weeks) — "
            "shorten peak hold/taper or move the race out."
        )
    else:
        peak = baseline * (1.0 + ramp_rate) ** (ramp_weeks + 1)

    ceiling = (
        ACWR_CEILING_MULT * trailing_28d_avg
        if trailing_28d_avg is not None and trailing_28d_avg > 0
        else None
    )

    def _clamp(value: float) -> tuple[float, bool]:
        if ceiling is not None and value > ceiling:
            return ceiling, True
        return value, False

    weeks: List[WeekTarget] = []

    for w in range(1, ramp_weeks + 1):
        raw = baseline * (1.0 + ramp_rate) ** w
        value, clamped = _clamp(raw)
        weeks.append({"week_index": w, "target_tss": round(value, 1), "phase": "ramp", "clamped": clamped})

    for w in range(ramp_weeks + 1, build_weeks + 1):
        value, clamped = _clamp(peak)
        weeks.append({"week_index": w, "target_tss": round(value, 1), "phase": "hold", "clamped": clamped})

    fractions = _taper_fractions(taper_weeks)
    for i, frac in enumerate(fractions):
        w = build_weeks + i + 1
        raw = peak * frac
        value, clamped = _clamp(raw)
        # The final taper week contains race day — flag it distinctly so the
        # UI can render it as the "race week" bar, not just another taper bar.
        phase = "race" if i == len(fractions) - 1 else "taper"
        weeks.append({"week_index": w, "target_tss": round(value, 1), "phase": phase, "clamped": clamped})

    return {
        "weeks": weeks,
        "peak": round(peak, 1),
        "ramp_weeks": ramp_weeks,
        "hold_weeks": hold_weeks,
        "taper_weeks": taper_weeks,
        "build_weeks": build_weeks,
        "weeks_to_race": weeks_to_race,
        "warning": warning,
    }
