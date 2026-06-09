"""Tests for issue #364: Settings: Integrations and About sections (runs against UAT)

Risk: MEDIUM — frontend feature with multiple API probes, graceful degradation.

AC coverage:
  A1  — integrations section + strava/stryd cards exist in settings.html
  A2  — GET /api/strava/status and GET /api/stryd/status respond 200 for auth'd user
  A3  — (visual card layout — skip: browser-only)
  A4  — GET /api/strava/connect returns authorize_url JSON (or 500 if unconfigured)
  A5  — POST /api/stryd/connect endpoint exists (returns 400/422 for bad creds)
  A6  — DELETE /api/strava/disconnect and DELETE /api/stryd/disconnect return 200
  A7  — (card update without reload — skip: browser-only)
  A8  — Google and Samsung Health placeholder cards exist in settings.html
  A9  — (console errors — skip: browser-only)
  B1  — GET /api/about returns app_version field
  B2  — GET /api/about returns git_sha field (local-dev fallback in UAT)
  B3  — GET /api/env returns environment field
  B4  — GitHub link exists in settings.html pointing to zealchaiwut/perf-coach
  B5  — Docs link exists in settings.html pointing to /docs/
  B6  — GET /api/about returns changelog_available bool; changelog link has correct href
  B7  — (about console errors — skip: browser-only)

Prerequisites: tester364 user must exist in UAT DB with password "Test364pass!".
"""
import os
from pathlib import Path

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")
_CREDENTIALS = {"username": "tester364", "password": "Test364pass!"}

_SETTINGS_HTML = Path(__file__).parent.parent / "frontend" / "pages" / "settings.html"


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _login():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/api/auth/login", json=_CREDENTIALS)
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
        session = c.cookies.get("session", "")
        csrf = ""
        for sc in r.headers.get_list("set-cookie"):
            if sc.startswith("csrf-token="):
                csrf = sc.split("=", 1)[1].split(";")[0]
                break
        assert session and csrf, f"Missing cookies: session={bool(session)}, csrf={bool(csrf)}"
        return session, csrf


class _AuthedClient:
    def __init__(self, base_url, session, csrf):
        self._cookie_header = f"session={session}; csrf-token={csrf}"
        self._csrf = csrf
        self._client = httpx.Client(base_url=base_url, timeout=10.0)

    def _h(self, extra=None):
        h = {"Cookie": self._cookie_header}
        if extra:
            h.update(extra)
        return h

    def get(self, url, **kw):
        kw.setdefault("headers", {}).update(self._h())
        return self._client.get(url, **kw)

    def post(self, url, **kw):
        kw.setdefault("headers", {}).update(
            self._h({"X-CSRF-Token": self._csrf, "Content-Type": "application/json"})
        )
        return self._client.post(url, **kw)

    def delete(self, url, **kw):
        # Use a fresh client to avoid stale-connection resets in the shared pool.
        kw.setdefault("headers", {}).update(
            self._h({"X-CSRF-Token": self._csrf})
        )
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
            return c.delete(url, **kw)

    def close(self):
        self._client.close()


@pytest.fixture(scope="module")
def authed():
    session, csrf = _login()
    c = _AuthedClient(BASE_URL, session, csrf)
    yield c
    c.close()


# ── AC A1: integrations section and strava/stryd cards in HTML ────────────────

def test_settings_integrations_and_about_sections__integrations_section_in_html():
    # AC A1: Integrations section exists with strava and stryd cards
    html = _SETTINGS_HTML.read_text()
    assert 'id="section-integrations"' in html, "Missing section-integrations div"
    assert 'id="strava-card"' in html, "Missing strava-card"
    assert 'id="stryd-card"' in html, "Missing stryd-card"


# ── AC A2: strava/stryd status endpoints respond 200 for auth'd user ─────────

def test_settings_integrations_and_about_sections__strava_status_200(authed):
    # AC A2: GET /api/strava/status returns 200 with connected field
    r = authed.get("/api/strava/status")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "connected" in data, f"Missing 'connected' key: {data}"
    assert isinstance(data["connected"], bool)


def test_settings_integrations_and_about_sections__stryd_status_200(authed):
    # AC A2: GET /api/stryd/status returns 200 with connected field
    r = authed.get("/api/stryd/status")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "connected" in data, f"Missing 'connected' key: {data}"
    assert isinstance(data["connected"], bool)


# ── AC A4: strava connect endpoint returns authorize_url JSON ─────────────────

def test_settings_integrations_and_about_sections__strava_connect_returns_json(authed):
    # AC A4: GET /api/strava/connect returns JSON (200 with authorize_url, or 500 if unconfigured)
    r = authed.get("/api/strava/connect")
    assert r.status_code in (200, 500), f"Unexpected status {r.status_code}: {r.text}"
    if r.status_code == 200:
        assert "authorize_url" in r.json(), f"Missing authorize_url: {r.json()}"


# ── AC A5: stryd connect endpoint exists ──────────────────────────────────────

def test_settings_integrations_and_about_sections__stryd_connect_endpoint_exists(authed):
    # AC A5: POST /api/stryd/connect exists; bad creds return 400 or 422, not 404
    r = authed.post("/api/stryd/connect", json={"email": "bad@test.com", "password": "bad"})
    assert r.status_code != 404, f"Endpoint not found (404): {r.text}"
    assert r.status_code in (400, 401, 422, 500), f"Unexpected status {r.status_code}: {r.text}"


# ── AC A6: disconnect endpoints return 200 ────────────────────────────────────

def test_settings_integrations_and_about_sections__strava_disconnect_200(authed):
    # AC A6: DELETE /api/strava/disconnect returns 200 with disconnected=True
    r = authed.delete("/api/strava/disconnect")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("disconnected") is True, f"Expected disconnected=True: {r.json()}"


def test_settings_integrations_and_about_sections__stryd_disconnect_200(authed):
    # AC A6: DELETE /api/stryd/disconnect returns 200 with disconnected=True
    r = authed.delete("/api/stryd/disconnect")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("disconnected") is True, f"Expected disconnected=True: {r.json()}"


# ── AC A8: Google and Samsung placeholder cards in HTML ───────────────────────

def test_settings_integrations_and_about_sections__google_samsung_placeholder_cards():
    # AC A8: Google and Samsung Health placeholder cards exist and are labelled coming soon
    html = _SETTINGS_HTML.read_text()
    assert 'id="google-card"' in html, "Missing google-card"
    assert 'id="samsung-card"' in html, "Missing samsung-card"
    assert "Sign in with Google" in html and "coming soon" in html, "Missing Google coming soon text"
    assert "Sleep import" in html, "Missing Samsung coming soon text"


# ── AC B1-B2: /api/about returns version and sha ─────────────────────────────

def test_settings_integrations_and_about_sections__about_returns_version_and_sha():
    # AC B1+B2: GET /api/about returns app_version and git_sha
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.get("/api/about")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "app_version" in data, f"Missing app_version: {data}"
    assert "git_sha" in data, f"Missing git_sha: {data}"
    assert data["app_version"], "app_version is empty"
    assert data["git_sha"], "git_sha is empty"


# ── AC B3: /api/env returns environment ──────────────────────────────────────

def test_settings_integrations_and_about_sections__env_endpoint_returns_environment():
    # AC B3: GET /api/env returns environment field
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.get("/api/env")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "environment" in data, f"Missing environment key: {data}"
    assert data["environment"] in ("uat", "prd", "local"), f"Unexpected env: {data['environment']}"


# ── AC B4-B5: GitHub and Docs links in settings.html about section ────────────

def test_settings_integrations_and_about_sections__about_github_and_docs_links():
    # AC B4+B5: GitHub link to zealchaiwut/perf-coach and Docs link to /docs/ present
    html = _SETTINGS_HTML.read_text()
    assert "https://github.com/zealchaiwut/perf-coach" in html, "Missing GitHub link"
    assert 'href="/docs/"' in html, "Missing Docs link"


# ── AC B6: changelog_available + changelog link in HTML ──────────────────────

def test_settings_integrations_and_about_sections__about_changelog_available_and_link():
    # AC B6: /api/about returns changelog_available bool; HTML has changelog link element
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.get("/api/about")
    assert r.status_code == 200
    data = r.json()
    assert "changelog_available" in data, f"Missing changelog_available: {data}"
    assert isinstance(data["changelog_available"], bool)

    html = _SETTINGS_HTML.read_text()
    assert 'id="about-changelog-link"' in html, "Missing about-changelog-link element"
    assert 'href="/CHANGELOG.md"' in html, "Changelog link missing /CHANGELOG.md href"


# ── Manual / browser-only skips ───────────────────────────────────────────────

def test_settings_integrations_and_about_sections__card_update_without_reload():
    # AC A7: card status updates without full page reload
    pytest.skip("manual — requires browser interaction to verify DOM update")


def test_settings_integrations_and_about_sections__no_console_errors_on_missing_endpoints():
    # AC A9: no JS console errors when endpoints absent
    pytest.skip("manual — requires browser devtools")


def test_settings_integrations_and_about_sections__visual_consistency():
    # General: sections visually consistent with existing settings style
    pytest.skip("manual — visual check required")


def test_settings_integrations_and_about_sections__no_regressions_other_sections():
    # General: no regressions in other settings sections
    pytest.skip("manual — full settings page smoke test required")
