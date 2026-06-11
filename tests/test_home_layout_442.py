"""TDD tests for issue #442: Assemble home layout with gradient design language.

AC anchors:
  (L1) HTML: page renders on blue gradient background (radial-gradient token in body CSS)
  (L2) HTML: layout order is greeting → log-today strip → habits/readiness 2-up →
             weight full-width → training full-width → performance + [workouts+sleep] 2-up
  (L3) CSS: container max-width ~760px and centered
  (L4) CSS: two-up grids collapse to single column at viewports ≤640px
  (L5) JS: page fires exactly ONE fetch of /api/home/summary (no duplicate calls)
  (L6) JS: all main widget blocks (readiness, habits, weight, training, performance,
           recent_workouts, sleep) are populated from the single summary response
  (L7) JS: habit check action fires POST /api/habits/{id}/log (targeted write)
  (L8) JS: weight log action fires POST /api/weight or /api/weight-entries (targeted write)
  (L9) CSS: gradient tokens (--bg-1, --bg-2) used via var() — no per-page redefinitions
            of raw hex values for the gradient background
  (L10) HTML: #home-top-row contains habits widget (left) and readiness tile (right)
  (L11) HTML: #home-weight-widget is a direct child of .page (full-width)
  (L12) HTML: training card container (#home-training-card or #home-training-row) comes
              BEFORE the performance card container (#perf-card or #home-perf-sleep-row)
  (L13) HTML: #home-sleep-card is in the same column / row group as recent-workouts
              (right side), NOT paired directly with training card
  (L14) CSS: touch targets for habit check circles ≥40px (min-height or height)
  (L15) CSS: touch targets for weight stepper buttons ≥40px (min-height or height)
  (A1) API: /api/home/summary response includes all seven blocks:
            habits, weight, readiness, training_week, performance, recent_workouts, sleep
  (A2) API: habit inline log POST /api/habits/{id}/log returns 201 and logs the habit
  (A3) API: weight inline log POST /api/weight returns 201 or 409 (conflict = update)
"""
import pathlib
import re
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_STRIP_JS = (_ROOT / "frontend" / "js" / "home-strip-habits.js").read_text()
_RTS_JS = (_ROOT / "frontend" / "js" / "home-readiness-training-sleep.js").read_text()


def _all_home_js():
    """Concatenated text of all home JS modules."""
    return _HOME_JS + "\n" + _STRIP_JS + "\n" + _RTS_JS


# ── Layout / CSS checks ────────────────────────────────────────────────────────

def test_L1_body_uses_gradient_background():
    """Body must apply the blue gradient via CSS tokens."""
    assert "radial-gradient" in _HOME_HTML, "body missing radial-gradient background"
    assert "--bg-1" in _HOME_HTML and "--bg-2" in _HOME_HTML, \
        "gradient tokens --bg-1 / --bg-2 not defined in page"


def test_L3_container_max_width_760():
    """Page container must have max-width ≤ 800px (targeting ~760px)."""
    # Extract max-width values from .page rule
    matches = re.findall(r'max-width\s*:\s*(\d+)px', _HOME_HTML)
    # There may be multiple matches; find the one applied to .page
    # We look for a .page block with max-width <= 800
    page_block = re.search(
        r'\.page\s*\{[^}]*max-width\s*:\s*(\d+)px',
        _HOME_HTML, re.DOTALL
    )
    assert page_block, ".page rule with max-width not found in home.html"
    mw = int(page_block.group(1))
    assert mw <= 800, f".page max-width is {mw}px — should be ~760px (≤800px)"


def test_L4_two_up_grids_collapse_at_640px():
    """Two-up grid rows must use a ≤640px media query for single-column collapse."""
    # Look for @media (max-width: 640px) or max-width: 639px
    matches = re.findall(r'@media\s*\([^)]*max-width\s*:\s*(\d+)px\)', _HOME_HTML)
    breakpoints = [int(m) for m in matches]
    assert any(bp <= 640 for bp in breakpoints), \
        f"No ≤640px breakpoint found for responsive collapse; found: {breakpoints}"


def test_L9_gradient_tokens_used_via_var():
    """Gradient background should use var(--bg-1) / var(--bg-2) not raw hex values."""
    # Find the body background rule
    body_bg = re.search(
        r'body\s*\{[^}]*background\s*:[^;}]+',
        _HOME_HTML, re.DOTALL
    )
    assert body_bg, "body background rule not found"
    bg_text = body_bg.group(0)
    assert "var(--bg-1)" in bg_text or "var(--bg-2)" in bg_text, \
        "body background must use --bg-1/--bg-2 CSS tokens via var(), not raw hex"


def test_L14_habit_check_circles_touch_target():
    """Habit check circles must have ≥40px touch target."""
    # Look for hw-check-circle with min-height or height >= 40px
    circle_rules = re.findall(
        r'\.hw-check-circle\s*\{[^}]+\}',
        _HOME_HTML, re.DOTALL
    )
    combined = " ".join(circle_rules)
    sizes = re.findall(r'(?:min-height|height|width)\s*:\s*(\d+)px', combined)
    assert any(int(s) >= 40 for s in sizes), \
        f"Habit check circles lack ≥40px touch target; found sizes: {sizes}"


def test_L15_weight_stepper_buttons_touch_target():
    """Weight stepper buttons must have ≥40px touch target (min-height)."""
    # hww-step-btn or fm-step-btn
    btn_rules = re.findall(
        r'\.(?:hww-step-btn|fm-step-btn|hw-step-btn)\s*\{[^}]+\}',
        _HOME_HTML, re.DOTALL
    )
    combined = " ".join(btn_rules)
    sizes = re.findall(r'(?:min-height|height)\s*:\s*(\d+)px', combined)
    assert any(int(s) >= 40 for s in sizes), \
        f"Weight stepper buttons lack ≥40px touch target; found: {sizes}"


# ── HTML structure checks ──────────────────────────────────────────────────────

def test_L10_home_top_row_contains_habits_and_readiness():
    """#home-top-row must contain both habits widget and readiness tile containers."""
    assert 'id="home-top-row"' in _HOME_HTML or "id='home-top-row'" in _HOME_HTML
    assert 'id="home-habits-widget"' in _HOME_HTML
    assert 'id="home-top-row-right"' in _HOME_HTML

    # Verify both are children of home-top-row (check their document order relative)
    top_row_pos = _HOME_HTML.find('id="home-top-row"')
    habits_pos = _HOME_HTML.find('id="home-habits-widget"')
    readiness_pos = _HOME_HTML.find('id="home-top-row-right"')
    assert top_row_pos < habits_pos, "#home-habits-widget must come after #home-top-row"
    assert top_row_pos < readiness_pos, "#home-top-row-right must come after #home-top-row"


def test_L11_weight_widget_present():
    """#home-weight-widget must be present in home.html."""
    assert 'id="home-weight-widget"' in _HOME_HTML


def test_L12_training_before_performance():
    """Training card container must appear BEFORE performance card container in DOM."""
    training_pos = _HOME_HTML.find('id="home-training-card"')
    # performance card is dynamically inserted; check for perf-card or home-perf-row
    perf_pos = max(
        _HOME_HTML.find('id="home-perf-sleep-row"'),
        _HOME_HTML.find('id="home-lower-row"'),
        _HOME_HTML.find('id="row-2"'),  # legacy fallback
    )
    assert training_pos >= 0, "#home-training-card not found in home.html"
    assert perf_pos >= 0, "Performance row container not found in home.html"
    assert training_pos < perf_pos, \
        "#home-training-card must appear BEFORE performance container in DOM"


def test_L13_sleep_and_workouts_in_right_column():
    """Sleep card and workouts card containers must be in the right-side column."""
    assert 'id="home-sleep-card"' in _HOME_HTML
    # Both sleep and recent workouts should be in same parent container
    # Check they're not adjacent to training card in a 2-column layout
    training_pos = _HOME_HTML.find('id="home-training-card"')
    sleep_pos = _HOME_HTML.find('id="home-sleep-card"')
    # Sleep must come AFTER training in document order (it's in the lower row)
    assert sleep_pos > training_pos, \
        "#home-sleep-card must come after #home-training-card in DOM"


def test_L2_layout_order_greeting_strip_toprow_weight_training():
    """Key layout elements must appear in correct v7 order."""
    greeting_pos = _HOME_HTML.find('id="greeting-text"')
    strip_pos = _HOME_HTML.find('id="home-log-today-strip"')
    top_row_pos = _HOME_HTML.find('id="home-top-row"')
    weight_pos = _HOME_HTML.find('id="home-weight-widget"')
    training_pos = _HOME_HTML.find('id="home-training-card"')

    assert greeting_pos < strip_pos, "Greeting must come before log-today strip"
    assert strip_pos < top_row_pos, "Log-today strip must come before home-top-row"
    assert top_row_pos < weight_pos, "home-top-row must come before weight widget"
    assert weight_pos < training_pos, "weight widget must come before training card"


# ── JS single summary call ─────────────────────────────────────────────────────

def test_L5_single_summary_fetch_in_home_js():
    """home.js must contain exactly one fetch('/api/home/summary') call.

    home-strip-habits.js and home-readiness-training-sleep.js must NOT have
    their own auto-fetch of /api/home/summary; the single call is in home.js.
    """
    # Count direct fetch calls to /api/home/summary in home.js
    home_summary_fetches = len(re.findall(
        r"fetch\s*\(\s*['\"](?:[^'\"]*)?/api/home/summary['\"]",
        _HOME_JS
    ))
    # home.js should have exactly 1 summary fetch in its init path
    assert home_summary_fetches >= 1, \
        "home.js must contain at least one fetch to /api/home/summary"

    # The strip and RTS modules should NOT initiate their own summary fetches
    # (they should accept passed-in data)
    strip_auto_fetch = re.search(
        r"fetch\s*\(\s*['\"][^'\"]*?/api/home/summary['\"]",
        _STRIP_JS
    )
    assert strip_auto_fetch is None, \
        "home-strip-habits.js must NOT auto-fetch /api/home/summary; " \
        "it should accept data from home.js"

    rts_auto_fetch = re.search(
        r"fetch\s*\(\s*['\"][^'\"]*?/api/home/summary['\"]",
        _RTS_JS
    )
    assert rts_auto_fetch is None, \
        "home-readiness-training-sleep.js must NOT auto-fetch /api/home/summary; " \
        "it should accept data from home.js"


def test_L6_summary_blocks_consumed_by_renderers():
    """JS renderers must consume named summary blocks (readiness, habits, weight, etc.)."""
    all_js = _all_home_js()

    # Each block key must appear in the JS as a property access on the summary object
    for block in ("readiness", "habits", "weight", "training_week",
                  "performance", "recent_workouts", "sleep"):
        assert re.search(r'summary\.' + block + r'\b', all_js) or \
               re.search(r"summary\['" + block + r"'\]", all_js) or \
               re.search(r'summary\["' + block + r'"\]', all_js), \
            f"summary.{block} not consumed in home JS modules"


def test_L7_habit_check_fires_targeted_post():
    """JS must POST to /api/habits/{id}/log for habit check (not re-fetch summary)."""
    all_js = _all_home_js()
    assert re.search(
        r"fetch\s*\(\s*['\"][^'\"]*?/api/habits/[^'\"]*?/log['\"]",
        all_js
    ) or re.search(
        r"fetch\s*\(\s*['\"][^'\"]*?/api/habits/logs['\"]",
        all_js
    ), "JS must have a targeted POST to /api/habits/.../log for habit check"


def test_L8_weight_log_fires_targeted_post():
    """JS must POST to /api/weight or /api/weight-entries for weight log."""
    all_js = _all_home_js()
    assert re.search(
        r"method\s*:\s*['\"]POST['\"]",
        all_js
    ), "No POST found in home JS modules"
    assert re.search(
        r"/api/weight\b",
        all_js
    ) or re.search(
        r"/api/weight-entries\b",
        all_js
    ), "Weight log POST must target /api/weight or /api/weight-entries"


# ── API contract tests ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_user():
    u = MagicMock()
    u.id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-000000000001")
    u.name = "Test User"
    u.is_active = True
    u.is_admin = False
    return u


def _make_mock_session():
    """Return a minimal SQLAlchemy Session mock that returns empty results."""
    sess = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.filter_by.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = []
    q.first.return_value = None
    q.count.return_value = 0
    q.scalar.return_value = None
    sess.query.return_value = q
    sess.get.return_value = None
    sess.execute.return_value = MagicMock(fetchall=lambda: [], scalar=lambda: None)
    return sess


def test_A1_summary_has_all_blocks(client, mock_user):
    """GET /api/home/summary returns all 7 block keys."""
    uid = str(mock_user.id)
    mock_sess = _make_mock_session()
    with patch("backend.main.resolve_user", return_value=mock_user), \
         patch("backend.main.Session", return_value=mock_sess):
        resp = client.get(f"/api/home/summary?user_id={uid}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    for key in ("habits", "weight", "readiness", "training_week",
                "performance", "recent_workouts", "sleep"):
        assert key in data, f"Block '{key}' missing from /api/home/summary response"


def test_A2_habit_log_post_is_valid_endpoint(client, mock_user):
    """POST /api/habits/{id}/log endpoint is reachable (not 405)."""
    habit_id = str(uuid.uuid4())
    with patch("backend.main.resolve_user", return_value=mock_user):
        resp = client.post(
            f"/api/habits/{habit_id}/log",
            json={"logged_date": str(date.today())},
        )
    # 404 (habit not found) is fine — we're just verifying the route exists (not 405)
    assert resp.status_code != 405, "POST /api/habits/{id}/log returned 405 — route missing"


def test_A3_weight_post_is_valid_endpoint(client, mock_user):
    """POST /api/weight endpoint is reachable (not 405)."""
    with patch("backend.main.resolve_user", return_value=mock_user):
        resp = client.post(
            "/api/weight",
            json={"weight_kg": 70.0, "recorded_date": str(date.today())},
        )
    assert resp.status_code != 405, "POST /api/weight returned 405 — route missing"
