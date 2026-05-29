"""Tests for issue #134: Fix all nav links and action buttons to valid routes"""
import os
import re
import pathlib
import pytest
import httpx
from html.parser import HTMLParser

UAT_BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")

STATIC_ROOT = pathlib.Path(__file__).parent.parent

# Pages listed in acceptance criteria
NAV_PAGES = [
    "index.html",
    "home.html",
    "weight.html",
    "habits.html",
    "users.html",
    "calendar.html",
    "log.html",
    "trends.html",
]


class _NavHrefCollector(HTMLParser):
    """Collect all href values inside <nav> elements."""

    def __init__(self):
        super().__init__()
        self._in_nav = 0
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag == "nav":
            self._in_nav += 1
        if self._in_nav and tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.hrefs.append(value)

    def handle_endtag(self, tag: str):
        if tag == "nav" and self._in_nav:
            self._in_nav -= 1


def _collect_nav_hrefs(filename: str) -> list[str]:
    content = (STATIC_ROOT / filename).read_text()
    parser = _NavHrefCollector()
    parser.feed(content)
    return parser.hrefs


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=UAT_BASE_URL, timeout=10.0) as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# AC: every nav href in the 8 pages resolves to HTTP 200
# ─────────────────────────────────────────────────────────────────────────────

def _nav_href_params():
    params = []
    for page in NAV_PAGES:
        for href in _collect_nav_hrefs(page):
            if href.startswith("/") or href.startswith("http"):
                params.append(pytest.param(page, href, id=f"{page}::{href}"))
    return params


@pytest.mark.parametrize("page,href", _nav_href_params())
def test_nav_href_returns_200(client, page, href):
    """Every nav href in the 8 AC pages resolves to HTTP 200."""
    r = client.get(href)
    assert r.status_code == 200, (
        f"{page}: nav href '{href}' returned {r.status_code}, expected 200"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC: Training Log link targets /log in every page that has it
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("page", NAV_PAGES)
def test_no_training_html_in_nav(page):
    """No nav link in any of the 8 pages points to training.html."""
    hrefs = _collect_nav_hrefs(page)
    bad = [h for h in hrefs if "training.html" in h]
    assert not bad, f"{page}: nav still contains training.html hrefs: {bad}"


@pytest.mark.parametrize("page", NAV_PAGES)
def test_no_slash_training_html_anywhere(page):
    """The literal string /training.html does not appear in any of the 8 pages."""
    content = (STATIC_ROOT / page).read_text()
    assert "/training.html" not in content, (
        f"{page}: still contains the string '/training.html'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC: /log and /trends routes return 200
# ─────────────────────────────────────────────────────────────────────────────

def test_log_route_200(client):
    """/log returns HTTP 200."""
    r = client.get("/log")
    assert r.status_code == 200, f"/log returned {r.status_code}"


def test_trends_route_200(client):
    """/trends returns HTTP 200."""
    r = client.get("/trends")
    assert r.status_code == 200, f"/trends returned {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# AC: log-workout-btn has disabled attribute and title="Coming soon"
# ─────────────────────────────────────────────────────────────────────────────

def test_log_workout_btn_is_disabled():
    """log-workout-btn has the disabled attribute."""
    content = (STATIC_ROOT / "log.html").read_text()
    match = re.search(r'id=["\']log-workout-btn["\'][^>]*>', content)
    assert match, "log-workout-btn element not found in log.html"
    tag = match.group(0)
    assert "disabled" in tag, f"log-workout-btn is missing 'disabled': {tag}"


def test_log_workout_btn_has_coming_soon_title():
    """log-workout-btn has title='Coming soon'."""
    content = (STATIC_ROOT / "log.html").read_text()
    match = re.search(r'id=["\']log-workout-btn["\'][^>]*>', content)
    assert match, "log-workout-btn element not found in log.html"
    tag = match.group(0)
    assert "Coming soon" in tag, (
        f"log-workout-btn is missing title='Coming soon': {tag}"
    )
