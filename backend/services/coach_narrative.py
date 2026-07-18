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
        "chosen_preset_code": {"type": "string"},
    },
    "required": ["now", "focus", "dream", "reflection"],
    "additionalProperties": False,
}

# Brief v4 — LLM returns only prose atoms; placement is deterministic.
_BRIEF_ATOM_SCHEMA = {
    "type": "object",
    "properties": {
        "today_verdict": {"type": "string"},
        "week_verdict": {"type": "string"},
        "week_verdict_sub": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "headline": {"type": "string"},
                    "evidence": {"type": "string"},
                    "do": {"type": "string"},
                },
                "required": ["id", "headline", "evidence", "do"],
                "additionalProperties": False,
            },
        },
        "chosen_preset_code": {"type": "string"},
    },
    "required": ["today_verdict", "week_verdict", "week_verdict_sub", "sections"],
    "additionalProperties": False,
}

ATOM_BUDGETS = {
    "today_verdict": 140,
    "week_verdict": 90,
    "week_verdict_sub": 110,
    "headline": 60,
    "evidence": 280,
    "do": 140,
}

_FOCUS_RANK_RE = re.compile(r"focus\s*#?\d", re.IGNORECASE)
_MD_HEADER_RE = re.compile(r"^##\s", re.MULTILINE)
_SENTENCE_RE = re.compile(r"[.!?](?:\s|$)")



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
    """Legacy four-section validator (historical messages / old tests)."""
    errors: list[str] = []
    allow = set(facts.get("required_numerals") or [])
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
        if tok in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "14"}:
            continue
        if not _numeral_allowed(tok, allow):
            errors.append(f"numeral '{tok}' not in facts allowlist")

    return errors


def _numerals_from_obj(obj: Any, bucket: set[str] | None = None) -> set[str]:
    from backend.services.coach_facts import _add_numeral

    bucket = bucket if bucket is not None else set()
    if obj is None:
        return bucket
    if isinstance(obj, dict):
        for v in obj.values():
            _numerals_from_obj(v, bucket)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numerals_from_obj(v, bucket)
    else:
        _add_numeral(bucket, obj)
        for tok in _extract_numerals(str(obj)):
            bucket.add(tok)
    return bucket


def _count_sentences(text: str) -> int:
    t = (text or "").strip()
    if not t:
        return 0
    parts = [p for p in _SENTENCE_RE.split(t) if p.strip()]
    # If no terminator, still one sentence
    return max(1, len(parts)) if t else 0


def validation_errors_brief(atoms: dict, facts: dict, skeleton: dict | None = None) -> list[str]:
    """Per-atom validators for brief v4."""
    errors: list[str] = []
    section_facts = facts.get("section_facts") or {}
    if not section_facts:
        try:
            from backend.services.coach_brief_map import collect_section_facts
            section_facts = collect_section_facts(facts)
        except Exception:
            section_facts = {}

    # Global connective numerals always ok
    connective = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "14", "5%"}

    def _check_atom(name: str, text: str, budget: int, allow: set[str]):
        body = (text or "").strip()
        if len(body) > budget:
            errors.append(f"atom '{name}' over budget ({len(body)}>{budget})")
        if _FOCUS_RANK_RE.search(body):
            errors.append(f"atom '{name}' forbids Focus #N pattern")
        if _MD_HEADER_RE.search(body):
            errors.append(f"atom '{name}' forbids Markdown ## headers")
        if name.endswith(".evidence") or name == "evidence":
            if _count_sentences(body) > 2:
                errors.append(f"atom '{name}' exceeds 2 sentences")
        for tok in _extract_numerals(body):
            if tok in connective:
                continue
            if not _numeral_allowed(tok, allow | connective):
                errors.append(f"atom '{name}' numeral '{tok}' not in section facts")

    # Top-level atoms: allow global required_numerals
    global_allow = set(facts.get("required_numerals") or [])
    try:
        from backend.services.coach_facts import collect_required_numerals
        global_allow.update(collect_required_numerals(facts))
    except Exception:
        pass

    _check_atom("today_verdict", atoms.get("today_verdict") or "", ATOM_BUDGETS["today_verdict"], global_allow)
    _check_atom("week_verdict", atoms.get("week_verdict") or "", ATOM_BUDGETS["week_verdict"], global_allow)
    _check_atom(
        "week_verdict_sub",
        atoms.get("week_verdict_sub") or "",
        ATOM_BUDGETS["week_verdict_sub"],
        global_allow,
    )

    skel_ids = {
        s["id"]
        for s in ((skeleton or {}).get("sections") or [])
        if isinstance(s, dict) and s.get("id")
    }
    for s in atoms.get("sections") or []:
        if not isinstance(s, dict):
            continue
        sid = s.get("id") or "?"
        if skel_ids and sid not in skel_ids:
            errors.append(f"atom section id '{sid}' not in skeleton")
            continue
        allow = _numerals_from_obj(section_facts.get(sid) or {})
        # evidence_strip numerals from skeleton are also allowed
        if skeleton:
            for ss in skeleton.get("sections") or []:
                if ss.get("id") == sid and ss.get("evidence_strip"):
                    allow.update(_extract_numerals(ss["evidence_strip"]))
        _check_atom(f"{sid}.headline", s.get("headline") or "", ATOM_BUDGETS["headline"], allow)
        _check_atom(f"{sid}.evidence", s.get("evidence") or "", ATOM_BUDGETS["evidence"], allow)
        _check_atom(f"{sid}.do", s.get("do") or "", ATOM_BUDGETS["do"], allow)

    return errors


def feedback_block(errors: list[str]) -> str:
    if not errors:
        return ""
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "Previous draft was rejected. Fix ALL of these without inventing new numbers "
        f"(only use facts allowlist / per-section facts):\n{lines}\n"
    )


def build_prompt(facts: dict, feedback: str = "") -> tuple[str, str]:
    """Legacy four-section prompt (kept for older callers)."""
    import json

    slim = {k: v for k, v in facts.items() if k != "plan_state"}
    system = (
        "You are a consultative performance coach writing a weekly Home brief "
        "(~one phone screen). Tone: clear, warm, direct — like a sharp human "
        "consultant, not a dashboard.\n"
        "Return JSON keys now, focus, dream, reflection, and chosen_preset_code "
        "when presets exist (plain prose, no ## headers). "
        "IGNORE repo files / prior chat — facts JSON only."
    )
    user = (
        f"{feedback}"
        "FACTS JSON follows. Write the four sections using ONLY these facts:\n\n"
        f"{json.dumps(slim, default=str)[:12000]}"
    )
    return system, user


def build_brief_prompt(
    facts: dict,
    skeleton: dict,
    feedback: str = "",
) -> tuple[str, str]:
    """Prompt for brief v4 atoms only."""
    import json

    slim_facts = {
        k: v
        for k, v in facts.items()
        if k not in ("plan_state",)
    }
    system = (
        "You are a consultative performance coach writing like a human texting "
        "an athlete — clear, warm, direct. Fill ONLY the prose atoms for a "
        "structured brief. Placement is already decided — do not move facts "
        "between sections.\n"
        "Return JSON: today_verdict (≤140), week_verdict (≤90), week_verdict_sub (≤110), "
        "sections[{id,headline≤60,evidence≤280/≤2 sentences,do≤140}], "
        "optional chosen_preset_code.\n"
        "RULES:\n"
        "- evidence_strip is the STATS line (already filled). Do NOT restate those "
        "same numbers, dates, or kg/TSS counts in evidence. Evidence is coach "
        "meaning: why it matters and how to feel about it.\n"
        "- evidence: 1–2 short sentences, spoken coach tone (e.g. 'You're on a "
        "deload — resting matters more than it feels'). Avoid jargon stacks.\n"
        "- do: one concrete action for today.\n"
        "- Never invent numerals; if you must cite a number, it must appear in "
        "that section's facts / evidence_strip.\n"
        "- Prefer almost no numerals in evidence when the strip already shows them.\n"
        "- Never write 'Focus #N' or '## ' Markdown headers.\n"
        "- Never assert which focus a session serves — that is data (serves_focus_rank).\n"
        "- If load.deload_week: do not tell them to ramp hard today.\n"
        "- Cite load.acwr_display / performance scores only when present in facts.\n"
        "- If active_presets non-empty, set chosen_preset_code to one exact code.\n"
        "- today_verdict must narrate the same lever as focus_ranked[0] "
        "(that section's DO) — not a competing story (e.g. do not lead with "
        "deload when weigh-in is focus #1).\n"
    )
    user = (
        f"{feedback}"
        "SECTION SKELETON (ids, cadence, evidence_strip — fill headline/evidence/do):\n"
        f"{json.dumps({'sections': skeleton.get('sections')}, default=str)[:6000]}\n\n"
        "FACTS JSON:\n"
        f"{json.dumps(slim_facts, default=str)[:10000]}"
    )
    return system, user


def call_llm_brief_atoms(
    facts: dict,
    skeleton: dict,
    feedback: str = "",
) -> dict | None:
    """LLM call returning brief v4 atoms dict."""
    system, user = build_brief_prompt(facts, skeleton, feedback)
    mode = coach_llm_mode()

    if mode in ("off", "fallback", "none", "disabled"):
        return None

    if mode in ("claude_cli", "claude", "cli"):
        from backend.services.coach_claude_cli import (
            call_claude_cli_sections,
            claude_cli_enabled,
        )

        if not claude_cli_enabled():
            return None
        # CLI returns a dict — may be legacy keys; accept atom shape
        raw = call_claude_cli_sections(system, user)
        return raw if isinstance(raw, dict) else None

    if mode in ("api", "http", "groq", "glm"):
        from backend.services.llm import llm_enabled, complete_structured

        if not llm_enabled():
            return None
        result = complete_structured(
            system=system,
            user=user,
            schema_name="coach_brief_atoms_v4",
            json_schema=_BRIEF_ATOM_SCHEMA,
            model_tier="deep",
            max_tokens=1400,
        )
        if result is None:
            result = complete_structured(
                system=system,
                user=user,
                schema_name="coach_brief_atoms_v4",
                json_schema=_BRIEF_ATOM_SCHEMA,
                model_tier="fast",
                max_tokens=1200,
            )
        return result if isinstance(result, dict) else None

    return None


def atoms_from_brief(brief: dict) -> dict:
    """Extract atom payload from a full brief (for validation of fallback)."""
    return {
        "today_verdict": (brief.get("today") or {}).get("today_verdict") or "",
        "week_verdict": (brief.get("digest") or {}).get("week_verdict") or "",
        "week_verdict_sub": (brief.get("digest") or {}).get("week_verdict_sub") or "",
        "sections": [
            {
                "id": s.get("id"),
                "headline": s.get("headline") or "",
                "evidence": s.get("evidence") or "",
                "do": s.get("do") or "",
            }
            for s in (brief.get("sections") or [])
            if isinstance(s, dict)
        ],
    }


def generate_brief(
    facts: dict,
    max_attempts: int = 3,
    *,
    db=None,
    user_id=None,
    brief_date=None,
) -> dict:
    """Build v4 brief via LangGraph/plain atom orch → persist when db given."""
    from datetime import date as _date

    from backend.services.coach_brief import (
        build_brief_skeleton,
        brief_to_text,
        compose_coach_brief,
        get_yesterday_brief_payload,
        merge_llm_atoms,
        persist_daily_brief,
    )

    brief_date = brief_date or _date.fromisoformat(
        str(facts.get("as_of") or _date.today().isoformat())[:10]
    )
    yesterday = None
    if db is not None and user_id is not None:
        yesterday = get_yesterday_brief_payload(db, user_id, brief_date)

    skeleton = build_brief_skeleton(facts, yesterday)
    mode = coach_orch_mode()
    attempts = 0
    chosen_code = None

    def _fallback() -> dict:
        b = compose_coach_brief(facts, yesterday)
        apply_chosen_preset(facts, None)
        return b

    brief: dict | None = None
    source = "fallback"

    if mode == "langgraph":
        try:
            from backend.services.coach_orch_langgraph import run_brief

            result = run_brief(facts, skeleton, max_attempts=max_attempts)
            brief = result.get("brief")
            chosen_code = result.get("chosen_preset_code")
            attempts = int(result.get("attempts") or 0)
            source = result.get("source") or (brief or {}).get("source") or "fallback"
            if brief:
                brief["source"] = source
                apply_chosen_preset(facts, chosen_code)
        except Exception as exc:
            _log.warning("coach brief langgraph unavailable (%s); plain path", exc)
            brief = None

    if brief is None:
        errors: list[str] = []
        for _ in range(max_attempts):
            attempts += 1
            fb = feedback_block(errors)
            atoms = call_llm_brief_atoms(facts, skeleton, fb)
            if atoms is None:
                errors = ["llm unavailable or empty"]
                continue
            chosen_code = atoms.pop("chosen_preset_code", None)
            errors = validation_errors_brief(atoms, facts, skeleton)
            if not errors:
                brief = merge_llm_atoms(skeleton, atoms, facts)
                source = _source_label()
                brief["source"] = source
                apply_chosen_preset(facts, chosen_code)
                break
        if brief is None:
            brief = _fallback()
            source = "fallback"

    if brief is not None:
        from backend.services.coach_brief import finalize_brief
        finalize_brief(brief, facts)
        brief["source"] = source

    text = brief_to_text(brief)
    if db is not None and user_id is not None:
        try:
            persist_daily_brief(db, user_id, brief_date, brief, source)
        except Exception as exc:
            _log.warning("persist daily_brief failed: %s", exc)

    return {
        "brief": brief,
        "text": text,
        "sections": parse_sections_from_text(text),
        "source": source,
        "attempts": attempts,
        "orch": mode,
        "chosen_preset": facts.get("chosen_preset"),
    }


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
        if result.get("chosen_preset_code"):
            sections["chosen_preset_code"] = str(result.get("chosen_preset_code")).strip()
        if not any(sections.get(k) for k in SECTION_ORDER):
            return None
        return sections

    _log.warning("Unknown COACH_LLM=%r — expected claude_cli|api|off", mode)
    return None


def coach_orch_mode() -> str:
    return (os.environ.get("COACH_ORCH") or "langgraph").strip().lower()


def apply_chosen_preset(facts: dict, chosen_code: str | None) -> dict:
    """Validate LLM pick against active_presets; update facts nudge/chosen_preset."""
    from backend.services.gap_analysis.session_presets import pick_preset_by_code

    presets = facts.get("active_presets") or []
    if not presets:
        return facts
    picked = pick_preset_by_code(presets, chosen_code) if chosen_code else None
    if picked is None:
        picked = presets[0]
    facts["chosen_preset"] = picked
    facts["nudge"] = {
        "focus_id": picked.get("code"),
        "focus_label": picked.get("name") or picked.get("kind"),
        "next_action": (
            f"{picked.get('name') or picked.get('kind')} ({picked.get('summary')})"
        ),
        "why": picked.get("notes"),
        "preset_code": picked.get("code"),
    }
    return facts


def generate_narrative(facts: dict, max_attempts: int = 3) -> dict:
    """Compat wrapper — builds v4 brief then renders legacy Markdown text."""
    result = generate_brief(facts, max_attempts=max_attempts)
    return {
        "text": result.get("text") or "",
        "sections": result.get("sections") or {},
        "source": result.get("source") or "fallback",
        "attempts": result.get("attempts") or 0,
        "orch": result.get("orch") or "plain",
        "chosen_preset": result.get("chosen_preset") or facts.get("chosen_preset"),
        "brief": result.get("brief"),
    }


def _source_label() -> str:
    mode = coach_llm_mode()
    if mode in ("claude_cli", "claude", "cli"):
        return "claude_cli"
    if mode in ("api", "http", "groq", "glm"):
        return "llm"
    return "fallback"
