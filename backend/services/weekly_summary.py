"""Weekly summary narrative service (issue #1314).

Exposes:
  assemble_facts(...)           — pure function: weekly metrics from pre-fetched data
  build_fallback_narrative(...) — pure function: deterministic text from facts
  numeral_guard_passes(...)     — validate LLM numbers against facts string
  build_signature(...)          — cache key for llm_generations
  get_narrative(...)            — LLM (DEEP tier) + cache wrapper, fallback-safe
  build_response(...)           — final response shape
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

import backend.services.llm as llm
from backend.utils.log import get_logger

_log = get_logger(__name__)

_MAX_NARRATIVE_LEN = 800

_NARRATIVE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
    },
    "required": ["narrative"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Facts assembler — pure function
# ---------------------------------------------------------------------------

def assemble_facts(
    week_start: date,
    current_workouts: list[dict],
    prev_workouts: list[dict],
    ctl_start: float,
    ctl_end: float,
    atl_start: float,
    atl_end: float,
    tsb_start: float,
    tsb_end: float,
    guardrail: dict,
    prs: list[dict],
) -> dict:
    """Assemble weekly summary facts from pre-fetched data.

    Pure function — no database access, no network calls.
    All raw data is passed in by the endpoint caller.
    """
    def _sum_attr(workouts, attr, cast=float):
        vals = [cast(w[attr]) for w in workouts if w.get(attr) is not None]
        return round(sum(vals), 3) if vals else None

    total_tss = _sum_attr(current_workouts, "tss")
    prev_tss = _sum_attr(prev_workouts, "tss")

    total_dist = _sum_attr(current_workouts, "distance_km")
    prev_dist = _sum_attr(prev_workouts, "distance_km")

    dur_sec = _sum_attr(current_workouts, "duration_seconds", int)
    total_dur_min = round(dur_sec / 60.0, 1) if dur_sec is not None else None

    by_type: dict[str, int] = {}
    for w in current_workouts:
        wt = (w.get("workout_type") or "").lower().strip()
        if wt:
            by_type[wt] = by_type.get(wt, 0) + 1

    return {
        "week_start": week_start.isoformat(),
        "workout_count": len(current_workouts),
        "workout_count_by_type": by_type,
        "total_tss": total_tss,
        "prev_week_tss": prev_tss,
        "total_distance_km": total_dist,
        "prev_week_distance_km": prev_dist,
        "total_duration_minutes": total_dur_min,
        "ctl_start": ctl_start,
        "ctl_end": ctl_end,
        "atl_start": atl_start,
        "atl_end": atl_end,
        "tsb_start": tsb_start,
        "tsb_end": tsb_end,
        "guardrail_state": guardrail.get("guardrail_state", "ok"),
        "guardrail_message": guardrail.get("guardrail_message", ""),
        "acwr": guardrail.get("acwr"),
        "prs_achieved": prs,
    }


# ---------------------------------------------------------------------------
# Fallback narrative — pure function
# ---------------------------------------------------------------------------

def build_fallback_narrative(facts: dict) -> str:
    """Build a deterministic coach-style bullet summary from facts.

    Pure function — no I/O.
    """
    count = facts.get("workout_count", 0)
    if not count:
        return (
            "No training logged this week. Rest is part of the plan — "
            "come back strong next week."
        )

    lines = []

    # Workout summary
    tss = facts.get("total_tss")
    dist = facts.get("total_distance_km")
    dur = facts.get("total_duration_minutes")

    by_type = facts.get("workout_count_by_type") or {}
    type_str = ", ".join(
        f"{v} {k}" for k, v in sorted(by_type.items()) if v > 0
    )
    base = f"{count} session{'s' if count != 1 else ''}"
    if type_str:
        base += f" ({type_str})"
    if tss is not None:
        base += f" — {tss:.0f} TSS"
    if dist is not None:
        base += f", {dist:.1f} km"
    if dur is not None:
        base += f", {dur:.0f} min"
    lines.append(base + ".")

    # TSS vs prior week
    prev_tss = facts.get("prev_week_tss")
    if tss is not None and prev_tss is not None:
        delta = tss - prev_tss
        direction = "up" if delta > 0 else "down"
        lines.append(f"Load {direction} {abs(delta):.0f} TSS vs last week ({prev_tss:.0f}).")

    # CTL trend
    ctl_start = facts.get("ctl_start")
    ctl_end = facts.get("ctl_end")
    if ctl_start is not None and ctl_end is not None:
        ctl_dir = "▲" if ctl_end > ctl_start else "▼" if ctl_end < ctl_start else "→"
        lines.append(
            f"Fitness (CTL): {ctl_start:.1f} → {ctl_end:.1f} {ctl_dir}. "
            f"Form (TSB): {facts.get('tsb_end', 0):.1f}."
        )

    # PRs
    prs = facts.get("prs_achieved") or []
    if prs:
        pr_names = ", ".join(p.get("track_name", "PR") for p in prs[:3])
        lines.append(f"PR{'s' if len(prs) > 1 else ''} this week: {pr_names}.")

    # Guardrail
    if facts.get("guardrail_state") == "warn":
        msg = facts.get("guardrail_message", "")
        if msg:
            lines.append(f"⚠ Load warning: {msg}")
        else:
            lines.append("⚠ Load warning: consider easing off this week.")

    return " ".join(lines)


# ---------------------------------------------------------------------------
# Numeral guard
# ---------------------------------------------------------------------------

def numeral_guard_passes(text: str, facts_str: str) -> bool:
    """Return True iff every number in text appears verbatim in facts_str."""
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    for n in nums:
        if n not in facts_str:
            return False
    return True


# ---------------------------------------------------------------------------
# Cache signature
# ---------------------------------------------------------------------------

def build_signature(user_id: str, week_start: str, facts: dict) -> str:
    canonical = json.dumps(
        {"user": user_id, "week": week_start, "facts": facts},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:64]


# ---------------------------------------------------------------------------
# Facts → string for numeral validation
# ---------------------------------------------------------------------------

def _facts_to_str(facts: dict) -> str:
    parts = []
    for k, v in facts.items():
        if v is None or isinstance(v, (list, dict)):
            continue
        parts.append(f"{k}={v}")
    # Also include PR names in facts_str so guard doesn't flag them
    for pr in facts.get("prs_achieved") or []:
        parts.append(str(pr.get("value_numeric", "")))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# LLM + cache wrapper
# ---------------------------------------------------------------------------

def get_narrative(
    user_id: str,
    week_start: str,
    facts: dict,
    *,
    db=None,
) -> tuple[str, str]:
    """Return (narrative, source) where source is 'llm' or 'fallback'.

    Uses GROQ_MODEL_DEEP tier and caches in llm_generations.
    """
    fallback = build_fallback_narrative(facts)

    if not llm.llm_enabled():
        return fallback, "fallback"

    facts_str = _facts_to_str(facts)
    sig = build_signature(user_id, week_start, facts)

    system = (
        "You are a performance coach writing a brief weekly training report. "
        "Rules: 2-4 sentences max, use ONLY the numbers given in the data, "
        "no medical advice, no injury warnings unless explicitly flagged in the data, "
        "no emoji, supportive and direct coach tone."
    )

    count = facts.get("workout_count", 0)
    if count == 0:
        user_prompt = (
            "Write a brief, honest 1-2 sentence weekly summary. "
            "The athlete logged zero workouts this week — acknowledge it honestly and supportively.\n"
            f"Data: {facts_str}\n"
            'Return JSON: {"narrative": "..."}'
        )
    else:
        user_prompt = (
            "Write a 2-4 sentence coach-style weekly training summary. "
            "Cover: what the week looked like, load trend vs last week, "
            "fitness/form direction, any PRs or flags. "
            "Use only the numbers in the data.\n"
            f"Data: {facts_str}\n"
            'Return JSON: {"narrative": "..."}'
        )

    def _generate():
        return llm.complete_structured(
            system=system,
            user=user_prompt,
            schema_name="weekly_summary",
            json_schema=_NARRATIVE_JSON_SCHEMA,
            model_tier="deep",
        )

    result = llm.get_or_generate(
        user_id=user_id,
        surface="weekly_summary",
        signature=sig,
        generate_fn=_generate,
        db=db,
    )

    if result is None:
        return fallback, "fallback"

    text = result.get("narrative", "")
    if not text:
        return fallback, "fallback"

    if len(text) > _MAX_NARRATIVE_LEN:
        _log.warning("weekly_summary: narrative too long, using fallback")
        return fallback, "fallback"

    if not numeral_guard_passes(text, facts_str):
        _log.warning("weekly_summary: numeral guard failed, using fallback")
        return fallback, "fallback"

    return text, "llm"


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

def build_response(
    week_start: str,
    facts: dict,
    narrative: str,
    source: str,
) -> dict:
    return {
        "week_start": week_start,
        "facts": facts,
        "narrative": narrative,
        "source": source,
    }
