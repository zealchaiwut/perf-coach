"""Today's training recommendation: keep / downgrade / rest / no_plan.

Combines today's planned session, today's readiness score, and the current
training-load verdict to answer the morning question: "should I still do
today's workout?"

Pure function: compute_today_recommendation takes plain-data inputs and
returns a deterministic recommendation dict. No I/O, no LLM.
"""
from __future__ import annotations

from typing import Literal, Optional

Recommendation = Literal["keep", "downgrade", "rest", "no_plan"]

# Session-name or block-target keywords that indicate a hard-effort session.
_HARD_KEYWORDS: tuple[str, ...] = (
    "interval", "tempo", "threshold", "long run", "longrun", "vo2",
    "repeat", "track", "speed", "hard",
)

# Readiness floor below which we recommend rest regardless of verdict/plan.
READINESS_REST_THRESHOLD: int = 35

# Session types that are never "hard" (always treated as easy/rest).
_SOFT_SESSION_TYPES = {"rest"}


def _structure_has_hard_blocks(structure: Optional[dict]) -> bool:
    """Return True if any block in the run structure signals a hard effort."""
    if not structure:
        return False
    blocks = structure.get("blocks") or []
    for block in blocks:
        target = (block.get("target") or "").lower()
        phase = (block.get("phase") or "").lower()
        combined = target + " " + phase
        if any(kw in combined for kw in _HARD_KEYWORDS):
            return True
    return False


def is_hard_session(session_type: str, name: Optional[str], structure: Optional[dict]) -> bool:
    """Return True when the planned session qualifies as a 'hard' session.

    Hard sessions are the ones the rules can downgrade:
    - runs whose blocks include tempo, intervals, long-run or hard-effort phases
    - sessions whose name contains hard-effort keywords
    - strength/plyo sessions whose name signals high intensity

    'rest' sessions are never hard.
    """
    if session_type in _SOFT_SESSION_TYPES:
        return False

    name_lower = (name or "").lower()
    if any(kw in name_lower for kw in _HARD_KEYWORDS):
        return True

    if session_type == "run":
        return _structure_has_hard_blocks(structure)

    return False


def _easy_structure_from(session_type: str, structure: Optional[dict]) -> Optional[dict]:
    """Build a replacement structure that is all-easy, preserving total duration."""
    if not structure:
        return None

    if session_type == "run":
        blocks = structure.get("blocks") or []
        total_min = sum(
            (b.get("duration_min") or 0) * max(1, b.get("repeat") or 1)
            for b in blocks
        )
        if total_min <= 0:
            return structure
        return {
            "blocks": [
                {
                    "phase": "main",
                    "duration_min": total_min,
                    "repeat": None,
                    "rest_min": None,
                    "target": "easy, conversational",
                }
            ]
        }

    # For strength/plyo, just strip intensity cues from the name by returning
    # structure unchanged — the caller will rename the session.
    return structure


def compute_today_recommendation(
    *,
    session_type: Optional[str],
    session_name: Optional[str],
    session_structure: Optional[dict],
    readiness_score: Optional[float],
    verdict: Optional[str],
    active_injuries: Optional[list] = None,
) -> dict:
    """Pure, deterministic recommendation engine.

    Rules (evaluated in priority order):
    1. No planned session → no_plan
    2. Active illness (energy==1 proxy) OR readiness < READINESS_REST_THRESHOLD → rest
    3. verdict back_off + hard session → downgrade
    4. verdict hold + hard session → downgrade
    5. otherwise → keep

    Returns:
        recommendation: keep | downgrade | rest | no_plan
        reason: human-readable one-line explanation
        apply_patch: dict with the fields to PATCH onto the planned session
                     when the user taps "apply", or None when not applicable
    """
    active_injuries = active_injuries or []

    if session_type is None:
        return {
            "recommendation": "no_plan",
            "reason": "No session planned for today.",
            "apply_patch": None,
        }

    hard = is_hard_session(session_type, session_name, session_structure)

    # Rule 2 — rest/illness
    if readiness_score is not None and readiness_score < READINESS_REST_THRESHOLD:
        return {
            "recommendation": "rest",
            "reason": f"Readiness {int(round(readiness_score))} — body needs recovery, not more load.",
            "apply_patch": None,
        }

    if active_injuries:
        return {
            "recommendation": "rest",
            "reason": "Active injury flagged — rest to protect recovery.",
            "apply_patch": None,
        }

    # Rule 3 — back_off + hard session
    if verdict == "back_off" and hard:
        easy_structure = _easy_structure_from(session_type, session_structure)
        return {
            "recommendation": "downgrade",
            "reason": "Training load spike (ACWR elevated) — swap today's hard session for an easy one.",
            "apply_patch": {
                "name": "Easy " + (session_name or session_type).lstrip("Easy "),
                "structure": easy_structure,
            },
        }

    # Rule 4 — hold + hard session
    if verdict == "hold" and hard:
        easy_structure = _easy_structure_from(session_type, session_structure)
        return {
            "recommendation": "downgrade",
            "reason": "Holding load this week — convert today's hard session to easy.",
            "apply_patch": {
                "name": "Easy " + (session_name or session_type).lstrip("Easy "),
                "structure": easy_structure,
            },
        }

    # Rule 5 — keep (also: back_off/hold + EASY session → still keep)
    return {
        "recommendation": "keep",
        "reason": "Go for it — conditions look good for today's session.",
        "apply_patch": None,
    }
