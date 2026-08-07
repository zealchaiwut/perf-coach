"""Issue #521 superseded by weight tab revamp — streak removed; coverage replaces adherence."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEIGHT_HTML = (ROOT / "frontend/pages/weight.html").read_text()
WEIGHT_JS = (ROOT / "frontend/js/weight.js").read_text()


def test_streak_compute_removed():
    assert "_computeStreak" not in WEIGHT_JS


def test_streak_badge_removed_from_html():
    assert 'id="streak-value"' not in WEIGHT_HTML


def test_coverage_strip_present():
    assert "cov-strip" in WEIGHT_HTML
    assert "renderCoverageGating" in WEIGHT_JS


def test_coverage_uses_chart_stats():
    assert "coverage_pct" in WEIGHT_JS
    assert "stats.rate" in WEIGHT_JS or "stats && stats.rate" in WEIGHT_JS
