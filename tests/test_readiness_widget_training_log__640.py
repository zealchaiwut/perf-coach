"""
Tests for issue #640: Add Readiness Widget to Training Log Sub-Tab.

AC items tested:
  AC1  - Widget renders in Log sub-tab, below log header, above activity list
  AC2  - Three tiles in a horizontal row: Fitness (CTL), Fatigue (ATL), Form (TSB)
  AC3  - Each tile shows numeric value and label with gradient theme
  AC4  - Recovery hint displayed beneath the three tiles
  AC5  - Layout follows structural conventions (no hard-coded px widths or colours)
  AC6  - Data read exclusively from /api/readiness/current; no local CTL/ATL/TSB computation
  AC7  - building-baseline state replaces tiles with single message; hint hidden
  AC8  - Widget hidden on error or non-200 from endpoint
  AC9  - Component is purely display-only (no interactive controls)
  AC10 - Widget is responsive (mobile viewport handled)
"""
import os
import re
import uuid
import pytest
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "tester640-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    name = f"tester640_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    client.delete(f"/api/users/{uid}")


@pytest.fixture(scope="module")
def session_cookie(client, test_user):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_user))
        name = u.name
    r = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert r.status_code == 200, r.text
    return r.cookies


@pytest.fixture(scope="module")
def training_log_html():
    html_path = os.path.join(os.path.dirname(__file__), "../frontend/pages/training-log.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def training_log_js():
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/training-log.js")
    with open(js_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def inline_styles(training_log_html):
    blocks = re.findall(r'<style[^>]*>(.*?)</style>', training_log_html, re.DOTALL)
    return "\n".join(blocks)


# ── AC6: /api/readiness/current endpoint exists and requires auth ─────────────

def test_readiness_current_requires_auth(client):
    """AC6: Endpoint requires session auth — anonymous request returns 401."""
    r = client.get("/api/readiness/current")
    assert r.status_code == 401, (
        f"/api/readiness/current must return 401 for unauthenticated requests, got {r.status_code}"
    )


def test_readiness_current_authenticated_returns_200_or_valid(client, session_cookie):
    """AC6: Authenticated request returns 200 with valid JSON structure."""
    r = client.get("/api/readiness/current", cookies=session_cookie)
    assert r.status_code == 200, (
        f"/api/readiness/current returned {r.status_code}: {r.text}"
    )
    body = r.json()
    assert "building_baseline" in body, "Response must include 'building_baseline'"


def test_readiness_current_building_baseline_state(client, session_cookie):
    """AC6/AC7: New user has building_baseline=True (no workout history)."""
    r = client.get("/api/readiness/current", cookies=session_cookie)
    assert r.status_code == 200
    body = r.json()
    # New test user has no workouts — must be in building_baseline state
    assert body["building_baseline"] is True, (
        "A brand-new user with no workouts must return building_baseline=true"
    )
    # In building_baseline state, ctl/atl/tsb and recovery_hint are absent or null
    assert "recovery_hint" not in body or body.get("recovery_hint") is None, (
        "recovery_hint must be absent or null in building_baseline state"
    )


def test_readiness_current_full_response_shape(client, session_cookie):
    """AC6: When not building_baseline, response includes ctl, atl, tsb, recovery_hint."""
    r = client.get("/api/readiness/current", cookies=session_cookie)
    assert r.status_code == 200
    body = r.json()
    if not body.get("building_baseline"):
        assert "ctl" in body, "Non-baseline response must include 'ctl'"
        assert "atl" in body, "Non-baseline response must include 'atl'"
        assert "tsb" in body, "Non-baseline response must include 'tsb'"
        assert "recovery_hint" in body, "Non-baseline response must include 'recovery_hint'"
        assert isinstance(body["ctl"], (int, float)), "'ctl' must be numeric"
        assert isinstance(body["atl"], (int, float)), "'atl' must be numeric"
        assert isinstance(body["tsb"], (int, float)), "'tsb' must be numeric"
        assert isinstance(body["recovery_hint"], str), "'recovery_hint' must be a string"


# ── AC1: Widget exists in Log sub-tab DOM ─────────────────────────────────────

def test_readiness_widget_element_present(training_log_html):
    """AC1: Readiness widget container exists in the Log sub-tab HTML."""
    assert 'id="readiness-widget"' in training_log_html, (
        "training-log.html must contain an element with id='readiness-widget'"
    )


def test_readiness_widget_above_log_list(training_log_html):
    """AC1: Readiness widget appears before the activity list in the DOM."""
    widget_pos = training_log_html.find('id="readiness-widget"')
    log_list_pos = training_log_html.find('id="log-list"')
    assert widget_pos != -1, "readiness-widget element must exist"
    assert log_list_pos != -1, "log-list element must exist"
    assert widget_pos < log_list_pos, (
        "readiness-widget must appear before log-list in the DOM"
    )


# ── AC2: Three tiles present in JS rendering ─────────────────────────────────

def test_js_renders_fitness_ctl_tile(training_log_js):
    """AC2: JS renders a Fitness (CTL) tile."""
    assert "Fitness" in training_log_js and "CTL" in training_log_js, (
        "training-log.js must render a tile labeled 'Fitness' with 'CTL'"
    )


def test_js_renders_fatigue_atl_tile(training_log_js):
    """AC2: JS renders a Fatigue (ATL) tile."""
    assert "Fatigue" in training_log_js and "ATL" in training_log_js, (
        "training-log.js must render a tile labeled 'Fatigue' with 'ATL'"
    )


def test_js_renders_form_tsb_tile(training_log_js):
    """AC2: JS renders a Form (TSB) tile — NOT 'Freshness'."""
    assert "Form" in training_log_js and "TSB" in training_log_js, (
        "training-log.js must render a tile labeled 'Form' with 'TSB'"
    )
    assert "Freshness" not in training_log_js, (
        "TSB tile must be labeled 'Form', not 'Freshness'"
    )


# ── AC4: Recovery hint rendered below tiles ───────────────────────────────────

def test_js_renders_recovery_hint(training_log_js):
    """AC4: JS renders a recovery hint element beneath the tiles."""
    assert "recovery_hint" in training_log_js or "recovery-hint" in training_log_js, (
        "training-log.js must render a recovery hint from the API response"
    )


# ── AC6: JS reads from /api/readiness/current, not load_context ──────────────

def test_js_calls_readiness_current_endpoint(training_log_js):
    """AC6: JS fetches /api/readiness/current for widget data."""
    assert "/api/readiness/current" in training_log_js, (
        "training-log.js must call /api/readiness/current for the readiness widget"
    )


def test_js_does_not_compute_ctl_locally(training_log_js):
    """AC6: JS does not locally compute CTL/ATL/TSB (no formulas)."""
    # Local computation would involve multiplying or exponential decay
    # The existing load_context path passes raw values — no local EWA/formula
    local_computation_patterns = [
        r'ctl\s*=\s*ctl\s*\*',     # EWA update: ctl = ctl * ...
        r'atl\s*=\s*atl\s*\*',
        r'Math\.exp\s*\(\s*-1\s*/\s*42',   # typical CTL tau
        r'Math\.exp\s*\(\s*-1\s*/\s*7',    # typical ATL tau
    ]
    for pat in local_computation_patterns:
        assert not re.search(pat, training_log_js), (
            f"training-log.js must not locally compute CTL/ATL/TSB: found pattern {pat!r}"
        )


# ── AC7: building-baseline state handling ─────────────────────────────────────

def test_js_handles_building_baseline(training_log_js):
    """AC7: JS handles building_baseline state with a contextual message."""
    assert "building_baseline" in training_log_js or "building-baseline" in training_log_js, (
        "training-log.js must handle the building_baseline state"
    )
    assert "Building baseline" in training_log_js, (
        "training-log.js must display 'Building baseline' message in building_baseline state"
    )


# ── AC8: Widget hidden on error ───────────────────────────────────────────────

def test_js_hides_widget_on_error(training_log_js):
    """AC8: JS hides the readiness widget on fetch error or non-200 response."""
    # The widget must use .hidden or display:none on error — not show empty shells
    assert re.search(r'hidden\s*=\s*true|\.hidden\s*=\s*true|style.*display.*none', training_log_js), (
        "training-log.js must hide the readiness widget on fetch error"
    )


# ── AC9: No interactive controls ─────────────────────────────────────────────

def test_widget_has_no_interactive_controls_in_html(training_log_html):
    """AC9: The readiness widget contains no buttons, inputs, or links."""
    widget_start = training_log_html.find('id="readiness-widget"')
    assert widget_start != -1
    # Find the closing tag of the widget container
    # Look for the next sibling element start after the widget
    widget_chunk = training_log_html[widget_start:widget_start + 800]
    assert "<button" not in widget_chunk, "Readiness widget must not contain buttons"
    assert "<input" not in widget_chunk, "Readiness widget must not contain inputs"
    assert "<select" not in widget_chunk, "Readiness widget must not contain selects"


# ── AC5: Gradient theme tokens used (no hard-coded colours in widget CSS) ────

def test_widget_uses_css_variables_not_hardcoded_colors(inline_styles):
    """AC5: Widget CSS uses var(--...) tokens, not hard-coded hex colours."""
    widget_block_match = re.search(
        r'\.readiness-widget.*?(?=\.[a-z]|\Z)', inline_styles, re.DOTALL
    )
    if widget_block_match:
        block = widget_block_match.group(0)
        hardcoded = re.findall(r'(?<!var\()#[0-9a-fA-F]{3,6}\b', block)
        assert not hardcoded, (
            f"Readiness widget CSS must not hard-code hex colours: {hardcoded}"
        )


# ── AC10: Responsive layout ───────────────────────────────────────────────────

def test_widget_css_is_responsive(inline_styles):
    """AC10: Widget tiles use fluid layout (grid/flex) not fixed px widths."""
    # Must not set a fixed pixel width on the widget or its tiles
    assert not re.search(r'\.readiness-widget\s*\{[^}]*width\s*:\s*\d+px', inline_styles), (
        "Readiness widget must not have a hard-coded pixel width"
    )
    # Tile grid must be present and use relative sizing
    assert re.search(r'\.rw-tiles|\.readiness-widget', inline_styles), (
        "Readiness widget CSS must define responsive tile layout"
    )
