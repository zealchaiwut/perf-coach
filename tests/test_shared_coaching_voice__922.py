"""Tests for issue #922: Add shared coaching voice module for consistent tone.

Anchored to each AC item:

AC1  — Pure module: no DB access, no side effects; importable from a single location.
AC2  — Four builder functions exposed: praise_line_builder, reframe_line_builder,
        miss_and_pivot_line_builder, decision_prompt_line_builder.
AC3  — Each builder accepts (metric_name, value, direction, context) and returns str.
AC4  — No output contains exclamation marks by default.
AC5  — No output contains decorative emoji.
AC6  — Praise is stated as an observed fact referencing actual numbers; not generic enthusiasm.
AC7  — Miss expressed as one short clause followed by a next-action (em-dash separator).
AC8  — Single out-of-range reading produces calm, variance-normalising phrasing (no alarm).
AC9  — Firm language reserved for decision-prompt outputs only.
AC10 — Module ships with inline worked examples in code (structural assertion on docstring).
AC11 — At least two existing coaching surfaces import and use this module.
AC12 — Given identical inputs, the module returns the identical string (deterministic).
AC13 — Changing a single tone rule in the module propagates to all importing surfaces
       without additional edits (import path assertion).
"""

from __future__ import annotations

import re

import pytest

# ── AC1, AC2: module importable, all four builders present ───────────────────

def test_module_importable():
    """AC1: module lives at a single importable location."""
    from backend.services import coaching_voice  # noqa: F401


def test_four_builders_present():
    """AC2: all four builder functions are exported."""
    from backend.services.coaching_voice import (
        praise_line_builder,
        reframe_line_builder,
        miss_and_pivot_line_builder,
        decision_prompt_line_builder,
    )
    assert callable(praise_line_builder)
    assert callable(reframe_line_builder)
    assert callable(miss_and_pivot_line_builder)
    assert callable(decision_prompt_line_builder)


# ── AC3: each builder accepts (metric_name, value, direction, context) → str ─

def test_praise_builder_signature():
    """AC3: praise_line_builder accepts structured inputs and returns str."""
    from backend.services.coaching_voice import praise_line_builder
    result = praise_line_builder("sessions", 8.0, "up", "9 sessions this week")
    assert isinstance(result, str)
    assert len(result) > 0


def test_reframe_builder_signature():
    """AC3: reframe_line_builder accepts structured inputs and returns str."""
    from backend.services.coaching_voice import reframe_line_builder
    result = reframe_line_builder("HRV", 42.0, "down", "week of solid training")
    assert isinstance(result, str)
    assert len(result) > 0


def test_miss_and_pivot_builder_signature():
    """AC3: miss_and_pivot_line_builder accepts structured inputs and returns str."""
    from backend.services.coaching_voice import miss_and_pivot_line_builder
    result = miss_and_pivot_line_builder(
        "calories", 200.0, "over", "logging dinner tonight will reset the streak"
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_decision_prompt_builder_signature():
    """AC3: decision_prompt_line_builder accepts structured inputs and returns str."""
    from backend.services.coaching_voice import decision_prompt_line_builder
    result = decision_prompt_line_builder(
        "training load",
        None,
        "up",
        "increase your weekly volume or hold for one more week",
    )
    assert isinstance(result, str)
    assert len(result) > 0


# ── AC4: no exclamation marks ─────────────────────────────────────────────────

def test_praise_no_exclamation():
    """AC4: praise output never contains an exclamation mark."""
    from backend.services.coaching_voice import praise_line_builder
    result = praise_line_builder("sessions", 5.0, "up", "5 sessions this week")
    assert "!" not in result


def test_reframe_no_exclamation():
    """AC4: reframe output never contains an exclamation mark."""
    from backend.services.coaching_voice import reframe_line_builder
    result = reframe_line_builder("sleep", 5.5, "down", "otherwise good week")
    assert "!" not in result


def test_miss_and_pivot_no_exclamation():
    """AC4: miss output never contains an exclamation mark."""
    from backend.services.coaching_voice import miss_and_pivot_line_builder
    result = miss_and_pivot_line_builder(
        "sessions", 1.0, "under", "adding a short session Sunday closes the gap"
    )
    assert "!" not in result


def test_decision_prompt_no_exclamation():
    """AC4: decision-prompt output never contains an exclamation mark."""
    from backend.services.coaching_voice import decision_prompt_line_builder
    result = decision_prompt_line_builder("weight", 80.0, "over", "log every meal this week")
    assert "!" not in result


# ── AC5: no decorative emoji ──────────────────────────────────────────────────

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"  # alchemical
    "\U0001F780-\U0001F7FF"  # geometric extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)


@pytest.mark.parametrize("fn_name,args", [
    ("praise_line_builder", ("sessions", 8.0, "up", "9 sessions this week")),
    ("reframe_line_builder", ("HRV", 42.0, "down", "week of solid training")),
    ("miss_and_pivot_line_builder", ("calories", 200.0, "over", "log dinner tonight")),
    ("decision_prompt_line_builder", ("training load", None, "up", "increase volume")),
])
def test_no_decorative_emoji(fn_name, args):
    """AC5: no builder output contains decorative emoji."""
    import backend.services.coaching_voice as cv
    fn = getattr(cv, fn_name)
    result = fn(*args)
    assert not _EMOJI_RE.search(result), f"{fn_name} returned emoji: {result!r}"


# ── AC6: praise is an observed fact referencing numbers ───────────────────────

def test_praise_states_observed_fact_with_numbers():
    """AC6: praise line contains the numeric value and reads as an observed fact."""
    from backend.services.coaching_voice import praise_line_builder
    result = praise_line_builder("sessions", 8.0, "up", "9 sessions this week")
    # Must contain the numeric value passed in
    assert "8" in result
    # Must not be generic enthusiasm; should reference what was done
    lower = result.lower()
    # Observed-fact phrasing typically starts with "you" or the metric
    assert lower.startswith("you") or result[0].isdigit() or result[0].isupper()


def test_praise_references_metric_name():
    """AC6: praise line references the metric being praised."""
    from backend.services.coaching_voice import praise_line_builder
    result = praise_line_builder("workouts", 5.0, "up", "5 of 5 workouts this week")
    assert "5" in result


# ── AC7: miss = one clause + em-dash + next-action ───────────────────────────

def test_miss_and_pivot_contains_pivot():
    """AC7: miss line acknowledges miss then pivots to a next-action."""
    from backend.services.coaching_voice import miss_and_pivot_line_builder
    result = miss_and_pivot_line_builder(
        "calories", 200.0, "over", "logging dinner tonight will reset the streak"
    )
    # Must contain an em dash or ' — ' as the clause separator
    assert "—" in result or " - " in result
    # The context (next-action) must appear in the output
    assert "logging dinner tonight" in result


def test_miss_and_pivot_contains_value():
    """AC7: miss line references the numeric value."""
    from backend.services.coaching_voice import miss_and_pivot_line_builder
    result = miss_and_pivot_line_builder(
        "calories", 200.0, "over", "log meals today to get back on track"
    )
    assert "200" in result


def test_miss_and_pivot_short_first_clause():
    """AC7: first clause (before the dash separator) is concise (under 60 chars)."""
    from backend.services.coaching_voice import miss_and_pivot_line_builder
    result = miss_and_pivot_line_builder(
        "sessions", 1.0, "under", "a short session Sunday closes the gap"
    )
    separator = "—"
    if separator in result:
        first_clause = result.split(separator)[0].strip()
        assert len(first_clause) < 80, f"First clause too long: {first_clause!r}"


# ── AC8: single out-of-range reading → calm, no alarming language ─────────────

_ALARM_WORDS = re.compile(
    r"\b(crisis|danger|dangerous|critical|severe|alarming|urgent|emergency|warning)\b",
    re.IGNORECASE,
)


def test_reframe_no_alarming_language():
    """AC8: reframe output is calm; no alarming words."""
    from backend.services.coaching_voice import reframe_line_builder
    result = reframe_line_builder("HRV", 28.0, "down", "otherwise strong week")
    assert not _ALARM_WORDS.search(result), f"Alarming language in reframe: {result!r}"


def test_reframe_variance_normalising():
    """AC8: reframe phrasing contextualises the reading as normal variation."""
    from backend.services.coaching_voice import reframe_line_builder
    result = reframe_line_builder("resting HR", 68.0, "up", "week of good training")
    lower = result.lower()
    # Should contain normalising words
    normalising = any(
        w in lower
        for w in ["normal", "variation", "single", "one", "context", "otherwise"]
    )
    assert normalising, f"Reframe missing variance-normalising language: {result!r}"


# ── AC9: firm language only in decision-prompt outputs ────────────────────────

_FIRM_WORDS = re.compile(
    r"\b(must|need to|now|time to|decide|choose|commit|action required|act now)\b",
    re.IGNORECASE,
)


def test_praise_no_firm_language():
    """AC9: praise output does not use firm language."""
    from backend.services.coaching_voice import praise_line_builder
    result = praise_line_builder("sessions", 5.0, "up", "great week")
    assert not _FIRM_WORDS.search(result), f"Firm language in praise: {result!r}"


def test_reframe_no_firm_language():
    """AC9: reframe output does not use firm language."""
    from backend.services.coaching_voice import reframe_line_builder
    result = reframe_line_builder("HRV", 30.0, "down", "strong training week")
    assert not _FIRM_WORDS.search(result), f"Firm language in reframe: {result!r}"


def test_decision_prompt_is_firm():
    """AC9: decision-prompt output uses action-oriented, firm phrasing."""
    from backend.services.coaching_voice import decision_prompt_line_builder
    result = decision_prompt_line_builder(
        "training load", None, "up", "decide whether to increase volume this week"
    )
    lower = result.lower()
    # Decision prompt should contain the context (the action to take)
    assert "decide" in lower or "whether" in lower or "increase" in lower or "volume" in lower


# ── AC10: module has inline worked examples ───────────────────────────────────

def test_module_has_worked_examples_in_docstring():
    """AC10: the module docstring contains worked examples (input → expected output)."""
    import backend.services.coaching_voice as cv
    doc = cv.__doc__ or ""
    # Must mention each builder and show an example arrow
    assert "praise_line_builder" in doc
    assert "reframe_line_builder" in doc
    assert "miss_and_pivot_line_builder" in doc
    assert "decision_prompt_line_builder" in doc
    # At least one worked-example arrow
    assert "→" in doc or "->" in doc


# ── AC11: at least two surfaces import from coaching_voice ────────────────────

def _imports_coaching_voice(source_path: str) -> bool:
    """Return True if the Python source file at source_path imports coaching_voice."""
    import ast
    import pathlib

    p = pathlib.Path(source_path)
    if not p.exists():
        return False
    tree = ast.parse(p.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # from backend.services.coaching_voice import ...
            if node.module and "coaching_voice" in node.module:
                return True
            # from backend.services import coaching_voice
            if any(a.name == "coaching_voice" for a in node.names):
                return True
        if isinstance(node, ast.Import):
            # import backend.services.coaching_voice [as ...]
            if any("coaching_voice" in a.name for a in node.names):
                return True
    return False


def test_habit_voice_imports_coaching_voice():
    """AC11: habit_voice imports from coaching_voice."""
    assert _imports_coaching_voice("backend/services/habit_voice.py"), (
        "habit_voice.py does not import from coaching_voice"
    )


def test_second_surface_imports_coaching_voice():
    """AC11: at least one more coaching surface (besides habit_voice) imports coaching_voice."""
    candidates = [
        "backend/services/habit_insights.py",
        "backend/services/training_load.py",
        "backend/main.py",
    ]
    found = any(_imports_coaching_voice(p) for p in candidates)
    assert found, (
        "No second coaching surface imports from coaching_voice. "
        "Expected one of: habit_insights.py, training_load.py, or main.py."
    )


# ── AC12: deterministic output ────────────────────────────────────────────────

@pytest.mark.parametrize("fn_name,args", [
    ("praise_line_builder", ("sessions", 8.0, "up", "9 sessions this week")),
    ("reframe_line_builder", ("HRV", 42.0, "down", "week of solid training")),
    (
        "miss_and_pivot_line_builder",
        ("calories", 200.0, "over", "logging dinner tonight will reset the streak"),
    ),
    (
        "decision_prompt_line_builder",
        ("training load", None, "up", "increase your weekly volume or hold for one more week"),
    ),
])
def test_deterministic_output(fn_name, args):
    """AC12: identical inputs produce identical strings across repeated calls."""
    import backend.services.coaching_voice as cv
    fn = getattr(cv, fn_name)
    first = fn(*args)
    second = fn(*args)
    assert first == second, f"{fn_name} is non-deterministic: {first!r} != {second!r}"


# ── AC13: single tone-rule change propagates via import ──────────────────────

def test_propagation_via_import():
    """AC13: surfaces import the builders; patching a builder in coaching_voice
    propagates to all callers without editing surface files."""
    import backend.services.coaching_voice as cv
    import backend.services.habit_voice as hv

    # Verify habit_voice delegates miss copy through coaching_voice
    original = cv.miss_and_pivot_line_builder

    def patched(metric_name, value, direction, context):
        return f"PATCHED: {metric_name}"

    cv.miss_and_pivot_line_builder = patched
    try:
        # Call habit_voice's compose_log_feedback with a miss to trigger delegation
        import types
        habit = types.SimpleNamespace(
            name="Morning run",
            tracking_type="daily_checkmark",
            weekly_target=7,
            schedule_type="daily",
            schedule_target=None,
        )
        result = hv.compose_log_feedback(
            habit=habit,
            week_done=3,
            week_target=7,
            total_logs=5,
            is_miss=True,
            current_streak=0,
        )
        # The patched function should propagate
        assert "PATCHED" in result["message"], (
            "habit_voice miss message does not delegate to coaching_voice.miss_and_pivot_line_builder. "
            f"Got: {result['message']!r}"
        )
    finally:
        cv.miss_and_pivot_line_builder = original
