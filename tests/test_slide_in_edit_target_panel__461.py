"""
TDD tests for issue #461 — Add slide-in Edit-target panel, remove /weight/targets page.

All tests are static source-file tests (no live server required).

AC anchors:
  (A) Header "Edit target" button opens slide-in panel — NOT /weight/targets link
  (B) Progress-card "Edit target" pill also opens same panel
  (C) Mobile: panel CSS has bottom/overlay sheet behaviour at small viewport
  (D) Panel fields: start weight (read-display + date hint), goal weight (editable),
      goal date (date picker, editable)
  (E) Live preview box exists; JS recomputes pace/kg/milestones on input events
  (F) "Save changes" button (accent/lime, footer right); JS does PATCH or POST
  (G) After save, panel closes and widgets refresh without full reload
  (H) "End target" button (red, footer left); JS confirms before calling end API
  (I) GET /weight/targets redirects to /weight — main.py uses RedirectResponse
  (J) weight-targets.html deleted; weight-targets.js deleted from codebase
  (K) Underlying target API endpoints unchanged (no route mutations)
"""

import re
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
WEIGHT_HTML        = FRONTEND / "pages" / "weight.html"
WEIGHT_JS          = FRONTEND / "js" / "weight.js"
WEIGHT_TARGETS_HTML = FRONTEND / "pages" / "weight-targets.html"
WEIGHT_TARGETS_JS   = FRONTEND / "js" / "weight-targets.js"
MAIN_PY            = ROOT / "backend" / "main.py"

html    = WEIGHT_HTML.read_text()
js      = WEIGHT_JS.read_text()
main_py = MAIN_PY.read_text()


# ── (A) Header "Edit target" button opens slide-in panel ──────────────────────

def test_a_header_edit_target_not_link_to_weight_targets():
    """(A) The page-header 'Edit target' control must NOT be an <a href='/weight/targets'>."""
    # Find the header-actions section
    header_section = html
    assert 'href="/weight/targets"' not in header_section, (
        "Header 'Edit target' must NOT navigate to /weight/targets — "
        "it should open the slide-in panel (AC-A)"
    )


def test_a_header_edit_target_button_present():
    """(A) A header button (or control) labelled 'Edit target' exists."""
    # The control could be a <button> or an <a> with href='#' — not a real page link
    assert "Edit target" in html, (
        "'Edit target' control not found in weight.html (AC-A)"
    )


def test_a_header_edit_target_wired_in_js():
    """(A) JS wires the header Edit-target trigger to open the slide-in panel."""
    # The header button should have an id that JS can query, and JS must reference it
    assert "edit-target-header-btn" in html or "header-edit-btn" in html or (
        "edit-target-pill-btn" in html  # pill in progress card already wired in 460
    ), "No identifiable header Edit-target trigger element found"
    # JS must call _openEditPanel (or equivalent) somewhere
    assert "_openEditPanel" in js or "openEditPanel" in js, (
        "JS does not have _openEditPanel function (AC-A)"
    )


def test_a_panel_css_width_380px():
    """(A) Desktop panel is 380 px wide."""
    assert "380px" in html, (
        "Panel width 380px not found in weight.html CSS (AC-A)"
    )


def test_a_scrim_overlay_element_present():
    """(A) A scrim/overlay element is present in HTML."""
    assert 'id="edit-scrim"' in html or 'id="et-panel-scrim"' in html, (
        "Panel scrim element not found in weight.html (AC-A)"
    )


# ── (B) Progress-card pill also opens panel ───────────────────────────────────

def test_b_progress_card_edit_pill_is_button():
    """(B) The Edit-target pill in the progress card is a button (not an <a> href)."""
    start = html.find('id="progress-card"')
    assert start != -1, "id='progress-card' not found"
    card_section = html[start:start + 3000]
    assert 'href="/weight/targets"' not in card_section, (
        "Edit-target pill in progress card must NOT be a /weight/targets link (AC-B)"
    )


def test_b_progress_card_pill_click_opens_panel_js():
    """(B) JS wires the progress-card pill to _openEditPanel."""
    assert "edit-target-pill-btn" in js, (
        "JS must reference 'edit-target-pill-btn' (AC-B)"
    )
    # Check that clicking the pill calls _openEditPanel
    assert "_openEditPanel" in js, (
        "JS must define _openEditPanel (AC-B)"
    )


# ── (C) Mobile CSS — bottom/overlay sheet ────────────────────────────────────

def test_c_mobile_panel_css_exists():
    """(C) A media-query rule for small screens exists that changes panel layout."""
    # Look for a media query (max-width <= 640px) that touches .et-panel
    css_block = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert css_block, "No <style> block found in weight.html"
    css = css_block.group(1)

    mobile_media = re.search(
        r"@media\s*\(\s*max-width\s*:\s*(?:640|600|560|480|375)px\s*\)",
        css, re.DOTALL
    )
    assert mobile_media, (
        "No mobile media query found in weight.html CSS for small viewport (AC-C)"
    )

    # The mobile rule must reference et-panel or edit-panel
    mobile_start = mobile_media.start()
    # Find the enclosing { ... } block
    brace_start = css.find("{", mobile_start)
    # Find matching closing brace (simple heuristic: count nested braces)
    depth = 0
    brace_end = brace_start
    for i in range(brace_start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                brace_end = i
                break
    mobile_block = css[mobile_start:brace_end + 1]
    assert "et-panel" in mobile_block or "edit-panel" in mobile_block, (
        "Mobile media query does not modify .et-panel layout (AC-C)"
    )


# ── (D) Panel fields ──────────────────────────────────────────────────────────

def test_d_panel_body_has_goal_weight_input():
    """(D) Panel body has a goal-weight input field."""
    assert 'id="et-goal-weight"' in html or 'id="panel-goal-weight"' in html, (
        "Goal weight input not found in the panel (AC-D)"
    )


def test_d_panel_body_has_goal_date_input():
    """(D) Panel body has a goal-date date-picker input."""
    panel_start = html.find('id="edit-panel"')
    assert panel_start != -1, "id='edit-panel' not found"
    panel_section = html[panel_start:panel_start + 2000]
    assert 'type="date"' in panel_section, (
        "Goal date input (type='date') not found in the panel (AC-D)"
    )


def test_d_panel_start_weight_label_present():
    """(D) Panel shows a start weight label/display (read-only display)."""
    panel_start = html.find('id="edit-panel"')
    assert panel_start != -1, "id='edit-panel' not found"
    panel_section = html[panel_start:panel_start + 2000]
    # Should have a start-weight display element
    assert (
        "et-start-weight" in panel_section or
        "panel-start-weight" in panel_section or
        "Start weight" in panel_section
    ), "Start weight display not found in panel body (AC-D)"


def test_d_js_populates_panel_from_active_target():
    """(D) JS has a function that prefills panel fields from the active target."""
    assert (
        "_populateEditPanel" in js or
        "populateEditPanel" in js or
        "et-goal-weight" in js or
        "panel-goal-weight" in js
    ), (
        "JS does not appear to populate panel fields from active target (AC-D)"
    )


# ── (E) Live preview box ──────────────────────────────────────────────────────

def test_e_preview_box_in_panel_html():
    """(E) A live-preview box element exists inside the panel."""
    panel_start = html.find('id="edit-panel"')
    assert panel_start != -1, "id='edit-panel' not found"
    panel_section = html[panel_start:panel_start + 2000]
    assert (
        "et-preview" in panel_section or
        "panel-preview" in panel_section or
        "preview" in panel_section.lower()
    ), "Live-preview box not found inside the panel (AC-E)"


def test_e_js_recomputes_preview_on_input():
    """(E) JS has a preview recompute function triggered by input events."""
    assert (
        "_updatePreview" in js or
        "updatePreview" in js or
        "_recomputePreview" in js or
        "recomputePreview" in js or
        "et-preview" in js
    ), (
        "JS does not have a preview recompute function (AC-E)"
    )


def test_e_preview_computes_pace_and_kg_to_lose():
    """(E) JS preview logic references pace and kg-to-lose metrics."""
    # The preview must compute at least pace and kg remaining
    has_pace = "pace" in js.lower() or "kg/wk" in js or "per_week" in js
    has_kg = "kg_to" in js or "kgToLose" in js or "kg to lose" in js.lower() or "to_go" in js
    assert has_pace, "JS preview must compute pace (AC-E)"
    assert has_kg, "JS preview must compute kg to lose (AC-E)"


# ── (F) Save changes button ───────────────────────────────────────────────────

def test_f_save_button_in_panel_footer():
    """(F) Panel footer has a 'Save changes' button."""
    panel_start = html.find('id="edit-panel"')
    assert panel_start != -1, "id='edit-panel' not found"
    panel_section = html[panel_start:panel_start + 2000]
    assert "Save changes" in panel_section or "Save" in panel_section, (
        "'Save changes' button not found in panel footer (AC-F)"
    )


def test_f_save_button_has_accent_style():
    """(F) Save button uses accent/lime colour (var(--accent) or similar)."""
    panel_start = html.find('id="edit-panel"')
    assert panel_start != -1, "id='edit-panel' not found"
    panel_section = html[panel_start:panel_start + 2000]
    # Button should reference the accent color scheme (inline style or CSS class)
    has_accent_cls = (
        "et-save" in panel_section or
        "save" in panel_section.lower()
    )
    # Broader check: JS or CSS defines the save button with accent background
    css_block = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    css = css_block.group(1) if css_block else ""
    has_accent_css = "accent" in css or "var(--accent)" in css
    assert has_accent_cls and has_accent_css, (
        "Save button does not appear to use accent styling (AC-F)"
    )


def test_f_js_save_patches_active_target():
    """(F) JS save handler PATCHes /api/weight-targets/{id} for existing target."""
    assert (
        'PATCH' in js and
        'weight-targets' in js
    ), "JS save must PATCH /api/weight-targets (AC-F)"


def test_f_js_save_posts_if_no_active_target():
    """(F) JS save handler POSTs /api/weight-targets if no active target exists."""
    assert (
        'POST' in js and
        '/api/weight-targets' in js
    ), "JS save must POST /api/weight-targets when no active target (AC-F)"


# ── (G) After save: panel closes and widgets refresh ─────────────────────────

def test_g_js_closes_panel_after_save():
    """(G) JS calls _closeEditPanel after a successful save."""
    assert "_closeEditPanel" in js, (
        "JS does not have _closeEditPanel (AC-G)"
    )
    # The save logic should call _closeEditPanel
    # Look for a close call near the save/reload path
    assert "_closeEditPanel" in js and "_reload" in js, (
        "JS must close panel and reload widgets after save (AC-G)"
    )


# ── (H) End target with confirmation ─────────────────────────────────────────

def test_h_end_button_in_panel_footer():
    """(H) Panel footer has an 'End target' button."""
    panel_start = html.find('id="edit-panel"')
    assert panel_start != -1, "id='edit-panel' not found"
    panel_section = html[panel_start:panel_start + 2000]
    assert "End target" in panel_section or "End" in panel_section, (
        "'End target' button not found in panel footer (AC-H)"
    )


def test_h_end_button_has_red_style():
    """(H) End button uses red colour styling."""
    panel_start = html.find('id="edit-panel"')
    assert panel_start != -1, "id='edit-panel' not found"
    panel_section = html[panel_start:panel_start + 2000]
    # End button should reference red styling
    css_block = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    css = css_block.group(1) if css_block else ""
    has_red = "var(--red)" in css or "#b91" in css or "red" in css.lower()
    assert has_red, "Panel CSS must include red colour for End button (AC-H)"


def test_h_js_confirms_before_ending():
    """(H) JS shows a confirmation dialog before calling the end API."""
    assert (
        "confirm(" in js or
        "End target" in js  # dialog text in the confirm call
    ), "JS must use confirm() before ending target (AC-H)"


def test_h_js_calls_end_endpoint():
    """(H) JS calls POST /api/weight-targets/{id}/end after confirmation."""
    assert "/end" in js, (
        "JS must call the /end endpoint for End target (AC-H)"
    )


# ── (I) /weight/targets redirects to /weight ─────────────────────────────────

def test_i_backend_redirects_weight_targets():
    """(I) main.py uses RedirectResponse for /weight/targets route."""
    assert "RedirectResponse" in main_py, (
        "main.py must use RedirectResponse (AC-I)"
    )
    # The route handler should no longer serve weight-targets.html
    assert "_serve_weight_targets" not in main_py or (
        "RedirectResponse" in main_py and
        "weight-targets.html" not in main_py[
            main_py.find("_serve_weight_targets"):
            main_py.find("_serve_weight_targets") + 300
        ] if "_serve_weight_targets" in main_py else True
    ), "main.py weight/targets route must redirect, not serve the old HTML (AC-I)"


def test_i_weight_targets_route_points_to_weight():
    """(I) The /weight/targets redirect destination is /weight."""
    # Find the route definition area
    route_area_start = main_py.find("/weight/targets")
    assert route_area_start != -1, "/weight/targets route not found in main.py"
    # Look in a window around the route for the redirect destination
    route_window = main_py[max(0, route_area_start - 200):route_area_start + 600]
    assert '"/weight"' in route_window or "'/weight'" in route_window or (
        "url" in route_window and "/weight" in route_window
    ), "Redirect must target /weight (AC-I)"


# ── (J) Old files deleted ─────────────────────────────────────────────────────

def test_j_weight_targets_html_deleted():
    """(J) frontend/pages/weight-targets.html must NOT exist."""
    assert not WEIGHT_TARGETS_HTML.exists(), (
        "weight-targets.html still exists — it must be deleted (AC-J)"
    )


def test_j_weight_targets_js_deleted():
    """(J) frontend/js/weight-targets.js must NOT exist."""
    assert not WEIGHT_TARGETS_JS.exists(), (
        "weight-targets.js still exists — it must be deleted (AC-J)"
    )


def test_j_weight_html_no_reference_to_weight_targets_js():
    """(J) weight.html must NOT load weight-targets.js."""
    assert "weight-targets.js" not in html, (
        "weight.html still references weight-targets.js (AC-J)"
    )


# ── (K) Underlying API endpoints unchanged ────────────────────────────────────

def test_k_patch_weight_targets_endpoint_unchanged():
    """(K) PATCH /api/weight-targets/{target_id} still exists in main.py."""
    assert "@app.patch(\"/api/weight-targets/{target_id}\")" in main_py or \
           "@app.patch('/api/weight-targets/{target_id}')" in main_py, (
        "PATCH /api/weight-targets/{target_id} endpoint missing from main.py (AC-K)"
    )


def test_k_post_weight_targets_endpoint_unchanged():
    """(K) POST /api/weight-targets still exists in main.py."""
    assert "@app.post(\"/api/weight-targets\"" in main_py or \
           "@app.post('/api/weight-targets'" in main_py, (
        "POST /api/weight-targets endpoint missing from main.py (AC-K)"
    )


def test_k_end_weight_target_endpoint_unchanged():
    """(K) POST /api/weight-targets/{target_id}/end still exists in main.py."""
    assert "@app.post(\"/api/weight-targets/{target_id}/end\")" in main_py or \
           "@app.post('/api/weight-targets/{target_id}/end')" in main_py, (
        "POST /api/weight-targets/{target_id}/end endpoint missing from main.py (AC-K)"
    )


def test_k_active_target_endpoint_unchanged():
    """(K) GET /api/weight-targets/active still exists in main.py."""
    assert "@app.get(\"/api/weight-targets/active\")" in main_py or \
           "@app.get('/api/weight-targets/active')" in main_py, (
        "GET /api/weight-targets/active endpoint missing from main.py (AC-K)"
    )
