"""Pattern-based plan fill — bands, focus bias, balancer, no-LLM guarantees."""
from __future__ import annotations

import random

import pytest

from backend.services.plan_pattern_fill import (
    fill_run,
    fill_slot,
    fill_strength,
    select_pattern,
)
from backend.services.plan_pattern_seeds import default_exercises, default_run_patterns, default_strength_patterns
from backend.services.plan_week_balance import balance_week_sessions, build_muscle_summary


def test_select_pattern_by_duration_band_and_subtype():
    pat = select_pattern(None, workout_type="run", subtype="easy_run", duration_min=70)
    assert pat is not None
    assert pat["kind"] == "run"
    assert pat["subtype"] == "easy_run"
    assert pat["duration_min_lo"] <= 70 <= pat["duration_min_hi"]


def test_easy_70_min_warmup_main_cooldown_scaled():
    pat = select_pattern(None, workout_type="run", subtype="easy", duration_min=70)
    assert pat is not None
    content = fill_run(pat, {"duration_minutes": 70, "subtype": "easy_run"})
    phases = [b["phase"] for b in content["blocks"]]
    assert phases == ["warmup", "main", "cooldown"]
    total = sum(int(b["duration_min"]) for b in content["blocks"])
    assert abs(total - 70) <= 2  # rounding on last block
    assert content["source"] == "pattern"
    assert "easy" in (content["intent"] or "").lower()


def test_strength_lower_focus_bias_prefers_lower_tags():
    pat = next(p for p in default_strength_patterns() if p["subtype"] == "strength_lower")
    pool = default_exercises()
    rng = random.Random(42)
    content = fill_strength(
        pat,
        {"duration_minutes": 50, "target_tss": 40, "subtype": "strength_lower"},
        pool,
        rng=rng,
    )
    assert content["exercises"]
    assert 4 <= len(content["exercises"]) <= 10
    names = {e["name"] for e in content["exercises"]}
    # Seeded lower session should include at least one lower-tagged compound
    lower_names = {
        e["name"] for e in pool
        if "lower" in e["focus_tags"] and "heavy_compound" in e["groups"]
    }
    assert names & lower_names
    assert content.get("_muscle_footprint")


def test_week_balancer_swaps_adjacent_lower_days():
    pool = default_exercises()
    pat_lower = next(p for p in default_strength_patterns() if p["subtype"] == "strength_lower")
    rng = random.Random(7)

    def _str_day(offset, seed):
        c = fill_strength(
            pat_lower,
            {
                "day_offset": offset,
                "workout_type": "strength",
                "target_tss": 35,
                "duration_minutes": 45,
                "subtype": "strength_lower",
            },
            pool,
            rng=random.Random(seed),
        )
        return {
            "day_offset": offset,
            "workout_type": "strength",
            "target_tss": 35,
            "duration_minutes": 45,
            "subtype": "strength_lower",
            "intent": c["intent"],
            "exercises": c["exercises"],
            "source": "pattern",
            "_muscle_footprint": c.get("_muscle_footprint") or {"quad": 2.0, "glute": 1.5},
            "slot_id": f"s{offset}",
        }

    sessions = [
        {"day_offset": 0, "workout_type": "rest", "target_tss": 0, "duration_minutes": 0, "intent": "Rest", "source": "template"},
        _str_day(1, 1),
        _str_day(2, 1),  # same footprint seed → overlap
        {"day_offset": 3, "workout_type": "run", "target_tss": 40, "duration_minutes": 45, "subtype": "easy_run", "intent": "Easy", "source": "pattern"},
    ]
    # Force identical footprints so balancer must try a swap
    sessions[1]["_muscle_footprint"] = {"quad": 3.0, "glute": 2.0}
    sessions[2]["_muscle_footprint"] = {"quad": 3.0, "glute": 2.0}
    before_names = [e["name"] for e in sessions[2]["exercises"]]
    out, summary = balance_week_sessions(sessions, db=None, week_ctx={})
    assert summary.get("swaps", 0) >= 1
    day2 = next(s for s in out if s["day_offset"] == 2)
    after_names = [e["name"] for e in (day2.get("exercises") or [])]
    # Pins unchanged
    assert day2["target_tss"] == 35
    assert day2["duration_minutes"] == 45
    assert day2["workout_type"] == "strength"
    assert build_muscle_summary(out)["week_heatmap"] is not None
    # Content should have been refilled (may or may not change names depending on avoid)
    assert after_names  # still has exercises
    del before_names, rng


def test_generate_slot_content_never_calls_llm(monkeypatch):
    from backend.services import plan_slot as ps

    def _boom(*_a, **_k):
        raise AssertionError("LLM must not be called for pattern fill")

    monkeypatch.setattr(ps, "generate_slot_content", ps.generate_slot_content)
    # Patch llm helpers if imported later — fill_slot path should not touch them
    content = ps.generate_slot_content(
        {"skeleton_slots": []},
        {
            "day_offset": 1,
            "workout_type": "run",
            "target_tss": 40,
            "duration_minutes": 70,
            "subtype": "easy",
        },
        llm_call=_boom,
        db=None,
    )
    assert content["source"] in ("pattern", "template")
    assert content.get("blocks")


def test_fill_slot_ignores_llm_call_callable():
    called = {"n": 0}

    def llm(_s, _u):
        called["n"] += 1
        return {"intent": "SHOULD NOT APPEAR"}

    from backend.services.plan_slot import generate_slot_content

    out = generate_slot_content(
        {},
        {
            "day_offset": 0,
            "workout_type": "run",
            "target_tss": 30,
            "duration_minutes": 45,
            "subtype": "easy_run",
        },
        llm_call=llm,
    )
    assert called["n"] == 0
    assert out.get("intent") != "SHOULD NOT APPEAR"
    assert out["source"] in ("pattern", "template")


def test_seed_run_patterns_cover_core_subtypes():
    subs = {p["subtype"] for p in default_run_patterns()}
    assert {"easy_run", "tempo", "intervals", "long_run"} <= subs


@pytest.mark.parametrize(
    "kind,subtype,dur",
    [
        ("run", "tempo", 50),
        ("run", "intervals", 55),
        ("strength", "strength_upper", 45),
        ("strength", "strength_full", 60),
    ],
)
def test_select_pattern_parametrized(kind, subtype, dur):
    wt = "run" if kind == "run" else "strength"
    pat = select_pattern(None, workout_type=wt, subtype=subtype, duration_min=dur)
    assert pat is not None
    assert pat["subtype"] == subtype
