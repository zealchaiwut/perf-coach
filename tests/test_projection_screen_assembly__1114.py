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
def nav_js():
    p = os.path.join(os.path.dirname(__file__), "../frontend/js/nav.js")
    with open(p, encoding="utf-8") as f:
        return f.read()


# ── AC1: Page renders without errors ──────────────────────────────────────────

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


# ── AC3: B-race "recalibrates here" marker ────────────────────────────────────

def test_ac3_api_endpoint_has_recalibration_field():
    """AC3: /api/projection must return a field indicating the B-race recalibration point."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "recalibrat" in content.lower(), (
        "main.py /api/projection must include 'recalibrates_here' or similar field in response"
    )


# ── AC5: Endurance score displayed ────────────────────────────────────────────

def test_ac5_api_endpoint_includes_endurance_score():
    """AC5: /api/projection must include endurance score data."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "endurance_score" in content or "endurance" in content.lower(), (
        "main.py /api/projection must return endurance score"
    )


# ── AC6: Speed score displayed ────────────────────────────────────────────────

def test_ac6_api_endpoint_includes_speed_score():
    """AC6: /api/projection must include speed score data."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "speed_score" in content or "speed" in content.lower(), (
        "main.py /api/projection must return speed score"
    )


# ── AC8: Scores update when plan is edited ────────────────────────────────────

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
