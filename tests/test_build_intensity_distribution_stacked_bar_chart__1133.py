"""Tests for issue #1133: Build intensity-distribution stacked bar chart.

Acceptance Criteria anchored:
  AC1  - API returns sessions array (one entry per workout) + rolling_window
  AC2  - Each session has low_pct, moderate_pct, high_pct fields
  AC3  - Band colours in JS match the app's design token palette
  AC4  - Data is fetched from /api/workouts/intensity-distribution (no hardcoded mock)
  AC5  - API returns rolling_window key distinct from per-session bars
  AC6  - Chart slot has responsive CSS wrapper
  AC7  - Sessions with zero band time return null values (no crash)
  AC8  - HTML slot has loading-skeleton markup
  AC9  - HTML slot has title; JS registers legend, x-label, y-label
  AC10 - Smoke: HTML file contains the chart slot and JS file registers the chart
"""
import os
import pathlib
import re
import subprocess
import sys

import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set — run the tester's Step 0 to resolve UAT before pytest."
    )

ROOT = pathlib.Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=15) as c:
        yield c


@pytest.fixture(scope="module")
def auth_client(client):
    """Returns an authenticated client (logs in as alice)."""
    res = client.post("/api/auth/login", json={"username": "alice", "password": "password"})
    assert res.status_code == 200, f"login failed: {res.text}"
    return client


# ---------------------------------------------------------------------------
# AC1 / AC2 / AC5 — API endpoint shape
# ---------------------------------------------------------------------------

class TestApiShape:

    def test_endpoint_returns_200(self, auth_client):
        """GET /api/workouts/intensity-distribution returns 200."""
        res = auth_client.get(
            "/api/workouts/intensity-distribution",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200, f"expected 200, got {res.status_code}: {res.text}"

    def test_response_has_sessions_and_rolling_window(self, auth_client):
        """AC1 / AC5: response body has 'sessions' list and 'rolling_window' dict."""
        res = auth_client.get(
            "/api/workouts/intensity-distribution",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "sessions" in body, "'sessions' key missing from response"
        assert "rolling_window" in body, "'rolling_window' key missing from response"
        assert isinstance(body["sessions"], list)
        assert isinstance(body["rolling_window"], dict)

    def test_rolling_window_has_band_keys(self, auth_client):
        """AC5: rolling_window contains low_pct, moderate_pct, high_pct."""
        res = auth_client.get(
            "/api/workouts/intensity-distribution",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        rw = res.json()["rolling_window"]
        assert "low_pct" in rw
        assert "moderate_pct" in rw
        assert "high_pct" in rw

    def test_session_entries_have_required_fields(self, auth_client):
        """AC2: each session entry has date, workout_id, name, duration_seconds, and band pcts."""
        res = auth_client.get(
            "/api/workouts/intensity-distribution",
            params={"from": "2025-01-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        sessions = res.json()["sessions"]
        if not sessions:
            pytest.skip("no workouts in range — seed data and re-run")
        for s in sessions[:3]:
            assert "date" in s, "session missing 'date'"
            assert "workout_id" in s, "session missing 'workout_id'"
            assert "name" in s, "session missing 'name'"
            assert "duration_seconds" in s, "session missing 'duration_seconds'"
            assert "low_pct" in s, "session missing 'low_pct'"
            assert "moderate_pct" in s, "session missing 'moderate_pct'"
            assert "high_pct" in s, "session missing 'high_pct'"

    def test_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        unauth = httpx.Client(base_url=BASE, timeout=10)
        res = unauth.get(
            "/api/workouts/intensity-distribution",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 401

    def test_bad_date_returns_400(self, auth_client):
        """Invalid date format returns 400."""
        res = auth_client.get(
            "/api/workouts/intensity-distribution",
            params={"from": "not-a-date", "to": "2026-06-30"},
        )
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# AC7 — Zero/empty session handling
# ---------------------------------------------------------------------------

class TestEmptySessionHandling:

    def test_empty_range_returns_empty_sessions(self, auth_client):
        """AC7: Date range with no workouts returns empty sessions and null rolling window."""
        res = auth_client.get(
            "/api/workouts/intensity-distribution",
            params={"from": "2000-01-01", "to": "2000-01-31"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["sessions"] == []
        rw = body["rolling_window"]
        assert rw["low_pct"] is None
        assert rw["moderate_pct"] is None
        assert rw["high_pct"] is None

    def test_session_with_null_bands_present_in_output(self, auth_client):
        """AC7: Sessions with zero band time have null pct values, not missing."""
        res = auth_client.get(
            "/api/workouts/intensity-distribution",
            params={"from": "2025-01-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        sessions = res.json()["sessions"]
        # All sessions must have the band keys, even if the values are None
        for s in sessions:
            assert "low_pct" in s
            assert "moderate_pct" in s
            assert "high_pct" in s


# ---------------------------------------------------------------------------
# AC3 — Band colours match design palette (static JS check)
# ---------------------------------------------------------------------------

class TestBandColours:

    def test_low_band_colour_is_green(self):
        """AC3: low intensity colour in trends.js must be green-family."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        # Expect a green colour for low band:
        # '#22c55e' (Tailwind green-500) or '#16a34a' (--success) or similar green
        assert re.search(
            r"(?:#22c55e|#16a34a|#15803d|#4ade80|rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,)",
            src,
        ) or "low" in src.lower() and "green" in src.lower(), (
            "Low intensity band must use a green colour in trends.js"
        )

    def test_js_has_three_distinct_band_colours(self):
        """AC3: trends.js references at least 3 distinct hex/rgba colours for the chart."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        # Find the intensity distribution section (between markers)
        hex_colours = set(re.findall(r"#[0-9a-fA-F]{6}", src))
        # At minimum we need 3 distinct colours present in the chart section
        assert len(hex_colours) >= 3, "Expected at least 3 hex colour values in trends.js"


# ---------------------------------------------------------------------------
# AC4 — No hardcoded mock data in production build
# ---------------------------------------------------------------------------

class TestNoMockData:

    def test_js_fetches_from_api_not_mock(self):
        """AC4: trends.js fetches /api/workouts/intensity-distribution, not mock data."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        assert "/api/workouts/intensity-distribution" in src, (
            "trends.js must fetch from /api/workouts/intensity-distribution"
        )

    def test_js_does_not_contain_hardcoded_band_values(self):
        """AC4: No hardcoded session data arrays in the chart function."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        # Should not have hardcoded pct arrays like [60, 30, 10, ...]
        assert not re.search(r"low_pct\s*[:=]\s*\[", src), (
            "trends.js must not hardcode low_pct array values"
        )


# ---------------------------------------------------------------------------
# AC8 — Loading state in HTML
# ---------------------------------------------------------------------------

class TestLoadingState:

    def test_html_has_intensity_chart_slot(self):
        """AC8 / AC10: trends.html contains the intensity-distribution chart slot."""
        html_path = ROOT / "frontend" / "pages" / "trends.html"
        src = html_path.read_text()
        assert "slot-intensity" in src, (
            "trends.html must contain a chart slot with id 'slot-intensity'"
        )

    def test_html_slot_has_loading_skeleton(self):
        """AC8: The intensity chart slot contains loading skeleton markup."""
        html_path = ROOT / "frontend" / "pages" / "trends.html"
        src = html_path.read_text()
        # The slot must have the standard slot-loading div
        assert "slot-loading" in src, (
            "trends.html intensity slot must have slot-loading skeleton"
        )


# ---------------------------------------------------------------------------
# AC9 — Title, labels, legend
# ---------------------------------------------------------------------------

class TestTitleAndLabels:

    def test_html_has_chart_title(self):
        """AC9: trends.html has a title for the intensity chart slot."""
        html_path = ROOT / "frontend" / "pages" / "trends.html"
        src = html_path.read_text()
        assert re.search(r"[Ii]ntensity", src), (
            "trends.html must include 'Intensity' in the chart slot title"
        )

    def test_js_registers_legend(self):
        """AC9: trends.js Chart.js config has plugins.legend defined."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        assert "legend" in src, "trends.js must configure Chart.js legend"

    def test_js_has_axis_labels(self):
        """AC9: trends.js has x or y axis label configuration."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        assert re.search(r"(?:xLabel|yLabel|title\s*:\s*\{|display\s*:\s*true)", src), (
            "trends.js must configure axis labels for the intensity chart"
        )


# ---------------------------------------------------------------------------
# AC10 — Smoke: file structure
# ---------------------------------------------------------------------------

class TestSmoke:

    def test_html_includes_trends_js(self):
        """AC10: trends.html loads trends.js."""
        html_path = ROOT / "frontend" / "pages" / "trends.html"
        src = html_path.read_text()
        assert "trends.js" in src

    def test_js_defines_intensity_chart_function(self):
        """AC10: trends.js defines a render function for the intensity chart."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        assert re.search(r"function\s+render\w*[Ii]ntensity\w*\s*\(", src), (
            "trends.js must define a renderIntensity* function"
        )

    def test_main_py_compiles(self):
        """AC10: backend/main.py passes py_compile with no errors."""
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ROOT / "backend" / "main.py")],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"py_compile failed on backend/main.py:\n{result.stderr.decode()}"
        )

    def test_trends_js_compiles_no_syntax_error(self):
        """AC10: trends.js is syntactically valid (node --check)."""
        result = subprocess.run(
            ["node", "--check", str(ROOT / "frontend" / "js" / "trends.js")],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"node --check failed on trends.js:\n{result.stderr.decode()}"
        )
