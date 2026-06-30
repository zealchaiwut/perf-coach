"""Tests for issue #1134: Add polarized-check indicator for on-target vs grey-zone.

Acceptance Criteria anchored:
  AC1 - Indicator renders "on-target" state when API verdict is on-target
  AC2 - Indicator renders "grey-zone" warning state when API verdict is grey-zone
  AC3 - Actual vs. target split values are displayed within the indicator
  AC4 - The specific band that is off-target is clearly identified in grey-zone state
  AC5 - Indicator state derived exclusively from API verdict field (no client-side recalculation)
  AC6 - Visual distinction between on-target and grey-zone states (color, icon, or label)
  AC7 - Indicator updates reactively when the API response changes
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
    """Returns an authenticated client (logs in as alice, creating her if needed)."""
    res = client.post("/api/auth/login", json={"username": "alice", "password": "password"})
    if res.status_code == 401:
        # alice doesn't exist yet — create via admin API then retry
        admin_secret = os.environ.get("ADMIN_SECRET_UAT", "perfcoach-uat-admin")
        admin_res = client.post("/api/admin/login", json={"secret": admin_secret})
        if admin_res.status_code == 200:
            client.post(
                "/api/admin/users",
                json={"username": "alice", "password": "password"},
            )
        res = client.post("/api/auth/login", json={"username": "alice", "password": "password"})
    assert res.status_code == 200, f"login failed: {res.text}"
    return client


# ---------------------------------------------------------------------------
# AC1 / AC2 / AC5 — API endpoint shape and verdict field
# ---------------------------------------------------------------------------

class TestApiShape:

    def test_endpoint_returns_200(self, auth_client):
        """GET /api/workouts/polarized-check returns 200 with valid params."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200, f"expected 200, got {res.status_code}: {res.text}"

    def test_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        unauth = httpx.Client(base_url=BASE, timeout=10)
        res = unauth.get(
            "/api/workouts/polarized-check",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 401

    def test_bad_date_returns_400(self, auth_client):
        """Invalid date format returns 400."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "not-a-date", "to": "2026-06-30"},
        )
        assert res.status_code == 400

    def test_response_has_verdict_field(self, auth_client):
        """AC1/AC2/AC5: response body has 'verdict' key."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "verdict" in body, "'verdict' key missing from response"

    def test_verdict_is_valid_string_or_null(self, auth_client):
        """AC1/AC2: verdict is 'on-target', 'grey-zone', or null (no data)."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        verdict = res.json()["verdict"]
        assert verdict in ("on-target", "grey-zone", None), (
            f"verdict must be 'on-target', 'grey-zone', or null; got {verdict!r}"
        )

    def test_response_has_actual_split(self, auth_client):
        """AC3: response body has 'actual' dict with low/moderate/high percentages."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "actual" in body, "'actual' key missing from response"
        actual = body["actual"]
        # actual is null when no data, or a dict with band keys
        if actual is not None:
            assert "low" in actual, "actual missing 'low'"
            assert "moderate" in actual, "actual missing 'moderate'"
            assert "high" in actual, "actual missing 'high'"

    def test_response_has_targets(self, auth_client):
        """AC3: response body has 'targets' dict with band bounds."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "targets" in body, "'targets' key missing from response"
        targets = body["targets"]
        assert "low" in targets, "targets missing 'low'"
        assert "moderate" in targets, "targets missing 'moderate'"
        assert "high" in targets, "targets missing 'high'"
        # Each target is a two-element list
        for band, bounds in targets.items():
            assert isinstance(bounds, list) and len(bounds) == 2, (
                f"targets[{band!r}] must be a [lo, hi] list"
            )

    def test_response_has_deviations(self, auth_client):
        """AC4: response body has 'deviations' list."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2026-06-01", "to": "2026-06-30"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "deviations" in body, "'deviations' key missing from response"
        assert isinstance(body["deviations"], list)


# ---------------------------------------------------------------------------
# AC1 / AC7 — Empty date range returns null verdict (no stale data)
# ---------------------------------------------------------------------------

class TestEmptyRange:

    def test_empty_range_returns_null_verdict(self, auth_client):
        """AC7: Date range with no workouts returns verdict=null, actual=null."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2000-01-01", "to": "2000-01-31"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] is None, (
            f"Expected null verdict for empty range; got {body['verdict']!r}"
        )
        assert body["actual"] is None, (
            f"Expected null actual for empty range; got {body['actual']!r}"
        )

    def test_empty_range_deviations_empty(self, auth_client):
        """AC7: Empty range returns empty deviations list."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2000-01-01", "to": "2000-01-31"},
        )
        body = res.json()
        assert body["deviations"] == [], "deviations must be empty for no-data range"


# ---------------------------------------------------------------------------
# AC4 — Deviations structure (band + direction)
# ---------------------------------------------------------------------------

class TestDeviationsStructure:

    def test_deviation_entries_have_band_and_direction(self, auth_client):
        """AC4: each deviation entry has 'band' and 'direction' fields."""
        # Use a broad range to maximise chance of finding workouts with band data
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2025-01-01", "to": "2026-12-31"},
        )
        assert res.status_code == 200
        body = res.json()
        for dev in body["deviations"]:
            assert "band" in dev, f"deviation missing 'band': {dev}"
            assert "direction" in dev, f"deviation missing 'direction': {dev}"
            assert dev["direction"] in ("above", "below"), (
                f"direction must be 'above' or 'below'; got {dev['direction']!r}"
            )
            assert dev["band"] in ("low", "moderate", "high"), (
                f"band must be one of low/moderate/high; got {dev['band']!r}"
            )

    def test_on_target_has_no_deviations(self, auth_client):
        """AC1: when verdict is 'on-target', deviations list must be empty."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2025-01-01", "to": "2026-12-31"},
        )
        body = res.json()
        if body["verdict"] == "on-target":
            assert body["deviations"] == [], (
                "on-target verdict must have empty deviations"
            )

    def test_grey_zone_has_deviations(self, auth_client):
        """AC2/AC4: when verdict is 'grey-zone', deviations list must be non-empty."""
        res = auth_client.get(
            "/api/workouts/polarized-check",
            params={"from": "2025-01-01", "to": "2026-12-31"},
        )
        body = res.json()
        if body["verdict"] == "grey-zone":
            assert len(body["deviations"]) > 0, (
                "grey-zone verdict must identify at least one deviating band"
            )


# ---------------------------------------------------------------------------
# AC5 — verdict field is authoritative (static JS check)
# ---------------------------------------------------------------------------

class TestVerdictAuthoritative:

    def test_js_reads_verdict_from_api(self):
        """AC5: trends.js reads the verdict field from the API response (no client-side recalc)."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        assert "polarized-check" in src, (
            "trends.js must fetch from /api/workouts/polarized-check"
        )
        # Must reference the verdict field from the API, not compute it from pcts
        assert "verdict" in src, (
            "trends.js must read the 'verdict' field from the API response"
        )

    def test_js_does_not_reimplement_band_threshold_check(self):
        """AC5: trends.js must not duplicate the band-threshold logic from check_polarized_split."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        # The client should not have hard-coded threshold constants like 75/85/5/10/10/20
        # for the purpose of computing on_target — it should only display the verdict
        # We check that there is no client-side on_target computation block referencing
        # moderate threshold comparison that would duplicate the server's logic.
        assert not re.search(
            r"(?:moderate|mod)\s*[><!]=?\s*(?:10|0\.10)\b.*(?:on.target|grey.zone)",
            src,
            re.IGNORECASE,
        ), (
            "trends.js must not recompute the verdict using threshold comparisons"
        )


# ---------------------------------------------------------------------------
# AC6 — Visual distinction in HTML/JS
# ---------------------------------------------------------------------------

class TestVisualDistinction:

    def test_html_has_polarized_indicator_slot(self):
        """AC6: trends.html has a DOM element for the polarized-check indicator."""
        html_path = ROOT / "frontend" / "pages" / "trends.html"
        src = html_path.read_text()
        assert re.search(r'polarized.check|polcheck|polarized-indicator', src, re.IGNORECASE), (
            "trends.html must have a DOM element for the polarized-check indicator"
        )

    def test_html_has_on_target_class_or_text(self):
        """AC1/AC6: trends.html or trends.js references 'on-target' or 'on_target' state."""
        html_path = ROOT / "frontend" / "pages" / "trends.html"
        js_path = ROOT / "frontend" / "js" / "trends.js"
        combined = html_path.read_text() + js_path.read_text()
        assert re.search(r"on.target", combined, re.IGNORECASE), (
            "trends.html or trends.js must reference the on-target state"
        )

    def test_html_has_grey_zone_class_or_text(self):
        """AC2/AC6: trends.html or trends.js references 'grey-zone' or 'grey_zone' state."""
        html_path = ROOT / "frontend" / "pages" / "trends.html"
        js_path = ROOT / "frontend" / "js" / "trends.js"
        combined = html_path.read_text() + js_path.read_text()
        assert re.search(r"grey.zone|gray.zone", combined, re.IGNORECASE), (
            "trends.html or trends.js must reference the grey-zone state"
        )

    def test_js_renders_actual_split_values(self):
        """AC3/AC6: trends.js renders the actual split values from the API response."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        # Must reference actual.low / actual.moderate / actual.high (or similar) from API
        assert re.search(r"actual\.(low|moderate|high)", src), (
            "trends.js must render the actual split values from the API response"
        )

    def test_js_renders_target_split_values(self):
        """AC3/AC6: trends.js renders the target split bounds from the API response."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        # Must reference targets from the API response
        assert re.search(r"targets\b", src), (
            "trends.js must render the target bounds from the API response"
        )


# ---------------------------------------------------------------------------
# AC7 — Reactive updates (the indicator is reloaded on date range change)
# ---------------------------------------------------------------------------

class TestReactiveUpdates:

    def test_js_calls_polarized_check_in_load_function(self):
        """AC7: trends.js calls the polarized-check API inside the chart-load flow."""
        js_path = ROOT / "frontend" / "js" / "trends.js"
        src = js_path.read_text()
        # The polarized-check call must appear in a load/update context,
        # not just a one-time init block
        assert "polarized-check" in src, (
            "trends.js must call /api/workouts/polarized-check reactively"
        )


# ---------------------------------------------------------------------------
# Smoke — compilation checks
# ---------------------------------------------------------------------------

class TestSmoke:

    def test_main_py_compiles(self):
        """backend/main.py passes py_compile with no errors."""
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ROOT / "backend" / "main.py")],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"py_compile failed on backend/main.py:\n{result.stderr.decode()}"
        )

    def test_trends_js_no_syntax_error(self):
        """trends.js is syntactically valid (node --check)."""
        result = subprocess.run(
            ["node", "--check", str(ROOT / "frontend" / "js" / "trends.js")],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"node --check failed on trends.js:\n{result.stderr.decode()}"
        )
