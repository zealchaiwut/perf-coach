"""P5-CP — revamp shell present for checkpoint walkthrough."""
from pathlib import Path


_V2_PAGES = [
    "v2-home.html",
    "v2-training-plan.html",
    "v2-training-log.html",
    "v2-training-trends.html",
    "v2-performance.html",
    "v2-training-admin.html",
    "v2-settings.html",
    "v2-settings-plan.html",
]


def test_v2_pages_exist():
    root = Path("frontend/pages")
    for name in _V2_PAGES:
        assert (root / name).is_file(), name


def test_mock_previews_exist():
    preview = Path("docs/revamp/mocks/preview")
    if not preview.is_dir():
        return
    assert any(preview.glob("*.html")), "expected mock preview HTML"


def test_cleanup_follow_up_documented():
    text = Path("docs/revamp/CLEANUP.md").read_text(encoding="utf-8")
    assert "training.html" in text