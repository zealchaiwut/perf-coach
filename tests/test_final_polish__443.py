"""Tests for issue #443: Final polish — docs, dead code, cross-links, smoke test.

AC items covered:
  (a) docs/mockups/home-redesign-v7.html exists in the repo
  (b) docs/mockups/README.md marks home-desktop.html and home-mobile.html as
      superseded by home-redesign-v7
  (c) docs/features/home.md exists and documents /api/home/summary contract
  (d) home.md documents every rendered block and its data source
  (e) home.md documents per-block degradation behavior (null/error)
  (f) home.md documents inline vs link-out actions
  (g) home.md documents single-call load strategy and rationale
  (h) home.md documents Bangkok-time (UTC+7) day-boundary logic
  (i) home.js does not contain old per-widget fetch calls to
      /api/home/readiness, /api/home/weight-summary,
      /api/home/weekly-summary
  (j) home.html no longer loads home-habits.js
  (k) home.html no longer loads home-readiness.js (old widget module)
  (l) init() in home.js does not call loadHabitsCard or loadHabitsStatsCard
  (m) init() in home.js does not call loadWeeklySummaryCard
  (n) init() in home.js does not call loadRow3 as a standalone top-level call
  (o) loadRecentWorkoutsCard in home.js does not make its own
      /api/home/recent-workouts fetch (uses summary block passed from caller)
  (p) nav.js LINKS array contains /home so all pages have a link back to home
  (q) habits.html, weight.html, training-log.html, settings.html each load nav.js
  (r) outbound link "All habits" (/habits) exists in home JS modules
  (s) outbound link "Open weight" (/weight) exists in home JS modules
  (t) outbound link "Edit target" (/weight/targets) exists in home JS modules
  (u) outbound link "All tracks" (/settings#personal-records) exists in home JS modules
  (v) outbound link "Training log" (/log) exists in home JS modules
  (w) CHANGELOG.md contains the required home redesign entry
  (x) docs/home-redesign-investigation.md has a Post-ship verification section
  (y) /api/home/summary endpoint returns 200 with all seven block keys
"""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_ROOT = pathlib.Path(__file__).parent.parent
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()
_STRIP_HABITS_JS = (_ROOT / "frontend" / "js" / "home-strip-habits.js").read_text()
_RTS_JS = (_ROOT / "frontend" / "js" / "home-readiness-training-sleep.js").read_text()
_WEIGHT_TREND_JS = (_ROOT / "frontend" / "js" / "home-weight-trend.js").read_text()
_MORNING_JS = (_ROOT / "frontend" / "js" / "home-morning.js").read_text()
_NAV_JS = (_ROOT / "frontend" / "js" / "nav.js").read_text()

client = TestClient(app)


# ── (a) Mockup file exists ────────────────────────────────────────────────────

def test_home_v7_mockup_exists():
    mockup = _ROOT / "docs" / "mockups" / "home-redesign-v7.html"
    assert mockup.is_file(), "docs/mockups/home-redesign-v7.html must exist in the repo"


# ── (b) Mockups README supersedes old home mockups ───────────────────────────

def test_mockups_readme_supersedes_home_desktop():
    readme = (_ROOT / "docs" / "mockups" / "README.md").read_text()
    assert "home-desktop.html" in readme, \
        "docs/mockups/README.md must reference home-desktop.html"
    assert "superseded" in readme.lower(), \
        "docs/mockups/README.md must mark old home mockups as superseded"


def test_mockups_readme_supersedes_home_mobile():
    readme = (_ROOT / "docs" / "mockups" / "README.md").read_text()
    assert "home-mobile.html" in readme, \
        "docs/mockups/README.md must reference home-mobile.html"


def test_mockups_readme_references_v7():
    readme = (_ROOT / "docs" / "mockups" / "README.md").read_text()
    assert "home-redesign-v7" in readme, \
        "docs/mockups/README.md must reference home-redesign-v7 as current"


# ── (c) home.md exists with /api/home/summary ────────────────────────────────

def test_home_feature_doc_exists():
    doc = _ROOT / "docs" / "features" / "home.md"
    assert doc.is_file(), "docs/features/home.md must exist"


def test_home_doc_summary_endpoint():
    doc = (_ROOT / "docs" / "features" / "home.md").read_text()
    assert "/api/home/summary" in doc, \
        "home.md must document the /api/home/summary request/response contract"


# ── (d) home.md documents all rendered blocks ─────────────────────────────────

@pytest.mark.parametrize("block", ["habits", "weight", "readiness", "training_week",
                                    "performance", "recent_workouts", "sleep"])
def test_home_doc_block_documented(block):
    doc = (_ROOT / "docs" / "features" / "home.md").read_text()
    assert block in doc, \
        f"home.md must document the '{block}' block and its data source"


# ── (e) home.md documents degradation behavior ───────────────────────────────

def test_home_doc_degradation():
    doc = (_ROOT / "docs" / "features" / "home.md").read_text()
    assert "null" in doc.lower() or "degradat" in doc.lower(), \
        "home.md must document per-block null/error degradation behavior"


# ── (f) home.md documents inline vs link-out actions ─────────────────────────

def test_home_doc_inline_actions():
    doc = (_ROOT / "docs" / "features" / "home.md").read_text()
    assert "inline" in doc.lower(), \
        "home.md must document inline actions (habit check/uncheck, weight stepper)"


def test_home_doc_linkout_actions():
    doc = (_ROOT / "docs" / "features" / "home.md").read_text()
    assert "link" in doc.lower(), \
        "home.md must document link-out actions (habit management, weight target, etc.)"


# ── (g) home.md documents single-call load strategy ──────────────────────────

def test_home_doc_single_call_strategy():
    doc = (_ROOT / "docs" / "features" / "home.md").read_text()
    assert "single" in doc.lower() or "one call" in doc.lower() or "single-call" in doc.lower(), \
        "home.md must document the single-call load strategy and its rationale"


# ── (h) home.md documents Bangkok-time day boundary ──────────────────────────

def test_home_doc_bangkok_time():
    doc = (_ROOT / "docs" / "features" / "home.md").read_text()
    assert "bangkok" in doc.lower() or "utc+7" in doc.lower() or "asia/bangkok" in doc.lower(), \
        "home.md must document Bangkok-time (UTC+7) day-boundary logic"


# ── (i) No old per-widget fetch calls in home.js ─────────────────────────────

def test_no_home_readiness_fetch_in_home_js():
    assert "/api/home/readiness" not in _HOME_JS, \
        "home.js must not call /api/home/readiness (replaced by /api/home/summary)"


def test_no_home_weight_summary_fetch_in_home_js():
    assert "/api/home/weight-summary" not in _HOME_JS, \
        "home.js must not call /api/home/weight-summary (replaced by /api/home/summary)"


def test_no_home_weekly_summary_fetch_in_home_js():
    assert "/api/home/weekly-summary" not in _HOME_JS, \
        "home.js must not call /api/home/weekly-summary (replaced by /api/home/summary)"


# ── (j) home.html no longer loads home-habits.js ─────────────────────────────

def test_home_html_no_home_habits_js():
    assert "home-habits.js" not in _HOME_HTML, \
        "home.html must not load home-habits.js — this module is dead code"


# ── (k) home.html does not load any old readiness-only widget module ──────────

def test_home_html_no_standalone_readiness_widget():
    assert "home-readiness.js" not in _HOME_HTML, \
        "home.html must not load home-readiness.js (readiness is now part of home-readiness-training-sleep.js)"


# ── (l) init() does not call dead habits card functions ──────────────────────

def test_init_no_loadHabitsCard():
    assert "loadHabitsCard(" not in _HOME_JS, \
        "home.js must not contain loadHabitsCard — removed as dead code"


def test_init_no_loadHabitsStatsCard():
    assert "loadHabitsStatsCard(" not in _HOME_JS, \
        "home.js must not contain loadHabitsStatsCard — removed as dead code"


# ── (m) init() does not call loadWeeklySummaryCard ───────────────────────────

def test_init_no_loadWeeklySummaryCard():
    assert "loadWeeklySummaryCard(" not in _HOME_JS, \
        "home.js must not contain loadWeeklySummaryCard — removed as dead code"


# ── (n) loadRow3 dead call removed from init ─────────────────────────────────

def test_no_loadRow3_in_home_js():
    assert "loadRow3(" not in _HOME_JS, \
        "home.js must not contain loadRow3 — removed as dead code (row-3 container absent from home.html)"


# ── (o) loadRecentWorkoutsCard does not fetch independently ──────────────────

def test_recent_workouts_no_standalone_fetch():
    assert "/api/home/recent-workouts" not in _HOME_JS, \
        "home.js must not call /api/home/recent-workouts independently; " \
        "use the summary.recent_workouts block passed from init()"


# ── (p) nav.js has /home in LINKS ────────────────────────────────────────────

def test_nav_js_has_home_link():
    assert "href: '/home'" in _NAV_JS or 'href: "/home"' in _NAV_JS, \
        "nav.js LINKS must contain an entry with href: '/home'"


# ── (q) Key pages load nav.js ────────────────────────────────────────────────

@pytest.mark.parametrize("page", ["habits.html", "weight.html", "training-log.html", "settings.html"])
def test_page_loads_nav_js(page):
    html = (_ROOT / "frontend" / "pages" / page).read_text()
    assert "nav.js" in html, \
        f"{page} must load nav.js to provide the /home link in the navigation"


# ── (r-v) Outbound links from home JS modules ────────────────────────────────

def test_outbound_link_all_habits():
    all_js = _HOME_JS + _STRIP_HABITS_JS + _RTS_JS
    assert "'/habits'" in all_js or '"/habits"' in all_js or "href=\"/habits" in all_js, \
        "home JS modules must contain an 'All habits' link to /habits"


def test_outbound_link_open_weight():
    # Weight outbound link lives in home-weight-trend.js (and morning weigh-in
    # helpers); scan those modules too after the home layout split.
    all_js = _HOME_JS + _STRIP_HABITS_JS + _RTS_JS + _WEIGHT_TREND_JS + _MORNING_JS
    assert "'/weight'" in all_js or '"/weight"' in all_js or 'href="/weight"' in all_js or "href='/weight'" in all_js, \
        "home JS modules must contain an 'Open weight' link to /weight"


def test_outbound_link_edit_target():
    all_js = _HOME_JS + _STRIP_HABITS_JS + _RTS_JS
    assert "/weight/targets" in all_js, \
        "home JS modules must contain an 'Edit target' link to /weight/targets"


def test_outbound_link_all_tracks():
    all_js = _HOME_JS + _STRIP_HABITS_JS + _RTS_JS
    assert "/settings#personal-records" in all_js or "/settings" in all_js, \
        "home JS modules must contain an 'All tracks' link to /settings#personal-records"


def test_outbound_link_training_log():
    all_js = _HOME_JS + _STRIP_HABITS_JS + _RTS_JS
    assert "'/log'" in all_js or '"/log"' in all_js or "href=\"/log" in all_js or "href='/log'" in all_js, \
        "home JS modules must contain a 'Training log' link to /log"


# ── (w) CHANGELOG has required entry ─────────────────────────────────────────

def test_changelog_home_redesign_entry():
    changelog = (_ROOT / "CHANGELOG.md").read_text()
    assert "Home redesign" in changelog or "home redesign" in changelog.lower(), \
        "CHANGELOG.md must contain a home redesign entry"
    required_terms = ["habit", "weight", "summary"]
    for term in required_terms:
        assert term in changelog.lower(), \
            f"CHANGELOG.md home redesign entry must mention '{term}'"


def test_changelog_entry_mentions_single_call():
    changelog = (_ROOT / "CHANGELOG.md").read_text()
    assert "single-call" in changelog.lower() or "single call" in changelog.lower(), \
        "CHANGELOG.md home redesign entry must mention 'single-call load'"


# ── (x) Investigation doc has Post-ship verification section ─────────────────

def test_investigation_doc_has_postship_section():
    doc = (_ROOT / "docs" / "home-redesign-investigation.md").read_text()
    assert "post-ship" in doc.lower() or "post ship" in doc.lower(), \
        "docs/home-redesign-investigation.md must have a 'Post-ship verification' section"


def test_investigation_doc_records_smoke_results():
    doc = (_ROOT / "docs" / "home-redesign-investigation.md").read_text()
    assert "smoke" in doc.lower() or "verification" in doc.lower(), \
        "docs/home-redesign-investigation.md must record smoke test / verification results"


# ── (y) /api/home/summary returns correct shape ──────────────────────────────

def test_home_summary_endpoint_requires_user():
    # Without user_id the endpoint should return 404 (not 500)
    res = client.get("/api/home/summary")
    assert res.status_code == 404


def test_home_summary_endpoint_shape_with_mock(monkeypatch):
    # Verify the endpoint returns all 7 block keys (each may be null)
    import uuid
    from unittest.mock import MagicMock, patch

    from backend.main import resolve_user

    uid = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.id = uuid.UUID(uid)
    mock_s = MagicMock()
    mock_s.get.return_value = mock_user
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_s
    mock_cm.__exit__.return_value = False

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=mock_cm), \
             patch("backend.main._build_habits_block", return_value=None), \
             patch("backend.main._build_weight_block", return_value=None), \
             patch("backend.main._build_readiness_block", return_value=None), \
             patch("backend.main._build_training_week_block", return_value=None), \
             patch("backend.main.get_athlete_performance", return_value=None), \
             patch("backend.main._build_recent_workouts_block", return_value=None), \
             patch("backend.main._build_sleep_block", return_value=None), \
             patch("backend.main.get_planned_sessions", return_value={"days": []}), \
             patch("backend.main.get_readiness", return_value=None), \
             patch("backend.main._home_slim_primary_race", return_value=None):

            res = client.get("/api/home/summary")
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert res.status_code == 200
    body = res.json()
    for key in ("habits", "weight", "readiness", "training_week",
                "performance", "recent_workouts", "sleep", "week_days", "race"):
        assert key in body, f"home/summary response missing block key: '{key}'"
