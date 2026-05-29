"""Tests for issue #128: Add CSV Export to Training Log Page

CSV export is entirely client-side; these tests verify:
- The JS implementation matches all acceptance criteria
- The API provides the required fields for the export
"""
import datetime
import pathlib
import re

import httpx
import pytest

BASE     = "http://localhost:9001"
TODAY    = datetime.date.today()
TODAY_STR = TODAY.isoformat()

JS_PATH  = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js"
HTML_PATH = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html"


# ── Fixtures ───────────────────────────────────────────────────────────────────

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
def sample_workouts(client, alice_id):
    """Create workouts covering special-char and optional-field scenarios."""
    payloads = [
        {
            "user_id": alice_id,
            "name": "Morning Run",
            "workout_date": (TODAY - datetime.timedelta(days=7)).isoformat(),
            "workout_type": "run",
            "duration_seconds": 2100,
            "distance_km": 5.2,
            "avg_hr": 155,
            "tss": 42.0,
            "exercises": [],
        },
        {
            "user_id": alice_id,
            "name": "Hills, Tempo",  # comma in title
            "workout_date": (TODAY - datetime.timedelta(days=5)).isoformat(),
            "workout_type": "run",
            "duration_seconds": 3600,
            "distance_km": 8.0,
            "avg_hr": 168,
            "tss": 75.0,
            "exercises": [],
        },
        {
            "user_id": alice_id,
            'name': 'Lift "heavy"',  # quotes in title
            "workout_date": (TODAY - datetime.timedelta(days=3)).isoformat(),
            "workout_type": "lift",
            "duration_seconds": 3600,
            "exercises": [],
        },
    ]
    created = []
    for p in payloads:
        res = client.post("/api/workouts", json=p)
        assert res.status_code == 201, f"Failed to create workout: {res.text}"
        created.append(res.json())
    return created


# ── AC-1: Export button exists and has handler ─────────────────────────────────

def test_export_button_in_html():
    html = HTML_PATH.read_text()
    assert 'id="log-export-btn"' in html


def test_export_button_handler_in_js():
    js = JS_PATH.read_text()
    assert "log-export-btn" in js
    # Must wire to exportCSV (not alert)
    assert "alert" not in js[js.find("log-export-btn"):]


# ── AC-2: Filename pattern ─────────────────────────────────────────────────────

def test_filename_pattern_in_js():
    js = JS_PATH.read_text()
    # Filename must embed from/to dates
    assert "'training-log-' + fromDate + '-to-' + toDate + '.csv'" in js


def test_filename_defaults_to_today_when_filters_unset():
    js = JS_PATH.read_text()
    export_body = _export_body(js)
    # When filters.from / filters.to are empty, today's ISO date is used
    assert "filters.from || today" in export_body
    assert "filters.to   || today" in export_body


# ── AC-3: Correct header row ──────────────────────────────────────────────────

def test_csv_header_exact_order():
    js = JS_PATH.read_text()
    assert "'date,type,title,distance_km,duration_minutes,avg_hr,tss,source'" in js


# ── AC-5: Rest-day rows excluded ──────────────────────────────────────────────

def test_rest_entries_skipped_in_export():
    js = JS_PATH.read_text()
    export_body = _export_body(js)
    assert "entry.type === 'rest'" in export_body


# ── AC-6: RFC 4180 CSV escaping ───────────────────────────────────────────────

def test_csvField_function_exists():
    js = JS_PATH.read_text()
    assert "function csvField" in js


def test_csvField_escapes_commas():
    js = JS_PATH.read_text()
    func_body = _func_body(js, "function csvField")
    assert "indexOf(',')" in func_body


def test_csvField_escapes_double_quotes_by_doubling():
    js = JS_PATH.read_text()
    func_body = _func_body(js, "function csvField")
    assert 'replace(/"/g, \'""' in func_body or 'replace(/"/g, "\\"\\"' in func_body


def test_csvField_escapes_newlines():
    js = JS_PATH.read_text()
    func_body = _func_body(js, "function csvField")
    assert r"indexOf('\n')" in func_body or "indexOf('\\n')" in func_body


def test_export_calls_csvField_for_every_column():
    js = JS_PATH.read_text()
    export_body = _export_body(js)
    count = export_body.count("csvField(")
    assert count >= 8, f"Expected ≥8 csvField calls (one per column), found {count}"


# ── AC-7: Empty result set → header-only CSV, no error ────────────────────────

def test_empty_result_still_produces_header():
    js = JS_PATH.read_text()
    export_body = _export_body(js)
    # rows is always initialised with the header before iterating
    header_idx = export_body.find("'date,type,title")
    rows_idx    = export_body.find("var rows")
    assert rows_idx != -1, "Must initialise rows array"
    assert header_idx != -1, "Header row must be in export function"
    assert header_idx > rows_idx, "Header row must be the first element of rows"


# ── AC-9: Client-side only — no new API endpoint, no fetch inside exportCSV ───

def test_no_fetch_inside_exportCSV():
    js = JS_PATH.read_text()
    export_body = _export_body(js)
    assert export_body.count("fetch(") == 0


def test_no_new_export_api_endpoint(client):
    res = client.get("/api/export/training-log", follow_redirects=False)
    assert res.status_code in (404, 405), (
        f"No backend export endpoint should exist; got {res.status_code}"
    )


# ── Integration: API returns the fields used in the CSV ───────────────────────

def test_api_returns_required_csv_fields(client, alice_id, sample_workouts):
    from_date = (TODAY - datetime.timedelta(days=14)).isoformat()
    res = client.get(
        f"/api/training-log?user_id={alice_id}&from={from_date}&to={TODAY_STR}"
    )
    assert res.status_code == 200
    weeks = res.json()["weeks"]
    assert weeks, "Expected at least one week of data"

    workouts = [e for w in weeks for e in w["entries"] if e["type"] != "rest"]
    assert workouts, "Expected at least one workout entry"

    required = {"date", "type", "title", "duration_minutes", "distance_km", "avg_hr", "tss", "source"}
    for entry in workouts:
        missing = required - set(entry.keys())
        assert not missing, f"API entry missing fields: {missing}"


def test_api_dates_are_iso_format(client, alice_id, sample_workouts):
    from_date = (TODAY - datetime.timedelta(days=14)).isoformat()
    res = client.get(
        f"/api/training-log?user_id={alice_id}&from={from_date}&to={TODAY_STR}"
    )
    assert res.status_code == 200
    workouts = [e for w in res.json()["weeks"] for e in w["entries"] if e["type"] != "rest"]
    for entry in workouts:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"]), (
            f"Date not YYYY-MM-DD: {entry['date']}"
        )


def test_api_workout_with_comma_title_accessible(client, alice_id, sample_workouts):
    """Verify a comma-in-title workout is returned so exportCSV can quote it."""
    from_date = (TODAY - datetime.timedelta(days=14)).isoformat()
    res = client.get(
        f"/api/training-log?user_id={alice_id}&from={from_date}&to={TODAY_STR}"
    )
    assert res.status_code == 200
    titles = [e["title"] for w in res.json()["weeks"] for e in w["entries"] if e["type"] != "rest"]
    assert any("," in (t or "") for t in titles), (
        "Expected a workout with a comma in its title"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _func_body(js: str, marker: str, max_chars: int = 600) -> str:
    idx = js.find(marker)
    assert idx != -1, f"Marker not found: {marker}"
    return js[idx: idx + max_chars]


def _export_body(js: str, max_chars: int = 1200) -> str:
    return _func_body(js, "function exportCSV", max_chars)
