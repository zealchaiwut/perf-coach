"""Tests for issue #1587: training-plan/log button-state bugs.

AC anchors verified:
  (a) _applyDraftWeek success path re-enables the Apply button (btn.disabled = false).
  (b) _loadWeek error (.catch) invokes the onDone callback so Save button is
      never stuck at "Saving…" after a successful PATCH + failed week reload.
  (c) Load-older keydown handler is guarded by a fired-once flag to prevent
      concurrent fetchAndRender(true) calls on rapid Enter/Space.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN_JS = (ROOT / "frontend" / "js" / "training-plan.js").read_text()
LOG_JS  = (ROOT / "frontend" / "js" / "training-log.js").read_text()


# ── Helper: extract a function or block ───────────────────────────────────────

def _extract_apply_draft_week(src):
    """Return the body of _applyDraftWeek (everything between its braces)."""
    m = re.search(r"function _applyDraftWeek\(\)\s*\{", src)
    assert m, "_applyDraftWeek not found in training-plan.js"
    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start:i - 1]


def _extract_load_week(src):
    """Return the body of _loadWeek (everything between its braces)."""
    # Phase B: optional opts (includeLoadPlan) — still the same onDone contract.
    m = re.search(r"function _loadWeek\(onDone(?:,\s*opts)?\)\s*\{", src)
    assert m, "_loadWeek(onDone[, opts]) not found in training-plan.js"
    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start:i - 1]


def _extract_then_catch(fn_body):
    """Split a function body at the first .catch( and return (then_part, catch_part)."""
    idx = fn_body.find(".catch(")
    assert idx != -1, ".catch not found in function body"
    return fn_body[:idx], fn_body[idx:]


# ── (a) _applyDraftWeek success path re-enables the button ───────────────────

def test_a_apply_draft_week_success_reenables_button():
    """After a successful POST /api/plan/draft/apply, btn.disabled must be reset to false (AC-a)."""
    body = _extract_apply_draft_week(PLAN_JS)
    then_part, catch_part = _extract_then_catch(body)

    # The success (.then) block must contain a statement that re-enables the button.
    # Accept either "btn.disabled = false" or "if (btn) btn.disabled = false".
    assert "btn.disabled = false" in then_part, (
        "_applyDraftWeek's success (.then) path does not re-enable the Apply button "
        "(btn.disabled = false missing before .catch). After a successful apply, a "
        "subsequent draft load can un-hide the same DOM node; if it is still disabled "
        "it becomes permanently unclickable until navigation."
    )


def test_a_apply_draft_week_catch_still_reenables_button():
    """The .catch path must still re-enable the button on failure (regression guard, AC-a)."""
    body = _extract_apply_draft_week(PLAN_JS)
    _, catch_part = _extract_then_catch(body)
    assert "btn.disabled = false" in catch_part, (
        "_applyDraftWeek's .catch path lost its existing btn.disabled = false."
    )


# ── (b) _loadWeek catch invokes onDone ───────────────────────────────────────

def test_b_load_week_catch_calls_on_done():
    """_loadWeek's .catch must call onDone (AC-b).

    When _smSave's PATCH succeeds but the follow-up week reload fails, the save
    button's onDone re-render is the only path that clears 'Saving…'. Without it,
    the button is permanently stuck disabled.
    """
    body = _extract_load_week(PLAN_JS)
    _, catch_part = _extract_then_catch(body)

    # Accept either direct "onDone()" or guarded "if (onDone) onDone()"
    has_on_done = "onDone()" in catch_part
    assert has_on_done, (
        "_loadWeek's .catch block does not call onDone(). If the week-reload GET "
        "fails after a successful PATCH, _smSave's Save button stays disabled "
        "reading 'Saving…' indefinitely."
    )


# ── (c) Load-older keydown guarded by fired-once flag ────────────────────────

def test_c_load_older_keydown_has_fired_once_guard():
    """The keydown handler on the Load-older sentinel must guard against double-fire (AC-c).

    The click handler is removed via removeEventListener but the anonymous keydown
    handler is never removed. Rapid Enter/Space fires fetchAndRender(true) concurrently.
    A 'fired' flag (or equivalent boolean guard) in triggerLoadOlder prevents this.
    """
    # Find the triggerLoadOlder function body
    m = re.search(r"var triggerLoadOlder\s*=\s*function\s*\(\)\s*\{", LOG_JS)
    assert m, "triggerLoadOlder not found in training-log.js"
    start = m.end()
    depth = 1
    i = start
    while i < len(LOG_JS) and depth:
        if LOG_JS[i] == "{":
            depth += 1
        elif LOG_JS[i] == "}":
            depth -= 1
        i += 1
    fn_body = LOG_JS[start:i - 1]

    # The body must contain an early-return guard (if ... return) to prevent re-fire.
    # Accept any boolean flag pattern: "if (_loadOlderFired) return",
    # "if (fired) return", "if (_fired) return", etc.
    has_guard = bool(re.search(r"if\s*\([^)]*[Ff]ired[^)]*\)\s*return", fn_body))
    assert has_guard, (
        "triggerLoadOlder does not have a fired-once guard. "
        "Rapid Enter/Space keydown events call fetchAndRender(true) concurrently. "
        "Add a boolean flag (e.g. _loadOlderFired) and check it at the top of "
        "triggerLoadOlder, returning early if already fired."
    )
