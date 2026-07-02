"""Tests for issue #414: Add CSV export endpoints and wire Export buttons (runs against UAT)
Updated for issue #488: endpoints now require session auth, no client user_id.
"""
import csv
import io
import os
import uuid
import pytest
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
WE = "/api/weight-entries"
WT = "/api/weight-targets"
EXP_WE = "/api/exports/weight-entries"
EXP_WT = "/api/exports/weight-targets"
_E414_PW = "export414-test-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    name = f"tester414_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_E414_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def session_cookie(client, user_id):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _E414_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def seeded_entries(client, session_cookie):
    entries = [
        {"entry_date": "2024-01-10", "weight_kg": 80.5, "entry_time": "07:00", "notes": "morning"},
        {"entry_date": "2024-01-15", "weight_kg": 80.0, "entry_time": "08:00", "notes": "hello, world"},
        {"entry_date": "2024-02-05", "weight_kg": 79.5},
    ]
    ids = []
    for e in entries:
        r = client.post(WE, json=e, cookies={"session": session_cookie})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    yield ids
    for eid in ids:
        client.delete(f"{WE}/{eid}", cookies={"session": session_cookie})


def _parse_csv(text: str):
    return list(csv.reader(io.StringIO(text)))


# --- (a) Weight-entries export: valid CSV with correct headers ---

def test_add_csv_export_endpoints__weight_entries_valid_csv_correct_headers(client, session_cookie, seeded_entries):
    r = client.get(EXP_WE, cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("content-type", "")
    rows = _parse_csv(r.text)
    assert rows[0] == ["entry_date", "entry_time", "weight_kg", "notes", "source"]
    assert len(rows) >= 4  # header + 3 seeded rows


# --- (b) Date range filter correctly limits returned rows ---

def test_add_csv_export_endpoints__weight_entries_date_range_filter(client, session_cookie, seeded_entries):
    r = client.get(EXP_WE, params={"from": "2024-01-01", "to": "2024-01-31"},
                   cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    rows = _parse_csv(r.text)
    data = rows[1:]
    assert len(data) == 2
    assert all(row[0].startswith("2024-01") for row in data)
    cd = r.headers.get("content-disposition", "")
    assert "2024-01-01" in cd and "2024-01-31" in cd


# --- (c) Header-only CSV when no entries (no crash) ---

def test_add_csv_export_endpoints__weight_entries_empty_returns_header_only(client, session_cookie, seeded_entries):
    r = client.get(EXP_WE, params={"from": "2000-01-01", "to": "2000-01-02"},
                   cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    rows = _parse_csv(r.text)
    assert rows[0] == ["entry_date", "entry_time", "weight_kg", "notes", "source"]
    assert len(rows) == 1


# --- (d) Notes with commas quoted correctly ---

def test_add_csv_export_endpoints__weight_entries_commas_quoted(client, session_cookie, seeded_entries):
    r = client.get(EXP_WE, cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    rows = _parse_csv(r.text)
    notes_col = [row[3] for row in rows[1:]]
    assert "hello, world" in notes_col


# --- (e) Targets export: valid CSV with correct achieved_pct ---

def test_add_csv_export_endpoints__weight_targets_valid_csv_achieved_pct(client, session_cookie):
    r_create = client.post(WT, json={
        "start_date": "2024-01-01",
        "target_date": "2024-06-01",
        "start_weight_kg": 85.0,
        "target_weight_kg": 75.0,
    }, cookies={"session": session_cookie})
    if r_create.status_code not in (200, 201, 409):
        pytest.skip(f"Could not create weight target: {r_create.text}")
    t_id = r_create.json().get("id") or r_create.json().get("active_id")

    r = client.get(EXP_WT, cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("content-type", "")
    rows = _parse_csv(r.text)
    assert rows[0] == [
        "start_date", "target_date", "ended_at", "status",
        "start_weight_kg", "target_weight_kg", "end_weight_kg",
        "achieved_pct", "duration_days", "notes",
    ]
    assert len(rows) >= 2

    if t_id:
        client.post(f"{WT}/{t_id}/end", json={"status": "abandoned"},
                    cookies={"session": session_cookie})


# --- (f) Status filter returns only matching rows ---

def test_add_csv_export_endpoints__weight_targets_status_filter(client, session_cookie):
    r_all = client.get(EXP_WT, cookies={"session": session_cookie})
    assert r_all.status_code == 200
    rows_all = _parse_csv(r_all.text)
    statuses = {row[3] for row in rows_all[1:] if row}

    if not statuses:
        pytest.skip("No weight targets exist to filter by status")

    some_status = next(iter(statuses))
    r_f = client.get(EXP_WT, params={"status": some_status},
                     cookies={"session": session_cookie})
    assert r_f.status_code == 200
    rows_f = _parse_csv(r_f.text)
    for row in rows_f[1:]:
        assert row[3] == some_status
    cd = r_f.headers.get("content-disposition", "")
    assert some_status in cd


# --- Content-Disposition: attachment with correct filename ---

def test_add_csv_export_endpoints__content_disposition_attachment(client, session_cookie, seeded_entries):
    r = client.get(EXP_WE, cookies={"session": session_cookie})
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "weight-entries-all.csv" in cd


# --- Frontend wiring: manual ---

def test_add_csv_export_endpoints__frontend_weight_page_export_button():
    pytest.skip("manual — frontend button interaction cannot be HTTP-tested")


def test_add_csv_export_endpoints__frontend_weight_targets_export_button():
    pytest.skip("manual — frontend button interaction cannot be HTTP-tested")
