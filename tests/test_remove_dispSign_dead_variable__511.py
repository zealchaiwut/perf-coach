"""
Tests for issue #511 — remove dead `dispSign` variable from _renderPastTargetsTable.
All ACs are static checks on the JS source file.
"""
import re
from pathlib import Path

WEIGHT_JS = Path(__file__).parents[1] / "frontend" / "js" / "weight.js"
SOURCE = WEIGHT_JS.read_text()


def test_dispSign_declaration_removed():
    """AC1: const dispSign = ... declaration must not exist anywhere in weight.js."""
    assert "dispSign" not in SOURCE, (
        "Dead variable 'dispSign' still present in weight.js"
    )


def test_sign_variable_still_present():
    """AC2: the `sign` variable must still be declared inside _renderPastTargetsTable."""
    func_match = re.search(
        r"function _renderPastTargetsTable\(.*?\}(?=\s*\nfunction |\s*\n//)",
        SOURCE,
        re.DOTALL,
    )
    assert func_match, "_renderPastTargetsTable function not found"
    func_body = func_match.group(0)
    assert re.search(r"\bconst sign\b", func_body), (
        "'sign' variable not declared inside _renderPastTargetsTable"
    )


def test_sign_used_in_template_string():
    """AC2: `sign` must appear in the template literal delta rendering."""
    func_match = re.search(
        r"function _renderPastTargetsTable\(.*?\}(?=\s*\nfunction |\s*\n//)",
        SOURCE,
        re.DOTALL,
    )
    assert func_match, "_renderPastTargetsTable function not found"
    func_body = func_match.group(0)
    # sign should appear in a template literal context
    assert re.search(r"\$\{sign\}", func_body), (
        "'sign' not used in a template string inside _renderPastTargetsTable"
    )


def test_no_dispSign_references_anywhere():
    """AC3: zero references to dispSign anywhere in the file."""
    matches = list(re.finditer(r"\bdispSign\b", SOURCE))
    assert len(matches) == 0, (
        f"Found {len(matches)} reference(s) to 'dispSign' in weight.js"
    )