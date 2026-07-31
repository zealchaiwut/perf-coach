"""Phase 3 — stretch, plyo and the monthly benchmark in the plan (spec §8, D5).

Stretch, plyo and drills move OUT of habits and INTO the plan: a checkbox asks
the athlete to remember and then to confirm; a planned session that verifies
itself from a logged workout does neither.

The most important property here is the boring one: **with no prefs set and a
non-benchmark week, this is the identity function.** ``build_skeleton`` has a
"same inputs ⇒ identical skeleton" contract and several callers, so a decorator
that quietly changed everyone's week would be a bad trade for a preference most
athletes leave off.
"""
from __future__ import annotations

import datetime

import pytest

from backend.services.plan_extras import (
    PLYO_STANDALONE_TSS,
    apply_prefs_extras,
    attach_benchmark,
    attach_plyo,
    attach_stretch,
    is_benchmark_week,
    planned_extras_summary,
)

BENCHMARK_WEEK = datetime.date(2026, 8, 3)      # first Monday of the month
ORDINARY_WEEK = datetime.date(2026, 8, 17)      # mid-month


def _slot(day, wtype="run", subtype="easy_run", tss=40, locked=False) -> dict:
    return {
        "day_offset": day,
        "workout_type": wtype,
        "subtype": subtype,
        "target_tss": tss,
        "duration_minutes": 45,
        "structure_hints": {},
        "locked": locked,
    }


def _week() -> list[dict]:
    return [
        _slot(0, "strength", "strength", 30),
        _slot(1, "run", "easy_run", 40),
        _slot(2, "rest", "rest", 0),
        _slot(3, "run", "tempo", 65),
        _slot(4, "rest", "rest", 0),
        _slot(5, "run", "long_run", 95),
        _slot(6, "rest", "rest", 0),
    ]


def _skeleton(week_start=ORDINARY_WEEK) -> dict:
    return {"week_start": week_start.isoformat(), "budget": {}, "slots": _week()}


# ── The identity property ────────────────────────────────────────────────────

def test_no_prefs_and_an_ordinary_week_changes_nothing():
    """The contract that makes this safe to add."""
    before = _skeleton()
    after = apply_prefs_extras(before, prefs={}, week_start=ORDINARY_WEEK)
    assert after["slots"] == before["slots"]


def test_the_input_skeleton_is_never_mutated():
    before = _skeleton()
    original = [dict(s) for s in before["slots"]]
    apply_prefs_extras(before, prefs={"stretch_daily_min": 10}, week_start=ORDINARY_WEEK)
    assert before["slots"] == original


def test_week_start_is_read_from_the_skeleton_when_not_passed():
    out = apply_prefs_extras(_skeleton(BENCHMARK_WEEK), prefs={})
    assert any(s.get("benchmark") for s in out["slots"])


# ── Stretch ──────────────────────────────────────────────────────────────────

def test_stretch_lands_on_every_day_including_rest():
    """Mobility on a rest day is the point, not an oversight."""
    slots = attach_stretch(_week(), 12)
    assert len(slots) == 7
    for slot in slots:
        kinds = [e["kind"] for e in slot["daily_extras"]]
        assert "stretch" in kinds


def test_stretch_carries_no_tss():
    """Stretching is not a training session and must not eat the load budget."""
    slots = attach_stretch(_week(), 12)
    before = sum(s["target_tss"] for s in _week())
    after = sum(s["target_tss"] for s in slots)
    assert after == before
    for slot in slots:
        for extra in slot["daily_extras"]:
            if extra["kind"] == "stretch":
                assert extra["target_tss"] == 0


@pytest.mark.parametrize("value", [0, None, -5])
def test_no_stretch_preference_leaves_the_week_alone(value):
    slots = attach_stretch(_week(), value)
    assert all("daily_extras" not in s for s in slots)


def test_stretch_duration_comes_from_the_preference():
    slots = attach_stretch(_week(), 15)
    extra = slots[0]["daily_extras"][0]
    assert extra["duration_minutes"] == 15
    assert extra["source"] == "prefs.stretch_daily_min"


# ── Plyo ─────────────────────────────────────────────────────────────────────

def test_plyo_off_by_default():
    slots = attach_plyo(_week(), plyo_mode="off", plyo_sessions_per_week=2)
    assert all(s["workout_type"] != "plyo" for s in slots)
    assert all("daily_extras" not in s for s in slots)


def test_zero_sessions_places_nothing():
    slots = attach_plyo(_week(), plyo_mode="standalone", plyo_sessions_per_week=0)
    assert all(s["workout_type"] != "plyo" for s in slots)


def test_superset_mode_hangs_plyo_off_a_strength_day():
    slots = attach_plyo(_week(), plyo_mode="superset", plyo_sessions_per_week=1)
    strength = slots[0]
    assert strength["workout_type"] == "strength"
    assert [e["kind"] for e in strength["daily_extras"]] == ["plyo"]
    # No new session was created.
    assert all(s["workout_type"] != "plyo" for s in slots)


def test_standalone_mode_claims_its_own_day():
    slots = attach_plyo(_week(), plyo_mode="standalone", plyo_sessions_per_week=1)
    plyo = [s for s in slots if s["workout_type"] == "plyo"]
    assert len(plyo) == 1
    assert plyo[0]["target_tss"] == PLYO_STANDALONE_TSS


def test_standalone_plyo_only_takes_a_rest_or_easy_day():
    """It must never overwrite the long run or a quality session."""
    slots = attach_plyo(_week(), plyo_mode="standalone", plyo_sessions_per_week=3)
    by_day = {s["day_offset"]: s for s in slots}
    assert by_day[5]["subtype"] == "long_run"
    assert by_day[3]["subtype"] == "tempo"


def test_standalone_plyo_avoids_preferred_rest_days():
    slots = attach_plyo(
        _week(), plyo_mode="standalone", plyo_sessions_per_week=2, rest_days={1, 2}
    )
    for slot in slots:
        if slot["workout_type"] == "plyo":
            assert slot["day_offset"] not in (1, 2)


def test_locked_slots_are_never_touched():
    week = _week()
    week[1] = _slot(1, "run", "easy_run", 40, locked=True)
    slots = attach_plyo(week, plyo_mode="standalone", plyo_sessions_per_week=1)
    assert slots[1]["workout_type"] == "run"


def test_plyo_placement_is_capped_at_the_requested_count():
    slots = attach_plyo(_week(), plyo_mode="standalone", plyo_sessions_per_week=2)
    assert sum(1 for s in slots if s["workout_type"] == "plyo") == 2


# ── Monthly benchmark ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "week_start,expected",
    [
        (datetime.date(2026, 8, 3), True),
        (datetime.date(2026, 8, 1), True),
        (datetime.date(2026, 8, 10), False),
        (datetime.date(2026, 8, 24), False),
    ],
)
def test_benchmark_weeks_are_the_month_s_first(week_start, expected):
    assert is_benchmark_week(week_start) is expected


def test_the_benchmark_flags_the_long_run():
    slots = attach_benchmark(_week(), BENCHMARK_WEEK)
    long_run = next(s for s in slots if s["subtype"] == "long_run")
    assert long_run["benchmark"] is True
    assert "fixed route" in long_run["structure_hints"]["benchmark"]


def test_no_benchmark_in_an_ordinary_week():
    slots = attach_benchmark(_week(), ORDINARY_WEEK)
    assert all("benchmark" not in s for s in slots)


def test_only_one_session_is_flagged():
    slots = attach_benchmark(_week(), BENCHMARK_WEEK)
    assert sum(1 for s in slots if s.get("benchmark")) == 1


def test_a_week_without_a_long_run_gets_no_benchmark():
    week = [s for s in _week() if s["subtype"] != "long_run"]
    slots = attach_benchmark(week, BENCHMARK_WEEK)
    assert all("benchmark" not in s for s in slots)


# ── Summary ──────────────────────────────────────────────────────────────────

def test_summary_reports_what_the_week_asks_for():
    out = apply_prefs_extras(
        _skeleton(BENCHMARK_WEEK),
        prefs={"stretch_daily_min": 10, "plyo_mode": "standalone", "plyo_sessions_per_week": 2},
        week_start=BENCHMARK_WEEK,
    )
    summary = planned_extras_summary(out["slots"])
    assert summary["stretch_minutes_planned"] == 70   # 10 min × 7 days
    assert summary["plyo_sessions_planned"] == 2
    assert summary["benchmark_week"] is True


def test_summary_of_an_untouched_week_is_all_zero():
    summary = planned_extras_summary(_week())
    assert summary == {
        "stretch_minutes_planned": 0,
        "plyo_sessions_planned": 0,
        "benchmark_week": False,
    }


def test_superset_plyo_counts_in_the_summary():
    out = apply_prefs_extras(
        _skeleton(),
        prefs={"plyo_mode": "superset", "plyo_sessions_per_week": 1},
        week_start=ORDINARY_WEEK,
    )
    assert planned_extras_summary(out["slots"])["plyo_sessions_planned"] == 1
