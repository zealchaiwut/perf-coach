"""Guards: dead COACH_LLM=claude_cli config is removed from docs, config, and services.

Issue #1716 (P3): start_worker.sh, .env.example, and docs/worker.md described the
parked coach_narrative / coach_claude_cli path (COACH_LLM=claude_cli) as live.
These modules are genuinely unreferenced by the worker and pending deletion.

AC1: backend/services/coach_narrative.py does not exist (deleted)
AC2: backend/services/coach_claude_cli.py does not exist (deleted)
AC3: start_worker.sh does not export or reference COACH_LLM
AC4: .env.example does not document COACH_LLM, COACH_ORCH, or COACH_CLAUDE_MODEL
     as live config options for the dead path
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_coach_narrative_module_deleted():
    """AC1: parked coach_narrative.py has been removed."""
    assert not (REPO / "backend/services/coach_narrative.py").exists(), (
        "backend/services/coach_narrative.py still exists — "
        "it is parked/unreferenced and should be deleted (issue #1716)"
    )


def test_coach_claude_cli_module_deleted():
    """AC2: parked coach_claude_cli.py has been removed."""
    assert not (REPO / "backend/services/coach_claude_cli.py").exists(), (
        "backend/services/coach_claude_cli.py still exists — "
        "it is parked/unreferenced and should be deleted (issue #1716)"
    )


def test_start_worker_sh_has_no_coach_llm():
    """AC3: start_worker.sh no longer sets COACH_LLM."""
    content = (REPO / "start_worker.sh").read_text()
    assert "COACH_LLM" not in content, (
        "start_worker.sh still references COACH_LLM — "
        "the dead config path should be removed (issue #1716)"
    )


def test_env_example_has_no_coach_llm():
    """AC4: .env.example no longer documents the dead COACH_LLM config."""
    content = (REPO / ".env.example").read_text()
    assert "COACH_LLM" not in content, (
        ".env.example still references COACH_LLM — "
        "the dead config path should be removed (issue #1716)"
    )


def test_env_example_has_no_coach_orch():
    """AC4: .env.example no longer documents the dead COACH_ORCH config."""
    content = (REPO / ".env.example").read_text()
    assert "COACH_ORCH" not in content, (
        ".env.example still references COACH_ORCH — "
        "the dead config path should be removed (issue #1716)"
    )


def test_env_example_has_no_coach_claude_model():
    """AC4: .env.example no longer documents the dead COACH_CLAUDE_MODEL config."""
    content = (REPO / ".env.example").read_text()
    assert "COACH_CLAUDE_MODEL" not in content, (
        ".env.example still references COACH_CLAUDE_MODEL — "
        "the dead config path should be removed (issue #1716)"
    )
