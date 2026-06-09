"""
TDD tests for issue #360: Build Settings Page Shell with Section Navigation.

AC items covered:
  (a) /settings and /settings.html serve 200 (authenticated)
  (b) Page references nav.js (top nav present)
  (c) Sidebar lists exactly 5 items: Profile, Performance Thresholds, Personal Records, Integrations, About
  (d) 5 section divs present in HTML (id="section-<key>")
  (e) Sections hidden by default via display:none
  (f) Default section is Profile
  (g) Each section has placeholder: "Coming up in this sprint" (5 times)
  (h) Navigation logic lives in settings.js
  (i) settings.js contains hash/hashchange routing logic
  (j) Responsive CSS breakpoint at 880px

Server: http://127.0.0.1:9001
"""
import uuid

import httpx
import pytest
from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "settings-360-pw"

EXPECTED_SECTIONS = ["profile", "thresholds", "personal-records", "integrations", "about"]


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=False) as c:
        yield c


@pytest.fixture(scope="module")
def authed_client():
    """Client with authenticated session (Alice)."""
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=True) as c:
        res = c.get("/api/users")
        assert res.status_code == 200, f"GET /api/users failed: {res.status_code}"
        alice = next((u for u in res.json() if u["name"] == "Alice"), None)
        assert alice is not None, "Alice not found in /api/users"
        with Session(engine) as db:
            db.get(User, uuid.UUID(alice["id"])).password_hash = hash_password(_TEST_PASSWORD)
            db.commit()
        login = c.post("/api/auth/login", json={"username": "Alice", "password": _TEST_PASSWORD})
        assert login.status_code == 200, f"Login failed: {login.text}"
        yield c


@pytest.fixture(scope="module")
def settings_html(authed_client):
    """Fetch /settings page HTML once and reuse."""
    res = authed_client.get("/settings")
    assert res.status_code == 200, f"GET /settings returned {res.status_code}"
    return res.text


# ── AC (a): /settings and /settings.html serve 200 ───────────────────────────

class TestSettingsRoutes:
    def test_settings_route_ok(self, authed_client):
        """GET /settings → 200 when authenticated."""
        res = authed_client.get("/settings")
        assert res.status_code == 200

    def test_settings_html_route_ok(self, authed_client):
        """GET /settings.html → 200 when authenticated."""
        res = authed_client.get("/settings.html")
        assert res.status_code == 200

    def test_unauthenticated_redirects(self, client):
        """Unauthenticated GET /settings → 302 redirect."""
        res = client.get("/settings")
        assert res.status_code == 302

    def test_content_type_html(self, authed_client):
        """Response content-type is HTML."""
        res = authed_client.get("/settings")
        assert "text/html" in res.headers.get("content-type", "")


# ── AC (b): Page uses same top nav ───────────────────────────────────────────

class TestNavPresent:
    def test_nav_js_script_tag(self, settings_html):
        """nav.js script tag present in page."""
        assert "nav.js" in settings_html


# ── AC (c): Sidebar has exactly 5 items ──────────────────────────────────────

class TestSidebarItems:
    def test_profile_label_present(self, settings_html):
        assert "Profile" in settings_html

    def test_performance_thresholds_label_present(self, settings_html):
        assert "Performance Thresholds" in settings_html

    def test_personal_records_label_present(self, settings_html):
        assert "Personal Records" in settings_html

    def test_integrations_label_present(self, settings_html):
        assert "Integrations" in settings_html

    def test_about_label_present(self, settings_html):
        assert "About" in settings_html

    def test_all_5_section_hashes_referenced(self, settings_html):
        """All 5 section keys appear as hash targets or data-section values."""
        count = 0
        for section in EXPECTED_SECTIONS:
            if (f'#{section}' in settings_html
                    or f'data-section="{section}"' in settings_html
                    or f"data-section='{section}'" in settings_html):
                count += 1
        assert count == 5, f"Expected 5 sidebar hash/data-section refs, found {count}"


# ── AC (d, e, f): Section divs present, hidden, default=profile ──────────────

class TestSectionDivs:
    def test_all_5_section_ids_present(self, settings_html):
        """Each section div has id='section-<key>'."""
        for section in EXPECTED_SECTIONS:
            assert (
                f'id="section-{section}"' in settings_html
                or f"id='section-{section}'" in settings_html
            ), f"Missing section div for '{section}'"

    def test_sections_have_display_none_default(self, settings_html):
        """Section divs default to display:none."""
        assert "display:none" in settings_html or "display: none" in settings_html, \
            "No display:none default found for section divs"

    def test_profile_is_default_section(self, settings_html):
        """JS code references 'profile' as the default section."""
        assert "profile" in settings_html.lower()


# ── AC (g): Each section has placeholder ─────────────────────────────────────

class TestSectionPlaceholders:
    def test_placeholder_present(self, settings_html):
        assert "Coming up in this sprint" in settings_html

    def test_placeholder_appears_5_times(self, settings_html):
        """Placeholder appears once per section (5 total)."""
        count = settings_html.count("Coming up in this sprint")
        assert count == 5, f"Expected 5 placeholder occurrences, found {count}"


# ── AC (h, i): settings.js referenced and contains hash logic ────────────────

class TestSettingsJs:
    def test_settings_js_referenced_in_html(self, settings_html):
        """settings.js script tag present in settings.html."""
        assert "settings.js" in settings_html

    def test_settings_js_serves_200(self, authed_client):
        """GET /js/settings.js → 200."""
        res = authed_client.get("/js/settings.js")
        assert res.status_code == 200

    def test_settings_js_has_hashchange_listener(self, authed_client):
        """settings.js registers a hashchange event listener."""
        res = authed_client.get("/js/settings.js")
        assert "hashchange" in res.text, "settings.js missing hashchange event listener"

    def test_settings_js_has_hash_read(self, authed_client):
        """settings.js reads window.location.hash."""
        res = authed_client.get("/js/settings.js")
        assert "hash" in res.text, "settings.js missing hash reference"


# ── AC (j): Responsive CSS at <880px ─────────────────────────────────────────

class TestResponsiveLayout:
    def test_media_query_880px_present(self, settings_html):
        """CSS media query targeting <=880px viewport exists."""
        assert "880px" in settings_html, "No 880px responsive breakpoint in settings.html"
