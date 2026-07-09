"""Deterministic training-load verdict engine (Part B of the load-metric fix).

The LLM must not decide whether an athlete should back off, hold, or build —
it faithfully narrated a bad ATL value and produced a dangerous
recommendation; a better prompt would not have helped, since the LLM has no
way to independently check its own arithmetic against the guardrail
thresholds. The verdict is computed here, in plain Python, from the Part-A
snapshot (backend/services/training_load.py's current_load()/
get_snapshot_series() — the single source of truth for CTL/ATL/TSB/ACWR).

Exposes:
  Verdict           — Literal["back_off", "hold", "build"]
  compute_verdict(...) — pure function: snapshot -> verdict + reason + a
                         convergence estimate when not "build"

Thresholds (ACWR_BACK_OFF_THRESHOLD=1.5, ACWR_HOLD_THRESHOLD=1.3,
ATL_CTL_HOLD_RATIO=1.25, TSB_HOLD_FLOOR=-25) are named constants, documented
in docs/calculations/acwr-guardrail.md alongside a note that ACWR's
injury-predictive validity is contested in the sports-science literature —
it is a useful flag, not a diagnosis, and the report's language must match
that confidence level (see backend/services/weekly_summary.py).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Literal, Optional, TypedDict

Verdict = Literal["back_off", "hold", "build"]

# ── Verdict thresholds — named constants, not literals ──────────────────────
# Above this ACWR, the acute spike is large enough to significantly raise
# injury risk (mirrors acwr.HIGH_BOUND — see docs/calculations/acwr-guardrail.md).
ACWR_BACK_OFF_THRESHOLD: float = 1.5
# Above this ACWR (and at/below ACWR_BACK_OFF_THRESHOLD), load is elevated
# enough to warrant holding rather than continuing to ramp (mirrors
# acwr.UPPER_BOUND / plan_suggestions.ACWR_HIGH_BOUND).
ACWR_HOLD_THRESHOLD: float = 1.3
# When ATL exceeds CTL by more than this ratio, acute load is running well
# ahead of fitness even if the windowed ACWR hasn't yet caught up (ACWR's
# chronic window lags real-time by design — this catches the gap ACWR alone
# can miss in the first ~2 weeks of a spike).
ATL_CTL_HOLD_RATIO: float = 1.25
# TSB (form) below this is "deeply fatigued" regardless of ACWR/ATL:CTL —
# stricter than training_load.FORM_BURIED_CEILING (-10), which flags routine
# fatigue; this is the threshold for actively holding load, not just a label.
TSB_HOLD_FLOOR: float = -25.0

# Below this CTL, the ATL:CTL and TSB hold-checks are skipped entirely. CTL
# starts at 0 and rises slowly (42-day EWMA); ATL reacts fast (7-day EWMA).
# For anyone cold-starting (a brand-new user, or returning after a long
# break), the FIRST real workout already makes atl >> ctl and tsb deeply
# negative — not because of overreach, but simply because CTL hasn't had
# time to reflect any fitness yet. Without this floor, compute_verdict would
# tell every new user to "hold" on day one, which is exactly the perpetual-
# flatline failure mode this whole fix exists to remove (just moved from the
# old static ceiling to the verdict layer). ACWR's own checks don't need this
# guard — compute_acwr already returns None during its own <28-day
# "baseline_forming" window (see docs/calculations/acwr-guardrail.md), and
# the acwr branches above are already gated on `is not None`.
_MIN_CTL_FOR_HOLD_GUARDS: float = 15.0

# ── Convergence-estimate constants ───────────────────────────────────────────
# CTL's own EWMA time constant (days) — mirrors training_load.CTL_DAYS. Not
# imported directly to keep this module import-light and independently
# testable; the two are asserted equal in tests/test_training_verdict.py.
_CTL_TIME_CONSTANT_DAYS: int = 42
_DAYS_PER_WEEK: int = 7
# Convergence is defined against the SAME threshold used for the "hold"
# verdict — "converged" means the projected ATL:CTL gap no longer implies an
# elevated ACWR, not literally acwr<=1.0.
_CONVERGENCE_TARGET_RATIO: float = ACWR_HOLD_THRESHOLD
# Convergence estimate horizon — beyond this, "weeks_to_converge" is reported
# as this cap rather than searching indefinitely (an athlete who won't
# converge within 2 years has a data problem, not a projection problem).
_MAX_CONVERGENCE_WEEKS: int = 104


class VerdictSnapshot(TypedDict, total=False):
    """The subset of current_load()'s/get_snapshot_series()'s return shape
    compute_verdict needs — pass either directly."""
    acwr: Optional[float]
    tsb: float
    ctl: float
    atl: float


class VerdictResult(TypedDict):
    verdict: Verdict
    reason: str
    acwr: Optional[float]
    tsb: float
    ctl: float
    atl: float
    expected_ctl_in_3w: Optional[float]
    weeks_to_converge: Optional[int]
    converge_date: Optional[str]


def _project_convergence(ctl: float, atl: float, today: date) -> tuple[Optional[float], Optional[int], Optional[str]]:
    """Project CTL forward assuming the athlete HOLDS current load steady
    (ATL stays ~constant at its current level; CTL's slow EWMA rises toward
    it) and find the smallest n (weeks) where the projected ATL:CTL ratio
    drops to _CONVERGENCE_TARGET_RATIO or below.

    Pure arithmetic — not a real re-simulation of the windowed ACWR (that
    would require per-day load assumptions this function isn't given); an
    honest estimate, not a forecast. Returns (expected_ctl_in_3w,
    weeks_to_converge, converge_date_iso). weeks_to_converge is 0 when
    already at/under target or when atl<=ctl (nothing to converge from).
    """
    weekly_ctl_gain = (atl - ctl) * (1 - math.exp(-_DAYS_PER_WEEK / _CTL_TIME_CONSTANT_DAYS))
    expected_ctl_in_3w = round(ctl + 3 * weekly_ctl_gain, 1)

    if ctl <= 0 or atl <= ctl * _CONVERGENCE_TARGET_RATIO:
        return expected_ctl_in_3w, 0, today.isoformat()

    if weekly_ctl_gain <= 0:
        # CTL isn't rising toward ATL (shouldn't happen when atl>ctl*target,
        # but guard against it rather than looping forever).
        return expected_ctl_in_3w, None, None

    projected_ctl = ctl
    for n in range(1, _MAX_CONVERGENCE_WEEKS + 1):
        projected_ctl = ctl + n * weekly_ctl_gain
        if projected_ctl <= 0:
            continue
        if atl / projected_ctl <= _CONVERGENCE_TARGET_RATIO:
            return expected_ctl_in_3w, n, (today + timedelta(weeks=n)).isoformat()

    return expected_ctl_in_3w, _MAX_CONVERGENCE_WEEKS, (today + timedelta(weeks=_MAX_CONVERGENCE_WEEKS)).isoformat()


def compute_verdict(
    snap: VerdictSnapshot,
    chronic_weekly: Optional[float] = None,
    last_week_actual: Optional[float] = None,
    *,
    today: Optional[date] = None,
) -> VerdictResult:
    """Deterministic back_off / hold / build verdict from a training-load
    snapshot. Pure function — no I/O, no LLM call.

    Args:
        snap: dict with acwr/tsb/ctl/atl — typically training_load.
            current_load()'s return value directly.
        chronic_weekly: trailing 28-day average weekly TSS. Accepted for
            future threshold refinement (e.g. scaling ATL_CTL_HOLD_RATIO by
            training history depth) — not currently used in the decision,
            kept as an explicit parameter so callers don't need to change
            when it is.
        last_week_actual: last completed week's actual TSS. Same as
            chronic_weekly — accepted, not yet used; keeps the signature
            stable for load_plan.py callers that already have both values
            on hand from the baseline-cap computation.
        today: for the convergence-date projection; defaults to date.today().

    Returns:
        VerdictResult. expected_ctl_in_3w/weeks_to_converge/converge_date
        are populated whenever verdict is "hold" or "back_off" (the single
        most useful thing the report can say); None for "build".
    """
    today = today or date.today()
    acwr = snap.get("acwr")
    tsb = float(snap.get("tsb", 0.0))
    ctl = float(snap.get("ctl", 0.0))
    atl = float(snap.get("atl", 0.0))

    if acwr is not None and acwr > ACWR_BACK_OFF_THRESHOLD:
        verdict: Verdict = "back_off"
        reason = f"ACWR {acwr:.2f} — acute load {(acwr - 1) * 100:.0f}% above chronic"
    elif acwr is not None and acwr > ACWR_HOLD_THRESHOLD:
        verdict = "hold"
        reason = f"ACWR {acwr:.2f} above the {ACWR_HOLD_THRESHOLD} guardrail"
    elif ctl > _MIN_CTL_FOR_HOLD_GUARDS and atl > ATL_CTL_HOLD_RATIO * ctl:
        verdict = "hold"
        reason = "acute load well above chronic; let CTL catch up"
    elif ctl > _MIN_CTL_FOR_HOLD_GUARDS and tsb < TSB_HOLD_FLOOR:
        verdict = "hold"
        reason = f"TSB {tsb:.1f} — deeply fatigued"
    else:
        verdict = "build"
        reason = "load and freshness within normal build range"

    expected_ctl_in_3w = weeks_to_converge = converge_date = None
    if verdict != "build":
        expected_ctl_in_3w, weeks_to_converge, converge_date = _project_convergence(ctl, atl, today)

    return {
        "verdict": verdict,
        "reason": reason,
        "acwr": acwr,
        "tsb": round(tsb, 2),
        "ctl": round(ctl, 2),
        "atl": round(atl, 2),
        "expected_ctl_in_3w": expected_ctl_in_3w,
        "weeks_to_converge": weeks_to_converge,
        "converge_date": converge_date,
    }
