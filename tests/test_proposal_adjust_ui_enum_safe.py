"""Adjust... on a preference proposal must not offer a broken flow for
enum-valued fields.

Found during review of #1643 (gap-analysis proposals expanded to cover
strength_lapsed/muscle_overused/muscle_untrained, all mapping to the enum
field strength_emphasis): the "Adjust..." button asks for a custom value via
window.prompt() and both the frontend parse (Number(raw)) and the backend
accept_proposal() adjust path (int(adjusted_to)) are int-only. Typing "less"
into that numeric prompt failed with a confusing "Enter a number" — it worked
fine before this PR because the only two proposal-eligible fields
(plyo_sessions_per_week, long_run.mp_segment_min) are both ints.

Fix: hide Adjust for proposals whose delta.to isn't numeric. Accept and
Decline are unaffected — accept applies the pre-computed delta.to with no
client-side parsing, so it already works correctly for enum proposals.

Static source check only — no live server needed, mirrors this repo's other
frontend regex-ratchet tests (e.g. test_reachability_gate__1602.py) rather
than exercising the DOM.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRAINING_PLAN_JS = (REPO / "frontend" / "js" / "training-plan.js").read_text()


def test_isnumericdelta_helper_exists():
    assert "_isNumericDelta" in TRAINING_PLAN_JS


def test_adjust_button_is_conditional_on_numeric_delta():
    """The Adjust button markup must be gated behind _isNumericDelta(p), not
    unconditionally rendered — a regression here silently reopens the bug."""
    idx = TRAINING_PLAN_JS.index("pl-prop-adjust")
    window = TRAINING_PLAN_JS[max(0, idx - 400):idx]
    assert "_isNumericDelta(p)" in window, (
        "the Adjust button's rendering no longer appears to be gated by "
        "_isNumericDelta — enum-valued proposals (e.g. strength_emphasis) "
        "would offer a numeric-only prompt again"
    )


def test_isnumericdelta_accepts_numbers_and_numeric_strings():
    m = re.search(
        r"function _isNumericDelta\(p\)\s*\{(.*?)\n  \}",
        TRAINING_PLAN_JS, re.S,
    )
    assert m, "could not locate _isNumericDelta's body"
    body = m.group(1)
    assert "typeof to === 'number'" in body
    assert "typeof to === 'string'" in body


def test_adjust_click_handler_still_guards_on_element_presence():
    """_bindProposalActions must still null-check the (possibly absent)
    adjust button rather than assume it's always in the DOM."""
    idx = TRAINING_PLAN_JS.index("querySelector('.pl-prop-adjust')")
    window = TRAINING_PLAN_JS[idx:idx + 120]
    assert "if (adjust)" in window
