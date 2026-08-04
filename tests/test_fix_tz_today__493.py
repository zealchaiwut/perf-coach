"""TDD tests for issue #493: Fix app-wide timezone inconsistency for 'today'.

Each test is anchored to one Acceptance Criterion.
Static inspection tests (no live server needed) verify that the correct
Bangkok-timezone pattern is used in the source files.
Live API tests verify runtime behavior.
"""

import datetime
import re
import pathlib

import httpx
import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
WEIGHT_JS  = REPO_ROOT / "frontend" / "js" / "weight.js"
MAIN_PY    = REPO_ROOT / "backend" / "main.py"

BASE = "http://127.0.0.1:9001"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _js():
    return WEIGHT_JS.read_text(encoding="utf-8")


def _py():
    return MAIN_PY.read_text(encoding="utf-8")


def _today_bkk() -> datetime.date:
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("Asia/Bangkok")).date()


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def auth_client():
    """Authenticated httpx client (session cookie from /api/auth/login)."""
    with httpx.Client(base_url=BASE, timeout=10) as c:
        res = c.post("/api/auth/login", json={"username": "alice", "password": "alice"})
        if res.status_code != 200:
            pytest.skip("Cannot authenticate as alice — live server not running or password wrong")
        yield c


# ── AC1 & AC2: frontend/js/weight.js uses Bangkok timezone for todayISO() ────

def test_ac1_weight_js_todayiso_uses_asia_bangkok():
    """AC1+AC2: todayISO() in weight.js must use Asia/Bangkok timezone string."""
    js = _js()
    # Locate the todayISO function body
    m = re.search(r"function todayISO\(\)\s*\{(.*?)\}", js, re.DOTALL)
    assert m, "todayISO() function not found in weight.js"
    body = m.group(1)
    assert "Asia/Bangkok" in body, (
        "todayISO() must derive today from Asia/Bangkok timezone; "
        "'Asia/Bangkok' not found in function body"
    )


def test_ac2_weight_js_todayiso_uses_tolocaledatestring_en_ca():
    """AC2: todayISO() uses toLocaleDateString('en-CA', ...) to get YYYY-MM-DD in Bangkok."""
    js = _js()
    m = re.search(r"function todayISO\(\)\s*\{(.*?)\}", js, re.DOTALL)
    assert m, "todayISO() function not found in weight.js"
    body = m.group(1)
    assert "en-CA" in body, (
        "todayISO() must use toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' }) "
        "to produce YYYY-MM-DD in Bangkok time"
    )


def test_ac2_todayiso_does_not_use_raw_new_date_getfullyear():
    """AC2: todayISO() must NOT derive date from raw new Date() getFullYear/getMonth/getDate."""
    js = _js()
    m = re.search(r"function todayISO\(\)\s*\{(.*?)\}", js, re.DOTALL)
    assert m, "todayISO() function not found in weight.js"
    body = m.group(1)
    # Old pattern built date from local-tz new Date() + getFullYear/getMonth/getDate
    assert "getFullYear" not in body, (
        "todayISO() must not use getFullYear() — that reads local timezone, not Bangkok"
    )
    assert "getMonth" not in body, (
        "todayISO() must not use getMonth() — that reads local timezone, not Bangkok"
    )
    assert "getDate" not in body, (
        "todayISO() must not use getDate() — that reads local timezone, not Bangkok"
    )


# ── AC3: backend weight endpoint uses BKK midnight for date validation ─────────

def test_ac3_create_weight_entry_uses_bkk_timezone():
    """AC3: create_weight_entry() must use the Bangkok-aware _today_bkk() helper
    for future-date validation, not server-local _date.today().
    The BKK logic is encapsulated in _today_bkk() which uses Asia/Bangkok.
    """
    py = _py()
    # Verify _today_bkk helper exists and uses Asia/Bangkok
    assert "_today_bkk" in py, "_today_bkk helper not defined in main.py"
    assert "Asia/Bangkok" in py, "Asia/Bangkok timezone not referenced in main.py"
    # Find the create_weight_entry function body
    m = re.search(
        r"def create_weight_entry\(.*?\n(.*?)(?=\n@app\.|\ndef |\Z)",
        py,
        re.DOTALL,
    )
    assert m, "create_weight_entry function not found in main.py"
    body = m.group(1)
    assert "_today_bkk()" in body, (
        "create_weight_entry must call _today_bkk() for future-date validation; "
        "not found in function body"
    )


def test_ac3_create_weight_entry_does_not_use_date_today_for_validation():
    """AC3: create_weight_entry() future-date guard must NOT use bare _date.today()."""
    py = _py()
    m = re.search(
        r"def create_weight_entry\(.*?\n(.*?)(?=\n@app\.|\ndef |\Z)",
        py,
        re.DOTALL,
    )
    assert m, "create_weight_entry function not found in main.py"
    body = m.group(1)
    # The guard line used to be: if entry_date > _date.today() + _timedelta(days=1)
    # It must now use a BKK-anchored today function/variable instead.
    assert "_date.today()" not in body, (
        "create_weight_entry must not use _date.today() for future-date validation; "
        "it must use a Bangkok-timezone today instead"
    )


# ── AC4: Home block today_bkk and weight chart endpoint agree ─────────────────

def test_ac4_get_weight_chart_uses_bkk_timezone_for_today():
    """AC4: get_weight_chart() uses Bangkok timezone for 'today', not server-local date.
    Ensures logged_today and today_marker agree with home block today_bkk.
    """
    py = _py()
    m = re.search(
        r"def get_weight_chart\(.*?\n(.*?)(?=\n@app\.|\ndef |\Z)",
        py,
        re.DOTALL,
    )
    assert m, "get_weight_chart function not found in main.py"
    body = m.group(1)
    assert "_today_bkk()" in body, (
        "get_weight_chart must call _today_bkk() for the 'today' variable "
        "so that logged_today and home block today_bkk agree"
    )


def test_ac4_get_weight_chart_does_not_use_bare_date_today():
    """AC4: get_weight_chart() must not use bare _date.today() for the 'today' variable."""
    py = _py()
    m = re.search(
        r"def get_weight_chart\(.*?\n(.*?)(?=\n@app\.|\ndef |\Z)",
        py,
        re.DOTALL,
    )
    assert m, "get_weight_chart function not found in main.py"
    body = m.group(1)
    assert "_date.today()" not in body, (
        "get_weight_chart must not use _date.today() for the 'today' variable; "
        "use Bangkok-timezone today instead"
    )


# ── AC5 (live): BKK-today entry accepted without 422 ─────────────────────────

def test_ac5_bkk_today_entry_accepted(auth_client):
    """AC5: A weight entry dated today-in-BKK is accepted (no 422).

    This test uses the live server. It posts with the current Bangkok date;
    even if the server clock is on an earlier UTC day, the entry should be accepted.
    """
    today_bkk = _today_bkk().isoformat()
    res = auth_client.post(
        "/api/weight-entries",
        json={"entry_date": today_bkk, "weight_kg": 70.0},
    )
    assert res.status_code in (201, 409), (
        f"Expected 201 or 409 for today-in-BKK date {today_bkk}, got {res.status_code}: {res.text}"
    )


# ── AC6 (live): logged_today reflects BKK date of inserted row ───────────────

def test_ac6_logged_today_reflects_bkk_date(auth_client):
    """AC6: After inserting a weight entry for today-in-BKK, logged_today is true
    in the weight chart response.
    """
    today_bkk = _today_bkk()
    today_str = today_bkk.isoformat()

    # Post today's entry (may already exist — 409 is fine)
    auth_client.post(
        "/api/weight-entries",
        json={"entry_date": today_str, "weight_kg": 70.0},
    )

    # Fetch chart data and verify logged_today
    res = auth_client.get("/api/weight-chart", params={"range": "7D"})
    assert res.status_code == 200, f"weight-chart returned {res.status_code}: {res.text}"
    data = res.json()
    assert "logged_today" in data, "Response must include 'logged_today' field"
    assert data["logged_today"] is True, (
        f"logged_today should be True after inserting entry for BKK today ({today_str})"
    )


# ── AC7: Future dates (beyond 1 BKK day) still rejected ─────────────────────

def test_ac7_far_future_date_rejected(auth_client):
    """AC7: Dates more than 1 day ahead of BKK today still return 422."""
    far_future = (_today_bkk() + datetime.timedelta(days=5)).isoformat()
    res = auth_client.post(
        "/api/weight-entries",
        json={"entry_date": far_future, "weight_kg": 70.0},
    )
    assert res.status_code == 422, (
        f"Expected 422 for far-future date {far_future}, got {res.status_code}: {res.text}"
    )


def test_ac7_yesterday_entry_still_accepted(auth_client):
    """AC7: An entry dated yesterday-in-BKK is accepted (no regression for past dates)."""
    yesterday = (_today_bkk() - datetime.timedelta(days=1)).isoformat()
    res = auth_client.post(
        "/api/weight-entries",
        json={"entry_date": yesterday, "weight_kg": 70.0},
    )
    assert res.status_code in (201, 409), (
        f"Expected 201 or 409 for yesterday-in-BKK {yesterday}, got {res.status_code}: {res.text}"
    )
