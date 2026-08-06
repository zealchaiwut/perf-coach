"""Two-rail suggestions (issue #1417), backend halves:

- get_suggestions(skeleton=True) returns the deterministic template with no
  LLM involvement (source="skeleton", zero attempts, never cached).
- build_single_session_prompt is the FREEFORM single-session prompt — no
  schedule-rail budget concept lives here any more (see #1596 below).

Pure-function tests; the live endpoint pass-through is covered by the
request-model validation tests at the bottom (no LLM key needed — skeleton
never calls the LLM, and validation rejects before any LLM call).

#1596 (Ask-AI consolidation): generate_single_session used to have two
branches for a PINNED slot budget — this file originally pinned target_tss/
duration_minutes straight into build_single_session_prompt (issue #1417,
2026-07-13). A week later, the plan_slot.py content-only path was added in
front of it (2026-07-20) and started intercepting every call that carried a
budget, so the #1417 prompt-pinning code stopped running — it just sat there
un-exercised, and the tests below that pinned it went stale (see
BASELINE_FAILURES.txt pre-#1596). #1596 deleted the dead branch; the pinned
case is now covered by the "pinned single-session generation" section below,
against the plan_slot path that was already the live behaviour.
"""
from unittest import mock

import backend.services.llm as llm
import backend.services.plan_suggestions as ps


_FACTS = {
    "trailing_28d_weekly_avg_tss": 300.0,
    "ctl": 40.0, "atl": 45.0, "tsb": -5.0,
    "allowed_offsets": [1, 2, 4, 5, 6],
    "preferred_rest_days": [0, 3],
    "strength_emphasis": "same",
    "notes": "",
    "week_start": "2026-07-13",
    "today_offset": None,
}


# ── skeleton mode ────────────────────────────────────────────────────────────

def test_skeleton_returns_template_without_llm():
    # skeleton=True path is deterministic — no LLM involvement (issue #1695: week-level LLM removed too)
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps, "_load_history_rows", return_value=[]), \
         mock.patch.object(llm, "get_or_generate", side_effect=AssertionError("LLM called")) as llm_cache, \
         mock.patch.object(llm, "complete_structured", side_effect=AssertionError("LLM called")) as llm_call:
        result = ps.get_suggestions("someone", skeleton=True)
    llm_cache.assert_not_called()
    llm_call.assert_not_called()
    assert result["source"] == "skeleton"
    assert result["attempts"] == 0
    assert result["suggestions"], "template must produce slots for open days"


def test_skeleton_slots_respect_allowed_offsets_and_rest_days():
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps, "_load_history_rows", return_value=[]):
        result = ps.get_suggestions("someone", skeleton=True)
    for s in result["suggestions"]:
        assert s["day_offset"] in _FACTS["allowed_offsets"] + _FACTS["preferred_rest_days"]
        if s["day_offset"] in _FACTS["preferred_rest_days"]:
            assert s["workout_type"] == "rest"


def test_skeleton_slots_start_blank():
    """Slots carry ONLY the budget (day/type/TSS/duration) — content stays
    blank until the athlete fills a slot with AI. Pre-filled template
    exercises read as already-generated sessions."""
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps, "_load_history_rows", return_value=[]):
        result = ps.get_suggestions("someone", skeleton=True)
    for s in result["suggestions"]:
        assert s["exercises"] is None
        assert s["blocks"] is None
        assert s["notes"] is None
        if s["workout_type"] != "rest":
            assert s["intent"] == ""
    # The budget itself must survive the stripping — the week's training
    # slots can't ALL be zero.
    assert sum(s["target_tss"] or 0 for s in result["suggestions"]) > 0


def test_single_session_prompt_pins_subtype():
    sys_p, _ = ps.build_single_session_prompt(
        _FACTS, 1, "run", "", subtype="intervals",
    )
    assert 'tagged this session "intervals"' in sys_p
    assert "interval session" in sys_p
    assert "The tag is binding" in sys_p


def test_single_session_prompt_ignores_subtype_for_wrong_type():
    # "upper" is a strength subtype — meaningless for a run; no rule emitted.
    sys_p, _ = ps.build_single_session_prompt(
        _FACTS, 1, "run", "", subtype="upper",
    )
    assert "tagged this session" not in sys_p


# ── provider selection (GLM vs Groq) ─────────────────────────────────────────

def test_provider_prefers_glm_when_key_present(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GLM_API_KEY", "zk-test")
    assert llm._provider() == "glm"
    assert llm._model("deep") == "glm-4.7-flash"
    assert llm._model("fast") == "glm-4.7-flash"


def test_provider_groq_without_glm_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    assert llm._provider() == "groq"
    assert llm._model("deep") == "openai/gpt-oss-120b"


def test_provider_env_override_wins(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GLM_API_KEY", "zk-test")
    assert llm._provider() == "groq"


def test_cerebras_is_opt_in_only(monkeypatch):
    # A present key alone never selects Cerebras — only LLM_PROVIDER does.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test")
    assert llm._provider() == "groq"
    monkeypatch.setenv("LLM_PROVIDER", "cerebras")
    assert llm._provider() == "cerebras"
    assert llm._model("deep") == "gpt-oss-120b"
    assert llm._api_key() == "csk-test"


def test_glm_payload_uses_json_object_with_inlined_schema(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GLM_API_KEY", "zk-test")
    monkeypatch.setenv("LLM_COACH_ENABLED", "true")
    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": '```json\n{"ok": 1}\n```'}}]}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr(llm.httpx, "post", _fake_post)
    out = llm.complete_structured(
        system="s", user="u", schema_name="x",
        json_schema={"type": "object"}, model_tier="deep", max_tokens=100,
    )
    assert out == {"ok": 1}  # fences stripped
    assert "api.z.ai" in captured["url"]
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in captured["payload"]["messages"][0]["content"]


def test_run_prompt_is_a_compact_three_block_estimation():
    sys_p, _ = ps.build_single_session_prompt(_FACTS, 1, "run", "")
    assert "EXACTLY 3 entries" in sys_p
    assert "simple estimation" in sys_p
    # The detailed strength template must NOT ride along on a run request.
    assert "Superset" not in sys_p


def test_run_fill_uses_the_small_token_cap():
    """Pinned fills go through fill_slot (pattern-based), never complete_structured."""
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch("backend.services.plan_pattern_fill.fill_slot",
                    return_value={
                        "intent": "Easy", "notes": None,
                        "blocks": [{"phase": "warmup", "duration_min": 10},
                                   {"phase": "main", "duration_min": 25},
                                   {"phase": "cooldown", "duration_min": 10}],
                        "exercises": None, "source": "pattern",
                    }) as fill, \
         mock.patch.object(llm, "complete_structured", side_effect=AssertionError("LLM called")) as llm_call:
        ps.generate_single_session(
            "someone", 1, "", workout_type="run",
            target_tss=40, duration_minutes=45,
        )
        ps.generate_single_session(
            "someone", 1, "", workout_type="strength",
            target_tss=45, duration_minutes=45,
        )
    assert fill.call_count == 2
    llm_call.assert_not_called()


def test_strength_prompt_pins_canonical_block_names():
    sys_p, _ = ps.build_single_session_prompt(_FACTS, 6, "strength", "")
    for block in ("Warm-up", "Heavy compound", "Superset 1", "Superset 2",
                  "Accessories", "Standalone", "Stretch"):
        assert block in sys_p, block
    assert "Do NOT invent other block names" in sys_p
    # The run branch must not carry the strength block spec.
    run_sys, _ = ps.build_single_session_prompt(_FACTS, 1, "run", "")
    assert "Heavy compound" not in run_sys


def test_single_session_prompt_describes_plyo_distinctly():
    sys_p, _ = ps.build_single_session_prompt(_FACTS, 1, "plyo", "")
    assert "EXPLOSIVE" in sys_p or "explosive" in sys_p
    assert "never the barbell-lift strength template" in sys_p


def test_stretch_is_a_known_workout_type():
    assert "stretch" in ps.KNOWN_WORKOUT_TYPES
    errs = ps.validation_errors(
        [{"day_offset": 4, "workout_type": "stretch", "target_tss": 15,
          "duration_minutes": 20, "intent": "mobility", "notes": None,
          "exercises": [{"block": "Mobility", "name": "Couch stretch",
                          "sets": 2, "reps": "45s hold", "load": "bodyweight"}],
          "blocks": None}],
        dict(_FACTS),
    )
    assert not [e for e in errs if "workout_type" in e], errs


def test_skeleton_false_returns_fallback_not_llm():
    """issue #1695: skeleton=False no longer calls the LLM — week-level path is deterministic."""
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(llm, "get_or_generate", side_effect=AssertionError("LLM called")) as llm_cache:
        result = ps.get_suggestions("someone", skeleton=False)
    llm_cache.assert_not_called()
    assert result["source"] == "fallback"


# ── history-based skeleton (rule-based, zero LLM) ────────────────────────────

# 3 weeks of a consistent pattern: Tue easy run, Wed intervals, Sat long run,
# Sun strength; one-off Thursday ride of week 2 must NOT prefill.
_HISTORY = [
    # (weekday, type, tss, duration_minutes)
    (1, "run", 55, 60), (1, "run", 52, 55), (1, "run", 58, 62),
    (2, "run", 78, 60), (2, "run", 82, 65),
    (5, "run", 120, 110), (5, "run", 112, 105), (5, "run", 131, 118),
    (6, "strength", 47, 45), (6, "strength", 51, 48),
    (3, "plyo", 40, 30),  # once only — not a habit
]

_HFACTS = {**_FACTS, "allowed_offsets": [1, 2, 3, 4, 5, 6], "preferred_rest_days": [0]}


def test_history_skeleton_prefills_habits_with_median_budget():
    slots = ps.history_skeleton_slots(_HISTORY, _HFACTS)
    by_day = {}
    for s in slots:
        by_day.setdefault(s["day_offset"], []).append(s)
    assert by_day[0][0]["workout_type"] == "rest"
    assert by_day[1][0]["workout_type"] == "run"
    assert by_day[1][0]["target_tss"] == 55  # median of 55/52/58
    assert by_day[5][0]["target_tss"] == 120
    assert by_day[6][0]["workout_type"] == "strength"
    assert 3 not in by_day, "a one-off is not a habit and must not prefill"
    # Content blank — budget only.
    for s in slots:
        assert s["exercises"] is None and s["blocks"] is None


def test_history_skeleton_tags_biggest_run_as_long():
    slots = ps.history_skeleton_slots(_HISTORY, _HFACTS)
    sat = next(s for s in slots if s["day_offset"] == 5)
    assert sat.get("subtype") == "long"
    tue = next(s for s in slots if s["day_offset"] == 1)
    assert tue.get("subtype") is None


def test_history_skeleton_enforces_strength_count():
    # History has 1 strength habit; ask for 3 → 2 added on the lightest days.
    slots = ps.history_skeleton_slots(_HISTORY, _HFACTS, strength_sessions=3)
    assert sum(1 for s in slots if s["workout_type"] == "strength") == 3
    # Ask for 0 → the Sunday habit is trimmed.
    slots = ps.history_skeleton_slots(_HISTORY, _HFACTS, strength_sessions=0)
    assert not any(s["workout_type"] == "strength" for s in slots)


def test_history_skeleton_respects_allowed_offsets():
    facts = {**_HFACTS, "allowed_offsets": [2, 5]}
    slots = ps.history_skeleton_slots(_HISTORY, facts)
    for s in slots:
        if s["workout_type"] != "rest":
            assert s["day_offset"] in (2, 5)


def test_skeleton_endpoint_path_uses_history_when_present():
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_HFACTS)), \
         mock.patch.object(ps, "_load_history_rows", return_value=list(_HISTORY)), \
         mock.patch.object(llm, "get_or_generate", side_effect=AssertionError("LLM called")) as llm_cache:
        result = ps.get_suggestions("someone", skeleton=True)
    llm_cache.assert_not_called()
    assert result["source"] == "history"
    assert any(s["workout_type"] == "run" for s in result["suggestions"])


def test_skeleton_falls_back_to_template_without_history():
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps, "_load_history_rows", return_value=[]):
        result = ps.get_suggestions("someone", skeleton=True)
    assert result["source"] == "skeleton"
    assert any(s["workout_type"] != "rest" for s in result["suggestions"])


# ── freeform single-session prompt has no budget concept ─────────────────────

def test_single_session_prompt_unchanged_without_budget():
    sys_p, _ = ps.build_single_session_prompt(_FACTS, 4, "run", "note")
    assert "fixed this session's budget" not in sys_p
    assert "target_tss MUST be" not in sys_p
    assert "duration_minutes MUST be" not in sys_p


def test_single_session_prompt_has_no_budget_params():
    """#1596: target_tss/duration_minutes were removed from this signature,
    not just left unused — passing them is a TypeError, so a future patch
    can't quietly re-thread a schedule-rail budget through the freeform
    prompt (that's the plan_slot.py path's job, see below)."""
    import inspect
    params = inspect.signature(ps.build_single_session_prompt).parameters
    assert "target_tss" not in params
    assert "duration_minutes" not in params


# ── pinned single-session generation (schedule rail owns the budget) ────────
# The ONE live path for a pinned request (target_tss and/or duration_minutes
# given): plan_slot.py's content-only machinery. Covers the three guardrails
# CLAUDE.md's "LLM policy" section requires of every sanctioned LLM surface.

def test_generate_single_session_with_pins_never_reaches_the_freeform_prompt():
    """A pinned request must not go anywhere near build_single_session_prompt
    — the schedule rail's TSS/duration are GIVENS, not something a freeform
    prompt should ever be negotiating."""
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps, "build_single_session_prompt") as legacy_prompt:
        ps.generate_single_session(
            "someone", 4, "", workout_type="strength",
            target_tss=63.0, duration_minutes=45,
        )
    legacy_prompt.assert_not_called()


def test_generate_single_session_with_pins_stamps_the_exact_numbers():
    """Guardrail: the LLM never produces a number. Python stamps the
    athlete's own target_tss/duration_minutes regardless of what content
    volunteers (here it tries to sneak in 999/999) — pins always win."""
    pattern_content = {
        "intent": "Heavy day", "notes": None, "blocks": None,
        "exercises": [
            {"block": "Warm-up", "name": "Band walk", "sets": 2, "reps": "10", "load": "band"},
            {"block": "Heavy compound", "name": "Squat", "sets": 4, "reps": "5", "load": "heavy"},
            {"block": "Superset 1", "name": "Bench", "sets": 3, "reps": "8", "load": "moderate"},
            {"block": "Superset 2", "name": "Row", "sets": 3, "reps": "8", "load": "moderate"},
        ],
        # Content must not override pins — stamp_session discards these.
        "target_tss": 999, "duration_minutes": 999,
        "source": "pattern",
    }
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch("backend.services.plan_pattern_fill.fill_slot",
                    return_value=pattern_content):
        session = ps.generate_single_session(
            "someone", 4, "", workout_type="strength",
            target_tss=63.0, duration_minutes=45,
        )
    assert session["target_tss"] == 63
    assert session["duration_minutes"] == 45
    assert session["source"] == "pattern"


def test_generate_single_session_with_pins_falls_back_to_template_on_provider_failure():
    """Guardrail: every path falls back. With no DB / no matching pattern,
    fill_slot returns the day template — still a usable, exact-budget
    session (never 422, never block)."""
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)):
        session = ps.generate_single_session(
            "someone", 4, "", workout_type="run",
            target_tss=63.0, duration_minutes=45,
        )
    assert session is not None
    assert session["source"] in ("template", "pattern")
    assert session["target_tss"] == 63
    assert session["duration_minutes"] == 45


def test_generate_single_session_without_pins_can_return_none():
    """Guardrail contrast: the no-budget path returns None (no TSS, no duration to template from).
    The endpoint (routers/projection.py) turns this into a 422, never a 500."""
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)):
        session = ps.generate_single_session("someone", 4, "", workout_type="run")
    assert session is None
