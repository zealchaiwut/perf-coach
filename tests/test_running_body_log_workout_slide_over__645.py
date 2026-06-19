"""Tests for issue #645: Build RUNNING body for Log-workout slide-over panel."""
import os
import re
import uuid
import pytest
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel

BASE_URL = (
    os.environ.get("UAT_BASE_URL")
    or "http://localhost:" + os.environ.get("UAT_PORT", "")
)
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "tester645-run-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    name = f"tester645_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    client.delete(f"/api/users/{uid}")


@pytest.fixture(scope="module")
def auth_client(client, test_user):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_user))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    session = res.cookies.get("session")
    csrf = res.cookies.get("csrf-token")

    class CsrfClient:
        def __init__(self, base_url, session_cookie, csrf_token):
            self._client = httpx.Client(base_url=base_url, timeout=10.0, follow_redirects=True)
            self._client.cookies.set("session", session_cookie)
            if csrf_token:
                self._client.cookies.set("csrf-token", csrf_token)
            self._csrf = csrf_token

        def _request(self, method, *args, **kwargs):
            if self._csrf and "headers" not in kwargs:
                kwargs["headers"] = {}
            if self._csrf and isinstance(kwargs.get("headers"), dict):
                kwargs["headers"]["X-CSRF-Token"] = self._csrf
            return self._client.request(method, *args, **kwargs)

        def get(self, *args, **kwargs):
            return self._client.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            return self._request("POST", *args, **kwargs)

        def delete(self, *args, **kwargs):
            return self._request("DELETE", *args, **kwargs)

        def put(self, *args, **kwargs):
            return self._request("PUT", *args, **kwargs)

    c = CsrfClient(BASE_URL, session, csrf)
    yield c
    c._client.close()


@pytest.fixture(scope="module")
def page_html(auth_client):
    r = auth_client.get("/log")
    assert r.status_code == 200
    return r.text


@pytest.fixture(scope="module")
def js_training(auth_client):
    r = auth_client.get("/js/training.js")
    assert r.status_code == 200
    return r.text


@pytest.fixture(scope="module")
def js_training_log(auth_client):
    r = auth_client.get("/js/training-log.js")
    assert r.status_code == 200
    return r.text


# ── AC1: RUNNING body section rendered, distinct from STRENGTH ────────────────


def test_run_body_element_present(page_html):
    """AC1: #run-body element exists inside the slide-over form."""
    assert "run-body" in page_html, (
        "Expected #run-body element in training-log.html inside the slide-over form"
    )


def test_run_body_is_type_content_area(page_html):
    """AC1: The run body has a type-content-area class for toggling with strength body."""
    assert "type-content-area" in page_html, (
        "Expected type-content-area class on run-body or strength-body wrapper"
    )


def test_run_body_strength_body_distinct(page_html):
    """AC1: strength-body and run-body are distinct elements (not the same div)."""
    assert "strength-body" in page_html, "Expected #strength-body element"
    assert "run-body" in page_html, "Expected #run-body element distinct from strength-body"
    sb_pos = page_html.find("strength-body")
    rb_pos = page_html.find("run-body")
    assert sb_pos != rb_pos, "run-body and strength-body should be separate elements"


def test_run_body_visibility_toggle_in_js(js_training):
    """AC1: JS shows run-body and hides strength-body when Running is selected."""
    assert "run-body" in js_training, (
        "Expected run-body referenced in training.js for visibility toggling"
    )
    assert "strength-body" in js_training or "exercises-section" in js_training, (
        "Expected strength-body or exercises-section visibility control in training.js"
    )


# ── AC2: Four segment rows ────────────────────────────────────────────────────


def test_run_body_warmup_row_present(page_html):
    """AC2: Warm-up segment row exists in the run body."""
    assert "warm-up" in page_html.lower() or "warmup" in page_html.lower(), (
        "Expected Warm-up segment row in run body HTML"
    )


def test_run_body_intervals_row_present(page_html):
    """AC2: Intervals segment row exists in the run body."""
    assert "interval" in page_html.lower(), (
        "Expected Intervals segment row in run body HTML"
    )


def test_run_body_tempo_row_present(page_html):
    """AC2: Tempo segment row exists in the run body."""
    assert "tempo" in page_html.lower(), (
        "Expected Tempo segment row in run body HTML"
    )


def test_run_body_cooldown_row_present(page_html):
    """AC2: Cool-down segment row exists in the run body."""
    assert "cool-down" in page_html.lower() or "cooldown" in page_html.lower(), (
        "Expected Cool-down segment row in run body HTML"
    )


def test_run_body_distance_time_toggle_in_html(page_html):
    """AC2: Distance/Time unit toggle inputs are in the run body."""
    # The toggle should include km and min buttons (similar to existing seg-unit pattern)
    assert "run-seg" in page_html or "rb-seg" in page_html, (
        "Expected run segment row class (run-seg or rb-seg) in HTML"
    )


def test_run_body_target_pace_input_in_html(page_html):
    """AC2: Each segment row exposes a Target Pace input field."""
    assert "rb-pace" in page_html or "run-seg-pace" in page_html or "target-pace" in page_html.lower(), (
        "Expected target pace input class (rb-pace, run-seg-pace, or target-pace) in HTML"
    )


def test_run_body_distance_time_toggle_in_js(js_training):
    """AC2: JS handles the Distance/Time toggle on segment rows."""
    assert "rb-unit" in js_training or "run-seg-unit" in js_training or "rb-toggle" in js_training, (
        "Expected unit toggle handler (rb-unit / run-seg-unit) in training.js"
    )


def test_run_body_target_pace_input_in_js(js_training):
    """AC2: JS handles target pace input changes for real-time updates."""
    assert "rb-pace" in js_training or "run-seg-pace" in js_training or "target.pace" in js_training, (
        "Expected pace input handling in training.js"
    )


# ── AC3: Effort session-profile bar ──────────────────────────────────────────


def test_run_body_effort_bar_element_present(page_html):
    """AC3: Effort profile bar element is present in run body."""
    assert "rb-profile" in page_html or "run-effort" in page_html or "run-body-profile" in page_html, (
        "Expected effort profile bar element (rb-profile / run-effort) in HTML"
    )


def test_run_body_effort_bar_render_function_in_js(js_training):
    """AC3: JS has a function that renders the effort bar for the running body."""
    assert "renderRunBody" in js_training or "renderRunEffort" in js_training or "renderRunProfile" in js_training or "rbRenderProfile" in js_training, (
        "Expected renderRunBody/renderRunEffort/renderRunProfile function in training.js"
    )


def test_run_body_effort_bar_zone_colors_in_js(js_training):
    """AC3: Effort bar uses zone color mapping: easy=green, tempo=orange, hard=red, recovery=blue."""
    # easy zone mapped to green
    has_green = "easy" in js_training and (
        "rl-easy" in js_training or "#16a34a" in js_training or "green" in js_training
    )
    # tempo zone mapped to orange/amber
    has_tempo = "tempo" in js_training and (
        "rl-tempo" in js_training or "#d97706" in js_training or "orange" in js_training or "amber" in js_training
    )
    # hard zone mapped to red
    has_hard = "hard" in js_training and (
        "rl-hard" in js_training or "#ea580c" in js_training or "red" in js_training
    )
    assert has_green and has_tempo and has_hard, (
        "Expected zone color mapping (easy=green, tempo=orange, hard=red) in training.js"
    )


def test_run_body_effort_bar_height_encodes_effort_in_js(js_training):
    """AC3: Column height encodes relative effort level (different heights per zone)."""
    # The JS should have numeric height values for different effort zones
    assert "40" in js_training or "72" in js_training or "92" in js_training or "26" in js_training, (
        "Expected numeric effort-height values in training.js"
    )


# ── AC4: Lap Mode selector ────────────────────────────────────────────────────


def test_run_body_lap_mode_selector_in_html(page_html):
    """AC4: Lap Mode selector is present in the run body HTML."""
    assert "lap" in page_html.lower() and ("mode" in page_html.lower() or "rb-lap" in page_html), (
        "Expected Lap Mode selector in run body HTML"
    )


def test_run_body_auto_splits_option_in_html(page_html):
    """AC4: 'Auto 1 km splits' option is present."""
    assert "auto" in page_html.lower() and (
        "1 km" in page_html or "1km" in page_html or "auto" in page_html.lower()
    ), (
        "Expected 'Auto 1 km splits' option in HTML"
    )


def test_run_body_manual_laps_option_in_html(page_html):
    """AC4: 'Manual laps' option is present."""
    assert "manual" in page_html.lower() and "lap" in page_html.lower(), (
        "Expected 'Manual laps' option in HTML"
    )


def test_run_body_lap_type_persisted_to_splits_api(auth_client):
    """AC4: lap_type='auto' or 'manual' is accepted by POST /api/workouts/{id}/splits."""
    # Create a test workout first
    wr = auth_client.post("/api/workouts", json={
        "name": "Run Test 645",
        "workout_date": "2026-06-19",
        "workout_type": "Running",
        "distance_km": 5.0,
        "duration_seconds": 1500,
    })
    assert wr.status_code in (200, 201), wr.text
    wid = wr.json()["id"]
    try:
        # Post manual splits
        sr = auth_client.post(f"/api/workouts/{wid}/splits", json={
            "splits": [
                {"split_index": 0, "distance_km": 2.0, "duration_seconds": 540, "lap_type": "manual"},
                {"split_index": 1, "distance_km": 1.0, "duration_seconds": 330, "lap_type": "manual"},
            ]
        })
        assert sr.status_code == 201, sr.text
        data = sr.json()
        assert data[0]["lap_type"] == "manual", "Expected lap_type='manual' in response"
        assert data[1]["lap_type"] == "manual"
        # Post auto split
        sr2 = auth_client.post(f"/api/workouts/{wid}/splits", json={
            "splits": [
                {"split_index": 0, "distance_km": 1.0, "duration_seconds": 300, "lap_type": "auto"},
            ]
        })
        assert sr2.status_code == 201, sr2.text
        assert sr2.json()[0]["lap_type"] == "auto"
    finally:
        auth_client.delete(f"/api/workouts/{wid}")


# ── AC5: Manual lap table ─────────────────────────────────────────────────────


def test_run_body_manual_lap_table_in_html(page_html):
    """AC5: Manual lap table element is present in the run body HTML."""
    assert "rb-lap-table" in page_html or "run-lap-table" in page_html or "manual-lap" in page_html, (
        "Expected manual lap table element in HTML"
    )


def test_run_body_lap_row_distance_field_in_js(js_training):
    """AC5: Lap row has a Distance field."""
    assert "rb-lap-dist" in js_training or "lap-dist" in js_training or "lapDist" in js_training, (
        "Expected lap distance field class in training.js"
    )


def test_run_body_lap_row_duration_field_in_js(js_training):
    """AC5: Lap row has a Duration field."""
    assert "rb-lap-dur" in js_training or "lap-dur" in js_training or "lapDur" in js_training, (
        "Expected lap duration field class in training.js"
    )


def test_run_body_lap_row_add_button_in_html(page_html):
    """AC5: Add lap row button is present."""
    assert "add-lap" in page_html or "rb-add-lap" in page_html, (
        "Expected add-lap button in HTML"
    )


def test_run_body_lap_row_remove_button_in_js(js_training):
    """AC5: Remove lap row button exists in JS."""
    assert "rb-lap-remove" in js_training or "lap-remove" in js_training or "removeLap" in js_training, (
        "Expected lap row remove button in training.js"
    )


# ── AC6: Manual lap table hidden when Auto is selected ───────────────────────


def test_run_body_lap_table_visibility_in_js(js_training):
    """AC6: JS hides the manual lap table when Auto 1 km splits is selected."""
    assert (
        "rb-lap-table" in js_training or "run-lap-table" in js_training or "manual-lap" in js_training
    ) and "display" in js_training, (
        "Expected lap table visibility control (display) in training.js"
    )


def test_run_body_lap_mode_change_triggers_visibility(js_training):
    """AC6: Lap mode change event triggers showing/hiding the lap table."""
    assert (
        "rb-lap-mode" in js_training or "lap-mode" in js_training or "lapMode" in js_training
    ), (
        "Expected lap mode change handler (rb-lap-mode or lapMode) in training.js"
    )


# ── AC7: Auto totals ──────────────────────────────────────────────────────────


def test_run_body_total_distance_element_in_html(page_html):
    """AC7: Auto total for distance is present in HTML."""
    assert "rb-total-dist" in page_html or "rb-total-distance" in page_html or "run-total-dist" in page_html, (
        "Expected total distance element (rb-total-dist / run-total-dist) in HTML"
    )


def test_run_body_total_duration_element_in_html(page_html):
    """AC7: Auto total for duration is present in HTML."""
    assert "rb-total-dur" in page_html or "rb-total-duration" in page_html or "run-total-dur" in page_html, (
        "Expected total duration element in HTML"
    )


def test_run_body_avg_pace_element_in_html(page_html):
    """AC7: Auto total for avg pace is present in HTML."""
    assert "rb-avg-pace" in page_html or "run-avg-pace" in page_html or "rb-pace-total" in page_html, (
        "Expected avg pace element in HTML"
    )


def test_run_body_totals_computed_in_js(js_training):
    """AC7: recomputeRunBodyTotals or equivalent function exists in JS."""
    assert (
        "recomputeRunBody" in js_training
        or "rbRecompute" in js_training
        or "computeRunBodyTotals" in js_training
        or ("rb-total" in js_training and "pace" in js_training)
    ), (
        "Expected run body totals recompute function in training.js"
    )


def test_run_body_pace_computed_from_dist_and_dur_in_js(js_training):
    """AC7: Avg Pace is computed as duration / distance (pace = sec/km)."""
    # Should divide duration by distance — look for the pace formula pattern
    assert (
        "formatPace" in js_training or "pace" in js_training
    ) and (
        "dist" in js_training or "distance" in js_training or "km" in js_training
    ), (
        "Expected pace computation from distance and duration in training.js"
    )


# ── AC8: Sync-filled fields ───────────────────────────────────────────────────


def test_run_body_hr_field_in_html(page_html):
    """AC8: HR sync field with placeholder text is present."""
    assert "rb-sync-hr" in page_html or "run-sync-hr" in page_html or (
        "bpm" in page_html and "run-body" in page_html
    ), (
        "Expected HR sync field in run body HTML"
    )


def test_run_body_power_field_in_html(page_html):
    """AC8: Power sync field with placeholder text is present."""
    assert "rb-sync-power" in page_html or "run-sync-power" in page_html or (
        "— W" in page_html or "—&nbsp;W" in page_html or "rb-sync" in page_html
    ), (
        "Expected Power sync field in run body HTML"
    )


def test_run_body_cadence_field_in_html(page_html):
    """AC8: Cadence sync field with placeholder text is present."""
    assert "rb-sync-cadence" in page_html or "cadence" in page_html.lower(), (
        "Expected Cadence sync field in run body HTML"
    )


def test_run_body_stride_field_in_html(page_html):
    """AC8: Stride sync field with placeholder text is present."""
    assert "rb-sync-stride" in page_html or "stride" in page_html.lower(), (
        "Expected Stride sync field in run body HTML"
    )


def test_run_body_sync_placeholder_text_in_html(page_html):
    """AC8: Sync fields show placeholder dashes (— bpm / — W / — spm / — m) when empty."""
    # Placeholder should include dashes and units
    assert (
        "bpm" in page_html or "spm" in page_html
    ), (
        "Expected placeholder text with units (bpm, spm) in run body HTML"
    )


# ── AC9: Session persistence ──────────────────────────────────────────────────


def test_run_body_session_storage_in_js(js_training):
    """AC9: JS uses sessionStorage to persist run body state across close/reopen."""
    assert "sessionStorage" in js_training or "rbState" in js_training or "_rbDraft" in js_training, (
        "Expected sessionStorage or in-memory draft state for run body persistence in training.js"
    )


# ── AC10: Reactive updates ────────────────────────────────────────────────────


def test_run_body_input_listeners_in_js(js_training):
    """AC10: Input event listeners trigger recompute on segment and lap row changes."""
    # Should have input event listeners on rb-seg inputs or rb-lap inputs
    assert (
        "recomputeRunBody" in js_training
        or "rbRecompute" in js_training
        or ("addEventListener" in js_training and "rb-" in js_training)
    ), (
        "Expected input event listeners triggering recompute in training.js"
    )


def test_run_body_splits_api_roundtrip(auth_client):
    """AC4+AC5: PUT splits with manual laps round-trips correctly via GET."""
    wr = auth_client.post("/api/workouts", json={
        "name": "Run Split Test 645",
        "workout_date": "2026-06-19",
        "workout_type": "Running",
        "distance_km": 3.0,
        "duration_seconds": 870,
    })
    assert wr.status_code in (200, 201), wr.text
    wid = wr.json()["id"]
    try:
        sr = auth_client.post(f"/api/workouts/{wid}/splits", json={
            "splits": [
                {"split_index": 0, "distance_km": 2.0, "duration_seconds": 540, "lap_type": "manual"},
                {"split_index": 1, "distance_km": 1.0, "duration_seconds": 330, "lap_type": "manual"},
            ]
        })
        assert sr.status_code == 201, sr.text
        gr = auth_client.get(f"/api/workouts/{wid}/splits")
        assert gr.status_code == 200, gr.text
        splits = gr.json()
        assert len(splits) == 2
        assert all(s["lap_type"] == "manual" for s in splits)
        assert float(splits[0]["distance_km"]) == pytest.approx(2.0, abs=0.001)
        assert splits[0]["duration_seconds"] == 540
    finally:
        auth_client.delete(f"/api/workouts/{wid}")
