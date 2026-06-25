"""Tests for issue #362: Build Performance Thresholds Settings Section (runs against UAT)

Risk: MEDIUM — new settings section with 3 inputs + API integration; no auth, deletion, or
destructive changes. Up to 2 tests per criterion.

Prerequisites: tester362 user must exist in UAT DB with password "Test362pass!".
Created by the tester workflow; recreate with set_user_password.py if needed.
"""
import os
import pytest
import httpx


BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")

_CREDENTIALS = {"username": "tester362", "password": "Test362pass!"}


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
def settings_html(authed_client):
    r = authed_client.get("/settings")
    assert r.status_code == 200
    return r.text


# ── AC 1: Performance Thresholds section renders inside settings.html ────────

def test_build_performance_thresholds__section_thresholds_div_in_settings(settings_html):
    # AC: section-thresholds div exists inside settings page
    assert 'id="section-thresholds"' in settings_html, "section-thresholds div missing from settings page"


# ── AC 2: FTP input (number, 50-600, default hint) ──────────────────────────

def test_build_performance_thresholds__ftp_input_attributes(settings_html):
    # AC: FTP input is number type with min=50, max=600, placeholder "(default: 280W)"
    assert 'id="thresholds-ftp"' in settings_html, "thresholds-ftp input missing"
    assert 'min="50"' in settings_html, "FTP min=50 attribute missing"
    assert 'max="600"' in settings_html, "FTP max=600 attribute missing"
    assert '(default: 280W)' in settings_html, "FTP default placeholder missing"


# ── AC 3: Threshold HR input (number, 100-220, default hint) ────────────────

def test_build_performance_thresholds__threshold_hr_input_attributes(settings_html):
    # AC: threshold HR input is number type with min=100, max=220, placeholder "(default: 170 bpm)"
    assert 'id="thresholds-hr"' in settings_html, "thresholds-hr input missing"
    assert 'min="100"' in settings_html, "HR min=100 attribute missing"
    assert 'max="220"' in settings_html, "HR max=220 attribute missing"
    assert '(default: 170 bpm)' in settings_html, "HR default placeholder missing"


# ── AC 4: Threshold pace input (text, M:SS/km, default hint) ────────────────

def test_build_performance_thresholds__threshold_pace_input_placeholder(settings_html):
    # AC: pace input is text type with placeholder "(default: 4:30/km)"
    assert 'id="thresholds-pace"' in settings_html, "thresholds-pace input missing"
    assert '(default: 4:30/km)' in settings_html, "Pace default placeholder missing"


# ── AC 5: "Use default" buttons present ─────────────────────────────────────

def test_build_performance_thresholds__use_default_buttons_present(settings_html):
    # AC: one "Use default" button per input (3 total)
    count = settings_html.count("Use default")
    assert count >= 3, f"Expected ≥3 'Use default' buttons in settings, found {count}"


# ── AC 5 (API): PATCH null clears ftp_w to null ─────────────────────────────

def test_build_performance_thresholds__patch_null_clears_ftp(authed_client):
    # AC: PATCH ftp_w=null sets field to null (Use default behaviour)
    authed_client.patch("/api/user-preferences", json={"ftp_w": 300})
    r = authed_client.patch("/api/user-preferences", json={"ftp_w": None})
    assert r.status_code == 200, f"PATCH null ftp_w failed: {r.status_code} {r.text}"
    assert r.json()["ftp_w"] is None, "ftp_w should be null after clearing"


# ── AC 6: Description labels present ────────────────────────────────────────

def test_build_performance_thresholds__description_labels_present(settings_html):
    # AC: each input has a description explaining its purpose
    assert "maximum sustainable power output" in settings_html, "FTP description missing"
    assert "lactate threshold" in settings_html, "Threshold HR description missing"
    assert "Running pace you can sustain" in settings_html, "Threshold pace description missing"


# ── AC 7: Pace parser (4:30, 4:30/km, 4:30 /km) ────────────────────────────

def test_build_performance_thresholds__pace_parser_handles_formats():
    # AC: pace parser treats "4:30", "4:30/km", "4:30 /km" as equivalent
    pytest.skip("manual — pace parsing is frontend JS; requires browser test")


# ── AC 8: Invalid input server-side validation ───────────────────────────────

def test_build_performance_thresholds__patch_invalid_ftp_returns_422(authed_client):
    # AC: FTP=999 (above max 600) returns 422 with field error
    r = authed_client.patch("/api/user-preferences", json={"ftp_w": 999})
    assert r.status_code == 422, f"Expected 422 for out-of-range FTP, got {r.status_code}"


def test_build_performance_thresholds__patch_invalid_pace_seconds_returns_422(authed_client):
    # AC: threshold_pace_seconds_per_km=50 (below min 180) returns 422
    r = authed_client.patch("/api/user-preferences", json={"threshold_pace_seconds_per_km": 50})
    assert r.status_code == 422, f"Expected 422 for out-of-range pace, got {r.status_code}"


# ── AC 9: Single Save button PATCHes all three values ───────────────────────

def test_build_performance_thresholds__patch_saves_all_three_threshold_values(authed_client):
    # AC: PATCH ftp_w=350, threshold_hr=165, threshold_pace_seconds_per_km=285 saves all; GET reflects them
    r = authed_client.patch("/api/user-preferences", json={
        "ftp_w": 350,
        "threshold_hr": 165,
        "threshold_pace_seconds_per_km": 285,
    })
    assert r.status_code == 200, f"PATCH failed: {r.status_code} {r.text}"
    row = r.json()
    assert row["ftp_w"] == 350, f"ftp_w not saved: {row}"
    assert row["threshold_hr"] == 165, f"threshold_hr not saved: {row}"
    assert row["threshold_pace_seconds_per_km"] == 285, f"threshold_pace not saved: {row}"

    # Verify persisted via GET
    r2 = authed_client.get("/api/user-preferences")
    assert r2.status_code == 200
    row2 = r2.json()["row"]
    assert row2["ftp_w"] == 350
    assert row2["threshold_hr"] == 165
    assert row2["threshold_pace_seconds_per_km"] == 285


# ── AC 10: Info card visible below inputs ────────────────────────────────────

def test_build_performance_thresholds__info_card_text_present(settings_html):
    # AC: info card reads "Changing these will recompute TSS for new workouts only..."
    assert "Changing these will recompute TSS for new workouts only" in settings_html, \
        "Info card text missing"
    assert "no retro recompute" in settings_html, "Info card retro-recompute note missing"


# ── AC 11: No console errors ─────────────────────────────────────────────────

def test_build_performance_thresholds__no_console_errors():
    # AC: zero console errors on page load, save, or clear actions
    pytest.skip("manual — requires browser DevTools console inspection")


# ── AC 12: Prerequisites ─────────────────────────────────────────────────────

def test_build_performance_thresholds__prerequisites_merged():
    # AC: tickets 1 (#356), 2 (#357), 5 (#360) merged before this work
    pytest.skip("manual — prerequisite merge status verified by sprint manager")
