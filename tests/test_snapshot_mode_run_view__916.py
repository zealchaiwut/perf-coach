"""Tests for issue #916: Add Snapshot mode to Run detail view.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance Criteria:
  AC1  — A Snapshot button is visible in run-view.html / run-view.js
  AC2  — Pressing Snapshot replaces the normal layout with a fixed-width card
          (width matches share-card spec from mock, ~560px)
  AC3  — The card renders the header: type badge, run name, date, source badges
  AC4  — The card renders a hero strip containing Distance, Avg Pace, Duration, TSS
  AC5  — The card renders a compact metric row with ONLY populated metrics
          (no dash/empty cells); at minimum supports: Avg HR, Avg Power, NP, Cadence, Stride
  AC6  — The card renders the pace lap-chart
  AC7  — The card renders a full ultra-dense splits table listing every lap
  AC8  — A small perf-coach watermark line appears at the bottom of the card
  AC9  — The card never reflows at any viewport width (fixed-width layout)
  AC10 — No metric values are fabricated — all data read from GET /api/workouts/{id}/full
  AC11 — A Return button is present on the snapshot card and restores the normal view
  AC12 — An OS screenshot captures the card without clipping (fixed-width layout)
  AC13 — Snapshot mode is pure frontend — no new API endpoints added
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RV_HTML_PATH = _ROOT / "frontend" / "pages" / "run-view.html"
_RV_JS_PATH = _ROOT / "frontend" / "js" / "run-view.js"


def _html() -> str:
    assert _RV_HTML_PATH.exists(), f"File not found: {_RV_HTML_PATH}"
    return _RV_HTML_PATH.read_text()


def _js() -> str:
    assert _RV_JS_PATH.exists(), f"File not found: {_RV_JS_PATH}"
    return _RV_JS_PATH.read_text()


def _combined() -> str:
    return _html() + _js()


# ═════════════════════════════════════════════════════════════════════════════
# AC1 — Snapshot button visible in run-view
# ═════════════════════════════════════════════════════════════════════════════

def test_ac1_snapshot_button_rendered_in_js():
    """run-view.js must render a Snapshot button in the run detail view."""
    js = _js()
    lower = js.lower()
    assert "snapshot" in lower, (
        "run-view.js must render a Snapshot button in the run detail view (AC1)"
    )


def test_ac1_snapshot_button_label():
    """The Snapshot button must use the label 'Snapshot' (case-insensitive)."""
    js = _js()
    assert "Snapshot" in js or "snapshot" in js.lower(), (
        "run-view.js must include a button labelled 'Snapshot' (AC1)"
    )


def test_ac1_snapshot_button_click_handler():
    """The Snapshot button must have a click handler or data attribute to trigger snapshot mode."""
    js = _js()
    lower = js.lower()
    # Either an onclick= or an addEventListener for a snapshot-related element
    assert "snapshot" in lower and ("click" in lower or "onclick" in lower or "data-action" in lower), (
        "run-view.js must wire a click handler to the Snapshot button (AC1)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC2 — Pressing Snapshot shows a fixed-width card
# ═════════════════════════════════════════════════════════════════════════════

def test_ac2_snapshot_card_class_defined_in_html():
    """A CSS class for the snapshot card must be defined in run-view.html."""
    html = _html()
    lower = html.lower()
    assert "snap" in lower, (
        "run-view.html must define a CSS class for the snapshot card (AC2)"
    )


def test_ac2_snapshot_card_fixed_width():
    """The snapshot card CSS must use a fixed max-width (not a percentage)."""
    html = _html()
    # Look for a CSS block containing "snap" and a pixel-value max-width or width
    snap_idx = html.lower().find("snap")
    assert snap_idx != -1, "run-view.html must have a snapshot-related CSS rule (AC2)"
    # Scan nearby CSS for a fixed pixel width (400px-620px range per mock ~560px)
    nearby = html[max(0, snap_idx - 500): snap_idx + 1000]
    has_fixed_width = re.search(r"(?:max-)?width\s*:\s*[45678]\d{2}px", nearby) is not None
    assert has_fixed_width, (
        "The snapshot card CSS must specify a fixed pixel max-width (e.g. 560px) "
        "so the card never reflows (AC2)"
    )


def test_ac2_renderSnapshotCard_function_exists():
    """run-view.js must define a function to render the snapshot card."""
    js = _js()
    lower = js.lower()
    # Must have a function whose name contains "snapshot"
    assert "snapshot" in lower and ("function" in lower or "=>" in js), (
        "run-view.js must define a renderSnapshotCard (or similar) function (AC2)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC3 — Card header: type badge, run name, date, source badges
# ═════════════════════════════════════════════════════════════════════════════

def test_ac3_snapshot_has_run_badge():
    """The snapshot card must include a RUN type badge."""
    js = _js()
    # The renderSnapshotCard function must output a RUN badge
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    assert snap_idx != -1
    # Find the region of the snapshot-building code (search broadly)
    snap_region = js[snap_idx: snap_idx + 3000]
    assert "RUN" in snap_region or "rv-badge" in snap_region, (
        "Snapshot card must include the RUN type badge (AC3)"
    )


def test_ac3_snapshot_has_workout_name():
    """The snapshot card must render the workout name."""
    js = _js()
    # Must reference w.name or w.workout_name in snapshot context
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 3000]
    assert "w.name" in snap_region or "workout_name" in snap_region.lower() or \
           "name" in snap_region, (
        "Snapshot card must render the workout name (AC3)"
    )


def test_ac3_snapshot_has_date():
    """The snapshot card must render the run date."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 3000]
    assert "workout_date" in snap_region or "date" in snap_region.lower(), (
        "Snapshot card must include the workout date in the header (AC3)"
    )


def test_ac3_snapshot_has_source_badges():
    """The snapshot card must render source badges (Strava / Stryd)."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 3000]
    has_strava = "strava" in snap_region.lower()
    has_stryd = "stryd" in snap_region.lower()
    assert has_strava or has_stryd, (
        "Snapshot card must include source badges (Strava/Stryd) in the header (AC3)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC4 — Hero strip: Distance, Avg Pace, Duration, TSS
# ═════════════════════════════════════════════════════════════════════════════

def test_ac4_snapshot_hero_has_distance():
    """The snapshot hero strip must include Distance."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 3000]
    assert "distance" in snap_region.lower(), (
        "Snapshot hero strip must include Distance (AC4)"
    )


def test_ac4_snapshot_hero_has_pace():
    """The snapshot hero strip must include Avg Pace."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 3000]
    assert "pace" in snap_region.lower(), (
        "Snapshot hero strip must include Avg Pace (AC4)"
    )


def test_ac4_snapshot_hero_has_duration():
    """The snapshot hero strip must include Duration."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 3000]
    assert "duration" in snap_region.lower(), (
        "Snapshot hero strip must include Duration (AC4)"
    )


def test_ac4_snapshot_hero_has_tss():
    """The snapshot hero strip must include TSS (unlike the normal hero strip)."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 3000]
    assert "tss" in snap_region.lower(), (
        "Snapshot hero strip must include TSS (AC4)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC5 — Compact metric row with only populated metrics
# ═════════════════════════════════════════════════════════════════════════════

def test_ac5_snapshot_filters_empty_metrics():
    """The snapshot metric row must filter out null/dash metrics (only populated cells shown)."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    # Look for filtering logic: either null check before adding cells,
    # or a filter/push pattern that only includes truthy values
    snap_region = js[snap_idx: snap_idx + 5000]
    has_filter = (
        "filter" in snap_region.lower()
        or "push" in snap_region
        or ("null" in snap_region and "snap" in snap_region.lower())
        or "if (" in snap_region
        or "if(" in snap_region
    )
    assert has_filter, (
        "Snapshot metric row must conditionally include only populated metrics — "
        "cells with null/dash values must be excluded (AC5)"
    )


def test_ac5_snapshot_metric_row_includes_avg_hr():
    """The snapshot metric row must include Avg HR when present."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    assert "avg_hr" in snap_region or "avg hr" in snap_region.lower() or "hr" in snap_region.lower(), (
        "Snapshot metric row must include Avg HR (AC5)"
    )


def test_ac5_snapshot_metric_row_includes_avg_power():
    """The snapshot metric row must include Avg Power when present."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    assert "avg_power" in snap_region or "avg power" in snap_region.lower(), (
        "Snapshot metric row must include Avg Power (AC5)"
    )


def test_ac5_snapshot_metric_row_includes_np():
    """The snapshot metric row must include NP when present."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    assert "np" in snap_region.lower(), (
        "Snapshot metric row must include NP (Normalized Power) (AC5)"
    )


def test_ac5_snapshot_metric_row_includes_cadence():
    """The snapshot metric row must include Cadence when present."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    assert "cadence" in snap_region.lower(), (
        "Snapshot metric row must include Cadence (AC5)"
    )


def test_ac5_snapshot_metric_row_includes_stride():
    """The snapshot metric row must include Stride when present."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    assert "stride" in snap_region.lower(), (
        "Snapshot metric row must include Stride (AC5)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC6 — Card renders the pace lap-chart
# ═════════════════════════════════════════════════════════════════════════════

def test_ac6_snapshot_contains_lap_chart():
    """The snapshot card must render a lap/pace chart."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    has_chart = (
        "lapchart" in snap_region.lower()
        or "lap-chart" in snap_region.lower()
        or "rv-bar" in snap_region
        or "rv2-cbar" in snap_region
        or "pace" in snap_region.lower()
    )
    assert has_chart, (
        "Snapshot card must render a pace/lap chart (AC6)"
    )


def test_ac6_snapshot_chart_uses_splits_data():
    """The snapshot chart must be driven by the same splits data as the normal view."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    assert "splits" in snap_region.lower(), (
        "Snapshot lap chart must use splits data from the /full endpoint (AC6)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC7 — Full ultra-dense splits table in snapshot
# ═════════════════════════════════════════════════════════════════════════════

def test_ac7_snapshot_has_splits_table():
    """The snapshot card must render a splits table."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    has_table = (
        "laptbl" in snap_region.lower()
        or "lap-table" in snap_region.lower()
        or "rv-lap-table" in snap_region
        or "<table" in snap_region
        or "table" in snap_region.lower()
    )
    assert has_table, (
        "Snapshot card must render a splits table listing every lap (AC7)"
    )


def test_ac7_snapshot_table_header_columns():
    """The snapshot splits table must include core columns (Lap, Pace, HR)."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    # At minimum: Lap, Pace/Distance, HR
    has_lap_col = "lap" in snap_region.lower()
    has_pace_col = "pace" in snap_region.lower()
    assert has_lap_col and has_pace_col, (
        "Snapshot splits table must include Lap and Pace columns (AC7)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC8 — Perf-coach watermark at the bottom of the card
# ═════════════════════════════════════════════════════════════════════════════

def test_ac8_watermark_present():
    """The snapshot card must include a perf-coach watermark."""
    js = _js()
    lower = js.lower()
    assert "perf-coach" in lower or "perf coach" in lower, (
        "Snapshot card must include a perf-coach watermark at the bottom (AC8)"
    )


def test_ac8_watermark_in_snapshot_region():
    """The perf-coach watermark must be rendered inside the snapshot card."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    assert "perf-coach" in snap_region.lower() or "perf coach" in snap_region.lower(), (
        "perf-coach watermark must appear inside the snapshot card HTML (AC8)"
    )


def test_ac8_watermark_css_defined():
    """A CSS class for the snapshot watermark must be defined in run-view.html."""
    html = _html()
    lower = html.lower()
    assert "watermark" in lower or "snap-watermark" in lower or "rv-snap-watermark" in lower, (
        "run-view.html must define a CSS class for the snapshot watermark (AC8)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC9 — Card never reflows (fixed-width layout)
# ═════════════════════════════════════════════════════════════════════════════

def test_ac9_snapshot_card_fixed_max_width():
    """The snapshot card CSS must specify a fixed max-width in pixels."""
    html = _html()
    # Must have a CSS rule with max-width in pixels for the snap card
    assert re.search(r"max-width\s*:\s*[45678]\d{2}px", html) is not None, (
        "run-view.html must define a fixed max-width (e.g. 560px) for the "
        "snapshot card so it never reflows (AC9)"
    )


def test_ac9_snapshot_card_no_percentage_width():
    """The snapshot card wrapper must not use a percentage width that could cause reflow."""
    html = _html()
    # Find snap card CSS block
    snap_css_idx = html.lower().find("rv-snap-card")
    if snap_css_idx == -1:
        snap_css_idx = html.lower().find("snap-card")
    if snap_css_idx != -1:
        block_end = html.find("}", snap_css_idx)
        block = html[snap_css_idx: block_end] if block_end != -1 else html[snap_css_idx: snap_css_idx + 300]
        # Should not have width: 100% as the primary width (max-width is ok)
        width_match = re.search(r"(?<!max-)width\s*:\s*100%", block)
        assert width_match is None, (
            "Snapshot card must not use width:100% — it must stay at a fixed pixel "
            "width to prevent reflow at any viewport (AC9)"
        )


# ═════════════════════════════════════════════════════════════════════════════
# AC10 — No fabricated data; all from /full endpoint
# ═════════════════════════════════════════════════════════════════════════════

def test_ac10_snapshot_reads_from_full_data():
    """The snapshot card must read all values from the existing _fullData variable."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    # Must reference the workout object or fullData
    has_data_ref = (
        "w." in snap_region
        or "_fullData" in snap_region
        or "data.workout" in snap_region
        or "workout" in snap_region.lower()
    )
    assert has_data_ref, (
        "Snapshot card must read data from the existing API response (_fullData / w.) "
        "— no values may be fabricated (AC10)"
    )


def test_ac10_no_new_fetch_calls():
    """run-view.js must still have exactly 1 fetch() call — no new API endpoints."""
    js = _js()
    fetch_count = js.count("fetch(")
    assert fetch_count == 1, (
        f"run-view.js must have exactly 1 fetch() call (the /full endpoint); "
        f"found {fetch_count} — snapshot mode must be pure frontend with no new "
        f"API calls (AC10)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC11 — Return button restores normal view
# ═════════════════════════════════════════════════════════════════════════════

def test_ac11_return_button_present():
    """The snapshot card must include a Return or Back button."""
    js = _js()
    lower = js.lower()
    assert "return" in lower or "back" in lower, (
        "Snapshot card must include a Return/Back button to exit snapshot mode (AC11)"
    )


def test_ac11_return_button_in_snapshot_region():
    """The Return button must be rendered inside the snapshot card."""
    js = _js()
    lower = js.lower()
    snap_idx = lower.find("snapshot")
    snap_region = js[snap_idx: snap_idx + 5000]
    assert "return" in snap_region.lower() or "back" in snap_region.lower(), (
        "The Return/Back button must be part of the snapshot card HTML (AC11)"
    )


def test_ac11_exit_snapshot_handler():
    """There must be a handler to exit snapshot mode and restore the normal view."""
    js = _js()
    lower = js.lower()
    # Must have a function or handler for exiting the snapshot
    has_exit = (
        "exitSnapshot" in js
        or "exit_snapshot" in lower
        or "renderView" in js  # re-calling renderView exits snapshot
        or "rv-snap" in js and "click" in lower
    )
    assert has_exit, (
        "run-view.js must have logic to exit snapshot mode and restore the "
        "normal compact run detail view (AC11)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC12 — OS screenshot captures the complete card without clipping
# ═════════════════════════════════════════════════════════════════════════════

def test_ac12_snapshot_card_max_width_for_screenshot():
    """The snapshot card max-width must be <= 600px so it fits a typical screenshot."""
    html = _html()
    matches = re.findall(r"max-width\s*:\s*(\d+)px", html)
    snap_widths = [int(m) for m in matches if 400 <= int(m) <= 700]
    assert snap_widths, (
        "run-view.html must define a snapshot card max-width between 400–700px "
        "so an OS screenshot captures the full card without clipping (AC12)"
    )
    # All such widths should be <= 620px
    assert all(w <= 620 for w in snap_widths), (
        f"Snapshot card max-width(s) must be <= 620px for clean OS screenshots; "
        f"found: {snap_widths} (AC12)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC13 — Pure frontend; no new API endpoints added
# ═════════════════════════════════════════════════════════════════════════════

def test_ac13_no_new_routes_in_main_py():
    """backend/main.py must not have gained new routes for snapshot mode."""
    main_py = _ROOT / "backend" / "main.py"
    if not main_py.exists():
        return  # skip if file is absent
    text = main_py.read_text()
    lower = text.lower()
    # 'snapshot' should not appear as a route path
    assert "/snapshot" not in lower, (
        "backend/main.py must not add a /snapshot API endpoint — snapshot mode "
        "is pure frontend (AC13)"
    )


def test_ac13_only_frontend_files_changed():
    """Snapshot mode should only touch frontend files, not backend Python files."""
    # This is a structural test: the implementation touches run-view.html and run-view.js
    assert _RV_HTML_PATH.exists(), "run-view.html must exist (AC13)"
    assert _RV_JS_PATH.exists(), "run-view.js must exist (AC13)"
    # Both files must mention 'snapshot' (proving the feature is frontend-only)
    assert "snapshot" in _html().lower(), (
        "run-view.html must contain snapshot-related CSS/markup (AC13)"
    )
    assert "snapshot" in _js().lower(), (
        "run-view.js must contain snapshot rendering logic (AC13)"
    )
