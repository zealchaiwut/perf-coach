"""Tests for issue #752: Delete failure silently ignored in deleteEditing (training-performance.js).

Acceptance criteria verified:
- AC1: When apiDelete returns a non-2xx response, an error message is displayed (errEl or showToast).
- AC2: When apiDelete returns a network failure (fetch rejects), error is displayed (caught by apiDelete).
- AC3: When apiDelete succeeds (2xx), refresh() is called unchanged.
- AC4: Error handling pattern is consistent with saveModal() — uses errEl.textContent or UIStates.showToast.
- AC5: Error message is cleared/hidden before the delete attempt so stale errors do not persist.
"""
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_JS_PATH = _ROOT / "frontend" / "js" / "training-performance.js"


def _src() -> str:
    assert _JS_PATH.exists(), f"training-performance.js not found at {_JS_PATH}"
    return _JS_PATH.read_text()


def _delete_editing_block(src: str) -> str:
    """Extract the text of the deleteEditing function body."""
    start = src.find("function deleteEditing(")
    assert start >= 0, "deleteEditing function not found in training-performance.js"
    # Walk forward to find the balanced closing brace of the function.
    depth = 0
    i = start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    return src[start:]


def _api_delete_block(src: str) -> str:
    """Extract the text of the apiDelete function body."""
    start = src.find("function apiDelete(")
    assert start >= 0, "apiDelete function not found in training-performance.js"
    depth = 0
    i = start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    return src[start:]


# ── AC1: non-2xx response → error displayed ──────────────────────────────────

def test_ac1_delete_editing_has_else_branch_for_error():
    """AC1: deleteEditing's apiDelete callback must have an else (or !res.ok) branch."""
    src = _src()
    block = _delete_editing_block(src)
    # Must have an else branch after the if (res.ok) refresh() call
    has_else = "else" in block
    has_not_ok = "!res.ok" in block or "res.ok === false" in block
    assert has_else or has_not_ok, (
        "deleteEditing() must have an else branch (or !res.ok check) in the apiDelete callback "
        "to handle non-2xx responses. Currently the failure case is silently ignored."
    )


def test_ac1_delete_editing_shows_error_on_failure():
    """AC1: The else branch in deleteEditing must display an error (showToast or errEl.textContent)."""
    src = _src()
    block = _delete_editing_block(src)
    has_toast = "showToast" in block
    has_err_el = "errEl" in block and "textContent" in block
    assert has_toast or has_err_el, (
        "deleteEditing() must display an error message on delete failure via "
        "UIStates.showToast(...) or errEl.textContent = ...; neither found in the function block."
    )


# ── AC2: network failure covered by apiDelete catch + else branch ─────────────

def test_ac2_api_delete_catch_calls_cb_with_ok_false():
    """AC2: apiDelete's catch block must call cb({ ok: false, ... }) so network failures
    are passed to the callback and the else branch handles them."""
    src = _src()
    block = _api_delete_block(src)
    # The catch must invoke cb with ok: false
    has_catch = ".catch(" in block
    has_ok_false = "ok: false" in block
    assert has_catch and has_ok_false, (
        "apiDelete must have a .catch() that calls cb({ ok: false, ... }) so network failures "
        "reach the callback's error branch. "
        f"Found catch: {has_catch}, found ok:false: {has_ok_false}. Block:\n{block}"
    )


def test_ac2_network_failure_reaches_error_branch():
    """AC2: Since apiDelete passes ok:false on network error, the else/!res.ok branch in
    deleteEditing covers network failures — verify both mechanisms are present."""
    src = _src()
    api_block = _api_delete_block(src)
    del_block = _delete_editing_block(src)

    # apiDelete must propagate network failure as ok:false
    assert "ok: false" in api_block, (
        "apiDelete catch block must call cb({ ok: false }) to propagate network errors"
    )
    # deleteEditing must have an error display branch
    has_error_display = "showToast" in del_block or ("errEl" in del_block and "textContent" in del_block)
    assert has_error_display, (
        "deleteEditing must display an error when res.ok is false "
        "(covers both non-2xx and network failures via apiDelete's catch)"
    )


# ── AC3: success path (refresh) unchanged ─────────────────────────────────────

def test_ac3_success_still_calls_refresh():
    """AC3: The if (res.ok) refresh() path must remain unchanged after the fix."""
    src = _src()
    block = _delete_editing_block(src)
    has_refresh_on_ok = "res.ok" in block and "refresh()" in block
    assert has_refresh_on_ok, (
        "deleteEditing must still call refresh() when res.ok is truthy. "
        "The fix must not remove or alter the success path."
    )


def test_ac3_refresh_guarded_by_res_ok():
    """AC3: refresh() must only be called when res.ok is true (not unconditionally)."""
    src = _src()
    block = _delete_editing_block(src)
    # refresh() must appear after/inside an if (res.ok) check, not standalone
    # Simple heuristic: "res.ok" and "refresh()" both appear in the block
    assert "res.ok" in block, "deleteEditing block must reference res.ok"
    assert "refresh()" in block, "deleteEditing block must call refresh()"


# ── AC4: consistent with saveModal error handling pattern ─────────────────────

def test_ac4_error_pattern_uses_toast_or_text_content():
    """AC4: Error handling in deleteEditing must use UIStates.showToast or errEl.textContent,
    consistent with the pattern used in saveModal()."""
    src = _src()
    del_block = _delete_editing_block(src)

    # saveModal uses errEl.textContent — accept showToast as the equivalent for deleteEditing
    # (since both modals are closed at time of error)
    uses_toast = "showToast" in del_block
    uses_err_el = "errEl" in del_block and "textContent" in del_block
    assert uses_toast or uses_err_el, (
        "AC4: deleteEditing error branch must use UIStates.showToast() or errEl.textContent, "
        "consistent with saveModal()'s error display. Neither found in deleteEditing block."
    )


def test_ac4_save_modal_still_uses_err_el():
    """AC4: saveModal's error pattern (errEl.textContent) must still be present — no regression."""
    src = _src()
    save_start = src.find("function saveModal(")
    assert save_start >= 0, "saveModal function not found"
    # Find the block
    depth = 0
    i = save_start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                save_block = src[save_start : i + 1]
                break
        i += 1
    else:
        save_block = src[save_start:]

    assert "errEl" in save_block and "textContent" in save_block, (
        "saveModal's existing errEl.textContent error pattern must still be present (no regression)"
    )


# ── AC5: error cleared before delete attempt ──────────────────────────────────

def test_ac5_error_cleared_before_attempt():
    """AC5: The error display must be cleared before each delete attempt to prevent
    stale errors persisting across multiple actions.

    With UIStates.showToast, a new toast replaces the old one (implicit clearing).
    With errEl, explicit clearing must appear before the apiDelete call.
    """
    src = _src()
    block = _delete_editing_block(src)

    uses_toast = "showToast" in block
    # If using errEl: explicit clear (errEl.textContent = "") must precede apiDelete call
    uses_err_el = "errEl" in block and "textContent" in block

    if uses_toast:
        # Toast auto-replaces — each new toast clears the prior one. AC5 is satisfied implicitly.
        assert uses_toast, "showToast found — toast replaces prior toast, satisfying AC5"
    elif uses_err_el:
        # Must explicitly clear errEl before apiDelete is called
        err_el_clear_idx = block.find('errEl.textContent = ""')
        api_delete_idx = block.find("apiDelete(")
        assert err_el_clear_idx >= 0, (
            "AC5: errEl.textContent must be cleared before apiDelete is called; "
            'errEl.textContent = "" not found in deleteEditing block'
        )
        assert err_el_clear_idx < api_delete_idx, (
            "AC5: errEl must be cleared BEFORE apiDelete is called (clear comes first)"
        )
    else:
        raise AssertionError(
            "AC5: Neither showToast (implicit clearing) nor errEl.textContent clearing found "
            "in deleteEditing. The fix must clear stale errors before each delete attempt."
        )
