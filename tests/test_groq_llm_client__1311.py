"""Tests for issue #1311: Groq LLM client service (runs against UAT)"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock


# --- Acceptance Criteria ---

def test_groq_llm_client__service_module_exports():
    # AC1: backend/services/llm.py exposes llm_enabled() and complete_structured()
    from backend.services.llm import llm_enabled, complete_structured

    # Functions exist and are callable
    assert callable(llm_enabled)
    assert callable(complete_structured)


def test_groq_llm_client__llm_enabled_false_by_default():
    # AC6: With LLM_COACH_ENABLED unset/false, llm_enabled() returns False
    with patch.dict(os.environ, {"LLM_COACH_ENABLED": "false", "GROQ_API_KEY": ""}, clear=False):
        from backend.services import llm
        # Force re-import to get fresh module state
        import importlib
        importlib.reload(llm)
        assert llm.llm_enabled() is False


def test_groq_llm_client__llm_enabled_requires_both_flags_and_key():
    # AC3, AC4: llm_enabled() returns True only if BOTH LLM_COACH_ENABLED=true AND GROQ_API_KEY set
    with patch.dict(os.environ, {"LLM_COACH_ENABLED": "true", "GROQ_API_KEY": "test_key"}):
        from backend.services import llm
        import importlib
        importlib.reload(llm)
        assert llm.llm_enabled() is True

    # Missing key → False
    with patch.dict(os.environ, {"LLM_COACH_ENABLED": "true", "GROQ_API_KEY": ""}, clear=False):
        from backend.services import llm
        import importlib
        importlib.reload(llm)
        assert llm.llm_enabled() is False


def test_groq_llm_client__complete_structured_returns_none_when_disabled():
    # AC4: complete_structured() returns None when llm_enabled() is False (fail-safe)
    with patch.dict(os.environ, {"LLM_COACH_ENABLED": "false"}, clear=False):
        from backend.services.llm import complete_structured
        result = complete_structured("sys", "user", "schema", {})
        assert result is None


def test_groq_llm_client__complete_structured_returns_none_on_http_error():
    # AC4b: HTTP error (e.g. 500) → returns None, never raises
    with patch.dict(os.environ, {"LLM_COACH_ENABLED": "true", "GROQ_API_KEY": "test_key"}):
        with patch("httpx.post") as mock_post:
            from backend.services.llm import complete_structured
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("HTTP 500")
            mock_post.return_value = mock_response

            result = complete_structured("sys", "user", "schema", {})
            assert result is None


def test_groq_llm_client__complete_structured_returns_none_on_timeout():
    # AC4c: Timeout → returns None, never raises
    import httpx
    with patch.dict(os.environ, {"LLM_COACH_ENABLED": "true", "GROQ_API_KEY": "test_key"}):
        with patch("httpx.post") as mock_post:
            from backend.services.llm import complete_structured
            mock_post.side_effect = httpx.TimeoutException("timeout")

            result = complete_structured("sys", "user", "schema", {})
            assert result is None


def test_groq_llm_client__complete_structured_success_path():
    # AC2: complete_structured() parses JSON response on success
    with patch.dict(os.environ, {"LLM_COACH_ENABLED": "true", "GROQ_API_KEY": "test_key"}):
        with patch("httpx.post") as mock_post:
            from backend.services.llm import complete_structured

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": '{"key": "value"}'}}]
            }
            mock_post.return_value = mock_response

            result = complete_structured("sys", "user", "schema", {})
            assert result == {"key": "value"}


def test_groq_llm_client__model_defaults():
    # AC3: GROQ_MODEL_FAST defaults to llama-3.1-8b-instant, GROQ_MODEL_DEEP to openai/gpt-oss-120b
    # Test without those vars set (so defaults are used)
    env_dict = dict(os.environ)
    env_dict.pop("GROQ_MODEL_FAST", None)
    env_dict.pop("GROQ_MODEL_DEEP", None)
    with patch.dict(os.environ, env_dict, clear=True):
        from backend.services import llm
        # Access internal _model() function
        assert "llama-3.1-8b-instant" in llm._model("fast")
        assert "gpt-oss" in llm._model("deep")


def test_groq_llm_client__cache_get_or_generate_exists():
    # AC5: get_or_generate() function exists and is callable
    from backend.services.llm import get_or_generate
    assert callable(get_or_generate)


def test_groq_llm_client__llm_generation_model_exists():
    # AC5: LlmGeneration model exists with correct schema
    from backend.models import LlmGeneration

    # Check required columns
    assert hasattr(LlmGeneration, "id")
    assert hasattr(LlmGeneration, "user_id")
    assert hasattr(LlmGeneration, "surface")
    assert hasattr(LlmGeneration, "input_signature")
    assert hasattr(LlmGeneration, "payload")
    assert hasattr(LlmGeneration, "model")
    assert hasattr(LlmGeneration, "created_at")
