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
    assert 'src="/js/admin-plan-library.js' in html
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
    assert 'id="btn-download"' not in html
    assert 'id="btn-import"' not in html
    assert 'id="btn-ex-download"' in html
    assert 'id="btn-ex-export-json"' in html
    assert 'id="btn-ex-import"' in html
    assert 'id="btn-ex-body-parts"' in html
    assert 'id="body-parts-modal"' in html
    assert 'id="body-parts-normalize"' in html
    assert 'id="btn-pat-download"' in html
    assert 'id="btn-pat-export-json"' in html
    assert 'id="btn-pat-import"' in html
    assert 'id="import-modal"' in html
    assert "/api/admin/plan-library/export" in js
    assert "/api/admin/plan-library/import" in js
    assert "/api/admin/plan-library/body-parts" in js
    assert "/api/admin/plan-library/normalize-body-parts" in js
    assert "normalizeBodyPart" in js
    assert "openBodyPartsModal" in js
    assert "PART_ALIASES" in js
    assert "downloadLlmPrompt" in js
    assert "downloadCatalogJson" in js
    assert "buildPlanLibraryLlmPrompt" in js
    assert "Download LLM prompt" in html
    assert "Bulk export JSON" in html
    assert "Bulk import JSON" in html
    assert "normalizeImportBundle" in js
    assert "validateExerciseDraft" in js
    assert "openImportModal" in js
    assert "Bulk import JSON" in js
    assert "downloadCatalogJson('exercises')" in js
    assert "downloadCatalogJson('patterns')" in js
    assert "plan-exercises-" in js
    assert "plan-patterns-" in js
    assert "invalid groups" in js or "Validation failed" in js
    # Variation C — Exercises grouped card grid
    assert 'id="ex-grid"' in html
    assert 'id="ex-list"' not in html
    assert 'id="btn-palette"' not in html
    assert 'id="cmd-palette"' not in html
    assert "openPalette" not in js
    assert "GROUP_SECTION_ORDER" in js
    assert "btn-add-group" in js
    assert "sib-hl" in js
    assert "tinybar" in js
    assert 'class="exc' in js
    # JSON-first exercise editor (LLM paste + live card + gated Save)
    assert 'id="ex-json"' in html
    assert 'id="ex-card-preview"' in html
    assert 'id="ex-json-checks"' in html
    assert 'id="edit-name"' not in html
    assert 'id="edit-groups"' not in html
    assert "validateExerciseDraft" in js
    assert "renderExerciseEditorPreview" in js
    assert "btn-save" in html
    # JSON-first pattern editor
    assert 'id="pat-json"' in html
    assert 'id="pat-card-preview"' in html
    assert 'id="pat-json-checks"' in html
    assert 'id="pat-edit-name"' not in html
    assert 'id="pat-raw-json"' not in html
    assert 'id="run-blocks"' not in html
    assert "validatePatternDraft" in js
    assert "renderPatternEditorPreview" in js
    admin = (root / "frontend" / "pages" / "admin.html").read_text(encoding="utf-8")
    assert 'href="/admin/plan-library"' in admin
    assert "pe-edit-groups" not in admin
    assert "pp-edit-recipe" not in admin


def test_exercise_json_validate_via_node():
    """validateExerciseDraft gates Save: incomplete → fail, full payload → ok."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node not available")
    root = Path(__file__).resolve().parents[1]
    src = (root / "frontend" / "js" / "admin-plan-library.js").read_text(encoding="utf-8")
    # Extract constants + unwrap/validate (no DOM).
    chunks = []
    for start_marker, end_marker in (
        ("  var GROUPS = [", "  var FOCUS = ["),
        ("  var FOCUS = [", "  var RUN_PHASES = ["),
        ("  function unwrapExerciseJson", "  function renderExerciseEditorPreview"),
    ):
        start = src.index(start_marker)
        end = src.index(end_marker)
        body = src[start:end]
        lines = [ln[2:] if ln.startswith("  ") else ln for ln in body.splitlines()]
        chunks.append("\n".join(lines))
    script = "\n".join(chunks) + r"""
var _selectedId = null;
var incomplete = validateExerciseDraft({ name: '', groups: ['warmup'], focus_tags: ['lower'] });
if (incomplete.ok) throw new Error('empty name should fail');
var wrapped = unwrapExerciseJson({ exercises: [{
  name: 'Test squat',
  groups: ['heavy_compound'],
  focus_tags: ['lower', 'full'],
  body_parts: [{ part: 'quad', ratio: 0.6 }, { part: 'glute', ratio: 0.4 }],
  tss_weight: 1.2,
  default_sets: 3,
  default_reps: '8',
  default_load: 'moderate',
}]});
var full = validateExerciseDraft(wrapped);
if (!full.ok) throw new Error('full payload failed: ' + JSON.stringify(full.checks));
if (full.body.active !== true) throw new Error('active should default true');
var badGroup = validateExerciseDraft(Object.assign({}, full.body, { groups: ['nope'] }));
if (badGroup.ok) throw new Error('bad group should fail');
console.log('ok');
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr or r.stdout


def test_pattern_json_validate_via_node():
    """validatePatternDraft gates Save for run + strength recipe shapes."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node not available")
    root = Path(__file__).resolve().parents[1]
    src = (root / "frontend" / "js" / "admin-plan-library.js").read_text(encoding="utf-8")
    chunks = []
    for start_marker, end_marker in (
        ("  var GROUPS = [", "  var FOCUS = ["),
        ("  var FOCUS = [", "  var PART_COLORS = {"),
        ("  var RUN_PHASES = [", "  var PAT_KINDS = ["),
        ("  function intish(v)", "  function parsePatternEditor"),
    ):
        start = src.index(start_marker)
        end = src.index(end_marker)
        body = src[start:end]
        lines = [ln[2:] if ln.startswith("  ") else ln for ln in body.splitlines()]
        chunks.append("\n".join(lines))
    script = "\n".join(chunks) + r"""
var _patSelectedId = null;
var incomplete = validatePatternDraft({ kind: 'run', name: '', subtype: 'easy_run' });
if (incomplete.ok) throw new Error('empty name should fail');
var run = unwrapPatternJson({ patterns: [{
  kind: 'run',
  subtype: 'easy_run',
  duration_min_lo: 0,
  duration_min_hi: 120,
  name: 'Easy aerobic',
  priority: 10,
  recipe: {
    intent_template: 'Easy aerobic run',
    notes_template: null,
    blocks: [
      { phase: 'warmup', duration_share: 0.15, target: 'easy' },
      { phase: 'main', duration_share: 0.70, target: 'easy' },
      { phase: 'cooldown', duration_share: 0.15, target: 'easy' }
    ]
  }
}]});
var full = validatePatternDraft(run);
if (!full.ok) throw new Error('run failed: ' + JSON.stringify(full.checks));
var strength = validatePatternDraft({
  kind: 'strength',
  subtype: 'strength_lower',
  duration_min_lo: 0,
  duration_min_hi: 180,
  name: 'Lower strength',
  priority: 10,
  recipe: {
    intent_template: 'Lower',
    notes_template: null,
    groups: [{ key: 'warmup', label: 'WU', time_share: 0.1, tss_share: 0.1,
      pick: { n: 2, from_tags: ['warmup'] } }],
    focus_bias: { primary_tag: 'lower', primary: 0.8, accessory: 0.2 }
  }
});
if (!strength.ok) throw new Error('strength failed: ' + JSON.stringify(strength.checks));
console.log('ok');
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr or r.stdout


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


def test_admin_plan_library_export_import_roundtrip(admin_client):
    c = admin_client
    seed = c.post("/api/admin/plan-patterns/seed")
    if seed.status_code == 401:
        pytest.skip("admin cookie rejected")
    assert seed.status_code == 200

    exported = c.get("/api/admin/plan-library/export")
    assert exported.status_code == 200, exported.text
    catalog = exported.json()
    assert catalog.get("version") == 1
    assert isinstance(catalog.get("exercises"), list)
    assert isinstance(catalog.get("patterns"), list)
    assert catalog["exercises"], "expected seeded exercises"
    assert "id" not in catalog["exercises"][0]

    name = "pytest-bulk-exercise-zzz"
    # Clean leftover
    for ex in catalog["exercises"]:
        if ex.get("name") == name:
            pass
    er = c.get("/api/admin/plan-exercises")
    for ex in er.json().get("exercises") or []:
        if ex.get("name") == name:
            c.delete(f"/api/admin/plan-exercises/{ex['id']}")

    created = c.post(
        "/api/admin/plan-library/import",
        json={
            "mode": "upsert",
            "exercises": [{
                "name": name,
                "groups": ["emom", "plyo"],
                "focus_tags": ["full"],
                "body_parts": [{"part": "core", "ratio": 1.0}],
                "tss_weight": 0.9,
                "default_sets": 3,
                "default_reps": "12",
                "default_load": "bodyweight",
                "active": True,
            }],
            "patterns": [],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["exercises"]["created"] == 1

    updated = c.post(
        "/api/admin/plan-library/import",
        json={
            "mode": "upsert",
            "exercises": [{
                "name": name,
                "groups": ["emom"],
                "focus_tags": ["full", "core"],
                "body_parts": [{"part": "core", "ratio": 1.0}],
                "tss_weight": 1.1,
                "default_sets": 4,
                "default_reps": "10",
                "default_load": "bodyweight",
                "active": True,
            }],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["exercises"]["updated"] == 1
    assert updated.json()["exercises"]["created"] == 0

    skipped = c.post(
        "/api/admin/plan-library/import",
        json={
            "mode": "create",
            "exercises": [{
                "name": name,
                "groups": ["standalone"],
                "focus_tags": ["full"],
                "body_parts": [{"part": "core", "ratio": 1.0}],
                "tss_weight": 1.0,
                "default_sets": 3,
                "default_reps": "10",
                "default_load": "bodyweight",
                "active": True,
            }],
        },
    )
    assert skipped.status_code == 200
    assert skipped.json()["exercises"]["skipped"] == 1

    rejected = c.post(
        "/api/admin/plan-library/import",
        json={
            "mode": "upsert",
            "exercises": [{
                "name": "pytest-bad-group-zzz",
                "groups": ["not_a_real_group"],
                "focus_tags": ["full"],
                "body_parts": [{"part": "core", "ratio": 1.0}],
                "tss_weight": 1.0,
                "default_sets": 3,
                "default_reps": "10",
                "default_load": "bodyweight",
                "active": True,
            }],
            "patterns": [{
                "kind": "strength",
                "subtype": "full",
                "name": "pytest-bad-from-tags",
                "duration_min_lo": 30,
                "duration_min_hi": 60,
                "priority": 10,
                "recipe": {
                    "intent_template": "Bad tags",
                    "groups": [{
                        "key": "main",
                        "pick": {"n": 1, "from_tags": ["bogus_tag"]},
                    }],
                },
                "active": True,
            }],
        },
    )
    assert rejected.status_code == 200, rejected.text
    rej = rejected.json()
    assert rej["exercises"]["created"] == 0
    assert rej["exercises"]["errors"], rej
    assert "invalid groups" in rej["exercises"]["errors"][0]["detail"]
    assert rej["patterns"]["created"] == 0
    assert rej["patterns"]["errors"], rej
    assert "from_tags" in rej["patterns"]["errors"][0]["detail"]

    # Cleanup
    er2 = c.get("/api/admin/plan-exercises")
    for ex in er2.json().get("exercises") or []:
        if ex.get("name") == name:
            assert c.delete(f"/api/admin/plan-exercises/{ex['id']}").status_code == 204
