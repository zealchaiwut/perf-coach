"""
Tests for issue #52: GET /trends/summary server-side aggregation endpoint
Server under test: http://127.0.0.1:9001
"""
import datetime
import json
import pathlib

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today().isoformat()

HOME_JS = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
TRENDS_JS = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "trends.js").read_text()
HOME_HTML = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
TRENDS_HTML = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "trends.html").read_text()

EXPECTED_KEYS = {"range", "readiness", "hrv", "rhr", "sleep", "energy", "mood", "tss", "deltas"}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


# ── AC-1: Preset range returns 200 with correct shape ────────────────────────

def test_ac1_range_7d_returns_200(client, alice_id):
    """GET /trends/summary?range=7d must return HTTP 200."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200, (
        f"Expected 200, got {res.status_code}. "
        "GET /trends/summary?range=7d must be handled by the backend."
    )


def test_ac1_range_30d_returns_200(client, alice_id):
    """GET /trends/summary?range=30d must return HTTP 200."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}."


def test_ac1_range_90d_returns_200(client, alice_id):
    """GET /trends/summary?range=90d must return HTTP 200."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=90d")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}."


def test_ac1_response_has_required_top_level_keys(client, alice_id):
    """Response must contain all required top-level keys."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200
    data = res.json()
    missing = EXPECTED_KEYS - set(data.keys())
    assert not missing, (
        f"Response is missing top-level keys: {missing}. "
        f"Got: {set(data.keys())}"
    )


def test_ac1_range_object_shape(client, alice_id):
    """response.range must contain from, to, and days."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    data = res.json()
    rng = data["range"]
    assert "from" in rng and "to" in rng and "days" in rng, (
        f"range object must have 'from', 'to', and 'days' keys; got {rng}"
    )
    assert rng["days"] == 7, (
        f"range.days must be 7 for ?range=7d; got {rng['days']}"
    )


def test_ac1_readiness_object_shape(client, alice_id):
    """response.readiness must contain series, avg, min, max."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    data = res.json()
    r = data["readiness"]
    assert "series" in r and "avg" in r and "min" in r and "max" in r, (
        f"readiness must have series, avg, min, max; got {r.keys()}"
    )
    assert isinstance(r["series"], list), "readiness.series must be a list"
    assert len(r["series"]) == 7, (
        f"readiness.series must have 7 entries for range=7d; got {len(r['series'])}"
    )


def test_ac1_hrv_rhr_shape(client, alice_id):
    """response.hrv and response.rhr must contain series, avg, min, max."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    data = res.json()
    for key in ("hrv", "rhr"):
        obj = data[key]
        assert "series" in obj and "avg" in obj and "min" in obj and "max" in obj, (
            f"{key} must have series, avg, min, max; got {obj.keys()}"
        )


def test_ac1_sleep_shape(client, alice_id):
    """response.sleep must contain series with hours and quality, plus avg_hours."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    data = res.json()
    sleep = data["sleep"]
    assert "series" in sleep and "avg_hours" in sleep, (
        f"sleep must have series and avg_hours; got {sleep.keys()}"
    )
    if sleep["series"]:
        entry = sleep["series"][0]
        assert "date" in entry and "hours" in entry and "quality" in entry, (
            f"sleep.series entries must have date, hours, quality; got {entry.keys()}"
        )


def test_ac1_tss_shape(client, alice_id):
    """response.tss must contain series, avg, total."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    data = res.json()
    tss = data["tss"]
    assert "series" in tss and "avg" in tss and "total" in tss, (
        f"tss must have series, avg, total; got {tss.keys()}"
    )


def test_ac1_deltas_object_shape(client, alice_id):
    """response.deltas must contain readiness, hrv, rhr, sleep, energy, mood, tss."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    data = res.json()
    deltas = data["deltas"]
    expected_delta_keys = {"readiness", "hrv", "rhr", "sleep", "energy", "mood", "tss"}
    missing = expected_delta_keys - set(deltas.keys())
    assert not missing, (
        f"deltas object is missing keys: {missing}; got {deltas.keys()}"
    )


def test_ac1_invalid_range_returns_400(client, alice_id):
    """An unrecognised range value must return 400."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=14d")
    assert res.status_code == 400, (
        f"Expected 400 for unsupported range '14d', got {res.status_code}."
    )


# ── AC-2: Explicit date range ─────────────────────────────────────────────────

def test_ac2_explicit_date_range_returns_200(client, alice_id):
    """GET /trends/summary?from=...&to=... must return HTTP 200."""
    res = client.get(f"/trends/summary?user_id={alice_id}&from=2026-01-01&to=2026-01-07")
    assert res.status_code == 200, (
        f"Expected 200 for explicit date range, got {res.status_code}."
    )


def test_ac2_explicit_date_range_days_count(client, alice_id):
    """range.days must equal 7 for a 7-day explicit date range."""
    res = client.get(f"/trends/summary?user_id={alice_id}&from=2026-01-01&to=2026-01-07")
    data = res.json()
    assert data["range"]["days"] == 7, (
        f"range.days must be 7 for from=2026-01-01&to=2026-01-07; got {data['range']['days']}"
    )


def test_ac2_explicit_range_from_to_match(client, alice_id):
    """range.from and range.to must match the requested dates."""
    res = client.get(f"/trends/summary?user_id={alice_id}&from=2026-01-01&to=2026-01-07")
    data = res.json()
    assert data["range"]["from"] == "2026-01-01", (
        f"range.from must be '2026-01-01'; got {data['range']['from']}"
    )
    assert data["range"]["to"] == "2026-01-07", (
        f"range.to must be '2026-01-07'; got {data['range']['to']}"
    )


def test_ac2_series_length_matches_range(client, alice_id):
    """All series arrays must have exactly range.days entries."""
    res = client.get(f"/trends/summary?user_id={alice_id}&from=2026-01-01&to=2026-01-07")
    data = res.json()
    days = data["range"]["days"]
    for key in ("readiness", "hrv", "rhr", "sleep", "energy", "mood", "tss"):
        series = data[key]["series"]
        assert len(series) == days, (
            f"{key}.series must have {days} entries for the requested range; got {len(series)}"
        )


# ── AC-3: Response size ≤ 50 KB for 90-day range ─────────────────────────────

def test_ac3_90d_response_under_50kb(client, alice_id):
    """90-day summary response must not exceed 50 KB."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=90d")
    assert res.status_code == 200
    body_bytes = len(res.content)
    assert body_bytes <= 50 * 1024, (
        f"90-day summary response must be ≤ 50 KB; got {body_bytes} bytes "
        f"({body_bytes / 1024:.1f} KB)."
    )


# ── AC-4: range.days for 90d ──────────────────────────────────────────────────

def test_ac4_90d_range_days(client, alice_id):
    """range.days must equal 90 for ?range=90d."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=90d")
    data = res.json()
    assert data["range"]["days"] == 90, (
        f"range.days must be 90 for ?range=90d; got {data['range']['days']}"
    )


def test_ac4_series_has_90_entries(client, alice_id):
    """All series arrays must have exactly 90 entries for ?range=90d."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=90d")
    data = res.json()
    for key in ("readiness", "hrv", "rhr", "sleep", "energy", "mood", "tss"):
        series = data[key]["series"]
        assert len(series) == 90, (
            f"{key}.series must have 90 entries for range=90d; got {len(series)}"
        )


# ── AC-5: Null entries for missing days; aggregates skip nulls ────────────────

def test_ac5_missing_days_are_null(client, alice_id):
    """Days with no recorded data must appear as null in each series."""
    # Use a far-future date range guaranteed to have no data
    res = client.get(f"/trends/summary?user_id={alice_id}&from=2099-01-01&to=2099-01-07")
    assert res.status_code == 200
    data = res.json()
    # All readiness scores must be null (no data in far future)
    null_scores = [s["score"] for s in data["readiness"]["series"] if s["score"] is None]
    assert len(null_scores) == 7, (
        "All 7 days in the far-future range must have null readiness scores "
        f"since no data exists; got {null_scores} null entries."
    )
    # Aggregates must be null too (no non-null values to average)
    assert data["readiness"]["avg"] is None, (
        "readiness.avg must be null when all series entries are null."
    )


def test_ac5_series_entries_have_date_field(client, alice_id):
    """Each series entry must include a date field."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    data = res.json()
    for entry in data["readiness"]["series"]:
        assert "date" in entry, f"readiness series entry missing 'date': {entry}"
    for entry in data["hrv"]["series"]:
        assert "date" in entry, f"hrv series entry missing 'date': {entry}"


def test_ac5_aggregates_are_none_when_no_data(client, alice_id):
    """avg/min/max must be null when there are no non-null data points."""
    res = client.get(f"/trends/summary?user_id={alice_id}&from=2099-01-01&to=2099-01-07")
    data = res.json()
    for key in ("hrv", "rhr", "energy", "mood"):
        assert data[key]["avg"] is None, (
            f"{key}.avg must be null for a range with no data; "
            f"got {data[key]['avg']}"
        )
    assert data["sleep"]["avg_hours"] is None, (
        "sleep.avg_hours must be null for a range with no data."
    )
    assert data["tss"]["avg"] is None and data["tss"]["total"] is None, (
        "tss.avg and tss.total must be null for a range with no data."
    )


# ── AC-6: deltas compare current vs preceding equal-length range ──────────────

def test_ac6_deltas_values_are_strings_or_none(client, alice_id):
    """All delta values must be strings (signed) or null."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    data = res.json()
    for key, val in data["deltas"].items():
        assert val is None or isinstance(val, str), (
            f"deltas.{key} must be a string or null; got {type(val).__name__}: {val}"
        )


def test_ac6_non_null_deltas_are_signed(client, alice_id):
    """Non-null delta strings must start with + or -."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    data = res.json()
    for key, val in data["deltas"].items():
        if val is None:
            continue
        assert val[0] in ("+", "-"), (
            f"deltas.{key} must start with '+' or '-'; got '{val}'"
        )


def test_ac6_sleep_delta_has_h_suffix(client, alice_id):
    """deltas.sleep, when non-null, must end with 'h' (hours suffix)."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    data = res.json()
    sleep_delta = data["deltas"]["sleep"]
    if sleep_delta is not None:
        assert sleep_delta.endswith("h"), (
            f"deltas.sleep must end with 'h'; got '{sleep_delta}'"
        )


def test_ac6_tss_delta_has_pct_suffix(client, alice_id):
    """deltas.tss, when non-null, must end with '%'."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    data = res.json()
    tss_delta = data["deltas"]["tss"]
    if tss_delta is not None:
        assert tss_delta.endswith("%"), (
            f"deltas.tss must end with '%'; got '{tss_delta}'"
        )


# ── AC-7: trends.js calls /trends/summary exclusively ────────────────────────

def test_ac7_trends_js_calls_trends_summary():
    """trends.js must call /trends/summary for chart data."""
    assert "/trends/summary" in TRENDS_JS, (
        "trends.js must call GET /trends/summary to fetch chart data. "
        "No direct calls to individual raw-row endpoints should remain."
    )


def test_ac7_trends_js_no_direct_readiness_call():
    """trends.js must not call /api/readiness directly."""
    assert "/api/readiness" not in TRENDS_JS, (
        "trends.js must not call /api/readiness directly. "
        "Readiness data must come from /trends/summary."
    )


def test_ac7_trends_js_passes_range_param():
    """trends.js must pass the range or from/to params to /trends/summary."""
    assert "range=" in TRENDS_JS or "&range=" in TRENDS_JS or "?range=" in TRENDS_JS or "from=" in TRENDS_JS, (
        "trends.js must pass a range (or from/to) query parameter to /trends/summary."
    )


def test_ac7_trends_js_uses_summary_readiness_series():
    """trends.js must read readiness scores from summary.readiness.series."""
    assert "readiness" in TRENDS_JS and "series" in TRENDS_JS, (
        "trends.js must read data from summary.readiness.series."
    )


def test_ac7_trends_html_loads_user_js():
    """trends.html must load js/user.js so userId is available for the summary call."""
    assert "user.js" in TRENDS_HTML, (
        "trends.html must include <script src='js/user.js'> so the user selector "
        "is loaded and userId can be passed to /trends/summary."
    )


# ── AC-8: Weekly digest (home page) calls /trends/summary ────────────────────

def test_ac8_home_js_calls_trends_summary():
    """home.js must call /trends/summary for the 7-day weekly digest chart."""
    assert "/trends/summary" in HOME_JS, (
        "home.js must call GET /trends/summary for the weekly digest chart. "
        "It must not call /api/daily-metrics/trend."
    )


def test_ac8_home_js_no_direct_daily_metrics_trend_call():
    """home.js must not call /api/daily-metrics/trend directly."""
    assert "/api/daily-metrics/trend" not in HOME_JS, (
        "home.js must not call /api/daily-metrics/trend for the weekly digest. "
        "This data must now come from /trends/summary?range=7d."
    )


def test_ac8_home_js_uses_7d_range():
    """home.js must request the 7-day range when fetching the weekly digest."""
    assert "range=7d" in HOME_JS or "7d" in HOME_JS, (
        "home.js must use range=7d (or equivalent) when calling /trends/summary "
        "for the weekly digest chart."
    )


def test_ac8_home_html_has_trend_section():
    """home.html must include a weekly digest / 7-day trend section."""
    has_section = (
        "section-trend" in HOME_HTML or
        "trend-chart" in HOME_HTML or
        "7-day" in HOME_HTML or
        "digest" in HOME_HTML.lower()
    )
    assert has_section, (
        "home.html must include a weekly digest section that shows the 7-day "
        "sleep/energy/mood trend chart."
    )


def test_ac8_home_js_reads_sleep_series():
    """home.js weekly digest must read sleep hours from summary.sleep.series."""
    assert "sleep" in HOME_JS and "series" in HOME_JS, (
        "home.js must read sleep data from summary.sleep.series for the weekly digest chart."
    )


# ── Endpoint shape regression guard ──────────────────────────────────────────

def test_regression_response_is_valid_json(client, alice_id):
    """GET /trends/summary must always return valid JSON."""
    for preset in ("7d", "30d", "90d"):
        res = client.get(f"/trends/summary?user_id={alice_id}&range={preset}")
        assert res.status_code == 200
        try:
            data = res.json()
        except Exception as exc:
            pytest.fail(f"Response for range={preset} is not valid JSON: {exc}")
        assert isinstance(data, dict), f"Response for range={preset} must be a JSON object."


def test_regression_invalid_user_returns_400(client):
    """An invalid user_id must return 400."""
    res = client.get("/trends/summary?user_id=not-a-uuid&range=7d")
    assert res.status_code == 400, (
        f"Expected 400 for invalid user_id, got {res.status_code}."
    )
