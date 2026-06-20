"""Tests for issue #697: Add readiness endpoint exposing CTL, ATL, TSB tiles.

Covers AC items:
  1.  GET /api/readiness exists and returns 200 for authenticated user
  2.  Response body includes ctl, atl, tsb, readiness_label, series
  3.  Endpoint delegates DB reads to compute_fitness_series (no raw query in routing)
  4.  Threshold comparisons use named constants, not magic numbers
  5.  building_baseline=true → ctl/atl/tsb/readiness_label are null, series=[]
  6.  Endpoint calls compute_fitness_series
  7.  Fitness tile = CTL, Fatigue tile = ATL, Freshness tile = TSB (JS check)
  8.  building_baseline tiles show "Building baseline" placeholder (JS check)
  9.  series used by chart component without errors (JS check)
 10.  Unit tests: normal shape, building_baseline suppression, label for ≥3 TSB ranges
 11.  401 for unauthenticated requests
"""
import inspect
import pathlib
import os

import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")

JS = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-log.js").read_text()


# ── Unit tests: pure-function behaviour ──────────────────────────────────────

def test_readiness_label_fatigued():
    """AC10: readiness_label returns 'Fatigued' for TSB below FORM_BURIED_CEILING."""
    from backend.services.training_load import readiness_label, FORM_BURIED_CEILING, READINESS_LABEL_FATIGUED
    tsb = FORM_BURIED_CEILING - 1.0
    assert readiness_label(tsb) == READINESS_LABEL_FATIGUED


def test_readiness_label_optimal():
    """AC10: readiness_label returns 'Optimal' for TSB in the neutral band."""
    from backend.services.training_load import (
        readiness_label, FORM_BURIED_CEILING, FORM_FRESH_FLOOR, READINESS_LABEL_OPTIMAL
    )
    tsb = (FORM_BURIED_CEILING + FORM_FRESH_FLOOR) / 2.0
    assert readiness_label(tsb) == READINESS_LABEL_OPTIMAL


def test_readiness_label_fresh():
    """AC10: readiness_label returns 'Fresh' for TSB at or above FORM_FRESH_FLOOR."""
    from backend.services.training_load import readiness_label, FORM_FRESH_FLOOR, READINESS_LABEL_FRESH
    tsb = FORM_FRESH_FLOOR + 1.0
    assert readiness_label(tsb) == READINESS_LABEL_FRESH


def test_readiness_label_boundary_buried_ceiling():
    """AC10: TSB exactly at FORM_BURIED_CEILING is 'Optimal', not 'Fatigued'."""
    from backend.services.training_load import readiness_label, FORM_BURIED_CEILING, READINESS_LABEL_OPTIMAL
    assert readiness_label(FORM_BURIED_CEILING) == READINESS_LABEL_OPTIMAL


def test_readiness_label_boundary_fresh_floor():
    """AC10: TSB exactly at FORM_FRESH_FLOOR is 'Fresh'."""
    from backend.services.training_load import readiness_label, FORM_FRESH_FLOOR, READINESS_LABEL_FRESH
    assert readiness_label(FORM_FRESH_FLOOR) == READINESS_LABEL_FRESH


def test_readiness_label_uses_named_constants():
    """AC4: readiness_label comparison lines reference named constants, not literals."""
    from backend.services.training_load import readiness_label
    lines = inspect.getsource(readiness_label).splitlines()
    # Skip docstring lines (inside triple-quote block); only inspect comparison lines.
    comparison_lines = [l for l in lines if "< " in l or ">= " in l or ">" in l]
    for line in comparison_lines:
        assert "-10" not in line, f"Magic number -10 found in comparison: {line!r}"
        assert " 5.0" not in line, f"Magic number 5.0 found in comparison: {line!r}"


def test_compute_fitness_series_callable():
    """AC6: compute_fitness_series exists and is callable."""
    from backend.services.training_load import compute_fitness_series
    assert callable(compute_fitness_series)


def test_compute_fitness_series_delegates_to_compute_load_curves():
    """AC6: compute_fitness_series calls compute_load_curves (verified via source inspection)."""
    from backend.services.training_load import compute_fitness_series
    source = inspect.getsource(compute_fitness_series)
    assert "compute_load_curves" in source, (
        "compute_fitness_series must delegate computation to compute_load_curves"
    )


def test_compute_fitness_series_no_inline_ewma():
    """AC6: compute_fitness_series does not re-implement the EWMA calculation inline."""
    from backend.services.training_load import compute_fitness_series
    source = inspect.getsource(compute_fitness_series)
    assert "exp(" not in source, "compute_fitness_series must not re-implement EWMA math"


def test_baseline_constants_exist():
    """AC4: BASELINE_WINDOW_DAYS and BASELINE_MIN_WORKOUT_DAYS are named constants."""
    from backend.services.training_load import BASELINE_WINDOW_DAYS, BASELINE_MIN_WORKOUT_DAYS
    assert isinstance(BASELINE_WINDOW_DAYS, int) and BASELINE_WINDOW_DAYS > 0
    assert isinstance(BASELINE_MIN_WORKOUT_DAYS, int) and BASELINE_MIN_WORKOUT_DAYS > 0


def test_readiness_label_constants_exist():
    """AC4: READINESS_LABEL_* constants are exported from training_load."""
    from backend.services.training_load import (
        READINESS_LABEL_FATIGUED, READINESS_LABEL_OPTIMAL, READINESS_LABEL_FRESH
    )
    assert READINESS_LABEL_FATIGUED == "Fatigued"
    assert READINESS_LABEL_OPTIMAL == "Optimal"
    assert READINESS_LABEL_FRESH == "Fresh"


# ── Endpoint source inspection ────────────────────────────────────────────────

def test_endpoint_calls_compute_fitness_series():
    """AC6: The GET /api/readiness handler calls compute_fitness_series."""
    import backend.main as m
    source = inspect.getsource(m.get_readiness)
    assert "compute_fitness_series" in source, (
        "get_readiness must call compute_fitness_series to derive metric values"
    )


def test_endpoint_no_inline_query_in_fitness_branch():
    """AC3: The no-params branch of get_readiness contains no raw SQL SELECT for TSS/CTL."""
    import backend.main as m
    source = inspect.getsource(m.get_readiness)
    # The legacy branch may have raw SQL; we check that the only raw query is inside
    # the from_date branch (contains "daily_readiness" table). The fitness branch
    # must not contain a SELECT for workouts/training_load.
    assert source.count("SELECT") <= 1, (
        "Only the legacy wellness-score branch should contain a raw SELECT; "
        "the fitness-state branch must delegate via compute_fitness_series"
    )


# ── Frontend JS checks ────────────────────────────────────────────────────────

def test_js_fetches_api_readiness():
    """AC1/JS: training-log.js calls /api/readiness (no-params URL)."""
    assert "'/api/readiness'" in JS or '"/api/readiness"' in JS, (
        "training-log.js must fetch /api/readiness for the readiness widget"
    )


def test_js_renders_fitness_tile():
    """AC7: training-log.js renders a 'Fitness' tile for CTL."""
    assert "'Fitness'" in JS or '"Fitness"' in JS, (
        "training-log.js must render a Fitness tile label"
    )


def test_js_renders_fatigue_tile():
    """AC7: training-log.js renders a 'Fatigue' tile for ATL."""
    assert "'Fatigue'" in JS or '"Fatigue"' in JS, (
        "training-log.js must render a Fatigue tile label"
    )


def test_js_renders_freshness_tile():
    """AC7: training-log.js renders a 'Freshness' tile for TSB."""
    assert "'Freshness'" in JS or '"Freshness"' in JS, (
        "training-log.js must render a Freshness tile label (was 'Form')"
    )


def test_js_building_baseline_message():
    """AC8: training-log.js shows 'Building baseline' placeholder text."""
    assert "Building baseline" in JS, (
        "training-log.js must display 'Building baseline' when building_baseline is true"
    )


def test_js_uses_series_for_sparkline():
    """AC9: training-log.js references data.series for sparkline rendering."""
    assert "data.series" in JS or ".series" in JS, (
        "training-log.js must use the series array from the API response for sparklines"
    )


def test_js_renders_sparkline_canvas():
    """AC9: training-log.js creates canvas elements for sparkline charts."""
    assert "sparkline" in JS.lower() or "rw-spark" in JS, (
        "training-log.js must render sparkline canvas elements using the series data"
    )


# ── Integration tests (require running UAT server) ────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def auth_client():
    """Client with a valid session for the test user."""
    with httpx.Client(base_url=BASE, timeout=10.0) as c:
        resp = c.post("/api/auth/login", json={"username": "testuser", "password": "TestPass123!"})
        if resp.status_code != 200:
            pytest.skip("testuser not available on UAT server")
        yield c


def test_endpoint_requires_auth(client):
    """AC11: GET /api/readiness returns 401 for unauthenticated requests."""
    resp = client.get("/api/readiness")
    assert resp.status_code == 401, (
        f"Unauthenticated GET /api/readiness must return 401, got {resp.status_code}"
    )


def test_endpoint_200_for_authenticated_user(auth_client):
    """AC1: GET /api/readiness returns 200 for an authenticated user."""
    resp = auth_client.get("/api/readiness")
    assert resp.status_code == 200, (
        f"Authenticated GET /api/readiness must return 200, got {resp.status_code}: {resp.text}"
    )


def test_endpoint_response_has_building_baseline_key(auth_client):
    """AC2/AC5: Response always includes building_baseline key."""
    resp = auth_client.get("/api/readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict), "Response must be a JSON object, not a list"
    assert "building_baseline" in data, "Response must contain 'building_baseline'"


def test_endpoint_normal_response_shape(auth_client):
    """AC2: When building_baseline is false, response includes ctl, atl, tsb, readiness_label, series."""
    resp = auth_client.get("/api/readiness")
    assert resp.status_code == 200
    data = resp.json()
    if data.get("building_baseline"):
        pytest.skip("Test user is in building_baseline state; cannot verify normal shape")
    for key in ("ctl", "atl", "tsb", "readiness_label", "series"):
        assert key in data, f"Response must contain '{key}'"
    assert isinstance(data["ctl"], (int, float)), "ctl must be numeric"
    assert isinstance(data["atl"], (int, float)), "atl must be numeric"
    assert isinstance(data["tsb"], (int, float)), "tsb must be numeric"
    assert isinstance(data["readiness_label"], str), "readiness_label must be a string"
    assert isinstance(data["series"], list), "series must be a list"


def test_endpoint_building_baseline_suppression(auth_client):
    """AC5: When building_baseline is true, numeric fields are null and series is empty."""
    resp = auth_client.get("/api/readiness")
    assert resp.status_code == 200
    data = resp.json()
    if not data.get("building_baseline"):
        pytest.skip("Test user has sufficient training history; cannot verify suppression")
    assert data.get("ctl") is None, "ctl must be null when building_baseline"
    assert data.get("atl") is None, "atl must be null when building_baseline"
    assert data.get("tsb") is None, "tsb must be null when building_baseline"
    assert data.get("readiness_label") is None, "readiness_label must be null when building_baseline"
    assert data.get("series") == [], "series must be empty list when building_baseline"


def test_legacy_wellness_range_still_works(auth_client):
    """Backward compat: GET /api/readiness?from=...&to=... still returns a list."""
    resp = auth_client.get("/api/readiness", params={"from": "2000-01-01", "to": "2000-01-03"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list), "Range query must return a list, not a dict"
    assert len(data) == 3, "Range query must return one entry per day"


def test_series_entries_have_date_ctl_atl_tsb(auth_client):
    """AC2: Each entry in the series array has date, ctl, atl, tsb."""
    resp = auth_client.get("/api/readiness")
    assert resp.status_code == 200
    data = resp.json()
    if data.get("building_baseline") or not data.get("series"):
        pytest.skip("No series data available to inspect")
    entry = data["series"][0]
    for key in ("date", "ctl", "atl", "tsb"):
        assert key in entry, f"series entry must contain '{key}'"
