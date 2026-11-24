"""P6-13 (#1887) — weekly check-in page wiring."""
from pathlib import Path

HTML = Path("frontend/pages/v2-weekly-check-in.html").read_text(encoding="utf-8")
JS = Path("frontend/js/v2-weekly-check-in.js").read_text(encoding="utf-8")
CSS = Path("frontend/css/revamp.css").read_text(encoding="utf-8")


def test_page_route_registered():
    from backend.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/v2/performance/check-in" in paths


def test_step_bar_and_layout_at_390():
    assert "wci-steps" in HTML and "Last week's changes" in HTML
    assert "wci-layout" in CSS
    assert "@media (max-width: 900px)" in CSS


def test_four_steps_and_api_wiring():
    for needle in (
        "data-checkin-step",
        "Last week's changes",
        "Copy · talk · paste back",
        "/api/weekly-check-in",
        "/api/weekly-check-in/refresh",
        "wci-preview",
        "Paste change list",
        "v2-weekly-check-in.js",
        "fetchWithCsrf",
    ):
        assert needle in HTML or needle in JS, needle


def test_coach_block_links_to_checkin_page():
    from backend.services import coach_block as cb

    assert cb.CHECKIN_LINK == "/v2/performance/check-in"