"""Plan pipeline v2 — per-slot content (stage 2) + validator + retry.

The LLM returns content only: intent / blocks|exercises / notes.
Pins (day/type/tss/duration) are stamped from the skeleton slot after validation.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Callable

from backend.services.plan_suggestions import (
    _EASY_RUN_BLOCKS,
    _LOWER_BODY_STRENGTH_EXERCISES,
    _TEMPO_RUN_BLOCKS,
    _UPPER_BODY_STRENGTH_EXERCISES,
    _is_hard_intent,
)
from backend.utils.log import get_logger

_log = get_logger(__name__)

SLOT_PROMPT_VERSION = "2026-07-20.2"

_STRENGTH_BLOCKS = frozenset({
    "Warm-up", "Heavy compound", "Superset 1", "Superset 2", "Standalone", "Accessories",
    # light / maintenance pattern labels (plan_pattern_seeds.groups_light)
    "Bodyweight", "Plyometrics", "Isometrics", "Stretch", "Cooldown",
    # duration-band finishers (plan_pattern_fill format_choices)
    "Finisher", "EMOM", "40/20",
})

_PIN_FIELDS = frozenset({
    "day_offset", "workout_type", "target_tss", "duration_minutes", "subtype", "locked",
})

_MAX_SLOT_TRIES = 2

# UI Suggest subtypes (easy/long/intervals/…) ↔ skeleton subtypes (easy_run/…).
_SUBTYPE_ALIASES: dict[str, str] = {
    "easy": "easy_run",
    "long": "long_run",
    "intervals": "intervals",
    "tempo": "tempo",
    "upper": "strength_upper",
    "lower": "strength_lower",
    "full": "strength_full",
    "light": "strength_light",
    # already-canonical
    "easy_run": "easy_run",
    "long_run": "long_run",
    "strength_upper": "strength_upper",
    "strength_lower": "strength_lower",
    "strength_full": "strength_full",
    "strength_light": "strength_light",
    "rest": "rest",
}

_INTERVAL_RUN_BLOCKS: list[dict] = [
    {"phase": "warmup", "duration_min": 12, "repeat": None, "rest_min": None, "target": "easy"},
    {"phase": "main", "duration_min": 3, "repeat": 6, "rest_min": 2, "target": "hard — interval effort"},
    {"phase": "cooldown", "duration_min": 8, "repeat": None, "rest_min": None, "target": "easy"},
]


def normalize_slot_subtype(workout_type: str | None, subtype: str | None) -> str | None:
    """Map Suggest-UI labels onto skeleton subtype vocabulary."""
    raw = (subtype or "").strip().lower()
    if not raw:
        wt = (workout_type or "").strip().lower()
        if wt == "run":
            return "easy_run"
        if wt == "strength":
            return "strength_lower"
        return wt or None
    return _SUBTYPE_ALIASES.get(raw, raw)


def strip_volunteered_pins(content: dict) -> dict:
    """Remove any pin fields the model volunteered — Python stamps them."""
    if not isinstance(content, dict):
        return {}
    return {k: v for k, v in content.items() if k not in _PIN_FIELDS}


def stamp_session(slot: dict, content: dict) -> dict:
    """Merge content onto slot pins. Pins always win."""
    clean = strip_volunteered_pins(content or {})
    return {
        "day_offset": slot["day_offset"],
        "workout_type": slot["workout_type"],
        "target_tss": slot["target_tss"],
        "duration_minutes": slot["duration_minutes"],
        "subtype": slot.get("subtype"),
        "intent": str(clean.get("intent") or "")[:140],
        "notes": clean.get("notes"),
        "blocks": clean.get("blocks"),
        "exercises": clean.get("exercises"),
        "source": clean.get("source") or "pattern",
        "structure_hints": slot.get("structure_hints") or {},
        "locked": bool(slot.get("locked")),
    }


def _blocks_duration_sum(blocks: list) -> float:
    total = 0.0
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        d = float(b.get("duration_min") or 0)
        rep = int(b.get("repeat") or 1)
        rest = float(b.get("rest_min") or 0)
        total += d * rep + rest * max(0, rep - 1)
    return total


def _duration_within_tolerance(actual: float, pinned: float) -> bool:
    """±10% of pinned, with a minimum ±5 min band."""
    pinned = float(pinned or 0)
    if pinned <= 0:
        return actual <= 5
    tol = max(5.0, pinned * 0.10)
    return abs(actual - pinned) <= tol + 1e-6


def validate_slot(content: dict, slot: dict, week_ctx: dict | None = None) -> list[str]:
    """Per-slot content checks. Empty list == valid."""
    errs: list[str] = []
    week_ctx = week_ctx or {}
    clean = strip_volunteered_pins(content or {})
    wt = str(slot.get("workout_type") or "").lower()
    subtype = normalize_slot_subtype(wt, slot.get("subtype")) or ""
    pinned_dur = float(slot.get("duration_minutes") or 0)
    intent = str(clean.get("intent") or "")

    if len(intent) > 140:
        errs.append(f"intent length {len(intent)} > 140")

    if wt == "rest":
        return errs

    if wt == "run":
        blocks = clean.get("blocks")
        if not blocks or not isinstance(blocks, list):
            errs.append("run slot requires blocks")
        else:
            for b in blocks:
                if not isinstance(b, dict) or not b.get("phase") or b.get("duration_min") is None:
                    errs.append(f"block missing phase/duration_min: {b!r}")
                    break
            phases = {str(b.get("phase") or "").lower() for b in blocks if isinstance(b, dict)}
            if "warmup" not in phases:
                errs.append("run blocks missing warmup phase")
            if "cooldown" not in phases:
                errs.append("run blocks missing cooldown phase")
            total = _blocks_duration_sum(blocks)
            if not _duration_within_tolerance(total, pinned_dur):
                errs.append(
                    f"blocks duration sum {total:.0f} outside ±10% (min ±5) of "
                    f"pinned {pinned_dur:.0f}"
                )
            # easy_run / pre-long-run day: no hard keywords
            is_easy = subtype in ("easy_run", "easy") or bool(slot.get("pre_long_run"))
            if is_easy:
                hard_hit = _is_hard_intent(intent)
                for b in blocks:
                    if isinstance(b, dict) and _is_hard_intent(str(b.get("target") or "")):
                        hard_hit = True
                if hard_hit:
                    errs.append("easy/pre-long-run day must not use hard-intent keywords")

            # intervals / tempo: must actually be quality work (not easy continuous)
            if subtype in ("intervals", "tempo"):
                quality = _is_hard_intent(intent)
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    if _is_hard_intent(str(b.get("target") or "")):
                        quality = True
                    if int(b.get("repeat") or 0) >= 2:
                        quality = True
                if not quality:
                    errs.append(
                        f"{subtype} slot requires hard/interval language or repeated main blocks"
                    )

        if subtype == "long_run" and pinned_dur >= 90:
            hints = slot.get("structure_hints") or {}
            if hints.get("fueling"):
                blob = (intent + " " + json.dumps(clean.get("blocks") or [])).lower()
                if not any(k in blob for k in ("fuel", "gel", "drink", "carb", "nutrition")):
                    errs.append("long_run ≥90 min requires a fueling cue in intent/blocks")

    if wt in ("strength", "plyo"):
        exercises = clean.get("exercises")
        if not exercises or not isinstance(exercises, list):
            errs.append(f"{wt} slot requires exercises")
        else:
            n = len(exercises)
            if n < 4 or n > 12:
                errs.append(f"{wt} needs 4–12 exercises, got {n}")
            for ex in exercises:
                if not isinstance(ex, dict) or not str(ex.get("name") or "").strip():
                    errs.append(f"exercise missing name: {ex!r}")
                    break
                block = str(ex.get("block") or "")
                if wt == "strength" and block and block not in _STRENGTH_BLOCKS:
                    errs.append(
                        f"strength block label {block!r} not in allowed set "
                        f"{sorted(_STRENGTH_BLOCKS)}"
                    )
                    break
            # Emphasis honor (light check): "more" ⇒ ≥6 exercises; "less" ⇒ ≤6
            emphasis = (week_ctx.get("strength_emphasis") or "same").lower()
            if wt == "strength" and emphasis == "more" and n < 6:
                errs.append("strength_emphasis=more expects ≥6 exercises")
            if wt == "strength" and emphasis == "less" and n > 6:
                errs.append("strength_emphasis=less expects ≤6 exercises")

    return errs


def insert_mp_segment(blocks: list[dict], mp_min: int) -> list[dict]:
    """Carve ``mp_min`` from the last non-cooldown block; insert MP before cooldown."""
    mp_min = max(0, int(mp_min))
    if mp_min <= 0 or not blocks:
        return blocks
    out = [dict(b) for b in blocks]
    cooldown_i = next(
        (i for i, b in enumerate(out) if (b.get("phase") or "") == "cooldown"),
        len(out),
    )
    donor_i = cooldown_i - 1 if cooldown_i > 0 else 0
    donor = out[donor_i]
    if donor.get("repeat") and int(donor.get("repeat") or 0) > 1 and donor_i > 0:
        donor_i = donor_i - 1
        donor = out[donor_i]
    donor_mins = int(donor.get("duration_min") or 0)
    take = min(mp_min, max(0, donor_mins - 10))  # leave ≥10 min in donor when possible
    if take <= 0:
        take = min(mp_min, max(1, donor_mins // 2))
    if take <= 0:
        return out
    donor["duration_min"] = max(1, donor_mins - take)
    out.insert(
        cooldown_i,
        {
            "phase": "mp",
            "duration_min": take,
            "repeat": None,
            "rest_min": None,
            "target": "marathon pace (MP)",
        },
    )
    return out


def template_content_for_slot(slot: dict) -> dict:
    """Day template scaled to pins — used when LLM retries are exhausted."""
    wt = str(slot.get("workout_type") or "").lower()
    subtype = normalize_slot_subtype(wt, slot.get("subtype")) or ""
    pinned_dur = int(slot.get("duration_minutes") or 0)

    if wt == "rest":
        return {
            "intent": "Rest day",
            "notes": None,
            "blocks": None,
            "exercises": None,
            "source": "template",
        }

    if wt == "run":
        if subtype == "intervals":
            blocks = [dict(b) for b in _INTERVAL_RUN_BLOCKS]
            intent = "Interval session"
        elif subtype == "tempo":
            blocks = [dict(b) for b in _TEMPO_RUN_BLOCKS]
            intent = "Tempo / quality run"
        else:
            blocks = [dict(b) for b in _EASY_RUN_BLOCKS]
            intent = "Easy aerobic run"
        # Scale durations to pinned (repeat sets keep relative structure)
        base = _blocks_duration_sum(blocks) or 1
        scale = (pinned_dur / base) if pinned_dur else 1.0
        for b in blocks:
            b["duration_min"] = max(1, int(round(float(b["duration_min"]) * scale)))
        notes = None
        if subtype == "long_run" and pinned_dur >= 90:
            intent = "Aerobic long run — fuel mid-run"
            for b in blocks:
                if b.get("phase") == "main":
                    b["target"] = "easy Z2 — gel/drink from minute 40"
        elif subtype == "tempo":
            for b in blocks:
                if b.get("phase") == "main":
                    b["target"] = "tempo — comfortably hard"
        if subtype == "long_run":
            mp_min = int(
                slot.get("mp_segment_min")
                or (slot.get("structure_hints") or {}).get("mp_segment_min")
                or 0
            )
            if mp_min > 0:
                blocks = insert_mp_segment(blocks, mp_min)
                intent = f"Aerobic long run — {mp_min} min MP before cooldown"
                notes = f"Finish with {mp_min} min at marathon pace before cooldown."
        return {
            "intent": intent[:140],
            "notes": notes,
            "blocks": blocks,
            "exercises": None,
            "source": "template",
        }

    if wt == "plyo":
        exercises = [
            {"block": "Warm-up", "name": "Bodyweight squat", "sets": 2, "reps": "10",
             "load": "easy pace"},
            {"block": "Plyometrics", "name": "Pogo jumps", "sets": 3, "reps": "20",
             "load": "bodyweight — soft landings"},
            {"block": "Plyometrics", "name": "Squat jump", "sets": 3, "reps": "8",
             "load": "bodyweight — soft landings"},
            {"block": "Plyometrics", "name": "Low box step-off", "sets": 2, "reps": "6/side",
             "load": "bodyweight — stick the landing"},
        ]
        return {
            "intent": "Short plyometric session",
            "notes": "Keep contacts crisp; stop short of fatigue.",
            "blocks": None,
            "exercises": exercises,
            "source": "template",
        }

    if wt == "strength":
        if subtype == "strength_light":
            exercises = [
                {"block": "Bodyweight", "name": "Bodyweight squat", "sets": 2, "reps": "15",
                 "load": "bodyweight, easy pace"},
                {"block": "Bodyweight", "name": "Push-up", "sets": 2, "reps": "10",
                 "load": "bodyweight or knees"},
                {"block": "Isometrics", "name": "Plank", "sets": 2, "reps": "30s hold",
                 "load": "bodyweight"},
                {"block": "Stretch", "name": "World's greatest stretch", "sets": 1, "reps": "5/side",
                 "load": "mobility"},
            ]
            intent = "Light strength / maintenance"
        elif subtype == "strength_upper":
            exercises = [dict(e) for e in _UPPER_BODY_STRENGTH_EXERCISES]
            intent = "Upper body strength"
        else:
            exercises = [dict(e) for e in _LOWER_BODY_STRENGTH_EXERCISES]
            intent = "Lower body strength"
        # Trim to validator max
        if len(exercises) > 12:
            exercises = exercises[:12]
        return {
            "intent": intent[:140],
            "notes": None,
            "blocks": None,
            "exercises": exercises,
            "source": "template",
        }

    return {
        "intent": (subtype or wt or "Session")[:140],
        "notes": None,
        "blocks": None,
        "exercises": None,
        "source": "template",
    }


def build_slot_prompt(
    week_ctx: dict,
    slot: dict,
    *,
    instruction: str | None = None,
    current: dict | None = None,
) -> tuple[str, str]:
    """(system, user) for one slot. Pins are in context but output must omit them."""
    skeleton = week_ctx.get("skeleton_slots") or []
    skeleton_summary = [
        {
            "day_offset": s.get("day_offset"),
            "workout_type": s.get("workout_type"),
            "target_tss": s.get("target_tss"),
            "duration_minutes": s.get("duration_minutes"),
            "subtype": s.get("subtype"),
        }
        for s in skeleton
    ]
    system = (
        f"SLOT_PROMPT_VERSION={SLOT_PROMPT_VERSION}\n"
        "You fill CONTENT for ONE training session slot. Return ONLY JSON:\n"
        '{"intent": "≤140 char title", "blocks": [...] | null, '
        '"exercises": [...] | null, "notes": string|null}\n'
        "Do NOT include day_offset, workout_type, target_tss, or duration_minutes — "
        "those are fixed by the schedule and stamped in Python.\n"
        "RULES:\n"
        "- run: blocks with warmup + main + cooldown; durations sum to the pinned duration (±10%).\n"
        "- subtype is BINDING — match it exactly:\n"
        "  · easy / easy_run: conversational easy only — no interval/tempo/threshold language.\n"
        "  · intervals: repeated hard efforts with jog recoveries (use main.repeat + rest_min;\n"
        "    put the prescription in main.target, e.g. \"6×3min hard, 2min jog\").\n"
        "  · tempo: sustained comfortably-hard / threshold blocks (not easy continuous).\n"
        "  · long / long_run: steady aerobic; if ≥90 min include a fueling cue.\n"
        "- strength/plyo: 4–12 named exercises; strength blocks ⊆ "
        "{Warm-up, Heavy compound, Superset 1, Superset 2, Standalone, Accessories, "
        "Finisher, EMOM, 40/20, Bodyweight, Plyometrics, Isometrics, Stretch}.\n"
        "- intent ≤ 140 characters; title should reflect the subtype "
        "(e.g. \"6x3min intervals\", not \"Easy aerobic run\" for an intervals slot).\n"
    )
    user = {
        "load": week_ctx.get("load"),
        "prefs": {
            "strength_emphasis": week_ctx.get("strength_emphasis"),
            "notes": week_ctx.get("notes"),
        },
        "skeleton_pins": skeleton_summary,
        "this_slot_pins": {
            "day_offset": slot.get("day_offset"),
            "workout_type": slot.get("workout_type"),
            "target_tss": slot.get("target_tss"),
            "duration_minutes": slot.get("duration_minutes"),
            "subtype": slot.get("subtype"),
            "structure_hints": slot.get("structure_hints"),
        },
        "existing_week": week_ctx.get("existing_week"),
        "recent_exercise_names": week_ctx.get("recent_exercise_names"),
        "instruction": instruction,
        "current_content": strip_volunteered_pins(current) if current else None,
    }
    return system, json.dumps(user, default=str)


def generate_slot_content(
    week_ctx: dict,
    slot: dict,
    *,
    instruction: str | None = None,
    current: dict | None = None,
    llm_call: Callable[[str, str], dict | None] | None = None,
    max_tries: int = _MAX_SLOT_TRIES,
    db=None,
    avoid_parts: set | None = None,
) -> dict:
    """Fill one slot from DB patterns (no LLM).

    `llm_call` / `instruction` / `max_tries` are retained for call-site
    compatibility but ignored — planning LLM is removed.
    """
    del instruction, llm_call, max_tries  # unused — no planning LLM
    from backend.services.plan_pattern_fill import fill_slot

    return fill_slot(
        slot,
        db=db,
        week_ctx=week_ctx,
        current=current,
        avoid_parts=avoid_parts,
    )


def build_week_ctx(
    *,
    facts: dict,
    skeleton_slots: list[dict],
    strength_emphasis: str = "same",
    notes: str = "",
) -> dict:
    """Shared context identical across a week's slot calls (no other content)."""
    return {
        "load": {
            "ctl": facts.get("ctl"),
            "atl": facts.get("atl"),
            "tsb": facts.get("tsb"),
            "trailing_28d_weekly_avg_tss": facts.get("trailing_28d_weekly_avg_tss"),
            "days_to_next_race": facts.get("days_to_next_race"),
            "phase": facts.get("phase"),
            "taper_state": facts.get("phase") == "taper",
        },
        "strength_emphasis": strength_emphasis,
        "notes": notes,
        "skeleton_slots": [
            {
                "day_offset": s["day_offset"],
                "workout_type": s["workout_type"],
                "target_tss": s["target_tss"],
                "duration_minutes": s["duration_minutes"],
                "subtype": s.get("subtype"),
            }
            for s in skeleton_slots
        ],
        "existing_week": facts.get("existing_week"),
        "recent_exercise_names": facts.get("recent_exercise_names") or [],
    }


def fill_week_slots(
    week_ctx: dict,
    slots: list[dict],
    *,
    llm_call: Callable[[str, str], dict | None] | None = None,
    existing_contents: list[dict | None] | None = None,
) -> list[dict]:
    """Generate content for every slot (independent / parallel-safe)."""
    existing_contents = existing_contents or [None] * len(slots)
    out = []
    for slot, cur in zip(slots, existing_contents):
        # Mark pre-long-run day for validator
        slot = dict(slot)
        long = next((s for s in slots if s.get("subtype") == "long_run"), None)
        if long and int(slot["day_offset"]) == int(long["day_offset"]) - 1:
            slot["pre_long_run"] = True
        out.append(generate_slot_content(week_ctx, slot, current=cur, llm_call=llm_call))
    return out
