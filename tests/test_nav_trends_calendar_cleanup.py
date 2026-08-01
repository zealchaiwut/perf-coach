"""nav-cleanup ticket: /trends enabled (#1636), then removed entirely
(feature/remove-trends-tab); /calendar removed entirely (this file's
original ticket).

/trends was enabled in nav.js and shipped live for less than a day before
the product owner, after actually using it, decided not to keep it — a
genuine reversal, not a bug. It was pulled the same way /calendar was:
page file, JS file, nav.js entry, and every backend endpoint that had no
caller left once the page was gone, all deleted outright rather than
hidden behind a flag.

Static assertions over nav.js and main.py (no bundler, no DOM harness — see
test_nav__consult_and_decisions.py for the same idiom) plus a route-table
check via the assembled FastAPI app (the same source of truth
tests/test_reachability_gate__1602.py uses), so a future revert of either
half of this change fails a test instead of just looking clean in a diff.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from backend.main import app

REPO = Path(__file__).resolve().parents[1]
NAV_JS = REPO / "frontend" / "js" / "nav.js"
MAIN_PY = REPO / "backend" / "main.py"


@pytest.fixture(scope="module")
def nav() -> str:
    return NAV_JS.read_text()


@pytest.fixture(scope="module")
def main_py() -> str:
    return MAIN_PY.read_text()


def _links_block(nav_src: str) -> str:
    start = nav_src.index("var LINKS = [")
    end = nav_src.index("];", start)
    return nav_src[start:end]


# ── /trends is gone, not just hidden (feature/remove-trends-tab) ────────────

def test_trends_link_is_not_in_nav_links(nav):
    assert "/trends" not in _links_block(nav)


def test_trends_page_file_deleted():
    assert not (REPO / "frontend" / "pages" / "trends.html").exists()


def test_trends_js_file_deleted():
    assert not (REPO / "frontend" / "js" / "trends.js").exists()


def test_trends_page_route_not_registered():
    """A route that used to exist must not still resolve — GET /trends
    should 404, not fall through to some other handler."""
    paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
    assert "/trends" not in paths
    assert "/trends.html" not in paths


def test_trends_summary_api_route_not_registered():
    """/trends/summary only ever existed to back the deleted page."""
    paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
    assert "/trends/summary" not in paths


def test_main_py_has_no_trends_page_entry(main_py):
    assert '"trends": "trends.html"' not in main_py


# ── /calendar is gone, not just hidden ──────────────────────────────────────

def test_calendar_link_is_not_in_nav_links(nav):
    assert "/calendar" not in _links_block(nav)


def test_calendar_page_file_deleted():
    assert not (REPO / "frontend" / "pages" / "calendar.html").exists()


def test_calendar_js_file_deleted():
    assert not (REPO / "frontend" / "js" / "calendar.js").exists()


def test_calendar_page_route_not_registered():
    """A route that used to exist must not still resolve — GET /calendar
    should 404, not fall through to some other handler."""
    paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
    assert "/calendar" not in paths
    assert "/calendar.html" not in paths


def test_calendar_month_api_route_not_registered():
    """/api/calendar/month only ever existed to back the deleted page."""
    paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
    assert "/api/calendar/month" not in paths


def test_main_py_has_no_calendar_page_entry(main_py):
    assert '"calendar": "calendar.html"' not in main_py


# ── Nav overflow at 1440px: the links row must never silently clip ─────────

def test_nav_has_a_clip_guard_after_positioning(nav):
    """_positionGlobalNav's page-column inset is cosmetic alignment; it must
    never leave .gn-links narrower than its own content (this is what
    rendered "Trends" as "Tren" on pages without a `.page` element, or with
    a narrow centered one). Both branches of _positionGlobalNav must call
    the guard."""
    fn_start = nav.index("function _positionGlobalNav(")
    fn_end = nav.index("\n  function _shrinkNavInsetIfClipped(")
    body = nav[fn_start:fn_end]
    assert body.count("_shrinkNavInsetIfClipped(gnav)") == 2, (
        "both the .page branch and the CONTENT_MAX fallback branch must "
        "call _shrinkNavInsetIfClipped"
    )


def test_shrink_guard_has_a_floor_and_is_bounded(nav):
    """An unbounded loop tied to layout reads is a hang risk; a floor keeps
    the nav from collapsing to zero padding on a pathological page."""
    assert "_NAV_PAD_FLOOR" in nav
    fn_start = nav.index("function _shrinkNavInsetIfClipped(")
    fn_end = nav.index("\n  function _observeNavRightWidth(")
    body = nav[fn_start:fn_end]
    assert "guard" in body and "40" in body, (
        "the clip-shrink loop must be bounded, not unconditional"
    )


def test_nav_right_width_is_observed_for_late_content(nav):
    """.gn-right keeps changing size after first paint (env.js populates the
    UAT/LOCAL badge asynchronously, the avatar swaps from initial to <img>)
    with no resize event — that drift is what let the padding go stale on
    /log, /habits and /trends even after the initial computation was
    correct. A ResizeObserver on .gn-right is what catches it."""
    assert "_observeNavRightWidth(nav)" in nav
    assert "ResizeObserver" in nav


def test_build_nav_wires_the_resize_observer(nav):
    build_start = nav.index("function buildNav(")
    build_end = nav.index("\n  // ── Copy for Claude")
    body = nav[build_start:build_end]
    assert "_observeNavRightWidth(nav)" in body
