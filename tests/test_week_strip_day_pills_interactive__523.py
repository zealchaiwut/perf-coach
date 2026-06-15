"""Tests for issue #523: Make week-strip day pills interactive and accessible.

The week strip is a client-side feature in `frontend/js/training-log.js` (the
`render()` function that paints `#week-strip`) styled by the page `<style>` block
in `frontend/pages/training-log.html`. These tests verify the markup, behaviour,
and CSS against each acceptance criterion. Each test is anchored to a specific
AC from the issue body.

Mapping:
  AC1 — Each day pill is a focusable, interactive element (button/role=button).
  AC2 — Tapping a day pill filters the log list to that date.
  AC3 — On load, today's pill is auto-scrolled into view on all screen widths.
  AC4 — Day pills are keyboard accessible: Tab to focus, Enter or Space activate.
  AC5 — Active/selected pill has a visible focus indicator (WCAG 2.1 AA).
  AC6 — Tapping an already-selected pill deselects it (full list restored).
"""
import pathlib

JS_PATH   = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js"
HTML_PATH = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html"


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


# ── AC1: each day pill is a focusable interactive element ──────────────────────

def test_pill_is_a_button_not_a_div():
    body = _func_body(_js(), "function render(monday, dotsByDate)")
    # Pills must be rendered as real <button> elements (natively focusable &
    # keyboard-operable), not inert <div>s.
    assert "<button" in body, "day pill must be a <button>"
    assert 'class="day-pill' in body
    assert 'type="button"' in body
    # The old inert markup must be gone.
    assert '<div class="day-pill' not in body


def test_pill_carries_its_date():
    body = _func_body(_js(), "function render(monday, dotsByDate)")
    # Each pill exposes its ISO date so the click handler knows which day.
    assert "data-date=" in body


# ── AC2: tapping a pill filters the log list to that date ─────────────────────

def test_select_day_handler_exists():
    assert "function selectDay" in _js()


def test_select_day_sets_date_filter_and_refreshes():
    body = _func_body(_js(), "function selectDay")
    # Filtering the log list to a single day sets both ends of the date filter…
    assert "filters.from" in body
    assert "filters.to" in body
    # …and re-renders the list in place (no full reload).
    assert "fetchAndRender()" in body
    assert "location.reload" not in _js()


def test_pills_wired_to_select_day():
    body = _func_body(_js(), "function render(monday, dotsByDate)")
    # The rendered pills are wired to the selection handler.
    assert "selectDay" in body


# ── AC3: today's pill is auto-scrolled into view on load (all widths) ─────────

def test_scroll_into_view_helper_exists():
    js = _js()
    assert "function scrollPillIntoView" in js


def test_scroll_helper_centers_horizontally():
    body = _func_body(_js(), "function scrollPillIntoView")
    # Centre the active/today pill within the horizontally-scrolling strip.
    assert "scrollLeft" in body


def test_render_invokes_scroll_on_load():
    body = _func_body(_js(), "function render(monday, dotsByDate)")
    assert "scrollPillIntoView(" in body


# ── AC4: keyboard accessible — Tab to focus, Enter or Space to activate ───────

def test_pills_are_natively_keyboard_operable():
    body = _func_body(_js(), "function render(monday, dotsByDate)")
    # Native <button> elements are Tab-focusable and fire click on both Enter
    # and Space with no extra JS — that is the accessible primitive required.
    assert "<button" in body
    assert 'type="button"' in body


def test_pill_has_accessible_label():
    body = _func_body(_js(), "function render(monday, dotsByDate)")
    # Screen readers must announce the full date (e.g. "Monday, June 9").
    assert "aria-label=" in body


# ── AC5: selected pill has a visible focus indicator meeting WCAG AA ──────────

def test_focus_visible_style_present():
    html = _html()
    assert ".day-pill:focus-visible" in html
    # Focus indicator uses an outline (token-backed primary colour).
    block = html[html.find(".day-pill:focus-visible"):
                 html.find(".day-pill:focus-visible") + 160]
    assert "outline" in block


def test_selected_pill_style_present():
    html = _html()
    # The active/selected pill has its own visible state class.
    assert ".day-pill.is-selected" in html


def test_selected_state_marked_in_markup():
    body = _func_body(_js(), "function render(monday, dotsByDate)")
    # Selection is reflected both as a CSS hook and as ARIA state.
    assert "is-selected" in body
    assert "aria-pressed=" in body


# ── AC6: tapping an already-selected pill deselects it ────────────────────────

def test_toggle_clears_filter_when_reselecting():
    body = _func_body(_js(), "function selectDay")
    # Re-selecting the active day clears the date filter (back to full list).
    assert "filters.from = ''" in body
    assert "filters.to = ''" in body


def test_render_computes_selection_from_single_day_filter():
    body = _func_body(_js(), "function render(monday, dotsByDate)")
    # A pill is "selected" only when the filter is pinned to exactly that day.
    assert "filters.from" in body
    assert "filters.to" in body
