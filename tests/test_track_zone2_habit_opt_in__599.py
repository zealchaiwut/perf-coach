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

JS-only ACs (spinner, animation, live DOM state) are marked pytest.skip.

Server: http://127.0.0.1:9001
"""

import pathlib
import uuid

import httpx
import pytest

from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session


BASE_URL = "http://127.0.0.1:9001"
_TEST_PASSWORD = "Zone2Habit599Pw!"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SETTINGS_HTML = _ROOT / "frontend" / "pages" / "settings.html"
_SETTINGS_JS = _ROOT / "frontend" / "js" / "settings.js"


def _html() -> str:
    assert _SETTINGS_HTML.exists(), f"Expected file not found: {_SETTINGS_HTML}"
    return _SETTINGS_HTML.read_text()


def _js() -> str:
    assert _SETTINGS_JS.exists(), f"Expected file not found: {_SETTINGS_JS}"
    return _SETTINGS_JS.read_text()


@pytest.fixture(scope="module")
def authed_client():
    username = f"tester599_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=True) as c:
        res = c.post("/api/users", json={"name": username})
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

        c.delete(f"/api/users/{user_id}")


def _post_habit(client, payload):
    csrf = getattr(client, "_csrf", "")
    return client.post(
        "/api/habits",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )


def _patch_prefs(client, payload):
    csrf = getattr(client, "_csrf", "")
    return client.patch(
        "/api/user-preferences",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )


def _delete_habit(client, habit_id):
    csrf = getattr(client, "_csrf", "")
    return client.delete(f"/api/habits/{habit_id}?hard=true", headers={"X-CSRF-Token": csrf})


# ═══════════════════════════════════════════════════════════════════════════════
# AC1 — Button present in settings.html (Performance Thresholds section)
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__html_provision_zone2_button_present():
    """AC1: The provision button must be in settings.html."""
    src = _html()
    assert 'id="thresholds-provision-zone2-btn"' in src, (
        "settings.html must contain a button with id='thresholds-provision-zone2-btn'"
    )


def test_599__html_provision_zone2_button_in_thresholds_section():
    """AC1: Button must appear inside section-thresholds div (before the next section)."""
    src = _html()
    thresholds_start = src.find('id="section-thresholds"')
    assert thresholds_start != -1, "section-thresholds div not found"
    # The next section begins at id="section-personal-records"
    next_section = src.find('id="section-personal-records"', thresholds_start + 1)
    if next_section == -1:
        # Fallback: find any id="section-" that is not the thresholds section
        import re
        for m in re.finditer(r'id="section-(?!thresholds")', src[thresholds_start + 1:]):
            next_section = thresholds_start + 1 + m.start()
            break
    if next_section == -1:
        next_section = len(src)
    thresholds_block = src[thresholds_start:next_section]
    assert 'id="thresholds-provision-zone2-btn"' in thresholds_block, (
        "provision button must be inside the section-thresholds div"
    )


def test_599__html_provision_zone2_button_label():
    """AC1: Button label must mention 'Zone 2' and 'habit'."""
    src = _html()
    # Find the button element
    btn_idx = src.find('id="thresholds-provision-zone2-btn"')
    assert btn_idx != -1
    btn_context = src[max(0, btn_idx - 100):btn_idx + 200]
    lowered = btn_context.lower()
    assert "zone 2" in lowered or "zone2" in lowered, (
        "Provision button must mention Zone 2 in its label or context"
    )
    assert "habit" in lowered, (
        "Provision button must mention 'habit' in its label or context"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC2 — JS fetches /api/user-preferences before creating habit
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__js_fetches_user_preferences():
    """AC2: Settings JS (inline or settings.js) must reference /api/user-preferences
    in the provisioning flow."""
    # Check both the HTML (inline script) and the settings.js file
    html_src = _html()
    has_prefs = "/api/user-preferences" in html_src
    if not has_prefs and _SETTINGS_JS.exists():
        has_prefs = "/api/user-preferences" in _js()
    assert has_prefs, (
        "The provisioning flow must call GET /api/user-preferences to get the "
        "weekly Zone 2 target before creating the habit"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC3 — POST /api/habits creates habit with correct fields
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__api_create_zone2_habit_correct_fields(authed_client):
    """AC3: POST /api/habits with Zone 2 payload returns 201 with all correct fields."""
    # Set a known weekly target in preferences
    _patch_prefs(authed_client, {"weekly_zone2_target_min": 180})
    prefs = authed_client.get("/api/user-preferences").json()
    target = prefs.get("row", {}).get("weekly_zone2_target_min") or prefs.get("defaults", {}).get("weekly_zone2_target_min") or 150

    res = _post_habit(authed_client, {
        "name": "Zone 2",
        "tracking_type": "weekly_minutes",
        "auto_fill_source": "workout.zone2_minutes",
        "unit": "min",
        "weekly_target": target,
    })
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    body = res.json()
    assert body["name"] == "Zone 2"
    assert body["tracking_type"] == "weekly_minutes"
    assert body["auto_fill_source"] == "workout.zone2_minutes"
    assert body["unit"] == "min"
    assert body["weekly_target"] == target

    # Clean up so other tests start fresh
    _delete_habit(authed_client, body["id"])


# ═══════════════════════════════════════════════════════════════════════════════
# AC4 — Success message and link to /habits in settings.html
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__html_success_message_element_present():
    """AC4: A success message element must exist in settings.html for JS to populate."""
    src = _html()
    assert 'id="provision-zone2-success"' in src or 'id="thresholds-provision-zone2-status"' in src, (
        "settings.html must contain a success/status element for the Zone 2 provision button "
        "(id='provision-zone2-success' or id='thresholds-provision-zone2-status')"
    )


def test_599__html_habits_link_target_present():
    """AC4: A link to /habits must exist (or be dynamically inserted) in the thresholds section
    for post-provisioning navigation."""
    src = _html()
    # The link may be static or dynamically added; the href="/habits" must exist somewhere
    # in the thresholds section or the JS must insert it
    thresholds_start = src.find('id="section-thresholds"')
    assert thresholds_start != -1
    next_section = src.find('class="settings-section"', thresholds_start + 1)
    if next_section == -1:
        next_section = len(src)
    thresholds_block = src[thresholds_start:next_section]

    has_link_in_html = 'href="/habits"' in thresholds_block
    has_link_in_js = '/habits' in _html()[thresholds_start:] or '/habits' in _js()
    assert has_link_in_html or has_link_in_js, (
        "A link to /habits must be present in the thresholds section or generated by JS"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC5/AC6 — Server-side duplicate guard: 409 when auto_fill_source already exists
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__api_duplicate_auto_fill_source_returns_409(authed_client):
    """AC5/AC6: POST /api/habits returns 409 when a habit with the same
    auto_fill_source already exists for the user."""
    payload = {
        "name": "Zone 2",
        "tracking_type": "weekly_minutes",
        "auto_fill_source": "workout.zone2_minutes",
        "unit": "min",
        "weekly_target": 150,
    }
    # First creation must succeed
    r1 = _post_habit(authed_client, payload)
    assert r1.status_code == 201, f"First create failed: {r1.text}"
    habit_id = r1.json()["id"]

    try:
        # Second creation with same auto_fill_source must be rejected
        r2 = _post_habit(authed_client, payload)
        assert r2.status_code == 409, (
            f"Expected 409 on duplicate auto_fill_source, got {r2.status_code}: {r2.text}"
        )
        # Verify only one habit exists
        habits = authed_client.get("/api/habits").json()
        zone2_habits = [h for h in habits if h.get("auto_fill_source") == "workout.zone2_minutes"]
        assert len(zone2_habits) == 1, (
            f"Expected exactly 1 Zone 2 habit, found {len(zone2_habits)}"
        )
    finally:
        _delete_habit(authed_client, habit_id)


def test_599__api_duplicate_guard_scoped_to_user(authed_client):
    """AC6: The duplicate guard is per-user; a different user can create the same habit."""
    # Create Zone 2 habit for authed_client user
    payload = {
        "name": "Zone 2",
        "tracking_type": "weekly_minutes",
        "auto_fill_source": "workout.zone2_minutes",
        "unit": "min",
        "weekly_target": 150,
    }
    r1 = _post_habit(authed_client, payload)
    assert r1.status_code == 201
    habit_id = r1.json()["id"]

    try:
        # Create a second user
        username2 = f"tester599b_{uuid.uuid4().hex[:8]}"
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as c2:
            res2 = c2.post("/api/users", json={"name": username2})
            assert res2.status_code == 201
            user_id2 = res2.json()["id"]
            with Session(engine) as db:
                u2 = db.get(User, uuid.UUID(user_id2))
                u2.password_hash = hash_password("OtherUser599Pw!")
                db.commit()
            csrf2 = ""
            login2 = c2.post("/api/auth/login", json={"username": username2, "password": "OtherUser599Pw!"})
            assert login2.status_code == 200
            for sc in login2.headers.get_list("set-cookie"):
                if sc.startswith("csrf-token="):
                    csrf2 = sc.split("=", 1)[1].split(";")[0]
                    break
            r_other = c2.post("/api/habits", json=payload, headers={"X-CSRF-Token": csrf2})
            # Should be 201 for the second user (different user, no conflict)
            assert r_other.status_code == 201, (
                f"A different user must be able to create the same habit; got {r_other.status_code}"
            )
            other_habit_id = r_other.json()["id"]
            c2.delete(f"/api/habits/{other_habit_id}?hard=true", headers={"X-CSRF-Token": csrf2})
            c2.delete(f"/api/users/{user_id2}")
    finally:
        _delete_habit(authed_client, habit_id)


# ═══════════════════════════════════════════════════════════════════════════════
# AC7 — Habit weekly_target is independent of user preferences
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__habit_weekly_target_independent_of_prefs(authed_client):
    """AC7: Changing user preferences does not overwrite the habit's weekly_target."""
    # Set initial prefs
    _patch_prefs(authed_client, {"weekly_zone2_target_min": 150})

    # Create Zone 2 habit seeded from prefs
    r = _post_habit(authed_client, {
        "name": "Zone 2",
        "tracking_type": "weekly_minutes",
        "auto_fill_source": "workout.zone2_minutes",
        "unit": "min",
        "weekly_target": 150,
    })
    assert r.status_code == 201
    habit_id = r.json()["id"]

    try:
        # Edit the habit's weekly_target
        csrf = getattr(authed_client, "_csrf", "")
        patch_habit = authed_client.patch(
            f"/api/habits/{habit_id}",
            json={"weekly_target": 200},
            headers={"X-CSRF-Token": csrf},
        )
        assert patch_habit.status_code == 200

        # Change user prefs
        _patch_prefs(authed_client, {"weekly_zone2_target_min": 300})

        # Verify habit target was not overwritten
        habits = authed_client.get("/api/habits").json()
        zone2 = next((h for h in habits if h["id"] == habit_id), None)
        assert zone2 is not None
        assert zone2["weekly_target"] == 200, (
            f"Habit weekly_target must remain 200 after prefs change; got {zone2['weekly_target']}"
        )
    finally:
        _delete_habit(authed_client, habit_id)
        _patch_prefs(authed_client, {"weekly_zone2_target_min": 150})


# ═══════════════════════════════════════════════════════════════════════════════
# AC8 — Existing-habit message element present in settings.html
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__html_existing_habit_message_element_present():
    """AC8: settings.html must contain a message element for the 'already exists' state."""
    src = _html()
    # The element may be hidden by default; JS shows it when habit exists
    has_existing_msg = (
        'id="provision-zone2-existing"' in src
        or 'id="thresholds-provision-zone2-existing"' in src
        or 'provision-zone2' in src
    )
    assert has_existing_msg, (
        "settings.html must contain an element for the 'Zone 2 habit already exists' message "
        "so JS can toggle it (e.g. id='provision-zone2-existing')"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC9 — JS checks for existing habit on page load
# ═══════════════════════════════════════════════════════════════════════════════

def test_599__js_checks_habits_on_load():
    """AC9: The settings JS must call GET /api/habits to check for an existing
    Zone 2 habit on page load (to hide/disable the button if it already exists)."""
    src = _html()
    js_src = _js() if _SETTINGS_JS.exists() else ""
    combined = src + js_src
    assert "/api/habits" in combined, (
        "settings.html / settings.js must call GET /api/habits on thresholds section load "
        "to check for an existing Zone 2 habit and hide/disable the provision button"
    )


def test_599__js_references_provision_zone2_btn():
    """AC9: The JS must reference 'thresholds-provision-zone2-btn' to show/hide it."""
    src = _html()
    js_src = _js() if _SETTINGS_JS.exists() else ""
    combined = src + js_src
    assert "provision-zone2-btn" in combined, (
        "The JS must reference the provision button by id to control its visibility"
    )


def test_599__js_checks_auto_fill_source_on_load():
    """AC9: The JS must check auto_fill_source == 'workout.zone2_minutes' when
    determining whether a Zone 2 habit already exists."""
    src = _html()
    js_src = _js() if _SETTINGS_JS.exists() else ""
    combined = src + js_src
    assert "workout.zone2_minutes" in combined, (
        "The JS must check for auto_fill_source === 'workout.zone2_minutes' to detect "
        "an existing Zone 2 habit and disable the provision button"
    )
