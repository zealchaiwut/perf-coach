"""Plan pipeline v2 Part A — skeleton, slot contract, validator, retry."""
from __future__ import annotations

from datetime import date
from copy import deepcopy

import pytest

from backend.services.load_plan import TAPER_CURVE, compute_load_plan
from backend.services.plan_skeleton import (
    assemble_week,
    build_skeleton,
    skeleton_pins_equal,
    weekly_budget,
)
from backend.services.plan_slot import (
    SLOT_PROMPT_VERSION,
    fill_week_slots,
    generate_slot_content,
    stamp_session,
    strip_volunteered_pins,
    template_content_for_slot,
    validate_slot,
    build_week_ctx,
    _duration_within_tolerance,
)
from backend.services.plan_prefs_accessor import get_plan_prefs
from backend.services.plan_suggestions import ACWR_HIGH_BOUND, FALLBACK_MIN_WEEKLY_TSS


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _hist_sat_long(weeks: int = 8) -> list[tuple[int, str, float, float]]:
    """Synthetic history: Sat long, Tue/Thu strength, Wed easy."""
    rows = []
    for _ in range(weeks):
        rows.extend([
            (1, "strength", 45, 45),
            (2, "run", 40, 45),
            (3, "strength", 40, 40),
            (5, "run", 95, 120),  # Saturday long
        ])
    return rows


# ── Budget ────────────────────────────────────────────────────────────────────

def test_weekly_budget_trailing_ramp_then_safety():
    b = weekly_budget(trailing_28d_weekly_avg_tss=200.0)
    assert b["source"] == "trailing_ramp"
    assert b["target_before_safety"] == pytest.approx(200 * 1.05, abs=0.2)
    ceiling = max(200.0, FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND
    assert b["weekly_target"] == pytest.approx(min(200 * 1.05, ceiling), abs=0.2)
    assert b["acwr_ceiling"] == pytest.approx(ceiling, abs=0.2)


def test_weekly_budget_midweek_subtracts_over_open_only():
    b = weekly_budget(
        trailing_28d_weekly_avg_tss=200.0,
        logged_tss_so_far=60.0,
        open_slot_count=4,
        race_anchored_target=200.0,
    )
    assert b["remaining_tss"] == pytest.approx(b["weekly_target"] - 60.0, abs=0.2)
    assert b["open_slot_count"] == 4
    assert b["per_open_slot_tss"] == pytest.approx(b["remaining_tss"] / 4, abs=0.2)


def test_budget_taper_week_equals_load_plan_after_clamp():
    """Regression: skeleton must not disagree with load_plan taper."""
    trailing = 280.0
    result = compute_load_plan(
        baseline=300.0,
        ramp_rate=0.05,
        hold_weeks=2,
        taper_weeks=3,
        weeks_to_race=6,
        trailing_28d_avg=trailing,
    )
    # Find a taper week
    taper_weeks = [w for w in result["weeks"] if w["phase"] == "taper"]
    assert taper_weeks, "expected at least one taper week"
    tw = taper_weeks[0]
    b = weekly_budget(
        trailing_28d_weekly_avg_tss=trailing,
        load_plan_week=tw,
    )
    # Target before safety == load_plan target; after safety ≤ ACWR ceiling
    assert b["taper_applied"] is True
    assert b["taper_curve"] == list(TAPER_CURVE)
    assert b["target_before_safety"] == pytest.approx(float(tw["target_tss"]), abs=0.2)
    ceiling = max(trailing, FALLBACK_MIN_WEEKLY_TSS) * ACWR_HIGH_BOUND
    if tw.get("ceiling") is not None:
        ceiling = min(ceiling, float(tw["ceiling"]))
    assert b["weekly_target"] == pytest.approx(min(float(tw["target_tss"]), ceiling), abs=0.2)


# ── Skeleton placement ────────────────────────────────────────────────────────

def test_skeleton_determinism():
    kwargs = dict(
        week_start=date(2026, 7, 20),
        history=_hist_sat_long(),
        preferred_rest_days=[0],
        strength_emphasis="same",
        trailing_28d_weekly_avg_tss=250.0,
        logged_tss_so_far=0.0,
    )
    a = build_skeleton(**kwargs)
    b = build_skeleton(**kwargs)
    assert len(a["slots"]) == 7
    for sa, sb in zip(a["slots"], b["slots"]):
        assert skeleton_pins_equal(sa, sb)


def test_skeleton_rest_days_and_pre_long_easy():
    sk = build_skeleton(
        week_start=date(2026, 7, 20),
        history=_hist_sat_long(),
        preferred_rest_days=[0, 3],
        strength_emphasis="same",
        trailing_28d_weekly_avg_tss=250.0,
    )
    by = {s["day_offset"]: s for s in sk["slots"]}
    assert by[0]["workout_type"] == "rest"
    assert by[3]["workout_type"] == "rest"
    long = next(s for s in sk["slots"] if s.get("subtype") == "long_run")
    pre = by.get(long["day_offset"] - 1)
    if pre is not None and pre["day_offset"] not in (0, 3):
        assert pre["workout_type"] in ("run", "rest")
        if pre["workout_type"] == "run":
            assert pre["subtype"] == "easy_run"


def test_skeleton_consecutive_training_cap():
    sk = build_skeleton(
        week_start=date(2026, 7, 20),
        history=_hist_sat_long(),
        preferred_rest_days=[],
        strength_emphasis="more",
        trailing_28d_weekly_avg_tss=300.0,
    )
    streak = 0
    max_streak = 0
    for s in sorted(sk["slots"], key=lambda x: x["day_offset"]):
        if s["workout_type"] != "rest":
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    assert max_streak <= 3


def test_skeleton_budget_sums_near_target():
    sk = build_skeleton(
        week_start=date(2026, 7, 20),
        history=_hist_sat_long(),
        preferred_rest_days=[0],
        trailing_28d_weekly_avg_tss=200.0,
        logged_tss_so_far=0.0,
    )
    total = sum(s["target_tss"] for s in sk["slots"] if s["workout_type"] != "rest")
    target = sk["budget"]["remaining_tss"]
    # ± rounding / clamp noise — allow 15 TSS slack
    assert abs(total - target) <= 15


# ── Contract ──────────────────────────────────────────────────────────────────

def test_strip_volunteered_pins():
    raw = {
        "day_offset": 9,
        "workout_type": "plyo",
        "target_tss": 999,
        "duration_minutes": 12,
        "intent": "Easy jog",
        "blocks": [{"phase": "warmup", "duration_min": 10, "repeat": 1, "rest_min": 0, "target": "easy"}],
    }
    clean = strip_volunteered_pins(raw)
    assert "day_offset" not in clean
    assert "target_tss" not in clean
    assert clean["intent"] == "Easy jog"


def test_stamp_session_pins_win():
    slot = {
        "day_offset": 5,
        "workout_type": "run",
        "target_tss": 90,
        "duration_minutes": 110,
        "subtype": "long_run",
        "structure_hints": {"fueling": True},
        "locked": False,
    }
    content = {
        "day_offset": 0,
        "target_tss": 1,
        "intent": "Long aerobic",
        "blocks": [
            {"phase": "warmup", "duration_min": 15, "repeat": 1, "rest_min": 0, "target": "easy"},
            {"phase": "main", "duration_min": 80, "repeat": 1, "rest_min": 0, "target": "Z2 gel at 40"},
            {"phase": "cooldown", "duration_min": 15, "repeat": 1, "rest_min": 0, "target": "easy"},
        ],
        "source": "llm",
    }
    sess = stamp_session(slot, content)
    assert sess["day_offset"] == 5
    assert sess["target_tss"] == 90
    assert sess["duration_minutes"] == 110
    assert sess["intent"] == "Long aerobic"


# ── Validator ─────────────────────────────────────────────────────────────────

def _good_easy_blocks(dur=45):
    w = max(5, int(dur * 0.15))
    c = max(5, int(dur * 0.15))
    m = max(1, dur - w - c)
    return [
        {"phase": "warmup", "duration_min": w, "repeat": 1, "rest_min": 0, "target": "easy"},
        {"phase": "main", "duration_min": m, "repeat": 1, "rest_min": 0, "target": "easy Z2"},
        {"phase": "cooldown", "duration_min": c, "repeat": 1, "rest_min": 0, "target": "easy"},
    ]


def test_validate_run_pass_and_fail():
    slot = {"workout_type": "run", "duration_minutes": 45, "subtype": "easy_run", "structure_hints": {}}
    ok = {"intent": "Easy run", "blocks": _good_easy_blocks(45)}
    assert validate_slot(ok, slot) == []

    bad = {"intent": "Intervals VO2", "blocks": _good_easy_blocks(45)}
    errs = validate_slot(bad, slot)
    assert any("hard-intent" in e for e in errs)

    no_blocks = {"intent": "Easy", "blocks": None}
    assert any("blocks" in e for e in validate_slot(no_blocks, slot))


def test_validate_blocks_sum_tolerance_edges():
    assert _duration_within_tolerance(45, 45) is True
    assert _duration_within_tolerance(49, 45) is True   # within ±5 min floor
    assert _duration_within_tolerance(51, 45) is False
    # 10% of 100 = 10
    assert _duration_within_tolerance(110, 100) is True
    assert _duration_within_tolerance(111, 100) is False


def test_validate_long_run_fueling():
    slot = {
        "workout_type": "run",
        "duration_minutes": 110,
        "subtype": "long_run",
        "structure_hints": {"fueling": True},
    }
    blocks = _good_easy_blocks(110)
    bad = {"intent": "Long aerobic", "blocks": blocks}
    assert any("fueling" in e for e in validate_slot(bad, slot))
    good = {"intent": "Long run — take a gel at 40", "blocks": blocks}
    assert validate_slot(good, slot) == []


def test_validate_strength_pass_and_fail():
    slot = {"workout_type": "strength", "duration_minutes": 45, "subtype": "strength_lower"}
    exercises = [
        {"block": "Warm-up", "name": "Squat", "sets": 2, "reps": "10", "load": "bw"},
        {"block": "Heavy compound", "name": "Back squat", "sets": 4, "reps": "8", "load": "mod"},
        {"block": "Superset 1", "name": "RDL", "sets": 3, "reps": "10", "load": "mod"},
        {"block": "Accessories", "name": "Plank", "sets": 3, "reps": "40s", "load": "bw"},
    ]
    assert validate_slot({"intent": "Lower", "exercises": exercises}, slot) == []

    bad_label = deepcopy(exercises)
    bad_label[1]["block"] = "Upper body push"
    errs = validate_slot({"intent": "Lower", "exercises": bad_label}, slot)
    assert any("block label" in e for e in errs)

    too_few = exercises[:2]
    assert any("4–12" in e or "4-12" in e or "4–10" in e for e in validate_slot({"intent": "x", "exercises": too_few}, slot))


def test_validate_intent_max_140():
    slot = {"workout_type": "rest", "duration_minutes": 0, "subtype": "rest"}
    errs = validate_slot({"intent": "x" * 141}, slot)
    assert any("140" in e for e in errs)


# ── Pattern fill (planning LLM removed) ───────────────────────────────────────

def test_retry_bad_then_good_is_llm():
    """llm_call is ignored — fill_slot owns content (template without a DB)."""
    slot = {
        "day_offset": 2,
        "workout_type": "run",
        "target_tss": 40,
        "duration_minutes": 45,
        "subtype": "easy_run",
        "structure_hints": {},
        "locked": False,
    }
    week_ctx = build_week_ctx(facts={}, skeleton_slots=[slot])
    calls = {"n": 0}

    def llm(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"intent": "Intervals VO2 max", "blocks": _good_easy_blocks(45)}
        return {"intent": "Easy aerobic", "blocks": _good_easy_blocks(45)}

    out = generate_slot_content(week_ctx, slot, llm_call=llm)
    assert out["source"] in ("pattern", "template")
    assert calls["n"] == 0
    assert out.get("blocks")


def test_retry_two_bad_is_template():
    slot = {
        "day_offset": 2,
        "workout_type": "run",
        "target_tss": 40,
        "duration_minutes": 45,
        "subtype": "easy_run",
        "structure_hints": {},
        "locked": False,
    }
    week_ctx = build_week_ctx(facts={}, skeleton_slots=[slot])

    def llm(system, user):
        return {"intent": "Intervals VO2", "blocks": _good_easy_blocks(45)}

    out = generate_slot_content(week_ctx, slot, llm_call=llm)
    assert out["source"] in ("pattern", "template")
    assert out.get("blocks")


def test_failed_call_burns_a_try():
    slot = {
        "day_offset": 2,
        "workout_type": "run",
        "target_tss": 40,
        "duration_minutes": 45,
        "subtype": "easy_run",
        "structure_hints": {},
        "locked": False,
    }
    week_ctx = build_week_ctx(facts={}, skeleton_slots=[slot])
    calls = {"n": 0}

    def llm(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # failed/unparseable burns try
        return {"intent": "Easy aerobic", "blocks": _good_easy_blocks(45)}

    out = generate_slot_content(week_ctx, slot, llm_call=llm)
    assert out["source"] in ("pattern", "template")
    assert calls["n"] == 0
    assert out.get("blocks")


def test_two_failed_calls_template():
    slot = {
        "day_offset": 2,
        "workout_type": "run",
        "target_tss": 40,
        "duration_minutes": 45,
        "subtype": "easy_run",
        "structure_hints": {},
        "locked": False,
    }
    week_ctx = build_week_ctx(facts={}, skeleton_slots=[slot])

    def llm(system, user):
        return None

    out = generate_slot_content(week_ctx, slot, llm_call=llm)
    assert out["source"] in ("pattern", "template")
    assert out.get("blocks")


# ── Assemble ──────────────────────────────────────────────────────────────────

def test_assemble_stamps_and_serves_on_sanity_noise():
    sk = build_skeleton(
        week_start=date(2026, 7, 20),
        history=_hist_sat_long(),
        preferred_rest_days=[0],
        trailing_28d_weekly_avg_tss=200.0,
    )
    week_ctx = build_week_ctx(
        facts={"trailing_28d_weekly_avg_tss": 200, "preferred_rest_days": [0], "allowed_offsets": list(range(7))},
        skeleton_slots=sk["slots"],
    )
    contents = fill_week_slots(week_ctx, sk["slots"], llm_call=None)
    result = assemble_week(sk["slots"], contents, facts=week_ctx.get("load") and {
        "trailing_28d_weekly_avg_tss": 200,
        "preferred_rest_days": [0],
        "allowed_offsets": list(range(7)),
    })
    assert result["source"] == "skeleton_v2"
    assert len(result["sessions"]) == 7
    for sess, slot in zip(result["sessions"], sk["slots"]):
        assert sess["target_tss"] == slot["target_tss"]
        assert sess["day_offset"] == slot["day_offset"]


def test_prefs_accessor_defaults_without_store():
    p = get_plan_prefs(preferred_rest_days=[6], strength_emphasis="more", notes="keep easy")
    assert p["preferred_rest_days"] == [6]
    assert p["strength_emphasis"] == "more"
    assert p["notes"] == "keep easy"
    assert p["prefs_version"] == 0


def test_slot_prompt_version_constant():
    assert SLOT_PROMPT_VERSION.startswith("2026-")


# ── Slot cache key isolation (Part B3) ────────────────────────────────────────

def test_cache_key_ignores_ctl_nudge():
    from backend.services.plan_slot_cache import slot_cache_key

    pins = {
        "day_offset": 5,
        "workout_type": "run",
        "target_tss": 92,
        "duration_minutes": 110,
        "subtype": "long_run",
        "structure_hints": {"fueling": True},
    }
    ctx = {
        "emphasis": "same",
        "taper_state": False,
        "notes": "",
        "recent_exercise_names": ["Back squat"],
        "race_bucket": "build",
    }
    a = slot_cache_key(pins=pins, content_ctx=ctx)
    # CTL is not in the key — identical pins/ctx ⇒ identical key
    b = slot_cache_key(pins=pins, content_ctx=ctx)
    assert a == b


def test_cache_key_moves_with_saturday_budget():
    from backend.services.plan_slot_cache import slot_cache_key

    base_pins = {
        "day_offset": 5,
        "workout_type": "run",
        "target_tss": 90,
        "duration_minutes": 110,
        "subtype": "long_run",
        "structure_hints": {},
    }
    ctx = {"emphasis": "same", "taper_state": False, "notes": "", "recent_exercise_names": []}
    a = slot_cache_key(pins=base_pins, content_ctx=ctx)
    moved = dict(base_pins, target_tss=110)
    b = slot_cache_key(pins=moved, content_ctx=ctx)
    assert a != b


def test_cache_key_emphasis_only_affects_when_in_ctx():
    from backend.services.plan_slot_cache import slot_cache_key

    pins = {
        "day_offset": 1,
        "workout_type": "strength",
        "target_tss": 45,
        "duration_minutes": 45,
        "subtype": "strength_lower",
        "structure_hints": {},
    }
    a = slot_cache_key(pins=pins, content_ctx={"emphasis": "same", "notes": "", "recent_exercise_names": []})
    b = slot_cache_key(pins=pins, content_ctx={"emphasis": "more", "notes": "", "recent_exercise_names": []})
    assert a != b


def test_cache_key_notes_edit_changes_all():
    from backend.services.plan_slot_cache import slot_cache_key

    pins = {
        "day_offset": 2,
        "workout_type": "run",
        "target_tss": 40,
        "duration_minutes": 45,
        "subtype": "easy_run",
        "structure_hints": {},
    }
    a = slot_cache_key(pins=pins, content_ctx={"emphasis": "same", "notes": "", "recent_exercise_names": []})
    b = slot_cache_key(pins=pins, content_ctx={"emphasis": "same", "notes": "keep easy", "recent_exercise_names": []})
    assert a != b
