"""Pydantic AI orchestration for plan suggestions (PLAN_ORCH=pydantic_ai).

The output is a typed Pydantic model, so the schema-level rules (ranges, enum,
≤7 sessions) are enforced by the type itself; the domain rule (ACWR ceiling)
lives in an output_validator that raises ModelRetry — that raise IS the loop,
re-prompting is handled by the framework (retries=N).

Unlike the plain/langgraph paths, this talks to Groq through pydantic-ai's own
OpenAI-compatible client rather than backend.services.llm — that different call
path is part of what's being compared. It still honours the same off-by-default
contract: run() checks llm_enabled() first and returns the template when the LLM
is disabled, and the caller (plan_suggestions._orch_pydantic_ai) falls back on
any exception (retries exhausted, provider error, missing dependency).

API targets pydantic-ai-slim 2.x (OpenAIChatModel / output_type /
@output_validator). Pin the version; the surface has moved across releases.

Exposes run(facts, max_attempts) -> {suggestions, source, attempts, orch}.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from backend.services.llm import llm_enabled
from backend.services.plan_suggestions import (
    _feedback_block,
    build_prompt,
    fallback_suggestions,
    validation_errors,
)
from backend.utils.log import get_logger

_log = get_logger(__name__)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_DEFAULT_MODEL_DEEP = "openai/gpt-oss-120b"

# Agent is built lazily (needs GROQ_API_KEY) and cached per (model, retries).
_agent_cache: dict = {}


class Session(BaseModel):
    day_offset: int = Field(ge=0, le=6)
    workout_type: Literal["run", "strength", "plyo", "rest"]
    target_tss: int = Field(ge=0, le=400)
    duration_minutes: int = Field(ge=0, le=360)
    intent: str = Field(max_length=200)


class PlanWeek(BaseModel):
    suggestions: list[Session] = Field(max_length=7)


def _build_agent(max_attempts: int) -> Agent:
    model_name = os.getenv("GROQ_MODEL_DEEP", _DEFAULT_MODEL_DEEP)
    key = (model_name, max_attempts)
    if key in _agent_cache:
        return _agent_cache[key]

    model = OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=_GROQ_BASE_URL, api_key=os.getenv("GROQ_API_KEY", "")),
    )
    agent = Agent(model, output_type=PlanWeek, deps_type=dict, retries=max_attempts)

    @agent.system_prompt
    def _system(ctx: RunContext[dict]) -> str:
        system, _ = build_prompt(ctx.deps)  # deps == facts
        return system

    @agent.output_validator
    def _check(ctx: RunContext[dict], output: PlanWeek) -> PlanWeek:
        errs = validation_errors([s.model_dump() for s in output.suggestions], ctx.deps)
        if errs:
            _log.warning("plan(pydantic_ai) output rejected: %s", errs)
            raise ModelRetry(_feedback_block(errs))  # framework re-prompts
        return output

    _agent_cache[key] = agent
    return agent


def _count_attempts(result) -> int:
    """Best-effort model-request count (retries hidden by the framework)."""
    try:
        msgs = result.all_messages()
        return sum(1 for m in msgs if type(m).__name__ == "ModelResponse") or 1
    except Exception:
        return 1


def run(facts: dict, max_attempts: int) -> dict:
    if not llm_enabled():
        return {
            "suggestions": fallback_suggestions(facts),
            "source": "fallback",
            "attempts": 0,
            "orch": "pydantic_ai",
        }
    _, user = build_prompt(facts)
    agent = _build_agent(max_attempts)
    result = agent.run_sync(user, deps=facts)
    return {
        "suggestions": [s.model_dump() for s in result.output.suggestions],
        "source": "llm",
        "attempts": _count_attempts(result),
        "orch": "pydantic_ai",
    }
