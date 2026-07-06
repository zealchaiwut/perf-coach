"""Unit tests for backend/services/llm.py (issue #1311).

Covers Acceptance Criteria:
- AC1: llm_enabled() and complete_structured() exist with correct signatures
- AC2: httpx POST to Groq with correct payload/timeout; no SDK dependency
- AC3: env config vars (GROQ_API_KEY, LLM_COACH_ENABLED, GROQ_MODEL_FAST, GROQ_MODEL_DEEP)
- AC4: fail-safe — HTTP 500, timeout, malformed JSON, disabled → None; no raises
- AC5: LlmGeneration model exists in backend.models
- AC6: get_or_generate — cache hit skips HTTP; stores on success; None on generation failure
- AC7: disabled or missing key → zero warnings spam (no exception at import)
- AC8: mocked httpx success/failure cases; migration model importable
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# AC7: module imports without error even when key absent
# ---------------------------------------------------------------------------


class TestModuleImport:
    def test_import_succeeds_without_env(self):
        """llm.py must import cleanly with no env vars set."""
        import backend.services.llm as llm  # noqa: F401
        assert llm is not None

    def test_llm_enabled_false_when_unset(self):
        from backend.services.llm import llm_enabled
        env = {"LLM_COACH_ENABLED": "", "GROQ_API_KEY": ""}
        with patch.dict(os.environ, env, clear=False):
            # remove keys entirely
            env2 = os.environ.copy()
            env2.pop("LLM_COACH_ENABLED", None)
            env2.pop("GROQ_API_KEY", None)
            with patch.dict(os.environ, env2, clear=True):
                os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
                os.environ.setdefault("ENVIRONMENT", "local")
                os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
                os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
                assert llm_enabled() is False


# ---------------------------------------------------------------------------
# AC3: env config
# ---------------------------------------------------------------------------


class TestEnvConfig:
    def test_llm_enabled_true_with_key(self):
        from backend.services.llm import llm_enabled
        with patch.dict(os.environ, {"LLM_COACH_ENABLED": "true", "GROQ_API_KEY": "gsk_test"}):
            assert llm_enabled() is True

    def test_llm_enabled_false_when_flag_missing(self):
        from backend.services.llm import llm_enabled
        env = os.environ.copy()
        env.pop("LLM_COACH_ENABLED", None)
        env["GROQ_API_KEY"] = "gsk_test"
        with patch.dict(os.environ, env, clear=True):
            os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
            os.environ.setdefault("ENVIRONMENT", "local")
            os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
            os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
            assert llm_enabled() is False

    def test_llm_enabled_false_when_key_absent(self):
        from backend.services.llm import llm_enabled
        env = os.environ.copy()
        env.pop("GROQ_API_KEY", None)
        env["LLM_COACH_ENABLED"] = "true"
        with patch.dict(os.environ, env, clear=True):
            os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
            os.environ.setdefault("ENVIRONMENT", "local")
            os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
            os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
            assert llm_enabled() is False

    def test_model_fast_default(self):
        from backend.services.llm import _model
        env = os.environ.copy()
        env.pop("GROQ_MODEL_FAST", None)
        with patch.dict(os.environ, env, clear=True):
            os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
            os.environ.setdefault("ENVIRONMENT", "local")
            os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
            os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
            assert _model("fast") == "llama-3.1-8b-instant"

    def test_model_deep_default(self):
        from backend.services.llm import _model
        env = os.environ.copy()
        env.pop("GROQ_MODEL_DEEP", None)
        with patch.dict(os.environ, env, clear=True):
            os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
            os.environ.setdefault("ENVIRONMENT", "local")
            os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
            os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
            assert _model("deep") == "openai/gpt-oss-120b"

    def test_model_fast_override(self):
        from backend.services.llm import _model
        with patch.dict(os.environ, {"GROQ_MODEL_FAST": "llama-custom"}):
            assert _model("fast") == "llama-custom"

    def test_model_deep_override(self):
        from backend.services.llm import _model
        with patch.dict(os.environ, {"GROQ_MODEL_DEEP": "deepseek-r1"}):
            assert _model("deep") == "deepseek-r1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA = {"type": "object", "properties": {"score": {"type": "number"}}, "required": ["score"]}
_SUCCESS_PAYLOAD = {"score": 9.5}


def _make_groq_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _make_enabled_env() -> dict:
    return {"LLM_COACH_ENABLED": "true", "GROQ_API_KEY": "gsk_test_key"}


# ---------------------------------------------------------------------------
# AC4 + AC8: disabled flag → None, no HTTP call
# ---------------------------------------------------------------------------


class TestDisabledFail:
    def test_disabled_flag_returns_none(self):
        from backend.services.llm import complete_structured
        env = os.environ.copy()
        env.pop("LLM_COACH_ENABLED", None)
        env.pop("GROQ_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
            os.environ.setdefault("ENVIRONMENT", "local")
            os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
            os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
            result = complete_structured("sys", "usr", "test_schema", _SCHEMA)
            assert result is None

    def test_disabled_makes_no_http_call(self):
        from backend.services.llm import complete_structured
        env = os.environ.copy()
        env.pop("LLM_COACH_ENABLED", None)
        env.pop("GROQ_API_KEY", None)
        with patch.dict(os.environ, env, clear=True), \
             patch("httpx.post") as mock_post:
            os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
            os.environ.setdefault("ENVIRONMENT", "local")
            os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
            os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
            complete_structured("sys", "usr", "test_schema", _SCHEMA)
            mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# AC2 + AC8: success path
# ---------------------------------------------------------------------------


class TestSuccessPath:
    def test_success_returns_parsed_dict(self):
        from backend.services.llm import complete_structured
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=_make_groq_response(_SUCCESS_PAYLOAD)):
            result = complete_structured("sys", "usr", "my_schema", _SCHEMA)
            assert result == _SUCCESS_PAYLOAD

    def test_success_posts_to_groq_url(self):
        from backend.services.llm import complete_structured, _GROQ_URL
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=_make_groq_response(_SUCCESS_PAYLOAD)) as mock_post:
            complete_structured("sys", "usr", "my_schema", _SCHEMA)
            call_args = mock_post.call_args
            assert call_args[0][0] == _GROQ_URL

    def test_success_includes_json_schema_response_format(self):
        from backend.services.llm import complete_structured
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=_make_groq_response(_SUCCESS_PAYLOAD)) as mock_post:
            complete_structured("sys", "usr", "my_schema", _SCHEMA)
            body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            rf = body["response_format"]
            assert rf["type"] == "json_schema"
            assert rf["json_schema"]["name"] == "my_schema"
            assert rf["json_schema"]["strict"] is True
            assert rf["json_schema"]["schema"] == _SCHEMA

    def test_success_uses_bearer_auth(self):
        from backend.services.llm import complete_structured
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=_make_groq_response(_SUCCESS_PAYLOAD)) as mock_post:
            complete_structured("sys", "usr", "my_schema", _SCHEMA)
            headers = mock_post.call_args.kwargs.get("headers") or mock_post.call_args[1].get("headers")
            assert headers.get("Authorization") == "Bearer gsk_test_key"

    def test_success_timeout_set(self):
        import httpx as _httpx
        from backend.services.llm import complete_structured
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=_make_groq_response(_SUCCESS_PAYLOAD)) as mock_post:
            complete_structured("sys", "usr", "my_schema", _SCHEMA)
            timeout = mock_post.call_args.kwargs.get("timeout") or mock_post.call_args[1].get("timeout")
            assert timeout is not None
            if isinstance(timeout, _httpx.Timeout):
                assert timeout.read == 60.0
                assert timeout.connect == 10.0
            else:
                assert timeout == 60.0 or (hasattr(timeout, "total") and timeout.total == 60.0)

    def test_fast_tier_uses_fast_model(self):
        from backend.services.llm import complete_structured
        with patch.dict(os.environ, {**_make_enabled_env(), "GROQ_MODEL_FAST": "llama-fast"}), \
             patch("httpx.post", return_value=_make_groq_response(_SUCCESS_PAYLOAD)) as mock_post:
            complete_structured("sys", "usr", "my_schema", _SCHEMA, model_tier="fast")
            body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert body["model"] == "llama-fast"

    def test_deep_tier_uses_deep_model(self):
        from backend.services.llm import complete_structured
        with patch.dict(os.environ, {**_make_enabled_env(), "GROQ_MODEL_DEEP": "deepseek-r2"}), \
             patch("httpx.post", return_value=_make_groq_response(_SUCCESS_PAYLOAD)) as mock_post:
            complete_structured("sys", "usr", "my_schema", _SCHEMA, model_tier="deep")
            body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert body["model"] == "deepseek-r2"


# ---------------------------------------------------------------------------
# AC4 + AC8: HTTP errors → None
# ---------------------------------------------------------------------------


class TestHttpErrorFail:
    def test_http_500_returns_none(self):
        import httpx as _httpx
        from backend.services.llm import complete_structured

        resp = MagicMock()
        resp.status_code = 500
        resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "500", request=MagicMock(), response=resp
        )
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=resp):
            result = complete_structured("sys", "usr", "my_schema", _SCHEMA)
            assert result is None

    def test_http_500_does_not_raise(self):
        import httpx as _httpx
        from backend.services.llm import complete_structured

        resp = MagicMock()
        resp.status_code = 500
        resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "500", request=MagicMock(), response=resp
        )
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=resp):
            try:
                complete_structured("sys", "usr", "my_schema", _SCHEMA)
            except Exception as exc:
                raise AssertionError(f"complete_structured raised: {exc}") from exc


# ---------------------------------------------------------------------------
# AC4 + AC8: timeout → None
# ---------------------------------------------------------------------------


class TestTimeoutFail:
    def test_timeout_returns_none(self):
        import httpx as _httpx
        from backend.services.llm import complete_structured
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", side_effect=_httpx.TimeoutException("timed out")):
            result = complete_structured("sys", "usr", "my_schema", _SCHEMA)
            assert result is None

    def test_timeout_does_not_raise(self):
        import httpx as _httpx
        from backend.services.llm import complete_structured
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", side_effect=_httpx.TimeoutException("timed out")):
            try:
                complete_structured("sys", "usr", "my_schema", _SCHEMA)
            except Exception as exc:
                raise AssertionError(f"complete_structured raised: {exc}") from exc


# ---------------------------------------------------------------------------
# AC4 + AC8: malformed JSON → None
# ---------------------------------------------------------------------------


class TestMalformedJsonFail:
    def test_malformed_json_returns_none(self):
        from backend.services.llm import complete_structured
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "not valid json {"}}]
        }
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=resp):
            result = complete_structured("sys", "usr", "my_schema", _SCHEMA)
            assert result is None

    def test_malformed_json_does_not_raise(self):
        from backend.services.llm import complete_structured
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "not valid json {"}}]
        }
        with patch.dict(os.environ, _make_enabled_env()), \
             patch("httpx.post", return_value=resp):
            try:
                complete_structured("sys", "usr", "my_schema", _SCHEMA)
            except Exception as exc:
                raise AssertionError(f"complete_structured raised: {exc}") from exc


# ---------------------------------------------------------------------------
# AC5: LlmGeneration model exists in backend.models
# ---------------------------------------------------------------------------


class TestLlmGenerationModel:
    def test_model_importable(self):
        from backend.models import LlmGeneration
        assert LlmGeneration is not None

    def test_model_has_required_columns(self):
        from backend.models import LlmGeneration
        cols = {c.name for c in LlmGeneration.__table__.columns}
        assert "id" in cols
        assert "user_id" in cols
        assert "surface" in cols
        assert "input_signature" in cols
        assert "payload" in cols
        assert "model" in cols
        assert "created_at" in cols

    def test_model_has_unique_constraint(self):
        from backend.models import LlmGeneration
        constraints = LlmGeneration.__table__.constraints
        unique_cols_sets = []
        for c in constraints:
            from sqlalchemy import UniqueConstraint
            if isinstance(c, UniqueConstraint):
                unique_cols_sets.append({col.name for col in c.columns})
        assert {"user_id", "surface", "input_signature"} in unique_cols_sets


# ---------------------------------------------------------------------------
# AC6: get_or_generate cache helper
# ---------------------------------------------------------------------------


class TestGetOrGenerate:
    def _make_db(self, cached_row=None):
        """Return a minimal mock db session."""
        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter_by.return_value = query
        query.first.return_value = cached_row
        return db

    def test_cache_hit_returns_payload_without_http(self):
        from backend.services.llm import get_or_generate
        cached = MagicMock()
        cached.payload = {"score": 8.0}
        db = self._make_db(cached_row=cached)

        generate_fn = MagicMock()
        result = get_or_generate("user-1", "habit_insights", "sig-abc", generate_fn, db=db)
        assert result == {"score": 8.0}
        generate_fn.assert_not_called()

    def test_cache_miss_calls_generate_fn(self):
        from backend.services.llm import get_or_generate
        db = self._make_db(cached_row=None)

        generate_fn = MagicMock(return_value={"score": 7.5})
        result = get_or_generate("user-1", "habit_insights", "sig-abc", generate_fn, db=db)
        assert result == {"score": 7.5}
        generate_fn.assert_called_once()

    def test_cache_miss_stores_on_success(self):
        from backend.services.llm import get_or_generate
        db = self._make_db(cached_row=None)

        generate_fn = MagicMock(return_value={"score": 7.5})
        get_or_generate("user-1", "habit_insights", "sig-abc", generate_fn, db=db)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_cache_miss_generate_none_returns_none(self):
        from backend.services.llm import get_or_generate
        db = self._make_db(cached_row=None)

        generate_fn = MagicMock(return_value=None)
        result = get_or_generate("user-1", "habit_insights", "sig-abc", generate_fn, db=db)
        assert result is None
        db.add.assert_not_called()

    def test_cache_miss_generate_exception_returns_none(self):
        from backend.services.llm import get_or_generate
        db = self._make_db(cached_row=None)

        generate_fn = MagicMock(side_effect=RuntimeError("boom"))
        result = get_or_generate("user-1", "habit_insights", "sig-abc", generate_fn, db=db)
        assert result is None

    def test_get_or_generate_no_db_import_raises(self):
        """When db=None and no real DB, must not crash on import."""
        from backend.services.llm import get_or_generate
        assert get_or_generate is not None


# ---------------------------------------------------------------------------
# AC2: no SDK import (httpx only — no openai package imported by llm.py)
# ---------------------------------------------------------------------------


class TestNoSdkDependency:
    def test_llm_module_does_not_import_openai(self):
        import backend.services.llm as llm_mod
        source = open(llm_mod.__file__).read()
        assert "import openai" not in source
        assert "from openai" not in source
