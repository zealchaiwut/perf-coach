"""
TDD tests for issue #475 – Verify log button --accent CSS variable meets WCAG contrast.

File: frontend/pages/weight.html:295 (log-submit-btn)
Concern: log button uses var(--accent) background + var(--accent-text) foreground;
         the :hover state reduces opacity to 0.88. Verify WCAG AA (4.5:1) is met.

All tests are pure static-file analysis – no live server required.
"""

import re
from pathlib import Path

STYLES_CSS   = Path(__file__).parent.parent / "frontend" / "css" / "styles.css"
WEIGHT_HTML  = Path(__file__).parent.parent / "frontend" / "pages" / "weight.html"

_styles = STYLES_CSS.read_text()
_weight = WEIGHT_HTML.read_text()

# ── Colour-math helpers ──────────────────────────────────────────────────────

def _srgb_linear(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _srgb_linear(r) + 0.7152 * _srgb_linear(g) + 0.0722 * _srgb_linear(b)


def _contrast(hex_a: str, hex_b: str) -> float:
    l1, l2 = _luminance(hex_a), _luminance(hex_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ── AC1: --accent is defined in the shared stylesheet ───────────────────────

def test_accent_defined_in_shared_stylesheet():
    """--accent token is defined in frontend/css/styles.css."""
    assert "--accent:" in _styles, \
        "--accent must be declared in frontend/css/styles.css"


def test_accent_text_defined_in_shared_stylesheet():
    """--accent-text token is defined in frontend/css/styles.css."""
    assert "--accent-text:" in _styles, \
        "--accent-text must be declared in frontend/css/styles.css"


def test_accent_hex_value_in_stylesheet():
    """--accent resolves to a known hex colour (currently #e4ff52)."""
    m = re.search(r"--accent\s*:\s*(#[0-9a-fA-F]{6})", _styles)
    assert m, "--accent must be declared with an explicit hex colour in styles.css"
    # Record the actual value so the test fails clearly if someone changes it
    # without updating the contrast comment.
    assert m.group(1).lower() == "#e4ff52", (
        f"--accent is {m.group(1)} – if you changed the colour, update the "
        "WCAG contrast comment and this assertion."
    )


def test_accent_text_hex_value_in_stylesheet():
    """--accent-text resolves to a known hex colour (currently #1a2400)."""
    m = re.search(r"--accent-text\s*:\s*(#[0-9a-fA-F]{6})", _styles)
    assert m, "--accent-text must be declared with an explicit hex colour in styles.css"
    assert m.group(1).lower() == "#1a2400", (
        f"--accent-text is {m.group(1)} – if you changed the colour, update "
        "the WCAG contrast comment and this assertion."
    )


# ── AC2: text-on-accent contrast meets WCAG AA ──────────────────────────────

def test_accent_text_on_accent_meets_wcag_aa():
    """--accent-text on --accent achieves >= 4.5:1 (WCAG AA normal text)."""
    ratio = _contrast("#1a2400", "#e4ff52")
    assert ratio >= 4.5, (
        f"--accent-text on --accent contrast is {ratio:.2f}:1, "
        "below WCAG AA minimum of 4.5:1"
    )


def test_accent_text_on_accent_meets_wcag_aaa():
    """--accent-text on --accent achieves >= 7:1 (WCAG AAA) — well over AA."""
    ratio = _contrast("#1a2400", "#e4ff52")
    assert ratio >= 7.0, (
        f"Contrast {ratio:.2f}:1 falls below WCAG AAA (7:1). "
        "The design token comment claimed ~14:1 – re-check the hex values."
    )


# ── AC3: weight page log button uses both tokens ─────────────────────────────

def test_log_button_uses_accent_background():
    """log-submit-btn in weight.html sets background to var(--accent)."""
    css_block = re.search(
        r"\.log-submit-btn\s*\{[^}]+\}", _weight, re.DOTALL
    )
    assert css_block, "No .log-submit-btn CSS rule found in weight.html"
    block = css_block.group()
    assert "var(--accent)" in block, \
        "log-submit-btn must use background: var(--accent)"


def test_log_button_uses_accent_text_color():
    """log-submit-btn in weight.html sets color to var(--accent-text)."""
    css_block = re.search(
        r"\.log-submit-btn\s*\{[^}]+\}", _weight, re.DOTALL
    )
    assert css_block, "No .log-submit-btn CSS rule found in weight.html"
    block = css_block.group()
    assert "var(--accent-text)" in block, \
        "log-submit-btn must use color: var(--accent-text) for WCAG-compliant text"


# ── AC4: hover opacity does not violate contrast ─────────────────────────────

def test_hover_opacity_still_passes_wcag_aa():
    """At hover opacity 0.88, blended text contrast still meets WCAG AA (4.5:1).

    Worst-case blend: accent-text (#1a2400) at 88% opacity over accent (#e4ff52).
    The accent background is fully opaque so the text channel blends against it.
    """
    # Alpha-blend accent-text over accent for the text foreground
    # text_blended = alpha * text_color + (1 - alpha) * bg_color
    alpha = 0.88
    text = (0x1a, 0x24, 0x00)
    bg   = (0xe4, 0xff, 0x52)
    blended = tuple(int(alpha * t + (1 - alpha) * b) for t, b in zip(text, bg))
    blended_hex = "#{:02x}{:02x}{:02x}".format(*blended)
    ratio = _contrast(blended_hex, "#e4ff52")
    assert ratio >= 4.5, (
        f"At hover opacity 0.88, blended contrast is {ratio:.2f}:1 "
        f"(blended text {blended_hex} on #e4ff52). WCAG AA requires 4.5:1."
    )


# ── AC5: WCAG contrast comment present in stylesheet ─────────────────────────

def test_accent_has_contrast_comment_in_stylesheet():
    """styles.css documents the --accent contrast ratio in a CSS comment."""
    accent_line = next(
        (ln for ln in _styles.splitlines() if "--accent:" in ln and "accent-text" not in ln),
        ""
    )
    assert "14" in accent_line or "WCAG" in accent_line or "contrast" in accent_line.lower(), (
        "The --accent declaration in styles.css must include a contrast-ratio "
        "comment (e.g. '/* ... 14.44:1 (WCAG AAA) */') so reviewers can verify "
        "the token at a glance. Found: " + repr(accent_line)
    )
