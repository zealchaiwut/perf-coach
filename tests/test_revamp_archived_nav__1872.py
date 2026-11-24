"""P5-10 retire Weight/Habits from nav when revamp on."""
from __future__ import annotations

from pathlib import Path


def test_archived_banner_script_on_legacy_pages():
    for page in ("weight.html", "habits.html"):
        html = Path("frontend/pages") / page
        text = html.read_text(encoding="utf-8")
        assert "revamp-archived-banner.js" in text
        assert "data-revamp-archived" in text


def test_nav_hides_weight_and_habits_when_revamp():
    js = Path("frontend/js/nav.js").read_text(encoding="utf-8")
    assert "navLinksForBar" in js
    assert 'l.href !== "/habits"' in js
    assert 'l.href !== "/weight"' in js


def test_nav_drops_revamp_back_link():
    js = Path("frontend/js/nav.js").read_text(encoding="utf-8")
    assert "injectRevampLink" not in js