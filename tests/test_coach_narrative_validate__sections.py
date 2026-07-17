"""Validators + deterministic fallback for coach narrative."""

from __future__ import annotations

from backend.services.coach_narrative import (
    compose_coach_narrative,
    parse_sections_from_text,
    sections_to_text,
    validation_errors,
)


def _base_facts(**overrides):
    facts = {
        "load": {
            "state": "locked",
            "reason": "ACWR 1.55 — hold ~316 TSS",
            "hold_tss": 316,
            "unlock_date": "2026-07-31",
        },
        "weight": {
            "phase": "measurement",
            "logged_days": 4,
            "window_days": 14,
            "gap_kg": 5.0,
            "recommended_deficit_kcal": None,
        },
        "timeline": [
            {
                "date": "2026-07-17",
                "phase": "hold",
                "directive": "Hold TSS ~316/week",
            }
        ],
        "constraints": ["Do not add volume while ACWR > 1.30"],
        "lever_ranking": {"rationale": "Weight measurement is more tractable"},
        "projection": {
            "full_compliance_label": "1:45",
            "current_trend_label": "1:52",
            "uncertainty_min": 3,
            "distance_label": "HM",
        },
        "focus_ranked": [
            {
                "id": "weight_measurement",
                "rank": 1,
                "label": "Weight measurement consistency",
                "rationale": "Build 12/14 weigh-ins",
                "tracking": {"current": 4, "target": 12, "unit": "weigh_ins_14d"},
            },
            {
                "id": "hold_load",
                "rank": 2,
                "label": "Hold training load",
                "rationale": "ACWR elevated",
                "tracking": {"unlock_date": "2026-07-31"},
            },
        ],
        "focus_noise": ["plyo"],
        "dream": {
            "a_race": {
                "name": "Bangkok HM",
                "date": "2026-12-14",
                "goal_time_label": "1:45",
            },
            "scenarios": [],
            "sell_line_facts": {
                "next_checkpoint_date": "2026-09-15",
                "next_checkpoint_label": "Mid-Sep tune-up",
                "next_checkpoint_target": "1:55",
            },
        },
        "reflection": {
            "sessions_planned": 5,
            "sessions_completed": 3,
            "adherence_pct": 60,
            "benchmarks": [
                {"id": "weight_measurement", "met": False, "detail": "4/12 weigh_ins_14d"}
            ],
            "next_session": {
                "name": "Easy 8k",
                "date": "2026-07-18",
                "why_focus": "Serves Focus #1: weight_measurement",
            },
        },
        "required_numerals": [
            "316", "2026-07-31", "4", "12", "14", "1.55", "1:45", "1:52",
            "3", "5", "60", "2026-09-15", "1:55", "2026-12-14", "2026-07-17",
            "2026-07-18", "8",
        ],
    }
    facts.update(overrides)
    return facts


def test_compose_has_four_section_headers():
    text = compose_coach_narrative(_base_facts())
    for h in ("## Now", "## Focus", "## Dream", "## Reflection"):
        assert h in text
    secs = parse_sections_from_text(text)
    assert len(secs["now"]) >= 24
    assert "316" in text or "Hold" in text
    assert "Weigh" in secs["focus"] or "Two things" in secs["focus"]


def test_validation_rejects_invented_tss():
    facts = _base_facts()
    bad = {
        "now": "Hold ~77777 TSS until unlock — made-up number for test padding xx.",
        "focus": "Focus on measurement consistency this week with honest logs.",
        "dream": "Checkpoint ladder awaits Mid-Sep tune-up on the calendar soon.",
        "reflection": "Logged three of five planned sessions in the last window.",
    }
    errs = validation_errors(bad, facts)
    assert any("77777" in e for e in errs)


def test_validation_rejects_short_section():
    facts = _base_facts()
    short = {
        "now": "Too short.",
        "focus": "Focus on measurement consistency this week with honest logs.",
        "dream": "Checkpoint ladder awaits Mid-Sep tune-up on the calendar soon.",
        "reflection": "Logged three of five planned sessions in the last window.",
    }
    errs = validation_errors(short, facts)
    assert any("now" in e and "short" in e for e in errs)


def test_validation_accepts_golden_sections():
    facts = _base_facts()
    text = compose_coach_narrative(facts)
    secs = parse_sections_from_text(text)
    # Recompute allowlist from facts so fallback prose always validates
    from backend.services.coach_facts import collect_required_numerals
    facts["required_numerals"] = collect_required_numerals(facts)
    errs = validation_errors(secs, facts)
    assert errs == [], errs
    assert sections_to_text(secs).startswith("## Now")
