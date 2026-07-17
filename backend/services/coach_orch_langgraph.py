"""LangGraph coach narrative orchestrator.

Graph: generate → validate → (retry with feedback | accept | fallback).
Mirrors plan_orch_langgraph.py — same llm.complete_structured stack.
"""

from __future__ import annotations

from typing import Any, TypedDict

from backend.utils.log import get_logger

_log = get_logger(__name__)


class CoachOrchState(TypedDict, total=False):
    facts: dict
    sections: dict
    errors: list
    attempt: int
    max_attempts: int
    source: str
    text: str


def _node_generate(state: CoachOrchState) -> dict:
    from backend.services.coach_narrative import call_llm_sections, feedback_block

    attempt = int(state.get("attempt") or 0) + 1
    errors = list(state.get("errors") or [])
    fb = feedback_block(errors) if errors else ""
    sections = call_llm_sections(state["facts"], fb)
    return {
        "attempt": attempt,
        "sections": sections or {},
        "source": "llm" if sections else "pending",
    }


def _node_validate(state: CoachOrchState) -> dict:
    from backend.services.coach_narrative import validation_errors

    sections = state.get("sections") or {}
    if not sections or not any(sections.values()):
        return {"errors": ["empty sections"], "source": "pending"}
    errs = validation_errors(sections, state["facts"])
    return {"errors": errs}


def _node_fallback(state: CoachOrchState) -> dict:
    from backend.services.coach_narrative import (
        compose_coach_narrative,
        parse_sections_from_text,
    )

    text = compose_coach_narrative(state["facts"])
    return {
        "text": text,
        "sections": parse_sections_from_text(text),
        "source": "fallback",
        "errors": [],
    }


def _node_accept(state: CoachOrchState) -> dict:
    from backend.services.coach_narrative import sections_to_text, _source_label

    sections = state.get("sections") or {}
    return {
        "text": sections_to_text(sections),
        "sections": sections,
        "source": _source_label(),
        "errors": [],
    }


def _route_after_validate(state: CoachOrchState) -> str:
    errors = state.get("errors") or []
    if not errors:
        return "accept"
    attempt = int(state.get("attempt") or 0)
    max_attempts = int(state.get("max_attempts") or 3)
    if attempt < max_attempts:
        return "retry"
    return "fallback"


def run(facts: dict, max_attempts: int = 3) -> dict[str, Any]:
    """Execute generate→validate→retry|accept|fallback. Returns narrative result."""
    from langgraph.graph import END, StateGraph

    g = StateGraph(CoachOrchState)
    g.add_node("generate", _node_generate)
    g.add_node("validate", _node_validate)
    g.add_node("accept", _node_accept)
    g.add_node("fallback", _node_fallback)

    g.set_entry_point("generate")
    g.add_edge("generate", "validate")
    g.add_conditional_edges(
        "validate",
        _route_after_validate,
        {
            "accept": "accept",
            "retry": "generate",
            "fallback": "fallback",
        },
    )
    g.add_edge("accept", END)
    g.add_edge("fallback", END)

    app = g.compile()
    init: CoachOrchState = {
        "facts": facts,
        "attempt": 0,
        "max_attempts": max_attempts,
        "errors": [],
        "sections": {},
    }
    final = app.invoke(init)
    return {
        "text": final.get("text") or "",
        "sections": final.get("sections") or {},
        "source": final.get("source") or "fallback",
        "attempts": int(final.get("attempt") or 0),
        "orch": "langgraph",
    }
