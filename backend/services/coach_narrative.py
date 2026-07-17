"""Coach narrative: prompts, validators, deterministic fallback, LLM call.

Produces Now / Focus / Dream / Reflection Markdown from coach_facts.
LLM may only use numerals present in facts['required_numerals'].
"""

from __future__ import annotations

import os
import re
from typing import Any

from backend.utils.log import get_logger

_log = get_logger(__name__)

SECTION_ORDER = ("now", "focus", "dream", "reflection")
SECTION_HEADERS = {
    "now": "## Now",
    "focus": "## Focus",
    "dream": "## Dream",
    "reflection": "## Reflection",
}
MAX_TOTAL_CHARS = 2500
MIN_SECTION_CHARS = 24

_NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "now": {"type": "string"},
        "focus": {"type": "string"},
        "dream": {"type": "string"},
        "reflection": {"type": "string"},
    },
    "required": ["now", "focus", "dream", "reflection"],
    "additionalProperties": False,
}


def sections_to_text(sections: dict[str, str]) -> str:
    parts = []
    for key in SECTION_ORDER:
        body = (sections.get(key) or "").strip()
        parts.append(f"{SECTION_HEADERS[key]}\n{body}")
    return "\n\n".join(parts)


def parse_sections_from_text(text: str) -> dict[str, str]:
    """Split Markdown ## Now/Focus/Dream/Reflection into a dict."""
    if not text:
        return {k: "" for k in SECTION_ORDER}
    pattern = re.compile(
        r"^##\s+(Now|Focus|Dream|Reflection)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    out = {k: "" for k in SECTION_ORDER}
    if not matches:
        # Legacy weekly message — put everything in Now
        out["now"] = text.strip()
        return out
    for i, m in enumerate(matches):
        key = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if key in out:
            out[key] = text[start:end].strip()
    return out


def _fmt_unlock(load: dict) -> str:
    ud = load.get("unlock_date")
    if not ud:
        return "soon"
    try:
        from datetime import date
        d = date.fromisoformat(str(ud)[:10])
        return d.strftime("%-d %b")
    except Exception:
        return str(ud)


def compose_coach_narrative(facts: dict) -> str:
    """Deterministic four-section fallback from facts."""
    load = facts.get("load") or {}
    weight = facts.get("weight") or {}
    timeline = facts.get("timeline") or []
    constraints = facts.get("constraints") or []
    ranking = facts.get("lever_ranking") or {}
    projection = facts.get("projection") or {}
    focus_ranked = facts.get("focus_ranked") or []
    focus_noise = facts.get("focus_noise") or []
    dream = facts.get("dream") or {}
    reflection = facts.get("reflection") or {}

    # ── Now ──
    now_bits: list[str] = []
    if load.get("state") == "locked":
        hold = load.get("hold_tss")
        hold_s = f"~{hold} TSS" if hold is not None else "current TSS"
        now_bits.append(
            f"{load.get('reason') or 'ACWR elevated'}. "
            f"Hold {hold_s}; do not add volume. "
            f"ACWR converges ~{_fmt_unlock(load)} — "
            "CTL rises because you hold, not because you add."
        )
    elif load.get("state") == "available":
        now_bits.append(
            "Load lever available — safe to begin a progressive ramp this week."
        )
    else:
        now_bits.append("Training load data unavailable — log workouts to enable guidance.")

    if weight.get("phase") == "measurement":
        logged = weight.get("logged_days")
        tgt = 12
        now_bits.append(
            f"Weight is available immediately via measurement: "
            f"{logged if logged is not None else '?'}/{tgt} weigh-ins in 14 days — "
            "honest logging first, then a modest deficit."
        )
    elif weight.get("phase") == "deficit":
        kcal = weight.get("recommended_deficit_kcal")
        now_bits.append(
            f"Weight logging is consistent — a modest deficit"
            + (f" (~{kcal} kcal)" if kcal is not None else "")
            + " is available without stacking aggression on a ramp."
        )

    if timeline:
        steps = []
        for ph in timeline[:4]:
            d = ph.get("date") or ""
            directive = ph.get("directive") or ""
            steps.append(f"• {d}: {directive}" if d else f"• {directive}")
        now_bits.append("Sequence:\n" + "\n".join(steps))
    if constraints:
        now_bits.append("Constraint: " + constraints[0])

    # ── Focus ──
    focus_bits: list[str] = []
    if focus_ranked:
        top = focus_ranked[:2]
        focus_bits.append(
            "Priorities this week (order matters): "
            + "; ".join(
                f"#{r.get('rank') or i+1} {r.get('label')}"
                for i, r in enumerate(top)
            )
            + "."
        )
        for r in top:
            tr = r.get("tracking") or {}
            track = ""
            if tr.get("current") is not None and tr.get("target") is not None:
                track = f" Tracking {tr['current']}/{tr['target']}."
            elif tr.get("unlock_date"):
                track = f" Unlock ~{tr['unlock_date']}."
            focus_bits.append(f"{r.get('label')}: {r.get('rationale') or ''}{track}".strip())
        if focus_noise:
            focus_bits.append(
                "Noise until the top levers move: " + ", ".join(focus_noise) + "."
            )
    else:
        focus_bits.append(ranking.get("rationale") or "Insufficient data to rank levers.")

    # ── Dream ──
    dream_bits: list[str] = []
    sell = dream.get("sell_line_facts") or {}
    a_race = dream.get("a_race") or {}
    if sell.get("next_checkpoint_date"):
        dream_bits.append(
            f"Next checkpoint: {sell.get('next_checkpoint_label') or 'milestone'} "
            f"on {sell['next_checkpoint_date']}"
            + (
                f" targeting {sell['next_checkpoint_target']}"
                if sell.get("next_checkpoint_target")
                else ""
            )
            + "."
        )
    if a_race.get("goal_time_label") and a_race.get("date"):
        dream_bits.append(
            f"A-race goal {a_race.get('goal_time_label')} on {a_race.get('date')}."
        )
    for sc in (dream.get("scenarios") or [])[:3]:
        dream_bits.append(
            f"{sc.get('label')}: ~{sc.get('finish_label')}"
            + (f" ({sc.get('caveat')})" if sc.get("caveat") else "")
            + "."
        )
    if not dream_bits:
        if projection.get("full_compliance_label"):
            dream_bits.append(
                f"Full compliance trends ~{projection['full_compliance_label']} "
                f"{projection.get('distance_label') or ''}; "
                f"current trend ~{projection.get('current_trend_label')} "
                f"± {projection.get('uncertainty_min', 0)} min."
            )
        else:
            dream_bits.append(
                "Set an A-race and checkpoints on the Plan tab to unlock the dream ladder."
            )

    # ── Reflection ──
    ref_bits: list[str] = []
    planned = reflection.get("sessions_planned")
    completed = reflection.get("sessions_completed")
    if planned is not None:
        pct = reflection.get("adherence_pct")
        ref_bits.append(
            f"Last window: {completed}/{planned} planned sessions done"
            + (f" (~{pct}% adherence)." if pct is not None else ".")
        )
    for b in (reflection.get("benchmarks") or [])[:3]:
        met = b.get("met")
        flag = "met" if met is True else ("miss" if met is False else "track")
        ref_bits.append(f"Benchmark [{flag}] {b.get('id')}: {b.get('detail')}")
    nxt = reflection.get("next_session")
    if nxt:
        ref_bits.append(
            f"Next: {nxt.get('name')} on {nxt.get('date')} — {nxt.get('why_focus')}."
        )
    if not ref_bits:
        ref_bits.append("Log planned sessions to unlock adherence reflection.")

    return sections_to_text({
        "now": " ".join(now_bits) if len(now_bits) == 1 else "\n\n".join(now_bits),
        "focus": "\n\n".join(focus_bits),
        "dream": "\n\n".join(dream_bits),
        "reflection": "\n\n".join(ref_bits),
    })


def _extract_numerals(text: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(
        r"\d{4}-\d{2}-\d{2}|\d+:\d{2}(?::\d{2})?|\d+(?:\.\d+)?",
        text or "",
    ):
        found.append(m.group(0))
    return found


def _numeral_allowed(tok: str, allow: set[str]) -> bool:
    if tok in allow:
        return True
    # Normalize trivial float/int variants (1.50 vs 1.5)
    if "." in tok:
        try:
            f = float(tok)
            if str(int(round(f))) in allow:
                return True
            if f"{f:.1f}" in allow or f"{f:.2f}" in allow:
                return True
        except ValueError:
            pass
    # Time tokens: exact or share allowlist entry
    if ":" in tok:
        return any(tok == a or tok in a for a in allow if ":" in a)
    # ISO dates: exact only
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tok):
        return False
    return False


def validation_errors(sections: dict[str, str], facts: dict) -> list[str]:
    """Return list of validation problems; empty means accept."""
    errors: list[str] = []
    allow = set(facts.get("required_numerals") or [])
    # Also allow numerals freshly collected
    try:
        from backend.services.coach_facts import collect_required_numerals
        allow.update(collect_required_numerals(facts))
    except Exception:
        pass

    total = 0
    for key in SECTION_ORDER:
        body = (sections.get(key) or "").strip()
        total += len(body)
        if len(body) < MIN_SECTION_CHARS:
            errors.append(f"section '{key}' too short (<{MIN_SECTION_CHARS} chars)")

    if total > MAX_TOTAL_CHARS:
        errors.append(f"total length {total} exceeds {MAX_TOTAL_CHARS}")

    joined = " ".join(sections.get(k) or "" for k in SECTION_ORDER)
    for tok in _extract_numerals(joined):
        # Very common connective numbers always allowed (section ranks, weeks)
        if tok in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "14"}:
            continue
        if not _numeral_allowed(tok, allow):
            errors.append(f"numeral '{tok}' not in facts allowlist")

    return errors


def feedback_block(errors: list[str]) -> str:
    if not errors:
        return ""
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "Previous draft was rejected. Fix ALL of these without inventing new numbers "
        f"(only use facts allowlist):\n{lines}\n"
    )


def build_prompt(facts: dict, feedback: str = "") -> tuple[str, str]:
    """Return (system, user) prompts for structured narrative generation."""
    import json

    # Strip bulky plan_state from prompt payload
    slim = {k: v for k, v in facts.items() if k != "plan_state"}
    system = (
        "You are a direct, ambitious performance coach writing a weekly Home brief. "
        "Argue WHY ORDER MATTERS (hold load vs measure weight vs later ramp/deficit). "
        "Be warm but not fluffy. Never invent TSS, dates, times, or kg values — "
        "use ONLY numbers present in the facts JSON / required_numerals. "
        "No medical claims. No inventing workouts. "
        "IGNORE any repository files, CLAUDE.md, open editors, or prior chat — "
        "the ONLY source of truth is the facts JSON in the user message. "
        "Return JSON with keys now, focus, dream, reflection (plain prose, no ## headers)."
    )
    user = (
        f"{feedback}"
        "FACTS JSON follows. Write the four sections using ONLY these facts "
        "(do not claim facts are missing if the JSON below is non-empty):\n\n"
        f"{json.dumps(slim, default=str)[:12000]}"
    )
    return system, user


def coach_llm_mode() -> str:
    """Resolve narrative provider.

    Explicit ``COACH_LLM`` always wins. Otherwise:
      - worker (``PERFCOACH_ROLE=worker``) → ``claude_cli``
      - webapp / everything else → ``off`` (deterministic fallback only)

    This keeps ``claude -p`` off Render webapps; generation belongs on zeal-server.
    """
    explicit = (os.environ.get("COACH_LLM") or "").strip().lower()
    if explicit:
        return explicit
    if (os.environ.get("PERFCOACH_ROLE") or "").strip().lower() == "worker":
        return "claude_cli"
    return "off"


def call_llm_sections(facts: dict, feedback: str = "") -> dict[str, str] | None:
    """Generate sections via Claude CLI (worker) or HTTP LLM API.

    Provider selected by ``coach_llm_mode()`` / ``COACH_LLM``:
      - ``claude_cli`` / ``claude`` / ``cli`` — ``claude -p`` subscription (worker)
      - ``api`` — ``llm.complete_structured`` (requires ``LLM_COACH_ENABLED``)
      - ``off`` / ``fallback`` / ``none`` — skip; orch uses deterministic prose
    """
    system, user = build_prompt(facts, feedback)
    mode = coach_llm_mode()

    if mode in ("off", "fallback", "none", "disabled"):
        return None

    if mode in ("claude_cli", "claude", "cli"):
        from backend.services.coach_claude_cli import (
            call_claude_cli_sections,
            claude_cli_enabled,
        )

        if not claude_cli_enabled():
            _log.warning("COACH_LLM=claude_cli but claude binary missing; no generation")
            return None
        return call_claude_cli_sections(system, user)

    if mode in ("api", "http", "groq", "glm"):
        from backend.services.llm import llm_enabled, complete_structured

        if not llm_enabled():
            return None
        # Prefer deep tier for quality; fall back fast.
        result = complete_structured(
            system=system,
            user=user,
            schema_name="coach_weekly_narrative",
            json_schema=_NARRATIVE_SCHEMA,
            model_tier="deep",
            max_tokens=1600,
        )
        if result is None:
            result = complete_structured(
                system=system,
                user=user,
                schema_name="coach_weekly_narrative",
                json_schema=_NARRATIVE_SCHEMA,
                model_tier="fast",
                max_tokens=1200,
            )
        if not result:
            return None
        sections = {k: str(result.get(k) or "").strip() for k in SECTION_ORDER}
        if not any(sections.values()):
            return None
        return sections

    _log.warning("Unknown COACH_LLM=%r — expected claude_cli|api|off", mode)
    return None


def coach_orch_mode() -> str:
    return (os.environ.get("COACH_ORCH") or "langgraph").strip().lower()


def generate_narrative(facts: dict, max_attempts: int = 3) -> dict:
    """Run orch (langgraph or plain) → {text, sections, source, attempts}."""
    mode = coach_orch_mode()
    if mode == "langgraph":
        try:
            from backend.services.coach_orch_langgraph import run as lg_run
            return lg_run(facts, max_attempts=max_attempts)
        except Exception as exc:
            _log.warning("coach langgraph unavailable (%s); plain fallback path", exc)

    # Plain retry loop (same contract)
    errors: list[str] = []
    attempts = 0
    sections = None
    for _ in range(max_attempts):
        attempts += 1
        fb = feedback_block(errors)
        sections = call_llm_sections(facts, fb)
        if sections is None:
            errors = ["llm unavailable or empty"]
            continue
        errors = validation_errors(sections, facts)
        if not errors:
            return {
                "text": sections_to_text(sections),
                "sections": sections,
                "source": _source_label(),
                "attempts": attempts,
                "orch": "plain",
            }
    fb_text = compose_coach_narrative(facts)
    return {
        "text": fb_text,
        "sections": parse_sections_from_text(fb_text),
        "source": "fallback",
        "attempts": attempts,
        "orch": "plain",
    }


def _source_label() -> str:
    mode = coach_llm_mode()
    if mode in ("claude_cli", "claude", "cli"):
        return "claude_cli"
    if mode in ("api", "http", "groq", "glm"):
        return "llm"
    return "fallback"
