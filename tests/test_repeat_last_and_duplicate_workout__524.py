"""Tests for issue #524: Add repeat-last and duplicate workout to log.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria:
  AC1 — A "Repeat Last Workout" action is visible and functional directly on the
        /log page without navigating away (no More-menu hop on the form page).
  AC2 — Clicking it pre-fills a NEW entry with the most recent workout's
        exercises, sets, reps, and weights (wires to the existing
        repeatLastWorkout entry point on /training).
  AC3 — Each workout entry's detail panel exposes a "Duplicate to Date" action.
  AC4 — Duplicate to Date opens a date-picker; confirming creates a full copy of
        that workout on the chosen date (POST /api/workouts/{id}/duplicate).
  AC5 — The duplicated entry appears for the target date and is INDEPENDENTLY
        editable (original unchanged when the copy is edited).
  AC6 — With no previous workout, Repeat Last Workout is disabled/hidden with an
        appropriate empty-state message.
  AC7 — Both actions are reachable on mobile viewport (<= 768 px).

Frontend ACs are verified by static analysis of the page/JS source (the same
style used for issue #522's inline quick-add modal). Backend ACs (AC4/AC5) are
verified against a live server (the same style used for issue #318).
"""
import datetime
import os
import pathlib
import re
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession

from backend.auth import (
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.models import User
from tests._admin_helpers import admin_cookies as _admin_cookies

# ── Source under test ────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOG_HTML = (_ROOT / "frontend" / "pages" / "training-log.html").read_text()
_LOG_JS = (_ROOT / "frontend" / "js" / "training-log.js").read_text()
_TRAINING_JS = (_ROOT / "frontend" / "js" / "training.js").read_text()
_MAIN_PY = (_ROOT / "backend" / "main.py").read_text()


def _func_body(src, signature, span=4000):
    """Return a chunk of source starting at `signature` (best-effort window)."""
    idx = src.find(signature)
    assert idx != -1, f"{signature!r} not found"
    return src[idx: idx + span]


# ─────────────────────────────────────────────────────────────────────────────
# AC1 — Repeat Last Workout visible + functional directly on /log
# ─────────────────────────────────────────────────────────────────────────────

def test_ac1_repeat_button_present_on_log_page():
    assert 'id="log-repeat-last-btn"' in _LOG_HTML, (
        "training-log.html must expose a #log-repeat-last-btn on the /log page"
    )


def test_ac1_repeat_button_label():
    idx = _LOG_HTML.index('id="log-repeat-last-btn"')
    # the visible label lives between the opening and closing tag
    snippet = _LOG_HTML[idx: idx + 160]
    assert "Repeat last" in snippet, (
        "Repeat button must be labelled with 'Repeat last'"
    )


def test_ac1_repeat_button_in_page_header_actions():
    """Lives in the page header action bar — visible without leaving /log."""
    idx = _LOG_HTML.index('id="log-repeat-last-btn"')
    header_start = _LOG_HTML.rfind("log-page-header-actions", 0, idx)
    assert header_start != -1, (
        "Repeat button must sit in .log-page-header-actions so it is visible "
        "directly on /log without navigating away"
    )


def test_ac1_repeat_button_click_handler_wired():
    assert "log-repeat-last-btn" in _LOG_JS, (
        "training-log.js must wire the #log-repeat-last-btn click handler"
    )


def test_ac1_repeat_navigates_to_existing_entry_point():
    """Wires to the existing repeatLastWorkout flow on /training (out-of-scope
    forbids re-implementing the repeat logic)."""
    assert "/training?repeat" in _LOG_JS, (
        "Repeat action must navigate to the /training?repeat entry point"
    )
    # No re-implemented repeat endpoint introduced.
    assert "/api/workouts/repeat" not in _LOG_JS
    assert "/api/repeat" not in _LOG_JS


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — Pre-fills a new entry with the previous workout's data
# ─────────────────────────────────────────────────────────────────────────────

def test_ac2_training_js_handles_repeat_param():
    assert "repeat" in _TRAINING_JS, "training.js must read the repeat URL param"
    # The param handler must invoke the existing prefill function.
    assert "repeatLastWorkout" in _TRAINING_JS


def test_ac2_repeat_param_triggers_prefill_on_load():
    """On /training?repeat=1 the form auto-runs repeatLastWorkout()."""
    # Look for a param read for 'repeat' followed by a repeatLastWorkout() call.
    assert "get('repeat')" in _TRAINING_JS or 'get("repeat")' in _TRAINING_JS, (
        "training.js must read the 'repeat' query param"
    )
    # repeatLastWorkout already prefills exercises/sets/reps/weights via
    # addExerciseRow; confirm that prefill path is intact.
    fn = _func_body(_TRAINING_JS, "function repeatLastWorkout")
    assert "addExerciseRow" in fn, (
        "repeatLastWorkout must populate exercise rows (sets/reps/weights)"
    )
    assert "/api/workouts/" in fn, (
        "repeatLastWorkout must fetch full workout detail (exercises included)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — Detail panel exposes a Duplicate to Date action
# ─────────────────────────────────────────────────────────────────────────────

def test_ac3_duplicate_button_present_in_detail_panel():
    assert 'id="dp-duplicate-btn"' in _LOG_HTML, (
        "Detail panel must expose a #dp-duplicate-btn action"
    )


def test_ac3_duplicate_button_in_actions_bar():
    idx = _LOG_HTML.index('id="dp-duplicate-btn"')
    bar_start = _LOG_HTML.rfind("dp-actions-bar", 0, idx)
    assert bar_start != -1, "Duplicate action must live in the .dp-actions-bar"


def test_ac3_duplicate_button_labelled():
    idx = _LOG_HTML.index('id="dp-duplicate-btn"')
    snippet = _LOG_HTML[idx: idx + 160]
    assert "Duplicate" in snippet, "Action must be labelled 'Duplicate'"


def test_ac3_duplicate_handler_wired():
    assert "dp-duplicate-btn" in _LOG_JS, (
        "training-log.js must wire the #dp-duplicate-btn click handler"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — Date picker + POST creates a full copy on the chosen date
# ─────────────────────────────────────────────────────────────────────────────

def test_ac4_duplicate_uses_date_picker_input():
    assert 'id="dup-date-input"' in _LOG_HTML, (
        "A date-picker input (#dup-date-input) must be present for Duplicate"
    )
    idx = _LOG_HTML.index('id="dup-date-input"')
    snippet = _LOG_HTML[max(0, idx - 80): idx + 80]
    assert 'type="date"' in snippet, "Duplicate picker must be an HTML date input"


def test_ac4_duplicate_posts_to_duplicate_endpoint():
    assert "/duplicate" in _LOG_JS, (
        "Duplicate flow must POST to the /api/workouts/{id}/duplicate endpoint"
    )


def test_ac4_backend_duplicate_endpoint_defined():
    assert '@app.post("/api/workouts/{workout_id}/duplicate"' in _MAIN_PY, (
        "backend must define POST /api/workouts/{workout_id}/duplicate"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC6 — Empty state when no previous workout
# ─────────────────────────────────────────────────────────────────────────────

def test_ac6_repeat_disabled_when_no_workouts():
    """training-log.js must toggle the repeat button's disabled state based on
    whether any workouts exist."""
    assert "log-repeat-last-btn" in _LOG_JS
    # The button is disabled (or hidden) when there is no workout history.
    assert "disabled" in _LOG_JS, (
        "Repeat button must be disabled/hidden when no workout exists"
    )


def test_ac6_empty_state_message_present():
    """An appropriate empty-state message/title is surfaced for the disabled
    repeat affordance."""
    assert "No previous workout" in _LOG_JS or "no previous workout" in _LOG_JS, (
        "An empty-state message must explain why Repeat is unavailable"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC7 — Mobile reachability (<= 768 px)
# ─────────────────────────────────────────────────────────────────────────────

def _mobile_media_blocks(css, viewport=768):
    """Return the bodies of every @media (max-width: Npx) block whose breakpoint
    is >= `viewport` (i.e. a `viewport`-wide screen is inside the query)."""
    blocks = []
    for m in re.finditer(r"@media[^{]*max-width:\s*(\d+)px[^{]*\{", css):
        if int(m.group(1)) < viewport:
            continue
        # brace-match the media block body
        depth = 0
        start = m.end() - 1
        for i in range(start, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(css[start: i + 1])
                    break
    return blocks


def test_ac7_actions_live_in_responsive_containers():
    """Both new affordances sit inside containers (.log-page-header-actions and
    .dp-actions-bar) that are restyled by a media query covering a <=768px
    viewport, so they remain reachable on mobile."""
    # Repeat button lives in the header-actions row; Duplicate in the actions bar.
    repeat_idx = _LOG_HTML.index('id="log-repeat-last-btn"')
    assert _LOG_HTML.rfind("log-page-header-actions", 0, repeat_idx) != -1
    dup_idx = _LOG_HTML.index('id="dp-duplicate-btn"')
    assert _LOG_HTML.rfind("dp-actions-bar", 0, dup_idx) != -1

    mobile = _mobile_media_blocks(_LOG_HTML, 768)
    assert mobile, "Expected a <=768px-covering media query on the log page"
    assert any("log-page-header" in b for b in mobile), (
        "The page header (holding Repeat last) must restyle for mobile"
    )
    assert any("dp-actions-bar" in b for b in mobile), (
        "The detail-panel actions bar (holding Duplicate) must restyle for mobile"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC4 / AC5 — Backend duplicate behaviour (live server)
# ═════════════════════════════════════════════════════════════════════════════

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "dup-wkt-524-pw"
TODAY = datetime.date.today()

_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    name = f"DupWkt524_{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]

    pw_hash = hash_password(_TEST_PASSWORD)
    with DBSession(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.password_hash = pw_hash
        session.commit()

    login_res = client.post(
        "/api/auth/login",
        json={"username": name, "password": _TEST_PASSWORD},
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
    yield {"id": user_id, "name": name, "client": authed}
    authed.close()
    client.delete(f"/api/users/{user_id}", cookies=_admin_cookies())


def _make_workout(authed, day):
    body = {
        "name": "Squat session 524",
        "workout_date": day.isoformat(),
        "workout_type": "lift",
        "remarks": "heavy day",
        "tss": 42.0,
        "exercises": [
            {"name": "Back squat", "sets": 5, "reps": 5, "weight_kg": 100.0, "rpe": 8},
            {"name": "Romanian deadlift", "sets": 3, "reps": 8, "weight_kg": 80.0},
        ],
    }
    res = authed.post("/api/workouts", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_ac4_duplicate_creates_copy_on_chosen_date(auth_user):
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=3))
    target = (TODAY - datetime.timedelta(days=1)).isoformat()

    res = authed.post(f"/api/workouts/{src['id']}/duplicate", json={"workout_date": target})
    assert res.status_code == 201, res.text
    dup = res.json()

    # New, distinct record on the chosen date.
    assert dup["id"] != src["id"], "Duplicate must be a new record"
    assert dup["workout_date"] == target, "Duplicate must land on the chosen date"

    # Full copy: name, type, remarks, tss, and every exercise (sets/reps/weights).
    assert dup["name"] == src["name"]
    assert dup["workout_type"] == src["workout_type"]
    assert dup["remarks"] == src["remarks"]
    assert dup["tss"] == src["tss"]
    assert len(dup["exercises"]) == len(src["exercises"]) == 2
    dup_ex = sorted(dup["exercises"], key=lambda e: e["name"])
    src_ex = sorted(src["exercises"], key=lambda e: e["name"])
    for d, s in zip(dup_ex, src_ex):
        assert d["name"] == s["name"]
        assert d["sets"] == s["sets"]
        assert d["reps"] == s["reps"]
        assert d["weight_kg"] == s["weight_kg"]

    authed.delete(f"/api/workouts/{dup['id']}")
    authed.delete(f"/api/workouts/{src['id']}")


def test_ac4_duplicate_rejects_invalid_date(auth_user):
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=2))
    res = authed.post(f"/api/workouts/{src['id']}/duplicate", json={"workout_date": "13/2025"})
    assert res.status_code == 422, res.text
    authed.delete(f"/api/workouts/{src['id']}")


def test_ac4_duplicate_rejects_future_date(auth_user):
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=2))
    future = (TODAY + datetime.timedelta(days=5)).isoformat()
    res = authed.post(f"/api/workouts/{src['id']}/duplicate", json={"workout_date": future})
    assert res.status_code == 422, res.text
    authed.delete(f"/api/workouts/{src['id']}")


def test_ac4_duplicate_unknown_workout_404(auth_user):
    authed = auth_user["client"]
    res = authed.post(
        f"/api/workouts/{uuid.uuid4()}/duplicate",
        json={"workout_date": TODAY.isoformat()},
    )
    assert res.status_code == 404, res.text


def test_ac4_duplicate_bad_id_400(auth_user):
    authed = auth_user["client"]
    res = authed.post(
        "/api/workouts/not-a-uuid/duplicate",
        json={"workout_date": TODAY.isoformat()},
    )
    assert res.status_code == 400, res.text


def test_ac5_duplicate_is_independent(auth_user):
    """Editing the duplicate must not touch the original (independent records)."""
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=4))
    target = (TODAY - datetime.timedelta(days=1)).isoformat()

    dup = authed.post(
        f"/api/workouts/{src['id']}/duplicate", json={"workout_date": target}
    ).json()

    # Edit only the duplicate.
    patch = authed.patch(
        f"/api/workouts/{dup['id']}", json={"name": "Edited copy 524", "tss": 99.0}
    )
    assert patch.status_code == 200, patch.text

    # Original is unchanged.
    orig = authed.get(f"/api/workouts/{src['id']}").json()
    assert orig["name"] == "Squat session 524"
    assert orig["tss"] == 42.0

    # Duplicate appears on the target date in the list.
    listing = authed.get(f"/api/workouts?from={target}&to={target}")
    assert listing.status_code == 200
    ids = [w["id"] for w in listing.json()]
    assert dup["id"] in ids, "Duplicate must appear in the log for its target date"

    authed.delete(f"/api/workouts/{dup['id']}")
    authed.delete(f"/api/workouts/{src['id']}")


def test_ac5_duplicate_not_linked_to_strava(auth_user):
    """A duplicate is a manual entry — independently editable, not tied to a
    synced source (so reconcile cannot overwrite it)."""
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=5))
    target = (TODAY - datetime.timedelta(days=1)).isoformat()
    dup = authed.post(
        f"/api/workouts/{src['id']}/duplicate", json={"workout_date": target}
    ).json()
    assert dup.get("strava_activity_pk") is None
    assert dup.get("stryd_activity_pk") is None
    authed.delete(f"/api/workouts/{dup['id']}")
    authed.delete(f"/api/workouts/{src['id']}")
