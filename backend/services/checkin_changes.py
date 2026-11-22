"""Parse CHANGES TO APPLY blocks for weekly check-in and race debrief (P6-15)."""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any

from backend.services.coach_block import _lines

PROMPT_VERSION_WEEKLY = "weekly-checkin-v1"
_CHANGE_KEYS = frozenset({"lessons", "skeleton", "goal", "review", "habits", "prefs"})
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_HEADING_RE = re.compile(r"^\s*([A-Za-z]+)\s*:\s*(.*)$")


def _extract_block(raw_text: str) -> str:
    if not raw_text:
        return ""
    out: list[str] = []
    in_block = False
    for line in raw_text.splitlines():
        if line.strip().upper() == "CHANGES TO APPLY":
            in_block = True
            continue
        if not in_block:
            continue
        if line.strip().startswith("```"):
            break
        out.append(line)
    return "\n".join(out).strip()


def _review_date_from_text(text: str, decided_on: date) -> date:
    m = _DATE_RE.search(text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return decided_on + timedelta(days=7)


def parse_changes_block(raw_text: str, *, decided_on: date | None = None) -> list[dict[str, Any]]:
    decided = decided_on or date.today()
    block = _extract_block(raw_text) or raw_text or ""
    items: list[dict[str, Any]] = []
    current_key: str | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_parts
        if current_key is None:
            return
        text = "\n".join(p.strip() for p in current_parts if p and p.strip()).strip()
        if text:
            review_on = _review_date_from_text(text, decided) if current_key == "review" else None
            items.append(
                {
                    "id": uuid.uuid4().hex,
                    "change_type": current_key,
                    "text": text,
                    "status": "not_yet",
                    "review_on": review_on.isoformat() if review_on else None,
                }
            )
        current_key = None
        current_parts = []

    for line in block.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            key = m.group(1).lower()
            rest = (m.group(2) or "").strip()
            if key in _CHANGE_KEYS:
                flush()
                current_key = key
                current_parts = [rest] if rest and not rest.startswith("<") else []
                continue
        if current_key and line.strip():
            if line[:1].isspace() or line.startswith("\t") or current_key == "lessons":
                current_parts.append(line.strip())
    flush()

    if not items:
        for key, text in _lines(block):
            if key in _CHANGE_KEYS and text:
                review_on = _review_date_from_text(text, decided) if key == "review" else None
                items.append(
                    {
                        "id": uuid.uuid4().hex,
                        "change_type": key,
                        "text": text.strip(),
                        "status": "not_yet",
                        "review_on": review_on.isoformat() if review_on else None,
                    }
                )
    return items


def changes_to_raw_text(items: list[dict[str, Any]]) -> str:
    lines = ["CHANGES TO APPLY"]
    for item in items:
        key = item.get("change_type") or "goal"
        text = (item.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{key}:  {text}")
    return "\n".join(lines)