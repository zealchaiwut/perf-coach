"""Tests for issue #522: Add inline quick-add modal for workout logging.

The quick-add modal is an entirely client-side feature built on the existing
`POST /api/workouts` endpoint. These tests verify the HTML markup and the JS
behaviour against each acceptance criterion. Each test is anchored to a
specific AC from the issue body.

Mapping:
  AC1 — "Log Workout" trigger opens a modal without navigating away.
  AC2 — Quick-add form includes date, type, name, duration/distance, TSS.
  AC3 — Submitting saves and appends to the list without a full page reload.
  AC4 — "Open full form" link inside the modal navigates to /training.
  AC5 — Existing /training?return=/log full-form flow remains functional.
  AC6 — Quick-add validates required fields and shows inline errors.
  AC7 — Modal is dismissible (Esc, backdrop click, explicit close button).
"""
import pathlib
import re

JS_PATH       = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js"
HTML_PATH     = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html"
TRAINING_JS   = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training.js"
TRAINING_HTML = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training.html"


def _js():
    return JS_PATH.read_text()


def _html():
    return HTML_PATH.read_text()


def _func_body(src, signature):
    """Return the brace-matched body of a function starting at `signature`."""
    start = src.find(signature)
    assert start != -1, f"{signature!r} not found"
    brace = src.find("{", start)
    assert brace != -1, f"no opening brace after {signature!r}"
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace:i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


# ── AC1: trigger opens a modal without navigating away ────────────────────────

def test_modal_markup_exists():
    html = _html()
    assert 'id="quick-add-modal"' in html


def test_new_button_opens_modal_not_navigation():
    js = _js()
    # The two triggers ("Log workout" header button + empty-state CTA) must open
    # the quick-add modal, not navigate to /training.
    assert "openQuickAdd" in js
    # No client-side navigation to the full form should remain for the triggers.
    assert "window.location.href = '/training?return=/log'" not in js
    assert 'window.location.href = "/training?return=/log"' not in js


def test_trigger_buttons_wired_to_open_modal():
    js = _js()
    # Both trigger ids must be referenced and wired to the open handler.
    assert "log-new-btn" in js
    assert "log-empty-cta" in js
    # The open handler is invoked from the wiring (single source of truth).
    assert js.count("openQuickAdd(") >= 2


# ── AC2: form includes date, type, name, duration/distance, TSS ───────────────

def test_form_has_all_required_fields():
    html = _html()
    for field_id in (
        'id="qa-date"',
        'id="qa-type"',
        'id="qa-name"',
        'id="qa-duration"',
        'id="qa-distance"',
        'id="qa-tss"',
    ):
        assert field_id in html, f"missing form field {field_id}"


def test_date_field_is_date_input():
    html = _html()
    block = html[html.find('id="qa-date"') - 80: html.find('id="qa-date"') + 80]
    assert 'type="date"' in block


# ── AC3: submitting saves and appends without a full page reload ───────────────

def test_submit_posts_to_workouts_endpoint():
    js = _js()
    body = _func_body(js, "function submitQuickAdd")
    assert "/api/workouts" in body
    assert "'POST'" in body or '"POST"' in body


def test_submit_refreshes_list_without_full_reload():
    js = _js()
    body = _func_body(js, "function submitQuickAdd")
    # Re-render the list in place rather than reloading the page.
    assert "fetchAndRender()" in body
    # A full page reload would defeat the purpose.
    assert "location.reload" not in js


def test_submit_sends_required_payload_fields():
    js = _js()
    body = _func_body(js, "function submitQuickAdd")
    for key in ("workout_date", "workout_type", "name", "tss"):
        assert key in body, f"payload missing {key}"
    # duration/distance both travel in the payload.
    assert "duration_seconds" in body
    assert "distance_km" in body


# ── AC4: "Open full form" link navigates to /training ─────────────────────────

def test_open_full_form_link_present():
    html = _html()
    assert 'id="qa-full-form-link"' in html
    # Links to the full form, preserving the return-to-/log round trip.
    assert "/training?return=/log" in html


# ── AC5: existing /training?return=/log flow remains functional ───────────────

def test_full_form_return_flow_unchanged():
    tjs = TRAINING_JS.read_text()
    # The full form still reads the return param and redirects back to it.
    assert "new URLSearchParams(location.search).get('return')" in tjs
    assert "window.location.replace(dest)" in tjs


# ── AC6: validates required fields, inline errors before submission ───────────

def test_validation_function_exists():
    js = _js()
    assert "function validateQuickAdd" in js


def test_inline_error_containers_exist():
    html = _html()
    # At minimum the required fields get an inline error slot.
    assert 'id="qa-name-error"' in html
    assert 'id="qa-date-error"' in html
    assert 'id="qa-type-error"' in html


def test_submit_blocks_when_invalid():
    js = _js()
    body = _func_body(js, "function submitQuickAdd")
    # Submission must short-circuit when validation fails, before the POST.
    assert "validateQuickAdd" in body
    valid_idx = body.find("validateQuickAdd")
    post_idx = body.find("/api/workouts")
    assert valid_idx != -1 and post_idx != -1
    assert valid_idx < post_idx, "validation must run before the POST"


# ── AC7: modal dismissible (Esc, backdrop, close button) ──────────────────────

def test_close_button_exists_and_wired():
    html = _html()
    js = _js()
    assert 'id="qa-close-btn"' in html
    assert "qa-close-btn" in js


def test_backdrop_dismiss():
    html = _html()
    js = _js()
    assert 'id="qa-backdrop"' in html
    assert "qa-backdrop" in js


def test_escape_key_closes_modal():
    js = _js()
    assert "closeQuickAdd" in js
    # An Escape handler must be able to close the quick-add modal.
    assert re.search(r"Escape", js) is not None
    # The close handler is referenced from keyboard handling.
    assert js.count("closeQuickAdd(") >= 1
