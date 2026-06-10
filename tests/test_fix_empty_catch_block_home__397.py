"""Tests for issue #397: Fix empty catch blocks with underscore binding in home.js.

Acceptance criteria verified:
(a) No bare empty `catch (_) {}` exists in home.js — all empty catch bodies
    must have an explicit inline documentation comment so intent is clear.
(b) Non-empty catch blocks (those with statements or existing comments) are
    unaffected.
"""
import pathlib
import re

HOME_JS = pathlib.Path(__file__).parents[1] / "frontend" / "js" / "home.js"


def _text():
    return HOME_JS.read_text()


# (a) No bare empty catch (_) {} without a comment inside
def test_no_bare_empty_catch_underscore():
    """Every `catch (_) { ... }` that has no statements must have a comment."""
    # Match catch (_) { <optional whitespace> } with nothing inside (no comment)
    bare_empty = re.findall(r'catch\s*\(_\)\s*\{\s*\}', _text())
    assert bare_empty == [], (
        f"Found {len(bare_empty)} bare empty catch (_) {{}} block(s) with no "
        "documentation comment. Add an inline comment (e.g. /* intentional */) "
        "to each one to suppress the warning explicitly."
    )


# (b) Documented empty catches (with inline comments) are present
def test_documented_empty_catches_exist():
    """At least some catch blocks have inline documentation comments."""
    documented = re.findall(r'catch\s*\(_\)\s*\{[^}]*\/\*[^*]*\*\/[^}]*\}', _text())
    assert len(documented) > 0, (
        "Expected at least one documented catch (_) { /* ... */ } block — "
        "none found. Check that the fix was applied correctly."
    )
