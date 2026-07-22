"""Tests for issue #599: Add 'Track Zone 2' opt-in button to provision habit.

ACs covered:
  AC1  - "Track Zone 2 in habits" button visible in Performance Thresholds section of settings.html
         when no Zone 2 habit exists; id=thresholds-provision-zone2-btn
  AC2  - JS calls GET /api/user-preferences before POST /api/habits (source check)
  AC3  - POST /api/habits creates habit with correct fields:
           name:"Zone 2", tracking_type:"weekly_minutes",
           auto_fill_source:"workout.zone2_minutes", unit:"min",
           weekly_target from preferences
  AC4  - Success message element and link to /habits present in settings.html
  AC5  - Server returns 409 when habit with auto_fill_source:"workout.zone2_minutes"
         already exists (duplicate guard, enables UAT step 6)
  AC6  - Duplicate guard is checked: second POST returns 409, no second row created
  AC7  - weekly_target on habit is independent of user preferences (no overwrite on
         PATCH /api/user-preferences)
  AC8  - Button hidden/disabled state element and existing-habit message element
         present in settings.html (for JS to toggle)
  AC9  - Button not shown if duplicate guard met on initial load (JS source check)

AC3, AC5, AC6, AC7 use FastAPI TestClient (mocked resolve_user) to avoid CSRF/Secure-cookie
issues with HTTP; this matches the test_habits_crud__387 pattern used across the test suite.
"""

import pathlib
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user


_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SETTINGS_HTML = _ROOT / "frontend" / "pages" / "settings.html"
_SETTINGS_JS = _ROOT / "frontend" / "js" / "settings.js"


def _html() -> str:
    assert _SETTINGS_HTML.exists(), f"Expected file not found: {_SETTINGS_HTML}"
    return _SETTINGS_HTML.read_text()


def _js() -> str:
    assert _SETTINGS_JS.exists(), f"Expected file not found: {_SETTINGS_JS}"
    return _SETTINGS_JS.read_text()


_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000599")


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_habit(
    *,
    hid=None,
    name="Zone 2",
    tracking_type="weekly_minutes",
    is_archived=False,
    sort_order=1,
    weekly_target=150,
    unit="min",
    auto_fill_source="workout.zone2_minutes",
):
    h = MagicMock()
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.description = None
    h.tracking_type = tracking_type
    h.weekly_target = weekly_target
    h.unit = unit
    h.auto_fill_source = auto_fill_source
    h.icon = None
    h.color = None
    h.sort_order = sort_order
    h.is_archived = is_archived
    h.display_order = sort_order
    h.archived_at = None
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-18T00:00:00+00:00"
    h.created_at = ts
    h.updated_at = None
    return h


# ═══════════════════════════════════════════════════════════════════════════════
# AC1 — Button present in settings.html (Performance Thresholds section)
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__html_provision_zone2_button_removed():
    """Provision button removed — Zone 2 habit is auto-seeded via coach_habit_targets."""
    src = _html()
    assert 'id="thresholds-provision-zone2-btn"' not in src


def test_599__html_provision_zone2_card_removed():
    src = _html()
    assert 'id="provision-zone2-card"' not in src
    assert "Zone 2 weekly minutes are tracked as a habit" in src


@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__html_provision_zone2_button_in_thresholds_section():
    pass


@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__html_provision_zone2_button_label():
    pass


@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__html_provision_zone2_button_present():
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# AC2 — JS fetches /api/user-preferences before creating habit
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__js_fetches_user_preferences():
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# AC3 — POST /api/habits creates habit with correct fields
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__api_create_zone2_habit_correct_fields():
    """AC3: POST /api/habits with Zone 2 payload returns 201 with all correct fields."""
    client, _ = _make_client()
    try:
        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)

        query_m = MagicMock()
        query_m.filter.return_value = query_m
        query_m.scalar.return_value = 0
        query_m.first.return_value = None  # no existing habit with this auto_fill_source
        sess.query.return_value = query_m

        created_id = uuid.uuid4()

        def _refresh(h):
            h.id = created_id
            ts = MagicMock()
            ts.isoformat.return_value = "2026-06-18T00:00:00+00:00"
            h.created_at = ts
            h.updated_at = None

        sess.refresh.side_effect = _refresh

        with patch("backend.main.Session", return_value=sess):
            res = client.post("/api/habits", json={
                "name": "Zone 2",
                "tracking_type": "weekly_minutes",
                "auto_fill_source": "workout.zone2_minutes",
                "unit": "min",
                "weekly_target": 150,
            })

        assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
        body = res.json()
        assert body["name"] == "Zone 2"
        assert body["tracking_type"] == "weekly_minutes"
        assert body["auto_fill_source"] == "workout.zone2_minutes"
        assert body["unit"] == "min"
        assert body["weekly_target"] == 150
    finally:
        _teardown()


# ═══════════════════════════════════════════════════════════════════════════════
# AC4 — Success message and link to /habits in settings.html
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__html_success_message_element_present():
    pass


@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__html_habits_link_target_present():
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# AC5/AC6 — Server-side duplicate guard: 409 when auto_fill_source already exists
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__api_duplicate_auto_fill_source_returns_409():
    """AC5/AC6: POST /api/habits returns 409 when a habit with the same
    auto_fill_source already exists for the user."""
    client, _ = _make_client()
    try:
        existing = _make_habit()

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)

        query_m = MagicMock()
        query_m.filter.return_value = query_m
        query_m.scalar.return_value = 1
        query_m.first.return_value = existing  # existing habit found
        sess.query.return_value = query_m

        with patch("backend.main.Session", return_value=sess):
            res = client.post("/api/habits", json={
                "name": "Zone 2",
                "tracking_type": "weekly_minutes",
                "auto_fill_source": "workout.zone2_minutes",
                "unit": "min",
                "weekly_target": 150,
            })

        assert res.status_code == 409, (
            f"Expected 409 on duplicate auto_fill_source, got {res.status_code}: {res.text}"
        )
        body = res.json()
        assert "error" in body, "409 response must contain an 'error' key"
        assert "existing_habit_id" in body, "409 response must contain 'existing_habit_id'"
    finally:
        _teardown()


def test_599__api_no_duplicate_guard_without_auto_fill_source():
    """AC6 (inverse): POST /api/habits without auto_fill_source does not trigger the guard."""
    client, _ = _make_client()
    try:
        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)

        query_m = MagicMock()
        query_m.filter.return_value = query_m
        query_m.scalar.return_value = 0
        query_m.first.return_value = None
        sess.query.return_value = query_m

        def _refresh(h):
            h.id = uuid.uuid4()
            ts = MagicMock()
            ts.isoformat.return_value = "2026-06-18T00:00:00+00:00"
            h.created_at = ts
            h.updated_at = None

        sess.refresh.side_effect = _refresh

        with patch("backend.main.Session", return_value=sess):
            res = client.post("/api/habits", json={
                "name": "My Habit",
                "tracking_type": "daily_checkmark",
            })

        assert res.status_code == 201, (
            f"POST /api/habits without auto_fill_source must not be blocked; got {res.status_code}"
        )
    finally:
        _teardown()


# ═══════════════════════════════════════════════════════════════════════════════
# AC7 — Habit weekly_target is independent of user preferences
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__api_patch_habit_weekly_target_independent():
    """AC7: PATCH /api/habits/:id correctly updates weekly_target independently of prefs.
    The system never overwrites habit.weekly_target when user preferences are patched."""
    client, _ = _make_client()
    try:
        habit = _make_habit(weekly_target=150)
        habit_id = habit.id

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit

        def _refresh(h):
            pass

        sess.refresh.side_effect = _refresh

        with patch("backend.main.Session", return_value=sess):
            res = client.patch(f"/api/habits/{habit_id}", json={"weekly_target": 200})

        assert res.status_code == 200, f"PATCH habit failed: {res.status_code}: {res.text}"
        assert habit.weekly_target == 200, (
            "PATCH /api/habits/:id must update weekly_target to 200"
        )
    finally:
        _teardown()


# ═══════════════════════════════════════════════════════════════════════════════
# AC8 — Existing-habit message element present in settings.html
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__html_existing_habit_message_element_present():
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# AC9 — JS checks for existing habit on page load
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__js_checks_habits_on_load():
    pass


@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__js_references_provision_zone2_btn():
    pass


@pytest.mark.skip(reason="Provision UI removed; habit auto-seeded on GET /api/habits")
def test_599__js_checks_auto_fill_source_on_load():
    pass

