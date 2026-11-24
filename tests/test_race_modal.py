"""Add / Edit race centered modal — catalog endpoint, payload, UI contract."""
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services.race_roles import RECALIBRATING_ROLES, ROLE_LABELS, ROLES

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "frontend" / "js" / "v2-performance.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "revamp.css").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "pages" / "v2-performance.html").read_text(encoding="utf-8")
UID = uuid.uuid4()


def test_roles_endpoint_requires_session():
    assert TestClient(app).get("/api/races/roles").status_code == 401


def test_roles_endpoint_matches_race_roles_module():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        r = TestClient(app).get("/api/races/roles")
        assert r.status_code == 200
        roles = r.json()["roles"]
        assert [row["id"] for row in roles] == list(ROLES)
        for row in roles:
            assert row["label"] == ROLE_LABELS[row["id"]]
            assert row["recalibrates"] is (row["id"] in RECALIBRATING_ROLES)
        assert {row["id"] for row in roles if row["recalibrates"]} == set(RECALIBRATING_ROLES)
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_modal_replaces_drawer_form():
    assert "rv-race-modal" in JS
    assert 'id="v2-race-modal-root"' in HTML
    assert "Role is independent of priority" not in JS
    assert "openDrawer(" in JS  # mobility / accept still use the drawer
    assert "renderRaceModal" in JS
    assert "openRaceDrawer" in JS


def test_every_entry_point_opens_modal():
    assert "openRaceDrawer(null, { asARace: true })" in JS
    assert "openRaceDrawer(null)" in JS
    assert "openRaceDrawer(raceIndex[" in JS
    assert "add=a-race" in JS


def test_presets_and_half_pace_math():
    assert "21.0975" in JS
    assert "42.195" in JS
    assert 'label: "Half"' in JS
    assert round(6600 / 21.0975) == 313  # 1:50:00 / Half → 5:13 /km
    assert "fmtPace(goal / dist)" in JS


def test_priority_and_role_are_radiogroups():
    assert 'role="radiogroup"' in JS
    assert 'role="radio"' in JS
    assert "ArrowRight" in JS and "ArrowLeft" in JS
    assert 'name="priority"' in JS
    assert 'name="role"' in JS
    assert 'data-field="priority"' in JS
    assert 'data-field="role"' in JS


def test_recalibration_tags_come_from_api():
    assert '"/api/races/roles"' in JS
    assert "RECALIBRATES" in JS
    assert "NO RECALIBRATE" in JS
    assert "r.recalibrates" in JS


def test_payload_shape_unchanged():
    assert '"PATCH", "/api/races/"' in JS
    assert '"POST", "/api/races"' in JS
    assert "goal_time_seconds: goal" in JS
    assert "payload.race_date = f.elements.race_date.value" in JS
    assert "payload.date = f.elements.race_date.value" in JS
    assert "priority: f.elements.priority.value" in JS
    assert "role: f.elements.role.value" in JS


def test_close_escape_backdrop_cancel_and_focus_return():
    assert "Discard unsaved race details?" in JS
    assert "requestCloseRaceModal" in JS
    assert 'ev.key === "Escape"' in JS
    assert "raceModalOpener" in JS
    assert "aria-label=\"Close\"" in JS


def test_css_desktop_and_phone_sheet():
    assert "width: 620px" in CSS
    assert "max-width: calc(100% - 32px)" in CSS
    assert "padding: 72px 16px 24px" in CSS
    assert "rgba(11, 21, 48, 0.55)" in CSS
    assert "0 24px 60px rgba(11, 21, 48, 0.45)" in CSS
    assert "max-height: 92vh" in CSS
    assert "border-radius: 16px 16px 0 0" in CSS
    assert "background: #fafbfe" in CSS
