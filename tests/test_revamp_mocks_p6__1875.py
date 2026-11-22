"""P6-1 (#1875) — provisional Phase 6 mocks indexed."""
from pathlib import Path

ROOT = Path("docs/revamp")
INDEX = (ROOT / "INDEX.md").read_text(encoding="utf-8")
SOURCE = ROOT / "mocks" / "source"


def test_three_provisional_dc_sources_exist():
    for name in ("HomeSeason.dc.html", "SeasonRoad.dc.html", "WeeklyCheckin.dc.html"):
        p = SOURCE / name
        assert p.is_file(), name
        text = p.read_text(encoding="utf-8")
        assert "PROVISIONAL" in text


def test_index_lists_phase6_with_provisional_note():
    for row in ("HomeSeason", "SeasonRoad", "WeeklyCheckin"):
        assert row in INDEX
    assert "provisional" in INDEX.lower()


def test_previews_and_screenshots_exist():
    for row in ("HomeSeason", "SeasonRoad", "WeeklyCheckin"):
        assert (ROOT / "mocks" / "preview" / f"{row}.html").is_file()
        assert (ROOT / "mocks" / "screenshots" / f"{row}.png").is_file()