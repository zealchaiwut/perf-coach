"""Tests for issue #218: POST /api/imports/sleep"""
import uuid

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
_RUN = str(uuid.uuid4())[:8]
IMPORT_DATE = "2026-05-01"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    if alice:
        return alice["id"]
    res = client.post("/api/users", json={"name": "Alice"})
    assert res.status_code in (201, 409)
    users = client.get("/api/users").json()
    alice = next((u for u in users if u["name"] == "Alice"), None)
    assert alice is not None
    return alice["id"]


def _full_payload(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "import_date": IMPORT_DATE,
        "source": "manual_json",
        "data": {
            "sleep_start_time": "22:00",
            "sleep_end_time": "23:00",
            "sleep_duration_minutes": 60,
            "deep_sleep_minutes": 15,
            "rem_sleep_minutes": 15,
            "light_sleep_minutes": 25,
            "awake_minutes": 5,
            "sleep_score": 85,
            "_run": _RUN,
        },
    }


@pytest.fixture(scope="module")
def first_import(client, user_id):
    res = client.post("/api/imports/sleep", json=_full_payload(user_id))
    assert res.status_code == 201
    body = res.json()
    assert body["source"] == "manual_json"
    assert body["status"] == "parsed"
    assert body["import_date"] == IMPORT_DATE
    return body["id"]


# 1. Valid POST with all data fields → 201, UUID returned
def test_valid_import_201(first_import):
    uuid.UUID(first_import)  # raises if not valid UUID


# 2. Duplicate → 409 with error_code and existing_id
def test_duplicate_409(client, user_id, first_import):
    res = client.post("/api/imports/sleep", json=_full_payload(user_id))
    assert res.status_code == 409
    body = res.json()
    assert body["error_code"] == "duplicate"
    assert body["message"] == "This data has already been imported"
    assert body["existing_id"] == first_import


# 3. Unknown user_id → 404
def test_unknown_user_404(client):
    payload = {
        "user_id": str(uuid.uuid4()),
        "import_date": IMPORT_DATE,
        "source": "manual_json",
        "data": {"sleep_score": 80},
    }
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 404


# 4. Invalid import_date → 422
def test_invalid_date_422(client, user_id):
    payload = {**_full_payload(user_id), "import_date": "2026-13-99"}
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 422


# 5. Invalid source → 422
def test_invalid_source_422(client, user_id):
    payload = {**_full_payload(user_id), "source": "fitbit"}
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 422


# 6. Empty data dict → 422
def test_empty_data_422(client, user_id):
    payload = {
        "user_id": user_id,
        "import_date": IMPORT_DATE,
        "source": "manual_json",
        "data": {},
    }
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 422


# 7. sleep_duration_minutes inconsistent with start/end → 422, field named in error
def test_duration_mismatch_422(client, user_id):
    payload = {
        "user_id": user_id,
        "import_date": IMPORT_DATE,
        "source": "manual_json",
        "data": {
            "sleep_start_time": "01:00",
            "sleep_end_time": "02:00",
            "sleep_duration_minutes": 500,
        },
    }
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 422
    assert "sleep_duration_minutes" in str(res.json().get("detail", {}))


# 8. *_minutes field out of 0-1440 range → 422
def test_minutes_out_of_range_422(client, user_id):
    payload = {
        "user_id": user_id,
        "import_date": IMPORT_DATE,
        "source": "manual_json",
        "data": {"awake_minutes": 1500},
    }
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 422


# 9. sleep_end_time before sleep_start_time → 422
def test_end_before_start_422(client, user_id):
    payload = {
        "user_id": user_id,
        "import_date": IMPORT_DATE,
        "source": "manual_json",
        "data": {"sleep_start_time": "07:00", "sleep_end_time": "06:00"},
    }
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 422


# 10. Single data field → 201
def test_single_field_201(client, user_id):
    payload = {
        "user_id": user_id,
        "import_date": IMPORT_DATE,
        "source": "manual_json",
        "data": {"sleep_score": 85, "_run": _RUN + "_single"},
    }
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 201
    body = res.json()
    assert body["source"] == "manual_json"
    assert body["status"] == "parsed"
    uuid.UUID(body["id"])
