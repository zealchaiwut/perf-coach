"""Tests for issue #320: Workout templates — Save as template + Start from template.

Acceptance criteria verified:
(a) HTML: #save-template-btn present and enabled (no disabled attr, no 'Coming in sprint-5')
(b) HTML: #template-picker-btn present for starting from a template
(c) HTML: stub disabled 'Coming in sprint-5' buttons removed entirely
(d) HTML: 'Add section' stub button removed
(e) JS: saveTemplate function defined and wired to #save-template-btn
(f) JS: openTemplatePicker function defined and wired to #template-picker-btn
(g) JS: applyTemplate function prefills exercise rows
(h) API: POST /api/workout-templates creates a template (201)
(i) API: GET /api/workout-templates lists templates for a user
(j) API: POST validates name required (422)
(k) API: POST validates at least one named exercise required (422)
(l) API: templates are user-scoped (other user cannot see them)
(m) Migration: workout_templates table schema has required columns
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session as DBSession

from backend.auth import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.models import User

# ── Path detection: prefer tester root post-merge, coder root pre-merge ──────
_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_TESTER_ROOT, _CODER_ROOT):
        js = root / "frontend" / "js" / "training.js"
        if js.exists() and "saveTemplate" in js.read_text():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_TRAINING_JS = (_ROOT / "frontend" / "js" / "training.js").read_text()
_TRAINING_HTML = (_ROOT / "frontend" / "pages" / "training.html").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today().isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "wkt-tpl-320-pw"

_env_vals = dotenv_values(_TESTER_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def _make_authed_client(client, name):
    res = client.post("/api/users", json={"name": name})
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
    return user_id, authed


@pytest.fixture(scope="module")
def auth_user(client):
    user_id, authed = _make_authed_client(client, f"TplUser320_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    client.delete(f"/api/users/{user_id}")


@pytest.fixture(scope="module")
def other_user(client):
    user_id, authed = _make_authed_client(client, f"TplOther320_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    client.delete(f"/api/users/{user_id}")


_SAMPLE_EXERCISES = [
    {"name": "Bench Press", "sets": 3, "reps": 8, "weight_kg": 80.0, "duration": None, "rpe": 8},
    {"name": "Squat", "sets": 4, "reps": 5, "weight_kg": 100.0, "duration": None, "rpe": 9},
]


# ── (a) HTML: #save-template-btn present and not disabled ────────────────────

def test_save_template_btn_present():
    assert 'id="save-template-btn"' in _TRAINING_HTML, (
        "#save-template-btn must be in training.html"
    )


def test_save_template_btn_not_disabled():
    idx = _TRAINING_HTML.index('id="save-template-btn"')
    snippet = _TRAINING_HTML[max(0, idx - 200): idx + 200]
    assert "disabled" not in snippet, (
        "#save-template-btn must not be disabled"
    )


def test_save_template_btn_no_sprint5_label():
    assert "Coming in sprint-5" not in _TRAINING_HTML, (
        "'Coming in sprint-5' placeholder text must be removed"
    )


# ── (b) HTML: #template-picker-btn present ───────────────────────────────────

def test_template_picker_btn_present():
    assert 'id="template-picker-btn"' in _TRAINING_HTML, (
        "#template-picker-btn must be in training.html"
    )


def test_template_picker_btn_label():
    idx = _TRAINING_HTML.index('id="template-picker-btn"')
    snippet = _TRAINING_HTML[idx: idx + 150]
    assert "template" in snippet.lower(), (
        "#template-picker-btn should mention 'template' in its label"
    )


# ── (c-d) HTML: stubs removed ────────────────────────────────────────────────

def test_add_section_stub_removed():
    assert "add-section-btn" not in _TRAINING_HTML, (
        "'Add section' stub button must be removed from training.html"
    )


# ── (e) JS: saveTemplate defined and wired ───────────────────────────────────

def test_js_has_saveTemplate_function():
    assert "function saveTemplate" in _TRAINING_JS, (
        "training.js must define saveTemplate()"
    )


def test_js_save_template_btn_wired():
    assert "save-template-btn" in _TRAINING_JS, (
        "training.js must reference save-template-btn"
    )
    assert "saveTemplate" in _TRAINING_JS


# ── (f) JS: openTemplatePicker defined and wired ─────────────────────────────

def test_js_has_openTemplatePicker_function():
    assert "function openTemplatePicker" in _TRAINING_JS, (
        "training.js must define openTemplatePicker()"
    )


def test_js_template_picker_btn_wired():
    assert "template-picker-btn" in _TRAINING_JS, (
        "training.js must reference template-picker-btn"
    )


# ── (g) JS: applyTemplate defined ────────────────────────────────────────────

def test_js_has_applyTemplate_function():
    assert "function applyTemplate" in _TRAINING_JS, (
        "training.js must define applyTemplate()"
    )


def test_js_applyTemplate_calls_addExerciseRow():
    assert "addExerciseRow" in _TRAINING_JS[_TRAINING_JS.index("function applyTemplate"):], (
        "applyTemplate must call addExerciseRow to prefill exercises"
    )


# ── (h) API: POST /api/workout-templates creates a template ──────────────────

def test_post_template_creates_201(auth_user):
    res = auth_user["client"].post(
        "/api/workout-templates",
        json={"name": "Push Day A", "exercises": _SAMPLE_EXERCISES},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Push Day A"
    assert len(body["exercises"]) == 2
    assert body["exercises"][0]["name"] == "Bench Press"
    assert "id" in body
    assert "created_at" in body


def test_post_template_persists_exercise_fields(auth_user):
    res = auth_user["client"].post(
        "/api/workout-templates",
        json={
            "name": "Leg Day",
            "exercises": [{"name": "Deadlift", "sets": 3, "reps": 5, "weight_kg": 120.0}],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    ex = body["exercises"][0]
    assert ex["name"] == "Deadlift"
    assert ex["sets"] == 3
    assert ex["reps"] == 5
    assert float(ex["weight_kg"]) == 120.0


# ── (i) API: GET /api/workout-templates lists templates ──────────────────────

def test_get_templates_lists_saved(auth_user):
    res = auth_user["client"].get("/api/workout-templates")
    assert res.status_code == 200, res.text
    templates = res.json()
    assert isinstance(templates, list)
    names = [t["name"] for t in templates]
    assert "Push Day A" in names
    assert "Leg Day" in names


def test_get_templates_returns_most_recent_first(auth_user):
    res = auth_user["client"].get("/api/workout-templates")
    assert res.status_code == 200
    templates = res.json()
    if len(templates) >= 2:
        assert templates[0]["created_at"] >= templates[1]["created_at"], (
            "Templates should be ordered most-recent first"
        )


# ── (j) API: POST validates name required ────────────────────────────────────

def test_post_template_requires_name(auth_user):
    res = auth_user["client"].post(
        "/api/workout-templates",
        json={"name": "", "exercises": _SAMPLE_EXERCISES},
    )
    assert res.status_code == 422, res.text


# ── (k) API: POST validates at least one named exercise ──────────────────────

def test_post_template_requires_exercises(auth_user):
    res = auth_user["client"].post(
        "/api/workout-templates",
        json={"name": "Empty", "exercises": []},
    )
    assert res.status_code == 422, res.text


def test_post_template_requires_named_exercise(auth_user):
    res = auth_user["client"].post(
        "/api/workout-templates",
        json={"name": "NoName", "exercises": [{"name": "", "sets": 3}]},
    )
    assert res.status_code == 422, res.text


# ── (l) API: user-scoped — other user cannot see templates ───────────────────

def test_templates_are_user_scoped(auth_user, other_user):
    res = other_user["client"].get("/api/workout-templates")
    assert res.status_code == 200, res.text
    names = [t["name"] for t in res.json()]
    assert "Push Day A" not in names, (
        "Templates must not be visible to other users"
    )


# ── (m) Migration: workout_templates table schema ────────────────────────────

def test_workout_templates_table_exists():
    insp = inspect(engine)
    assert insp.has_table("workout_templates"), (
        "workout_templates table must exist in the database"
    )


def test_workout_templates_required_columns():
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("workout_templates")}
    for required in ("id", "user_id", "name", "exercises", "created_at"):
        assert required in cols, f"workout_templates must have column '{required}'"


def test_workout_templates_exercises_is_jsonb():
    insp = inspect(engine)
    cols = insp.get_columns("workout_templates")
    ex_col = next(c for c in cols if c["name"] == "exercises")
    assert "json" in str(ex_col["type"]).lower(), (
        "workout_templates.exercises must be JSONB/JSON type"
    )
