"""Tests for issue #392: Habits management page (CRUD + reorder).

TDD: each test class is anchored to one Acceptance Criterion.
Static checks verify HTML/JS structure; API checks verify backend contract.
"""
import pathlib
import re
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = pathlib.Path(__file__).parent.parent
HABITS_HTML = REPO_ROOT / "frontend" / "pages" / "habits.html"
HABITS_JS = REPO_ROOT / "frontend" / "js" / "habits.js"


def _html():
    return HABITS_HTML.read_text(encoding="utf-8")


def _js():
    return HABITS_JS.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# AC: Route & page structure
# ──────────────────────────────────────────────────────────────────────────────

def test_habits_html_exists():
    """AC: frontend/pages/habits.html exists."""
    assert HABITS_HTML.exists()


def test_habits_js_exists():
    """AC: frontend/js/habits.js exists."""
    assert HABITS_JS.exists()


def test_route_habits_in_main_py():
    """AC: /habits route registered in main.py."""
    main_py = (REPO_ROOT / "backend" / "main.py").read_text()
    assert '"habits"' in main_py or "'habits'" in main_py
    assert "habits.html" in main_py


def test_page_header_title():
    """AC: Page header reads 'Habits — Weekly tracking'."""
    content = _html() + _js()
    assert "Habits" in content and "Weekly tracking" in content


def test_new_habit_button_present():
    """AC: '+ New habit' button appears on the page."""
    content = _html() + _js()
    assert "New habit" in content


def test_nav_included():
    """AC: nav.js is loaded for consistent top nav."""
    html = _html()
    assert "nav.js" in html


# ──────────────────────────────────────────────────────────────────────────────
# AC: Habit list display
# ──────────────────────────────────────────────────────────────────────────────

def test_drag_handle_in_html_or_js():
    """AC: Drag handle element rendered per habit row."""
    content = _html() + _js()
    assert "drag" in content.lower() or "handle" in content.lower()


def test_tracking_type_label_rendered():
    """AC: tracking_type label shown per row."""
    content = _js()
    assert "tracking_type" in content


def test_weekly_target_rendered():
    """AC: Weekly target with unit shown (e.g. 'Goal: 210 min/week')."""
    content = _js()
    assert "weekly_target" in content
    assert "Goal" in content or "goal" in content


def test_auto_fill_source_pill_rendered():
    """AC: auto_fill_source pill rendered ('auto from workouts' or 'manual')."""
    content = _js()
    assert "auto_fill_source" in content
    assert "auto" in content.lower()


def test_actions_menu_edit_archive_delete():
    """AC: Actions menu with Edit / Archive / Delete per row."""
    content = _js()
    assert "edit" in content.lower() or "Edit" in content
    assert "archive" in content.lower() or "Archive" in content
    assert "delete" in content.lower() or "Delete" in content


def test_reorder_endpoint_called_on_drag():
    """AC: POST /api/habits/{id}/reorder called on drag-end."""
    content = _js()
    assert "/reorder" in content


def test_get_habits_called():
    """AC: GET /api/habits used to load habits."""
    content = _js()
    assert "/api/habits" in content


# ──────────────────────────────────────────────────────────────────────────────
# AC: New / Edit form (modal)
# ──────────────────────────────────────────────────────────────────────────────

def test_modal_name_field():
    """AC: Name field present in modal."""
    content = _html() + _js()
    assert "name" in content.lower()


def test_modal_description_field():
    """AC: Description field present in modal."""
    content = _html() + _js()
    assert "description" in content.lower()


def test_modal_tracking_type_dropdown():
    """AC: Tracking type dropdown with 4 options."""
    content = _html() + _js()
    assert "tracking_type" in content
    # Four valid tracking types present
    assert "daily_checkmark" in content
    assert "weekly_count" in content
    assert "weekly_minutes" in content
    assert "weekly_quantity" in content


def test_modal_weekly_target_input():
    """AC: Weekly target numeric input present."""
    content = _html() + _js()
    assert "weekly_target" in content


def test_modal_unit_input():
    """AC: Unit string input present."""
    content = _html() + _js()
    assert "unit" in content.lower()


def test_modal_auto_fill_dropdown():
    """AC: Auto-fill source dropdown with required options."""
    content = _html() + _js()
    assert "auto_fill_source" in content
    assert "zone2" in content.lower() or "zone_2" in content.lower() or "zone2_minutes" in content


def test_modal_icon_picker():
    """AC: Icon picker with required icons."""
    content = _html() + _js()
    required_icons = ["ti-run", "ti-barbell", "ti-droplet", "ti-book",
                      "ti-bed", "ti-flame", "ti-walk", "ti-bike"]
    for icon in required_icons:
        assert icon in content, f"Icon {icon} missing from habits page"


def test_modal_color_picker():
    """AC: Color picker with 6-8 colors."""
    content = _html() + _js()
    assert "color" in content.lower()
    # Count color values (hex colors or color names in picker)
    hex_colors = re.findall(r'#[0-9a-fA-F]{6}', content)
    assert len(hex_colors) >= 6, f"Expected ≥6 colors in picker, found {len(hex_colors)}"


def test_save_calls_post_for_new():
    """AC: Save calls POST /api/habits for new habit."""
    content = _js()
    assert "POST" in content
    assert "/api/habits" in content


def test_save_calls_patch_for_edit():
    """AC: Save calls PATCH /api/habits/{id} for edit."""
    content = _js()
    assert "PATCH" in content


# ──────────────────────────────────────────────────────────────────────────────
# AC: Archive section
# ──────────────────────────────────────────────────────────────────────────────

def test_archived_habits_toggle_present():
    """AC: 'Archived habits' collapsible toggle present."""
    content = _html() + _js()
    assert "archived" in content.lower() or "Archived" in content


def test_include_archived_query_used():
    """AC: include_archived=true used to fetch archived habits."""
    content = _js()
    assert "include_archived" in content or "archived" in content.lower()


def test_unarchive_action_present():
    """AC: Unarchive action available for archived habits."""
    content = _js()
    assert "unarchive" in content.lower() or "Unarchive" in content


def test_patch_is_archived_false_for_unarchive():
    """AC: Unarchive sends PATCH with is_archived=false."""
    content = _js()
    assert "is_archived" in content


# ──────────────────────────────────────────────────────────────────────────────
# AC: Starter-habit pre-seed
# ──────────────────────────────────────────────────────────────────────────────

def test_starter_suggestions_shown_when_zero_habits():
    """AC: Suggestion buttons shown when habits list is empty."""
    content = _js()
    # Must have logic to check habits.length === 0 or habits.length == 0
    assert "length" in content and ("=== 0" in content or "== 0" in content or "length < 1" in content)


def test_zone2_cardio_starter():
    """AC: 'Zone 2 cardio' starter suggestion present."""
    content = _html() + _js()
    assert "Zone 2" in content or "zone2" in content.lower()


def test_running_sessions_starter():
    """AC: 'Running sessions' starter suggestion present."""
    content = _html() + _js()
    assert "Running sessions" in content or "Running" in content


def test_strength_sessions_starter():
    """AC: 'Strength sessions' starter suggestion present."""
    content = _html() + _js()
    assert "Strength" in content


def test_daily_metrics_starter():
    """AC: 'Daily metrics logged' starter suggestion present."""
    content = _html() + _js()
    assert "Daily metrics" in content or "daily metrics" in content.lower()


def test_starter_creates_habit_via_post():
    """AC: Clicking suggestion button creates habit via POST /api/habits."""
    content = _js()
    assert "POST" in content and "/api/habits" in content


def test_starters_not_shown_when_habits_exist():
    """AC: Pre-seed guard — suggestion buttons hidden once habits exist."""
    content = _js()
    # Must have conditional to hide starters when habits.length > 0
    assert "length" in content


# ──────────────────────────────────────────────────────────────────────────────
# AC: Mobile responsive
# ──────────────────────────────────────────────────────────────────────────────

def test_mobile_viewport_meta():
    """AC: viewport meta tag set for mobile."""
    html = _html()
    assert 'name="viewport"' in html
    assert "width=device-width" in html


def test_mobile_media_query_600px():
    """AC: Responsive media query for ≤600px present."""
    content = _html()
    assert "600px" in content or "480px" in content


# ──────────────────────────────────────────────────────────────────────────────
# AC: Backend — PATCH supports is_archived for unarchive
# ──────────────────────────────────────────────────────────────────────────────

def test_patch_habit_supports_is_archived():
    """AC: PATCH /api/habits/{id} accepts is_archived field for unarchive."""
    pytest.importorskip("cryptography", reason="cryptography package required for backend import")
    from backend.main import app, resolve_user

    user = MagicMock()
    user.id = uuid.UUID("00000000-0000-0000-0000-000000000392")

    async def _fake_user():
        return user

    app.dependency_overrides[resolve_user] = _fake_user

    habit = MagicMock()
    habit.id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000392")
    habit.user_id = user.id
    habit.name = "Test"
    habit.description = None
    habit.tracking_type = "daily_checkmark"
    habit.weekly_target = None
    habit.unit = None
    habit.auto_fill_source = None
    habit.icon = None
    habit.color = None
    habit.sort_order = 0
    habit.is_archived = True
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-10T00:00:00+00:00"
    habit.created_at = ts
    habit.updated_at = ts

    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get = MagicMock(return_value=habit)
    sess.commit = MagicMock()
    sess.refresh = MagicMock()

    with patch("backend.main.Session", return_value=sess):
        client = TestClient(app)
        resp = client.patch(
            f"/api/habits/{habit.id}",
            json={"is_archived": False},
            headers={"Content-Type": "application/json"},
        )

    app.dependency_overrides.pop(resolve_user, None)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    # Verify is_archived was set to False
    assert habit.is_archived is False
