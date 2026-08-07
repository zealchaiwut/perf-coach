"""Tests for issue #218: POST /api/imports/sleep"""
import uuid

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_RUN = str(uuid.uuid4())[:8]
IMPORT_DATE = "2026-05-01"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    if alice:
        return alice["id"]
    res = client.post("/api/users", json={"name": "Alice"}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
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


# 3. Unauthenticated request → 401 (endpoint resolves user from session, not body)
def test_unauthenticated_401(client):
    payload = {
        "import_date": IMPORT_DATE,
        "source": "manual_json",
        "data": {"sleep_score": 80},
    }
    res = client.post("/api/imports/sleep", json=payload)
    assert res.status_code == 401


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


# ── GET /api/imports/sleep (issue #219) ───────────────────────────────────────

LIST_DATE_A = "2026-01-15"
LIST_DATE_B = "2026-02-20"
LIST_DATE_C = "2026-03-10"


@pytest.fixture(scope="module")
def list_user_id(client):
    name = f"ListUser_{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next((u for u in users if u["name"] == name), None)
    assert u is not None
    return u["id"]


def _post_import(client, uid: str, import_date: str, tag: str) -> str:
    res = client.post(
        "/api/imports/sleep",
        json={
            "user_id": uid,
            "import_date": import_date,
            "source": "manual_json",
            "data": {"sleep_score": 80, "_tag": tag},
        },
    )
    assert res.status_code == 201
    return res.json()["id"]


@pytest.fixture(scope="module")
def list_imports(client, list_user_id):
    ids = [
        _post_import(client, list_user_id, LIST_DATE_A, f"{_RUN}_a"),
        _post_import(client, list_user_id, LIST_DATE_B, f"{_RUN}_b"),
        _post_import(client, list_user_id, LIST_DATE_C, f"{_RUN}_c"),
    ]
    return ids


# (a) Empty list for user with no imports
def test_get_list_empty(client):
    new_user = client.post("/api/users", json={"name": f"EmptyUser_{_RUN}"}).json()
    uid = new_user["id"]
    res = client.get(f"/api/imports/sleep?user_id={uid}")
    assert res.status_code == 200
    body = res.json()
    assert body["imports"] == []
    assert body["count"] == 0
    assert body["summary"]["total"] == 0
    assert body["summary"]["by_status"] == {}
    assert body["summary"]["date_range"] == {"earliest": None, "latest": None}


# (b) Returns correct imports for valid user_id
def test_get_list_returns_imports(client, list_user_id, list_imports):
    res = client.get(f"/api/imports/sleep?user_id={list_user_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == len(list_imports)
    assert len(body["imports"]) == body["count"]
    returned_ids = {i["id"] for i in body["imports"]}
    for iid in list_imports:
        assert iid in returned_ids


# (c) from/to date range filter
def test_get_list_date_range(client, list_user_id, list_imports):
    res = client.get(f"/api/imports/sleep?user_id={list_user_id}&from=2026-01-01&to=2026-02-28")
    assert res.status_code == 200
    body = res.json()
    dates = [i["import_date"] for i in body["imports"]]
    assert all("2026-01-01" <= d <= "2026-02-28" for d in dates)
    assert LIST_DATE_A in dates
    assert LIST_DATE_B in dates
    assert LIST_DATE_C not in dates


# (d) status filter
def test_get_list_status_filter(client, list_user_id, list_imports):
    res = client.get(f"/api/imports/sleep?user_id={list_user_id}&status=parsed")
    assert res.status_code == 200
    body = res.json()
    assert all(i["import_status"] == "parsed" for i in body["imports"])

    res2 = client.get(f"/api/imports/sleep?user_id={list_user_id}&status=rejected")
    assert res2.status_code == 200
    assert res2.json()["count"] == 0


# (e) summary.by_status counts match actual records
def test_get_list_summary_by_status(client, list_user_id, list_imports):
    res = client.get(f"/api/imports/sleep?user_id={list_user_id}")
    assert res.status_code == 200
    body = res.json()
    by_status = body["summary"]["by_status"]
    assert body["summary"]["total"] == body["count"]
    assert sum(by_status.values()) == body["count"]


# (f) raw_data and parsed_data absent from every item
def test_get_list_no_raw_parsed(client, list_user_id, list_imports):
    res = client.get(f"/api/imports/sleep?user_id={list_user_id}")
    assert res.status_code == 200
    for item in res.json()["imports"]:
        assert "raw_data" not in item
        assert "parsed_data" not in item


# 404 for unknown user_id
def test_get_list_unknown_user_404(client):
    res = client.get(f"/api/imports/sleep?user_id={uuid.uuid4()}")
    assert res.status_code == 404
