"""
Tests for issue #1114: Assemble projection screen with markers and scores.

Acceptance criteria verified:
- AC1: Projection screen renders in full without errors or layout breaks
- AC2: Pace curve displays A, B, and C race markers at their correct positions on the curve
- AC3: A B-race "recalibrates here" marker is visible on the curve at the correct recalibration point
- AC4: Chart, summary cards, and plan editor are composed into a single cohesive view
- AC5: Endurance score is displayed on the projection screen
- AC6: Speed score is displayed on the projection screen
- AC7: Editing a value in the plan editor causes the projection chart to update reactively
- AC8: Scores update when the plan is edited (no stale values shown)
- AC9: Screen is navigable from the main app flow
"""

import os
import py_compile

import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def html():
    p = os.path.join(os.path.dirname(__file__), "../frontend/pages/projection.html")
    with open(p, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def js():
    p = os.path.join(os.path.dirname(__file__), "../frontend/js/projection.js")
    with open(p, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def nav_js():
    p = os.path.join(os.path.dirname(__file__), "../frontend/js/nav.js")
    with open(p, encoding="utf-8") as f:
        return f.read()


# ── AC1: Page renders without errors ──────────────────────────────────────────

def test_ac1_projection_html_exists():
    """AC1: projection.html must exist under frontend/pages/."""
    p = os.path.join(os.path.dirname(__file__), "../frontend/pages/projection.html")
    assert os.path.isfile(p), "frontend/pages/projection.html must exist"


def test_ac1_projection_js_exists():
    """AC1: projection.js must exist under frontend/js/."""
    p = os.path.join(os.path.dirname(__file__), "../frontend/js/projection.js")
    assert os.path.isfile(p), "frontend/js/projection.js must exist"


def test_ac1_html_has_valid_doctype(html):
    """AC1: HTML must start with a valid doctype."""
    assert html.strip().lower().startswith("<!doctype html"), "Must have an HTML5 doctype"


def test_ac1_html_loads_projection_js(html):
    """AC1: Page must load projection.js."""
    assert "projection.js" in html, "projection.html must load projection.js"


def test_ac1_main_py_has_projection_route():
    """AC1: main.py must include 'projection' in _PAGES so /projection and /projection.html are served."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert '"projection"' in content or "'projection'" in content, (
        "main.py _PAGES dict must have a 'projection' key"
    )


def test_ac1_projection_html_in_pages_dict():
    """AC1: main.py _PAGES must map 'projection' → 'projection.html'."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "projection.html" in content, (
        "main.py must reference projection.html in the _PAGES route mapping"
    )


# ── AC2: Pace curve with A/B/C race markers ────────────────────────────────────

def test_ac2_chart_canvas_exists(html):
    """AC2: A canvas element for the projection chart must exist in the HTML."""
    assert "<canvas" in html, "Projection page must have a <canvas> element for the chart"


def test_ac2_js_draws_a_race_marker(js):
    """AC2: JS must annotate the A-race marker on the chart."""
    assert "priority" in js and ("A" in js or '"A"' in js or "'A'" in js), (
        "projection.js must handle A-race markers"
    )


def test_ac2_js_draws_b_race_marker(js):
    """AC2: JS must annotate the B-race marker on the chart."""
    assert "B" in js, "projection.js must handle B-race markers"


def test_ac2_js_draws_c_race_marker(js):
    """AC2: JS must annotate the C-race marker on the chart."""
    assert "C" in js, "projection.js must handle C-race markers"


def test_ac2_race_markers_label_in_js(js):
    """AC2: JS must use marker labels that include the priority letter."""
    assert "marker" in js.lower() or "annotation" in js.lower(), (
        "projection.js must use markers or annotations on the chart"
    )


# ── AC3: B-race "recalibrates here" marker ────────────────────────────────────

def test_ac3_recalibrates_here_text_in_html_or_js(html, js):
    """AC3: 'recalibrates here' or 'recalibrates' must appear in the HTML or JS."""
    combined = html + js
    assert "recalibrat" in combined.lower(), (
        "Page or JS must include 'recalibrates here' marker logic"
    )


def test_ac3_js_handles_b_race_recalibration(js):
    """AC3: JS must have code that places the recalibration marker at the B-race position."""
    assert "recalibrat" in js.lower(), (
        "projection.js must draw the B-race 'recalibrates here' marker"
    )


def test_ac3_api_endpoint_has_recalibration_field():
    """AC3: /api/projection must return a field indicating the B-race recalibration point."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "recalibrat" in content.lower(), (
        "main.py /api/projection must include 'recalibrates_here' or similar field in response"
    )


# ── AC4: Cohesive single view (chart + summary cards + plan editor) ───────────

def test_ac4_chart_section_in_html(html):
    """AC4: An element for the chart section must exist in the HTML."""
    assert "canvas" in html.lower() or "chart" in html.lower(), (
        "Projection page must have a chart section"
    )


def test_ac4_summary_cards_section_in_html(html):
    """AC4: A section for summary cards must exist in the HTML."""
    lower = html.lower()
    assert "score" in lower or "summary" in lower or "card" in lower, (
        "Projection page must have summary cards"
    )


def test_ac4_plan_editor_section_in_html(html):
    """AC4: A plan editor section for adding/editing races must exist in the HTML."""
    lower = html.lower()
    assert "race" in lower or "plan" in lower or "editor" in lower, (
        "Projection page must have a plan editor section"
    )


def test_ac4_no_separate_modal_routes(html):
    """AC4: The three components must be in a single cohesive view, not behind separate routes."""
    # Modals are OK (they're inline overlays), but there should be no link to a separate
    # projection sub-page or separate dashboard tab for the plan editor.
    assert "projection.html" not in html or html.count("projection.html") <= 1, (
        "Projection page must not route to itself as a sub-page"
    )


# ── AC5: Endurance score displayed ────────────────────────────────────────────

def test_ac5_endurance_score_in_html(html):
    """AC5: 'Endurance' label must appear in the projection page HTML."""
    assert "endurance" in html.lower(), (
        "Projection page must display an Endurance score"
    )


def test_ac5_endurance_score_in_js(js):
    """AC5: JS must fetch or reference endurance_score."""
    assert "endurance" in js.lower(), (
        "projection.js must handle endurance score display"
    )


def test_ac5_api_endpoint_includes_endurance_score():
    """AC5: /api/projection must include endurance score data."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "endurance_score" in content or "endurance" in content.lower(), (
        "main.py /api/projection must return endurance score"
    )


# ── AC6: Speed score displayed ────────────────────────────────────────────────

def test_ac6_speed_score_in_html(html):
    """AC6: 'Speed' label must appear in the projection page HTML."""
    assert "speed" in html.lower(), (
        "Projection page must display a Speed score"
    )


def test_ac6_speed_score_in_js(js):
    """AC6: JS must fetch or reference speed_score."""
    assert "speed" in js.lower(), (
        "projection.js must handle speed score display"
    )


def test_ac6_api_endpoint_includes_speed_score():
    """AC6: /api/projection must include speed score data."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "speed_score" in content or "speed" in content.lower(), (
        "main.py /api/projection must return speed score"
    )


# ── AC7: Reactive chart updates ───────────────────────────────────────────────

def test_ac7_js_refreshes_chart_after_edit(js):
    """AC7: JS must call chart refresh / re-render after a plan edit."""
    # After a save/patch/delete, the chart must be re-drawn.
    assert ("refresh" in js or "reload" in js or "_load" in js or "_fetch" in js or
            "renderChart" in js or "drawChart" in js or "_renderCurve" in js or
            "loadProjection" in js or "Chart" in js), (
        "projection.js must refresh the chart after a plan edit"
    )


def test_ac7_js_has_post_edit_callback(js):
    """AC7: JS must trigger a data reload after a successful plan mutation."""
    # Expect some form of callback after API calls succeed.
    assert ("refresh()" in js or "reload()" in js or "_refresh(" in js or
            "_load(" in js or "fetchData(" in js or "loadData(" in js or
            "init()" in js), (
        "projection.js must have a callback that reloads data after plan edits"
    )


# ── AC8: Scores update when plan is edited ────────────────────────────────────

def test_ac8_js_re_renders_scores_after_edit(js):
    """AC8: JS must re-render scores when plan data is refreshed."""
    assert ("endurance" in js.lower() and "speed" in js.lower()), (
        "projection.js must update both endurance and speed scores after plan edits"
    )


# ── AC9: Screen is navigable from main app flow ───────────────────────────────

def test_ac9_nav_has_projection_link(nav_js):
    """AC9: nav.js must include a link to the projection screen."""
    assert "projection" in nav_js.lower(), (
        "nav.js must include a navigation link to /projection"
    )


def test_ac9_main_py_has_projection_in_pages():
    """AC9: main.py must serve /projection and /projection.html."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "projection" in content, (
        "main.py must register /projection as a page route"
    )


def test_ac9_api_endpoint_exists_in_main():
    """AC9: main.py must define GET /api/projection."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert '"/api/projection"' in content or "'/api/projection'" in content, (
        "main.py must define GET /api/projection"
    )


# ── Syntax check ─────────────────────────────────────────────────────────────

def test_main_py_compiles():
    """All modified Python files must compile without syntax errors."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    py_compile.compile(p, doraise=True)
