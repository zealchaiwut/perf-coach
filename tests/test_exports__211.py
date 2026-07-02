"""Tests for issue #211: GET /api/exports/workouts CSV download endpoint"""
import csv
import io
import uuid

import httpx
import pytest

from backend.models import Workout
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
DATE_A = "2025-04-01"
DATE_B = "2025-04-02"
DATE_C = "2025-04-03"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
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


@pytest.fixture(scope="module")
def seeded(client, alice_id):
    """Seed known workout rows for export tests."""
    payloads = [
        {
            "user_id": alice_id,
            "workout_date": DATE_A,
            "name": "Morning run",
            "workout_type": "run",
            "distance_km": 10.0,
            "duration_seconds": 3600,
            "avg_hr": 145,
            "tss": 60.0,
            "remarks": None,
        },
        {
            "user_id": alice_id,
            "workout_date": DATE_B,
            "name": "Long run, easy",
            "workout_type": "run",
            "distance_km": 20.0,
            "duration_seconds": 7200,
            "avg_hr": 140,
            "tss": 100.0,
            "remarks": "easy, recovery",
        },
        {
            "user_id": alice_id,
            "workout_date": DATE_C,
            "name": "Afternoon ride",
            "workout_type": "ride",
            "distance_km": 50.0,
            "duration_seconds": 5400,
            "avg_hr": 150,
            "tss": 80.0,
            "remarks": None,
        },
    ]
    for p in payloads:
        res = client.post("/api/workouts", json=p)
        assert res.status_code in (201, 409), f"seed failed: {res.text}"
    return alice_id


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


# (a) CSV headers match columns that actually exist on Workout model

def test_csv_headers_match_model(client, seeded):
    res = client.get(f"/api/exports/workouts?user_id={seeded}")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    rows = _parse_csv(res.text)
    assert len(rows) >= 1
    desired = ["workout_date", "workout_type", "name", "distance_km", "duration_seconds", "avg_hr", "tss", "source", "remarks"]
    model_cols = {c.key for c in Workout.__table__.columns}
    expected_headers = [c for c in desired if c in model_cols]
    assert rows[0] == expected_headers


# (b) types filter returns only matching workout_type rows

def test_types_filter(client, seeded):
    res = client.get(f"/api/exports/workouts?user_id={seeded}&types=run")
    assert res.status_code == 200
    rows = _parse_csv(res.text)
    headers = rows[0]
    type_idx = headers.index("workout_type")
    data_rows = rows[1:]
    assert all(r[type_idx] == "run" for r in data_rows if r)

    res2 = client.get(f"/api/exports/workouts?user_id={seeded}&types=run,ride&from={DATE_A}&to={DATE_C}")
    assert res2.status_code == 200
    rows2 = _parse_csv(res2.text)
    types_seen = {r[type_idx] for r in rows2[1:] if r}
    assert types_seen <= {"run", "ride"}


# (c) from/to date range correctly bounds results

def test_date_range_filter(client, seeded):
    res = client.get(
        f"/api/exports/workouts?user_id={seeded}&from={DATE_A}&to={DATE_B}"
    )
    assert res.status_code == 200
    cd = res.headers.get("content-disposition", "")
    assert f'filename="workouts-{DATE_A}-to-{DATE_B}.csv"' in cd
    rows = _parse_csv(res.text)
    headers = rows[0]
    date_idx = headers.index("workout_date")
    dates = [r[date_idx] for r in rows[1:] if r]
    assert DATE_A in dates
    assert DATE_B in dates
    assert DATE_C not in dates
    assert dates == sorted(dates)


# (d) commas in name and remarks are escaped in output

def test_comma_in_name_and_remarks_escaped(client, seeded):
    res = client.get(
        f"/api/exports/workouts?user_id={seeded}&from={DATE_B}&to={DATE_B}"
    )
    assert res.status_code == 200
    rows = _parse_csv(res.text)
    headers = rows[0]
    name_idx = headers.index("name")
    remarks_idx = headers.index("remarks") if "remarks" in headers else None
    data_rows = [r for r in rows[1:] if r and r[0] == DATE_B]
    assert len(data_rows) == 1
    assert data_rows[0][name_idx] == "Long run, easy"
    if remarks_idx is not None:
        assert data_rows[0][remarks_idx] == "easy, recovery"


# (e) empty date range returns header-only CSV

def test_empty_result_returns_header_only(client, alice_id):
    res = client.get(
        f"/api/exports/workouts?user_id={alice_id}&from=2000-01-01&to=2000-01-02"
    )
    assert res.status_code == 200
    rows = _parse_csv(res.text)
    assert len(rows) == 1
    assert rows[0][0] == "workout_date"


# (f) from > to returns 422

def test_from_after_to_returns_422(client, alice_id):
    res = client.get(
        f"/api/exports/workouts?user_id={alice_id}&from=2025-06-01&to=2025-01-01"
    )
    assert res.status_code == 422


# missing user_id returns 422

def test_missing_user_id_returns_422(client):
    res = client.get("/api/exports/workouts")
    assert res.status_code == 422


# unknown user_id returns 404

def test_unknown_user_returns_404(client):
    unknown = str(uuid.uuid4())
    res = client.get(f"/api/exports/workouts?user_id={unknown}")
    assert res.status_code == 404


# duration_seconds is raw integer, not MM:SS

def test_duration_seconds_is_integer(client, seeded):
    res = client.get(
        f"/api/exports/workouts?user_id={seeded}&from={DATE_A}&to={DATE_A}"
    )
    assert res.status_code == 200
    rows = _parse_csv(res.text)
    headers = rows[0]
    if "duration_seconds" not in headers:
        pytest.skip("duration_seconds not in model")
    dur_idx = headers.index("duration_seconds")
    data_rows = [r for r in rows[1:] if r]
    assert len(data_rows) >= 1
    val = data_rows[0][dur_idx]
    if val:
        assert ":" not in val
        int(val)
