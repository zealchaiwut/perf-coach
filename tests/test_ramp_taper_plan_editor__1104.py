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
from tests._admin_helpers import admin_cookies as _admin_cookies

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
        r = bare.post("/api/users", json={"name": uname}, cookies=_admin_cookies())
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
    """AC1 (updated — Plan-tab revamp Part 1, race-anchored-plan.md): the old
    standalone plan-ramp-rate-input was replaced by the Session Load Plan
    card's settings-panel input, id="lp-ramp-input" (a percentage, 0-10%,
    not the old absolute TSS/week value)."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="lp-ramp-input"' in html, "Missing ramp-rate input element"
    assert 'type="number"' in html or 'type=number' in html, "Ramp rate input must be type=number"


def test_ac1_ramp_rate_unit_label_in_html():
    """AC1 (updated — Plan-tab revamp Part 1): unit is now "% / wk" (a
    fraction, per docs/calculations/load-plan.md), not "TSS/week"; label text
    is sentence case ("Ramp rate") per CLAUDE.md's string-literal convention."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert "% / wk" in html or "Ramp rate" in html, "Missing unit label for ramp-rate"


def test_ac2_taper_window_input_in_html():
    """AC2 (updated — Plan-tab revamp Part 1): the old standalone
    plan-taper-window-input was replaced by the Session Load Plan card's
    settings-panel input, id="lp-taper-input"."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="lp-taper-input"' in html, "Missing taper-window input element"


def test_ac2_taper_window_unit_label_in_html():
    """AC2: training-log.html has a unit label for the taper-window input."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert "plan-taper-window-unit" in html or "weeks" in html or "Taper Window" in html, \
        "Missing unit label for taper-window"


# ── AC4: Schedule preview element present in HTML ─────────────────────────────

def test_ac4_schedule_preview_host_in_html():
    """AC4 (updated — Plan-tab revamp Part 1, race-anchored-plan.md): the mock
    ramp/taper bar preview (#plan-sched/#plan-wklabels, computed client-side
    from arbitrary constants — see the old _computeScheduleSeries) was
    replaced by the real race-anchored season chart, rendered into
    #lp-chart-wrap from GET /api/plan/load-plan (see
    docs/calculations/load-plan.md). Nothing here is client-computed anymore."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="lp-chart-wrap"' in html, "Missing season-chart host element"


def test_ac4_schedule_preview_section_in_html():
    """AC4 (updated — Plan-tab revamp Part 1): the old plan-settings-section
    was replaced by the Session Load Plan card, id="load-plan-section"."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="load-plan-section"' in html, "Missing Session Load Plan card section"


# ── AC8: JS contains no forecast or projection math ──────────────────────────

def test_ac8_no_projection_api_call_in_plan_js():
    """AC8: training-performance.js does not call a forecast or projection endpoint."""
    js_path = _ROOT / "frontend" / "js" / "training-performance.js"
    js = js_path.read_text(encoding="utf-8")
    assert "/api/projection" not in js, "plan JS must not call a projection endpoint"
    assert "/api/forecast" not in js, "plan JS must not call a forecast endpoint"


# ── AC3 / AC5: JS wires input-change events for live preview ─────────────────
# Updated 2026-07-09: plan settings (ramp/taper/schedule preview) moved from
# the Projection tab to the Plan tab (training-plan.js) — Projection's old
# slot now shows Race-readiness specificity instead.

def test_ac3_js_wires_input_change_events():
    """AC3 (updated — Plan-tab revamp Part 1): training-plan.js wires the
    Session Load Plan settings-panel inputs (lp-ramp-input/lp-taper-input),
    not the old standalone plan-ramp-rate-input/plan-taper-window-input."""
    js_path = _ROOT / "frontend" / "js" / "training-plan.js"
    js = js_path.read_text(encoding="utf-8")
    assert "lp-ramp-input" in js, "JS must reference the ramp-rate input"
    assert "lp-taper-input" in js, "JS must reference the taper-window input"


def test_ac3_js_has_schedule_preview_render_function():
    """AC3 (updated — Plan-tab revamp Part 1): the old client-computed
    _renderSchedulePreview was replaced by _renderLoadPlanChart, which draws
    the server-computed race-anchored series from GET /api/plan/load-plan."""
    js_path = _ROOT / "frontend" / "js" / "training-plan.js"
    js = js_path.read_text(encoding="utf-8")
    assert "_renderLoadPlanChart" in js, "JS must reference the season-chart render function"


def test_ac3_projection_js_no_longer_owns_plan_settings():
    """AC3 (new): training-performance.js no longer wires the ramp/taper inputs
    or renders the schedule preview — that moved to training-plan.js."""
    js_path = _ROOT / "frontend" / "js" / "training-performance.js"
    js = js_path.read_text(encoding="utf-8")
    assert "plan-ramp-rate-input" not in js
    assert "renderSchedulePreview" not in js


# ── Compile checks ────────────────────────────────────────────────────────────

def test_py_compile_main():
    """backend/main.py compiles without errors."""
    py_compile.compile(str(_ROOT / "backend" / "main.py"), doraise=True)


def test_py_compile_models():
    """backend/models.py compiles without errors."""
    py_compile.compile(str(_ROOT / "backend" / "models.py"), doraise=True)
