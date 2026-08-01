"""Weekly-summary facts and deterministic narrative — the LLM-free half.

``assemble_facts`` turns pre-fetched workout rows into weekly metrics, and
``build_fallback_narrative`` renders those metrics as coach-style text. Both are
pure: no I/O, no LLM, no provider key.

Split out of ``weekly_summary`` for Priority 2 (D4). ``daily_brief`` imports
only these two, and ``daily_brief`` sits on the compute worker's daily_coach
path via ``coach_facts``. While they lived next to ``get_narrative``, importing
them dragged ``backend.services.llm`` onto the worker for a function the worker
never calls. Same split, same reason, as ``coach_sections``.

``weekly_summary`` re-exports both, so every existing caller and test keeps
working against the old import path.
"""

from __future__ import annotations

from datetime import date


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
    gap_findings: Optional[list[dict]] = None,
) -> dict:
    """Assemble weekly summary facts from pre-fetched data.

    Pure function — no database access, no network calls.
    All raw data is passed in by the endpoint caller.

    verdict: the deterministic training_verdict.compute_verdict() result
        (computed by the caller from the Part-A snapshot at week_end), or
        None. When provided, its fields land in facts as GIVENS the LLM must
        explain, never derive or contradict — see build_prompt()/
        validate_summary() below.

    gap_findings: list of active gap-finding dicts for the week, or None.
        None  → key absent from facts (analyzer has never run; backward-compat).
        []    → key present but empty dict (analyzer ran, no active findings).
        [...]  → key present with top finding (highest severity) + others_count.
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

    out: dict = {
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

    # gap_findings integration (issue #1378):
    # Key absent when gap_findings is None (analyzer never ran — backward compat).
    if gap_findings is not None:
        if not gap_findings:
            out["gap_findings"] = {}
        else:
            # Pick the finding with the highest severity; stable sort by severity desc.
            sorted_findings = sorted(gap_findings, key=lambda f: f.get("severity", 0), reverse=True)
            top = sorted_findings[0]
            evidence = top.get("evidence") or []
            evidence_value = evidence[0]["value"] if evidence else None
            out["gap_findings"] = {
                "top": {
                    "code": top.get("code"),
                    "severity": top.get("severity"),
                    "recommendation": top.get("recommendation"),
                    "evidence_value": evidence_value,
                    "target": top.get("target"),
                },
                "others_count": len(sorted_findings) - 1,
            }

    return out


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
        parts = [base]
        if verdict_sentence:
            parts.append(verdict_sentence)
        # Gap finding applies even to zero-workout weeks (issue #1378)
        gf = facts.get("gap_findings")
        if gf and gf.get("top"):
            top = gf["top"]
            rec = top.get("recommendation", "")
            severity = top.get("severity", 0)
            label = "Priority gap" if severity == 3 else "Gap finding"
            parts.append(f"{label}: {rec}")
        return " ".join(parts)

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

    # Gap finding (issue #1378): render top finding recommendation when present.
    # Key absent → analyzer never ran → no change. Key = {} → no active findings.
    gf = facts.get("gap_findings")
    if gf and gf.get("top"):
        top = gf["top"]
        rec = top.get("recommendation", "")
        severity = top.get("severity", 0)
        label = "Priority gap" if severity == 3 else "Gap finding"
        others = gf.get("others_count", 0)
        finding_line = f"{label}: {rec}"
        if others > 0:
            finding_line += f" ({others} more finding{'s' if others > 1 else ''} this week.)"
        lines.append(finding_line)

    # Subjective signals — the report closes by asking, not only asserting
    # (spec B.5). A fixed question keeps the deterministic template honest
    # about not being the whole picture.
    lines.append("How's sleep, resting HR, and how do your legs feel in the morning?")

    return " ".join(lines)
