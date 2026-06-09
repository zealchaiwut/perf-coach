"""TDD tests for issue #364: Settings – Integrations and About sections.

AC items covered (static HTML analysis + live API):
  AC-A1  — Integrations section has Strava card (id=strava-card)
  AC-A2  — Integrations section has Stryd card (id=stryd-card)
  AC-A3  — Strava card has badge element (id=strava-badge)
  AC-A4  — Stryd card has badge element (id=stryd-badge)
  AC-A5  — Stryd card has inline form wrap element (id=stryd-form-wrap)
  AC-A6  — Strava card has branded icon element
  AC-A7  — Stryd card has branded icon element
  AC-A8  — Google placeholder card exists (id=google-card)
  AC-A9  — Samsung Health placeholder card exists (id=samsung-card)
  AC-A10 — Google card has "coming soon" text, no interactive connect button
  AC-A11 — Samsung Health card has "coming soon" text, no interactive connect button
  AC-A12 — Strava card actions div present (id=strava-actions)
  AC-A13 — Stryd card actions div present (id=stryd-actions)
  AC-B1  — GET /api/about returns HTTP 200 (no auth required)
  AC-B2  — /api/about response has app_version field (string, non-empty)
  AC-B3  — /api/about response has git_sha field (string)
  AC-B4  — /api/about response has environment field (string)
  AC-B5  — /api/about response has changelog_available field (bool)
  AC-B6  — /api/about git_sha falls back to "local-dev" when GIT_SHA not set
  AC-B7  — /api/about app_version non-empty, not blank
  AC-B8  — /api/about changelog_available is True (CHANGELOG.md exists in repo)
  AC-B9  — /api/about environment matches /api/env response
  AC-B10 — Settings HTML about section has id=about-version element
  AC-B11 — Settings HTML about section has id=about-sha element
  AC-B12 — Settings HTML about section has id=about-env element
  AC-B13 — Settings HTML has GitHub repo link
  AC-B14 — Settings HTML has Docs link to /docs/
  AC-B15 — Settings HTML has changelog link element (id=about-changelog-link)

Browser-only ACs skipped (need Selenium/DevTools):
  - No console errors on missing endpoints (AC-A, AC-B)
  - Strava OAuth popup flow (AC-A3)
  - Stryd inline form reveal on Connect click (AC-A5)
  - Card update without full page reload (AC-A7)
  - Environment fallback "local" when /api/env absent (AC-B fallback)
"""
import os
from pathlib import Path

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")

_SETTINGS_HTML = Path(__file__).parent.parent / "frontend" / "pages" / "settings.html"
_CHANGELOG_MD = Path(__file__).parent.parent / "CHANGELOG.md"


# ── HTML fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def settings_html_text():
    assert _SETTINGS_HTML.exists(), f"settings.html not found at {_SETTINGS_HTML}"
    return _SETTINGS_HTML.read_text(encoding="utf-8")


# ── AC-A1: Strava card exists ─────────────────────────────────────────────────

class TestStravaCardStructure:
    def test_strava_card_div_present(self, settings_html_text):
        """AC-A1: Strava card container exists."""
        assert 'id="strava-card"' in settings_html_text

    def test_strava_badge_present(self, settings_html_text):
        """AC-A3: Strava badge element exists."""
        assert 'id="strava-badge"' in settings_html_text

    def test_strava_actions_present(self, settings_html_text):
        """AC-A12: Strava actions div exists."""
        assert 'id="strava-actions"' in settings_html_text

    def test_strava_icon_present(self, settings_html_text):
        """AC-A6: Strava card has branded icon element."""
        assert 'strava-icon' in settings_html_text or 'integration-icon' in settings_html_text

    def test_strava_name_in_card(self, settings_html_text):
        """Strava service name appears in card."""
        assert "Strava" in settings_html_text


# ── AC-A2: Stryd card exists ──────────────────────────────────────────────────

class TestStrydCardStructure:
    def test_stryd_card_div_present(self, settings_html_text):
        """AC-A2: Stryd card container exists."""
        assert 'id="stryd-card"' in settings_html_text

    def test_stryd_badge_present(self, settings_html_text):
        """AC-A4: Stryd badge element exists."""
        assert 'id="stryd-badge"' in settings_html_text

    def test_stryd_actions_present(self, settings_html_text):
        """AC-A13: Stryd actions div exists."""
        assert 'id="stryd-actions"' in settings_html_text

    def test_stryd_form_wrap_present(self, settings_html_text):
        """AC-A5: Stryd inline form wrap element exists for credential entry."""
        assert 'id="stryd-form-wrap"' in settings_html_text

    def test_stryd_icon_present(self, settings_html_text):
        """AC-A7: Stryd card has branded icon element."""
        assert 'stryd-icon' in settings_html_text or 'integration-icon' in settings_html_text

    def test_stryd_name_in_card(self, settings_html_text):
        """Stryd service name appears in card."""
        assert "Stryd" in settings_html_text


# ── AC-A8/A9: Google and Samsung Health placeholder cards ──────────────────────

class TestPlaceholderCards:
    def test_google_card_present(self, settings_html_text):
        """AC-A8: Google placeholder card div exists."""
        assert 'id="google-card"' in settings_html_text

    def test_samsung_card_present(self, settings_html_text):
        """AC-A9: Samsung Health placeholder card div exists."""
        assert 'id="samsung-card"' in settings_html_text

    def test_google_coming_soon_text(self, settings_html_text):
        """AC-A10: Google card has 'coming soon' indicator text."""
        # Find Google card block and check for coming-soon text nearby
        lower = settings_html_text.lower()
        google_pos = lower.find('id="google-card"')
        assert google_pos != -1, "google-card not found"
        snippet = lower[google_pos:google_pos + 800]
        assert "coming soon" in snippet, "Google card missing 'coming soon' text"

    def test_samsung_coming_soon_text(self, settings_html_text):
        """AC-A11: Samsung Health card has 'coming soon' indicator text."""
        lower = settings_html_text.lower()
        samsung_pos = lower.find('id="samsung-card"')
        assert samsung_pos != -1, "samsung-card not found"
        snippet = lower[samsung_pos:samsung_pos + 800]
        assert "coming soon" in snippet, "Samsung Health card missing 'coming soon' text"

    def test_google_card_no_connect_button(self, settings_html_text):
        """AC-A10: Google card has no interactive connect/disconnect button."""
        # Find Google card and verify no connect button id inside it
        google_pos = settings_html_text.find('id="google-card"')
        assert google_pos != -1
        # Find the closing tag of this card - look for next integration-card or section end
        next_card = settings_html_text.find('integration-card', google_pos + 20)
        if next_card == -1:
            next_card = settings_html_text.find('id="section-', google_pos + 20)
        snippet = settings_html_text[google_pos:next_card if next_card != -1 else google_pos + 1000]
        assert 'id="google-connect' not in snippet
        assert 'id="google-disconnect' not in snippet

    def test_samsung_card_no_connect_button(self, settings_html_text):
        """AC-A11: Samsung Health card has no interactive connect/disconnect button."""
        samsung_pos = settings_html_text.find('id="samsung-card"')
        assert samsung_pos != -1
        next_card = settings_html_text.find('integration-card', samsung_pos + 20)
        if next_card == -1:
            next_card = settings_html_text.find('id="section-', samsung_pos + 20)
        snippet = settings_html_text[samsung_pos:next_card if next_card != -1 else samsung_pos + 1000]
        assert 'id="samsung-connect' not in snippet
        assert 'id="samsung-disconnect' not in snippet

    def test_google_card_has_google_name(self, settings_html_text):
        """Google card references Google."""
        google_pos = settings_html_text.find('id="google-card"')
        assert google_pos != -1
        snippet = settings_html_text[google_pos:google_pos + 800]
        assert "Google" in snippet

    def test_samsung_card_has_samsung_name(self, settings_html_text):
        """Samsung card references Samsung Health."""
        samsung_pos = settings_html_text.find('id="samsung-card"')
        assert samsung_pos != -1
        snippet = settings_html_text[samsung_pos:samsung_pos + 800]
        assert "Samsung" in snippet


# ── AC-B1–B9: /api/about endpoint ────────────────────────────────────────────

class TestAboutEndpoint:
    def test_about_returns_200(self):
        """AC-B1: GET /api/about returns HTTP 200."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            r = c.get("/api/about")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_about_has_app_version(self):
        """AC-B2: Response has app_version field as non-empty string."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            data = c.get("/api/about").json()
        assert "app_version" in data
        assert isinstance(data["app_version"], str)
        assert data["app_version"].strip() != ""

    def test_about_has_git_sha(self):
        """AC-B3: Response has git_sha field as string."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            data = c.get("/api/about").json()
        assert "git_sha" in data
        assert isinstance(data["git_sha"], str)

    def test_about_has_environment(self):
        """AC-B4: Response has environment field as string."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            data = c.get("/api/about").json()
        assert "environment" in data
        assert isinstance(data["environment"], str)

    def test_about_has_changelog_available(self):
        """AC-B5: Response has changelog_available field as bool."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            data = c.get("/api/about").json()
        assert "changelog_available" in data
        assert isinstance(data["changelog_available"], bool)

    def test_about_git_sha_non_empty(self):
        """AC-B6: git_sha is non-empty (either real SHA or 'local-dev' fallback)."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            data = c.get("/api/about").json()
        assert data["git_sha"].strip() != ""

    def test_about_app_version_non_empty(self):
        """AC-B7: app_version is non-empty."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            data = c.get("/api/about").json()
        assert data["app_version"].strip() != ""

    def test_about_changelog_available_true_when_file_exists(self):
        """AC-B8: changelog_available matches whether CHANGELOG.md exists on disk."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            data = c.get("/api/about").json()
        expected = _CHANGELOG_MD.exists()
        assert data["changelog_available"] == expected

    def test_about_environment_matches_env_endpoint(self):
        """AC-B9: environment matches GET /api/env."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            about_data = c.get("/api/about").json()
            env_data = c.get("/api/env").json()
        assert about_data["environment"] == env_data["environment"]


# ── AC-B10–B15: About section HTML structure ──────────────────────────────────

class TestAboutSectionHtml:
    def test_about_version_element(self, settings_html_text):
        """AC-B10: id=about-version element present."""
        assert 'id="about-version"' in settings_html_text

    def test_about_sha_element(self, settings_html_text):
        """AC-B11: id=about-sha element present."""
        assert 'id="about-sha"' in settings_html_text

    def test_about_env_element(self, settings_html_text):
        """AC-B12: id=about-env element present."""
        assert 'id="about-env"' in settings_html_text

    def test_about_github_link(self, settings_html_text):
        """AC-B13: GitHub repository link present in settings page."""
        assert "github.com/zealchaiwut/perf-coach" in settings_html_text

    def test_about_docs_link(self, settings_html_text):
        """AC-B14: Docs link pointing to /docs/ present."""
        assert 'href="/docs/"' in settings_html_text or "href='/docs/'" in settings_html_text

    def test_about_changelog_link_element(self, settings_html_text):
        """AC-B15: Changelog link element exists (may be hidden by JS)."""
        assert 'id="about-changelog-link"' in settings_html_text

    def test_about_section_no_placeholder_text(self, settings_html_text):
        """About section no longer has the 'Coming up in this sprint' placeholder."""
        # Find section-about and check its content
        about_pos = settings_html_text.find('id="section-about"')
        assert about_pos != -1
        # Look at the content within this section (next section starts with id="section-)
        next_section = settings_html_text.find('id="section-', about_pos + 20)
        snippet = settings_html_text[about_pos:next_section if next_section != -1 else about_pos + 2000]
        assert "Coming up in this sprint" not in snippet
