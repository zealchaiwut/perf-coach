"""Mobility sessions — pattern pick, fill, validate (WC-11 / WC-12)."""
from __future__ import annotations

from typing import Any

_QUALITY_RUN_SUBTYPES = frozenset({"tempo", "intervals", "quality", "threshold"})


def _is_quality_run(slot: dict) -> bool:
    if (slot.get("workout_type") or "") != "run":
        return False
    sub = str(slot.get("subtype") or "").lower()
    if sub in _QUALITY_RUN_SUBTYPES:
        return True
    hints = slot.get("structure_hints") or {}
    return bool(hints.get("quality"))


def _next_day_slot(slots: list[dict], day: int) -> dict | None:
    nxt = day + 1
    if nxt > 6:
        return None
    for s in slots:
        if int(s.get("day_offset", -1)) == nxt and not s.get("is_mobility"):
            return s
    return None


def mobility_subtype_for_day(primary_slot: dict, all_slots: list[dict], day: int) -> str:
    """Pick mobility pattern subtype from the day's primary session (WC-11 rules)."""
    wt = (primary_slot.get("workout_type") or "").lower()
    sub = str(primary_slot.get("subtype") or "").lower()

    if wt == "strength" or wt == "plyo":
        return "stretch_core"
    if sub == "long_run" or primary_slot.get("race_day"):
        return "stretch_light"
    if wt == "rest":
        nxt = _next_day_slot(all_slots, day)
        if nxt and (
            nxt.get("subtype") == "long_run"
            or nxt.get("race_day")
            or (nxt.get("workout_type") or "") == "run" and "race" in sub
        ):
            return "yin"
        return "stretch_light"
    if _is_quality_run(primary_slot):
        return "stretch_posterior"
    if wt == "run":
        if day == 0:
            return "stretch_hips"
        if day == 2:
            return "stretch_upper"
        return "stretch_hips"
    return "stretch_core"


def attach_mobility_slots(slots: list[dict], stretch_daily_min: int) -> list[dict]:
    """Add one mobility slot per calendar day (replaces daily_extras stretch)."""
    if not stretch_daily_min or stretch_daily_min <= 0:
        return slots
    primary = [
        s for s in slots
        if not s.get("is_mobility") and (s.get("workout_type") or "") != "mobility"
    ]
    by_day = {int(s["day_offset"]): s for s in primary}
    mobility: list[dict] = []
    for day in range(7):
        anchor = by_day.get(day) or {
            "day_offset": day,
            "workout_type": "rest",
            "subtype": "rest",
        }
        subtype = mobility_subtype_for_day(anchor, primary, day)
        mobility.append({
            "day_offset": day,
            "workout_type": "mobility",
            "subtype": subtype,
            "target_tss": 0,
            "duration_minutes": int(stretch_daily_min),
            "intent": "",
            "notes": None,
            "exercises": None,
            "blocks": None,
            "source": "prefs.stretch_daily_min",
            "is_mobility": True,
        })
    return list(slots) + mobility


def validate_mobility_content(
    content: dict,
    *,
    pattern: dict | None,
    pool: list[dict],
    prior_quality_day: bool = False,
) -> list[str]:
    """Validator: stretch-group exercises, duration band, no PNF after quality."""
    errors: list[str] = []
    exercises = content.get("exercises") or []
    stretch_names = {
        (e.get("name") or "").lower()
        for e in pool
        if "stretch" in (e.get("groups") or [])
    }
    for ex in exercises:
        name = (ex.get("name") or "").lower()
        if name and stretch_names and name not in stretch_names:
            errors.append(f"exercise not in stretch pool: {ex.get('name')}")
        if prior_quality_day and ex.get("pnf"):
            errors.append(f"PNF not allowed after quality day: {ex.get('name')}")

    if pattern:
        lo = int(pattern.get("duration_min_lo") or 0)
        hi = int(pattern.get("duration_min_hi") or 999)
        dur = int(content.get("duration_minutes") or 0)
        if dur and (dur < lo or dur > hi):
            errors.append(f"duration {dur} outside band {lo}-{hi}")
        recipe = pattern.get("recipe") or {}
        if prior_quality_day and recipe.get("pnf_allowed") is False:
            for ex in exercises:
                if ex.get("pnf"):
                    errors.append("pattern disallows PNF after quality")
                    break
    return errors


def quality_day_before_map(slots: list[dict]) -> dict[int, bool]:
    """For each day offset, True when the prior day was a quality run."""
    primary = {
        int(s["day_offset"]): s
        for s in slots
        if not s.get("is_mobility") and (s.get("workout_type") or "") != "mobility"
    }
    out: dict[int, bool] = {}
    for day in range(1, 7):
        prev = primary.get(day - 1)
        if prev and _is_quality_run(prev):
            out[day] = True
    return out


def maybe_refine_mobility(content: dict, *, pool: list[dict], pattern: dict | None) -> dict:
    """Optional LLM refine hook — deterministic only today; returns content unchanged
    unless a future refine path passes library-only validation."""
    _ = (pool, pattern)
    return content
