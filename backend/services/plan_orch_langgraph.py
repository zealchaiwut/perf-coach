"""LangGraph orchestration for plan suggestions (PLAN_ORCH=langgraph).

The retry loop is expressed as a state graph: generate → validate, with a
conditional edge back to generate on rejection (the cycle), or on to accept /
fallback. Same domain primitives as plan_suggestions.py — only the control flow
differs. Importing this module imports langgraph; the caller
(plan_suggestions._orch_langgraph) wraps that import in try/except so a missing
dependency degrades to the deterministic template rather than erroring.

Exposes run(facts, max_attempts) -> {suggestions, source, attempts, orch}.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import StateGraph, END

from backend.services.plan_suggestions import (
    _call_llm,
    _feedback_block,
    fallback_suggestions,
    validation_errors,
)
from backend.utils.log import get_logger

_log = get_logger(__name__)


class PlanState(TypedDict):
    facts: dict
    max_attempts: int
    suggestions: list
    errors: list
    attempts: int
    source: str
    llm_available: bool


def _generate(state: PlanState) -> dict:
    feedback = _feedback_block(state["errors"]) if state["errors"] else ""
    raw = _call_llm(state["facts"], feedback)
    if raw is None:
        _log.warning("plan(langgraph) attempt %d: LLM call failed/unavailable", state["attempts"] + 1)
        return {"llm_available": False, "attempts": state["attempts"] + 1}
    return {
        "suggestions": raw.get("suggestions", []),
        "attempts": state["attempts"] + 1,
        "llm_available": True,
    }


def _validate(state: PlanState) -> dict:
    return {"errors": validation_errors(state["suggestions"], state["facts"])}


def _accept(state: PlanState) -> dict:
    return {"source": "llm"}


def _use_fallback(state: PlanState) -> dict:
    return {"suggestions": fallback_suggestions(state["facts"]), "source": "fallback"}


def _route_after_generate(state: PlanState) -> str:
    if state["llm_available"]:
        return "validate"
    # An unparseable/failed call (network blip, or Groq's strict-mode
    # validator rejecting a single generation that dropped a required-but-
    # nullable key) is a transient generation slip, not proof the LLM is
    # down — retry like any other rejection, don't give up on attempt 1.
    if state["attempts"] >= state["max_attempts"]:
        return "fallback"
    return "generate"


def _route_after_validate(state: PlanState) -> str:
    if not state["errors"]:
        return "accept"
    if state["attempts"] >= state["max_attempts"]:
        return "fallback"
    _log.warning("plan(langgraph) retry %d rejected: %s", state["attempts"], state["errors"])
    return "generate"  # the cycle


def _build_app():
    g = StateGraph(PlanState)
    g.add_node("generate", _generate)
    g.add_node("validate", _validate)
    g.add_node("accept", _accept)
    g.add_node("fallback", _use_fallback)
    g.set_entry_point("generate")
    g.add_conditional_edges("generate", _route_after_generate,
                            {"validate": "validate", "fallback": "fallback", "generate": "generate"})
    g.add_conditional_edges("validate", _route_after_validate,
                            {"accept": "accept", "generate": "generate", "fallback": "fallback"})
    g.add_edge("accept", END)
    g.add_edge("fallback", END)
    return g.compile()


# Compiled once at import; the graph shape is static.
_APP = _build_app()


def run(facts: dict, max_attempts: int) -> dict:
    final = _APP.invoke({
        "facts": facts, "max_attempts": max_attempts,
        "suggestions": [], "errors": [], "attempts": 0,
        "source": "", "llm_available": True,
    })
    # attempts counts generate calls made — including retries on a failed/
    # unparseable call (see _route_after_generate), so this honestly reports
    # how many times the LLM was actually asked, same as the plain orchestrator.
    return {
        "suggestions": final["suggestions"],
        "source": final["source"],
        "attempts": final["attempts"],
        "orch": "langgraph",
    }
