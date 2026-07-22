"""Per-slot LLM cache keys for plan pipeline v2 (surface: plan_slot).

Raw CTL/ATL/TSB/trailing are deliberately excluded — load reaches a slot only
through its pins. A CTL nudge with unchanged pins regenerates nothing.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.services.plan_slot import SLOT_PROMPT_VERSION

SURFACE = "plan_slot"


def _tss_rounded_to_5(tss) -> int:
    try:
        return int(round(float(tss) / 5.0) * 5)
    except (TypeError, ValueError):
        return 0


def slot_cache_key(
    *,
    pins: dict,
    content_ctx: dict,
) -> str:
    """sha256(SLOT_PROMPT_VERSION, pins, content_ctx) — stable key order."""
    payload = {
        "prompt_version": SLOT_PROMPT_VERSION,
        "pins": {
            "day": pins.get("day_offset"),
            "type": pins.get("workout_type"),
            "tss": _tss_rounded_to_5(pins.get("target_tss")),
            "dur": int(pins.get("duration_minutes") or 0),
            "subtype": pins.get("subtype"),
            "hints": pins.get("structure_hints") or {},
        },
        "content_ctx": {
            "emphasis": content_ctx.get("emphasis") or content_ctx.get("strength_emphasis") or "same",
            "taper_state": bool(content_ctx.get("taper_state")),
            "notes": (content_ctx.get("notes") or "")[:300],
            "recent_exercise_names": list(content_ctx.get("recent_exercise_names") or []),
            "race_bucket": content_ctx.get("race_bucket"),
        },
    }
    serialised = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


def race_bucket(days_to_race: int | None) -> str | None:
    if days_to_race is None:
        return None
    d = int(days_to_race)
    if d < 0:
        return None
    if d <= 7:
        return "race_week"
    if d <= 21:
        return "taper"
    if d <= 56:
        return "build"
    return "base"


def content_ctx_from_week(week_ctx: dict) -> dict:
    load = week_ctx.get("load") or {}
    return {
        "emphasis": week_ctx.get("strength_emphasis") or "same",
        "taper_state": bool(load.get("taper_state") or load.get("phase") == "taper"),
        "notes": week_ctx.get("notes") or "",
        "recent_exercise_names": list(week_ctx.get("recent_exercise_names") or []),
        "race_bucket": race_bucket(load.get("days_to_next_race")),
    }
