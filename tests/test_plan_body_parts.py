"""Plan-library body-part aliases (plurals → canonical) + admin catalog."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.services.plan_body_parts import (
    PLAN_BODY_PARTS,
    catalog_payload,
    normalize_body_parts_list,
    normalize_plan_body_part,
)


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


@pytest.mark.parametrize(
    "raw,canon",
    [
        ("glute", "glute"),
        ("glutes", "glute"),
        ("calf", "calf"),
        ("calves", "calf"),
        ("quad", "quad"),
        ("quads", "quad"),
        ("hamstring", "hamstring"),
        ("hamstrings", "hamstring"),
        ("hip", "hip"),
        ("hips", "hip"),
        ("shoulder", "shoulder"),
        ("shoulders", "shoulder"),
        ("abs", "core"),
        ("traps", "trapezius"),
        ("pecs", "chest"),
        ("back", "upper_back"),
        ("arms", "biceps"),
        ("Hip Flexors", "hip_flexor"),
        ("hip-flexor", "hip_flexor"),
    ],
)
def test_normalize_plan_body_part_aliases(raw, canon):
    assert normalize_plan_body_part(raw) == canon


def test_normalize_body_parts_list_merges_plurals():
    cleaned, err = normalize_body_parts_list([
        {"part": "glutes", "ratio": 0.4},
        {"part": "glute", "ratio": 0.2},
        {"part": "calves", "ratio": 0.4},
    ])
    assert err is None
    assert cleaned is not None
    by_part = {p["part"]: p["ratio"] for p in cleaned}
    assert by_part["glute"] == pytest.approx(0.6)
    assert by_part["calf"] == pytest.approx(0.4)
    assert set(by_part) <= PLAN_BODY_PARTS


def test_normalize_body_parts_list_rejects_unknown():
    cleaned, err = normalize_body_parts_list([{"part": "earlobes", "ratio": 1.0}])
    assert cleaned is None
    assert err and "invalid body_parts.part" in err


def test_catalog_payload_includes_aliases():
    payload = catalog_payload()
    keys = {p["key"] for p in payload["parts"]}
    assert keys == set(PLAN_BODY_PARTS)
    glute = next(p for p in payload["parts"] if p["key"] == "glute")
    assert "glutes" in glute["aliases"]
    assert glute["color"].startswith("#")


def test_admin_body_parts_catalog_endpoint(admin_client):
    c = admin_client
    r = c.get("/api/admin/plan-library/body-parts")
    if r.status_code == 401:
        pytest.skip("admin cookie rejected")
    assert r.status_code == 200, r.text
    parts = r.json().get("parts") or []
    assert len(parts) >= 10
    assert any(p.get("key") == "calf" and "calves" in (p.get("aliases") or []) for p in parts)


def test_admin_import_accepts_plural_body_parts(admin_client):
    c = admin_client
    name = "pytest-plural-bp-zzz"
    er = c.get("/api/admin/plan-exercises")
    if er.status_code == 401:
        pytest.skip("admin cookie rejected")
    for ex in er.json().get("exercises") or []:
        if ex.get("name") == name:
            c.delete(f"/api/admin/plan-exercises/{ex['id']}")

    created = c.post(
        "/api/admin/plan-library/import",
        json={
            "mode": "upsert",
            "exercises": [{
                "name": name,
                "groups": ["standalone"],
                "focus_tags": ["lower"],
                "body_parts": [
                    {"part": "glutes", "ratio": 0.5},
                    {"part": "calves", "ratio": 0.5},
                ],
                "tss_weight": 1.0,
                "default_sets": 3,
                "default_reps": "10",
                "default_load": "bodyweight",
                "active": True,
            }],
            "patterns": [],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["exercises"]["created"] == 1
    assert not created.json()["exercises"]["errors"]

    listed = c.get("/api/admin/plan-exercises")
    row = next(ex for ex in listed.json()["exercises"] if ex["name"] == name)
    parts = {p["part"]: p["ratio"] for p in row["body_parts"]}
    assert parts == {"glute": 0.5, "calf": 0.5}
    c.delete(f"/api/admin/plan-exercises/{row['id']}")


def test_admin_normalize_body_parts_rewrites_pool(admin_client):
    from backend.db import engine
    from backend.models import PlanExercise
    from sqlalchemy.orm import Session

    c = admin_client
    name = "pytest-normalize-bp-zzz"
    er = c.get("/api/admin/plan-exercises")
    if er.status_code == 401:
        pytest.skip("admin cookie rejected")
    for ex in er.json().get("exercises") or []:
        if ex.get("name") == name:
            c.delete(f"/api/admin/plan-exercises/{ex['id']}")

    created = c.post(
        "/api/admin/plan-exercises",
        json={
            "name": name,
            "groups": ["standalone"],
            "focus_tags": ["lower"],
            "body_parts": [{"part": "hamstring", "ratio": 1.0}],
            "tss_weight": 1.0,
            "default_sets": 3,
            "default_reps": "8",
            "default_load": "light",
            "active": True,
        },
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]

    # Plant legacy plurals directly (bypass API normalize) so Normalize pool has work.
    with Session(engine) as db:
        row = db.query(PlanExercise).filter(PlanExercise.id == eid).first()
        assert row is not None
        row.body_parts = [
            {"part": "glutes", "ratio": 0.6},
            {"part": "calves", "ratio": 0.4},
        ]
        db.commit()

    norm = c.post("/api/admin/plan-library/normalize-body-parts")
    assert norm.status_code == 200, norm.text
    body = norm.json()
    assert body["updated"] >= 1

    listed = c.get("/api/admin/plan-exercises")
    row = next(ex for ex in listed.json()["exercises"] if ex["id"] == eid)
    parts = {p["part"]: p["ratio"] for p in row["body_parts"]}
    assert parts == {"glute": 0.6, "calf": 0.4}

    c.delete(f"/api/admin/plan-exercises/{eid}")


def test_js_client_aliases_mirror_backend():
    root = Path(__file__).resolve().parents[1]
    js = (root / "frontend" / "js" / "admin-plan-library.js").read_text(encoding="utf-8")
    assert "glutes: 'glute'" in js
    assert "calves: 'calf'" in js
    assert "function normalizeBodyPart" in js
    assert "function openBodyPartsModal" in js
    html = (root / "frontend" / "pages" / "admin-plan-library.html").read_text(encoding="utf-8")
    assert 'id="btn-ex-body-parts"' in html
    assert 'id="body-parts-modal"' in html
