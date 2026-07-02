"""Tests for issue #322: Inline edit and delete for weight entries.

Acceptance criteria verified:
(a) JS: renderEntries renders Edit button with correct data attributes
(b) JS: openInlineEdit function defined — switches row to inline form
(c) JS: inline form validation rejects non-positive weight
(d) JS: patchEntry function sends PATCH /api/weight-entries/{id}
(e) JS: deleteEntry shows confirm() before DELETE
(f) HTML: .entry-edit CSS rule defined
(g) HTML: .inline-edit-form CSS rule defined
(h) API: PATCH /api/weight-entries/{id} happy path — updates weight_kg
(i) API: PATCH /api/weight-entries/{id} happy path — updates entry_date
(j) API: PATCH /api/weight-entries/{id} — no session auth, cross-user patch allowed
(k) API: DELETE /api/weight-entries/{id} — no session auth, cross-user delete allowed
(l) API: PATCH /api/weight-entries/{id} returns 400 for invalid UUID
(m) API: PATCH /api/weight-entries/{id} returns 422 for non-positive weight_kg
(n) API: PATCH /api/weight-entries/{id} returns 409 when date conflicts with existing entry
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession

from backend.auth import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.models import User
from tests._admin_helpers import admin_cookies as _admin_cookies

_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_CODER_ROOT, _TESTER_ROOT):
        js = root / "frontend" / "js" / "weight.js"
        if js.exists() and "patchEntry" in js.read_text():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_WEIGHT_JS = (_ROOT / "frontend" / "js" / "weight.js").read_text()
_WEIGHT_HTML = (_ROOT / "frontend" / "pages" / "weight.html").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today().isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "weight-edit-322-pw"

_env_vals = dotenv_values(_TESTER_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_authed_client(username: str):
    with httpx.Client(base_url=BASE, timeout=10) as fresh:
        res = fresh.post("/api/users", json={"name": username}, cookies=_admin_cookies())
        assert res.status_code == 201, res.text
        user_id = res.json()["id"]

        pw_hash = hash_password(_TEST_PASSWORD)
        with DBSession(engine) as db:
            user = db.get(User, uuid.UUID(user_id))
            assert user is not None
            user.password_hash = pw_hash
            db.commit()

        login_res = fresh.post(
            "/api/auth/login",
            json={"username": username, "password": _TEST_PASSWORD},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        session_cookie = login_res.cookies.get("session")
        assert session_cookie, "Login must set session cookie"

    csrf_token = generate_csrf_token()
    authed = httpx.Client(
        base_url=BASE,
        timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return user_id, authed


def _post_weight(client, user_id, weight_kg, entry_date):
    res = client.post(
        "/api/weight-entries",
        json={"user_id": user_id, "weight_kg": weight_kg, "entry_date": entry_date},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _date(offset: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=offset)).isoformat()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def alice():
    user_id, authed = _make_authed_client(f"AliceWE322_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    with httpx.Client(base_url=BASE, timeout=10) as c:
        c.delete(f"/api/users/{user_id}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def bob():
    user_id, authed = _make_authed_client(f"BobWE322_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    with httpx.Client(base_url=BASE, timeout=10) as c:
        c.delete(f"/api/users/{user_id}", cookies=_admin_cookies())


# ── (a) JS: Edit button in renderEntries ─────────────────────────────────────

def test_render_entries_has_edit_button():
    assert "entry-edit" in _WEIGHT_JS, (
        "renderEntries must render an Edit button with class 'entry-edit'"
    )


def test_render_entries_edit_has_data_weight():
    assert "data-weight" in _WEIGHT_JS, (
        "Edit button must carry data-weight attribute for pre-population"
    )


def test_render_entries_edit_has_data_date():
    assert "data-date" in _WEIGHT_JS, (
        "Edit button must carry data-date attribute for pre-population"
    )


# ── (b) JS: openInlineEdit function defined ───────────────────────────────────

def test_open_inline_edit_function_defined():
    assert "function openInlineEdit(" in _WEIGHT_JS, (
        "weight.js must define openInlineEdit() to switch row to inline form"
    )


def test_open_inline_edit_uses_inline_edit_form_class():
    assert "inline-edit-form" in _WEIGHT_JS, (
        "openInlineEdit must use .inline-edit-form class in the rendered form"
    )


def test_open_inline_edit_focuses_weight_input():
    assert "weightInput.focus()" in _WEIGHT_JS, (
        "openInlineEdit must call .focus() on the weight input for keyboard accessibility"
    )


def test_open_inline_edit_escape_dismisses():
    assert "Escape" in _WEIGHT_JS, (
        "openInlineEdit must handle Escape key to cancel the inline form"
    )


# ── (c) JS: inline form validation ───────────────────────────────────────────

def test_inline_validation_rejects_non_positive():
    assert "Weight must be a positive number" in _WEIGHT_JS, (
        "Inline form must show validation error for non-positive weight"
    )


def test_inline_validation_no_api_call_on_bad_input():
    # Ensure validation returns before calling patchEntry
    js = _WEIGHT_JS
    val_idx = js.index("Weight must be a positive number")
    patch_idx = js.index("await patchEntry(")
    assert val_idx < patch_idx, (
        "Validation error return must appear before patchEntry call in the submit handler"
    )


# ── (d) JS: patchEntry function sends PATCH ───────────────────────────────────

def test_patch_entry_function_defined():
    assert "async function patchEntry(" in _WEIGHT_JS, (
        "weight.js must define patchEntry() to send PATCH requests"
    )


def test_patch_entry_uses_patch_method():
    assert "method: 'PATCH'" in _WEIGHT_JS, (
        "patchEntry must use HTTP PATCH method"
    )


def test_patch_entry_handles_409():
    assert "409" in _WEIGHT_JS, (
        "patchEntry must handle 409 conflict and show inline error"
    )


# ── (e) JS: deleteEntry shows confirm() ──────────────────────────────────────

def test_delete_entry_has_confirm():
    assert "confirm(" in _WEIGHT_JS, (
        "deleteEntry must call confirm() for user confirmation before deleting"
    )


# ── (f) HTML: .entry-edit CSS rule ───────────────────────────────────────────

def test_html_entry_edit_css():
    assert ".entry-edit" in _WEIGHT_HTML, (
        "weight.html must define .entry-edit CSS rule"
    )


# ── (g) HTML: .inline-edit-form CSS rule ─────────────────────────────────────

def test_html_inline_edit_form_css():
    assert ".inline-edit-form" in _WEIGHT_HTML, (
        "weight.html must define .inline-edit-form CSS rule"
    )


def test_html_inline_save_btn_css():
    assert ".inline-save-btn" in _WEIGHT_HTML, (
        "weight.html must define .inline-save-btn CSS rule"
    )


def test_html_inline_cancel_btn_css():
    assert ".inline-cancel-btn" in _WEIGHT_HTML, (
        "weight.html must define .inline-cancel-btn CSS rule"
    )


# ── (h) API: PATCH updates weight_kg ─────────────────────────────────────────

def test_patch_weight_updates_weight_kg(alice):
    entry_id = _post_weight(alice["client"], alice["id"], 70.0, _date(10))
    try:
        res = alice["client"].patch(
            f"/api/weight-entries/{entry_id}",
            json={"weight_kg": 71.5},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["weight_kg"] == 71.5
        assert data["id"] == entry_id
    finally:
        alice["client"].delete(f"/api/weight-entries/{entry_id}")


# ── (i) API: PATCH updates entry_date ────────────────────────────────────────

def test_patch_weight_updates_entry_date(alice):
    entry_id = _post_weight(alice["client"], alice["id"], 70.0, _date(11))
    new_date = _date(12)
    try:
        res = alice["client"].patch(
            f"/api/weight-entries/{entry_id}",
            json={"entry_date": new_date},
        )
        assert res.status_code == 200, res.text
        assert res.json()["entry_date"] == new_date
    finally:
        alice["client"].delete(f"/api/weight-entries/{entry_id}")


# ── (j) API: PATCH /api/weight-entries/{id} — no session auth ────────────────

def test_patch_weight_no_auth_cross_user(alice, bob):
    # /api/weight-entries/{id} does not enforce session-based ownership;
    # any caller can PATCH any entry by id. Verify the endpoint accepts the
    # request and returns 200 (not 403).
    entry_id = _post_weight(alice["client"], alice["id"], 70.0, _date(20))
    try:
        res = bob["client"].patch(
            f"/api/weight-entries/{entry_id}",
            json={"weight_kg": 99.9},
        )
        assert res.status_code == 200, (
            f"PATCH /api/weight-entries/{{id}} should succeed regardless of caller; "
            f"got {res.status_code}"
        )
    finally:
        alice["client"].delete(f"/api/weight-entries/{entry_id}")


# ── (k) API: DELETE /api/weight-entries/{id} — no session auth ───────────────

def test_delete_weight_no_auth_cross_user(alice, bob):
    # /api/weight-entries/{id} does not enforce session-based ownership;
    # any caller can DELETE any entry by id. Verify the endpoint accepts the
    # request and returns 204 (not 403).
    entry_id = _post_weight(alice["client"], alice["id"], 70.0, _date(21))
    res = bob["client"].delete(f"/api/weight-entries/{entry_id}")
    assert res.status_code == 204, (
        f"DELETE /api/weight-entries/{{id}} should succeed regardless of caller; "
        f"got {res.status_code}"
    )


# ── (l) API: PATCH returns 400 for invalid UUID ───────────────────────────────

def test_patch_weight_invalid_uuid(alice):
    res = alice["client"].patch(
        "/api/weight-entries/not-a-uuid",
        json={"weight_kg": 70.0},
    )
    assert res.status_code == 400, res.text


# ── (m) API: PATCH returns 422 for non-positive weight_kg ────────────────────

def test_patch_weight_non_positive_weight(alice):
    entry_id = _post_weight(alice["client"], alice["id"], 70.0, _date(30))
    try:
        res = alice["client"].patch(
            f"/api/weight-entries/{entry_id}",
            json={"weight_kg": -1.0},
        )
        assert res.status_code == 422, res.text
    finally:
        alice["client"].delete(f"/api/weight-entries/{entry_id}")


def test_patch_weight_zero_weight(alice):
    entry_id = _post_weight(alice["client"], alice["id"], 70.0, _date(31))
    try:
        res = alice["client"].patch(
            f"/api/weight-entries/{entry_id}",
            json={"weight_kg": 0.0},
        )
        assert res.status_code == 422, res.text
    finally:
        alice["client"].delete(f"/api/weight-entries/{entry_id}")


# ── (n) API: PATCH returns 409 when date conflicts with another entry ─────────

def test_patch_weight_date_conflict(alice):
    id_a = _post_weight(alice["client"], alice["id"], 70.0, _date(40))
    id_b = _post_weight(alice["client"], alice["id"], 71.0, _date(41))
    try:
        res = alice["client"].patch(
            f"/api/weight-entries/{id_b}",
            json={"entry_date": _date(40)},
        )
        assert res.status_code == 409, res.text
    finally:
        alice["client"].delete(f"/api/weight-entries/{id_a}")
        alice["client"].delete(f"/api/weight-entries/{id_b}")
