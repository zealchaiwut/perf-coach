"""
Tests for issue #414: CSV export endpoints for weight entries and targets.
Updated for issue #488: endpoints now require session auth, no client user_id.
6 AC anchors:
  (a) entries export returns valid CSV with correct headers
  (b) date range filter returns only entries within range
  (c) header-only CSV when no entries (no crash)
  (d) notes containing commas are quoted correctly
  (e) targets export returns valid CSV with achieved_pct computed correctly
  (f) status filter on targets returns only matching rows
"""
import csv
import io
import os
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.db import engine
from backend.models import User as _UserModel

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")

DATE_A = "2025-04-01"
DATE_B = "2025-04-15"
DATE_C = "2025-05-01"

_TARGET_START = "2025-01-01"
_TARGET_END = "2025-04-01"
_TARGET_ENDED_AT = "2025-04-10T08:00:00+00:00"
_EXPORT_TEST_PW = "export-test-pw-414"


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def test_uid(client):
    name = f"wt341_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, f"user creation failed: {r.text}"
    uid = r.json()["id"]
    pw_hash = _hash_pw(_EXPORT_TEST_PW)
    with _OrmSess(engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    client.delete(f"/api/users/{uid}")


@pytest.fixture(scope="module")
def session_cookie(client, test_uid):
    with _OrmSess(engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_uid))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _EXPORT_TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def seeded_entries(client, test_uid, session_cookie):
    client.post("/api/weight-entries", json={
        "entry_date": DATE_A, "weight_kg": 80.0, "notes": "normal day",
    }, cookies={"session": session_cookie})
    client.post("/api/weight-entries", json={
        "entry_date": DATE_B, "weight_kg": 79.5, "notes": "note with, comma",
    }, cookies={"session": session_cookie})
    client.post("/api/weight-entries", json={
        "entry_date": DATE_C, "weight_kg": 79.0,
    }, cookies={"session": session_cookie})
    return session_cookie


@pytest.fixture(scope="module")
def seeded_targets(client, test_uid, session_cookie):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weight_targets "
                "(user_id, start_weight_kg, start_date, target_weight_kg, target_date, status, ended_at, end_weight_kg) "
                "VALUES (:uid, 80.0, :sd, 70.0, :td, 'achieved', :ea, 74.0)"
            ),
            {"uid": test_uid, "sd": _TARGET_START, "td": _TARGET_END, "ea": _TARGET_ENDED_AT},
        )
        conn.execute(
            text(
                "INSERT INTO weight_targets "
                "(user_id, start_weight_kg, start_date, target_weight_kg, target_date, status, ended_at) "
                "VALUES (:uid, 80.0, '2025-05-01', 70.0, '2025-08-01', 'abandoned', :ea)"
            ),
            {"uid": test_uid, "ea": _TARGET_ENDED_AT},
        )
    return session_cookie


# ── (a) entries export returns valid CSV with correct headers ──────────────────

def test_a_entries_export_has_correct_headers(client, seeded_entries):
    """AC (a): GET /api/exports/weight-entries returns text/csv with exact header row."""
    r = client.get("/api/exports/weight-entries", cookies={"session": seeded_entries})
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    rows = _parse_csv(r.text)
    assert rows[0] == ["entry_date", "entry_time", "weight_kg", "notes", "source"]


# ── (b) date range filter returns only entries within range ────────────────────

def test_b_date_range_filter(client, seeded_entries):
    """AC (b): from/to params restrict rows and set filename correctly."""
    r = client.get(
        f"/api/exports/weight-entries?from={DATE_A}&to={DATE_B}",
        cookies={"session": seeded_entries},
    )
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert f'filename="weight-entries-{DATE_A}-to-{DATE_B}.csv"' in cd
    rows = _parse_csv(r.text)
    dates = [row[0] for row in rows[1:] if row]
    assert DATE_A in dates
    assert DATE_B in dates
    assert DATE_C not in dates
    assert dates == sorted(dates)


# ── (c) header-only CSV when no entries ───────────────────────────────────────

def test_c_header_only_when_empty(client, seeded_entries):
    """AC (c): empty result returns header row only without error."""
    r = client.get(
        "/api/exports/weight-entries?from=2000-01-01&to=2000-01-31",
        cookies={"session": seeded_entries},
    )
    assert r.status_code == 200
    rows = _parse_csv(r.text)
    assert len(rows) == 1
    assert rows[0][0] == "entry_date"


# ── (d) notes containing commas are quoted correctly ──────────────────────────

def test_d_comma_in_notes_quoted(client, seeded_entries):
    """AC (d): csv.reader reconstructs comma-containing notes as a single field."""
    r = client.get(
        f"/api/exports/weight-entries?from={DATE_B}&to={DATE_B}",
        cookies={"session": seeded_entries},
    )
    assert r.status_code == 200
    rows = _parse_csv(r.text)
    data_rows = [row for row in rows[1:] if row and row[0] == DATE_B]
    assert len(data_rows) >= 1
    assert data_rows[0][3] == "note with, comma"


# ── (e) targets export returns CSV with achieved_pct computed correctly ────────

def test_e_targets_export_achieved_pct(client, seeded_targets):
    """AC (e): achieved_pct = (start - end) / (start - target) * 100 = 60.0 for test data."""
    r = client.get("/api/exports/weight-targets", cookies={"session": seeded_targets})
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    cd = r.headers.get("content-disposition", "")
    assert 'filename="weight-targets-all.csv"' in cd
    rows = _parse_csv(r.text)
    assert rows[0] == [
        "start_date", "target_date", "ended_at", "status",
        "start_weight_kg", "target_weight_kg", "end_weight_kg",
        "achieved_pct", "duration_days", "notes",
    ]
    achieved_row = next((row for row in rows[1:] if row and row[3] == "achieved"), None)
    assert achieved_row is not None
    # start=80, target=70, end=74 → achieved_pct = (80-74)/(80-70)*100 = 60.0
    assert float(achieved_row[7]) == 60.0


# ── (f) status filter on targets returns only matching rows ───────────────────

def test_f_status_filter_targets(client, seeded_targets):
    """AC (f): ?status=achieved returns only achieved rows; filename includes status."""
    r = client.get("/api/exports/weight-targets?status=achieved",
                   cookies={"session": seeded_targets})
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert 'filename="weight-targets-achieved.csv"' in cd
    rows = _parse_csv(r.text)
    data_rows = [row for row in rows[1:] if row]
    assert len(data_rows) >= 1
    assert all(row[3] == "achieved" for row in data_rows)
    assert not any(row[3] == "abandoned" for row in data_rows)
