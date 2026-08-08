"""Tests for issue #415: Final polish — weight tracking docs, links, empty states.

AC anchors verified:
  (ac1)  docs/mockups/weight-tracking-desktop.html exists
  (ac2)  docs/mockups/weight-tracking-mobile.html exists
  (ac3)  docs/mockups/weight-target-management-desktop.html exists
  (ac4)  docs/mockups/README.md contains weight tracking entry with live page paths
  (ac5)  docs/features/weight-tracking.md exists and covers all required topics:
           purpose, data model (weight_entries + weight_targets), all API endpoints,
           7-day moving average with worked example, status_label threshold logic,
           projection math, known limitations
  (ac6)  Home page weight widget navigates to /weight (not /weight.html)
  (ac7)  /weight with zero entries shows "No weight entries yet — log your first weigh-in above"
  (ac8)  /weight/targets with no target history shows graceful empty state (no crash)
  (ac9)  Active target card handles weight_target=null without crashing
  (ac10) Chart.js CDN slow/fail: "Loading chart..." placeholder visible; no blank area
  (ac11) Date picker / quick log rejects future dates more than 1 day ahead
  (ac12) CHANGELOG.md exists and contains an entry describing weight tracking feature
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MOCKUPS = DOCS / "mockups"
FEATURES = DOCS / "features"
PAGES_DIR = ROOT / "frontend" / "pages"
JS_DIR = ROOT / "frontend" / "js"
CHANGELOG = ROOT / "CHANGELOG.md"

WEIGHT_HTML = (PAGES_DIR / "weight.html").read_text()
WEIGHT_JS = (JS_DIR / "weight.js").read_text()
WT_HTML = (PAGES_DIR / "weight-targets.html").read_text() if (PAGES_DIR / "weight-targets.html").exists() else ""
WT_JS = (JS_DIR / "weight-targets.js").read_text() if (JS_DIR / "weight-targets.js").exists() else ""
HOME_JS = (JS_DIR / "home.js").read_text() if (JS_DIR / "home.js").exists() else ""
HOME_WEIGHT_TREND_JS = (
    (JS_DIR / "home-weight-trend.js").read_text()
    if (JS_DIR / "home-weight-trend.js").exists() else ""
)


# ── AC1: Mockup desktop file ───────────────────────────────────────────────────

def test_ac1_weight_tracking_desktop_mockup_exists():
    assert (MOCKUPS / "weight-tracking-desktop.html").exists(), \
        "docs/mockups/weight-tracking-desktop.html must exist"


# ── AC2: Mockup mobile file ────────────────────────────────────────────────────

def test_ac2_weight_tracking_mobile_mockup_exists():
    assert (MOCKUPS / "weight-tracking-mobile.html").exists(), \
        "docs/mockups/weight-tracking-mobile.html must exist"


# ── AC3: Mockup target management file ────────────────────────────────────────

def test_ac3_weight_target_management_mockup_exists():
    assert (MOCKUPS / "weight-target-management-desktop.html").exists(), \
        "docs/mockups/weight-target-management-desktop.html must exist"


# ── AC4: README.md entry ──────────────────────────────────────────────────────

def test_ac4_mockups_readme_has_weight_tracking_entry():
    readme = (MOCKUPS / "README.md").read_text()
    assert "Weight tracking" in readme, \
        "docs/mockups/README.md must contain a 'Weight tracking' entry"


def test_ac4_mockups_readme_references_all_three_files():
    readme = (MOCKUPS / "README.md").read_text()
    assert "weight-tracking-desktop.html" in readme, \
        "README.md must reference weight-tracking-desktop.html"
    assert "weight-tracking-mobile.html" in readme, \
        "README.md must reference weight-tracking-mobile.html"
    assert "weight-target-management-desktop.html" in readme, \
        "README.md must reference weight-target-management-desktop.html"


def test_ac4_mockups_readme_references_live_pages():
    readme = (MOCKUPS / "README.md").read_text()
    assert "/weight" in readme, \
        "README.md must reference live page at /weight"
    assert "/weight/targets" in readme, \
        "README.md must reference live page at /weight/targets"


# ── AC5: Feature doc ──────────────────────────────────────────────────────────

def test_ac5_weight_tracking_feature_doc_exists():
    assert (FEATURES / "weight-tracking.md").exists(), \
        "docs/features/weight-tracking.md must exist"


def test_ac5_feature_doc_covers_purpose():
    doc = (FEATURES / "weight-tracking.md").read_text()
    assert "Purpose" in doc or "purpose" in doc.lower(), \
        "feature doc must cover purpose"


def test_ac5_feature_doc_covers_data_model():
    doc = (FEATURES / "weight-tracking.md").read_text()
    assert "weight_entries" in doc, "feature doc must describe weight_entries table"
    assert "weight_targets" in doc, "feature doc must describe weight_targets table"


def test_ac5_feature_doc_covers_api_endpoints():
    doc = (FEATURES / "weight-tracking.md").read_text()
    for endpoint in [
        "/api/weight-entries",
        "/api/weight-targets",
        "/api/weight-chart",
        "/api/exports/weight",
    ]:
        assert endpoint in doc, f"feature doc must document endpoint {endpoint}"


def test_ac5_feature_doc_covers_7day_moving_average():
    doc = (FEATURES / "weight-tracking.md").read_text().lower()
    assert "7-day" in doc or "7 day" in doc or "moving average" in doc, \
        "feature doc must explain 7-day moving average"
    assert "example" in doc or "worked" in doc, \
        "feature doc must include a worked example for moving average"


def test_ac5_feature_doc_covers_status_label_thresholds():
    doc = (FEATURES / "weight-tracking.md").read_text()
    assert "status_label" in doc, "feature doc must explain status_label"
    assert "tolerance" in doc, "feature doc must explain tolerance threshold"
    assert "on_track" in doc or "on-track" in doc, "feature doc must document on_track status"


def test_ac5_feature_doc_covers_projection_math():
    doc = (FEATURES / "weight-tracking.md").read_text().lower()
    assert "projection" in doc or "projected" in doc, \
        "feature doc must explain projection math"
    assert "linear" in doc, "feature doc must mention linear projection"


def test_ac5_feature_doc_covers_known_limitations():
    doc = (FEATURES / "weight-tracking.md").read_text().lower()
    assert "known limitation" in doc or "limitation" in doc, \
        "feature doc must list known limitations"
    assert "single active target" in doc or "one active target" in doc, \
        "feature doc must mention single active target limitation"
    assert "unit" in doc and "kg" in doc, \
        "feature doc must mention no unit switching limitation"
    assert "samsung" in doc or "auto-import" in doc or "auto import" in doc, \
        "feature doc must mention no Samsung Health auto-import limitation"


# ── AC6: Home page widget links to /weight ────────────────────────────────────

def test_ac6_home_weight_widget_click_navigates_to_weight():
    assert "window.location.href = '/weight'" in HOME_JS or \
           'window.location.href="/weight"' in HOME_JS, \
        "home.js weight widget click must navigate to /weight"


def test_ac6_home_weight_widget_empty_state_links_to_weight():
    # Empty-state /weight link lives in home-weight-trend.js after the split.
    assert 'href="/weight"' in HOME_WEIGHT_TREND_JS or "href='/weight'" in HOME_WEIGHT_TREND_JS, \
        "home-weight-trend.js empty state must link to /weight (not /weight.html)"


def test_ac6_no_legacy_weight_html_link_in_home():
    assert 'href="/weight.html"' not in HOME_JS, \
        "home.js must not link to /weight.html (legacy URL)"


# ── AC7: /weight empty state ──────────────────────────────────────────────────

def test_ac7_weight_empty_state_message_in_js():
    assert "No weight entries yet" in WEIGHT_JS, \
        "weight.js must render 'No weight entries yet' empty state message"


def test_ac7_weight_empty_state_log_prompt():
    assert "log your first weigh-in above" in WEIGHT_JS or \
           "log your first weigh" in WEIGHT_JS.lower(), \
        "weight.js empty state must prompt user to log first weigh-in"


def test_ac7_weight_empty_state_shown_when_no_entries():
    assert "entries.length" in WEIGHT_JS or "!entries" in WEIGHT_JS, \
        "weight.js must check entries length to show empty state"


def test_ac7_weight_empty_state_no_nan_nan_in_title():
    assert "NaN" not in WEIGHT_HTML, \
        "weight.html must not contain literal NaN"


# ── AC8: /weight/targets empty state ─────────────────────────────────────────

def test_ac8_targets_history_empty_state_element():
    assert "history-empty" in WT_HTML, \
        "weight-targets.html must have history-empty element"


def test_ac8_targets_history_empty_state_text():
    assert "No completed targets" in WT_HTML or "no targets" in WT_HTML.lower() or \
           "no completed targets" in WT_HTML.lower(), \
        "weight-targets.html must show empty state text for no history"


def test_ac8_targets_history_empty_shown_by_js():
    assert "history-empty" in WT_JS, \
        "weight-targets.js must reference history-empty element to show/hide it"


def test_ac8_targets_page_handles_null_active_target():
    assert "_activeTarget" in WT_JS, \
        "weight-targets.js must use _activeTarget variable"
    assert "_activeTarget = data.target || null" in WT_JS or \
           "_activeTarget = null" in WT_JS, \
        "weight-targets.js must handle null active target gracefully"


# ── AC9: Active target card null handling ──────────────────────────────────────

def test_ac9_null_target_renders_form_instead():
    assert "renderNewTargetForm" in WT_JS, \
        "weight-targets.js must call renderNewTargetForm when _activeTarget is null"


def test_ac9_renderpage_checks_active_target():
    js = WT_JS
    assert "if (_activeTarget)" in js or "if(_activeTarget)" in js, \
        "weight-targets.js renderPage must guard active card rendering on null _activeTarget"


def test_ac9_no_unchecked_property_access_on_null_target():
    # Verify renderActiveCard is only called when _activeTarget is truthy
    idx_active = WT_JS.find("renderActiveCard")
    idx_check = WT_JS.rfind("if (_activeTarget)", 0, idx_active)
    assert idx_check != -1, \
        "renderActiveCard must only be called inside if(_activeTarget) guard"


# ── AC10: Chart.js loading placeholder ────────────────────────────────────────

def test_ac10_chart_loading_element_exists():
    assert 'id="chart-loading"' in WEIGHT_HTML, \
        "weight.html must have id=chart-loading element"


def test_ac10_chart_loading_text():
    assert "Loading chart" in WEIGHT_HTML, \
        "chart-loading element must contain 'Loading chart' text"


def test_ac10_canvas_starts_hidden():
    assert 'id="weight-chart"' in WEIGHT_HTML and "hidden" in WEIGHT_HTML, \
        "weight-chart canvas must start hidden"


def test_ac10_js_hides_loading_on_render():
    assert "chart-loading" in WEIGHT_JS and "hidden" in WEIGHT_JS, \
        "weight.js must hide chart-loading element when chart renders"


def test_ac10_js_reveals_canvas_on_render():
    assert "weight-chart" in WEIGHT_JS and "hidden = false" in WEIGHT_JS, \
        "weight.js must set weight-chart canvas hidden=false when chart renders"


# ── AC11: Date validation — future dates ──────────────────────────────────────

def test_ac11_backfill_rejects_future_dates():
    assert "addDays(todayISO(), 1)" in WEIGHT_JS or \
           "addDays(todayISO(),1)" in WEIGHT_JS, \
        "weight.js backfill must allow up to 1 day ahead"


def test_ac11_backfill_future_date_error_message():
    assert "future date" in WEIGHT_JS.lower() or \
           "Cannot log a weight entry for a future date" in WEIGHT_JS, \
        "weight.js must show error message when future date is rejected"


def test_ac11_backfill_future_date_check():
    assert "date > addDays" in WEIGHT_JS or "date > addDays" in WEIGHT_JS, \
        "weight.js must reject dates beyond addDays(todayISO(), 1)"


def test_ac11_quicklog_always_uses_today():
    assert "todayISO()" in WEIGHT_JS, \
        "weight.js quicklog must use todayISO() for entry_date"


# ── AC12: CHANGELOG has weight tracking entry ─────────────────────────────────

def test_ac12_changelog_exists():
    assert CHANGELOG.exists(), "CHANGELOG.md must exist at repo root"


def test_ac12_changelog_has_weight_tracking():
    text = CHANGELOG.read_text().lower()
    assert "weight" in text, \
        "CHANGELOG.md must contain an entry mentioning weight tracking"


def test_ac12_changelog_sprint_51_entry():
    text = CHANGELOG.read_text()
    assert "sprint 51" in text.lower() or "Sprint 51" in text, \
        "CHANGELOG.md must have a Sprint 51 section"


def test_ac12_changelog_issue_415():
    text = CHANGELOG.read_text()
    assert "#415" in text, \
        "CHANGELOG.md must reference issue #415"


# ── AC13: End-to-end fresh user usability ─────────────────────────────────────

def test_ac13_weight_route_registered():
    main_py = (ROOT / "backend" / "main.py").read_text()
    # Route is registered via _PAGES dict loop: "weight": "weight.html"
    assert '"weight"' in main_py and "weight.html" in main_py, \
        "main.py must register the /weight route (via _PAGES dict)"


def test_ac13_weight_targets_route_removed():
    # AC #461 consolidated the standalone page into weight.html's slide-in
    # panel and left /weight/targets as a redirect shim; a later cleanup
    # deleted the route outright (zero callers — see #1602's reachability
    # gate), so main.py must no longer register it at all.
    main_py = (ROOT / "backend" / "main.py").read_text()
    assert '"/weight/targets"' not in main_py and "'/weight/targets'" not in main_py, \
        "main.py must not register the /weight/targets route — it was deleted"


def test_ac13_weight_page_title():
    assert "<title>Weight" in WEIGHT_HTML, \
        "weight.html must have Weight page title"


def test_ac13_weight_targets_page_title():
    assert "Weight targets" in WT_HTML or "weight targets" in WT_HTML.lower(), \
        "weight-targets.html must have Weight targets page title"


def test_ac13_weight_page_has_no_undefined_in_html():
    assert "undefined" not in WEIGHT_HTML, \
        "weight.html must not contain literal 'undefined'"


def test_ac13_weight_exports_not_using_legacy_api():
    # Export buttons must use /api/exports/* not the old legacy weight endpoints
    assert "/api/exports/weight" in WEIGHT_HTML or "/api/exports/weight" in WEIGHT_JS, \
        "weight page must reference /api/exports/weight* export endpoints"
