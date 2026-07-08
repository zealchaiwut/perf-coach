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
    return "validate" if state["llm_available"] else "fallback"


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
                            {"validate": "validate", "fallback": "fallback"})
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
    # attempts counts generate calls; on a clean LLM-off exit that is 1, which
    # over-reports "0 real attempts" — normalise the disabled case to 0.
    attempts = final["attempts"]
    if final["source"] == "fallback" and not final.get("llm_available", True):
        attempts = max(0, attempts - 1)
    return {
        "suggestions": final["suggestions"],
        "source": final["source"],
        "attempts": attempts,
        "orch": "langgraph",
    }
