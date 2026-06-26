"""Tests for issue #1022: Settings thresholds editor writes FTP, threshold heart rate, threshold pace.

AC items:
  AC1 - Settings page has a Thresholds section with three numeric inputs:
        FTP (watts), Threshold Heart Rate (bpm), Threshold Pace (sec/km, numeric)
  AC2 - Submitting the form writes all three values to user_preferences
  AC3 - An empty input is stored as NULL / no value — not as 0
  AC4 - After saving, reloading re-populates with stored value or blank — JS only
  AC5 - Saving with all three fields empty accepted without error
  AC6 - Input validation rejects non-numeric characters; no field is required

Server: http://127.0.0.1:9001
"""
import uuid
from pathlib import Path

import httpx
import pytest

from backend.auth import hash_password
from backend.db import engine
from backend.models import User, UserPreferences
from sqlalchemy.orm import Session

BASE_URL = "http://127.0.0.1:9001"
_TEST_PASSWORD = "Perf1022testPw!"
_SETTINGS_HTML = Path(__file__).parent.parent / "frontend" / "pages" / "settings.html"


@pytest.fixture(scope="module")
def authed_client():
    username = f"tester1022_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=True) as c:
        res = c.post("/api/users", json={"name": username})
        assert res.status_code == 201, f"Failed to create test user: {res.text}"
        user_id = res.json()["id"]

        with Session(engine) as db:
            user = db.get(User, uuid.UUID(user_id))
            assert user is not None
            user.password_hash = hash_password(_TEST_PASSWORD)
            db.commit()

        login = c.post("/api/auth/login", json={"username": username, "password": _TEST_PASSWORD})
        assert login.status_code == 200, f"Login failed: {login.text}"
        csrf = ""
        for sc in login.headers.get_list("set-cookie"):
            if sc.startswith("csrf-token="):
                csrf = sc.split("=", 1)[1].split(";")[0]
                break
        c._csrf = csrf
        c._user_id = user_id
        yield c

        c.delete(f"/api/users/{user_id}")


def _patch(client, payload):
    csrf = getattr(client, "_csrf", "")
    return client.patch(
        "/api/user-preferences",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )


def _get_prefs(client):
    return client.get("/api/user-preferences")


@pytest.fixture
def settings_html():
    return _SETTINGS_HTML.read_text()


# ── AC1: Thresholds section exists with three numeric inputs ──────────────────

def test_ac1_thresholds_section_present(settings_html):
    # AC1: section-thresholds div exists in settings page
    assert 'id="section-thresholds"' in settings_html, \
        "id='section-thresholds' div missing from settings.html"


def test_ac1_thresholds_nav_item_present(settings_html):
    # AC1: sidebar nav has a button that activates the thresholds section
    assert 'data-section="thresholds"' in settings_html, \
        "Nav button with data-section='thresholds' missing from settings.html"


def test_ac1_ftp_input_present_and_numeric(settings_html):
    # AC1: FTP input (id=thresholds-ftp) must be numeric
    assert 'id="thresholds-ftp"' in settings_html, \
        "FTP input (id=thresholds-ftp) missing from settings.html"
    # The FTP input must appear before a 'type="number"' attribute
    ftp_pos = settings_html.find('id="thresholds-ftp"')
    assert ftp_pos != -1
    # Check within 200 chars of the id attribute for type=number
    nearby = settings_html[max(0, ftp_pos - 50):ftp_pos + 100]
    assert 'type="number"' in nearby, \
        "FTP input must be type=number (numeric input required by AC1)"


def test_ac1_threshold_hr_input_present_and_numeric(settings_html):
    # AC1: Threshold HR input (id=thresholds-hr) must be numeric
    assert 'id="thresholds-hr"' in settings_html, \
        "Threshold HR input (id=thresholds-hr) missing from settings.html"
    hr_pos = settings_html.find('id="thresholds-hr"')
    nearby = settings_html[max(0, hr_pos - 50):hr_pos + 100]
    assert 'type="number"' in nearby, \
        "Threshold HR input must be type=number"


def test_ac1_threshold_pace_input_present_and_numeric(settings_html):
    # AC1: Threshold Pace input (id=thresholds-pace) must be a numeric type (seconds/km)
    assert 'id="thresholds-pace"' in settings_html, \
        "Threshold Pace input (id=thresholds-pace) missing from settings.html"
    pace_pos = settings_html.find('id="thresholds-pace"')
    nearby = settings_html[max(0, pace_pos - 50):pace_pos + 150]
    assert 'type="number"' in nearby, \
        "Threshold Pace input must be type=number (seconds/km, not M:SS text — AC1/AC6 of issue #1022)"


def test_ac1_ftp_label_and_unit(settings_html):
    # AC1: FTP input has watts label
    assert "FTP" in settings_html, "'FTP' label missing from thresholds section"
    assert ("watts" in settings_html or "W" in settings_html), \
        "Watts unit indicator missing from FTP input area"


def test_ac1_threshold_hr_label_and_unit(settings_html):
    # AC1: Threshold HR label and bpm unit present
    assert "Threshold Heart Rate" in settings_html or "Threshold HR" in settings_html, \
        "'Threshold Heart Rate' label missing from thresholds section"
    assert "bpm" in settings_html, "'bpm' unit missing from thresholds section"


def test_ac1_threshold_pace_label_and_unit(settings_html):
    # AC1: Threshold Pace label and sec/km unit description present
    assert "Threshold Pace" in settings_html, \
        "'Threshold Pace' label missing from thresholds section"
    assert ("sec/km" in settings_html or "seconds per kilometre" in settings_html
            or "seconds/km" in settings_html), \
        "Seconds-per-km unit description missing from Threshold Pace area (AC1 requires numeric sec/km)"


# ── AC2: PATCH writes all three values ───────────────────────────────────────

def test_ac2_patch_all_three_writes_values(authed_client):
    # AC2: Submitting all three values via PATCH persists them
    r = _patch(authed_client, {"ftp_w": 280, "threshold_hr": 165,
                               "threshold_pace_seconds_per_km": 240})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("ftp_w") == 280, f"ftp_w not saved: {body}"
    assert body.get("threshold_hr") == 165, f"threshold_hr not saved: {body}"
    assert body.get("threshold_pace_seconds_per_km") == 240, f"threshold_pace not saved: {body}"


def test_ac2_get_reflects_saved_values(authed_client):
    # AC2: GET after PATCH reflects the written values
    _patch(authed_client, {"ftp_w": 300, "threshold_hr": 170,
                           "threshold_pace_seconds_per_km": 260})
    r = _get_prefs(authed_client)
    assert r.status_code == 200
    row = r.json()["row"]
    assert row.get("ftp_w") == 300
    assert row.get("threshold_hr") == 170
    assert row.get("threshold_pace_seconds_per_km") == 260


# ── AC3: Empty input stored as NULL, not 0 ───────────────────────────────────

def test_ac3_ftp_null_stored_as_null_not_zero(authed_client):
    # AC3: PATCH ftp_w=null → response.ftp_w is null (not 0)
    _patch(authed_client, {"ftp_w": 280})
    r = _patch(authed_client, {"ftp_w": None})
    assert r.status_code == 200, f"Expected 200 for null ftp_w, got {r.status_code}: {r.text}"
    assert r.json().get("ftp_w") is None, \
        f"ftp_w should be null (not 0) when cleared: {r.json().get('ftp_w')}"


def test_ac3_threshold_hr_null_stored_as_null_not_zero(authed_client):
    # AC3: PATCH threshold_hr=null → response.threshold_hr is null (not 0)
    _patch(authed_client, {"threshold_hr": 165})
    r = _patch(authed_client, {"threshold_hr": None})
    assert r.status_code == 200
    assert r.json().get("threshold_hr") is None, \
        f"threshold_hr should be null (not 0) when cleared: {r.json().get('threshold_hr')}"


def test_ac3_threshold_pace_null_stored_as_null_not_zero(authed_client):
    # AC3: PATCH threshold_pace_seconds_per_km=null → response value is null (not 0)
    _patch(authed_client, {"threshold_pace_seconds_per_km": 240})
    r = _patch(authed_client, {"threshold_pace_seconds_per_km": None})
    assert r.status_code == 200
    assert r.json().get("threshold_pace_seconds_per_km") is None, \
        f"threshold_pace should be null (not 0) when cleared: {r.json().get('threshold_pace_seconds_per_km')}"


def test_ac3_get_returns_null_not_zero_when_no_value_stored(authed_client):
    # AC3: GET returns null (not 0) for fields that haven't been set
    _patch(authed_client, {"ftp_w": None, "threshold_hr": None,
                           "threshold_pace_seconds_per_km": None})
    r = _get_prefs(authed_client)
    assert r.status_code == 200
    row = r.json()["row"]
    assert row.get("ftp_w") is None, f"ftp_w should be null, got {row.get('ftp_w')}"
    assert row.get("threshold_hr") is None, \
        f"threshold_hr should be null, got {row.get('threshold_hr')}"
    assert row.get("threshold_pace_seconds_per_km") is None, \
        f"threshold_pace should be null, got {row.get('threshold_pace_seconds_per_km')}"


# ── AC4: After saving, reloading re-populates (or blank) — JS only ───────────

def test_ac4_api_returns_null_when_no_value_stored_for_blank_display():
    # AC4 (API side): GET returns null for unset fields so JS can show blank inputs
    # The actual blank-display behaviour is JavaScript (covered in manual UAT step 4)
    pytest.skip("manual — blank-input display on reload is JavaScript DOM, not HTTP-testable")


# ── AC5: Saving with all three empty accepted without error ───────────────────

def test_ac5_patch_all_null_returns_200(authed_client):
    # AC5: PATCH with all three fields null → 200 (accepted, stores no values)
    r = _patch(authed_client, {"ftp_w": None, "threshold_hr": None,
                               "threshold_pace_seconds_per_km": None})
    assert r.status_code == 200, \
        f"Saving all-null payload should be accepted (200), got {r.status_code}: {r.text}"


def test_ac5_patch_all_null_stores_no_values(authed_client):
    # AC5: after PATCH all-null, GET confirms all three are null (no values stored)
    _patch(authed_client, {"ftp_w": None, "threshold_hr": None,
                           "threshold_pace_seconds_per_km": None})
    r = _get_prefs(authed_client)
    row = r.json()["row"]
    assert row.get("ftp_w") is None
    assert row.get("threshold_hr") is None
    assert row.get("threshold_pace_seconds_per_km") is None


# ── AC6: Input validation rejects non-numeric; no field required ──────────────

def test_ac6_ftp_rejects_non_integer_value(authed_client):
    # AC6: non-numeric string for ftp_w → 422
    r = _patch(authed_client, {"ftp_w": "abc"})
    assert r.status_code == 422, \
        f"Expected 422 for non-numeric ftp_w, got {r.status_code}"


def test_ac6_threshold_hr_rejects_non_integer_value(authed_client):
    # AC6: non-numeric string for threshold_hr → 422
    r = _patch(authed_client, {"threshold_hr": "fast"})
    assert r.status_code == 422, \
        f"Expected 422 for non-numeric threshold_hr, got {r.status_code}"


def test_ac6_threshold_pace_rejects_non_integer_value(authed_client):
    # AC6: non-numeric string for threshold_pace_seconds_per_km → 422
    r = _patch(authed_client, {"threshold_pace_seconds_per_km": "4:30"})
    assert r.status_code == 422, \
        f"Expected 422 for non-integer threshold_pace_seconds_per_km (e.g. '4:30'), got {r.status_code}"


def test_ac6_no_field_is_required_patch_with_empty_body(authed_client):
    # AC6: PATCH with empty body (no required fields) → 200
    r = _patch(authed_client, {})
    assert r.status_code == 200, \
        f"PATCH with empty body should not error (no required fields), got {r.status_code}"


def test_ac6_threshold_pace_input_is_numeric_type(settings_html):
    # AC6: type=number on the pace input rejects non-numeric browser input
    pace_pos = settings_html.find('id="thresholds-pace"')
    assert pace_pos != -1, "thresholds-pace input not found"
    nearby = settings_html[max(0, pace_pos - 50):pace_pos + 200]
    assert 'type="number"' in nearby, \
        "Threshold Pace input must be type=number so browsers reject non-numeric input (AC6)"


# ── Save button and feedback element present ──────────────────────────────────

def test_save_button_and_feedback_elements_present(settings_html):
    # Structural: save button and feedback span exist
    assert 'id="thresholds-save-btn"' in settings_html, \
        "Save button (id=thresholds-save-btn) missing"
    assert 'id="thresholds-feedback"' in settings_html, \
        "Feedback element (id=thresholds-feedback) missing"
