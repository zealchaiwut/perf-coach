"""Tests for issue #1319 — _emit_startup_info() must be called at module import time.

AC: calling `_emit_startup_info()` once at module import time (bottom of llm.py)
so the startup INFO log fires on application start.
"""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch


class TestEmitStartupInfoCalled:
    """_emit_startup_info() must be invoked at module level so the log fires on import."""

    def _reload_llm(self, env: dict):
        """Force a fresh import of llm.py with the given env and return the module."""
        to_remove = [k for k in sys.modules if k.startswith("backend.services.llm")]
        for k in to_remove:
            del sys.modules[k]
        with patch.dict(os.environ, env, clear=False):
            mod = importlib.import_module("backend.services.llm")
        return mod

    def test_startup_logged_is_true_after_import(self):
        """After import, _startup_logged must be True — proves _emit_startup_info() was called."""
        env = {
            "LLM_COACH_ENABLED": "",
            "GROQ_API_KEY": "",
            "GLM_API_KEY": "",
        }
        mod = self._reload_llm(env)
        assert mod._startup_logged is True, (
            "_startup_logged is False after import — _emit_startup_info() was not called at module level"
        )

    def test_second_call_is_no_op(self):
        """_emit_startup_info() must be idempotent — second call must not log again."""
        import backend.services.llm as llm
        llm._startup_logged = True
        with patch.object(llm._log, "info") as mock_info:
            llm._emit_startup_info()
            mock_info.assert_not_called()

    def test_disabled_logs_info(self):
        """When LLM_COACH_ENABLED is not set, startup log fires with 'disabled' message."""
        import backend.services.llm as llm
        llm._startup_logged = False
        env = os.environ.copy()
        env.pop("LLM_COACH_ENABLED", None)
        env.pop("GROQ_API_KEY", None)
        env.pop("GLM_API_KEY", None)
        with patch.dict(os.environ, env, clear=True), \
             patch.object(llm._log, "info") as mock_info:
            os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
            os.environ.setdefault("ENVIRONMENT", "local")
            os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
            os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
            llm._emit_startup_info()
        mock_info.assert_called_once()
        msg = mock_info.call_args[0][0]
        assert "disabled" in msg.lower()

    def test_enabled_but_no_key_logs_info(self):
        """When enabled but no API key, startup log fires with 'no API key' message."""
        import backend.services.llm as llm
        llm._startup_logged = False
        env = os.environ.copy()
        env["LLM_COACH_ENABLED"] = "true"
        env.pop("GROQ_API_KEY", None)
        env.pop("GLM_API_KEY", None)
        with patch.dict(os.environ, env, clear=True), \
             patch.object(llm._log, "info") as mock_info:
            os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
            os.environ.setdefault("ENVIRONMENT", "local")
            os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
            os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
            llm._emit_startup_info()
        mock_info.assert_called_once()
        msg = mock_info.call_args[0][0]
        assert "no api key" in msg.lower() or "unavailable" in msg.lower()
