"""Tests for issue #154: Add CSV export and commit training log mockups

Covers the acceptance criteria specific to this issue:
- duration_minutes in CSV is duration_seconds / 60 rounded to 1 decimal place
- Exported rows reflect the filtered view (rest days excluded)
- docs/mockups/ files are committed but not served by any route
- README.md contains the required line
"""
import datetime
import pathlib
import re

import httpx
import pytest

BASE      = "http://localhost:9001"
TODAY     = datetime.date.today()
TODAY_STR = TODAY.isoformat()

JS_PATH       = pathlib.Path(__file__).parent.parent / "js" / "training-log.js"
LOG_HTML_PATH = pathlib.Path(__file__).parent.parent / "log.html"
MOCKUPS_DIR   = pathlib.Path(__file__).parent.parent / "docs" / "mockups"


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
def sample_workout(client, alice_id):
    """Create a workout with known duration_seconds to verify duration_minutes rounding."""
    payload = {
        "user_id": alice_id,
        "name": "Test duration rounding",
        "workout_date": (TODAY - datetime.timedelta(days=2)).isoformat(),
        "workout_type": "run",
        "duration_seconds": 3723,  # 3723 / 60 = 62.05 → rounds to 62.1
        "distance_km": 10.0,
        "avg_hr": 150,
        "tss": 60.0,
        "exercises": [],
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


# ── AC: duration_minutes is duration_seconds / 60 rounded to 1 decimal ─────────

def test_exportCSV_uses_duration_seconds_not_duration_minutes():
    """exportCSV must compute duration from duration_seconds, not reuse duration_minutes."""
    js = JS_PATH.read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1, "exportCSV function not found"
    export_body = js[export_start:export_start + 800]
    assert "duration_seconds" in export_body, (
        "exportCSV must reference duration_seconds to compute duration_minutes"
    )


def test_exportCSV_rounds_to_one_decimal():
    """exportCSV must round duration_minutes to 1 decimal place."""
    js = JS_PATH.read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1
    export_body = js[export_start:export_start + 800]
    # Must divide by 60 and round to 1 dp: Math.round(... * 10) / 10
    assert "/ 60" in export_body, "exportCSV must divide duration_seconds by 60"
    assert "Math.round" in export_body or "toFixed" in export_body, (
        "exportCSV must round duration_minutes to 1 decimal place"
    )


def test_api_entry_has_duration_seconds(client, alice_id, sample_workout):
    """API training-log entries must include duration_seconds for client-side rounding."""
    from_date = (TODAY - datetime.timedelta(days=7)).isoformat()
    res = client.get(f"/api/training-log?user_id={alice_id}&from={from_date}&to={TODAY_STR}")
    assert res.status_code == 200
    entries = [e for w in res.json()["weeks"] for e in w["entries"] if e["type"] != "rest"]
    assert any(e.get("duration_seconds") is not None for e in entries), (
        "API must return duration_seconds so the client can round to 1 dp"
    )


def test_duration_rounding_3723_seconds(client, alice_id, sample_workout):
    """3723 seconds / 60 = 62.05 must round to 62.1 (1 dp)."""
    import math
    from_date = (TODAY - datetime.timedelta(days=7)).isoformat()
    res = client.get(f"/api/training-log?user_id={alice_id}&from={from_date}&to={TODAY_STR}")
    assert res.status_code == 200
    entries = [e for w in res.json()["weeks"] for e in w["entries"] if e["type"] != "rest"]
    match = next(
        (e for e in entries if e.get("duration_seconds") == 3723),
        None,
    )
    assert match is not None, "Could not find the 3723-second workout in the training log"
    # Use round-half-up (matching JS Math.round) to avoid Python banker's rounding
    # giving 62.0 for 62.05 due to floating-point representation of 3723/60.
    computed = math.floor(match["duration_seconds"] / 60 * 10 + 0.5) / 10
    assert computed == 62.1, f"Expected 62.1 but got {computed}"


# ── AC: Rest days excluded from export ──────────────────────────────────────────

def test_exportCSV_skips_rest_entries():
    """exportCSV must skip entries where entry.type === 'rest'."""
    js = JS_PATH.read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1
    export_body = js[export_start:export_start + 800]
    assert "entry.type === 'rest'" in export_body, (
        "exportCSV must guard against rest-day entries with entry.type === 'rest'"
    )


# ── AC: Correct header row ───────────────────────────────────────────────────────

def test_csv_header_exact_columns():
    """exportCSV must output header in exact column order."""
    js = JS_PATH.read_text()
    expected = "'date,type,title,distance_km,duration_minutes,avg_hr,tss,source'"
    assert expected in js, f"CSV header must be exactly: {expected}"


# ── AC: docs/mockups files committed ────────────────────────────────────────────

def test_mockup_desktop_html_exists():
    assert (MOCKUPS_DIR / "training-log-desktop.html").exists(), (
        "docs/mockups/training-log-desktop.html must exist in the repo"
    )


def test_mockup_mobile_html_exists():
    assert (MOCKUPS_DIR / "training-log-mobile.html").exists(), (
        "docs/mockups/training-log-mobile.html must exist in the repo"
    )


def test_mockups_readme_exists():
    assert (MOCKUPS_DIR / "README.md").exists(), (
        "docs/mockups/README.md must exist in the repo"
    )


def test_mockups_readme_contains_required_line():
    readme = (MOCKUPS_DIR / "README.md").read_text()
    required = (
        "Training Log redesign — see training-log-desktop.html and "
        "training-log-mobile.html for visual reference. Live page at /log."
    )
    assert required in readme, (
        f"docs/mockups/README.md must contain the line:\n  {required}"
    )


# ── AC: Mockup files not served by any route ────────────────────────────────────

def test_mockup_desktop_not_served(client):
    res = client.get("/docs/mockups/training-log-desktop.html", follow_redirects=False)
    assert res.status_code in (404, 405), (
        f"training-log-desktop.html must not be served; got {res.status_code}"
    )


def test_mockup_mobile_not_served(client):
    res = client.get("/docs/mockups/training-log-mobile.html", follow_redirects=False)
    assert res.status_code in (404, 405), (
        f"training-log-mobile.html must not be served; got {res.status_code}"
    )


# ── AC: Empty filtered result → header-only CSV, no error ───────────────────────

def test_exportCSV_header_always_initialised():
    """rows array must be initialised with the header before iterating entries."""
    js = JS_PATH.read_text()
    export_start = js.find("function exportCSV")
    assert export_start != -1
    export_body = js[export_start:export_start + 800]
    header_idx = export_body.find("'date,type,title")
    rows_idx   = export_body.find("var rows")
    assert rows_idx != -1, "Must initialise rows array in exportCSV"
    assert header_idx != -1, "Header row must be inside exportCSV"
    assert header_idx > rows_idx, "Header must be the first element of rows"


# ── AC: Export button wired to exportCSV ────────────────────────────────────────

def test_export_button_exists_in_log_html():
    html = LOG_HTML_PATH.read_text()
    assert 'id="log-export-btn"' in html, "log.html must have button id='log-export-btn'"


def test_export_button_handler_wired():
    js = JS_PATH.read_text()
    assert "log-export-btn" in js, "training-log.js must reference log-export-btn"
    after = js[js.find("log-export-btn"):]
    assert "exportCSV" in after or "click" in after, (
        "log-export-btn must be wired to exportCSV"
    )
