"""Plan-suggestion run structure (PRD feedback, 2026-07-08): "Please do the
same on RUN as well. I do not want to decide only with TSS and duration."

Run suggestions now require a `blocks` breakdown (phase/duration_min/repeat/
rest_min/target — the same shape PlannedSession.structure.blocks and the
manual Add-session run-block builder already use), mirroring the exercises
requirement just added for strength/plyo.
"""
import backend.services.plan_suggestions as ps


def _base_facts(trailing=200.0):
    return {"trailing_28d_weekly_avg_tss": trailing}


_EASY_BLOCKS = [
    {"phase": "warmup", "duration_min": 10, "repeat": None, "rest_min": None, "target": "easy"},
    {"phase": "main", "duration_min": 30, "repeat": None, "rest_min": None, "target": "easy"},
]


def _run_suggestion(offset=0, blocks=None, **kw):
    s = {"day_offset": offset, "workout_type": "run", "target_tss": 50,
         "duration_minutes": 40, "intent": "run"}
    s.update(kw)
    if blocks is not None:
        s["blocks"] = blocks
    return s


# ── LLM schema: blocks required (Groq strict mode), nullable, well-shaped ────

def test_llm_json_schema_lists_blocks_as_required():
    item_schema = ps._LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]
    assert "blocks" in item_schema["properties"]
    assert "blocks" in item_schema["required"]


def test_llm_json_schema_blocks_is_nullable_array():
    b_schema = ps._LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]["properties"]["blocks"]
    assert set(b_schema["type"]) == {"array", "null"}


def test_llm_json_schema_block_item_shape():
    b_item = ps._LLM_JSON_SCHEMA["properties"]["suggestions"]["items"]["properties"]["blocks"]["items"]
    assert set(b_item["required"]) == {"phase", "duration_min", "repeat", "rest_min", "target"}
    assert b_item["additionalProperties"] is False
    assert b_item["properties"]["phase"]["enum"] == ["warmup", "main", "cooldown"]
    # repeat/rest_min/target are nullable (not every phase repeats or has a rest)
    assert "null" in b_item["properties"]["repeat"]["type"]
    assert "null" in b_item["properties"]["rest_min"]["type"]
    assert "null" in b_item["properties"]["target"]["type"]


# ── validation_errors: run must carry a real blocks breakdown ────────────────

def test_validation_rejects_run_with_no_blocks_key():
    errs = ps.validation_errors([_run_suggestion()], _base_facts())
    assert any("no blocks breakdown" in e for e in errs)


def test_validation_rejects_run_with_empty_blocks_list():
    errs = ps.validation_errors([_run_suggestion(blocks=[])], _base_facts())
    assert any("no blocks breakdown" in e for e in errs)


def test_validation_rejects_run_with_null_blocks():
    errs = ps.validation_errors([_run_suggestion(blocks=None)], _base_facts())
    assert any("no blocks breakdown" in e for e in errs)


def test_validation_accepts_run_with_real_blocks():
    good = _run_suggestion(blocks=_EASY_BLOCKS)
    assert ps.validation_errors([good], _base_facts()) == []


def test_validation_rejects_block_entry_missing_phase():
    bad = _run_suggestion(blocks=[{"duration_min": 20, "repeat": None, "rest_min": None, "target": None}])
    errs = ps.validation_errors([bad], _base_facts())
    assert any("missing phase/duration_min" in e for e in errs)


def test_validation_rejects_block_entry_missing_duration():
    bad = _run_suggestion(blocks=[{"phase": "main", "repeat": None, "rest_min": None, "target": None}])
    errs = ps.validation_errors([bad], _base_facts())
    assert any("missing phase/duration_min" in e for e in errs)


def test_validation_accepts_interval_style_blocks_with_repeat():
    good = _run_suggestion(blocks=[
        {"phase": "warmup", "duration_min": 10, "repeat": None, "rest_min": None, "target": "easy"},
        {"phase": "main", "duration_min": 10, "repeat": 3, "rest_min": 2, "target": "92% CP"},
        {"phase": "cooldown", "duration_min": 8, "repeat": None, "rest_min": None, "target": "easy"},
    ])
    assert ps.validation_errors([good], _base_facts()) == []


def test_validation_strength_plyo_rest_do_not_require_blocks():
    strength = {"day_offset": 1, "workout_type": "strength", "target_tss": 40, "duration_minutes": 45,
                "intent": "x", "exercises": [{"block": "Main", "name": "Squat", "sets": 3, "reps": "8", "load": "moderate"}]}
    rest = {"day_offset": 3, "workout_type": "rest", "target_tss": 0, "duration_minutes": 0, "intent": "rest"}
    assert ps.validation_errors([strength, rest], _base_facts()) == []


# ── fallback_suggestions: run sessions carry a real blocks breakdown ─────────

def test_fallback_run_sessions_have_blocks():
    result = ps.fallback_suggestions(_base_facts())
    runs = [s for s in result if s["workout_type"] == "run"]
    assert runs, "expected at least one run session in the default template"
    for s in runs:
        assert s.get("blocks"), f"run session at offset {s['day_offset']} has no blocks"
        for b in s["blocks"]:
            assert b.get("phase") in ("warmup", "main", "cooldown")
            assert b.get("duration_min")


def test_fallback_strength_and_rest_sessions_have_no_blocks():
    result = ps.fallback_suggestions(_base_facts())
    for s in result:
        if s["workout_type"] in ("strength", "rest"):
            assert not s.get("blocks")


def test_fallback_more_strength_conversion_clears_blocks():
    facts = {**_base_facts(), "strength_emphasis": "more"}
    result = ps.fallback_suggestions(facts)
    converted = [s for s in result if s["workout_type"] == "strength"]
    assert converted
    for s in converted:
        assert not s.get("blocks")


def test_fallback_blocks_are_deep_copied_not_shared_with_template():
    r1 = ps.fallback_suggestions(_base_facts())
    run1 = next(s for s in r1 if s["workout_type"] == "run")
    run1["blocks"][0]["target"] = "MUTATED"

    r2 = ps.fallback_suggestions(_base_facts())
    run2 = next(s for s in r2 if s["workout_type"] == "run")
    assert run2["blocks"][0]["target"] != "MUTATED"


def test_fallback_rest_requested_on_run_day_clears_blocks():
    run_offsets = [s["day_offset"] for s in ps.fallback_suggestions(_base_facts())
                  if s["workout_type"] == "run"]
    assert run_offsets
    facts = {**_base_facts(), "preferred_rest_days": [run_offsets[0]]}
    result = ps.fallback_suggestions(facts)
    forced = next(s for s in result if s["day_offset"] == run_offsets[0])
    assert forced["workout_type"] == "rest"
    assert not forced.get("blocks")


# ── build_prompt mentions the blocks requirement ─────────────────────────────

def test_build_prompt_instructs_blocks_for_run():
    sys_p, _ = ps.build_prompt(_base_facts())
    assert "blocks" in sys_p
    assert "warmup" in sys_p and "cooldown" in sys_p
    assert "repeat" in sys_p and "rest_min" in sys_p
