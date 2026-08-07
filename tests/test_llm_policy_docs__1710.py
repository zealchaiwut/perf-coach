"""Documentation-accuracy tests for LLM policy reconciliation (issue #1710).

CLAUDE.md's "exactly one in-app LLM surface" claim was contradicted by four
additional live call sites (habit_insights, habit_nudges, readiness_explanation,
weekly_summary). The test_consolidation__worker_has_no_llm.py docstring also
cited "Ask-AI single session" as a sanctioned surface — stale since Ask-AI
plan generation switched to deterministic pattern-fill.

These tests verify the reconciliation:

AC1 — CLAUDE.md's LLM policy section documents all five live surfaces.
AC2 — Each of the four webapp surfaces falls back gracefully when LLM is
       disabled (no exception; returns the deterministic result).
AC3 — The worker-consolidation test docstring no longer references
       "Ask-AI single session" as a sanctioned provider-call surface.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
CLAUDE_MD = (REPO / "CLAUDE.md").read_text()


# ---------------------------------------------------------------------------
# AC1 — CLAUDE.md documents all live LLM surfaces
# ---------------------------------------------------------------------------

class TestClaudeMdDocumentsAllLlmSurfaces:
    """AC1: policy table is complete."""

    def test_habit_insights_surface_documented(self):
        assert "habit_insights" in CLAUDE_MD, (
            "CLAUDE.md should document the habit_insights LLM surface"
        )

    def test_habit_nudges_surface_documented(self):
        assert "habit_nudges" in CLAUDE_MD, (
            "CLAUDE.md should document the habit_nudges LLM surface"
        )

    def test_readiness_explanation_surface_documented(self):
        assert "readiness_explanation" in CLAUDE_MD, (
            "CLAUDE.md should document the readiness_explanation LLM surface"
        )

    def test_weekly_summary_surface_documented(self):
        assert "weekly_summary" in CLAUDE_MD, (
            "CLAUDE.md should document the weekly_summary LLM surface"
        )

    def test_weekly_coach_message_surface_still_documented(self):
        assert "weekly_coach_message" in CLAUDE_MD, (
            "CLAUDE.md must retain the original weekly_coach_message surface"
        )

    def test_no_longer_claims_exactly_one_surface(self):
        assert "Exactly one in-app LLM surface is sanctioned" not in CLAUDE_MD, (
            "CLAUDE.md should not claim 'exactly one' surface — there are five"
        )


# ---------------------------------------------------------------------------
# AC2 — each webapp surface falls back when LLM is disabled
# ---------------------------------------------------------------------------

class TestHabitInsightsFallback:
    """AC2: habit_insights returns original insights when LLM is off."""

    def test_returns_original_when_llm_disabled(self):
        from backend.services.habit_insights import apply_llm_insights

        insight = {
            "habit_name": "Sleep",
            "outcome_name": "HRV",
            "coefficient": 0.42,
            "sample_size": 30,
            "lag_days": 1,
            "line": "Original deterministic line",
        }
        with patch("backend.services.llm.llm_enabled", return_value=False):
            result = apply_llm_insights([insight], user_id="user-test")
        assert result == [insight]

    def test_empty_insights_returned_unchanged(self):
        from backend.services.habit_insights import apply_llm_insights

        with patch("backend.services.llm.llm_enabled", return_value=False):
            result = apply_llm_insights([], user_id="user-test")
        assert result == []


class TestHabitNudgesFallback:
    """AC2: habit_nudges returns original result when LLM is off."""

    def test_returns_original_when_llm_disabled(self):
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = {"nudges": ["Keep it up with Sleep — 6 out of 7 days this week."]}
        with patch("backend.services.llm.llm_enabled", return_value=False):
            result = apply_llm_nudges(nudge_result, {}, [], user_id="user-test")
        assert result is nudge_result

    def test_empty_nudges_returned_unchanged(self):
        from backend.services.habit_nudges import apply_llm_nudges

        nudge_result = {"nudges": []}
        with patch("backend.services.llm.llm_enabled", return_value=False):
            result = apply_llm_nudges(nudge_result, {}, [], user_id="user-test")
        assert result is nudge_result


class TestReadinessExplanationFallback:
    """AC2: readiness_explanation returns rule-based string when LLM is off."""

    def _factors(self):
        return [
            {"factor": "sleep_hours", "value": 6.0, "score": 35.0, "impact": "negative"},
            {"factor": "hrv", "value": 55.0, "score": 60.0, "impact": "positive"},
            {"factor": "rhr", "value": 62.0, "score": 50.0, "impact": "neutral"},
            {"factor": "energy", "value": 3.0, "score": 50.0, "impact": "neutral"},
            {"factor": "mood", "value": 3.0, "score": 50.0, "impact": "neutral"},
        ]

    def test_returns_string_when_llm_disabled(self):
        from backend.services.readiness_explanation import get_readiness_explanation

        with patch("backend.services.llm.llm_enabled", return_value=False):
            result = get_readiness_explanation(
                user_id="user-test",
                target_date="2026-08-06",
                facts={"sleep_hours": 6.0, "hrv": 55.0, "rhr": 62.0},
                fallback_factors=self._factors(),
            )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_never_raises_when_llm_disabled(self):
        from backend.services.readiness_explanation import get_readiness_explanation

        with patch("backend.services.llm.llm_enabled", return_value=False):
            result = get_readiness_explanation(
                user_id="user-test",
                target_date="2026-08-06",
                facts={},
                fallback_factors=[],
            )
        assert isinstance(result, str)


class TestWeeklySummaryFallback:
    """AC2: weekly_summary returns fallback tuple when LLM is off."""

    def _facts(self):
        return {
            "week_start": "2026-07-28",
            "workout_count": 4,
            "workout_count_by_type": {"run": 3, "strength": 1},
            "total_tss": 280.0,
            "prev_week_tss": 260.0,
            "total_distance_km": 35.0,
            "prev_week_distance_km": 33.0,
            "total_duration_minutes": 180.0,
            "ctl_start": 42.0,
            "ctl_end": 44.0,
            "atl_start": 48.0,
            "atl_end": 50.0,
            "tsb_start": -6.0,
            "tsb_end": -6.0,
            "guardrail_state": "ok",
            "guardrail_message": "",
            "acwr": 1.08,
            "prs_this_week": [],
        }

    def test_returns_fallback_source_when_llm_disabled(self):
        from backend.services.weekly_summary import get_narrative

        with patch("backend.services.llm.llm_enabled", return_value=False):
            text, source = get_narrative(
                user_id="user-test",
                week_start="2026-07-28",
                facts=self._facts(),
            )
        assert source == "fallback"
        assert isinstance(text, str)
        assert len(text) > 0


# ---------------------------------------------------------------------------
# AC3 — test_consolidation docstring no longer mentions stale "Ask-AI" surface
# ---------------------------------------------------------------------------

class TestConsolidationDocstringIsUpdated:
    """AC3: worker-consolidation test docstring reflects current single worker surface."""

    def test_ask_ai_single_session_removed_from_docstring(self):
        """The stale 'Ask-AI single session' claim must be gone."""
        consolidation_file = REPO / "tests" / "test_consolidation__worker_has_no_llm.py"
        source = consolidation_file.read_text()
        # The old docstring said: "Two surfaces earn a provider call:
        # 1. Ask-AI single session — interactive, in the webapp."
        # Since Ask-AI is now pattern-fill-only, it must not be claimed as an LLM surface.
        assert "Ask-AI single session" not in source, (
            "test_consolidation__worker_has_no_llm.py still describes 'Ask-AI single session' "
            "as an LLM surface — it's been pattern-fill-only since the PR #1597 consolidation"
        )

    def test_docstring_does_not_claim_two_sanctioned_surfaces(self):
        """The stale 'exactly two calls wide' / 'Two surfaces' claim must be gone."""
        consolidation_file = REPO / "tests" / "test_consolidation__worker_has_no_llm.py"
        source = consolidation_file.read_text()
        # The old module docstring opened with: "Guard: the worker's LLM surface
        # stays exactly two calls wide." and "Two surfaces earn a provider call:"
        # This is wrong — only the daily coach message is on the worker.
        assert "exactly two calls wide" not in source, (
            "test_consolidation__worker_has_no_llm.py still claims 'exactly two calls wide' "
            "in its docstring — only the daily coach message (weekly_coach_message) runs on "
            "the worker; other surfaces (habit_insights etc.) are webapp-side"
        )
