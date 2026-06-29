"""Tests for issue #453: Split habits.html into smaller components.

AC anchors verified:
  (ac1)  frontend/css/habits.css exists and is non-trivial (> 500 lines)
  (ac2)  habits.html loads habits.css via <link rel="stylesheet">
  (ac3)  habits.html inline <style> block is absent or minimal (< 50 lines)
  (ac4)  habits.html total line count is < 500 (CSS extracted)
  (ac5)  hero section (hero-row) is still present in habits.html
  (ac6)  daily grid section (habits-day-grid) is still present in habits.html
  (ac7)  weekly habits section (weekly-habits) is still present in habits.html
  (ac8)  habit slideover modal (habit-slideover) is still present in habits.html
  (ac9)  habits.css contains the wheel card styles (hw2-card)
  (ac10) habits.css contains responsive breakpoint rules (@media)
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "frontend" / "pages"
CSS_DIR = ROOT / "frontend" / "css"

HABITS_HTML = (PAGES_DIR / "habits.html").read_text()
HABITS_CSS_PATH = CSS_DIR / "habits.css"


# ── AC1: habits.css exists and is non-trivial ─────────────────────────────────

def test_ac1_habits_css_exists():
    """frontend/css/habits.css must exist."""
    assert HABITS_CSS_PATH.exists(), "frontend/css/habits.css must exist"


def test_ac1_habits_css_non_trivial():
    """habits.css must have more than 500 lines (contains extracted styles)."""
    css_lines = HABITS_CSS_PATH.read_text().splitlines()
    assert len(css_lines) > 500, \
        f"habits.css has only {len(css_lines)} lines — expected > 500"


# ── AC2: habits.html links habits.css ────────────────────────────────────────

def test_ac2_habits_html_links_habits_css():
    """habits.html must load habits.css via <link rel="stylesheet">."""
    assert 'href="css/habits.css"' in HABITS_HTML or \
           "href='css/habits.css'" in HABITS_HTML, \
        "habits.html must reference habits.css via <link>"


# ── AC3: inline <style> block is absent or minimal ───────────────────────────

def test_ac3_no_large_inline_style_block():
    """habits.html inline <style> block (if any) must be < 50 lines."""
    # Find style blocks
    style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', HABITS_HTML, re.DOTALL)
    if not style_blocks:
        return  # no inline styles at all — pass
    total_inline_lines = sum(len(block.splitlines()) for block in style_blocks)
    assert total_inline_lines < 50, \
        f"habits.html has {total_inline_lines} lines of inline CSS — must be < 50 after extraction"


# ── AC4: habits.html line count reduced ──────────────────────────────────────

def test_ac4_habits_html_line_count_reduced():
    """habits.html must be < 500 lines after CSS extraction."""
    line_count = len(HABITS_HTML.splitlines())
    assert line_count < 500, \
        f"habits.html has {line_count} lines — must be < 500 after CSS extraction"


# ── AC5: hero section still present ──────────────────────────────────────────

def test_ac5_hero_row_present():
    """hero-row section must still be present in habits.html."""
    assert 'id="hero-row"' in HABITS_HTML or 'class="hero-row"' in HABITS_HTML, \
        "habits.html must still contain the hero-row section"


# ── AC6: daily grid section still present ────────────────────────────────────

def test_ac6_daily_grid_present():
    """habits-day-grid section must still be present in habits.html."""
    assert "habits-day-grid" in HABITS_HTML, \
        "habits.html must still contain the habits-day-grid section"


# ── AC7: weekly habits section still present ─────────────────────────────────

def test_ac7_weekly_habits_present():
    """weekly-habits section must still be present in habits.html."""
    assert "weekly-habits" in HABITS_HTML, \
        "habits.html must still contain the weekly-habits section"


# ── AC8: habit slideover modal still present ─────────────────────────────────

def test_ac8_habit_slideover_present():
    """habit-slideover modal must still be present in habits.html."""
    assert "habit-slideover" in HABITS_HTML, \
        "habits.html must still contain the habit-slideover modal"


# ── AC9: habits.css contains wheel card styles ───────────────────────────────

def test_ac9_habits_css_contains_wheel_styles():
    """habits.css must contain the hw2-card wheel card styles."""
    habits_css = HABITS_CSS_PATH.read_text()
    assert "hw2-card" in habits_css, \
        "habits.css must contain the hw2-card wheel card styles"


# ── AC10: habits.css contains responsive breakpoints ─────────────────────────

def test_ac10_habits_css_has_media_queries():
    """habits.css must contain @media breakpoint rules."""
    habits_css = HABITS_CSS_PATH.read_text()
    assert "@media" in habits_css, \
        "habits.css must contain @media responsive breakpoint rules"
