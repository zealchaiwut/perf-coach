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

    if deload_enabled and phase == ramp and week_index in
            (deload_start_week, deload_start_week + 4, deload_start_week + 8, ...):
        target(w) *= (1 - DELOAD_CUT_FRACTION)   # deload BEFORE the ceiling clamp

    ceiling(w) = ACWR_CEILING_MULT * mean(last 4 weeks' ACTUAL target_tss)   # see "Moving ceiling" below
    target(w)  = min(target(w), ceiling(w))                                 # ACWR ceiling always wins

The ``+ 1`` exponent on ``peak`` is deliberate. The naive version
(``baseline * (1 + ramp_rate) ** ramp_weeks``) makes the ramp's last week
*equal* peak, so a 4-week hold would render five bars at peak. With the
``+ 1``, the ramp tops out strictly below peak and the hold block is exactly
``hold_weeks`` long.

Worked example (baseline 316, ramp_rate 0.05, hold_weeks 4, taper_weeks 3,
weeks_to_race 19, no ceiling binding)::

    build_weeks = 19 - 3 = 16
    ramp_weeks  = 16 - 4 = 12
    peak        = 316 * 1.05 ** 13 ≈ 596

    Ramp w1-12:  332, 348, 366, 384, 403, 424, 445, 467, 490, 515, 540, 568
    Hold w13-16: 596, 596, 596, 596
    Taper w17-19: 447, 358, 238 (peak * 0.75, 0.60, 0.40)

Counterintuitive note (surface as a tooltip on the peak-hold field in the
UI): raising ``hold_weeks`` *lowers* peak, because it shortens the ramp for a
fixed ``weeks_to_race``.

Moving ceiling
--------------
The ACWR ceiling is meant to answer "is this week's jump safe relative to
recent load", so it must move as the plan's own load moves — a STATIC ceiling
(``ACWR_CEILING_MULT * trailing_28d_avg`` applied unchanged to every future
week, the pre-2026-07 behaviour) clamps the first week the ramp outgrows
today's real trailing average and then FLATLINES every week after that at the
exact same number, since the ceiling never rises even though the plan's own
targets are rising. That produces a visibly wrong chart: a ramp that's
supposed to climb 5%/week instead goes flat for a dozen weeks.

Instead the ceiling for week ``w`` is ``ACWR_CEILING_MULT`` times the mean of
the ACTUAL (post-deload, post-clamp) ``target_tss`` of the trailing 4 weeks —
i.e. a real rolling 28-day chronic-load window computed over the plan's own
sequence, seeded with today's real ``trailing_28d_avg`` for the 4 "virtual"
weeks before week 1 (since we don't have a per-week breakdown of history,
only the aggregate). Concretely: a length-4 sliding window starts as
``[trailing_28d_avg] * 4``; after each week's target is finalized (deload
applied, then clamped against that week's own ceiling), it's pushed into the
window and the oldest value drops off. Each week's ``ceiling`` is exposed on
its ``WeekTarget`` entry so callers/UI can show exactly what bound applied.

This lets the ramp climb indefinitely as long as no single week jumps more
than ``ACWR_CEILING_MULT`` above its own trailing 4-week window — which is
what ACWR is actually meant to police — instead of being permanently pinned
to a snapshot of today's chronic load. A deload week's cut value still enters
the window, so it legitimately (and correctly) pulls the following weeks'
ceiling down a little — a real down week does lower rolling chronic load.

Baseline week (skip deload)
---------------------------
``baseline`` is the most recent *completed* week's actual TSS that is **not**
on the athlete's 4-week deload cycle. Plan ``week_index`` 1 is this week;
last week is index 0, two weeks ago is −1, etc. The same
``is_deload_cycle_week`` rule used for future ramp cuts flags those prior
weeks, so a just-finished deload (e.g. week 0 when ``deload_start_week=4``)
does not seed the next ramp — callers walk back via
``resolve_baseline_weeks_ago`` and pass that week's logged TSS here.

Baseline cap
------------
``baseline`` (that resolved week's actual TSS) is wrong when that week was
itself a spike. A single hard week can run 30-40% above chronic load without
being a real change in fitness — ramping 5%/week off a spike compounds an
overshoot that already exists before the plan even starts.

The baseline actually used for the ramp/peak math is capped against chronic
load: ``min(raw_baseline, BASELINE_CAP_MULT * chronic_weekly)``, where
``chronic_weekly`` is the SAME ``trailing_28d_avg`` already passed in for the
moving ceiling above (one number, two uses — never a second independent
"chronic load" estimate). When the cap binds, ``baseline_capped`` is True and
callers MUST surface that plainly (a silent cap reads as "the ramp is
broken," not as the safety feature it is) — see
``docs/calculations/load-plan.md``.

This is a different guard from the moving ACWR ceiling above: the cap fixes
the ramp's STARTING POINT (once, from ``raw_baseline``); the ceiling limits
EACH WEEK going forward. Both apply; the cap runs first, then every
downstream week (including week 1) is still subject to its own ceiling.

Verdict consolidation
----------------------
When the deterministic training_verdict.compute_verdict() result is
``"hold"`` or ``"back_off"`` (see backend/services/training_verdict.py — a
Python-computed judgment from the Part-A CTL/ATL/TSB/ACWR snapshot, never an
LLM decision), the NEAR-TERM weeks that would otherwise be ``ramp`` or
``hold`` phase are overridden to a flat target instead: ``baseline`` when
``"hold"``, ``BACK_OFF_TARGET_MULT * baseline`` when ``"back_off"``. Their
``phase`` becomes ``"consolidation"`` so the season chart renders a visibly
flat block instead of a ramp that would otherwise pretend to continue
climbing through a state the athlete's own snapshot says isn't safe to build
from yet. Taper and race weeks are NEVER overridden — they already have
their own down-curve and a race close enough to be tapering for takes
priority over a consolidation block.

**Only the near-term weeks, not the whole season** (2026-07-10 fix): how
many weeks get flattened is ``consolidation_weeks`` — the SAME
``weeks_to_converge`` estimate compute_verdict() already computes ("how long
until this normalizes"), defaulting to 1 (just the current week) when not
given. Weeks beyond that horizon use the normal ramp/hold formula for their
own index, exactly as if verdict were "build". Before this fix, a single
day's verdict flattened the ENTIRE remaining ramp+hold phase (potentially
15+ weeks) at one TSS value, contradicting the verdict's own "back to normal
in ~1 week" convergence estimate shown right next to it in the UI — a
today-only snapshot was being rendered as a multi-month forecast.

The verdict is a snapshot of *today*; it is not baked into the plan beyond
the current computation — the caller re-derives it fresh on every request
(from the current CTL/ATL/TSB/ACWR), so as soon as the athlete's numbers
recover to "build", the very next call resumes the normal ramp/hold/taper
series with no separate "resume" step required. The consolidation-horizon
fix above makes this true WITHIN a single request too, not just across days.

Deload (every 4th week)
------------------------
When ``deload_enabled`` is True, every 4th ``week_index`` starting at
``deload_start_week`` (default 4 → weeks 4, 8, 12, ...; start 2 → weeks
2, 6, 10, ...) that falls in the RAMP phase is cut by
``DELOAD_CUT_FRACTION`` (30%) BEFORE the ceiling clamp. The start week is
the athlete's pick of WHICH week of the 4-week cycle is the down week —
someone already two weeks into a build wants the next deload in two weeks,
not re-zeroed to week 4 of the plan. Peak-hold weeks are NEVER deloaded (2026-07 fix) — the
hold phase is immediately followed by taper, which already IS the recovery
reduction; cutting the last hold week right before a taper is redundant at
best and, if it lands on hold week 4 (the week right before taper starts),
would mean the athlete never actually holds a full 4 weeks at peak. Taper/
race weeks are never cut either — they already have their own down-curve,
and double-tapering would be wrong.

Critically, the formula for week ``w`` is computed directly from ``w``
(``baseline * (1 + ramp_rate) ** w``), never recursively from week ``w-1``'s
(possibly cut) value — so week 5 resumes the ramp from where week 4 WOULD
have been without the cut, not from the cut value. A deload week is a single
down week, not a reset of the whole ramp trajectory. (The moving ceiling
window still sees the cut value, per above — a deload legitimately softens
the following week's ceiling a little, same as it would for a real athlete.)
"""

from __future__ import annotations

from collections import deque
from typing import List, Optional, TypedDict

# ── Taper shape ────────────────────────────────────────────────────────────
# Fraction of peak TSS assigned to each taper week, for the default 3-week
# taper. A documented constant, not a magic number — no equivalent existed
# in the old settings before this module. TODO: make this configurable per
# athlete/plan; today every plan uses this one curve, interpolated (see
# _taper_fractions) when taper_weeks != len(TAPER_CURVE).
TAPER_CURVE: List[float] = [0.75, 0.60, 0.40]

# Multiplier applied to the trailing 4-week window to get the ACWR ceiling a
# week's target may never exceed, regardless of what the ramp/hold/taper math
# wants. Matches backend/services/plan_suggestions.py's ACWR_HIGH_BOUND
# (itself a mirror of acwr.UPPER_BOUND, not acwr.HIGH_BOUND — see
# docs/calculations/load-plan.md "Known weaknesses" for the discrepancy this
# name inherits).
ACWR_CEILING_MULT: float = 1.3

# Rolling window size (in weeks) for the moving ACWR ceiling — 4 weeks ≈ the
# 28-day chronic-load window the rest of the app uses (see acwr.py). See the
# module docstring's "Moving ceiling" section.
_CEILING_WINDOW_WEEKS: int = 4

# Deload ("cut 30% every 4th week") — see the module docstring's "Deload"
# section. A deload week's cut is a single down week, not a ramp reset: the
# next week's raw target is recomputed from the uncut formula, not from the
# deload's lower value.
DELOAD_CUT_FRACTION: float = 0.30
_DELOAD_EVERY_N_WEEKS: int = 4

# Baseline cap — see the module docstring's "Baseline cap" section. A spike
# week (last week's actual TSS well above chronic load) must not seed the
# ramp at the spike's own level; cap it against chronic load instead.
BASELINE_CAP_MULT: float = 1.15

# Consolidation block (verdict-aware, see module docstring's "Verdict
# consolidation" section) — the back_off target as a fraction of baseline.
BACK_OFF_TARGET_MULT: float = 0.9

# How far back resolve_baseline_weeks_ago may walk when skipping deload-cycle
# weeks. At most 1-in-4 weeks is a deload, so 8 is plenty of headroom.
_BASELINE_LOOKBACK_WEEKS: int = 8


def is_deload_cycle_week(
    week_index: int,
    *,
    deload_enabled: bool = False,
    deload_start_week: int = 4,
) -> bool:
    """True when ``week_index`` lands on the athlete's 4-week deload cycle.

    Uses the same numbering as ``compute_load_plan``: 1 = this week, 0 = last
    completed week, −1 = two weeks ago, …. Works for any integer so prior
    calendar weeks can be flagged the same way future target bars are.
    Peak-hold / taper cuts are a separate concern inside ``compute_load_plan``;
    this helper only answers the cycle question.
    """
    if not deload_enabled:
        return False
    start = min(max(1, int(deload_start_week)), _DELOAD_EVERY_N_WEEKS)
    return int(week_index) % _DELOAD_EVERY_N_WEEKS == start % _DELOAD_EVERY_N_WEEKS


def resolve_baseline_weeks_ago(
    *,
    deload_enabled: bool = False,
    deload_start_week: int = 4,
    max_lookback_weeks: int = _BASELINE_LOOKBACK_WEEKS,
) -> int:
    """Return how many weeks ago to take the ramp baseline from.

    1 = last completed week (plan ``week_index`` 0). When deload is enabled,
    skips weeks on the deload cycle so the ramp resumes from the last real
    build week (e.g. after a week-0 deload, return 2 → two weeks ago).
    """
    lookback = max(1, int(max_lookback_weeks))
    for weeks_ago in range(1, lookback + 1):
        week_index = 1 - weeks_ago
        if not is_deload_cycle_week(
            week_index,
            deload_enabled=deload_enabled,
            deload_start_week=deload_start_week,
        ):
            return weeks_ago
    return 1


class WeekTarget(TypedDict):
    week_index: int  # 1-based, 1..weeks_to_race
    target_tss: float
    phase: str  # "ramp" | "hold" | "taper" | "race"
    clamped: bool
    deload: bool
    ceiling: Optional[float]  # this week's own moving ACWR ceiling, or None if unset


class LoadPlanResult(TypedDict):
    weeks: List[WeekTarget]
    peak: float
    ramp_weeks: int
    hold_weeks: int
    taper_weeks: int
    build_weeks: int
    weeks_to_race: int
    warning: Optional[str]
    raw_baseline: float  # last completed week's actual TSS, BEFORE any cap
    baseline: float  # the value actually used for ramp/peak math (may be capped)
    chronic_weekly: Optional[float]  # == trailing_28d_avg; None if not enough history
    baseline_capped: bool  # True when baseline < raw_baseline


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
    deload_enabled: bool = False,
    deload_start_week: int = 4,
    verdict: Optional[str] = None,
    consolidation_weeks: Optional[int] = None,
) -> LoadPlanResult:
    """Compute the per-week target-TSS series from now to an A race.

    Args:
        baseline: ACTUAL TSS of the resolved baseline week (never planned
            TSS — a missed week must lower future targets, not silently
            inflate them). Callers should pass the week chosen by
            ``resolve_baseline_weeks_ago`` so a just-finished deload does
            not seed the ramp. Capped against chronic load before use —
            see the module docstring's "Baseline cap" section; the
            raw/capped/chronic values are all returned so callers can
            surface the cap.
        ramp_rate: fractional weekly increase, e.g. 0.05 for 5%/week.
        hold_weeks: length of the peak-hold plateau, in weeks.
        taper_weeks: length of the taper, in weeks.
        weeks_to_race: total weeks counted in the series (build + taper).
        trailing_28d_avg: trailing 28-day average weekly TSS — seeds BOTH the
            baseline cap and the MOVING ACWR ceiling (see module docstring;
            one number, two uses). Ceiling is skipped entirely (every week's
            `ceiling` is None) and the baseline is never capped when this is
            None or 0 (not enough history yet).
        deload_enabled: cut every 4th week that falls in the ramp phase by
            DELOAD_CUT_FRACTION. See module docstring.
        deload_start_week: which week of the 4-week cycle the deload lands
            on — first deload at this week_index, then every 4 weeks after
            (start 4 → 4, 8, 12, ...; start 2 → 2, 6, 10, ...). Clamped to
            1..4. Ignored when deload_enabled is False.
        verdict: "hold" | "back_off" | "build" | None — from
            training_verdict.compute_verdict(). "hold"/"back_off" override
            ONLY the near-term weeks (see `consolidation_weeks`) to a flat
            consolidation target (phase becomes "consolidation"); anything
            else (including None) leaves the ramp/hold/taper math untouched.
            See module docstring's "Verdict consolidation" section.
        consolidation_weeks: how many of the NEAREST ramp/hold weeks the
            "hold"/"back_off" override applies to — from
            training_verdict.compute_verdict()'s own `weeks_to_converge`
            estimate (the verdict engine's answer to "how long until this
            normalizes"). Weeks beyond this horizon use the normal ramp/hold
            formula for their own index, unaffected — the verdict is a
            snapshot of TODAY, not a multi-month forecast, so it must not
            flatline the entire season chart. Defaults to 1 (just the
            current week) when a verdict is active but this isn't given, or
            when the estimate is 0/None. Ignored when verdict isn't
            "hold"/"back_off".

    Returns:
        LoadPlanResult — see the module docstring for the math.
    """
    raw_baseline = max(0.0, float(baseline))
    ramp_rate = float(ramp_rate)
    hold_weeks = max(0, int(hold_weeks))
    taper_weeks = max(0, int(taper_weeks))
    weeks_to_race = max(0, int(weeks_to_race))
    deload_enabled = bool(deload_enabled)
    deload_start_week = min(max(1, int(deload_start_week)), _DELOAD_EVERY_N_WEEKS)

    chronic_weekly = (
        float(trailing_28d_avg) if trailing_28d_avg is not None and trailing_28d_avg > 0 else None
    )
    if chronic_weekly is not None:
        baseline = min(raw_baseline, BASELINE_CAP_MULT * chronic_weekly)
    else:
        baseline = raw_baseline
    baseline_capped = baseline < raw_baseline

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

    # Moving ACWR ceiling — a rolling 4-week window of this SAME series' own
    # finalized (post-deload, post-clamp) values, seeded with today's real
    # trailing_28d_avg for the 4 "virtual" weeks before week 1. See the
    # module docstring's "Moving ceiling" section for why a static ceiling
    # (unchanged for every future week) is wrong.
    history: Optional[deque] = (
        deque([float(trailing_28d_avg)] * _CEILING_WINDOW_WEEKS, maxlen=_CEILING_WINDOW_WEEKS)
        if trailing_28d_avg is not None and trailing_28d_avg > 0
        else None
    )

    def _ceiling_now() -> Optional[float]:
        if history is None:
            return None
        return ACWR_CEILING_MULT * (sum(history) / len(history))

    def _finalize(value: float) -> tuple[float, bool, Optional[float]]:
        """Clamp `value` against the CURRENT moving ceiling, then push the
        finalized value into the rolling window for subsequent weeks."""
        ceiling = _ceiling_now()
        if ceiling is not None and value > ceiling:
            value, clamped = ceiling, True
        else:
            clamped = False
        if history is not None:
            history.append(value)
        return value, clamped, ceiling

    def _is_deload(week_index: int) -> bool:
        return (
            deload_enabled
            and week_index % _DELOAD_EVERY_N_WEEKS == deload_start_week % _DELOAD_EVERY_N_WEEKS
        )

    # Verdict consolidation — see module docstring. Only "hold"/"back_off"
    # override anything, and ONLY for the near-term weeks the verdict engine
    # itself says are affected (`consolidation_weeks`, from compute_verdict's
    # own weeks_to_converge estimate) — a verdict is a snapshot of today, not
    # a forecast for the whole season. Weeks beyond that horizon fall through
    # to the normal ramp/hold formula at their own index, same as if verdict
    # were "build". Defaults to 1 (just the current week) so a bare
    # "hold"/"back_off" with no horizon given still does something sane
    # without flatlining the rest of the chart.
    consolidation_target: Optional[float] = None
    if verdict == "hold":
        consolidation_target = baseline
    elif verdict == "back_off":
        consolidation_target = baseline * BACK_OFF_TARGET_MULT
    consolidation_horizon = (
        max(1, int(consolidation_weeks)) if consolidation_target is not None and consolidation_weeks
        else (1 if consolidation_target is not None else 0)
    )

    weeks: List[WeekTarget] = []

    for w in range(1, ramp_weeks + 1):
        if consolidation_target is not None and w <= consolidation_horizon:
            value, clamped, ceiling = _finalize(consolidation_target)
            weeks.append({
                "week_index": w, "target_tss": round(value, 1), "phase": "consolidation",
                "clamped": clamped, "deload": False,
                "ceiling": round(ceiling, 1) if ceiling is not None else None,
            })
            continue
        raw = baseline * (1.0 + ramp_rate) ** w
        deload = _is_deload(w)
        if deload:
            raw *= (1.0 - DELOAD_CUT_FRACTION)
        value, clamped, ceiling = _finalize(raw)
        weeks.append({
            "week_index": w, "target_tss": round(value, 1), "phase": "ramp",
            "clamped": clamped, "deload": deload,
            "ceiling": round(ceiling, 1) if ceiling is not None else None,
        })

    for w in range(ramp_weeks + 1, build_weeks + 1):
        if consolidation_target is not None and w <= consolidation_horizon:
            value, clamped, ceiling = _finalize(consolidation_target)
            weeks.append({
                "week_index": w, "target_tss": round(value, 1), "phase": "consolidation",
                "clamped": clamped, "deload": False,
                "ceiling": round(ceiling, 1) if ceiling is not None else None,
            })
            continue
        # Hold weeks are never deloaded — taper (which starts immediately
        # after) already IS the recovery reduction; see module docstring's
        # "Deload" section.
        value, clamped, ceiling = _finalize(peak)
        weeks.append({
            "week_index": w, "target_tss": round(value, 1), "phase": "hold",
            "clamped": clamped, "deload": False,
            "ceiling": round(ceiling, 1) if ceiling is not None else None,
        })

    fractions = _taper_fractions(taper_weeks)
    for i, frac in enumerate(fractions):
        w = build_weeks + i + 1
        raw = peak * frac
        value, clamped, ceiling = _finalize(raw)
        # The final taper week contains race day — flag it distinctly so the
        # UI can render it as the "race week" bar, not just another taper bar.
        # Taper/race weeks are never deloaded — they already have their own
        # down-curve; a further cut would double-taper.
        phase = "race" if i == len(fractions) - 1 else "taper"
        weeks.append({
            "week_index": w, "target_tss": round(value, 1), "phase": phase,
            "clamped": clamped, "deload": False,
            "ceiling": round(ceiling, 1) if ceiling is not None else None,
        })

    return {
        "weeks": weeks,
        "peak": round(peak, 1),
        "ramp_weeks": ramp_weeks,
        "hold_weeks": hold_weeks,
        "taper_weeks": taper_weeks,
        "build_weeks": build_weeks,
        "weeks_to_race": weeks_to_race,
        "warning": warning,
        "raw_baseline": round(raw_baseline, 1),
        "baseline": round(baseline, 1),
        "chronic_weekly": round(chronic_weekly, 1) if chronic_weekly is not None else None,
        "baseline_capped": baseline_capped,
    }
