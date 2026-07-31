"""Guard: the worker's LLM surface stays exactly two calls wide.

The rule is **minimal LLM**, not no LLM (see CLAUDE.md). Two surfaces earn a
provider call:

1. **Ask-AI single session** — interactive, in the webapp.
2. **The daily coach message** — the warmth rephrase in ``weekly_coach_message``,
   which runs on the worker.

Everything else Priority 2 parked stays parked: ``coach_narrative`` and its
LangGraph orchestrator, ``coach_claude_cli``, ``plan_draft`` and its slot cache,
and ``phrasing.py``'s LLM path. Those are the modules that made the worker's
surface sprawl — atom validators, retry loops, a ``claude -p`` transport — and
none of them is coming back without a decision.

So this file no longer asserts "no LLM on the worker". It asserts that the
*parked cluster* stays unreachable, and that no third-party SDK appears. The
line it defends is: adding warmth to one message is a decision; re-importing the
whole parked orchestration stack is a regression.

Note ``backend.services.llm`` IS now expected on the worker — it is what the
daily message's rephrase calls.

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

import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# The parked cluster. These modules exist only to make LLM calls that the
# consolidation decided not to keep; importing one from the worker means the
# parked orchestration is reachable again.
#
# backend.services.llm is deliberately NOT here — the daily coach message's
# warmth rephrase calls it, which is one of the two sanctioned LLM surfaces.
FORBIDDEN_MODULES = {
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


def test_worker_does_not_load_the_parked_llm_cluster(worker_modules):
    """Minimal LLM means two sanctioned calls, not an open door."""
    hits = sorted(worker_modules & FORBIDDEN_MODULES)
    assert not hits, (
        "importing backend.worker_app pulled in parked LLM module(s): "
        + ", ".join(hits)
        + ". These were parked in Priority 2 and stay parked — move the import "
        "inside the function that needs it, or drop the dependency."
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
    """The BRIEF stays deterministic even though the daily message does not.

    These are two different surfaces. The warmth rephrase was restored for the
    daily message only; the brief's LLM atom assembly — validators, retry loops,
    the 22 Jul hardening scars — stays parked in coach_narrative.
    """
    from backend.services import coach_brief

    assert callable(coach_brief.build_brief_deterministic)

    modules = _loaded_modules("backend.services.coach_brief")
    hits = sorted(modules & FORBIDDEN_MODULES)
    assert not hits, f"coach_brief pulled in {hits}"


def test_daily_message_has_its_warmth_rephrase():
    """Restored deliberately — one of the two sanctioned LLM surfaces."""
    import backend.services.weekly_coach_message as wcm

    assert hasattr(wcm, "_call_llm_narrative")


def test_warmth_rephrase_is_guarded_by_a_numeral_check():
    """The prose may change; the numbers may not.

    The message is trusted because its figures come from the engines. A rephrase
    that alters one is discarded rather than shown — a warm sentence is not
    worth a wrong number.
    """
    import backend.services.weekly_coach_message as wcm

    assert wcm._numbers_preserved("hold 315 TSS, 1:45 goal", "Hold 315 TSS — 1:45 is the goal.")
    assert not wcm._numbers_preserved("hold 315 TSS", "Hold 320 TSS")
    assert not wcm._numbers_preserved("315 TSS over 5 runs", "315 TSS over some runs")


def test_warmth_rephrase_falls_back_rather_than_raising():
    """Any failure must yield the deterministic text, never an exception — the
    athlete always gets a message."""
    src = inspect.getsource(wcm_module()._build_message)
    assert "except Exception" in src
    assert "compose_deterministic_message" in src


def wcm_module():
    import backend.services.weekly_coach_message as wcm

    return wcm
