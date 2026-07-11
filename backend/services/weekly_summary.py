"""Weekly summary narrative service (issue #1314; verdict-aware since the
load-metric single-source-of-truth fix).

Exposes:
  assemble_facts(...)           — pure function: weekly metrics from pre-fetched data
  build_fallback_narrative(...) — pure function: deterministic text from facts,
                                   states the verdict explicitly
  numeral_guard_passes(...)     — validate LLM numbers against facts string
  validate_summary(...)         — pure function: list of violation reasons (empty = valid);
                                   rejects narration that contradicts the verdict
  build_signature(...)          — cache key for llm_generations
  get_narrative(...)            — LLM (DEEP tier) + retry-once-then-fallback + cache wrapper
  build_response(...)           — final response shape

Verdict-aware (backend/services/training_verdict.py): the LLM is never asked
to decide whether the athlete should back off, hold, or build — that verdict
is computed deterministically upstream (from the Part-A training-load
snapshot) and passed into facts as a GIVEN. The LLM's only job is to explain
it in prose; validate_summary rejects any narration that contradicts it
(recommending an increase when verdict != "build") and the plain-Python
retry loop below gives it one chance to fix that before falling back to the
deterministic template — matching the existing LLM_COACH_ENABLED fallback
contract. No LangGraph — see docs/calculations/acwr-guardrail.md.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Optional

import backend.services.llm as llm
from backend.utils.log import get_logger

_log = get_logger(__name__)

_MAX_NARRATIVE_LEN = 800

# Retry-once-then-fallback — matches plan_suggestions.py's contract.
_MAX_SUMMARY_ATTEMPTS = 2

# Language that reads as "increase your training load" — forbidden in the
# narrative whenever verdict != "build". Deliberately broad (false positives
# just cost one retry); a missed increase-recommendation is the actual bug
# this guards against.
_INCREASE_LANGUAGE_PATTERNS = (
    r"\bincrease\b", r"\bincreasing\b", r"\bramp(ing)?\s+up\b", r"\bramp\s+it\s+up\b",
    r"\badd(ing)?\s+(more\s+)?(volume|load|tss|mileage|intensity)\b",
    r"\bpush(ing)?\s+harder\b", r"\bmore\s+training\b", r"\bstep(ping)?\s+up\b",
    r"\bbuild(ing)?\s+(on|from)\s+this\b", r"\bkeep\s+(pushing|building|ramping)\b",
)

# A match is legitimate hold/back_off language, not a contradiction, when it's
# negated ("don't add load", "avoid increasing volume") — scan a short window
# before the match for one of these instead of trying variable-length
# lookbehind (Python re doesn't support it).
_NEGATION_WORDS = (
    "don't", "do not", "doesn't", "does not", "won't", "avoid", "without",
    "not to", "never", "hold off", "holding off", "no need to", "shouldn't",
    "skip", "resist the urge to",
)
_NEGATION_WINDOW = 25


def _increase_language_violation(lowered: str) -> bool:
    """True iff the text contains un-negated increase-language."""
    for pat in _INCREASE_LANGUAGE_PATTERNS:
        for m in re.finditer(pat, lowered):
            prefix = lowered[max(0, m.start() - _NEGATION_WINDOW):m.start()]
            if not any(neg in prefix for neg in _NEGATION_WORDS):
                return True
    return False

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
    verdict: Optional[dict] = None,
) -> dict:
    """Assemble weekly summary facts from pre-fetched data.

    Pure function — no database access, no network calls.
    All raw data is passed in by the endpoint caller.

    verdict: the deterministic training_verdict.compute_verdict() result
        (computed by the caller from the Part-A snapshot at week_end), or
        None. When provided, its fields land in facts as GIVENS the LLM must
        explain, never derive or contradict — see build_prompt()/
        validate_summary() below.
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
        "verdict": (verdict or {}).get("verdict"),
        "verdict_reason": (verdict or {}).get("reason"),
        "verdict_modifiers": (verdict or {}).get("modifiers") or [],
        "expected_ctl_in_3w": (verdict or {}).get("expected_ctl_in_3w"),
        "weeks_to_converge": (verdict or {}).get("weeks_to_converge"),
        "converge_date": (verdict or {}).get("converge_date"),
    }


# ---------------------------------------------------------------------------
# Fallback narrative — pure function
# ---------------------------------------------------------------------------

def _verdict_sentence(facts: dict) -> str:
    """Deterministic verdict statement — states the given verdict plainly,
    with the convergence estimate for anything other than "build". Used by
    BOTH the fallback template and as ground truth for validate_summary's
    contradiction check; the LLM path is instructed to explain this, never
    derive or contradict it."""
    verdict = facts.get("verdict")
    if not verdict:
        return ""
    reason = facts.get("verdict_reason") or ""
    if verdict == "back_off":
        sentence = f"Back off this week: {reason}."
    elif verdict == "hold":
        sentence = f"Hold current load, don't add: {reason}."
    else:
        sentence = f"Build: {reason}."

    weeks = facts.get("weeks_to_converge")
    converge_date = facts.get("converge_date")
    expected_ctl = facts.get("expected_ctl_in_3w")
    if verdict != "build" and weeks and converge_date and expected_ctl is not None:
        sentence += (
            f" CTL is estimated to reach ~{expected_ctl:.0f} within 3 weeks, bringing load back "
            f"under the guardrail around {converge_date} (~{weeks} week{'s' if weeks != 1 else ''})."
        )
    return sentence


def build_fallback_narrative(facts: dict) -> str:
    """Build a deterministic coach-style bullet summary from facts.

    Pure function — no I/O. Always states the verdict when one is present in
    facts (verdict-aware since the load-metric fix) — this is the template
    LLM_COACH_ENABLED=0 falls back to, so the verdict must reach the athlete
    even with the LLM entirely off.
    """
    count = facts.get("workout_count", 0)
    verdict_sentence = _verdict_sentence(facts)
    if not count:
        base = (
            "No training logged this week. Rest is part of the plan — "
            "come back strong next week."
        )
        return (base + " " + verdict_sentence) if verdict_sentence else base

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

    # Verdict (deterministic — see _verdict_sentence)
    if verdict_sentence:
        lines.append(verdict_sentence)

    # Modifier reasons — state which wellness rule caused a downgrade
    modifiers = facts.get("verdict_modifiers") or []
    if modifiers:
        parts = []
        for m in modifiers:
            rule = m.get("rule", "")
            val = m.get("value")
            if rule == "low_readiness_today":
                parts.append(f"today's readiness score ({val:.0f})" if isinstance(val, float) else f"today's readiness score ({val})")
            elif rule == "low_readiness_trend":
                parts.append(f"7-day readiness average ({val:.0f})" if isinstance(val, float) else f"7-day readiness average ({val})")
            elif rule == "illness_or_severe_injury":
                parts.append(f"active {val}")
            elif rule == "niggle_or_minor_injury":
                parts.append(f"active {val}")
        if parts:
            lines.append(f"Downgrade reason: {'; '.join(parts)}.")

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

    # Subjective signals — the report closes by asking, not only asserting
    # (spec B.5). A fixed question keeps the deterministic template honest
    # about not being the whole picture.
    lines.append("How's sleep, resting HR, and how do your legs feel in the morning?")

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
# Verdict-contradiction validation
# ---------------------------------------------------------------------------

def validate_summary(text: str, facts: dict) -> list[str]:
    """Return a list of human-readable violation reasons (empty == valid).

    Same numeral-guard/length checks get_narrative already applied, PLUS the
    verdict checks: reject narration that recommends an increase when
    verdict != "build", and require the verdict itself to be stated (not
    just implied) so the athlete sees the same word the deterministic
    template would have used. Each reason is fed straight back to the model
    as retry feedback — see _feedback_block.
    """
    errs: list[str] = []

    if not text:
        errs.append("narrative is empty")
        return errs

    if len(text) > _MAX_NARRATIVE_LEN:
        errs.append(f"narrative exceeds {_MAX_NARRATIVE_LEN} characters")

    facts_str = _facts_to_str(facts)
    if not numeral_guard_passes(text, facts_str):
        errs.append("narrative contains a number that does not appear in the given data")

    verdict = facts.get("verdict")
    if verdict:
        lowered = text.lower()
        if verdict != "build" and _increase_language_violation(lowered):
            errs.append(
                f"narrative recommends increasing training load, but the given verdict is "
                f"{verdict!r} — never recommend an increase when verdict is 'hold' or 'back_off'"
            )
        verdict_word = verdict.replace("_", " ")
        if verdict_word not in lowered and verdict not in lowered:
            errs.append(
                f"narrative must explicitly state the verdict ({verdict_word!r}) — "
                "explain it, do not omit or re-derive it"
            )

    return errs


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
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            # Both the fallback template and the LLM display numbers rounded
            # to varying precision (CTL/TSB at .1f, ACWR at .2f, convergence
            # CTL at .0f) — include those roundings so numeral_guard_passes
            # matches on the displayed form, not just the raw stored value.
            for nd in (0, 1, 2):
                parts.append(f"{v:.{nd}f}")
    # Also include PR names in facts_str so guard doesn't flag them
    for pr in facts.get("prs_achieved") or []:
        parts.append(str(pr.get("value_numeric", "")))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# LLM + cache wrapper
# ---------------------------------------------------------------------------

def _feedback_block(errs: list[str]) -> str:
    """Correction feedback appended to the user prompt on a retry — same
    contract as plan_suggestions.py's _feedback_block."""
    return (
        "\n\nYour previous answer was REJECTED for these reasons:\n- "
        + "\n- ".join(errs)
        + "\nFix every issue and return corrected JSON matching the schema."
    )


def _build_prompt(facts: dict, facts_str: str) -> tuple[str, str]:
    """Build (system_prompt, user_prompt). The verdict (when present) is a
    GIVEN the model must explain, never derive or contradict — it must not
    recommend an increase when verdict != "build", and must state the
    verdict explicitly (validate_summary enforces both)."""
    system = (
        "You are a performance coach writing a brief weekly training report. "
        "Rules: 2-4 sentences max, use ONLY the numbers given in the data, "
        "no medical advice, no injury warnings unless explicitly flagged in the data, "
        "no emoji, supportive and direct coach tone. "
        "End with one short question about a subjective signal not in the data — sleep, "
        "resting HR, or how their legs feel in the morning — the report should ask, not only assert."
    )

    verdict = facts.get("verdict")
    if verdict:
        verdict_word = verdict.replace("_", " ")
        system += (
            f"\nGIVEN VERDICT (do not derive, do not contradict): {verdict_word!r} — "
            f"{facts.get('verdict_reason', '')}. State this verdict explicitly in the narrative, "
            "in your own words. "
        )
        if verdict != "build":
            system += (
                "The athlete must NOT increase training load this week — do not recommend adding "
                "volume, intensity, or mileage in any form. "
            )
            if facts.get("weeks_to_converge") and facts.get("converge_date"):
                system += (
                    f"You may mention that load is expected back within the safe range in "
                    f"~{facts['weeks_to_converge']} week(s), around {facts['converge_date']} — "
                    "label this as an estimate, not a guarantee."
                )
        modifiers = facts.get("verdict_modifiers") or []
        if modifiers:
            mod_desc = []
            for m in modifiers:
                rule = m.get("rule", "")
                val = m.get("value")
                if rule == "low_readiness_today":
                    mod_desc.append(f"today's readiness score is {val}")
                elif rule == "low_readiness_trend":
                    mod_desc.append(f"7-day readiness average is {val}")
                elif rule == "illness_or_severe_injury":
                    mod_desc.append(f"active {val}")
                elif rule == "niggle_or_minor_injury":
                    mod_desc.append(f"active {val}")
            if mod_desc:
                system += (
                    f" The verdict was downgraded due to wellness signals: {'; '.join(mod_desc)}. "
                    "Mention this reason when explaining the verdict. "
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

    return system, user_prompt


def get_narrative(
    user_id: str,
    week_start: str,
    facts: dict,
    *,
    db=None,
) -> tuple[str, str]:
    """Return (narrative, source) where source is 'llm' or 'fallback'.

    Uses GROQ_MODEL_DEEP tier and caches in llm_generations. Retries once
    with the specific validate_summary violation appended (plain Python
    loop, no LangGraph — matches plan_suggestions.py's contract), then falls
    back to the deterministic template. The retry loop runs INSIDE the
    cached generate_fn so the cache key covers the whole attempt sequence,
    not each individual attempt.
    """
    fallback = build_fallback_narrative(facts)

    if not llm.llm_enabled():
        return fallback, "fallback"

    facts_str = _facts_to_str(facts)
    sig = build_signature(user_id, week_start, facts)
    system, base_user_prompt = _build_prompt(facts, facts_str)

    def _generate():
        feedback = ""
        for attempt in range(1, _MAX_SUMMARY_ATTEMPTS + 1):
            raw = llm.complete_structured(
                system=system,
                user=base_user_prompt + feedback,
                schema_name="weekly_summary",
                json_schema=_NARRATIVE_JSON_SCHEMA,
                model_tier="deep",
            )
            if raw is None:
                # Transient generation failure — worth one retry, same as
                # plan_suggestions.py's orchestrator.
                _log.warning("weekly_summary attempt %d: LLM call failed/unavailable", attempt)
                continue
            text = raw.get("narrative", "")
            errs = validate_summary(text, facts)
            if not errs:
                return {"narrative": text}
            _log.warning("weekly_summary retry %d rejected: %s", attempt, errs)
            feedback = _feedback_block(errs)
        return None

    result = llm.get_or_generate(
        user_id=user_id,
        surface="weekly_summary",
        signature=sig,
        generate_fn=_generate,
        db=db,
        model_tier="deep",
    )

    if result is None:
        return fallback, "fallback"

    text = result.get("narrative", "")
    if not text:
        return fallback, "fallback"

    # Belt-and-suspenders: re-validate even a cache hit (a cached row from
    # before this validation existed could otherwise slip through).
    if validate_summary(text, facts):
        _log.warning("weekly_summary: cached narrative fails current validation, using fallback")
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
