"""Unit tests for coach_facts helpers (no DB required for ranking/numerals)."""

from __future__ import annotations

from backend.services.coach_facts import (
    collect_required_numerals,
    rank_focus_levers,
)


def test_rank_focus_locked_acwr_and_poor_weigh_ins():
    """Locked load + measurement phase → hold_load and weight_measurement on top."""
    plan_state = {
        "lever_ranking": {
            "bigger_lever": "load",
            "more_tractable": "weight",
            "rationale": "CTL gap large but ACWR locked",
        }
    }
    load = {
        "state": "locked",
        "reason": "ACWR 1.55 — hold ~316 TSS",
        "unlock_date": "2026-07-31",
        "hold_tss": 316,
    }
    weight = {
        "phase": "measurement",
        "logged_days": 4,
        "window_days": 14,
        "gap_kg": 5.0,
    }
    gaps = [{"code": "plyo", "severity": "info", "text": "No plyo in 21d"}]
    ranked, noise = rank_focus_levers(
        plan_state=plan_state,
        weight=weight,
        load=load,
        gaps_top=gaps,
        volume_mix={"missing_long": False, "missing_quality": False},
    )
    assert ranked
    top_ids = [r["id"] for r in ranked[:2]]
    assert "hold_load" in top_ids
    assert "weight_measurement" in top_ids
    assert ranked[0]["rank"] == 1
    assert "plyo" in noise or any(r["id"] == "plyo" for r in ranked[2:])


def test_rank_focus_unlocked_long_run_gap():
    plan_state = {"lever_ranking": {}}
    load = {"state": "available", "reason": "", "unlock_date": None}
    weight = {"phase": "none", "logged_days": 12, "gap_kg": 0}
    gaps = [
        {
            "code": "aerobic_durability",
            "severity": "warn",
            "text": "No long run ≥14 km in 14d",
        }
    ]
    ranked, _noise = rank_focus_levers(
        plan_state=plan_state,
        weight=weight,
        load=load,
        gaps_top=gaps,
        volume_mix={"missing_long": True, "missing_quality": False},
    )
    ids = [r["id"] for r in ranked]
    assert "long_run" in ids
    assert ids.index("long_run") <= 2


def test_collect_required_numerals_includes_unlock_and_tss():
    facts = {
        "load": {"hold_tss": 316, "unlock_date": "2026-07-31", "acwr": 1.55},
        "weight": {"logged_days": 4, "gap_kg": 5.2},
        "rationale": "skip me as key but walk nested",
    }
    nums = collect_required_numerals(facts)
    assert "316" in nums
    assert "2026-07-31" in nums
    assert "4" in nums
