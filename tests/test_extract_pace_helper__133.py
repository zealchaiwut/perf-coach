"""Tests for issue #133: Extract _pace() as a module-level helper."""
import os
import sys
import pytest
import httpx
from datetime import date

# Allow direct import of backend module for unit-testing _pace.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.main import _pace

UAT_BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")

ALICE_USER_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=UAT_BASE_URL, timeout=10.0) as c:
        yield c


# ─── Unit tests for _pace() ───────────────────────────────────────────────────

def test_pace_run_returns_seconds_per_km():
    assert _pace("run", 3600, 10.0) == 360.0


def test_pace_bike_returns_seconds_per_km():
    assert _pace("bike", 1800, 30.0) == 60.0


def test_pace_non_distance_type_returns_none():
    assert _pace("strength", 3600, 10.0) is None


def test_pace_none_duration_returns_none():
    assert _pace("run", None, 10.0) is None


def test_pace_none_distance_returns_none():
    assert _pace("run", 3600, None) is None


def test_pace_zero_distance_returns_none():
    assert _pace("run", 3600, 0) is None


def test_pace_both_none_returns_none():
    assert _pace("run", None, None) is None


# ─── Integration tests: pace field appears in /api/training-log ───────────────

@pytest.fixture(scope="module")
def run_entry(client):
    """Create a run workout with distance and duration, return its date and id."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Test Run #133",
        "workout_date": str(date.today()),
        "workout_type": "run",
        "distance_km": 10.0,
        "duration_seconds": 3600,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Setup failed: {res.text}"
    wid = res.json()["id"]
    yield {"id": wid, "date": str(date.today())}
    client.delete(f"/api/workouts/{wid}")


def test_training_log_entry_has_pace_field(client, run_entry):
    """average_pace_seconds_per_km is present for run entries."""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": run_entry["date"],
        "to": run_entry["date"],
    })
    assert r.status_code == 200
    entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == run_entry["id"]]
    assert entries, "run entry not found in training log"
    entry = entries[0]
    assert "average_pace_seconds_per_km" in entry
    assert entry["average_pace_seconds_per_km"] == 360.0


def test_training_log_non_distance_entry_pace_is_null(client):
    """average_pace_seconds_per_km is null for strength workouts."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Strength #133",
        "workout_date": str(date.today()),
        "workout_type": "strength",
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201
    wid = res.json()["id"]
    try:
        r = client.get("/api/training-log", params={
            "user_id": ALICE_USER_ID,
            "from": str(date.today()),
            "to": str(date.today()),
        })
        entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == wid]
        assert entries, "strength entry not found"
        assert entries[0].get("average_pace_seconds_per_km") is None
    finally:
        client.delete(f"/api/workouts/{wid}")
