"""Tests for issue #642: Change Training Log Close Button to Grey.

Acceptance Criteria tested:
  AC1  - Close button is rendered in grey (#6B7280 / var(--text-sub))
  AC2  - Grey colour meets WCAG AA contrast against its background
  AC3  - Hover and focus states are present with grey-tinted variants
  AC4  - No other button classes are unintentionally altered by this change
  AC5  - Dark mode: out of scope (not implemented in this app)

Static asset contract tests anchored to the frontend HTML source.
"""
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_HTML = (_REPO / "frontend" / "pages" / "training-log.html").read_text()


# ── AC1: Close button colour is the design-system grey token ─────────────────

def test_ac1_dp_icon_btn_uses_text_sub_token():
    """dp-icon-btn must use var(--text-sub) for its colour, not the old #555."""
    # Extract the .dp-icon-btn rule block (stop at the next rule)
    m = re.search(
        r'\.dp-icon-btn\s*\{([^}]+)\}',
        _HTML,
    )
    assert m, ".dp-icon-btn rule not found in training-log.html"
    rule_body = m.group(1)
    assert 'var(--text-sub)' in rule_body, (
        f".dp-icon-btn must set color: var(--text-sub). Found rule body: {rule_body!r}"
    )


def test_ac1_dp_icon_btn_does_not_use_555():
    """dp-icon-btn must NOT use the old hard-coded #555 colour."""
    m = re.search(r'\.dp-icon-btn\s*\{([^}]+)\}', _HTML)
    assert m, ".dp-icon-btn rule not found"
    rule_body = m.group(1)
    assert '#555' not in rule_body, (
        ".dp-icon-btn must not use #555; switch to var(--text-sub)"
    )


def test_ac1_text_sub_token_resolves_to_6b7280():
    """The --text-sub CSS custom property must resolve to #6b7280 (design-system value)."""
    # The token should be defined in styles.css or in the page's :root
    import re as _re
    css_path = _REPO / "frontend" / "css" / "styles.css"
    css = css_path.read_text()
    # Look for --text-sub: #6b7280 (allow surrounding whitespace / semicolon)
    assert _re.search(r'--text-sub\s*:\s*#6[Bb]7280', css), (
        "--text-sub must be defined as #6b7280 in styles.css"
    )


# ── AC2: WCAG AA contrast ─────────────────────────────────────────────────────

def test_ac2_text_sub_passes_wcag_aa():
    """#6b7280 on white (#ffffff) must achieve at least 4.5:1 contrast (WCAG AA normal text).

    Using the WCAG relative luminance formula directly so the test is self-contained.
    """
    def _linearise(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    def _luminance(r: int, g: int, b: int) -> float:
        return 0.2126 * _linearise(r) + 0.7152 * _linearise(g) + 0.0722 * _linearise(b)

    def _contrast(lum1: float, lum2: float) -> float:
        lighter, darker = max(lum1, lum2), min(lum1, lum2)
        return (lighter + 0.05) / (darker + 0.05)

    grey = _luminance(0x6b, 0x72, 0x80)   # #6b7280
    white = _luminance(0xff, 0xff, 0xff)  # #ffffff

    ratio = _contrast(white, grey)
    assert ratio >= 4.5, (
        f"#6b7280 on white fails WCAG AA: contrast ratio is {ratio:.2f}:1 (need ≥ 4.5:1)"
    )


# ── AC3: Hover and focus states with grey-tinted variants ────────────────────

def test_ac3_hover_state_present_for_dp_icon_btn():
    """A :hover rule for .dp-icon-btn must be present."""
    assert '.dp-icon-btn:hover' in _HTML, (
        ".dp-icon-btn:hover rule is missing from training-log.html"
    )


def test_ac3_hover_has_background():
    """The hover rule must set a background (grey-tinted variant)."""
    m = re.search(r'\.dp-icon-btn:hover\s*\{([^}]+)\}', _HTML)
    assert m, ".dp-icon-btn:hover rule not found"
    assert 'background' in m.group(1), (
        ".dp-icon-btn:hover must include a background property"
    )


def test_ac3_focus_visible_state_present():
    """A :focus-visible rule must target .dp-icon-btn (WCAG 2.4.7)."""
    assert '.dp-icon-btn:focus-visible' in _HTML, (
        ".dp-icon-btn:focus-visible rule is missing from training-log.html"
    )


# ── AC4: No other button classes unintentionally changed ─────────────────────

def test_ac4_qa_close_btn_unchanged():
    """The .qa-close-btn (duplicate panel close) must still use var(--text-sub)."""
    m = re.search(r'\.qa-close-btn\s*\{([^}]+)\}', _HTML)
    assert m, ".qa-close-btn rule not found"
    rule_body = m.group(1)
    assert 'var(--text-sub)' in rule_body, (
        ".qa-close-btn must still use var(--text-sub) — do not alter it"
    )


def test_ac4_primary_button_class_unchanged():
    """Primary button class (btn--primary or .btn-primary) must not reference #6b7280."""
    # Ensure no primary button gained the grey colour unintentionally
    primary_pattern = re.search(
        r'\.btn[-_]primary\s*\{([^}]+)\}|\.btn--primary\s*\{([^}]+)\}',
        _HTML,
    )
    if primary_pattern:
        rule = primary_pattern.group(1) or primary_pattern.group(2)
        assert '#6b7280' not in rule and 'text-sub' not in rule, (
            "Primary button must not use grey colour"
        )


def test_ac4_dp_close_btn_present_in_html():
    """The #dp-close-btn element must still be present in the HTML."""
    assert 'id="dp-close-btn"' in _HTML, "#dp-close-btn is missing from training-log.html"


def test_ac4_dp_close_btn_uses_dp_icon_btn_class():
    """#dp-close-btn must keep the dp-icon-btn class (class reassignment check)."""
    m = re.search(r'id="dp-close-btn"[^>]*class="([^"]*)"', _HTML)
    if not m:
        m = re.search(r'class="([^"]*)"[^>]*id="dp-close-btn"', _HTML)
    assert m, "#dp-close-btn element not found"
    assert 'dp-icon-btn' in m.group(1), (
        "#dp-close-btn must still carry the dp-icon-btn class"
    )
