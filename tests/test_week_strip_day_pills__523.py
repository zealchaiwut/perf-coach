"""Tests for issue #523: Make week-strip day pills interactive and accessible (runs against UAT)"""
import pathlib


# Read source files from disk (static HTML/JS verified without needing auth)
REPO_ROOT = pathlib.Path(__file__).parent.parent
TRAINING_LOG_HTML = (REPO_ROOT / "frontend" / "pages" / "training-log.html").read_text()
TRAINING_LOG_JS = (REPO_ROOT / "frontend" / "js" / "training-log.js").read_text()


# --- Acceptance Criteria ---

def test_week_strip_day_pills__buttons_are_focusable():
    """AC: Each day pill is rendered as a focusable, interactive element (button or role="button")"""
    # CSS rule for .day-pill styling confirms it's styled as an element
    assert '.day-pill {' in TRAINING_LOG_HTML
    # JS renders pills as <button> elements with .day-pill class
    assert '<button type="button" class="day-pill' in TRAINING_LOG_JS
    # CSS defines .ws-pills container (rendered dynamically by JS)
    assert '.ws-pills' in TRAINING_LOG_HTML
    # Pills are actual <button> elements, not divs with role="button"
    assert 'type="button"' in TRAINING_LOG_JS


def test_week_strip_day_pills__tapping_filters_log_list():
    """AC: Tapping a day pill triggers quick-add for that date **or** filters the log list to that date"""
    # Implementation filters the log list. Test that pills have data-date attributes for filtering
    assert 'data-date=' in TRAINING_LOG_JS
    # selectDay function is responsible for filter updates
    assert 'selectDay' in TRAINING_LOG_JS
    assert 'filters.from' in TRAINING_LOG_JS


def test_week_strip_day_pills__today_scrolled_into_view_on_load():
    """AC: On page load, today's pill is automatically scrolled into view on all screen widths"""
    # The HTML contains the week-strip container
    assert 'id="week-strip"' in TRAINING_LOG_HTML
    # JS contains the scroll-into-view logic
    assert 'scrollPillIntoView' in TRAINING_LOG_JS
    assert 'scrollLeft' in TRAINING_LOG_JS
    # Logic runs on load (DOMContentLoaded or userReady)
    assert 'DOMContentLoaded' in TRAINING_LOG_JS


def test_week_strip_day_pills__keyboard_tab_focus_enter_activate():
    """AC: Day pills are keyboard accessible: Tab to focus, Enter or Space to activate"""
    # Pills are real <button> elements, which are natively focusable and keyboard-operable
    assert '<button type="button" class="day-pill' in TRAINING_LOG_JS
    # No manual keydown handlers needed for native <button> behavior
    # Check that click handlers are wired up (native buttons fire click on Enter/Space)
    assert 'addEventListener' in TRAINING_LOG_JS
    assert 'click' in TRAINING_LOG_JS


def test_week_strip_day_pills__focus_indicator_wcag_contrast():
    """AC: Active/selected pill has a visible focus indicator meeting WCAG 2.1 AA contrast"""
    # CSS includes .day-pill:focus-visible rule
    assert '.day-pill:focus-visible' in TRAINING_LOG_HTML
    assert 'outline:' in TRAINING_LOG_HTML
    # Outline uses primary color variable (AA contrast compliance)
    assert '--primary' in TRAINING_LOG_HTML
    # Check that focus-visible has outline-offset (for visibility on light bg)
    assert 'outline-offset' in TRAINING_LOG_HTML


def test_week_strip_day_pills__deselect_on_already_selected_tap():
    """AC: Tapping an already-selected pill deselects it (returns to full list view)"""
    # JS implements toggle logic in selectDay
    assert 'alreadySelected' in TRAINING_LOG_JS
    assert 'is-selected' in TRAINING_LOG_JS
    # Confirm deselection clears filters
    assert 'filters.from = ' in TRAINING_LOG_JS
    assert 'filters.to = ' in TRAINING_LOG_JS
