"""Plan pipeline v2 — deterministic weekly skeleton (stage 1).

LLM never architects the week. Safety (ACWR clamp) is always the last step
of budget computation. Taper ownership: load_plan.TAPER_CURVE only.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
from statistics import median
from typing import Any

from backend.services.load_plan import TAPER_CURVE, compute_load_plan
from backend.services.plan_suggestions import (
    ACWR_HIGH_BOUND,
    FALLBACK_MIN_WEEKLY_TSS,
    _MAX_CONSECUTIVE_TRAINING_DAYS,
    validation_errors,
)
from backend.utils.log import get_logger

_log = get_logger(__name__)

# Soft ramp when no race-anchored plan exists (matches legacy fallback intent).
_NO_PLAN_RAMP: float = 1.05

_STRENGTH_BLOCK_LABELS = frozenset({
    "Warm-up", "Heavy compound", "Superset 1", "Superset 2", "Standalone", "Accessories",
})

_PIN_KEYS = frozenset({
    "day_offset", "workout_type", "target_tss", "duration_minutes", "subtype", "locked",
})


def weekly_budget(
    *,
    trailing_28d_weekly_avg_tss: float,
    logged_tss_so_far: float = 0.0,
    open_slot_count: int | None = None,
    load_plan_week: dict | None = None,
    race_anchored_target: float | None = None,
) -> dict[str, Any]:
    """Budget waterfall: TARGET → TAPER (via load_plan week) → SAFETY → MIDWEEK.

    `load_plan_week` is one entry from compute_load_plan()["weeks"] for the
    target week_index (already tapered when phase == "taper"). Do NOT re-derive
    taper fractions here — load_plan owns TAPER_CURVE.
    """
    trailing = float(trailing_28d_weekly_avg_tss or 0.0)
    logged = max(0.0, float(logged_tss_so_far or 0.0))

    # 1. TARGET
    if race_anchored_target is not None:
        target = float(race_anchored_target)
        source = "race_anchored"
    elif load_plan_week is not None and load_plan_week.get("target_tss") is not None:
        target = float(load_plan_week["target_tss"])
        source = "load_plan"
    else:
        target = max(trailing, FALLBACK_MIN_WEEKLY_TSS) * _NO_PLAN_RAMP
        source = "trailing_ramp"

    # 2. TAPER — already baked into load_plan_week.target_tss when phase is taper.
    # Expose taper metadata for callers/tests; never multiply again.
    phase = (load_plan_week or {}).get("phase")
    taper_applied = phase == "taper"
    taper_curve = list(TAPER_CURVE)

    # 3. SAFETY — ACWR clamp last
    ceiling = max(trailing, FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND
    # Prefer load_plan's moving ceiling when present
    lp_ceiling = (load_plan_week or {}).get("ceiling")
    if lp_ceiling is not None:
        ceiling = min(ceiling, float(lp_ceiling))
    clamped = min(target, ceiling)
    safety_clamped = clamped < target - 1e-6

    # 4. MIDWEEK — remainder over OPEN slots only
    remaining = max(0.0, round(clamped - logged, 1))
    open_n = open_slot_count if open_slot_count is not None else 7
    per_open = (remaining / open_n) if open_n > 0 else 0.0

    return {
        "target_before_safety": round(target, 1),
        "weekly_target": round(clamped, 1),
        "acwr_ceiling": round(ceiling, 1),
        "logged_tss_so_far": round(logged, 1),
        "remaining_tss": remaining,
        "open_slot_count": open_n,
        "per_open_slot_tss": round(per_open, 1),
        "source": source,
        "phase": phase,
        "taper_applied": taper_applied,
        "taper_curve": taper_curve,
        "safety_clamped": safety_clamped,
    }


def _long_run_weekday(history: list[tuple[int, str, float, float]]) -> int:
    """Median weekday of the highest-TSS run per week over history; default Sat=5."""
    # Group by week-ish: take top run each "chunk" — simpler: collect weekday of
    # each week's max run by sorting runs and taking top per rolling 7-day isn't
    # available without dates. Use all high-TSS runs: for each weekday, take the
    # max TSS run on that day; then among weekdays that hosted a "long" (top
    # quartile), pick the modal weekday of the absolute max runs.
    runs = [
        (wd, float(tss or 0), float(dur or 0))
        for wd, wtype, tss, dur in history
        if (wtype or "").lower() == "run" and 0 <= int(wd) <= 6
    ]
    if len(runs) < 2:
        return 5  # Saturday
    # Per occurrence of a "long candidate": runs at or above the 75th percentile TSS
    tss_vals = sorted(r[1] for r in runs)
    thresh = tss_vals[max(0, int(0.75 * (len(tss_vals) - 1)))]
    longs = [r[0] for r in runs if r[1] >= thresh and r[1] > 0]
    if not longs:
        # Fall back to weekday of the single highest-TSS run
        return max(runs, key=lambda r: r[1])[0]
    try:
        return int(round(median(longs)))
    except Exception:
        return 5


def _strength_weekdays(history: list[tuple[int, str, float, float]], n: int) -> list[int]:
    by_day: dict[int, list[float]] = {}
    for wd, wtype, tss, _dur in history:
        if (wtype or "").lower() != "strength" or not (0 <= int(wd) <= 6):
            continue
        by_day.setdefault(int(wd), []).append(float(tss or 0))
    ranked = sorted(
        by_day.keys(),
        key=lambda d: (-len(by_day[d]), -median(by_day[d])),
    )
    if ranked:
        return ranked[:n]
    # Defaults: Tue + Thu (offsets 1, 3)
    defaults = [1, 3, 5, 2, 4]
    return defaults[:n]


def _run_medians_by_day(
    history: list[tuple[int, str, float, float]],
) -> dict[int, tuple[float, float]]:
    """weekday → (median_tss, median_duration) for habitual runs (≥2)."""
    by_day: dict[int, list[tuple[float, float]]] = {}
    for wd, wtype, tss, dur in history:
        if (wtype or "").lower() != "run" or not (0 <= int(wd) <= 6):
            continue
        by_day.setdefault(int(wd), []).append((float(tss or 0), float(dur or 0)))
    out: dict[int, tuple[float, float]] = {}
    for d, vals in by_day.items():
        if len(vals) >= 2:
            out[d] = (median(v[0] for v in vals), median(v[1] for v in vals))
    return out


def _long_run_floors() -> tuple[int, int]:
    """(min_duration_min, min_tss) from aerobic_durability_gap preset."""
    try:
        from backend.services.gap_analysis.session_presets import _PRESET_DEFAULTS
        c = (_PRESET_DEFAULTS.get("aerobic_durability_gap") or {}).get("constraints") or {}
        return int(c.get("min_duration_min") or 110), int(c.get("min_tss") or 80)
    except Exception:
        return 110, 80


def _structure_hints_for(subtype: str) -> dict:
    try:
        from backend.services.gap_analysis.session_presets import _PRESET_DEFAULTS
    except Exception:
        _PRESET_DEFAULTS = {}
    mapping = {
        "long_run": "aerobic_durability_gap",
        "easy_run": "base_neglected",
        "tempo": "speed_neglected",
        "plyo": "plyo_deficit",
        "strength_lower": "strength_lapsed",
        "strength_upper": "strength_lapsed",
    }
    code = mapping.get(subtype)
    if not code:
        return {}
    raw = _PRESET_DEFAULTS.get(code) or {}
    return copy.deepcopy(raw.get("structure_hints") or {})


def _clamp_tss(v: float) -> int:
    return int(max(0, min(400, round(v))))


def _can_place(occupied: dict[int, str], day: int, *, rest_days: set[int]) -> bool:
    if day in rest_days or day in occupied:
        return False
    # Check consecutive training if we place a training day here
    streak_before = 0
    for d in range(day - 1, -1, -1):
        t = occupied.get(d)
        if t is None or t == "rest":
            break
        streak_before += 1
    streak_after = 0
    for d in range(day + 1, 7):
        t = occupied.get(d)
        if t is None or t == "rest":
            break
        streak_after += 1
    return streak_before + 1 + streak_after <= _MAX_CONSECUTIVE_TRAINING_DAYS


def build_skeleton(
    *,
    week_start: date,
    history: list[tuple[int, str, float, float]],
    preferred_rest_days: list[int] | None = None,
    strength_emphasis: str = "same",
    trailing_28d_weekly_avg_tss: float = 0.0,
    logged_tss_so_far: float = 0.0,
    allowed_offsets: list[int] | None = None,
    load_plan_week: dict | None = None,
    race_anchored_target: float | None = None,
    existing_occupied: set[int] | None = None,
) -> dict[str, Any]:
    """Build 7 deterministic slots. Same inputs ⇒ identical skeleton."""
    rest = set(int(d) for d in (preferred_rest_days or []) if 0 <= int(d) <= 6)
    allowed = set(range(7) if allowed_offsets is None else [int(o) for o in allowed_offsets])
    occupied_existing = set(existing_occupied or [])

    # Open = allowed and not already logged/planned and not preferred rest
    # (rest still get a rest slot; they are not "open" for budget distribution)
    open_for_budget = [
        d for d in range(7)
        if d in allowed and d not in occupied_existing and d not in rest
    ]

    budget = weekly_budget(
        trailing_28d_weekly_avg_tss=trailing_28d_weekly_avg_tss,
        logged_tss_so_far=logged_tss_so_far,
        open_slot_count=max(1, len(open_for_budget)),
        load_plan_week=load_plan_week,
        race_anchored_target=race_anchored_target,
    )
    remaining = float(budget["remaining_tss"])

    # emphasis → strength count
    n_strength = {"less": 1, "same": 2, "more": 3}.get(
        (strength_emphasis or "same").lower(), 2
    )

    slots: list[dict | None] = [None] * 7
    occupied: dict[int, str] = {}  # day → type for consecutive checks

    # Mark existing occupied as locked placeholders (not regenerated)
    for d in occupied_existing:
        if 0 <= d <= 6:
            occupied[d] = "locked"
            slots[d] = {
                "day_offset": d,
                "workout_type": "rest",
                "target_tss": 0,
                "duration_minutes": 0,
                "subtype": "rest",
                "structure_hints": {},
                "locked": True,
                "skip": True,  # already scheduled/logged
            }

    # 1. Preferred rest days first
    for d in sorted(rest):
        if slots[d] is not None:
            continue
        slots[d] = {
            "day_offset": d,
            "workout_type": "rest",
            "target_tss": 0,
            "duration_minutes": 0,
            "subtype": "rest",
            "structure_hints": {},
            "locked": False,
        }
        occupied[d] = "rest"

    # 2. Long run
    long_wd = _long_run_weekday(history)
    if long_wd in rest or long_wd in occupied_existing or long_wd not in allowed:
        # Find nearest open Saturday-preferring day
        candidates = [d for d in (5, 6, 4, 3, 2, 1, 0) if d not in rest and d not in occupied and d in allowed]
        long_wd = candidates[0] if candidates else None

    long_dur_floor, long_tss_floor = _long_run_floors()
    long_tss = 0
    if long_wd is not None and _can_place(occupied, long_wd, rest_days=rest):
        long_tss = _clamp_tss(min(max(long_tss_floor, remaining * 0.35), remaining))
        long_dur = max(long_dur_floor, int(round(long_tss * 1.2 / 5) * 5))  # rough min↔TSS
        long_dur = min(150, long_dur)
        # Clamp floor to budget
        if long_tss > remaining:
            long_tss = _clamp_tss(remaining)
        slots[long_wd] = {
            "day_offset": long_wd,
            "workout_type": "run",
            "target_tss": long_tss,
            "duration_minutes": long_dur,
            "subtype": "long_run",
            "structure_hints": _structure_hints_for("long_run"),
            "locked": False,
        }
        occupied[long_wd] = "run"
        remaining = max(0.0, remaining - long_tss)

        # 3. Day before long = easy-or-rest by construction
        pre = long_wd - 1
        if pre >= 0 and slots[pre] is None and pre in allowed and pre not in rest:
            # Prefer easy run if budget allows; else rest
            if remaining >= 20 and _can_place(occupied, pre, rest_days=rest):
                easy_tss = _clamp_tss(min(35, remaining * 0.15))
                slots[pre] = {
                    "day_offset": pre,
                    "workout_type": "run",
                    "target_tss": easy_tss,
                    "duration_minutes": max(30, int(round(easy_tss * 1.1 / 5) * 5)),
                    "subtype": "easy_run",
                    "structure_hints": _structure_hints_for("easy_run"),
                    "locked": False,
                }
                occupied[pre] = "run"
                remaining = max(0.0, remaining - easy_tss)
            else:
                slots[pre] = {
                    "day_offset": pre,
                    "workout_type": "rest",
                    "target_tss": 0,
                    "duration_minutes": 0,
                    "subtype": "rest",
                    "structure_hints": {},
                    "locked": False,
                }
                occupied[pre] = "rest"

    # 4. Strength slots
    strength_days = _strength_weekdays(history, n_strength)
    rotation = ["strength_lower", "strength_upper"]
    placed_s = 0
    for d in strength_days:
        if placed_s >= n_strength:
            break
        if slots[d] is not None or d not in allowed or d in rest:
            continue
        if not _can_place(occupied, d, rest_days=rest):
            continue
        sub = rotation[placed_s % 2]
        stss = _clamp_tss(min(50, max(25, remaining * 0.12)))
        if stss <= 0 and remaining < 15:
            break
        slots[d] = {
            "day_offset": d,
            "workout_type": "strength",
            "target_tss": stss,
            "duration_minutes": 45,
            "subtype": sub,
            "structure_hints": _structure_hints_for(sub),
            "locked": False,
        }
        occupied[d] = "strength"
        remaining = max(0.0, remaining - stss)
        placed_s += 1

    # Fill missing strength on lightest open days if emphasis wants more
    while placed_s < n_strength:
        candidates = [
            d for d in range(7)
            if slots[d] is None and d in allowed and d not in rest
            and _can_place(occupied, d, rest_days=rest)
        ]
        if not candidates:
            break
        d = candidates[0]
        sub = rotation[placed_s % 2]
        stss = _clamp_tss(min(50, max(20, remaining * 0.12)))
        slots[d] = {
            "day_offset": d,
            "workout_type": "strength",
            "target_tss": stss,
            "duration_minutes": 45,
            "subtype": sub,
            "structure_hints": _structure_hints_for(sub),
            "locked": False,
        }
        occupied[d] = "strength"
        remaining = max(0.0, remaining - stss)
        placed_s += 1

    # 5. Remaining budget → run slots proportional to history medians
    run_meds = _run_medians_by_day(history)
    open_days = [
        d for d in range(7)
        if slots[d] is None and d in allowed and d not in rest
        and _can_place(occupied, d, rest_days=rest)
    ]
    if open_days and remaining > 0:
        weights = []
        for d in open_days:
            if d in run_meds and run_meds[d][0] > 0:
                weights.append(run_meds[d][0])
            else:
                weights.append(40.0)  # default easy weight
        wsum = sum(weights) or 1.0
        allocated = 0
        for i, d in enumerate(open_days):
            if i == len(open_days) - 1:
                tss = _clamp_tss(remaining - allocated)
            else:
                tss = _clamp_tss(remaining * (weights[i] / wsum))
                allocated += tss
            if tss <= 0:
                slots[d] = {
                    "day_offset": d,
                    "workout_type": "rest",
                    "target_tss": 0,
                    "duration_minutes": 0,
                    "subtype": "rest",
                    "structure_hints": {},
                    "locked": False,
                }
                occupied[d] = "rest"
                continue
            med_dur = run_meds.get(d, (0, 45))[1] or 45
            dur = int(round(med_dur / 5.0) * 5) if med_dur else max(30, int(round(tss * 1.1 / 5) * 5))
            # Highest remaining run (non-long) gets tempo if TSS high enough
            subtype = "tempo" if tss >= 60 and d != long_wd else "easy_run"
            slots[d] = {
                "day_offset": d,
                "workout_type": "run",
                "target_tss": tss,
                "duration_minutes": dur,
                "subtype": subtype,
                "structure_hints": _structure_hints_for(subtype),
                "locked": False,
            }
            occupied[d] = "run"

    # Fill any remaining empty days as rest
    for d in range(7):
        if slots[d] is None:
            slots[d] = {
                "day_offset": d,
                "workout_type": "rest",
                "target_tss": 0,
                "duration_minutes": 0,
                "subtype": "rest",
                "structure_hints": {},
                "locked": False,
            }

    # Drop skip markers from output list but keep 7 slots
    out_slots = []
    for s in slots:
        assert s is not None
        clean = {k: v for k, v in s.items() if k != "skip"}
        out_slots.append(clean)

    # Scale training TSS to hit weekly remaining budget (open slots only) ± rounding
    _rescale_open_tss(out_slots, budget["remaining_tss"], occupied_existing | rest)

    return {
        "week_start": week_start.isoformat() if isinstance(week_start, date) else str(week_start),
        "budget": budget,
        "slots": out_slots,
    }


def _rescale_open_tss(slots: list[dict], target_remaining: float, exclude: set[int]) -> None:
    """Proportionally scale non-rest open slots so sum ≈ target_remaining."""
    train = [
        s for s in slots
        if s.get("workout_type") != "rest"
        and not s.get("locked")
        and int(s["day_offset"]) not in exclude
    ]
    if not train:
        return
    cur = sum(float(s.get("target_tss") or 0) for s in train)
    if cur <= 0 or target_remaining <= 0:
        return
    factor = float(target_remaining) / cur
    running = 0
    for i, s in enumerate(train):
        if i == len(train) - 1:
            s["target_tss"] = _clamp_tss(target_remaining - running)
        else:
            newt = _clamp_tss(float(s["target_tss"]) * factor)
            s["target_tss"] = newt
            running += newt


def assemble_week(
    slots: list[dict],
    contents: list[dict | None],
    *,
    facts: dict | None = None,
) -> dict[str, Any]:
    """Merge skeleton pins + per-slot content. Sanity-check week rules once."""
    sessions = []
    for slot, content in zip(slots, contents):
        if slot.get("locked") and slot.get("workout_type") == "rest" and slot.get("skip"):
            continue
        c = content or {}
        sess = {
            "day_offset": slot["day_offset"],
            "workout_type": slot["workout_type"],
            "target_tss": slot["target_tss"],
            "duration_minutes": slot["duration_minutes"],
            "subtype": slot.get("subtype"),
            "intent": c.get("intent") or "",
            "notes": c.get("notes"),
            "blocks": c.get("blocks"),
            "exercises": c.get("exercises"),
            "source": c.get("source") or "template",
            "structure_hints": slot.get("structure_hints") or {},
            "locked": bool(slot.get("locked")),
        }
        if isinstance(c.get("_muscle_footprint"), dict):
            sess["_muscle_footprint"] = c["_muscle_footprint"]
        if c.get("pattern_name"):
            sess["pattern_name"] = c["pattern_name"]
        sessions.append(sess)

    sanity_errors: list[str] = []
    if facts is not None:
        # Map to validation_errors shape
        as_suggestions = [
            {
                "day_offset": s["day_offset"],
                "workout_type": s["workout_type"],
                "target_tss": s["target_tss"],
                "duration_minutes": s["duration_minutes"],
                "intent": s.get("intent") or "",
                "notes": s.get("notes"),
                "blocks": s.get("blocks"),
                "exercises": s.get("exercises"),
            }
            for s in sessions
            if not s.get("locked")
        ]
        try:
            sanity_errors = validation_errors(as_suggestions, facts)
        except Exception as exc:
            sanity_errors = [f"sanity check raised: {exc}"]
        if sanity_errors:
            _log.error(
                "plan_skeleton assemble sanity failure (serving anyway): %s",
                sanity_errors,
            )

    return {
        "sessions": sessions,
        "sanity_errors": sanity_errors,
        "source": "skeleton_v2",
    }


def skeleton_pins_equal(a: dict, b: dict) -> bool:
    """Compare pin fields only (for determinism tests)."""
    keys = ("day_offset", "workout_type", "target_tss", "duration_minutes", "subtype")
    return all(a.get(k) == b.get(k) for k in keys)
