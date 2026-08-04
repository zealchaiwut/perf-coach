"""
Coach plan lever & phase engine — deterministic, rule-based, zero LLM calls.

Translates training-load and weight signals into structured coaching state:
levers (load, weight), periodization timeline, interaction constraints,
and lever ranking.  The output is consumed by AI-facing surfaces that
generate coaching narrative; this module contains only pure math and
rule logic so callers can rely on it without re-deriving it.

No LLM imports allowed in this file.  A static test enforces this.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any
from backend.utils.time import today_bangkok

# ── Module constants ───────────────────────────────────────────────────────────
ACWR_LOCK_THRESHOLD: float = 1.30

# Minimum logged days in a 14-day window before a deficit is recommended.
LOG_CONSISTENCY_THRESHOLD: int = 12
LOG_CONSISTENCY_TOTAL: int = 14

# Recommended deficit when weight logging is consistent and ramp is inactive.
DEFICIT_MIN_KCAL: int = 300
DEFICIT_MAX_KCAL: int = 400
DEFICIT_RAMP_CAP_KCAL: int = 0  # capped to zero during ramp phase

# EWMA time-constants (days) — match training_load.py defaults.
ATL_DAYS: int = 7
CTL_DAYS: int = 42

# Maximum weeks the convergence simulation may run before capping.
ACWR_CONVERGENCE_WEEKS_CAP: int = 12

# Representative target CTL (TSS/day) by race distance.
_TARGET_CTL: dict[str, float] = {
    "5k": 50.0,
    "10k": 60.0,
    "half": 70.0,
    "marathon": 85.0,
}


# ── ACWR convergence simulation ───────────────────────────────────────────────

def simulate_acwr_convergence(
    atl: float,
    ctl: float,
    current_daily_tss: float,
    today: date,
    *,
    target_acwr: float = ACWR_LOCK_THRESHOLD,
    max_weeks: int = ACWR_CONVERGENCE_WEEKS_CAP,
    atl_days: int = ATL_DAYS,
    ctl_days: int = CTL_DAYS,
) -> date:
    """Simulate holding daily TSS constant and return the first date ACWR < target.

    Iterates the Banister EWMA update rule for ATL and CTL day-by-day,
    keeping ``current_daily_tss`` constant.  Returns ``today + i`` on the
    first iteration ``i`` where ``ATL / CTL < target_acwr``.  Capped at
    ``max_weeks * 7`` days.

    Worked example
    --------------
    ATL=96, CTL=60, daily_tss=316/7 ≈ 45.14 →
        Day 1: ACWR ≈ 1.496  Day 2: ≈ 1.406  Day 3: ≈ 1.327  Day 4: ≈ 1.259
    Convergence on day 4 → today + 4 days.
    """
    alpha_atl = 1.0 - math.exp(-1.0 / atl_days)
    alpha_ctl = 1.0 - math.exp(-1.0 / ctl_days)

    cur_atl = float(atl)
    cur_ctl = float(ctl)
    max_days = max_weeks * 7

    for i in range(1, max_days + 1):
        cur_atl = cur_atl + (current_daily_tss - cur_atl) * alpha_atl
        cur_ctl = cur_ctl + (current_daily_tss - cur_ctl) * alpha_ctl
        if cur_ctl > 0 and cur_atl / cur_ctl < target_acwr:
            return today + timedelta(days=i)

    return today + timedelta(days=max_days)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _attr(obj: Any, key: str, default: Any = None) -> Any:
    """Return obj[key] (dict) or obj.key (object), falling back to default."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _race_date(goal: Any) -> date | None:
    raw = _attr(goal, "race_date")
    if raw is None:
        return None
    if isinstance(raw, str):
        return date.fromisoformat(raw)
    return raw


# ── Load lever ─────────────────────────────────────────────────────────────────

def _compute_load_lever(snapshot: Any, today: date) -> dict:
    if snapshot is None:
        return {"state": "unavailable"}

    acwr = _attr(snapshot, "acwr")
    atl = _attr(snapshot, "atl")
    ctl = _attr(snapshot, "ctl")
    tss_for_day = _attr(snapshot, "tss_for_day", 0) or 0

    if acwr is None or atl is None or ctl is None:
        return {"state": "unavailable"}

    current_daily_tss = float(tss_for_day)
    current_weekly_tss = round(current_daily_tss * 7)

    unlock_date = simulate_acwr_convergence(
        atl=float(atl),
        ctl=float(ctl),
        current_daily_tss=current_daily_tss,
        today=today,
    )

    if float(acwr) > ACWR_LOCK_THRESHOLD:
        return {
            "state": "locked",
            "reason": f"ACWR {float(acwr):.2f} — hold ~{current_weekly_tss} TSS",
            "unlock_date": unlock_date,
        }

    return {
        "state": "available",
        "unlock_date": today,
    }


# ── Weight lever ───────────────────────────────────────────────────────────────

def _compute_weight_lever(
    log_consistency: Any,
    is_ramp_active: bool,
    *,
    threshold: int = LOG_CONSISTENCY_THRESHOLD,
) -> dict:
    if log_consistency is None:
        return {"state": "unavailable"}

    if isinstance(log_consistency, dict):
        logged_days = int(log_consistency.get("logged_days", 0))
    else:
        logged_days = int(log_consistency)

    if logged_days < threshold:
        return {
            "state": "active (measurement)",
            "logged_days": logged_days,
            "threshold": threshold,
        }

    deficit = DEFICIT_RAMP_CAP_KCAL if is_ramp_active else DEFICIT_MIN_KCAL
    return {
        "state": "active (deficit)",
        "recommended_deficit_kcal": deficit,
    }


# ── Timeline ───────────────────────────────────────────────────────────────────

def _compute_timeline(goal: Any, unlock_date: date, today: date) -> list[dict]:
    rd = _race_date(goal)
    if rd is None:
        return []

    # Back-compute phase boundaries from race_date.
    taper_end = rd
    taper_start = rd - timedelta(days=14)

    cut_end_end = rd - timedelta(days=63)   # 9 weeks before race
    cut_end_start = rd - timedelta(days=70)  # 10 weeks before race

    peak_start = cut_end_end + timedelta(days=1)
    peak_end = taper_start - timedelta(days=1)

    # Ramp: unlock_date until day before cut-end begins.
    ramp_start = unlock_date
    ramp_end = cut_end_start - timedelta(days=1)

    # Hold: today until day before ramp.
    hold_start = today
    hold_end = unlock_date - timedelta(days=1)

    def _fmt(d: date) -> str:
        return d.strftime("%B %-d")

    phases = [
        {
            "name": "hold",
            "start_date": hold_start,
            "end_date": hold_end,
            "directive": (
                f"Hold current TSS constant; ACWR converges by {_fmt(unlock_date)}."
            ),
        },
        {
            "name": "ramp",
            "start_date": ramp_start,
            "end_date": ramp_end,
            "directive": (
                f"Increase weekly TSS 5% per week from {_fmt(ramp_start)}"
                f" through {_fmt(ramp_end)}."
            ),
        },
        {
            "name": "cut-end",
            "start_date": cut_end_start,
            "end_date": cut_end_end,
            "directive": (
                f"Reduce calorie deficit to zero by {_fmt(cut_end_end)}"
                " (9 weeks before race)."
            ),
        },
        {
            "name": "peak block",
            "start_date": peak_start,
            "end_date": peak_end,
            "directive": (
                "Maintain peak training intensity;"
                " race-specific workouts and race-pace sharpening."
            ),
        },
        {
            "name": "taper",
            "start_date": taper_start,
            "end_date": taper_end,
            "directive": (
                f"Reduce volume 20–30% per week; maintain intensity;"
                f" arrive rested for {_fmt(taper_end)}."
            ),
        },
    ]

    # Sort chronologically by start_date.
    phases.sort(key=lambda p: p["start_date"])
    return phases


def _is_ramp_active(phases: list[dict], today: date) -> bool:
    for p in phases:
        if p["name"] == "ramp":
            return p["start_date"] <= today <= p["end_date"]
    return False


# ── Constraints ────────────────────────────────────────────────────────────────

def _compute_constraints(
    load_lever: dict,
    weight_lever: dict,
    is_ramp_active: bool,
) -> list[str]:
    out: list[str] = []
    if is_ramp_active:
        out.append(
            "modest deficit + rising volume OK; no aggressive deficit during ramp"
        )
    if load_lever.get("state") == "locked":
        out.append(
            "ACWR elevated — hold TSS; defer volume increases until load stabilizes"
        )
    if weight_lever.get("state") == "active (measurement)":
        out.append(
            "Insufficient weight logs — measure consistently before targeting a deficit"
        )
    return out


# ── Lever ranking ──────────────────────────────────────────────────────────────

def _compute_lever_ranking(
    snapshot: Any,
    goal: Any,
    weight_status: Any,
    load_lever: dict,
) -> dict:
    race_distance = _attr(goal, "race_distance") or "half"
    target_ctl = _TARGET_CTL.get(str(race_distance), 70.0)
    current_ctl = float(_attr(snapshot, "ctl", 0) or 0)
    ctl_gap = max(0.0, target_ctl - current_ctl)

    weight_gap = float(_attr(weight_status, "gap_kg", 0) or 0)

    # Normalised magnitude: each CTL-point ≈ 0.5 performance units; each kg ≈ 1.
    load_mag = ctl_gap * 0.5
    weight_mag = weight_gap

    bigger_lever = "load" if load_mag >= weight_mag else "weight"
    more_tractable = "weight" if load_lever.get("state") == "locked" else "load"

    rationale = (
        f"CTL gap {ctl_gap:.0f} TSS vs weight gap {weight_gap:.1f} kg; "
        f"{'load' if bigger_lever == 'load' else 'weight'} lever offers larger"
        " performance impact. "
        + (
            "Load lever locked — act on weight first."
            if load_lever.get("state") == "locked"
            else "Load lever available — prioritise training volume."
        )
    )

    return {
        "bigger_lever": bigger_lever,
        "more_tractable": more_tractable,
        "rationale": rationale,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def build_plan_state(
    goal: Any,
    training_load_snapshot: Any,
    acwr_state: str,
    guardrail_state: str,
    weight_status: Any,
    log_consistency: Any,
    *,
    _today: date | None = None,
) -> dict:
    """Return structured coaching plan state derived from training and weight signals.

    Parameters
    ----------
    goal:
        PerformanceGoal object or dict-like with ``race_date`` and ``race_distance``.
    training_load_snapshot:
        TrainingLoadSnapshot-like with ``ctl``, ``atl``, ``acwr``, ``tss_for_day``.
    acwr_state:
        Pre-classified ACWR band: ``"high_risk"``, ``"productive"``, etc.
    guardrail_state:
        ``"warn"`` or ``"ok"`` from ``compute_guardrail``.
    weight_status:
        Dict-like with ``gap_kg``, ``current_kg``, ``goal_kg``.
    log_consistency:
        Dict with ``logged_days`` / ``total_days``, or plain int (days logged).
    _today:
        Override today's date (for deterministic tests).

    Returns
    -------
    dict with keys ``levers``, ``timeline``, ``constraints``, ``lever_ranking``.
    Each section degrades to ``{"state": "unavailable"}`` when inputs are None.
    """
    today = _today if _today is not None else today_bangkok()

    if goal is None:
        return {
            "levers": {
                "load": {"state": "unavailable"},
                "weight": {"state": "unavailable"},
            },
            "timeline": [],
            "constraints": [],
            "lever_ranking": {"state": "unavailable"},
        }

    load_lever = _compute_load_lever(training_load_snapshot, today)
    unlock_date: date = load_lever.get("unlock_date") or today

    timeline = _compute_timeline(goal, unlock_date, today)
    ramp_active = _is_ramp_active(timeline, today)

    weight_lever = _compute_weight_lever(log_consistency, ramp_active)
    constraints = _compute_constraints(load_lever, weight_lever, ramp_active)
    lever_ranking = _compute_lever_ranking(
        training_load_snapshot, goal, weight_status, load_lever
    )

    return {
        "levers": {
            "load": load_lever,
            "weight": weight_lever,
        },
        "timeline": timeline,
        "constraints": constraints,
        "lever_ranking": lever_ranking,
    }


# ── Training habit adherence ───────────────────────────────────────────────────

def get_training_habit_adherence(
    training_habits: list,
    logs: list,
    days: int,
    *,
    _today: date | None = None,
) -> float:
    """Return adherence ratio for training-section habits over the given day window.

    Parameters
    ----------
    training_habits:
        Habit-like objects (duck-typed via ``_attr``); each must have an ``id``.
    logs:
        HabitLog-like objects with ``habit_id`` and ``log_date``.
    days:
        Length of the window ending today (inclusive).

    Returns
    -------
    Completed checkins / expected checkins, clamped to [0.0, 1.0].
    Returns 0.0 when there are no habits or no expected checkins.
    """
    if not training_habits or days <= 0:
        return 0.0

    today = _today if _today is not None else today_bangkok()
    window_start = today - timedelta(days=days - 1)

    training_ids = {_attr(h, "id") for h in training_habits}

    # Count distinct (habit_id, log_date) pairs within the window
    seen: set = set()
    for log in logs:
        hid = _attr(log, "habit_id")
        ld = _attr(log, "log_date")
        if hid in training_ids and ld is not None and window_start <= ld <= today:
            seen.add((hid, ld))

    expected = len(training_habits) * days
    return min(1.0, len(seen) / expected)
