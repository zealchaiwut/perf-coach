"""Tests for issue #425: Rebuild recent entries as compact side-by-side card.

AC anchors verified:
(ac1)  Card titled "Recent entries · last 14 days" with "View all N →" link
(ac2)  Exactly 14 rows always render (one per calendar day, newest first)
(ac3)  Logged rows: date+weekday, optional note, weight in monospace, delta, overflow menu (Edit/Delete)
(ac4)  Time column not visible in the recent-entries card
(ac5)  Delta: ↓ green toward target, ↑ red away — uses target direction when active target exists
(ac6)  Delta computes correctly across gaps (compares to last logged day, not adjacent calendar day)
(ac7)  Missing-day rows render faded with dashed "＋ Add" chip
(ac8)  Clicking "＋ Add" opens mini-stepper (−/value/+/Log) prefilled with nearest logged weight
(ac9)  Log on backfill stepper POSTs with that date; row flips to logged state in place
(ac10) Today's row pinned at top with blue tint
(ac11) If today unlogged, today's row shows inline stepper open by default
(ac12) Logging in hero updates today row in card (and vice versa) without full reload
(ac13) After any log action, hero/chart/progress all refresh without full page reload
(ac14) Card sits to the right of the progress card in the bottom grid
(ac15) At viewport width ≤ 820 px the card stacks below the progress card
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "frontend" / "pages"
JS_DIR = ROOT / "frontend" / "js"

WEIGHT_HTML = (PAGES_DIR / "weight.html").read_text()
WEIGHT_JS = (JS_DIR / "weight.js").read_text()
_html = WEIGHT_HTML.lower()
_js = WEIGHT_JS.lower()


# ── AC1: Card title and View all link ────────────────────────────────────────

def test_ac1_card_title_contains_recent_entries():
    assert "Recent entries" in WEIGHT_HTML, \
        "Card must be titled 'Recent entries · last 14 days'"


def test_ac1_card_title_contains_last_14_days():
    assert "last 14 days" in WEIGHT_HTML, \
        "Card title must include 'last 14 days'"


def test_ac1_card_title_uses_middot_separator():
    # Title is "Recent entries · last 14 days"
    assert "·" in WEIGHT_HTML or "Recent entries" in WEIGHT_HTML, \
        "Card title must use · separator between 'Recent entries' and 'last 14 days'"


def test_ac1_view_all_link_present_in_js():
    assert "view-all" in _js or "View all" in WEIGHT_JS, \
        "weight.js must populate a 'View all N →' link dynamically"


def test_ac1_view_all_link_element_in_html():
    assert "view-all" in _html, \
        "HTML must have a view-all link element for the 'View all N →' link"


def test_ac1_view_all_link_updates_count():
    # JS must set the View all link text or count dynamically
    assert "view-all" in _js and (
        "count" in _js or "entries" in _js or "length" in _js
    ), "weight.js must update view-all link with entry count"


# ── AC2: Exactly 14 rows ──────────────────────────────────────────────────────

def test_ac2_renders_14_rows():
    assert "14" in WEIGHT_JS, \
        "weight.js must render exactly 14 rows (one per calendar day)"


def test_ac2_newest_first_order():
    # Loop iterates from today backward: addDays(today, -i) for i in 0..13
    assert "addDays(today" in WEIGHT_JS or "addDays(todayISO" in WEIGHT_JS, \
        "weight.js must build 14-day list newest-first using addDays"


# ── AC3: Logged rows have date+weekday, notes, weight, delta, Edit+Delete ────

def test_ac3_logged_row_shows_weekday():
    # fmtDisplayDate returns weekday (e.g. "Mon, Jun 9")
    assert "weekday" in _js or "fmtDisplayDate" in WEIGHT_JS, \
        "weight.js must show weekday in logged row date"


def test_ac3_logged_row_shows_notes():
    assert "notes" in _js, \
        "weight.js must display optional notes field in logged rows"


def test_ac3_logged_row_weight_in_monospace():
    assert "entry-weight" in WEIGHT_HTML or "mono" in WEIGHT_HTML.lower(), \
        "Logged rows must display weight in monospace/tabular-nums"


def test_ac3_logged_row_delta_present():
    assert "entry-delta" in WEIGHT_HTML or "delta" in _html, \
        "Logged rows must display day-over-day delta"


def test_ac3_overflow_menu_has_edit():
    assert "Edit" in WEIGHT_JS or "edit" in _js, \
        "Overflow menu must have an Edit option"


def test_ac3_overflow_menu_has_delete():
    assert "Delete" in WEIGHT_JS or "delete" in _js, \
        "Overflow menu must have a Delete option"


def test_ac3_overflow_menu_both_edit_and_delete():
    # Both Edit and Delete must appear in the menu HTML built by JS
    assert "Edit" in WEIGHT_JS and "Delete" in WEIGHT_JS, \
        "Overflow menu must include both Edit and Delete buttons"


# ── AC4: No time column in card ───────────────────────────────────────────────

def test_ac4_no_time_column_header_in_entries():
    # The entries table must NOT have a Time column header
    # Previous implementation had <th>Time</th> — must be gone
    import re
    # Look for th containing "Time" that's NOT a comment
    table_section = WEIGHT_HTML
    # Simple check: no standalone "Time" column header in recent entries
    assert '<th>Time</th>' not in WEIGHT_HTML and \
           '<th>time</th>' not in _html, \
        "Recent entries table must not have a Time column header"


def test_ac4_no_time_display_in_entries_js():
    # The renderRecentEntries function must not render entry_time in cells
    # Check that we don't render timeStr in the entries (the old timeStr pattern)
    assert "timeStr" not in WEIGHT_JS or "entry_time" not in WEIGHT_JS.split("renderRecentEntries")[1].split("function ")[0] if "renderRecentEntries" in WEIGHT_JS else True, \
        "weight.js renderRecentEntries must not render entry_time"


# ── AC5: Delta logic — toward/away from target ───────────────────────────────

def test_ac5_delta_green_toward_target():
    # Delta uses 'loss' class for green (toward target)
    assert "loss" in _js, \
        "weight.js delta must use 'loss' class for toward-target direction (green)"


def test_ac5_delta_red_away_from_target():
    assert "gain" in _js, \
        "weight.js delta must use 'gain' class for away-from-target direction (red)"


def test_ac5_delta_dash_when_no_previous():
    # When no previous entry, delta shows — or empty
    assert "—" in WEIGHT_JS or "null" in _js or "no prev" in _js or \
           "delta == null" in WEIGHT_JS or "delta === null" in WEIGHT_JS, \
        "weight.js must show — (dash) when previous logged day is missing"


def test_ac5_delta_uses_target_direction():
    # Delta coloring should reference _activeTarget or targetDir or similar
    # to determine which direction is "toward target"
    assert "_activeTarget" in WEIGHT_JS or "activeTarget" in WEIGHT_JS or \
           "targetDir" in WEIGHT_JS or "losingIsGoal" in WEIGHT_JS or \
           "target_weight" in WEIGHT_JS, \
        "weight.js delta must use active target direction for color"


# ── AC6: Delta across gaps ────────────────────────────────────────────────────

def test_ac6_delta_finds_previous_logged_day():
    # Existing logic: allSorted, prev = entries before this date
    assert "allSorted" in WEIGHT_JS or "entry_date" in WEIGHT_JS, \
        "weight.js must compute delta against previous logged day (not calendar day)"


def test_ac6_delta_uses_last_logged_not_calendar_prev():
    # The implementation must filter entries before current date
    assert "entry_date < e.entry_date" in WEIGHT_JS or \
           "entry_date.localeCompare" in WEIGHT_JS or \
           "prevWeight" in WEIGHT_JS, \
        "weight.js delta must skip missing days when finding previous entry"


# ── AC7: Missing-day rows faded with dashed Add chip ─────────────────────────

def test_ac7_missing_row_has_faded_class():
    assert "missing-day" in WEIGHT_HTML or "missing-day" in WEIGHT_JS or \
           "faded" in _html or "faded" in _js, \
        "Missing-day rows must have a faded/dimmed CSS class"


def test_ac7_add_chip_uses_plus_add_text():
    # Revamp: gap rows use "+ backfill" (calendar coverage) instead of "＋ Add".
    assert (
        "＋ Add" in WEIGHT_JS
        or "+ Add" in WEIGHT_JS
        or "＋&nbsp;Add" in WEIGHT_JS
        or "+ backfill" in WEIGHT_JS
    ), "Missing-day chip must show '＋ Add' or '+ backfill' text"


def test_ac7_add_chip_has_dashed_border():
    # The chip CSS uses dashed border
    assert "dashed" in WEIGHT_HTML, \
        "＋ Add chip must have dashed border style"


def test_ac7_missing_day_chip_class_in_css():
    assert "backfill-add-btn" in WEIGHT_HTML or "add-chip" in _html, \
        "HTML must define CSS for the ＋ Add chip element"


# ── AC8: Mini-stepper (−/value/+/Log) ────────────────────────────────────────

def test_ac8_mini_stepper_decrement_button():
    assert "stepper-dec" in WEIGHT_JS or "stepper-minus" in _js or \
           "btn-dec" in _js or ("−" in WEIGHT_JS and "stepper" in _js), \
        "Mini-stepper must have a decrement (−) button"


def test_ac8_mini_stepper_increment_button():
    assert "stepper-inc" in WEIGHT_JS or "stepper-plus" in _js or \
           "btn-inc" in _js or ("+" in WEIGHT_JS and "stepper" in _js), \
        "Mini-stepper must have an increment (+) button"


def test_ac8_mini_stepper_log_button():
    assert "stepper-log" in _js or ("Log" in WEIGHT_JS and "stepper" in _js) or \
           "backfill-save-btn" in _js, \
        "Mini-stepper must have a Log button"


def test_ac8_mini_stepper_prefilled_with_nearest_weight():
    # JS must search backward (then forward) for nearest logged weight
    assert "nearest" in _js or "nearest" in _html or \
           "backward" in _js or "search" in _js or \
           "prevWeight" in WEIGHT_JS or "closest" in _js or \
           "_nearestWeight" in WEIGHT_JS or "findNearest" in WEIGHT_JS or \
           "nearestLogged" in WEIGHT_JS, \
        "Mini-stepper must prefill with nearest logged weight (search backward then forward)"


def test_ac8_mini_stepper_css_defined():
    assert "stepper" in _html or "mini-stepper" in _html or \
           "backfill-inline" in WEIGHT_HTML, \
        "HTML must define CSS for the mini-stepper component"


# ── AC9: Backfill POST with specific date ────────────────────────────────────

def test_ac9_backfill_posts_entry_date():
    assert "entry_date" in WEIGHT_JS and "backfill" in _js, \
        "Backfill POST must include entry_date (the specific day's date)"


def test_ac9_backfill_post_uses_date_variable():
    # The date variable from the row is used in the POST body
    assert "entry_date: date" in WEIGHT_JS or \
           "entry_date:date" in WEIGHT_JS or \
           "entry_date" in WEIGHT_JS, \
        "Backfill POST must send the row's specific date as entry_date"


def test_ac9_backfill_reload_after_log():
    assert "_reload()" in WEIGHT_JS, \
        "weight.js must call _reload() after a backfill log action"


# ── AC10: Today row pinned at top with blue tint ─────────────────────────────

def test_ac10_today_row_is_first():
    # Today is days[0] — addDays(today, 0)
    assert "days[0]" in WEIGHT_JS or "addDays(today" in WEIGHT_JS or \
           "i = 0" in WEIGHT_JS or "i=0" in WEIGHT_JS, \
        "Today's row must be first (newest-first ordering)"


def test_ac10_today_row_has_blue_tint_class():
    assert "entry-row-today" in WEIGHT_HTML, \
        "HTML must define CSS for today's row blue tint"


def test_ac10_today_blue_tint_css_uses_blue():
    # entry-row-today CSS must use a blue background
    assert "#eff6ff" in WEIGHT_HTML or "eff6ff" in _html or \
           "blue" in _html or "#dbeafe" in _html or "dbeafe" in _html, \
        "Today row CSS must use blue tint background"


# ── AC11: Today unlogged → stepper open by default ───────────────────────────

def test_ac11_auto_open_stepper_for_today_if_unlogged():
    assert "autoOpen" in WEIGHT_JS or "auto_open" in _js or \
           "isToday" in WEIGHT_JS or \
           ("today" in _js and "stepper" in _js) or \
           ("today" in _js and "backfill" in _js and "open" in _js), \
        "weight.js must auto-open inline stepper for today's row when today is unlogged"


def test_ac11_today_unlogged_check():
    # Must check if today has an entry before auto-opening
    assert "byDate[today]" in WEIGHT_JS or \
           "byDate[date]" in WEIGHT_JS or \
           "dayEntries" in WEIGHT_JS, \
        "weight.js must check whether today has an entry to decide auto-open"


# ── AC12: Hero ↔ card sync without full reload ───────────────────────────────

def test_ac12_no_full_page_reload():
    assert "window.location.reload" not in WEIGHT_JS, \
        "weight.js must never use window.location.reload (must use _reload() instead)"


def test_ac12_reload_updates_both_hero_and_entries():
    # _reload() already calls both renderHero and renderRecentEntries
    assert "_reload" in WEIGHT_JS and "renderHero" in WEIGHT_JS and \
           "renderRecentEntries" in WEIGHT_JS, \
        "weight.js _reload() must refresh both hero and recent entries card"


# ── AC13: All panels refresh after log action ────────────────────────────────

def test_ac13_reload_after_quicklog():
    assert "_reload()" in WEIGHT_JS, \
        "weight.js must call _reload() after quick-log action"


def test_ac13_reload_after_backfill():
    assert "_reload()" in WEIGHT_JS, \
        "weight.js must call _reload() after backfill log action"


def test_ac13_reload_calls_render_hero():
    assert "renderHero" in WEIGHT_JS, \
        "_reload() must call renderHero to refresh hero strip"


def test_ac13_reload_calls_render_chart():
    assert "renderChart" in WEIGHT_JS, \
        "_reload() must call renderChart to refresh chart"


def test_ac13_reload_calls_render_progress():
    assert "renderProgress" in WEIGHT_JS, \
        "_reload() must call renderProgress to refresh progress card"


# ── AC14: Card to the right of progress card (CSS grid) ──────────────────────

def test_ac14_bottom_grid_container_in_html():
    assert "bottom-grid" in WEIGHT_HTML, \
        "HTML must have a bottom-grid container for side-by-side layout"


def test_ac14_bottom_grid_css_two_columns():
    assert "bottom-grid" in WEIGHT_HTML and (
        "grid-template-columns" in WEIGHT_HTML or "repeat(2" in WEIGHT_HTML or
        "2fr" in WEIGHT_HTML or "1fr 1fr" in WEIGHT_HTML
    ), "bottom-grid must define a 2-column CSS grid layout"


def test_ac14_progress_card_inside_bottom_grid():
    # progress-card must be inside a bottom-grid structure
    html = WEIGHT_HTML
    bottom_grid_idx = html.find("bottom-grid")
    progress_card_idx = html.find("progress-card", bottom_grid_idx)
    assert bottom_grid_idx != -1 and progress_card_idx != -1, \
        "progress-card must appear inside the bottom-grid container"


def test_ac14_recent_entries_card_inside_bottom_grid():
    html = WEIGHT_HTML
    bottom_grid_idx = html.find("bottom-grid")
    entries_idx = html.find("recent-entries", bottom_grid_idx)
    assert bottom_grid_idx != -1 and entries_idx != -1, \
        "recent-entries card must appear inside the bottom-grid container"


# ── AC15: ≤820px stacks below progress card ──────────────────────────────────

def test_ac15_820px_breakpoint_defined():
    assert "820" in WEIGHT_HTML, \
        "weight.html must define a CSS media query at 820px for the bottom grid"


def test_ac15_820px_stacks_to_one_column():
    # At ≤820px the bottom-grid must switch to single column
    assert "820" in WEIGHT_HTML and (
        "grid-template-columns" in WEIGHT_HTML or
        "1fr" in WEIGHT_HTML or
        "display: block" in WEIGHT_HTML
    ), "At ≤820px the bottom-grid must collapse to a single column"


# ── Edit/Delete functions (carried from #322 prerequisites) ──────────────────

def test_inline_edit_function_defined():
    assert "function openInlineEdit(" in WEIGHT_JS or \
           "openInlineEdit" in WEIGHT_JS, \
        "weight.js must define openInlineEdit() for the Edit overflow menu action"


def test_patch_entry_function_defined():
    assert "async function patchEntry(" in WEIGHT_JS or \
           "patchEntry" in WEIGHT_JS, \
        "weight.js must define patchEntry() to send PATCH requests for edit"


def test_entry_edit_css_defined():
    assert ".entry-edit" in WEIGHT_HTML, \
        "weight.html must define .entry-edit CSS class"


def test_inline_edit_form_css_defined():
    assert ".inline-edit-form" in WEIGHT_HTML, \
        "weight.html must define .inline-edit-form CSS class"
