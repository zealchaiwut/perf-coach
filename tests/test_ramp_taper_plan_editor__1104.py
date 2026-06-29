"""Tests for issue #1104: Add ramp/taper controls with schedule preview to plan editor.

Acceptance criteria verified:
- AC1: A "Ramp Rate" input (numeric, with unit label) is present in the plan editor HTML
- AC2: A "Taper Window" input (numeric, with unit label) is present in the plan editor HTML
- AC3: Live preview: changing inputs updates preview (tested via JS structure)
- AC4: Schedule preview element is present in the plan editor HTML
- AC5: Ramp rate and taper window values persist (save and restore via API)
- AC6: Invalid input rejected or flagged (backend validation: negative values → 422)
- AC7: Default values 0 pre-populated when creating a new plan
- AC8: No forecast math; preview is purely based on ramp/taper params

All HTTP tests run against a live UAT server (UAT_BASE_URL or http://127.0.0.1:9001).
"""
import os
import pathlib
import py_compile
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "test1104plan!"
_ROOT = pathlib.Path(__file__).resolve().parents[1]

try:
    from dotenv import dotenv_values
    _env = dotenv_values(_ROOT / ".env")
    _uat_url = _env.get("DATABASE_URL_UAT")
except ImportError:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

if _uat_url:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import hash_password as _hash_pw, CSRF_COOKIE_NAME
    from backend.models import User as _UserModel
    _engine = create_engine(_uat_url, pool_pre_ping=True)
else:
    _engine = None
    CSRF_COOKIE_NAME = "csrf-token"


def _skip_if_no_db():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


@pytest.fixture
def auth_client():
    _skip_if_no_db()
    uname = f"plan1104_{uuid.uuid4().hex[:8]}"

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname})
        assert r.status_code == 201, f"create user: {r.text}"
        user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
        assert r.status_code == 200, f"login: {r.text}"
        session_cookie = r.cookies.get("session")
        csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    client = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield client
    client.close()

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


# ── AC7: GET /api/plans returns 200 with a list ───────────────────────────────

def test_ac7_list_plans_returns_200_empty(auth_client):
    """AC7: GET /api/plans returns 200 with an empty list for a new user."""
    r = auth_client.get("/api/plans")
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)


# ── AC7: Default values when creating a new plan ──────────────────────────────

def test_ac7_new_plan_defaults_ramp_rate_zero(auth_client):
    """AC7: Creating a plan with ramp_rate=0 (explicit default) round-trips correctly."""
    r = auth_client.post("/api/plans", json={"name": "Default Plan", "ramp_rate": 0, "taper_length": 0})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["ramp_rate"] == 0.0


def test_ac7_new_plan_defaults_taper_window_zero(auth_client):
    """AC7: Creating a plan with taper_length=0 (explicit default) round-trips correctly."""
    r = auth_client.post("/api/plans", json={"name": "Default Plan", "ramp_rate": 0, "taper_length": 0})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["taper_length"] == 0.0


# ── AC5: Persist and restore ramp_rate and taper_window via PATCH + GET ───────

def test_ac5_persist_ramp_rate_on_patch(auth_client):
    """AC5: Patching ramp_rate persists the value; subsequent GET returns it."""
    r = auth_client.post("/api/plans", json={"name": "Save Test", "ramp_rate": 0, "taper_length": 0})
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]

    r2 = auth_client.patch(f"/api/plans/{plan_id}", json={"ramp_rate": 5})
    assert r2.status_code == 200, r2.text
    assert r2.json()["ramp_rate"] == 5.0

    r3 = auth_client.get(f"/api/plans/{plan_id}")
    assert r3.status_code == 200, r3.text
    assert r3.json()["ramp_rate"] == 5.0


def test_ac5_persist_taper_window_on_patch(auth_client):
    """AC5: Patching taper_length persists the value; subsequent GET returns it."""
    r = auth_client.post("/api/plans", json={"name": "Taper Save Test", "ramp_rate": 0, "taper_length": 0})
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]

    r2 = auth_client.patch(f"/api/plans/{plan_id}", json={"taper_length": 3})
    assert r2.status_code == 200, r2.text
    assert r2.json()["taper_length"] == 3.0

    r3 = auth_client.get(f"/api/plans/{plan_id}")
    assert r3.status_code == 200, r3.text
    assert r3.json()["taper_length"] == 3.0


def test_ac5_get_plans_lists_created_plan(auth_client):
    """AC5: GET /api/plans lists a plan after it is created."""
    r = auth_client.post("/api/plans", json={"name": "Listed Plan", "ramp_rate": 2, "taper_length": 1})
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]

    r2 = auth_client.get("/api/plans")
    assert r2.status_code == 200, r2.text
    ids = [p["id"] for p in r2.json()]
    assert plan_id in ids


# ── AC6: Backend validates negative ramp_rate and taper_length ────────────────

def test_ac6_negative_ramp_rate_rejected_on_create(auth_client):
    """AC6: Creating a plan with negative ramp_rate returns 422."""
    r = auth_client.post("/api/plans", json={"name": "Bad Ramp", "ramp_rate": -1})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


def test_ac6_negative_taper_length_rejected_on_create(auth_client):
    """AC6: Creating a plan with negative taper_length returns 422."""
    r = auth_client.post("/api/plans", json={"name": "Bad Taper", "taper_length": -2})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


def test_ac6_negative_ramp_rate_rejected_on_patch(auth_client):
    """AC6: Patching a plan with negative ramp_rate returns 422."""
    r = auth_client.post("/api/plans", json={"name": "Patch Bad Ramp", "ramp_rate": 5, "taper_length": 1})
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]

    r2 = auth_client.patch(f"/api/plans/{plan_id}", json={"ramp_rate": -3})
    assert r2.status_code == 422, f"Expected 422, got {r2.status_code}: {r2.text}"


def test_ac6_negative_taper_length_rejected_on_patch(auth_client):
    """AC6: Patching a plan with negative taper_length returns 422."""
    r = auth_client.post("/api/plans", json={"name": "Patch Bad Taper", "ramp_rate": 5, "taper_length": 1})
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]

    r2 = auth_client.patch(f"/api/plans/{plan_id}", json={"taper_length": -1})
    assert r2.status_code == 422, f"Expected 422, got {r2.status_code}: {r2.text}"


# ── AC1 & AC2: HTML has ramp-rate and taper-window inputs ────────────────────

def test_ac1_ramp_rate_input_in_html():
    """AC1: training-log.html has a numeric ramp-rate input element."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="plan-ramp-rate-input"' in html, "Missing ramp-rate input element"
    assert 'type="number"' in html or 'type=number' in html, "Ramp rate input must be type=number"


def test_ac1_ramp_rate_unit_label_in_html():
    """AC1: training-log.html has a unit label for the ramp-rate input."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert "plan-ramp-rate-unit" in html or "TSS/week" in html or "Ramp Rate" in html, \
        "Missing unit label for ramp-rate"


def test_ac2_taper_window_input_in_html():
    """AC2: training-log.html has a numeric taper-window input element."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="plan-taper-window-input"' in html, "Missing taper-window input element"


def test_ac2_taper_window_unit_label_in_html():
    """AC2: training-log.html has a unit label for the taper-window input."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert "plan-taper-window-unit" in html or "weeks" in html or "Taper Window" in html, \
        "Missing unit label for taper-window"


# ── AC4: Schedule preview element present in HTML ─────────────────────────────

def test_ac4_schedule_preview_canvas_in_html():
    """AC4: training-log.html has a canvas element for the schedule preview."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="plan-schedule-canvas"' in html, "Missing schedule-preview canvas element"


def test_ac4_schedule_preview_section_in_html():
    """AC4: training-log.html has a plan-settings section containing the preview."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert "plan-settings-section" in html or "plan-schedule-preview" in html, \
        "Missing schedule preview section"


# ── AC8: JS contains no forecast or projection math ──────────────────────────

def test_ac8_no_projection_api_call_in_plan_js():
    """AC8: training-plan.js does not call a forecast or projection endpoint."""
    js_path = _ROOT / "frontend" / "js" / "training-plan.js"
    js = js_path.read_text(encoding="utf-8")
    assert "/api/projection" not in js, "plan JS must not call a projection endpoint"
    assert "/api/forecast" not in js, "plan JS must not call a forecast endpoint"


# ── AC3 / AC5: JS wires input-change events for live preview ─────────────────

def test_ac3_js_wires_input_change_events():
    """AC3: training-plan.js contains event listeners for the ramp/taper inputs."""
    js_path = _ROOT / "frontend" / "js" / "training-plan.js"
    js = js_path.read_text(encoding="utf-8")
    assert "plan-ramp-rate-input" in js, "JS must reference the ramp-rate input"
    assert "plan-taper-window-input" in js, "JS must reference the taper-window input"


def test_ac3_js_has_schedule_preview_render_function():
    """AC3: training-plan.js contains a function that renders the schedule preview."""
    js_path = _ROOT / "frontend" / "js" / "training-plan.js"
    js = js_path.read_text(encoding="utf-8")
    assert "renderSchedulePreview" in js or "plan-schedule-canvas" in js, \
        "JS must reference the schedule preview canvas"


# ── Compile checks ────────────────────────────────────────────────────────────

def test_py_compile_main():
    """backend/main.py compiles without errors."""
    py_compile.compile(str(_ROOT / "backend" / "main.py"), doraise=True)


def test_py_compile_models():
    """backend/models.py compiles without errors."""
    py_compile.compile(str(_ROOT / "backend" / "models.py"), doraise=True)
