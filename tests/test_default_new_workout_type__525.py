"""Tests for issue #525: Default new workout type to most recent selection.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria:
  AC1 — On form open, workout type pre-selects the user's most recently logged
        workout type.
  AC2 — If no prior workout exists, the default remains the form's built-in
        default (the quick-add Type select has no literal "Strength" option; its
        built-in default is the empty "Select…" placeholder, so "default remains
        Strength" is satisfied by leaving that built-in default untouched).
  AC3 — The user can override the pre-selected type before submitting.
  AC4 — Selection is persisted per user (not per browser session): the default
        is derived from the user's own workout history on the server, scoped to
        the session user — never localStorage/sessionStorage, never cross-user.
  AC5 — The pre-selected value is visually identical to a manual selection (no
        special indicator).

The default is sourced from a new backend endpoint:
  GET /api/workouts/recent-type -> {"workout_type": <raw type or null>}

Backend ACs (AC1/AC2/AC4) are verified against a live server (the same style as
issue #524/#318). Frontend wiring ACs (AC1/AC3/AC4/AC5) are verified by static
analysis of the page/JS source (the same style as issue #522/#524).
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

# ── Source under test ────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOG_HTML = (_ROOT / "frontend" / "pages" / "training-log.html").read_text()
_LOG_JS = (_ROOT / "frontend" / "js" / "training-log.js").read_text()
_MAIN_PY = (_ROOT / "backend" / "main.py").read_text()


def _func_body(src, signature, span=2000):
    """Return a chunk of source starting at `signature` (best-effort window)."""
    idx = src.find(signature)
    assert idx != -1, f"{signature!r} not found"
    return src[idx: idx + span]


def _js_func(src, name):
    """Return exactly one JS function body (brace-matched), so assertions never
    bleed into the following function."""
    sig = "function " + name
    start = src.find(sig)
    assert start != -1, f"{sig!r} not found"
    brace = src.find("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start: i + 1]
    return src[start:]


# ═════════════════════════════════════════════════════════════════════════════
# Static analysis — frontend wiring
# ═════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# AC1 — Form open pre-selects the most recent type
# ─────────────────────────────────────────────────────────────────────────────

def test_ac1_backend_recent_type_endpoint_defined():
    assert '@app.get("/api/workouts/recent-type")' in _MAIN_PY, (
        "backend must define GET /api/workouts/recent-type"
    )


def test_ac1_recent_type_route_registered_before_workout_id_route():
    """The literal /recent-type route must be registered before the
    /api/workouts/{workout_id} catch-all, otherwise FastAPI captures
    'recent-type' as a workout id and the endpoint 400s."""
    recent_idx = _MAIN_PY.find('@app.get("/api/workouts/recent-type")')
    byid_idx = _MAIN_PY.find('@app.get("/api/workouts/{workout_id}")')
    assert recent_idx != -1 and byid_idx != -1
    assert recent_idx < byid_idx, (
        "/api/workouts/recent-type must be declared before "
        "/api/workouts/{workout_id}"
    )


def test_ac1_open_form_prefills_type_from_endpoint():
    """openQuickAdd must trigger a prefill that reads the recent-type endpoint."""
    body = _js_func(_LOG_JS, "openQuickAdd")
    assert "prefillDefaultWorkoutType" in body, (
        "openQuickAdd must call prefillDefaultWorkoutType() on form open"
    )
    prefill = _js_func(_LOG_JS, "prefillDefaultWorkoutType")
    assert "/api/workouts/recent-type" in prefill, (
        "prefill must fetch the most recent type from /api/workouts/recent-type"
    )
    assert "qa-type" in prefill, "prefill must target the qa-type select"


def test_ac1_prefill_sets_select_value():
    """The fetched type must be applied to the select's value."""
    prefill = _js_func(_LOG_JS, "prefillDefaultWorkoutType")
    assert re.search(r"\.value\s*=", prefill), (
        "prefill must assign the resolved type to the select's value"
    )
    # The raw stored type is normalized onto the canonical option keys.
    assert "normalizeTypeKey" in prefill, (
        "prefill must normalize the stored type onto canonical option keys"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — No prior workout -> built-in default retained
# ─────────────────────────────────────────────────────────────────────────────

def test_ac2_builtin_default_is_the_placeholder():
    """The quick-add Type select's built-in default is the empty placeholder
    (no literal 'Strength' option exists); the prefill must not change it when
    there is no history."""
    idx = _LOG_HTML.index('id="qa-type"')
    snippet = _LOG_HTML[idx: idx + 320]
    # First option is the empty placeholder — the built-in default.
    assert '<option value="">' in snippet, (
        "qa-type must keep its empty placeholder as the built-in default"
    )


def test_ac2_prefill_noop_when_no_history():
    """When the endpoint returns no type, prefill must leave the select alone."""
    prefill = _js_func(_LOG_JS, "prefillDefaultWorkoutType")
    # Guards against a missing/null workout_type before touching the select.
    assert re.search(r"!\s*data\.workout_type|data\.workout_type\s*\)", prefill), (
        "prefill must bail when workout_type is absent (no history)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — User can override the pre-selected type
# ─────────────────────────────────────────────────────────────────────────────

def test_ac3_select_not_disabled_by_prefill():
    """Prefill must not lock the select — the user can still change it."""
    prefill = _js_func(_LOG_JS, "prefillDefaultWorkoutType")
    assert "disabled" not in prefill, (
        "prefill must not disable the type select"
    )
    assert "readonly" not in prefill.lower()


def test_ac3_submit_reads_live_select_value():
    """Submission reads whatever is in qa-type at submit time, so a manual
    override wins over the pre-selected default."""
    assert "workout_type: (qaEl('qa-type').value" in _LOG_JS, (
        "submit must read the live qa-type value (override wins)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — Persisted per user, not per browser session
# ─────────────────────────────────────────────────────────────────────────────

def test_ac4_default_comes_from_server_not_storage():
    """The default must be server-derived (per user), never browser storage."""
    prefill = _js_func(_LOG_JS, "prefillDefaultWorkoutType")
    assert "localStorage" not in prefill, (
        "default type must not be read from localStorage (that is per-browser)"
    )
    assert "sessionStorage" not in prefill, (
        "default type must not be read from sessionStorage"
    )


def test_ac4_endpoint_scoped_to_session_user():
    """The endpoint must resolve the user from the session, not a client id."""
    body = _func_body(_MAIN_PY, "def get_recent_workout_type", span=1600)
    assert "resolve_user" in body, (
        "recent-type must derive the user from the session via resolve_user"
    )
    assert "Workout.user_id == user.id" in body, (
        "recent-type must filter workouts to the session user"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC5 — Pre-selected value visually identical to a manual selection
# ─────────────────────────────────────────────────────────────────────────────

def test_ac5_no_special_indicator_added():
    """Prefill must only set the value — no marker class/attribute/dataset that
    would make a pre-selected type look different from a manual one."""
    prefill = _js_func(_LOG_JS, "prefillDefaultWorkoutType")
    assert "classList.add" not in prefill, "prefill must not add a marker class"
    assert "setAttribute" not in prefill, "prefill must not add a marker attribute"
    assert "dataset" not in prefill, "prefill must not tag the select via dataset"


# ═════════════════════════════════════════════════════════════════════════════
# Live server — backend behaviour (AC1 / AC2 / AC4)
# ═════════════════════════════════════════════════════════════════════════════

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "default-type-525-pw"
TODAY = datetime.date.today()

_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _make_authed_user(label):
    """Create + log in a user on a throwaway bare client, returning an
    authenticated (session + CSRF) client.

    Each call uses its OWN bare client so login cookies never pollute a shared
    cookie jar — a shared jar would later flip anonymous calls to authenticated
    and force CSRF on user creation.
    """
    name = f"DefType525_{label}_{_RUN}"
    with httpx.Client(base_url=BASE, timeout=10) as bare:
        res = bare.post("/api/users", json={"name": name})
        assert res.status_code == 201, res.text
        user_id = res.json()["id"]

        pw_hash = hash_password(_TEST_PASSWORD)
        with DBSession(engine) as session:
            user = session.get(User, uuid.UUID(user_id))
            assert user is not None
            user.password_hash = pw_hash
            session.commit()

        login_res = bare.post(
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
    return {"id": user_id, "name": name, "client": authed}


@pytest.fixture(scope="module")
def auth_user():
    u = _make_authed_user("main")
    yield u
    u["client"].delete(f"/api/users/{u['id']}")
    u["client"].close()


def _make_workout(authed, day, wtype):
    body = {
        "name": f"{wtype} session 525",
        "workout_date": day.isoformat(),
        "workout_type": wtype,
    }
    res = authed.post("/api/workouts", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_ac1_recent_type_returns_most_recent(auth_user):
    """AC1: endpoint returns the user's most recently logged type."""
    authed = auth_user["client"]
    older = _make_workout(authed, TODAY - datetime.timedelta(days=5), "bike")
    newer = _make_workout(authed, TODAY - datetime.timedelta(days=1), "run")

    res = authed.get("/api/workouts/recent-type")
    assert res.status_code == 200, res.text
    assert res.json()["workout_type"] == "run", (
        "must return the most recent (by date) workout type"
    )

    authed.delete(f"/api/workouts/{older['id']}")
    authed.delete(f"/api/workouts/{newer['id']}")


def test_ac1_recent_type_follows_latest_change(auth_user):
    """AC1 (UAT step 3-4): logging a newer type updates the default."""
    authed = auth_user["client"]
    first = _make_workout(authed, TODAY - datetime.timedelta(days=2), "run")
    assert authed.get("/api/workouts/recent-type").json()["workout_type"] == "run"

    second = _make_workout(authed, TODAY, "lift")
    assert authed.get("/api/workouts/recent-type").json()["workout_type"] == "lift", (
        "default must follow the latest logged type"
    )

    authed.delete(f"/api/workouts/{first['id']}")
    authed.delete(f"/api/workouts/{second['id']}")


def test_ac2_no_history_returns_null():
    """AC2 (UAT step 5): a brand-new user with no history gets null, so the form
    keeps its built-in default."""
    fresh = _make_authed_user("fresh")
    try:
        res = fresh["client"].get("/api/workouts/recent-type")
        assert res.status_code == 200, res.text
        assert res.json()["workout_type"] is None, (
            "a user with no workout history must get null (built-in default)"
        )
    finally:
        fresh["client"].delete(f"/api/users/{fresh['id']}")
        fresh["client"].close()


def test_ac4_recent_type_is_per_user():
    """AC4: the default is per user — one user's recent type never bleeds into
    another's."""
    user_a = _make_authed_user("a")
    user_b = _make_authed_user("b")
    try:
        wa = _make_workout(user_a["client"], TODAY, "bike")
        # user_b has no workouts -> must still be null, unaffected by user_a.
        res_b = user_b["client"].get("/api/workouts/recent-type")
        assert res_b.json()["workout_type"] is None, (
            "user B's default must not reflect user A's history"
        )
        # user_a sees their own.
        res_a = user_a["client"].get("/api/workouts/recent-type")
        assert res_a.json()["workout_type"] == "bike"
        user_a["client"].delete(f"/api/workouts/{wa['id']}")
    finally:
        user_a["client"].delete(f"/api/users/{user_a['id']}")
        user_b["client"].delete(f"/api/users/{user_b['id']}")
        user_a["client"].close()
        user_b["client"].close()


def test_ac4_recent_type_requires_auth():
    """AC4: anonymous requests are rejected (identity from session, not client)."""
    with httpx.Client(base_url=BASE, timeout=10) as anon:
        res = anon.get("/api/workouts/recent-type")
        assert res.status_code == 401, res.text
