"""LangGraph coach brief orchestrator (v4 atoms).

Graph: generate → validate → (retry with feedback | accept | fallback).
Legacy ``run()`` still produces four-section Markdown for older callers.
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


class CoachBriefState(TypedDict, total=False):
    facts: dict
    skeleton: dict
    atoms: dict
    brief: dict
    errors: list
    attempt: int
    max_attempts: int
    source: str
    chosen_preset_code: str | None


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
    from backend.services.coach_narrative import SECTION_ORDER, validation_errors

    sections = dict(state.get("sections") or {})
    prose = {k: sections.get(k) for k in SECTION_ORDER}
    if not any(prose.values()):
        return {"errors": ["empty sections"], "source": "pending"}
    errs = validation_errors(prose, state["facts"])
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
    """Legacy: generate→validate→retry|accept|fallback → Markdown narrative."""
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


# ── Brief v4 atom graph ──────────────────────────────────────────────────────


def _brief_generate(state: CoachBriefState) -> dict:
    from backend.services.coach_narrative import call_llm_brief_atoms, feedback_block

    attempt = int(state.get("attempt") or 0) + 1
    errors = list(state.get("errors") or [])
    fb = feedback_block(errors) if errors else ""
    atoms = call_llm_brief_atoms(state["facts"], state["skeleton"], fb)
    return {
        "attempt": attempt,
        "atoms": atoms or {},
        "source": "llm" if atoms else "pending",
    }


def _brief_validate(state: CoachBriefState) -> dict:
    from backend.services.coach_narrative import validation_errors_brief

    atoms = dict(state.get("atoms") or {})
    if not atoms.get("today_verdict") and not atoms.get("sections"):
        return {"errors": ["empty atoms"], "source": "pending"}
    errs = validation_errors_brief(atoms, state["facts"], state.get("skeleton"))
    return {"errors": errs}


def _brief_accept(state: CoachBriefState) -> dict:
    from backend.services.coach_brief import merge_llm_atoms
    from backend.services.coach_narrative import _source_label

    atoms = dict(state.get("atoms") or {})
    code = atoms.pop("chosen_preset_code", None)
    brief = merge_llm_atoms(state["skeleton"], atoms, state.get("facts"))
    source = _source_label()
    brief["source"] = source
    return {
        "brief": brief,
        "source": source,
        "chosen_preset_code": code,
        "errors": [],
    }


def _brief_fallback(state: CoachBriefState) -> dict:
    from backend.services.coach_brief import compose_coach_brief

    brief = compose_coach_brief(state["facts"])
    return {
        "brief": brief,
        "source": "fallback",
        "chosen_preset_code": None,
        "errors": [],
    }


def _brief_route(state: CoachBriefState) -> str:
    errors = state.get("errors") or []
    if not errors:
        return "accept"
    attempt = int(state.get("attempt") or 0)
    max_attempts = int(state.get("max_attempts") or 3)
    if attempt < max_attempts:
        return "retry"
    return "fallback"


def run_brief(facts: dict, skeleton: dict, max_attempts: int = 3) -> dict[str, Any]:
    """Atom generate→validate→retry|accept|fallback → v4 brief JSON."""
    from langgraph.graph import END, StateGraph

    g = StateGraph(CoachBriefState)
    g.add_node("generate", _brief_generate)
    g.add_node("validate", _brief_validate)
    g.add_node("accept", _brief_accept)
    g.add_node("fallback", _brief_fallback)

    g.set_entry_point("generate")
    g.add_edge("generate", "validate")
    g.add_conditional_edges(
        "validate",
        _brief_route,
        {
            "accept": "accept",
            "retry": "generate",
            "fallback": "fallback",
        },
    )
    g.add_edge("accept", END)
    g.add_edge("fallback", END)

    app = g.compile()
    init: CoachBriefState = {
        "facts": facts,
        "skeleton": skeleton,
        "attempt": 0,
        "max_attempts": max_attempts,
        "errors": [],
        "atoms": {},
    }
    final = app.invoke(init)
    return {
        "brief": final.get("brief") or {},
        "source": final.get("source") or "fallback",
        "attempts": int(final.get("attempt") or 0),
        "chosen_preset_code": final.get("chosen_preset_code"),
        "orch": "langgraph",
    }
