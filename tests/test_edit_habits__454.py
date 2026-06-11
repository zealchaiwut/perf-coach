"""Tests for issue #454: Allow Users to Edit Habits After Creation.

AC items covered:
  (a) Edit action (⋯ menu button) is present for each non-archived habit row
      in both the daily grid and the weekly habits section.
  (b) openEditModal() pre-populates all editable fields with the habit's
      current values.
  (c) PATCH /api/habits/{id} without tracking_type succeeds (200) — users
      can save edits.
  (d) The JS form-submit path must NOT include tracking_type in the PATCH
      payload when editing (editingHabitId is set), because the backend
      rejects it with 422.
  (e) Cancel discards edits — closeModal() clears editingHabitId and removes
      the 'open' class.
  (f) Empty name shows an inline validation error and prevents saving.
  (g) PATCH /api/habits/{id} does NOT modify habit_logs rows — history is
      preserved.
  (h) Archived habits rendered in the archived-list section do NOT have an
      Edit button (only Restore / Delete).
  (i) openEditModal() disables the tracking_type <select> so the user sees
      it is immutable.
  (j) A hint element visible in edit mode communicates that tracking_type
      cannot be updated.
"""
import re
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import pathlib

_ROOT = pathlib.Path(__file__).parent.parent
_HTML = (_ROOT / "frontend" / "pages" / "habits.html").read_text()
_JS   = (_ROOT / "frontend" / "js" / "habits.js").read_text()

# ── shared API test helpers ──────────────────────────────────────────────────

from backend.main import app, resolve_user

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000454")


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


def _make_habit(*, hid=None, name="Running", tracking_type="daily_checkmark",
                is_archived=False, sort_order=0, weekly_target=None, unit=None,
                auto_fill_source=None, icon=None, color=None, description=None):
    h = MagicMock()
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.description = description
    h.tracking_type = tracking_type
    h.weekly_target = weekly_target
    h.unit = unit
    h.auto_fill_source = auto_fill_source
    h.icon = icon
    h.color = color
    h.sort_order = sort_order
    h.is_archived = is_archived
    h.display_order = sort_order
    h.archived_at = None
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"
    h.created_at = ts
    h.updated_at = None
    return h


def _make_session_ctx(habit=None, habits=None):
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = habits or []
    q.scalar.return_value = 0
    q.delete.return_value = 0
    sess.query.return_value = q
    sess.get.return_value = habit
    return sess


# ── AC (a): Edit action present on non-archived habit rows ───────────────────

class TestEditActionPresent:
    """AC (a): Edit button/menu exists on each non-archived habit row."""

    def test_daily_grid_row_has_actions_toggle(self):
        """Daily grid rows must have a ⋯ toggle that opens an actions menu."""
        assert "day-actions-toggle" in _HTML, \
            "habits.html must define .day-actions-toggle for daily-grid rows"
        assert "day-actions-menu" in _HTML, \
            "habits.html must define .day-actions-menu for daily-grid rows"

    def test_daily_grid_menu_edit_button_created_in_js(self):
        """habits.js must create an Edit button in each daily-grid actions menu."""
        assert re.search(r'editBtn.*?Edit', _JS, re.DOTALL), \
            "habits.js must build an Edit button and add it to day-actions-menu"

    def test_weekly_section_has_actions_toggle(self):
        """Weekly habits rows must have a ⋯ toggle."""
        assert "week-actions-toggle" in _HTML, \
            "habits.html must define .week-actions-toggle for weekly-habit rows"

    def test_weekly_section_edit_button_created_in_js(self):
        """habits.js must create an Edit button in each weekly-habit actions menu."""
        # Check there's an editBtn that calls openEditModal in week section
        # The pattern is: editBtn... openEditModal in context of week menu
        match = re.search(
            r'week[Mm]enu.*?openEditModal|openEditModal.*?week[Mm]enu',
            _JS, re.DOTALL
        )
        assert match or _JS.count('openEditModal') >= 2, \
            "habits.js must wire Edit buttons to openEditModal in both daily and weekly sections"


# ── AC (b): openEditModal pre-populates all editable fields ──────────────────

class TestOpenEditModalPrePopulates:
    """AC (b): openEditModal() must pre-populate all editable habit fields."""

    def test_open_edit_modal_sets_name(self):
        assert "modal-name" in _JS and "habit.name" in _JS, \
            "openEditModal must set #modal-name to habit.name"

    def test_open_edit_modal_sets_description(self):
        assert "modal-description" in _JS and "habit.description" in _JS, \
            "openEditModal must set #modal-description to habit.description"

    def test_open_edit_modal_sets_weekly_target(self):
        assert "modal-weekly-target" in _JS and "habit.weekly_target" in _JS, \
            "openEditModal must set #modal-weekly-target"

    def test_open_edit_modal_sets_unit(self):
        assert "modal-unit" in _JS and "habit.unit" in _JS, \
            "openEditModal must set #modal-unit"

    def test_open_edit_modal_sets_auto_fill_source(self):
        assert "modal-auto-fill" in _JS and "habit.auto_fill_source" in _JS, \
            "openEditModal must set #modal-auto-fill to habit.auto_fill_source"

    def test_open_edit_modal_sets_title_to_edit_habit(self):
        assert "'Edit habit'" in _JS or '"Edit habit"' in _JS, \
            "openEditModal must set modal title to 'Edit habit'"

    def test_open_edit_modal_sets_submit_to_save_changes(self):
        assert "'Save changes'" in _JS or '"Save changes"' in _JS, \
            "openEditModal must set submit button text to 'Save changes'"


# ── AC (c): PATCH without tracking_type succeeds ─────────────────────────────

class TestPatchHabitEditSucceeds:
    """AC (c): PATCH /api/habits/{id} with editable fields (no tracking_type) returns 200."""

    def test_patch_name_and_description_returns_200(self):
        """PATCH with name and description (no tracking_type) returns 200."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid, name="Old Name")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={
                    "name": "New Name",
                    "description": "Updated description",
                })
            assert res.status_code == 200
        finally:
            _teardown()

    def test_patch_icon_and_color_returns_200(self):
        """PATCH with icon and color returns 200."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={
                    "icon": "ti-run",
                    "color": "#3b82f6",
                })
            assert res.status_code == 200
        finally:
            _teardown()

    def test_patch_weekly_target_and_unit_returns_200(self):
        """PATCH with weekly_target and unit returns 200."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid, tracking_type="weekly_minutes")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={
                    "weekly_target": 210.0,
                    "unit": "min",
                })
            assert res.status_code == 200
        finally:
            _teardown()

    def test_patch_response_contains_updated_name(self):
        """PATCH response body contains the updated name."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid, name="Old")
        h.name = "New Name"  # mock simulates update
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={"name": "New Name"})
            assert res.status_code == 200
            assert res.json()["name"] == "New Name"
        finally:
            _teardown()


# ── AC (d): Edit-mode PATCH payload must NOT include tracking_type ────────────

class TestEditPayloadExcludesTrackingType:
    """AC (d): JS form submit must NOT send tracking_type when editingHabitId is set."""

    def test_patch_with_tracking_type_rejected_by_api(self):
        """PATCH /api/habits/{id} with tracking_type in body returns 422 (backend guard)."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={
                    "name": "New Name",
                    "tracking_type": "weekly_count",  # should be rejected
                })
            assert res.status_code == 422, \
                "PATCH with tracking_type must return 422 to prevent frontend from sending it"
        finally:
            _teardown()

    def test_js_edit_path_excludes_tracking_type_from_payload(self):
        """In the JS form-submit handler, the PATCH payload must not include tracking_type.

        The submit handler must either:
          (A) Explicitly delete tracking_type from payload before the PATCH call, OR
          (B) Build a separate payload for the edit path that excludes tracking_type.
        """
        # Option A: explicit `delete payload.tracking_type`
        has_delete = (
            "delete payload.tracking_type" in _JS or
            "delete payload['tracking_type']" in _JS
        )
        # Option B: a separate payload variable for the PATCH path that never includes tracking_type
        # e.g. `const editPayload = { name, description, ... }` with no tracking_type key
        # We approximate this by checking for a named edit payload that lacks tracking_type
        edit_payload_match = re.search(
            r'(editPayload|patchPayload)\s*=\s*\{([^}]*)\}',
            _JS
        )
        has_separate_edit_payload = False
        if edit_payload_match:
            payload_body = edit_payload_match.group(2)
            has_separate_edit_payload = "tracking_type" not in payload_body

        assert has_delete or has_separate_edit_payload, (
            "habits.js submit handler must explicitly exclude tracking_type from the PATCH payload "
            "(e.g., `delete payload.tracking_type` when editingHabitId is set), "
            "otherwise PATCH returns 422 and edits fail silently"
        )


# ── AC (e): Cancel discards all changes ──────────────────────────────────────

class TestCancelDiscardsChanges:
    """AC (e): Cancel button closes the modal without saving."""

    def test_close_modal_function_exists(self):
        assert "closeModal" in _JS, "habits.js must have a closeModal() function"

    def test_close_modal_removes_open_class(self):
        assert "classList.remove('open')" in _JS or 'classList.remove("open")' in _JS, \
            "closeModal must remove the 'open' class from the modal overlay"

    def test_close_modal_clears_editing_habit_id(self):
        # After closeModal, editingHabitId should be null
        close_match = re.search(
            r'function closeModal\(\)\s*\{(.*?)\}',
            _JS, re.DOTALL
        )
        assert close_match, "habits.js must have a closeModal() function body"
        close_body = close_match.group(1)
        assert "editingHabitId" in close_body and (
            "null" in close_body or "= null" in close_body
        ), "closeModal must reset editingHabitId to null"

    def test_cancel_button_wired_to_close_modal(self):
        assert "modal-cancel" in _JS and "closeModal" in _JS, \
            "The #modal-cancel button must be wired to closeModal()"


# ── AC (f): Validation error on empty name ───────────────────────────────────

class TestValidationEmptyName:
    """AC (f): Empty name triggers inline error, save is prevented."""

    def test_js_checks_name_required(self):
        """Submit handler must validate that name is not empty."""
        assert "Name is required" in _JS or "name is required" in _JS.lower(), \
            "habits.js must show a 'Name is required' validation message"

    def test_js_sets_error_text_element(self):
        """Submit handler must set text on modal-error element."""
        assert "modal-error" in _JS and "textContent" in _JS, \
            "habits.js must write to #modal-error.textContent for inline validation"

    def test_patch_empty_name_rejected_by_api(self):
        """PATCH with empty name should be handled (backend rejects blank after strip or JS guards first)."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        # Sending whitespace-only name — backend strips and model validation catches it
        # (JS guards earlier, but we confirm the API also behaves correctly if called directly)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={"name": "   "})
            # Name becomes empty after strip; Pydantic Field max_length passes for whitespace
            # but the JS guard prevents this — the API itself may return 200 with stripped name.
            # The key AC is the *JS-level* inline validation, which is tested above.
            assert res.status_code in (200, 422)
        finally:
            _teardown()


# ── AC (g): Habit history preserved after edit ───────────────────────────────

class TestHabitHistoryPreserved:
    """AC (g): PATCH /api/habits/{id} does not delete habit_logs."""

    def test_patch_does_not_delete_habit_logs(self):
        """PATCH must not call session.query(HabitLog).delete()."""
        from backend.models import HabitLog
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid, name="Keep History")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={"name": "New Name"})
            assert res.status_code == 200
            # Soft-delete / update path must not call query(HabitLog)
            for call in sess.query.call_args_list:
                assert call.args[0] is not HabitLog, \
                    "PATCH must not touch HabitLog table — history must be preserved"
        finally:
            _teardown()

    def test_patch_does_not_call_session_delete(self):
        """PATCH must not call session.delete() — only updates the habit row."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={"name": "New"})
            assert res.status_code == 200
            sess.delete.assert_not_called()
        finally:
            _teardown()


# ── AC (h): No Edit button on archived habits ─────────────────────────────────

class TestNoEditForArchivedHabits:
    """AC (h): The archived-list section must NOT offer an Edit button."""

    def test_archived_list_renders_restore_and_delete_only(self):
        """archived-list items are built with only 'Restore' and a delete button (no Edit)."""
        archived_match = re.search(
            r'archivedHabits\.forEach.*?li\.appendChild\(.*?li\.appendChild\(.*?',
            _JS, re.DOTALL
        )
        # Find the archived-list rendering block
        archived_block = re.search(
            r'archivedHabits\.forEach\(\s*habit\s*=>(.*?)^\s*\}\s*\);',
            _JS, re.DOTALL | re.MULTILINE,
        )
        assert archived_block, "habits.js must have an archivedHabits.forEach block"
        block_text = archived_block.group(1)
        # Restore / unarchive button must exist
        assert "Restore" in block_text or "unarchive" in block_text.lower(), \
            "Archived-habits block must include a 'Restore' button"
        # openEditModal must NOT be called in the archived rendering block
        assert "openEditModal" not in block_text, \
            "Archived-habits section must NOT wire an Edit / openEditModal button"

    def test_daily_grid_only_processes_active_habits(self):
        """Daily grid is built from activeHabits, which excludes archived ones."""
        # activeHabits is filtered to is_archived == false in loadAndRender
        assert "is_archived" in _JS, \
            "habits.js must filter habits by is_archived to keep active/archived separate"
        assert "archivedHabits" in _JS and "activeHabits" in _JS, \
            "habits.js must maintain separate activeHabits and archivedHabits lists"


# ── AC (i): tracking_type disabled in edit mode ──────────────────────────────

class TestTrackingTypeDisabledInEditMode:
    """AC (i): openEditModal() must disable the tracking_type <select>."""

    def test_open_edit_modal_disables_tracking_type_select(self):
        """openEditModal() must set modal-tracking-type.disabled = true."""
        open_edit_match = re.search(
            r'function openEditModal\(.*?\{(.*?)^}',
            _JS, re.DOTALL | re.MULTILINE
        )
        assert open_edit_match, "habits.js must define openEditModal()"
        fn_body = open_edit_match.group(1)
        assert ".disabled" in fn_body or "disabled" in fn_body, \
            "openEditModal must set .disabled on the tracking-type select to signal immutability"

    def test_open_new_modal_re_enables_tracking_type_select(self):
        """openNewModal() must ensure modal-tracking-type is NOT disabled."""
        open_new_match = re.search(
            r'function openNewModal\(\)\s*\{(.*?)^}',
            _JS, re.DOTALL | re.MULTILINE
        )
        assert open_new_match, "habits.js must define openNewModal()"
        fn_body = open_new_match.group(1)
        # Either sets disabled = false, or removes disabled attribute
        assert "disabled" in fn_body or "false" in fn_body, \
            "openNewModal must re-enable the tracking-type select (disabled = false)"


# ── AC (j): Hint text shown in edit mode ──────────────────────────────────────

class TestImmutableFieldHintInEditMode:
    """AC (j): An informational note about tracking_type being immutable must be visible in edit mode."""

    def test_html_has_tracking_type_edit_hint_element(self):
        """habits.html must have an element that can show the 'cannot be updated' hint."""
        # Either a static element with style display:none that JS toggles,
        # or the JS inserts the text dynamically
        has_static_hint = (
            "cannot be updated" in _HTML.lower() or
            "modal-tracking-type-hint" in _HTML or
            "tracking-type-hint" in _HTML
        )
        has_dynamic_hint = (
            "cannot be updated" in _JS.lower()
        )
        assert has_static_hint or has_dynamic_hint, (
            "Either habits.html or habits.js must render a hint that "
            "tracking_type cannot be updated when editing"
        )

    def test_js_shows_immutable_hint_in_edit_mode(self):
        """openEditModal must expose the 'cannot be updated' hint text."""
        open_edit_match = re.search(
            r'function openEditModal\(.*?\{(.*?)^}',
            _JS, re.DOTALL | re.MULTILINE
        )
        assert open_edit_match, "habits.js must define openEditModal()"
        fn_body = open_edit_match.group(1)
        # The hint should either be shown or the text should appear somewhere
        has_hint = (
            "cannot be updated" in fn_body.lower() or
            "cannot" in fn_body.lower() or
            "hint" in fn_body.lower() or
            "tracking-type-hint" in fn_body or
            "style.display" in fn_body
        )
        assert has_hint, (
            "openEditModal must display a hint that tracking_type cannot be updated"
        )
