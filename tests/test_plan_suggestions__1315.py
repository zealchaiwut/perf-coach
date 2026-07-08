"""Unit tests for training plan suggestions feature (issue #1315).

Covers Acceptance Criteria:
- AC1: GET /api/plan/suggestions session-auth endpoint, response shape
- AC2: Facts assembled rule-side: CTL/ATL/TSB, 7/28-day load, readiness trend,
       next race (date/distance/goal), guardrail/ACWR headroom
- AC3: Hard rule-side validation of LLM output (reject + fall back on violation):
       ≤7 sessions; per-session TSS within sane bounds; WEEKLY total TSS within
       ACWR-safe ramp vs trailing 28-day average; workout types from known set;
       rest days allowed
- AC4: JSON-schema structured output, DEEP model tier; prompt includes safety instruction
- AC5: Deterministic fallback: template week scaled from trailing 28-day average load
       respecting ramp cap; pure function unit-tested
- AC6: Cached in llm_generations (surface="plan_suggestion", signature over facts)
- AC7: Frontend suggestions panel HTML element present
- AC8: Accepted suggestion creates planned session identical to manually created one;
       validator rejects over-ramp / unknown-type / >7-session outputs
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import service under test
# ---------------------------------------------------------------------------

from backend.services import plan_suggestions as ps


# ---------------------------------------------------------------------------
# AC3/AC8 — validator tests (pure function)
# ---------------------------------------------------------------------------

KNOWN_TYPES = ps.KNOWN_WORKOUT_TYPES


class TestValidateSuggestions:
    """AC3 / AC8: validator rejects bad LLM output; falls back on violation."""

    def _valid_facts(self, trailing_weekly_avg=200.0):
        return {
            "trailing_28d_weekly_avg_tss": trailing_weekly_avg,
            "acwr_headroom_tss": trailing_weekly_avg * 0.3,
        }

    def _valid_suggestion(self, workout_type="run", tss=60, duration=50):
        s = {
            "day_offset": 1,
            "workout_type": workout_type,
            "target_tss": tss,
            "duration_minutes": duration,
            "intent": "Easy aerobic run to build base fitness.",
        }
        # strength/plyo now require an exercises breakdown — default one in so
        # callers that don't care about this detail still produce valid output.
        if workout_type in ("strength", "plyo"):
            s["exercises"] = [
                {"block": "Main", "name": "Back squat", "sets": 3, "reps": "8", "load": "moderate"},
            ]
        return s

    def test_valid_output_passes(self):
        facts = self._valid_facts(200.0)
        suggestions = [
            self._valid_suggestion("run", 60, 50),
            self._valid_suggestion("strength", 40, 45),
            self._valid_suggestion("rest", 0, 0),
        ]
        assert ps.validate_suggestions(suggestions, facts) is True

    def test_too_many_sessions_fails(self):
        facts = self._valid_facts(200.0)
        suggestions = [self._valid_suggestion() for _ in range(8)]
        assert ps.validate_suggestions(suggestions, facts) is False

    def test_exactly_7_sessions_passes(self):
        facts = self._valid_facts(500.0)
        suggestions = [self._valid_suggestion("run", 50, 45) for _ in range(7)]
        assert ps.validate_suggestions(suggestions, facts) is True

    def test_unknown_workout_type_fails(self):
        facts = self._valid_facts(200.0)
        suggestions = [self._valid_suggestion(workout_type="yoga")]
        assert ps.validate_suggestions(suggestions, facts) is False

    def test_per_session_tss_too_high_fails(self):
        facts = self._valid_facts(200.0)
        suggestions = [self._valid_suggestion("run", tss=401)]
        assert ps.validate_suggestions(suggestions, facts) is False

    def test_per_session_tss_negative_fails(self):
        facts = self._valid_facts(200.0)
        suggestions = [self._valid_suggestion("run", tss=-1)]
        assert ps.validate_suggestions(suggestions, facts) is False

    def test_rest_day_zero_tss_passes(self):
        facts = self._valid_facts(200.0)
        suggestions = [self._valid_suggestion("rest", tss=0, duration=0)]
        assert ps.validate_suggestions(suggestions, facts) is True

    def test_weekly_total_tss_exceeds_acwr_ramp_fails(self):
        # trailing 28d avg = 100, max safe = 100 * 1.3 = 130
        facts = self._valid_facts(100.0)
        suggestions = [self._valid_suggestion("run", tss=50) for _ in range(4)]
        # total = 200 > 130
        assert ps.validate_suggestions(suggestions, facts) is False

    def test_weekly_total_tss_within_ramp_passes(self):
        facts = self._valid_facts(200.0)
        # 4 sessions × 60 TSS = 240 < 200 * 1.3 = 260
        suggestions = [self._valid_suggestion("run", tss=60) for _ in range(4)]
        assert ps.validate_suggestions(suggestions, facts) is True

    def test_all_known_types_pass(self):
        facts = self._valid_facts(500.0)
        for t in KNOWN_TYPES:
            tss = 0 if t == "rest" else 50
            suggestions = [self._valid_suggestion(t, tss=tss)]
            assert ps.validate_suggestions(suggestions, facts) is True, f"type {t!r} should pass"

    def test_empty_suggestions_passes(self):
        facts = self._valid_facts(200.0)
        assert ps.validate_suggestions([], facts) is True


# ---------------------------------------------------------------------------
# AC5 — fallback generator (pure function)
# ---------------------------------------------------------------------------

class TestFallbackSuggestions:
    """AC5: template week scaled from trailing 28d avg, respects ramp cap."""

    def _base_facts(self, trailing_weekly_avg=200.0, days_to_race=None):
        facts = {
            "trailing_28d_weekly_avg_tss": trailing_weekly_avg,
            "acwr_headroom_tss": trailing_weekly_avg * 0.3,
        }
        if days_to_race is not None:
            facts["days_to_next_race"] = days_to_race
        return facts

    def test_returns_list(self):
        result = ps.fallback_suggestions(self._base_facts(200.0))
        assert isinstance(result, list)

    def test_at_most_7_sessions(self):
        result = ps.fallback_suggestions(self._base_facts(200.0))
        assert len(result) <= 7

    def test_each_session_has_required_keys(self):
        result = ps.fallback_suggestions(self._base_facts(200.0))
        for s in result:
            assert "day_offset" in s
            assert "workout_type" in s
            assert "target_tss" in s
            assert "duration_minutes" in s
            assert "intent" in s

    def test_all_types_are_known(self):
        result = ps.fallback_suggestions(self._base_facts(200.0))
        for s in result:
            assert s["workout_type"] in KNOWN_TYPES, f"{s['workout_type']!r} not in known types"

    def test_weekly_total_within_ramp_cap(self):
        trailing = 200.0
        result = ps.fallback_suggestions(self._base_facts(trailing))
        total_tss = sum(s.get("target_tss", 0) for s in result)
        max_allowed = trailing * ps.ACWR_HIGH_BOUND
        assert total_tss <= max_allowed, f"{total_tss} > {max_allowed}"

    def test_taper_when_race_within_14_days(self):
        # With no race, get base TSS total
        normal = ps.fallback_suggestions(self._base_facts(300.0))
        normal_total = sum(s.get("target_tss", 0) for s in normal)

        # With race in 7 days, total should be lower
        taper = ps.fallback_suggestions(self._base_facts(300.0, days_to_race=7))
        taper_total = sum(s.get("target_tss", 0) for s in taper)

        assert taper_total < normal_total, "taper week should have less TSS than normal"

    def test_no_race_taper_when_race_far(self):
        normal = ps.fallback_suggestions(self._base_facts(300.0))
        far_race = ps.fallback_suggestions(self._base_facts(300.0, days_to_race=30))
        assert sum(s.get("target_tss", 0) for s in far_race) == sum(
            s.get("target_tss", 0) for s in normal
        )

    def test_zero_trailing_load_still_returns_sessions(self):
        result = ps.fallback_suggestions(self._base_facts(0.0))
        assert isinstance(result, list)
        assert len(result) > 0

    def test_fallback_respects_ramp_cap_for_low_base(self):
        # Edge: very low trailing, fallback should not produce unsafe spike
        result = ps.fallback_suggestions(self._base_facts(20.0))
        total = sum(s.get("target_tss", 0) for s in result)
        assert total <= max(20.0 * ps.ACWR_HIGH_BOUND, ps.FALLBACK_MIN_WEEKLY_TSS * ps.ACWR_HIGH_BOUND)

    def test_day_offsets_in_range(self):
        result = ps.fallback_suggestions(self._base_facts(200.0))
        for s in result:
            assert 0 <= s["day_offset"] <= 6

    def test_is_deterministic(self):
        facts = self._base_facts(250.0)
        r1 = ps.fallback_suggestions(facts)
        r2 = ps.fallback_suggestions(facts)
        assert r1 == r2


# ---------------------------------------------------------------------------
# AC4 — LLM prompt contains safety instruction
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    """AC4: prompt includes safety instruction re: ramp limit and taper."""

    def _base_facts(self):
        return {
            "ctl": 42.0,
            "atl": 45.0,
            "tsb": -3.0,
            "trailing_28d_weekly_avg_tss": 200.0,
            "acwr_headroom_tss": 60.0,
            "trailing_7d_tss": 150.0,
            "readiness_trend": [70, 72, 68],
            "days_to_next_race": None,
        }

    def test_prompt_mentions_ramp(self):
        sys_p, user_p = ps.build_prompt(self._base_facts())
        combined = (sys_p + user_p).lower()
        assert "ramp" in combined or "acwr" in combined or "headroom" in combined

    def test_prompt_mentions_taper_when_race_imminent(self):
        facts = {**self._base_facts(), "days_to_next_race": 10}
        sys_p, user_p = ps.build_prompt(facts)
        combined = (sys_p + user_p).lower()
        assert "taper" in combined or "race" in combined

    def test_prompt_returns_tuple_of_strings(self):
        sys_p, user_p = ps.build_prompt(self._base_facts())
        assert isinstance(sys_p, str)
        assert isinstance(user_p, str)


# ---------------------------------------------------------------------------
# AC6 — signature function
# ---------------------------------------------------------------------------

class TestBuildSignature:
    """AC6: signature changes when facts change."""

    def _facts(self, ctl=42.0, atl=45.0):
        return {"ctl": ctl, "atl": atl, "trailing_28d_weekly_avg_tss": 200.0}

    def test_same_facts_same_sig(self):
        assert ps.build_signature(self._facts()) == ps.build_signature(self._facts())

    def test_different_facts_different_sig(self):
        assert ps.build_signature(self._facts(ctl=42.0)) != ps.build_signature(self._facts(ctl=43.0))

    def test_returns_string(self):
        sig = ps.build_signature(self._facts())
        assert isinstance(sig, str)
        assert len(sig) == 64  # sha256 hex


# ---------------------------------------------------------------------------
# Mocked LLM happy path
# ---------------------------------------------------------------------------

class TestGetSuggestionsLLMPath:
    """Mocked LLM happy path — valid structured output is returned as source='llm'."""

    def _valid_llm_output(self):
        return {
            "suggestions": [
                {"day_offset": 1, "workout_type": "run", "target_tss": 60, "duration_minutes": 50, "intent": "Easy zone 2 run."},
                {"day_offset": 3, "workout_type": "run", "target_tss": 80, "duration_minutes": 65, "intent": "Tempo intervals."},
                {"day_offset": 5, "workout_type": "strength", "target_tss": 40, "duration_minutes": 45, "intent": "Leg strength.",
                 "exercises": [{"block": "Main", "name": "Back squat", "sets": 3, "reps": "8", "load": "moderate"}]},
                {"day_offset": 6, "workout_type": "rest", "target_tss": 0, "duration_minutes": 0, "intent": "Full rest."},
            ]
        }

    def test_llm_enabled_path_returns_llm_source(self):
        facts = {
            "ctl": 42.0, "atl": 45.0, "tsb": -3.0,
            "trailing_28d_weekly_avg_tss": 200.0,
            "acwr_headroom_tss": 60.0,
            "trailing_7d_tss": 150.0,
            "readiness_trend": [70, 72, 68],
            "days_to_next_race": None,
        }
        llm_raw = self._valid_llm_output()

        with patch.object(ps, "_call_llm", return_value=llm_raw):
            result = ps.get_suggestions_from_facts(facts)

        assert result["source"] == "llm"
        assert len(result["suggestions"]) == 4

    def test_llm_invalid_output_falls_back(self):
        facts = {
            "ctl": 42.0, "atl": 45.0, "tsb": -3.0,
            "trailing_28d_weekly_avg_tss": 100.0,
            "acwr_headroom_tss": 30.0,
            "trailing_7d_tss": 80.0,
            "readiness_trend": [70],
            "days_to_next_race": None,
        }
        # Over-ramp LLM output: 4 × 50 TSS = 200 > 100 * 1.3 = 130
        bad_output = {
            "suggestions": [
                {"day_offset": i, "workout_type": "run", "target_tss": 50, "duration_minutes": 45, "intent": "Run."}
                for i in range(4)
            ]
        }
        with patch.object(ps, "_call_llm", return_value=bad_output):
            result = ps.get_suggestions_from_facts(facts)

        assert result["source"] == "fallback"

    def test_llm_disabled_falls_back(self):
        facts = {
            "ctl": 42.0, "atl": 45.0, "tsb": -3.0,
            "trailing_28d_weekly_avg_tss": 200.0,
            "acwr_headroom_tss": 60.0,
            "trailing_7d_tss": 150.0,
            "readiness_trend": [70],
            "days_to_next_race": None,
        }
        with patch.object(ps, "_call_llm", return_value=None):
            result = ps.get_suggestions_from_facts(facts)

        assert result["source"] == "fallback"

    def test_response_shape(self):
        facts = {
            "ctl": 42.0, "atl": 45.0, "tsb": -3.0,
            "trailing_28d_weekly_avg_tss": 200.0,
            "acwr_headroom_tss": 60.0,
            "trailing_7d_tss": 150.0,
            "readiness_trend": [70],
            "days_to_next_race": None,
        }
        with patch.object(ps, "_call_llm", return_value=None):
            result = ps.get_suggestions_from_facts(facts)

        assert "suggestions" in result
        assert "source" in result
        assert result["source"] in ("llm", "fallback")
        for s in result["suggestions"]:
            assert "day_offset" in s
            assert "workout_type" in s
            assert "target_tss" in s
            assert "duration_minutes" in s
            assert "intent" in s


# ---------------------------------------------------------------------------
# AC1 — Endpoint auth guard (live server not required — test via direct import)
# ---------------------------------------------------------------------------

class TestEndpointImport:
    """AC1: endpoint module loads and router is registered."""

    def test_router_has_plan_suggestions_route(self):
        from backend.routers import projection
        routes = [r.path for r in projection.router.routes]
        assert "/api/plan/suggestions" in routes


# ---------------------------------------------------------------------------
# AC7 — Frontend HTML element present
# ---------------------------------------------------------------------------

class TestFrontendPresence:
    """AC7: suggestions panel HTML element in training-log.html."""

    def test_suggestions_panel_element_present(self):
        import os
        html_path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "pages", "training-log.html"
        )
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        assert "plan-suggestions" in html

    def test_suggestions_js_loaded(self):
        import os
        html_path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "pages", "training-log.html"
        )
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        # suggestions JS is either inline or references a function
        assert "suggestions" in html.lower()
