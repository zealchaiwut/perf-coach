"""TDD tests for issue #361: Build Profile Section in Settings Page.

AC anchors:
  (a)  Profile section div present and populated with form fields
  (b)  Display name field: text input with placeholder from users.name
  (c)  Email field: read-only input
  (d)  Timezone dropdown has exactly the 9 required options
  (e)  Week starts on dropdown: Monday (1) and Sunday (7)
  (f)  GET /api/user-preferences returns user_name and user_email
  (g)  PATCH /api/user-preferences uses session auth — no user_id in body
  (h)  PATCH with only changed fields returns updated prefs
  (i)  PATCH with invalid timezone returns 422 with field info
  (j)  No avatar upload UI present
  (k)  Avatar section contains deferred comment
  (l)  Avatar circle element present for initials display
  (m)  Save button present and initially disabled
  (n)  Per-field error feedback element present
  (o)  users.email column exists in DB schema
"""
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import (
    create_session_cookie,
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.db import engine
from backend.main import app, resolve_user
from backend.models import User

_SETTINGS_HTML = Path(__file__).parent.parent / "frontend" / "pages" / "settings.html"
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


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_mock_user(uid: str | None = None) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = uid or "00000000-0000-0000-0000-000000000361"
    u.name = "test361user"
    u.email = None
    return u


def _client_with_session(mock_user: MagicMock) -> TestClient:
    """Return a TestClient that bypasses session auth via dependency override."""
    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    token = create_session_cookie(str(mock_user.id), time.time())
    csrf = generate_csrf_token()
    return TestClient(
        app,
        cookies={COOKIE_NAME: token, CSRF_COOKIE_NAME: csrf},
        headers={"X-CSRF-Token": csrf},
    )


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


@pytest.fixture(scope="module")
def settings_html() -> str:
    return _SETTINGS_HTML.read_text()


# ── (a) Profile section div populated with form fields ────────────────────────


def test_a_profile_section_has_display_name_input(settings_html):
    """AC (a/b): settings.html has a text input for display_name."""
    assert "profile-display-name" in settings_html or 'name="display_name"' in settings_html, (
        "Profile section must have a display_name input element"
    )


def test_a_profile_section_has_email_input(settings_html):
    """AC (a/c): settings.html has an email input field."""
    assert "profile-email" in settings_html, (
        "Profile section must have an email input element with id profile-email"
    )


def test_a_profile_section_has_timezone_select(settings_html):
    """AC (a/d): settings.html has a timezone select element."""
    assert "profile-timezone" in settings_html, (
        "Profile section must have a timezone select element with id profile-timezone"
    )


def test_a_profile_section_has_week_start_select(settings_html):
    """AC (a/e): settings.html has a week_start_day select element."""
    assert "profile-week-start" in settings_html, (
        "Profile section must have a week_start_day select element with id profile-week-start"
    )


# ── (b) Display name field attributes ────────────────────────────────────────


def test_b_display_name_is_text_input(settings_html):
    """AC (b): display_name input is type='text'."""
    idx = settings_html.find("profile-display-name")
    assert idx != -1, "profile-display-name not found"
    snippet = settings_html[max(0, idx - 200):idx + 200]
    assert 'type="text"' in snippet or "type='text'" in snippet, (
        "display_name input must be type text"
    )


# ── (c) Email field read-only ─────────────────────────────────────────────────


def test_c_email_field_is_readonly(settings_html):
    """AC (c): email input has readonly attribute."""
    idx = settings_html.find("profile-email")
    assert idx != -1, "profile-email not found"
    snippet = settings_html[max(0, idx - 200):idx + 300]
    assert "readonly" in snippet.lower(), "email input must have readonly attribute"


# ── (d) Timezone dropdown — exactly 9 options ─────────────────────────────────


def test_d_timezone_dropdown_has_all_required_options(settings_html):
    """AC (d): Timezone select contains all 9 required timezone values."""
    for tz in _REQUIRED_TIMEZONES:
        assert tz in settings_html, f"Timezone option missing: {tz}"


def test_d_timezone_dropdown_has_asia_bangkok_first(settings_html):
    """AC (d): Asia/Bangkok appears first (it is the default)."""
    idx_tz_select = settings_html.find("profile-timezone")
    assert idx_tz_select != -1
    # Search the full HTML after the select for ordering
    chunk = settings_html[idx_tz_select:idx_tz_select + 1200]
    pos_bangkok = chunk.find("Asia/Bangkok")
    pos_sydney = chunk.find("Australia/Sydney")
    assert pos_bangkok != -1, "Asia/Bangkok not found near profile-timezone select"
    assert pos_sydney != -1, "Australia/Sydney not found near profile-timezone select"
    assert pos_bangkok < pos_sydney, "Asia/Bangkok must appear before Australia/Sydney"


# ── (e) Week starts on dropdown ───────────────────────────────────────────────


def test_e_week_start_has_monday_value_1(settings_html):
    """AC (e): Week starts on select has option value='1' for Monday."""
    idx = settings_html.find("profile-week-start")
    assert idx != -1
    chunk = settings_html[idx:idx + 400]
    assert 'value="1"' in chunk or "value='1'" in chunk, (
        "Week start select must have value=1 (Monday)"
    )


def test_e_week_start_has_sunday_value_7(settings_html):
    """AC (e): Week starts on select has option value='7' for Sunday."""
    idx = settings_html.find("profile-week-start")
    assert idx != -1
    chunk = settings_html[idx:idx + 400]
    assert 'value="7"' in chunk or "value='7'" in chunk, (
        "Week start select must have value=7 (Sunday)"
    )


# ── (f) GET /api/user-preferences returns user_name and user_email ─────────────


def test_f_get_prefs_returns_user_name():
    """AC (f): GET /api/user-preferences response includes user_name for display_name placeholder."""
    uid = str(uuid.uuid4())
    name = f"pref361_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, name) VALUES (:id, :name)"),
            {"id": uid, "name": name},
        )
    try:
        mock = _make_mock_user(uid)
        client = _client_with_session(mock)
        try:
            resp = client.get("/api/user-preferences")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert "user_name" in body.get("row", {}), (
                f"GET /api/user-preferences must include user_name in row. Got: {body}"
            )
            assert body["row"]["user_name"] == name
        finally:
            _teardown()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})


def test_f_get_prefs_returns_user_email():
    """AC (f): GET /api/user-preferences response includes user_email."""
    uid = str(uuid.uuid4())
    name = f"pref361e_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, name) VALUES (:id, :name)"),
            {"id": uid, "name": name},
        )
    try:
        mock = _make_mock_user(uid)
        client = _client_with_session(mock)
        try:
            resp = client.get("/api/user-preferences")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert "user_email" in body.get("row", {}), (
                f"GET /api/user-preferences must include user_email in row. Got: {body}"
            )
        finally:
            _teardown()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})


# ── (g) PATCH uses session auth — no user_id in body ─────────────────────────


def test_g_patch_requires_session_returns_401_without_cookie():
    """AC (g): PATCH /api/user-preferences without session cookie returns 401."""
    with TestClient(app) as anon:
        resp = anon.patch("/api/user-preferences", json={"display_name": "X"})
    assert resp.status_code == 401, (
        f"PATCH without session must return 401, got {resp.status_code}"
    )


def test_g_patch_accepts_request_without_user_id_in_body():
    """AC (g): PATCH with session cookie succeeds without user_id in request body."""
    uid = str(uuid.uuid4())
    name = f"pref361g_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, name) VALUES (:id, :name)"),
            {"id": uid, "name": name},
        )
    try:
        mock = _make_mock_user(uid)
        mock.id = uid
        client = _client_with_session(mock)
        try:
            resp = client.patch("/api/user-preferences", json={"display_name": "SomeNewName"})
            assert resp.status_code == 200, (
                f"PATCH with session but no user_id in body must succeed. Got: {resp.status_code} {resp.text}"
            )
        finally:
            _teardown()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})


# ── (h) PATCH with only changed fields persists ───────────────────────────────


def test_h_patch_timezone_only_persists():
    """AC (h): PATCH {timezone: 'America/New_York'} updates timezone, GET confirms."""
    uid = str(uuid.uuid4())
    name = f"pref361h_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, name) VALUES (:id, :name)"),
            {"id": uid, "name": name},
        )
    try:
        mock = _make_mock_user(uid)
        mock.id = uid
        client = _client_with_session(mock)
        try:
            patch_resp = client.patch(
                "/api/user-preferences", json={"timezone": "America/New_York"}
            )
            assert patch_resp.status_code == 200, patch_resp.text
            assert patch_resp.json()["timezone"] == "America/New_York"

            get_resp = client.get("/api/user-preferences")
            assert get_resp.status_code == 200
            assert get_resp.json()["row"]["timezone"] == "America/New_York"
        finally:
            _teardown()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})


def test_h_patch_week_start_day_7_persists():
    """AC (h): PATCH {week_start_day: 7} (Sunday) persists correctly."""
    uid = str(uuid.uuid4())
    name = f"pref361hs_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, name) VALUES (:id, :name)"),
            {"id": uid, "name": name},
        )
    try:
        mock = _make_mock_user(uid)
        mock.id = uid
        client = _client_with_session(mock)
        try:
            resp = client.patch("/api/user-preferences", json={"week_start_day": 7})
            assert resp.status_code == 200, resp.text
            assert resp.json()["week_start_day"] == 7
        finally:
            _teardown()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})


def test_h_patch_display_name_persists():
    """AC (h): PATCH {display_name: 'Chaiwut'} persists correctly."""
    uid = str(uuid.uuid4())
    name = f"pref361hd_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, name) VALUES (:id, :name)"),
            {"id": uid, "name": name},
        )
    try:
        mock = _make_mock_user(uid)
        mock.id = uid
        client = _client_with_session(mock)
        try:
            resp = client.patch("/api/user-preferences", json={"display_name": "Chaiwut"})
            assert resp.status_code == 200, resp.text
            assert resp.json()["display_name"] == "Chaiwut"
        finally:
            _teardown()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})


# ── (i) PATCH validation failures ─────────────────────────────────────────────


def test_i_patch_invalid_timezone_returns_422():
    """AC (i): PATCH with invalid timezone returns 422 with field detail."""
    uid = str(uuid.uuid4())
    name = f"pref361i_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, name) VALUES (:id, :name)"),
            {"id": uid, "name": name},
        )
    try:
        mock = _make_mock_user(uid)
        mock.id = uid
        client = _client_with_session(mock)
        try:
            resp = client.patch("/api/user-preferences", json={"timezone": "Mars/Olympus"})
            assert resp.status_code == 422, resp.text
            detail = resp.json().get("detail", [])
            if isinstance(detail, list):
                fields = [e.get("field") for e in detail]
                assert "timezone" in fields, f"422 detail must name the field. Got: {detail}"
        finally:
            _teardown()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})


# ── (j) No avatar upload UI present ───────────────────────────────────────────


def test_j_no_avatar_upload_ui(settings_html):
    """AC (j): settings.html must not contain an avatar file upload input."""
    assert 'type="file"' not in settings_html and "type='file'" not in settings_html, (
        "No avatar upload UI should be present (upload is deferred to future sprint)"
    )


def test_j_no_upload_photo_label(settings_html):
    """AC (j): 'Upload Photo' label/button must not be present."""
    assert "Upload Photo" not in settings_html, (
        "Upload Photo UI must not be present (deferred)"
    )


# ── (k) Avatar section deferred comment ───────────────────────────────────────


def test_k_avatar_deferred_comment_present(settings_html):
    """AC (k): settings.html has comment 'Avatar upload deferred to future sprint.'"""
    assert "Avatar upload deferred to future sprint" in settings_html, (
        "settings.html must contain the deferred comment about avatar upload"
    )


# ── (l) Avatar circle present for initials ────────────────────────────────────


def test_l_avatar_circle_element_present(settings_html):
    """AC (l): Avatar circle element exists to display user initials."""
    assert "settings-avatar-circle" in settings_html, (
        "Avatar circle element (settings-avatar-circle) must remain for initials display"
    )


def test_l_avatar_initials_element_present(settings_html):
    """AC (l): Avatar initials span exists."""
    assert "settings-avatar-initials" in settings_html, (
        "Avatar initials span (settings-avatar-initials) must be present"
    )


# ── (m) Save button present and disabled by default ───────────────────────────


def test_m_save_button_present_and_disabled(settings_html):
    """AC (m): Profile save button exists and has disabled attribute."""
    assert "profile-save-btn" in settings_html, (
        "Profile save button (id=profile-save-btn) must be present"
    )
    idx = settings_html.find("profile-save-btn")
    snippet = settings_html[max(0, idx - 50):idx + 300]
    assert "disabled" in snippet, (
        "Profile save button must have disabled attribute on initial render"
    )


# ── (n) Per-field feedback element present ────────────────────────────────────


def test_n_profile_feedback_element_present(settings_html):
    """AC (n): A feedback element for profile save messages is present."""
    assert "profile-feedback" in settings_html, (
        "Profile feedback element (profile-feedback) must be present for save messages"
    )


# ── (o) users.email column in DB ─────────────────────────────────────────────


def test_o_users_email_column_exists():
    """AC (o): users table has an email column."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'email'"
            )
        ).fetchone()
    assert result is not None, (
        "users table must have an email column (add via Alembic migration)"
    )
