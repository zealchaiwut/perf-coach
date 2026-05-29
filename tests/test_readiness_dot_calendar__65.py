"""
Tests for issue #65: Add Readiness Dot to Calendar Day Cells
Server under test: http://127.0.0.1:9001
"""
import pathlib

import httpx
import pytest
from datetime import date

BASE = "http://127.0.0.1:9001"

HTML = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "calendar.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "calendar.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    users = client.get("/api/users").json()
    alice = next((u for u in users if u["name"].lower() == "alice"), None)
    assert alice, "Alice user not found in UAT database"
    return alice["id"]


# ── Band-color mapping ────────────────────────────────────────────────────────

def test_js_has_readiness_green_class():
    """calendar.js must apply readiness-green for high scores."""
    assert "readiness-green" in JS, "calendar.js must use readiness-green class"


def test_js_has_readiness_amber_class():
    """calendar.js must apply readiness-amber for moderate scores."""
    assert "readiness-amber" in JS, "calendar.js must use readiness-amber class"


def test_js_has_readiness_red_class():
    """calendar.js must apply readiness-red for low scores."""
    assert "readiness-red" in JS, "calendar.js must use readiness-red class"


def test_css_readiness_green_color():
    """calendar.html must define readiness-green with green background."""
    assert "readiness-green" in HTML, "CSS must define .readiness-green"
    assert "#16a34a" in HTML, "readiness-green must use green color #16a34a"


def test_css_readiness_amber_color():
    """calendar.html must define readiness-amber with amber background."""
    assert "readiness-amber" in HTML, "CSS must define .readiness-amber"
    assert "#eab308" in HTML, "readiness-amber must use amber color #eab308"


def test_css_readiness_red_color():
    """calendar.html must define readiness-red with red background."""
    assert "readiness-red" in HTML, "CSS must define .readiness-red"
    assert "#ef4444" in HTML, "readiness-red must use red color #ef4444"


def test_js_band_thresholds_match_home_js():
    """calendar.js readiness thresholds must mirror home.js (red<50, amber<=70, green>70)."""
    assert "< 50" in JS or "<50" in JS, "calendar.js must use threshold 50 for red band"
    assert "<= 70" in JS or "<=70" in JS, "calendar.js must use threshold 70 for amber band"


# ── Missing-data gray fallback ────────────────────────────────────────────────

def test_js_has_readiness_gray_class():
    """calendar.js must apply readiness-gray when score is null."""
    assert "readiness-gray" in JS, "calendar.js must use readiness-gray for missing data"


def test_css_readiness_gray_defined():
    """calendar.html must define readiness-gray with gray background."""
    assert "readiness-gray" in HTML, "CSS must define .readiness-gray"
    assert "#9ca3af" in HTML, "readiness-gray must use gray color #9ca3af"


def test_js_null_score_yields_gray():
    """calendar.js readinessBandClass must return readiness-gray for null score."""
    assert "readiness-gray" in JS and "score == null" in JS, (
        "calendar.js must return readiness-gray when score is null"
    )


# ── Tooltip content composition ───────────────────────────────────────────────

def test_js_tooltip_has_readiness_label():
    """calendar.js combined tooltip must contain 'Readiness:' label."""
    assert "Readiness:" in JS, "calendar.js tooltip must include 'Readiness:' label"


def test_js_tooltip_no_data_label():
    """calendar.js must show 'Readiness: No data' when score is absent."""
    assert "No data" in JS, "calendar.js must include 'No data' text for missing readiness"


def test_js_tooltip_energy_label():
    """calendar.js combined tooltip must still contain 'Energy:' label."""
    assert "Energy:" in JS, "calendar.js tooltip must include 'Energy:' label"


def test_js_tooltip_sleep_label():
    """calendar.js combined tooltip must still contain 'Sleep:' label."""
    assert "Sleep:" in JS, "calendar.js tooltip must include 'Sleep:' label"


def test_css_tooltip_hover_on_container():
    """calendar.html tooltip CSS must trigger on .cal-recovery-dots hover."""
    assert "cal-recovery-dots[data-tooltip]" in HTML, (
        "CSS tooltip must be on .cal-recovery-dots[data-tooltip], not individual dots"
    )
    assert ":hover::after" in HTML, "CSS tooltip must use :hover::after"


# ── Readiness dot element ─────────────────────────────────────────────────────

def test_js_renders_readiness_dot():
    """calendar.js must create a cal-recovery-dot--readiness element."""
    assert "cal-recovery-dot--readiness" in JS, (
        "calendar.js must render a readiness dot with class 'cal-recovery-dot--readiness'"
    )


def test_js_fetches_readiness_api():
    """calendar.js must call /api/readiness endpoint."""
    assert "/api/readiness" in JS, (
        "calendar.js must fetch /api/readiness to get readiness scores"
    )


# ── Sprint 7 regression ───────────────────────────────────────────────────────

def test_sprint7_sleep_dot_class_preserved():
    """Existing cal-recovery-dot--sleep class must still be rendered."""
    assert "cal-recovery-dot--sleep" in JS, "Sprint 7 sleep dot class must be preserved"


def test_sprint7_energy_dot_class_preserved():
    """Existing cal-recovery-dot--energy class must still be rendered."""
    assert "cal-recovery-dot--energy" in JS, "Sprint 7 energy dot class must be preserved"


def test_sprint7_scale_classes_preserved():
    """CSS scale-1 through scale-5 must still be defined."""
    for i in range(1, 6):
        assert f"scale-{i}" in HTML, f"Sprint 7 CSS class .scale-{i} must be preserved"


# ── /api/readiness range endpoint ────────────────────────────────────────────

def test_readiness_api_returns_200(client, alice_id):
    """GET /api/readiness must return 200 for a valid date range."""
    today = date.today()
    mm = str(today.month).zfill(2)
    from_d = f"{today.year}-{mm}-01"
    to_d = f"{today.year}-{mm}-{str(today.day).zfill(2)}"
    res = client.get(
        "/api/readiness",
        params={"user_id": alice_id, "from": from_d, "to": to_d},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"


def test_readiness_api_returns_list(client, alice_id):
    """GET /api/readiness must return a list."""
    today = date.today()
    mm = str(today.month).zfill(2)
    from_d = f"{today.year}-{mm}-01"
    to_d = f"{today.year}-{mm}-{str(today.day).zfill(2)}"
    res = client.get(
        "/api/readiness",
        params={"user_id": alice_id, "from": from_d, "to": to_d},
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list), "Response must be a list"


def test_readiness_api_null_for_missing_days(client, alice_id):
    """GET /api/readiness returns null entries for days with no data."""
    res = client.get(
        "/api/readiness",
        params={"user_id": alice_id, "from": "2000-01-01", "to": "2000-01-05"},
    )
    assert res.status_code == 200
    data = res.json()
    assert all(entry is None for entry in data), (
        "Days with no readiness data must be represented as null"
    )
