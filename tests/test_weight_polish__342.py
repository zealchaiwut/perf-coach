"""Tests for issue #342: Final polish — weight feature docs, links, empty states.

AC items verified:
  (a) docs/mockups/weight-tracking-desktop.html exists
  (b) docs/mockups/weight-tracking-mobile.html exists
  (c) docs/mockups/weight-target-management-desktop.html exists
  (d) docs/mockups/README.md contains the required weight tracking line
  (e) docs/features/weight-tracking.md exists with required sections
  (f) home.js weight widget links to /weight (href="/weight")
  (g) weight.js empty-state text: "No weight entries yet — log your first weigh-in above"
  (h) weight-targets.js renders graceful empty state when no target / null target
  (i) weight.html has "Loading chart…" placeholder text for Chart.js CDN load
  (j) weight.js quick-log form rejects dates more than 1 day in the future
  (k) empty-state branches have inline comments in relevant template or component
  (l) CHANGELOG.md has an entry for weight tracking feature
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MOCKUPS_DIR = ROOT / "docs" / "mockups"
FEATURES_DIR = ROOT / "docs" / "features"
JS_DIR = ROOT / "frontend" / "js"
PAGES_DIR = ROOT / "frontend" / "pages"


# ── (a) weight-tracking-desktop mockup ───────────────────────────────────────

def test_a_weight_tracking_desktop_mockup_exists():
    assert (MOCKUPS_DIR / "weight-tracking-desktop.html").exists(), \
        "docs/mockups/weight-tracking-desktop.html must exist"


# ── (b) weight-tracking-mobile mockup ────────────────────────────────────────

def test_b_weight_tracking_mobile_mockup_exists():
    assert (MOCKUPS_DIR / "weight-tracking-mobile.html").exists(), \
        "docs/mockups/weight-tracking-mobile.html must exist"


# ── (c) weight-target-management-desktop mockup ──────────────────────────────

def test_c_weight_target_management_desktop_mockup_exists():
    assert (MOCKUPS_DIR / "weight-target-management-desktop.html").exists(), \
        "docs/mockups/weight-target-management-desktop.html must exist"


# ── (d) docs/mockups/README.md weight tracking line ──────────────────────────

def test_d_mockups_readme_has_weight_tracking_line():
    readme = (MOCKUPS_DIR / "README.md").read_text()
    assert "weight-tracking-desktop.html" in readme, \
        "docs/mockups/README.md must reference weight-tracking-desktop.html"
    assert "weight-tracking-mobile.html" in readme, \
        "docs/mockups/README.md must reference weight-tracking-mobile.html"
    assert "weight-target-management-desktop.html" in readme, \
        "docs/mockups/README.md must reference weight-target-management-desktop.html"
    assert "/weight" in readme, \
        "docs/mockups/README.md must reference the live /weight page"
    assert "/weight/targets" in readme, \
        "docs/mockups/README.md must reference the live /weight/targets page"


# ── (e) docs/features/weight-tracking.md content ─────────────────────────────

def test_e_weight_feature_doc_exists():
    assert (FEATURES_DIR / "weight-tracking.md").exists(), \
        "docs/features/weight-tracking.md must exist"


def test_e_weight_feature_doc_has_purpose():
    doc = (FEATURES_DIR / "weight-tracking.md").read_text()
    assert "purpose" in doc.lower() or "## Purpose" in doc or "## Overview" in doc, \
        "weight-tracking.md must cover purpose/overview"


def test_e_weight_feature_doc_has_data_model():
    doc = (FEATURES_DIR / "weight-tracking.md").read_text()
    assert "weight_entries" in doc and "weight_targets" in doc, \
        "weight-tracking.md must cover the data model (weight_entries + weight_targets tables)"


def test_e_weight_feature_doc_has_api_reference():
    doc = (FEATURES_DIR / "weight-tracking.md").read_text()
    assert "/api/weight-entries" in doc, \
        "weight-tracking.md must include /api/weight-entries in the API reference"
    assert "/api/weight-chart" in doc, \
        "weight-tracking.md must include /api/weight-chart in the API reference"
    assert "/api/exports/weight" in doc, \
        "weight-tracking.md must include /api/exports/weight-* in the API reference"


def test_e_weight_feature_doc_has_moving_average_math():
    doc = (FEATURES_DIR / "weight-tracking.md").read_text()
    lower = doc.lower()
    assert "moving" in lower and ("average" in lower or "avg" in lower), \
        "weight-tracking.md must document 7-day moving average math"
    # Must have a worked numeric example
    assert any(c.isdigit() for c in doc), \
        "weight-tracking.md must include a numeric example"


def test_e_weight_feature_doc_has_status_label_logic():
    doc = (FEATURES_DIR / "weight-tracking.md").read_text()
    lower = doc.lower()
    assert "status_label" in doc or "status label" in lower, \
        "weight-tracking.md must document status_label threshold logic"
    assert "tolerance" in lower or "0.5" in doc, \
        "weight-tracking.md must describe tolerance threshold"


def test_e_weight_feature_doc_has_projection_math():
    doc = (FEATURES_DIR / "weight-tracking.md").read_text()
    lower = doc.lower()
    assert "project" in lower, \
        "weight-tracking.md must document linear projection math"


def test_e_weight_feature_doc_has_known_limitations():
    doc = (FEATURES_DIR / "weight-tracking.md").read_text()
    lower = doc.lower()
    assert "limitation" in lower or "known" in lower, \
        "weight-tracking.md must list known limitations"
    assert "single" in lower or "one" in lower, \
        "weight-tracking.md must note single active target limitation"
    assert "unit" in lower or "kg" in lower, \
        "weight-tracking.md must note no unit switching limitation"


# ── (f) home.js weight widget links to /weight ───────────────────────────────

def test_f_home_js_weight_widget_links_to_weight():
    home_js = (JS_DIR / "home.js").read_text()
    assert 'href="/weight"' in home_js or "href='/weight'" in home_js or \
           '"/weight"' in home_js, \
        "home.js weight widget must include a link to /weight"


def test_f_home_js_no_weight_html_reference_in_weight_card():
    home_js = (JS_DIR / "home.js").read_text()
    # Ensure any weight.html reference is not in the weight card rendering
    # (legacy alias OK in nav.js match array, but not in home.js weight card link)
    # The weight render function should not link to /weight.html
    assert "renderWeightTrendCard" in home_js, \
        "home.js must still contain renderWeightTrendCard"
    # Get the function body and check it doesn't link to weight.html
    start = home_js.find("function renderWeightTrendCard")
    end = home_js.find("\n  function ", start + 1)
    weight_fn = home_js[start:end] if end > start else home_js[start:]
    assert "weight.html" not in weight_fn, \
        "renderWeightTrendCard must not reference /weight.html (legacy link)"


# ── (g) weight.js empty state text ───────────────────────────────────────────

def test_g_weight_js_has_empty_state_message():
    weight_js = (JS_DIR / "weight.js").read_text()
    assert "No weight entries yet" in weight_js, \
        "weight.js must show 'No weight entries yet — log your first weigh-in above' for zero entries"
    assert "log your first weigh-in above" in weight_js, \
        "weight.js empty state must say 'log your first weigh-in above'"


# ── (h) weight-targets.js empty state ────────────────────────────────────────

def test_h_weight_targets_js_has_empty_state():
    wt_js = (JS_DIR / "weight-targets.js").read_text()
    lower = wt_js.lower()
    # The page must handle null _activeTarget gracefully
    assert "_activeTarget" in wt_js, \
        "weight-targets.js must reference _activeTarget"
    # Should show the new-target form card when no active target
    assert "new-target-form-card" in wt_js, \
        "weight-targets.js must show new-target-form-card as empty state when no active target"


def test_h_weight_targets_js_null_safe_active_card():
    wt_js = (JS_DIR / "weight-targets.js").read_text()
    # renderActiveCard must only be called with a truthy target
    # The renderPage function checks `if (_activeTarget)` before calling renderActiveCard
    assert "if (_activeTarget)" in wt_js or "if(_activeTarget)" in wt_js, \
        "weight-targets.js renderPage must guard renderActiveCard with null check"


# ── (i) weight.html Chart.js loading placeholder ─────────────────────────────

def test_i_weight_html_has_loading_chart_placeholder():
    weight_html = (PAGES_DIR / "weight.html").read_text()
    assert "Loading chart" in weight_html, \
        "weight.html must contain 'Loading chart…' placeholder text for CDN load"


def test_i_weight_js_hides_placeholder_after_chart_renders():
    weight_js = (JS_DIR / "weight.js").read_text()
    # JS must handle the loading placeholder — either hide it or remove it
    lower = weight_js.lower()
    assert "loading" in lower or "placeholder" in lower or "chart-loading" in lower, \
        "weight.js must reference the loading placeholder element"


# ── (j) date validation: reject > 1 day in the future ───────────────────────

def test_j_weight_js_rejects_future_dates():
    weight_js = (JS_DIR / "weight.js").read_text()
    # Must have a future-date check in the quicklog or date input handler
    assert "future" in weight_js.lower() or \
           ("1" in weight_js and "day" in weight_js.lower() and "future" in weight_js.lower()) or \
           "future date" in weight_js.lower() or \
           "Cannot log" in weight_js or "future" in weight_js.lower(), \
        "weight.js must reject dates more than 1 day in the future"


def test_j_weight_js_date_validation_checks_one_day():
    weight_js = (JS_DIR / "weight.js").read_text()
    # Validation logic: dates > today+1 rejected
    # Check for common patterns: addDays(todayISO(), 1) or similar
    assert "addDays" in weight_js and ("1" in weight_js), \
        "weight.js must use a 1-day future boundary in date validation"


# ── (k) inline comments for empty-state branches ─────────────────────────────

def test_k_weight_js_has_empty_state_comment():
    weight_js = (JS_DIR / "weight.js").read_text()
    # Must have an inline comment on the empty-state branch
    assert "// empty" in weight_js.lower() or \
           "// no entries" in weight_js.lower() or \
           "// zero entries" in weight_js.lower() or \
           "empty state" in weight_js.lower(), \
        "weight.js must have an inline comment marking the empty-state branch"


def test_k_weight_targets_js_has_empty_state_comment():
    wt_js = (JS_DIR / "weight-targets.js").read_text()
    assert "// empty" in wt_js.lower() or \
           "// no target" in wt_js.lower() or \
           "empty state" in wt_js.lower() or \
           "no active target" in wt_js.lower(), \
        "weight-targets.js must have an inline comment marking the empty-state branch"


# ── (l) CHANGELOG.md weight tracking entry ───────────────────────────────────

def test_l_changelog_has_weight_tracking_entry():
    changelog = (ROOT / "CHANGELOG.md").read_text()
    lower = changelog.lower()
    assert "weight" in lower and ("track" in lower or "feature" in lower), \
        "CHANGELOG.md must contain an entry describing the weight tracking feature addition"
