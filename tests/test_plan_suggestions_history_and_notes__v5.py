"""Plan-suggestion v5 (PRD feedback, 2026-07-08):
1. Lighter/Harder should touch exercise sets/reps, not just the TSS number
   (frontend-only change — see training-plan.js _adjustSession, exercised via
   manual/live testing; no Python surface to unit-test).
2. Suggestions should see the athlete's recently-used exercises (actually
   logged strength/plyo workouts in the last 14 days, plus anything already
   planned this week) and avoid defaulting to them.
3. Sessions should carry a coach's rationale (`notes`) explaining WHY, and the
   strength templates should reflect a real 4-6 sub-section session structure
   (Warm-up / Heavy compound / Superset 1-2 / Standalone / Accessories).

Real-Postgres for assemble_facts (recent-exercise query); pure unit tests for
the schema/prompt/fallback pieces.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import backend.services.plan_suggestions as ps
from backend.db import engine
from backend.models import PlannedSession, User, Workout, WorkoutExercise


def _base_facts(trailing=200.0):
    return {"trailing_28d_weekly_avg_tss": trailing}


# ── LLM schema: notes is nullable and required (Groq strict-mode lesson) ─────

def test_llm_json_schema_lists_notes_as_required():
    item_schema = ps._LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]
    assert "notes" in item_schema["properties"]
    assert "notes" in item_schema["required"]


def test_llm_json_schema_notes_is_nullable_string():
    notes_schema = ps._LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]["properties"]["notes"]
    assert set(notes_schema["type"]) == {"string", "null"}


# ── build_prompt: recent-exercise avoidance + notes rationale + rich blocks ──

def test_build_prompt_mentions_recent_exercise_names():
    facts = {**_base_facts(), "recent_exercise_names": ["Back squat", "Plank"]}
    sys_p, user_p = ps.build_prompt(facts)
    assert "Back squat" in sys_p and "Plank" in sys_p
    assert "Back squat" in user_p
    assert "vary" in sys_p.lower() or "avoid" in sys_p.lower()


def test_build_prompt_omits_avoid_repeat_rule_when_no_history():
    facts = _base_facts()
    sys_p, _ = ps.build_prompt(facts)
    assert "recently used" not in sys_p.lower()


def test_build_prompt_instructs_notes_rationale():
    sys_p, _ = ps.build_prompt(_base_facts())
    assert "rationale" in sys_p.lower()
    assert "notes" in sys_p.lower()


def test_build_prompt_mentions_rich_strength_subsections():
    sys_p, _ = ps.build_prompt(_base_facts())
    for word in ("Heavy compound", "Superset 1", "Superset 2", "Standalone", "Accessories"):
        assert word in sys_p


def test_build_prompt_mentions_planned_exercise_names_in_existing_week():
    facts = {**_base_facts(), "existing_week": [
        {"day_offset": 1, "date": "2026-07-07", "has_workout": False,
         "workout_type": None, "has_planned": True, "planned_type": "strength",
         "planned_status": "planned", "planned_exercise_names": ["Back squat", "Plank"]},
    ]}
    _, user_p = ps.build_prompt(facts)
    assert "Back squat, Plank" in user_p


def test_rule_numbering_has_no_gaps_or_dupes():
    """Regression: the dynamic rule-number bookkeeping (notes/rest/avoid-repeat
    are all conditionally inserted) must never produce a duplicate or skipped
    number in the SAFETY RULES list."""
    facts = {**_base_facts(), "preferred_rest_days": [2],
             "recent_exercise_names": ["Back squat"]}
    sys_p, _ = ps.build_prompt(facts)
    import re
    nums = [int(n) for n in re.findall(r"^(\d+)\. ", sys_p, re.MULTILINE)]
    assert nums == list(range(1, len(nums) + 1)), nums


# ── fallback_suggestions: notes defaults to None (no fabricated rationale) ───

def test_fallback_sessions_have_notes_key_defaulting_none():
    result = ps.fallback_suggestions(_base_facts())
    for s in result:
        assert "notes" in s
        assert s["notes"] is None


def test_fallback_strength_templates_have_4_to_6_subsections():
    result = ps.fallback_suggestions(_base_facts())
    for s in result:
        if s["workout_type"] == "strength" and s.get("exercises"):
            blocks = []
            for e in s["exercises"]:
                if e["block"] not in blocks:
                    blocks.append(e["block"])
            assert 4 <= len(blocks) <= 6, f"expected 4-6 sub-sections, got {blocks}"
            assert "Heavy compound" in blocks


# ── assemble_facts: recent-exercise history (real-PG) ────────────────────────

@pytest.fixture()
def history_user():
    with Session(engine) as s:
        u = User(name=f"plan-sug-history-{uuid.uuid4().hex[:8]}", is_active=True)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    yield uid
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        s.commit()


def test_assemble_facts_includes_recently_done_strength_exercises(history_user):
    done_date = date.today() - timedelta(days=3)
    with Session(engine) as s:
        w = Workout(user_id=history_user, workout_date=done_date, name="Leg day", workout_type="strength")
        s.add(w); s.flush()
        s.add(WorkoutExercise(workout_id=w.id, display_order=0, name="Back squat", sets=4, reps=8))
        s.add(WorkoutExercise(workout_id=w.id, display_order=1, name="Romanian deadlift", sets=3, reps=10))
        s.commit()

    facts = ps.assemble_facts(str(history_user))
    assert "Back squat" in facts["recent_exercise_names"]
    assert "Romanian deadlift" in facts["recent_exercise_names"]


def test_assemble_facts_ignores_exercises_older_than_14_days(history_user):
    old_date = date.today() - timedelta(days=20)
    with Session(engine) as s:
        w = Workout(user_id=history_user, workout_date=old_date, name="Old day", workout_type="strength")
        s.add(w); s.flush()
        s.add(WorkoutExercise(workout_id=w.id, display_order=0, name="Ancient exercise", sets=3, reps=10))
        s.commit()

    facts = ps.assemble_facts(str(history_user))
    assert "Ancient exercise" not in facts["recent_exercise_names"]


def test_assemble_facts_ignores_non_strength_workout_exercises(history_user):
    # A run workout with an (unusual but possible) WorkoutExercise row must not
    # pollute the strength/plyo-only recent-exercise list.
    run_date = date.today() - timedelta(days=1)
    with Session(engine) as s:
        w = Workout(user_id=history_user, workout_date=run_date, name="Easy run", workout_type="run")
        s.add(w); s.flush()
        s.add(WorkoutExercise(workout_id=w.id, display_order=0, name="Should not appear", sets=1, reps=1))
        s.commit()

    facts = ps.assemble_facts(str(history_user))
    assert "Should not appear" not in facts["recent_exercise_names"]


def test_assemble_facts_includes_this_weeks_already_planned_exercises(history_user):
    week_start = date.today() - timedelta(days=date.today().weekday())
    today_offset = date.today().weekday()
    planned_offset = min(today_offset + 1, 6)
    with Session(engine) as s:
        s.add(PlannedSession(
            user_id=history_user, planned_date=week_start + timedelta(days=planned_offset),
            session_type="strength", status="planned",
            structure={"exercises": [{"block": "Main", "name": "Front squat", "sets": 3, "reps": "8", "load": "moderate"}]},
        ))
        s.commit()

    facts = ps.assemble_facts(str(history_user))
    assert "Front squat" in facts["recent_exercise_names"]
    entry = next(d for d in facts["existing_week"] if d["day_offset"] == planned_offset)
    assert entry["planned_exercise_names"] == ["Front squat"]


def test_assemble_facts_recent_exercise_names_deduped_and_capped(history_user):
    done_date = date.today() - timedelta(days=2)
    with Session(engine) as s:
        w = Workout(user_id=history_user, workout_date=done_date, name="Big day", workout_type="strength")
        s.add(w); s.flush()
        for i in range(25):
            s.add(WorkoutExercise(workout_id=w.id, display_order=i, name=f"Exercise {i % 5}", sets=3, reps=10))
        s.commit()

    facts = ps.assemble_facts(str(history_user))
    assert len(facts["recent_exercise_names"]) <= 20
    assert len(facts["recent_exercise_names"]) == len(set(facts["recent_exercise_names"]))
