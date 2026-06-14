"""
TDD tests for issue #489: Remove broken legacy /api/weight endpoints

AC-1: No frontend or test file references /api/weight (only /api/weight-entries)
AC-2: All four legacy endpoints removed (return 404)
AC-3: WeightEntryIn and WeightEntryPatch Pydantic models removed from main.py
AC-4: grep -r 'recorded_date' returns no matches
AC-5: grep -r '/api/weight[^-]' returns no matches
AC-6: /api/weight-entries endpoints still work (no regression)

Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
REPO_ROOT = pathlib.Path(__file__).parent.parent
THIS_FILE = pathlib.Path(__file__).name


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


# ── AC-1: No frontend or test references to /api/weight ──────────────────────

def test_ac1_no_legacy_weight_in_frontend_js():
    """AC-1: No frontend JS file calls /api/weight (without -entries suffix)."""
    js_dir = REPO_ROOT / "frontend" / "js"
    pattern = re.compile(r"/api/weight(?!-)")
    for js_file in js_dir.glob("*.js"):
        content = js_file.read_text()
        matches = pattern.findall(content)
        assert not matches, (
            f"{js_file.name} still references legacy /api/weight: {matches}"
        )


def test_ac1_no_legacy_weight_in_tests():
    """AC-1: No test file calls /api/weight (without -entries suffix) except this removal test."""
    tests_dir = REPO_ROOT / "tests"
    pattern = re.compile(r"/api/weight(?!-entries)")
    for py_file in tests_dir.glob("*.py"):
        if py_file.name == THIS_FILE:
            continue  # this file documents the removal — allowed to reference the removed path
        content = py_file.read_text()
        matches = pattern.findall(content)
        assert not matches, (
            f"{py_file.name} still references legacy /api/weight: {matches}"
        )


# ── AC-2: All four legacy endpoints return 404 ───────────────────────────────

LEGACY_WEIGHT = "/api/weight"


def test_ac2_get_weight_returns_404(client):
    """AC-2: GET /api/weight returns 404 (endpoint removed)."""
    res = client.get(LEGACY_WEIGHT)
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


def test_ac2_post_weight_returns_404(client):
    """AC-2: POST /api/weight returns 404 (endpoint removed)."""
    res = client.post(LEGACY_WEIGHT, json={"weight_kg": 70.0, "entry_date": "2026-06-01"})
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


def test_ac2_delete_weight_returns_404(client):
    """AC-2: DELETE /api/weight/{id} returns 404 (endpoint removed)."""
    res = client.delete(f"{LEGACY_WEIGHT}/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


def test_ac2_patch_weight_returns_404(client):
    """AC-2: PATCH /api/weight/{id} returns 404 (endpoint removed)."""
    res = client.patch(
        f"{LEGACY_WEIGHT}/00000000-0000-0000-0000-000000000000",
        json={"weight_kg": 70.0},
    )
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


# ── AC-3: WeightEntryIn and WeightEntryPatch Pydantic models removed ─────────

def test_ac3_weight_entry_in_model_removed():
    """AC-3: WeightEntryIn Pydantic model removed from backend/main.py."""
    content = (REPO_ROOT / "backend" / "main.py").read_text()
    assert "class WeightEntryIn" not in content, (
        "WeightEntryIn Pydantic model still present in backend/main.py"
    )


def test_ac3_weight_entry_patch_model_removed():
    """AC-3: WeightEntryPatch Pydantic model removed from backend/main.py."""
    content = (REPO_ROOT / "backend" / "main.py").read_text()
    assert "class WeightEntryPatch" not in content, (
        "WeightEntryPatch Pydantic model still present in backend/main.py"
    )


# ── AC-4: No 'recorded_date' anywhere in the repo ────────────────────────────

def test_ac4_no_recorded_date_in_backend():
    """AC-4: No 'recorded_date' in backend/ Python files."""
    for py_file in (REPO_ROOT / "backend").rglob("*.py"):
        content = py_file.read_text()
        assert "recorded_date" not in content, (
            f"{py_file.relative_to(REPO_ROOT)} still contains 'recorded_date'"
        )


def test_ac4_no_recorded_date_in_frontend():
    """AC-4: No 'recorded_date' in frontend/ JS files."""
    for js_file in (REPO_ROOT / "frontend").rglob("*.js"):
        content = js_file.read_text()
        assert "recorded_date" not in content, (
            f"{js_file.relative_to(REPO_ROOT)} still contains 'recorded_date'"
        )


def test_ac4_no_recorded_date_in_tests():
    """AC-4: No 'recorded_date' in tests/ Python files (except this removal test)."""
    for py_file in (REPO_ROOT / "tests").glob("*.py"):
        if py_file.name == THIS_FILE:
            continue
        content = py_file.read_text()
        assert "recorded_date" not in content, (
            f"{py_file.name} still contains 'recorded_date'"
        )


# ── AC-5: No '/api/weight[^-]' in the codebase ───────────────────────────────

def test_ac5_no_legacy_weight_in_backend():
    """AC-5: No '/api/weight' (without -entries) in backend/ Python files."""
    pattern = re.compile(r"/api/weight(?!-)")
    for py_file in (REPO_ROOT / "backend").rglob("*.py"):
        content = py_file.read_text()
        matches = pattern.findall(content)
        assert not matches, (
            f"{py_file.relative_to(REPO_ROOT)} still has legacy /api/weight path"
        )


# ── AC-6: /api/weight-entries works (no regression) ─────────────────────────

def test_ac6_weight_entries_get_returns_200(client, alice_id):
    """AC-6: GET /api/weight-entries returns 200 with entries/count/summary (no regression)."""
    res = client.get(f"/api/weight-entries?user_id={alice_id}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "entries" in data, "Response missing 'entries' key"
    assert "count" in data, "Response missing 'count' key"
    assert "summary" in data, "Response missing 'summary' key"


def test_ac6_weight_entries_post_and_delete_work(client, alice_id):
    """AC-6: POST then DELETE via /api/weight-entries works (no regression)."""
    post_res = client.post(
        "/api/weight-entries",
        json={"user_id": alice_id, "entry_date": "2026-06-13", "weight_kg": 73.5},
    )
    assert post_res.status_code in (201, 409), (
        f"POST /api/weight-entries failed: {post_res.status_code} {post_res.text}"
    )
    if post_res.status_code == 201:
        entry_id = post_res.json()["id"]
        del_res = client.delete(f"/api/weight-entries/{entry_id}")
        assert del_res.status_code == 204, f"DELETE failed: {del_res.status_code}"
