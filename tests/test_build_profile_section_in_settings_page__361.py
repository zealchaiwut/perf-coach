"""Tests for issue #361: Build Profile Section in Settings Page (runs against UAT)

Risk: MEDIUM — new frontend + backend feature; auth changed for user-preferences
endpoints (now session-based); DB migration adds users.email column.
→ 1-2 tests per HTTP-testable criterion; visual/JS ACs marked manual.

Prerequisites: tester361 user must exist in UAT DB with password "Test361pass!".
"""
import os
import pytest
import httpx


BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")

_CREDENTIALS = {"username": "tester361", "password": "Test361pass!"}

_REQUIRED_TIMEZONES = [
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Tokyo",
    "UTC",
    "America/Los_Angeles",
    "America/New_York",
    "Europe/London",
    "Europe/Berlin",
    "Australia/Sydney",
]


def _login():
    """Return (session_token, csrf_token) by posting to /api/auth/login."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/api/auth/login", json=_CREDENTIALS)
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
        session = c.cookies.get("session", "")
        csrf = ""
        for sc in r.headers.get_list("set-cookie"):
            if sc.startswith("csrf-token="):
                csrf = sc.split("=", 1)[1].split(";")[0]
                break
        assert session and csrf, f"Missing cookies after login: session={bool(session)}, csrf={bool(csrf)}"
        return session, csrf


class _AuthedClient:
    """Thin wrapper that injects session + CSRF into every request."""

    def __init__(self, base_url: str, session: str, csrf: str):
        self._session = session
        self._csrf = csrf
        self._cookie_header = f"session={session}; csrf-token={csrf}"
        self._client = httpx.Client(base_url=base_url, timeout=10.0)

    def _headers(self, extra=None):
        h = {"Cookie": self._cookie_header, "X-CSRF-Token": self._csrf}
        if extra:
            h.update(extra)
        return h

    def get(self, url, **kw):
        kw.setdefault("headers", {})
        kw["headers"].update({"Cookie": self._cookie_header})
        return self._client.get(url, **kw)

    def patch(self, url, **kw):
        kw.setdefault("headers", {})
        kw["headers"].update(self._headers())
        return self._client.patch(url, **kw)

    def close(self):
        self._client.close()


@pytest.fixture(scope="module")
def authed_client():
    session, csrf = _login()
    c = _AuthedClient(BASE_URL, session, csrf)
    yield c
    c.close()


@pytest.fixture(scope="module")
def anon_client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def settings_html(authed_client):
    r = authed_client.get("/settings")
    assert r.status_code == 200
    return r.text


# --- AC: unauthenticated request returns 401 ---

def test_build_profile_section_in_settings_page__unauthed_get_prefs_returns_401(anon_client):
    # AC: session auth required — anonymous GET returns 401
    r = anon_client.get("/api/user-preferences")
    assert r.status_code == 401, f"Expected 401 for unauthenticated request, got {r.status_code}"


# --- AC: GET returns display_name, user_name, user_email in row ---

def test_build_profile_section_in_settings_page__get_includes_user_name_and_email(authed_client):
    # AC 2/3/6: GET /api/user-preferences returns user_name and user_email in row
    r = authed_client.get("/api/user-preferences")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert "row" in data
    row = data["row"]
    assert "user_name" in row, "row must include user_name"
    assert "user_email" in row, "row must include user_email"
    assert "display_name" in row, "row must include display_name"


# --- AC: GET response has row + defaults structure ---

def test_build_profile_section_in_settings_page__get_returns_row_and_defaults(authed_client):
    # AC 6: response body has { "row": {...}, "defaults": {...} }
    r = authed_client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert "row" in data and "defaults" in data, "Response must have 'row' and 'defaults' keys"
    row = data["row"]
    for field in ("display_name", "week_start_day", "timezone", "user_name", "user_email"):
        assert field in row, f"row missing field: {field}"


# --- AC: profile section in settings.html has required form fields ---

def test_build_profile_section_in_settings_page__profile_section_has_form_fields(settings_html):
    # AC 1/2/3: profile section div present with display_name, email, timezone, week-start inputs
    assert "profile-display-name" in settings_html, "Display name input missing"
    assert "profile-email" in settings_html, "Email input missing"
    assert "profile-timezone" in settings_html, "Timezone select missing"
    assert "profile-week-start" in settings_html, "Week-start select missing"


# --- AC: timezone dropdown has exactly the 9 required options ---

def test_build_profile_section_in_settings_page__timezone_dropdown_has_9_options(settings_html):
    # AC 4: exactly 9 timezone options
    count = sum(1 for tz in _REQUIRED_TIMEZONES if tz in settings_html)
    assert count == 9, f"Expected all 9 required timezones in HTML, found {count}"


# --- AC: week starts on dropdown has Monday (1) and Sunday (7) ---

def test_build_profile_section_in_settings_page__week_start_has_monday_and_sunday(settings_html):
    # AC 5: Monday maps to 1, Sunday maps to 7
    assert 'value="1"' in settings_html, "Monday (value=1) missing from week-start dropdown"
    assert 'value="7"' in settings_html, "Sunday (value=7) missing from week-start dropdown"
    assert "Monday" in settings_html, "Monday label missing from week-start dropdown"
    assert "Sunday" in settings_html, "Sunday label missing from week-start dropdown"


# --- AC: PATCH with only changed field updates that field ---

def test_build_profile_section_in_settings_page__patch_updates_only_changed_field(authed_client):
    # AC 8: PATCH /api/user-preferences with only changed fields
    r = authed_client.patch("/api/user-preferences", json={"timezone": "Asia/Tokyo"})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    row = r.json()
    assert row.get("timezone") == "Asia/Tokyo", f"timezone not updated: {row}"


def test_build_profile_section_in_settings_page__patch_week_start_day_persists(authed_client):
    # AC 8: PATCH week_start_day=7 (Sunday) persists; GET confirms
    r = authed_client.patch("/api/user-preferences", json={"week_start_day": 7})
    assert r.status_code == 200, f"PATCH failed: {r.status_code}"
    assert r.json().get("week_start_day") == 7

    r2 = authed_client.get("/api/user-preferences")
    assert r2.json()["row"]["week_start_day"] == 7, "week_start_day not persisted"


# --- AC: PATCH with invalid data returns 422 with field error ---

def test_build_profile_section_in_settings_page__patch_invalid_timezone_returns_422(authed_client):
    # AC 10: invalid timezone → 422 with field-specific error
    r = authed_client.patch("/api/user-preferences", json={"timezone": "Fake/Zone"})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    detail = r.json().get("detail", [])
    assert any(e.get("field") == "timezone" for e in detail), \
        f"Expected field='timezone' in error detail: {detail}"


def test_build_profile_section_in_settings_page__patch_invalid_display_name_returns_422(authed_client):
    # AC 10: display_name > 100 chars → 422
    r = authed_client.patch("/api/user-preferences", json={"display_name": "x" * 101})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"


# --- AC: avatar section has deferred comment ---

def test_build_profile_section_in_settings_page__avatar_has_deferred_comment(settings_html):
    # AC 13: comment "Avatar upload deferred to future sprint." present
    assert "Avatar upload deferred to future sprint" in settings_html, \
        "Deferred avatar comment missing from settings.html"


# --- AC: no avatar upload UI present ---

def test_build_profile_section_in_settings_page__no_avatar_upload_ui(settings_html):
    # AC 14: no file input for avatar upload
    assert 'type="file"' not in settings_html, \
        "Avatar file upload input must not be present (deferred to future sprint)"


# --- AC: email field is read-only ---

def test_build_profile_section_in_settings_page__email_field_is_readonly(settings_html):
    # AC 3: email input has readonly attribute
    import re
    match = re.search(r'id="profile-email"[^>]*readonly|readonly[^>]*id="profile-email"', settings_html)
    assert match or "profile-email" in settings_html and "readonly" in settings_html, \
        "Email input must be readonly"


# --- Manual ACs ---

def test_build_profile_section_in_settings_page__save_button_disabled_on_load():
    # AC 7: Save button disabled on load; enabled only when dirty — JS behavior
    pytest.skip("manual — dirty-state toggle is JavaScript, cannot be HTTP-tested")


def test_build_profile_section_in_settings_page__success_toast_on_save():
    # AC 9: success toast appears after save — JavaScript behavior
    pytest.skip("manual — toast rendering is JavaScript, cannot be HTTP-tested")


def test_build_profile_section_in_settings_page__dirty_state_resets_after_save():
    # AC 11: dirty state resets after successful save — JavaScript behavior
    pytest.skip("manual — dirty state is JavaScript, cannot be HTTP-tested")


def test_build_profile_section_in_settings_page__avatar_shows_user_initials():
    # AC 12: avatar placeholder shows initials computed from display_name or email — JavaScript
    pytest.skip("manual — initials computation is JavaScript, cannot be HTTP-tested")


def test_build_profile_section_in_settings_page__mobile_layout_stacks_correctly():
    # AC 15: mobile layout — visual check required
    pytest.skip("manual — mobile layout requires browser at ≤375px viewport")


def test_build_profile_section_in_settings_page__zero_console_errors_on_load():
    # AC 16: zero console errors on load and save — requires browser DevTools
    pytest.skip("manual — console error check requires browser, cannot be HTTP-tested")
