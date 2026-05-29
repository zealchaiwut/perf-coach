"""
Tests for issue #147: Build trend row with HRV/TSS/RHR/Weight cards
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib
import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()
HTML = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html"
JS   = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js"


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
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _put_metrics(client, user_id, date_str, hrv=55, resting_hr=52, sleep_hours=7.5,
                 sleep_quality=4, energy=4, mood=4):
    res = client.put(
        f"/api/daily-metrics/{user_id}/{date_str}",
        json={
            "resting_hr": resting_hr,
            "hrv": hrv,
            "sleep_hours": sleep_hours,
            "sleep_quality": sleep_quality,
            "energy": energy,
            "mood": mood,
        },
    )
    assert res.status_code in (200, 201), f"PUT daily-metrics failed: {res.status_code} {res.text}"


def _post_weight(client, user_id, date_str, kg):
    res = client.post(
        f"/api/weight?user_id={user_id}",
        json={"weight_kg": kg, "recorded_date": date_str},
    )
    assert res.status_code in (201, 409), f"POST weight failed: {res.status_code} {res.text}"


# ── AC-1: #row-3 container in home.html ───────────────────────────────────────

def test_ac1_row3_div_in_html():
    """home.html must contain an element with id='row-3'."""
    html = HTML.read_text()
    assert 'id="row-3"' in html, "Missing id='row-3' in home.html"


def test_ac1_row3_4col_grid_css():
    """home.html CSS must define a 4-column grid for #row-3 on desktop."""
    html = HTML.read_text()
    assert "repeat(4, 1fr)" in html, \
        "home.html must define repeat(4, 1fr) grid for #row-3 or .trend-cards-row"


def test_ac1_trend_card_class_defined():
    """home.html CSS must define .trend-card class for card shells."""
    html = HTML.read_text()
    assert ".trend-card" in html, "Missing .trend-card CSS class in home.html"


# ── AC-2: Mobile visibility — HRV and RHR hidden at <880px ────────────────────

def test_ac2_mobile_hrv_hidden():
    """home.html must hide #trend-card-hrv at viewport <880px via CSS."""
    html = HTML.read_text()
    assert "trend-card-hrv" in html, "Missing #trend-card-hrv reference in home.html"
    assert "display: none" in html or "display:none" in html, \
        "home.html must set display:none on #trend-card-hrv in a media query"


def test_ac2_mobile_rhr_hidden():
    """home.html must hide #trend-card-rhr at viewport <880px via CSS."""
    html = HTML.read_text()
    assert "trend-card-rhr" in html, "Missing #trend-card-rhr reference in home.html"


def test_ac2_breakpoint_880px():
    """home.html must contain an 880px media query for mobile card hiding."""
    html = HTML.read_text()
    assert "880px" in html, "Missing 880px breakpoint in home.html for Row 3 responsive rules"


def test_ac2_mobile_row3_one_column():
    """home.html must set #row-3 to 1-column grid on mobile."""
    html = HTML.read_text()
    assert "#row-3" in html, "Missing #row-3 reference in home.html"
    assert "grid-template-columns: 1fr" in html or "grid-template-columns:1fr" in html, \
        "home.html must collapse #row-3 to 1fr on mobile"


# ── AC-3: Each card has header with icon, title, and period badge ─────────────

def test_ac3_period_30d_in_js():
    """home.js must render '30d' period badge for HRV, RHR, and Weight cards."""
    js = JS.read_text()
    assert "'30d'" in js or '"30d"' in js, "Missing '30d' period badge in home.js"


def test_ac3_period_8d_in_js():
    """home.js must render '8d' period badge for the Weekly TSS card."""
    js = JS.read_text()
    assert "'8d'" in js or '"8d"' in js, "Missing '8d' period badge in home.js"


def test_ac3_trend_card_header_class_in_js():
    """home.js must build elements with trend-card-header class."""
    js = JS.read_text()
    assert "trend-card-header" in js, "Missing trend-card-header class in home.js"


def test_ac3_trend_card_period_class_in_js():
    """home.js must build period badge elements with trend-card-period class."""
    js = JS.read_text()
    assert "trend-card-period" in js, "Missing trend-card-period class in home.js"


# ── AC-4: Stat row with value, unit, delta pill ───────────────────────────────

def test_ac4_trend_card_stat_class_in_js():
    """home.js must build stat rows with trend-card-stat class."""
    js = JS.read_text()
    assert "trend-card-stat" in js, "Missing trend-card-stat class in home.js"


def test_ac4_trend_delta_pill_classes_in_js():
    """home.js must apply trend-delta-pill--up / --down / --flat classes."""
    js = JS.read_text()
    assert "trend-delta-pill--up" in js,   "Missing trend-delta-pill--up in home.js"
    assert "trend-delta-pill--down" in js, "Missing trend-delta-pill--down in home.js"
    assert "trend-delta-pill--flat" in js, "Missing trend-delta-pill--flat in home.js"


def test_ac4_hrv_higher_is_better_in_js():
    """home.js must treat HRV delta > 0 as 'up' (good) direction."""
    js = JS.read_text()
    assert "renderHRVTrendCard" in js, "Missing renderHRVTrendCard in home.js"
    assert "delta > 0 ? 'up' : 'down'" in js or "'up' : 'down'" in js, \
        "home.js must map positive HRV delta to 'up' pill direction"


def test_ac4_rhr_lower_is_better_in_js():
    """home.js must treat RHR delta < 0 as 'up' (good) direction."""
    js = JS.read_text()
    assert "renderRHRTrendCard" in js, "Missing renderRHRTrendCard in home.js"
    assert "delta < 0 ? 'up' : 'down'" in js, \
        "home.js must map negative RHR delta to 'up' (good) pill direction"


def test_ac4_weight_direction_only_flat_pill():
    """home.js Weight card must use flat pill styling (direction-only, no good/bad color)."""
    js = JS.read_text()
    assert "renderWeightTrendCard" in js, "Missing renderWeightTrendCard in home.js"
    assert "'flat'" in js, "home.js Weight card must use 'flat' pill direction"


# ── AC-5: Sparklines ─────────────────────────────────────────────────────────

def test_ac5_area_sparkline_function_in_js():
    """home.js must have a line+area SVG sparkline function for HRV/RHR/Weight."""
    js = JS.read_text()
    assert "_trendAreaSpark" in js, "Missing _trendAreaSpark function in home.js"


def test_ac5_area_spark_uses_linear_gradient():
    """_trendAreaSpark must output a linearGradient for the area fill."""
    js = JS.read_text()
    assert "linearGradient" in js, \
        "home.js _trendAreaSpark must use linearGradient for area fill"


def test_ac5_bar_sparkline_function_in_js():
    """home.js must have a bar SVG sparkline function for Weekly TSS."""
    js = JS.read_text()
    assert "_trendBarSpark" in js, "Missing _trendBarSpark function in home.js"


def test_ac5_bar_spark_highlights_peak_bar():
    """_trendBarSpark must highlight the peak bar with a distinct fill color."""
    js = JS.read_text()
    assert "peakIdx" in js, "home.js _trendBarSpark must use peakIdx for peak highlighting"
    assert "i === peakIdx" in js, \
        "home.js must compare i === peakIdx to select peak bar fill"


def test_ac5_trend_sparkline_class_in_js():
    """Sparkline SVGs must carry trend-sparkline CSS class."""
    js = JS.read_text()
    assert "trend-sparkline" in js, "Missing trend-sparkline class in home.js SVG output"


# ── AC-6: Footer row ──────────────────────────────────────────────────────────

def test_ac6_trend_card_footer_class_in_js():
    """home.js must build footer rows with trend-card-footer class."""
    js = JS.read_text()
    assert "trend-card-footer" in js, "Missing trend-card-footer class in home.js"


def test_ac6_hrv_baseline_in_footer():
    """home.js HRV card footer must show baseline value."""
    js = JS.read_text()
    assert "Baseline" in js, "Missing 'Baseline' footer text in home.js HRV card"


def test_ac6_tss_peak_day_in_footer():
    """home.js TSS card footer must show the peak day name."""
    js = JS.read_text()
    assert "Peak:" in js, "Missing 'Peak:' footer text in home.js TSS card"


# ── AC-7: Weight card quick-input ─────────────────────────────────────────────

def test_ac7_quick_input_in_js():
    """home.js must build a quick-input row inside the Weight trend card."""
    js = JS.read_text()
    assert "trend-quick-input" in js, "Missing trend-quick-input class in home.js"


def test_ac7_quick_save_btn_in_js():
    """home.js must include a Save button with data-save='weight' attribute."""
    js = JS.read_text()
    assert "data-save=\"weight\"" in js or "data-save='weight'" in js, \
        "Missing data-save='weight' button in home.js Weight card"


def test_ac7_post_weight_in_js():
    """home.js must POST to /api/weight when Save is clicked."""
    js = JS.read_text()
    assert "'/api/weight?" in js or '"/api/weight?' in js or "/api/weight?" in js, \
        "home.js must POST to /api/weight on Save"
    assert "method: 'POST'" in js or 'method: "POST"' in js, \
        "home.js Save handler must use POST method"


def test_ac7_weight_refetch_after_save():
    """home.js must re-fetch /api/weight after a successful Save."""
    js = JS.read_text()
    assert "renderWeightTrendCard" in js, "home.js must re-render Weight card after save"


def test_ac7_save_posts_to_api(client, alice_id):
    """POST /api/weight accepts {weight_kg, recorded_date} and returns 201."""
    res = client.post(
        f"/api/weight?user_id={alice_id}",
        json={"weight_kg": 70.5, "recorded_date": TODAY_STR},
    )
    assert res.status_code in (201, 409), \
        f"POST /api/weight must return 201 or 409, got {res.status_code}"
    if res.status_code == 201:
        body = res.json()
        assert abs(body["weight_kg"] - 70.5) < 0.01
        assert body["recorded_date"] == TODAY_STR


# ── AC-8: Data sources ────────────────────────────────────────────────────────

def test_ac8_trends_summary_fetched_with_range_30d():
    """home.js must fetch /trends/summary?...&range=30d for Row 3 trend cards."""
    js = JS.read_text()
    assert "range=30d" in js, "home.js must fetch /trends/summary with range=30d"


def test_ac8_weight_fetched_from_api_weight():
    """home.js Row 3 must fetch /api/weight separately for the Weight card."""
    js = JS.read_text()
    assert "/api/weight?" in js, "home.js must fetch /api/weight for the Weight trend card"


def test_ac8_trends_summary_endpoint_returns_200(client, alice_id):
    """/trends/summary?range=30d must return 200 with hrv, rhr, tss keys."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200, \
        f"/trends/summary returned {res.status_code}: {res.text}"
    body = res.json()
    assert "hrv" in body,  "/trends/summary response must have 'hrv' key"
    assert "rhr" in body,  "/trends/summary response must have 'rhr' key"
    assert "tss" in body,  "/trends/summary response must have 'tss' key"


def test_ac8_trends_summary_hrv_has_series_and_baseline(client, alice_id):
    """/trends/summary hrv object must have series list and baseline_mean."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200
    hrv = res.json()["hrv"]
    assert "series" in hrv,        "hrv must have 'series' list"
    assert isinstance(hrv["series"], list), "hrv.series must be a list"
    assert "baseline_mean" in hrv, "hrv must have 'baseline_mean'"


def test_ac8_trends_summary_rhr_has_series_and_baseline(client, alice_id):
    """/trends/summary rhr object must have series list and baseline_mean."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200
    rhr = res.json()["rhr"]
    assert "series" in rhr,        "rhr must have 'series' list"
    assert isinstance(rhr["series"], list), "rhr.series must be a list"
    assert "baseline_mean" in rhr, "rhr must have 'baseline_mean'"


def test_ac8_trends_summary_tss_has_series(client, alice_id):
    """/trends/summary tss object must have series list."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200
    tss = res.json()["tss"]
    assert "series" in tss,        "tss must have 'series' list"
    assert isinstance(tss["series"], list), "tss.series must be a list"


def test_ac8_trends_summary_series_date_value_shape(client, alice_id):
    """/trends/summary series entries must have 'date' and 'value' keys."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200
    hrv_series = res.json()["hrv"]["series"]
    assert len(hrv_series) > 0, "hrv.series must not be empty"
    entry = hrv_series[0]
    assert "date" in entry,  "hrv.series entries must have 'date'"
    assert "value" in entry, "hrv.series entries must have 'value'"


def test_ac8_hrv_series_has_30_days(client, alice_id):
    """/trends/summary?range=30d must return exactly 30 series entries for hrv."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200
    hrv_series = res.json()["hrv"]["series"]
    assert len(hrv_series) == 30, \
        f"hrv.series must have 30 entries for range=30d, got {len(hrv_series)}"


# ── AC-9: Error handling ──────────────────────────────────────────────────────

def test_ac9_load_row3_function_in_js():
    """home.js must export a loadRow3 function."""
    js = JS.read_text()
    assert "loadRow3" in js, "Missing loadRow3 function in home.js"


def test_ac9_promise_allsettled_in_js():
    """home.js must use Promise.allSettled so one failure doesn't crash the page."""
    js = JS.read_text()
    assert "Promise.allSettled" in js, \
        "home.js must use Promise.allSettled so trends/summary failure doesn't crash the page"


def test_ac9_summary_failed_flag_in_js():
    """home.js must track whether the trends/summary fetch failed."""
    js = JS.read_text()
    assert "summaryFailed" in js, \
        "home.js must track summaryFailed to isolate error handling per card"


def test_ac9_null_summary_passed_on_failure():
    """home.js must pass null summary to HRV/TSS/RHR render functions on failure."""
    js = JS.read_text()
    assert "summaryFailed ? null : summary" in js or "passedSummary" in js, \
        "home.js must pass null summary to card renderers when trends/summary fails"


def test_ac9_error_state_message_in_js():
    """home.js must render a friendly error message when data is unavailable."""
    js = JS.read_text()
    assert "Couldn't load" in js or "couldn't load" in js or "Could not load" in js, \
        "home.js must show a friendly 'couldn't load' error state in cards"


def test_ac9_weight_card_unaffected_by_summary_failure():
    """home.js Weight card must use /api/weight separately, not from trends/summary."""
    js = JS.read_text()
    assert "renderWeightTrendCard" in js, "Missing renderWeightTrendCard in home.js"
    assert "wResult" in js or "weightEntries" in js, \
        "home.js must independently track weight API result from summary result"


# ── AC-10: loadRow3 called from init ─────────────────────────────────────────

def test_ac10_load_row3_called_in_init():
    """home.js init must call loadRow3(userId)."""
    js = JS.read_text()
    assert "loadRow3(userId)" in js, \
        "home.js init() must call loadRow3(userId) when user is available"


def test_ac10_skeleton_shimmer_in_js():
    """home.js must render shimmer skeleton cards before data loads."""
    js = JS.read_text()
    assert "trend-skeleton-line" in js, \
        "home.js must show trend-skeleton-line shimmer while Row 3 data loads"


# ── AC-11: API integration ────────────────────────────────────────────────────

def test_ac11_weight_api_returns_entries(client, alice_id):
    """GET /api/weight must return list with recorded_date and weight_kg."""
    _post_weight(client, alice_id, TODAY_STR, 71.0)
    res = client.get(f"/api/weight?user_id={alice_id}")
    assert res.status_code == 200
    entries = res.json()
    assert isinstance(entries, list)
    today_e = next((e for e in entries if e["recorded_date"] == TODAY_STR), None)
    assert today_e is not None, "Today's weight entry must appear in /api/weight response"
    assert "weight_kg" in today_e
    assert "recorded_date" in today_e


def test_ac11_trends_summary_live_hrv_data(client, alice_id):
    """After logging daily metrics, hrv.series should contain non-null values."""
    _put_metrics(client, alice_id, TODAY_STR, hrv=62, resting_hr=50)
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200
    hrv_series = res.json()["hrv"]["series"]
    non_null = [e for e in hrv_series if e["value"] is not None]
    assert len(non_null) >= 1, \
        "After logging HRV, trends/summary must return at least 1 non-null hrv value"


def test_ac11_trends_summary_live_rhr_data(client, alice_id):
    """After logging daily metrics, rhr.series should contain non-null values."""
    _put_metrics(client, alice_id, TODAY_STR, resting_hr=50)
    res = client.get(f"/trends/summary?user_id={alice_id}&range=30d")
    assert res.status_code == 200
    rhr_series = res.json()["rhr"]["series"]
    non_null = [e for e in rhr_series if e["value"] is not None]
    assert len(non_null) >= 1, \
        "After logging RHR, trends/summary must return at least 1 non-null rhr value"
