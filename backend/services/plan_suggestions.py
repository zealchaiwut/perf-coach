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

# Default template: day_offset → (workout_type, tss_fraction_of_weekly, duration_min)
# Fractions sum to 1.0 (excluding rest days at 0).
_TEMPLATE: list[dict] = [
    {"day_offset": 0, "workout_type": "run",      "tss_fraction": 0.20, "duration_base": 45, "intent": "Easy aerobic run — keep effort conversational."},
    {"day_offset": 1, "workout_type": "strength",  "tss_fraction": 0.15, "duration_base": 45, "intent": "Lower body strength — squats, lunges, hip work."},
    {"day_offset": 2, "workout_type": "run",       "tss_fraction": 0.25, "duration_base": 60, "intent": "Moderate-effort run or tempo intervals."},
    {"day_offset": 3, "workout_type": "rest",      "tss_fraction": 0.00, "duration_base": 0,  "intent": "Rest or light stretching."},
    {"day_offset": 4, "workout_type": "run",       "tss_fraction": 0.20, "duration_base": 50, "intent": "Easy aerobic run — maintain base fitness."},
    {"day_offset": 5, "workout_type": "strength",  "tss_fraction": 0.20, "duration_base": 45, "intent": "Upper body and core strength."},
    {"day_offset": 6, "workout_type": "run",       "tss_fraction": 0.00, "duration_base": 30, "intent": "Optional very easy jog or full rest."},
]


# ── Pure functions ────────────────────────────────────────────────────────────

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
    """
    errs: list[str] = []

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

    sessions = []
    for tmpl in _TEMPLATE:
        frac = tmpl["tss_fraction"]
        raw_tss = round(target_weekly * frac) if frac > 0 else 0
        sessions.append({
            "day_offset": tmpl["day_offset"],
            "workout_type": tmpl["workout_type"],
            "target_tss": raw_tss,
            "duration_minutes": tmpl["duration_base"],
            "intent": tmpl["intent"],
        })

    return sessions


def build_prompt(facts: dict) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the LLM suggestion call."""
    trailing = facts.get("trailing_28d_weekly_avg_tss", 0.0)
    headroom = facts.get("acwr_headroom_tss", 0.0)
    ctl = facts.get("ctl", 0.0)
    atl = facts.get("atl", 0.0)
    tsb = facts.get("tsb", 0.0)
    days_to_race = facts.get("days_to_next_race")
    readiness_trend = facts.get("readiness_trend", [])

    taper_note = ""
    if days_to_race is not None and 0 <= int(days_to_race) <= _TAPER_WINDOW_DAYS:
        taper_note = (
            f" The athlete has a race in {days_to_race} days — "
            "apply a taper: reduce weekly TSS to approximately 60% of normal "
            "and favour easy sessions."
        )

    system = (
        "You are a running coach producing a structured next-week training plan. "
        "Return ONLY a JSON object matching the schema. "
        "SAFETY RULES — you MUST follow these:\n"
        f"1. Total weekly TSS across all sessions must not exceed {round(max(float(trailing), FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND)} "
        f"(ACWR safe ceiling: trailing 28-day weekly average {round(float(trailing))} × {ACWR_HIGH_BOUND}).\n"
        "2. Each session's target_tss must be between 0 and 400.\n"
        "3. You may propose at most 7 sessions.\n"
        "4. workout_type must be exactly one of: run, strength, plyo, rest.\n"
        "5. Include at least one rest day.\n"
        f"6. Respect ramp limits: do not increase weekly TSS by more than 30% above the trailing average.{taper_note}\n"
    )

    trend_str = ", ".join(str(v) for v in (readiness_trend or [])[-7:]) or "no data"

    user = (
        f"Current training load: CTL={ctl}, ATL={atl}, TSB={tsb}.\n"
        f"Trailing 28-day weekly average TSS: {trailing}.\n"
        f"ACWR headroom (how much more TSS is safe this week): {round(float(headroom))}.\n"
        f"Recent readiness scores (last {len(readiness_trend or [])} days): {trend_str}.\n"
    )
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
    user += (
        "\nPropose a 7-day training week (day_offset 0=Monday through 6=Sunday). "
        "Each session needs day_offset, workout_type, target_tss, duration_minutes, and a one-line intent. "
        "Not every day needs a session — use rest days as needed."
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
                },
                "required": ["day_offset", "workout_type", "target_tss", "duration_minutes", "intent"],
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

def assemble_facts(user_id: str, db=None) -> dict:
    """Assemble training facts for a user from the database.

    Reads: CTL/ATL/TSB, 7-day and 28-day TSS, readiness trend, next race,
    and ACWR headroom.
    """
    from datetime import date as _date

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from backend.db import engine
    from backend.models import DailyReadiness, Race
    from backend.services.training_load import current_load, daily_tss_series
    from backend.services.acwr import compute_acwr, HIGH_BOUND as _acwr_high

    today = _date.today()

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
    finally:
        if _own_session:
            db.close()

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
    }

    if next_race is not None:
        facts["days_to_next_race"] = (next_race.race_date - today).days
        facts["next_race_distance_km"] = float(next_race.distance_km) if next_race.distance_km else None
        facts["next_race_goal_time_seconds"] = next_race.goal_time_seconds

    return facts


def get_suggestions(user_id: str, db=None) -> dict:
    """Full entry point: assemble facts → cache-aware LLM call → fallback.

    Returns {'facts': {...}, 'suggestions': [...], 'source': 'llm' | 'fallback',
    'attempts': int, 'orch': str}. The cache is keyed per-orchestrator (surface
    carries the PLAN_ORCH value) so switching orchestrators to A/B compare on the
    same facts returns each one's own result instead of colliding on the cache.
    """
    facts = assemble_facts(user_id, db=db)
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
