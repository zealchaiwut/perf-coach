"""Tests for issue #658: Fix baseline drift after clearing a thresholds field in Settings.

Bug: After PATCH sends null for a cleared field, _tBaseline was updated with the
system default (via `saved.X != null ? saved.X : defs.X`) instead of null.
This caused every subsequent 'Save' to re-fire a PATCH for that field even when
nothing had changed, bypassing the 'No changes to save' short-circuit.

Affected fields (4 of the 7): max_hr, zone2_hr_min, zone2_hr_max,
weekly_zone2_target_min. ftp_w, threshold_hr, threshold_pace_seconds_per_km
were already corrected.

Fix: Store saved.X directly (no fallback to defs.X) in the post-save
_tBaseline update block for all seven fields.

ACs:
  AC1 - settings.html does not contain the fallback pattern for max_hr
  AC2 - settings.html does not contain the fallback pattern for zone2_hr_min
  AC3 - settings.html does not contain the fallback pattern for zone2_hr_max
  AC4 - settings.html does not contain the fallback pattern for weekly_zone2_target_min
  AC5 - PATCH max_hr=null round-trips as null via GET
  AC6 - PATCH zone2_hr_min=null round-trips as null via GET
  AC7 - PATCH zone2_hr_max=null round-trips as null via GET
  AC8 - PATCH weekly_zone2_target_min=null round-trips as null via GET
  AC9 - ftp_w baseline fix remains: PATCH ftp_w=null round-trips as null
  AC10- threshold_hr baseline fix remains: PATCH threshold_hr=null round-trips as null
  AC11- threshold_pace baseline fix remains: PATCH threshold_pace_seconds_per_km=null
        round-trips as null

JS-only runtime behavior (actual _tBaseline update, no-redundant-PATCH check) is
marked manual-skip — these cannot be tested via HTTP.

Server: http://127.0.0.1:9001
"""
import uuid
import re

import httpx
import pytest

from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = "http://127.0.0.1:9001"
_TEST_PASSWORD = "Perf658testPw!"

SETTINGS_HTML_PATH = "frontend/pages/settings.html"


@pytest.fixture(scope="module")
def settings_html_source():
    with open(SETTINGS_HTML_PATH, "r") as f:
        return f.read()


@pytest.fixture(scope="module")
def authed_client():
    username = f"tester658_{uuid.uuid4().hex[:8]}"
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


def _patch(client, payload):
    csrf = getattr(client, "_csrf", "")
    return client.patch(
        "/api/user-preferences",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )


def _get_prefs(client):
    return client.get("/api/user-preferences")


# ── AC1-AC4: Static source checks — no defs fallback in _tBaseline post-save block ──

def test_658__ac1_max_hr_no_defs_fallback_in_baseline(settings_html_source):
    # AC1: the post-save _tBaseline update must NOT use `defs.max_hr` as fallback
    # The buggy pattern was: `max_hr: saved.max_hr != null ? saved.max_hr : defs.max_hr`
    assert "saved.max_hr != null ? saved.max_hr : defs.max_hr" not in settings_html_source, (
        "Bug present: max_hr still falls back to defs.max_hr in _tBaseline post-save block. "
        "Use `max_hr: saved.max_hr` directly."
    )


def test_658__ac2_zone2_hr_min_no_defs_fallback_in_baseline(settings_html_source):
    # AC2: zone2_hr_min must not fall back to defs.zone2_hr_min in _tBaseline post-save
    assert "saved.zone2_hr_min != null ? saved.zone2_hr_min : defs.zone2_hr_min" not in settings_html_source, (
        "Bug present: zone2_hr_min still falls back to defs.zone2_hr_min in _tBaseline post-save block."
    )


def test_658__ac3_zone2_hr_max_no_defs_fallback_in_baseline(settings_html_source):
    # AC3: zone2_hr_max must not fall back to defs.zone2_hr_max in _tBaseline post-save
    assert "saved.zone2_hr_max != null ? saved.zone2_hr_max : defs.zone2_hr_max" not in settings_html_source, (
        "Bug present: zone2_hr_max still falls back to defs.zone2_hr_max in _tBaseline post-save block."
    )


def test_658__ac4_weekly_zone2_no_defs_fallback_in_baseline(settings_html_source):
    # AC4: weekly_zone2_target_min must not fall back to defs.weekly_zone2_target_min in _tBaseline
    assert (
        "saved.weekly_zone2_target_min != null ? saved.weekly_zone2_target_min : defs.weekly_zone2_target_min"
        not in settings_html_source
    ), (
        "Bug present: weekly_zone2_target_min still falls back to defs.weekly_zone2_target_min "
        "in _tBaseline post-save block."
    )


# ── AC5-AC8: API round-trip: PATCH null → GET returns null for affected fields ──

def test_658__ac5_patch_max_hr_null_round_trips(authed_client):
    # AC5: PATCH max_hr=185, then PATCH max_hr=null → GET row.max_hr is null
    _patch(authed_client, {"max_hr": 185})
    r = _patch(authed_client, {"max_hr": None})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("max_hr") is None, f"max_hr should be null after clear: {r.json()}"
    get_r = _get_prefs(authed_client)
    assert get_r.json()["row"]["max_hr"] is None, (
        f"GET row.max_hr should be null after PATCH null: {get_r.json()['row']}"
    )


def test_658__ac6_patch_zone2_hr_min_null_round_trips(authed_client):
    # AC6: PATCH zone2_hr_min=135, then PATCH zone2_hr_min=null → GET row.zone2_hr_min is null
    _patch(authed_client, {"zone2_hr_min": 135})
    r = _patch(authed_client, {"zone2_hr_min": None})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("zone2_hr_min") is None, f"zone2_hr_min should be null: {r.json()}"
    get_r = _get_prefs(authed_client)
    assert get_r.json()["row"]["zone2_hr_min"] is None, (
        f"GET row.zone2_hr_min should be null after PATCH null: {get_r.json()['row']}"
    )


def test_658__ac7_patch_zone2_hr_max_null_round_trips(authed_client):
    # AC7: PATCH zone2_hr_max=160, then PATCH zone2_hr_max=null → GET row.zone2_hr_max is null
    _patch(authed_client, {"zone2_hr_max": 160})
    r = _patch(authed_client, {"zone2_hr_max": None})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("zone2_hr_max") is None, f"zone2_hr_max should be null: {r.json()}"
    get_r = _get_prefs(authed_client)
    assert get_r.json()["row"]["zone2_hr_max"] is None, (
        f"GET row.zone2_hr_max should be null after PATCH null: {get_r.json()['row']}"
    )


def test_658__ac8_patch_weekly_zone2_target_null_round_trips(authed_client):
    # AC8: PATCH weekly_zone2_target_min=200, then null → GET row.weekly_zone2_target_min is null
    _patch(authed_client, {"weekly_zone2_target_min": 200})
    r = _patch(authed_client, {"weekly_zone2_target_min": None})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("weekly_zone2_target_min") is None, (
        f"weekly_zone2_target_min should be null: {r.json()}"
    )
    get_r = _get_prefs(authed_client)
    assert get_r.json()["row"]["weekly_zone2_target_min"] is None, (
        f"GET row.weekly_zone2_target_min should be null after PATCH null: {get_r.json()['row']}"
    )


# ── AC9-AC11: Confirm the already-fixed fields remain correct ────────────────

def test_658__ac9_patch_ftp_w_null_round_trips(authed_client):
    # AC9: regression guard — ftp_w was already fixed and must stay correct
    _patch(authed_client, {"ftp_w": 300})
    r = _patch(authed_client, {"ftp_w": None})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("ftp_w") is None, f"ftp_w should be null after clear: {r.json()}"
    get_r = _get_prefs(authed_client)
    assert get_r.json()["row"]["ftp_w"] is None


def test_658__ac10_patch_threshold_hr_null_round_trips(authed_client):
    # AC10: regression guard — threshold_hr was already fixed
    _patch(authed_client, {"threshold_hr": 165})
    r = _patch(authed_client, {"threshold_hr": None})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("threshold_hr") is None, f"threshold_hr should be null: {r.json()}"
    get_r = _get_prefs(authed_client)
    assert get_r.json()["row"]["threshold_hr"] is None


def test_658__ac11_patch_threshold_pace_null_round_trips(authed_client):
    # AC11: regression guard — threshold_pace_seconds_per_km was already fixed
    _patch(authed_client, {"threshold_pace_seconds_per_km": 260})
    r = _patch(authed_client, {"threshold_pace_seconds_per_km": None})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("threshold_pace_seconds_per_km") is None, (
        f"threshold_pace_seconds_per_km should be null: {r.json()}"
    )
    get_r = _get_prefs(authed_client)
    assert get_r.json()["row"]["threshold_pace_seconds_per_km"] is None


# ── JS-only ACs (cannot be HTTP-tested) ─────────────────────────────────────

def test_658__js_baseline_stays_null_after_clear_save():
    # After a cleared-field save, _tBaseline stores null (not defs fallback) — JS only
    pytest.skip("manual — _tBaseline update is client-side JS, cannot be HTTP-tested")


def test_658__js_no_redundant_patch_after_clear_save():
    # No spurious PATCH fired on subsequent save when nothing changed — JS only
    pytest.skip("manual — redundant-PATCH detection requires network inspector, not HTTP test")
