"""Pass 3–6: swap ranking, actual spend, homework, add_to_set proposals."""
from __future__ import annotations

from datetime import date, timedelta

from backend.services.session_pins import structure_actual_spend, sum_spend
from backend.services.session_swap import rank_swap_candidates
from backend.services.session_homework import (
    active_homework,
    append_homework_item,
    matches_session_type,
    pick_exercise_for_muscle,
    pre_place_for_slot,
    week_expiry,
)
from backend.services.training_load import estimate_planned_session_metrics
from backend.services.pref_catalog import validate_payload, normalize_payload


POOL = [
    {
        "id": "1",
        "name": "Back squat",
        "groups": ["heavy_compound"],
        "body_parts": [{"part": "quad", "ratio": 0.5}, {"part": "lower_back", "ratio": 0.3}],
        "tss_weight": 1.2,
        "default_sets": 4,
        "default_reps": "8",
        "default_load": "moderate",
    },
    {
        "id": "2",
        "name": "Hip thrust",
        "groups": ["heavy_compound", "accessories"],
        "body_parts": [{"part": "glute", "ratio": 0.7}, {"part": "hamstring", "ratio": 0.3}],
        "tss_weight": 1.1,
        "default_sets": 3,
        "default_reps": "12",
        "default_load": "moderate",
    },
    {
        "id": "3",
        "name": "Bird dog",
        "groups": ["accessories"],
        "body_parts": [{"part": "core", "ratio": 0.6}, {"part": "lower_back", "ratio": 0.2}],
        "tss_weight": 0.6,
        "default_sets": 3,
        "default_reps": "10",
        "default_load": "bodyweight",
    },
    {
        "id": "4",
        "name": "Clam shell",
        "groups": ["accessories", "superset"],
        "body_parts": [{"part": "glute", "ratio": 0.8}],
        "tss_weight": 0.5,
        "default_sets": 3,
        "default_reps": "15",
        "default_load": "band",
    },
]


def test_swap_block_scope_and_disable_in_session():
    result = rank_swap_candidates(
        pool=POOL,
        block="Heavy compound",
        current_name="Deadlift",
        current_body_parts=[{"part": "glute", "ratio": 0.5}],
        current_tss=17.0,
        session_names={"hip thrust": "Heavy compound"},
        avoid_parts=set(),
    )
    names = {e["name"] for e in result["eligible"]}
    assert "Back squat" in names
    assert "Hip thrust" not in names  # disabled, not eligible
    dis = {e["name"]: e for e in result["disabled"]}
    assert "Hip thrust" in dis
    assert dis["Hip thrust"]["why"] == "already in session"
    assert dis["Hip thrust"]["where"] == "Heavy compound"


def test_swap_avoid_filter_disables_not_hides():
    result = rank_swap_candidates(
        pool=POOL,
        block="heavy_compound",
        current_name="X",
        current_body_parts=None,
        current_tss=10,
        session_names={},
        avoid_parts={"lower_back"},
    )
    dis = {e["name"]: e for e in result["disabled"]}
    assert "Back squat" in dis
    assert "loads lower back" in dis["Back squat"]["why"]
    assert any(e["name"] == "Hip thrust" for e in result["eligible"])


def test_swap_search_all_blocks_escape():
    scoped = rank_swap_candidates(
        pool=POOL,
        block="heavy_compound",
        current_name="X",
        current_body_parts=None,
        current_tss=5,
        session_names={},
        query="Bird",
        search_all_blocks=False,
    )
    assert scoped["eligible"] == []
    assert scoped["offer_all_blocks"] is True
    allb = rank_swap_candidates(
        pool=POOL,
        block="heavy_compound",
        current_name="X",
        current_body_parts=None,
        current_tss=5,
        session_names={},
        query="Bird",
        search_all_blocks=True,
    )
    assert any(e["name"] == "Bird dog" for e in allb["eligible"])


def test_actual_spend_skips_skipped_rows():
    structure = {
        "target_tss": 50,
        "exercises": [
            {"name": "A", "spend_tss": 20, "spend_min": 10, "state": "done"},
            {"name": "B", "spend_tss": 15, "spend_min": 8, "state": "skipped"},
            {"name": "C", "spend_tss": 10, "spend_min": 5, "state": "done"},
        ],
    }
    spend = structure_actual_spend(structure)
    assert spend["actual_tss"] == 30.0
    assert spend["actual_duration_min"] == 15.0
    assert spend["planned_tss"] == 50.0
    assert spend["skipped_count"] == 1
    est = estimate_planned_session_metrics(
        {"strength_tss_per_min": 1.0}, "strength", structure,
    )
    assert est["estimated_tss"] == 30


def test_homework_expiry_and_type_match():
    today = date(2026, 8, 6)
    prefs = {
        "weekly_focus": [{
            "exercise_name": "Clam shell",
            "session_types": ["strength"],
            "sets": 3,
            "reps": "15",
            "expires_on": (today - timedelta(days=1)).isoformat(),
        }],
        "required_exercises": [{
            "exercise_name": "Hip thrust",
            "session_types": ["strength"],
            "sets": 3,
            "reps": "12",
        }],
    }
    active = active_homework(prefs, as_of=today)
    names = {i["exercise_name"] for i in active}
    assert "Hip thrust" in names
    assert "Clam shell" not in names  # expired
    assert matches_session_type(active[0], "strength")
    rows = pre_place_for_slot(prefs, "strength", as_of=today, pool=POOL)
    assert len(rows) == 1
    assert rows[0]["source"] == "homework_standing"
    assert rows[0]["pinned"] is True


def test_homework_week_keeps_expiry_on_replan():
    today = date(2026, 8, 6)
    keep = (today + timedelta(days=4)).isoformat()
    assert week_expiry(today=today, keep=keep) == keep
    fresh = week_expiry(today=today, keep=None)
    assert fresh == (today + timedelta(days=7)).isoformat()


def test_homework_pref_validation():
    payload = normalize_payload({
        "weekly_focus": [{
            "exercise_name": "Clam shell",
            "session_types": ["strength"],
            "sets": 3,
            "reps": "15",
            "expires_on": "2026-08-13",
        }],
    })
    errs = validate_payload(payload)
    assert "weekly_focus" not in errs


def test_pick_exercise_for_muscle_deterministic():
    a = pick_exercise_for_muscle(POOL, "glute")
    b = pick_exercise_for_muscle(POOL, "glute")
    assert a is not None and b is not None
    assert a["name"] == b["name"]
    assert a["name"] == "Clam shell"  # higher glute ratio than Hip thrust


def test_append_homework_item_fields():
    payload = {}
    week = append_homework_item(
        payload, "weekly_focus",
        {"exercise_name": "Clam shell", "session_types": ["strength"]},
        today=date(2026, 8, 6),
    )
    assert len(week["weekly_focus"]) == 1
    assert week["weekly_focus"][0]["expires_on"] == "2026-08-13"
    standing = append_homework_item(
        week, "required_exercises",
        {"exercise_name": "Clam shell", "session_types": ["strength"]},
        today=date(2026, 8, 6),
    )
    assert "expires_on" not in standing["required_exercises"][0]
