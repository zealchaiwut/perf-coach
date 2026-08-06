"""Session budget pins + exercise-level pin / refill contract."""
from __future__ import annotations

import copy
import random

from backend.services.plan_pattern_fill import fill_slot, fill_strength
from backend.services.plan_pattern_seeds import default_exercises, default_strength_patterns
from backend.services.session_pins import (
    exercise_is_pinned,
    refill_contract,
    split_pinned_exercises,
    sum_spend,
)


def test_non_generated_defaults_pinned():
    assert exercise_is_pinned({"name": "A", "source": "swap"}) is True
    assert exercise_is_pinned({"name": "B", "source": "generated"}) is False
    assert exercise_is_pinned({"name": "C", "source": "generated", "pinned": True}) is True
    assert exercise_is_pinned({"name": "D", "source": "manual", "pinned": False}) is False


def test_refill_blocked_when_pinned_exceeds_budget():
    exercises = [
        {"name": "Deadlift", "source": "swap", "pinned": True, "spend_tss": 30, "spend_min": 14, "block": "Heavy compound"},
        {"name": "RDL", "source": "manual", "pinned": True, "spend_tss": 25, "spend_min": 10, "block": "Superset 1"},
    ]
    c = refill_contract(target_tss=50, duration_minutes=45, exercises=exercises)
    assert c["ok"] is False
    assert c["blocked"] == "pinned_exceeds_budget"
    assert "exceed" in c["reason"]


def test_refill_contract_ok_with_room():
    exercises = [
        {"name": "Deadlift", "source": "swap", "pinned": True, "spend_tss": 17, "spend_min": 14, "block": "Heavy compound"},
        {"name": "Curl", "source": "generated", "pinned": False, "spend_tss": 5, "spend_min": 4, "block": "Accessories"},
    ]
    c = refill_contract(target_tss=50, duration_minutes=45, exercises=exercises)
    assert c["ok"] is True
    assert c["pinned_count"] == 1
    assert c["remain_tss"] == 33.0
    assert "keeps 1 pinned" in c["reason"]


def test_refill_keeps_pinned_rows_byte_identical():
    pat = next(p for p in default_strength_patterns() if p["subtype"] == "strength_lower")
    pool = default_exercises()
    base = fill_strength(
        pat,
        {"duration_minutes": 50, "target_tss": 40, "subtype": "strength_lower"},
        pool,
        rng=random.Random(7),
    )
    exercises = base["exercises"]
    assert len(exercises) >= 3
    # Pin first three rows deliberately
    pinned = []
    for i, ex in enumerate(exercises[:3]):
        row = copy.deepcopy(ex)
        row["source"] = "swap"
        row["pinned"] = True
        row["replaced_name"] = "Original " + str(i)
        pinned.append(row)
    for ex in exercises[3:]:
        ex["source"] = "generated"
        ex["pinned"] = False

    current = {
        "exercises": pinned + exercises[3:],
        "source": "user",
        "intent": base.get("intent"),
    }
    slot = {"duration_minutes": 50, "target_tss": 40, "subtype": "strength_lower", "workout_type": "strength", "day_offset": 1}
    out = fill_slot(
        slot,
        current=current,
        rng=random.Random(99),
        respect_exercise_pins=True,
    )
    assert not out.get("refill_blocked")
    kept = out["exercises"][:3]
    for before, after in zip(pinned, kept):
        assert after["name"] == before["name"]
        assert after["source"] == "swap"
        assert after["pinned"] is True
        assert after.get("replaced_name") == before.get("replaced_name")
        assert after.get("sets") == before.get("sets")
        assert after.get("reps") == before.get("reps")


def test_refill_blocked_returns_without_mutation():
    exercises = [
        {"name": "A", "source": "manual", "pinned": True, "spend_tss": 40, "spend_min": 20, "block": "Heavy compound"},
        {"name": "B", "source": "generated", "pinned": False, "spend_tss": 5, "spend_min": 4, "block": "Accessories"},
    ]
    current = {"exercises": copy.deepcopy(exercises), "source": "user"}
    out = fill_slot(
        {"duration_minutes": 40, "target_tss": 30, "subtype": "strength_lower", "workout_type": "strength"},
        current=current,
        respect_exercise_pins=True,
    )
    assert out.get("refill_blocked") is True
    assert out["exercises"][0]["name"] == "A"
    assert out["exercises"][1]["name"] == "B"


def test_pre_placed_reduces_pick_count_and_budget():
    pat = next(p for p in default_strength_patterns() if p["subtype"] == "strength_lower")
    pool = default_exercises()
    # Find a heavy_compound exercise from the pool
    heavy = next(e for e in pool if "heavy_compound" in (e.get("groups") or []))
    pre = [{
        "name": heavy["name"],
        "sets": 4,
        "reps": "6",
        "load": "heavy",
        "block": "Heavy compound",
        "source": "manual",
        "pinned": True,
        "spend_tss": 15,
        "spend_min": 12,
    }]
    content = fill_strength(
        pat,
        {"duration_minutes": 50, "target_tss": 40, "subtype": "strength_lower"},
        pool,
        rng=random.Random(3),
        pre_placed=pre,
    )
    names = [e["name"] for e in content["exercises"]]
    assert names[0] == heavy["name"]
    assert content["exercises"][0]["pinned"] is True
    # Trace records pre_placed
    start = content["_budget_trace"][0]
    assert start["op"] == "budget_start"
    assert start["pre_placed"] == 1
    assert start["pinned_tss"] == 15


def test_fill_scoring_untouched_same_seed_same_picks():
    """No pre_placed → identical to prior fill_strength behaviour (scoring unchanged)."""
    pat = next(p for p in default_strength_patterns() if p["subtype"] == "strength_lower")
    pool = default_exercises()
    a = fill_strength(
        pat,
        {"duration_minutes": 50, "target_tss": 40, "subtype": "strength_lower"},
        pool,
        rng=random.Random(42),
    )
    b = fill_strength(
        pat,
        {"duration_minutes": 50, "target_tss": 40, "subtype": "strength_lower"},
        pool,
        rng=random.Random(42),
    )
    assert [e["name"] for e in a["exercises"]] == [e["name"] for e in b["exercises"]]


def test_split_and_spend():
    pinned, unpinned = split_pinned_exercises([
        {"name": "A", "source": "homework_standing", "spend_tss": 8, "spend_min": 5},
        {"name": "B", "source": "generated", "spend_tss": 4, "spend_min": 3},
    ])
    assert len(pinned) == 1 and len(unpinned) == 1
    tss, mins = sum_spend(pinned)
    assert tss == 8 and mins == 5
