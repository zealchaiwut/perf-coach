"""Tests for issue #393: MVP Polish — Bangkok time, /api/healthz, docs.

TDD: one test per Acceptance Criterion. Static checks for JS/HTML/docs;
live API checks hit http://127.0.0.1:9001.
"""
import importlib
import pathlib
import re
import sys

import httpx
import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
BASE = "http://127.0.0.1:9001"

HOME_JS = REPO_ROOT / "frontend" / "js" / "home.js"
HOME_HABITS_JS = REPO_ROOT / "frontend" / "js" / "home-habits.js"
TRAINING_LOG_HTML = REPO_ROOT / "frontend" / "pages" / "training-log.html"
HABITS_HTML = REPO_ROOT / "frontend" / "pages" / "habits.html"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
README = REPO_ROOT / "README.md"
TIME_PY = REPO_ROOT / "backend" / "utils" / "time.py"
MVP_FLOW_DOC = REPO_ROOT / "docs" / "mvp-flow-test.md"
MVP_FEATURE_DOC = REPO_ROOT / "docs" / "features" / "mvp-daily-use.md"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC: backend/utils/time.py exports now_bangkok() and today_bangkok() ──────

def test_time_py_exists():
    """AC: backend/utils/time.py must exist."""
    assert TIME_PY.exists(), "backend/utils/time.py not found"


def test_time_py_exports_now_bangkok():
    """AC: time.py exports now_bangkok()."""
    src = TIME_PY.read_text()
    assert "def now_bangkok" in src, "now_bangkok() not defined in backend/utils/time.py"


def test_time_py_exports_today_bangkok():
    """AC: time.py exports today_bangkok()."""
    src = TIME_PY.read_text()
    assert "def today_bangkok" in src, "today_bangkok() not defined in backend/utils/time.py"


def test_now_bangkok_returns_datetime():
    """AC: now_bangkok() returns a timezone-aware Bangkok datetime."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    sys.path.insert(0, str(REPO_ROOT))
    from backend.utils.time import now_bangkok
    result = now_bangkok()
    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    assert str(result.tzinfo) in ("Asia/Bangkok", "UTC+07:00")


def test_today_bangkok_returns_date():
    """AC: today_bangkok() returns a date object."""
    from datetime import date
    sys.path.insert(0, str(REPO_ROOT))
    from backend.utils.time import today_bangkok
    result = today_bangkok()
    assert isinstance(result, date)


# ── AC: GET /api/healthz returns 200 with {ok, version, env} ─────────────────

def test_healthz_returns_200(client):
    """AC: GET /api/healthz returns HTTP 200."""
    res = client.get("/api/healthz")
    assert res.status_code == 200


def test_healthz_response_shape(client):
    """AC: response body has ok, version, env keys."""
    body = client.get("/api/healthz").json()
    assert "ok" in body
    assert "version" in body
    assert "env" in body


def test_healthz_ok_is_true(client):
    """AC: ok field is exactly true (boolean)."""
    body = client.get("/api/healthz").json()
    assert body["ok"] is True


def test_healthz_version_is_string(client):
    """AC: version is a non-empty string."""
    body = client.get("/api/healthz").json()
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0


def test_healthz_env_is_string(client):
    """AC: env is a non-empty string."""
    body = client.get("/api/healthz").json()
    assert isinstance(body["env"], str)
    assert len(body["env"]) > 0


def test_healthz_no_auth_required():
    """AC: /api/healthz requires no authentication."""
    res = httpx.get(f"{BASE}/api/healthz", timeout=10)
    assert res.status_code == 200


def test_healthz_content_type_json(client):
    """AC: response content-type is JSON."""
    res = client.get("/api/healthz")
    assert "application/json" in res.headers.get("content-type", "")


# ── AC: Bangkok timezone — day boundary in Log Today ──────────────────────────

def test_home_js_uses_bangkok_for_today():
    """AC: home.js computes today's date in Bangkok timezone (not raw new Date())."""
    src = HOME_JS.read_text()
    # Should use Intl.DateTimeFormat or toLocaleDateString with Asia/Bangkok
    assert "Asia/Bangkok" in src, (
        "home.js must derive today's date using Asia/Bangkok timezone "
        "(Intl.DateTimeFormat or toLocaleDateString with timeZone:'Asia/Bangkok')"
    )


# ── AC: Week starts on Bangkok Monday ────────────────────────────────────────

def test_home_js_bangkok_monday():
    """AC: home.js week-start calculation uses Bangkok timezone."""
    src = HOME_JS.read_text()
    assert "Asia/Bangkok" in src, (
        "home.js must use Asia/Bangkok for week-start (Bangkok Monday) calculation"
    )


# ── AC: No widget shows undefined or NaN ──────────────────────────────────────

def test_home_js_guards_undefined_in_zone2():
    """AC: zone2 widget guards against undefined/NaN before rendering."""
    # home-habits.js or home.js must not render raw undefined
    for js_path in [HOME_JS, HOME_HABITS_JS]:
        if js_path.exists():
            src = js_path.read_text()
            # Must have null/undefined guard in value rendering (|| 0 or != null)
            assert ("|| 0" in src or "!= null" in src or "null ?" in src
                    or "?? 0" in src or "isNaN" in src), (
                f"{js_path.name} should guard numeric values against undefined/NaN"
            )


# ── AC: Empty state — training log shows friendly message ────────────────────

def test_training_log_empty_state_exists():
    """AC: training-log.html has a friendly empty-state element."""
    src = TRAINING_LOG_HTML.read_text()
    assert "log-empty-msg" in src or "empty-state" in src, (
        "training-log.html must contain a friendly empty state for no workouts"
    )


def test_training_log_empty_state_has_message():
    """AC: training-log empty state has user-friendly copy (no 'undefined' or 'NaN')."""
    src = TRAINING_LOG_HTML.read_text()
    assert "No workouts" in src or "Start tracking" in src or "Log your first" in src


# ── AC: Fresh user sees suggestion buttons ────────────────────────────────────

def test_habits_page_has_starter_section():
    """AC: habits.html has a starter/suggestion section for new users."""
    src = HABITS_HTML.read_text()
    assert "starter-section" in src or "starter-grid" in src, (
        "habits.html must contain a starter section shown to users with no habits"
    )


def test_habits_js_shows_starter_when_no_habits():
    """AC: habits.js shows starter section when active and archived habits are empty."""
    js_path = REPO_ROOT / "frontend" / "js" / "habits.js"
    assert js_path.exists()
    src = js_path.read_text()
    assert "starter-section" in src, "habits.js must toggle the starter section"
    assert "activeHabits.length === 0" in src or "habits.length === 0" in src, (
        "habits.js must show starters when no active habits exist"
    )


# ── AC: CHANGELOG has MVP daily-use foundation entry ─────────────────────────

def test_changelog_has_mvp_entry():
    """AC: CHANGELOG.md contains an MVP daily-use foundation entry."""
    assert CHANGELOG.exists(), "CHANGELOG.md not found"
    src = CHANGELOG.read_text()
    assert "MVP" in src and ("daily-use" in src.lower() or "daily use" in src.lower()), (
        "CHANGELOG.md must have an 'MVP daily-use foundation' entry"
    )


def test_changelog_mvp_mentions_habits():
    """AC: CHANGELOG MVP entry mentions the habits unified system."""
    src = CHANGELOG.read_text()
    assert "habit" in src.lower(), "CHANGELOG MVP entry must mention habits"


def test_changelog_mvp_mentions_zone2():
    """AC: CHANGELOG MVP entry mentions zone2_minutes tracking."""
    src = CHANGELOG.read_text()
    assert "zone2" in src.lower() or "zone 2" in src.lower(), (
        "CHANGELOG MVP entry must mention zone2_minutes tracking"
    )


def test_changelog_mvp_mentions_mobile():
    """AC: CHANGELOG MVP entry mentions mobile workout or daily-metrics form."""
    src = CHANGELOG.read_text()
    assert "mobile" in src.lower(), "CHANGELOG MVP entry must mention mobile features"


def test_changelog_mvp_mentions_weekly_widget():
    """AC: CHANGELOG MVP entry mentions weekly habits home widget."""
    src = CHANGELOG.read_text()
    assert "weekly" in src.lower() or "widget" in src.lower(), (
        "CHANGELOG MVP entry must mention the weekly habits home widget"
    )


# ── AC: README.md Features section reflects MVP ───────────────────────────────

def test_readme_features_section_exists():
    """AC: README.md has a Features section."""
    assert README.exists()
    src = README.read_text()
    assert "## Features" in src, "README.md must have a ## Features section"


def test_readme_features_mentions_habits():
    """AC: README Features section mentions habits (unified system)."""
    src = README.read_text()
    assert "habit" in src.lower()


def test_readme_features_mentions_zone2():
    """AC: README Features section mentions Zone 2 or zone2_minutes."""
    src = README.read_text()
    assert "zone 2" in src.lower() or "zone2" in src.lower(), (
        "README Features section should mention Zone 2 tracking"
    )


def test_readme_features_mentions_weekly_widget():
    """AC: README Features section mentions the weekly habits widget."""
    src = README.read_text()
    assert "weekly" in src.lower() and "widget" in src.lower() or "weekly habits" in src.lower(), (
        "README should mention the weekly habits home widget"
    )


# ── AC: docs/mvp-flow-test.md exists ─────────────────────────────────────────

def test_mvp_flow_test_doc_exists():
    """AC: docs/mvp-flow-test.md must exist."""
    assert MVP_FLOW_DOC.exists(), "docs/mvp-flow-test.md not found"


def test_mvp_flow_test_doc_has_content():
    """AC: docs/mvp-flow-test.md documents timing and flow steps."""
    src = MVP_FLOW_DOC.read_text()
    assert len(src.strip()) > 100, "docs/mvp-flow-test.md must have substantive content"
    assert "minute" in src.lower() or "timing" in src.lower() or "flow" in src.lower()


# ── AC: docs/features/mvp-daily-use.md exists and covers key topics ──────────

def test_mvp_daily_use_doc_exists():
    """AC: docs/features/mvp-daily-use.md must exist."""
    assert MVP_FEATURE_DOC.exists(), "docs/features/mvp-daily-use.md not found"


def test_mvp_daily_use_doc_covers_log_metrics():
    """AC: doc explains how to log metrics."""
    src = MVP_FEATURE_DOC.read_text()
    assert "log" in src.lower() and "metric" in src.lower(), (
        "docs/features/mvp-daily-use.md must explain how to log metrics"
    )


def test_mvp_daily_use_doc_covers_workouts():
    """AC: doc explains how to log workouts."""
    src = MVP_FEATURE_DOC.read_text()
    assert "workout" in src.lower(), (
        "docs/features/mvp-daily-use.md must explain how to log workouts"
    )


def test_mvp_daily_use_doc_covers_habits():
    """AC: doc explains how to manage habits."""
    src = MVP_FEATURE_DOC.read_text()
    assert "habit" in src.lower(), (
        "docs/features/mvp-daily-use.md must explain how to manage habits"
    )


def test_mvp_daily_use_doc_covers_weekly_widget():
    """AC: doc explains how to interpret the weekly widget."""
    src = MVP_FEATURE_DOC.read_text()
    assert "weekly" in src.lower() or "widget" in src.lower(), (
        "docs/features/mvp-daily-use.md must explain how to interpret the weekly widget"
    )
