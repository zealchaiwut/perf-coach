"""Tests for issue #542 — Pin Chart.js CDN to a specific version."""
import re
from pathlib import Path

TRAINING_LOG = (
    Path(__file__).parents[1] / "frontend" / "pages" / "training-log.html"
)

FLOATING_TAG_RE = re.compile(
    r'cdn\.jsdelivr\.net/npm/chart\.js@(\d+(?:\.\d+)?)'
    r'/dist/chart\.umd\.min\.js'
)
PINNED_VERSION_RE = re.compile(
    r'cdn\.jsdelivr\.net/npm/chart\.js@(\d+\.\d+\.\d+)'
    r'/dist/chart\.umd\.min\.js'
)


def _html() -> str:
    return TRAINING_LOG.read_text()


def test_chartjs_url_is_pinned_to_patch_version():
    """AC1: CDN URL must use a full semver patch version (x.y.z)."""
    html = _html()
    matches = PINNED_VERSION_RE.findall(html)
    assert matches, (
        "No pinned Chart.js CDN URL found in training-log.html. "
        "Expected a URL like chart.js@4.4.4/dist/chart.umd.min.js"
    )


def test_no_floating_chartjs_cdn_reference():
    """AC2: No floating major-only or minor-only tag remains."""
    html = _html()
    all_matches = FLOATING_TAG_RE.findall(html)
    # A match is "floating" if it does NOT have two dots (i.e., not x.y.z)
    floating = [v for v in all_matches if v.count(".") < 2]
    assert not floating, (
        f"Floating Chart.js CDN tag(s) still present: {floating}. "
        "Pin to a full patch version like @4.4.4."
    )


def test_exactly_one_chartjs_cdn_reference():
    """AC2: Only one Chart.js CDN script tag should exist."""
    html = _html()
    all_matches = PINNED_VERSION_RE.findall(html)
    assert len(all_matches) == 1, (
        f"Expected exactly 1 pinned Chart.js CDN reference, "
        f"found {len(all_matches)}."
    )
