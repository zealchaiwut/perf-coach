"""Training plan suggestion service (issue #1315).

Exposes:
  KNOWN_WORKOUT_TYPES         — set of valid session types (mirrors PlannedSession)
  ACWR_HIGH_BOUND             — max safe ACWR ratio (from acwr.py HIGH_BOUND)
  FALLBACK_MIN_WEEKLY_TSS     — floor for fallback weekly target when base is near-zero
  validate_suggestions(...)   — pure function: True iff LLM output passes all rules
  fallback_suggestions(...)   — pure function: template week from trailing load + ramp cap
  build_prompt(...)           — (system, user) strings for LLM
  build_signature(...)        — sha256 signature over facts dict
  get_suggestions_from_facts(...)  — LLM (DEEP tier) + validation + fallback, no DB
  assemble_facts(...)         — DB caller: builds the facts dict for a user
  get_suggestions(...)        — full entry point: assemble → cache → LLM/fallback
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from typing import Any

import backend.services.llm as llm_svc
from backend.utils.log import get_logger

_log = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

KNOWN_WORKOUT_TYPES: frozenset[str] = frozenset({"run", "strength", "plyo", "stretch", "rest"})

# Mirror of acwr.HIGH_BOUND — weekly TSS must not exceed trailing_avg × this.
ACWR_HIGH_BOUND: float = 1.3

# When trailing 28-day avg is very low, still allow a minimal template week.
FALLBACK_MIN_WEEKLY_TSS: float = 80.0

# Per-session TSS bounds (sane range: rest=0, hard session ≤ 400).
_MAX_SESSION_TSS: int = 400
_MIN_SESSION_TSS: int = 0

# Conservative ramp factor for fallback when no race-anchored target exists.
# Taper is owned solely by load_plan.TAPER_CURVE — do NOT re-derive here.
_FALLBACK_RAMP_FACTOR: float = 1.10

# Suggestions should aim near the week's remaining TSS target, but ACWR /
# ceiling is the hard guardrail — don't reject plans that miss the target by
# a modest amount (athletes often already have sessions on the week).
_TARGET_BAND_FRACTION: float = 0.15

_SURFACE = "plan_suggestion"


def _target_aware_enabled() -> bool:
    """Off by default (Plan tab revamp, Part 3) — with this unset, assemble_facts,
    build_prompt, and validation_errors are byte-identical to pre-Part-3 behaviour.
    Mirrors the on/off convention in backend/services/llm.py's LLM_COACH_ENABLED."""
    return os.getenv("PLAN_TARGET_AWARE_ENABLED", "").strip().lower() in ("1", "true", "yes")

# Bumped whenever build_prompt() or _LLM_JSON_SCHEMA changes meaningfully.
# Folded into build_signature() below so an edited prompt can never silently
# serve an LlmGeneration row cached from the OLD prompt — the cache key is
# only the `facts` dict, and identical facts (same notes/rest-days/emphasis)
# hash identically across a prompt change. Hit exactly this in production:
# a fix to build_prompt() had no visible effect because the athlete's retry
# used unchanged facts and kept matching a pre-fix cached row.
_PROMPT_VERSION = "2026-07-09.8"

# ── Scoping / rules constants (day-offset semantics: 0=Monday .. 6=Sunday of
# the target week; facts["week_start"] is that Monday's ISO date) ────────────

_VALID_STRENGTH_EMPHASIS: frozenset[str] = frozenset({"less", "same", "more"})

# Heuristic for "this looks like a hard/interval effort" when an intent string
# has no other structure to check — used only for the pre-long-run-day rule.
_HARD_INTENT_KEYWORDS: tuple[str, ...] = (
    "interval", "tempo", "threshold", "repeat", "track", "speed work", "vo2",
)

# A run's target_tss at or above this fraction of the week's long-run TSS
# counts as "hard" for the pre-long-run-day rule, even without a keyword hit.
_HARD_RUN_TSS_FRACTION_OF_LONG_RUN: float = 0.70

# Longest allowed streak of consecutive non-rest days before a rest/easy day
# is required (keeps the week from stacking training on top of training).
_MAX_CONSECUTIVE_TRAINING_DAYS: int = 3

# Generic detailed strength templates — block-grouped exercises (block, name,
# sets, reps, load), the same shape PlannedSession.structure.exercises stores
# and the manual Add-session form builder produces. `reps`/`load` are short
# descriptive strings (not always numeric — "30s hold", "bodyweight") since
# structure is freeform JSONB with no server-side exercise schema. Feeds
# fallback_suggestions() so an offline/no-LLM week still gets real sessions,
# not a bare one-line intent the athlete has to build out by hand.
# Six sub-sections within 60-90 min — Warm-up, Heavy compound (1 primary
# lift), Superset 1 / Superset 2 (2 exercises each, paired opposing muscle
# groups so they alternate), Standalone (1 isolation move), Accessories
# (core/stability/stretch) — matching how the athlete actually programs a
# session, not a flat 3-block placeholder.
_LOWER_BODY_STRENGTH_EXERCISES: list[dict] = [
    {"block": "Warm-up", "name": "Bodyweight squat", "sets": 2, "reps": "15", "load": "bodyweight, warm-up pace"},
    {"block": "Warm-up", "name": "Spiderman lunge w/ rotation", "sets": 1, "reps": "8", "load": "bodyweight, per side"},
    {"block": "Warm-up", "name": "Lateral band walk", "sets": 2, "reps": "15", "load": "light band, per side"},
    {"block": "Heavy compound", "name": "Back squat", "sets": 4, "reps": "8", "load": "moderate — not a 1RM-testing weight"},
    {"block": "Superset 1", "name": "Romanian deadlift", "sets": 3, "reps": "10", "load": "moderate dumbbells"},
    {"block": "Superset 1", "name": "Dumbbell overhead press", "sets": 3, "reps": "10", "load": "moderate — upper push"},
    {"block": "Superset 2", "name": "Walking lunge", "sets": 3, "reps": "10", "load": "bodyweight or light dumbbells, per leg"},
    {"block": "Superset 2", "name": "Dumbbell bent-over row", "sets": 3, "reps": "10", "load": "moderate — upper pull"},
    {"block": "Standalone", "name": "Hip thrust", "sets": 3, "reps": "10", "load": "moderate, 2s pause at top"},
    {"block": "Accessories", "name": "Plank", "sets": 3, "reps": "40s hold", "load": "bodyweight"},
    {"block": "Accessories", "name": "Side plank", "sets": 2, "reps": "25-30s hold", "load": "bodyweight, per side"},
]
_UPPER_BODY_STRENGTH_EXERCISES: list[dict] = [
    {"block": "Warm-up", "name": "Arm circles + band pull-apart", "sets": 1, "reps": "15", "load": "light band"},
    {"block": "Warm-up", "name": "Scapular push-up", "sets": 2, "reps": "10", "load": "bodyweight"},
    {"block": "Heavy compound", "name": "Dumbbell bench press", "sets": 4, "reps": "8", "load": "moderate"},
    {"block": "Superset 1", "name": "Dumbbell overhead press", "sets": 3, "reps": "10", "load": "moderate — upper push"},
    {"block": "Superset 1", "name": "Goblet squat", "sets": 3, "reps": "10", "load": "moderate — lower complement"},
    {"block": "Superset 2", "name": "Dumbbell bent-over row", "sets": 3, "reps": "10", "load": "moderate — upper pull"},
    {"block": "Superset 2", "name": "Romanian deadlift", "sets": 3, "reps": "10", "load": "moderate — lower complement"},
    {"block": "Standalone", "name": "Farmer's carry", "sets": 3, "reps": "30m", "load": "moderate dumbbells"},
    {"block": "Accessories", "name": "Dead bug", "sets": 3, "reps": "10", "load": "bodyweight, per side"},
    {"block": "Accessories", "name": "Bird dog", "sets": 3, "reps": "10", "load": "bodyweight, per side"},
]

# Run block templates — phase-structured (warmup / main / cooldown), the same
# shape PlannedSession.structure.blocks + the "Copy for Stryd Workout Builder"
# export already expect (see _runDetailHtml / _strydText in training-plan.js).
# `repeat`/`rest_min`/`target` are None outside a repeated main set.
_EASY_RUN_BLOCKS: list[dict] = [
    {"phase": "warmup", "duration_min": 8, "repeat": None, "rest_min": None, "target": "easy"},
    {"phase": "main", "duration_min": 30, "repeat": None, "rest_min": None, "target": "easy, conversational"},
    {"phase": "cooldown", "duration_min": 5, "repeat": None, "rest_min": None, "target": "easy"},
]
_TEMPO_RUN_BLOCKS: list[dict] = [
    {"phase": "warmup", "duration_min": 10, "repeat": None, "rest_min": None, "target": "easy"},
    {"phase": "main", "duration_min": 10, "repeat": 3, "rest_min": 2, "target": "tempo — comfortably hard"},
    {"phase": "cooldown", "duration_min": 8, "repeat": None, "rest_min": None, "target": "easy"},
]
# Default template: day_offset → (workout_type, tss_fraction_of_weekly, duration_min)
# Fractions sum to 1.0 (excluding rest days at 0). `exercises` is for
# strength/plyo, `blocks` for run — never both.
_TEMPLATE: list[dict] = [
    {"day_offset": 0, "workout_type": "run",      "tss_fraction": 0.20, "duration_base": 45, "intent": "Easy aerobic run — keep effort conversational.", "exercises": None, "blocks": _EASY_RUN_BLOCKS},
    {"day_offset": 1, "workout_type": "strength",  "tss_fraction": 0.15, "duration_base": 45, "intent": "Lower body strength — squats, lunges, hip work.", "exercises": _LOWER_BODY_STRENGTH_EXERCISES, "blocks": None},
    {"day_offset": 2, "workout_type": "run",       "tss_fraction": 0.25, "duration_base": 60, "intent": "Moderate-effort run or tempo intervals.", "exercises": None, "blocks": _TEMPO_RUN_BLOCKS},
    {"day_offset": 3, "workout_type": "rest",      "tss_fraction": 0.00, "duration_base": 0,  "intent": "Rest or light stretching.", "exercises": None, "blocks": None},
    {"day_offset": 4, "workout_type": "run",       "tss_fraction": 0.20, "duration_base": 50, "intent": "Easy aerobic run — maintain base fitness.", "exercises": None, "blocks": _EASY_RUN_BLOCKS},
    {"day_offset": 5, "workout_type": "strength",  "tss_fraction": 0.20, "duration_base": 45, "intent": "Upper body and core strength.", "exercises": _UPPER_BODY_STRENGTH_EXERCISES, "blocks": None},
    {"day_offset": 6, "workout_type": "run",       "tss_fraction": 0.00, "duration_base": 30, "intent": "Optional very easy jog or full rest.", "exercises": None, "blocks": _EASY_RUN_BLOCKS},
]


# ── Pure functions ────────────────────────────────────────────────────────────

def _allowed_offsets(facts: dict) -> list[int]:
    """day_offsets suggestions may occupy. Defaults to the full week (0..6) when
    facts carries no `allowed_offsets` key — preserves prior behaviour for any
    caller (or test) that built a facts dict before this key existed."""
    offs = facts.get("allowed_offsets")
    if offs is None:
        return list(range(7))
    return [int(o) for o in offs]


def _preferred_rest_days(facts: dict) -> list[int]:
    days = facts.get("preferred_rest_days") or []
    return [int(d) for d in days]


def _is_hard_intent(intent: str) -> bool:
    text = (intent or "").lower()
    return any(kw in text for kw in _HARD_INTENT_KEYWORDS)


def _find_long_run(suggestions: list[dict]) -> dict | None:
    """The 'run' session with the highest target_tss — the week's long run, used
    as the anchor for the pre-long-run-day rule. None if there's no run session
    or fewer than 2 runs (nothing to sequence relative to)."""
    runs = [s for s in suggestions if str(s.get("workout_type", "")).lower() == "run"]
    if len(runs) < 2:
        return None
    return max(runs, key=lambda s: float(s.get("target_tss") or 0.0))


def validation_errors(suggestions: list[dict], facts: dict) -> list[str]:
    """Return a list of human-readable rule violations. Empty list == valid.

    Same rules as validate_suggestions, but each string names exactly what broke
    so it can be fed straight back to the model as correction feedback (the
    enabler for the retry loop in the orchestrators below).

    Rules:
    - ≤ 7 sessions
    - each session_type in KNOWN_WORKOUT_TYPES
    - each target_tss numeric, in [_MIN_SESSION_TSS, _MAX_SESSION_TSS]
    - weekly total TSS ≤ max(trailing_avg, FALLBACK_MIN_WEEKLY_TSS) × ACWR_HIGH_BOUND
    - every day_offset is in facts["allowed_offsets"] (default: whole week)
    - every day_offset in facts["preferred_rest_days"] is either absent or
      workout_type == "rest"
    - the day immediately before the week's long run (the highest-TSS run) is
      not another hard/interval run
    - no more than _MAX_CONSECUTIVE_TRAINING_DAYS consecutive non-rest days
    """
    errs: list[str] = []
    allowed = set(_allowed_offsets(facts))
    rest_requested = set(_preferred_rest_days(facts))

    if len(suggestions) > 7:
        errs.append(f"Too many sessions: {len(suggestions)} (max 7).")

    trailing_avg = float(facts.get("trailing_28d_weekly_avg_tss") or 0.0)
    max_weekly = round(max(trailing_avg, FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND)
    total_tss = 0.0

    for s in suggestions:
        wt = str(s.get("workout_type", "")).lower().strip()
        if wt not in KNOWN_WORKOUT_TYPES:
            errs.append(
                f"Invalid workout_type {s.get('workout_type')!r}; "
                f"allowed: {sorted(KNOWN_WORKOUT_TYPES)}."
            )

        offset = s.get("day_offset")
        if allowed and offset is not None and int(offset) not in allowed:
            errs.append(
                f"day_offset {offset} is not open for suggestions "
                f"(allowed: {sorted(allowed)} — the rest are already scheduled, "
                "already happened, or before today)."
            )

        if offset is not None and int(offset) in rest_requested and wt not in ("", "rest"):
            errs.append(
                f"day_offset {offset} was requested by the athlete as a REST day "
                f"but was proposed as {wt!r}."
            )

        if wt in ("strength", "plyo"):
            exercises = s.get("exercises")
            if not exercises or not isinstance(exercises, list):
                errs.append(
                    f"day_offset {offset} is {wt!r} but has no exercises breakdown — "
                    "add 4-10 entries ({block, name, sets, reps, load}), not just a one-line intent."
                )
            else:
                for ex in exercises:
                    if not isinstance(ex, dict) or not str(ex.get("name") or "").strip():
                        errs.append(
                            f"day_offset {offset} has an exercises entry missing a name: {ex!r}."
                        )
                        break

        if wt == "run":
            blocks = s.get("blocks")
            if not blocks or not isinstance(blocks, list):
                errs.append(
                    f"day_offset {offset} is 'run' but has no blocks breakdown — "
                    "add phase entries ({phase, duration_min, repeat, rest_min, target}), "
                    "not just a bare duration."
                )
            else:
                for b in blocks:
                    if not isinstance(b, dict) or not b.get("phase") or not b.get("duration_min"):
                        errs.append(
                            f"day_offset {offset} has a blocks entry missing phase/duration_min: {b!r}."
                        )
                        break

        tss = s.get("target_tss")
        try:
            tss_f = float(tss) if tss is not None else 0.0
        except (TypeError, ValueError):
            errs.append(f"Non-numeric target_tss {tss!r}.")
            continue

        if tss_f < _MIN_SESSION_TSS or tss_f > _MAX_SESSION_TSS:
            errs.append(
                f"Session target_tss {tss_f:.0f} out of range "
                f"[{_MIN_SESSION_TSS}, {_MAX_SESSION_TSS}]."
            )

        total_tss += tss_f

    if total_tss > max_weekly:
        errs.append(
            f"Weekly TSS {total_tss:.0f} exceeds ACWR safe ceiling {max_weekly} "
            f"(trailing avg {round(trailing_avg)} × {ACWR_HIGH_BOUND}). "
            "Reduce hard sessions."
        )

    # ── Target-aware checks (Plan tab revamp, Part 3) — only run when facts
    # carries a race-anchored target_tss (PLAN_TARGET_AWARE_ENABLED and an A
    # race resolved in assemble_facts); absent that key, this block is a no-op
    # and validation_errors is byte-identical to pre-Part-3 behaviour.
    target_tss = facts.get("target_tss")
    if target_tss is not None:
        target_tss = float(target_tss)
        logged_so_far = float(facts.get("logged_tss_so_far") or 0.0)
        combined = logged_so_far + total_tss
        lower = target_tss * (1 - _TARGET_BAND_FRACTION)
        upper = target_tss * (1 + _TARGET_BAND_FRACTION)
        if not (lower <= combined <= upper):
            pct = round(abs(combined - target_tss) / target_tss * 100) if target_tss else 0
            direction = "exceeds" if combined > target_tss else "falls short of"
            errs.append(
                f"Weekly TSS {combined:.0f} (logged {logged_so_far:.0f} + suggested {total_tss:.0f}) "
                f"{direction} the {target_tss:.0f} TSS target by {pct}% — aim within "
                f"±{round(_TARGET_BAND_FRACTION * 100)}% ({lower:.0f}-{upper:.0f}); "
                "ACWR ceiling is the hard limit."
            )

        acwr_ceiling = facts.get("acwr_ceiling")
        if acwr_ceiling is not None and combined > float(acwr_ceiling):
            errs.append(
                f"Weekly TSS {combined:.0f} exceeds the ACWR ceiling {float(acwr_ceiling):.0f} "
                "— reduce volume even if that means missing the target."
            )

        today_offset = facts.get("today_offset")
        if today_offset is not None:
            today_offset = int(today_offset)
            for s in suggestions:
                offset = s.get("day_offset")
                if offset is not None and int(offset) < today_offset:
                    errs.append(
                        f"day_offset {offset} is already in the past (today is day_offset "
                        f"{today_offset}) — cannot schedule a new session there."
                    )

    # A requested rest day must show up EXPLICITLY as rest — silently omitting
    # it isn't enough; the athlete checked that box to see it honoured.
    present_offsets = {int(s["day_offset"]) for s in suggestions if s.get("day_offset") is not None}
    for off in sorted(rest_requested):
        if off in allowed and off not in present_offsets:
            errs.append(
                f"day_offset {off} was requested as REST but has no session at all — "
                "add an explicit workout_type=\"rest\", target_tss=0 session for it."
            )

    # Pre-long-run-day rule: the day before the week's long run (highest-TSS
    # run) must not be another hard/interval run — that's how easy fitness
    # gets undermined right before the effort meant to build it.
    long_run = _find_long_run(suggestions)
    if long_run is not None:
        pre_offset = int(long_run["day_offset"]) - 1
        pre_day = next((s for s in suggestions if int(s.get("day_offset", -99)) == pre_offset), None)
        if pre_day is not None and str(pre_day.get("workout_type", "")).lower() == "run":
            pre_tss = float(pre_day.get("target_tss") or 0.0)
            long_tss = float(long_run.get("target_tss") or 0.0)
            hard = _is_hard_intent(pre_day.get("intent", "")) or (
                long_tss > 0 and pre_tss >= _HARD_RUN_TSS_FRACTION_OF_LONG_RUN * long_tss
            )
            if hard:
                errs.append(
                    f"day_offset {pre_offset} (the day before the long run at "
                    f"day_offset {long_run['day_offset']}) is another hard run. "
                    "Make it rest, an easy run, or a non-run session instead."
                )

    # Training/rest balance: no more than _MAX_CONSECUTIVE_TRAINING_DAYS
    # consecutive non-rest days among the offsets actually open this week.
    by_offset = {int(s["day_offset"]): s for s in suggestions if s.get("day_offset") is not None}
    streak = 0
    for off in sorted(allowed) if allowed else sorted(by_offset):
        s = by_offset.get(off)
        is_training = s is not None and str(s.get("workout_type", "")).lower() != "rest"
        streak = streak + 1 if is_training else 0
        if streak > _MAX_CONSECUTIVE_TRAINING_DAYS:
            errs.append(
                f"{streak} consecutive training days ending at day_offset {off} — "
                f"insert a rest or easy day at least every {_MAX_CONSECUTIVE_TRAINING_DAYS} days."
            )
            break

    # Zone-2 weekly floor (prefs catalog, reads: validation) — only when
    # target-aware mode is on and the athlete set a positive target.
    z2_min = int(facts.get("zone2_weekly_min") or 0)
    if z2_min > 0 and facts.get("target_tss") is not None:
        # Approximate Z2 minutes from easy/run sessions where intent looks aerobic
        z2_mins = 0
        for s in suggestions:
            wt = str(s.get("workout_type", "")).lower()
            intent = str(s.get("intent") or "").lower()
            dur = int(s.get("duration_minutes") or 0)
            if wt == "run" and any(k in intent for k in ("easy", "aerobic", "z2", "zone 2", "zone2", "base")):
                z2_mins += dur
            elif wt == "run":
                # Count half of unmarked run duration as potential Z2 (conservative)
                z2_mins += dur // 2
        if z2_mins < z2_min:
            errs.append(
                f"Estimated zone-2 minutes {z2_mins} fall short of preference "
                f"zone2_weekly_min={z2_min}."
            )

    return errs


def validate_suggestions(suggestions: list[dict], facts: dict) -> bool:
    """True iff LLM-proposed suggestions pass every hard rule (see validation_errors)."""
    return not validation_errors(suggestions, facts)


def _feedback_block(errs: list[str]) -> str:
    """Correction feedback appended to the user prompt on a retry."""
    return (
        "\n\nYour previous answer was REJECTED for these reasons:\n- "
        + "\n- ".join(errs)
        + "\nFix every issue and return corrected JSON matching the schema."
    )


def fallback_suggestions(facts: dict) -> list[dict]:
    """Build a deterministic template week from trailing load + ramp cap.

    Pure function — no DB access, no network calls.
    Respects ACWR ramp cap. When facts carry a race-anchored `target_tss`
    (from load_plan via assemble_facts), that number is the weekly target —
    including any taper already applied by load_plan.TAPER_CURVE. This module
    never multiplies by its own taper factor.
    """
    trailing_avg = float(facts.get("trailing_28d_weekly_avg_tss") or 0.0)
    if facts.get("target_tss") is not None:
        target_weekly = float(facts["target_tss"])
    else:
        base = max(trailing_avg, FALLBACK_MIN_WEEKLY_TSS)
        target_weekly = base * _FALLBACK_RAMP_FACTOR

    # Clamp to ACWR safe ceiling (always last).
    max_weekly = max(trailing_avg, FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND
    if facts.get("acwr_ceiling") is not None:
        max_weekly = min(max_weekly, float(facts["acwr_ceiling"]))
    target_weekly = min(target_weekly, max_weekly)

    allowed = set(_allowed_offsets(facts))
    rest_requested = set(_preferred_rest_days(facts))
    emphasis = facts.get("strength_emphasis") or "same"
    if emphasis not in _VALID_STRENGTH_EMPHASIS:
        emphasis = "same"

    sessions = []
    for tmpl in _TEMPLATE:
        if tmpl["day_offset"] not in allowed:
            continue
        frac = tmpl["tss_fraction"]
        raw_tss = round(target_weekly * frac) if frac > 0 else 0
        exercises = tmpl.get("exercises")
        blocks = tmpl.get("blocks")
        sessions.append({
            "day_offset": tmpl["day_offset"],
            "workout_type": tmpl["workout_type"],
            "target_tss": raw_tss,
            "duration_minutes": tmpl["duration_base"],
            "intent": tmpl["intent"],
            # No fabricated rationale for the deterministic template — only the
            # LLM path (which actually reasons about the athlete's real
            # schedule/fatigue) produces `notes`.
            "notes": None,
            # Deep-copied so per-session Lighter/Harder-style edits downstream
            # (or a future "more" swap re-picking this same template row) never
            # mutate the shared module-level constant.
            "exercises": [dict(e) for e in exercises] if exercises else None,
            "blocks": [dict(b) for b in blocks] if blocks else None,
        })

    # Requested rest days always win, overriding whatever the template had.
    for s in sessions:
        if s["day_offset"] in rest_requested:
            s.update(workout_type="rest", target_tss=0, duration_minutes=0,
                     intent="Rest day (requested).", notes=None, exercises=None, blocks=None)

    if emphasis != "same":
        long_run = _find_long_run(sessions)
        long_off = long_run["day_offset"] if long_run else None
        if emphasis == "more":
            # Convert the easiest eligible run (never the long run, never a
            # forced rest day) into a strength session — with a real exercise
            # breakdown, not just a bare label.
            candidates = [s for s in sessions
                          if s["workout_type"] == "run" and s["day_offset"] != long_off
                          and s["day_offset"] not in rest_requested]
            if candidates:
                pick = min(candidates, key=lambda s: s["target_tss"])
                # The picked candidate is a RUN row — its duration_minutes/
                # target_tss came from that run's own (often much shorter,
                # sometimes 0-TSS "optional easy jog") template numbers. Left
                # unchanged, the converted session claimed e.g. 30min/0 TSS
                # while carrying the full 10-entry _UPPER_BODY_STRENGTH_
                # EXERCISES list — self-contradictory (can't fit 10 exercises
                # in 30min, and a real strength session isn't 0 TSS). Reuse
                # the same duration/TSS-fraction the template's own strength
                # rows use (see _TEMPLATE day_offset 1) instead.
                pick.update(workout_type="strength",
                            target_tss=round(target_weekly * 0.15),
                            duration_minutes=45,
                            intent="Extra strength session (requested more strength this week).",
                            exercises=[dict(e) for e in _UPPER_BODY_STRENGTH_EXERCISES], blocks=None)
        else:  # "less"
            candidates = [s for s in sessions
                          if s["workout_type"] == "strength" and s["day_offset"] not in rest_requested]
            if candidates:
                pick = min(candidates, key=lambda s: s["target_tss"])
                pick.update(workout_type="rest", target_tss=0, duration_minutes=0,
                            intent="Rest (requested less strength this week).", exercises=None, blocks=None)

    return sessions


_DAY_NAMES: tuple[str, ...] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def build_prompt(facts: dict) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the LLM suggestion call."""
    trailing = facts.get("trailing_28d_weekly_avg_tss", 0.0)
    headroom = facts.get("acwr_headroom_tss", 0.0)
    ctl = facts.get("ctl", 0.0)
    atl = facts.get("atl", 0.0)
    tsb = facts.get("tsb", 0.0)
    days_to_race = facts.get("days_to_next_race")
    readiness_trend = facts.get("readiness_trend", [])
    allowed = _allowed_offsets(facts)
    rest_requested = _preferred_rest_days(facts)
    emphasis = facts.get("strength_emphasis") or "same"
    if emphasis not in _VALID_STRENGTH_EMPHASIS:
        emphasis = "same"
    notes = (facts.get("notes") or "").strip()
    today_offset = facts.get("today_offset")
    existing_week = facts.get("existing_week") or []
    recent_exercise_names = facts.get("recent_exercise_names") or []

    taper_note = ""
    # Taper language comes from load_plan phase only — no ad-hoc day-window factor.
    if facts.get("phase") == "taper":
        taper_note = (
            " The athlete is in a TAPER week (load_plan phase) — "
            "honour the reduced weekly target and favour easy sessions."
        )

    allowed_str = ", ".join(f"{o} ({_DAY_NAMES[o]})" for o in sorted(allowed)) or "none — the week is fully covered already"
    recent_ex_str = ", ".join(recent_exercise_names) if recent_exercise_names else ""

    target_tss = facts.get("target_tss")

    _n = 7
    target_rule_n = None
    if target_tss is not None:
        target_rule_n = _n; _n += 1
    notes_binding_rule_n = None
    if notes:
        notes_binding_rule_n = _n; _n += 1
    notes_rule_n = _n; _n += 1
    rest_rule_n = None
    if rest_requested:
        rest_rule_n = _n; _n += 1
    avoid_repeat_rule_n = None
    if recent_ex_str:
        avoid_repeat_rule_n = _n; _n += 1
    exercises_rule_n = _n; _n += 1
    blocks_rule_n = _n; _n += 1
    long_run_rule_n = _n; _n += 1
    consec_rule_n = _n; _n += 1

    # Athlete notes must outrank the generic phase-mix template. Without an
    # explicit numbered rule the model treats the trailing "Additional notes"
    # line as background and lays down its default long-run/quality/strength
    # distribution instead (observed: "run Tue, long run Sat, strength Sun"
    # answered with strength Tue/Sat and a run Sun).
    notes_binding_rule = (
        f"{notes_binding_rule_n}. The athlete's own notes (the 'Additional notes from the athlete' "
        "line below) are BINDING scheduling constraints, not background context. When they name a "
        "day and a session type (e.g. \"run Tue, strength Fri\"), you MUST schedule exactly that "
        "type on that day — including two same-day entries per rule 3 when they ask for both (e.g. "
        "\"strength and an easy run on Fri\"). Phrasing like \"I had a plan of running Tue\" states "
        "the athlete's intended plan for THIS week unless it clearly describes already-completed "
        "training. The generic phase mix in these rules fills in ONLY where the notes are silent.\n"
    ) if notes_binding_rule_n else ""
    rest_rule = (
        f"{rest_rule_n}. The athlete asked for these day_offsets to be REST: "
        f"{', '.join(str(o) for o in sorted(rest_requested))}. You MUST include an explicit "
        "session for each of these — workout_type=\"rest\", target_tss=0 — do not omit them.\n"
    ) if rest_rule_n else ""
    avoid_repeat_rule = (
        f"{avoid_repeat_rule_n}. The athlete's recently used / already-planned exercises this week are: "
        f"{recent_ex_str}. Do NOT default to these out of habit — pick something different unless you "
        "genuinely think one of them is still the best choice for this session (e.g. a key compound lift "
        "the athlete is actively progressing). Vary the exercise selection across the week.\n"
    ) if avoid_repeat_rule_n else ""

    # Race-anchored weekly TSS target (Plan tab revamp, Part 3) — only present
    # when PLAN_TARGET_AWARE_ENABLED and an A race resolved a target_tss for
    # this week (see assemble_facts). Supersedes rule 6's generic ramp-limit
    # language with a concrete number: fill what's LEFT, not the whole target.
    target_rule = ""
    if target_rule_n:
        remaining = facts.get("remaining_tss")
        logged_so_far = facts.get("logged_tss_so_far") or 0.0
        ceiling = facts.get("acwr_ceiling")
        phase = facts.get("phase") or "hold"
        days_left = facts.get("days_remaining_in_week")
        phase_note = {
            "ramp": "Normal mix for this phase: one long run, one quality/hard session, "
                    "supporting easy runs and strength.",
            "hold": "Normal mix for this phase: one long run, one quality/hard session, "
                    "supporting easy runs and strength.",
            "taper": "TAPER PHASE: volume drops but intensity is RETAINED. Produce fewer "
                     "and/or shorter sessions than a normal week — do NOT cut intensity and "
                     "keep volume, that is backwards. Keep some sharpening (short quality "
                     "efforts) even as total time drops.",
            "race": "RACE PHASE: the race itself plus short shakeouts only — no long runs, "
                    "no new heavy strength, no new hard efforts.",
            # A deterministic training_verdict.compute_verdict() result of
            # "hold"/"back_off" overrides the ramp/hold phase entirely (see
            # load_plan.py's "Verdict consolidation") — the athlete's own
            # current CTL/ATL/TSB/ACWR says this is not a week to build from.
            # Never fall through to the generic "Normal mix" default here;
            # that's exactly the bug this system is supposed to prevent.
            "consolidation": "CONSOLIDATION — the athlete's current training-load verdict says "
                              "hold or back off, not build. Easy/moderate sessions only: no new "
                              "hard intervals, no long-run PRs, no heavy new strength. The target "
                              "TSS itself is already reduced to reflect this — fill it with easy "
                              "volume, not intensity.",
        }.get(phase, "Normal mix: one long run, one quality/hard session, supporting easy "
                     "runs and strength.")
        target_rule = (
            f"{target_rule_n}. This week has a weekly TSS target of {round(float(facts.get('target_tss') or 0))} "
            f"({phase} phase"
            + (f", {days_left} day(s) left" if days_left is not None else "")
            + f"). The athlete has already logged {round(float(logged_so_far))} TSS. "
            f"Aim for proposed sessions to sum near {round(float(remaining or 0))} TSS remaining "
            f"(within ±{round(_TARGET_BAND_FRACTION * 100)}% is fine — the target is a guide, not a "
            "hard fill). Prefer staying under the ACWR ceiling over hitting the number exactly; "
            "do not double-count what's already logged.\n"
            + (f"Hard ceiling: total week TSS (logged + proposed) must stay within the ACWR "
               f"limit of {round(float(ceiling))}.\n" if ceiling is not None else "")
            + phase_note + "\n"
        )

    system = (
        "You are a running coach producing a structured training plan for the "
        "REMAINDER of the athlete's current week — not a fresh Monday-to-Sunday "
        "week. Return ONLY a JSON object matching the schema. "
        "SAFETY RULES — you MUST follow these:\n"
        f"1. Total weekly TSS across all sessions must not exceed {round(max(float(trailing), FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND)} "
        f"(ACWR safe ceiling: trailing 28-day weekly average {round(float(trailing))} × {ACWR_HIGH_BOUND}).\n"
        "2. Each session's target_tss must be between 0 and 400.\n"
        "3. At most 7 sessions total. If the athlete's notes describe MORE THAN ONE "
        "distinct session on the same day (e.g. \"short strength tomorrow followed by "
        "an easy run\" = two separate sessions, same day), you MUST output BOTH as "
        "separate entries with the SAME day_offset value repeated across two array "
        "items — do not collapse them into one, and do not merge the easy run into "
        "the strength session's own duration/TSS. Minimal example of what two same-"
        "day entries look like in the suggestions array (values illustrative only): "
        '[{"day_offset": 4, "workout_type": "strength", ...}, {"day_offset": 4, '
        '"workout_type": "run", ...}]. Each entry still counts toward the 7-session '
        "cap and the day's/week's TSS limits.\n"
        "4. workout_type must be exactly one of: run, strength, plyo, stretch, rest.\n"
        "5. Only propose sessions for these day_offsets — every other day is already "
        f"scheduled, already logged, or in the past: {allowed_str}.\n"
        f"6. Respect ramp limits: do not increase weekly TSS by more than 30% above the trailing average.{taper_note}\n"
        f"{target_rule}"
        f"{notes_binding_rule}"
        f"{notes_rule_n}. `intent` = a short session TITLE, 4-5 words max (e.g. \"Full body strength, "
        "glute focus\") — it becomes the saved session's name; no full sentences. `notes` = the coach's "
        "RATIONALE (why this weight/exercise/pairing — fatigue "
        "management, what's already logged/planned, why an exercise was avoided/kept). Terse coach-style, "
        "e.g. \"Legs stay fresh — Thursday is intervals.\" Null only for rest days.\n"
        f"{rest_rule}"
        f"{avoid_repeat_rule}"
        f"{exercises_rule_n}. strength/plyo/stretch sessions: DEFAULT `exercises` array of 8-14 entries in 4-6 "
        "blocks, 60-90min total — \"Warm-up\" (3-4 activation moves), \"Heavy compound\" (1 primary lift), "
        "\"Superset 1\"/\"Superset 2\" (2 exercises each, PAIRED opposing muscle groups, e.g. hinge+push), "
        "\"Standalone\" (1 isolation move), \"Accessories\" (2-3 core/stability moves). If the athlete's "
        "notes ask for a SHORT/quick/brief session instead, scale down: 4-6 entries in 2-3 blocks "
        "(\"Warm-up\" + 1-2 of Heavy compound/Superset), 20-35min total — do not pad a requested-short "
        "session up to the default size. Entry = {block, name, sets, reps, load}: sets=integer; reps/load "
        "are short strings (reps: \"10\"/\"30s hold\"; load: \"bodyweight\"/\"moderate\"/\"65% 1RM "
        "(~45kg)\"). A plyo session is EXPLOSIVE jump/power work — box jumps, bounds, hops, depth "
        "jumps, jump squats, med-ball throws — low reps (3-6), few sets, FULL recovery between "
        "efforts, bodyweight or light load: never the barbell-lift strength template. A stretch "
        "session is mobility/flexibility work: 4-8 hold/flow entries in 1-2 blocks, 15-30min, "
        "mostly bodyweight — never barbell lifts. Never empty for strength/plyo/stretch; null "
        "for run/rest.\n"
        f"{blocks_rule_n}. run sessions: `blocks` array (2-5 entries), one per phase, not just a duration "
        "number. Entry = {phase, duration_min, repeat, rest_min, target}: phase is warmup/main/cooldown "
        "(repeat \"main\" for multiple work segments); repeat=integer reps of that phase or null; "
        "rest_min=rest between reps or null; target=short effort/pace (\"easy\"/\"tempo\"/\"92% CP\") or "
        "null. Easy/steady run = single non-repeated \"main\" phase. Null for strength/plyo/stretch/rest.\n"
        f"{long_run_rule_n}. The highest-target_tss run session is the week's LONG RUN — the day before it "
        "must not be another hard/interval run; use rest, easy run, or non-run instead.\n"
        f"{consec_rule_n}. No more than {_MAX_CONSECUTIVE_TRAINING_DAYS} consecutive training days without "
        "a rest/easy day — balance against current CTL/ATL.\n"
    )

    trend_str = ", ".join(str(v) for v in (readiness_trend or [])[-7:]) or "no data"

    user = (
        f"Current training load: CTL={ctl}, ATL={atl}, TSB={tsb}.\n"
        f"Trailing 28-day weekly average TSS: {trailing}.\n"
        f"ACWR headroom (how much more TSS is safe this week): {round(float(headroom))}.\n"
        f"Recent readiness scores (last {len(readiness_trend or [])} days): {trend_str}.\n"
    )
    if existing_week:
        lines = []
        for d in existing_week:
            if d.get("has_workout") or d.get("has_planned"):
                bits = []
                if d.get("has_workout"):
                    bits.append(f"already logged a {d.get('workout_type') or 'workout'}")
                if d.get("has_planned"):
                    bits.append(f"already has a planned {d.get('planned_type') or 'session'} ({d.get('planned_status')})")
                if d.get("planned_exercise_names"):
                    bits.append("exercises: " + ", ".join(d["planned_exercise_names"]))
                lines.append(f"  - day_offset {d['day_offset']} ({_DAY_NAMES[d['day_offset']]} {d.get('date', '')}): " + "; ".join(bits))
        if lines:
            user += "Current schedule this week (do not duplicate or contradict these):\n" + "\n".join(lines) + "\n"
    if recent_ex_str:
        user += f"Recently used / already-planned exercises (avoid defaulting to these — see rule above): {recent_ex_str}.\n"
    if days_to_race is not None:
        race_dist = facts.get("next_race_distance_km")
        race_goal = facts.get("next_race_goal_time_seconds")
        user += f"Next race: in {days_to_race} days"
        if race_dist:
            user += f", {race_dist} km"
        if race_goal:
            mins = int(race_goal) // 60
            user += f", goal {mins} min"
        user += ".\n"
    if emphasis == "more":
        user += "The athlete wants MORE strength training than usual this week.\n"
    elif emphasis == "less":
        user += "The athlete wants LESS strength training than usual this week.\n"
    # Training prefs (catalog) — flow into the prompt; deep generation enforcement
    # of plyo supersets / MP segments is a later ticket.
    prefs_bits = []
    if facts.get("prefs_version"):
        prefs_bits.append(f"prefs_version={facts['prefs_version']}")
    if facts.get("plyo_mode") and facts.get("plyo_mode") != "off":
        prefs_bits.append(f"plyo_mode={facts['plyo_mode']}")
    if int(facts.get("plyo_sessions_per_week") or 0) > 0:
        prefs_bits.append(f"plyo_sessions_per_week={facts['plyo_sessions_per_week']}")
    if int(facts.get("long_run_mp_segment_min") or 0) > 0:
        prefs_bits.append(f"long_run.mp_segment_min={facts['long_run_mp_segment_min']}")
    if int(facts.get("stretch_daily_min") or 0) > 0:
        prefs_bits.append(f"stretch_daily_min={facts['stretch_daily_min']}")
    if int(facts.get("zone2_weekly_min") or 0) > 0:
        prefs_bits.append(f"zone2_weekly_min={facts['zone2_weekly_min']}")
    if prefs_bits:
        user += (
            "Active training preferences (honour; safety rules still win): "
            + ", ".join(prefs_bits)
            + ".\n"
        )
    if notes:
        # Anchor day-name language ("Tue", "Sat") in the notes to concrete
        # day_offsets. today_offset covers "today"/"tomorrow" but is None for
        # a next-week request (today isn't in the target week), so ALSO emit
        # the full offset↔day↔date table whenever week_start is known —
        # without it the model must infer the mapping from allowed_str alone,
        # which is unreliable (observed: intervals requested "today" landing
        # on the wrong day_offset; "run Tue" answered with strength on Tue).
        week_start_iso = facts.get("week_start")
        if week_start_iso:
            try:
                ws = date.fromisoformat(week_start_iso)
                mapping = ", ".join(
                    f"{o}={_DAY_NAMES[o]} {(ws + timedelta(days=o)).isoformat()}" for o in range(7)
                )
                user += f"Target week day mapping (day_offset=day date): {mapping}.\n"
            except ValueError:
                pass
        if today_offset is not None:
            user += f"TODAY is day_offset {today_offset} ({_DAY_NAMES[today_offset]}). "
        user += f"Additional notes from the athlete: {notes}\n"
    user += (
        f"\nPropose sessions ONLY for day_offset(s) {allowed_str} "
        "(day_offset 0=Monday through 6=Sunday, same numbering as the current week). "
        "Each session needs day_offset, workout_type, target_tss, duration_minutes, intent, and notes "
        "(the rationale — see the safety rules above). strength/plyo sessions additionally need the "
        "exercises breakdown; run sessions need the blocks breakdown — not every open day needs a "
        "session; use rest as needed."
    )

    return system, user


def build_signature(facts: dict) -> str:
    """SHA-256 signature over (_PROMPT_VERSION, facts dict), stable key ordering.

    Versioned so a build_prompt()/schema edit invalidates every previously
    cached LlmGeneration row instead of silently continuing to serve them.
    """
    serialised = json.dumps({"prompt_version": _PROMPT_VERSION, "facts": facts}, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


_LLM_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "maxItems": 7,
            "items": {
                "type": "object",
                "properties": {
                    "day_offset":       {"type": "integer", "minimum": 0, "maximum": 6},
                    "workout_type":     {"type": "string", "enum": sorted(KNOWN_WORKOUT_TYPES)},
                    "target_tss":       {"type": "integer", "minimum": 0, "maximum": 400},
                    "duration_minutes": {"type": "integer", "minimum": 0, "maximum": 360},
                    "intent":           {"type": "string", "maxLength": 200},
                    # Coach's rationale for THIS session's choices — why this
                    # weight/exercise/pairing, referencing fatigue, what's
                    # already logged/planned this week, or recent-exercise
                    # avoidance. Nullable (a rest day has nothing to explain).
                    "notes": {"type": ["string", "null"], "maxLength": 600},
                    # Block-grouped exercise breakdown — required (by
                    # validation_errors, not JSON-schema-required, since it only
                    # applies to strength/plyo) for those two workout_types.
                    "exercises": {
                        "type": ["array", "null"],
                        "maxItems": 14,
                        "items": {
                            "type": "object",
                            "properties": {
                                "block": {"type": "string", "maxLength": 40},
                                "name":  {"type": "string", "maxLength": 100},
                                "sets":  {"type": "integer", "minimum": 1, "maximum": 10},
                                "reps":  {"type": "string", "maxLength": 40},
                                "load":  {"type": "string", "maxLength": 120},
                            },
                            "required": ["block", "name", "sets", "reps", "load"],
                            "additionalProperties": False,
                        },
                    },
                    # Phase-structured run breakdown — required (by
                    # validation_errors) for workout_type="run".
                    "blocks": {
                        "type": ["array", "null"],
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "properties": {
                                "phase":        {"type": "string", "enum": ["warmup", "main", "cooldown"]},
                                "duration_min": {"type": "integer", "minimum": 1, "maximum": 180},
                                "repeat":       {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
                                "rest_min":     {"type": ["number", "null"], "minimum": 0, "maximum": 30},
                                "target":       {"type": ["string", "null"], "maxLength": 60},
                            },
                            "required": ["phase", "duration_min", "repeat", "rest_min", "target"],
                            "additionalProperties": False,
                        },
                    },
                },
                # Groq/OpenAI strict structured-output mode requires EVERY
                # property to be listed here — "optional" is expressed via a
                # nullable type (exercises/blocks: ["array","null"]), not omission.
                "required": ["day_offset", "workout_type", "target_tss", "duration_minutes", "intent", "notes", "exercises", "blocks"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


# Worst case: 7 sessions, each up to 14 exercises (~40 tokens/entry) or 5
# blocks, plus a 600-char notes field — needs comfortably more than Groq's
# implicit completion default, which otherwise truncates the JSON mid-object
# (surfaces as an opaque 400 "max completion tokens reached").
#
# Also bounded from above: this org's Groq on_demand tier caps openai/gpt-oss-*
# models at 8000 tokens/minute TOTAL (input + this budget) — confirmed via a
# live 413 ("Request too large ... tokens per minute (TPM): Limit 8000") that
# silently fell back to the deterministic template (which never reads the
# athlete's free-text notes) on every retry. Input runs ~1650-1750 tokens for
# a typical request post-prompt-trim (see build_prompt), so 5700 leaves ~550
# tokens (~7%) of headroom under the cap while still exceeding the ~5200-5500
# token worst case above by a real margin.
_LLM_MAX_COMPLETION_TOKENS = 5700


def _call_llm(facts: dict, feedback: str = "") -> dict | None:
    """Call LLM; return raw dict (not yet validated) or None.

    `feedback` (non-empty on a retry) is appended to the user prompt so the model
    sees exactly which rules its previous answer broke.
    """
    system, user = build_prompt(facts)
    return llm_svc.complete_structured(
        system=system,
        user=user + feedback,
        schema_name="plan_suggestion",
        json_schema=_LLM_JSON_SCHEMA,
        model_tier="deep",
        max_tokens=_LLM_MAX_COMPLETION_TOKENS,
    )


# ── Orchestration ─────────────────────────────────────────────────────────────
#
# LLM plan → validate → template fallback, one implementation. There were once
# four, switched per-request by PLAN_ORCH so their outputs could be A/B'd on
# real data: single-shot, a plain retry loop, LangGraph, and Pydantic AI. The
# comparison is over — the single-shot path won and the rest were deleted with
# the env var, so there is nothing left to switch between.
#
# Still fallback-safe: any failure (LLM off, network, invalid output) returns
# the deterministic template.

def _template_result(facts: dict, attempts: int, orch: str) -> dict:
    return {
        "suggestions": fallback_suggestions(facts),
        "source": "fallback",
        "attempts": attempts,
        "orch": orch,
    }


def get_suggestions_from_facts(facts: dict) -> dict:
    """Attempt LLM suggestions; fall back to the deterministic template if the
    LLM is disabled, unreachable, or returns something that fails validation.

    Single-shot: one call, one validation, no retry. Returns
    {'suggestions': [...], 'source': 'llm'|'fallback', 'attempts': int,
    'orch': str}. ``orch`` is always "single" — it survives in the payload
    because callers and tests read the response shape, not because there is
    anything to choose.
    """
    raw = _call_llm(facts)
    if raw is not None:
        suggestions = raw.get("suggestions", [])
        if validate_suggestions(suggestions, facts):
            return {"suggestions": suggestions, "source": "llm", "attempts": 1, "orch": "single"}
        _log.warning("LLM plan_suggestion output failed validation — using fallback")
    return _template_result(facts, attempts=1 if raw is not None else 0, orch="single")


# ── DB-calling layer ──────────────────────────────────────────────────────────

def assemble_facts(
    user_id: str,
    db=None,
    *,
    week_start: "date | None" = None,
    preferred_rest_days: list[int] | None = None,
    strength_emphasis: str | None = None,
    notes: str | None = None,
) -> dict:
    """Assemble training facts for a user from the database.

    Reads: CTL/ATL/TSB, 7-day and 28-day TSS, readiness trend, next race,
    ACWR headroom, and — for the target week (`week_start`'s Monday, default
    the CURRENT week) — which day_offsets are still open for a suggestion
    (`allowed_offsets`) plus what's already scheduled there (`existing_week`).

    A day_offset is NOT open when it's before today (already passed this week)
    or already has a workout logged or a planned session of any status — the
    point being to fill in what's missing, not duplicate or contradict the
    athlete's real schedule. `preferred_rest_days` / `strength_emphasis` /
    `notes` are the athlete's own input, passed straight into facts for
    `build_prompt` and `fallback_suggestions` to honour.
    """
    from sqlalchemy import func, text
    from sqlalchemy.orm import Session

    from backend.db import engine
    from backend.models import DailyReadiness, PlannedSession, Race, Workout, WorkoutExercise
    from backend.services.training_load import current_load, daily_tss_series
    from backend.services.acwr import compute_acwr, HIGH_BOUND as _acwr_high
    from backend.utils.time import today_bangkok

    # BKK-local "today" — matches the app-wide convention (workout_date, week
    # windows) fixed in the reconcile.py timezone bug. Using server-local
    # today_bangkok() here would misjudge which day_offset is "today" whenever
    # the server clock isn't BKK, silently re-opening or closing the wrong day.
    today = today_bangkok()

    # CTL / ATL / TSB
    load = current_load(user_id)
    ctl = float(load.get("ctl") or 0.0)
    atl = float(load.get("atl") or 0.0)
    tsb = float(load.get("tsb") or 0.0)

    # 7-day TSS (recent acute load)
    start_7 = today - timedelta(days=6)
    series_7 = daily_tss_series(user_id, start_7, today)
    trailing_7d = float(sum(v for _, v in series_7))

    # 28-day TSS series for ACWR + weekly average
    start_28 = today - timedelta(days=27)
    series_28 = daily_tss_series(user_id, start_28, today)
    total_28d = float(sum(v for _, v in series_28))
    trailing_28d_weekly_avg = round(total_28d / 4.0, 1)

    # ACWR headroom: how much more TSS can be added this week before hitting HIGH_BOUND
    acwr_series = [v for _, v in series_28]
    acwr_result = compute_acwr(acwr_series)
    chronic = total_28d / 4.0  # same as compute_acwr's chronic
    acwr_safe_max_weekly = chronic * _acwr_high
    # headroom = max safe weekly - what's already accumulated in current week
    current_week_start = today - timedelta(days=today.weekday())
    series_this_week = daily_tss_series(user_id, current_week_start, today)
    this_week_tss = float(sum(v for _, v in series_this_week))
    acwr_headroom = max(0.0, round(acwr_safe_max_weekly - this_week_tss, 1))

    # Readiness trend (last 7 days)
    _own_session = db is None
    if _own_session:
        db = Session(engine)
    _prefs_stored = None
    next_race = None
    next_race_date = None
    next_race_km = None
    next_race_goal = None
    try:
        readiness_rows = (
            db.query(DailyReadiness)
            .filter(
                DailyReadiness.user_id == user_id,
                DailyReadiness.date >= start_7,
                DailyReadiness.date <= today,
            )
            .order_by(DailyReadiness.date)
            .all()
        )
        readiness_trend = [float(r.score) for r in readiness_rows if r.score is not None]

        # Next upcoming A-priority race — snapshot scalars before the session
        # closes / commit expires ORM state (DetachedInstanceError otherwise).
        next_race = (
            db.query(Race)
            .filter(
                Race.user_id == user_id,
                Race.race_date > today,
                Race.status == "planned",
                Race.priority == "A",
            )
            .order_by(Race.race_date)
            .first()
        )
        next_race_date = next_race.race_date if next_race is not None else None
        next_race_km = (
            float(next_race.distance_km)
            if next_race is not None and next_race.distance_km is not None
            else None
        )
        next_race_goal = next_race.goal_time_seconds if next_race is not None else None

        # ── Target-week scoping: which day_offsets are still open ───────────
        target_week_start = week_start if week_start is not None else current_week_start
        # offset_of_today: 0..6 if the target week contains today, negative if
        # the target week is entirely in the future, >6 if entirely in the past.
        offset_of_today = (today - target_week_start).days
        start_offset = max(0, min(offset_of_today, 7))

        week_workouts = (
            db.query(Workout)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date >= target_week_start,
                Workout.workout_date <= target_week_start + timedelta(days=6),
            )
            .all()
        )
        week_planned = (
            db.query(PlannedSession)
            .filter(
                PlannedSession.user_id == user_id,
                PlannedSession.planned_date >= target_week_start,
                PlannedSession.planned_date <= target_week_start + timedelta(days=6),
            )
            .all()
        )
        workouts_by_date = {}
        for w in week_workouts:
            workouts_by_date.setdefault(w.workout_date, w)
        planned_by_date = {}
        for p in week_planned:
            planned_by_date.setdefault(p.planned_date, p)

        def _structure_exercise_names(structure) -> list[str]:
            if not isinstance(structure, dict):
                return []
            exs = structure.get("exercises")
            if not isinstance(exs, list):
                return []
            return [str(e.get("name")).strip() for e in exs if isinstance(e, dict) and e.get("name")]

        existing_week: list[dict] = []
        allowed_offsets: list[int] = []
        planned_exercise_names: list[str] = []  # this week's own strength/plyo picks
        for offset in range(7):
            d = target_week_start + timedelta(days=offset)
            w = workouts_by_date.get(d)
            p = planned_by_date.get(d)
            p_names = _structure_exercise_names(p.structure) if p is not None else []
            planned_exercise_names.extend(p_names)
            entry = {
                "day_offset": offset,
                "date": d.isoformat(),
                "has_workout": w is not None,
                "workout_type": (w.workout_type if w is not None else None),
                "has_planned": p is not None,
                "planned_type": (p.session_type if p is not None else None),
                "planned_status": (p.status if p is not None else None),
                "planned_exercise_names": p_names,
            }
            existing_week.append(entry)
            if offset >= start_offset and w is None and p is None:
                allowed_offsets.append(offset)

        # ── Target-aware TSS facts (Plan tab revamp, Part 3) — off by default;
        # gated by PLAN_TARGET_AWARE_ENABLED so assemble_facts is byte-identical
        # to pre-Part-3 behaviour until explicitly turned on. target_tss/phase
        # come from the SAME compute_load_plan() math and A-race resolution
        # convention (next_race, above) as the Session Load Plan card and
        # week-load endpoint — never reimplement the ramp/hold/taper math here.
        target_tss = None
        logged_tss_so_far = None
        remaining_tss = None
        acwr_ceiling = None
        phase = None
        days_remaining_in_week = None
        verdict = None
        verdict_reason = None

        if _target_aware_enabled():
            from backend.models import TrainingPlan
            from backend.services.load_plan import compute_load_plan
            from backend.services.load_plan import ACWR_CEILING_MULT as _acwr_ceiling_mult
            from backend.services.load_plan import resolve_baseline_weeks_ago as _resolve_baseline_weeks_ago
            from backend.services.training_load import get_weekly_volume as _get_weekly_volume

            acwr_ceiling = (
                round(_acwr_ceiling_mult * trailing_28d_weekly_avg, 1)
                if trailing_28d_weekly_avg else None
            )
            if offset_of_today < 0:
                days_remaining_in_week = 7
            elif offset_of_today > 6:
                days_remaining_in_week = 0
            else:
                days_remaining_in_week = 7 - offset_of_today
            logged_tss_so_far = _get_weekly_volume(
                str(user_id), target_week_start, target_week_start + timedelta(days=6)
            )["total_tss"]

            if next_race_date is not None:
                plan_row = (
                    db.query(TrainingPlan)
                    .filter(TrainingPlan.user_id == user_id)
                    .order_by(TrainingPlan.created_at.asc())
                    .first()
                )
                ramp_rate = float(plan_row.ramp_rate) if plan_row and plan_row.ramp_rate is not None else 0.05
                plan_hold_weeks = int(plan_row.hold_weeks) if plan_row and plan_row.hold_weeks is not None else 4
                plan_taper_weeks = (
                    int(round(float(plan_row.taper_length))) if plan_row and plan_row.taper_length is not None else 3
                )
                plan_deload_enabled = bool(plan_row.deload_enabled) if plan_row and plan_row.deload_enabled is not None else False
                plan_deload_start_week = (
                    int(plan_row.deload_start_week) if plan_row and plan_row.deload_start_week is not None else 4
                )

                baseline_weeks_ago = _resolve_baseline_weeks_ago(
                    deload_enabled=plan_deload_enabled,
                    deload_start_week=plan_deload_start_week,
                )
                baseline_week_start = current_week_start - timedelta(weeks=baseline_weeks_ago)
                baseline_week_end = baseline_week_start + timedelta(days=6)
                baseline_logged = _get_weekly_volume(str(user_id), baseline_week_start, baseline_week_end)["total_tss"]
                from backend.services.load_plan import resolve_baseline_seed as _resolve_baseline_seed
                from backend.services.training_load import (
                    estimate_historical_pace_and_tss as _est_baseline,
                    estimate_planned_session_metrics as _est_planned,
                )
                from backend.models import PlannedSession as _PlannedSession
                _est_b = _est_baseline(str(user_id), db)
                baseline_planned = 0.0
                for _p in (
                    db.query(_PlannedSession)
                    .filter(
                        _PlannedSession.user_id == user_id,
                        _PlannedSession.planned_date >= baseline_week_start,
                        _PlannedSession.planned_date <= baseline_week_end,
                    )
                    .all()
                ):
                    _e = _est_planned(_est_b, _p.session_type, _p.structure)
                    if _e.get("estimated_tss"):
                        baseline_planned += float(_e["estimated_tss"])
                baseline_tss = _resolve_baseline_seed(baseline_logged, baseline_planned)

                race_week_start = next_race_date - timedelta(days=next_race_date.weekday())
                weeks_to_race = ((race_week_start - current_week_start).days // 7) + 1

                from backend.services.training_load import current_load as _current_load
                from backend.services.training_verdict import compute_verdict as _compute_verdict

                _snap = _current_load(str(user_id), as_of=today)
                verdict_result = _compute_verdict(
                    _snap, chronic_weekly=trailing_28d_weekly_avg, today=today,
                )
                verdict = verdict_result["verdict"]
                verdict_reason = verdict_result["reason"]

                lp_result = compute_load_plan(
                    baseline=baseline_tss, ramp_rate=ramp_rate, hold_weeks=plan_hold_weeks,
                    taper_weeks=plan_taper_weeks, weeks_to_race=weeks_to_race,
                    trailing_28d_avg=trailing_28d_weekly_avg, deload_enabled=plan_deload_enabled,
                    deload_start_week=plan_deload_start_week,
                    verdict=verdict_result["verdict"],
                )
                week_index = ((target_week_start - current_week_start).days // 7) + 1
                target_week = next((w for w in lp_result["weeks"] if w["week_index"] == week_index), None)
                if target_week is not None:
                    target_tss = target_week["target_tss"]
                    phase = target_week["phase"]
                    remaining_tss = max(0.0, round(target_tss - logged_tss_so_far, 1))
                    # This week's own moving ceiling (see load_plan.py) —
                    # supersedes the static estimate above when a race/plan
                    # resolved a real series to read it from.
                    acwr_ceiling = target_week["ceiling"] if target_week["ceiling"] is not None else acwr_ceiling

        # ── Recent exercise history (avoid defaulting to the same picks) ────
        # Last 14 days of ACTUALLY LOGGED strength/plyo workouts — what the
        # athlete really did, not just planned. Most-recent-first, deduped.
        _lookback_start = today - timedelta(days=14)
        recent_rows = (
            db.query(WorkoutExercise.name, Workout.workout_date)
            .join(Workout, WorkoutExercise.workout_id == Workout.id)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date >= _lookback_start,
                Workout.workout_date <= today,
                func.lower(Workout.workout_type).in_(("strength", "plyo")),
            )
            .order_by(Workout.workout_date.desc())
            .all()
        )
        recent_exercise_names: list[str] = []
        _seen_names: set[str] = set()
        for name, _wd in recent_rows:
            n = str(name).strip()
            if n and n not in _seen_names:
                _seen_names.add(n)
                recent_exercise_names.append(n)
        # This week's own already-planned picks count too, so a later
        # suggestion in the SAME week doesn't duplicate an earlier one.
        for n in planned_exercise_names:
            if n and n not in _seen_names:
                _seen_names.add(n)
                recent_exercise_names.append(n)
        recent_exercise_names = recent_exercise_names[:20]

        # Stored training prefs (versioned) — while session still open.
        try:
            from backend.services.training_prefs import prefs_for_assemble_facts
            _prefs_stored = prefs_for_assemble_facts(db, user_id)
            if _own_session:
                db.commit()
        except Exception:
            _prefs_stored = None
            # Roll back even on a caller-supplied session: the prefs fetch can
            # write (carry-forward), and a failed write otherwise leaves the
            # shared session's transaction aborted for the rest of the request.
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        if _own_session:
            db.close()

    rest_days_in = preferred_rest_days
    emphasis_in = strength_emphasis
    notes_in = notes
    prefs_version = 0
    plyo_mode = "off"
    plyo_sessions_per_week = 0
    long_run_mp_segment_min = 0
    stretch_daily_min = 0
    zone2_weekly_min = 0

    if _prefs_stored:
        prefs_version = int(_prefs_stored.get("prefs_version") or 0)
        if rest_days_in is None:
            rest_days_in = _prefs_stored.get("preferred_rest_days")
        if emphasis_in is None:
            emphasis_in = _prefs_stored.get("strength_emphasis")
        if notes_in is None:
            notes_in = _prefs_stored.get("notes")
        plyo_mode = _prefs_stored.get("plyo_mode") or "off"
        plyo_sessions_per_week = int(_prefs_stored.get("plyo_sessions_per_week") or 0)
        long_run_mp_segment_min = int(_prefs_stored.get("long_run_mp_segment_min") or 0)
        stretch_daily_min = int(_prefs_stored.get("stretch_daily_min") or 0)
        zone2_weekly_min = int(_prefs_stored.get("zone2_weekly_min") or 0)

    rest_days = sorted({int(d) for d in (rest_days_in or []) if int(d) in allowed_offsets})
    emphasis = (emphasis_in or "same").strip().lower()
    if emphasis not in _VALID_STRENGTH_EMPHASIS:
        emphasis = "same"
    notes_clean = (notes_in or "").strip()[:300]

    facts: dict[str, Any] = {
        "ctl": round(ctl, 2),
        "atl": round(atl, 2),
        "tsb": round(tsb, 2),
        "trailing_7d_tss": trailing_7d,
        "trailing_28d_weekly_avg_tss": trailing_28d_weekly_avg,
        "acwr_headroom_tss": acwr_headroom,
        "readiness_trend": readiness_trend,
        "days_to_next_race": None,
        "next_race_distance_km": None,
        "next_race_goal_time_seconds": None,
        "week_start": target_week_start.isoformat(),
        "today_offset": offset_of_today if 0 <= offset_of_today <= 6 else None,
        "allowed_offsets": allowed_offsets,
        "existing_week": existing_week,
        "preferred_rest_days": rest_days,
        "strength_emphasis": emphasis,
        "notes": notes_clean,
        "recent_exercise_names": recent_exercise_names,
        "prefs_version": prefs_version,
        "plyo_mode": plyo_mode,
        "plyo_sessions_per_week": plyo_sessions_per_week,
        "long_run_mp_segment_min": long_run_mp_segment_min,
        "stretch_daily_min": stretch_daily_min,
        "zone2_weekly_min": zone2_weekly_min,
    }

    if next_race_date is not None:
        facts["days_to_next_race"] = (next_race_date - today).days
        facts["next_race_distance_km"] = next_race_km
        facts["next_race_goal_time_seconds"] = next_race_goal

    # Only added when PLAN_TARGET_AWARE_ENABLED — an unset flag must produce a
    # facts dict byte-identical to pre-Part-3 behaviour (same keys, same
    # build_signature hash for the same inputs).
    if _target_aware_enabled():
        facts["target_tss"] = target_tss
        facts["logged_tss_so_far"] = logged_tss_so_far
        facts["remaining_tss"] = remaining_tss
        facts["acwr_ceiling"] = acwr_ceiling
        facts["days_remaining_in_week"] = days_remaining_in_week
        facts["phase"] = phase
        # Deterministic verdict (backend/services/training_verdict.py) — a
        # "hold"/"back_off" verdict already reshaped target_tss/phase above
        # ("consolidation") via compute_load_plan(verdict=...); these two are
        # for the prompt/report layer's own reference, not re-derivation.
        facts["verdict"] = verdict
        facts["verdict_reason"] = verdict_reason

    return facts


def history_skeleton_slots(
    history: list[tuple[int, str, float, float]],
    facts: dict,
    strength_sessions: int | None = None,
) -> list[dict]:
    """Rule-based schedule skeleton from the athlete's OWN recent weeks —
    pure function, zero LLM (two-rail flow, issue #1417).

    history: (weekday 0-6, workout_type, tss, duration_minutes) tuples from
    the last 3 completed weeks. A weekday/type pair seen at least twice in
    that window is a habit worth prefilling; its slot gets the median TSS
    and duration. The highest-TSS run weekday is tagged subtype "long".
    strength_sessions (when given) is enforced exactly: extra strength
    slots are trimmed weakest-habit-first; missing ones are added to the
    lightest open days.
    """
    from statistics import median

    allowed = facts.get("allowed_offsets")
    allowed = list(range(7)) if allowed is None else list(allowed)
    rest_days = list(facts.get("preferred_rest_days") or [])

    by_day: dict[int, dict[str, list[tuple[float, float]]]] = {}
    for wd, wtype, tss, dur_min in history:
        t = (wtype or "").lower()
        if t not in KNOWN_WORKOUT_TYPES or t == "rest" or not (0 <= wd <= 6):
            continue
        by_day.setdefault(wd, {}).setdefault(t, []).append((float(tss or 0), float(dur_min or 0)))

    slots: list[dict] = []
    for d in range(7):
        if d in rest_days:
            slots.append({
                "day_offset": d, "workout_type": "rest", "target_tss": 0,
                "duration_minutes": 0, "intent": "Rest day (requested).",
                "notes": None, "exercises": None, "blocks": None,
            })
            continue
        if d not in allowed:
            continue
        for t, vals in sorted(by_day.get(d, {}).items()):
            if len(vals) < 2:  # not a habit — one-offs don't prefill
                continue
            slots.append({
                "day_offset": d, "workout_type": t,
                "target_tss": round(median(v[0] for v in vals)),
                "duration_minutes": int(round(median(v[1] for v in vals) / 5.0) * 5),
                "intent": "", "notes": None, "exercises": None, "blocks": None,
                "_habit_count": len(vals),
            })

    # Long-run tag: the biggest habitual run of the week.
    runs = [s for s in slots if s["workout_type"] == "run"]
    if runs:
        max(runs, key=lambda s: s["target_tss"])["subtype"] = "long"

    if strength_sessions is not None:
        _enforce_strength_count(slots, strength_sessions, allowed, rest_days)

    for s in slots:
        s.pop("_habit_count", None)
    slots.sort(key=lambda s: s["day_offset"])
    return slots


def _enforce_strength_count(slots: list[dict], strength_sessions: int,
                            allowed: list[int], rest_days: list[int]) -> None:
    """Make the slot list contain EXACTLY `strength_sessions` strength slots
    (in place): extras trimmed weakest-habit-first, missing ones added to the
    lightest open non-rest days. Shared by the history skeleton and the
    template fallback — an explicit count is binding on both paths."""
    want = max(0, min(7, int(strength_sessions)))
    strength = [s for s in slots if s["workout_type"] == "strength"]
    strength.sort(key=lambda s: (-s.get("_habit_count", 0), -s["target_tss"]))
    for s in strength[want:]:
        slots.remove(s)
    # Add missing strength to the lightest open non-rest days first.
    day_tss = {d: sum(s["target_tss"] for s in slots if s["day_offset"] == d)
               for d in allowed if d not in rest_days}
    have_strength = {s["day_offset"] for s in slots if s["workout_type"] == "strength"}
    candidates = sorted(
        [d for d in day_tss if d not in have_strength],
        key=lambda d: day_tss[d],
    )
    for d in candidates[: max(0, want - len(strength[:want]))]:
        slots.append({
            "day_offset": d, "workout_type": "strength", "target_tss": 50,
            "duration_minutes": 45, "intent": "", "notes": None,
            "exercises": None, "blocks": None,
        })


def _load_history_rows(user_id: str, week_start: "date", db=None) -> list[tuple[int, str, float, float]]:
    """(weekday, type, tss, duration_minutes) for the 21 days before week_start."""
    from backend.models import Workout

    _own = db is None
    if _own:
        from backend.db import engine
        from sqlalchemy.orm import Session
        db = Session(engine)
    try:
        rows = (
            db.query(Workout.workout_date, Workout.workout_type, Workout.tss, Workout.duration_seconds)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date >= week_start - timedelta(days=21),
                Workout.workout_date < week_start,
            )
            .all()
        )
        return [
            (r[0].weekday(), r[1] or "", float(r[2] or 0), float(r[3] or 0) / 60.0)
            for r in rows
        ]
    finally:
        if _own:
            db.close()


def get_suggestions(
    user_id: str,
    db=None,
    *,
    week_start: "date | None" = None,
    preferred_rest_days: list[int] | None = None,
    strength_emphasis: str | None = None,
    notes: str | None = None,
    skeleton: bool = False,
    strength_sessions: int | None = None,
) -> dict:
    """Full entry point: assemble facts → cache-aware LLM call → fallback.

    Returns {'facts': {...}, 'suggestions': [...], 'source': 'llm' | 'fallback',
    'attempts': int, 'orch': str}. One surface, one orchestrator — the cache key
    used to carry the PLAN_ORCH value so an A/B switch wouldn't collide on it,
    which stopped mattering when the alternatives were deleted.
    week_start/preferred_rest_days/strength_emphasis/notes are the athlete's
    scoping + preference input (see assemble_facts) — they flow into facts and
    therefore into the cache signature, so different input never collides.

    skeleton=True (two-rail flow, issue #1417) skips the LLM entirely and
    returns the deterministic template — day/type/TSS/duration slots the
    athlete then rearranges on the schedule rail before per-slot content is
    generated via generate_single_session. Instant, zero LLM cost, never
    cached (the template is pure computation over facts).
    """
    facts = assemble_facts(
        user_id, db=db, week_start=week_start,
        preferred_rest_days=preferred_rest_days,
        strength_emphasis=strength_emphasis, notes=notes,
    )
    if skeleton:
        # Rule-based, zero LLM. First choice: the athlete's OWN last 3
        # weeks — a weekday/type habit prefills a slot with its median
        # TSS/duration (history_skeleton_slots). Only when there's no
        # history at all does the generic template fill in. Slots carry
        # only the budget — content (intent/notes/exercises/blocks) stays
        # blank until the athlete fills a slot with AI.
        history = _load_history_rows(user_id, date.fromisoformat(facts["week_start"]), db=db)
        slots = history_skeleton_slots(history, facts, strength_sessions=strength_sessions)
        source = "history"
        if not any(s["workout_type"] != "rest" for s in slots):
            slots = [
                {**s, "intent": s.get("intent") if s.get("workout_type") == "rest" else "",
                 "notes": None, "exercises": None, "blocks": None}
                for s in fallback_suggestions(facts)
            ]
            # An explicit strength count is binding on the template path too
            # — a no-history athlete asking for 0 strength must not get the
            # template's hardcoded 2 strength days.
            if strength_sessions is not None:
                _allowed = facts.get("allowed_offsets")
                _allowed = list(range(7)) if _allowed is None else list(_allowed)
                _enforce_strength_count(
                    slots, strength_sessions, _allowed,
                    list(facts.get("preferred_rest_days") or []),
                )
                slots.sort(key=lambda s: s["day_offset"])
            source = "skeleton"
        # Prefs-driven plyo / stretch / MP / benchmark — same post-pass as
        # plan_draft. Without this, Build schedule ignored plyo / week.
        from backend.services.plan_extras import apply_prefs_extras
        week_start_d = date.fromisoformat(facts["week_start"])
        extras_prefs = {
            "plyo_mode": facts.get("plyo_mode") or "off",
            "plyo_sessions_per_week": int(facts.get("plyo_sessions_per_week") or 0),
            "stretch_daily_min": int(facts.get("stretch_daily_min") or 0),
            "long_run_mp_segment_min": int(facts.get("long_run_mp_segment_min") or 0),
        }
        decorated = apply_prefs_extras(
            {"slots": slots, "week_start": facts["week_start"]},
            prefs=extras_prefs,
            week_start=week_start_d,
            rest_days=set(facts.get("preferred_rest_days") or []),
        )
        slots = decorated.get("slots") or slots
        return {
            "facts": facts,
            "suggestions": slots,
            "source": source,
            "attempts": 0,
            "orch": "none",
        }
    sig = build_signature(facts)
    surface = _SURFACE

    # Cache lookup via get_or_generate.
    def _generate():
        return get_suggestions_from_facts(facts)

    cached_or_new = llm_svc.get_or_generate(
        user_id=str(user_id),
        surface=surface,
        signature=sig,
        generate_fn=_generate,
        model_tier="deep",  # matches _call_llm's model_tier — see llm.get_or_generate
    )

    if cached_or_new is not None:
        return {"facts": facts, **cached_or_new}

    # LLM unavailable — always fallback gracefully.
    fallback = get_suggestions_from_facts(facts)
    return {"facts": facts, **fallback}


# ── Single-session generation (Ask-AI for one day) ────────────────────────────
# Shared by two UI entry points: (1) Add-session's "Ask AI" mode — pick a
# date/type/note and generate ONE fresh session; (2) a suggestion row's
# "Refine" — regenerate ONE already-suggested session with a note ("change
# focus", "faster intervals"), passing its current content as a starting
# point. Deliberately NOT the same code path as the whole-week generator
# above: a single session is a much smaller prompt/output (no 7-session
# array, no whole-week TSS-budget derivation to redo), so it stays cheap
# against the same Groq TPM/RPM limits that bit the whole-week path.

_LLM_SINGLE_SESSION_SCHEMA: dict = {
    "type": "object",
    "properties": {"session": _LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]},
    "required": ["session"],
    "additionalProperties": False,
}

# gpt-oss (the "deep" tier) is a reasoning model whose hidden reasoning
# tokens count against max_completion_tokens — a trivial strength-session
# request measured 1403 completion tokens with 1014 of them reasoning, so
# the old cap of 1500 truncated real refine requests mid-JSON and Groq's
# strict-mode surfaced that as an opaque 400 (json_validate_failed).
# Sized to match the whole-week surface's headroom (5700); Groq bills only
# tokens actually generated.
_SINGLE_SESSION_MAX_COMPLETION_TOKENS = 6000
# Runs are deliberately cheap (the slot already fixes TSS/duration; the LLM
# only splits it into warmup/main/cooldown): a small cap matters because
# Groq's free tier PRE-BOOKS prompt + max_completion_tokens against an 8k
# tokens-per-minute budget — at 6000 every call costs ~6.9k and only ONE
# fits per minute; at 2000 a run fill costs ~2.7k and several fit.
_RUN_SESSION_MAX_COMPLETION_TOKENS = 2000


SESSION_SUBTYPES: dict[str, dict[str, str]] = {
    "run": {
        "easy": "a conversational, fully aerobic easy run — no quality segments",
        "long": "the week's LONG run — steady aerobic, even effort, no intervals",
        "intervals": "an interval session — repeated hard efforts with recovery jogs between",
        "tempo": "a tempo run — sustained comfortably-hard blocks at threshold-ish effort",
    },
    "strength": {
        "upper": "an UPPER-body strength session — push/pull emphasis, minimal leg loading",
        "lower": "a LOWER-body strength session — hinge/squat/single-leg emphasis",
        "full": "a FULL-body strength session — balanced upper/lower/core",
        "light": "a LIGHT maintenance strength session — short, low load, no grinding sets",
    },
}

# Skeleton / draft subtypes (easy_run, …) → Suggest-UI labels (easy, …).
_SKELETON_SUBTYPE_TO_UI: dict[str, str] = {
    "easy_run": "easy",
    "long_run": "long",
    "intervals": "intervals",
    "tempo": "tempo",
    "strength_upper": "upper",
    "strength_lower": "lower",
    "strength_full": "full",
    "strength_light": "light",
    "plyo": "plyo",
    "stretch": "stretch",
}


def coerce_ui_subtype(workout_type: str | None, subtype: str | None) -> str | None:
    """Accept UI (`easy`) or skeleton (`easy_run`) labels; return UI key or None."""
    raw = (subtype or "").strip().lower()
    if not raw:
        return None
    wt = (workout_type or "").strip().lower()
    valid = SESSION_SUBTYPES.get(wt, {})
    if raw in valid:
        return raw
    from backend.services.plan_slot import normalize_slot_subtype
    canon = normalize_slot_subtype(wt, raw)
    ui = _SKELETON_SUBTYPE_TO_UI.get(canon or "", canon)
    if ui in valid:
        return ui
    return None


def build_single_session_prompt(
    facts: dict,
    day_offset: int,
    workout_type: str | None,
    note: str,
    current_session: dict | None = None,
    subtype: str | None = None,
) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for a ONE-session generate/refine call.

    This is the freeform path: no schedule-rail budget is pinned, so the LLM
    proposes target_tss/duration_minutes itself, bounded by the rules below
    and checked by validation_errors (range + weekly ACWR ceiling). When the
    schedule rail HAS pinned a budget (two-rail flow, issue #1417),
    generate_single_session takes the plan_slot.py content-only path instead
    — this prompt is never reached with a budget to honour, so it does not
    build one. subtype is the slot's optional flavor tag (SESSION_SUBTYPES)
    — e.g. a run is "easy" vs "intervals", a strength day is "upper" vs
    "light"."""
    trailing = facts.get("trailing_28d_weekly_avg_tss", 0.0)
    max_weekly = round(max(float(trailing), FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND)
    day_name = _DAY_NAMES[day_offset]

    subtype_rule = ""
    ui_subtype = coerce_ui_subtype(workout_type, subtype) if subtype else None
    subtype_desc = SESSION_SUBTYPES.get(workout_type or "", {}).get(ui_subtype or "")
    if subtype_desc:
        subtype_rule = (
            f"6. The athlete tagged this session \"{ui_subtype}\": build {subtype_desc}. "
            "The tag is binding — do not build a different kind of session.\n"
        )

    system = (
        "You are a running coach. Produce or REVISE exactly ONE training session "
        "for a single day — not a whole week. Return ONLY a JSON object matching "
        "the schema (a single `session`).\n"
        "RULES:\n"
        f"1. day_offset MUST be {day_offset} ({day_name}) — do not move it to another day.\n"
        f"2. target_tss must be 0-400 and should not by itself push the athlete's "
        f"weekly total above {max_weekly} (their ACWR safe ceiling).\n"
        "3. workout_type must be exactly one of: run, strength, plyo, stretch, rest"
        + (f" — the athlete asked for \"{workout_type}\"; use that unless their note "
           "explicitly asks for something else.\n" if workout_type else ".\n")
        + (
            # Runs are a cheap estimation task — the slot already fixes TSS
            # and duration; the model only splits them into three phases.
            # Paired with the small run token cap below, this keeps a run
            # fill inside Groq's per-minute token budget in one call.
            "4. run: include `blocks` with EXACTLY 3 entries — warmup, main, cooldown "
            "({phase, duration_min, repeat, rest_min, target}). Split the session's duration "
            "across the three phases and give each a short effort target (\"easy\"/\"tempo\"/"
            "\"5 × 3min hard, 2min jog\" — intervals detail goes in the main block's target "
            "string, repeat and rest_min). This is a simple estimation, not a design task — "
            "be brief, no long deliberation. `exercises` null.\n"
            if workout_type == "run" else
            "4. strength/plyo/stretch: include `exercises` (4-14 entries, {block, name, sets, reps, "
            "load}); scale to a short (4-6 entries) session if the note asks for brief/quick. "
            "For a STRENGTH session, `block` values MUST follow this exact sequence and naming — "
            "\"Warm-up\" (2-4 activation moves), \"Heavy compound\" (1 primary lift), "
            "\"Superset 1\" and \"Superset 2\" (2 exercises each, paired opposing muscle groups), "
            "then \"Accessories\" (2-3 core/stability moves) or \"Standalone\" (1 isolation move), "
            "finishing with \"Stretch\" (1-2 cool-down stretches). Do NOT invent other block names "
            "(no \"Upper body push\"/\"Lower body hinge\" style groupings). A plyo "
            "session is EXPLOSIVE jump/power work — box jumps, bounds, hops, depth jumps, jump "
            "squats, med-ball throws — low reps (3-6), few sets, FULL recovery between efforts, "
            "bodyweight or light load: never the barbell-lift strength template. A stretch session "
            "is mobility/flexibility holds and flows, mostly bodyweight, never barbell lifts. "
            "run: include `blocks` (2-5 entries, {phase, duration_min, repeat, "
            "rest_min, target}). rest: both null.\n"
        )
        + "5. `intent` = a short session TITLE, 4-5 words max (e.g. \"Full body strength, glute focus\") "
        "— it becomes the saved session's name, so no full sentences. "
        "`notes` = terse coach rationale for this session, or null for rest.\n"
        f"{subtype_rule}"
    )

    user = f"This session is for day_offset {day_offset} ({day_name})."
    if current_session:
        user += (
            "\nCurrent session to revise (keep whatever the note doesn't ask to change): "
            + json.dumps(current_session, default=str)
        )
    else:
        user += " There is no existing session — create one from scratch."
    user += f"\nAthlete's request: {note.strip()}\n" if note else "\n"
    user += "Return the single updated/created session as `session`."
    return system, user


def generate_single_session(
    user_id: str,
    day_offset: int,
    note: str,
    *,
    workout_type: str | None = None,
    current_session: dict | None = None,
    week_start: "date | None" = None,
    preferred_rest_days: list[int] | None = None,
    strength_emphasis: str | None = None,
    notes: str | None = None,
    target_tss: float | None = None,
    duration_minutes: int | None = None,
    subtype: str | None = None,
    seed: int | None = None,
    db=None,
) -> dict | None:
    """Fill ONE session from DB patterns using pinned type/TSS/duration.

    Planning LLM removed — `note` is ignored for content generation.
    Requires pins (target_tss and/or duration_minutes); without pins returns None.
    Pass ``seed`` to reshuffle strength/plyo picks; omit for the stable hash.
    """
    del note  # unused — no freeform LLM refine
    import random

    from backend.services.plan_prefs_accessor import get_plan_prefs
    from backend.services.plan_slot import (
        build_week_ctx,
        normalize_slot_subtype,
        stamp_session,
    )
    from backend.services.plan_pattern_fill import fill_slot

    if target_tss is None and duration_minutes is None:
        return None

    prefs = get_plan_prefs(
        db, user_id,
        preferred_rest_days=preferred_rest_days,
        strength_emphasis=strength_emphasis,
        notes=notes,
    )
    facts = assemble_facts(
        user_id, db=db, week_start=week_start,
        preferred_rest_days=prefs["preferred_rest_days"],
        strength_emphasis=prefs["strength_emphasis"],
        notes=prefs["notes"],
    )

    slot = {
        "day_offset": day_offset,
        "workout_type": (workout_type or "run").lower(),
        "target_tss": round(float(target_tss)) if target_tss is not None else 0,
        "duration_minutes": int(duration_minutes) if duration_minutes is not None else 0,
        "subtype": normalize_slot_subtype(workout_type, subtype),
        "structure_hints": {},
        "locked": False,
    }
    mp_min = int(prefs.get("long_run_mp_segment_min") or 0)
    if mp_min > 0 and slot["subtype"] == "long_run":
        slot["mp_segment_min"] = mp_min
        slot["structure_hints"] = {"mp_segment_min": mp_min}
    week_ctx = build_week_ctx(
        facts=facts,
        skeleton_slots=[slot],
        strength_emphasis=prefs["strength_emphasis"],
        notes=prefs["notes"],
    )
    current = None
    if current_session and isinstance(current_session, dict):
        current = {
            "intent": current_session.get("intent"),
            "notes": current_session.get("notes"),
            "blocks": current_session.get("blocks"),
            "exercises": current_session.get("exercises"),
            "source": current_session.get("source"),
        }
    rng = random.Random(int(seed) & 0xFFFFFFFF) if seed is not None else None
    content = fill_slot(slot, db=db, week_ctx=week_ctx, current=current, rng=rng)
    footprint = content.pop("_muscle_footprint", None)
    fill_log = content.pop("fill_log", None)
    stamped = stamp_session(slot, content)
    stamped["source"] = content.get("source") or "pattern"
    if footprint:
        stamped["_muscle_footprint"] = footprint
    if content.get("pattern_name"):
        stamped["pattern_name"] = content["pattern_name"]
    if fill_log:
        stamped["fill_log"] = fill_log
    if seed is not None:
        stamped["seed"] = int(seed) & 0xFFFFFFFF
    return stamped
