"""Tests for issue #323: Remove orphaned log.html and log.js dead code"""
import os
import pathlib
import re

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")

REPO_ROOT = pathlib.Path(__file__).parent.parent
FRONTEND_PAGES = REPO_ROOT / "frontend" / "pages"
FRONTEND_JS = REPO_ROOT / "frontend" / "js"
BACKEND = REPO_ROOT / "backend"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=False) as c:
        yield c


# ── AC: log.html and log.js are deleted ───────────────────────────────────────

def test_log_html_deleted():
    assert not (FRONTEND_PAGES / "log.html").exists(), "log.html must be deleted"


def test_log_js_deleted():
    assert not (FRONTEND_JS / "log.js").exists(), "log.js must be deleted"


def test_training_log_html_still_exists():
    assert (FRONTEND_PAGES / "training-log.html").exists(), "training-log.html must not be removed"


# ── AC: Zero remaining references to log.html / log.js in routes and scripts ──

def _source_files():
    for ext in ("*.html", "*.js", "*.py"):
        yield from FRONTEND_PAGES.glob(ext)
        yield from FRONTEND_JS.glob(ext)
    yield from BACKEND.glob("*.py")


def test_no_log_html_refs_in_source():
    # Match standalone log.html but NOT training-log.html
    hits = []
    log_ref = re.compile(r'(?<!training-)(?<!\w)log\.html')
    for path in _source_files():
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if log_ref.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert not hits, "Stale log.html refs found:\n" + "\n".join(hits)


def test_no_log_js_refs_in_source():
    # Match standalone log.js but NOT training-log.js
    hits = []
    log_ref = re.compile(r'(?<!training-)(?<!\w)log\.js')
    for path in _source_files():
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if log_ref.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert not hits, "Stale log.js refs found:\n" + "\n".join(hits)


# ── AC: nav.js match array no longer includes /log.html ───────────────────────

def test_nav_js_match_array_no_log_html():
    nav_js = (FRONTEND_JS / "nav.js").read_text()
    assert "/log.html" not in nav_js, "nav.js match array must not contain /log.html"


# ── AC: /log route still exists (serves training-log.html) ────────────────────

def test_log_route_exists_not_404(client):
    """GET /log returns 302 (auth redirect) not 404 — route is still registered."""
    res = client.get("/log")
    assert res.status_code != 404, f"/log must not return 404, got {res.status_code}"
    assert res.status_code in (200, 302), f"Unexpected status: {res.status_code}"


def test_log_route_redirects_to_login_not_missing(client):
    """/log redirects to /login (auth guard), not to a 404 or error page."""
    res = client.get("/log")
    if res.status_code == 302:
        assert res.headers.get("location") == "/login", (
            f"/log redirect should go to /login, got {res.headers.get('location')}"
        )


def test_log_dot_html_route_still_valid(client):
    """/log.html legacy route still exists (maps to training-log.html)."""
    res = client.get("/log.html")
    assert res.status_code != 404, f"/log.html must not return 404, got {res.status_code}"
