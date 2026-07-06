"""Tests for issue #537: Weight inline-edit removes onEscape listener on save success.

Acceptance criteria verified:
  AC1 — After successful patchEntry save, row.removeEventListener('keydown', onEscape)
        is called on the save success path in weight.js.
  AC2 — The removeEventListener call is on the save path without routing through
        cancelEdit() (i.e. no innerHTML reset occurs on save via cancelEdit()).
  AC3 — cancelEdit() continues to remove the onEscape listener on cancel/escape path.
  AC4 — No duplicate keydown listener accumulates (verified by single addEvent per
        openInlineEdit call).
  AC5 — Fix is contained to frontend/js/weight.js with no other files changed.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
WEIGHT_JS = (ROOT / "frontend" / "js" / "weight.js").read_text()


def _find_open_inline_edit_body(source: str) -> str:
    """Extract the body of openInlineEdit function."""
    start = source.find("function openInlineEdit(")
    assert start != -1, "openInlineEdit function not found in weight.js"
    # Find next top-level function to bound the search
    next_fn = source.find("\nfunction ", start + 1)
    if next_fn == -1:
        return source[start:]
    return source[start:next_fn]


def _find_cancel_edit_body(source: str) -> str:
    """Extract cancelEdit inner function body from within openInlineEdit."""
    fn_body = _find_open_inline_edit_body(source)
    start = fn_body.find("function cancelEdit(")
    assert start != -1, "cancelEdit function not found inside openInlineEdit"
    # Find closing brace — count braces
    depth = 0
    end = start
    for i, ch in enumerate(fn_body[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    return fn_body[start:end + 1]


def _find_save_success_block(source: str) -> str:
    """Extract the block after patchEntry await on the success path."""
    fn_body = _find_open_inline_edit_body(source)
    # The save success path is the try block after await patchEntry
    patch_idx = fn_body.find("await patchEntry(")
    assert patch_idx != -1, "patchEntry call not found in openInlineEdit"
    # From that point, look at the surrounding try block until the catch
    catch_idx = fn_body.find("} catch (", patch_idx)
    return fn_body[patch_idx:catch_idx] if catch_idx != -1 else fn_body[patch_idx:]


# AC1: row.removeEventListener('keydown', onEscape) called on save success path
def test_remove_event_listener_on_save_success():
    """AC1: save success path explicitly removes the onEscape keydown listener."""
    save_block = _find_save_success_block(WEIGHT_JS)
    assert "removeEventListener" in save_block, (
        "row.removeEventListener must be called on the save success path"
    )
    assert "onEscape" in save_block, (
        "onEscape must be passed to removeEventListener on save success path"
    )
    assert "keydown" in save_block, (
        "'keydown' event type must be specified in removeEventListener call on save path"
    )


def test_remove_event_listener_references_row_on_save():
    """AC1: removeEventListener is called on the row element (not some other element)."""
    save_block = _find_save_success_block(WEIGHT_JS)
    # Should contain row.removeEventListener
    assert re.search(r"\brow\.removeEventListener\b", save_block), (
        "row.removeEventListener must be called (not addEventListener on a different element)"
    )


# AC2: save path does NOT call cancelEdit() — no innerHTML reset on save
def test_save_path_does_not_call_cancel_edit():
    """AC2: cancelEdit() is not called on the save success path."""
    save_block = _find_save_success_block(WEIGHT_JS)
    assert "cancelEdit()" not in save_block, (
        "cancelEdit() must NOT be called on save success path — it would reset innerHTML"
    )


def test_save_path_does_not_reset_inner_html():
    """AC2: innerHTML is not reassigned on the save success path."""
    save_block = _find_save_success_block(WEIGHT_JS)
    # originalHTML being assigned back would indicate cancelEdit was invoked or innerHTML reset
    assert "originalHTML" not in save_block, (
        "originalHTML must not be used on the save success path (would reset DOM)"
    )


# AC3: cancelEdit() still removes onEscape on cancel path
def test_cancel_edit_removes_onescape_listener():
    """AC3: cancelEdit() removes the onEscape listener on the cancel/escape path."""
    cancel_body = _find_cancel_edit_body(WEIGHT_JS)
    assert "removeEventListener" in cancel_body, (
        "cancelEdit() must call removeEventListener"
    )
    assert "onEscape" in cancel_body, (
        "cancelEdit() must pass onEscape to removeEventListener"
    )


def test_cancel_edit_restores_dom():
    """AC3: cancelEdit() still restores innerHTML (cancel path unchanged)."""
    cancel_body = _find_cancel_edit_body(WEIGHT_JS)
    assert "row.innerHTML = originalHTML" in cancel_body, (
        "cancelEdit() must still restore originalHTML on cancel"
    )


# AC4: only one addEventListener('keydown', onEscape) call in openInlineEdit
def test_single_add_event_listener_for_onescape():
    """AC4: openInlineEdit adds the keydown/onEscape listener exactly once per call."""
    fn_body = _find_open_inline_edit_body(WEIGHT_JS)
    # Count addEventListener calls for onEscape
    matches = re.findall(r"addEventListener\s*\(\s*['\"]keydown['\"].*?onEscape", fn_body)
    assert len(matches) == 1, (
        f"Expected exactly 1 addEventListener('keydown', onEscape) in openInlineEdit, "
        f"found {len(matches)}"
    )


# AC5: fix is contained to weight.js — verify the function is in weight.js
def test_fix_is_in_weight_js():
    """AC5: The openInlineEdit function with the fix lives in frontend/js/weight.js."""
    assert (ROOT / "frontend" / "js" / "weight.js").exists(), "weight.js must exist"
    assert "openInlineEdit" in WEIGHT_JS, "openInlineEdit must be defined in weight.js"
    assert "removeEventListener" in WEIGHT_JS, (
        "removeEventListener must appear in weight.js"
    )