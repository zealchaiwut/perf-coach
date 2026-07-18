"""Deterministic section mapper for Coach brief v4.

Every placed fact maps to exactly one section. The LLM never chooses placement.
"""
from __future__ import annotations

from typing import Any

# fact_key → section_id. Duplicate values across keys are fine; duplicate keys
# or a key mapping to two sections is impossible in a dict. Import-time assert
# below catches accidental double-assignment if we ever merge maps.
FACT_TO_SECTION: dict[str, str] = {
    # load_deload
    "load.deload_week": "load_deload",
    "load.week_tss": "load_deload",
    "load.last_week_tss": "load_deload",
    "load.acwr": "load_deload",
    "load.acwr_peak_21d": "load_deload",
    "load.load_ceiling_tss": "load_deload",
    "load.ctl": "load_deload",
    "load.unlock_date": "load_deload",
    "load.state": "load_deload",
    # weight_gate
    "weight.logged_days": "weight_gate",
    "weight.window_days": "weight_gate",
    "weight.gap_kg": "weight_gate",
    "weight.payoff_label": "weight_gate",
    "weight.payoff_cut_kg": "weight_gate",
    "weight.current_kg": "weight_gate",
    "weight.plan_today_kg": "weight_gate",
    "weight.gap_to_plan_kg": "weight_gate",
    "weight.gap_direction": "weight_gate",
    "weight.goal_kg": "weight_gate",
    "weight.goal_date": "weight_gate",
    "weight.next_milestone_date": "weight_gate",
    "weight.next_milestone_kg": "weight_gate",
    # longrun_fade
    "volume_mix.recent_longs": "longrun_fade",
    "volume_mix.missing_long": "longrun_fade",
    "volume_mix.long_volume_ok": "longrun_fade",
    "volume_mix.latest_long_mins": "longrun_fade",
    "volume_mix.latest_long_date": "longrun_fade",
    "chosen_preset": "longrun_fade",
    "nudge.preset_code": "longrun_fade",
    # season
    "goal": "season",
    "dream.a_race": "season",
    "dream.milestones": "season",
    "projection": "season",
    "performance": "season",
    # week_review
    "reflection.sessions_completed": "week_review",
    "reflection.sessions_planned": "week_review",
    "reflection.adherence_pct": "week_review",
    "praise": "week_review",
    "reflection.highlights": "week_review",
}

SECTION_ORDER = (
    "load_deload",
    "weight_gate",
    "longrun_fade",
    "season",
    "week_review",
)

# focus_ranked[].id → brief section — digest titles sync from that section's headline
FOCUS_ID_TO_SECTION: dict[str, str] = {
    "respect_deload": "load_deload",
    "ramp_caution": "load_deload",
    "hold_load": "load_deload",
    "ramp_load": "load_deload",
    "weight_measurement": "weight_gate",
    "weight_deficit": "weight_gate",
    "long_run": "longrun_fade",
    "long_run_fueling": "longrun_fade",
    "quality_intervals": "longrun_fade",
    "tempo": "longrun_fade",
    "plyo": "week_review",
    "strength": "week_review",
}

SECTION_META: dict[str, dict[str, str]] = {
    "load_deload": {"cadence": "today", "card_link": "readiness"},
    "weight_gate": {"cadence": "today", "card_link": "weight"},
    "longrun_fade": {"cadence": "weekly", "card_link": "plan"},
    "season": {"cadence": "season", "card_link": "performance"},
    "week_review": {"cadence": "weekly", "card_link": None},
}

# Fail fast if a future edit assigns the same fact_key twice (can't happen in
# one dict) or if SECTION_META misses an ORDER id.
_seen_sections = set(FACT_TO_SECTION.values())
assert set(SECTION_ORDER) >= _seen_sections, (
    f"SECTION_ORDER missing sections: {_seen_sections - set(SECTION_ORDER)}"
)
assert set(SECTION_META) == set(SECTION_ORDER), "SECTION_META/ORDER mismatch"


def section_id_for_fact(fact_key: str) -> str | None:
    return FACT_TO_SECTION.get(fact_key)


def _dig(facts: dict, dotted: str) -> Any:
    cur: Any = facts
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def collect_section_facts(facts: dict) -> dict[str, dict[str, Any]]:
    """Expose facts['section_facts'][section_id] = {fact_key: value}."""
    out: dict[str, dict[str, Any]] = {sid: {} for sid in SECTION_ORDER}
    for key, sid in FACT_TO_SECTION.items():
        val = _dig(facts, key) if "." in key else facts.get(key)
        if val is None:
            continue
        out[sid][key] = val
    return out


def _fmt_num(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v - round(v)) < 1e-6:
            return str(int(round(v)))
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def build_evidence_strip(section_id: str, section_facts: dict[str, Any], facts: dict) -> str:
    """Deterministic mono facts line (≤90 chars target)."""
    load = facts.get("load") or {}
    weight = facts.get("weight") or {}
    if section_id == "load_deload":
        parts = [
            f"{_fmt_num(load.get('week_tss'))} / {_fmt_num(load.get('last_week_tss'))} TSS",
        ]
        peak = load.get("acwr_peak_21d")
        acwr = load.get("acwr_display")
        if acwr is None:
            acwr = load.get("acwr")
        if peak is not None:
            parts.append(f"ACWR peak {_fmt_num(peak)}")
        elif acwr is not None:
            parts.append(f"ACWR {_fmt_num(acwr)}")
        if load.get("load_ceiling_tss") is not None:
            parts.append(f"ceiling ~{_fmt_num(load.get('load_ceiling_tss'))} TSS/wk")
        return " · ".join(parts)[:90]

    if section_id == "weight_gate":
        logged = weight.get("logged_days")
        window = weight.get("window_days") or 14
        gate = max(12, int(window) - 2) if window else 12
        parts = [f"{_fmt_num(logged)} / {gate} logged"]
        cur = weight.get("current_kg")
        plan = weight.get("plan_today_kg")
        direction = (weight.get("gap_direction") or "").lower()
        dir_label = {
            "behind": "behind plan",
            "ahead": "ahead of plan",
            "on_plan": "on plan",
        }.get(direction)
        if cur is not None and plan is not None:
            bit = f"now {_fmt_num(cur)} · plan today {_fmt_num(plan)}"
            if dir_label:
                bit += f" ({dir_label})"
            parts.append(bit)
        elif cur is not None:
            parts.append(f"now {_fmt_num(cur)} kg")
        ms_kg = weight.get("next_milestone_kg")
        ms_date = weight.get("next_milestone_date")
        if ms_kg is not None and ms_date:
            parts.append(f"next {_fmt_num(ms_kg)} kg by {str(ms_date)[:10]}")
        # Payoff (−N kg → race time) is explained in the evidence prose — not
        # the strip — so it isn't read as "current weight change" or a timer.
        return " · ".join(parts)[:140]

    if section_id == "longrun_fade":
        vm = facts.get("volume_mix") or {}
        longs = vm.get("recent_longs") or []
        parts: list[str] = []
        if vm.get("missing_long") or not longs:
            parts.append("Not enough — no long (~90+ min) in ~3 weeks")
        else:
            parts.append("Volume: enough")
            latest = longs[0] if isinstance(longs[0], dict) else None
            mins = None
            if latest:
                mins = latest.get("mins") or latest.get("duration_min")
                d = str(latest.get("date") or "")[:10]
                if mins:
                    label = f"latest {int(mins)} min"
                    if d:
                        # Prefer short month-day over raw ISO range of two dates
                        try:
                            from datetime import date as _date
                            dd = _date.fromisoformat(d)
                            label += f" ({dd.strftime('%b')} {dd.day})"
                        except Exception:
                            label += f" ({d})"
                    parts.append(label)
            # Second long as corroboration (duration, not bare date)
            if len(longs) > 1 and isinstance(longs[1], dict):
                m2 = longs[1].get("mins") or longs[1].get("duration_min")
                if m2:
                    parts.append(f"prior {int(m2)} min")
            parts.append("gap = late fade / fueling")
        return " · ".join(parts)[:140]

    if section_id == "season":
        proj = facts.get("projection") or {}
        goal = facts.get("goal") or {}
        name = goal.get("name") or "A-race"
        label = proj.get("current_trend_label") or goal.get("target_time_label")
        unc = proj.get("uncertainty_min")
        parts = [str(name)]
        if label and not proj.get("unavailable"):
            parts.append(f"est {label}" + (f" ±{unc} min" if unc else ""))
        return " · ".join(parts)[:90]

    if section_id == "week_review":
        ref = facts.get("reflection") or {}
        parts = [
            f"{_fmt_num(ref.get('sessions_completed'))} sessions",
        ]
        if ref.get("adherence_pct") is not None:
            parts.append(f"{ref['adherence_pct']}% adherence")
        praise = facts.get("praise") or []
        if praise:
            parts.append(str(praise[0])[:40] if not isinstance(praise[0], dict) else str(praise[0].get("text") or "")[:40])
        return " · ".join(p for p in parts if p)[:90]

    return ""


def build_sections(facts: dict) -> list[dict]:
    """Section skeleton with deterministic fields; LLM fills headline/evidence/do later."""
    section_facts = collect_section_facts(facts)
    facts["section_facts"] = section_facts
    out: list[dict] = []
    for sid in SECTION_ORDER:
        meta = SECTION_META[sid]
        sf = section_facts.get(sid) or {}
        # Skip empty sections with no usable facts (season always kept if goal)
        if not sf and sid not in ("season", "week_review"):
            continue
        if sid == "season" and not (facts.get("goal") or (facts.get("dream") or {}).get("a_race")):
            continue
        out.append({
            "id": sid,
            "cadence": meta["cadence"],
            "headline": "",
            "evidence": "",
            "evidence_strip": build_evidence_strip(sid, sf, facts),
            "card_link": meta["card_link"],
            "do": "",
            "changed_since_yesterday": True,
            "fact_hash": "",
        })
    return out
