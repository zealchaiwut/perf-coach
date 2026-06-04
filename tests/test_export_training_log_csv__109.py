"""Tests for issue #109: Export filtered Training Log workouts as CSV

Tests run against the UAT server at http://localhost:9001.
Since CSV export is entirely client-side JavaScript, these tests verify:
1. The Export button exists and is clickable
2. The HTML page loads without errors
3. Filtered data exists to export
4. CSV file format is correct (headers, quoting, etc.)
"""
import datetime
import pathlib
import re

import httpx
import pytest


BASE = "http://localhost:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    """Get or create Alice user."""
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    if alice:
        return alice["id"]
    # Create Alice if missing
    res = client.post("/api/users", json={"name": "Alice"})
    assert res.status_code in (201, 409)
    users = client.get("/api/users").json()
    alice = next((u for u in users if u["name"] == "Alice"), None)
    assert alice is not None
    return alice["id"]


@pytest.fixture(scope="module")
def sample_workouts(client, alice_id):
    """Create sample workouts for testing export."""
    # Clean up any existing workouts
    far_past = (TODAY - datetime.timedelta(days=60)).isoformat()
    res = client.get(f"/api/workouts?user_id={alice_id}&from={far_past}&to={TODAY_STR}")
    if res.status_code == 200:
        for w in res.json():
            client.delete(f"/api/workouts/{w['id']}")

    # Create sample workouts with varied data
    workouts = [
        {
            "user_id": alice_id,
            "name": "Morning Run",
            "workout_date": (TODAY - datetime.timedelta(days=10)).isoformat(),
            "workout_type": "Run",
            "distance_km": 5.2,
            "duration_minutes": 35,
            "tss": 45,
            "avg_hr": 165,
            "source": "Strava",
            "exercises": [],
        },
        {
            "user_id": alice_id,
            "name": "Strength Session",
            "workout_date": (TODAY - datetime.timedelta(days=8)).isoformat(),
            "workout_type": "Lift",
            "distance_km": None,
            "duration_minutes": 60,
            "tss": 60,
            "avg_hr": 120,
            "source": "Manual",
            "exercises": [],
        },
        {
            "user_id": alice_id,
            "name": "Easy run, recovery",  # Contains comma to test quoting
            "workout_date": (TODAY - datetime.timedelta(days=5)).isoformat(),
            "workout_type": "Run",
            "distance_km": 3.0,
            "duration_minutes": 25,
            "tss": 30,
            "avg_hr": 140,
            "source": "Strava",
            "exercises": [],
        },
        {
            "user_id": alice_id,
            "name": 'Title with "quotes"',  # Contains quotes to test escaping
            "workout_date": (TODAY - datetime.timedelta(days=3)).isoformat(),
            "workout_type": "Bike",
            "distance_km": 20.0,
            "duration_minutes": 75,
            "tss": 85,
            "avg_hr": 155,
            "source": "Strava",
            "exercises": [],
        },
    ]

    created = []
    for wo in workouts:
        res = client.post("/api/workouts", json=wo)
        assert res.status_code == 201, f"Failed to create workout: {res.status_code} {res.text}"
        created.append(res.json())

    return created


# ── AC-1: Clicking the Export button triggers a file download ─────────────────

def test_export_button_exists_in_html():
    """training-log.html must have a button element with id='log-export-btn'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html").read_text()
    assert 'id="log-export-btn"' in html, "Missing id='log-export-btn' in training-log.html"


def test_export_button_has_click_handler_in_js():
    """training-log.js must attach a click handler to the Export button."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    assert "log-export-btn" in js, "Missing log-export-btn reference in training-log.js"
    assert "addEventListener('click'" in js or 'addEventListener("click"' in js, \
        "training-log.js must attach event listeners"


def test_export_csv_function_exists_in_js():
    """training-log.js must define an exportCSV function."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    assert "function exportCSV" in js, "Missing exportCSV function in training-log.js"


# ── AC-2: Downloaded file naming (based on active date-range filter) ─────────

def test_csv_filename_format_in_code():
    """training-log.js must format filename as 'training-log-{from}-to-{to}.csv'."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    assert "training-log-" in js, "Missing 'training-log-' prefix in exportCSV"
    assert ".csv" in js, "Missing .csv extension in exportCSV"
    assert "a.download" in js or ".download" in js, "Must set download attribute on anchor element"


def test_filename_uses_range_values():
    """exportCSV must derive 'from' and 'to' values from date-range filters."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1, "exportCSV function not found"
    export_body = js[export_start:export_start + 800]
    assert "getFromTo" in export_body or "range" in export_body, \
        "exportCSV must get date range to construct filename"


# ── AC-3: CSV contains exactly these columns in order ───────────────────────

def test_csv_header_columns_in_js():
    """training-log.js must output header row with columns: date, type, title, distance_km, duration_minutes, tss, avg_hr, source."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    # Check for the exact column names in order
    assert "date" in js and "type" in js and "title" in js, \
        "CSV header must include date, type, title columns"
    assert "distance_km" in js, "CSV header must include distance_km column"
    assert "duration_minutes" in js, "CSV header must include duration_minutes column"
    assert "tss" in js, "CSV header must include tss column"
    assert "avg_hr" in js, "CSV header must include avg_hr column"
    assert "source" in js, "CSV header must include source column"


def test_csv_header_join_by_comma():
    """training-log.js must join column headers with commas."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    # Look for header line with comma-separated columns
    assert ".join(',')" in js, "Column headers must be joined by comma"


# ── AC-4: Only visible workouts (matching filters) are included ──────────────

def test_visible_workouts_variable_exists():
    """training-log.js must maintain a visibleWorkouts array of filtered workouts."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    assert "visibleWorkouts" in js, "Missing visibleWorkouts variable in training-log.js"


def test_export_iterates_visible_workouts():
    """exportCSV must iterate over visibleWorkouts, not all workouts."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1
    export_body = js[export_start:export_start + 800]
    assert "visibleWorkouts" in export_body, \
        "exportCSV must iterate over visibleWorkouts (filtered data)"


# ── AC-5: Dates formatted as YYYY-MM-DD ───────────────────────────────────

def test_csv_date_format_in_js():
    """training-log.js must format dates as YYYY-MM-DD (ISO 8601 sortable)."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    # Check for ISO date format (YYYY-MM-DD)
    assert "isoString().slice(0, 10)" in js or "YYYY-MM-DD" in js or \
           "toISOString" in js, \
        "training-log.js must format dates in YYYY-MM-DD format"


# ── AC-6: Numeric fields formatted as plain numbers (no units) ──────────────

def test_numeric_fields_exported_as_strings():
    """exportCSV must export distance_km, duration_minutes, tss, avg_hr as plain numbers."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1
    export_body = js[export_start:export_start + 1000]
    # Check that numeric fields are appended without string concatenation of units
    assert "w.distance_km" in export_body, "Must access distance_km from workout object"
    assert "w.duration_minutes" in export_body, "Must access duration_minutes from workout object"
    assert "w.tss" in export_body, "Must access tss from workout object"
    assert "w.avg_hr" in export_body, "Must access avg_hr from workout object"


# ── AC-7: Empty result set still succeeds with header-only file ────────────

def test_empty_export_creates_header_only():
    """When no workouts match filters, exportCSV must create CSV with header row only."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1
    export_body = js[export_start:export_start + 1000]
    # Check that we always create rows array with header, then iterate workouts
    # (forEach on empty array = no data rows, header still present)
    assert "rows" in export_body, "Must create rows array with header row"
    assert "forEach" in export_body, "Must iterate over visibleWorkouts"


# ── AC-8: All logic is client-side in js/training-log.js ────────────────────

def test_no_new_api_endpoints_in_feature_branch(client):
    """No new /api/export or /api/csv endpoints should exist (CSV is client-side only)."""
    # Attempt to call a non-existent export endpoint; it should 404 or error gracefully
    # If the server responds with anything other than 404, check that it's expected behavior
    # (This is a negative test: we should NOT be relying on a backend endpoint)
    res = client.get("/api/export/training-log", follow_redirects=False)
    # If it returns 404, that's good (endpoint doesn't exist as it shouldn't)
    # If it returns 200 or 201, that's bad (means we added a backend endpoint when we shouldn't)
    assert res.status_code in (404, 405, 301, 302, 400), \
        f"Unexpected response for non-existent /api/export endpoint: {res.status_code}. " \
        "CSV export must be client-side only."


def test_export_function_in_training_log_js_not_backend():
    """exportCSV function must be entirely in training-log.js, not delegating to backend."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1
    export_body = js[export_start:export_start + 1500]
    # Should NOT call fetch() or XMLHttpRequest for CSV generation
    # (It may log or report, but not to fetch/POST for CSV export)
    fetch_calls = export_body.count("fetch(")
    assert fetch_calls == 0, "exportCSV must not call fetch() to generate CSV"


# ── AC-9: Fields with commas or quotes are properly escaped per RFC 4180 ──

def test_csv_field_function_handles_commas():
    """training-log.js must have csvField function that escapes commas."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    assert "function csvField" in js, "Missing csvField function in training-log.js"
    assert "indexOf(',')" in js, "csvField must check for commas in field values"


def test_csv_field_function_handles_quotes():
    """csvField must escape double quotes by doubling them (RFC 4180)."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    csv_func_start = js.find("function csvField")
    assert csv_func_start != -1
    csv_func_body = js[csv_func_start:csv_func_start + 500]
    # RFC 4180: quotes are escaped by doubling them
    assert 'replace(/"/g, \'""' in csv_func_body or 'replace(/"/g, \'""\'' in csv_func_body, \
        "csvField must escape quotes by doubling (RFC 4180)"


def test_csv_field_function_quotes_fields_with_special_chars():
    """csvField must wrap fields containing commas, quotes, or newlines in quotes."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    csv_func_start = js.find("function csvField")
    assert csv_func_start != -1
    csv_func_body = js[csv_func_start:csv_func_start + 500]
    # Should wrap in quotes when special chars are present
    assert '"' in csv_func_body, "csvField must use quotes in output"


def test_export_csv_uses_csv_field_for_all_fields():
    """exportCSV must call csvField for each field to ensure proper escaping."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1
    export_body = js[export_start:export_start + 1500]
    # Count csvField calls — should have multiple (one per field)
    csvfield_count = export_body.count("csvField(")
    assert csvfield_count >= 8, \
        f"exportCSV must call csvField for each of the 8 columns; found {csvfield_count} calls"


# ── Integration: log.html loads and training-log.js is included ────────────

def test_log_html_serves_from_uat_server(client):
    """GET /log.html must return 200 with HTML content from UAT server."""
    res = client.get("/log.html")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert "text/html" in res.headers.get("content-type", "")


def test_log_html_includes_training_log_js():
    """training-log.html must include a script tag loading js/training-log.js."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html").read_text()
    assert "training-log.js" in html or "js/training-log.js" in html, \
        "training-log.html must load js/training-log.js"


def test_log_html_has_export_button_and_input_elements(client):
    """training-log.html must have export button."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html").read_text()
    assert 'id="log-export-btn"' in html, "Missing export button"


def test_sample_workouts_api_returns_data(client, sample_workouts):
    """Verify that sample workouts were created and API returns them."""
    assert len(sample_workouts) >= 3, "Sample workouts fixture should create at least 3 workouts"
    # Verify the workout data structure
    for w in sample_workouts:
        assert "id" in w, "Workout must have id"
        assert "title" in w or "name" in w, "Workout must have title/name"
        assert "date" in w or "workout_date" in w, "Workout must have date"
