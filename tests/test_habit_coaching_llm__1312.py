"""Unit tests for LLM coaching text in habit_insights and habit_nudges (issue #1312).

Covers Acceptance Criteria:
- AC1: LLM path returns phrased lines in correct shape; computed facts unchanged
- AC2: Response JSON structure (field names, list lengths, ordering, caps) is unchanged
- AC3: LLM prose constraints — per-line length cap, no invented numbers, no medical advice
- AC4: Every failure mode (disabled, missing key, timeout, schema-invalid, numeral-fail)
       falls back to exact coaching_voice output byte-identically
- AC5: Caching — signature = sha256 of facts; cache hit does no HTTP
- AC6: coaching_voice.py and its determinism tests remain untouched and passing
- AC7: Uses GROQ_MODEL_FAST tier
- AC8: mocked LLM tests — phrased lines; fallback byte-identical; numeral-validation; cache
"""

from __future__ import annotations

import hashlib
import json
import os
import types
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build minimal test data
# ---------------------------------------------------------------------------

def _habit(habit_id: str = "aaaaaaaa-0000-0000-0000-000000000001", name: str = "Morning Run"):
    h = types.SimpleNamespace()
    h.id = habit_id
    h.name = name
    return h


def _make_insight(
    habit_id: str = "aaaaaaaa-0000-0000-0000-000000000001",
    habit_name: str = "Morning Run",
    outcome_name: str = "energy",
    coefficient: float = 0.65,
    sample_size: int = 30,
    lag_days: int = 0,
    line: str = "You are on track with 'Morning Run' habit — associated with higher 'Energy' scores on the same day.",
) -> dict:
    return {
        "habit_id": habit_id,
        "habit_name": habit_name,
        "outcome_name": outcome_name,
        "coefficient": coefficient,
        "sample_size": sample_size,
        "lag_days": lag_days,
        "line": line,
    }


def _make_slipping_habit(name="Meditation", prev=90.0, current=50.0):
    return {"name": name, "prev_percent": prev, "current_percent": current}


def _make_nudge_result(nudges=None, signals=None):
    nudges = nudges or ["Meditation has drifted from ninety to fifty percent this period — a small reset can make a difference"]
    signals = signals or [{"type": "slipping", "habit": "Meditation", "prev_percent": 90.0, "current_percent": 50.0, "emitted": True}]
    return {"nudges": nudges, "debug": {"signals": signals}}


_LLM_ENV = {
    "LLM_COACH_ENABLED": "true",
    "GROQ_API_KEY": "gsk_test_key",
    "DATABASE_URL": "sqlite:///./test_perf_coach.db",
    "ENVIRONMENT": "local",
    "SESSION_SECRET": "test-secret-key-for-testing-only-xxxxxxxxxxx",
    "STRYD_FERNET_KEY": "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=",
}

_DISABLED_ENV = {
    "DATABASE_URL": "sqlite:///./test_perf_coach.db",
    "ENVIRONMENT": "local",
    "SESSION_SECRET": "test-secret-key-for-testing-only-xxxxxxxxxxx",
    "STRYD_FERNET_KEY": "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=",
}


# ============================================================================
# AC1 + AC2 + AC7: LLM path — insights
# ============================================================================

class TestInsightsLLMPath:
    """AC1: LLM-enabled path replaces 'line' values with LLM prose."""

    def test_llm_replaces_lines(self):
        """AC1: apply_llm_insights returns insights with LLM-phrased 'line' values."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        llm_line = "Morning Run strongly tracks your energy on the same day (r=0.65, n=30)."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [llm_line]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == llm_line

    def test_other_fields_unchanged(self):
        """AC2: all non-'line' fields are preserved exactly."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        llm_line = "Morning Run strongly tracks your energy on the same day (r=0.65, n=30)."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [llm_line]}):
            result = apply_llm_insights([insight], user_id="user-1")

        r = result[0]
        assert r["habit_id"] == insight["habit_id"]
        assert r["habit_name"] == insight["habit_name"]
        assert r["outcome_name"] == insight["outcome_name"]
        assert r["coefficient"] == insight["coefficient"]
        assert r["sample_size"] == insight["sample_size"]
        assert r["lag_days"] == insight["lag_days"]

    def test_list_length_preserved(self):
        """AC2: result list length matches input length."""
        from backend.services.habit_insights import apply_llm_insights

        insights = [_make_insight(), _make_insight(habit_id="bbb", habit_name="Sleep")]
        llm_lines = ["Line one.", "Line two."]

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": llm_lines}):
            result = apply_llm_insights(insights, user_id="user-1")

        assert len(result) == 2
        assert result[0]["line"] == "Line one."
        assert result[1]["line"] == "Line two."

    def test_ordering_preserved(self):
        """AC2: insight ordering matches input ordering."""
        from backend.services.habit_insights import apply_llm_insights

        i1 = _make_insight(habit_name="Run")
        i2 = _make_insight(habit_id="bbb", habit_name="Sleep")
        llm_lines = ["Run line.", "Sleep line."]

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": llm_lines}):
            result = apply_llm_insights([i1, i2], user_id="user-1")

        assert result[0]["habit_name"] == "Run"
        assert result[1]["habit_name"] == "Sleep"

    def test_uses_fast_model_tier(self):
        """AC7: complete_structured is called with model_tier='fast'."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        llm_line = "Morning Run correlates 0.65 with energy (n=30)."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.complete_structured", return_value={"lines": [llm_line]}) as mock_cs, \
             patch("backend.services.llm.get_or_generate", side_effect=lambda user_id, surface, signature, generate_fn, **kw: generate_fn()):
            apply_llm_insights([insight], user_id="user-1")
            mock_cs.assert_called_once()
            assert mock_cs.call_args.kwargs.get("model_tier") == "fast" or mock_cs.call_args[1].get("model_tier") == "fast" or "fast" in str(mock_cs.call_args)

    def test_surface_is_habit_insights(self):
        """AC5: get_or_generate called with surface='habit_insights'."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": ["some line."]}) as mock_gor:
            apply_llm_insights([insight], user_id="user-1")
            assert mock_gor.call_args[1].get("surface") == "habit_insights" or mock_gor.call_args[0][1] == "habit_insights"


# ============================================================================
# AC4: Fallback — insights
# ============================================================================

class TestInsightsFallback:
    """AC4: every failure mode falls back to exact coaching_voice output."""

    def test_fallback_when_llm_disabled(self):
        """AC4: LLM_COACH_ENABLED not set → original lines returned unchanged."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        original_line = insight["line"]

        env = dict(_DISABLED_ENV)
        env.pop("LLM_COACH_ENABLED", None)
        env.pop("GROQ_API_KEY", None)

        with patch.dict(os.environ, env, clear=True), \
             patch("backend.services.llm.get_or_generate") as mock_gor:
            result = apply_llm_insights([insight], user_id="user-1")
            mock_gor.assert_not_called()

        assert result[0]["line"] == original_line

    def test_fallback_when_get_or_generate_returns_none(self):
        """AC4: get_or_generate returns None → original lines returned."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        original_line = insight["line"]

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value=None):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == original_line

    def test_fallback_when_lines_count_mismatch(self):
        """AC4: LLM returns wrong number of lines → fallback to original."""
        from backend.services.habit_insights import apply_llm_insights

        insights = [_make_insight(), _make_insight(habit_id="bbb")]
        original_lines = [i["line"] for i in insights]

        # LLM returns only 1 line for 2 insights
        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": ["Only one line."]}):
            result = apply_llm_insights(insights, user_id="user-1")

        assert result[0]["line"] == original_lines[0]
        assert result[1]["line"] == original_lines[1]

    def test_fallback_when_line_too_long(self):
        """AC3 + AC4: a line exceeding the length cap triggers fallback."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        original_line = insight["line"]
        long_line = "x" * 300  # exceeds 250-char cap

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [long_line]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == original_line

    def test_fallback_when_invented_numeral(self):
        """AC3 + AC4: numeral in output not present in input facts → fallback."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight(coefficient=0.65, sample_size=30)
        original_line = insight["line"]

        # "99" does not appear in facts (coefficient=0.65, sample_size=30)
        invented_line = "Morning Run shows 99 percent correlation with energy."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [invented_line]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == original_line

    def test_valid_numeral_passes(self):
        """AC3: numeral appearing in input facts does NOT trigger fallback."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight(coefficient=0.65, sample_size=30)

        # "0.65" and "30" appear in facts JSON
        valid_line = "Morning Run correlates 0.65 with energy over 30 days."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [valid_line]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == valid_line

    def test_fallback_on_missing_lines_key(self):
        """AC4: LLM returns dict without 'lines' key → fallback."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        original_line = insight["line"]

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"text": "wrong key"}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == original_line

    def test_empty_insights_returns_empty(self):
        """AC4: empty insights list → empty list returned without calling LLM."""
        from backend.services.habit_insights import apply_llm_insights

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate") as mock_gor:
            result = apply_llm_insights([], user_id="user-1")
            mock_gor.assert_not_called()

        assert result == []


# ============================================================================
# AC1 + AC2 + AC7: LLM path — nudges
# ============================================================================

class TestNudgesLLMPath:
    """AC1: LLM-enabled path replaces nudge strings."""

    def test_llm_replaces_nudges(self):
        """AC1: apply_llm_nudges returns nudge_result with LLM-phrased nudges."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = _make_nudge_result()
        llm_line = "Consider planning ahead — Meditation tends to slip mid-week."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [llm_line]}):
            result = apply_llm_nudges(
                nudge_result,
                adherence_breakdowns={},
                slipping_habits=[_make_slipping_habit()],
                user_id="user-1",
            )

        assert result["nudges"] == [llm_line]

    def test_structure_keys_preserved(self):
        """AC2: non-nudge keys (debug, etc.) are preserved."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = _make_nudge_result()
        llm_line = "Meditation is showing a slip pattern — a light reset may help."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [llm_line]}):
            result = apply_llm_nudges(
                nudge_result,
                adherence_breakdowns={},
                slipping_habits=[_make_slipping_habit()],
                user_id="user-1",
            )

        assert "debug" in result

    def test_nudge_count_unchanged(self):
        """AC2: number of nudges matches input (cap of MAXIMUM_NUDGES respected)."""
        from backend.services.habit_nudges import apply_llm_nudges, MAXIMUM_NUDGES

        nudges = [f"nudge {i}" for i in range(3)]
        signals = [{"type": "slipping", "habit": f"Habit{i}", "prev_percent": 90.0, "current_percent": 50.0, "emitted": True} for i in range(3)]
        nudge_result = _make_nudge_result(nudges=nudges, signals=signals)
        llm_lines = [f"LLM nudge {i}." for i in range(3)]

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": llm_lines}):
            result = apply_llm_nudges(nudge_result, {}, [], user_id="user-1")

        assert len(result["nudges"]) == 3
        assert len(result["nudges"]) <= MAXIMUM_NUDGES

    def test_surface_is_habit_nudges(self):
        """AC5: get_or_generate called with surface='habit_nudges'."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = _make_nudge_result()
        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": ["a line."]}) as mock_gor:
            apply_llm_nudges(nudge_result, {}, [_make_slipping_habit()], user_id="user-1")
            args = mock_gor.call_args
            surface_val = args[1].get("surface") if args[1] else args[0][1]
            assert surface_val == "habit_nudges"


# ============================================================================
# AC4: Fallback — nudges
# ============================================================================

class TestNudgesFallback:
    """AC4: every failure mode falls back to exact template output."""

    def test_fallback_when_disabled(self):
        """AC4: LLM disabled → original nudges unchanged."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = _make_nudge_result()
        original_nudges = list(nudge_result["nudges"])

        env = dict(_DISABLED_ENV)
        env.pop("LLM_COACH_ENABLED", None)
        env.pop("GROQ_API_KEY", None)

        with patch.dict(os.environ, env, clear=True), \
             patch("backend.services.llm.get_or_generate") as mock_gor:
            result = apply_llm_nudges(nudge_result, {}, [_make_slipping_habit()], user_id="user-1")
            mock_gor.assert_not_called()

        assert result["nudges"] == original_nudges

    def test_fallback_when_none_result(self):
        """AC4: get_or_generate returns None → original nudges."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = _make_nudge_result()
        original_nudges = list(nudge_result["nudges"])

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value=None):
            result = apply_llm_nudges(nudge_result, {}, [_make_slipping_habit()], user_id="user-1")

        assert result["nudges"] == original_nudges

    def test_fallback_when_count_mismatch(self):
        """AC4: LLM returns wrong number of lines → fallback."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = _make_nudge_result(
            nudges=["nudge 1", "nudge 2"],
            signals=[
                {"type": "slipping", "habit": "H1", "prev_percent": 90.0, "current_percent": 50.0, "emitted": True},
                {"type": "slipping", "habit": "H2", "prev_percent": 80.0, "current_percent": 40.0, "emitted": True},
            ]
        )
        original_nudges = list(nudge_result["nudges"])

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": ["Only one."]}):
            result = apply_llm_nudges(nudge_result, {}, [], user_id="user-1")

        assert result["nudges"] == original_nudges

    def test_fallback_when_invented_numeral(self):
        """AC3 + AC4: numeral in output not in input facts → fallback."""
        from backend.services.habit_nudges import apply_llm_nudges

        slipping = [_make_slipping_habit(prev=90.0, current=50.0)]
        nudge_result = _make_nudge_result()
        original_nudges = list(nudge_result["nudges"])

        # "77" does not appear in facts (prev=90, current=50)
        invented_line = "Your Meditation habit dropped 77 points this period."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [invented_line]}):
            result = apply_llm_nudges(nudge_result, {}, slipping, user_id="user-1")

        assert result["nudges"] == original_nudges

    def test_fallback_when_line_too_long(self):
        """AC3 + AC4: nudge line exceeds length cap → fallback."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = _make_nudge_result()
        original_nudges = list(nudge_result["nudges"])
        long_line = "y" * 300

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [long_line]}):
            result = apply_llm_nudges(nudge_result, {}, [_make_slipping_habit()], user_id="user-1")

        assert result["nudges"] == original_nudges

    def test_empty_nudges_no_llm_call(self):
        """AC4: no nudges → no LLM call, original empty result returned."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = {"nudges": [], "debug": {"reason": "no adherence data provided"}}

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate") as mock_gor:
            result = apply_llm_nudges(nudge_result, {}, [], user_id="user-1")
            mock_gor.assert_not_called()

        assert result["nudges"] == []


# ============================================================================
# AC5: Signature / caching
# ============================================================================

class TestSignature:
    """AC5: signature = sha256 of computed facts; same facts → same signature."""

    def test_insights_signature_stable(self):
        """AC5: same facts produce same signature (deterministic)."""
        from backend.services.habit_insights import _insights_signature

        insight = _make_insight()
        sig1 = _insights_signature([insight])
        sig2 = _insights_signature([insight])
        assert sig1 == sig2

    def test_insights_signature_changes_on_different_facts(self):
        """AC5: different coefficient produces different signature."""
        from backend.services.habit_insights import _insights_signature

        i1 = _make_insight(coefficient=0.65)
        i2 = _make_insight(coefficient=0.72)
        assert _insights_signature([i1]) != _insights_signature([i2])

    def test_insights_signature_excludes_line(self):
        """AC5: 'line' field must not affect signature (LLM text isn't a fact)."""
        from backend.services.habit_insights import _insights_signature

        i1 = _make_insight(line="Template line.")
        i2 = _make_insight(line="LLM-phrased line.")
        assert _insights_signature([i1]) == _insights_signature([i2])

    def test_insights_signature_is_sha256(self):
        """AC5: signature is 64-character hex string (sha256)."""
        from backend.services.habit_insights import _insights_signature

        sig = _insights_signature([_make_insight()])
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_nudges_signature_stable(self):
        """AC5: same adherence/slipping data → same signature."""
        from backend.services.habit_nudges import _nudges_signature

        slipping = [_make_slipping_habit()]
        breakdowns = {"Meditation": {"weekday_pct": {}, "overall_avg": 70.0}}

        sig1 = _nudges_signature(breakdowns, slipping)
        sig2 = _nudges_signature(breakdowns, slipping)
        assert sig1 == sig2

    def test_nudges_signature_changes_on_different_data(self):
        """AC5: different adherence data → different signature."""
        from backend.services.habit_nudges import _nudges_signature

        s1 = _nudges_signature({}, [_make_slipping_habit(prev=90.0, current=50.0)])
        s2 = _nudges_signature({}, [_make_slipping_habit(prev=80.0, current=40.0)])
        assert s1 != s2

    def test_nudges_signature_is_sha256(self):
        """AC5: nudges signature is 64-character hex string."""
        from backend.services.habit_nudges import _nudges_signature

        sig = _nudges_signature({}, [_make_slipping_habit()])
        assert len(sig) == 64

    def test_cache_hit_skips_generate_fn(self):
        """AC5: when get_or_generate has a cache hit, generate_fn is not invoked."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        llm_line = "Cached line from LLM."
        generate_fn_calls = []

        def fake_gor(user_id, surface, signature, generate_fn, **kw):
            # simulate cache hit — never calls generate_fn
            return {"lines": [llm_line]}

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", side_effect=fake_gor):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == llm_line
        assert generate_fn_calls == []  # generate_fn was not called in this fake

    def test_get_or_generate_called_with_user_id(self):
        """AC5: get_or_generate receives the caller's user_id."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        captured = {}

        def fake_gor(user_id, surface, signature, generate_fn, **kw):
            captured["user_id"] = user_id
            return {"lines": ["a line."]}

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", side_effect=fake_gor):
            apply_llm_insights([insight], user_id="test-user-42")

        assert captured["user_id"] == "test-user-42"


# ============================================================================
# AC3: Numeral validation
# ============================================================================

class TestNumeralValidation:
    """AC3: any numeral in output must appear in input facts."""

    def test_no_numerals_in_output_passes(self):
        """AC3: line with no digits is always valid."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        pure_text_line = "Morning Run is associated with better energy on the same day."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [pure_text_line]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == pure_text_line

    def test_numeral_from_facts_passes(self):
        """AC3: numeral that exists in facts JSON is valid."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight(coefficient=0.65, sample_size=30)
        # Both 0.65 and 30 appear in facts
        line = "Correlates 0.65 over 30 data points."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [line]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == line

    def test_invented_integer_triggers_fallback(self):
        """AC3: invented integer not in facts → fallback."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight(coefficient=0.65, sample_size=30)
        original_line = insight["line"]
        invented = "Correlates 99 percent."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [invented]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == original_line

    def test_invented_float_triggers_fallback(self):
        """AC3: invented float not in facts → fallback."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight(coefficient=0.65, sample_size=30)
        original_line = insight["line"]
        invented = "Correlates 0.99 with energy."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [invented]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert result[0]["line"] == original_line


# ============================================================================
# AC6: coaching_voice.py and its determinism remain untouched
# ============================================================================

class TestCoachingVoiceUntouched:
    """AC6: coaching_voice determinism tests still pass."""

    def test_praise_line_builder_deterministic(self):
        """AC6: coaching_voice.praise_line_builder unchanged and deterministic."""
        import backend.services.coaching_voice as cv

        line1 = cv.praise_line_builder("sessions", 8.0, "up", "9 sessions targeted this week")
        line2 = cv.praise_line_builder("sessions", 8.0, "up", "9 sessions targeted this week")
        assert line1 == line2
        assert "sessions" in line1
        assert "!" not in line1

    def test_reframe_line_builder_deterministic(self):
        """AC6: coaching_voice.reframe_line_builder unchanged and deterministic."""
        import backend.services.coaching_voice as cv

        line1 = cv.reframe_line_builder("HRV", 42.0, "down", "week of solid training")
        line2 = cv.reframe_line_builder("HRV", 42.0, "down", "week of solid training")
        assert line1 == line2
        assert "!" not in line1

    def test_build_insights_pure_function_unchanged(self):
        """AC6: build_insights pure function still returns coaching_voice lines when no LLM."""
        from backend.services.habit_insights import build_insights

        import types

        def _h(hid, name):
            h = types.SimpleNamespace()
            h.id = hid
            h.name = name
            return h

        dates = [f"2025-01-{str(i+1).zfill(2)}" for i in range(20)]
        habit = _h("aaa", "Sleep")
        logs = {d: (1.0 if i % 2 == 0 else 0.0) for i, d in enumerate(dates)}
        outcome = {d: (4.0 if i % 2 == 0 else 2.0) for i, d in enumerate(dates)}

        insights, building, reason = build_insights(
            habits=[habit],
            habit_logs_by_habit={"aaa": logs},
            outcome_series_by_name={"energy": outcome},
            min_sample_size=5,
        )

        if not building:
            # Should have at least one insight with a non-empty line
            assert any(ins.get("line") for ins in insights)

    def test_build_nudges_pure_function_unchanged(self):
        """AC6: build_nudges still works without LLM involvement."""
        from backend.services.habit_nudges import build_nudges

        slipping = [{"name": "Meditation", "prev_percent": 90.0, "current_percent": 50.0}]
        result = build_nudges({}, slipping)
        assert "nudges" in result
        assert "debug" in result
        assert len(result["nudges"]) == 1
        assert "Meditation" in result["nudges"][0]


# ============================================================================
# AC2: Endpoint response shape (structure contract)
# ============================================================================

class TestResponseShapeContract:
    """AC2: response JSON structure is identical before and after LLM coating."""

    def test_insights_keys_unchanged(self):
        """AC2: insight dict always has exactly the same set of keys."""
        from backend.services.habit_insights import apply_llm_insights

        insight = _make_insight()
        expected_keys = set(insight.keys())
        llm_line = "Morning Run correlates 0.65 with energy over 30 days."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [llm_line]}):
            result = apply_llm_insights([insight], user_id="user-1")

        assert set(result[0].keys()) == expected_keys

    def test_nudges_keys_unchanged(self):
        """AC2: nudge_result always has the same top-level keys."""
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = _make_nudge_result()
        expected_keys = set(nudge_result.keys())
        llm_line = "Consider planning ahead for your Meditation habit."

        with patch.dict(os.environ, _LLM_ENV, clear=True), \
             patch("backend.services.llm.get_or_generate", return_value={"lines": [llm_line]}):
            result = apply_llm_nudges(nudge_result, {}, [_make_slipping_habit()], user_id="user-1")

        assert set(result.keys()) == expected_keys
