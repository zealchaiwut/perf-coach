"""Shared coaching voice module — single source of tone for all coaching surfaces.

Pure formatting module: no database access, no mutations, no global state.
All coaching string templates live here so that a single phrase edit propagates
to every surface that imports from this module.

Four builder functions
----------------------
praise_line_builder(metric_name, value, direction, context)
    State an observed fact. Reference the user's actual numbers. No enthusiasm.

reframe_line_builder(metric_name, value, direction, context)
    Normalise a single out-of-range reading with calm, contextual phrasing.
    Never use alarming language for a lone data point.

miss_and_pivot_line_builder(metric_name, value, direction, context)
    Acknowledge a miss in one short clause, then pivot immediately to a
    concrete next action (separated by an em dash).

decision_prompt_line_builder(metric_name, value, direction, context)
    Firm, action-oriented copy. The only place where directive language is
    appropriate. All other builders use softer, observational phrasing.

Common signature for all builders
----------------------------------
    metric_name : str   — the metric being discussed (e.g. "sessions", "HRV")
    value       : float | None — the numeric value to reference (e.g. 8.0)
    direction   : str   — "up" | "down" | "over" | "under" | "neutral"
    context     : str   — surface-supplied clause (next action, comparator, etc.)

Returns: str — a plain-language coaching string.

Rules (enforced by tests)
--------------------------
- No output contains exclamation marks.
- No output contains decorative emoji.
- Praise references actual numbers and reads as an observed fact.
- Miss lines contain an em dash (—) separating the clause from the pivot.
- Reframe lines contain normalising language ("normal variation", "single", etc.).
- Decision-prompt lines are the only outputs that may use directive language.
- All builders are deterministic: identical inputs → identical strings.

Worked examples
---------------
praise_line_builder("sessions", 8.0, "up", "9 sessions targeted this week"):
    → "You hit 8.0 sessions — 9 sessions targeted this week."

praise_line_builder("workouts", 5.0, "up", "5 of 5 workouts completed"):
    → "You completed 5.0 workouts — 5 of 5 workouts completed."

reframe_line_builder("HRV", 42.0, "down", "week of solid training"):
    → "One lower HRV reading in a week of solid training is normal variation."

reframe_line_builder("resting HR", 68.0, "up", "strong training block"):
    → "A single elevated resting HR reading during a strong training block is normal variation."

miss_and_pivot_line_builder("calories", 200.0, "over", "logging dinner tonight will reset the streak"):
    → "You were 200 calories over — logging dinner tonight will reset the streak."

miss_and_pivot_line_builder("sessions", 1.0, "under", "a short session Sunday closes the gap"):
    → "You were 1 session under — a short session Sunday closes the gap."

decision_prompt_line_builder("training load", None, "up", "increase your weekly volume or hold for one more week"):
    → "Your training load is rising: increase your weekly volume or hold for one more week."

decision_prompt_line_builder("weight", 80.0, "over", "log every meal this week"):
    → "Your weight is above target: log every meal this week."
"""

from __future__ import annotations


def praise_line_builder(
    metric_name: str,
    value: float | None,
    direction: str,
    context: str,
) -> str:
    """Return an observed-fact praise string referencing the user's actual numbers.

    Worked example:
        praise_line_builder("sessions", 8.0, "up", "9 sessions targeted this week")
        → "You hit 8.0 sessions — 9 sessions targeted this week."
    """
    if value is None:
        return f"You are on track with {metric_name} — {context}."

    verb = _praise_verb(direction)
    formatted_value = _format_value(value)
    return f"You {verb} {formatted_value} {metric_name} — {context}."


def reframe_line_builder(
    metric_name: str,
    value: float | None,
    direction: str,
    context: str,
) -> str:
    """Return calm, variance-normalising phrasing for a single out-of-range reading.

    Worked example:
        reframe_line_builder("HRV", 42.0, "down", "week of solid training")
        → "One lower HRV reading in a week of solid training is normal variation."
    """
    qualifier = _reframe_qualifier(direction)
    return (
        f"A single {qualifier} {metric_name} reading in {context} "
        f"is normal variation."
    )


def miss_and_pivot_line_builder(
    metric_name: str,
    value: float | None,
    direction: str,
    context: str,
) -> str:
    """Return a miss clause followed by a next-action pivot (em-dash separated).

    Worked example:
        miss_and_pivot_line_builder("calories", 200.0, "over",
                                    "logging dinner tonight will reset the streak")
        → "You were 200 calories over — logging dinner tonight will reset the streak."
    """
    miss_clause = _miss_clause(metric_name, value, direction)
    return f"{miss_clause} — {context}."


def decision_prompt_line_builder(
    metric_name: str,
    value: float | None,
    direction: str,
    context: str,
) -> str:
    """Return firm, action-oriented copy for a choice the user must make.

    Firm language is reserved for this builder only. All other builders use
    observational, softer phrasing.

    Worked example:
        decision_prompt_line_builder("training load", None, "up",
                                     "increase your weekly volume or hold for one more week")
        → "Your training load is rising: increase your weekly volume or hold for one more week."
    """
    state = _direction_state(metric_name, value, direction)
    return f"Your {metric_name} is {state}: {context}."


# ── Internal helpers ──────────────────────────────────────────────────────────

def _format_value(value: float) -> str:
    """Format a numeric value: integer-looking floats drop the decimal."""
    if value == int(value):
        return str(int(value))
    return str(value)


def _praise_verb(direction: str) -> str:
    """Return an observed-fact verb for the given direction."""
    return {
        "up": "hit",
        "down": "maintained",
        "over": "exceeded",
        "under": "achieved",
        "neutral": "completed",
    }.get(direction, "completed")


def _reframe_qualifier(direction: str) -> str:
    """Return a calm, descriptive qualifier for a reframe."""
    return {
        "up": "elevated",
        "down": "lower",
        "over": "above-range",
        "under": "below-range",
        "neutral": "atypical",
    }.get(direction, "atypical")


def _miss_clause(metric_name: str, value: float | None, direction: str) -> str:
    """Return the short acknowledgement clause for a miss line."""
    if value is None:
        prep = _direction_prep(direction)
        return f"You were {prep} on {metric_name}"
    formatted = _format_value(value)
    units = _direction_units(metric_name, direction)
    return f"You were {formatted} {units}"


def _direction_prep(direction: str) -> str:
    return {
        "over": "over",
        "under": "short",
        "up": "high",
        "down": "low",
        "neutral": "off",
    }.get(direction, "off")


def _direction_units(metric_name: str, direction: str) -> str:
    """Return '<metric_name> <over|under|...>' for the miss clause."""
    prep = {
        "over": "over",
        "under": "under",
        "up": f"{metric_name} above target",
        "down": f"{metric_name} below target",
        "neutral": f"{metric_name} off target",
    }.get(direction)
    if prep in ("over", "under"):
        return f"{metric_name} {prep}"
    return prep or f"{metric_name} off"


def _direction_state(metric_name: str, value: float | None, direction: str) -> str:
    """Return a short, firm state description for a decision prompt."""
    return {
        "up": "rising",
        "down": "falling",
        "over": "above target",
        "under": "below target",
        "neutral": "at a crossroads",
    }.get(direction, "changing")


def correlation_line_builder(
    habit_name: str,
    label: str,
    context: str,
) -> str:
    """Return an associative correlation insight string.

    Uses logging-framing ("Logging X is associated with...") rather than
    progress-tracking framing ("You are on track with...").  Correlation
    insights are observational — they never imply goal attainment.

    Worked example:
        correlation_line_builder(
            "Morning Run", "Energy",
            "associated with higher 'Energy' scores on the same day"
        )
        → "Logging 'Morning Run' is associated with higher 'Energy' scores on the same day."
    """
    return f"Logging '{habit_name}' is {context}."
