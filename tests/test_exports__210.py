"""Tests for issue #210: GET /api/exports/daily-metrics CSV download endpoint"""
import csv
import io
import datetime
import uuid

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
DATE_A = "2025-03-01"
DATE_B = "2025-03-02"
DATE_C = "2025-03-03"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
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


@pytest.fixture(scope="module")
def seeded(client, alice_id):
    """Seed known daily_metrics rows for export tests."""
    for date in (DATE_A, DATE_B, DATE_C):
        client.delete(f"/api/daily-metrics/{alice_id}/{date}")

    payloads = [
        {
            "user_id": alice_id,
            "metric_date": DATE_A,
            "resting_hr": 55,
            "hrv": 70,
            "sleep_hours": 7.5,
            "energy": 4,
            "mood": 4,
            "notes": "normal day",
        },
        {
            "user_id": alice_id,
            "metric_date": DATE_B,
            "resting_hr": None,
            "hrv": None,
            "sleep_hours": None,
            "energy": None,
            "mood": None,
            "notes": "comma, in notes",
        },
        {
            "user_id": alice_id,
            "metric_date": DATE_C,
            "resting_hr": 60,
            "hrv": 65,
            "sleep_hours": 8.0,
            "energy": 5,
            "mood": 5,
            "notes": None,
        },
    ]
    for p in payloads:
        res = client.post("/api/daily-metrics", json=p)
        assert res.status_code in (201, 409), f"seed failed: {res.text}"
    return alice_id


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


# (a) correct headers returned

def test_correct_headers(client, seeded):
    res = client.get(f"/api/exports/daily-metrics?user_id={seeded}")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    cd = res.headers.get("content-disposition", "")
    assert 'filename="daily-metrics-all.csv"' in cd
    rows = _parse_csv(res.text)
    assert rows[0] == ["metric_date", "rhr", "hrv", "sleep_hours", "energy", "mood", "weight_kg", "notes"]


# (b) date range filter works

def test_date_range_filter(client, seeded):
    res = client.get(
        f"/api/exports/daily-metrics?user_id={seeded}&from={DATE_A}&to={DATE_B}"
    )
    assert res.status_code == 200
    cd = res.headers.get("content-disposition", "")
    assert f'filename="daily-metrics-{DATE_A}-to-{DATE_B}.csv"' in cd
    rows = _parse_csv(res.text)
    dates = [r[0] for r in rows[1:]]
    assert DATE_A in dates
    assert DATE_B in dates
    assert DATE_C not in dates
    assert dates == sorted(dates)


# (c) header-only CSV on empty result

def test_empty_result_returns_header_only(client, alice_id):
    res = client.get(
        f"/api/exports/daily-metrics?user_id={alice_id}&from=2000-01-01&to=2000-01-02"
    )
    assert res.status_code == 200
    rows = _parse_csv(res.text)
    assert len(rows) == 1
    assert rows[0][0] == "metric_date"


# (d) comma in notes field is properly escaped

def test_comma_in_notes_escaped(client, seeded):
    res = client.get(
        f"/api/exports/daily-metrics?user_id={seeded}&from={DATE_B}&to={DATE_B}"
    )
    assert res.status_code == 200
    rows = _parse_csv(res.text)
    data_rows = [r for r in rows[1:] if r and r[0] == DATE_B]
    assert len(data_rows) == 1
    assert data_rows[0][7] == "comma, in notes"


# (e) 404 for unknown user_id

def test_unknown_user_returns_404(client):
    unknown = str(uuid.uuid4())
    res = client.get(f"/api/exports/daily-metrics?user_id={unknown}")
    assert res.status_code == 404


# (f) 422 when from > to

def test_from_after_to_returns_422(client, alice_id):
    res = client.get(
        f"/api/exports/daily-metrics?user_id={alice_id}&from=2025-06-01&to=2025-01-01"
    )
    assert res.status_code == 422
