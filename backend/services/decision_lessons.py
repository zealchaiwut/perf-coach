"""Lessons from a race-debrief change list (revamp P4-13).

``raw_text`` is immutable and stays exactly what was pasted; lessons are *derived
from it on read* (no second copy to drift). Format, from the race-debrief prompt::

    CHANGES TO APPLY
    lessons:  Went out too fast in the first 5 km
              Take the first gel before 40 minutes
    skeleton: ...

``lessons:`` may carry the first lesson on its own line and then one or two more
lines (optionally bulleted or numbered), or hold them on the following lines. They
end at the next change-list key, a blank line, or the third lesson. A paste with no
``lessons:`` line (an ordinary check-in) yields none.
"""
from __future__ import annotations

import re
from typing import Optional

# Mirrors session_consult.PROMPT_VERSION_RACE (asserted equal in tests; importing it
# here would be circular because session_consult reads lessons from this module).
PROMPT_VERSION_RACE = "race-debrief-v2"

MAX_LESSONS = 3
LESSON_MAX_CHARS = 200

_KEYS = ("prefs", "skeleton", "goal", "habits", "review", "lessons")
_KEY_LINE = re.compile(r"^\s*(%s)\s*:\s*(.*)$" % "|".join(_KEYS), re.I)
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s*")
_VERSION_LINE = re.compile(r"prompt_version\s*:\s*%s\b" % re.escape(PROMPT_VERSION_RACE), re.I)
_SESSION_LINE = re.compile(r"session_id\s*:\s*([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})")


def _clean(text: str) -> str:
    t = _BULLET.sub("", text).strip()
    return t[:LESSON_MAX_CHARS].rstrip()


def parse_lessons(raw_text: Optional[str]) -> list[str]:
    lines = (raw_text or "").splitlines()
    for i, line in enumerate(lines):
        m = _KEY_LINE.match(line)
        if not m or m.group(1).lower() != "lessons":
            continue
        out: list[str] = []
        first = _clean(m.group(2))
        if first and not first.startswith("<"):  # an unfilled "<1-3 lessons>" placeholder
            out.append(first)
        for nxt in lines[i + 1:]:
            if len(out) >= MAX_LESSONS or not nxt.strip() or _KEY_LINE.match(nxt):
                break
            lesson = _clean(nxt)
            if lesson:
                out.append(lesson)
        return out[:MAX_LESSONS]
    return []


def looks_like_race_debrief(raw_text: Optional[str]) -> bool:
    """True when the paste carries the race-debrief prompt version line or a lessons line."""
    text = raw_text or ""
    if _VERSION_LINE.search(text):
        return True
    return any(
        (m := _KEY_LINE.match(line)) is not None and m.group(1).lower() == "lessons"
        for line in text.splitlines()
    )


def session_id_in(raw_text: Optional[str]) -> Optional[str]:
    """The ``session_id:`` header of a pasted prompt, if the paste included it."""
    m = _SESSION_LINE.search(raw_text or "")
    return m.group(1) if m else None
