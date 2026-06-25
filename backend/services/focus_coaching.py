"""Focus-aware coaching builders for the user's focus habits.

Pure function module — no database access, no mutations, no global state.
All user-facing copy is delegated to :mod:`backend.services.coaching_voice`
so that tone changes propagate automatically.

Public API
----------
build_slipping_warning(habit_name, slipping_signal)
    Prospective warning copy when H4 signals a likely miss.
    Returns None when the habit is not slipping.

build_recommit_or_drop(habit_name, consistency_pct_7d)
    Recommit-or-drop decision copy when a focus habit has dropped meaningfully.
    Never presents this as a streak-loss notification.

build_minimum_version_offer(habit_name, minimum_version)
    Offer the minimum viable version of the habit on a struggling day.
    Returns None when minimum_version is None or empty.

build_anchor_cue(habit_name, anchor_event)
    Cue copy linking the habit to an existing anchor action.
    Returns None when anchor_event is None or empty.

build_keystone_elevation(keystone_name, support_names, correlation_signal)
    Elevate the keystone habit, label it priority and label the others
    as supports.  All language is associative — never causal.
    When the H3 correlation signal carries a non-empty reason (invalid
    signal), returns a dict with available=False.

Signal schemas (pre-fetched by caller — never queried here)
-----------------------------------------------------------
slipping_signal : dict with keys
    is_slipping          bool
    predicted_miss_weekday  str | None
    days_until_miss      int | None
    consistency_pct_7d   float | None

correlation_signal : dict with keys (matches compute_correlation output)
    r      float
    n      int
    reason str  (empty when valid, non-empty when data is insufficient)
"""

from __future__ import annotations

import backend.services.coaching_voice as coaching_voice


# ── Slipping warning ──────────────────────────────────────────────────────────

def build_slipping_warning(
    habit_name: str,
    slipping_signal: dict,
) -> dict | None:
    """Return prospective warning copy for a focus habit showing H4 slipping signals.

    Returns None when is_slipping is False.

    Returns a dict with:
        message                 str
        type                    "slipping_warning"
        includes_recommit_or_drop   True
    """
    if not slipping_signal.get("is_slipping"):
        return None

    predicted_day = slipping_signal.get("predicted_miss_weekday")
    context_clause = (
        f"recommit to {habit_name} or choose to step back for now"
    )
    if predicted_day:
        context_clause = (
            f"recommit to {habit_name} before {predicted_day} "
            f"or choose to step back for now"
        )

    message = coaching_voice.decision_prompt_line_builder(
        habit_name,
        None,
        "down",
        context_clause,
    )

    return {
        "message": message,
        "type": "slipping_warning",
        "includes_recommit_or_drop": True,
    }


# ── Recommit-or-drop ──────────────────────────────────────────────────────────

def build_recommit_or_drop(
    habit_name: str,
    consistency_pct_7d: float | None = None,
) -> dict:
    """Return recommit-or-drop decision copy when a focus habit has dropped meaningfully.

    Presents a choice between recommitting and stepping back — never a
    streak-loss notification.

    Returns a dict with:
        message  str
        type     "recommit_or_drop"
    """
    context = (
        f"recommit to {habit_name} this week or choose to pause it for now"
    )
    message = coaching_voice.decision_prompt_line_builder(
        habit_name,
        None,
        "down",
        context,
    )
    return {
        "message": message,
        "type": "recommit_or_drop",
    }


# ── Minimum version offer ─────────────────────────────────────────────────────

def build_minimum_version_offer(
    habit_name: str,
    minimum_version: str | None,
) -> dict | None:
    """Return minimum-version offer copy for a struggling day.

    Returns None when minimum_version is None or empty — the feature is
    silently skipped, preserving the existing coaching flow.

    Returns a dict with:
        message  str
        type     "minimum_version_offer"
    """
    if not minimum_version:
        return None

    context = f"{minimum_version} counts today — your streak stays intact"
    message = coaching_voice.decision_prompt_line_builder(
        habit_name,
        None,
        "neutral",
        context,
    )
    return {
        "message": message,
        "type": "minimum_version_offer",
    }


# ── Anchor cue ────────────────────────────────────────────────────────────────

def build_anchor_cue(
    habit_name: str,
    anchor_event: str | None,
) -> dict | None:
    """Return anchor cue copy linking the habit to an existing action.

    Returns None when anchor_event is None or empty.

    Returns a dict with:
        message  str
        type     "anchor_cue"
    """
    if not anchor_event:
        return None

    context = f"right after your {anchor_event}, do {habit_name}"
    message = coaching_voice.decision_prompt_line_builder(
        habit_name,
        None,
        "neutral",
        context,
    )
    return {
        "message": message,
        "type": "anchor_cue",
    }


# ── Keystone elevation ────────────────────────────────────────────────────────

def build_keystone_elevation(
    keystone_name: str,
    support_names: list[str],
    correlation_signal: dict,
) -> dict:
    """Elevate the keystone focus habit with associative, never causal language.

    Uses the H3 correlation_signal dict verbatim — no numbers are invented.
    When the signal carries a non-empty reason (insufficient data), returns
    a dict with available=False.

    Returns a dict with:
        message          str   (empty when available=False)
        keystone_role    "priority"
        support_names    list[str]
        available        bool
        reason           str   (non-empty when available=False)
    """
    reason = correlation_signal.get("reason", "")
    if reason:
        return {
            "message": "",
            "keystone_role": "priority",
            "support_names": list(support_names),
            "available": False,
            "reason": reason,
        }

    n = correlation_signal.get("n", 0)
    context = (
        f"tends to go along with {' and '.join(support_names)} "
        f"(n = {n}); focus here as your priority this week"
    )
    message = coaching_voice.praise_line_builder(
        keystone_name,
        None,
        "up",
        context,
    )
    return {
        "message": message,
        "keystone_role": "priority",
        "support_names": list(support_names),
        "available": True,
        "reason": "",
    }
