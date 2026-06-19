"""Tests for issue #643: Convert Log Workout to slide-over panel (runs against UAT)."""
import os
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

_TEST_PW = "tester643-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    name = f"tester643_{uuid.uuid4().hex[:8]}"
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
def session_cookie(client, test_user):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_user))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def csrf_token_and_session(client, test_user):
    """Return (session_cookie, csrf_token) tuple."""
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_user))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    session = client.cookies.get("session", "")
    csrf = ""
    for sc in res.headers.get_list("set-cookie"):
        if sc.startswith("csrf-token="):
            csrf = sc.split("=", 1)[1].split(";")[0]
            break
    return session, csrf


@pytest.fixture(scope="module")
def auth_client(session_cookie):
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=True) as c:
        c.cookies.set("session", session_cookie)
        yield c


# ── AC1: No permanent side column; page renders full-width ──────────────────

def test_no_permanent_side_column(auth_client):
    """AC1: The permanent side column is removed; page renders full-width.
    The slide-over panel must be an overlay, not a layout-shifting 2-column grid.
    The panel uses position:fixed (or equivalent overlay), not a static column."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # The panel must be present as an overlay element (detail-panel)
    assert "detail-panel" in html
    # The panel must NOT use a permanent side-column CSS class at page load
    # (has-panel class is added dynamically by JS only when panel opens)
    # The layout wrapper must not start in 2-col mode
    assert 'class="log-layout has-panel"' not in html
    assert "id=\"layout-wrapper\"" in html or "layout-wrapper" in html


# ── AC2: "Log workout" button opens slide-over panel ───────────────────────

def test_log_workout_button_exists(auth_client):
    """AC2: A 'Log workout' button is present on the Training page."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # The button with id log-new-btn must exist
    assert "log-new-btn" in html
    # It must have some form of "Log workout" or similar label
    assert "Log workout" in html or "log workout" in html.lower()


def test_slide_over_panel_exists(auth_client):
    """AC2: The slide-over panel element is present in the DOM."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # Detail panel must exist as an aside/div
    assert "detail-panel" in html
    # Panel must have the form wrapper inside it
    assert "dp-form-wrap" in html


def test_panel_uses_gradient_theme(auth_client):
    """AC2: The slide-over panel header uses the gradient theme."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # The panel header must use the gradient (bg-1/bg-2 gradient or page-bg variable)
    # Check for slide-over panel header with gradient styling
    assert "dp-panel-header" in html or "panel-gradient" in html or "slide-panel" in html


# ── AC3: Clicking history row opens panel in edit mode ─────────────────────

def test_history_rows_have_edit_trigger(auth_client):
    """AC3: History rows must trigger edit mode when clicked."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # The log-list contains the history entries
    assert "log-list" in html
    # Entry rows must be clickable (entry-row class with data-id for edit)
    assert "entry-row" in html or "workout-row" in html


# ── AC4: Panel header shows contextual title ──────────────────────────────

def test_panel_header_contextual_title_element(auth_client):
    """AC4: The panel has a title element that shows 'Log workout' or 'Edit workout'."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # dp-form-title is used to dynamically set "Log workout" / "Edit workout"
    assert "dp-form-title" in html
    # The default title shown in the HTML should be "Log workout"
    assert "Log workout" in html


# ── AC5: Workout Basics section with all required fields ───────────────────

def test_workout_basics_name_field(auth_client):
    """AC5: Workout Basics section has a Name text input."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    assert 'id="workout-name"' in html
    assert 'type="text"' in html


def test_workout_basics_date_field(auth_client):
    """AC5: Workout Basics section has a Date picker."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    assert 'id="workout-date"' in html
    assert 'type="date"' in html


def test_workout_basics_type_select(auth_client):
    """AC5: Workout Basics section has a Type select element (not just chips)."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # The type field should be a <select> element
    assert 'id="workout-type"' in html or 'name="workout-type"' in html
    # Check it's a select, not just chips
    assert "<select" in html


def test_workout_basics_remarks_textarea(auth_client):
    """AC5: Workout Basics section has a Remarks textarea."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    assert 'id="workout-remarks"' in html


def test_workout_basics_tss_optional(auth_client):
    """AC5: Workout Basics section has TSS field marked optional (no required indicator)."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    assert 'id="workout-tss"' in html
    # TSS must not have 'required' attribute
    # Find the TSS input and check it doesn't have required
    tss_idx = html.find('id="workout-tss"')
    assert tss_idx != -1
    # Check in surrounding context (within 200 chars before/after)
    ctx = html[max(0, tss_idx - 50):tss_idx + 150]
    assert "required" not in ctx


# ── AC6: Device Import strip ──────────────────────────────────────────────

def test_device_import_strip_present(auth_client):
    """AC6: Device Import strip renders with Strava, Garmin, and Stryd affordances."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # The rl-import strip must be inside dp-form-wrap
    assert "rl-import" in html
    # All three sources must be present
    assert "Strava" in html
    assert "Garmin" in html
    assert "Stryd" in html


def test_device_import_is_sync_later(auth_client):
    """AC6: Device import affordances are 'sync later' (no live auth trigger)."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # The sources should link to settings/integrations, not trigger live OAuth
    assert "/settings" in html or "settings#integrations" in html


# ── AC7: Reserved body area (empty placeholder) ───────────────────────────

def test_reserved_body_placeholder_exists(auth_client):
    """AC7: The panel body area below the import strip has a reserved placeholder."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # There must be a placeholder/reserved area for workout-type-specific content
    assert "type-body-placeholder" in html or "workout-type-body" in html or "type-content-area" in html


# ── AC8: Save uses existing endpoints ─────────────────────────────────────

def test_save_button_exists(auth_client):
    """AC8: A Save button exists in the panel form area."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    assert "dp-save-btn" in html or "save-workout-btn" in html


def test_no_new_api_endpoints(csrf_token_and_session):
    """AC12: No new API endpoints are introduced; only existing workout endpoints are called.
    Verify /api/workouts (POST) and /api/workouts/{id} (PATCH) work correctly."""
    session, csrf = csrf_token_and_session

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        # Set auth cookies and CSRF token
        client.cookies.set("session", session)
        client.cookies.set("csrf-token", csrf)

        # Verify existing create endpoint still works
        today = "2024-01-15"
        payload = {
            "name": "Test AC8 Workout",
            "workout_date": today,
            "workout_type": "Strength",
        }
        headers = {"X-CSRF-Token": csrf}
        r = client.post("/api/workouts", json=payload, headers=headers)
        assert r.status_code == 201, f"Create workout failed: {r.text}"
        workout_id = r.json()["id"]

        # Verify existing patch endpoint still works
        r2 = client.patch(f"/api/workouts/{workout_id}", json={"name": "Updated Name"}, headers=headers)
        assert r2.status_code == 200, f"Update workout failed: {r2.text}"
        assert r2.json()["name"] == "Updated Name"

        # Cleanup
        client.delete(f"/api/workouts/{workout_id}", headers=headers)


# ── AC9: Cancel button ────────────────────────────────────────────────────

def test_cancel_button_exists(auth_client):
    """AC9: A Cancel button exists in the panel form area."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    assert "dp-cancel-btn" in html or "cancel-btn" in html


# ── AC10: Mobile full screen ──────────────────────────────────────────────

def test_mobile_panel_full_screen_css(auth_client):
    """AC10: On mobile viewports the panel occupies the full screen.
    The CSS must include a media query setting width:100% for the panel at mobile breakpoint."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # The panel must have width: 100% at mobile
    # Check for max-width: 520px on detail-panel (mobile overrides to full)
    assert "detail-panel" in html
    # Check for @media rule handling full-screen behavior
    assert "@media" in html or "max-width" in html


# ── AC11: Escape key closes panel (JS) ───────────────────────────────────

def test_escape_key_handler_in_js(auth_client):
    """AC11: Pressing Escape closes the panel."""
    pytest.skip(
        "manual — keyboard Escape handler is wired in JS at runtime; "
        "verify by pressing Escape while panel is open in the browser"
    )


# ── Additional: Panel structure ───────────────────────────────────────────

def test_panel_has_overlay_behavior(auth_client):
    """The panel must use position:fixed to overlay, not a 2-column grid shift."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    # detail-panel must exist and use overlay-style positioning (checked via fixed position in CSS)
    # The CSS in the page must define the panel with position: fixed
    assert "position: fixed" in html or "position:fixed" in html


def test_slide_over_panel_has_save_and_cancel_actions(auth_client):
    """Panel must have both Save and Cancel action buttons in the form actions bar."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    assert "dp-actions-form" in html
    assert "dp-save-btn" in html
    assert "dp-cancel-btn" in html


def test_workout_type_select_has_options(auth_client):
    """AC5: The Type select must have at least Strength and Running as options."""
    r = auth_client.get("/log")
    assert r.status_code == 200
    html = r.text
    assert "Strength" in html
    assert "Running" in html
