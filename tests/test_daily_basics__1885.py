"""Issue #1885 — Home daily basics panel wiring (P6-11)."""
from __future__ import annotations

from pathlib import Path


def test_v2_home_has_daily_basics_js():
    text = Path("frontend/js/v2-home.js").read_text(encoding="utf-8")
    assert "Daily basics" in text
    assert "rv-daily-basics" in text
    assert "/api/body-log" in text
    assert "data-bl-field" in text
    assert "dailyBasicsHtml(data.daily_basics)" in text


def test_daily_basics_touch_targets_css():
    text = Path("frontend/css/revamp.css").read_text(encoding="utf-8")
    assert "rv-daily-row" in text
    assert "min-height: 44px" in text


def test_revamp_home_payload_includes_daily_basics():
    text = Path("backend/services/revamp_home.py").read_text(encoding="utf-8")
    assert '"daily_basics"' in text
    assert "support_blocks" in text