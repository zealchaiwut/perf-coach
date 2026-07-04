"""
Tests for issue #510 — remove dead `_cardBEntryNotes` variable from weight.js.
All ACs are static checks on the JS source file.

The variable was already removed by a prior deadcode cleanup commit; these
tests formally anchor all five AC items so a regression would be caught.
"""
import re
from pathlib import Path

WEIGHT_JS = Path(__file__).parents[1] / "frontend" / "js" / "weight.js"
SOURCE = WEIGHT_JS.read_text()


def test_cardBEntryNotes_declaration_removed():
    """AC1: let _cardBEntryNotes = null declaration must not exist anywhere in weight.js."""
    assert "_cardBEntryNotes" not in SOURCE, (
        "Dead variable '_cardBEntryNotes' declaration still present in weight.js"
    )


def test_no_cardBEntryNotes_assignments_in_cardBSetLoggedState():
    """AC2: both assignment sites inside _cardBSetLoggedState must be gone."""
    func_match = re.search(
        r"function _cardBSetLoggedState\b.*?\}(?=\s*\n(?:function |//))",
        SOURCE,
        re.DOTALL,
    )
    assert func_match, "_cardBSetLoggedState function not found in weight.js"
    func_body = func_match.group(0)
    assert "_cardBEntryNotes" not in func_body, (
        "Assignment to '_cardBEntryNotes' still present inside _cardBSetLoggedState"
    )


def test_no_cardBEntryNotes_references_anywhere():
    """AC3: zero references to _cardBEntryNotes anywhere in the file."""
    matches = list(re.finditer(r"\b_cardBEntryNotes\b", SOURCE))
    assert len(matches) == 0, (
        f"Found {len(matches)} reference(s) to '_cardBEntryNotes' in weight.js"
    )


def test_edit_link_handler_reads_dataset_directly():
    """AC4: the edit-link handler reads from logged.dataset directly (no notes variable intermediary)."""
    edit_handler_match = re.search(
        r"editBtn\.addEventListener\('click'.*?\}\s*\)",
        SOURCE,
        re.DOTALL,
    )
    assert edit_handler_match, "edit-link addEventListener handler not found in weight.js"
    handler_body = edit_handler_match.group(0)
    assert "logged.dataset" in handler_body, (
        "edit-link handler does not read from logged.dataset directly"
    )
    assert "_cardBEntryNotes" not in handler_body, (
        "edit-link handler still references dead '_cardBEntryNotes' variable"
    )


def test_cardBSetLoggedState_still_sets_dataset_weight():
    """AC4 (invariant): _cardBSetLoggedState still sets logged.dataset.weight for the edit-link handler to read."""
    func_match = re.search(
        r"function _cardBSetLoggedState\b.*?\}(?=\s*\n(?:function |//))",
        SOURCE,
        re.DOTALL,
    )
    assert func_match, "_cardBSetLoggedState function not found in weight.js"
    func_body = func_match.group(0)
    assert "logged.dataset.weight" in func_body, (
        "_cardBSetLoggedState no longer sets logged.dataset.weight — edit-link handler will break"
    )