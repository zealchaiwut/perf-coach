"""Tests for issue #353: Wire Home Page Weight Widget to Real API

TDD — each test is anchored to one Acceptance Criterion.

(AC-1)  Widget calls GET /api/home/weight-summary on mount
(AC-2)  current_weight renders large
(AC-3)  7-day average renders below current weight
(AC-4)  "This week" delta pill with direction-aware coloring
(AC-5)  "This month" delta pill with same direction logic
(AC-6)  SVG polyline sparkline from ma30 (container width × 40 px, blue accent)
(AC-7)  Progress bar when target exists (progress_pct); status pill colored
(AC-8)  "Set a target →" link to /weight/targets when no target
(AC-9)  Empty state: "No weight logged yet" + link to /weight
(AC-10) Loading state: skeleton UI while fetch in flight
(AC-11) Error state: "Could not load weight data" + retry button
(AC-12) Click anywhere on widget navigates to /weight
(AC-13) API: 401 for unauthenticated requests (session auth, no user_id param)
(AC-14) API: correct response shape with entries present
(AC-15) API: null current_weight and empty ma30 when no entries
(AC-16) API: target block includes direction, progress_pct, status_label
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as DBSession

from backend.auth import COOKIE_NAME, CSRF_COOKIE_NAME, generate_csrf_token, hash_password
from backend.models import User
from tests._admin_helpers import admin_cookies as _admin_cookies

# ── Root detection ────────────────────────────────────────────────────────────

_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_CODER_ROOT, _TESTER_ROOT):
        if (root / "frontend" / "js" / "home.js").exists():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today()
TODAY_ISO = TODAY.isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "wt353-test-pw"

_env_vals = dotenv_values(_TESTER_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_authed_client(username: str):
    with httpx.Client(base_url=BASE, timeout=10) as fresh:
        res = fresh.post("/api/users", json={"name": username}, cookies=_admin_cookies())
        assert res.status_code == 201, res.text
        user_id = res.json()["id"]

        pw_hash = hash_password(_TEST_PASSWORD)
        with DBSession(engine) as db:
            user = db.get(User, uuid.UUID(user_id))
            assert user is not None
            user.password_hash = pw_hash
            db.commit()

        login_res = fresh.post(
            "/api/auth/login",
            json={"username": username, "password": _TEST_PASSWORD},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        session_cookie = login_res.cookies.get("session")
        assert session_cookie, "Login must set session cookie"

    csrf_token = generate_csrf_token()
    authed = httpx.Client(
        base_url=BASE,
        timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return user_id, authed


def _seed_weight_entry(user_id: str, date_iso: str, weight_kg: float) -> str:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO weight_entries (user_id, entry_date, weight_kg) "
                "VALUES (:uid, :d, :w) RETURNING id"
            ),
            {"uid": user_id, "d": date_iso, "w": weight_kg},
        ).fetchone()
    return str(row.id)


def _seed_weight_target(
    user_id: str,
    start_w: float,
    target_w: float,
    start_date: str,
    target_date: str,
) -> str:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO weight_targets "
                "(user_id, start_weight_kg, start_date, target_weight_kg, target_date) "
                "VALUES (:uid, :sw, :sd, :tw, :td) RETURNING id"
            ),
            {"uid": user_id, "sw": start_w, "sd": start_date, "tw": target_w, "td": target_date},
        ).fetchone()
    return str(row.id)


def _cleanup_user(user_id: str):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def alice():
    user_id, authed = _make_authed_client(f"Alice353_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    _cleanup_user(user_id)


@pytest.fixture(scope="module")
def bob_empty():
    """User with no weight entries."""
    user_id, authed = _make_authed_client(f"BobEmpty353_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    _cleanup_user(user_id)


# ══════════════════════════════════════════════════════════════════════════════
# Frontend static analysis — home.js and home.html
# ══════════════════════════════════════════════════════════════════════════════

# AC-1: Widget calls /api/home/weight-summary on mount

def test_home_js_calls_weight_summary_endpoint():
    """AC-1: home.js must call GET /api/home/weight-summary."""
    assert "/api/home/weight-summary" in _HOME_JS, (
        "home.js must fetch /api/home/weight-summary on widget mount"
    )


def test_home_js_weight_summary_fetch_direct():
    """AC-1: home.js must call /api/home/weight-summary (no user_id param).
    May use raw fetch() or the shared _homeFetch helper."""
    assert (
        "'/api/home/weight-summary'" in _HOME_JS
        or '"/api/home/weight-summary"' in _HOME_JS
    ), "home.js must call /api/home/weight-summary — no user_id query param"


# AC-2: Current weight rendered large

def test_home_js_renders_current_weight():
    """AC-2: home.js references current_weight from summary."""
    assert "current_weight" in _HOME_JS, (
        "home.js must render current_weight from the summary response"
    )


def test_home_html_has_large_weight_style():
    """AC-2: CSS class ww-current present for large weight rendering."""
    assert "ww-current" in _HOME_HTML or "ww-current" in _HOME_JS, (
        "home.html/home.js must define ww-current style for large weight value"
    )


# AC-3: 7-day average

def test_home_js_renders_avg_7d():
    """AC-3: home.js renders avg_7d from summary."""
    assert "avg_7d" in _HOME_JS, (
        "home.js must render avg_7d (7-day average) below the current weight"
    )


def test_home_js_avg_label():
    """AC-3: home.js includes 'avg' label."""
    assert "avg" in _HOME_JS, "home.js must include 'avg' label for 7-day average"


# AC-4/5: Delta pills for week and month

def test_home_js_delta_week():
    """AC-4: home.js renders delta_week as a pill."""
    assert "delta_week" in _HOME_JS, "home.js must render delta_week delta pill"


def test_home_js_delta_month():
    """AC-5: home.js renders delta_month as a pill."""
    assert "delta_month" in _HOME_JS, "home.js must render delta_month delta pill"


def test_home_js_direction_aware_coloring():
    """AC-4/5: home.js uses direction field to color delta pills green/red."""
    assert "direction" in _HOME_JS, (
        "home.js must use direction field from target to color delta pills"
    )
    assert "'down'" in _HOME_JS or '"down"' in _HOME_JS, (
        "home.js must check direction==='down' for pill coloring"
    )


# AC-6: SVG sparkline from ma30 (40 px height, blue accent)

def test_home_js_sparkline_uses_ma30():
    """AC-6: home.js renders sparkline using ma30."""
    assert "ma30" in _HOME_JS, "home.js must use ma30 from summary for the sparkline"


def test_home_js_sparkline_is_svg():
    """AC-6: Sparkline is rendered as SVG."""
    assert "<svg" in _HOME_JS or "svg" in _HOME_JS.lower(), (
        "home.js must render an SVG sparkline for the weight widget"
    )


def test_home_js_sparkline_height_40():
    """AC-6: Sparkline height is 40 px."""
    assert "40" in _HOME_JS or "40px" in _HOME_HTML, (
        "Sparkline height must be 40 px"
    )


def test_home_js_sparkline_blue_accent():
    """AC-6: Sparkline uses blue accent color."""
    assert "#2b4ca8" in _HOME_JS or "blue" in _HOME_JS.lower(), (
        "home.js sparkline must use the blue accent color (#2b4ca8)"
    )


# AC-7: Progress bar when target exists

def test_home_js_progress_bar_progress_pct():
    """AC-7: home.js renders progress bar using progress_pct."""
    assert "progress_pct" in _HOME_JS, (
        "home.js must render ww-progress-bar using progress_pct when target exists"
    )


def test_home_js_status_pill_on_track():
    """AC-7: home.js handles 'on_track' status."""
    assert "on_track" in _HOME_JS, "home.js must handle on_track status"


def test_home_js_status_pill_behind():
    """AC-7: home.js handles 'behind' status."""
    assert "behind" in _HOME_JS, "home.js must handle behind status"


def test_home_js_status_pill_ahead():
    """AC-7: home.js handles 'ahead' status."""
    assert "ahead" in _HOME_JS, "home.js must handle ahead status"


# AC-8: "Set a target →" link

def test_home_js_set_target_link():
    """AC-8: home.js shows 'Set a target' link when no active target."""
    assert "Set a target" in _HOME_JS, (
        "home.js must render 'Set a target' when no active target"
    )


def test_home_js_set_target_href():
    """AC-8: 'Set a target' link points to /weight/targets."""
    assert "/weight/targets" in _HOME_JS, (
        "home.js must link to /weight/targets for 'Set a target'"
    )


# AC-9: Empty state

def test_home_js_empty_state_message():
    """AC-9: home.js shows 'No weight logged' empty state when current_weight is null."""
    assert "No weight logged" in _HOME_JS, (
        "home.js must show 'No weight logged' empty state"
    )


def test_home_js_empty_state_link_to_weight():
    """AC-9: Empty state includes link to /weight."""
    idx = _HOME_JS.find("No weight logged")
    assert idx != -1
    context = _HOME_JS[idx: idx + 300]
    assert "/weight" in context, "Empty state must link to /weight"


# AC-10: Loading skeleton

def test_home_js_weight_widget_skeleton_loading():
    """AC-10: home.js shows skeleton UI while fetching."""
    assert (
        "UIStates.loadingHTML" in _HOME_JS
        or "trend-skeleton" in _HOME_JS
        or "skeleton" in _HOME_JS
    ), "home.js must render skeleton UI during weight widget fetch"


# AC-11: Error state with retry

def test_home_js_error_message():
    """AC-11: home.js shows 'Could not load weight data' on failure."""
    assert "Could not load weight data" in _HOME_JS, (
        "home.js must show 'Could not load weight data' error message"
    )


def test_home_js_retry_button():
    """AC-11: Error state has a retry button that re-fetches."""
    idx = _HOME_JS.find("Could not load weight data")
    assert idx != -1
    context = _HOME_JS[max(0, idx - 100): idx + 400]
    assert "retry" in context.lower() or "Retry" in context, (
        "Error state must include a retry button"
    )


# AC-12: Click navigates to /weight

def test_home_js_weight_widget_click_navigates():
    """AC-12: Clicking the weight widget navigates to /weight."""
    assert "window.location" in _HOME_JS or "location.href" in _HOME_JS, (
        "home.js must navigate to /weight on widget click"
    )


def test_home_js_weight_widget_navigates_to_weight():
    """AC-12: Navigation target is /weight."""
    assert (
        'href="/weight"' in _HOME_JS
        or "href='/weight'" in _HOME_JS
        or '"/weight"' in _HOME_JS
        or "'/weight'" in _HOME_JS
    ), "home.js must navigate to /weight (not /weight/targets) on widget click"


# ══════════════════════════════════════════════════════════════════════════════
# Backend API tests (require live server + UAT DB)
# ══════════════════════════════════════════════════════════════════════════════

# AC-13: 401 for unauthenticated (session auth — no user_id param)

def test_weight_summary_401_unauthenticated():
    """AC-13: GET /api/home/weight-summary returns 401 when not authenticated."""
    with httpx.Client(base_url=BASE, timeout=10) as c:
        res = c.get("/api/home/weight-summary")
    assert res.status_code == 401, (
        f"Expected 401 for unauthenticated request, got {res.status_code}"
    )


# AC-15: Empty response when no entries

def test_weight_summary_empty_when_no_entries(bob_empty):
    """AC-15: Returns null current_weight and empty ma30 when user has no weight entries."""
    res = bob_empty["client"].get("/api/home/weight-summary")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()

    assert body["current_weight"] is None, (
        f"current_weight must be null when no entries, got {body.get('current_weight')}"
    )
    assert body["avg_7d"] is None, (
        f"avg_7d must be null when no entries, got {body.get('avg_7d')}"
    )
    assert body["delta_week"] is None, (
        f"delta_week must be null when no entries, got {body.get('delta_week')}"
    )
    assert body["delta_month"] is None, (
        f"delta_month must be null when no entries, got {body.get('delta_month')}"
    )
    assert body["ma30"] == [], (
        f"ma30 must be empty list when no entries, got {body.get('ma30')}"
    )
    assert body["target"] is None, (
        f"target must be null when no entries, got {body.get('target')}"
    )


# AC-14: Correct shape with entries

def test_weight_summary_response_shape_with_entries(alice):
    """AC-14: Returns correct response shape when user has weight entries."""
    uid = alice["id"]
    d_30d = (TODAY - datetime.timedelta(days=30)).isoformat()
    d_7d = (TODAY - datetime.timedelta(days=7)).isoformat()

    ids_to_clean = []
    try:
        ids_to_clean.append(_seed_weight_entry(uid, d_30d, 90.0))
        ids_to_clean.append(_seed_weight_entry(uid, d_7d, 89.0))
        ids_to_clean.append(_seed_weight_entry(uid, TODAY_ISO, 88.4))

        res = alice["client"].get("/api/home/weight-summary")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        body = res.json()

        assert body["current_weight"] == pytest.approx(88.4, abs=0.01), (
            f"current_weight must be most recent entry (88.4), got {body['current_weight']}"
        )
        assert body["avg_7d"] is not None, "avg_7d must not be null when entries exist"
        assert isinstance(body["delta_week"], (int, float)) or body["delta_week"] is None
        assert isinstance(body["delta_month"], (int, float)) or body["delta_month"] is None
        assert isinstance(body["ma30"], list), "ma30 must be a list"
        assert len(body["ma30"]) >= 1, "ma30 must have at least one item"

        for item in body["ma30"]:
            assert "date" in item, "Each ma30 item must have a 'date' field"
            assert "value" in item, "Each ma30 item must have a 'value' field"
            assert isinstance(item["value"], (int, float)), "ma30 value must be numeric"

    finally:
        for eid in ids_to_clean:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM weight_entries WHERE id = :id"), {"id": eid})


def test_weight_summary_delta_week_correct(alice):
    """AC-14: delta_week is current - 7d-ago moving average."""
    uid = alice["id"]
    d_7d = (TODAY - datetime.timedelta(days=7)).isoformat()

    ids_to_clean = []
    try:
        ids_to_clean.append(_seed_weight_entry(uid, d_7d, 89.0))
        ids_to_clean.append(_seed_weight_entry(uid, TODAY_ISO, 88.0))

        res = alice["client"].get("/api/home/weight-summary")
        assert res.status_code == 200
        body = res.json()

        assert body["delta_week"] is not None, "delta_week must not be null"
        assert body["delta_week"] == pytest.approx(-1.0, abs=0.05), (
            f"delta_week should be ~-1.0 (88.0 - 89.0), got {body['delta_week']}"
        )

    finally:
        for eid in ids_to_clean:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM weight_entries WHERE id = :id"), {"id": eid})


# AC-16: Target block has direction, progress_pct, status_label

def test_weight_summary_target_block_fields(alice):
    """AC-16: target block includes direction, progress_pct, status_label."""
    uid = alice["id"]
    d_start = (TODAY - datetime.timedelta(days=14)).isoformat()
    d_target = (TODAY + datetime.timedelta(days=60)).isoformat()

    ids_to_clean = []
    target_id = None
    try:
        ids_to_clean.append(_seed_weight_entry(uid, TODAY_ISO, 85.0))
        target_id = _seed_weight_target(uid, 90.0, 80.0, d_start, d_target)

        res = alice["client"].get("/api/home/weight-summary")
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["target"] is not None, "target must not be null when active target exists"
        t = body["target"]

        assert "direction" in t, "target must include 'direction'"
        assert t["direction"] in ("down", "up"), f"direction must be 'down'/'up', got {t['direction']}"
        assert t["direction"] == "down", (
            "direction must be 'down' for loss target (target_weight < start_weight)"
        )
        assert "progress_pct" in t, "target must include 'progress_pct'"
        assert 0 <= t["progress_pct"] <= 100, f"progress_pct must be 0-100, got {t['progress_pct']}"
        assert "status_label" in t, "target must include 'status_label'"
        assert t["status_label"] in ("on_track", "behind", "ahead", "no_data"), (
            f"status_label must be one of on_track/behind/ahead/no_data, got {t['status_label']}"
        )

    finally:
        for eid in ids_to_clean:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM weight_entries WHERE id = :id"), {"id": eid})
        if target_id:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM weight_targets WHERE id = :id"), {"id": target_id})


def test_weight_summary_target_direction_up(alice):
    """AC-16: direction='up' for gain target."""
    uid = alice["id"]
    d_start = (TODAY - datetime.timedelta(days=7)).isoformat()
    d_target = (TODAY + datetime.timedelta(days=60)).isoformat()

    ids_to_clean = []
    target_id = None
    try:
        ids_to_clean.append(_seed_weight_entry(uid, TODAY_ISO, 72.0))
        target_id = _seed_weight_target(uid, 70.0, 80.0, d_start, d_target)

        res = alice["client"].get("/api/home/weight-summary")
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["target"] is not None
        assert body["target"]["direction"] == "up", (
            f"direction must be 'up' for gain target, got {body['target']['direction']}"
        )

    finally:
        for eid in ids_to_clean:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM weight_entries WHERE id = :id"), {"id": eid})
        if target_id:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM weight_targets WHERE id = :id"), {"id": target_id})


def test_weight_summary_no_target_when_none(alice):
    """AC-16: target is null when no active target."""
    uid = alice["id"]

    ids_to_clean = []
    try:
        ids_to_clean.append(_seed_weight_entry(uid, TODAY_ISO, 85.0))

        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM weight_targets WHERE user_id = :uid AND status = 'active'"),
                {"uid": uid},
            )

        res = alice["client"].get("/api/home/weight-summary")
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["target"] is None, "target must be null when no active target"

    finally:
        for eid in ids_to_clean:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM weight_entries WHERE id = :id"), {"id": eid})


def test_no_console_errors_manual():
    """AC-17: No console errors in any state — verified manually via browser DevTools."""
    pytest.skip("Manual UAT step — verify via browser DevTools during UAT")
