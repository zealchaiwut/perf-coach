"""Part 1–3: Coach brief v4 mapper, hashes, serves_focus_rank, atoms, FE open cap."""

from __future__ import annotations

import pytest

from backend.services.coach_brief_map import (
    FACT_TO_SECTION,
    SECTION_ORDER,
    build_sections,
    collect_section_facts,
)
from backend.services.coach_brief import (
    apply_changed_flags,
    brief_to_text,
    compose_coach_brief,
    fact_hash_for_section,
)
from backend.services.coach_facts import _focus_for_session


def test_mapper_each_fact_one_section():
    # Import-time assert already guards SECTION_META; ensure no empty map
    assert FACT_TO_SECTION
    assert set(FACT_TO_SECTION.values()) <= set(SECTION_ORDER)


def test_serves_focus_rank_long_run_is_rank_2_not_1():
    focus = [
        {
            "id": "weight_measurement",
            "rank": 1,
            "label": "Weigh-ins",
        },
        {
            "id": "long_run",
            "rank": 2,
            "label": "Long-run durability",
        },
    ]
    matched = _focus_for_session(focus, "Aerobic long run", "run")
    assert matched is not None
    rank, fid = matched
    assert rank == 2
    assert fid == "long_run"


def test_serves_focus_rank_no_match_returns_none():
    focus = [
        {"id": "weight_measurement", "rank": 1, "label": "Weigh-ins"},
    ]
    assert _focus_for_session(focus, "Mystery session", "other") is None


def test_changed_flags_stable_then_weight_flip():
    facts_a = {
        "load": {
            "deload_week": True,
            "week_tss": 262,
            "last_week_tss": 285,
            "acwr_display": 1.1,
            "acwr": 1.1,
            "load_ceiling_tss": 408,
        },
        "weight": {"logged_days": 6, "window_days": 14, "payoff_cut_kg": 6, "payoff_label": "4:02"},
        "goal": {"name": "Bangsaen42", "target_time_label": "4:15"},
        "projection": {"current_trend_label": "4:14", "uncertainty_min": 14},
        "reflection": {"sessions_completed": 4, "adherence_pct": 80},
        "focus_ranked": [],
        "as_of": "2026-07-18",
    }
    sections = build_sections(facts_a)
    sf = collect_section_facts(facts_a)
    for s in sections:
        s["fact_hash"] = fact_hash_for_section(sf.get(s["id"]) or {})
    yday = {"sections": [{**s} for s in sections]}
    apply_changed_flags(sections, yday)
    assert all(s["changed_since_yesterday"] is False for s in sections)

    facts_b = dict(facts_a)
    facts_b["weight"] = dict(facts_a["weight"], logged_days=7)
    sections_b = build_sections(facts_b)
    sf_b = collect_section_facts(facts_b)
    for s in sections_b:
        s["fact_hash"] = fact_hash_for_section(sf_b.get(s["id"]) or {})
    apply_changed_flags(sections_b, yday)
    flipped = {s["id"]: s["changed_since_yesterday"] for s in sections_b}
    assert flipped.get("weight_gate") is True
    # Other sections with unchanged facts stay False
    for sid, ch in flipped.items():
        if sid != "weight_gate":
            assert ch is False, sid


def test_fallback_validates_and_brief_to_text():
    facts = {
        "as_of": "2026-07-18",
        "load": {
            "deload_week": True,
            "week_tss": 262,
            "last_week_tss": 285,
            "acwr_display": 1.05,
            "acwr": 1.05,
            "load_ceiling_tss": 400,
            "state": "available",
        },
        "weight": {
            "logged_days": 6,
            "window_days": 14,
            "phase": "measurement",
            "payoff_cut_kg": 6,
            "payoff_label": "4:02:46",
        },
        "goal": {"name": "Bangsaen42", "target_time_label": "4:15", "race_date": "2026-11-15"},
        "projection": {
            "current_trend_label": "4:14:49",
            "uncertainty_min": 14,
            "unavailable": False,
        },
        "dream": {"a_race": {"name": "Bangsaen42", "date": "2026-11-15"}},
        "reflection": {
            "sessions_completed": 4,
            "sessions_planned": 5,
            "adherence_pct": 80,
            "next_session": {
                "name": "Aerobic long run",
                "type": "run",
                "serves_focus_rank": 2,
            },
        },
        "focus_ranked": [
            {
                "id": "weight_measurement",
                "rank": 1,
                "label": "Weigh in every morning",
                "rationale": "gate before calories",
                "tracking": {"current": 6, "target": 12},
            },
            {
                "id": "respect_deload",
                "rank": 2,
                "label": "Respect this deload week",
                "rationale": "keep quiet",
                "tracking": None,
            },
            {
                "id": "long_run",
                "rank": 3,
                "label": "Long run + fuel",
                "rationale": "late fade",
                "tracking": None,
            },
        ],
        "chosen_preset": {
            "code": "aerobic_long",
            "name": "Aerobic long run",
            "kind": "run",
            "summary": "≥110 min · Z1–Z2",
        },
        "volume_mix": {"recent_longs": [{"duration_min": 107, "date": "2026-07-18"}]},
        "praise": [],
    }
    brief = compose_coach_brief(facts)
    assert brief["schema_version"] == 4
    assert brief["source"] == "fallback"
    focus = (brief.get("digest") or {}).get("focus") or []
    assert len(focus) == 3
    by_sid = {s["id"]: s for s in brief["sections"]}
    for row in focus:
        sid = row.get("section_id")
        assert sid and sid in by_sid
        assert row["title"] == by_sid[sid]["headline"]

    # Focus #1 is weight → today_verdict is weigh-in DO, not deload session line
    assert (
        "Scale" in brief["today"]["today_verdict"]
        or "scale" in brief["today"]["today_verdict"].lower()
        or "Weigh" in brief["today"]["today_verdict"]
        or "weigh" in brief["today"]["today_verdict"].lower()
    )
    assert "Deload week — this session" not in brief["today"]["today_verdict"]
    chip_kinds = {c["kind"] for c in brief["today"]["chips"]}
    assert "weigh_in" not in chip_kinds
    assert "deload" not in chip_kinds
    # Open priority: weight_gate first among open_by_default
    open_ids = [s["id"] for s in brief["sections"] if s.get("open_by_default")]
    assert open_ids[0] == "weight_gate"
    assert len(open_ids) <= 3

    text = brief_to_text(brief)
    assert "## Now" in text
    assert "## Focus" in text
    assert "## Dream" in text
    assert "## Reflection" in text


def test_fe_open_cap_max_three():
    """Mirror CoachBrief.openSectionIds rule: max 3 changed sections open."""
    sections = [
        {"id": "a", "changed_since_yesterday": True, "open_by_default": True},
        {"id": "b", "changed_since_yesterday": True, "open_by_default": True},
        {"id": "c", "changed_since_yesterday": True, "open_by_default": True},
        {"id": "d", "changed_since_yesterday": True, "open_by_default": False},
        {"id": "e", "changed_since_yesterday": False},
    ]
    open_ids = [s["id"] for s in sections if s.get("open_by_default")][:3]
    assert open_ids == ["a", "b", "c"]


def test_digest_fe_hides_focus_rows():
    """Slim digest: week verdict only — no .hc-f-row in rendered HTML."""
    from pathlib import Path
    src = Path("frontend/js/home-coach-digest.js").read_text()
    assert "hc-f-row" not in src
    assert "week_verdict" in src
    assert "Full brief" in src


def test_longrun_strip_says_enough_not_bare_dates():
    from backend.services.coach_brief_map import build_evidence_strip
    from backend.services.coach_brief import _longrun_fade_evidence

    facts = {
        "volume_mix": {
            "missing_long": False,
            "long_volume_ok": True,
            "recent_longs": [
                {"date": "2026-07-18", "mins": 107, "name": "Morning Run"},
                {"date": "2026-07-12", "mins": 106, "name": "Morning Run"},
            ],
        }
    }
    strip = build_evidence_strip("longrun_fade", {}, facts)
    assert "enough" in strip.lower()
    assert "107" in strip
    assert "2026-07-18 · 2026-07-12" not in strip
    text = _longrun_fade_evidence(facts)
    # Prose must not restate the strip durations
    assert "107" not in text
    assert "106" not in text
    assert "fueling" in text.lower() or "fade" in text.lower() or "long" in text.lower()


def test_weight_gate_strip_explains_plan_not_payoff_timer():
    from backend.services.coach_brief_map import build_evidence_strip

    facts = {
        "weight": {
            "logged_days": 6,
            "window_days": 14,
            "current_kg": 78.4,
            "plan_today_kg": 76.1,
            "gap_direction": "behind",
            "payoff_cut_kg": 6,
            "payoff_label": "4:02:46",
            "next_milestone_kg": 74.0,
            "next_milestone_date": "2026-09-01",
        }
    }
    strip = build_evidence_strip("weight_gate", {}, facts)
    assert "6 / 12 logged" in strip
    assert "78.4" in strip or "78.40" in strip or "now 78" in strip
    assert "plan today" in strip
    assert "behind" in strip
    assert "4:02" not in strip  # race prize stays out of the strip
    assert "−6" not in strip and "-6" not in strip


def test_weight_gate_evidence_is_prose_not_stats_dup():
    from backend.services.coach_brief import _weight_gate_evidence

    text = _weight_gate_evidence({
        "weight": {
            "logged_days": 6,
            "window_days": 14,
            "current_kg": 78.4,
            "plan_today_kg": 76.1,
            "gap_direction": "behind",
            "payoff_cut_kg": 6,
            "payoff_label": "4:02:46",
            "next_milestone_kg": 74.0,
            "next_milestone_date": "2026-09-01",
        }
    })
    assert "78.4" not in text
    assert "76.1" not in text
    assert "4:02:46" not in text
    assert "6/12" not in text
    assert "gate" in text.lower() or "food" in text.lower()
    assert "diet" in text.lower() or "deficit" in text.lower() or "weigh" in text.lower()


def test_fmt_pace_and_duration():
    from backend.services.coach_brief import _fmt_duration, _fmt_pace, _praise_for_workout

    assert _fmt_duration(3720) == "1h 02m"
    assert _fmt_duration(45 * 60) == "45 min"
    assert _fmt_pace(10.0, 50 * 60) == "5:00/km"
    assert "long run" in _praise_for_workout("Sunday Long", "run", "longrun").lower()
    assert "long run" in _praise_for_workout(
        "Morning Run", "run", None, distance_km=15.5, duration_seconds=6454
    ).lower()


def test_strip_fe_shows_todays_workout():
    from pathlib import Path
    src = Path("frontend/js/home-coach-strip.js").read_text()
    assert "completed_workout" in src
    assert "planned_today" in src
    assert "hc-tag--done" in src
    assert "hc-tag--rest" in src
    assert "hc-sess-praise" in src
    assert "hc-sess-stats" in src
    assert "TODAY\\'S PLAN" in src or "TODAY'S PLAN" in src or "hc-sess--plan" in src
