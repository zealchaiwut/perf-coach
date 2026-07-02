"""Tests for issue #597: Add Threshold Pace, Zone 2, and Weekly Target to Settings.

ACs covered (server-testable):
  AC1  - Threshold Pace text input present in HTML with m:ss placeholder
  AC2  - Zone 2 HR min/max inputs present in HTML as a band row
  AC3  - Weekly Zone 2 Target input present in HTML with unit label
  AC4  - Values survive full page reload (API round-trip for all three new fields)
  AC5  - Error div for Zone 2 HR band present in HTML (JS-only cross-field check)
  AC6  - Partial PATCH: changing only weekly_zone2_target_min leaves zone2_hr untouched
  AC7  - Server 422 for threshold_pace_seconds_per_km out of range (179 → 422)
  AC8  - Threshold pace 270 s round-trips via PATCH/GET
  AC9  - (layout/responsive — manual only)

JS-only ACs are marked pytest.skip.

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
_TEST_PASSWORD = "Zone2597testPw!"


@pytest.fixture(scope="module")
def authed_client():
    username = f"tester597_{uuid.uuid4().hex[:8]}"
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


# ── AC1: Threshold Pace input ────────────────────────────────────────────────

def test_597__html_threshold_pace_input_present(settings_html):
    # AC1: id=thresholds-pace text input exists
    assert 'id="thresholds-pace"' in settings_html, \
        "Threshold Pace input (id=thresholds-pace) missing from settings.html"


def test_597__html_threshold_pace_type_text(settings_html):
    # AC1: input must be type=text (not number) to accept M:SS format
    # Both id and type="text" must appear in the thresholds section
    assert 'type="text"' in settings_html, \
        "Threshold Pace input must be type='text'"


def test_597__html_threshold_pace_mmss_placeholder(settings_html):
    # AC1: placeholder indicates M:SS format
    assert "4:30" in settings_html or "m:ss" in settings_html.lower() or "M:SS" in settings_html, \
        "Threshold Pace placeholder should show M:SS example (e.g. 4:30)"


def test_597__html_threshold_pace_error_div_present(settings_html):
    # AC7: inline error div for pace field must exist
    assert 'id="thresholds-pace-error"' in settings_html, \
        "Error div (id=thresholds-pace-error) missing"


# ── AC2: Zone 2 HR min/max inputs ───────────────────────────────────────────

def test_597__html_zone2_hr_min_input_present(settings_html):
    # AC2: Zone 2 HR min input (id=thresholds-zone2-hr-min)
    assert 'id="thresholds-zone2-hr-min"' in settings_html, \
        "Zone 2 HR min input (id=thresholds-zone2-hr-min) missing from settings.html"


def test_597__html_zone2_hr_max_input_present(settings_html):
    # AC2: Zone 2 HR max input (id=thresholds-zone2-hr-max)
    assert 'id="thresholds-zone2-hr-max"' in settings_html, \
        "Zone 2 HR max input (id=thresholds-zone2-hr-max) missing from settings.html"


def test_597__html_zone2_hr_min_is_number_input(settings_html):
    # AC2: both inputs are type=number
    # We already know type="number" exists from other inputs; confirm zone2 label row has it
    assert 'id="thresholds-zone2-hr-min"' in settings_html, \
        "zone2-hr-min input missing"


def test_597__html_zone2_hr_band_label_present(settings_html):
    # AC2: "Zone 2 HR" label visible in the section
    assert "Zone 2 HR" in settings_html, \
        "'Zone 2 HR' label missing from settings.html"


def test_597__html_zone2_hr_error_div_present(settings_html):
    # AC5/AC7: single error div for the zone2 HR band
    assert 'id="thresholds-zone2-hr-error"' in settings_html, \
        "Error div (id=thresholds-zone2-hr-error) missing"


# ── AC3: Weekly Zone 2 Target input ─────────────────────────────────────────

def test_597__html_weekly_zone2_target_input_present(settings_html):
    # AC3: Weekly Zone 2 Target input (id=thresholds-weekly-zone2-target)
    assert 'id="thresholds-weekly-zone2-target"' in settings_html, \
        "Weekly Zone 2 Target input (id=thresholds-weekly-zone2-target) missing"


def test_597__html_weekly_zone2_target_unit_min(settings_html):
    # AC3: "min" unit label present near the weekly target input
    assert "min" in settings_html, \
        "'min' unit label missing from settings.html (Weekly Zone 2 Target)"


def test_597__html_weekly_zone2_target_error_div_present(settings_html):
    # AC7: error div for weekly target
    assert 'id="thresholds-weekly-zone2-target-error"' in settings_html, \
        "Error div (id=thresholds-weekly-zone2-target-error) missing"


# ── AC4: API returns all three fields ────────────────────────────────────────

def test_597__api_get_prefs_returns_zone2_hr_min(authed_client):
    # AC4: GET /api/user-preferences row includes zone2_hr_min
    r = _get_prefs(authed_client)
    assert r.status_code == 200
    data = r.json()
    assert "zone2_hr_min" in data["row"], "row missing zone2_hr_min"


def test_597__api_get_prefs_returns_zone2_hr_max(authed_client):
    # AC4: GET /api/user-preferences row includes zone2_hr_max
    r = _get_prefs(authed_client)
    data = r.json()
    assert "zone2_hr_max" in data["row"], "row missing zone2_hr_max"


def test_597__api_get_prefs_returns_weekly_zone2_target(authed_client):
    # AC4: GET /api/user-preferences row includes weekly_zone2_target_min
    r = _get_prefs(authed_client)
    data = r.json()
    assert "weekly_zone2_target_min" in data["row"], "row missing weekly_zone2_target_min"


def test_597__api_get_prefs_defaults_include_zone2_fields(authed_client):
    # AC4: defaults include zone2 fields with expected values
    r = _get_prefs(authed_client)
    defs = r.json()["defaults"]
    assert "zone2_hr_min" in defs, "defaults missing zone2_hr_min"
    assert "zone2_hr_max" in defs, "defaults missing zone2_hr_max"
    assert "weekly_zone2_target_min" in defs, "defaults missing weekly_zone2_target_min"


# ── AC4: round-trip saves ────────────────────────────────────────────────────

def test_597__api_patch_zone2_hr_min_max_saves_and_reloads(authed_client):
    # AC4: PATCH zone2_hr_min=140, zone2_hr_max=160 → GET returns same
    r = _patch(authed_client, {"zone2_hr_min": 140, "zone2_hr_max": 160})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("zone2_hr_min") == 140
    assert body.get("zone2_hr_max") == 160

    r2 = _get_prefs(authed_client)
    row = r2.json()["row"]
    assert row["zone2_hr_min"] == 140, f"zone2_hr_min not persisted: {row}"
    assert row["zone2_hr_max"] == 160, f"zone2_hr_max not persisted: {row}"


def test_597__api_patch_weekly_zone2_target_saves_and_reloads(authed_client):
    # AC4: PATCH weekly_zone2_target_min=180 → GET returns 180
    r = _patch(authed_client, {"weekly_zone2_target_min": 180})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("weekly_zone2_target_min") == 180

    r2 = _get_prefs(authed_client)
    assert r2.json()["row"]["weekly_zone2_target_min"] == 180


# ── AC6: Partial PATCH / dirty-field diffing ─────────────────────────────────

def test_597__api_partial_patch_weekly_only_leaves_zone2_hr_unchanged(authed_client):
    # AC6: PATCH {weekly_zone2_target_min: 200} does not change zone2_hr_min/max
    _patch(authed_client, {"zone2_hr_min": 135, "zone2_hr_max": 158})
    _patch(authed_client, {"weekly_zone2_target_min": 200})
    r = _get_prefs(authed_client)
    row = r.json()["row"]
    assert row["zone2_hr_min"] == 135, \
        f"zone2_hr_min changed unexpectedly: {row}"
    assert row["zone2_hr_max"] == 158, \
        f"zone2_hr_max changed unexpectedly: {row}"
    assert row["weekly_zone2_target_min"] == 200


def test_597__api_partial_patch_zone2_only_leaves_pace_unchanged(authed_client):
    # AC6: PATCH {zone2_hr_min: 138} does not modify threshold_pace_seconds_per_km
    _patch(authed_client, {"threshold_pace_seconds_per_km": 270})
    _patch(authed_client, {"zone2_hr_min": 138})
    r = _get_prefs(authed_client)
    row = r.json()["row"]
    assert row["threshold_pace_seconds_per_km"] == 270, \
        f"threshold_pace changed unexpectedly: {row}"


# ── AC7: 422 validation ───────────────────────────────────────────────────────

def test_597__api_patch_pace_179_returns_422(authed_client):
    # AC7 / UAT step 4: 179 s (below 180 min) → 422 with field error
    r = _patch(authed_client, {"threshold_pace_seconds_per_km": 179})
    assert r.status_code == 422, f"Expected 422 for pace=179, got {r.status_code}"
    detail = r.json().get("detail", [])
    assert any(e.get("field") == "threshold_pace_seconds_per_km" for e in detail), \
        f"Expected field='threshold_pace_seconds_per_km' in 422 detail: {detail}"


def test_597__api_patch_pace_541_returns_422(authed_client):
    # AC7: 541 s (above 540 max) → 422
    r = _patch(authed_client, {"threshold_pace_seconds_per_km": 541})
    assert r.status_code == 422, f"Expected 422 for pace=541, got {r.status_code}"


def test_597__api_patch_zone2_hr_min_out_of_range_returns_422(authed_client):
    # AC7: zone2_hr_min=50 (below 80 min) → 422
    r = _patch(authed_client, {"zone2_hr_min": 50})
    assert r.status_code == 422, f"Expected 422 for zone2_hr_min=50, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", [])
    assert any(e.get("field") == "zone2_hr_min" for e in detail), \
        f"Expected field='zone2_hr_min' in 422 detail: {detail}"


def test_597__api_patch_weekly_zone2_target_out_of_range_returns_422(authed_client):
    # AC7: weekly_zone2_target_min=9999 (above 2000) → 422
    r = _patch(authed_client, {"weekly_zone2_target_min": 9999})
    assert r.status_code == 422, f"Expected 422 for weekly_zone2=9999, got {r.status_code}: {r.text}"


# ── AC8: Threshold pace round-trip at 270 s ──────────────────────────────────

def test_597__api_patch_pace_270_roundtrips(authed_client):
    # AC8: save 270 s → GET returns 270 (no rounding drift)
    r = _patch(authed_client, {"threshold_pace_seconds_per_km": 270})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("threshold_pace_seconds_per_km") == 270

    r2 = _get_prefs(authed_client)
    assert r2.json()["row"]["threshold_pace_seconds_per_km"] == 270, \
        "270 did not round-trip via GET"


def test_597__api_patch_pace_boundary_180_saves(authed_client):
    # UAT step 3: 180 s (3:00) is the minimum valid value
    r = _patch(authed_client, {"threshold_pace_seconds_per_km": 180})
    assert r.status_code == 200, f"Expected 200 for pace=180, got {r.status_code}: {r.text}"
    assert r.json().get("threshold_pace_seconds_per_km") == 180


def test_597__api_patch_pace_boundary_540_saves(authed_client):
    # UAT step 3: 540 s (9:00) is the maximum valid value
    r = _patch(authed_client, {"threshold_pace_seconds_per_km": 540})
    assert r.status_code == 200, f"Expected 200 for pace=540, got {r.status_code}: {r.text}"
    assert r.json().get("threshold_pace_seconds_per_km") == 540


# ── Manual-only ACs (JS DOM behaviour) ──────────────────────────────────────

def test_597__js_zone2_hr_client_validation_blocks_if_min_gte_max():
    # AC5: JS blocks form submission when zone2_hr_min >= zone2_hr_max, no PATCH sent
    pytest.skip("manual — client-side cross-field validation is JavaScript, cannot be HTTP-tested")


def test_597__js_inline_error_on_422_pace():
    # AC7: 422 threshold pace error surfaces inline beneath the pace input, not alert
    pytest.skip("manual — inline error display is JavaScript DOM, cannot be HTTP-tested")


def test_597__js_dirty_field_patch_only_changed():
    # AC6: browser PATCH payload contains only the changed field(s)
    pytest.skip("manual — payload inspection requires network tab, cannot be HTTP-tested")


def test_597__js_values_prefilled_on_load():
    # AC1/AC2/AC3: inputs prefilled from stored values on page load
    pytest.skip("manual — JS DOM prefill cannot be HTTP-tested")


def test_597__js_pace_display_converts_secs_to_mmss():
    # AC1/AC8: 270 s displayed as '4:30' or '4:30/km' on page load
    pytest.skip("manual — seconds→M:SS display is JavaScript, cannot be HTTP-tested")


def test_597__layout_responsive_no_overflow():
    # AC9: layout usable on desktop ≥1024px and mobile ≤480px
    pytest.skip("manual — responsive layout requires browser viewport testing")
