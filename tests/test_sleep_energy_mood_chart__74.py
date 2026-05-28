"""
Tests for issue #74: Add Sleep, Energy, and Mood Trend Chart

A unified chart renders sleep quality (bars or area fill) on the primary time
axis with energy and mood overlaid as visually-distinct lines/dots.
Missing days show as gaps, tooltip shows all available values, toggle controls
let users hide individual series, and the chart degrades gracefully when fewer
than all three series are returned.

Server under test: http://127.0.0.1:9001
"""
import json
import pathlib
import re
import subprocess

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
ROOT = pathlib.Path(__file__).parent.parent

HTML = (ROOT / "trends.html").read_text()
JS   = (ROOT / "js" / "trends.js").read_text()
MOCK = (ROOT / "js" / "mock-data.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── Node.js helper ────────────────────────────────────────────────────────────

def _node(script: str) -> object:
    src = f"{MOCK}\n{script}"
    r = subprocess.run(["node", "-e", src], capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, f"node exited non-zero:\n{r.stderr}"
    return json.loads(r.stdout)


# ── Regression guards ─────────────────────────────────────────────────────────

def test_regression_trends_html_served(client):
    """GET /trends.html must still return 200."""
    res = client.get("/trends.html")
    assert res.status_code == 200, f"trends.html returned {res.status_code}"


def test_regression_readiness_slot_untouched():
    """#slot-readiness must still exist after adding the sleep/energy/mood chart."""
    assert 'id="slot-readiness"' in HTML or "id='slot-readiness'" in HTML, \
        "#slot-readiness must not have been removed"


# ── AC-1: Single chart — sleep on primary time axis (bars or area fill) ───────

def test_ac1_sleep_energy_slot_in_html():
    """trends.html must contain a dedicated slot for the sleep/energy/mood chart."""
    has_slot = (
        'id="slot-sleep-energy"' in HTML
        or "id='slot-sleep-energy'" in HTML
        or 'id="slot-sleep-energy-mood"' in HTML
        or 'id="slot-sem"' in HTML
        or "id='slot-sem'" in HTML
    )
    assert has_slot, \
        "trends.html must define a chart slot for the sleep/energy/mood chart"


def test_ac1_sleep_body_element_present():
    """trends.html must have a body container (chart-slot-body) for the chart."""
    has_body = (
        'id="slot-sleep-energy-body"' in HTML
        or "id='slot-sleep-energy-body'" in HTML
        or 'id="slot-sleep-energy-mood-body"' in HTML
        or 'id="slot-sem-body"' in HTML
        or "id='slot-sem-body'" in HTML
    )
    assert has_body, \
        "trends.html must have a chart-slot-body element for the sleep/energy/mood chart"


def test_ac1_render_function_exists():
    """trends.js must define a render function for the sleep/energy/mood chart."""
    has_fn = (
        "renderSleepEnergyChart" in JS
        or "renderSleepEnergyMoodChart" in JS
        or "renderSleepChart" in JS
        or "renderSEMChart" in JS
    )
    assert has_fn, \
        "trends.js must define a function to render the sleep/energy/mood chart"


def test_ac1_sleep_on_primary_axis():
    """Sleep must be assigned to a dedicated primary Y-axis (ySleep or similar)."""
    has_sleep_axis = (
        "ySleep" in JS
        or "yAxisID: 'sleep'" in JS
        or 'yAxisID: "sleep"' in JS
        or "yAxisID: 'ySleep'" in JS
    )
    assert has_sleep_axis, \
        "trends.js must assign the sleep dataset to a dedicated primary Y-axis " \
        "(e.g. ySleep) — sleep is the primary metric on the chart"


def test_ac1_sleep_rendered_as_bar_or_area_fill():
    """Sleep must be rendered as bars or area fill, not a plain unfilled line."""
    # Check that the sleep dataset is either: type 'bar', OR has fill enabled
    # The chart renders sleep differently from energy/mood (which are plain lines)
    sleep_section = ""
    for fn_name in ["renderSleepEnergyChart", "renderSleepEnergyMoodChart", "renderSleepChart"]:
        if fn_name in JS:
            start = JS.find(fn_name)
            end = JS.find("\n  function", start + 1)
            if end == -1:
                end = start + 3000
            sleep_section = JS[start:end]
            break
    if not sleep_section:
        sleep_section = JS

    has_bar_sleep = (
        "type: 'bar'" in sleep_section
        or "type:'bar'" in sleep_section
    )
    has_area_sleep = (
        # fill: true or fill: 'start' or fill: 'origin' — not fill: false
        re.search(r"fill:\s*(?!'false'|false|\"false\")", sleep_section)
        and "fill: false" not in sleep_section[:sleep_section.find("fill:") + 20]
        if sleep_section.count("fill:") == 1
        else (
            "fill: 'start'" in sleep_section
            or "fill: 'origin'" in sleep_section
            or "fill: true" in sleep_section
            or 'fill: "start"' in sleep_section
            or 'fill: "origin"' in sleep_section
        )
    )

    assert has_bar_sleep or has_area_sleep, \
        "trends.js must render sleep as bars (type: 'bar') or as an area fill " \
        "(fill: 'start' / fill: 'origin' / fill: true) — not a plain unfilled line. " \
        "AC-1 specifies 'bars or area fills' for the sleep series."


def test_ac1_sleep_series_consumed_from_summary():
    """trends.js must read sleep data from summary.sleep.series."""
    assert "sleep.series" in JS or "summary.sleep" in JS, \
        "trends.js must consume sleep data from summary.sleep.series"


# ── AC-2: Energy and mood overlaid as visually-distinct lines/dots ─────────────

def test_ac2_energy_dataset_present():
    """trends.js must include an energy dataset in the chart."""
    assert "energy" in JS and ("Energy" in JS or "'energy'" in JS or '"energy"' in JS), \
        "trends.js must render an energy dataset in the sleep/energy/mood chart"


def test_ac2_mood_dataset_present():
    """trends.js must include a mood dataset in the chart."""
    assert "mood" in JS and ("Mood" in JS or "'mood'" in JS or '"mood"' in JS), \
        "trends.js must render a mood dataset in the sleep/energy/mood chart"


def test_ac2_energy_and_mood_use_distinct_colors():
    """Energy and mood datasets must have different border colors."""
    # Extract colors from sleep/energy/mood render function
    colors = re.findall(r"borderColor:\s*['\"]([^'\"]+)['\"]", JS)
    # Verify at least 3 distinct colors are used in the file (sleep, energy, mood)
    unique_colors = set(colors)
    assert len(unique_colors) >= 3, \
        "trends.js must define at least 3 distinct borderColor values — " \
        "one each for sleep, energy, and mood — so the series are visually distinguishable"


def test_ac2_energy_series_consumed_from_summary():
    """trends.js must read energy data from summary.energy.series."""
    assert "energy.series" in JS or "summary.energy" in JS, \
        "trends.js must consume energy data from summary.energy.series"


def test_ac2_mood_series_consumed_from_summary():
    """trends.js must read mood data from summary.mood.series."""
    assert "mood.series" in JS or "summary.mood" in JS, \
        "trends.js must consume mood data from summary.mood.series"


# ── AC-3: Missing days render as gaps (not zero values) ───────────────────────

def test_ac3_span_gaps_false_prevents_zero_interpolation():
    """All three datasets must set spanGaps: false so missing days break the line."""
    span_gaps_count = JS.count("spanGaps: false") + JS.count("spanGaps:false")
    assert span_gaps_count >= 3, \
        f"trends.js sets spanGaps: false {span_gaps_count} time(s) but needs at least 3 — " \
        "one per series (sleep, energy, mood) so null values render as gaps"


def test_ac3_null_values_in_mock_data():
    """mockGetTrendsSummary must return null entries in sleep/energy/mood series."""
    result = _node(
        "const r = mockGetTrendsSummary({range:'30d'});"
        "const sleepNulls  = r.sleep.series.filter(s => s.value === null).length;"
        "const energyNulls = r.energy.series.filter(s => s.value === null).length;"
        "const moodNulls   = r.mood.series.filter(s => s.value === null).length;"
        "process.stdout.write(JSON.stringify({sleepNulls, energyNulls, moodNulls}));"
    )
    assert result["sleepNulls"] > 0, \
        "mockGetTrendsSummary sleep.series must include at least one null value to exercise gap rendering"
    assert result["energyNulls"] > 0, \
        "mockGetTrendsSummary energy.series must include at least one null value to exercise gap rendering"
    assert result["moodNulls"] > 0, \
        "mockGetTrendsSummary mood.series must include at least one null value to exercise gap rendering"


# ── AC-4: Tooltip shows all available values for the hovered day ──────────────

def test_ac4_tooltip_callback_present():
    """trends.js must define a tooltip callback for the sleep/energy/mood chart."""
    has_tooltip = "tooltip" in JS and "callbacks" in JS
    assert has_tooltip, \
        "trends.js must configure tooltip callbacks for the sleep/energy/mood chart"


def test_ac4_tooltip_shows_date():
    """The tooltip title must show the date for the hovered data point."""
    # A title callback that returns the date is required
    has_date_title = (
        "title" in JS
        and (
            ".date" in JS
            or "date" in JS
        )
    )
    assert has_date_title, \
        "trends.js tooltip title callback must return the date for the hovered day"


def test_ac4_tooltip_labels_include_sleep_value():
    """Tooltip body must display the sleep value with its unit."""
    has_sleep_label = (
        "Sleep" in JS
        and (
            "label" in JS
            or "afterLabel" in JS
            or "afterBody" in JS
        )
    )
    # The tooltip must explicitly show sleep — Chart.js default labels use dataset.label
    # which must be set to 'Sleep (h)' or similar including the unit
    has_sleep_unit = (
        "Sleep (h)" in JS
        or "sleep_hours" in JS
        or "sleep hours" in JS.lower()
        or re.search(r"Sleep.*\(h\)", JS)
        or "Sleep quality" in JS
        or "sleep quality" in JS.lower()
    )
    assert has_sleep_unit, \
        "trends.js must label the sleep dataset with its unit (e.g. 'Sleep (h)' or 'Sleep quality') " \
        "so the tooltip displays the sleep value with its unit (AC-4)"


# ── AC-5: Optional weekly-average annotation ──────────────────────────────────

def test_ac5_weekly_average_annotation_implemented():
    """trends.js must implement a weekly-average annotation for the sleep/energy/mood chart."""
    has_weekly_avg = (
        "weeklyAvg" in JS
        or "weekly_avg" in JS
        or "weekAvg" in JS
        or "week_avg" in JS
        or "weeklyAverage" in JS
        or "weekly average" in JS.lower()
        or "weekly avg" in JS.lower()
        or ("annotation" in JS.lower() and "week" in JS.lower())
    )
    assert has_weekly_avg, \
        "trends.js must implement a weekly-average annotation for the sleep/energy/mood chart " \
        "(AC-5 requires a label or marker at the top of each week column when enabled)"


# ── AC-6: Toggle controls to show/hide individual series ──────────────────────

def test_ac6_toggle_control_in_html():
    """trends.html must render toggle buttons to show/hide mood and energy series."""
    # The slot-sleep-energy section must contain explicit controls for mood/energy visibility —
    # not just date-range preset buttons or classList.toggle('active') for other purposes.
    has_toggle = (
        "btn-toggle" in HTML
        or "series-toggle" in HTML
        or "data-series" in HTML
        or "show-mood" in HTML
        or "show-energy" in HTML
        or "hide-mood" in HTML
        or "hide-energy" in HTML
        or "toggle-mood" in HTML
        or "toggle-energy" in HTML
        or re.search(
            r'id="slot-sleep-energy".*?(?:checkbox|data-dataset|data-series)',
            HTML, re.DOTALL
        )
    )
    assert has_toggle, \
        "trends.html must contain toggle buttons or checkboxes within the sleep/energy/mood " \
        "chart slot to individually show or hide the mood series and energy series (AC-6). " \
        "Note: generic classList.toggle() used for date-range buttons does not qualify."


def test_ac6_toggle_logic_in_js():
    """trends.js must implement logic to show/hide mood or energy datasets by index."""
    # Must use Chart.js dataset visibility API — not generic element.hidden on emptyBanner
    has_toggle_logic = (
        "setDatasetVisibility" in JS
        or "dataset.hidden" in JS
        or "getDatasetMeta" in JS
        or "toggleDataset" in JS
        or "ds.hidden" in JS
        or re.search(r'chart\.\w*(hide|show|toggle|visible)', JS, re.IGNORECASE)
        or re.search(r'\.hidden\s*=\s*!', JS)
    )
    assert has_toggle_logic, \
        "trends.js must implement series-level toggle logic " \
        "(e.g. chart.setDatasetVisibility(), dataset.hidden, ds.hidden, or getDatasetMeta().hidden) " \
        "to show/hide the mood and energy datasets on demand (AC-6). " \
        "Note: emptyBanner.hidden and classList.toggle('active') do not qualify."


# ── AC-7: Mobile legibility at ≥ 320 px width ────────────────────────────────

def test_ac7_responsive_true():
    """Sleep/energy/mood chart must set responsive: true."""
    assert "responsive: true" in JS or "responsive:true" in JS, \
        "trends.js sleep/energy/mood chart must set responsive: true"


def test_ac7_maintain_aspect_ratio_false():
    """Chart must set maintainAspectRatio: false to prevent horizontal overflow."""
    assert "maintainAspectRatio: false" in JS or "maintainAspectRatio:false" in JS, \
        "trends.js sleep/energy/mood chart must set maintainAspectRatio: false"


def test_ac7_max_rotation_zero():
    """X-axis labels must not rotate on narrow viewports."""
    assert "maxRotation: 0" in JS or "maxRotation:0" in JS, \
        "trends.js must set maxRotation: 0 on the X-axis to keep labels horizontal on 320px viewports"


def test_ac7_max_ticks_limit_set():
    """X-axis must limit tick count to prevent label overlap on narrow screens."""
    assert "maxTicksLimit" in JS, \
        "trends.js must set maxTicksLimit on the sleep/energy/mood chart X-axis"


# ── AC-8: Graceful with partial series (1 or 2 of 3 returned) ────────────────

def test_ac8_missing_energy_series_handled():
    """trends.js must not crash when energy.series is absent from the API response."""
    # Code must guard against missing energy series before calling .map()
    has_energy_guard = (
        "energy && energy.series" in JS
        or "energy?.series" in JS
        or "energy.series ??" in JS
        or "hasEnergy" in JS
        or "energy && summary.energy" in JS
        or "summary.energy &&" in JS
        or "summary?.energy" in JS
        or "if (summary.energy" in JS
        or "(summary.energy)" in JS
    )
    assert has_energy_guard, \
        "trends.js must guard against a missing energy series " \
        "(e.g. summary?.energy?.series or an explicit guard) — AC-8 requires the chart " \
        "to render gracefully when the API omits one or two series"


def test_ac8_missing_mood_series_handled():
    """trends.js must not crash when mood.series is absent from the API response."""
    has_mood_guard = (
        "mood && mood.series" in JS
        or "mood?.series" in JS
        or "mood.series ??" in JS
        or "hasMood" in JS
        or "mood && summary.mood" in JS
        or "summary.mood &&" in JS
        or "summary?.mood" in JS
        or "if (summary.mood" in JS
        or "(summary.mood)" in JS
    )
    assert has_mood_guard, \
        "trends.js must guard against a missing mood series " \
        "(e.g. summary?.mood?.series or an explicit guard) — AC-8 requires the chart " \
        "to render gracefully when the API omits one or two series"


def test_ac8_missing_sleep_series_handled():
    """trends.js must not crash when sleep.series is absent from the API response."""
    has_sleep_guard = (
        "sleep && sleep.series" in JS
        or "sleep?.series" in JS
        or "sleep.series ??" in JS
        or "hasSleep" in JS
        or "sleep && summary.sleep" in JS
        or "summary.sleep &&" in JS
        or "summary?.sleep" in JS
        or "if (summary.sleep" in JS
    )
    assert has_sleep_guard, \
        "trends.js must guard against a missing sleep series — AC-8 requires the chart " \
        "to render gracefully with only 1 or 2 of the three series available"


# ── AC-9: No additional API calls beyond /trends/summary ─────────────────────

def test_ac9_no_extra_fetch_in_render_function():
    """renderSleepEnergyChart must not issue its own fetch() call."""
    sleep_fn = ""
    for fn_name in ["renderSleepEnergyChart", "renderSleepEnergyMoodChart", "renderSleepChart"]:
        if fn_name in JS:
            start = JS.find(fn_name)
            end = JS.find("\n  function", start + 1)
            if end == -1:
                end = start + 3000
            sleep_fn = JS[start:end]
            break
    assert "fetch(" not in sleep_fn, \
        "renderSleepEnergyChart must not issue its own fetch() — all data comes " \
        "from the single /trends/summary response already loaded by loadChartData (AC-9)"


def test_ac9_summary_endpoint_provides_all_three_series():
    """mockGetTrendsSummary must return sleep, energy, and mood series in a single call."""
    result = _node(
        "const r = mockGetTrendsSummary({range:'7d'});"
        "process.stdout.write(JSON.stringify({"
        "  hasSleep:  Array.isArray(r.sleep.series),"
        "  hasEnergy: Array.isArray(r.energy.series),"
        "  hasMood:   Array.isArray(r.mood.series)"
        "}));"
    )
    assert result["hasSleep"],  "mockGetTrendsSummary must return sleep.series as an array"
    assert result["hasEnergy"], "mockGetTrendsSummary must return energy.series as an array"
    assert result["hasMood"],   "mockGetTrendsSummary must return mood.series as an array"


def test_ac9_series_have_date_value_shape():
    """All three series must use the {date, value} shape the chart code expects."""
    result = _node(
        "const r = mockGetTrendsSummary({range:'7d'});"
        "const s = r.sleep.series[0]; const e = r.energy.series[0]; const m = r.mood.series[0];"
        "process.stdout.write(JSON.stringify({"
        "  sleepHasDate:  'date' in s, sleepHasValue:  'value' in s,"
        "  energyHasDate: 'date' in e, energyHasValue: 'value' in e,"
        "  moodHasDate:   'date' in m, moodHasValue:   'value' in m"
        "}));"
    )
    assert result["sleepHasDate"]  and result["sleepHasValue"],  \
        "sleep.series entries must have {date, value} shape"
    assert result["energyHasDate"] and result["energyHasValue"], \
        "energy.series entries must have {date, value} shape"
    assert result["moodHasDate"]   and result["moodHasValue"],   \
        "mood.series entries must have {date, value} shape"
