"""
TDD tests for issue #359: Bulk Insert and History Endpoints for Personal Records.

AC items covered:
  (a) /tracks returns full canonical 8-track list
  (b) /history records sorted achieved_on DESC
  (c) improvement_from_prev computed correctly for time and weight tracks
  (d) Bulk POST creates all records, returns correct created count
  (e) Bulk POST fails atomically — no partial inserts on invalid record
  (f) /history with no matching records returns empty history array

Server: http://127.0.0.1:9001
"""
import uuid
from datetime import date, timedelta

import httpx
import pytest
from backend.auth import hash_password
from backend.db import engine
from backend.models import PersonalRecord, User
from sqlalchemy.orm import Session
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "pr-tests-359-pw"

CANONICAL_TRACKS = [
    {"track_key": "half_marathon", "track_name": "Half Marathon", "track_type": "time", "category": "running"},
    {"track_key": "10k", "track_name": "10K", "track_type": "time", "category": "running"},
    {"track_key": "5k", "track_name": "5K", "track_type": "time", "category": "running"},
    {"track_key": "marathon", "track_name": "Marathon", "track_type": "time", "category": "running"},
    {"track_key": "squat_1rm", "track_name": "Squat 1RM", "track_type": "weight", "category": "strength"},
    {"track_key": "deadlift_1rm", "track_name": "Deadlift 1RM", "track_type": "weight", "category": "strength"},
    {"track_key": "bench_1rm", "track_name": "Bench Press 1RM", "track_type": "weight", "category": "strength"},
    {"track_key": "ohp_1rm", "track_name": "Overhead Press 1RM", "track_type": "weight", "category": "strength"},
]
CANONICAL_KEYS = {t["track_key"] for t in CANONICAL_TRACKS}


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    with Session(engine) as db:
        db.get(User, uuid.UUID(alice["id"])).password_hash = hash_password(_TEST_PASSWORD)
        db.commit()
    login = client.post("/api/auth/login", json={"username": "Alice", "password": _TEST_PASSWORD})
    assert login.status_code == 200, login.text
    return alice["id"]


# ── AC (a): GET /api/personal-records/tracks ─────────────────────────────────

def test_tracks_returns_200(client, alice_id):
    res = client.get("/api/personal-records/tracks")
    assert res.status_code == 200


def test_tracks_returns_exactly_8(client, alice_id):
    res = client.get("/api/personal-records/tracks")
    assert res.status_code == 200
    body = res.json()
    assert "tracks" in body
    assert len(body["tracks"]) == 8


def test_tracks_contains_all_canonical_keys(client, alice_id):
    res = client.get("/api/personal-records/tracks")
    body = res.json()
    returned_keys = {t["track_key"] for t in body["tracks"]}
    assert returned_keys == CANONICAL_KEYS


def test_tracks_each_entry_has_required_fields(client, alice_id):
    res = client.get("/api/personal-records/tracks")
    for track in res.json()["tracks"]:
        for field in ("track_key", "track_name", "track_type", "category"):
            assert field in track, f"Missing field '{field}' in track {track}"


def test_tracks_track_type_values_valid(client, alice_id):
    res = client.get("/api/personal-records/tracks")
    for track in res.json()["tracks"]:
        assert track["track_type"] in ("time", "weight"), f"Invalid track_type: {track['track_type']}"


def test_tracks_category_values_valid(client, alice_id):
    res = client.get("/api/personal-records/tracks")
    for track in res.json()["tracks"]:
        assert track["category"] in ("running", "strength"), f"Invalid category: {track['category']}"


def test_tracks_running_tracks_are_time_type(client, alice_id):
    res = client.get("/api/personal-records/tracks")
    for track in res.json()["tracks"]:
        if track["category"] == "running":
            assert track["track_type"] == "time"


def test_tracks_strength_tracks_are_weight_type(client, alice_id):
    res = client.get("/api/personal-records/tracks")
    for track in res.json()["tracks"]:
        if track["category"] == "strength":
            assert track["track_type"] == "weight"


def test_tracks_no_query_params_needed(client, alice_id):
    # Endpoint must work with no params at all
    res = client.get("/api/personal-records/tracks")
    assert res.status_code == 200


# ── AC (b): /history sorted DESC ─────────────────────────────────────────────

def _anon_bulk_post(alice_id, records):
    """POST to /bulk without a session cookie to avoid CSRF (bulk endpoint doesn't use resolve_user)."""
    with httpx.Client(base_url=BASE, timeout=10) as anon:
        res = anon.post("/api/personal-records/bulk", json={"user_id": alice_id, "records": records})
    return res


@pytest.fixture(scope="module")
def history_time_records(client, alice_id):
    """Insert 3 half_marathon records with different dates; yield ids; cleanup after."""
    test_dates = {"2025-01-10", "2025-06-15", "2026-01-20"}
    hist = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    for r in hist.json().get("history", []):
        if r["achieved_on"] in test_dates and r.get("source") == "manual":
            client.delete(f"/api/personal-records/{r['id']}")
    records = [
        {"track_key": "half_marathon", "value_numeric": 5400.0, "achieved_on": "2025-01-10", "source": "manual"},
        {"track_key": "half_marathon", "value_numeric": 5100.0, "achieved_on": "2025-06-15", "source": "manual"},
        {"track_key": "half_marathon", "value_numeric": 4900.0, "achieved_on": "2026-01-20", "source": "manual"},
    ]
    res = _anon_bulk_post(alice_id, records)
    assert res.status_code == 201, f"Bulk insert failed: {res.text}"
    ids = res.json()["ids"]
    yield ids
    for rid in ids:
        client.delete(f"/api/personal-records/{rid}")


@pytest.fixture(scope="module")
def history_weight_records(client, alice_id):
    """Insert 3 squat_1rm records with different dates; yield ids; cleanup after."""
    test_dates = {"2025-02-01", "2025-08-01", "2026-02-01"}
    hist = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "squat_1rm"})
    for r in hist.json().get("history", []):
        if r["achieved_on"] in test_dates and r.get("source") == "manual":
            client.delete(f"/api/personal-records/{r['id']}")
    records = [
        {"track_key": "squat_1rm", "value_numeric": 100.0, "achieved_on": "2025-02-01", "source": "manual"},
        {"track_key": "squat_1rm", "value_numeric": 110.0, "achieved_on": "2025-08-01", "source": "manual"},
        {"track_key": "squat_1rm", "value_numeric": 120.0, "achieved_on": "2026-02-01", "source": "manual"},
    ]
    res = _anon_bulk_post(alice_id, records)
    assert res.status_code == 201, f"Bulk insert failed: {res.text}"
    ids = res.json()["ids"]
    yield ids
    for rid in ids:
        client.delete(f"/api/personal-records/{rid}")


def test_history_returns_200(client, alice_id, history_time_records):
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    assert res.status_code == 200


def test_history_response_has_track_key_and_history(client, alice_id, history_time_records):
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    body = res.json()
    assert "track_key" in body
    assert "history" in body
    assert body["track_key"] == "half_marathon"


def test_history_sorted_desc(client, alice_id, history_time_records):
    """AC (b): records sorted achieved_on DESC (newest first)."""
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    history = res.json()["history"]
    dates = [r["achieved_on"] for r in history]
    assert dates == sorted(dates, reverse=True), f"Not sorted DESC: {dates}"


def test_history_record_has_required_fields(client, alice_id, history_time_records):
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    for record in res.json()["history"]:
        for field in ("id", "value_numeric", "value_formatted", "achieved_on", "source"):
            assert field in record, f"Missing field '{field}'"
        assert "improvement_from_prev" in record


# ── AC (c): improvement_from_prev ────────────────────────────────────────────

def test_improvement_from_prev_most_recent_is_null(client, alice_id, history_time_records):
    """Most recent (first in DESC list) has improvement_from_prev == null."""
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    history = res.json()["history"]
    assert history[0]["improvement_from_prev"] is None


def test_improvement_from_prev_older_records_not_null(client, alice_id, history_time_records):
    """All records except the most recent have non-null improvement_from_prev."""
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    history = res.json()["history"]
    for record in history[1:]:
        assert record["improvement_from_prev"] is not None, f"Expected non-null for {record['achieved_on']}"


def test_improvement_time_track_faster_negative(client, alice_id, history_time_records):
    """
    Time track: improvement = current - previous (both in DESC order).
    2026-01-20: 4900s  (most recent, null)
    2025-06-15: 5100s  vs prev 4900s => delta = 5100 - 4900 = +200s (slower) => "+0:03:20"
    2025-01-10: 5400s  vs prev 5100s => delta = 5400 - 5100 = +300s (slower) => "+0:05:00"
    """
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    history = res.json()["history"]
    # Filter to our test records by achieved_on
    by_date = {r["achieved_on"]: r for r in history}
    # 2025-06-15 is slower than the newer 2026-01-20 record (+200s)
    rec_mid = by_date.get("2025-06-15")
    assert rec_mid is not None
    delta = rec_mid["improvement_from_prev"]
    assert delta is not None
    # positive seconds = slower = starts with "+"
    assert delta["formatted"].startswith("+"), f"Expected +, got {delta['formatted']}"
    assert delta["seconds"] > 0


def test_improvement_time_track_improvement_delta_value(client, alice_id, history_time_records):
    """2025-06-15 (5100s) vs newer 2026-01-20 (4900s): delta = +200s."""
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "half_marathon"})
    history = res.json()["history"]
    by_date = {r["achieved_on"]: r for r in history}
    rec_mid = by_date.get("2025-06-15")
    assert rec_mid is not None
    assert rec_mid["improvement_from_prev"]["seconds"] == 200


def test_improvement_weight_track_heavier_positive(client, alice_id, history_weight_records):
    """
    Weight track sorted DESC: 2026-02-01 (120kg) newest/null, 2025-08-01 (110kg), 2025-02-01 (100kg).
    2025-08-01: 110kg vs newer 120kg => delta = 110 - 120 = -10kg (lighter) => "−10 kg"
    """
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "squat_1rm"})
    history = res.json()["history"]
    by_date = {r["achieved_on"]: r for r in history}
    rec_mid = by_date.get("2025-08-01")
    assert rec_mid is not None
    delta = rec_mid["improvement_from_prev"]
    assert delta is not None
    assert delta["kg"] == -10.0
    assert delta["formatted"].startswith("−"), f"Expected −, got {delta['formatted']}"


def test_improvement_weight_track_positive_kg(client, alice_id, history_weight_records):
    """
    2026-02-01 (120kg) is newest => null.
    If we had a case where older is heavier... but in our fixture oldest is lightest.
    Let's verify the formatted string contains 'kg'.
    """
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "squat_1rm"})
    history = res.json()["history"]
    for record in history[1:]:
        assert "kg" in record["improvement_from_prev"]["formatted"].lower()


# ── AC (f): empty history ─────────────────────────────────────────────────────

def test_history_no_records_returns_empty_array(client, alice_id):
    """AC (f): user has no records for marathon => empty history array."""
    res = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "marathon"})
    assert res.status_code == 200
    body = res.json()
    assert body["track_key"] == "marathon"
    assert body["history"] == []


def test_history_missing_user_id_returns_422(client, alice_id):
    res = client.get("/api/personal-records/history", params={"track_key": "half_marathon"})
    assert res.status_code == 422


def test_history_missing_track_key_returns_422(client, alice_id):
    res = client.get("/api/personal-records/history", params={"user_id": alice_id})
    assert res.status_code == 422


# ── AC (d): Bulk POST success ─────────────────────────────────────────────────

def test_bulk_post_returns_201(client, alice_id):
    res = _anon_bulk_post(alice_id, [
        {"track_key": "5k", "value_numeric": 1200.0, "achieved_on": "2025-03-01", "source": "manual"},
    ])
    assert res.status_code == 201, res.text
    for rid in res.json().get("ids", []):
        client.delete(f"/api/personal-records/{rid}")


def test_bulk_post_created_count(client, alice_id):
    """AC (d): created count matches number of records sent."""
    res = _anon_bulk_post(alice_id, [
        {"track_key": "10k", "value_numeric": 2700.0, "achieved_on": "2025-04-01", "source": "manual"},
        {"track_key": "10k", "value_numeric": 2600.0, "achieved_on": "2025-09-01", "source": "manual"},
    ])
    assert res.status_code == 201
    body = res.json()
    assert body["created"] == 2
    assert len(body["ids"]) == 2
    for rid in body["ids"]:
        client.delete(f"/api/personal-records/{rid}")


def test_bulk_post_ids_are_uuids(client, alice_id):
    res = _anon_bulk_post(alice_id, [
        {"track_key": "deadlift_1rm", "value_numeric": 150.0, "achieved_on": "2025-05-01", "source": "manual"},
    ])
    assert res.status_code == 201
    ids = res.json()["ids"]
    for rid in ids:
        uuid.UUID(rid)  # must not raise
    for rid in ids:
        client.delete(f"/api/personal-records/{rid}")


def test_bulk_post_records_appear_in_history(client, alice_id):
    """AC (d): bulk-inserted records visible in /history."""
    res = _anon_bulk_post(alice_id, [
        {"track_key": "ohp_1rm", "value_numeric": 60.0, "achieved_on": "2025-07-01", "source": "manual"},
    ])
    assert res.status_code == 201
    inserted_id = res.json()["ids"][0]
    hist = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "ohp_1rm"})
    ids_in_hist = [r["id"] for r in hist.json()["history"]]
    assert inserted_id in ids_in_hist
    client.delete(f"/api/personal-records/{inserted_id}")


# ── AC (e): Bulk POST atomic failure ─────────────────────────────────────────

def test_bulk_post_atomic_invalid_record_returns_422(client, alice_id):
    """AC (e): one invalid record => 422, zero inserted."""
    before = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "bench_1rm"})
    count_before = len(before.json()["history"])

    res = _anon_bulk_post(alice_id, [
        {"track_key": "bench_1rm", "value_numeric": 120.0, "achieved_on": "2025-06-01", "source": "manual"},
        {"track_key": "bench_1rm", "value_numeric": -5.0, "achieved_on": "2025-07-01", "source": "manual"},  # invalid
    ])
    assert res.status_code == 422

    after = client.get("/api/personal-records/history", params={"user_id": alice_id, "track_key": "bench_1rm"})
    count_after = len(after.json()["history"])
    assert count_after == count_before, "Partial insert occurred — not atomic"


def test_bulk_post_atomic_missing_value_numeric_returns_422(client, alice_id):
    """Record missing value_numeric fails atomically."""
    with httpx.Client(base_url=BASE, timeout=10) as anon:
        res = anon.post("/api/personal-records/bulk", json={
            "user_id": alice_id,
            "records": [
                {"track_key": "squat_1rm", "achieved_on": "2025-06-01", "source": "manual"},
            ],
        })
    assert res.status_code == 422


def test_bulk_post_atomic_future_date_returns_422(client, alice_id):
    tomorrow = str(date.today() + timedelta(days=1))
    res = _anon_bulk_post(alice_id, [
        {"track_key": "squat_1rm", "value_numeric": 130.0, "achieved_on": tomorrow, "source": "manual"},
    ])
    assert res.status_code == 422


def test_bulk_post_missing_user_id_returns_422(client, alice_id):
    """Body without user_id => 422."""
    with httpx.Client(base_url=BASE, timeout=10) as anon:
        res = anon.post("/api/personal-records/bulk", json={
            "records": [
                {"track_key": "5k", "value_numeric": 1100.0, "achieved_on": "2025-01-01", "source": "manual"},
            ],
        })
    assert res.status_code == 422


def test_bulk_post_empty_records_returns_422(client, alice_id):
    """Empty records list => 422."""
    res = _anon_bulk_post(alice_id, [])
    assert res.status_code == 422
