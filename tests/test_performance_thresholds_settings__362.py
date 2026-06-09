"""Tests for issue #362: Build Performance Thresholds Settings Section (runs against UAT)

Risk: LOW-MEDIUM — frontend-only feature; PATCH /api/user-preferences already exists and validated.
→ Tests cover all HTTP-testable ACs; JS-only behaviours (inline errors, "Use default" button DOM
  manipulation, no console errors) are marked manual.

Prerequisites: tester362 user must exist in UAT DB with password "Test362pass!".
"""
import os
import pytest
import httpx


BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")

_CREDENTIALS = {"username": "tester362", "password": "Test362pass!"}


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


# ── AC 1: Performance Thresholds section renders in correct div ──────────────

def test_performance_thresholds_settings__section_div_present(settings_html):
    # AC 1: section-thresholds div is present and has h1
    assert 'id="section-thresholds"' in settings_html, \
        "section-thresholds div missing from settings.html"
    assert "Performance Thresholds" in settings_html, \
        "h1 'Performance Thresholds' missing"


# ── AC 2: FTP input ──────────────────────────────────────────────────────────

def test_performance_thresholds_settings__ftp_input_present(settings_html):
    # AC 2: FTP number input with id thresholds-ftp is present
    assert 'id="thresholds-ftp"' in settings_html, \
        "FTP input (id=thresholds-ftp) missing from settings.html"
    # must be a number input
    assert 'type="number"' in settings_html, \
        "FTP must be a number input"


def test_performance_thresholds_settings__ftp_default_hint_present(settings_html):
    # AC 2: default hint "(default: 280W)" present
    assert "280" in settings_html, \
        "FTP default value 280 not referenced in settings.html"
    assert "default: 280" in settings_html or "280W" in settings_html, \
        "FTP default hint '280W' missing"


# ── AC 3: Threshold HR input ─────────────────────────────────────────────────

def test_performance_thresholds_settings__threshold_hr_input_present(settings_html):
    # AC 3: Threshold HR number input with id thresholds-hr is present
    assert 'id="thresholds-hr"' in settings_html, \
        "Threshold HR input (id=thresholds-hr) missing from settings.html"


def test_performance_thresholds_settings__threshold_hr_default_hint_present(settings_html):
    # AC 3: default hint "170 bpm" present
    assert "170" in settings_html, \
        "Threshold HR default 170 not referenced in settings.html"
    assert "default: 170" in settings_html or "170 bpm" in settings_html, \
        "Threshold HR default hint '170 bpm' missing"


# ── AC 4: Threshold Pace input ───────────────────────────────────────────────

def test_performance_thresholds_settings__threshold_pace_input_present(settings_html):
    # AC 4: Threshold pace text input with id thresholds-pace is present
    assert 'id="thresholds-pace"' in settings_html, \
        "Threshold pace input (id=thresholds-pace) missing from settings.html"


def test_performance_thresholds_settings__threshold_pace_default_hint_present(settings_html):
    # AC 4: default hint "4:30/km" present
    assert "4:30" in settings_html, \
        "Threshold pace default 4:30 not referenced in settings.html"


# ── AC 5: "Use default" buttons ──────────────────────────────────────────────

def test_performance_thresholds_settings__use_default_buttons_present(settings_html):
    # AC 5: each input must have a "Use default" button
    assert settings_html.count("Use default") >= 3, \
        "Expected at least 3 'Use default' buttons (one per threshold field)"


# ── AC 6: Description labels present ─────────────────────────────────────────

def test_performance_thresholds_settings__description_labels_present(settings_html):
    # AC 6: description text present for each field
    # FTP description
    assert "FTP" in settings_html or "Functional Threshold Power" in settings_html, \
        "FTP description label missing"
    # HR description
    assert "heart rate" in settings_html.lower() or "threshold hr" in settings_html.lower(), \
        "Threshold HR description label missing"
    # Pace description
    assert "pace" in settings_html.lower(), \
        "Threshold pace description label missing"


# ── AC 9: Single Save button present ─────────────────────────────────────────

def test_performance_thresholds_settings__save_button_present(settings_html):
    # AC 9: Save button exists for thresholds section
    assert 'id="thresholds-save-btn"' in settings_html, \
        "Thresholds Save button (id=thresholds-save-btn) missing"


# ── AC 10: Info card present ─────────────────────────────────────────────────

def test_performance_thresholds_settings__info_card_text_present(settings_html):
    # AC 10: info card with TSS recompute note
    assert "new workouts only" in settings_html, \
        "Info card text 'new workouts only' missing from settings.html"
    assert "no retro recompute" in settings_html or "Past workouts keep" in settings_html, \
        "Info card retro-recompute note missing from settings.html"


# ── AC 9: GET /api/user-preferences returns threshold fields ─────────────────

def test_performance_thresholds_settings__get_prefs_returns_threshold_fields(authed_client):
    # AC 9: GET response row includes ftp_w, threshold_hr, threshold_pace_seconds_per_km
    r = authed_client.get("/api/user-preferences")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert "row" in data and "defaults" in data
    row = data["row"]
    assert "ftp_w" in row, "row missing ftp_w"
    assert "threshold_hr" in row, "row missing threshold_hr"
    assert "threshold_pace_seconds_per_km" in row, "row missing threshold_pace_seconds_per_km"
    defaults = data["defaults"]
    assert defaults.get("ftp_w") == 280, f"ftp_w default must be 280, got {defaults.get('ftp_w')}"
    assert defaults.get("threshold_hr") == 170, \
        f"threshold_hr default must be 170, got {defaults.get('threshold_hr')}"
    assert defaults.get("threshold_pace_seconds_per_km") == 270, \
        f"threshold_pace_seconds_per_km default must be 270, got {defaults.get('threshold_pace_seconds_per_km')}"


# ── AC 9: PATCH saves valid FTP ───────────────────────────────────────────────

def test_performance_thresholds_settings__patch_ftp_valid_saves(authed_client):
    # AC 9: PATCH ftp_w=350 saves and returns updated value
    r = authed_client.patch("/api/user-preferences", json={"ftp_w": 350})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("ftp_w") == 350, f"ftp_w not updated: {r.json()}"


def test_performance_thresholds_settings__patch_ftp_null_clears(authed_client):
    # AC 5: PATCH ftp_w=null clears the value → GET returns null, shows default
    r = authed_client.patch("/api/user-preferences", json={"ftp_w": None})
    assert r.status_code == 200, f"Expected 200 for ftp_w=null, got {r.status_code}: {r.text}"
    assert r.json().get("ftp_w") is None, f"ftp_w should be null after clear: {r.json()}"

    r2 = authed_client.get("/api/user-preferences")
    assert r2.json()["row"]["ftp_w"] is None, "ftp_w should be null on GET after clear"


# ── AC 8: PATCH with out-of-range FTP returns 422 ────────────────────────────

def test_performance_thresholds_settings__patch_ftp_out_of_range_returns_422(authed_client):
    # AC 8: ftp_w=999 is out of 50–600 range → 422
    r = authed_client.patch("/api/user-preferences", json={"ftp_w": 999})
    assert r.status_code == 422, f"Expected 422 for ftp_w=999, got {r.status_code}"
    detail = r.json().get("detail", [])
    assert any(e.get("field") == "ftp_w" for e in detail), \
        f"Expected field='ftp_w' in 422 detail: {detail}"


def test_performance_thresholds_settings__patch_ftp_below_min_returns_422(authed_client):
    # AC 8: ftp_w=10 is below 50 → 422
    r = authed_client.patch("/api/user-preferences", json={"ftp_w": 10})
    assert r.status_code == 422, f"Expected 422 for ftp_w=10, got {r.status_code}"


# ── AC 9: PATCH saves valid threshold HR ─────────────────────────────────────

def test_performance_thresholds_settings__patch_threshold_hr_valid_saves(authed_client):
    # AC 9: PATCH threshold_hr=165 saves correctly
    r = authed_client.patch("/api/user-preferences", json={"threshold_hr": 165})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("threshold_hr") == 165, f"threshold_hr not updated: {r.json()}"


def test_performance_thresholds_settings__patch_threshold_hr_null_clears(authed_client):
    # AC 5: PATCH threshold_hr=null clears
    r = authed_client.patch("/api/user-preferences", json={"threshold_hr": None})
    assert r.status_code == 200, f"Expected 200 for threshold_hr=null, got {r.status_code}"
    assert r.json().get("threshold_hr") is None


# ── AC 8: PATCH with out-of-range HR returns 422 ─────────────────────────────

def test_performance_thresholds_settings__patch_threshold_hr_out_of_range_returns_422(authed_client):
    # AC 8: threshold_hr=250 is above 220 → 422
    r = authed_client.patch("/api/user-preferences", json={"threshold_hr": 250})
    assert r.status_code == 422, f"Expected 422 for threshold_hr=250, got {r.status_code}"
    detail = r.json().get("detail", [])
    assert any(e.get("field") == "threshold_hr" for e in detail), \
        f"Expected field='threshold_hr' in 422 detail: {detail}"


# ── AC 9: PATCH saves valid threshold pace (seconds per km) ──────────────────

def test_performance_thresholds_settings__patch_threshold_pace_valid_saves(authed_client):
    # AC 9: PATCH threshold_pace_seconds_per_km=285 (4:45/km) saves
    r = authed_client.patch("/api/user-preferences", json={"threshold_pace_seconds_per_km": 285})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("threshold_pace_seconds_per_km") == 285, \
        f"threshold_pace_seconds_per_km not updated: {r.json()}"


def test_performance_thresholds_settings__patch_threshold_pace_null_clears(authed_client):
    # AC 5: PATCH threshold_pace_seconds_per_km=null clears
    r = authed_client.patch("/api/user-preferences", json={"threshold_pace_seconds_per_km": None})
    assert r.status_code == 200, f"Expected 200 for pace=null, got {r.status_code}"
    assert r.json().get("threshold_pace_seconds_per_km") is None


def test_performance_thresholds_settings__patch_threshold_pace_out_of_range_returns_422(authed_client):
    # AC 8: pace=50 (under 180s min) → 422
    r = authed_client.patch("/api/user-preferences", json={"threshold_pace_seconds_per_km": 50})
    assert r.status_code == 422, f"Expected 422 for pace=50s, got {r.status_code}"
    detail = r.json().get("detail", [])
    assert any(e.get("field") == "threshold_pace_seconds_per_km" for e in detail), \
        f"Expected field='threshold_pace_seconds_per_km' in 422 detail: {detail}"


# ── AC 9: PATCH all three at once ────────────────────────────────────────────

def test_performance_thresholds_settings__patch_all_three_values_at_once(authed_client):
    # AC 9: save all three fields in a single PATCH
    payload = {"ftp_w": 350, "threshold_hr": 165, "threshold_pace_seconds_per_km": 285}
    r = authed_client.patch("/api/user-preferences", json=payload)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    row = r.json()
    assert row.get("ftp_w") == 350
    assert row.get("threshold_hr") == 165
    assert row.get("threshold_pace_seconds_per_km") == 285


# ── Manual ACs ───────────────────────────────────────────────────────────────

def test_performance_thresholds_settings__pace_parser_formats():
    # AC 7: pace parser handles "4:30", "4:30/km", "4:30 /km" → JS-only
    pytest.skip("manual — pace string parsing is JavaScript, cannot be HTTP-tested")


def test_performance_thresholds_settings__invalid_input_shows_inline_error():
    # AC 8: inline error on invalid input — JS DOM behaviour
    pytest.skip("manual — inline error display is JavaScript, cannot be HTTP-tested")


def test_performance_thresholds_settings__use_default_clears_field():
    # AC 5: Use default button clears field to null — JS DOM behaviour
    pytest.skip("manual — Use default button is JavaScript, cannot be HTTP-tested")


def test_performance_thresholds_settings__no_console_errors():
    # AC 11: no console errors on load/save/clear — requires browser DevTools
    pytest.skip("manual — console error check requires browser, cannot be HTTP-tested")
