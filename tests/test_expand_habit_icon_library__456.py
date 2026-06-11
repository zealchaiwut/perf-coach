"""Tests for issue #456: Expand Habit Icon Library and Increase Icon Size.

AC items covered:
  (a) ICONS array has at least 30 distinct icons
  (b) Icons cover fitness, mindfulness, nutrition, learning, social,
      productivity, and self-care categories
  (c) Daily-grid icon display size is at least 28px (was 24)
  (d) Archived-list icon display size is at least 28px (was 22)
  (e) .habit-icon-chip CSS width/height are at least 28px (was 26)
  (f) Icon picker .icon-option size is larger than original 40px
  (g) Icon picker has overflow/scroll so full set fits
  (h) All original icons are preserved (no data loss / backward compat)
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
_JS   = (_ROOT / "frontend" / "js" / "habits.js").read_text()
_HTML = (_ROOT / "frontend" / "pages" / "habits.html").read_text()


# ── (a) At least 30 icons ─────────────────────────────────────────────────────

def test_icon_library_has_at_least_30_icons():
    # Extract the ICONS array from habits.js
    m = re.search(r"const ICONS\s*=\s*\[(.*?)\];", _JS, re.DOTALL)
    assert m, "ICONS array not found in habits.js"
    icons = re.findall(r"'(ti-[^']+)'", m.group(1))
    assert len(icons) >= 30, (
        f"ICONS array has only {len(icons)} icons; need at least 30. "
        f"Current: {icons}"
    )


def test_icon_library_has_no_duplicates():
    m = re.search(r"const ICONS\s*=\s*\[(.*?)\];", _JS, re.DOTALL)
    assert m, "ICONS array not found in habits.js"
    icons = re.findall(r"'(ti-[^']+)'", m.group(1))
    assert len(icons) == len(set(icons)), (
        f"Duplicate icons found: {[i for i in icons if icons.count(i) > 1]}"
    )


# ── (b) Categories represented ───────────────────────────────────────────────

def _icons_in_array():
    m = re.search(r"const ICONS\s*=\s*\[(.*?)\];", _JS, re.DOTALL)
    assert m, "ICONS array not found"
    return re.findall(r"'(ti-[^']+)'", m.group(1))


# Fitness icons
@pytest.mark.parametrize("icon", ["ti-run", "ti-barbell", "ti-bike"])
def test_fitness_icons_present(icon):
    assert icon in _icons_in_array(), f"Fitness icon '{icon}' missing from ICONS"


# Mindfulness icons — at least one of these
def test_mindfulness_category_present():
    mindfulness = {"ti-meditation", "ti-brain", "ti-heart", "ti-sun", "ti-moon"}
    icons = set(_icons_in_array())
    present = mindfulness & icons
    assert present, (
        f"No mindfulness icons found in ICONS. Expected at least one of {mindfulness}"
    )


# Nutrition icons — at least one of these
def test_nutrition_category_present():
    nutrition = {"ti-droplet", "ti-apple", "ti-coffee", "ti-salad", "ti-soup", "ti-bottle"}
    icons = set(_icons_in_array())
    present = nutrition & icons
    assert present, (
        f"No nutrition icons found in ICONS. Expected at least one of {nutrition}"
    )


# Learning icons — at least one of these
def test_learning_category_present():
    learning = {"ti-book", "ti-pencil", "ti-school", "ti-notebook", "ti-certificate"}
    icons = set(_icons_in_array())
    present = learning & icons
    assert present, (
        f"No learning icons found in ICONS. Expected at least one of {learning}"
    )


# Social icons — at least one of these
def test_social_category_present():
    social = {"ti-users", "ti-message", "ti-phone", "ti-friends"}
    icons = set(_icons_in_array())
    present = social & icons
    assert present, (
        f"No social icons found in ICONS. Expected at least one of {social}"
    )


# Productivity icons — at least one of these
def test_productivity_category_present():
    productivity = {"ti-clipboard", "ti-clock", "ti-calendar", "ti-target", "ti-check"}
    icons = set(_icons_in_array())
    present = productivity & icons
    assert present, (
        f"No productivity icons found in ICONS. Expected at least one of {productivity}"
    )


# Self-care icons — at least one of these
def test_self_care_category_present():
    self_care = {"ti-bed", "ti-bath", "ti-mood-smile", "ti-stethoscope", "ti-massage"}
    icons = set(_icons_in_array())
    present = self_care & icons
    assert present, (
        f"No self-care icons found in ICONS. Expected at least one of {self_care}"
    )


# ── (c) Daily-grid icon size >= 28 ────────────────────────────────────────────

def test_daily_grid_icon_size_at_least_28():
    # habits.js renders daily-grid icons via: habitIconHTML(habit.icon, habit.color, N)
    # inside the forEach loop that builds the daily-grid table rows.
    # Find all occurrences of habitIconHTML inside the daily section.
    matches = re.findall(r"habitIconHTML\([^,]+,\s*[^,]+,\s*(\d+)\)", _JS)
    sizes = [int(s) for s in matches]
    small = [s for s in sizes if s < 28]
    assert not small, (
        f"Found habitIconHTML call(s) with size < 28px: {small}. "
        "All icon sizes in the habit list/card view must be >= 28px."
    )


# ── (d) Archived-list icon size >= 28 ────────────────────────────────────────

def test_archived_list_icon_size_at_least_28():
    # Archived list used to call habitIconHTML(..., 22)
    m = re.search(r"habitIconHTML\([^,]+,\s*[^,]+,\s*(\d+)\)", _JS)
    # The specific check: no call with size < 28 (covers both daily and archived)
    matches = re.findall(r"habitIconHTML\([^,]+,\s*[^,]+,\s*(\d+)\)", _JS)
    sizes = [int(s) for s in matches]
    assert all(s >= 28 for s in sizes), (
        f"habitIconHTML called with size(s) < 28: "
        f"{[s for s in sizes if s < 28]}"
    )


# ── (e) .habit-icon-chip CSS dimensions >= 28px ───────────────────────────────

def test_habit_icon_chip_css_width_at_least_28():
    # The .habit-icon-chip class in habits.html must have width/height >= 28px.
    m = re.search(
        r"\.habit-icon-chip\s*\{([^}]+)\}", _HTML, re.DOTALL
    )
    assert m, ".habit-icon-chip CSS block not found in habits.html"
    block = m.group(1)
    w = re.search(r"width\s*:\s*(\d+)px", block)
    h = re.search(r"height\s*:\s*(\d+)px", block)
    assert w, "width not found in .habit-icon-chip block"
    assert h, "height not found in .habit-icon-chip block"
    assert int(w.group(1)) >= 28, (
        f".habit-icon-chip width is {w.group(1)}px; must be >= 28px"
    )
    assert int(h.group(1)) >= 28, (
        f".habit-icon-chip height is {h.group(1)}px; must be >= 28px"
    )


# ── (f) .icon-option size is larger than original 40px ───────────────────────

def test_icon_picker_option_size_increased():
    m = re.search(
        r"\.icon-option\s*\{([^}]+)\}", _HTML, re.DOTALL
    )
    assert m, ".icon-option CSS block not found in habits.html"
    block = m.group(1)
    w = re.search(r"width\s*:\s*(\d+)px", block)
    h = re.search(r"height\s*:\s*(\d+)px", block)
    assert w and h, "width/height not found in .icon-option CSS block"
    assert int(w.group(1)) > 40, (
        f".icon-option width is {w.group(1)}px; must be > 40px (original)"
    )
    assert int(h.group(1)) > 40, (
        f".icon-option height is {h.group(1)}px; must be > 40px (original)"
    )


# ── (g) Icon picker is scrollable ────────────────────────────────────────────

def test_icon_picker_is_scrollable():
    m = re.search(r"\.icon-picker\s*\{([^}]+)\}", _HTML, re.DOTALL)
    assert m, ".icon-picker CSS block not found in habits.html"
    block = m.group(1)
    has_overflow = re.search(r"overflow(?:-y)?\s*:", block)
    has_max_height = re.search(r"max-height\s*:", block)
    assert has_overflow or has_max_height, (
        ".icon-picker must have overflow or max-height to be scrollable "
        f"(block: {block.strip()!r})"
    )


# ── (h) Original icons preserved (backward compatibility) ────────────────────

ORIGINAL_ICONS = [
    'ti-run', 'ti-barbell', 'ti-droplet', 'ti-book',
    'ti-bed', 'ti-flame', 'ti-walk', 'ti-bike',
    'ti-meditation', 'ti-shoe', 'ti-clipboard',
]


@pytest.mark.parametrize("icon", ORIGINAL_ICONS)
def test_original_icon_preserved(icon):
    icons = _icons_in_array()
    assert icon in icons, (
        f"Original icon '{icon}' is missing from ICONS — "
        "removing icons causes data loss for habits that used them"
    )
