"""Unit tests for Claude CLI coach narrative helper (no real claude invoke)."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from backend.services.coach_claude_cli import (
    _extract_sections,
    call_claude_cli_sections,
    claude_cli_enabled,
)


def test_extract_sections_from_structured_output():
    payload = {
        "type": "result",
        "structured_output": {
            "now": "Hold load this week while measuring weight carefully.",
            "focus": "Priority one is weigh-ins before any deficit talk.",
            "dream": "A-race goal stays the north star through checkpoints.",
            "reflection": "Hit most planned sessions; next easy run advances focus.",
        },
    }
    secs = _extract_sections(payload)
    assert secs["now"].startswith("Hold load")
    assert secs["reflection"]


def test_extract_sections_from_result_json_string():
    inner = {
        "now": "Hold load this week while measuring weight carefully.",
        "focus": "Priority one is weigh-ins before any deficit talk.",
        "dream": "A-race goal stays the north star through checkpoints.",
        "reflection": "Hit most planned sessions; next easy run advances focus.",
    }
    secs = _extract_sections({"result": json.dumps(inner)})
    assert secs["focus"].startswith("Priority")


def test_claude_cli_enabled_respects_env(monkeypatch):
    monkeypatch.setenv("COACH_LLM", "api")
    assert claude_cli_enabled() is False
    monkeypatch.setenv("COACH_LLM", "claude_cli")
    with patch("backend.services.coach_claude_cli.shutil.which", return_value="/bin/claude"):
        assert claude_cli_enabled() is True
    with patch("backend.services.coach_claude_cli.shutil.which", return_value=None):
        assert claude_cli_enabled() is False


def test_call_claude_cli_sections_parses_subprocess(monkeypatch):
    monkeypatch.setenv("COACH_CLAUDE_MODEL", "sonnet")
    inner = {
        "now": "Hold load this week while measuring weight carefully.",
        "focus": "Priority one is weigh-ins before any deficit talk.",
        "dream": "A-race goal stays the north star through checkpoints.",
        "reflection": "Hit most planned sessions; next easy run advances focus.",
    }
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = json.dumps({"structured_output": inner})
    proc.stderr = ""
    with patch("backend.services.coach_claude_cli.shutil.which", return_value="claude"), \
         patch("backend.services.coach_claude_cli.subprocess.run", return_value=proc) as run:
        secs = call_claude_cli_sections("sys", "user")
    assert secs["now"].startswith("Hold")
    cmd = run.call_args.args[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--json-schema" in cmd
    assert "--output-format" in cmd
    assert "--setting-sources" in cmd
    # ANTHROPIC_API_KEY stripped; cwd is home for keychain auth
    env = run.call_args.kwargs["env"]
    assert "ANTHROPIC_API_KEY" not in env
    assert run.call_args.kwargs["cwd"] == os.path.expanduser("~")
