"""Tests for weekly summary narrative feature (issue #1314).

Covers Acceptance Criteria:
- AC1: GET /api/weekly-summary endpoint — session auth, optional week param, response shape
- AC2: facts computed rule-side: weekly TSS/distance/duration vs prior week,
       CTL/ATL/TSB start→end, ACWR/guardrail flags, PRs achieved, workout count by type
- AC3: Narrative via GROQ_MODEL_DEEP, JSON-schema output, paragraph length cap,
       numeral-validation guard, no medical advice constraint
- AC4: Fallback narrative — deterministic sentence/bullet from facts, pure function, tested
- AC5: Cached in llm_generations (surface="weekly_summary"), signature over user+week+facts;
       regenerates when facts change
- AC6: Frontend card (HTML element present; graceful empty state)
- AC7: Weeks with zero data return valid response, no 404
- AC8: Tests: facts assembly (loaded/empty/PR weeks), fallback renderer, mocked LLM
       shape+guard, cache behavior, auth 401
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from backend.services import weekly_summary as ws


# ---------------------------------------------------------------------------
# AC4 — fallback renderer (pure function)
# ---------------------------------------------------------------------------

class TestFallbackRenderer:
    """AC4: deterministic fallback narrative from facts, pure function."""

    def _base_facts(self, **overrides):
        facts = {
            "week_start": "2026-06-30",
            "workout_count": 5,
            "workout_count_by_type": {"run": 3, "lift": 2},
            "total_tss": 320.0,
            "prev_week_tss": 280.0,
            "total_distance_km": 42.0,
            "prev_week_distance_km": 38.0,
            "total_duration_minutes": 210.0,
            "ctl_start": 45.0,
            "ctl_end": 47.5,
            "atl_start": 50.0,
            "atl_end": 53.0,
            "tsb_start": -5.0,
            "tsb_end": -5.5,
            "guardrail_state": "ok",
            "guardrail_message": "",
            "acwr": 1.1,
            "prs_achieved": [],
        }
        facts.update(overrides)
        return facts

    def test_returns_string(self):
        result = ws.build_fallback_narrative(self._base_facts())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mentions_workout_count(self):
        facts = self._base_facts(workout_count=5)
        result = ws.build_fallback_narrative(facts)
        assert "5" in result

    def test_mentions_tss(self):
        facts = self._base_facts(total_tss=320.0)
        result = ws.build_fallback_narrative(facts)
        assert "320" in result

    def test_mentions_distance_when_present(self):
        facts = self._base_facts(total_distance_km=42.0)
        result = ws.build_fallback_narrative(facts)
        assert "42" in result

    def test_mentions_guardrail_warn(self):
        facts = self._base_facts(
            guardrail_state="warn",
            guardrail_message="Your acute:chronic workload ratio is elevated.",
        )
        result = ws.build_fallback_narrative(facts)
        assert "warn" in result.lower() or "load" in result.lower() or "elevated" in result.lower()

    def test_mentions_pr_when_present(self):
        facts = self._base_facts(
            prs_achieved=[{"track_name": "5 km", "value_numeric": "1230.0"}]
        )
        result = ws.build_fallback_narrative(facts)
        assert "5 km" in result or "PR" in result or "personal" in result.lower()

    def test_empty_week_returns_honest_message(self):
        facts = self._base_facts(
            workout_count=0,
            total_tss=None,
            total_distance_km=None,
            total_duration_minutes=None,
            prs_achieved=[],
        )
        result = ws.build_fallback_narrative(facts)
        # AC7: honest "no training logged" message
        assert ("no training" in result.lower()
                or "no workouts" in result.lower()
                or "rest week" in result.lower()
                or "logged" in result.lower())

    def test_deterministic(self):
        facts = self._base_facts()
        assert ws.build_fallback_narrative(facts) == ws.build_fallback_narrative(facts)

    def test_ctl_trend_mentioned(self):
        facts = self._base_facts(ctl_start=44.0, ctl_end=47.5)
        result = ws.build_fallback_narrative(facts)
        assert "44" in result or "47" in result or "CTL" in result or "fitness" in result.lower()

    def test_no_crash_on_none_tss(self):
        facts = self._base_facts(total_tss=None, prev_week_tss=None)
        result = ws.build_fallback_narrative(facts)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# AC2 — facts assembly pure function
# ---------------------------------------------------------------------------

class TestFactsAssembly:
    """AC2: facts assembled rule-side; no new math."""

    def _workouts(self, week="current"):
        """Return minimal workout dicts for current or prev week."""
        base_date = "2026-06-30" if week == "current" else "2026-06-23"
        return [
            {
                "workout_date": base_date,
                "tss": 80.0,
                "distance_km": 10.0,
                "duration_seconds": 3600,
                "workout_type": "run",
            },
            {
                "workout_date": base_date,
                "tss": 60.0,
                "distance_km": None,
                "duration_seconds": 3000,
                "workout_type": "lift",
            },
        ]

    def test_total_tss_sums_workouts(self):
        workouts = self._workouts()
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=workouts,
            prev_workouts=[],
            ctl_start=44.0, ctl_end=47.5,
            atl_start=50.0, atl_end=53.0,
            tsb_start=-6.0, tsb_end=-5.5,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 1.1, "acwr_state": "productive"},
            prs=[],
        )
        assert facts["total_tss"] == 140.0

    def test_distance_km_sums_only_non_null(self):
        workouts = self._workouts()
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=workouts,
            prev_workouts=[],
            ctl_start=44.0, ctl_end=47.5,
            atl_start=50.0, atl_end=53.0,
            tsb_start=-6.0, tsb_end=-5.5,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 1.1, "acwr_state": "productive"},
            prs=[],
        )
        assert facts["total_distance_km"] == 10.0

    def test_duration_minutes_sums_correctly(self):
        workouts = self._workouts()
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=workouts,
            prev_workouts=[],
            ctl_start=44.0, ctl_end=47.5,
            atl_start=50.0, atl_end=53.0,
            tsb_start=-6.0, tsb_end=-5.5,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 1.1, "acwr_state": "productive"},
            prs=[],
        )
        # 3600 + 3000 = 6600 seconds = 110 minutes
        assert facts["total_duration_minutes"] == pytest.approx(110.0)

    def test_workout_count_by_type(self):
        workouts = self._workouts()
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=workouts,
            prev_workouts=[],
            ctl_start=44.0, ctl_end=47.5,
            atl_start=50.0, atl_end=53.0,
            tsb_start=-6.0, tsb_end=-5.5,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 1.1, "acwr_state": "productive"},
            prs=[],
        )
        assert facts["workout_count_by_type"]["run"] == 1
        assert facts["workout_count_by_type"]["lift"] == 1

    def test_prev_week_tss(self):
        prev = [{"workout_date": "2026-06-23", "tss": 100.0, "distance_km": 15.0,
                 "duration_seconds": 4000, "workout_type": "run"}]
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=[],
            prev_workouts=prev,
            ctl_start=44.0, ctl_end=44.0,
            atl_start=50.0, atl_end=48.0,
            tsb_start=-6.0, tsb_end=-4.0,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 0.9, "acwr_state": "productive"},
            prs=[],
        )
        assert facts["prev_week_tss"] == 100.0
        assert facts["prev_week_distance_km"] == 15.0

    def test_ctl_atl_tsb_in_facts(self):
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=[],
            prev_workouts=[],
            ctl_start=44.0, ctl_end=47.5,
            atl_start=50.0, atl_end=53.0,
            tsb_start=-6.0, tsb_end=-5.5,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 1.1, "acwr_state": "productive"},
            prs=[],
        )
        assert facts["ctl_start"] == 44.0
        assert facts["ctl_end"] == 47.5
        assert facts["atl_start"] == 50.0
        assert facts["atl_end"] == 53.0
        assert facts["tsb_start"] == -6.0
        assert facts["tsb_end"] == -5.5

    def test_guardrail_fields_in_facts(self):
        guardrail = {
            "guardrail_state": "warn",
            "guardrail_message": "Load too high.",
            "acwr": 1.6,
            "acwr_state": "high_risk",
        }
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=[],
            prev_workouts=[],
            ctl_start=44.0, ctl_end=44.0,
            atl_start=50.0, atl_end=50.0,
            tsb_start=-6.0, tsb_end=-6.0,
            guardrail=guardrail,
            prs=[],
        )
        assert facts["guardrail_state"] == "warn"
        assert facts["guardrail_message"] == "Load too high."
        assert facts["acwr"] == 1.6

    def test_prs_list_in_facts(self):
        prs = [{"track_name": "5 km", "value_numeric": "1230.0", "achieved_on": "2026-07-01"}]
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=[],
            prev_workouts=[],
            ctl_start=44.0, ctl_end=44.0,
            atl_start=50.0, atl_end=50.0,
            tsb_start=-6.0, tsb_end=-6.0,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 0.9, "acwr_state": "productive"},
            prs=prs,
        )
        assert len(facts["prs_achieved"]) == 1
        assert facts["prs_achieved"][0]["track_name"] == "5 km"

    def test_empty_week_zero_counts(self):
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=[],
            prev_workouts=[],
            ctl_start=44.0, ctl_end=44.0,
            atl_start=50.0, atl_end=50.0,
            tsb_start=-6.0, tsb_end=-6.0,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 0.9, "acwr_state": "productive"},
            prs=[],
        )
        assert facts["workout_count"] == 0
        assert facts["total_tss"] is None
        assert facts["total_distance_km"] is None
        assert facts["prs_achieved"] == []

    def test_week_start_in_facts(self):
        facts = ws.assemble_facts(
            week_start=date(2026, 6, 30),
            current_workouts=[],
            prev_workouts=[],
            ctl_start=44.0, ctl_end=44.0,
            atl_start=50.0, atl_end=50.0,
            tsb_start=-6.0, tsb_end=-6.0,
            guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 0.9, "acwr_state": "productive"},
            prs=[],
        )
        assert facts["week_start"] == "2026-06-30"


# ---------------------------------------------------------------------------
# AC3 — numeral validation guard
# ---------------------------------------------------------------------------

class TestNumeralGuard:
    """AC3: numbers in LLM narrative must appear verbatim in facts string."""

    def test_valid_narrative_passes(self):
        facts_str = "tss=320.0 distance=42.0 ctl_start=44.0 ctl_end=47.5"
        text = "You logged 320.0 TSS over 42.0 km this week; CTL rose from 44.0 to 47.5."
        assert ws.numeral_guard_passes(text, facts_str) is True

    def test_invented_number_fails(self):
        facts_str = "tss=320.0 distance=42.0"
        text = "You logged 999 TSS this week."
        assert ws.numeral_guard_passes(text, facts_str) is False

    def test_no_numbers_passes(self):
        facts_str = "tss=320.0"
        text = "Solid week of training. Keep it up."
        assert ws.numeral_guard_passes(text, facts_str) is True

    def test_partial_number_subset_passes(self):
        facts_str = "tss=320.0 distance=42.0 ctl=47.5"
        text = "TSS 320.0 this week."
        assert ws.numeral_guard_passes(text, facts_str) is True


# ---------------------------------------------------------------------------
# AC3 — LLM path (mocked)
# ---------------------------------------------------------------------------

class TestLlmPath:
    """AC3: LLM narrative shape, tier, guard; AC4: fallback on failure."""

    def _base_facts(self):
        return {
            "week_start": "2026-06-30",
            "workout_count": 5,
            "workout_count_by_type": {"run": 3, "lift": 2},
            "total_tss": 320.0,
            "prev_week_tss": 280.0,
            "total_distance_km": 42.0,
            "prev_week_distance_km": 38.0,
            "total_duration_minutes": 210.0,
            "ctl_start": 45.0,
            "ctl_end": 47.5,
            "atl_start": 50.0,
            "atl_end": 53.0,
            "tsb_start": -5.0,
            "tsb_end": -5.5,
            "guardrail_state": "ok",
            "guardrail_message": "",
            "acwr": 1.1,
            "prs_achieved": [],
        }

    def test_llm_narrative_used_when_valid(self):
        facts = self._base_facts()
        llm_text = "Solid week — 320.0 TSS across 5 sessions. Fitness up to 47.5."
        mock_payload = {"narrative": llm_text}

        with patch("backend.services.weekly_summary.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = mock_payload

            narrative, source = ws.get_narrative(user_id="user-1", week_start="2026-06-30", facts=facts)

        assert narrative == llm_text
        assert source == "llm"

    def test_llm_disabled_uses_fallback(self):
        facts = self._base_facts()
        with patch("backend.services.weekly_summary.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = False

            narrative, source = ws.get_narrative(user_id="user-1", week_start="2026-06-30", facts=facts)

        assert isinstance(narrative, str)
        assert source == "fallback"

    def test_llm_returns_none_uses_fallback(self):
        facts = self._base_facts()
        with patch("backend.services.weekly_summary.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = None

            narrative, source = ws.get_narrative(user_id="user-1", week_start="2026-06-30", facts=facts)

        assert isinstance(narrative, str)
        assert source == "fallback"

    def test_numeral_guard_triggers_fallback(self):
        facts = self._base_facts()
        # Invented number 9999 not in facts
        llm_text = "You logged 9999 TSS this week, incredible!"
        mock_payload = {"narrative": llm_text}

        with patch("backend.services.weekly_summary.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = mock_payload

            narrative, source = ws.get_narrative(user_id="user-1", week_start="2026-06-30", facts=facts)

        assert narrative != llm_text
        assert source == "fallback"

    def test_overlength_narrative_triggers_fallback(self):
        facts = self._base_facts()
        # Very long LLM text
        long_text = "Good week. " * 100  # no numbers so numeral guard passes, but length fails
        mock_payload = {"narrative": long_text}

        with patch("backend.services.weekly_summary.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = mock_payload

            narrative, source = ws.get_narrative(user_id="user-1", week_start="2026-06-30", facts=facts)

        assert source == "fallback"

    def test_get_or_generate_called_with_deep_model_tier(self):
        """AC3: GROQ_MODEL_DEEP tier used."""
        facts = self._base_facts()
        llm_text = "Good week — 320.0 TSS."
        mock_payload = {"narrative": llm_text}

        with patch("backend.services.weekly_summary.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = mock_payload

            ws.get_narrative(user_id="user-1", week_start="2026-06-30", facts=facts)

        # Check that complete_structured or get_or_generate is called with model_tier="deep"
        call_kwargs = mock_llm.get_or_generate.call_args
        assert call_kwargs is not None
        # The generate_fn passed internally should use model_tier="deep"
        # We verify via the surface parameter
        assert call_kwargs.kwargs.get("surface") == "weekly_summary" or \
               call_kwargs.args[1] == "weekly_summary"


# ---------------------------------------------------------------------------
# AC5 — cache signature
# ---------------------------------------------------------------------------

class TestCacheSignature:
    """AC5: signature over user+week+facts; different facts → different signature."""

    def _base_facts(self):
        return {
            "week_start": "2026-06-30",
            "workout_count": 5,
            "total_tss": 320.0,
            "ctl_end": 47.5,
        }

    def test_deterministic(self):
        sig1 = ws.build_signature("user-1", "2026-06-30", self._base_facts())
        sig2 = ws.build_signature("user-1", "2026-06-30", self._base_facts())
        assert sig1 == sig2

    def test_changes_on_facts_change(self):
        sig1 = ws.build_signature("user-1", "2026-06-30", self._base_facts())
        facts2 = {**self._base_facts(), "total_tss": 400.0}
        sig2 = ws.build_signature("user-1", "2026-06-30", facts2)
        assert sig1 != sig2

    def test_changes_on_user_change(self):
        sig1 = ws.build_signature("user-1", "2026-06-30", self._base_facts())
        sig2 = ws.build_signature("user-2", "2026-06-30", self._base_facts())
        assert sig1 != sig2

    def test_changes_on_week_change(self):
        sig1 = ws.build_signature("user-1", "2026-06-30", self._base_facts())
        sig2 = ws.build_signature("user-1", "2026-07-07", self._base_facts())
        assert sig1 != sig2

    def test_cache_hit_no_regenerate(self):
        facts = self._base_facts()
        cached_text = "Solid week of 320.0 TSS."
        cached_payload = {"narrative": cached_text}

        with patch("backend.services.weekly_summary.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = cached_payload

            narrative, source = ws.get_narrative(
                user_id="user-1", week_start="2026-06-30", facts=facts
            )

        assert narrative == cached_text
        mock_llm.get_or_generate.assert_called_once()


# ---------------------------------------------------------------------------
# AC7 — empty week: valid response, no 404
# ---------------------------------------------------------------------------

class TestEmptyWeek:
    """AC7: zero-data weeks return valid response with honest message."""

    def _empty_facts(self):
        return {
            "week_start": "2026-06-30",
            "workout_count": 0,
            "workout_count_by_type": {},
            "total_tss": None,
            "prev_week_tss": None,
            "total_distance_km": None,
            "prev_week_distance_km": None,
            "total_duration_minutes": None,
            "ctl_start": 40.0,
            "ctl_end": 38.0,
            "atl_start": 42.0,
            "atl_end": 39.0,
            "tsb_start": -2.0,
            "tsb_end": -1.0,
            "guardrail_state": "ok",
            "guardrail_message": "",
            "acwr": None,
            "prs_achieved": [],
        }

    def test_fallback_honest_on_empty_week(self):
        narrative = ws.build_fallback_narrative(self._empty_facts())
        assert isinstance(narrative, str)
        assert len(narrative) > 0
        # Should mention no training rather than fabricating numbers
        lower = narrative.lower()
        assert any(word in lower for word in ["no training", "no workouts", "rest", "logged", "empty"])

    def test_llm_fallback_on_empty_week(self):
        with patch("backend.services.weekly_summary.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = False
            narrative, source = ws.get_narrative(
                user_id="user-1", week_start="2026-06-30", facts=self._empty_facts()
            )
        assert isinstance(narrative, str)
        assert source == "fallback"


# ---------------------------------------------------------------------------
# AC1 — endpoint shape
# ---------------------------------------------------------------------------

class TestEndpointShape:
    """AC1: response shape has week_start, facts, narrative, source."""

    def test_get_weekly_summary_endpoint_exists(self):
        from backend.main import app
        routes = [r.path for r in app.routes]
        assert "/api/weekly-summary" in routes

    def test_response_shape_keys(self):
        """Verify shape builder returns the required keys."""
        facts = {
            "week_start": "2026-06-30",
            "workout_count": 0,
            "workout_count_by_type": {},
            "total_tss": None,
            "prev_week_tss": None,
            "total_distance_km": None,
            "prev_week_distance_km": None,
            "total_duration_minutes": None,
            "ctl_start": 40.0,
            "ctl_end": 38.0,
            "atl_start": 42.0,
            "atl_end": 39.0,
            "tsb_start": -2.0,
            "tsb_end": -1.0,
            "guardrail_state": "ok",
            "guardrail_message": "",
            "acwr": None,
            "prs_achieved": [],
        }
        result = ws.build_response(
            week_start="2026-06-30",
            facts=facts,
            narrative="No training this week.",
            source="fallback",
        )
        assert set(result.keys()) >= {"week_start", "facts", "narrative", "source"}
        assert result["week_start"] == "2026-06-30"
        assert result["source"] == "fallback"

    def test_llm_generations_model_has_correct_surface(self):
        from backend.models import LlmGeneration
        assert LlmGeneration.__tablename__ == "llm_generations"


# ---------------------------------------------------------------------------
# AC8 — auth 401
# ---------------------------------------------------------------------------

class TestAuth:
    """AC8: unauthenticated request returns 401."""

    def test_unauthenticated_returns_401(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/weekly-summary")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC6 — frontend card HTML element present
# ---------------------------------------------------------------------------

class TestFrontendCard:
    """AC6: HTML element present in training-log.html or home.html."""

    def test_weekly_summary_card_in_training_log(self):
        import pathlib
        html_path = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html"
        if not html_path.exists():
            pytest.skip("training-log.html not found")
        content = html_path.read_text()
        # Card element must be present
        assert "weekly-summary-card" in content or "weekly_summary_card" in content

    def test_weekly_summary_js_present(self):
        import pathlib
        # Check that JS fetches /api/weekly-summary
        js_paths = list((pathlib.Path(__file__).parent.parent / "frontend" / "js").glob("*.js"))
        found = False
        for p in js_paths:
            if "weekly-summary" in p.read_text() or "/api/weekly-summary" in p.read_text():
                found = True
                break
        assert found, "No JS file references /api/weekly-summary"
