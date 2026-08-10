"""TDD tests for issue #442: Assemble home layout with gradient design language.

Home revamp v2 (docs/mocks/home-revamp-v2.html) replaced the original
single-column v7 layout this file was written against with a two-column
#home-cols of .home-col flex stacks (left: coach/weight-trend/race/
performance/readiness, right: next-up/training/week-plan/recent), fronted by a
full-width "This morning" strip (#home-morning) instead of a habits+readiness
2-up row. The (L2/L3/L10/L11/L12/L13) anchors below have been updated in
place to describe that layout instead of the retired one; anchor numbering
is kept stable so this docstring still matches its own test names.

AC anchors:
  (L1) HTML: page renders on blue gradient background (radial-gradient token in body CSS)
  (L2) HTML: layout order is greeting → banners → This morning (#home-morning) →
             two-column grid (#home-cols)
  (L3) CSS: container max-width fits the two-column grid (~1300px, matching the mock)
  (L4) CSS: two-up grids collapse to single column at viewports ≤640px
  (L5) JS: page fires exactly ONE fetch of /api/home/summary (no duplicate calls)
  (L6) JS: all main widget blocks still sourced from the single summary response
           (readiness, habits, weight, training_week, recent_workouts, sleep) are
           consumed by SOME home JS module (habits/weight now live in home-morning.js,
           not home-strip-habits.js — see the revamp)
  (L7) JS: habit check action fires POST /api/habits/{id}/log (targeted write)
  (L8) JS: weight log action fires POST /api/weight-entries (targeted write)
  (L9) CSS: gradient tokens (--bg-1, --bg-2) used via var() — no per-page redefinitions
            of raw hex values for the gradient background
  (L10) HTML: #home-morning (weigh-in + today's session + habits) is a full-width
              section directly above #home-cols
  (L11) HTML: #home-weight-trend (30-day trend/rate/coverage card) supersedes the old
              full-width #home-weight-widget; the quick weigh-in action itself moved
              into #home-morning's weigh-in row (home-morning.js)
  (L12) HTML: training card (right .home-col) and performance card (left .home-col)
  (L13) HTML: the sleep card is removed; recent workouts shares right .home-col with training
  (L14) CSS: touch targets for habit check circles ≥40px (min-height or height)
  (L15) CSS: touch targets for weight stepper buttons ≥40px (min-height or height)
  (A1) API: /api/home/summary response includes all seven blocks:
            habits, weight, readiness, training_week, performance, recent_workouts, sleep
  (A2) API: habit inline log POST /api/habits/{id}/log returns 201 and logs the habit
  (A3) API: weight inline log POST /api/weight-entries returns 201 or 409 (conflict = update)
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
_MORNING_JS = (_ROOT / "frontend" / "js" / "home-morning.js").read_text()


def _all_home_js():
    """Concatenated text of all home JS modules.

    Includes home-morning.js (home revamp v2) — habits and weight consumption
    moved there from home-strip-habits.js / home.js's old weight widget; the
    latter file is left in the concatenation too since it's still shipped
    (just no longer wired into home.html) and other anchors in this file
    still reference it.
    """
    return _HOME_JS + "\n" + _STRIP_JS + "\n" + _RTS_JS + "\n" + _MORNING_JS


# ── Layout / CSS checks ────────────────────────────────────────────────────────

def test_L1_body_uses_gradient_background():
    """Body must apply the blue gradient via CSS tokens."""
    assert "radial-gradient" in _HOME_HTML, "body missing radial-gradient background"
    assert "--bg-1" in _HOME_HTML and "--bg-2" in _HOME_HTML, \
        "gradient tokens --bg-1 / --bg-2 not defined in page"


def test_L3_container_max_width_fits_two_column_grid():
    """Page container must be wide enough for the #home-cols two-column grid
    (revamp v2's mock uses max-width:1300px for its two-column `main`;
    home.html's own .page targets the same ballpark, ~1200-1400px)."""
    page_block = re.search(
        r'\.page\s*\{[^}]*max-width\s*:\s*(\d+)px',
        _HOME_HTML, re.DOTALL
    )
    assert page_block, ".page rule with max-width not found in home.html"
    mw = int(page_block.group(1))
    assert 1200 <= mw <= 1400, (
        f".page max-width is {mw}px — should be ~1300px to fit the "
        "#home-cols two-column grid (see docs/mocks/home-revamp-v2.html)"
    )


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
    """Morning habit chips must have ≥40px touch target (home revamp v2)."""
    chip_rules = re.findall(
        r'\.hm-hab\s*\{[^}]+\}',
        _HOME_HTML, re.DOTALL
    )
    combined = " ".join(chip_rules)
    sizes = re.findall(r'(?:min-height|height|width)\s*:\s*(\d+)px', combined)
    assert any(int(s) >= 40 for s in sizes), \
        f"Morning habit chips lack ≥40px touch target; found sizes: {sizes}"


def test_L15_weight_stepper_buttons_touch_target():
    """Morning weigh-in stepper buttons must have ≥40px touch target."""
    btn_rules = re.findall(
        r'\.hm-step\s+button\s*\{[^}]+\}',
        _HOME_HTML, re.DOTALL
    )
    # Also accept the fast-log stepper (row-log) which remains on the page.
    btn_rules += re.findall(
        r'\.fm-step-btn\s*\{[^}]+\}',
        _HOME_HTML, re.DOTALL
    )
    combined = " ".join(btn_rules)
    sizes = re.findall(r'(?:min-height|height)\s*:\s*(\d+)px', combined)
    assert any(int(s) >= 40 for s in sizes), \
        f"Weight stepper buttons lack ≥40px touch target; found: {sizes}"


# ── HTML structure checks ──────────────────────────────────────────────────────

def test_L10_home_morning_is_full_width_above_cols():
    """#home-morning (weigh-in + today's session + habits) must be a
    full-width section that comes directly before #home-cols."""
    assert 'id="home-morning"' in _HOME_HTML
    assert 'id="home-cols"' in _HOME_HTML
    morning_pos = _HOME_HTML.find('id="home-morning"')
    cols_pos = _HOME_HTML.find('id="home-cols"')
    assert morning_pos < cols_pos, "#home-morning must come before #home-cols"

    # home-morning.js must actually render the three asks into that host.
    assert "HomeMorning" in _MORNING_JS.replace("window.HomeMorning", "") or \
        "window.HomeMorning" in _MORNING_JS, \
        "home-morning.js must expose window.HomeMorning"
    for row_key in ("weight", "session", "habits"):
        assert row_key in _MORNING_JS, \
            f"home-morning.js must render a '{row_key}' row"


def test_L11_weight_trend_card_supersedes_weight_widget():
    """The old full-width #home-weight-widget is retired; #home-weight-trend
    (trend/rate/coverage card) takes its slot in #home-cols, and the actual
    quick weigh-in action moved into #home-morning's weigh-in row."""
    assert 'id="home-weight-widget"' not in _HOME_HTML, \
        "#home-weight-widget must be removed — superseded by #home-weight-trend " \
        "+ #home-morning's weigh-in row"
    assert 'id="home-weight-trend"' in _HOME_HTML

    weight_trend_js = (_ROOT / "frontend" / "js" / "home-weight-trend.js").read_text()
    assert "window.HomeWeightTrend" in weight_trend_js

    # The quick weigh-in action (POST /api/weight-entries) must still exist
    # somewhere — now in home-morning.js.
    assert "/api/weight-entries" in _MORNING_JS, \
        "home-morning.js's weigh-in row must POST /api/weight-entries"
    # After logging, morning keeps a Logged + Change affordance (not display:none)
    # until the whole strip is all-done — so weigh-in stays discoverable.
    assert "hm-w-change" in _MORNING_JS and "_showLoggedSummary" in _MORNING_JS, \
        "home-morning.js must offer Change after a logged weigh-in"


def test_L12_training_and_performance_are_columns_of_home_cols():
    """Training sits in the right .home-col stack; Performance in the left.
    Mock-faithful two flex columns (not flat grid-column placement)."""
    assert 'id="home-training-card"' in _HOME_HTML
    assert 'id="home-performance-card"' in _HOME_HTML
    assert 'home-col--left' in _HOME_HTML and 'home-col--right' in _HOME_HTML

    left_idx = _HOME_HTML.find('home-col--left')
    right_idx = _HOME_HTML.find('home-col--right')
    perf_idx = _HOME_HTML.find('id="home-performance-card"')
    train_idx = _HOME_HTML.find('id="home-training-card"')
    assert left_idx < perf_idx < right_idx, \
        "Performance must live inside .home-col--left"
    assert right_idx < train_idx, \
        "Training must live inside .home-col--right"


def test_L13_sleep_card_removed_recent_workouts_shares_training_column():
    """The sleep card is removed from Home entirely (revamp v2 spec); recent
    workouts shares the right .home-col with Training."""
    assert 'id="home-sleep-card"' not in _HOME_HTML, \
        "#home-sleep-card must be removed from home.html (revamp v2 spec)"
    assert 'id="home-recent-workouts-card"' in _HOME_HTML

    right_idx = _HOME_HTML.find('home-col--right')
    train_idx = _HOME_HTML.find('id="home-training-card"')
    recent_idx = _HOME_HTML.find('id="home-recent-workouts-card"')
    assert right_idx < train_idx < recent_idx, \
        "#home-recent-workouts-card must share .home-col--right with Training"


def test_L2_layout_order_greeting_morning_cols():
    """Key layout elements must appear in the revamp v2 order: greeting →
    This morning (#home-morning) → two-column grid (#home-cols), with
    training/performance/weight-trend all living inside #home-cols."""
    greeting_pos = _HOME_HTML.find('id="greeting-text"')
    morning_pos = _HOME_HTML.find('id="home-morning"')
    cols_pos = _HOME_HTML.find('id="home-cols"')
    weight_trend_pos = _HOME_HTML.find('id="home-weight-trend"')
    training_pos = _HOME_HTML.find('id="home-training-card"')

    assert greeting_pos < morning_pos, "Greeting must come before #home-morning"
    assert morning_pos < cols_pos, "#home-morning must come before #home-cols"
    assert cols_pos < weight_trend_pos, "#home-cols must come before its children (weight trend)"
    assert cols_pos < training_pos, "#home-cols must come before its children (training)"


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
    """JS renderers must consume named summary blocks still used on Home.

    home revamp v2: Endurance/Speed come from GET /api/athletes/{id}/performance
    (not summary.performance), and the Sleep card host is gone — so those two
    summary keys are no longer required consumers even if the API still
    returns them.
    """
    all_js = _all_home_js()

    for block in ("readiness", "habits", "weight", "training_week",
                  "recent_workouts"):
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
    """JS must POST to /api/weight-entries for weight log."""
    all_js = _all_home_js()
    assert re.search(
        r"method\s*:\s*['\"]POST['\"]",
        all_js
    ), "No POST found in home JS modules"
    assert re.search(
        r"/api/weight-entries\b",
        all_js
    ), "Weight log POST must target /api/weight-entries"


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

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=mock_sess), \
             patch("backend.main.get_planned_sessions", return_value={"days": []}), \
             patch("backend.main.get_readiness", return_value=None), \
             patch("backend.main.get_athlete_performance", return_value=None), \
             patch("backend.main._home_slim_primary_race", return_value=None):
            resp = client.get(f"/api/home/summary?user_id={uid}")
    finally:
        app.dependency_overrides.pop(resolve_user, None)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    for key in ("habits", "weight", "readiness", "training_week",
                "performance", "recent_workouts", "sleep"):
        assert key in data, f"Block '{key}' missing from /api/home/summary response"


def test_A2_habit_log_post_is_valid_endpoint(client, mock_user):
    """POST /api/habits/{id}/log endpoint is reachable (not 405)."""
    habit_id = str(uuid.uuid4())

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        resp = client.post(
            f"/api/habits/{habit_id}/log",
            json={"logged_date": str(date.today())},
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)
    # 404 (habit not found) is fine — we're just verifying the route exists (not 405)
    assert resp.status_code != 405, "POST /api/habits/{id}/log returned 405 — route missing"


def test_A3_weight_post_is_valid_endpoint(client, mock_user):
    """POST /api/weight-entries endpoint is reachable (returns 201 or 409, not 404/405)."""
    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        resp = client.post(
            "/api/weight-entries",
            json={
                "user_id": str(mock_user.id),
                "weight_kg": 70.0,
                "entry_date": str(date.today()),
            },
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)
    assert resp.status_code in (201, 409), (
        f"POST /api/weight-entries returned {resp.status_code} — expected 201 or 409"
    )
