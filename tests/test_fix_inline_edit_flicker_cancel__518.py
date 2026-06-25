"""Tests for issue #518: Fix inline-edit flicker and heavy cancel on weight rows.

Acceptance criteria verified:
(a) JS: openInlineEdit saves original row innerHTML before overwriting it
(b) JS: Cancel button restores original DOM — does NOT call _reload()
(c) JS: Escape key restores original DOM — does NOT call _reload()
(d) JS: Save success updates only affected row (no full _reload() on success)
(e) JS: Save network error shows inline error and stays in edit mode (no _reload())
"""
import pathlib
import re

_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_CODER_ROOT, _TESTER_ROOT):
        js = root / "frontend" / "js" / "weight.js"
        if js.exists() and "openInlineEdit" in js.read_text():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_WEIGHT_JS = (_ROOT / "frontend" / "js" / "weight.js").read_text()


def _extract_open_inline_edit(js: str) -> str:
    """Return the body of openInlineEdit from opening brace to its closing brace."""
    start = js.find("function openInlineEdit(")
    assert start != -1, "openInlineEdit not found in weight.js"
    depth = 0
    i = start
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start : i + 1]
        i += 1
    return js[start:]


_OPEN_INLINE = _extract_open_inline_edit(_WEIGHT_JS)


# ── (a) JS: originalHTML saved before innerHTML overwrite ─────────────────────

def test_original_html_saved_before_overwrite():
    """openInlineEdit must snapshot the original row innerHTML before overwriting."""
    js = _OPEN_INLINE
    # Find where original innerHTML is READ (saved to a variable)
    read_idx = js.find("= row.innerHTML")
    assert read_idx != -1, (
        "openInlineEdit must read row.innerHTML into a variable to save original state"
    )
    # Find where row.innerHTML is first WRITTEN (overwritten with edit form)
    write_idx = js.find("row.innerHTML = `")
    assert write_idx != -1, "openInlineEdit must overwrite row.innerHTML with the edit form"
    assert read_idx < write_idx, (
        "openInlineEdit must save row.innerHTML BEFORE overwriting it with the edit form"
    )


def test_original_html_variable_assigned():
    """A local variable must capture row.innerHTML for restore."""
    js = _OPEN_INLINE
    # Look for a pattern like: const/let originalHTML = row.innerHTML
    assert re.search(r"(const|let)\s+\w+\s*=\s*row\.innerHTML", js), (
        "openInlineEdit must assign row.innerHTML to a local variable "
        "before replacing it (e.g. const originalHTML = row.innerHTML)"
    )


# ── (b) JS: Cancel button restores original DOM, no _reload() ─────────────────

def test_cancel_btn_does_not_call_reload():
    """The inline-cancel-btn click handler must NOT call _reload()."""
    js = _OPEN_INLINE
    # Find all cancel-btn listener blocks
    cancel_idx = js.find("inline-cancel-btn")
    assert cancel_idx != -1, "openInlineEdit must wire an inline-cancel-btn listener"
    # The listener code should restore innerHTML, not call _reload
    listener_snippet = js[cancel_idx : cancel_idx + 300]
    assert "_reload()" not in listener_snippet, (
        "inline-cancel-btn click handler must NOT call _reload() — "
        "it should restore the original row innerHTML from local state"
    )


def test_cancel_btn_restores_original_html():
    """The inline-cancel-btn click handler must restore row.innerHTML."""
    js = _OPEN_INLINE
    cancel_idx = js.find("inline-cancel-btn")
    assert cancel_idx != -1
    # After the cancel btn reference, we expect row.innerHTML to be restored
    post_cancel = js[cancel_idx:]
    assert "row.innerHTML" in post_cancel, (
        "inline-cancel-btn handler must restore row.innerHTML from the saved snapshot"
    )


# ── (c) JS: Escape key restores original DOM, no _reload() ────────────────────

def test_escape_handler_does_not_call_reload():
    """Escape keydown handler must NOT call _reload()."""
    js = _OPEN_INLINE
    # Handle both single and double quote styles
    escape_idx = js.find("'Escape'")
    if escape_idx == -1:
        escape_idx = js.find('"Escape"')
    assert escape_idx != -1, "openInlineEdit must handle the Escape key"
    snippet = js[escape_idx : escape_idx + 200]
    assert "_reload()" not in snippet, (
        "Escape key handler must NOT call _reload() — "
        "it should restore the original row innerHTML from local state"
    )


def test_escape_handler_restores_original_html():
    """Escape key must cause row.innerHTML to be restored (via cancelEdit or inline)."""
    js = _OPEN_INLINE
    # row.innerHTML must be restored somewhere in the function — either inline or via a helper
    escape_idx = js.find("'Escape'")
    if escape_idx == -1:
        escape_idx = js.find('"Escape"')
    assert escape_idx != -1, "openInlineEdit must handle the Escape key"
    # The function must assign row.innerHTML back (restore) somewhere
    assert re.search(r"row\.innerHTML\s*=\s*\w+", js), (
        "openInlineEdit must restore row.innerHTML from the saved snapshot "
        "when Escape is pressed (either inline or via a cancel helper)"
    )
    # The escape handler must not do a full reload — it should call a cancel fn or inline-restore
    snippet = js[escape_idx : escape_idx + 200]
    assert "_reload()" not in snippet, (
        "Escape key handler must NOT call _reload()"
    )


# ── (d) JS: Save success — no full _reload(), only affected row updated ────────

def test_save_success_does_not_call_full_reload():
    """On successful patchEntry, openInlineEdit must NOT call _reload()."""
    js = _OPEN_INLINE
    # Find the submit handler
    submit_idx = js.find("form.addEventListener('submit'")
    if submit_idx == -1:
        submit_idx = js.find('form.addEventListener("submit"')
    assert submit_idx != -1, "openInlineEdit must add a submit event listener"

    submit_body = js[submit_idx:]
    # Find the try block for the patchEntry call
    patch_idx = submit_body.find("await patchEntry(")
    assert patch_idx != -1, "Submit handler must call patchEntry"

    # Extract content after patchEntry up to the catch
    after_patch = submit_body[patch_idx:]
    catch_idx = after_patch.find("} catch (")
    success_block = after_patch[:catch_idx] if catch_idx != -1 else after_patch[:400]

    assert "_reload()" not in success_block, (
        "After a successful patchEntry, openInlineEdit must NOT call _reload() — "
        "only the affected row should be updated optimistically"
    )


def test_save_success_updates_recent_entries():
    """On success, _recentEntries must be updated in memory."""
    js = _OPEN_INLINE
    submit_idx = js.find("form.addEventListener('submit'")
    if submit_idx == -1:
        submit_idx = js.find('form.addEventListener("submit"')
    assert submit_idx != -1
    submit_body = js[submit_idx:]
    patch_idx = submit_body.find("await patchEntry(")
    assert patch_idx != -1
    after_patch = submit_body[patch_idx:]
    catch_idx = after_patch.find("} catch (")
    success_block = after_patch[:catch_idx] if catch_idx != -1 else after_patch[:600]

    assert "_recentEntries" in success_block, (
        "After patchEntry succeeds, openInlineEdit must update _recentEntries "
        "to reflect the new weight without a full network reload"
    )


def test_save_success_calls_render_recent_entries():
    """On success, renderRecentEntries (or _reloadEntries) must be called to refresh the row."""
    js = _OPEN_INLINE
    submit_idx = js.find("form.addEventListener('submit'")
    if submit_idx == -1:
        submit_idx = js.find('form.addEventListener("submit"')
    assert submit_idx != -1
    submit_body = js[submit_idx:]
    patch_idx = submit_body.find("await patchEntry(")
    assert patch_idx != -1
    after_patch = submit_body[patch_idx:]
    catch_idx = after_patch.find("} catch (")
    success_block = after_patch[:catch_idx] if catch_idx != -1 else after_patch[:600]

    has_render = "renderRecentEntries(" in success_block or "_reloadEntries(" in success_block
    assert has_render, (
        "After patchEntry succeeds, openInlineEdit must call renderRecentEntries() "
        "or _reloadEntries() to update the row display without a full table reload"
    )


# ── (e) JS: Save network error — inline error shown, stays in edit mode ────────

def test_save_error_shows_inline_error():
    """Non-conflict save errors must display in the errEl element."""
    js = _OPEN_INLINE
    submit_idx = js.find("form.addEventListener('submit'")
    if submit_idx == -1:
        submit_idx = js.find('form.addEventListener("submit"')
    assert submit_idx != -1
    submit_body = js[submit_idx:]
    catch_idx = submit_body.find("} catch (")
    assert catch_idx != -1, "Submit handler must have a catch block"
    catch_block = submit_body[catch_idx : catch_idx + 400]

    # Error should write to errEl, not show a page-level error for generic failures
    assert "errEl.textContent" in catch_block, (
        "The catch block must write the error message to errEl.textContent "
        "so the row stays in edit mode with an inline error"
    )


def test_save_error_does_not_call_reload():
    """Non-conflict save errors must NOT call _reload() (row stays in edit mode)."""
    js = _OPEN_INLINE
    submit_idx = js.find("form.addEventListener('submit'")
    if submit_idx == -1:
        submit_idx = js.find('form.addEventListener("submit"')
    assert submit_idx != -1
    submit_body = js[submit_idx:]
    catch_idx = submit_body.find("} catch (")
    assert catch_idx != -1
    catch_block = submit_body[catch_idx : catch_idx + 400]

    assert "_reload()" not in catch_block, (
        "The catch block must NOT call _reload() — "
        "a network error should leave the row in edit mode so the user can retry"
    )
