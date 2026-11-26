"""V1 screenshot picker restored on the v2 session drawer."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT = (ROOT / "frontend/js/lib/run-screenshot.js").read_text(encoding="utf-8")
DRAWER = (ROOT / "frontend/js/v2-run-drawer.js").read_text(encoding="utf-8")
HTML = (ROOT / "frontend/pages/v2-training-log.html").read_text(encoding="utf-8")


def test_v2_log_loads_screenshot_module():
    assert "run-screenshot.js" in HTML
    assert "v2-run-drawer.js" in HTML
    assert HTML.find("run-screenshot.js") < HTML.find("v2-run-drawer.js")


def test_drawer_opens_screenshot_picker():
    assert "RunScreenshot.capture" in DRAWER
    assert "v2-drawer-shot" in DRAWER


def test_picker_has_v1_choices():
    for label in (
        "Dark",
        "Light",
        "With graph",
        "No graph",
        "Manual",
        "1 km",
        "Save image",
        "Theme",
        "Graph",
        "Laps",
    ):
        assert label in SHOT, label
    assert "rd4_shot_theme" in SHOT
    assert "rd4_shot_graph" in SHOT
    assert "rd4_shot_lap" in SHOT
    assert "buildShareCard" in SHOT
