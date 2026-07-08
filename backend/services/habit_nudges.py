"""Pure function for generating habit adherence coaching nudges.

No I/O, no database access, no side effects.  All data is supplied by
the caller (typically the thin endpoint layer that runs queries).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants — never inline these as magic numbers
# ---------------------------------------------------------------------------

MAXIMUM_NUDGES: int = 5

# A weekday is "materially lower" when it falls this many percentage points
# below the habit's own overall average.
_WEEKDAY_DIP_THRESHOLD: float = 15.0

# A habit is "slipping" if its current-period adherence is this many points
# below the previous-period value.  Callers supply already-filtered lists, so
# this is a secondary guard only.
_SLIP_MIN_DROP: float = 10.0

_WEEKDAY_NAMES = {
    0: "Mondays",
    1: "Tuesdays",
    2: "Wednesdays",
    3: "Thursdays",
    4: "Fridays",
    5: "Saturdays",
    6: "Sundays",
}

_PCT_WORDS = {
    0: "zero",
    10: "ten",
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
    100: "one hundred",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pct_to_word(value: float) -> str:
    """Return the plain English word for a percentage rounded to the nearest ten.

    Examples:
        >>> _pct_to_word(88.0)
        'ninety'
        >>> _pct_to_word(52.0)
        'fifty'
        >>> _pct_to_word(100.0)
        'one hundred'
    """
    rounded = round(value / 10) * 10
    rounded = max(0, min(100, rounded))
    return _PCT_WORDS.get(rounded, str(rounded))


def _weekday_nudge(habit_name: str, weekday_int: int) -> str:
    """Return a non-judgmental sentence about a recurring low-adherence weekday."""
    day = _WEEKDAY_NAMES[weekday_int]
    return f"you tend to skip {habit_name} on {day} — it might help to plan ahead for that day"


def _slipping_nudge(habit_name: str, prev_pct: float, current_pct: float) -> str:
    """Return a supportive sentence about a habit whose adherence has slipped."""
    prev_word = _pct_to_word(prev_pct)
    curr_word = _pct_to_word(current_pct)
    return (
        f"{habit_name} has drifted from {prev_word} to {curr_word} percent this period "
        f"— a small reset can make a difference"
    )


def _collect_weekday_candidates(
    adherence_breakdowns: dict[str, Any],
) -> list[tuple[str, dict]]:
    """Return (nudge_str, debug_info) pairs for all weekday-dip signals."""
    candidates: list[tuple[str, dict]] = []
    for habit_name, breakdown in adherence_breakdowns.items():
        weekday_pct = breakdown.get("weekday_pct") or {}
        overall_avg = breakdown.get("overall_avg", 0.0)
        for day_int, pct in weekday_pct.items():
            if overall_avg - pct >= _WEEKDAY_DIP_THRESHOLD:
                nudge = _weekday_nudge(habit_name, int(day_int))
                debug = {
                    "type": "weekday_pattern",
                    "habit": habit_name,
                    "weekday": _WEEKDAY_NAMES[int(day_int)],
                    "weekday_pct": pct,
                    "overall_avg": overall_avg,
                }
                candidates.append((nudge, debug))
    return candidates


def _collect_slipping_candidates(
    slipping_habits: list[dict[str, Any]],
) -> list[tuple[str, dict]]:
    """Return (nudge_str, debug_info) pairs for all slipping-habit signals."""
    candidates: list[tuple[str, dict]] = []
    for item in slipping_habits:
        name = item.get("name", "")
        prev = float(item.get("prev_percent", 0.0))
        current = float(item.get("current_percent", 0.0))
        if prev - current >= _SLIP_MIN_DROP:
            nudge = _slipping_nudge(name, prev, current)
            debug = {
                "type": "slipping",
                "habit": name,
                "prev_percent": prev,
                "current_percent": current,
            }
            candidates.append((nudge, debug))
    return candidates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_nudges(
    adherence_breakdowns: dict[str, Any] | None,
    slipping_habits: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Transform adherence breakdowns and slipping-habit signals into coaching nudges.

    The function is pure — it performs no I/O, mutates no inputs, and has no
    observable side effects.  All data is provided by the caller.

    Parameters
    ----------
    adherence_breakdowns:
        Mapping of habit name to its weekday-level adherence breakdown.
        Each value is a dict with:
          - ``weekday_pct``: dict mapping weekday integer (0=Monday … 6=Sunday)
            to the adherence percentage for that weekday.
          - ``overall_avg``: float — the habit's mean adherence across all weekdays.
        Typically the output of ``compute_adherence_breakdown``.
        Pass ``None`` or ``{}`` when no breakdown data is available.
    slipping_habits:
        List of dicts, each with keys ``name`` (str), ``prev_percent`` (float),
        and ``current_percent`` (float).  Typically the output of
        ``detect_slipping_habits``.
        Pass ``None`` or ``[]`` when no slipping-habit data is available.

    Returns
    -------
    dict
        A dict with two keys:

        ``nudges``
            A list of plain-language coaching strings, at most ``MAXIMUM_NUDGES``
            entries.  No nudge string contains raw percentage digits or the ``%``
            character — all numeric values are expressed in words ("fifty
            percent", not "50%").  Tone is supportive and non-judgmental.

        ``debug``
            A dict explaining why each nudge was or was not emitted.  Always
            includes a ``signals`` key listing every candidate, each marked
            ``emitted: true/false`` with a ``reason`` when omitted.  When both
            inputs are absent, ``debug`` contains only a ``reason`` string.

    Worked example — weekday-pattern nudge::

        adherence_breakdowns = {
            "Morning Run": {
                "weekday_pct": {
                    0: 85.0, 1: 82.0, 2: 88.0, 3: 80.0,
                    4: 10.0,  # Friday — far below the average
                    5: 90.0, 6: 84.0,
                },
                "overall_avg": 74.1,
            }
        }
        result = build_nudges(adherence_breakdowns, [])
        # overall_avg (74.1) - Friday (10.0) = 64.1, exceeds threshold
        # Expected:
        # result["nudges"] == [
        #     "you tend to skip Morning Run on Fridays — it might help to plan ahead for that day"
        # ]
        # result["debug"]["signals"][0]["type"] == "weekday_pattern"

    Worked example — slipping-habit nudge::

        slipping_habits = [
            {"name": "Meditation", "prev_percent": 90.0, "current_percent": 50.0}
        ]
        result = build_nudges({}, slipping_habits)
        # 90 → "ninety", 50 → "fifty"
        # Expected:
        # result["nudges"] == [
        #     "Meditation has drifted from ninety to fifty percent this period "
        #     "— a small reset can make a difference"
        # ]
        # result["debug"]["signals"][0]["type"] == "slipping"
    """
    # Guard: both inputs are None
    if adherence_breakdowns is None and slipping_habits is None:
        return {"nudges": [], "debug": {"reason": "inputs were None"}}

    breakdowns = adherence_breakdowns or {}
    slipping = slipping_habits or []

    # Guard: both inputs are effectively empty
    if not breakdowns and not slipping:
        return {"nudges": [], "debug": {"reason": "no adherence data provided"}}

    # Collect all candidate nudges from both signal sources
    weekday_candidates = _collect_weekday_candidates(breakdowns)
    slipping_candidates = _collect_slipping_candidates(slipping)
    all_candidates = weekday_candidates + slipping_candidates

    # Apply the cap
    emitted = all_candidates[:MAXIMUM_NUDGES]
    omitted = all_candidates[MAXIMUM_NUDGES:]

    nudges = [nudge for nudge, _ in emitted]

    # Build debug payload
    signals = []
    for nudge, info in emitted:
        signals.append({**info, "emitted": True})
    for nudge, info in omitted:
        signals.append({**info, "emitted": False, "omit_reason": "cap reached"})

    debug: dict[str, Any] = {"signals": signals}
    if omitted:
        debug["cap_note"] = (
            f"{len(omitted)} candidate nudge(s) omitted because MAXIMUM_NUDGES "
            f"({MAXIMUM_NUDGES}) was reached"
        )

    return {"nudges": nudges, "debug": debug}


# ── LLM coaching overlay (issue #1312) ────────────────────────────────────────

_MAX_NUDGE_LINE_LEN = 250
_MEDICAL_TERMS = ("doctor", "injury", "medical", "diagnos", "treat", "pain", "consult")

_NUDGES_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


def _nudges_facts_text(
    adherence_breakdowns: dict[str, Any],
    slipping_habits: list[dict[str, Any]],
) -> str:
    return json.dumps(
        {"breakdowns": adherence_breakdowns, "slipping": slipping_habits},
        sort_keys=True,
    )


def _nudges_signature(
    adherence_breakdowns: dict[str, Any],
    slipping_habits: list[dict[str, Any]],
) -> str:
    return hashlib.sha256(
        _nudges_facts_text(adherence_breakdowns, slipping_habits).encode()
    ).hexdigest()


def _validate_nudge_lines(lines: list[str], facts_text: str, expected_count: int) -> bool:
    if len(lines) != expected_count:
        return False
    for line in lines:
        if len(line) > _MAX_NUDGE_LINE_LEN:
            return False
        for num in re.findall(r"\d+(?:\.\d+)?", line):
            if num not in facts_text:
                return False
        if any(term in line.lower() for term in _MEDICAL_TERMS):
            return False
    return True


def apply_llm_nudges(
    nudge_result: dict[str, Any],
    adherence_breakdowns: dict[str, Any],
    slipping_habits: list[dict[str, Any]],
    user_id: str,
    db=None,
) -> dict[str, Any]:
    """Replace nudge strings with LLM prose when LLM is enabled.

    Falls back to the original nudge_result on any failure.
    The pure build_nudges function is not modified.
    """
    nudges = nudge_result.get("nudges", [])
    if not nudges:
        return nudge_result

    import backend.services.llm as _llm  # lazy to avoid circular at module load

    if not _llm.llm_enabled():
        return nudge_result

    facts_text = _nudges_facts_text(adherence_breakdowns, slipping_habits)
    sig = _nudges_signature(adherence_breakdowns, slipping_habits)

    signals = (nudge_result.get("debug") or {}).get("signals", [])
    prompt_lines = [
        f"{i+1}. Original: '{nudge}' | Data: {json.dumps(signals[i] if i < len(signals) else {})}"
        for i, nudge in enumerate(nudges)
    ]

    system = (
        "You are a performance coach writing concise, supportive habit nudges. "
        "Rules: one line per nudge, max 250 characters, no medical or injury advice, "
        "use only numbers given in the data (no invented figures), "
        "no exclamation marks, no emoji, supportive and non-judgmental tone."
    )
    user = (
        "Rephrase each numbered nudge as a warm, one-sentence coaching line. "
        "Return JSON: {\"lines\": [...]}.\n" + "\n".join(prompt_lines)
    )

    def _generate():
        return _llm.complete_structured(
            system=system,
            user=user,
            schema_name="habit_nudges_lines",
            json_schema=_NUDGES_JSON_SCHEMA,
            model_tier="fast",
        )

    result = _llm.get_or_generate(
        user_id=user_id,
        surface="habit_nudges",
        signature=sig,
        generate_fn=_generate,
        db=db,
    )

    if result is None:
        return nudge_result

    lines = result.get("lines", [])
    if not _validate_nudge_lines(lines, facts_text, len(nudges)):
        return nudge_result

    return {**nudge_result, "nudges": lines}
