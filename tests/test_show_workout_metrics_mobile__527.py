"""Tests for issue #527: Show workout metrics and badges on mobile viewports.

The `@media (max-width:599px)` block in training-log.html used to hide
`.entry-metric` and `.source-badges-wrap` entirely, stripping distance, pace,
duration, and source badges from list rows on phones. These tests anchor each
acceptance criterion to the static CSS so the regression cannot return.

Pure frontend (CSS) change — parsed statically from the page source.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
PAGE = (ROOT / "frontend" / "pages" / "training-log.html").read_text()


def _media_block(max_px: int) -> str:
    """Return the body of the `@media (max-width: <max_px>px)` block."""
    m = re.search(
        r"@media\s*\(\s*max-width:\s*%dpx\s*\)\s*\{" % max_px,
        PAGE,
    )
    assert m, f"no @media (max-width: {max_px}px) block found"
    # walk braces from the opening { to find the matching close
    start = m.end() - 1
    depth = 0
    for i in range(start, len(PAGE)):
        if PAGE[i] == "{":
            depth += 1
        elif PAGE[i] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start + 1 : i]
    raise AssertionError(f"unterminated @media (max-width: {max_px}px) block")


# The mobile breakpoint was standardised from 599px to 640px elsewhere in the
# project; this module was never updated. Because the lookup ran at MODULE
# SCOPE, its assert became a COLLECTION ERROR rather than a test failure — so
# pytest reported it as a top-level interruption and the whole module silently
# left the suite (issue #1606).
#
# Resolved lazily now: a future breakpoint change fails this module's tests
# loudly instead of deleting them from the run.
_MOBILE_MAX_PX = 640


def _mobile():
    return _media_block(_MOBILE_MAX_PX)


def _declarations_for(block: str, selector: str):
    """Return the list of declaration bodies for every rule whose selector
    list contains `selector` within the given CSS block."""
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", block):
        selectors = [s.strip() for s in sel.split(",")]
        if any(selector == s or s.endswith(" " + selector) or s == selector
               for s in selectors):
            out.append(body)
    return out


# ── AC 1: Distance, pace, duration visible at 375px and 599px ────────────────

def test_entry_metric_not_hidden_on_mobile():
    """`.entry-metric` (distance/pace/duration) must NOT be display:none ≤599px."""
    for body in _declarations_for(_mobile(), ".entry-metric"):
        assert "display: none" not in body.replace(" ", " "), \
            ".entry-metric is hidden in the ≤599px block"
        assert "display:none" not in body.replace(" ", ""), \
            ".entry-metric is hidden in the ≤599px block"


def test_entry_metric_rule_present_on_mobile():
    """The mobile block must still address `.entry-metric` (keep it laid out)."""
    assert ".entry-metric" in _mobile(), \
        "no .entry-metric rule in the ≤599px block"


# ── AC 2: Source badge visible on mobile (icon-only acceptable) ──────────────

def test_source_badges_not_hidden_on_mobile():
    """`.source-badges-wrap` must NOT be display:none ≤599px."""
    for body in _declarations_for(_mobile(), ".source-badges-wrap"):
        assert "display:none" not in body.replace(" ", ""), \
            ".source-badges-wrap is hidden in the ≤599px block"


def test_source_badge_markup_is_icon_sized():
    """Badge text is short (icon-style), so it renders fine when space is tight."""
    js = (ROOT / "frontend" / "js" / "training-log.js").read_text()
    # strava + stryd short glyph labels still present
    assert "source-badge--strava" in js
    assert "source-badge--stryd" in js
    assert "source-badge--manual" in js


# ── AC 3: No horizontal overflow at 375px ────────────────────────────────────

def test_rows_wrap_to_avoid_overflow_on_mobile():
    """Rows must wrap (flex-wrap) so metric/badges drop to a new line instead of
    forcing horizontal scroll at narrow widths."""
    row_bodies = _declarations_for(_mobile(), ".entry-row")
    assert row_bodies, "no .entry-row rule in the ≤599px block"
    assert any("flex-wrap: wrap" in b or "flex-wrap:wrap" in b.replace(" ", "")
               for b in row_bodies), \
        ".entry-row must use flex-wrap: wrap on mobile to prevent overflow"


def test_no_fixed_huge_widths_introduced():
    """Sanity: the page must not introduce a min-width that exceeds 375px on the
    list container."""
    # #log-list keeps a padding rule on mobile, no min-width forcing overflow
    assert "min-width: 375" not in PAGE


# ── AC 4: Desktop layout (600px+) unchanged ──────────────────────────────────

def test_mobile_rules_scoped_to_max_599():
    """The visibility fix lives inside a max-width:599px block, so 600px+ is
    untouched."""
    assert re.search(r"@media\s*\(\s*max-width:\s*599px\s*\)", PAGE), \
        "the ≤599px media query must exist"


def test_desktop_entry_metric_default_is_flex():
    """The base (non-media) `.entry-metric` rule keeps its desktop display:flex."""
    # grab the first .entry-metric rule that appears before any @media
    pre_media = PAGE.split("@media", 1)[0]
    m = re.search(r"\.entry-metric\s*\{([^{}]*)\}", pre_media)
    assert m, "base .entry-metric rule missing"
    assert "display: flex" in m.group(1) or "display:flex" in m.group(1).replace(" ", ""), \
        "desktop .entry-metric should remain display:flex"
