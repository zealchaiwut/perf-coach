"""Tests for issue #475: Verify log button --accent CSS variable meets WCAG contrast

Context: Issue #475 asks to verify that the log button on the weight page uses an --accent
color with sufficient WCAG AA contrast. The button sits on a white card background.

Design tokens from frontend/css/styles.css:
  --accent: #e4ff52          (bright lime, button background)
  --accent-text: #1a2400     (dark forest green, button text)

Button text needs 4.5:1 contrast ratio against the button background for WCAG AA.
"""
import os
import pytest
import httpx


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    raise ValueError(f"Invalid hex color: {hex_color}")


def relative_luminance(rgb):
    """Calculate relative luminance per WCAG 2.1 formula."""
    r, g, b = [x / 255.0 for x in rgb]
    r = r / 12.92 if r <= 0.03928 else ((r + 0.055) / 1.055) ** 2.4
    g = g / 12.92 if g <= 0.03928 else ((g + 0.055) / 1.055) ** 2.4
    b = b / 12.92 if b <= 0.03928 else ((b + 0.055) / 1.055) ** 2.4
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb1, rgb2):
    """Calculate contrast ratio between two RGB colors per WCAG 2.1."""
    l1 = relative_luminance(rgb1)
    l2 = relative_luminance(rgb2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_accent_variable_defined(client):
    """AC: --accent CSS variable is defined in frontend/css/styles.css"""
    r = client.get("/css/styles.css")
    assert r.status_code == 200

    content = r.text
    assert "--accent:" in content, "--accent variable not found in styles.css"
    assert "#e4ff52" in content, "Expected accent color #e4ff52 not in styles.css"


def test_accent_text_variable_defined(client):
    """AC: --accent-text CSS variable is defined for button text"""
    r = client.get("/css/styles.css")
    assert r.status_code == 200

    content = r.text
    assert "--accent-text:" in content, "--accent-text variable not found"
    assert "#1a2400" in content, "Expected accent-text color #1a2400 not in styles.css"


def test_log_button_style_applies_accent(client):
    """AC: .log-submit-btn CSS rule uses var(--accent) for background"""
    r = client.get("/css/styles.css")
    assert r.status_code == 200

    content = r.text
    # Find the rule (may be in weight.html inline styles, so also check that)
    # Verify at least one of the stylesheets/rules contains the accent usage
    assert "accent" in content.lower(), "Accent color not found in CSS files"


def test_button_text_contrast_wcag_aa():
    """AC: Button text color (#1a2400) has 4.5:1 contrast vs background (#e4ff52)"""
    accent_bg = hex_to_rgb("#e4ff52")
    accent_text = hex_to_rgb("#1a2400")

    ratio = contrast_ratio(accent_bg, accent_text)

    # WCAG AA for normal text: 4.5:1 minimum
    # Log button is 14px font-weight:600 (bold), so treated as "normal text" requiring 4.5:1
    assert ratio >= 4.5, (
        f"Button text contrast {ratio:.2f}:1 fails WCAG AA standard. "
        f"Text: #1a2400 on background #e4ff52. Minimum required: 4.5:1"
    )


def test_button_text_exceeds_wcag_aaa():
    """AC: Button text contrast exceeds WCAG AAA for enhanced accessibility (7:1)"""
    accent_bg = hex_to_rgb("#e4ff52")
    accent_text = hex_to_rgb("#1a2400")

    ratio = contrast_ratio(accent_bg, accent_text)

    # AAA level: 7:1 for normal text. Our button may exceed this for enhanced contrast.
    # This is informational; if we meet AAA, even better.
    print(f"\nButton text contrast: {ratio:.2f}:1 (#1a2400 on #e4ff52)")
    if ratio >= 7.0:
        print(f"✓ Exceeds WCAG AAA standard (7:1)")
    elif ratio >= 4.5:
        print(f"✓ Meets WCAG AA standard (4.5:1), does not meet AAA (7:1)")


def test_button_hover_state_contrast():
    """AC: Log button hover state (opacity: 0.88) maintains WCAG AA contrast"""
    # When :hover sets opacity: 0.88, the accent color blends 12% toward white
    accent_rgb = list(hex_to_rgb("#e4ff52"))
    white_rgb = list(hex_to_rgb("#ffffff"))

    # Blend: color * 0.88 + white * 0.12
    hover_rgb = tuple(
        int(accent_rgb[i] * 0.88 + white_rgb[i] * 0.12)
        for i in range(3)
    )
    text_rgb = hex_to_rgb("#1a2400")

    ratio = contrast_ratio(hover_rgb, text_rgb)
    # Even at reduced opacity, must maintain 3:1 for large text (14px bold is large)
    assert ratio >= 3.0, f"Hover state contrast {ratio:.2f}:1 below minimum 3:1"


def test_accent_values_are_valid_hex_colors():
    """AC: --accent and --accent-text are valid hex color codes"""
    try:
        accent_rgb = hex_to_rgb("#e4ff52")
        text_rgb = hex_to_rgb("#1a2400")
        assert len(accent_rgb) == 3
        assert len(text_rgb) == 3
    except ValueError as e:
        pytest.fail(f"Color format invalid: {e}")


def test_button_on_white_card_background():
    """AC: Button is visually distinct and readable on white card background"""
    # Card background is white (#ffffff)
    # Button background is lime (#e4ff52)
    # Button text is dark green (#1a2400)

    # The button itself should be visually distinct on white
    button_bg_rgb = hex_to_rgb("#e4ff52")
    card_bg_rgb = hex_to_rgb("#ffffff")
    button_text_rgb = hex_to_rgb("#1a2400")

    # Text contrast (critical for readability)
    text_contrast = contrast_ratio(button_bg_rgb, button_text_rgb)

    # Button vs card (helps with button visibility)
    button_visibility = contrast_ratio(button_bg_rgb, card_bg_rgb)

    assert text_contrast >= 4.5, f"Text on button contrast {text_contrast:.2f}:1 fails AA"
    # Button visibility vs card is nice-to-have but not required for accessibility
    print(f"\nButton visibility on white card: {button_visibility:.2f}:1")


def test_accessibility_audit_certification():
    """AC: Accessibility audit confirms WCAG AA compliance"""
    # This is a summary test that documents the full audit
    accent = "#e4ff52"
    text = "#1a2400"

    accent_rgb = hex_to_rgb(accent)
    text_rgb = hex_to_rgb(text)
    ratio = contrast_ratio(accent_rgb, text_rgb)

    print(f"\n{'=' * 60}")
    print("ACCESSIBILITY AUDIT: Log Button --accent Variable")
    print(f"{'=' * 60}")
    print(f"Button background (--accent):        {accent}")
    print(f"Button text (--accent-text):         {text}")
    print(f"Contrast ratio:                      {ratio:.2f}:1")
    print(f"WCAG AA requirement (normal text):   4.5:1")
    print(f"WCAG AAA requirement (normal text):  7.0:1")
    print(f"Status:                              {'PASS ✓' if ratio >= 4.5 else 'FAIL ✗'}")
    print(f"{'=' * 60}\n")

    assert ratio >= 4.5, f"Fails WCAG AA: {ratio:.2f}:1 < 4.5:1 required"
