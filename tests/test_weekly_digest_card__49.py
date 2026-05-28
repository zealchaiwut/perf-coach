"""
Tests for issue #49 / #50: Home dashboard — weekly digest card (template-based, 7-day summary)
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


@pytest.fixture(scope="module")
def new_user_id(client):
    res = client.post("/api/users", json={"name": "DigestTestUser49"})
    assert res.status_code in (200, 201)
    uid = res.json()["id"]
    yield uid
    client.delete(f"/api/users/{uid}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _put_metric(client, user_id, date_str, hrv=50, resting_hr=55, sleep_hours=7.5,
                sleep_quality=4, energy=4, mood=4):
    res = client.put(
        f"/api/daily-metrics/{user_id}/{date_str}",
        json={
            "hrv": hrv,
            "resting_hr": resting_hr,
            "sleep_hours": sleep_hours,
            "sleep_quality": sleep_quality,
            "energy": energy,
            "mood": mood,
        },
    )
    assert res.status_code in (200, 201), f"PUT metric failed: {res.status_code} {res.text}"
    return res.json()


def _delete_metric(client, user_id, date_str):
    client.delete(f"/api/daily-metrics/{user_id}/{date_str}")


def _seed_7_days(client, user_id, base_hrv=50, base_rhr=55):
    """Insert 7 days of daily metrics ending today."""
    dates = []
    for i in range(6, -1, -1):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        _put_metric(client, user_id, d, hrv=base_hrv, resting_hr=base_rhr)
        dates.append(d)
    return dates


def _cleanup_dates(client, user_id, dates):
    for d in dates:
        _delete_metric(client, user_id, d)


# ── AC: HTML structure ────────────────────────────────────────────────────────

def test_ac_digest_section_exists_in_html():
    """home.html must have an element with id='section-digest'."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="section-digest"' in html, "Missing id='section-digest' in home.html"


def test_ac_digest_links_to_trends_7d():
    """The digest card must href to trends.html?range=7d (or /trends?range=7d)."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert re.search(r'href=["\']trends\.html\?range=7d["\']', html) or \
           re.search(r'href=["\'][^"\']*trends[^"\']*range=7d["\']', html), \
        "digest card must link to trends page with range=7d"


def test_ac_digest_section_body_exists_in_html():
    """home.html must have id='section-digest-body' for dynamic content."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="section-digest-body"' in html, "Missing id='section-digest-body' in home.html"


def test_ac_digest_positioned_in_main():
    """The digest section must be inside <main> on the home page."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    main_start = html.find("<main")
    main_end = html.find("</main>")
    assert main_start != -1 and main_end != -1, "<main> block not found in home.html"
    main_block = html[main_start:main_end]
    assert 'id="section-digest"' in main_block, "digest section must be inside <main>"


# ── AC: /trends/summary endpoint ─────────────────────────────────────────────

def test_ac_summary_endpoint_7d_returns_200(client, alice_id):
    """GET /trends/summary?range=7d must return 200 with expected top-level keys."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200, f"Unexpected status: {res.status_code} {res.text}"
    data = res.json()
    for key in ("range", "readiness", "sleep", "hrv", "rhr", "tss", "deltas"):
        assert key in data, f"Missing key '{key}' in /trends/summary response"


def test_ac_summary_endpoint_deltas_are_strings(client, alice_id):
    """Delta values must be string-formatted (e.g. '+4', '-0.5h', '+70%')."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200
    deltas = res.json().get("deltas", {})
    # Each non-null delta must be a string
    for key, val in deltas.items():
        if val is not None:
            assert isinstance(val, str), f"Delta '{key}' must be a string, got {type(val)}: {val}"


def test_ac_summary_endpoint_readiness_series_length(client, alice_id):
    """readiness.series must have exactly 7 entries for range=7d."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200
    series = res.json()["readiness"]["series"]
    assert len(series) == 7, f"Expected 7 readiness entries, got {len(series)}"


def test_ac_summary_endpoint_no_data_yields_null_avgs(client, new_user_id):
    """A user with no entries must get null avg/min/max for all metrics."""
    res = client.get(f"/trends/summary?user_id={new_user_id}&range=7d")
    assert res.status_code == 200
    data = res.json()
    assert data["readiness"]["avg"] is None, "readiness.avg must be null for empty user"
    assert data["sleep"]["avg_hours"] is None, "sleep.avg_hours must be null for empty user"
    assert data["tss"]["total"] is None, "tss.total must be null for empty user"


def test_ac_summary_endpoint_with_data_yields_non_null_avg(client, new_user_id):
    """A user with 7 days of data must get non-null averages."""
    dates = _seed_7_days(client, new_user_id)
    try:
        res = client.get(f"/trends/summary?user_id={new_user_id}&range=7d")
        assert res.status_code == 200
        data = res.json()
        assert data["readiness"]["avg"] is not None, "readiness.avg must be non-null with 7 days of data"
        assert data["sleep"]["avg_hours"] is not None, "sleep.avg_hours must be non-null with 7 days of data"
    finally:
        _cleanup_dates(client, new_user_id, dates)


# ── AC: days_with_data logic (tested via endpoint series) ────────────────────

def test_ac_fewer_than_3_days_yields_mostly_null_series(client, new_user_id):
    """With 2 days of data the series has at most 2 non-null readiness scores."""
    dates = []
    for i in range(1, -1, -1):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        _put_metric(client, new_user_id, d)
        dates.append(d)
    try:
        res = client.get(f"/trends/summary?user_id={new_user_id}&range=7d")
        assert res.status_code == 200
        series = res.json()["readiness"]["series"]
        non_null = [s for s in series if s["score"] is not None]
        assert len(non_null) <= 2, f"Expected ≤2 non-null scores with 2 days of data, got {len(non_null)}"
    finally:
        _cleanup_dates(client, new_user_id, dates)


def test_ac_3_days_data_yields_3_non_null_readiness(client, new_user_id):
    """With exactly 3 days of data the series has exactly 3 non-null readiness scores."""
    dates = []
    for i in range(2, -1, -1):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        _put_metric(client, new_user_id, d)
        dates.append(d)
    try:
        res = client.get(f"/trends/summary?user_id={new_user_id}&range=7d")
        assert res.status_code == 200
        series = res.json()["readiness"]["series"]
        non_null = [s for s in series if s["score"] is not None]
        assert len(non_null) == 3, f"Expected 3 non-null readiness scores, got {len(non_null)}"
    finally:
        _cleanup_dates(client, new_user_id, dates)


# ── AC: delta suppression thresholds ─────────────────────────────────────────

def test_ac_readiness_delta_format(client, new_user_id):
    """With data in both current and prior week, readiness delta is a signed integer string."""
    current_dates = []
    prev_dates = []
    for i in range(6, -1, -1):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        _put_metric(client, new_user_id, d, hrv=50, resting_hr=55)
        current_dates.append(d)
    for i in range(13, 6, -1):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        _put_metric(client, new_user_id, d, hrv=40, resting_hr=60)
        prev_dates.append(d)
    try:
        res = client.get(f"/trends/summary?user_id={new_user_id}&range=7d")
        assert res.status_code == 200
        delta = res.json()["deltas"]["readiness"]
        if delta is not None:
            assert re.match(r'^[+-]\d+$', delta), \
                f"readiness delta must be signed integer string like '+4' or '-3', got: {delta}"
    finally:
        _cleanup_dates(client, new_user_id, current_dates + prev_dates)


def test_ac_sleep_delta_format(client, new_user_id):
    """Sleep delta string must end with 'h' (e.g. '-0.5h', '+1.0h')."""
    current_dates = []
    prev_dates = []
    for i in range(6, -1, -1):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        _put_metric(client, new_user_id, d, sleep_hours=8.0)
        current_dates.append(d)
    for i in range(13, 6, -1):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        _put_metric(client, new_user_id, d, sleep_hours=7.0)
        prev_dates.append(d)
    try:
        res = client.get(f"/trends/summary?user_id={new_user_id}&range=7d")
        assert res.status_code == 200
        delta = res.json()["deltas"]["sleep"]
        if delta is not None:
            assert delta.endswith("h"), f"sleep delta must end with 'h', got: {delta}"
    finally:
        _cleanup_dates(client, new_user_id, current_dates + prev_dates)


def test_ac_tss_delta_format(client, alice_id):
    """TSS delta string must end with '%' when both periods have workouts."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200
    delta = res.json()["deltas"]["tss"]
    if delta is not None:
        assert delta.endswith("%"), f"TSS delta must be a percentage string ending with '%', got: {delta}"


# ── AC: JS helpers (tested via mock data shape) ───────────────────────────────

def test_ac_mock_data_shape_matches_api():
    """MOCK_TRENDS_SUMMARY in mock-data.js must have keys matching the real API shape."""
    mock_js = (pathlib.Path(__file__).parent.parent / "js" / "mock-data.js").read_text()
    for key in ("range", "readiness", "sleep", "hrv", "rhr", "tss", "deltas"):
        assert key in mock_js, f"MOCK_TRENDS_SUMMARY must include key '{key}'"


def test_ac_mock_data_deltas_are_strings():
    """MOCK_TRENDS_SUMMARY deltas must be quoted strings (not raw numbers)."""
    mock_js = (pathlib.Path(__file__).parent.parent / "js" / "mock-data.js").read_text()
    # Keys may be unquoted or quoted in JS object literals
    for key in ("readiness", "hrv", "rhr", "sleep", "tss"):
        # Match: `key: '+4'` or `'key': '+4'` or `"key": "+4"` etc.
        pattern = rf"""['"]?{key}['"]?\s*:\s*['"][^'"]+['"]"""
        assert re.search(pattern, mock_js), \
            f"MOCK delta for '{key}' must be a quoted string"


# ── AC: max 5 lines in JS (structural check) ─────────────────────────────────

def test_ac_home_js_slices_to_5_lines():
    """home.js must limit digest lines to at most 5 (slice(0, 5) or equivalent)."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "slice(0, 5)" in js, "home.js must call .slice(0, 5) to cap digest lines at 5"


def test_ac_home_js_has_daily_cache_key():
    """home.js must define a localStorage cache key for the digest (constant or function)."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "DIGEST_CACHE_KEY" in js or "digestCacheKey" in js, \
        "home.js must define DIGEST_CACHE_KEY or digestCacheKey for daily caching"


def test_ac_home_js_cache_uses_today_iso():
    """The digest cache must gate on todayISO() to expire daily."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "todayISO()" in js, "Digest cache must call todayISO() to validate daily expiry"


def test_ac_home_js_not_enough_data_message():
    """home.js must render 'Not enough data yet' when days_with_data < 3."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "Not enough data yet" in js, "home.js must include 'Not enough data yet' message"


def test_ac_home_js_correct_endpoint_url():
    """home.js must fetch from /trends/summary, not /api/trends/summary."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "/trends/summary" in js, "home.js must fetch from /trends/summary"
    assert "'/api/trends/summary" not in js and '"/api/trends/summary' not in js, \
        "home.js must NOT use /api/trends/summary (no /api prefix)"
