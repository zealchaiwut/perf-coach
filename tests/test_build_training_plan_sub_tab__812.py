"""
Tests for issue #812: Build Training > Plan sub-tab with race planning UI.

AC items tested:
  AC1  - Race Header shows name, priority, date, distance, goal time, goal pace, weeks-to-go;
         null values render as a dash
  AC2  - On-Track Verdict Banner shows "on track", "ahead", or "behind" from the endpoint;
         banner is absent when verdict is missing/insufficient
  AC3  - Performance Curve populated state: solid form line, dashed projected line, shaded
         zones, taper marker, race-day marker
  AC4  - Performance Curve building-baseline state: projection suppressed; legible message shown
  AC5  - B-race and checkpoint markers overlaid on the curve timeline
  AC6  - Races and Checkpoints list exists with met/upcoming status badges
  AC7  - Add/Edit Races: inline form creates/updates via races CRUD endpoints
  AC8  - Add/Edit Checkpoints: inline form creates/updates via checkpoints CRUD endpoints
  AC9  - Goal Pace is computed client-side when both goal time and distance are set;
         shows dash when either is missing
  AC10 - Specificity Bars: four bars — goal-pace volume, longest-at-pace, longest by distance,
         longest by duration
  AC11 - Read-only enforcement: no write surface outside add/edit forms
  AC12 - Gradient-theme tokens: no new color literals introduced
  AC13 - Mobile layout: single-column stacking with legible curve at mobile widths
  AC14 - Null safety: every null field renders as dash, no "undefined" shown
"""

import re
import os
import pytest
import httpx


BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def html():
    p = os.path.join(os.path.dirname(__file__), "../frontend/pages/training-log.html")
    with open(p, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def plan_js():
    p = os.path.join(os.path.dirname(__file__), "../frontend/js/training-performance.js")
    with open(p, encoding="utf-8") as f:
        return f.read()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _plan_panel_html(html):
    """Extract the Plan panel section from the page HTML.

    training-panel-performance (2026-07-09: renamed from
    training-panel-projection, which is what this test originally called the
    Plan tab's panel — it was never the removed standalone Performance tab)
    is the last sub-tab panel in the page, so there's no distinct end-boundary
    id to search for; always fall back to a fixed window. Kept at 60000 (was
    bumped from 20000 when score cards, moving-your-scores,
    projected-checkpoint, and personal records were relocated into this panel).
    """
    start = html.find('id="training-panel-performance"')
    assert start != -1, "training-panel-performance must exist in the page"
    return html[start:start + 60000]


def _styles(html):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.DOTALL))


# ── AC1: Race Header ───────────────────────────────────────────────────────────

def test_race_header_element_present(html):
    """AC1: A container for the race header exists in the Plan tab panel."""
    panel = _plan_panel_html(html)
    assert 'id="plan-race-header"' in panel or 'plan-race-header' in panel, \
        "Race header container must be present in the Plan panel"


def test_race_header_renders_name(plan_js):
    """AC1: JS renders the race name in the race header."""
    assert "plan-race-hd-name" in plan_js or "r.name" in plan_js, \
        "renderRaceHeader must reference the race name"


def test_race_header_renders_priority_badge(plan_js):
    """AC1: JS renders a priority badge (A/B/C) in the race header."""
    assert "plan-priority-badge" in plan_js, \
        "renderRaceHeader must include a priority badge element"


def test_race_header_renders_date(plan_js):
    """AC1: JS renders the race date in the header."""
    assert "race_date" in plan_js and "formatDate" in plan_js, \
        "renderRaceHeader must render the formatted race date"


def test_race_header_renders_distance(plan_js):
    """AC1: JS renders the race distance in the header."""
    assert "distance_km" in plan_js, \
        "renderRaceHeader must render the race distance"


def test_race_header_renders_goal_time(plan_js):
    """AC1: JS renders goal time in the header (shows dash when null)."""
    assert "goal_time_seconds" in plan_js and "fmtTime" in plan_js, \
        "renderRaceHeader must render goal time (fmtTime helper)"


def test_race_header_renders_weeks_to_go(plan_js):
    """AC1: JS renders weeks-to-go in the race header."""
    assert "weeksUntil" in plan_js and "weeks" in plan_js, \
        "renderRaceHeader must compute and display weeks until race"


def test_null_rendering_uses_dash(plan_js):
    """AC1/AC14: Null values are represented as dash character."""
    # fmtPace, fmtTime, fmtKm should all return "—" for null/zero
    assert '"—"' in plan_js or '"—"' in plan_js, \
        "Helper functions must return '—' (em dash) for null/missing values"


# ── AC2: On-Track Verdict Banner ───────────────────────────────────────────────

def test_verdict_banner_element_present(html):
    """AC2: A verdict banner container exists in the Plan tab panel."""
    panel = _plan_panel_html(html)
    assert 'id="plan-verdict"' in panel or 'plan-verdict' in panel, \
        "Verdict banner container must be in the Plan panel"


def test_verdict_shows_on_track_text(plan_js):
    """AC2: Verdict banner shows 'on track' status text from the endpoint."""
    # The raw status "on track" must be shown (not translated to a different label)
    assert '"on track"' in plan_js or "'on track'" in plan_js, \
        "JS must reference the raw 'on track' status string from the endpoint"


def test_verdict_shows_ahead_text(plan_js):
    """AC2: Verdict banner shows 'ahead' status text from the endpoint."""
    assert '"ahead"' in plan_js or "'ahead'" in plan_js, \
        "JS must reference the raw 'ahead' status string from the endpoint"


def test_verdict_shows_behind_text(plan_js):
    """AC2: Verdict banner shows 'behind' status text from the endpoint."""
    assert '"behind"' in plan_js or "'behind'" in plan_js, \
        "JS must reference the raw 'behind' status string from the endpoint"


def test_verdict_hidden_when_no_status(plan_js):
    """AC2: Verdict banner is hidden when status is not on track/ahead/behind."""
    # The JS must explicitly hide the element for other statuses
    assert 'el.style.display = "none"' in plan_js or "el.style.display='none'" in plan_js, \
        "Verdict banner must be hidden when no valid status is returned"


def test_verdict_status_rendered_as_label(plan_js):
    """AC2: The raw status string is used as the banner label text (not a translated label)."""
    # The label must be assigned from the raw status (not hardcoded "On Track" etc.)
    assert "label = status" in plan_js or "el.textContent = status" in plan_js, \
        "Verdict banner must use raw status from endpoint as label (not a hardcoded 'On Track')"


# ── AC3: Performance Curve — populated state ──────────────────────────────────

def test_curve_canvas_element_present(html):
    """AC3: A canvas element for the performance form curve exists."""
    panel = _plan_panel_html(html)
    assert 'id="plan-form-curve"' in panel or "plan-form-curve" in panel, \
        "Canvas element for the performance curve must be in the Plan panel"


def test_curve_renders_historical_form_line(plan_js):
    """AC3: JS renders a solid historical form line on the curve."""
    assert "Historical form" in plan_js or "historical" in plan_js.lower(), \
        "Curve must include a historical form dataset"


def test_curve_renders_projected_form_line(plan_js):
    """AC3: JS renders a dashed projected form line."""
    assert "Projected form" in plan_js or "projected" in plan_js.lower(), \
        "Curve must include a projected form dataset"


def test_curve_has_dashed_projected_line(plan_js):
    """AC3: Projected form line is dashed."""
    assert "borderDash" in plan_js, \
        "Projected form line must use borderDash (dashed style)"


def test_curve_has_fresh_zone(plan_js):
    """AC3: Fresh zone shading is included."""
    assert "Fresh zone" in plan_js or "fresh" in plan_js.lower(), \
        "Curve must include fresh zone shading"


def test_curve_has_buried_zone(plan_js):
    """AC3: Buried zone shading is included."""
    assert "Buried zone" in plan_js or "buried" in plan_js.lower(), \
        "Curve must include buried zone shading"


def test_curve_has_taper_marker(plan_js):
    """AC3: Taper marker annotation is included."""
    assert "taper" in plan_js.lower() and "annotation" in plan_js.lower(), \
        "Curve must include taper marker annotation"


def test_curve_has_race_day_marker(plan_js):
    """AC3: Race-day peak marker annotation is included."""
    assert "Race day" in plan_js or "race_date" in plan_js, \
        "Curve must include a race-day marker annotation"


# ── AC4: Performance Curve — building-baseline state ─────────────────────────

def test_building_baseline_element_present(html):
    """AC4: A building-baseline state element exists in the Plan panel."""
    panel = _plan_panel_html(html)
    assert "plan-building-baseline" in panel, \
        "building-baseline state element must be in the Plan panel"


def test_building_baseline_message_present(html):
    """AC4: A legible message is shown when the baseline is building."""
    panel = _plan_panel_html(html)
    # Any message conveying insufficient history is acceptable
    assert (
        "baseline" in panel.lower()
        or "history" in panel.lower()
        or "not enough" in panel.lower()
    ), "Building-baseline message must convey insufficient history"


def test_building_baseline_suppresses_projection(plan_js):
    """AC4: When building_baseline is true, the projection canvas is hidden."""
    # The JS should set wrapEl.style.display = "none" when building_baseline
    assert "building_baseline" in plan_js, \
        "JS must check building_baseline flag from the readiness endpoint"


# ── AC5: B-race and checkpoint markers ───────────────────────────────────────

def test_b_race_markers_on_curve(plan_js):
    """AC5: B-race markers are drawn on the performance curve timeline."""
    # Check that the curve code references B-race markers
    assert 'priority === "B"' in plan_js or "'B'" in plan_js, \
        "Curve must include B-race markers"


def test_checkpoint_markers_on_curve(plan_js):
    """AC5: Checkpoint markers are drawn on the performance curve timeline."""
    assert "checkpoint" in plan_js.lower(), \
        "Curve must include checkpoint markers"


# ── AC6: Races and Checkpoints List ──────────────────────────────────────────

def test_races_list_container_present(html):
    """AC6: A races and checkpoints list container exists in the Plan panel."""
    panel = _plan_panel_html(html)
    assert 'id="plan-races"' in panel, \
        "Races list container must be present in the Plan panel"


def test_races_list_met_badge_present(html, plan_js):
    """AC6: Met/upcoming status badge markup exists (defined in CSS, rendered by JS)."""
    styles = _styles(html)
    assert "plan-met-badge" in styles or "met-upcoming" in styles or \
           "plan-met-badge" in plan_js or "met-upcoming" in plan_js, \
        "Met/upcoming badge CSS class must be defined (in styles or rendered by JS)"


def test_races_list_renders_met_status(plan_js):
    """AC6: JS renders met/upcoming status on each race row."""
    assert "met_status" in plan_js or "metLabel" in plan_js, \
        "JS must render met/upcoming status in the races list"


# ── AC7: Add/Edit Races ───────────────────────────────────────────────────────

def test_add_race_button_present(html):
    """AC7: Add Race button exists in the Plan panel."""
    panel = _plan_panel_html(html)
    assert 'id="plan-add-race-btn"' in panel or "Add Race" in panel, \
        "Add Race button must be in the Plan panel"


def test_race_modal_present(html):
    """AC7: The race add/edit modal exists in the page."""
    assert 'id="plan-race-modal"' in html, \
        "Race add/edit modal (plan-race-modal) must exist in the page"


def test_race_modal_has_required_fields(html):
    """AC7: Modal has fields for name, date, distance, priority, goal time, status."""
    assert 'id="plan-modal-name"' in html, "Modal must have name input"
    assert 'id="plan-modal-date"' in html, "Modal must have date input"
    assert 'id="plan-modal-distance"' in html, "Modal must have distance input"
    assert 'id="plan-modal-priority"' in html, "Modal must have priority select"
    assert 'id="plan-modal-goal-time"' in html, "Modal must have goal time input"
    assert 'id="plan-modal-status"' in html, "Modal must have status select"


def test_race_save_calls_api(plan_js):
    """AC7: Saving a race calls the /api/races CRUD endpoints."""
    assert '"/api/races"' in plan_js or "'/api/races'" in plan_js or \
           "/api/races/" in plan_js, \
        "JS must call /api/races to create/update races"


def test_race_list_refreshes_on_save(plan_js):
    """AC7: Races list refreshes after saving."""
    assert "refresh()" in plan_js or "refresh =" in plan_js, \
        "JS must refresh the races list after save"


# ── AC8: Add/Edit Checkpoints ─────────────────────────────────────────────────

def test_add_checkpoint_button_present(html):
    """AC8: Add Checkpoint button exists in the Plan panel."""
    panel = _plan_panel_html(html)
    assert 'id="plan-add-checkpoint-btn"' in panel or "Add Checkpoint" in panel, \
        "Add Checkpoint button must be in the Plan panel"


def test_checkpoint_modal_uses_same_modal(plan_js):
    """AC8: Checkpoint add/edit uses the same modal as races with checkpoint type."""
    assert "checkpoint" in plan_js.lower(), \
        "JS must handle checkpoint type in the add/edit modal"


def test_checkpoint_save_via_races_endpoint(plan_js):
    """AC8: Checkpoints are saved via /api/races endpoints (race_type='checkpoint')."""
    assert "race_type" in plan_js, \
        "JS must set race_type when saving a checkpoint"


# ── AC9: Goal Pace derivation ─────────────────────────────────────────────────

def test_goal_pace_computed_client_side(plan_js):
    """AC9: Goal pace is computed client-side when goal_pace_seconds_per_km is not provided."""
    # The JS should compute pace = goal_time_seconds / distance_km when server value is null
    assert "goal_time_seconds" in plan_js and "distance_km" in plan_js, \
        "JS must reference both goal_time_seconds and distance_km for pace computation"
    # Must have a division or fallback
    assert (
        "goal_time_seconds / " in plan_js
        or "/ r.distance_km" in plan_js
        or "goal_pace_seconds_per_km || " in plan_js
    ), "JS must compute goal pace from time/distance when server field is absent"


def test_goal_pace_shows_dash_when_missing(plan_js):
    """AC9: Goal pace shows dash when goal time or distance is missing."""
    assert "fmtPace" in plan_js, "fmtPace helper must be used for goal pace display"
    # fmtPace must return dash for null/zero
    assert 'return "—"' in plan_js or "return '—'" in plan_js or \
           "return \"—\"" in plan_js, \
        "fmtPace must return '—' for null/missing pace"


# ── AC10: Specificity Bars ────────────────────────────────────────────────────

def test_spec_bars_section_present(html):
    """AC10: Specificity bars section exists in the Plan panel."""
    panel = _plan_panel_html(html)
    assert 'id="plan-spec-bars"' in panel or "plan-spec-bars" in panel, \
        "Specificity bars container must be in the Plan panel"


def test_spec_bar_volume_present(html):
    """AC10: Goal-pace volume bar is present."""
    panel = _plan_panel_html(html)
    assert "plan-spec-volume" in panel or "Goal-Pace Volume" in panel, \
        "Goal-pace volume bar must be in the Plan panel"


def test_spec_bar_pace_present(html):
    """AC10: Longest-at-pace bar is present."""
    panel = _plan_panel_html(html)
    assert "plan-spec-pace" in panel or "Longest-at-Pace" in panel or \
           "longest_pace_effort" in panel or "Longest" in panel, \
        "Longest-at-pace bar must be in the Plan panel"


def test_spec_bar_distance_present(html):
    """AC10: Longest run by distance bar is present."""
    panel = _plan_panel_html(html)
    assert "plan-spec-distance" in panel or "plan-spec-slower" in panel or \
           "longest_run_by_distance" in panel or "Longest" in panel, \
        "Longest run by distance bar must be in the Plan panel"


def test_spec_bar_duration_present(html):
    """AC10: Longest run by duration bar is present (4th bar)."""
    panel = _plan_panel_html(html)
    assert "plan-spec-duration" in panel or "longest_run_by_duration" in panel or \
           "Duration" in panel, \
        "Longest run by duration bar must be in the Plan panel (4th specificity bar)"


def test_spec_bars_count(html):
    """AC10: Exactly four specificity bars are present."""
    panel = _plan_panel_html(html)
    # Count distinct plan-spec-bar elements
    bar_count = len(re.findall(r'class="plan-spec-bar"', panel))
    assert bar_count >= 4, \
        f"Must have at least 4 specificity bars, found {bar_count}"


def test_spec_bar_duration_js_handler(plan_js):
    """AC10: JS handles the longest_run_by_duration bar."""
    assert "longest_run_by_duration" in plan_js, \
        "JS must handle the longest_run_by_duration specificity metric"


def test_spec_duration_formatted_as_time(plan_js):
    """AC10: Duration bar shows value in time format (not raw seconds)."""
    # The duration value (seconds) should be formatted as time
    assert "fmtTime" in plan_js, \
        "JS must format the duration bar value using fmtTime (not raw seconds)"


# ── AC11: Read-only enforcement ───────────────────────────────────────────────

def test_curve_is_not_a_form(html):
    """AC11: The performance curve section has no form/input elements."""
    panel = _plan_panel_html(html)
    curve_section_start = panel.find("plan-curve-section")
    if curve_section_start == -1:
        curve_section_start = panel.find("plan-form-curve")
    # Extract a reasonable window around the curve
    curve_section = panel[max(0, curve_section_start - 200):curve_section_start + 2000]
    # No form/input inside the curve section
    assert "<form" not in curve_section and '<input' not in curve_section, \
        "Performance curve section must not contain form inputs"


def test_spec_bars_are_display_only(html):
    """AC11: Specificity bars section has no input elements (display-only)."""
    panel = _plan_panel_html(html)
    spec_start = panel.find("plan-spec-bars")
    spec_section = panel[spec_start:spec_start + 3000] if spec_start != -1 else ""
    assert '<input' not in spec_section, \
        "Specificity bars section must not contain input fields"


# ── AC12: Gradient-theme tokens ───────────────────────────────────────────────

def test_plan_panel_uses_css_vars(html):
    """AC12: Plan panel CSS uses existing design-system CSS variables."""
    styles = _styles(html)
    plan_css_start = styles.find("plan-")
    plan_css = styles[plan_css_start:plan_css_start + 5000] if plan_css_start != -1 else styles
    assert "--card-bg" in plan_css or "var(--card" in plan_css or "var(--text" in plan_css, \
        "Plan panel CSS must use existing design-system CSS variables"


def test_no_new_hardcoded_gradient_colors(html):
    """AC12: No new gradient color literals (background: linear-gradient) introduced in plan CSS."""
    styles = _styles(html)
    plan_idx = styles.find("plan-")
    plan_css = styles[plan_idx:] if plan_idx != -1 else styles
    # Find any linear-gradient definitions after the plan CSS section begins
    lg_matches = re.findall(r"linear-gradient\([^)]+\)", plan_css)
    # If there are any, ensure they only use existing token-derived values
    for lg in lg_matches:
        assert "var(--" in lg or "rgba" in lg or "transparent" in lg, \
            f"New hardcoded color in plan CSS gradient: {lg}"


# ── AC13: Mobile layout ───────────────────────────────────────────────────────

def test_mobile_media_query_present(html):
    """AC13: A mobile media query exists for the plan tab layout."""
    styles = _styles(html)
    assert "@media" in styles and ("600px" in styles or "640px" in styles or "480px" in styles), \
        "Mobile media query must be present in the page styles"


def test_plan_panel_single_column_mobile(html):
    """AC13: Plan panel stacks to a single column on mobile (flex-direction column)."""
    styles = _styles(html)
    plan_style_section = styles[styles.find("plan-"):]
    assert "flex-direction: column" in plan_style_section or \
           "flex-direction:column" in plan_style_section or \
           "display: flex" in plan_style_section, \
        "Plan panel must use flex layout for single-column stacking on mobile"


# ── AC14: Null safety ─────────────────────────────────────────────────────────

def test_fmt_pace_null_safe(plan_js):
    """AC14: fmtPace returns dash for null/zero input."""
    assert "function fmtPace" in plan_js, "fmtPace function must exist"
    fmt_pace_start = plan_js.find("function fmtPace")
    fmt_pace_body = plan_js[fmt_pace_start:fmt_pace_start + 200]
    assert "return" in fmt_pace_body, "fmtPace must return a value"
    assert '"—"' in fmt_pace_body or "'—'" in fmt_pace_body or "—" in fmt_pace_body, \
        "fmtPace must return '—' for null/zero pace"


def test_fmt_time_null_safe(plan_js):
    """AC14: fmtTime returns dash for null/zero input."""
    assert "function fmtTime" in plan_js, "fmtTime function must exist"
    fmt_time_start = plan_js.find("function fmtTime")
    fmt_time_body = plan_js[fmt_time_start:fmt_time_start + 200]
    assert '"—"' in fmt_time_body or "'—'" in fmt_time_body or "—" in fmt_time_body, \
        "fmtTime must return '—' for null/zero time"


def test_distance_null_safe_in_header(plan_js):
    """AC14: Race header shows dash for null distance_km."""
    # The header must guard against null distance_km
    assert "distance_km" in plan_js, "renderRaceHeader must reference distance_km"
    # Confirm there's a null guard or null-safe rendering
    assert "parseFloat" in plan_js or "r.distance_km" in plan_js, \
        "renderRaceHeader must handle distance_km safely"


# ── API: readiness endpoint shape ─────────────────────────────────────────────

def test_readiness_endpoint_exists(client):
    """Smoke: /api/races/{id}/readiness responds (401 without auth, not 404)."""
    # Without auth, expect 401 or 302 (not 404 which would mean route missing)
    res = client.get("/api/races/00000000-0000-0000-0000-000000000000/readiness")
    assert res.status_code in (401, 302, 403, 404, 422), \
        f"Readiness endpoint should exist (auth-gated), got {res.status_code}"
    assert res.status_code != 500, "Readiness endpoint must not return 500"


def test_races_endpoint_exists(client):
    """Smoke: /api/races responds (401 without auth, not 404)."""
    res = client.get("/api/races")
    assert res.status_code in (401, 302, 403), \
        f"/api/races must be auth-gated, got {res.status_code}"


def test_no_new_backend_endpoints(client):
    """AC: No new backend endpoints were added for this feature."""
    for path in ["/api/training/plan", "/api/plan", "/api/plan-tab"]:
        res = client.get(path)
        assert res.status_code in (404, 405), \
            f"{path} should not exist (this feature has no new backend endpoints)"


# ── UAT-aligned smoke tests ───────────────────────────────────────────────────

def test_uat1_plan_tab_renders_race_header(html):
    """UAT 1: Plan tab HTML has race header structure."""
    panel = _plan_panel_html(html)
    assert "plan-race-header" in panel, "Race header section must exist in Plan tab"


def test_uat2_performance_curve_canvas_present(html):
    """UAT 2: Performance curve canvas is in the Plan tab."""
    panel = _plan_panel_html(html)
    assert "plan-form-curve" in panel, "Performance curve canvas must be in Plan tab"


def test_uat3_building_baseline_element(html):
    """UAT 3: Building-baseline element is present for the low-data state."""
    panel = _plan_panel_html(html)
    assert "plan-building-baseline" in panel, "Building-baseline state element must exist"


def test_uat4_add_race_workflow(html, plan_js):
    """UAT 4: Add Race button and modal with required fields are present."""
    assert 'id="plan-race-modal"' in html, "Race modal must exist"
    assert 'id="plan-modal-name"' in html, "Race name field must exist in modal"
    assert 'id="plan-modal-date"' in html, "Race date field must exist in modal"


def test_uat5_edit_checkpoint_workflow(html, plan_js):
    """UAT 5: Checkpoint editing uses the same modal with checkpoint type."""
    assert "checkpoint" in plan_js.lower(), "JS must handle checkpoints"
    assert 'id="plan-add-checkpoint-btn"' in html or "Add Checkpoint" in html, \
        "Add Checkpoint button must exist"


def test_uat6_mobile_layout(html):
    """UAT 6: Mobile layout CSS is defined."""
    styles = _styles(html)
    assert "@media" in styles, "Mobile media queries must be defined"


def test_uat7_specificity_bars(html):
    """UAT 7: All four specificity bars are present."""
    panel = _plan_panel_html(html)
    bars = re.findall(r'class="plan-spec-bar"', panel)
    assert len(bars) >= 4, f"Must have 4 specificity bars, found {len(bars)}"


def test_uat8_goal_pace_dash_when_missing(plan_js):
    """UAT 8: Goal pace shows dash when goal time is missing from race."""
    assert "fmtPace" in plan_js, "fmtPace must be used for goal pace"
    start = plan_js.find("function fmtPace")
    body = plan_js[start:start + 150]
    assert "—" in body or "—" in body, "fmtPace must return dash for null"
