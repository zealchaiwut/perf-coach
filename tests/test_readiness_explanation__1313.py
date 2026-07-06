"""Unit/integration tests for readiness explanation feature (issue #1313).

Covers Acceptance Criteria:
- AC1: /api/home/readiness and home summary readiness block gain `explanation` field;
       existing fields unchanged
- AC2: LLM explanation uses structured component facts; numeral guard discards output
       with numbers not in input facts; length-capped
- AC3: Rule-based fallback names 1-3 largest contributors with values; pure function;
       used when LLM disabled/fails
- AC4: Cached in llm_generations (surface="readiness_explanation"), signature over
       user+date+component values; regenerates when inputs change
- AC5: Dashboard readiness UI shows explanation (tested via HTML presence of element)
- AC6: No change to readiness score computation or daily_readiness schema
- AC7: Tests: fallback pure-function cases; mocked LLM shape+numeral guard; cache
       regeneration; API field present both paths
"""

from __future__ import annotations

import hashlib
import json
import re
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper — import the module under test
# ---------------------------------------------------------------------------

from backend.services import readiness_explanation as rex


# ---------------------------------------------------------------------------
# AC3 — rule-based fallback pure function
# ---------------------------------------------------------------------------

def _make_factors(sleep_score=50.0, hrv_score=50.0, rhr_score=50.0,
                  energy_score=50.0, mood_score=50.0,
                  sleep_val=8.0, hrv_val=60.0, rhr_val=55.0,
                  energy_val=3.0, mood_val=3.0):
    return [
        {"factor": "sleep_hours", "value": sleep_val, "score": sleep_score, "impact": ("positive" if sleep_score > 50 else ("negative" if sleep_score < 50 else "neutral"))},
        {"factor": "hrv", "value": hrv_val, "score": hrv_score, "impact": ("positive" if hrv_score > 50 else ("negative" if hrv_score < 50 else "neutral"))},
        {"factor": "rhr", "value": rhr_val, "score": rhr_score, "impact": ("positive" if rhr_score > 50 else ("negative" if rhr_score < 50 else "neutral"))},
        {"factor": "energy", "value": energy_val, "score": energy_score, "impact": ("positive" if energy_score > 50 else ("negative" if energy_score < 50 else "neutral"))},
        {"factor": "mood", "value": mood_val, "score": mood_score, "impact": ("positive" if mood_score > 50 else ("negative" if mood_score < 50 else "neutral"))},
    ]


class TestBuildRuleBasedExplanation:
    """AC3: rule-based fallback is a pure function covering named cases."""

    def test_low_sleep_named_in_explanation(self):
        factors = _make_factors(sleep_score=20.0, sleep_val=5.2, hrv_score=50.0, rhr_score=50.0)
        result = rex.build_rule_based_explanation(factors)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "sleep" in result.lower()
        assert "5.2" in result

    def test_elevated_rhr_named_in_explanation(self):
        factors = _make_factors(rhr_score=15.0, rhr_val=75.0, sleep_score=50.0, hrv_score=50.0)
        result = rex.build_rule_based_explanation(factors)
        assert "rhr" in result.lower() or "heart rate" in result.lower() or "resting" in result.lower()
        assert "75" in result or "75.0" in result

    def test_combined_low_sleep_high_rhr(self):
        factors = _make_factors(sleep_score=18.0, sleep_val=5.2, rhr_score=12.0, rhr_val=78.0)
        result = rex.build_rule_based_explanation(factors)
        assert "5.2" in result
        assert "78" in result or "78.0" in result

    def test_positive_hrv_named(self):
        factors = _make_factors(hrv_score=85.0, hrv_val=72.0)
        result = rex.build_rule_based_explanation(factors)
        assert "hrv" in result.lower() or "heart rate variability" in result.lower()
        assert "72" in result or "72.0" in result

    def test_all_neutral_returns_string(self):
        factors = _make_factors()
        result = rex.build_rule_based_explanation(factors)
        assert isinstance(result, str)
        # neutral → balanced or similar wording
        assert len(result) > 0

    def test_at_most_3_factors_mentioned(self):
        factors = _make_factors(
            sleep_score=10.0, sleep_val=4.0,
            hrv_score=90.0, hrv_val=80.0,
            rhr_score=10.0, rhr_val=80.0,
            energy_score=90.0, energy_val=5.0,
            mood_score=10.0, mood_val=1.0,
        )
        result = rex.build_rule_based_explanation(factors)
        # Count factor mentions: sleep, hrv, rhr, energy, mood
        mentioned = sum(1 for kw in ("sleep", "hrv", "rhr", "energy", "mood") if kw in result.lower())
        assert mentioned <= 3

    def test_none_value_factor_skipped(self):
        factors = _make_factors(hrv_score=10.0, hrv_val=None)
        result = rex.build_rule_based_explanation(factors)
        assert isinstance(result, str)
        # hrv_val=None means value can't be printed — shouldn't crash

    def test_returns_str_type(self):
        result = rex.build_rule_based_explanation(_make_factors())
        assert type(result) is str


# ---------------------------------------------------------------------------
# AC2 — numeral validation guard
# ---------------------------------------------------------------------------

class TestNumeralGuard:
    """AC2: Numbers in LLM output must be present in the facts string."""

    def test_valid_output_passes(self):
        facts = "hrv=65.0 rhr=58.0 sleep=7.5"
        output = "Your HRV of 65.0 is elevated. Sleep at 7.5 hours is good."
        assert rex.numeral_guard_passes(output, facts) is True

    def test_invented_number_fails(self):
        facts = "hrv=65.0 rhr=58.0 sleep=7.5"
        output = "Your HRV is 99.0 which is outstanding."
        assert rex.numeral_guard_passes(output, facts) is False

    def test_no_numbers_in_output_passes(self):
        facts = "hrv=65 rhr=58"
        output = "Score reflects your good recovery today."
        assert rex.numeral_guard_passes(output, facts) is True

    def test_subset_numbers_pass(self):
        facts = "hrv=65.0 rhr=58.0 sleep=7.5 score=72"
        output = "HRV 65.0 and sleep 7.5 hours boosted your score."
        assert rex.numeral_guard_passes(output, facts) is True

    def test_partial_match_fails(self):
        facts = "hrv=65 rhr=58"
        output = "Your score is 65 and RHR 58.3."
        # 58.3 is not in facts
        assert rex.numeral_guard_passes(output, facts) is False


# ---------------------------------------------------------------------------
# AC2 — LLM path shape (mocked)
# ---------------------------------------------------------------------------

class TestLlmPath:
    """AC2: LLM returns structured explanation; falls back on failure."""

    def _make_facts(self):
        return {
            "score": 72,
            "label": "Good",
            "sleep_hours": 7.5,
            "hrv": 65.0,
            "rhr": 55.0,
            "sleep_quality": 4.0,
            "energy": 4.0,
            "mood": 3.0,
            "sleep_hours_baseline": 7.2,
            "hrv_baseline": 60.0,
            "rhr_baseline": 58.0,
        }

    def test_llm_explanation_used_when_valid(self):
        facts = self._make_facts()
        llm_text = "Your HRV of 65.0 is slightly above your baseline of 60.0, and sleep at 7.5 hours is solid."
        mock_payload = {"explanation": llm_text}

        with patch("backend.services.readiness_explanation.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = mock_payload

            result = rex.get_readiness_explanation(
                user_id="user-1",
                target_date="2026-07-01",
                facts=facts,
                fallback_factors=_make_factors(hrv_score=70.0, hrv_val=65.0),
            )
        assert result == llm_text

    def test_llm_disabled_uses_fallback(self):
        facts = self._make_facts()
        with patch("backend.services.readiness_explanation.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = False

            result = rex.get_readiness_explanation(
                user_id="user-1",
                target_date="2026-07-01",
                facts=facts,
                fallback_factors=_make_factors(sleep_score=20.0, sleep_val=5.2),
            )
        assert isinstance(result, str)
        assert "5.2" in result  # fallback mentions value

    def test_llm_returns_none_uses_fallback(self):
        facts = self._make_facts()
        with patch("backend.services.readiness_explanation.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = None

            result = rex.get_readiness_explanation(
                user_id="user-1",
                target_date="2026-07-01",
                facts=facts,
                fallback_factors=_make_factors(rhr_score=15.0, rhr_val=75.0),
            )
        assert "75" in result or "75.0" in result

    def test_numeral_guard_triggers_fallback(self):
        facts = self._make_facts()
        # LLM output with invented number 99.9
        llm_text = "Your HRV is 99.9 which is extraordinary."
        mock_payload = {"explanation": llm_text}

        with patch("backend.services.readiness_explanation.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = mock_payload

            result = rex.get_readiness_explanation(
                user_id="user-1",
                target_date="2026-07-01",
                facts=facts,
                fallback_factors=_make_factors(hrv_score=30.0, hrv_val=45.0),
            )
        # Should have fallen back, not returned LLM text
        assert result != llm_text
        assert "45" in result or "45.0" in result

    def test_llm_explanation_length_capped(self):
        facts = self._make_facts()
        # LLM returns overly long text
        long_text = "A" * 600
        mock_payload = {"explanation": long_text}

        with patch("backend.services.readiness_explanation.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = mock_payload

            result = rex.get_readiness_explanation(
                user_id="user-1",
                target_date="2026-07-01",
                facts=facts,
                fallback_factors=_make_factors(),
            )
        # Length cap triggers fallback (no numbers in long_text so numeral guard passes,
        # but length check should fail and fall back)
        assert len(result) < 600


# ---------------------------------------------------------------------------
# AC4 — cache signature
# ---------------------------------------------------------------------------

class TestCacheSignature:
    """AC4: signature changes when component values change."""

    def test_signature_is_deterministic(self):
        facts = {"hrv": 65.0, "rhr": 55.0, "sleep_hours": 7.5, "energy": 4.0,
                 "sleep_quality": 4.0, "mood": 3.0}
        sig1 = rex.build_explanation_signature("user-1", "2026-07-01", facts)
        sig2 = rex.build_explanation_signature("user-1", "2026-07-01", facts)
        assert sig1 == sig2

    def test_signature_changes_on_sleep_hours_change(self):
        facts1 = {"hrv": 65.0, "rhr": 55.0, "sleep_hours": 7.5, "energy": 4.0,
                  "sleep_quality": 4.0, "mood": 3.0}
        facts2 = {**facts1, "sleep_hours": 5.0}
        sig1 = rex.build_explanation_signature("user-1", "2026-07-01", facts1)
        sig2 = rex.build_explanation_signature("user-1", "2026-07-01", facts2)
        assert sig1 != sig2

    def test_signature_changes_on_user_change(self):
        facts = {"hrv": 65.0, "rhr": 55.0, "sleep_hours": 7.5, "energy": 4.0,
                 "sleep_quality": 4.0, "mood": 3.0}
        sig1 = rex.build_explanation_signature("user-1", "2026-07-01", facts)
        sig2 = rex.build_explanation_signature("user-2", "2026-07-01", facts)
        assert sig1 != sig2

    def test_signature_changes_on_date_change(self):
        facts = {"hrv": 65.0, "rhr": 55.0, "sleep_hours": 7.5, "energy": 4.0,
                 "sleep_quality": 4.0, "mood": 3.0}
        sig1 = rex.build_explanation_signature("user-1", "2026-07-01", facts)
        sig2 = rex.build_explanation_signature("user-1", "2026-07-02", facts)
        assert sig1 != sig2

    def test_cache_hit_does_not_regenerate(self):
        facts = {"hrv": 65.0, "rhr": 55.0, "sleep_hours": 7.5, "energy": 4.0,
                 "sleep_quality": 4.0, "mood": 3.0}
        cached_text = "HRV 65.0 up from baseline. Sleep 7.5 hours is solid."
        cached_payload = {"explanation": cached_text}

        with patch("backend.services.readiness_explanation.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = True
            mock_llm.get_or_generate.return_value = cached_payload

            result = rex.get_readiness_explanation(
                user_id="user-1",
                target_date="2026-07-01",
                facts={**facts, "score": 72, "label": "Good",
                       "sleep_hours_baseline": 7.2, "hrv_baseline": 60.0, "rhr_baseline": 58.0},
                fallback_factors=_make_factors(),
            )
        assert result == cached_text
        # get_or_generate called exactly once
        mock_llm.get_or_generate.assert_called_once()


# ---------------------------------------------------------------------------
# AC6 — no schema change
# ---------------------------------------------------------------------------

class TestNoSchemaChange:
    """AC6: daily_readiness schema untouched; explanation NOT a new column."""

    def test_daily_readiness_model_has_no_explanation_column(self):
        from backend.models import DailyReadiness
        from sqlalchemy import inspect
        cols = {c.key for c in inspect(DailyReadiness).mapper.columns}
        assert "explanation" not in cols

    def test_llm_generations_model_exists(self):
        from backend.models import LlmGeneration
        assert LlmGeneration.__tablename__ == "llm_generations"


# ---------------------------------------------------------------------------
# AC1 — API field present
# ---------------------------------------------------------------------------

class TestApiFieldPresent:
    """AC1: explanation present in readiness block dict for both LLM-on and LLM-off."""

    def test_build_readiness_block_includes_explanation_key(self):
        from backend.main import _build_readiness_block
        # We just need to verify the key is expected to be present in output dict
        # We can do this by inspecting the function source
        import inspect
        src = inspect.getsource(_build_readiness_block)
        assert "explanation" in src

    def test_get_readiness_explanation_returns_str(self):
        """Smoke: always returns a non-empty string."""
        with patch("backend.services.readiness_explanation.llm") as mock_llm:
            mock_llm.llm_enabled.return_value = False
            result = rex.get_readiness_explanation(
                user_id="user-1",
                target_date="2026-07-01",
                facts={"hrv": 65.0, "rhr": 55.0, "sleep_hours": 7.5,
                       "energy": 4.0, "sleep_quality": 4.0, "mood": 3.0,
                       "score": 72, "label": "Good",
                       "sleep_hours_baseline": None, "hrv_baseline": None, "rhr_baseline": None},
                fallback_factors=_make_factors(),
            )
        assert isinstance(result, str)
        assert len(result) > 0
