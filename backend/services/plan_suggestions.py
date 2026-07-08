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

KNOWN_WORKOUT_TYPES: frozenset[str] = frozenset({"run", "strength", "plyo", "rest"})

# Mirror of acwr.HIGH_BOUND — weekly TSS must not exceed trailing_avg × this.
ACWR_HIGH_BOUND: float = 1.3

# When trailing 28-day avg is very low, still allow a minimal template week.
FALLBACK_MIN_WEEKLY_TSS: float = 80.0

# Per-session TSS bounds (sane range: rest=0, hard session ≤ 400).
_MAX_SESSION_TSS: int = 400
_MIN_SESSION_TSS: int = 0

# Race taper window in days.
_TAPER_WINDOW_DAYS: int = 14
# Fraction of normal weekly TSS during taper.
_TAPER_FACTOR: float = 0.60

# Conservative ramp factor for fallback (10% increase, well below HIGH_BOUND).
_FALLBACK_RAMP_FACTOR: float = 1.10

_SURFACE = "plan_suggestion"

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
_LOWER_BODY_STRENGTH_EXERCISES: list[dict] = [
    {"block": "Warm-up", "name": "Leg swings (front-back + lateral)", "sets": 1, "reps": "10", "load": "bodyweight, per direction per leg"},
    {"block": "Warm-up", "name": "Bodyweight squat", "sets": 1, "reps": "10", "load": "bodyweight"},
    {"block": "Main", "name": "Back squat", "sets": 3, "reps": "8", "load": "moderate"},
    {"block": "Main", "name": "Romanian deadlift", "sets": 3, "reps": "10", "load": "moderate"},
    {"block": "Main", "name": "Walking lunge", "sets": 3, "reps": "10", "load": "bodyweight or light dumbbells, per leg"},
    {"block": "Core", "name": "Plank", "sets": 3, "reps": "40s hold", "load": "bodyweight"},
    {"block": "Core", "name": "Side plank", "sets": 2, "reps": "25-30s hold", "load": "bodyweight, per side"},
]
_UPPER_BODY_STRENGTH_EXERCISES: list[dict] = [
    {"block": "Warm-up", "name": "Arm circles + band pull-apart", "sets": 1, "reps": "15", "load": "light band"},
    {"block": "Main", "name": "Dumbbell overhead press", "sets": 3, "reps": "10", "load": "moderate"},
    {"block": "Main", "name": "Dumbbell bent-over row", "sets": 3, "reps": "10", "load": "moderate"},
    {"block": "Main", "name": "Push-up", "sets": 3, "reps": "12", "load": "bodyweight"},
    {"block": "Core", "name": "Dead bug", "sets": 3, "reps": "10", "load": "bodyweight, per side"},
    {"block": "Core", "name": "Bird dog", "sets": 3, "reps": "10", "load": "bodyweight, per side"},
]

# Default template: day_offset → (workout_type, tss_fraction_of_weekly, duration_min)
# Fractions sum to 1.0 (excluding rest days at 0). exercises is None for run/rest
# (run structure — blocks — is a separate, not-yet-built follow-up).
_TEMPLATE: list[dict] = [
    {"day_offset": 0, "workout_type": "run",      "tss_fraction": 0.20, "duration_base": 45, "intent": "Easy aerobic run — keep effort conversational.", "exercises": None},
    {"day_offset": 1, "workout_type": "strength",  "tss_fraction": 0.15, "duration_base": 45, "intent": "Lower body strength — squats, lunges, hip work.", "exercises": _LOWER_BODY_STRENGTH_EXERCISES},
    {"day_offset": 2, "workout_type": "run",       "tss_fraction": 0.25, "duration_base": 60, "intent": "Moderate-effort run or tempo intervals.", "exercises": None},
    {"day_offset": 3, "workout_type": "rest",      "tss_fraction": 0.00, "duration_base": 0,  "intent": "Rest or light stretching.", "exercises": None},
    {"day_offset": 4, "workout_type": "run",       "tss_fraction": 0.20, "duration_base": 50, "intent": "Easy aerobic run — maintain base fitness.", "exercises": None},
    {"day_offset": 5, "workout_type": "strength",  "tss_fraction": 0.20, "duration_base": 45, "intent": "Upper body and core strength.", "exercises": _UPPER_BODY_STRENGTH_EXERCISES},
    {"day_offset": 6, "workout_type": "run",       "tss_fraction": 0.00, "duration_base": 30, "intent": "Optional very easy jog or full rest.", "exercises": None},
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
    Respects ACWR ramp cap and tapers if race is within _TAPER_WINDOW_DAYS.

    Only emits sessions for facts["allowed_offsets"] (default: the whole week,
    so callers/tests that never set this key get the original 7-day template
    unchanged). Honours facts["preferred_rest_days"] by forcing those offsets
    to rest, and facts["strength_emphasis"] ("less"|"same"|"more") by nudging
    one run<->strength swap — the template's weekly-TSS math (ramp/taper/ACWR)
    is unchanged; only which offsets/types appear shifts.
    """
    trailing_avg = float(facts.get("trailing_28d_weekly_avg_tss") or 0.0)
    base = max(trailing_avg, FALLBACK_MIN_WEEKLY_TSS)
    target_weekly = base * _FALLBACK_RAMP_FACTOR

    # Race taper: reduce if race is within 14 days.
    days_to_race = facts.get("days_to_next_race")
    if days_to_race is not None and 0 <= int(days_to_race) <= _TAPER_WINDOW_DAYS:
        target_weekly *= _TAPER_FACTOR

    # Clamp to ACWR safe ceiling.
    max_weekly = max(trailing_avg, FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND
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
        sessions.append({
            "day_offset": tmpl["day_offset"],
            "workout_type": tmpl["workout_type"],
            "target_tss": raw_tss,
            "duration_minutes": tmpl["duration_base"],
            "intent": tmpl["intent"],
            # Deep-copied so per-session Lighter/Harder-style edits downstream
            # (or a future "more" swap re-picking this same template row) never
            # mutate the shared module-level constant.
            "exercises": [dict(e) for e in exercises] if exercises else None,
        })

    # Requested rest days always win, overriding whatever the template had.
    for s in sessions:
        if s["day_offset"] in rest_requested:
            s.update(workout_type="rest", target_tss=0, duration_minutes=0,
                     intent="Rest day (requested).", exercises=None)

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
                pick.update(workout_type="strength",
                            intent="Extra strength session (requested more strength this week).",
                            exercises=[dict(e) for e in _UPPER_BODY_STRENGTH_EXERCISES])
        else:  # "less"
            candidates = [s for s in sessions
                          if s["workout_type"] == "strength" and s["day_offset"] not in rest_requested]
            if candidates:
                pick = min(candidates, key=lambda s: s["target_tss"])
                pick.update(workout_type="rest", target_tss=0, duration_minutes=0,
                            intent="Rest (requested less strength this week).", exercises=None)

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
    existing_week = facts.get("existing_week") or []

    taper_note = ""
    if days_to_race is not None and 0 <= int(days_to_race) <= _TAPER_WINDOW_DAYS:
        taper_note = (
            f" The athlete has a race in {days_to_race} days — "
            "apply a taper: reduce weekly TSS to approximately 60% of normal "
            "and favour easy sessions."
        )

    allowed_str = ", ".join(f"{o} ({_DAY_NAMES[o]})" for o in sorted(allowed)) or "none — the week is fully covered already"
    rest_rule = ""
    if rest_requested:
        rest_rule = (
            f"7. The athlete asked for these day_offsets to be REST: "
            f"{', '.join(str(o) for o in sorted(rest_requested))}. You MUST include an explicit "
            "session for each of these — workout_type=\"rest\", target_tss=0 — do not omit them.\n"
        )
    exercises_rule_n = 8 if rest_requested else 7
    long_run_rule_n = exercises_rule_n + 1
    consec_rule_n = long_run_rule_n + 1

    system = (
        "You are a running coach producing a structured training plan for the "
        "REMAINDER of the athlete's current week — not a fresh Monday-to-Sunday "
        "week. Return ONLY a JSON object matching the schema. "
        "SAFETY RULES — you MUST follow these:\n"
        f"1. Total weekly TSS across all sessions must not exceed {round(max(float(trailing), FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND)} "
        f"(ACWR safe ceiling: trailing 28-day weekly average {round(float(trailing))} × {ACWR_HIGH_BOUND}).\n"
        "2. Each session's target_tss must be between 0 and 400.\n"
        "3. You may propose at most 7 sessions.\n"
        "4. workout_type must be exactly one of: run, strength, plyo, rest.\n"
        "5. Only propose sessions for these day_offsets — every other day is already "
        f"scheduled, already logged, or in the past: {allowed_str}.\n"
        f"6. Respect ramp limits: do not increase weekly TSS by more than 30% above the trailing average.{taper_note}\n"
        f"{rest_rule}"
        f"{exercises_rule_n}. For every workout_type=\"strength\" or \"plyo\" session, you MUST include "
        "an `exercises` array of 4-10 entries — a real session, not a placeholder. Each entry is "
        "{block, name, sets, reps, load}: `block` groups exercises like a coach would write a session "
        "(e.g. \"Warm-up\", \"Main\", \"Core\", \"Hip\", \"Accessories\" — your choice, whatever fits); "
        "`sets` is an integer; `reps` and `load` are short descriptive strings, not always plain numbers "
        "(e.g. reps: \"10\", \"12\", \"30s hold\"; load: \"bodyweight\", \"moderate\", \"~10-14kg per hand\", "
        "\"light band, per side\"). Example entry: "
        '{"block": "Main", "name": "Back squat", "sets": 3, "reps": "8", "load": "moderate"}. '
        "Never leave exercises empty or omitted for strength/plyo. Do not include exercises for run/rest "
        "sessions (leave it null or omit it).\n"
        f"{long_run_rule_n}. Identify the single 'run' session with the highest target_tss as the "
        "week's LONG RUN. The day immediately before it must NOT be another hard/interval run "
        "(no tempo/threshold/interval intent, no high-TSS run) — use rest, an easy run, or a "
        "non-run session there instead.\n"
        f"{consec_rule_n}. Do not schedule more than {_MAX_CONSECUTIVE_TRAINING_DAYS} consecutive "
        "training days without a rest or easy day — balance load against the athlete's current CTL/ATL.\n"
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
                lines.append(f"  - day_offset {d['day_offset']} ({_DAY_NAMES[d['day_offset']]} {d.get('date', '')}): " + "; ".join(bits))
        if lines:
            user += "Current schedule this week (do not duplicate or contradict these):\n" + "\n".join(lines) + "\n"
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
    if notes:
        user += f"Additional notes from the athlete: {notes}\n"
    user += (
        f"\nPropose sessions ONLY for day_offset(s) {allowed_str} "
        "(day_offset 0=Monday through 6=Sunday, same numbering as the current week). "
        "Each session needs day_offset, workout_type, target_tss, duration_minutes, and a one-line intent. "
        "strength/plyo sessions additionally need the exercises breakdown (see the safety rules above) — "
        "not every open day needs a session; use rest as needed."
    )

    return system, user


def build_signature(facts: dict) -> str:
    """SHA-256 signature over the facts dict (stable key ordering)."""
    serialised = json.dumps(facts, sort_keys=True, default=str)
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
                },
                # Groq/OpenAI strict structured-output mode requires EVERY
                # property to be listed here — "optional" is expressed via a
                # nullable type (exercises: ["array","null"]), not omission.
                "required": ["day_offset", "workout_type", "target_tss", "duration_minutes", "intent", "exercises"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


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
    )


# ── Orchestration ─────────────────────────────────────────────────────────────
#
# The same feature — LLM plan → validate → retry-with-feedback → template
# fallback — implemented three ways so their outputs can be A/B'd on real data.
# All share the domain primitives above; they differ only in HOW the retry loop
# is expressed. Selected per-request via the PLAN_ORCH env var; unset keeps the
# original single-shot behaviour so nothing changes by default. Every path is
# fallback-safe: any failure (LLM off, network, missing optional dependency,
# retries exhausted) returns the deterministic template.

_MAX_PLAN_ATTEMPTS = 3
_VALID_ORCH = {"single", "plain", "langgraph", "pydantic_ai"}


def _plan_orch() -> str:
    orch = os.getenv("PLAN_ORCH", "").strip().lower()
    return orch if orch in _VALID_ORCH else "single"


def _template_result(facts: dict, attempts: int, orch: str) -> dict:
    return {
        "suggestions": fallback_suggestions(facts),
        "source": "fallback",
        "attempts": attempts,
        "orch": orch,
    }


# 1. Single-shot (original behaviour) — one call, one validation, no retry.
def _orch_single(facts: dict) -> dict:
    raw = _call_llm(facts)
    if raw is not None:
        suggestions = raw.get("suggestions", [])
        if validate_suggestions(suggestions, facts):
            return {"suggestions": suggestions, "source": "llm", "attempts": 1, "orch": "single"}
        _log.warning("LLM plan_suggestion output failed validation — using fallback")
    return _template_result(facts, attempts=1 if raw is not None else 0, orch="single")


# 2. Plain Python — an explicit while loop with reflection feedback.
def _orch_plain(facts: dict) -> dict:
    feedback = ""
    attempt = 0
    for attempt in range(1, _MAX_PLAN_ATTEMPTS + 1):
        raw = _call_llm(facts, feedback)
        if raw is None:
            return _template_result(facts, attempts=attempt - 1, orch="plain")
        suggestions = raw.get("suggestions", [])
        errs = validation_errors(suggestions, facts)
        if not errs:
            return {"suggestions": suggestions, "source": "llm", "attempts": attempt, "orch": "plain"}
        _log.warning("plan(plain) retry %d rejected: %s", attempt, errs)
        feedback = _feedback_block(errs)
    return _template_result(facts, attempts=attempt, orch="plain")


# 3. LangGraph — the loop as nodes + a conditional edge (validate → generate).
def _orch_langgraph(facts: dict) -> dict:
    try:
        from backend.services.plan_orch_langgraph import run as _run
    except Exception as exc:  # dependency missing / import error → fallback-safe
        _log.warning("plan(langgraph) unavailable (%s) — using fallback", exc)
        return _template_result(facts, attempts=0, orch="langgraph")
    try:
        return _run(facts, _MAX_PLAN_ATTEMPTS)
    except Exception as exc:
        _log.warning("plan(langgraph) failed (%s) — using fallback", exc)
        return _template_result(facts, attempts=0, orch="langgraph")


# 4. Pydantic AI — a typed agent whose output_validator raises ModelRetry.
def _orch_pydantic_ai(facts: dict) -> dict:
    try:
        from backend.services.plan_orch_pydantic_ai import run as _run
    except Exception as exc:
        _log.warning("plan(pydantic_ai) unavailable (%s) — using fallback", exc)
        return _template_result(facts, attempts=0, orch="pydantic_ai")
    try:
        return _run(facts, _MAX_PLAN_ATTEMPTS)
    except Exception as exc:
        _log.warning("plan(pydantic_ai) failed (%s) — using fallback", exc)
        return _template_result(facts, attempts=0, orch="pydantic_ai")


_ORCHESTRATORS = {
    "single": _orch_single,
    "plain": _orch_plain,
    "langgraph": _orch_langgraph,
    "pydantic_ai": _orch_pydantic_ai,
}


def get_suggestions_from_facts(facts: dict) -> dict:
    """Attempt LLM suggestions via the selected orchestrator; fall back to the
    deterministic template if disabled or invalid.

    Returns {'suggestions': [...], 'source': 'llm'|'fallback', 'attempts': int,
    'orch': str}. Orchestrator chosen by PLAN_ORCH (default 'single').
    """
    orch = _plan_orch()
    return _ORCHESTRATORS[orch](facts)


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
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from backend.db import engine
    from backend.models import DailyReadiness, PlannedSession, Race, Workout
    from backend.services.training_load import current_load, daily_tss_series
    from backend.services.acwr import compute_acwr, HIGH_BOUND as _acwr_high
    from backend.utils.time import today_bangkok

    # BKK-local "today" — matches the app-wide convention (workout_date, week
    # windows) fixed in the reconcile.py timezone bug. Using server-local
    # date.today() here would misjudge which day_offset is "today" whenever
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

        # Next upcoming A-priority race
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

        existing_week: list[dict] = []
        allowed_offsets: list[int] = []
        for offset in range(7):
            d = target_week_start + timedelta(days=offset)
            w = workouts_by_date.get(d)
            p = planned_by_date.get(d)
            entry = {
                "day_offset": offset,
                "date": d.isoformat(),
                "has_workout": w is not None,
                "workout_type": (w.workout_type if w is not None else None),
                "has_planned": p is not None,
                "planned_type": (p.session_type if p is not None else None),
                "planned_status": (p.status if p is not None else None),
            }
            existing_week.append(entry)
            if offset >= start_offset and w is None and p is None:
                allowed_offsets.append(offset)
    finally:
        if _own_session:
            db.close()

    rest_days = sorted({int(d) for d in (preferred_rest_days or []) if int(d) in allowed_offsets})
    emphasis = (strength_emphasis or "same").strip().lower()
    if emphasis not in _VALID_STRENGTH_EMPHASIS:
        emphasis = "same"
    notes_clean = (notes or "").strip()[:300]

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
        "allowed_offsets": allowed_offsets,
        "existing_week": existing_week,
        "preferred_rest_days": rest_days,
        "strength_emphasis": emphasis,
        "notes": notes_clean,
    }

    if next_race is not None:
        facts["days_to_next_race"] = (next_race.race_date - today).days
        facts["next_race_distance_km"] = float(next_race.distance_km) if next_race.distance_km else None
        facts["next_race_goal_time_seconds"] = next_race.goal_time_seconds

    return facts


def get_suggestions(
    user_id: str,
    db=None,
    *,
    week_start: "date | None" = None,
    preferred_rest_days: list[int] | None = None,
    strength_emphasis: str | None = None,
    notes: str | None = None,
) -> dict:
    """Full entry point: assemble facts → cache-aware LLM call → fallback.

    Returns {'facts': {...}, 'suggestions': [...], 'source': 'llm' | 'fallback',
    'attempts': int, 'orch': str}. The cache is keyed per-orchestrator (surface
    carries the PLAN_ORCH value) so switching orchestrators to A/B compare on the
    same facts returns each one's own result instead of colliding on the cache.
    week_start/preferred_rest_days/strength_emphasis/notes are the athlete's
    scoping + preference input (see assemble_facts) — they flow into facts and
    therefore into the cache signature, so different input never collides.
    """
    facts = assemble_facts(
        user_id, db=db, week_start=week_start,
        preferred_rest_days=preferred_rest_days,
        strength_emphasis=strength_emphasis, notes=notes,
    )
    sig = build_signature(facts)
    orch = _plan_orch()
    surface = _SURFACE if orch == "single" else _SURFACE + ":" + orch

    # Cache lookup via get_or_generate.
    def _generate():
        return get_suggestions_from_facts(facts)

    cached_or_new = llm_svc.get_or_generate(
        user_id=str(user_id),
        surface=surface,
        signature=sig,
        generate_fn=_generate,
    )

    if cached_or_new is not None:
        return {"facts": facts, **cached_or_new}

    # LLM unavailable — always fallback gracefully.
    fallback = get_suggestions_from_facts(facts)
    return {"facts": facts, **fallback}
