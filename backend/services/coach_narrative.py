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
MAX_TOTAL_CHARS = 2800
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


def _fmt_day(iso: str | None) -> str:
    if not iso:
        return "soon"
    try:
        from datetime import date
        d = date.fromisoformat(str(iso)[:10])
        return d.strftime("%-d %B")
    except Exception:
        return str(iso)


def compose_coach_narrative(facts: dict) -> str:
    """Deterministic fallback — consultative coach tone, facts-only."""
    load = facts.get("load") or {}
    weight = facts.get("weight") or {}
    timeline = facts.get("timeline") or []
    ranking = facts.get("lever_ranking") or {}
    projection = facts.get("projection") or {}
    focus_ranked = facts.get("focus_ranked") or []
    focus_noise = facts.get("focus_noise") or []
    dream = facts.get("dream") or {}
    reflection = facts.get("reflection") or {}
    goal = facts.get("goal") or {}
    praise = facts.get("praise") or reflection.get("praise") or []
    volume_mix = facts.get("volume_mix") or {}

    # ── Now ──
    now_bits: list[str] = []
    if load.get("deload_week"):
        now_bits.append(
            load.get("deload_rationale")
            or "This is a deload week — keep it quiet on purpose."
        )
        if load.get("ramp_caution_text"):
            now_bits.append(load["ramp_caution_text"])
        gap = load.get("ctl_gap_to_target")
        if gap:
            now_bits.append(
                f"Fitness is still the big time lever: you're ~{gap:.0f} CTL short "
                f"of what a {projection.get('goal_label') or goal.get('target_time_label') or 'goal'} "
                "needs, and that only closes with consistent weeks after the deload."
            )
    elif load.get("state") == "locked":
        hold = load.get("hold_tss")
        hold_s = f"~{hold} TSS/week" if hold is not None else "this week's TSS"
        now_bits.append(
            f"{load.get('reason') or 'ACWR is elevated'}. "
            f"Hold {hold_s}; do not add volume. "
            f"Unlock ~{_fmt_unlock(load)}."
        )
    elif load.get("state") == "available":
        acwr = load.get("acwr")
        acwr_bit = f"ACWR is {acwr} — " if acwr is not None else ""
        ramp_end = None
        for ph in timeline:
            if (ph.get("phase") or "").lower() in ("ramp", "build") or (
                "ramp" in (ph.get("directive") or "").lower()
            ):
                ramp_end = ph.get("end_date") or ph.get("date")
        line = f"You're clear to resume the ramp. {acwr_bit}"
        if ramp_end:
            line += f"Go up ~5% a week through {_fmt_day(ramp_end)}. That's it — no heroics."
        else:
            line += "Go up ~5% a week. That's it — no heroics, just don't miss weeks."
        now_bits.append(line)
        if load.get("ramp_caution_text"):
            now_bits.append(load["ramp_caution_text"])
        gap = load.get("ctl_gap_to_target")
        if gap:
            now_bits.append(
                f"Fitness is where the time is: you're ~{gap:.0f} CTL short of the "
                f"{projection.get('goal_label') or 'goal'} target, and that only closes "
                "with consistent weeks."
            )
    else:
        now_bits.append("Training load data is thin — log workouts so guidance can speak.")

    if weight.get("phase") == "measurement":
        logged = weight.get("logged_days")
        win = weight.get("window_days") or 14
        tgt = 12
        deficit_when = None
        for ph in timeline:
            if "deficit" in (ph.get("directive") or "").lower() or (
                ph.get("phase") or ""
            ).lower() in ("cut-end", "deficit"):
                deficit_when = ph.get("date")
                break
        payoff = weight.get("payoff_label")
        cut = weight.get("payoff_cut_kg")
        payoff_bit = ""
        if payoff and cut:
            payoff_bit = (
                f" If you eventually lose ~{cut:.0f} kg with fitness intact, "
                f"the same engine projects closer to {payoff} — that's the prize, "
                "and noisy weigh-ins can't unlock it yet."
            )
        now_bits.append(
            "Don't touch your calories yet.\n\n"
            f"You've logged {logged if logged is not None else '?'} of the last {tgt} "
            f"weigh-ins ({win}-day window). That's not enough to tell a real trend "
            f"from water weight.{payoff_bit} Weigh in every morning until you hit "
            f"{tgt} of {14}."
            + (
                f" Then we talk food around {_fmt_day(deficit_when)}."
                if deficit_when
                else " Then we talk food."
            )
        )
    elif weight.get("phase") == "deficit":
        kcal = weight.get("recommended_deficit_kcal")
        now_bits.append(
            "Weight logging is consistent — a modest deficit"
            + (f" (~{kcal} kcal)" if kcal is not None else "")
            + " is fair without stacking aggression on the ramp."
        )

    # ── Focus ──
    focus_bits: list[str] = []
    if focus_ranked:
        top = focus_ranked[:2]
        focus_bits.append("Two things this week:" if len(top) >= 2 else "This week:")
        for i, r in enumerate(top):
            rid = r.get("id") or ""
            tr = r.get("tracking") or {}
            if "weight" in rid:
                focus_bits.append(
                    f"{i + 1}. Weigh in daily. Get to "
                    f"{tr.get('current', '?')}/{tr.get('target', 12)}. "
                    "That's the gate before we touch food"
                    + (
                        f" — and the path to ~{weight.get('payoff_label')} if you "
                        f"later cut ~{weight.get('payoff_cut_kg'):.0f} kg."
                        if weight.get("payoff_label") and weight.get("payoff_cut_kg")
                        else "."
                    )
                )
            elif rid in ("respect_deload", "ramp_caution", "hold_load"):
                focus_bits.append(
                    f"{i + 1}. {(r.get('rationale') or r.get('label') or '').rstrip('.')}."
                )
            elif rid in ("long_run_fueling", "long_run"):
                longs = volume_mix.get("recent_longs") or []
                if longs and rid == "long_run_fueling":
                    bits = " and ".join(
                        f"{x.get('mins')} min ({_fmt_day(x.get('date'))})"
                        for x in longs[:2]
                    )
                    focus_bits.append(
                        f"{i + 1}. Your long runs are happening — {bits}. "
                        "Keep that; the work now is late-run fueling so efficiency "
                        "doesn't fade when the marathon punishes it."
                    )
                else:
                    focus_bits.append(
                        f"{i + 1}. {(r.get('rationale') or r.get('label') or '').rstrip('.')}."
                    )
            else:
                focus_bits.append(
                    f"{i + 1}. {(r.get('rationale') or r.get('label') or '').rstrip('.')}."
                )
        if focus_noise:
            focus_bits.append(
                ", ".join(str(n).replace("_", " ") for n in focus_noise[:4])
                + " — fine ideas, none beat these right now."
            )
        nxt = reflection.get("next_session")
        if nxt:
            why = nxt.get("why_focus") or ""
            rank_m = re.search(r"Focus #(\d+)", why or "")
            rank_bit = f" That's Focus #{rank_m.group(1)}." if rank_m else ""
            focus_bits.append(
                f"Next up: {nxt.get('name')} on {_fmt_day(nxt.get('date'))}."
                f"{rank_bit}"
            )
    else:
        focus_bits.append(
            ranking.get("rationale") or "Insufficient data to rank levers this week."
        )

    # ── Dream ──
    dream_bits: list[str] = []
    a_race = dream.get("a_race") or {}
    name = a_race.get("name") or goal.get("name")
    race_date = a_race.get("date") or goal.get("race_date")
    goal_label = (
        a_race.get("goal_time_label")
        or goal.get("target_time_label")
        or projection.get("goal_label")
    )
    if name and race_date and goal_label:
        dream_bits.append(f"{name}, {_fmt_day(race_date)}. Goal {goal_label}.")

    perf = facts.get("performance") or {}
    if perf.get("endurance") is not None or perf.get("speed") is not None:
        parts = []
        if perf.get("endurance") is not None:
            d = perf.get("endurance_direction")
            parts.append(
                f"Endurance {perf['endurance']}"
                + (f" ({d})" if d else "")
            )
        if perf.get("speed") is not None:
            d = perf.get("speed_direction")
            parts.append(
                f"Speed {perf['speed']}"
                + (f" ({d})" if d else "")
            )
        dream_bits.append(
            "Performance tab scores: " + ", ".join(parts) + "."
        )

    milestones = dream.get("milestones") or []
    for m in milestones:
        if m.get("kind") == "a_race":
            continue  # covered above + estimate below
        line = (
            f"Checkpoint: {m.get('name')} on {_fmt_day(m.get('date'))}"
        )
        if m.get("goal_time_label"):
            line += f" — goal {m['goal_time_label']}"
        if m.get("est_label"):
            line += f", current estimate ~{m['est_label']}"
        line += ". Progress check toward the A-race — not a separate season."
        dream_bits.append(line)

    # Fallback if milestones empty but sell_line exists
    sell = dream.get("sell_line_facts") or {}
    if not any(m.get("kind") != "a_race" for m in milestones) and sell.get("next_checkpoint_date"):
        dream_bits.append(
            f"Near-term benchmark: {sell.get('next_checkpoint_label')} on "
            f"{_fmt_day(sell['next_checkpoint_date'])}"
            + (
                f" (target {sell['next_checkpoint_target']})"
                if sell.get("next_checkpoint_target")
                else ""
            )
            + "."
        )

    trend = projection.get("current_trend_label")
    if trend and not projection.get("unavailable"):
        band = projection.get("uncertainty_min")
        dream_bits.append(
            f"A-race race-day estimate ~{trend}"
            + (f" ±{band} min" if band else "")
            + " (same engine as the Performance tab)."
        )

    for sc in dream.get("scenarios") or []:
        if sc.get("id") == "weight_cut":
            dream_bits.append(
                sc.get("sell")
                or (
                    f"Lose ~{sc.get('cut_kg'):.0f} kg and the projection moves toward "
                    f"{sc.get('finish_label')} — measurement first so we don't guess."
                )
            )
            break

    if not dream_bits:
        dream_bits.append(
            "Set an A-race and a B-race checkpoint on the Plan tab to unlock Dream."
        )

    # ── Reflection ──
    ref_bits: list[str] = []
    planned = reflection.get("sessions_planned")
    completed = reflection.get("sessions_completed")
    if load.get("deload_week") or (
        load.get("last_week_tss") and load.get("week_tss") is not None
        and load["week_tss"] < (load.get("last_week_tss") or 0) * 0.8
    ):
        ref_bits.append(
            f"This week is light on purpose"
            + (
                f" ({int(load.get('week_tss') or 0)} TSS vs "
                f"{int(load.get('last_week_tss') or 0)} last week)."
                if load.get("last_week_tss") is not None
                else "."
            )
            + " One quiet week doesn't undo anything; three in a row would."
        )
    elif planned is not None:
        pct = reflection.get("adherence_pct")
        ref_bits.append(
            f"Last window: {completed}/{planned} planned sessions"
            + (f" (~{pct}% adherence)." if pct is not None else ".")
        )

    if praise:
        named = []
        for p in praise[:3]:
            kind = p.get("kind") or ""
            nm = p.get("name") or "session"
            if kind == "incline_intervals":
                named.append(f"the incline intervals ({nm} on {_fmt_day(p.get('date'))})")
            elif kind == "intervals":
                named.append(f"intervals on {_fmt_day(p.get('date'))}")
            elif kind == "strength":
                named.append(f"strength on {_fmt_day(p.get('date'))}")
            elif kind.startswith("planned_"):
                named.append(f"planned {kind.replace('planned_', '')}: {nm} ({_fmt_day(p.get('date'))})")
        if named:
            ref_bits.append(
                "Credit where it's due: " + "; ".join(named) + ". Keep that quality in the mix."
            )
    longs = volume_mix.get("recent_longs") or []
    if longs and not any(
        (r.get("id") or "") in ("long_run_fueling", "long_run") for r in focus_ranked[:2]
    ):
        bits = " and ".join(
            f"{x.get('mins')} min on {_fmt_day(x.get('date'))}" for x in longs[:2]
        )
        ref_bits.append(
            f"Long-run consistency is real — {bits}. Keep practising fueling on them."
        )

    if not ref_bits:
        ref_bits.append("Nothing alarming — keep the main levers honest.")
    ref_bits.append(
        "How's sleep? Resting heart rate? And what do your legs feel like "
        "when you first stand up in the morning?"
    )

    return sections_to_text({
        "now": "\n\n".join(now_bits),
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
        "You are a consultative performance coach writing a weekly Home brief "
        "(~one phone screen). Tone: clear, warm, direct — like a sharp human "
        "consultant, not a dashboard.\n"
        "VOICE: short paragraphs, one idea per beat. Argue ORDER (why this before that).\n"
        "FACTS DISCIPLINE — never invent TSS, dates, finish times, kg:\n"
        "- If load.deload_week is true: say so. Do NOT tell them to ramp hard this week.\n"
        "- If load.ramp_caution / load_ceiling_tss / acwr_peak_21d: warn not to dump "
        "TSS back on; respect the moving-average ceiling and ~5%/week only.\n"
        "- If volume_mix.recent_longs exists: PRAISE those longs. Never claim they "
        "are missing long runs. Durability = late-run fueling/decoupling, not "
        "'do a long run'.\n"
        "- Dream MUST use dream.milestones (curated 1–2 checkpoints + A-race) — "
        "do NOT list every B-race. Prefer half-or-longer (e.g. Bangkok Airways HM) "
        "and optionally a longer volume checkpoint; cite goal + est_label when present.\n"
        "- Mention performance.endurance / performance.speed (Performance tab scores) "
        "briefly alongside the A-race estimate (projection.current_trend_label). "
        "One short beat — not a score dump.\n"
        "- Weight: push measurement, then sell payoff "
        "(weight.payoff_label / weight_cut scenario) — 'if you lose X you project closer to Y'.\n"
        "- Reflection: praise items in praise[] (incline intervals, strength, planned "
        "strength). Light week context from load.week_tss vs last_week_tss. End with "
        "sleep / RHR / morning legs questions when useful.\n"
        "- Finish estimates: only projection.current_trend_label when unavailable is "
        "false. Never invent CTL-ratio times.\n"
        "Return JSON keys now, focus, dream, reflection (plain prose, no ## headers). "
        "IGNORE repo files / prior chat — facts JSON only."
    )
    user = (
        f"{feedback}"
        "FACTS JSON follows. Write the four sections using ONLY these facts:\n\n"
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
