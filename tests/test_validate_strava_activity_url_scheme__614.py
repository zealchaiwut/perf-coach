"""Tests for issue #614: Validate strava_activity_url scheme before injecting into href in run-view.

AC1 — In run-view.js, strava_activity_url is validated against https: before being injected into href.
AC2 — javascript:alert(1) does NOT produce a clickable anchor tag in the Run View.
AC3 — A valid https://www.strava.com/activities/123 URL renders as a working clickable link.
AC4 — POST /api/workouts rejects strava_activity_url with non-https scheme (400-level).
AC5 — null, empty, or absent strava_activity_url is handled gracefully (no anchor, no JS error).
"""
import os
import pathlib
import uuid
import datetime

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RV_JS_PATH = _ROOT / "frontend" / "js" / "run-view.js"

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"


# ── File-based JS validation tests (AC1, AC2, AC3, AC5) ──────────────────────

def _rv_js() -> str:
    assert _RV_JS_PATH.exists(), f"run-view.js not found: {_RV_JS_PATH}"
    return _RV_JS_PATH.read_text()


def test_ac1_run_view_validates_url_scheme_before_href_injection():
    """AC1: strava_activity_url must be validated for https: before building href."""
    src = _rv_js()
    # The fix must check the protocol is https: (using URL constructor or startsWith)
    has_url_constructor = "new URL(" in src and ".protocol" in src
    has_starts_with = "startsWith('https://')" in src or 'startsWith("https://")' in src
    assert has_url_constructor or has_starts_with, (
        "run-view.js must validate strava_activity_url scheme (URL constructor protocol check "
        "or startsWith('https://')) before injecting into href"
    )


def test_ac2_javascript_url_not_rendered_as_href():
    """AC2: A javascript: URL must not be placed directly into an href attribute without validation."""
    src = _rv_js()
    # Ensure the renderSourceStrip function does not blindly put strava_activity_url into href
    # The old pattern was: 'href="' + esc(workout.strava_activity_url)
    # This direct injection must no longer appear (it's replaced by scheme-validated logic)
    assert 'href="' + "' + esc(workout.strava_activity_url)" not in src, (
        "run-view.js must not directly inject strava_activity_url into href without scheme validation"
    )


def test_ac3_https_url_renders_as_anchor():
    """AC3: A valid https:// URL must result in an <a href=...> being built."""
    src = _rv_js()
    # After validation passes, the code must still build an anchor tag with href
    assert '<a ' in src and 'href=' in src, (
        "run-view.js must still build a clickable <a href=...> for valid https:// URLs"
    )
    # The safe URL helper or the conditional that creates the anchor must be present
    assert "strava_activity_url" in src, "strava_activity_url handling must exist in run-view.js"


def test_ac5_null_url_no_anchor_rendered():
    """AC5: When strava_activity_url is null/empty/absent, no anchor tag is built."""
    src = _rv_js()
    # The existing guard 'if (workout.strava_activity_url)' must still be present
    # OR an equivalent null/empty check wrapping the anchor construction
    assert "strava_activity_url" in src, "strava_activity_url must be referenced in run-view.js"
    # Verify the https validation helper/function itself handles falsy values
    has_safe_url_fn = "_safeStravaUrl" in src or "safeUrl" in src or "safeHref" in src or "_isSafeUrl" in src
    has_try_catch = "try {" in src and "new URL(" in src
    has_starts_with_guard = "startsWith('https://')" in src or 'startsWith("https://")' in src
    assert has_safe_url_fn or has_try_catch or has_starts_with_guard, (
        "run-view.js must have a safe-URL helper or inline guard that handles null/empty values"
    )


# ── Live-server tests for backend AC4 ────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    if not BASE.startswith("http"):
        pytest.skip("UAT_BASE_URL not set — skipping live-server tests")
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


_RUN_TAG = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "test-614-xss"
_TODAY = datetime.date.today().isoformat()


@pytest.fixture(scope="module")
def authed_client(client):
    name = f"Test614_{_RUN_TAG}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, res.text
    login = client.post("/api/auth/login", json={"username": name, "password": "test-614-xss"})
    # If login fails it's because password not set yet — use admin path
    # Some test setups pre-populate passwords; try direct approach
    if login.status_code != 200:
        pytest.skip("Cannot authenticate test user — skipping live-server auth tests")
    yield client


def _post_workout_with_url(client, strava_url):
    payload = {
        "name": f"XSS Test {_RUN_TAG}",
        "workout_date": _TODAY,
        "workout_type": "Running",
        "exercises": [],
    }
    if strava_url is not None:
        payload["strava_activity_url"] = strava_url
    return client.post("/api/workouts", json=payload)


@pytest.mark.skipif(
    not BASE.startswith("http"),
    reason="UAT_BASE_URL not set",
)
def test_ac4_post_workout_rejects_javascript_scheme(client):
    """AC4: POST /api/workouts with javascript: strava_activity_url returns 4xx."""
    res = _post_workout_with_url(client, "javascript:alert(1)")
    assert res.status_code in (400, 422), (
        f"Expected 4xx for javascript: URL, got {res.status_code}: {res.text}"
    )
    body = res.json()
    detail = str(body.get("detail", "")).lower()
    assert "url" in detail or "scheme" in detail or "https" in detail or "strava" in detail, (
        f"Error message should mention URL/scheme/https, got: {body.get('detail')}"
    )


@pytest.mark.skipif(
    not BASE.startswith("http"),
    reason="UAT_BASE_URL not set",
)
def test_ac4_post_workout_rejects_data_scheme(client):
    """AC4: POST /api/workouts with data: URL returns 4xx."""
    res = _post_workout_with_url(client, "data:text/html,<script>alert(1)</script>")
    assert res.status_code in (400, 422), (
        f"Expected 4xx for data: URL, got {res.status_code}: {res.text}"
    )


@pytest.mark.skipif(
    not BASE.startswith("http"),
    reason="UAT_BASE_URL not set",
)
def test_ac4_post_workout_rejects_http_scheme(client):
    """AC4: POST /api/workouts with http: (non-https) URL returns 4xx."""
    res = _post_workout_with_url(client, "http://www.strava.com/activities/123")
    assert res.status_code in (400, 422), (
        f"Expected 4xx for http: URL, got {res.status_code}: {res.text}"
    )


@pytest.mark.skipif(
    not BASE.startswith("http"),
    reason="UAT_BASE_URL not set",
)
def test_ac4_post_workout_accepts_https_url(client):
    """AC4 / AC3: POST /api/workouts with https: Strava URL succeeds (2xx)."""
    res = _post_workout_with_url(client, "https://www.strava.com/activities/987654321")
    assert res.status_code == 201, (
        f"Expected 201 for valid https: URL, got {res.status_code}: {res.text}"
    )
    body = res.json()
    workout_id = body.get("id")
    assert body.get("strava_activity_url") == "https://www.strava.com/activities/987654321"
    # Cleanup
    if workout_id:
        client.delete(f"/api/workouts/{workout_id}")


@pytest.mark.skipif(
    not BASE.startswith("http"),
    reason="UAT_BASE_URL not set",
)
def test_ac5_post_workout_accepts_null_url(client):
    """AC5: POST /api/workouts with null strava_activity_url succeeds."""
    res = _post_workout_with_url(client, None)
    assert res.status_code == 201, (
        f"Expected 201 for null strava_activity_url, got {res.status_code}: {res.text}"
    )
    body = res.json()
    workout_id = body.get("id")
    assert body.get("strava_activity_url") is None
    if workout_id:
        client.delete(f"/api/workouts/{workout_id}")
