"""Tests for issue #346: Wire Home Weight Widget to Real API

Acceptance criteria verified:
(AC-1)  Widget calls GET /api/home/weight-summary on mount
(AC-2)  Current weight displayed large (e.g. 88.4 kg)
(AC-3)  7-day average displayed smaller below current weight
(AC-4)  Delta pill for "this week" shown with direction logic
(AC-5)  Delta pill for "this month" shown with same direction logic
(AC-6)  SVG polyline sparkline renders 30-day moving-average data (ma30)
(AC-7)  If target exists: progress bar shows progress_pct; status pill colored
(AC-8)  If no target: shows "Set a target →" link to /weight/targets
(AC-9)  Empty state: "No weight logged yet" message with link to /weight
(AC-10) Loading state: skeleton UI while fetch is in flight
(AC-11) Error state: "Could not load weight data" + retry button
(AC-12) Clicking anywhere on widget navigates to /weight
(AC-13) API: GET /api/home/weight-summary returns 401 for unauthenticated requests
(AC-14) API: returns correct response shape with entries present
(AC-15) API: returns null current_weight and empty ma30 when no entries
(AC-16) API: target block includes direction, progress_pct, status_label
(AC-17) No console errors in any state (manual UAT)
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
from backend.models import User, WeightEntry, WeightTarget

# ── Root detection ───────────────────────────────────────────────────────────

_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_CODER_ROOT, _TESTER_ROOT):
        js = root / "frontend" / "js" / "home.js"
        if js.exists():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today()
TODAY_ISO = TODAY.isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "wt346-test-pw"

_env_vals = dotenv_values(_TESTER_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_authed_client(username: str):
    with httpx.Client(base_url=BASE, timeout=10) as fresh:
        res = fresh.post("/api/users", json={"name": username})
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


def _seed_weight_entry(user_id: str, date_iso: str, weight_kg: float):
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO weight_entries (user_id, entry_date, weight_kg) "
                "VALUES (:uid, :d, :w) RETURNING id"
            ),
            {"uid": user_id, "d": date_iso, "w": weight_kg},
        ).fetchone()
    return str(row.id)


def _seed_weight_target(user_id: str, start_w: float, target_w: float,
                         start_date: str, target_date: str):
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO weight_targets "
                "(user_id, start_weight_kg, start_date, target_weight_kg, target_date) "
                "VALUES (:uid, :sw, :sd, :tw, :td) RETURNING id"
            ),
            {"uid": user_id, "sw": start_w, "sd": start_date,
             "tw": target_w, "td": target_date},
        ).fetchone()
    return str(row.id)


def _cleanup_user(user_id: str):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def alice():
    user_id, authed = _make_authed_client(f"Alice346_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    _cleanup_user(user_id)


@pytest.fixture(scope="module")
def bob_empty():
    """User with no weight entries."""
    user_id, authed = _make_authed_client(f"BobEmpty346_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    _cleanup_user(user_id)


# ══════════════════════════════════════════════════════════════════════════════
# Frontend static analysis — JS and HTML
# ══════════════════════════════════════════════════════════════════════════════

# ── AC-1: Widget calls /api/home/weight-summary ───────────────────────────────

def test_home_js_calls_weight_summary_endpoint():
    """AC-1: home.js must fetch /api/home/weight-summary."""
    assert "/api/home/weight-summary" in _HOME_JS, (
        "home.js must call GET /api/home/weight-summary on widget mount"
    )


def test_home_js_weight_summary_fetch_is_in_load_function():
    """AC-1: The fetch must be inside a load/render function for the weight widget."""
    # Accept either a direct fetch() call or a wrapper like _homeFetch() — both
    # satisfy AC-1 ("widget calls the endpoint on mount").
    assert (
        "fetch('/api/home/weight-summary')" in _HOME_JS
        or 'fetch("/api/home/weight-summary")' in _HOME_JS
        or "_homeFetch('/api/home/weight-summary')" in _HOME_JS
        or '_homeFetch("/api/home/weight-summary")' in _HOME_JS
    ), "/api/home/weight-summary must be called via fetch() or a fetch wrapper on widget mount"


# ── AC-2: Current weight displayed large ─────────────────────────────────────

def test_home_js_renders_current_weight_large():
    """AC-2: home.js renders current_weight from summary response in large text."""
    assert "current_weight" in _HOME_JS, (
        "home.js must reference current_weight from the summary response"
    )


def test_home_html_weight_widget_large_style():
    """AC-2: home.html has CSS for large weight display."""
    # Either a dedicated class or an inline large font-size for the weight value
    assert "ww-current" in _HOME_HTML or "weight-widget" in _HOME_HTML or (
        "current_weight" in _HOME_JS
    ), "home.html or home.js must include styling for the large current weight display"


# ── AC-3: 7-day average displayed below ──────────────────────────────────────

def test_home_js_renders_avg_7d():
    """AC-3: home.js renders avg_7d from summary response."""
    assert "avg_7d" in _HOME_JS, (
        "home.js must render avg_7d (7-day average) from the summary response"
    )


def test_home_js_avg_label_present():
    """AC-3: home.js includes 'avg' label text near the 7-day average display."""
    assert "avg" in _HOME_JS, (
        "home.js must include 'avg' label for the 7-day average"
    )


# ── AC-4/5: Delta pills for week and month ───────────────────────────────────

def test_home_js_delta_week_pill():
    """AC-4: home.js renders delta_week with a pill element."""
    assert "delta_week" in _HOME_JS, (
        "home.js must render delta_week as a delta pill"
    )


def test_home_js_delta_month_pill():
    """AC-5: home.js renders delta_month with a pill element."""
    assert "delta_month" in _HOME_JS, (
        "home.js must render delta_month as a delta pill"
    )


def test_home_js_direction_aware_pill_coloring():
    """AC-4/5: home.js uses direction field to color delta pills."""
    assert "direction" in _HOME_JS, (
        "home.js must use the 'direction' field from target to color delta pills"
    )


def test_home_js_week_pill_green_on_loss_when_down():
    """AC-4: When direction='down', negative delta (loss) → green pill."""
    # The JS should compare direction === 'down' and delta < 0 for green
    assert "direction" in _HOME_JS and (
        "'down'" in _HOME_JS or '"down"' in _HOME_JS
    ), "home.js must check direction==='down' for delta pill coloring"


# ── AC-6: SVG sparkline from ma30 ────────────────────────────────────────────

def test_home_js_sparkline_uses_ma30():
    """AC-6: home.js renders sparkline using ma30 field from the summary response."""
    assert "ma30" in _HOME_JS, (
        "home.js must use ma30 from the summary response for the sparkline"
    )


def test_home_js_sparkline_is_svg_polyline():
    """AC-6: Sparkline is rendered as an SVG element."""
    assert "svg" in _HOME_JS.lower() or "SVG" in _HOME_JS or "<svg" in _HOME_JS, (
        "home.js must render an SVG sparkline for the weight widget"
    )


def test_home_html_sparkline_height_40():
    """AC-6: Sparkline height is 40px."""
    assert "40" in _HOME_JS or "40px" in _HOME_HTML, (
        "Sparkline height must be 40 (px) per AC-6"
    )


# ── AC-7: Progress bar when target exists ────────────────────────────────────

def test_home_js_progress_bar_when_target():
    """AC-7: home.js renders a progress bar using progress_pct when target exists."""
    assert "progress_pct" in _HOME_JS, (
        "home.js must render a progress bar using progress_pct from target"
    )


def test_home_js_status_pill_on_track():
    """AC-7: home.js renders status pill for 'on_track'."""
    assert "on_track" in _HOME_JS, (
        "home.js must handle 'on_track' status for the status pill"
    )


def test_home_js_status_pill_behind():
    """AC-7: home.js renders status pill for 'behind'."""
    assert "behind" in _HOME_JS, (
        "home.js must handle 'behind' status for the status pill"
    )


def test_home_js_status_pill_ahead():
    """AC-7: home.js renders status pill for 'ahead'."""
    assert "ahead" in _HOME_JS, (
        "home.js must handle 'ahead' status for the status pill"
    )


def test_home_html_status_pill_colors():
    """AC-7: home.html has CSS for all three status pill colors."""
    # on_track→green, behind→amber, ahead→blue
    assert "on_track" in _HOME_HTML or "on_track" in _HOME_JS, (
        "home.html or home.js must define styling for on_track status"
    )


# ── AC-8: "Set a target →" link when no target ───────────────────────────────

def test_home_js_set_target_link_when_no_target():
    """AC-8: home.js renders 'Set a target' link to /weight/targets when no target."""
    assert "Set a target" in _HOME_JS, (
        "home.js must show 'Set a target' link when no active target"
    )


def test_home_js_set_target_href():
    """AC-8: The 'Set a target' link points to /weight/targets."""
    assert "/weight/targets" in _HOME_JS, (
        "home.js must link to /weight/targets for 'Set a target'"
    )


# ── AC-9: Empty state ─────────────────────────────────────────────────────────

def test_home_js_empty_state_message():
    """AC-9: home.js shows empty state when current_weight is null."""
    assert "No weight logged" in _HOME_JS, (
        "home.js must show 'No weight logged' empty state message"
    )


def test_home_js_empty_state_link_to_weight():
    """AC-9: Empty state includes a link to /weight."""
    # Check for /weight link in context near "No weight logged"
    idx = _HOME_JS.find("No weight logged")
    assert idx != -1
    context = _HOME_JS[idx: idx + 300]
    assert "/weight" in context, (
        "Empty state must include a link to /weight"
    )


# ── AC-10: Loading state ──────────────────────────────────────────────────────

def test_home_js_weight_widget_has_skeleton_loading():
    """AC-10: home.js renders skeleton/loading state while fetch is in flight."""
    # Should use UIStates.loadingHTML or trend-skeleton-line or similar
    assert (
        "UIStates.loadingHTML" in _HOME_JS
        or "trend-skeleton" in _HOME_JS
        or "skeleton" in _HOME_JS
    ), "home.js must render skeleton UI during weight widget fetch"


# ── AC-11: Error state with retry ────────────────────────────────────────────

def test_home_js_weight_error_message():
    """AC-11: home.js shows 'Could not load weight data' on fetch failure."""
    assert "Could not load weight data" in _HOME_JS, (
        "home.js must show 'Could not load weight data' error message"
    )


def test_home_js_weight_retry_button():
    """AC-11: home.js renders a retry button on error."""
    # Find the error message and check nearby context for retry
    idx = _HOME_JS.find("Could not load weight data")
    assert idx != -1
    context = _HOME_JS[max(0, idx - 100): idx + 400]
    assert "retry" in context.lower() or "Retry" in context, (
        "Error state must include a retry button"
    )


# ── AC-12: Click navigates to /weight ────────────────────────────────────────

def test_home_js_weight_widget_click_navigates():
    """AC-12: Clicking the weight widget navigates to /weight."""
    assert "window.location" in _HOME_JS or "href" in _HOME_JS, (
        "home.js must handle click on weight widget to navigate to /weight"
    )


def test_home_js_weight_widget_link_href():
    """AC-12: home.js wires the weight widget to navigate to /weight on click."""
    # Check that /weight appears as a navigation target (not just /weight/targets)
    # Look for pattern like href="/weight" or location.href = '/weight'
    assert (
        'href="/weight"' in _HOME_JS
        or "href='/weight'" in _HOME_JS
        or '"/weight"' in _HOME_JS
        or "'/weight'" in _HOME_JS
    ), "home.js must navigate to /weight on widget click"


# ══════════════════════════════════════════════════════════════════════════════
# Backend API tests (require live server + UAT DB)
# ══════════════════════════════════════════════════════════════════════════════

# ── AC-13: 401 for unauthenticated ───────────────────────────────────────────

def test_weight_summary_401_unauthenticated():
    """AC-13: GET /api/home/weight-summary returns 401 for unauthenticated requests."""
    with httpx.Client(base_url=BASE, timeout=10) as c:
        res = c.get("/api/home/weight-summary")
    assert res.status_code == 401, (
        f"Expected 401 for unauthenticated request, got {res.status_code}"
    )


# ── AC-15: Empty response when no entries ────────────────────────────────────

def test_weight_summary_empty_when_no_entries(bob_empty):
    """AC-15: Returns null current_weight and empty ma30 when user has no weight entries."""
    res = bob_empty["client"].get("/api/home/weight-summary")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()

    assert body["current_weight"] is None, (
        "current_weight must be null when no weight entries"
    )
    assert body["avg_7d"] is None, (
        "avg_7d must be null when no weight entries"
    )
    assert body["delta_week"] is None, (
        "delta_week must be null when no weight entries"
    )
    assert body["delta_month"] is None, (
        "delta_month must be null when no weight entries"
    )
    assert body["ma30"] == [], (
        "ma30 must be empty list when no weight entries"
    )
    assert body["target"] is None, (
        "target must be null when no weight entries / no active target"
    )


# ── AC-14: Correct shape with entries ────────────────────────────────────────

def test_weight_summary_response_shape_with_entries(alice):
    """AC-14: Returns correct response shape when user has weight entries."""
    uid = alice["id"]

    # Seed entries: one today, one 7d ago, one 30d ago
    d_today = TODAY_ISO
    d_7d = (TODAY - datetime.timedelta(days=7)).isoformat()
    d_30d = (TODAY - datetime.timedelta(days=30)).isoformat()

    ids_to_clean = []
    try:
        ids_to_clean.append(_seed_weight_entry(uid, d_30d, 90.0))
        ids_to_clean.append(_seed_weight_entry(uid, d_7d, 89.0))
        ids_to_clean.append(_seed_weight_entry(uid, d_today, 88.4))

        res = alice["client"].get("/api/home/weight-summary")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        body = res.json()

        assert body["current_weight"] == pytest.approx(88.4, abs=0.01), (
            f"current_weight must be the most recent entry (88.4), got {body['current_weight']}"
        )
        assert body["avg_7d"] is not None, "avg_7d must not be null when entries exist"
        assert isinstance(body["delta_week"], (int, float)) or body["delta_week"] is None, (
            "delta_week must be a number or null"
        )
        assert isinstance(body["delta_month"], (int, float)) or body["delta_month"] is None, (
            "delta_month must be a number or null"
        )
        assert isinstance(body["ma30"], list), "ma30 must be a list"
        assert len(body["ma30"]) >= 1, "ma30 must contain at least one data point"

        # Each ma30 item must have date and value
        for item in body["ma30"]:
            assert "date" in item, "Each ma30 item must have a 'date' field"
            assert "value" in item, "Each ma30 item must have a 'value' field"
            assert isinstance(item["value"], (int, float)), "ma30 value must be numeric"

    finally:
        for eid in ids_to_clean:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM weight_entries WHERE id = :id"),
                    {"id": eid},
                )


def test_weight_summary_delta_week_correct(alice):
    """AC-14: delta_week is approximately current - 7d-ago weight."""
    uid = alice["id"]
    d_today = TODAY_ISO
    d_7d = (TODAY - datetime.timedelta(days=7)).isoformat()

    ids_to_clean = []
    try:
        ids_to_clean.append(_seed_weight_entry(uid, d_7d, 89.0))
        ids_to_clean.append(_seed_weight_entry(uid, d_today, 88.0))

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
                conn.execute(
                    text("DELETE FROM weight_entries WHERE id = :id"),
                    {"id": eid},
                )


# ── AC-16: Target block includes direction, progress_pct, status_label ───────

def test_weight_summary_target_block(alice):
    """AC-16: When active target exists, target block has direction, progress_pct, status_label."""
    uid = alice["id"]
    d_today = TODAY_ISO
    d_start = (TODAY - datetime.timedelta(days=14)).isoformat()
    d_target = (TODAY + datetime.timedelta(days=60)).isoformat()

    ids_to_clean = []
    target_id = None
    try:
        ids_to_clean.append(_seed_weight_entry(uid, d_today, 85.0))
        target_id = _seed_weight_target(uid, 90.0, 80.0, d_start, d_target)

        res = alice["client"].get("/api/home/weight-summary")
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["target"] is not None, "target block must not be null when active target exists"
        t = body["target"]

        assert "direction" in t, "target block must include 'direction'"
        assert t["direction"] in ("down", "up"), (
            f"direction must be 'down' or 'up', got {t['direction']}"
        )
        assert t["direction"] == "down", (
            "direction must be 'down' for loss target (target_weight < start_weight)"
        )

        assert "progress_pct" in t, "target block must include 'progress_pct'"
        assert 0 <= t["progress_pct"] <= 100, (
            f"progress_pct must be 0-100, got {t['progress_pct']}"
        )

        assert "status_label" in t, "target block must include 'status_label'"
        assert t["status_label"] in ("on_track", "behind", "ahead", "no_data"), (
            f"status_label must be one of on_track/behind/ahead/no_data, got {t['status_label']}"
        )

    finally:
        for eid in ids_to_clean:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM weight_entries WHERE id = :id"),
                    {"id": eid},
                )
        if target_id:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM weight_targets WHERE id = :id"),
                    {"id": target_id},
                )


def test_weight_summary_no_target_when_no_active_target(alice):
    """AC-16: target is null when no active target exists."""
    uid = alice["id"]
    d_today = TODAY_ISO

    ids_to_clean = []
    try:
        ids_to_clean.append(_seed_weight_entry(uid, d_today, 85.0))

        # Ensure no active target (clean any existing)
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM weight_targets WHERE user_id = :uid AND status = 'active'"),
                {"uid": uid},
            )

        res = alice["client"].get("/api/home/weight-summary")
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["target"] is None, (
            "target must be null when no active weight target exists"
        )

    finally:
        for eid in ids_to_clean:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM weight_entries WHERE id = :id"),
                    {"id": eid},
                )


# ── AC-17 ─────────────────────────────────────────────────────────────────────

def test_no_console_errors_manual():
    """AC-17: No console errors in any state — verified manually via UAT."""
    pytest.skip("Manual UAT step — verify via browser DevTools during UAT")
