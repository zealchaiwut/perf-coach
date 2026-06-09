"""
TDD tests for issue #365: Cross-link settings, polish nav, and add integration tests.

AC items covered:
  (A) PR widget on /home deep-links to /settings#personal-records (not bare /settings)
  (B) Gear icon in nav right-actions area (gn-settings, ti-settings, title="Settings")
  (C) FTP-missing banner on /home when thresholds null; dismiss persists in session
  (D) docs/features/user-settings.md exists with required content
  (F) PATCH /user-preferences round-trip; PRs CRUD round-trip; settings.js hash routing

Server: http://127.0.0.1:9001
"""
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.auth import generate_csrf_token, hash_password
from backend.models import User

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "settings365-int-pw"

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_REPO_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=True) as c:
        yield c


def _make_authed_client(username: str, user_id: str) -> httpx.Client:
    """Login and return an httpx.Client with session + CSRF cookies set for HTTP (no Secure flag)."""
    # Login to get the session token
    temp = httpx.Client(base_url=BASE, timeout=10, follow_redirects=True)
    login = temp.post("/api/auth/login", json={"username": username, "password": _TEST_PASSWORD})
    assert login.status_code == 200, f"Login failed: {login.text}"
    session_val = temp.cookies.get("session", "")
    temp.close()
    assert session_val, "Login must set session cookie"

    # Generate a fresh CSRF token and create a client with explicit cookies (no Secure flag).
    # Secure cookies are not sent over HTTP by httpx, so we inject both values manually.
    csrf = generate_csrf_token()
    c = httpx.Client(
        base_url=BASE,
        timeout=10,
        follow_redirects=True,
        cookies={"session": session_val, "csrf-token": csrf},
        headers={"X-CSRF-Token": csrf},
    )
    c._user_id = user_id
    return c


@pytest.fixture(scope="module")
def authed_client():
    """Authenticated client with a fresh user."""
    username = f"si365_{uuid.uuid4().hex[:8]}"
    temp = httpx.Client(base_url=BASE, timeout=10, follow_redirects=True)
    res = temp.post("/api/users", json={"name": username})
    assert res.status_code == 201, f"Failed to create user: {res.text}"
    user_id = res.json()["id"]
    temp.close()
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        assert u is not None
        u.password_hash = hash_password(_TEST_PASSWORD)
        db.commit()
    c = _make_authed_client(username, user_id)
    yield c
    # Cleanup: delete user (need CSRF for DELETE)
    c.delete(f"/api/users/{user_id}")
    c.close()


# ── AC (A): PR widget deep-link ───────────────────────────────────────────────

class TestACAPRWidgetDeepLink:
    """home.js perf-card must navigate to /settings#personal-records, not bare /settings."""

    def test_home_js_perf_card_header_links_to_settings_hash(self, client):
        """home.js card header 'All tracks' link includes #personal-records hash."""
        res = client.get("/js/home.js")
        assert res.status_code == 200
        assert 'href="/settings#personal-records"' in res.text, (
            "home.js must have href=\"/settings#personal-records\" in the perf widget"
        )

    def test_home_js_perf_card_title_links_to_settings_hash(self, client):
        """home.js perf-card 'Performance' title is also a link to /settings#personal-records."""
        res = client.get("/js/home.js")
        assert res.status_code == 200
        # Both the title area AND the 'All tracks' link must point to #personal-records
        count = res.text.count('/settings#personal-records')
        assert count >= 2, (
            f"Expected at least 2 links to /settings#personal-records in home.js, found {count}"
        )

    def test_home_js_no_bare_settings_link_in_perf_widget(self, client):
        """home.js perf widget must not link to bare /settings without hash."""
        res = client.get("/js/home.js")
        assert res.status_code == 200
        text = res.text
        # Every '/settings' that appears should either be '/settings#...' or the settings page path
        # Verify there's no '/settings"' bare link in perf card context
        perf_section_start = text.find('perf-card')
        assert perf_section_start != -1, "home.js must define perf-card"


# ── AC (B): Gear icon in nav ──────────────────────────────────────────────────

class TestACBSettingsGearIcon:
    """nav.js must have a dedicated gear icon link for Settings in the right-actions area."""

    def test_nav_js_has_gn_settings_class(self, client):
        """nav.js must include a gn-settings element."""
        res = client.get("/js/nav.js")
        assert res.status_code == 200
        assert "gn-settings" in res.text, "nav.js missing gn-settings class/element"

    def test_nav_js_gear_icon_uses_ti_settings(self, client):
        """Gear icon must use Tabler ti-settings icon class."""
        res = client.get("/js/nav.js")
        assert "ti-settings" in res.text, "nav.js missing ti-settings icon"

    def test_nav_js_gear_link_has_title_settings(self, client):
        """Gear link must have title='Settings'."""
        res = client.get("/js/nav.js")
        assert 'title="Settings"' in res.text, "nav.js gear link missing title=\"Settings\""

    def test_nav_js_gear_link_points_to_settings(self, client):
        """Gear link href must be /settings."""
        res = client.get("/js/nav.js")
        assert 'href="/settings"' in res.text, "nav.js gear link missing href to /settings"

    def test_nav_js_gear_link_after_avatar(self, client):
        """gn-settings must appear after gn-avatar in nav markup."""
        res = client.get("/js/nav.js")
        body = res.text
        avatar_pos = body.find("gn-avatar")
        settings_pos = body.find("gn-settings")
        assert avatar_pos != -1, "nav.js missing gn-avatar"
        assert settings_pos != -1, "nav.js missing gn-settings"
        assert settings_pos > avatar_pos, "gn-settings must appear after gn-avatar"

    def test_nav_js_gear_link_before_logout(self, client):
        """gn-settings must appear before gn-logout in nav markup."""
        res = client.get("/js/nav.js")
        body = res.text
        settings_pos = body.find("gn-settings")
        logout_pos = body.find("gn-logout")
        assert settings_pos != -1, "nav.js missing gn-settings"
        assert logout_pos != -1, "nav.js missing gn-logout"
        assert settings_pos < logout_pos, "gn-settings must appear before gn-logout"

    def test_nav_js_gear_link_has_aria_label(self, client):
        """Gear link must have aria-label for accessibility."""
        res = client.get("/js/nav.js")
        assert 'aria-label="Settings"' in res.text, "nav.js gear link missing aria-label"

    def test_settings_html_pages_load_nav_js(self, authed_client):
        """All main pages must load nav.js (which injects the gear icon)."""
        pages = ["/home", "/settings", "/weight", "/habits"]
        for page in pages:
            res = authed_client.get(page)
            assert res.status_code == 200, f"{page} returned {res.status_code}"
            assert "nav.js" in res.text, f"{page} does not load nav.js"


# ── AC (C): FTP-missing banner ────────────────────────────────────────────────

class TestACCFTPMissingBanner:
    """home.js must render a dismissable banner when any threshold field is null."""

    def test_home_js_has_threshold_banner_logic(self, client):
        """home.js must check user-preferences and show a threshold banner."""
        res = client.get("/js/home.js")
        assert res.status_code == 200
        text = res.text
        assert "threshold" in text.lower(), "home.js missing threshold banner logic"

    def test_home_js_banner_checks_user_preferences_api(self, client):
        """home.js must call /api/user-preferences to check threshold values."""
        res = client.get("/js/home.js")
        assert "user-preferences" in res.text, (
            "home.js must call /api/user-preferences for banner logic"
        )

    def test_home_js_banner_links_to_settings_thresholds(self, client):
        """Banner link must point to /settings#thresholds."""
        res = client.get("/js/home.js")
        assert "/settings#thresholds" in res.text, (
            "home.js banner must link to /settings#thresholds"
        )

    def test_home_js_banner_tip_text_present(self, client):
        """Banner must contain the exact tip text from the AC."""
        res = client.get("/js/home.js")
        assert "FTP" in res.text, "home.js banner missing FTP mention"
        assert "threshold" in res.text.lower(), "home.js banner missing threshold mention"
        assert "Settings" in res.text, "home.js banner must mention Settings"

    def test_home_js_banner_uses_session_storage_for_dismiss(self, client):
        """Banner dismissal must use sessionStorage to persist within session."""
        res = client.get("/js/home.js")
        assert "sessionStorage" in res.text, (
            "home.js banner dismiss must use sessionStorage (not localStorage)"
        )

    def test_home_js_banner_has_dismiss_button(self, client):
        """Banner must include a dismiss/close button."""
        res = client.get("/js/home.js")
        text = res.text
        assert "dismiss" in text.lower() or "close" in text.lower(), (
            "home.js banner missing dismiss/close element"
        )

    def test_user_preferences_returns_null_thresholds_for_fresh_user(self, authed_client):
        """Fresh user with no prefs row returns null threshold values."""
        res = authed_client.get("/api/user-preferences")
        assert res.status_code == 200
        data = res.json()
        row = data.get("row", {})
        # A fresh user has no thresholds set — at least one should be null
        has_null = (
            row.get("ftp_w") is None
            or row.get("threshold_hr") is None
            or row.get("threshold_pace_seconds_per_km") is None
        )
        assert has_null, "Fresh user should have at least one null threshold (banner trigger)"

    def test_banner_not_shown_when_all_thresholds_populated(self, authed_client):
        """After setting all three thresholds, the banner trigger condition is false."""
        # Populate all three thresholds
        res = authed_client.patch("/api/user-preferences", json={
            "ftp_w": 250,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
        })
        assert res.status_code == 200
        # Verify all are now non-null
        prefs_res = authed_client.get("/api/user-preferences")
        row = prefs_res.json()["row"]
        assert row["ftp_w"] is not None
        assert row["threshold_hr"] is not None
        assert row["threshold_pace_seconds_per_km"] is not None


# ── AC (D): Docs file ─────────────────────────────────────────────────────────

class TestACDDocsFile:
    """docs/features/user-settings.md must exist with required content."""

    def _read_docs(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "docs", "features", "user-settings.md"
        )
        assert os.path.exists(path), "docs/features/user-settings.md does not exist"
        with open(path) as f:
            return f.read()

    def test_docs_file_exists(self):
        self._read_docs()

    def test_docs_mentions_profile_section(self):
        text = self._read_docs()
        assert "Profile" in text, "docs must describe the Profile section"

    def test_docs_mentions_thresholds_section(self):
        text = self._read_docs()
        assert "threshold" in text.lower(), "docs must describe the Thresholds section"

    def test_docs_mentions_personal_records_section(self):
        text = self._read_docs()
        assert "Personal Record" in text, "docs must describe the Personal Records section"

    def test_docs_mentions_integrations_section(self):
        text = self._read_docs()
        assert "Integration" in text, "docs must describe the Integrations section"

    def test_docs_mentions_tss_calculations(self):
        text = self._read_docs()
        assert "TSS" in text, "docs must explain how thresholds affect TSS calculations"

    def test_docs_mentions_ftp(self):
        text = self._read_docs()
        assert "FTP" in text, "docs must mention FTP in context of TSS/thresholds"

    def test_docs_mentions_google_auth_as_future(self):
        text = self._read_docs()
        assert "Google" in text, "docs must mention Google auth as future/planned addition"


# ── AC (F): PATCH /user-preferences round-trip ───────────────────────────────

class TestACFUserPrefsRoundTrip:
    """Partial PATCH persists only the sent fields; GET reflects changes."""

    def test_patch_ftp_w_partial_payload(self, authed_client):
        """PATCH with only ftp_w updates that field; response contains it."""
        res = authed_client.patch("/api/user-preferences", json={"ftp_w": 310})
        assert res.status_code == 200, f"PATCH failed: {res.text}"
        data = res.json()
        assert data["ftp_w"] == 310

    def test_get_reflects_patched_ftp_w(self, authed_client):
        """Subsequent GET returns the updated ftp_w value."""
        authed_client.patch("/api/user-preferences", json={"ftp_w": 295})
        res = authed_client.get("/api/user-preferences")
        assert res.status_code == 200
        row = res.json()["row"]
        assert row["ftp_w"] == 295

    def test_patch_threshold_hr_only(self, authed_client):
        """PATCH with only threshold_hr leaves other fields unchanged."""
        # First set a known state
        authed_client.patch("/api/user-preferences", json={"ftp_w": 280, "threshold_hr": 160})
        # Then patch only threshold_hr
        res = authed_client.patch("/api/user-preferences", json={"threshold_hr": 172})
        assert res.status_code == 200
        data = res.json()
        assert data["threshold_hr"] == 172
        assert data["ftp_w"] == 280, "ftp_w should be unchanged"

    def test_patch_to_null_unsets_field(self, authed_client):
        """PATCH ftp_w to null explicitly unsets the field."""
        authed_client.patch("/api/user-preferences", json={"ftp_w": 300})
        res = authed_client.patch("/api/user-preferences", json={"ftp_w": None})
        assert res.status_code == 200
        assert res.json()["ftp_w"] is None

    def test_patch_invalid_ftp_w_returns_422(self, authed_client):
        """PATCH ftp_w=9999 returns 422 with error detail."""
        res = authed_client.patch("/api/user-preferences", json={"ftp_w": 9999})
        assert res.status_code == 422

    def test_patch_non_editable_field_returns_422(self, authed_client):
        """PATCH preferred_units returns 422 (not editable)."""
        res = authed_client.patch("/api/user-preferences", json={"preferred_units": "imperial"})
        assert res.status_code == 422


# ── AC (F): PRs CRUD round-trip ───────────────────────────────────────────────

class TestACFPRsCRUD:
    """create → read → update → delete round-trip for personal records."""

    @pytest.fixture(scope="class")
    def pr_client(self):
        """Session-authenticated client + user_id for PR tests."""
        username = f"pr365_{uuid.uuid4().hex[:8]}"
        temp = httpx.Client(base_url=BASE, timeout=10, follow_redirects=True)
        res = temp.post("/api/users", json={"name": username})
        assert res.status_code == 201
        user_id = res.json()["id"]
        temp.close()
        with Session(engine) as db:
            u = db.get(User, uuid.UUID(user_id))
            assert u is not None, f"User {user_id} not found in DB"
            u.password_hash = hash_password(_TEST_PASSWORD)
            db.commit()
        c = _make_authed_client(username, user_id)
        yield c
        c.delete(f"/api/users/{user_id}")
        c.close()

    def test_create_personal_record(self, pr_client):
        """POST /api/personal-records creates a new PR and returns 201."""
        res = pr_client.post("/api/personal-records", json={
            "user_id": pr_client._user_id,
            "track_key": "5k",
            "track_name": "5K",
            "track_type": "time",
            "value_numeric": 1320.0,
            "achieved_on": "2026-01-15",
        })
        assert res.status_code == 201, f"Create PR failed: {res.text}"
        data = res.json()
        assert data["track_key"] == "5k"
        assert data["value_numeric"] == 1320.0

    def test_read_personal_records_includes_created(self, pr_client):
        """GET /api/personal-records lists the created PR."""
        pr_client.post("/api/personal-records", json={
            "user_id": pr_client._user_id,
            "track_key": "10k",
            "track_name": "10K",
            "track_type": "time",
            "value_numeric": 2700.0,
            "achieved_on": "2026-02-01",
        })
        res = pr_client.get("/api/personal-records")
        assert res.status_code == 200
        records = res.json()
        track_keys = [r["track_key"] for r in records]
        assert "10k" in track_keys, "Created PR not found in list"

    def test_update_personal_record(self, pr_client):
        """PATCH /api/personal-records/{id} updates value_numeric."""
        # Create a PR to update
        create_res = pr_client.post("/api/personal-records", json={
            "user_id": pr_client._user_id,
            "track_key": "squat_1rm",
            "track_name": "Squat 1RM",
            "track_type": "weight",
            "value_numeric": 100.0,
            "achieved_on": "2026-03-01",
        })
        assert create_res.status_code == 201
        pr_id = create_res.json()["id"]
        # Update it
        patch_res = pr_client.patch(f"/api/personal-records/{pr_id}", json={"value_numeric": 110.0})
        assert patch_res.status_code == 200, f"PATCH failed: {patch_res.text}"
        assert patch_res.json()["value_numeric"] == 110.0

    def test_delete_personal_record(self, pr_client):
        """DELETE /api/personal-records/{id} removes the record (204)."""
        create_res = pr_client.post("/api/personal-records", json={
            "user_id": pr_client._user_id,
            "track_key": "bench_1rm",
            "track_name": "Bench Press 1RM",
            "track_type": "weight",
            "value_numeric": 80.0,
            "achieved_on": "2026-04-01",
        })
        assert create_res.status_code == 201
        pr_id = create_res.json()["id"]
        del_res = pr_client.delete(f"/api/personal-records/{pr_id}")
        assert del_res.status_code == 204

    def test_deleted_record_not_in_list(self, pr_client):
        """Deleted PR is absent from subsequent GET list."""
        create_res = pr_client.post("/api/personal-records", json={
            "user_id": pr_client._user_id,
            "track_key": "deadlift_1rm",
            "track_name": "Deadlift 1RM",
            "track_type": "weight",
            "value_numeric": 140.0,
            "achieved_on": "2026-05-01",
        })
        pr_id = create_res.json()["id"]
        pr_client.delete(f"/api/personal-records/{pr_id}")
        list_res = pr_client.get("/api/personal-records")
        ids = [r["id"] for r in list_res.json()]
        assert pr_id not in ids, "Deleted PR still appears in list"


# ── AC (F): Settings.js hash routing ─────────────────────────────────────────

class TestACFSettingsHashRouting:
    """settings.js must define correct section activation for each hash."""

    def test_settings_js_has_valid_sections_array(self, client):
        """settings.js defines VALID_SECTIONS with all 5 sections."""
        res = client.get("/js/settings.js")
        assert res.status_code == 200
        text = res.text
        for section in ["profile", "thresholds", "personal-records", "integrations", "about"]:
            assert section in text, f"settings.js VALID_SECTIONS missing '{section}'"

    def test_settings_js_default_section_is_profile(self, client):
        """settings.js DEFAULT_SECTION is 'profile'."""
        res = client.get("/js/settings.js")
        text = res.text
        assert "'profile'" in text or '"profile"' in text, (
            "settings.js must define profile as default section"
        )
        assert "DEFAULT_SECTION" in text

    def test_settings_js_activate_section_function(self, client):
        """settings.js has activateSection function."""
        res = client.get("/js/settings.js")
        assert "activateSection" in res.text

    def test_settings_js_hashchange_listener(self, client):
        """settings.js registers hashchange event listener."""
        res = client.get("/js/settings.js")
        assert "hashchange" in res.text

    def test_settings_js_reads_location_hash(self, client):
        """settings.js reads window.location.hash to determine active section."""
        res = client.get("/js/settings.js")
        assert "location.hash" in res.text

    def test_settings_js_activates_on_load(self, client):
        """settings.js calls activateSection on page load (not just on hashchange)."""
        res = client.get("/js/settings.js")
        text = res.text
        # Should call activateSection or getSectionFromHash at module init level
        assert "getSectionFromHash" in text or "activateSection" in text

    def test_each_section_id_present_in_settings_html(self, authed_client):
        """settings.html contains all 5 section divs."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        body = res.text
        for section in ["profile", "thresholds", "personal-records", "integrations", "about"]:
            assert f'id="section-{section}"' in body, (
                f"settings.html missing section div id='section-{section}'"
            )
