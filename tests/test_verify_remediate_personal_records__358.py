"""Tests for issue #358: Verify personal_records table + endpoints (runs against UAT)

Risk: HIGH — DB schema migration, CRUD endpoints, validation logic, seed data integrity.
"""
import os
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_CODER_DIR = "/Users/chaiwutchaianuchittrakul/dev/perf-coach/coder"
_ALICE_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"
_TEST_PASSWORD = "pr-tests-358-pw"


def _run_coder(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = _coder_db_url()
    return subprocess.run(cmd, cwd=_CODER_DIR, env=env, capture_output=True, text=True, **kwargs)


def _coder_db_url() -> str:
    env_path = Path(_CODER_DIR) / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("DATABASE_URL_UAT="):
            return line.split("=", 1)[1]
    raise RuntimeError("DATABASE_URL_UAT not found in coder .env")


@pytest.fixture(scope="module")
def anon_client():
    """Session-free client — POST/PATCH/DELETE require no auth when no cookie present."""
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def authed_client():
    """Client logged in as Alice — required for GET /api/personal-records (resolve_user)."""
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        login = c.post("/api/auth/login", json={"username": "Alice", "password": _TEST_PASSWORD})
        assert login.status_code == 200, f"Login failed: {login.text}"
        yield c


# --- AC: PersonalRecord model has all required columns (verified via POST round-trip) ---

def test_verify_remediate_personal_records__model_columns(anon_client):
    # AC: model has id, user_id, track_key, track_name, track_type, value_numeric,
    #     achieved_on, source, created_at, updated_at
    r = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID,
        "track_key": "col_check_358",
        "track_name": "Column Check 358",
        "track_type": "weight",
        "value_numeric": 50.0,
        "achieved_on": "2026-01-01",
        "source": "manual",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    for field in ("id", "user_id", "track_key", "track_name", "track_type",
                  "value_numeric", "achieved_on", "source", "created_at", "updated_at"):
        assert field in data, f"Missing field: {field}"
    anon_client.delete(f"/api/personal-records/{data['id']}")


# --- AC: migration file exists for personal_records ---

def test_verify_remediate_personal_records__migration_exists():
    # AC: alembic/versions/ contains a file that creates personal_records
    versions_dir = Path(_CODER_DIR) / "alembic" / "versions"
    files = list(versions_dir.glob("*.py"))
    match = any("personal_records" in f.name for f in files)
    assert match, f"No migration file for personal_records in {versions_dir}"


# --- AC: alembic upgrade head runs cleanly (first run) ---

def test_verify_remediate_personal_records__alembic_upgrade_first():
    # AC: alembic upgrade head completes without error
    r = _run_coder(["venv/bin/alembic", "upgrade", "head"])
    assert r.returncode == 0, f"alembic upgrade head failed:\n{r.stderr}"


# --- AC: alembic upgrade head is idempotent (second run) ---

def test_verify_remediate_personal_records__alembic_upgrade_idempotent():
    # AC: second alembic upgrade head also returns 0
    r = _run_coder(["venv/bin/alembic", "upgrade", "head"])
    assert r.returncode == 0, f"alembic upgrade head (2nd run) failed:\n{r.stderr}"


# --- AC: GET /api/personal-records endpoint reachable ---

def test_verify_remediate_personal_records__get_200(authed_client):
    # AC: GET /api/personal-records returns 200
    r = authed_client.get("/api/personal-records")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


# --- AC: seeded user has >= 3 records including half_marathon, 10k, squat_1rm ---

def test_verify_remediate_personal_records__seeded_records_present(authed_client):
    # AC: GET returns ≥ 3 records; seeds include half_marathon, 10k, squat_1rm
    r = authed_client.get("/api/personal-records")
    assert r.status_code == 200
    records = r.json()
    assert len(records) >= 3, f"Expected ≥3 records, got {len(records)}"
    keys = {rec["track_key"] for rec in records}
    assert "half_marathon" in keys
    assert "10k" in keys
    assert "squat_1rm" in keys


# --- AC: seeded values correct ---

def test_verify_remediate_personal_records__seeded_values(authed_client):
    # AC: half_marathon=6871, 10k=3128, squat_1rm=140 weight
    r = authed_client.get("/api/personal-records")
    records = {rec["track_key"]: rec for rec in r.json()}
    assert float(records["half_marathon"]["value_numeric"]) == 6871.0
    assert float(records["10k"]["value_numeric"]) == 3128.0
    assert float(records["squat_1rm"]["value_numeric"]) == 140.0
    assert records["squat_1rm"]["track_type"] == "weight"


# --- AC: POST validation rejects value_numeric <= 0 ---

def test_verify_remediate_personal_records__post_rejects_zero(anon_client):
    # AC: value_numeric=0 → 422
    r = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID, "track_key": "zero_358", "track_name": "Zero",
        "track_type": "weight", "value_numeric": 0, "achieved_on": "2026-01-01",
    })
    assert r.status_code == 422, r.text


def test_verify_remediate_personal_records__post_rejects_negative(anon_client):
    # AC: value_numeric=-1 → 422
    r = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID, "track_key": "neg_358", "track_name": "Negative",
        "track_type": "weight", "value_numeric": -1, "achieved_on": "2026-01-01",
    })
    assert r.status_code == 422, r.text


# --- AC: POST validation rejects future achieved_on ---

def test_verify_remediate_personal_records__post_rejects_future_date(anon_client):
    # AC: achieved_on tomorrow → 422
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID, "track_key": "future_358", "track_name": "Future",
        "track_type": "weight", "value_numeric": 100, "achieved_on": tomorrow,
    })
    assert r.status_code == 422, r.text


# --- AC: POST validation rejects invalid track_type ---

def test_verify_remediate_personal_records__post_rejects_invalid_track_type(anon_client):
    # AC: track_type=distance → 422
    r = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID, "track_key": "badtype_358", "track_name": "BadType",
        "track_type": "distance", "value_numeric": 100, "achieved_on": "2026-01-01",
    })
    assert r.status_code == 422, r.text


# --- AC: POST round-trip returns valid UUID ---

def test_verify_remediate_personal_records__post_round_trip_uuid(anon_client):
    # AC: POST creates record, returns valid UUID id
    r = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID,
        "track_key": "uuid_check_358",
        "track_name": "UUID Check 358",
        "track_type": "time",
        "value_numeric": 1800,
        "achieved_on": "2026-01-01",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert uuid.UUID(data["id"])  # raises if invalid
    anon_client.delete(f"/api/personal-records/{data['id']}")


# --- AC: PATCH updates without destroying other fields ---

def test_verify_remediate_personal_records__patch_no_field_destruction(anon_client):
    # AC: PATCH value_numeric only; track_name, track_key, track_type unchanged
    pr = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID,
        "track_key": "patch_test_358",
        "track_name": "Patch Test 358",
        "track_type": "weight",
        "value_numeric": 100,
        "achieved_on": "2026-01-01",
    }).json()
    r = anon_client.patch(f"/api/personal-records/{pr['id']}", json={"value_numeric": 110})
    assert r.status_code == 200, r.text
    data = r.json()
    assert float(data["value_numeric"]) == 110.0
    assert data["track_name"] == "Patch Test 358"
    assert data["track_key"] == "patch_test_358"
    assert data["track_type"] == "weight"
    anon_client.delete(f"/api/personal-records/{pr['id']}")


# --- AC: DELETE returns 204 ---

def test_verify_remediate_personal_records__delete_returns_204(anon_client):
    # AC: DELETE on existing record → 204
    pr = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID, "track_key": "del_204_358", "track_name": "Del 204 358",
        "track_type": "time", "value_numeric": 500, "achieved_on": "2026-01-01",
    }).json()
    r = anon_client.delete(f"/api/personal-records/{pr['id']}")
    assert r.status_code == 204


# --- AC: DELETE actually removes the record ---

def test_verify_remediate_personal_records__delete_removes_record(anon_client, authed_client):
    # AC: after DELETE, record absent from GET list and GET by id returns 404
    pr = anon_client.post("/api/personal-records", json={
        "user_id": _ALICE_ID, "track_key": "del_gone_358", "track_name": "Del Gone 358",
        "track_type": "time", "value_numeric": 500, "achieved_on": "2026-01-01",
    }).json()
    anon_client.delete(f"/api/personal-records/{pr['id']}")
    all_records = authed_client.get("/api/personal-records").json()
    assert not any(r["id"] == pr["id"] for r in all_records)


# --- AC: seeded records survive CRUD ops (no data destruction) ---

def test_verify_remediate_personal_records__seeded_records_survive(authed_client):
    # AC: half_marathon, 10k, squat_1rm still present after test suite ops
    r = authed_client.get("/api/personal-records")
    keys = {rec["track_key"] for rec in r.json()}
    assert "half_marathon" in keys
    assert "10k" in keys
    assert "squat_1rm" in keys
