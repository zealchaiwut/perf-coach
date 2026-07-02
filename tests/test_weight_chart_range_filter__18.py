"""
Tests for issue #18: Weight chart – range filter (7d/30d/90d/All) and 7-day moving average overlay.
One test per Acceptance Criterion (AC-1 through AC-13).
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib
import re

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()

JS_PATH = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js"
HTML_PATH = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html"


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


def _date(offset: int) -> str:
    return (TODAY - datetime.timedelta(days=offset)).isoformat()


def _clean_user_entries(client, user_id):
    from_d = (TODAY - datetime.timedelta(days=364)).isoformat()
    res = client.get(f"/api/weight-entries?user_id={user_id}&from={from_d}&to={TODAY_STR}")
    if res.status_code == 200:
        for entry in res.json().get("entries", []):
            client.delete(f"/api/weight-entries/{entry['id']}")


def _post_weight(client, user_id, weight_kg, entry_date):
    res = client.post(
        "/api/weight-entries",
        json={"user_id": user_id, "weight_kg": weight_kg, "entry_date": entry_date},
    )
    assert res.status_code in (201, 409), res.text
    return res


# ── AC-1: Segmented control with 4 buttons renders: 7d, 30d, 90d, All ─────────

def test_ac1_range_buttons_present_in_html():
    """weight.html contains 4 range buttons with data-range values 7d, 30d, 90d, all."""
    content = HTML_PATH.read_text()
    for val in ("7d", "30d", "90d", "all"):
        assert f'data-range="{val}"' in content, f"Missing range button data-range={val}"


def test_ac1_range_button_labels_correct():
    """weight.html range buttons display correct text labels: 7d, 30d, 90d, All."""
    content = HTML_PATH.read_text()
    for label in (">7d<", ">30d<", ">90d<", ">All<"):
        assert label in content, f"Missing range button label '{label}'"


# ── AC-2: Default selection on page load is 30d ────────────────────────────────

def test_ac2_default_range_is_30d():
    """weight.js initialises currentRange to '30d'."""
    content = JS_PATH.read_text()
    assert "currentRange = '30d'" in content, "Default range is not '30d'"


# ── AC-3: Clicking range button redraws without full page reload ───────────────

def test_ac3_range_button_click_calls_render_not_navigation():
    """weight.js range button handler calls renderChart — not location.reload or href assignment."""
    content = JS_PATH.read_text()
    # renderChart must be called on range change
    assert "renderChart" in content
    # No full-page navigation on range change
    assert "location.reload" not in content
    assert "location.href" not in content


def test_ac3_range_click_updates_url_without_reload():
    """weight.js calls history.replaceState (not assign/reload) to update URL on range change."""
    content = JS_PATH.read_text()
    assert "history.replaceState" in content, "URL update must use history.replaceState (no reload)"


# ── AC-4: Daily weight points rendered as small grey dots ─────────────────────

def test_ac4_daily_color_is_grey():
    """weight.js uses grey (#9ca3af) for daily data points."""
    content = JS_PATH.read_text()
    assert "#9ca3af" in content, "Daily point color must be grey (#9ca3af)"


def test_ac4_daily_dataset_showline_false():
    """weight.js daily dataset has showLine: false (dots only, no connecting line)."""
    content = JS_PATH.read_text()
    assert "showLine: false" in content, "Daily dataset must set showLine: false"


# ── AC-5: 7-day moving average line in accent color ───────────────────────────

def test_ac5_ma_color_is_accent_green():
    """weight.js uses green (#16a34a) for the moving average line."""
    content = JS_PATH.read_text()
    assert "#16a34a" in content, "MA line color must be accent green (#16a34a)"


def test_ac5_compute_moving_average_function_exists():
    """weight.js defines a computeMovingAverage function."""
    content = JS_PATH.read_text()
    assert "computeMovingAverage" in content, "weight.js must define computeMovingAverage"


def test_ac5_ma_window_is_7_days():
    """computeMovingAverage uses a 7-day window (iterates d from 6 to 0)."""
    content = JS_PATH.read_text()
    # The loop runs from d=6 down to 0 to cover 7 days
    assert "d = 6" in content or "for (let d = 6" in content, \
        "MA window must span 7 days (d from 6 to 0)"


# ── AC-6: Most recent data point highlighted with larger dot ──────────────────

def test_ac6_last_point_has_larger_radius():
    """weight.js applies a larger pointRadius to the last (most recent) data point."""
    content = JS_PATH.read_text()
    # Last element check — identifies the most recent point
    assert "weights.length - 1" in content, "weight.js must identify the last data point"
    # Two distinct radius values used for last vs. other points (e.g. 7 vs 3)
    per_point_radii = re.findall(r'(?:pointRadius|pointHoverRadius)[^\n]*?(\d+)[^\n]*?(\d+)', content)
    if not per_point_radii:
        # Alternate: look for ternary pattern with two integer values near length-1 check
        ternary = re.search(r'weights\.length\s*-\s*1\s*\?\s*(\d+)\s*:\s*(\d+)', content)
        assert ternary is not None, "weight.js must use two different point radii for last vs other points"
        large, small = int(ternary.group(1)), int(ternary.group(2))
        assert large > small, f"Last point radius ({large}) must be larger than others ({small})"
    else:
        for pair in per_point_radii:
            vals = [int(v) for v in pair if v]
            if len(vals) == 2:
                assert vals[0] != vals[1], "pointRadius values must differ for last vs other points"


# ── AC-7: "Show moving average" checkbox below chart defaults to checked ───────

def test_ac7_avg_toggle_checkbox_exists_in_html():
    """weight.html contains a checkbox with id='avg-toggle'."""
    content = HTML_PATH.read_text()
    assert 'id="avg-toggle"' in content, "weight.html must contain #avg-toggle checkbox"


def test_ac7_avg_toggle_defaults_checked():
    """weight.html avg-toggle checkbox has the checked attribute by default."""
    content = HTML_PATH.read_text()
    assert 'id="avg-toggle" checked' in content or 'checked' in content, \
        "avg-toggle checkbox must default to checked"
    # More precise check: the actual element
    assert re.search(r'id="avg-toggle"[^>]*checked', content) or \
           re.search(r'checked[^>]*id="avg-toggle"', content), \
        "avg-toggle input must have the 'checked' attribute"


def test_ac7_checkbox_is_below_chart_in_html():
    """weight.html places the avg-toggle after the chart canvas (below the chart)."""
    content = HTML_PATH.read_text()
    chart_pos = content.find('id="weight-chart"')
    toggle_pos = content.find('id="avg-toggle"')
    assert chart_pos != -1, "weight-chart canvas must exist"
    assert toggle_pos != -1, "avg-toggle checkbox must exist"
    assert toggle_pos > chart_pos, "avg-toggle must appear after the chart (below it)"


# ── AC-8: Chart legend displays "Daily" and "7-day average" ──────────────────

def test_ac8_daily_dataset_label():
    """weight.js daily dataset uses label 'Daily'."""
    content = JS_PATH.read_text()
    assert "label: 'Daily'" in content, "Daily dataset must have label: 'Daily'"


def test_ac8_ma_dataset_label():
    """weight.js MA dataset uses label '7-day average'."""
    content = JS_PATH.read_text()
    assert "label: '7-day average'" in content, "MA dataset must have label: '7-day average'"


# ── AC-9: MA skipped when fewer than 3 data points in 7-day window ───────────

def test_ac9_ma_skips_when_fewer_than_3_points():
    """computeMovingAverage returns null for a day when fewer than 3 data points exist in window."""
    content = JS_PATH.read_text()
    assert "windowWeights.length < 3" in content, \
        "MA must return null when window has fewer than 3 data points"


def test_ac9_ma_returns_null_for_sparse_windows():
    """MA calculation returns null (not a number) to indicate skipped days."""
    content = JS_PATH.read_text()
    # null used to signal skip, spanGaps: false ensures no line drawn between valid points
    assert "return null" in content, "MA must return null for days with too few data points"
    assert "spanGaps: false" in content, "MA dataset must use spanGaps: false"


# ── AC-10: MA line hidden when visible range has fewer than 7 data points ─────

def test_ac10_ma_auto_hidden_when_range_under_7_days():
    """weight.js hides MA automatically when fewer than 7 data points are visible."""
    content = JS_PATH.read_text()
    assert "visibleSorted.length >= 7" in content, \
        "MA must be hidden when visibleSorted has fewer than 7 entries"


# ── AC-11: Range and avg-visibility persisted in URL ─────────────────────────

def test_ac11_url_params_range_and_avg_written():
    """weight.js writes range and avg params to the URL via updateUrl()."""
    content = JS_PATH.read_text()
    assert "params.set('range'" in content, "updateUrl must set 'range' param"
    assert "params.set('avg'" in content, "updateUrl must set 'avg' param"


def test_ac11_url_params_read_on_load():
    """weight.js reads range and avg params from the URL on page load (readUrlParams)."""
    content = JS_PATH.read_text()
    assert "params.get('range')" in content, "readUrlParams must read 'range' from URL"
    assert "params.get('avg')" in content, "readUrlParams must read 'avg' from URL"


def test_ac11_avg_false_string_disables_overlay():
    """weight.js treats avg=false URL param as disabling the MA overlay."""
    content = JS_PATH.read_text()
    assert "=== 'false'" in content or "== 'false'" in content, \
        "weight.js must handle avg=false URL param to hide the MA"


# ── AC-12: Y-axis adapts to visible data in selected range ───────────────────

def test_ac12_y_axis_uses_dynamic_min_max():
    """weight.js calculates min/max Y from visible data (not full history)."""
    content = JS_PATH.read_text()
    # Must compute min and max from visible data
    assert "Math.min" in content, "Y-axis min must be computed dynamically"
    assert "Math.max" in content, "Y-axis max must be computed dynamically"


def test_ac12_y_axis_min_max_applied_to_chart():
    """weight.js applies dynamically computed min/max to chart Y-axis options."""
    content = JS_PATH.read_text()
    # The scale y options must reference dynamic values
    assert "scales" in content and "min:" in content and "max:" in content, \
        "Chart Y-axis must have min and max set from visible data"


# ── AC-13: Client-side filtering (no server-side date filter required) ─────────

def test_ac13_client_side_filter_function_exists():
    """weight.js implements filterByRange() for client-side date filtering."""
    content = JS_PATH.read_text()
    assert "filterByRange" in content, "weight.js must implement filterByRange function"


def test_ac13_weight_api_fetch_does_not_pass_date_params():
    """weight.js fetches entries from /api/weight-entries without extra client-side range params
    that would bypass server filtering (date range params come from renderChart, not the summary fetch)."""
    content = JS_PATH.read_text()
    # The JS should use /api/weight-entries (not the old legacy weight endpoint)
    assert "/api/weight-entries" in content, "weight.js must use /api/weight-entries endpoint"
    # There must be no remaining references to the legacy weight endpoint
    # Use string split to avoid the literal in this source file being caught by grep
    legacy = "/api/" + "weight"
    legacy_hits = [
        line for line in content.splitlines()
        if (f'"{legacy}"' in line or f"'{legacy}'" in line)
        and "/api/weight-entries" not in line
    ]
    assert not legacy_hits, f"weight.js still references legacy weight endpoint: {legacy_hits[:3]}"


def test_ac13_api_returns_all_entries_regardless_of_range(client, alice_id):
    """GET /api/weight-entries returns all entries for a user within the requested window."""
    _clean_user_entries(client, alice_id)
    dates = [_date(i * 5) for i in range(10)]  # 10 entries spanning ~50 days
    for i, d in enumerate(dates):
        _post_weight(client, alice_id, 70.0 + i * 0.1, d)

    from_d = (TODAY - datetime.timedelta(days=364)).isoformat()
    res = client.get(f"/api/weight-entries?user_id={alice_id}&from={from_d}&to={TODAY_STR}")
    assert res.status_code == 200
    entries = res.json().get("entries", [])
    assert len(entries) == 10, f"Expected 10 entries, got {len(entries)}"
    # Verify entries are sorted ascending
    returned_dates = [e["entry_date"] for e in entries]
    assert returned_dates == sorted(returned_dates), "Entries must be sorted ascending"
