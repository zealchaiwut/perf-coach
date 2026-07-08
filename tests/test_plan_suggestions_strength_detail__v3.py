"""Plan-suggestion strength detail (PRD feedback, 2026-07-08): "the session
didn't have details" — suggestions carried only target_tss/duration/intent,
so clicking Add produced an empty-shell planned session with no exercises.

Strength/plyo suggestions now require a real exercises breakdown (block-
grouped {block, name, sets, reps, load}, the same shape PlannedSession's
structure JSONB and the manual Add-session form builder already use).

Also locks in a real bug this feature hit live: Groq's strict JSON-schema
mode requires EVERY object property to be listed in `required` (optionality
is expressed via a nullable type, not omission) — the first version of the
schema added `exercises` as a property without adding it to `required`,
which Groq's API rejected outright (400) on every single call, silently
falling back to the deterministic template forever. See
test_llm_json_schema_lists_exercises_as_required below.
"""
import backend.services.plan_suggestions as ps


def _base_facts(trailing=200.0):
    return {"trailing_28d_weekly_avg_tss": trailing}


# ── schema regression: exercises MUST be in `required` (Groq strict mode) ────

def test_llm_json_schema_lists_exercises_as_required():
    item_schema = ps._LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]
    assert "exercises" in item_schema["properties"]
    assert "exercises" in item_schema["required"], (
        "Groq strict JSON-schema mode 400s the whole request if a schema "
        "property isn't listed in `required` (nullable type expresses "
        "optionality instead) — this silently forces every call to fallback."
    )


def test_llm_json_schema_exercises_is_nullable_array():
    ex_schema = ps._LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]["properties"]["exercises"]
    assert set(ex_schema["type"]) == {"array", "null"}


def test_llm_json_schema_exercise_item_required_fields():
    ex_item = ps._LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]["properties"]["exercises"]["items"]
    assert set(ex_item["required"]) == {"block", "name", "sets", "reps", "load"}
    assert ex_item["additionalProperties"] is False


# ── validation_errors: strength/plyo must carry a real exercises breakdown ──

def _strength(offset=1, exercises=None, **kw):
    s = {"day_offset": offset, "workout_type": "strength", "target_tss": 40,
         "duration_minutes": 45, "intent": "Strength session"}
    s.update(kw)
    if exercises is not None:
        s["exercises"] = exercises
    return s


def test_validation_rejects_strength_with_no_exercises_key():
    errs = ps.validation_errors([_strength()], _base_facts())
    assert any("no exercises breakdown" in e for e in errs)


def test_validation_rejects_strength_with_empty_exercises_list():
    errs = ps.validation_errors([_strength(exercises=[])], _base_facts())
    assert any("no exercises breakdown" in e for e in errs)


def test_validation_rejects_strength_with_null_exercises():
    errs = ps.validation_errors([_strength(exercises=None)], _base_facts())
    assert any("no exercises breakdown" in e for e in errs)


def test_validation_accepts_strength_with_real_exercises():
    good = _strength(exercises=[
        {"block": "Main", "name": "Back squat", "sets": 3, "reps": "8", "load": "moderate"},
    ])
    assert ps.validation_errors([good], _base_facts()) == []


def test_validation_rejects_exercise_entry_missing_name():
    bad = _strength(exercises=[{"block": "Main", "sets": 3, "reps": "8", "load": "moderate"}])
    errs = ps.validation_errors([bad], _base_facts())
    assert any("missing a name" in e for e in errs)


def test_validation_plyo_also_requires_exercises():
    plyo = {"day_offset": 1, "workout_type": "plyo", "target_tss": 30,
            "duration_minutes": 30, "intent": "Plyo circuit"}
    errs = ps.validation_errors([plyo], _base_facts())
    assert any("no exercises breakdown" in e for e in errs)


def test_validation_run_and_rest_do_not_require_exercises():
    # run needs a `blocks` breakdown (see test_plan_suggestions_scoping__v2.py's
    # run-blocks rule tests) but never `exercises` — that's strength/plyo only.
    run = {"day_offset": 0, "workout_type": "run", "target_tss": 50,
           "duration_minutes": 30, "intent": "easy run",
           "blocks": [{"phase": "main", "duration_min": 30, "repeat": None, "rest_min": None, "target": "easy"}]}
    rest = {"day_offset": 3, "workout_type": "rest", "target_tss": 0,
            "duration_minutes": 0, "intent": "rest"}
    assert ps.validation_errors([run, rest], _base_facts()) == []


# ── fallback_suggestions: strength sessions carry a real exercise breakdown ──

def test_fallback_strength_sessions_have_exercises():
    result = ps.fallback_suggestions(_base_facts())
    strength = [s for s in result if s["workout_type"] == "strength"]
    assert strength, "expected at least one strength session in the default template"
    for s in strength:
        assert s.get("exercises"), f"strength session at offset {s['day_offset']} has no exercises"
        for ex in s["exercises"]:
            assert ex.get("name"), ex
            assert ex.get("block")


def test_fallback_run_and_rest_sessions_have_no_exercises():
    result = ps.fallback_suggestions(_base_facts())
    for s in result:
        if s["workout_type"] in ("run", "rest"):
            assert not s.get("exercises")


def test_fallback_more_strength_conversion_carries_exercises():
    facts = {**_base_facts(), "strength_emphasis": "more"}
    result = ps.fallback_suggestions(facts)
    converted = [s for s in result if s["workout_type"] == "strength"]
    # at least the newly-converted one must have a real breakdown
    assert any(s.get("exercises") for s in converted)


def test_fallback_exercises_are_deep_copied_not_shared_with_template():
    r1 = ps.fallback_suggestions(_base_facts())
    strength1 = next(s for s in r1 if s["workout_type"] == "strength")
    strength1["exercises"][0]["name"] = "MUTATED"

    r2 = ps.fallback_suggestions(_base_facts())
    strength2 = next(s for s in r2 if s["workout_type"] == "strength")
    assert strength2["exercises"][0]["name"] != "MUTATED", (
        "fallback_suggestions must return independent exercise dicts per call — "
        "mutating one result must never leak into the module-level template constant"
    )


def test_fallback_rest_requested_on_strength_day_clears_exercises():
    """A requested rest day that used to be a strength slot must not carry a
    stale exercises list once forced to rest."""
    strength_offsets = [s["day_offset"] for s in ps.fallback_suggestions(_base_facts())
                        if s["workout_type"] == "strength"]
    assert strength_offsets
    facts = {**_base_facts(), "preferred_rest_days": [strength_offsets[0]]}
    result = ps.fallback_suggestions(facts)
    forced = next(s for s in result if s["day_offset"] == strength_offsets[0])
    assert forced["workout_type"] == "rest"
    assert not forced.get("exercises")


# ── build_prompt mentions the exercises requirement ──────────────────────────

def test_build_prompt_instructs_exercises_for_strength_plyo():
    sys_p, _ = ps.build_prompt(_base_facts())
    assert "exercises" in sys_p
    assert "block" in sys_p and "sets" in sys_p and "reps" in sys_p and "load" in sys_p
