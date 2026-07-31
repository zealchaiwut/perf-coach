"""Priority 2 guard: the compute worker makes no LLM calls.

D4 parks the in-app coach LLM and D1 parks worker drafts, leaving exactly one
LLM call in perf-coach — Ask-AI single session, interactive, in the webapp. The
worker's job is syncs, backfills, Banister refit, precompute, and a
deterministic daily message.

That is easy to state and easy to regress: one convenience import of
``backend.services.llm`` in any module the worker's daily_coach path touches
puts a provider client back on zeal-server. This file is the tripwire.

The check is a RUNTIME one — import ``backend.worker_app`` in a clean
interpreter and look at ``sys.modules`` — rather than a static AST walk, because
this codebase deliberately uses function-local imports to keep heavy or
optional dependencies out of a module's load path. A static walk cannot tell a
function-local import (never loaded unless called) from a module-level one
(always loaded), so it would either false-positive on the former or miss the
latter. What actually matters is what ends up loaded, and sys.modules is that.

Mirrors the older single-file guard in test_coach_plan__build_state.py
(test_no_llm_imports), widened from one module to a whole import graph.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Modules whose presence means an LLM client is reachable from the worker.
# The parked cluster is listed alongside the client itself: those modules exist
# only to make LLM calls, so importing one is the same failure a step earlier.
FORBIDDEN_MODULES = {
    "backend.services.llm",
    "backend.services.coach_narrative",
    "backend.services.coach_claude_cli",
    "backend.services.coach_orch_langgraph",
    "backend.services.plan_draft",
    "backend.services.plan_slot_cache",
}

# Third-party clients. Nothing in perf-coach should pull these onto the worker.
FORBIDDEN_ROOTS = {
    "anthropic",
    "openai",
    "langchain",
    "langgraph",
    "litellm",
    "groq",
}


def _loaded_modules(import_target: str) -> set[str]:
    """Import `import_target` in a fresh interpreter, return its sys.modules."""
    script = textwrap.dedent(
        f"""
        import sys, json
        import {import_target}  # noqa: F401
        print(json.dumps(sorted(sys.modules)))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        pytest.fail(f"importing {import_target} failed:\n{proc.stderr[-3000:]}")
    import json

    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


@pytest.fixture(scope="module")
def worker_modules() -> set[str]:
    return _loaded_modules("backend.worker_app")


def test_worker_does_not_load_an_llm_client(worker_modules):
    """The whole point of D4: zero LLM on the worker."""
    hits = sorted(worker_modules & FORBIDDEN_MODULES)
    assert not hits, (
        "importing backend.worker_app pulled in LLM module(s): "
        + ", ".join(hits)
        + ". The worker must stay deterministic — move the import inside the "
        "function that needs it, or drop the dependency."
    )


def test_worker_does_not_load_a_third_party_llm_sdk(worker_modules):
    hits = sorted(m for m in worker_modules if m.split(".")[0] in FORBIDDEN_ROOTS)
    assert not hits, f"worker loaded third-party LLM SDK(s): {hits}"


def test_plan_draft_is_not_a_dispatchable_job():
    """Parking drafts means removing the handler, not just leaving the
    scheduler quiet. plan_draft was the single edge that made llm,
    plan_slot_cache and the whole parked coach cluster reachable from the
    worker — the dispatch entry was the door, so the door is what closed."""
    import backend.worker_app as w

    assert "plan_draft" not in w._DISPATCH, (
        "plan_draft is back in the worker dispatch table; it re-opens the "
        "import path plan_draft -> plan_slot_cache -> plan_suggestions -> llm."
    )


def test_draft_notify_still_answers_with_pipeline_off():
    """Hermes polls this on a schedule. Parked must mean 'nothing today', not
    an outage — a 404 would read as the worker being down."""
    import backend.worker_app as w

    out = w.plan_draft_notify()
    assert out["pipeline_off"] is True
    assert out["deliver_now"] is False
    assert out["ready"] is False


def test_deterministic_brief_builder_exists_and_is_llm_free():
    """The brief still gets built — just without the narrative LLM."""
    from backend.services import coach_brief

    assert callable(coach_brief.build_brief_deterministic)

    modules = _loaded_modules("backend.services.coach_brief")
    hits = sorted(modules & FORBIDDEN_MODULES)
    assert not hits, f"coach_brief pulled in {hits}"


def test_weekly_coach_message_has_no_warmth_rephrase():
    """The LLM 'add warmth, preserve every number' layer is gone. It was the
    last LLM call on the daily message path."""
    import backend.services.weekly_coach_message as wcm

    assert not hasattr(wcm, "_call_llm_narrative"), (
        "the warmth-rephrase layer is back on the daily coach message"
    )
