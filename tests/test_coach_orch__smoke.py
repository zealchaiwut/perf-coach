"""Orch smoke: LLM mocked accept / retry→fallback / LLM off."""

from __future__ import annotations

from unittest.mock import patch

from backend.services.coach_narrative import (
    compose_coach_narrative,
    generate_narrative,
    parse_sections_from_text,
)


def _facts():
    from tests.test_coach_narrative_validate__sections import _base_facts
    from backend.services.coach_facts import collect_required_numerals

    facts = _base_facts()
    facts["required_numerals"] = collect_required_numerals(facts)
    return facts


def test_generate_fallback_when_llm_off(monkeypatch):
    monkeypatch.setenv("COACH_ORCH", "plain")
    with patch(
        "backend.services.coach_narrative.call_llm_sections",
        return_value=None,
    ):
        result = generate_narrative(_facts(), max_attempts=2)
    assert result["source"] == "fallback"
    assert "## Now" in result["text"]
    assert result["sections"]["now"]


def test_generate_accepts_valid_llm(monkeypatch):
    monkeypatch.setenv("COACH_ORCH", "plain")
    monkeypatch.setenv("COACH_LLM", "api")
    facts = _facts()
    good = parse_sections_from_text(compose_coach_narrative(facts))
    with patch(
        "backend.services.coach_narrative.call_llm_sections",
        return_value=good,
    ) as mock_call:
        result = generate_narrative(facts, max_attempts=3)
    assert result["source"] in ("llm", "claude_cli")
    assert mock_call.call_count == 1
    assert result["attempts"] == 1


def test_generate_retries_then_fallback(monkeypatch):
    monkeypatch.setenv("COACH_ORCH", "plain")
    facts = _facts()
    bad = {
        "now": "Invented 77777 TSS for padding the now section length here.",
        "focus": "Focus section needs enough characters to pass min length.",
        "dream": "Dream section needs enough characters to pass min length.",
        "reflection": "Reflection needs enough characters to pass min length.",
    }
    with patch(
        "backend.services.coach_narrative.call_llm_sections",
        return_value=bad,
    ) as mock_call:
        result = generate_narrative(facts, max_attempts=2)
    assert result["source"] == "fallback"
    assert mock_call.call_count == 2


def test_langgraph_orch_fallback_path(monkeypatch):
    monkeypatch.setenv("COACH_ORCH", "langgraph")
    facts = _facts()
    with patch(
        "backend.services.coach_narrative.call_llm_sections",
        return_value=None,
    ):
        from backend.services.coach_orch_langgraph import run

        result = run(facts, max_attempts=2)
    assert result["source"] == "fallback"
    assert result["orch"] == "langgraph"
    assert "## Focus" in result["text"]
