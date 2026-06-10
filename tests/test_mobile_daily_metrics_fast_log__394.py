"""
Tests for issue #394: Mobile-optimize daily metrics fast-log flow
Static file checks (HTML source + JS source) unless noted otherwise.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).parent.parent
HTML = ROOT / "frontend" / "pages" / "home.html"
JS   = ROOT / "frontend" / "js"  / "home.js"


@pytest.fixture(scope="module")
def html():
    return HTML.read_text()


@pytest.fixture(scope="module")
def js():
    return JS.read_text()


# ── AC1: single-column, large-tap-target mobile form ─────────────────────────

def test_ac1_fast_log_section_exists(html):
    """home.html must have a fast-log section (id='fast-log-section')."""
    assert 'id="fast-log-section"' in html, \
        "Missing id='fast-log-section' in home.html"


def test_ac1_single_column_flex_column_css(html):
    """CSS must use flex-direction:column for single-column layout."""
    assert "flex-direction: column" in html or "flex-direction:column" in html, \
        "CSS must declare flex-direction:column for single-column form layout"


def test_ac1_min_height_tap_target_css(html):
    """CSS must set min-height on interactive elements for large tap targets."""
    assert "min-height" in html, \
        "CSS must define min-height for large tap targets"


def test_ac1_media_query_for_mobile(html):
    """home.html CSS must include @media queries for mobile layout."""
    assert "@media" in html, \
        "home.html must have @media queries for responsive/mobile layout"


# ── AC2: exact field order ────────────────────────────────────────────────────

def test_ac2_rhr_input_exists(html):
    """home.html must have an RHR input (id='fm-rhr')."""
    assert 'id="fm-rhr"' in html, "Missing id='fm-rhr' in home.html"


def test_ac2_hrv_input_exists(html):
    """home.html must have an HRV input (id='fm-hrv')."""
    assert 'id="fm-hrv"' in html, "Missing id='fm-hrv' in home.html"


def test_ac2_sleep_input_exists(html):
    """home.html must have a sleep_hours input (id='fm-sleep')."""
    assert 'id="fm-sleep"' in html, "Missing id='fm-sleep' in home.html"


def test_ac2_energy_pills_exist(html):
    """home.html must have an energy pill group (id='fm-energy-pills')."""
    assert 'id="fm-energy-pills"' in html, "Missing id='fm-energy-pills' in home.html"


def test_ac2_mood_pills_exist(html):
    """home.html must have a mood pill group (id='fm-mood-pills')."""
    assert 'id="fm-mood-pills"' in html, "Missing id='fm-mood-pills' in home.html"


def test_ac2_weight_input_exists(html):
    """home.html must have an optional weight_kg input (id='fm-weight')."""
    assert 'id="fm-weight"' in html, "Missing id='fm-weight' in home.html"


def test_ac2_notes_textarea_exists(html):
    """home.html must have an optional notes textarea (id='fm-notes')."""
    assert 'id="fm-notes"' in html, "Missing id='fm-notes' in home.html"


def test_ac2_field_order_rhr_before_hrv(html):
    """RHR field must appear before HRV field in HTML source."""
    assert html.find('id="fm-rhr"') < html.find('id="fm-hrv"'), \
        "fm-rhr must appear before fm-hrv in the form"


def test_ac2_field_order_hrv_before_sleep(html):
    """HRV field must appear before sleep_hours field."""
    assert html.find('id="fm-hrv"') < html.find('id="fm-sleep"'), \
        "fm-hrv must appear before fm-sleep in the form"


def test_ac2_field_order_sleep_before_energy(html):
    """sleep_hours field must appear before energy pills."""
    assert html.find('id="fm-sleep"') < html.find('id="fm-energy-pills"'), \
        "fm-sleep must appear before fm-energy-pills in the form"


def test_ac2_field_order_energy_before_mood(html):
    """energy pills must appear before mood pills."""
    assert html.find('id="fm-energy-pills"') < html.find('id="fm-mood-pills"'), \
        "fm-energy-pills must appear before fm-mood-pills in the form"


def test_ac2_field_order_mood_before_weight(html):
    """mood pills must appear before weight_kg field."""
    assert html.find('id="fm-mood-pills"') < html.find('id="fm-weight"'), \
        "fm-mood-pills must appear before fm-weight in the form"


def test_ac2_field_order_weight_before_notes(html):
    """weight_kg field must appear before notes textarea."""
    assert html.find('id="fm-weight"') < html.find('id="fm-notes"'), \
        "fm-weight must appear before fm-notes in the form"


# ── AC3: stepper buttons + bounds ─────────────────────────────────────────────

def test_ac3_rhr_minus_button(html):
    """home.html must have a minus stepper button for RHR (id='fm-rhr-minus')."""
    assert 'id="fm-rhr-minus"' in html, "Missing id='fm-rhr-minus'"


def test_ac3_rhr_plus_button(html):
    """home.html must have a plus stepper button for RHR (id='fm-rhr-plus')."""
    assert 'id="fm-rhr-plus"' in html, "Missing id='fm-rhr-plus'"


def test_ac3_hrv_minus_button(html):
    """home.html must have a minus stepper button for HRV (id='fm-hrv-minus')."""
    assert 'id="fm-hrv-minus"' in html, "Missing id='fm-hrv-minus'"


def test_ac3_hrv_plus_button(html):
    """home.html must have a plus stepper button for HRV (id='fm-hrv-plus')."""
    assert 'id="fm-hrv-plus"' in html, "Missing id='fm-hrv-plus'"


def test_ac3_sleep_minus_button(html):
    """home.html must have a minus stepper button for sleep (id='fm-sleep-minus')."""
    assert 'id="fm-sleep-minus"' in html, "Missing id='fm-sleep-minus'"


def test_ac3_sleep_plus_button(html):
    """home.html must have a plus stepper button for sleep (id='fm-sleep-plus')."""
    assert 'id="fm-sleep-plus"' in html, "Missing id='fm-sleep-plus'"


def test_ac3_weight_minus_button(html):
    """home.html must have a minus stepper button for weight (id='fm-weight-minus')."""
    assert 'id="fm-weight-minus"' in html, "Missing id='fm-weight-minus'"


def test_ac3_weight_plus_button(html):
    """home.html must have a plus stepper button for weight (id='fm-weight-plus')."""
    assert 'id="fm-weight-plus"' in html, "Missing id='fm-weight-plus'"


def test_ac3_rhr_bounds_min30_max120(html):
    """fm-rhr input must have min='30' and max='120'."""
    idx = html.find('id="fm-rhr"')
    assert idx != -1
    snippet = html[max(0, idx - 150):idx + 300]
    assert 'min="30"' in snippet, "fm-rhr must have min='30'"
    assert 'max="120"' in snippet, "fm-rhr must have max='120'"


def test_ac3_hrv_bounds_min0_max200(html):
    """fm-hrv input must have min='0' and max='200'."""
    idx = html.find('id="fm-hrv"')
    assert idx != -1
    snippet = html[max(0, idx - 150):idx + 300]
    assert 'min="0"' in snippet, "fm-hrv must have min='0'"
    assert 'max="200"' in snippet, "fm-hrv must have max='200'"


def test_ac3_sleep_bounds_min0_max12(html):
    """fm-sleep input must have min='0' and max='12'."""
    idx = html.find('id="fm-sleep"')
    assert idx != -1
    snippet = html[max(0, idx - 150):idx + 300]
    assert 'min="0"' in snippet, "fm-sleep must have min='0'"
    assert 'max="12"' in snippet, "fm-sleep must have max='12'"


def test_ac3_sleep_step_half(html):
    """fm-sleep input must allow 0.5 decimal increments (step='0.5')."""
    idx = html.find('id="fm-sleep"')
    assert idx != -1
    snippet = html[max(0, idx - 150):idx + 300]
    assert 'step="0.5"' in snippet, "fm-sleep must have step='0.5'"


def test_ac3_weight_bounds_min30_max200(html):
    """fm-weight input must have min='30' and max='200'."""
    idx = html.find('id="fm-weight"')
    assert idx != -1
    snippet = html[max(0, idx - 150):idx + 300]
    assert 'min="30"' in snippet, "fm-weight must have min='30'"
    assert 'max="200"' in snippet, "fm-weight must have max='200'"


def test_ac3_stepper_js_clamps_to_bounds(js):
    """JS must clamp stepper values to min/max bounds (Math.min/Math.max)."""
    assert "Math.min" in js and "Math.max" in js, \
        "JS stepper must use Math.min/Math.max to clamp to bounds"


def test_ac3_stepper_js_wired(js):
    """JS must wire click handlers for stepper buttons."""
    assert "fm-rhr-plus" in js or "fm-hrv-plus" in js, \
        "JS must attach click handlers to stepper buttons"


def test_ac3_sleep_step_0_5_in_js(js):
    """JS stepper must use 0.5 increment for sleep_hours."""
    assert "0.5" in js, "JS must use 0.5 step for sleep_hours stepper"


# ── AC4: segmented pills for energy and mood ──────────────────────────────────

def test_ac4_energy_pills_1_to_5(html):
    """energy pill group must contain buttons data-val='1' through data-val='5'."""
    idx = html.find('id="fm-energy-pills"')
    assert idx != -1
    snippet = html[idx:idx + 600]
    for v in range(1, 6):
        assert f'data-val="{v}"' in snippet, \
            f"fm-energy-pills must contain a button with data-val='{v}'"


def test_ac4_mood_pills_1_to_5(html):
    """mood pill group must contain buttons data-val='1' through data-val='5'."""
    idx = html.find('id="fm-mood-pills"')
    assert idx != -1
    snippet = html[idx:idx + 600]
    for v in range(1, 6):
        assert f'data-val="{v}"' in snippet, \
            f"fm-mood-pills must contain a button with data-val='{v}'"


def test_ac4_pill_class_on_buttons(html):
    """Pill buttons must use the 'fm-pill' CSS class."""
    assert 'class="fm-pill"' in html, \
        "Pill buttons must have class='fm-pill'"


def test_ac4_pill_active_toggle_in_js(js):
    """JS must toggle 'active' class on selected pill and deselect siblings."""
    assert "active" in js, "JS must use 'active' class for selected pill state"
    assert "fm-energy-pills" in js and "fm-mood-pills" in js, \
        "JS must wire up both energy and mood pill groups"


def test_ac4_pill_immediate_select_in_js(js):
    """JS must select pill immediately on click (no confirm step)."""
    assert "fm-energy-pills" in js, \
        "JS must attach click handler to fm-energy-pills for immediate selection"


# ── AC5: inline Save button visible at bottom ─────────────────────────────────

def test_ac5_save_button_exists(html):
    """home.html must have a save button (id='fm-save')."""
    assert 'id="fm-save"' in html, "Missing id='fm-save' button in home.html"


def test_ac5_save_after_notes(html):
    """Save button must appear after the notes textarea in the HTML."""
    notes_pos = html.find('id="fm-notes"')
    save_pos  = html.find('id="fm-save"')
    assert notes_pos != -1 and save_pos != -1
    assert notes_pos < save_pos, \
        "fm-save must appear after fm-notes in the HTML source"


# ── AC6: auto-save debounce on blur ──────────────────────────────────────────

def test_ac6_autosave_800ms_in_js(js):
    """JS must use 800ms debounce for auto-save."""
    assert "800" in js, "JS must use 800 ms debounce for auto-save on blur"


def test_ac6_blur_event_in_js(js):
    """JS must listen for 'blur' event to trigger auto-save."""
    assert "blur" in js, "JS must use blur event for auto-save trigger"


def test_ac6_debounce_clears_pending_timer(js):
    """JS must cancel pending timers to avoid duplicate save requests."""
    assert "clearTimeout" in js, \
        "JS must use clearTimeout to prevent duplicate auto-save requests"


# ── AC7: non-blocking 'Saved' toast ≥2 seconds ───────────────────────────────

def test_ac7_saved_toast_shown(js):
    """JS must display a 'Saved' toast after a successful save."""
    assert "Saved" in js, "JS must show 'Saved' message after save"


def test_ac7_toast_duration_at_least_2000ms(js):
    """JS toast must be visible for at least 2000ms."""
    assert "2000" in js or "3000" in js, \
        "JS must keep the Saved toast visible for at least 2000ms"


def test_ac7_toast_nonblocking(js):
    """showToast / toast call must not block the form (form stays open)."""
    assert "showToast" in js or "UIStates" in js, \
        "JS must use a non-blocking toast mechanism (UIStates.showToast)"


# ── AC8: 'Log today' CTA banner ──────────────────────────────────────────────

def test_ac8_banner_element_exists(html):
    """home.html must have a 'Log today' banner element (id='log-today-banner')."""
    assert 'id="log-today-banner"' in html, \
        "Missing id='log-today-banner' in home.html"


def test_ac8_banner_cta_button_exists(html):
    """The 'Log today' banner must contain a CTA button."""
    assert 'id="log-today-cta-btn"' in html, \
        "Missing id='log-today-cta-btn' in home.html"


def test_ac8_banner_before_main_content(html):
    """'Log today' banner must appear before the main content cards in HTML."""
    banner_pos  = html.find('id="log-today-banner"')
    row1_pos    = html.find('id="row-1"')
    assert banner_pos != -1 and row1_pos != -1
    assert banner_pos < row1_pos, \
        "log-today-banner must appear before row-1 in the HTML"


def test_ac8_js_checks_today_metrics_for_banner(js):
    """JS must fetch today's daily-metrics to decide whether to show the banner."""
    assert "log-today-banner" in js, \
        "JS must reference log-today-banner to show/hide it"


def test_ac8_banner_hidden_when_metrics_logged(js):
    """JS must hide the banner when today's metrics row already exists."""
    assert ("display" in js or "hidden" in js or ".style" in js), \
        "JS must change display/visibility of banner based on today's metrics"


# ── AC9: tapping CTA opens form directly ─────────────────────────────────────

def test_ac9_cta_opens_form_in_js(js):
    """JS must wire the 'Log today' CTA to open/scroll to the metrics form."""
    assert "log-today-cta-btn" in js, \
        "JS must wire the log-today-cta-btn to open the fast-log form"


def test_ac9_cta_wires_scroll_or_focus(js):
    """Tapping CTA must scroll to or focus the metrics form."""
    assert "scroll" in js.lower() or "focus" in js.lower() or "fast-log" in js, \
        "JS must scroll to or focus the metrics form when CTA is tapped"


# ── AC10: backend field verification (read-only) ─────────────────────────────

def test_ac10_backend_accepts_resting_hr():
    """Backend DailyMetricBody must have resting_hr."""
    main_py = (ROOT / "backend" / "main.py").read_text()
    cls_idx = main_py.find("class DailyMetricBody")
    assert cls_idx != -1
    cls_body = main_py[cls_idx:cls_idx + 500]
    assert "resting_hr" in cls_body, "DailyMetricBody must have resting_hr"


def test_ac10_backend_accepts_hrv():
    """Backend DailyMetricBody must have hrv."""
    main_py = (ROOT / "backend" / "main.py").read_text()
    cls_idx = main_py.find("class DailyMetricBody")
    cls_body = main_py[cls_idx:cls_idx + 500]
    assert "hrv" in cls_body, "DailyMetricBody must have hrv"


def test_ac10_backend_accepts_sleep_hours():
    """Backend DailyMetricBody must have sleep_hours."""
    main_py = (ROOT / "backend" / "main.py").read_text()
    cls_idx = main_py.find("class DailyMetricBody")
    cls_body = main_py[cls_idx:cls_idx + 500]
    assert "sleep_hours" in cls_body, "DailyMetricBody must have sleep_hours"


def test_ac10_backend_accepts_energy():
    """Backend DailyMetricBody must have energy."""
    main_py = (ROOT / "backend" / "main.py").read_text()
    cls_idx = main_py.find("class DailyMetricBody")
    cls_body = main_py[cls_idx:cls_idx + 500]
    assert "energy" in cls_body, "DailyMetricBody must have energy"


def test_ac10_backend_accepts_mood():
    """Backend DailyMetricBody must have mood."""
    main_py = (ROOT / "backend" / "main.py").read_text()
    cls_idx = main_py.find("class DailyMetricBody")
    cls_body = main_py[cls_idx:cls_idx + 500]
    assert "mood" in cls_body, "DailyMetricBody must have mood"


def test_ac10_backend_accepts_notes():
    """Backend DailyMetricBody must have notes."""
    main_py = (ROOT / "backend" / "main.py").read_text()
    cls_idx = main_py.find("class DailyMetricBody")
    cls_body = main_py[cls_idx:cls_idx + 500]
    assert "notes" in cls_body, "DailyMetricBody must have notes"


def test_ac10_backend_missing_weight_kg():
    """DailyMetricBody must NOT have weight_kg — verified discrepancy for issue #394."""
    main_py = (ROOT / "backend" / "main.py").read_text()
    cls_idx = main_py.find("class DailyMetricBody")
    assert cls_idx != -1
    cls_body = main_py[cls_idx:cls_idx + 500]
    assert "weight_kg" not in cls_body, \
        "DailyMetricBody must NOT contain weight_kg; " \
        "discrepancy: /api/daily-metrics does not accept weight_kg but the form includes it"


# ── AC11: design tokens and typography ───────────────────────────────────────

def test_ac11_inter_tight_font(html):
    """home.html must use Inter Tight font."""
    assert "Inter Tight" in html, "home.html must reference Inter Tight font"


def test_ac11_css_variables(html):
    """home.html CSS must use CSS custom properties (design tokens)."""
    assert "var(--" in html, "home.html CSS must use var(--…) design tokens"


def test_ac11_monospace_numbers(html):
    """CSS must render numbers in monospace (JetBrains Mono or font-variant-numeric)."""
    assert "JetBrains Mono" in html or "monospace" in html or "font-variant-numeric" in html, \
        "CSS must use monospace font for numeric value display"


def test_ac11_fast_log_css_uses_variables(html):
    """Fast-log CSS must use the shared CSS variable tokens, not hardcoded colours."""
    fl_idx = html.find(".fast-log")
    assert fl_idx != -1, "home.html must define .fast-log CSS"
    fl_block = html[fl_idx:fl_idx + 1200]
    assert "var(--" in fl_block, \
        ".fast-log CSS must use CSS custom property tokens (var(--…))"
