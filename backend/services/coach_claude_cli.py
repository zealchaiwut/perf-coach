"""Weekly coach narrative via Claude Code CLI (`claude -p`).

Once-a-week generation — uses the Claude.ai subscription (keychain) instead of
the rate-limited z.ai / Groq HTTP client. Strips ANTHROPIC_API_KEY so a stale
API key cannot force a zero-balance failure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

from backend.utils.log import get_logger

_log = get_logger(__name__)

SECTION_KEYS = ("now", "focus", "dream", "reflection")

_DEFAULT_TIMEOUT_SEC = 180
_DEFAULT_MODEL = "sonnet"


def claude_cli_enabled() -> bool:
    """True when COACH_LLM=claude_cli (default) and `claude` is on PATH."""
    mode = (os.environ.get("COACH_LLM") or "claude_cli").strip().lower()
    if mode not in ("claude_cli", "claude", "cli"):
        return False
    return shutil.which(os.environ.get("COACH_CLAUDE_BIN") or "claude") is not None


def _schema_for_cli() -> dict:
    return {
        "type": "object",
        "properties": {
            "now": {"type": "string"},
            "focus": {"type": "string"},
            "dream": {"type": "string"},
            "reflection": {"type": "string"},
        },
        "required": list(SECTION_KEYS),
        "additionalProperties": False,
    }


def _extract_sections(payload: Any) -> dict[str, str] | None:
    """Normalize claude -p JSON / structured_output / raw text into sections."""
    if payload is None:
        return None

    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        # Try JSON object first
        try:
            return _extract_sections(json.loads(text))
        except json.JSONDecodeError:
            pass
        # Fenced JSON
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return _extract_sections(json.loads(m.group(1)))
            except json.JSONDecodeError:
                pass
        # Bare object in stdout
        m = re.search(r"\{[\s\S]*\"now\"[\s\S]*\}", text)
        if m:
            try:
                return _extract_sections(json.loads(m.group(0)))
            except json.JSONDecodeError:
                pass
        return None

    if not isinstance(payload, dict):
        return None

    # Prefer structured_output from --json-schema
    for key in ("structured_output", "structuredOutput"):
        if key in payload and payload[key]:
            got = _extract_sections(payload[key])
            if got:
                return got

    # Direct section keys
    if any(k in payload for k in SECTION_KEYS):
        sections = {k: str(payload.get(k) or "").strip() for k in SECTION_KEYS}
        if any(sections.values()):
            return sections

    # --output-format json wraps the assistant text in "result"
    if "result" in payload:
        return _extract_sections(payload["result"])

    return None


def call_claude_cli_sections(
    system: str,
    user: str,
    *,
    timeout_sec: int | None = None,
) -> dict[str, str] | None:
    """Run `claude -p` with JSON schema; return {now,focus,dream,reflection} or None."""
    bin_name = os.environ.get("COACH_CLAUDE_BIN") or "claude"
    if not shutil.which(bin_name):
        _log.warning("claude CLI not found on PATH (%s)", bin_name)
        return None

    model = (os.environ.get("COACH_CLAUDE_MODEL") or _DEFAULT_MODEL).strip()
    timeout = timeout_sec or int(
        os.environ.get("COACH_CLAUDE_TIMEOUT_SEC") or _DEFAULT_TIMEOUT_SEC
    )
    schema = json.dumps(_schema_for_cli(), separators=(",", ":"))

    cmd = [
        bin_name,
        "--model", model,
        "--system-prompt", system,
        "--output-format", "json",
        "--json-schema", schema,
        "--tools", "",
        "--disable-slash-commands",
        "--setting-sources", "user",
        "--no-session-persistence",
        "-p", user,
    ]

    # Subscription / keychain auth — same gotcha as Commander estimator.
    # Do NOT set CLAUDE_CODE_SIMPLE / --bare (those skip keychain → "Not logged in").
    # --setting-sources user skips project CLAUDE.md / local settings that can
    # hijack a weekly coaching prompt when cwd is the app repo.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=os.path.expanduser("~"),
        )
    except subprocess.TimeoutExpired:
        _log.warning("claude -p timed out after %ss", timeout)
        return None
    except FileNotFoundError:
        _log.warning("claude CLI not found")
        return None
    except Exception as exc:
        _log.warning("claude -p failed: %s", exc)
        return None

    if proc.returncode != 0:
        _log.warning(
            "claude -p exit %s: %s",
            proc.returncode,
            (proc.stderr or proc.stdout or "")[:400],
        )
        return None

    stdout = (proc.stdout or "").strip()
    if not stdout:
        _log.warning("claude -p returned empty stdout")
        return None

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = stdout

    sections = _extract_sections(payload)
    if not sections:
        _log.warning(
            "claude -p could not parse sections (preview=%r)",
            stdout[:240],
        )
        return None
    return sections
