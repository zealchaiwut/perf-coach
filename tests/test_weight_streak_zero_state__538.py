"""
Tests for issue #538: Weight page streak badge zero-state copy.
One test per Acceptance Criterion — all are static file checks (no server needed).
"""
import re


WEIGHT_JS = "frontend/js/weight.js"
WEIGHT_HTML = "frontend/pages/weight.html"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# AC1: streak === 0 → "No streak yet"
def test_streak_zero_shows_no_streak_yet():
    """The JS ternary must handle streak===0 by returning 'No streak yet'."""
    src = _read(WEIGHT_JS)
    assert "No streak yet" in src, "weight.js must contain 'No streak yet' for streak===0"


# AC2: streak === 1 → "1-day streak" (unchanged)
def test_streak_one_shows_singular():
    """The JS ternary must still produce '1-day streak' for streak===1."""
    src = _read(WEIGHT_JS)
    assert "'1-day streak'" in src, "weight.js must contain '1-day streak' for streak===1"


# AC3: streak >= 2 → "${streak}-day streak" (unchanged)
def test_streak_plural_template_present():
    """The JS ternary must still produce the template literal for streak>=2."""
    src = _read(WEIGHT_JS)
    assert "`${streak}-day streak`" in src, "weight.js must contain template literal for streak>=2"


# AC4: initial HTML default must not be "0-day streak"
def test_html_default_is_not_zero_day_streak():
    """The initial HTML for #streak-value must not default to '0-day streak'."""
    src = _read(WEIGHT_HTML)
    assert "0-day streak" not in src, "weight.html must not contain '0-day streak' as default text"


# AC5: fix in the JS ternary covers all three cases in one expression
def test_js_ternary_covers_all_three_cases():
    """The ternary expression in weight.js must cover zero, one, and plural cases."""
    src = _read(WEIGHT_JS)
    # The three cases must all appear on the same logical line
    pattern = re.compile(
        r"streak === 0.*No streak yet.*streak === 1.*1-day streak.*\$\{streak\}-day streak",
        re.DOTALL,
    )
    assert pattern.search(src), (
        "weight.js ternary must cover all three cases: streak===0, ===1, >=2"
    )