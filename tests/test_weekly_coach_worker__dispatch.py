"""Weekly coach job is registered on the compute worker, not the webapp."""

from __future__ import annotations


def test_weekly_coach_in_worker_dispatch():
    from backend import worker_app

    assert "weekly_coach" in worker_app._DISPATCH
    assert callable(worker_app._DISPATCH["weekly_coach"])


def test_coach_llm_defaults_off_on_webapp(monkeypatch):
    monkeypatch.delenv("COACH_LLM", raising=False)
    monkeypatch.delenv("PERFCOACH_ROLE", raising=False)
    from backend.services.coach_narrative import coach_llm_mode

    assert coach_llm_mode() == "off"


def test_coach_llm_defaults_claude_on_worker(monkeypatch):
    monkeypatch.delenv("COACH_LLM", raising=False)
    monkeypatch.setenv("PERFCOACH_ROLE", "worker")
    from backend.services.coach_narrative import coach_llm_mode

    assert coach_llm_mode() == "claude_cli"
