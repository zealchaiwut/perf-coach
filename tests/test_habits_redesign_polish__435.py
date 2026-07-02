"""Tests for issue #435: Habits redesign — final polish, docs, and smoke verification.

AC items covered:
  (a) docs/mockups/habits-redesign-v1.html exists in the repo
  (b) docs/mockups/README.md contains habits entry with live path /habits
  (c) docs/features/habits.md exists and documents the /api/habits/week endpoint
  (d) habits.md documents all five wheel color rules (full/partial/zero/today-pending/future)
  (e) habits.md documents streak rules including 365-day cap
  (f) habits.md documents the backfill window (current week only; past weeks read-only)
  (g) habits.md documents add-mode logging behavior
  (h) habits.md documents the pace formula for weekly habits
  (i) habits.md documents both-percentages decision (elapsed % → wheel; full-week % → grid)
  (j) No per-habit /progress API calls remain in habits.js
  (k) No orphaned dead CSS classes from old list in habits.html (.week-habit-icon,
      .week-habit-name-row, .week-habit-bar-outer in responsive block)
  (l) Modal code (create/edit/archive) is still present in habits.js and habits.html
  (m) Page makes exactly one /api/habits/week fetch call on initial load (loadAndRender)
  (n) scheduleHeroRefresh makes a single debounced /api/habits/week call after mutations
  (o) CHANGELOG.md has the required habits redesign entry
  (p) docs/habits-redesign-investigation.md has a Post-ship verification section
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
_HTML = (_ROOT / "frontend" / "pages" / "habits.html").read_text()
_JS   = (_ROOT / "frontend" / "js" / "habits.js").read_text()


# ── (a) Mockup file exists ────────────────────────────────────────────────────

def test_mockup_html_exists():
    mockup = _ROOT / "docs" / "mockups" / "habits-redesign-v1.html"
    assert mockup.is_file(), "docs/mockups/habits-redesign-v1.html must exist in the repo"


# ── (b) Mockups README has habits entry ───────────────────────────────────────

def test_mockups_readme_habits_entry():
    readme = (_ROOT / "docs" / "mockups" / "README.md").read_text()
    assert "habits-redesign-v1.html" in readme, \
        "docs/mockups/README.md must reference habits-redesign-v1.html"
    assert "/habits" in readme, \
        "docs/mockups/README.md must reference the live page at /habits"


# ── (c) habits.md exists with /api/habits/week ───────────────────────────────

def test_habits_feature_doc_exists():
    doc = _ROOT / "docs" / "features" / "habits.md"
    assert doc.is_file(), "docs/features/habits.md must exist"


def test_habits_doc_week_endpoint():
    doc = (_ROOT / "docs" / "features" / "habits.md").read_text()
    assert "/api/habits/week" in doc, \
        "habits.md must document the /api/habits/week endpoint request/response contract"


# ── (d) Wheel color rules documented ─────────────────────────────────────────

@pytest.mark.parametrize("state", ["full", "partial", "zero", "today", "future"])
def test_habits_doc_wheel_color_states(state):
    doc = (_ROOT / "docs" / "features" / "habits.md").read_text()
    assert state in doc.lower(), \
        f"habits.md must document wheel color rule for state: '{state}'"


# ── (e) Streak rules ──────────────────────────────────────────────────────────

def test_habits_doc_streak_rules():
    doc = (_ROOT / "docs" / "features" / "habits.md").read_text()
    assert "streak" in doc.lower(), "habits.md must document streak rules"
    assert "365" in doc, "habits.md must mention the 365-day streak cap"
    assert "today" in doc.lower() and ("pending" in doc.lower() or "today-pending" in doc.lower()), \
        "habits.md must state that today-pending does not break streak"


# ── (f) Backfill window ───────────────────────────────────────────────────────

def test_habits_doc_backfill_window():
    doc = (_ROOT / "docs" / "features" / "habits.md").read_text()
    assert "backfill" in doc.lower(), \
        "habits.md must document the backfill window"
    # Past weeks should be documented as read-only
    assert "read-only" in doc.lower() or "readonly" in doc.lower() or "past week" in doc.lower(), \
        "habits.md must note that past weeks are read-only"


# ── (g) Add-mode logging behavior ────────────────────────────────────────────

def test_habits_doc_add_mode():
    doc = (_ROOT / "docs" / "features" / "habits.md").read_text()
    assert "add" in doc.lower() and "mode" in doc.lower(), \
        "habits.md must document add-mode logging behavior"


# ── (h) Pace formula ──────────────────────────────────────────────────────────

def test_habits_doc_pace_formula():
    doc = (_ROOT / "docs" / "features" / "habits.md").read_text()
    assert "pace" in doc.lower(), "habits.md must document the pace formula for weekly habits"


# ── (i) Both-percentages decision ────────────────────────────────────────────

def test_habits_doc_both_percentages():
    doc = (_ROOT / "docs" / "features" / "habits.md").read_text()
    assert "elapsed" in doc.lower(), \
        "habits.md must state that elapsed % drives the wheel"
    # full-week % drives the grid
    lower = doc.lower()
    assert "full" in lower and "grid" in lower, \
        "habits.md must state that full-week % drives the grid"


# ── (j) No per-habit /progress calls in habits.js ────────────────────────────

def test_no_per_habit_progress_calls():
    # The old pattern fetches /api/habits/{id}/progress individually
    # No fetch to any URL ending in /progress should appear
    assert "/progress" not in _JS, \
        "habits.js must not contain per-habit /progress calls; all data comes from /api/habits/week"


# ── (k) No orphaned dead CSS from old list design ────────────────────────────

def test_no_dead_css_week_habit_icon():
    # .week-habit-icon is dead — icon uses .habit-icon-chip via habitIconHTML()
    assert ".week-habit-icon" not in _HTML, \
        "habits.html must not have orphaned .week-habit-icon CSS (icon rendered via .habit-icon-chip)"


def test_no_dead_responsive_css_week_habit_name_row():
    # Old responsive override for .week-habit-name-row is dead
    assert ".week-habit-name-row" not in _HTML, \
        "habits.html must not have orphaned .week-habit-name-row CSS"


def test_no_dead_responsive_css_week_habit_bar_outer():
    # Old responsive override for .week-habit-bar-outer is dead
    assert ".week-habit-bar-outer" not in _HTML, \
        "habits.html must not have orphaned .week-habit-bar-outer CSS (replaced by smooth/segmented bars)"


# ── (l) Modal code retained ───────────────────────────────────────────────────

def test_modal_css_present_in_html():
    assert ".modal-overlay" in _HTML, "habits.html must retain the habit modal overlay CSS"
    assert "habit-modal" in _HTML, "habits.html must retain the #habit-modal element"


def test_modal_js_present():
    assert "openHabitForm" in _JS, "habits.js must retain openHabitForm() for the create flow"
    assert "openEditModal" in _JS, "habits.js must retain openEditModal() for the edit flow"
    assert "archiveHabit" in _JS, "habits.js must retain archiveHabit() for the archive flow"


# ── (m) Single /api/habits/week call on initial load ─────────────────────────

def test_single_week_fetch_in_load_and_render():
    # loadAndRender must fetch /api/habits/week exactly once (via weekUrl variable)
    load_fn_match = re.search(
        r'async function loadAndRender\(\)(.*?)^}',
        _JS,
        re.DOTALL | re.MULTILINE,
    )
    assert load_fn_match, "habits.js must contain loadAndRender() function"
    fn_body = load_fn_match.group(1)

    # Count calls to fetch(weekUrl) — the week endpoint fetch
    week_endpoint_fetches = re.findall(r'fetch\(weekUrl\)', fn_body)
    assert len(week_endpoint_fetches) == 1, (
        f"loadAndRender() must call fetch(weekUrl) exactly once; found {len(week_endpoint_fetches)}"
    )

    # Confirm weekUrl is set to /api/habits/week
    assert "/api/habits/week" in fn_body, \
        "loadAndRender() must construct weekUrl pointing to /api/habits/week"


# ── (n) scheduleHeroRefresh debounced single call ────────────────────────────

def test_schedule_hero_refresh_single_fetch():
    assert "scheduleHeroRefresh" in _JS, "habits.js must contain scheduleHeroRefresh()"
    # scheduleHeroRefresh must use setTimeout (debounced)
    assert "setTimeout" in _JS, "scheduleHeroRefresh must be debounced via setTimeout"
    # It should make exactly one fetch to /api/habits/week
    refresh_match = re.search(
        r'function scheduleHeroRefresh\(\)(.*?)^}',
        _JS,
        re.DOTALL | re.MULTILINE,
    )
    assert refresh_match, "scheduleHeroRefresh() function must exist in habits.js"
    fn_body = refresh_match.group(1)
    week_fetches = re.findall(r"fetch\([^)]*week[^)]*\)", fn_body)
    assert len(week_fetches) == 1, (
        f"scheduleHeroRefresh must fetch /api/habits/week exactly once; found {len(week_fetches)}"
    )


# ── (o) CHANGELOG entry ───────────────────────────────────────────────────────

def test_changelog_habits_redesign_entry():
    changelog = (_ROOT / "CHANGELOG.md").read_text()
    assert "Habits redesign" in changelog, \
        "CHANGELOG.md must contain 'Habits redesign' entry"
    lower = changelog.lower()
    assert "week wheel" in lower, \
        "CHANGELOG entry must mention 'week wheel'"
    assert "daily grid" in lower, \
        "CHANGELOG entry must mention 'daily grid'"
    assert "day score" in lower or "day scores" in lower, \
        "CHANGELOG entry must mention 'day scores'"
    assert "weekly habits" in lower or "weekly habit" in lower, \
        "CHANGELOG entry must mention weekly habits"


# ── (p) Post-ship verification section ───────────────────────────────────────

def test_post_ship_verification_section():
    doc = (_ROOT / "docs" / "habits-redesign-investigation.md").read_text()
    lower = doc.lower()
    assert "post-ship" in lower or "post ship" in lower, \
        "habits-redesign-investigation.md must have a 'Post-ship verification' section"


def test_post_ship_smoke_flows_recorded():
    doc = (_ROOT / "docs" / "habits-redesign-investigation.md").read_text()
    lower = doc.lower()
    # All 6 smoke flows should be noted
    assert "fresh user" in lower or "starter" in lower, \
        "Post-ship section must record fresh-user / starter flow result"
    assert "check" in lower and "today" in lower, \
        "Post-ship section must record check-today flow result"
    assert "backfill" in lower, \
        "Post-ship section must record backfill flow result"
    assert "zone" in lower or "workout" in lower, \
        "Post-ship section must record workout auto-sync flow result"
    assert "manual" in lower and "weekly" in lower or "accumulate" in lower, \
        "Post-ship section must record manual weekly log flow result"
    assert "last week" in lower or "previous week" in lower or "read-only" in lower, \
        "Post-ship section must record navigate-to-last-week read-only flow result"
