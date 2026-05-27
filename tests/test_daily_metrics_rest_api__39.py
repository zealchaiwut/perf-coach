"""
Tests for issue #39: REST API for daily_metrics — GET, POST, PATCH, PUT, DELETE
Server under test: http://127.0.0.1:9001
"""
import datetime
import uuid

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today().isoformat()
TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
TEST_DATE = "2026-01-15"
TEST_DATE_2 = "2026-01-16"


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


def _delete_metric(client, user_id, metric_date):
    client.delete(f"/api/daily-metrics/{user_id}/{metric_date}")


# ── POST /api/daily-metrics ──────────────────────────────────────────────────

def test_post_creates_row(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    payload = {
        "user_id": alice_id,
        "metric_date": TEST_DATE,
        "resting_hr": 55,
        "hrv": 65,
        "sleep_hours": 7.5,
        "sleep_quality": 4,
        "energy": 4,
        "mood": 4,
        "notes": "felt good",
    }
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["metric_date"] == TEST_DATE
    assert data["resting_hr"] == 55
    assert data["hrv"] == 65
    assert data["sleep_hours"] == 7.5
    assert data["sleep_quality"] == 4
    assert data["energy"] == 4
    assert data["mood"] == 4
    assert data["notes"] == "felt good"
    assert "created_at" in data
    assert "updated_at" in data
    _delete_metric(client, alice_id, TEST_DATE)


def test_post_returns_409_on_duplicate(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    payload = {"user_id": alice_id, "metric_date": TEST_DATE, "resting_hr": 60}
    client.post("/api/daily-metrics", json=payload)
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 409
    assert "PATCH" in res.json()["error"]
    _delete_metric(client, alice_id, TEST_DATE)


def test_post_rejects_future_date(client, alice_id):
    payload = {"user_id": alice_id, "metric_date": TOMORROW}
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 422


def test_post_rejects_invalid_resting_hr(client, alice_id):
    payload = {"user_id": alice_id, "metric_date": TEST_DATE, "resting_hr": 250}
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["field"] == "resting_hr"


def test_post_rejects_invalid_hrv(client, alice_id):
    payload = {"user_id": alice_id, "metric_date": TEST_DATE, "hrv": 400}
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "hrv"


def test_post_rejects_invalid_sleep_hours(client, alice_id):
    payload = {"user_id": alice_id, "metric_date": TEST_DATE, "sleep_hours": 25.0}
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "sleep_hours"


def test_post_rejects_invalid_sleep_quality(client, alice_id):
    payload = {"user_id": alice_id, "metric_date": TEST_DATE, "sleep_quality": 6}
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "sleep_quality"


def test_post_rejects_invalid_energy(client, alice_id):
    payload = {"user_id": alice_id, "metric_date": TEST_DATE, "energy": 0}
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "energy"


def test_post_rejects_invalid_mood(client, alice_id):
    payload = {"user_id": alice_id, "metric_date": TEST_DATE, "mood": 6}
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "mood"


# ── GET /api/daily-metrics/{user_id}/{metric_date} ───────────────────────────

def test_get_single_returns_row(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    client.post("/api/daily-metrics", json={"user_id": alice_id, "metric_date": TEST_DATE, "resting_hr": 58})
    res = client.get(f"/api/daily-metrics/{alice_id}/{TEST_DATE}")
    assert res.status_code == 200
    data = res.json()
    assert data["metric_date"] == TEST_DATE
    assert data["resting_hr"] == 58
    assert "created_at" in data
    assert "updated_at" in data
    _delete_metric(client, alice_id, TEST_DATE)


def test_get_single_returns_404(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    res = client.get(f"/api/daily-metrics/{alice_id}/{TEST_DATE}")
    assert res.status_code == 404


def test_get_single_rejects_invalid_date(client, alice_id):
    res = client.get(f"/api/daily-metrics/{alice_id}/not-a-date")
    assert res.status_code == 400


# ── GET /api/daily-metrics ──────────────────────────────────────────────────

def test_list_returns_array(client, alice_id):
    res = client.get("/api/daily-metrics", params={"user_id": alice_id})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_list_with_date_range(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    client.post("/api/daily-metrics", json={"user_id": alice_id, "metric_date": TEST_DATE, "resting_hr": 57})
    res = client.get("/api/daily-metrics", params={"user_id": alice_id, "from": "2026-01-01", "to": "2026-01-31"})
    assert res.status_code == 200
    items = res.json()
    match = next((x for x in items if x["metric_date"] == TEST_DATE), None)
    assert match is not None
    _delete_metric(client, alice_id, TEST_DATE)


def test_list_sorted_desc(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    _delete_metric(client, alice_id, TEST_DATE_2)
    client.post("/api/daily-metrics", json={"user_id": alice_id, "metric_date": TEST_DATE})
    client.post("/api/daily-metrics", json={"user_id": alice_id, "metric_date": TEST_DATE_2})
    res = client.get("/api/daily-metrics", params={"user_id": alice_id, "from": "2026-01-01", "to": "2026-01-31"})
    dates = [x["metric_date"] for x in res.json()]
    idx_1 = next((i for i, d in enumerate(dates) if d == TEST_DATE), None)
    idx_2 = next((i for i, d in enumerate(dates) if d == TEST_DATE_2), None)
    assert idx_1 is not None and idx_2 is not None
    assert idx_2 < idx_1, "Results should be sorted metric_date DESC"
    _delete_metric(client, alice_id, TEST_DATE)
    _delete_metric(client, alice_id, TEST_DATE_2)


def test_list_invalid_user_id(client):
    res = client.get("/api/daily-metrics", params={"user_id": "not-a-uuid"})
    assert res.status_code == 400


# ── PATCH /api/daily-metrics/{user_id}/{metric_date} ────────────────────────

def test_patch_updates_only_provided_fields(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    client.post("/api/daily-metrics", json={
        "user_id": alice_id, "metric_date": TEST_DATE,
        "resting_hr": 60, "hrv": 70, "notes": "original",
    })
    res = client.patch(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", json={"notes": "felt great"})
    assert res.status_code == 200
    data = res.json()
    assert data["notes"] == "felt great"
    assert data["resting_hr"] == 60
    assert data["hrv"] == 70
    _delete_metric(client, alice_id, TEST_DATE)


def test_patch_returns_404_when_missing(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    res = client.patch(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", json={"notes": "x"})
    assert res.status_code == 404


def test_patch_rejects_future_date(client, alice_id):
    res = client.patch(f"/api/daily-metrics/{alice_id}/{TOMORROW}", json={"notes": "x"})
    assert res.status_code == 422


def test_patch_rejects_invalid_field(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    client.post("/api/daily-metrics", json={"user_id": alice_id, "metric_date": TEST_DATE})
    res = client.patch(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", json={"resting_hr": 250})
    assert res.status_code == 422
    _delete_metric(client, alice_id, TEST_DATE)


# ── PUT /api/daily-metrics/{user_id}/{metric_date} ──────────────────────────

def test_put_creates_new_row(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    res = client.put(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", json={"resting_hr": 62, "mood": 3})
    assert res.status_code == 200
    data = res.json()
    assert data["resting_hr"] == 62
    assert data["mood"] == 3
    assert data["metric_date"] == TEST_DATE
    _delete_metric(client, alice_id, TEST_DATE)


def test_put_updates_existing_row(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    client.put(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", json={"resting_hr": 62, "mood": 3})
    res = client.put(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", json={"resting_hr": 55, "mood": 5})
    assert res.status_code == 200
    data = res.json()
    assert data["resting_hr"] == 55
    assert data["mood"] == 5
    _delete_metric(client, alice_id, TEST_DATE)


def test_put_rejects_future_date(client, alice_id):
    res = client.put(f"/api/daily-metrics/{alice_id}/{TOMORROW}", json={})
    assert res.status_code == 422


def test_put_rejects_invalid_field(client, alice_id):
    res = client.put(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", json={"resting_hr": 250})
    assert res.status_code == 422


# ── DELETE /api/daily-metrics/{user_id}/{metric_date} ───────────────────────

def test_delete_removes_row(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    client.post("/api/daily-metrics", json={"user_id": alice_id, "metric_date": TEST_DATE, "resting_hr": 60})
    res = client.delete(f"/api/daily-metrics/{alice_id}/{TEST_DATE}")
    assert res.status_code == 204
    get_res = client.get(f"/api/daily-metrics/{alice_id}/{TEST_DATE}")
    assert get_res.status_code == 404


def test_delete_returns_404_when_missing(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    res = client.delete(f"/api/daily-metrics/{alice_id}/{TEST_DATE}")
    assert res.status_code == 404


def test_delete_invalid_user_id(client):
    res = client.delete(f"/api/daily-metrics/not-a-uuid/{TEST_DATE}")
    assert res.status_code == 400


# ── Response payload completeness ───────────────────────────────────────────

def test_response_includes_timestamps(client, alice_id):
    _delete_metric(client, alice_id, TEST_DATE)
    res = client.post("/api/daily-metrics", json={"user_id": alice_id, "metric_date": TEST_DATE})
    assert res.status_code == 201
    data = res.json()
    assert data.get("created_at") is not None
    assert data.get("updated_at") is not None
    _delete_metric(client, alice_id, TEST_DATE)
