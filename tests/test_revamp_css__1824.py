"""Issue #1824 — revamp.css tokens scoped to rv-page."""
from pathlib import Path


def test_revamp_css_uses_prefixed_tokens_only():
    text = Path("frontend/css/revamp.css").read_text(encoding="utf-8")
    assert "body.rv-page" in text
    assert "--rv-primary:" in text
    assert "--rv-accent:" in text
    assert ".rv-btn" in text
    assert ".rv-drawer" in text


def test_components_page_and_helpers_exist():
    assert Path("frontend/pages/v2-components.html").is_file()
    assert Path("frontend/js/revamp-ui.js").is_file()