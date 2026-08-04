"""Admin plan-patterns CRUD smoke + Ask-AI UI removed."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_ask_ai_button_absent_from_training_plan_js():
    root = Path(__file__).resolve().parents[1]
    js = (root / "frontend" / "js" / "training-plan.js").read_text(encoding="utf-8")
    assert "pl-sf-askai" not in js
    assert "Ask AI to generate" not in js
    assert "✨ Refine with AI" not in js
    assert "✨ Generate with AI" not in js
    assert "Fill from patterns" in js


def test_claude_md_planning_llm_removed():
    root = Path(__file__).resolve().parents[1]
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Ask-AI single session" not in text
    assert "Planning has no LLM" in text
    assert "Daily coach message warmth rephrase" in text


@pytest.fixture
def admin_client():
    """httpx client against live UAT server with admin cookie, if available."""
    import httpx
    from backend.auth import create_admin_cookie
    import time

    base = os.getenv("PERF_COACH_TEST_BASE", "http://127.0.0.1:9001")
    secret = os.getenv("ADMIN_SECRET_UAT") or os.getenv("ADMIN_SECRET_PRD")
    if not secret:
        pytest.skip("No ADMIN_SECRET — skip live admin smoke")
    try:
        r = httpx.get(f"{base}/api/health", timeout=2.0)
        if r.status_code >= 500:
            pytest.skip("server unhealthy")
    except Exception:
        pytest.skip("live server not reachable")

    token = create_admin_cookie(time.time())
    from backend.auth import ADMIN_COOKIE_NAME
    with httpx.Client(base_url=base, cookies={ADMIN_COOKIE_NAME: token}, timeout=15.0) as c:
        yield c


def test_admin_plan_patterns_crud_smoke(admin_client):
    c = admin_client
    # List (may be empty before seed)
    r = c.get("/api/admin/plan-patterns")
    if r.status_code == 401:
        pytest.skip("admin cookie rejected")
    assert r.status_code == 200
    assert "patterns" in r.json()

    seed = c.post("/api/admin/plan-patterns/seed")
    assert seed.status_code == 200

    body = {
        "kind": "run",
        "subtype": "easy_run",
        "duration_min_lo": 0,
        "duration_min_hi": 30,
        "name": "pytest-temp-easy-short",
        "priority": 99,
        "recipe": {
            "intent_template": "pytest easy",
            "blocks": [
                {"phase": "warmup", "duration_share": 0.2},
                {"phase": "main", "duration_share": 0.6},
                {"phase": "cooldown", "duration_share": 0.2},
            ],
        },
        "active": True,
    }
    created = c.post("/api/admin/plan-patterns", json=body)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    patched = c.patch(f"/api/admin/plan-patterns/{pid}", json={**body, "priority": 100})
    assert patched.status_code == 200
    assert patched.json()["priority"] == 100

    deleted = c.delete(f"/api/admin/plan-patterns/{pid}")
    assert deleted.status_code == 204

    # Exercises list + create/delete
    er = c.get("/api/admin/plan-exercises")
    assert er.status_code == 200
    name = "pytest-temp-exercise-zzz"
    # Clean leftover if prior run crashed
    for ex in er.json().get("exercises") or []:
        if ex.get("name") == name:
            c.delete(f"/api/admin/plan-exercises/{ex['id']}")
    ec = c.post(
        "/api/admin/plan-exercises",
        json={
            "name": name,
            "groups": ["standalone"],
            "focus_tags": ["full"],
            "body_parts": [{"part": "core", "ratio": 1.0}],
            "tss_weight": 1.0,
            "default_sets": 3,
            "default_reps": "10",
            "default_load": "bodyweight",
            "active": True,
        },
    )
    assert ec.status_code == 201, ec.text
    eid = ec.json()["id"]
    assert c.delete(f"/api/admin/plan-exercises/{eid}").status_code == 204


def test_admin_plan_library_page_shell():
    root = Path(__file__).resolve().parents[1]
    html = (root / "frontend" / "pages" / "admin-plan-library.html").read_text(encoding="utf-8")
    js = (root / "frontend" / "js" / "admin-plan-library.js").read_text(encoding="utf-8")
    assert 'src="/js/admin-plan-library.js"' in html
    assert "Plan library" in html
    assert 'id="tab-exercises"' in html
    assert 'id="tab-patterns"' in html
    assert 'id="tab-preview"' in html
    assert 'id="panel-patterns"' in html
    assert 'id="panel-preview"' in html
    assert 'id="pat-preview-out"' not in html
    assert "/api/admin/plan-exercises" in js
    assert "/api/admin/plan-patterns" in js
    assert "/api/admin/plan-exercises/preview" in js
    assert "setTab('preview')" in js
    assert "Seed defaults" in html
    admin = (root / "frontend" / "pages" / "admin.html").read_text(encoding="utf-8")
    assert 'href="/admin/plan-library"' in admin
    assert "pe-edit-groups" not in admin
    assert "pp-edit-recipe" not in admin


def test_admin_plan_library_page_route(admin_client):
    c = admin_client
    for path in ("/admin/plan-library", "/admin/exercises"):
        r = c.get(path)
        if r.status_code == 401:
            pytest.skip("admin cookie rejected")
        assert r.status_code == 200, path
        assert "Plan library" in r.text
        assert "admin-plan-library.js" in r.text
        assert "tab-patterns" in r.text


def test_admin_plan_exercises_preview_smoke(admin_client):
    c = admin_client
    seed = c.post("/api/admin/plan-patterns/seed")
    if seed.status_code == 401:
        pytest.skip("admin cookie rejected")
    assert seed.status_code == 200
    r = c.post(
        "/api/admin/plan-exercises/preview",
        json={"subtype": "strength_light", "duration_minutes": 45, "target_tss": 40},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("subtype") == "strength_light"
    assert isinstance(data.get("exercises"), list)
    assert len(data["exercises"]) >= 1
