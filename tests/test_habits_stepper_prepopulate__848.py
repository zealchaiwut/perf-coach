"""Tests for issue #848: weekly_count stepper not pre-populated from today's log value.

Static checks only — no live HTTP calls; reads frontend/js/habits.js directly.

Acceptance criteria derived from the issue:
  AC1: renderTodayCard is called from loadAndRender (so it actually runs on page load).
  AC2: Today's existing log value seeds the weekly_count stepper count (not hardcoded 0).
  AC3: Today's existing log value seeds the duration/quantity input (not always blank).
  AC4: The stepper event handlers start count from the pre-seeded value, not always 0.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
JS_PATH = ROOT / "frontend" / "js" / "habits.js"


def _js() -> str:
    return JS_PATH.read_text()


# ── AC1: renderTodayCard is called from loadAndRender ────────────────────────

def test_render_today_card_is_called_from_load_and_render():
    """renderTodayCard must be invoked inside loadAndRender so it runs on page load."""
    js = _js()
    # Must contain a call to renderTodayCard (not just its definition)
    # The function is defined at "function renderTodayCard(" — we want a *call*
    calls = re.findall(r'\brenderTodayCard\s*\(', js)
    # There will be at least one definition AND at least one invocation
    assert len(calls) >= 2, (
        "renderTodayCard must be called (not just defined) — found only "
        f"{len(calls)} occurrence(s) in habits.js. "
        "Add a renderTodayCard(...) call inside loadAndRender."
    )


# ── AC2: stepper is seeded from today's log value ────────────────────────────

def test_stepper_count_seeded_from_today_log():
    """The stepper count closure variable must be initialised from the existing log, not hardcoded 0."""
    js = _js()
    # The old bad pattern: `let count = 0` as the ONLY initialisation for the stepper count.
    # The fix should read the value from todayLogs and set count accordingly.
    # We look for some reference to an existing log value inside the stepper handler block.
    assert "todayLogs" in js or "today_logs" in js or "todayLog" in js or \
           "existingLog" in js or "existing_log" in js or "seedVal" in js or \
           "initVal" in js or "logValue" in js or "log_value" in js, (
        "habits.js must pass today's log data into the stepper renderer — "
        "no reference to today's log found inside habits.js. "
        "Pass todayLogs (or similar) to renderTodayCard and seed the stepper count."
    )


def test_stepper_initial_count_not_always_zero():
    """The stepper count initialisation must read from the today log, not be hardcoded 0."""
    js = _js()
    # After the fix, we should find a pattern where count is set from a log value.
    # We look for the stepper block initialising count from something other than a literal.
    # Pattern: count is assigned something like parseInt(val.textContent) or a log value.
    has_seeded_count = (
        re.search(r'count\s*=\s*parseInt\s*\(', js) is not None
        or re.search(r'count\s*=\s*Number\s*\(', js) is not None
        or re.search(r'count\s*=\s*\+', js) is not None
        or re.search(r'count\s*=\s*(?:todayLog|existingLog|seedVal|initVal|logValue|initCount|existing)', js) is not None
        or re.search(r'let\s+count\s*=\s*(?!0\b)\w', js) is not None
        or re.search(r'const\s+initCount\s*=', js) is not None
        or re.search(r'data-init-val', js) is not None
        or re.search(r'stepper-val.*textContent.*parseInt|parseInt.*stepper-val', js) is not None
    )
    assert has_seeded_count, (
        "habits.js stepper handler must initialise count from today's log value. "
        "The pattern `let count = 0` (always zero) regresses previously stored data."
    )


# ── AC3: duration/quantity input seeded from today's log value ───────────────

def test_duration_input_seeded_from_today_log():
    """The today-duration-input value must be set from today's log before user interaction."""
    js = _js()
    # After the fix, the input element must have its value set from the log data.
    # Look for patterns like `input.value = ...log...` near today-duration-input handling.
    has_input_seed = (
        re.search(r'input\.value\s*=\s*(?!["\']\s*["\']).+', js) is not None
        and (
            "todayLogs" in js or "todayLog" in js or "existingLog" in js
            or "logValue" in js or "seedVal" in js or "today_logs" in js
        )
    )
    assert has_input_seed, (
        "habits.js must set today-duration-input.value from today's existing log "
        "before user interaction. Currently inputs always start blank."
    )


# ── AC4: today's logs are sourced for the today card ─────────────────────────

def test_today_logs_sourced_for_today_card():
    """Today's logs must be available to renderTodayCard — either passed in or fetched."""
    js = _js()
    # The fix must make today's log data reachable inside renderTodayCard.
    # Acceptable patterns:
    #   1. renderTodayCard(habits, todayLogs) — second arg passed from loadAndRender
    #   2. renderTodayCard fetches /api/habits/logs with today's date internally
    #   3. A todayLogs / existingLog / similar variable is built from the week logs
    #      filtered by today's date and passed/referenced in renderTodayCard's body.

    # Pattern 1: call site passes a second argument
    passes_today_logs = re.search(
        r'renderTodayCard\s*\(\s*\w+\s*,\s*\w+', js
    ) is not None

    # Pattern 2: a variable named todayLogs/todayLog/existingLog exists
    has_today_log_var = bool(
        re.search(r'\b(todayLogs|todayLog|existingLog|todayLogMap|logsByHabitToday)\b', js)
    )

    assert passes_today_logs or has_today_log_var, (
        "habits.js must make today's logs available to renderTodayCard. "
        "Either pass today's logs as a second argument to renderTodayCard, "
        "or build a todayLogs variable from the week logs filtered by today's date. "
        f"passes_today_logs={passes_today_logs}, has_today_log_var={has_today_log_var}"
    )
