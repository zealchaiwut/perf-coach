"""Orch smoke: LLM mocked accept / retry→fallback / LLM off."""

from __future__ import annotations

from unittest.mock import patch

from backend.services.coach_brief import compose_coach_brief
from backend.services.coach_narrative import (
    atoms_from_brief,
    generate_narrative,
)


def _facts():
    from tests.test_coach_narrative_validate__sections import _base_facts
    from backend.services.coach_facts import collect_required_numerals

    facts = _base_facts()
    facts["required_numerals"] = collect_required_numerals(facts)
    facts["as_of"] = "2026-07-18"
    return facts


def _good_atoms(facts):
    return atoms_from_brief(compose_coach_brief(facts))


def test_generate_fallback_when_llm_off(monkeypatch):
    monkeypatch.setenv("COACH_ORCH", "plain")
    with patch(
        "backend.services.coach_narrative.call_llm_brief_atoms",
        return_value=None,
    ):
        result = generate_narrative(_facts(), max_attempts=2)
    assert result["source"] == "fallback"
    assert "## Now" in result["text"]
    assert result["sections"]["now"]
    assert result.get("brief", {}).get("schema_version") == 4


def test_generate_accepts_valid_llm(monkeypatch):
    monkeypatch.setenv("COACH_ORCH", "plain")
    monkeypatch.setenv("COACH_LLM", "api")
    facts = _facts()
    good = _good_atoms(facts)
    with patch(
        "backend.services.coach_narrative.call_llm_brief_atoms",
        return_value=good,
    ) as mock_call:
        result = generate_narrative(facts, max_attempts=3)
    assert result["source"] in ("llm", "claude_cli")
    assert mock_call.call_count == 1
    assert result["attempts"] == 1
    assert result["brief"]["schema_version"] == 4


def test_generate_retries_then_fallback(monkeypatch):
    monkeypatch.setenv("COACH_ORCH", "plain")
    facts = _facts()
    bad = {
        "today_verdict": "Invented 77777 TSS which is not allowed.",
        "week_verdict": "Bad week verdict with 77777.",
        "week_verdict_sub": "Still citing 77777 wrongly.",
        "sections": [
            {
                "id": "load_deload",
                "headline": "Nope",
                "evidence": "Totally fake 77777 TSS number here.",
                "do": "Do nothing with 77777.",
            }
        ],
    }
    with patch(
        "backend.services.coach_narrative.call_llm_brief_atoms",
        return_value=bad,
    ) as mock_call:
        result = generate_narrative(facts, max_attempts=2)
    assert result["source"] == "fallback"
    assert mock_call.call_count == 2


def test_langgraph_orch_fallback_path(monkeypatch):
    monkeypatch.setenv("COACH_ORCH", "langgraph")
    facts = _facts()
    with patch(
        "backend.services.coach_narrative.call_llm_brief_atoms",
        return_value=None,
    ):
        from backend.services.coach_orch_langgraph import run_brief
        from backend.services.coach_brief import build_brief_skeleton

        skel = build_brief_skeleton(facts)
        result = run_brief(facts, skel, max_attempts=2)
    assert result["source"] == "fallback"
    assert result["orch"] == "langgraph"
    assert result["brief"]["schema_version"] == 4
