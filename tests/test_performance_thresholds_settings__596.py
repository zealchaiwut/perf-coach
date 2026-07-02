"""Tests for issue #596: Add Performance Thresholds Section to Settings Page.

ACs covered:
  AC1  - "Performance Thresholds" nav entry present and links to section-thresholds div
  AC2  - Section has FTP (ftp_w), Threshold HR (threshold_hr), Max HR (max_hr) inputs
  AC3  - GET /api/user-preferences returns row.max_hr and defaults.max_hr=190
  AC4  - PATCH sends only changed fields; max_hr persists correctly (round-trip)
  AC5  - Save button and success-feedback element present
  AC6  - Generic error feedback element present
  AC7  - PATCH max_hr out-of-range → 422 with field-level error
  AC8  - Successful save round-trips (verified via API, not browser reload)
  AC9  - Section follows same HTML pattern as Profile/Security/Integrations

JS-only ACs (inline error display, prefill with defaults, partial-payload check) are
marked manual-skip below.

Server: http://127.0.0.1:9001
"""
import uuid

import httpx
import pytest

from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session
from tests._admin_helpers import admin_cookies as _admin_cookies


BASE_URL = "http://127.0.0.1:9001"
_TEST_PASSWORD = "Perf596testPw!"


@pytest.fixture(scope="module")
def authed_client():
    username = f"tester596_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=True) as c:
        res = c.post("/api/users", json={"name": username}, cookies=_admin_cookies())
        assert res.status_code == 201, f"Failed to create test user: {res.text}"
        user_id = res.json()["id"]

        with Session(engine) as db:
            user = db.get(User, uuid.UUID(user_id))
            assert user is not None
            user.password_hash = hash_password(_TEST_PASSWORD)
            db.commit()

        csrf = ""
        login = c.post("/api/auth/login", json={"username": username, "password": _TEST_PASSWORD})
        assert login.status_code == 200, f"Login failed: {login.text}"
        for sc in login.headers.get_list("set-cookie"):
            if sc.startswith("csrf-token="):
                csrf = sc.split("=", 1)[1].split(";")[0]
                break

        c._csrf = csrf
        yield c

        c.delete(f"/api/users/{user_id}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def settings_html(authed_client):
    r = authed_client.get("/settings")
    assert r.status_code == 200
    return r.text


def _patch(client, payload):
    csrf = getattr(client, "_csrf", "")
    return client.patch(
        "/api/user-preferences",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )


def _get_prefs(client):
    return client.get("/api/user-preferences")


# ── AC1: Performance Thresholds nav entry ────────────────────────────────────

def test_performance_thresholds_596__nav_entry_present(settings_html):
    # AC1: sidebar nav has a button/link for the thresholds section
    assert 'data-section="thresholds"' in settings_html, \
        "Nav button with data-section='thresholds' missing from settings.html"
    assert "Performance Thresholds" in settings_html, \
        "'Performance Thresholds' text missing from settings nav"


def test_performance_thresholds_596__section_div_present(settings_html):
    # AC1: section-thresholds div exists
    assert 'id="section-thresholds"' in settings_html, \
        "id='section-thresholds' div missing from settings.html"


# ── AC2: Three required inputs (FTP, Threshold HR, Max HR) ───────────────────

def test_performance_thresholds_596__ftp_input_present(settings_html):
    # AC2: FTP number input with id=thresholds-ftp
    assert 'id="thresholds-ftp"' in settings_html, \
        "FTP input (id=thresholds-ftp) missing"
    assert 'type="number"' in settings_html, \
        "FTP input must be type=number"


def test_performance_thresholds_596__threshold_hr_input_present(settings_html):
    # AC2: Threshold HR input with id=thresholds-hr
    assert 'id="thresholds-hr"' in settings_html, \
        "Threshold HR input (id=thresholds-hr) missing"


def test_performance_thresholds_596__max_hr_input_present(settings_html):
    # AC2: Max HR number input with id=thresholds-max-hr must be present
    assert 'id="thresholds-max-hr"' in settings_html, \
        "Max HR input (id=thresholds-max-hr) missing from settings.html"


def test_performance_thresholds_596__max_hr_label_and_unit(settings_html):
    # AC2: 'Max HR' label and 'bpm' unit indicator present
    assert "Max HR" in settings_html or "Max Heart Rate" in settings_html, \
        "'Max HR' / 'Max Heart Rate' label missing from thresholds section"
    assert "bpm" in settings_html, \
        "'bpm' unit label missing from thresholds section"


def test_performance_thresholds_596__max_hr_default_hint(settings_html):
    # AC2: Default value for max_hr (190) referenced in page
    assert "190" in settings_html, \
        "Max HR default value 190 not referenced in settings.html"


# ── AC3: GET response includes max_hr field and default ───────────────────────

def test_performance_thresholds_596__get_prefs_returns_max_hr(authed_client):
    # AC3: GET /api/user-preferences row includes max_hr; defaults.max_hr == 190
    r = _get_prefs(authed_client)
    assert r.status_code == 200, f"GET /api/user-preferences failed: {r.status_code}"
    data = r.json()
    assert "row" in data, "Response missing 'row' key"
    assert "defaults" in data, "Response missing 'defaults' key"
    assert "max_hr" in data["row"], "row missing max_hr field"
    defaults = data["defaults"]
    assert "max_hr" in defaults, "defaults missing max_hr"
    assert defaults["max_hr"] == 190, \
        f"defaults.max_hr should be 190, got {defaults.get('max_hr')}"


def test_performance_thresholds_596__get_prefs_also_returns_ftp_and_threshold_hr(authed_client):
    # AC3: GET also returns the other two required fields
    r = _get_prefs(authed_client)
    data = r.json()
    row = data["row"]
    assert "ftp_w" in row, "row missing ftp_w"
    assert "threshold_hr" in row, "row missing threshold_hr"
    assert data["defaults"].get("ftp_w") == 280
    assert data["defaults"].get("threshold_hr") == 170


# ── AC4/AC8: PATCH max_hr saves and round-trips ──────────────────────────────

def test_performance_thresholds_596__patch_max_hr_valid_saves(authed_client):
    # AC4/AC8: PATCH max_hr=185 → 200 → response.max_hr == 185
    r = _patch(authed_client, {"max_hr": 185})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("max_hr") == 185, f"max_hr not persisted: {r.json()}"


def test_performance_thresholds_596__patch_max_hr_round_trips(authed_client):
    # AC8: After PATCH, GET returns the saved max_hr
    _patch(authed_client, {"max_hr": 185})
    r = _get_prefs(authed_client)
    assert r.json()["row"]["max_hr"] == 185, \
        f"max_hr not round-tripped via GET: {r.json()['row']}"


def test_performance_thresholds_596__patch_max_hr_null_clears(authed_client):
    # AC4: PATCH max_hr=null clears custom value (reverts to default display)
    r = _patch(authed_client, {"max_hr": None})
    assert r.status_code == 200, f"Expected 200 for max_hr=null, got {r.status_code}: {r.text}"
    assert r.json().get("max_hr") is None, \
        f"max_hr should be null after clear, got {r.json().get('max_hr')}"


def test_performance_thresholds_596__patch_only_max_hr_leaves_ftp_unchanged(authed_client):
    # AC4: partial PATCH (max_hr only) does not alter other fields
    _patch(authed_client, {"ftp_w": 300})
    _patch(authed_client, {"max_hr": 185})
    r = _get_prefs(authed_client)
    assert r.json()["row"]["ftp_w"] == 300, \
        f"ftp_w changed unexpectedly: {r.json()['row']}"
    assert r.json()["row"]["max_hr"] == 185


# ── AC5: Save button and success-feedback element ───────────────────────────

def test_performance_thresholds_596__save_button_present(settings_html):
    # AC5: Save button with id=thresholds-save-btn
    assert 'id="thresholds-save-btn"' in settings_html, \
        "Save button (id=thresholds-save-btn) missing"


def test_performance_thresholds_596__feedback_element_present(settings_html):
    # AC5/AC6: thresholds-feedback element (used for success and generic error)
    assert 'id="thresholds-feedback"' in settings_html, \
        "Feedback element (id=thresholds-feedback) missing"


# ── AC6/AC7: Inline error element for max_hr ────────────────────────────────

def test_performance_thresholds_596__max_hr_inline_error_element_present(settings_html):
    # AC7: inline error div for max_hr field must exist in DOM
    assert 'id="thresholds-max-hr-error"' in settings_html, \
        "Inline error div (id=thresholds-max-hr-error) missing"


# ── AC7: 422 with field-level error for max_hr ───────────────────────────────

def test_performance_thresholds_596__patch_max_hr_too_high_returns_422(authed_client):
    # AC7: max_hr=9999 (above 230) → 422 with field='max_hr'
    r = _patch(authed_client, {"max_hr": 9999})
    assert r.status_code == 422, f"Expected 422 for max_hr=9999, got {r.status_code}"
    detail = r.json().get("detail", [])
    assert any(e.get("field") == "max_hr" for e in detail), \
        f"Expected field='max_hr' in 422 detail: {detail}"


def test_performance_thresholds_596__patch_max_hr_too_low_returns_422(authed_client):
    # AC7: max_hr=50 (below 120) → 422
    r = _patch(authed_client, {"max_hr": 50})
    assert r.status_code == 422, f"Expected 422 for max_hr=50, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", [])
    assert any(e.get("field") == "max_hr" for e in detail), \
        f"Expected field='max_hr' in 422 detail: {detail}"


def test_performance_thresholds_596__patch_valid_ftp_and_max_hr_together(authed_client):
    # AC4: PATCH with both ftp_w and max_hr saves both
    r = _patch(authed_client, {"ftp_w": 250, "max_hr": 190})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("ftp_w") == 250
    assert body.get("max_hr") == 190


# ── AC9: Section follows existing settings HTML pattern ─────────────────────

def test_performance_thresholds_596__section_follows_settings_pattern(settings_html):
    # AC9: section has settings-section class and h1 heading
    assert 'class="settings-section' in settings_html, \
        "settings-section class pattern missing"
    assert "<h1>Performance Thresholds</h1>" in settings_html, \
        "h1 'Performance Thresholds' heading missing from section"


# ── Manual-only ACs (JS DOM behaviour) ──────────────────────────────────────

def test_performance_thresholds_596__prefill_shows_default_when_null():
    # AC3: when row.max_hr is null, input displays defaults.max_hr (190) — JS only
    pytest.skip("manual — prefill with defaults is JavaScript, cannot be HTTP-tested")


def test_performance_thresholds_596__partial_patch_only_changed_fields():
    # AC4: JS sends only changed fields in PATCH — verified via network inspector
    pytest.skip("manual — partial-patch JS behaviour cannot be HTTP-tested")


def test_performance_thresholds_596__inline_error_display_on_422():
    # AC7: field-level error shown inline beneath max_hr input on 422 — JS only
    pytest.skip("manual — inline error display is JavaScript DOM, cannot be HTTP-tested")


def test_performance_thresholds_596__success_message_appears_after_save():
    # AC5: 'Preferences saved.' message appears after successful PATCH — JS only
    pytest.skip("manual — success feedback display is JavaScript, cannot be HTTP-tested")


def test_performance_thresholds_596__generic_error_on_network_failure():
    # AC6: generic error line on non-422 network failure — JS only
    pytest.skip("manual — network error handling is JavaScript, cannot be HTTP-tested")
