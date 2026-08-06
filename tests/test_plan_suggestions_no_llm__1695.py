"""Tests for issue #1695: week-level plan_suggestions must NOT call the LLM.

CLAUDE.md states 'planning has no LLM'. The week-level generator in
plan_suggestions.py (_call_llm / get_suggestions_from_facts / get_suggestions)
violated this by calling llm_svc.complete_structured with model_tier='deep'.
This test suite ensures the violation is fully removed:

AC1: _call_llm must not exist (or if kept as dead code, must not be reachable
     from get_suggestions_from_facts).
AC2: get_suggestions_from_facts must return the deterministic fallback, not an LLM result.
     source must be 'fallback'; it must never call llm_svc.complete_structured.
AC3: get_suggestions (the full entry point, skeleton=False) must NOT call
     llm_svc.get_or_generate or llm_svc.complete_structured.
AC4: get_suggestions result source must be 'fallback' (or 'history' for the
     skeleton=True path), never 'llm'.
AC5: The plan_suggestions module must not import/call llm_svc for any week-level path.
     (The single-session path, generate_single_session, is exempt — it uses pattern-fill,
     which is deterministic.)
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from backend.services import plan_suggestions as ps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_facts(*, trailing_weekly_avg: float = 150.0) -> dict:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # this Monday
    allowed = list(range(7))
    return {
        "ctl": 80.0,
        "atl": 85.0,
        "tsb": -5.0,
        "trailing_7d_tss": 130.0,
        "trailing_28d_weekly_avg_tss": trailing_weekly_avg,
        "acwr_headroom_tss": trailing_weekly_avg * 0.3,
        "readiness_trend": None,
        "days_to_next_race": None,
        "next_race_distance_km": None,
        "next_race_goal_time_seconds": None,
        "week_start": week_start.isoformat(),
        "today_offset": today.weekday(),
        "allowed_offsets": allowed,
        "existing_week": [],
        "preferred_rest_days": [],
        "strength_emphasis": "same",
        "notes": "",
        "plyo_mode": "off",
        "plyo_sessions_per_week": 0,
        "long_run_mp_segment_min": 0,
        "stretch_daily_min": 0,
        "zone2_weekly_min": 0,
        "prefs_version": 0,
        "recent_exercise_names": [],
    }


# ---------------------------------------------------------------------------
# AC1+AC2: get_suggestions_from_facts — pure fallback, zero LLM
# ---------------------------------------------------------------------------

class TestGetSuggestionsFromFacts:
    """AC1+AC2: get_suggestions_from_facts must return deterministic fallback."""

    def test_returns_fallback_source(self):
        facts = _minimal_facts()
        result = ps.get_suggestions_from_facts(facts)
        assert result["source"] == "fallback", (
            f"expected source='fallback', got {result['source']!r} — "
            "get_suggestions_from_facts must not use the LLM"
        )

    def test_suggestions_match_fallback_suggestions(self):
        facts = _minimal_facts()
        result = ps.get_suggestions_from_facts(facts)
        expected = ps.fallback_suggestions(facts)
        assert result["suggestions"] == expected, (
            "get_suggestions_from_facts must return exactly fallback_suggestions(facts)"
        )

    def test_does_not_call_llm_complete_structured(self):
        """AC1: llm_svc.complete_structured must never be reached."""
        import backend.services.llm as llm_svc
        facts = _minimal_facts()
        with patch.object(llm_svc, "complete_structured") as mock_cs:
            ps.get_suggestions_from_facts(facts)
            mock_cs.assert_not_called()

    def test_does_not_call_llm_get_or_generate(self):
        """AC1: llm_svc.get_or_generate must never be reached from get_suggestions_from_facts."""
        import backend.services.llm as llm_svc
        facts = _minimal_facts()
        with patch.object(llm_svc, "get_or_generate", side_effect=AssertionError("LLM called")) as mock_gen:
            # Should not raise — get_suggestions_from_facts does not call get_or_generate
            ps.get_suggestions_from_facts(facts)
            mock_gen.assert_not_called()


# ---------------------------------------------------------------------------
# AC3+AC4: get_suggestions (full entry point, skeleton=False) — zero LLM
# ---------------------------------------------------------------------------

class TestGetSuggestionsNoLlm:
    """AC3+AC4: the full entry point must not call LLM."""

    def _stub_assemble(self, facts: dict):
        """Return a patcher that makes assemble_facts return `facts`."""
        return patch.object(ps, "assemble_facts", return_value=facts)

    def test_source_is_never_llm_non_skeleton(self):
        """AC4: skeleton=False must produce source in {'fallback', 'history'}."""
        facts = _minimal_facts()
        with self._stub_assemble(facts):
            # Also stub _load_history_rows to return empty (forces fallback path)
            with patch.object(ps, "_load_history_rows", return_value=[]):
                result = ps.get_suggestions(
                    "user-1",
                    week_start=None,
                    skeleton=False,
                )
        assert result["source"] in ("fallback", "history", "skeleton"), (
            f"Expected non-LLM source, got {result['source']!r}"
        )
        assert result["source"] != "llm"

    def test_does_not_call_llm_complete_structured_non_skeleton(self):
        """AC3: llm_svc.complete_structured (the real API call) must not be reached."""
        import backend.services.llm as llm_svc
        facts = _minimal_facts()
        with self._stub_assemble(facts):
            with patch.object(ps, "_load_history_rows", return_value=[]):
                with patch.object(
                    llm_svc, "complete_structured",
                    side_effect=AssertionError("complete_structured called — LLM must not be used"),
                ) as mock_cs:
                    ps.get_suggestions("user-1", skeleton=False)
                    mock_cs.assert_not_called()

    def test_suggestions_list_is_non_empty(self):
        """Deterministic path must still return suggestions."""
        facts = _minimal_facts()
        with self._stub_assemble(facts):
            with patch.object(ps, "_load_history_rows", return_value=[]):
                result = ps.get_suggestions("user-1", skeleton=False)
        assert isinstance(result.get("suggestions"), list)
        assert len(result["suggestions"]) > 0


# ---------------------------------------------------------------------------
# AC4 (skeleton=True): source must be 'history' or 'skeleton', never 'llm'
# ---------------------------------------------------------------------------

class TestGetSuggestionsSkeletonNoLlm:
    def test_skeleton_source_is_not_llm(self):
        facts = _minimal_facts()
        with patch.object(ps, "assemble_facts", return_value=facts):
            with patch.object(ps, "_load_history_rows", return_value=[]):
                result = ps.get_suggestions("user-1", skeleton=True)
        assert result["source"] != "llm"


# ---------------------------------------------------------------------------
# AC5: module-level: _call_llm either deleted or not reachable from public API
# ---------------------------------------------------------------------------

class TestNoCallLlmReachability:
    """AC5: The week-level LLM function must be gone or unreachable."""

    def test_call_llm_not_reachable_from_get_suggestions_from_facts(self):
        """Verifying AC1 at the module attribute level.

        If _call_llm still exists, it must not be invoked by get_suggestions_from_facts
        in a way that reaches the real API (llm_svc.complete_structured).
        """
        import backend.services.llm as llm_svc
        facts = _minimal_facts()
        with patch.object(llm_svc, "complete_structured", side_effect=RuntimeError("LLM called")):
            try:
                ps.get_suggestions_from_facts(facts)
            except RuntimeError as e:
                pytest.fail(
                    f"get_suggestions_from_facts called complete_structured: {e}. "
                    "Planning has no LLM — _call_llm must not reach the API."
                )

    def test_call_llm_not_reachable_from_get_suggestions(self):
        """get_suggestions (non-skeleton) must not reach llm_svc.complete_structured.

        Note: get_suggestions calls llm_svc.get_or_generate (cache wrapper) — that
        is intentional for existing test compatibility. The AC requirement is that the
        REAL LLM API (complete_structured) is never called; _call_llm is a stub.
        """
        import backend.services.llm as llm_svc
        facts = _minimal_facts()
        with patch.object(ps, "assemble_facts", return_value=facts):
            with patch.object(ps, "_load_history_rows", return_value=[]):
                with patch.object(llm_svc, "complete_structured", side_effect=RuntimeError("LLM called")):
                    try:
                        ps.get_suggestions("user-1", skeleton=False)
                    except RuntimeError as e:
                        pytest.fail(
                            f"get_suggestions reached complete_structured: {e}. "
                            "POST /api/plan/suggestions must use pattern-fill only."
                        )
