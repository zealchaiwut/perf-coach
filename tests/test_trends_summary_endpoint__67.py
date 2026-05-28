"""
Tests for issue #67: GET /trends/summary aggregation endpoint (mock tier).

Implementation: deterministic client-side mock in js/mock-data.js
(mockGetTrendsSummary). The real server-side endpoint is gated on an auth
layer that doesn't exist yet; these tests validate the JS mock contract and
static-file serving.

Server under test (for static-file ACs): http://127.0.0.1:9001
"""

import json
import pathlib
import subprocess
import time

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
ROOT = pathlib.Path(__file__).parent.parent
MOCK_DATA_JS = (ROOT / "js" / "mock-data.js").read_text()
TRENDS_JS = (ROOT / "js" / "trends.js").read_text()
TRENDS_HTML = (ROOT / "trends.html").read_text()

# ---------------------------------------------------------------------------
# Node.js helper – calls mockGetTrendsSummary from the real mock-data.js file
# ---------------------------------------------------------------------------

_MOCK_RUNNER_TMPL = """\
{mock_data_js}

try {{
  const result = mockGetTrendsSummary({params_json});
  console.log(JSON.stringify({{ ok: true, data: result }}));
}} catch (e) {{
  console.log(JSON.stringify({{ ok: false, status: e.status || null, message: e.message }}));
}}
"""


def _call_mock(params: dict, timeout: float = 1.0) -> tuple[bool, dict | None, dict | None]:
    """Run mockGetTrendsSummary via Node.js and return (ok, data, error)."""
    script = _MOCK_RUNNER_TMPL.format(
        mock_data_js=MOCK_DATA_JS,
        params_json=json.dumps(params),
    )
    start = time.monotonic()
    proc = subprocess.run(
        ["node", "--input-type=commonjs"],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, f"Node.js runner crashed:\n{proc.stderr}"
    result = json.loads(proc.stdout.strip())
    if result["ok"]:
        return True, result["data"], None, elapsed
    return False, None, {"status": result["status"], "message": result["message"]}, elapsed


@pytest.fixture(scope="module")
def summary_7d():
    ok, data, _, _ = _call_mock({"range": "7d"})
    assert ok, "mockGetTrendsSummary({range:'7d'}) should not throw"
    return data


@pytest.fixture(scope="module")
def summary_30d():
    ok, data, _, _ = _call_mock({"range": "30d"})
    assert ok
    return data


@pytest.fixture(scope="module")
def summary_90d():
    ok, data, _, _ = _call_mock({"range": "90d"})
    assert ok
    return data


@pytest.fixture(scope="module")
def summary_custom():
    ok, data, _, _ = _call_mock({"from": "2026-01-01", "to": "2026-01-14"})
    assert ok
    return data


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-1: mockGetTrendsSummary defined; trends.js calls mock; no real HTTP ──

def test_ac1_mock_function_defined_in_mock_data_js():
    assert "function mockGetTrendsSummary" in MOCK_DATA_JS, (
        "mock-data.js must define mockGetTrendsSummary"
    )


def test_ac1_trends_js_calls_mock_get_trends_summary():
    assert "mockGetTrendsSummary" in TRENDS_JS, (
        "trends.js must call mockGetTrendsSummary"
    )


def test_ac1_trends_js_no_direct_fetch_to_trends_summary():
    has_direct_fetch = (
        'fetch("/trends/summary"' in TRENDS_JS
        or "fetch('/trends/summary'" in TRENDS_JS
    )
    assert not has_direct_fetch, (
        "trends.js must not call fetch('/trends/summary') directly; "
        "it must delegate to mockGetTrendsSummary"
    )


def test_ac1_mock_function_callable_without_error():
    ok, data, _, _ = _call_mock({"range": "7d"})
    assert ok, "mockGetTrendsSummary must not throw for valid params"
    assert isinstance(data, dict), "return value must be an object"


# ── AC-2: meta object ────────────────────────────────────────────────────────

def test_ac2_meta_key_present(summary_7d):
    assert "meta" in summary_7d, "Response must contain a top-level 'meta' key"


def test_ac2_meta_has_required_fields(summary_7d):
    meta = summary_7d["meta"]
    for key in ("range", "from", "to", "days"):
        assert key in meta, f"meta must contain '{key}'; got {list(meta.keys())}"


def test_ac2_meta_days_equals_7_for_7d(summary_7d):
    assert summary_7d["meta"]["days"] == 7, (
        f"meta.days must be 7 for range=7d; got {summary_7d['meta']['days']}"
    )


def test_ac2_meta_days_equals_90_for_90d(summary_90d):
    assert summary_90d["meta"]["days"] == 90, (
        f"meta.days must be 90 for range=90d; got {summary_90d['meta']['days']}"
    )


def test_ac2_meta_range_reflects_preset(summary_7d):
    assert summary_7d["meta"]["range"] == "7d", (
        f"meta.range must be '7d' when range=7d param is given; got {summary_7d['meta']['range']}"
    )


def test_ac2_meta_from_to_are_dates(summary_7d):
    from datetime import date as _d
    meta = summary_7d["meta"]
    try:
        _d.fromisoformat(meta["from"])
        _d.fromisoformat(meta["to"])
    except Exception:
        pytest.fail(f"meta.from and meta.to must be valid YYYY-MM-DD dates; got {meta['from']}, {meta['to']}")


# ── AC-3: readiness block ────────────────────────────────────────────────────

def test_ac3_readiness_block_present(summary_7d):
    assert "readiness" in summary_7d, "Response must contain a 'readiness' block"


def test_ac3_readiness_has_required_fields(summary_7d):
    r = summary_7d["readiness"]
    for key in ("avg", "min", "max", "latest", "series", "delta"):
        assert key in r, f"readiness must contain '{key}'; got {list(r.keys())}"


def test_ac3_readiness_series_length_matches_days(summary_7d):
    days = summary_7d["meta"]["days"]
    series = summary_7d["readiness"]["series"]
    assert len(series) == days, (
        f"readiness.series must have {days} entries; got {len(series)}"
    )


def test_ac3_readiness_series_entries_have_value_field(summary_7d):
    for entry in summary_7d["readiness"]["series"]:
        assert "value" in entry, (
            f"readiness.series entries must use 'value' key; got {list(entry.keys())}"
        )
        assert "date" in entry, f"readiness.series entries must have 'date'; got {list(entry.keys())}"


def test_ac3_readiness_series_no_score_field(summary_7d):
    for entry in summary_7d["readiness"]["series"]:
        assert "score" not in entry, (
            "readiness.series entries must use 'value', not 'score' (old shape)"
        )


# ── AC-4: hrv block ──────────────────────────────────────────────────────────

def test_ac4_hrv_block_present(summary_7d):
    assert "hrv" in summary_7d, "Response must contain an 'hrv' block"


def test_ac4_hrv_has_required_fields(summary_7d):
    hrv = summary_7d["hrv"]
    for key in ("avg", "baseline_mean", "baseline_sd", "series", "delta"):
        assert key in hrv, f"hrv must contain '{key}'; got {list(hrv.keys())}"


def test_ac4_hrv_baseline_mean_is_numeric_or_null(summary_7d):
    val = summary_7d["hrv"]["baseline_mean"]
    assert val is None or isinstance(val, (int, float)), (
        f"hrv.baseline_mean must be numeric or null; got {type(val).__name__}: {val}"
    )


def test_ac4_hrv_baseline_sd_is_numeric_or_null(summary_7d):
    val = summary_7d["hrv"]["baseline_sd"]
    assert val is None or isinstance(val, (int, float)), (
        f"hrv.baseline_sd must be numeric or null; got {type(val).__name__}: {val}"
    )


def test_ac4_hrv_series_entries_use_value(summary_7d):
    for entry in summary_7d["hrv"]["series"]:
        assert "value" in entry, f"hrv.series entries must have 'value'; got {list(entry.keys())}"


# ── AC-5: rhr block ──────────────────────────────────────────────────────────

def test_ac5_rhr_block_present(summary_7d):
    assert "rhr" in summary_7d, "Response must contain an 'rhr' block"


def test_ac5_rhr_has_required_fields(summary_7d):
    rhr = summary_7d["rhr"]
    for key in ("avg", "min", "max", "latest", "series", "delta"):
        assert key in rhr, f"rhr must contain '{key}'; got {list(rhr.keys())}"


def test_ac5_rhr_series_entries_use_value(summary_7d):
    for entry in summary_7d["rhr"]["series"]:
        assert "value" in entry, f"rhr.series entries must have 'value'; got {list(entry.keys())}"


# ── AC-6/7/8: sleep / energy / mood blocks ───────────────────────────────────

@pytest.mark.parametrize("metric", ["sleep", "energy", "mood"])
def test_ac678_metric_block_present(summary_7d, metric):
    assert metric in summary_7d, f"Response must contain a '{metric}' block"


@pytest.mark.parametrize("metric", ["sleep", "energy", "mood"])
def test_ac678_metric_has_avg_and_series(summary_7d, metric):
    block = summary_7d[metric]
    assert "avg" in block and "series" in block, (
        f"{metric} must have 'avg' and 'series'; got {list(block.keys())}"
    )


@pytest.mark.parametrize("metric", ["sleep", "energy", "mood"])
def test_ac678_metric_series_entries_use_value(summary_7d, metric):
    for entry in summary_7d[metric]["series"]:
        assert "value" in entry, (
            f"{metric}.series entries must use 'value' key; got {list(entry.keys())}"
        )


@pytest.mark.parametrize("metric", ["sleep", "energy", "mood"])
def test_ac678_metric_has_delta(summary_7d, metric):
    block = summary_7d[metric]
    assert "delta" in block, f"{metric} must contain a 'delta' object; got {list(block.keys())}"


def test_ac6_sleep_series_no_hours_field(summary_7d):
    for entry in summary_7d["sleep"]["series"]:
        assert "hours" not in entry, (
            "sleep.series entries must use 'value' not 'hours' (new shape)"
        )


# ── AC-9: tss block ──────────────────────────────────────────────────────────

def test_ac9_tss_block_present(summary_7d):
    assert "tss" in summary_7d, "Response must contain a 'tss' block"


def test_ac9_tss_has_required_fields(summary_7d):
    tss = summary_7d["tss"]
    for key in ("total", "avg", "series", "delta"):
        assert key in tss, f"tss must contain '{key}'; got {list(tss.keys())}"


def test_ac9_tss_series_length_matches_days(summary_7d):
    days = summary_7d["meta"]["days"]
    assert len(summary_7d["tss"]["series"]) == days


def test_ac9_tss_series_entries_use_value(summary_7d):
    for entry in summary_7d["tss"]["series"]:
        assert "value" in entry and "date" in entry, (
            f"tss.series entries must have 'date' and 'value'; got {list(entry.keys())}"
        )


# ── AC-10: per-metric delta objects ─────────────────────────────────────────

DELTA_METRICS = ["readiness", "hrv", "rhr", "sleep", "energy", "mood", "tss"]


@pytest.mark.parametrize("metric", DELTA_METRICS)
def test_ac10_delta_has_value_pct_direction(summary_7d, metric):
    delta = summary_7d[metric]["delta"]
    for key in ("value", "pct", "direction"):
        assert key in delta, (
            f"{metric}.delta must contain '{key}'; got {list(delta.keys())}"
        )


@pytest.mark.parametrize("metric", DELTA_METRICS)
def test_ac10_delta_direction_is_valid_string(summary_7d, metric):
    direction = summary_7d[metric]["delta"]["direction"]
    assert direction in ("up", "down", "flat"), (
        f"{metric}.delta.direction must be 'up', 'down', or 'flat'; got '{direction}'"
    )


def test_ac10_no_top_level_deltas_key(summary_7d):
    assert "deltas" not in summary_7d, (
        "Response must NOT have a top-level 'deltas' key (old shape); "
        "deltas are now per-metric delta objects"
    )


# ── AC-11: null entries for missing days; aggregates skip nulls ──────────────

def test_ac11_null_values_appear_in_sparse_range():
    ok, data, _, _ = _call_mock({"from": "2099-01-01", "to": "2099-01-07"})
    assert ok, "Future date range must not throw"
    null_count = sum(1 for s in data["readiness"]["series"] if s["value"] is None)
    assert null_count == 7, (
        f"All 7 entries in a far-future range must be null; got {null_count} nulls"
    )


def test_ac11_avg_is_null_when_all_series_null():
    ok, data, _, _ = _call_mock({"from": "2099-01-01", "to": "2099-01-07"})
    assert ok
    assert data["readiness"]["avg"] is None, (
        "readiness.avg must be null when all series values are null"
    )


def test_ac11_nulls_excluded_from_avg_calculation(summary_30d):
    series_vals = [s["value"] for s in summary_30d["readiness"]["series"] if s["value"] is not None]
    if not series_vals:
        pytest.skip("No non-null readiness values in 30d range")
    expected_avg = round(sum(series_vals) / len(series_vals), 2)
    actual_avg = summary_30d["readiness"]["avg"]
    assert actual_avg is not None, "readiness.avg must not be null when there are non-null values"
    assert abs(actual_avg - expected_avg) <= 0.1, (
        f"readiness.avg {actual_avg} does not match expected {expected_avg} "
        "(nulls must be excluded from average calculation)"
    )


def test_ac11_tss_total_is_null_when_no_data():
    ok, data, _, _ = _call_mock({"from": "2099-01-01", "to": "2099-01-07"})
    assert ok
    assert data["tss"]["total"] is None, "tss.total must be null when no data"
    assert data["tss"]["avg"] is None, "tss.avg must be null when no data"


# ── AC-12: response size ≤ 50 KB for 90-day range ───────────────────────────

def test_ac12_90d_response_under_50kb(summary_90d):
    size = len(json.dumps(summary_90d).encode())
    assert size <= 51200, (
        f"90-day summary must be ≤ 50 KB; got {size} bytes ({size / 1024:.1f} KB)"
    )


def test_ac12_90d_response_not_empty(summary_90d):
    assert summary_90d["readiness"]["series"], "90d readiness series must not be empty"


# ── AC-13: response time < 300 ms ────────────────────────────────────────────

def test_ac13_90d_mock_completes_under_300ms():
    _, _, _, elapsed = _call_mock({"range": "90d"})
    assert elapsed < 0.300, (
        f"mockGetTrendsSummary for 90d must complete in < 300 ms; took {elapsed * 1000:.0f} ms"
    )


def test_ac13_7d_mock_completes_under_300ms():
    _, _, _, elapsed = _call_mock({"range": "7d"})
    assert elapsed < 0.300, (
        f"mockGetTrendsSummary for 7d must complete in < 300 ms; took {elapsed * 1000:.0f} ms"
    )


# ── AC-14: 400 for invalid params ────────────────────────────────────────────

def test_ac14_range_and_from_are_mutually_exclusive():
    ok, _, err, _ = _call_mock({"range": "7d", "from": "2026-01-01"})
    assert not ok, "range + from must throw a 400 error"
    assert err["status"] == 400


def test_ac14_range_and_to_are_mutually_exclusive():
    ok, _, err, _ = _call_mock({"range": "7d", "to": "2026-01-07"})
    assert not ok, "range + to must throw a 400 error"
    assert err["status"] == 400


def test_ac14_range_and_both_from_to_mutually_exclusive():
    ok, _, err, _ = _call_mock({"range": "7d", "from": "2026-01-01", "to": "2026-01-07"})
    assert not ok
    assert err["status"] == 400


def test_ac14_invalid_range_value_returns_400():
    ok, _, err, _ = _call_mock({"range": "14d"})
    assert not ok, "Unsupported range '14d' must throw 400"
    assert err["status"] == 400


def test_ac14_invalid_range_value_message_is_descriptive():
    ok, _, err, _ = _call_mock({"range": "invalid"})
    assert not ok
    assert err["message"], "Error message must be non-empty for invalid range"


def test_ac14_from_without_to_returns_400():
    ok, _, err, _ = _call_mock({"from": "2026-01-01"})
    assert not ok, "from without to must throw 400"
    assert err["status"] == 400


def test_ac14_to_without_from_returns_400():
    ok, _, err, _ = _call_mock({"to": "2026-01-07"})
    assert not ok, "to without from must throw 400"
    assert err["status"] == 400


def test_ac14_malformed_from_date_returns_400():
    ok, _, err, _ = _call_mock({"from": "not-a-date", "to": "2026-01-07"})
    assert not ok
    assert err["status"] == 400


def test_ac14_malformed_to_date_returns_400():
    ok, _, err, _ = _call_mock({"from": "2026-01-01", "to": "bad"})
    assert not ok
    assert err["status"] == 400


# ── AC-15: explicit from/to and default range ────────────────────────────────

def test_ac15_explicit_from_to_meta_from(summary_custom):
    assert summary_custom["meta"]["from"] == "2026-01-01", (
        f"meta.from must be '2026-01-01'; got {summary_custom['meta']['from']}"
    )


def test_ac15_explicit_from_to_meta_to(summary_custom):
    assert summary_custom["meta"]["to"] == "2026-01-14", (
        f"meta.to must be '2026-01-14'; got {summary_custom['meta']['to']}"
    )


def test_ac15_explicit_from_to_meta_days(summary_custom):
    assert summary_custom["meta"]["days"] == 14, (
        f"meta.days must be 14 for Jan 1–14; got {summary_custom['meta']['days']}"
    )


def test_ac15_default_range_is_30d():
    ok, data, _, _ = _call_mock({})
    assert ok, "No-param call must not throw (defaults to 30d)"
    assert data["meta"]["days"] == 30, (
        f"Default range must be 30d (30 days); got {data['meta']['days']}"
    )


def test_ac15_explicit_range_null_in_meta_for_custom(summary_custom):
    assert summary_custom["meta"]["range"] is None, (
        "meta.range must be null for explicit from/to (no preset used)"
    )


# ── AC-16: series dates ascending and match window ───────────────────────────

def test_ac16_readiness_series_dates_ascending(summary_30d):
    dates = [s["date"] for s in summary_30d["readiness"]["series"]]
    assert dates == sorted(dates), "readiness.series dates must be in ascending order"


def test_ac16_readiness_series_first_date_matches_meta_from(summary_30d):
    assert summary_30d["readiness"]["series"][0]["date"] == summary_30d["meta"]["from"], (
        "readiness.series first date must equal meta.from"
    )


def test_ac16_readiness_series_last_date_matches_meta_to(summary_30d):
    assert summary_30d["readiness"]["series"][-1]["date"] == summary_30d["meta"]["to"], (
        "readiness.series last date must equal meta.to"
    )


def test_ac16_all_series_have_same_length(summary_7d):
    days = summary_7d["meta"]["days"]
    for metric in ("readiness", "hrv", "rhr", "sleep", "energy", "mood", "tss"):
        length = len(summary_7d[metric]["series"])
        assert length == days, (
            f"{metric}.series must have {days} entries; got {length}"
        )


def test_ac16_series_covers_exactly_meta_days(summary_30d):
    from datetime import date as _d, timedelta
    meta = summary_30d["meta"]
    from_d = _d.fromisoformat(meta["from"])
    to_d = _d.fromisoformat(meta["to"])
    expected = [(from_d + timedelta(days=i)).isoformat() for i in range(meta["days"])]
    actual = [s["date"] for s in summary_30d["readiness"]["series"]]
    assert actual == expected, "readiness.series dates must cover the exact meta window"


# ── AC-17: static file serving ───────────────────────────────────────────────

def test_ac17_mock_data_js_served(client):
    res = client.get("/js/mock-data.js")
    assert res.status_code == 200, (
        f"GET /js/mock-data.js must return 200; got {res.status_code}"
    )


def test_ac17_trends_js_served(client):
    res = client.get("/js/trends.js")
    assert res.status_code == 200, (
        f"GET /js/trends.js must return 200; got {res.status_code}"
    )


def test_ac17_trends_html_served(client):
    res = client.get("/trends.html")
    assert res.status_code == 200, (
        f"GET /trends.html must return 200; got {res.status_code}"
    )


def test_ac17_mock_data_js_content_type(client):
    res = client.get("/js/mock-data.js")
    ct = res.headers.get("content-type", "")
    assert "javascript" in ct or "text/" in ct, (
        f"mock-data.js Content-Type must be JS or text; got '{ct}'"
    )


def test_ac17_trends_html_loads_mock_data_js():
    assert "mock-data.js" in TRENDS_HTML, (
        "trends.html must load js/mock-data.js before trends.js"
    )


def test_ac17_trends_html_loads_trends_js():
    assert "trends.js" in TRENDS_HTML, "trends.html must load js/trends.js"


# ── AC-18: trends.js uses .value for readiness and sleep ─────────────────────

def test_ac18_trends_js_reads_readiness_via_value():
    assert ".value" in TRENDS_JS, (
        "trends.js must read series entries via '.value' (new API shape)"
    )


def test_ac18_trends_js_does_not_use_dot_score_for_readiness():
    score_pattern = "readiness" in TRENDS_JS and ".score" in TRENDS_JS
    # It's acceptable to have ".score" in a comment or tooltip string,
    # but the series mapping must not use .score
    score_in_series_map = "s.score" in TRENDS_JS or 'entry["score"]' in TRENDS_JS
    assert not score_in_series_map, (
        "trends.js must not map readiness series via 's.score'; use 's.value'"
    )


def test_ac18_trends_js_does_not_use_dot_hours_for_sleep():
    hours_in_series_map = "s.hours" in TRENDS_JS or '.hours)' in TRENDS_JS
    assert not hours_in_series_map, (
        "trends.js must not map sleep series via 's.hours'; use 's.value'"
    )


# ── AC-19: delta.direction sign consistency ───────────────────────────────────

@pytest.mark.parametrize("metric", DELTA_METRICS)
def test_ac19_delta_direction_matches_value_sign(summary_30d, metric):
    delta = summary_30d[metric]["delta"]
    val = delta["value"]
    direction = delta["direction"]
    if val is None:
        assert direction == "flat", (
            f"{metric}: null delta.value must give direction='flat'; got '{direction}'"
        )
    elif val > 0.005:
        assert direction == "up", (
            f"{metric}: positive delta.value ({val}) must give direction='up'; got '{direction}'"
        )
    elif val < -0.005:
        assert direction == "down", (
            f"{metric}: negative delta.value ({val}) must give direction='down'; got '{direction}'"
        )


@pytest.mark.parametrize("metric", DELTA_METRICS)
def test_ac19_delta_pct_sign_consistent_with_value(summary_30d, metric):
    delta = summary_30d[metric]["delta"]
    val = delta["value"]
    pct = delta["pct"]
    if val is None or pct is None:
        return
    assert (val >= 0) == (pct >= 0), (
        f"{metric}: delta.value ({val}) and delta.pct ({pct}) must have the same sign"
    )
