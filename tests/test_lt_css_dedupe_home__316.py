"""Tests for issue #316: Remove duplicate .lt-* CSS rules in home.html.

Acceptance criteria verified:
(a) Exactly one LOG TODAY CARD section comment
(b) Core .lt-* class definitions each appear exactly once
(c) Responsive .lt-grid override appears exactly once
"""
import pathlib
import re

HOME_HTML = pathlib.Path(__file__).parents[1] / "frontend" / "pages" / "home.html"


def _text():
    return HOME_HTML.read_text()


# (a) Exactly one LOG TODAY CARD section
def test_single_log_today_card_section():
    count = _text().count("/* ---- LOG TODAY CARD ---- */")
    assert count == 1, f"Expected 1 LOG TODAY CARD section, found {count}"


# (b) Core .lt-* definitions each appear once
def test_lt_grid_defined_once():
    matches = re.findall(r"\.lt-grid\s*\{\s*display:\s*grid", _text())
    assert len(matches) == 1, f"Expected 1 .lt-grid definition, found {len(matches)}"


def test_lt_input_defined_once():
    matches = re.findall(r"\.lt-input\s*\{", _text())
    assert len(matches) == 1, f"Expected 1 .lt-input rule, found {len(matches)}"


def test_lt_save_btn_defined_once():
    matches = re.findall(r"\.lt-save-btn\s*\{", _text())
    assert len(matches) == 1, f"Expected 1 .lt-save-btn rule, found {len(matches)}"


def test_lt_feedback_defined_once():
    matches = re.findall(r"\.lt-feedback\s*\{", _text())
    assert len(matches) == 1, f"Expected 1 .lt-feedback rule, found {len(matches)}"


# (c) Responsive .lt-grid override appears exactly once
def test_lt_grid_responsive_override_once():
    matches = re.findall(r"\.lt-grid\s*\{\s*grid-template-columns:\s*repeat\(3,\s*1fr\)", _text())
    assert len(matches) == 1, f"Expected 1 responsive .lt-grid override, found {len(matches)}"
