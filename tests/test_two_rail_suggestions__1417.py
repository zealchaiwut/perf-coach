"""Two-rail suggestions (issue #1417), backend halves:

- get_suggestions(skeleton=True) returns the deterministic template with no
  LLM involvement (source="skeleton", zero attempts, never cached).
- build_single_session_prompt pins the schedule rail's slot budget
  (target_tss / duration_minutes) as a hard prompt rule.

Pure-function tests; the live endpoint pass-through is covered by the
request-model validation tests at the bottom (no LLM key needed — skeleton
never calls the LLM, and validation rejects before any LLM call).
"""
from unittest import mock

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
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps, "_load_history_rows", return_value=[]), \
         mock.patch.object(ps.llm_svc, "get_or_generate") as llm_cache, \
         mock.patch.object(ps.llm_svc, "complete_structured") as llm_call:
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


def test_run_prompt_is_a_compact_three_block_estimation():
    sys_p, _ = ps.build_single_session_prompt(_FACTS, 1, "run", "")
    assert "EXACTLY 3 entries" in sys_p
    assert "simple estimation" in sys_p
    # The detailed strength template must NOT ride along on a run request.
    assert "Superset" not in sys_p


def test_run_fill_uses_the_small_token_cap():
    captured = {}

    def _fake_complete(system, user, **kw):
        captured.update(kw)
        return None

    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps.llm_svc, "complete_structured", side_effect=_fake_complete):
        ps.generate_single_session("someone", 1, "", workout_type="run")
    assert captured["max_tokens"] == ps._RUN_SESSION_MAX_COMPLETION_TOKENS

    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps.llm_svc, "complete_structured", side_effect=_fake_complete):
        ps.generate_single_session("someone", 1, "", workout_type="strength")
    assert captured["max_tokens"] == ps._SINGLE_SESSION_MAX_COMPLETION_TOKENS


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


def test_skeleton_false_still_takes_llm_path():
    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps.llm_svc, "get_or_generate", return_value=None) as llm_cache:
        result = ps.get_suggestions("someone", skeleton=False)
    llm_cache.assert_called_once()
    assert result["source"] in ("llm", "fallback")


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
         mock.patch.object(ps.llm_svc, "get_or_generate") as llm_cache:
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


# ── slot-budget pinning in the single-session prompt ─────────────────────────

def test_single_session_prompt_pins_slot_budget():
    sys_p, _ = ps.build_single_session_prompt(
        _FACTS, 4, "strength", "", target_tss=63.0, duration_minutes=45,
    )
    assert "target_tss MUST be 63" in sys_p
    assert "duration_minutes MUST be 45" in sys_p
    assert "do not resize the slot" in sys_p


def test_single_session_prompt_pins_partial_budget():
    sys_p, _ = ps.build_single_session_prompt(
        _FACTS, 4, "run", "", target_tss=80.0,
    )
    assert "target_tss MUST be 80" in sys_p
    assert "duration_minutes MUST" not in sys_p


def test_single_session_prompt_unchanged_without_budget():
    sys_p, _ = ps.build_single_session_prompt(_FACTS, 4, "run", "note")
    assert "fixed this session's budget" not in sys_p
    assert "target_tss MUST be" not in sys_p
    assert "duration_minutes MUST be" not in sys_p


def test_generate_single_session_threads_budget_to_prompt():
    captured = {}

    def _fake_complete(system, user, **kw):
        captured["system"] = system
        return None  # short-circuit after prompt build

    with mock.patch.object(ps, "assemble_facts", return_value=dict(_FACTS)), \
         mock.patch.object(ps.llm_svc, "complete_structured", side_effect=_fake_complete):
        out = ps.generate_single_session(
            "someone", 4, "", workout_type="strength",
            target_tss=63.0, duration_minutes=45,
        )
    assert out is None
    assert "target_tss MUST be 63" in captured["system"]
    assert "duration_minutes MUST be 45" in captured["system"]
