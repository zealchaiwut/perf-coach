"""Plan-suggestion v2: scope to the OPEN remainder of a week, honour athlete
input (rest days / strength emphasis / notes), and new training-safety rules
(no hard run the day before the long run; no >3 consecutive training days).

PRD feedback (2026-07-08): "Suggest sessions" always proposed a fresh Mon-Sun
week regardless of today, ignored what was already scheduled/logged, took no
input, and had no long-run/spacing awareness.

Real-Postgres for the assemble_facts DB tests (existing schedule query); pure
unit tests for validation_errors/fallback_suggestions/build_prompt (no DB).
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import backend.services.plan_suggestions as ps
from backend.db import engine
from backend.models import PlannedSession, User, Workout


# ── back-compat: pure functions default to the whole week when the new keys
#    are absent — old callers/tests must see byte-identical behaviour ────────

def _old_style_facts(trailing=200.0):
    return {"trailing_28d_weekly_avg_tss": trailing}


_EASY_BLOCKS = [
    {"phase": "warmup", "duration_min": 10, "repeat": None, "rest_min": None, "target": "easy"},
    {"phase": "main", "duration_min": 20, "repeat": None, "rest_min": None, "target": "easy"},
]


def _run(offset, tss=30, duration=30, intent="x", blocks=_EASY_BLOCKS):
    """A valid 'run' suggestion (blocks included) for tests exercising rules
    OTHER than the blocks-required-for-run rule itself."""
    return {"day_offset": offset, "workout_type": "run", "target_tss": tss,
            "duration_minutes": duration, "intent": intent, "blocks": blocks}


def test_fallback_suggestions_full_week_when_no_scoping_keys():
    result = ps.fallback_suggestions(_old_style_facts())
    assert [s["day_offset"] for s in result] == list(range(7))


def test_validation_errors_empty_facts_means_whole_week_allowed():
    good = [{"day_offset": i, "workout_type": "rest", "target_tss": 0,
             "duration_minutes": 0, "intent": "x"} for i in range(7)]
    assert ps.validation_errors(good, _old_style_facts()) == []


# ── scoping: allowed_offsets restricts fallback + is enforced in validation ──

def test_fallback_suggestions_restricted_to_allowed_offsets():
    facts = {**_old_style_facts(), "allowed_offsets": [2, 3, 4, 5, 6]}
    result = ps.fallback_suggestions(facts)
    assert [s["day_offset"] for s in result] == [2, 3, 4, 5, 6]


def test_validation_rejects_offset_outside_allowed():
    facts = {**_old_style_facts(), "allowed_offsets": [2, 3, 4, 5, 6]}
    bad = [_run(0, tss=50)]
    errs = ps.validation_errors(bad, facts)
    assert any("day_offset 0" in e and "not open" in e for e in errs)


# ── preferred rest days ───────────────────────────────────────────────────────

def test_fallback_suggestions_forces_requested_rest_days():
    facts = {**_old_style_facts(), "preferred_rest_days": [2, 5]}
    result = ps.fallback_suggestions(facts)
    by_off = {s["day_offset"]: s for s in result}
    assert by_off[2]["workout_type"] == "rest" and by_off[2]["target_tss"] == 0
    assert by_off[5]["workout_type"] == "rest" and by_off[5]["target_tss"] == 0


def test_validation_rejects_non_rest_on_requested_rest_day():
    facts = {**_old_style_facts(), "preferred_rest_days": [3]}
    bad = [_run(3, tss=50)]
    errs = ps.validation_errors(bad, facts)
    assert any("day_offset 3" in e and "REST" in e for e in errs)


def test_validation_allows_rest_on_requested_rest_day():
    facts = {**_old_style_facts(), "preferred_rest_days": [3]}
    ok = [{"day_offset": 3, "workout_type": "rest", "target_tss": 0,
           "duration_minutes": 0, "intent": "rest"}]
    assert ps.validation_errors(ok, facts) == []


def test_validation_rejects_omitted_requested_rest_day():
    """A requested rest day must show up explicitly as rest — silently
    omitting it isn't enough (the athlete checked that box to see it honoured)."""
    facts = {**_old_style_facts(), "preferred_rest_days": [3]}
    no_mention = [_run(4, tss=50)]
    errs = ps.validation_errors(no_mention, facts)
    assert any("day_offset 3" in e and "no session at all" in e for e in errs)


# ── strength emphasis ─────────────────────────────────────────────────────────

def test_fallback_more_strength_converts_an_easy_run():
    before = ps.fallback_suggestions(_old_style_facts())
    before_strength = sum(1 for s in before if s["workout_type"] == "strength")

    facts = {**_old_style_facts(), "strength_emphasis": "more"}
    after = ps.fallback_suggestions(facts)
    after_strength = sum(1 for s in after if s["workout_type"] == "strength")
    assert after_strength == before_strength + 1


def test_fallback_more_strength_never_converts_the_long_run():
    facts = {**_old_style_facts(), "strength_emphasis": "more"}
    result = ps.fallback_suggestions(facts)
    long_run = ps._find_long_run(ps.fallback_suggestions(_old_style_facts()))
    assert long_run is not None
    kept = next(s for s in result if s["day_offset"] == long_run["day_offset"])
    assert kept["workout_type"] == "run"


def test_fallback_less_strength_converts_one_to_rest():
    facts = {**_old_style_facts(), "strength_emphasis": "less"}
    result = ps.fallback_suggestions(facts)
    before_strength = sum(1 for s in ps.fallback_suggestions(_old_style_facts())
                          if s["workout_type"] == "strength")
    after_strength = sum(1 for s in result if s["workout_type"] == "strength")
    assert after_strength == before_strength - 1


def test_fallback_invalid_emphasis_treated_as_same():
    facts = {**_old_style_facts(), "strength_emphasis": "nonsense"}
    result = ps.fallback_suggestions(facts)
    baseline = ps.fallback_suggestions(_old_style_facts())
    assert [s["workout_type"] for s in result] == [s["workout_type"] for s in baseline]


# ── new hard rule: no hard run the day before the long run ──────────────────

def test_validation_rejects_hard_run_before_long_run_by_tss():
    # long run at offset 5 (tss 200); offset 4 run at 180 (>=70% of 200) -> hard
    suggestions = [
        _run(4, tss=180, duration=60, intent="steady run"),
        _run(5, tss=200, duration=90, intent="long run"),
    ]
    errs = ps.validation_errors(suggestions, _old_style_facts())
    assert any("before the long run" in e for e in errs)


def test_validation_rejects_hard_run_before_long_run_by_keyword():
    suggestions = [
        _run(4, tss=20, duration=30, intent="Tempo intervals at threshold"),
        _run(5, tss=200, duration=90, intent="long run"),
    ]
    errs = ps.validation_errors(suggestions, _old_style_facts())
    assert any("before the long run" in e for e in errs)


def test_validation_allows_easy_run_before_long_run():
    suggestions = [
        _run(4, tss=30, duration=30, intent="easy shakeout jog"),
        _run(5, tss=200, duration=90, intent="long run"),
    ]
    errs = ps.validation_errors(suggestions, _old_style_facts())
    assert not any("before the long run" in e for e in errs)


def test_validation_allows_rest_before_long_run():
    suggestions = [
        {"day_offset": 4, "workout_type": "rest", "target_tss": 0, "duration_minutes": 0, "intent": "rest"},
        _run(5, tss=200, duration=90, intent="long run"),
    ]
    assert ps.validation_errors(suggestions, _old_style_facts()) == []


def test_no_long_run_rule_when_fewer_than_two_runs():
    suggestions = [_run(5, tss=200, duration=90, intent="long run")]
    assert ps._find_long_run(suggestions) is None
    assert ps.validation_errors(suggestions, _old_style_facts()) == []


# ── new hard rule: no more than 3 consecutive training days ──────────────────

def test_validation_rejects_four_consecutive_training_days():
    suggestions = [_run(i) for i in range(4)]
    errs = ps.validation_errors(suggestions, _old_style_facts())
    assert any("consecutive training days" in e for e in errs)


def test_validation_allows_three_consecutive_training_days():
    suggestions = [_run(i) for i in range(3)]
    assert not any("consecutive" in e for e in ps.validation_errors(suggestions, _old_style_facts()))


def test_validation_missing_day_counts_as_a_break_in_the_streak():
    # offsets 0,1,2 training, offset 3 has NO suggestion (implicit rest), 4,5,6 training
    # -> longest streak is 3, not 6.
    suggestions = [_run(i) for i in (0, 1, 2, 4, 5, 6)]
    assert not any("consecutive" in e for e in ps.validation_errors(suggestions, _old_style_facts()))


# ── build_prompt mentions scoping / prefs / rules ─────────────────────────────

def test_build_prompt_mentions_allowed_offsets():
    facts = {**_old_style_facts(), "allowed_offsets": [3, 4, 5, 6]}
    sys_p, user_p = ps.build_prompt(facts)
    combined = sys_p + user_p
    assert "3" in combined and "Thursday" in combined


def test_build_prompt_mentions_requested_rest_days():
    facts = {**_old_style_facts(), "preferred_rest_days": [2]}
    sys_p, _ = ps.build_prompt(facts)
    assert "REST" in sys_p and "2" in sys_p


def test_build_prompt_mentions_strength_emphasis():
    facts = {**_old_style_facts(), "strength_emphasis": "more"}
    _, user_p = ps.build_prompt(facts)
    assert "MORE strength" in user_p


def test_build_prompt_mentions_notes():
    facts = {**_old_style_facts(), "notes": "easing back after a cold"}
    _, user_p = ps.build_prompt(facts)
    assert "easing back after a cold" in user_p


def test_build_prompt_notes_get_a_binding_rule():
    """With notes present, the system prompt must carry a numbered rule making
    them binding scheduling constraints — without it the generic phase-mix
    template outranks the athlete's own day/type requests (observed: "run
    Tue, long run Sat, strength Sun" answered with strength Tue/Sat)."""
    facts = {**_old_style_facts(), "notes": "run Tue, strength Fri"}
    sys_p, _ = ps.build_prompt(facts)
    assert "BINDING scheduling constraints" in sys_p
    # Rule numbering must stay contiguous (no duplicate/skipped numbers).
    import re
    nums = [int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", sys_p, re.M)]
    assert nums == list(range(1, len(nums) + 1)), nums


def test_build_prompt_no_binding_rule_without_notes():
    sys_p, _ = ps.build_prompt({**_old_style_facts(), "notes": None})
    assert "BINDING scheduling constraints" not in sys_p
    import re
    nums = [int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", sys_p, re.M)]
    assert nums == list(range(1, len(nums) + 1)), nums


def test_build_prompt_notes_emit_day_date_mapping():
    """Day-name language in notes ("Tue", "Sat") must be anchored by the full
    offset<->day<->date table — today_offset alone is None for a next-week
    request, leaving the model to guess the mapping."""
    facts = {
        **_old_style_facts(),
        "notes": "run Tue, long run Sat",
        "week_start": "2026-07-13",
        "today_offset": None,
    }
    _, user_p = ps.build_prompt(facts)
    assert "Target week day mapping" in user_p
    assert "1=Tuesday 2026-07-14" in user_p
    assert "5=Saturday 2026-07-18" in user_p


def test_build_prompt_mentions_long_run_and_consecutive_rules():
    sys_p, _ = ps.build_prompt(_old_style_facts())
    assert "long run" in sys_p.lower()
    assert "consecutive" in sys_p.lower()


def test_build_prompt_mentions_existing_schedule():
    facts = {**_old_style_facts(), "existing_week": [
        {"day_offset": 1, "date": "2026-07-07", "has_workout": True,
         "workout_type": "strength", "has_planned": False,
         "planned_type": None, "planned_status": None},
    ]}
    _, user_p = ps.build_prompt(facts)
    assert "already logged a strength" in user_p


# ── assemble_facts: real-PG scoping (day-offset math + existing schedule) ────

@pytest.fixture()
def scoped_user():
    with Session(engine) as s:
        u = User(name=f"plan-sug-scope-{uuid.uuid4().hex[:8]}", is_active=True)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    yield uid
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        s.commit()


def test_assemble_facts_current_week_starts_at_todays_offset(scoped_user):
    facts = ps.assemble_facts(str(scoped_user))
    today = date.today()
    week_start = date.fromisoformat(facts["week_start"])
    expected_offset = (today - week_start).days
    assert min(facts["allowed_offsets"]) == expected_offset
    assert facts["allowed_offsets"] == list(range(expected_offset, 7))


def test_assemble_facts_future_week_is_fully_open(scoped_user):
    next_monday = date.today() - timedelta(days=date.today().weekday()) + timedelta(days=7)
    facts = ps.assemble_facts(str(scoped_user), week_start=next_monday)
    assert facts["allowed_offsets"] == list(range(7))


def test_assemble_facts_excludes_days_with_existing_workout_or_planned(scoped_user):
    week_start = date.today() - timedelta(days=date.today().weekday())
    # A workout two days from now (within the week) and a planned session three
    # days from now — both should drop out of allowed_offsets.
    today_offset = date.today().weekday()
    wo_offset = min(today_offset + 1, 6)
    ps_offset = min(today_offset + 2, 6)
    with Session(engine) as s:
        s.add(Workout(user_id=scoped_user, workout_date=week_start + timedelta(days=wo_offset),
                      name="Synced run", workout_type="run"))
        s.add(PlannedSession(user_id=scoped_user, planned_date=week_start + timedelta(days=ps_offset),
                             session_type="rest", status="planned"))
        s.commit()

    facts = ps.assemble_facts(str(scoped_user))
    assert wo_offset not in facts["allowed_offsets"]
    assert ps_offset not in facts["allowed_offsets"]
    entry_wo = next(d for d in facts["existing_week"] if d["day_offset"] == wo_offset)
    assert entry_wo["has_workout"] is True and entry_wo["workout_type"] == "run"
    entry_ps = next(d for d in facts["existing_week"] if d["day_offset"] == ps_offset)
    assert entry_ps["has_planned"] is True and entry_ps["planned_type"] == "rest"


def test_assemble_facts_threads_preferences(scoped_user):
    facts = ps.assemble_facts(
        str(scoped_user), preferred_rest_days=[0, 6],
        strength_emphasis="more", notes="  taper this week  ",
    )
    # rest days outside allowed_offsets are dropped; only assert the ones that
    # ARE within the open range survive (depends on today, so just check no
    # crash + normalization behaviour on notes/emphasis).
    assert facts["strength_emphasis"] == "more"
    assert facts["notes"] == "taper this week"
    assert set(facts["preferred_rest_days"]).issubset({0, 6})


def test_assemble_facts_invalid_emphasis_normalizes_to_same(scoped_user):
    facts = ps.assemble_facts(str(scoped_user), strength_emphasis="whatever")
    assert facts["strength_emphasis"] == "same"


def test_assemble_facts_with_a_race_does_not_detach(scoped_user):
    """Regression: prefs commit + session close must not leave Race detached
    when reading days_to_next_race (was DetachedInstanceError → 500 on Suggest)."""
    from backend.models import Race
    race_day = date.today() + timedelta(days=90)
    with Session(engine) as s:
        s.add(Race(
            user_id=scoped_user,
            name="Regression A",
            race_date=race_day,
            distance_km=42.2,
            goal_time_seconds=15300,
            priority="A",
            status="planned",
        ))
        s.commit()

    facts = ps.assemble_facts(str(scoped_user))
    assert facts["days_to_next_race"] == (race_day - date.today()).days
    assert facts["next_race_distance_km"] == 42.2
    assert facts["next_race_goal_time_seconds"] == 15300


def test_get_suggestions_passes_scoping_into_facts(scoped_user):
    next_monday = date.today() - timedelta(days=date.today().weekday()) + timedelta(days=7)
    result = ps.get_suggestions(str(scoped_user), week_start=next_monday,
                                strength_emphasis="more")
    assert result["facts"]["week_start"] == next_monday.isoformat()
    assert result["facts"]["strength_emphasis"] == "more"
    assert len(result["suggestions"]) > 0
