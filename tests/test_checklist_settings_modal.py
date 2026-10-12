"""Manage checklist settings modal (WC-16)."""
from __future__ import annotations

from types import SimpleNamespace

from backend.services.checklist_week import _session_role
from backend.services.pref_catalog import PREF_FIELDS, validate_payload


def test_pref_catalog_has_checklist_settings_fields():
    assert "mobility_checklist_role" in PREF_FIELDS
    assert "checklist_fuel_enabled" in PREF_FIELDS
    assert PREF_FIELDS["weekly_checklist_enabled"]["default"] is True
    payload = {
        "stretch_daily_min": 15,
        "mobility_checklist_role": "core",
        "checklist_fuel_enabled": True,
        "weekly_checklist_enabled": True,
    }
    assert not validate_payload(payload)


def test_mobility_session_role_reads_pref():
    ps = SimpleNamespace(session_type="mobility")
    assert _session_role(ps, {"mobility_checklist_role": "core"}) == "core"
    assert _session_role(ps, {"mobility_checklist_role": "optional"}) == "optional"


def test_habits_page_wires_checklist_settings():
    page = open("frontend/pages/habits.html", encoding="utf-8").read()
    assert "checklist-settings.js" in page
    assert "checklist-settings-overlay" in page
    assert 'href="/settings"' not in open(
        "frontend/js/checklist-habits-page.js", encoding="utf-8"
    ).read()


def test_checklist_settings_module_exports():
    src = open("frontend/js/checklist-settings.js", encoding="utf-8").read()
    assert "ChecklistSettings" in src
    assert "/api/preferences" in src
    assert "/api/plan/rebuild-week" in src
    assert "/api/plan/build-status" in src
    assert "checklist_role" in src


def test_plan_build_status_ui_aliases():
    from backend.services.plan_build_status import plan_build_status

    # Smoke: keys the modal reads exist on the helper return shape.
    import inspect

    src = inspect.getsource(plan_build_status)
    assert '"status"' in src
    assert '"last_built_at"' in src
