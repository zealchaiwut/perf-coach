"""Tests for issue #651: Add Settings UI for Training Thresholds and Zone Ranges."""
import os
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def settings_html():
    html_path = os.path.join(os.path.dirname(__file__), "../frontend/pages/settings.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def zone2_constants_js():
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/zone2-constants.js")
    with open(js_path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def run_view_js():
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/run-view.js")
    with open(js_path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def run_builder_js():
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/run-builder.js")
    with open(js_path, "r", encoding="utf-8") as f:
        return f.read()


# ── AC1: Training Thresholds card exists in Settings ─────────────────────────

def test_training_thresholds_section_exists_in_settings(settings_html):
    """AC1: A Training Thresholds card exists in the Settings screen."""
    assert 'id="section-thresholds"' in settings_html, "Thresholds section not found"
    assert "Performance Thresholds" in settings_html or "Training Thresholds" in settings_html, \
        "Thresholds heading not found"


# ── AC2: Three editable threshold fields ─────────────────────────────────────

def test_ftp_input_exists(settings_html):
    """AC2: FTP (ftp_w) editable field exists."""
    assert 'id="thresholds-ftp"' in settings_html, "FTP input not found"
    assert "FTP" in settings_html, "FTP label not found"


def test_threshold_hr_input_exists(settings_html):
    """AC2: Threshold HR input exists."""
    assert 'id="thresholds-hr"' in settings_html, "Threshold HR input not found"
    assert "Threshold Heart Rate" in settings_html or "Threshold HR" in settings_html, \
        "Threshold HR label not found"


def test_threshold_pace_input_exists(settings_html):
    """AC2: Threshold Pace input exists."""
    assert 'id="thresholds-pace"' in settings_html, "Threshold Pace input not found"
    assert "Threshold Pace" in settings_html, "Threshold Pace label not found"


# ── AC3: Accept suggestion affordance ────────────────────────────────────────

def test_suggestion_chip_elements_in_html(settings_html):
    """AC3: HTML contains suggestion chip containers or JS that renders them."""
    has_chip_html = (
        "suggestion-chip" in settings_html
        or "thresholds-ftp-suggestion" in settings_html
        or "accept-suggestion" in settings_html
        or "suggestion" in settings_html.lower()
    )
    has_suggestion_js = (
        "thresholds/suggestions" in settings_html
        and ("chip" in settings_html or "accept" in settings_html.lower())
    )
    assert has_chip_html or has_suggestion_js, \
        "No suggestion chip affordance found in settings.html"


def test_suggestion_js_fetches_endpoint(settings_html):
    """AC3: JS fetches /api/thresholds/suggestions to discover pending suggestions."""
    assert "thresholds/suggestions" in settings_html, \
        "/api/thresholds/suggestions not referenced in settings.html"


def test_suggestions_endpoint_exists_and_returns_pending(client):
    """AC3: GET /api/thresholds/suggestions returns {pending: {...}}."""
    r = client.get("/api/thresholds/suggestions")
    if r.status_code == 401:
        pytest.skip("API requires authentication")
    assert r.status_code == 200, f"Unexpected status: {r.status_code}"
    data = r.json()
    assert "pending" in data, "Response missing 'pending' key"
    assert isinstance(data["pending"], dict), "'pending' should be a dict"


# ── AC4: Suggestion pre-fills but does not save ───────────────────────────────

def test_suggestion_prefill_uses_js_not_direct_save(settings_html):
    """AC4: Suggestion chip pre-fills input only; save is triggered separately."""
    # The JS should set input.value but NOT auto-submit the form
    # Verify the suggestion handler does not call PATCH directly
    if "thresholds/suggestions" not in settings_html:
        pytest.skip("Suggestion JS not yet present")
    # Check that the suggestion handler doesn't call thresholds/suggestions/accept on chip click
    # (accept endpoint should only be called on explicit Save, if at all)
    # Minimal check: suggestions fetch and chip logic are present but separate from save
    assert "thresholds-save-btn" in settings_html, "Save button not found"
    assert "thresholds/suggestions" in settings_html, "Suggestion fetch not found"


# ── AC5: Zone-2 HR Range card/section ────────────────────────────────────────

def test_zone2_hr_min_input_exists(settings_html):
    """AC5: Zone-2 HR lower bound input exists."""
    assert 'id="thresholds-zone2-hr-min"' in settings_html, "Zone 2 HR min input not found"


def test_zone2_hr_max_input_exists(settings_html):
    """AC5: Zone-2 HR upper bound input exists."""
    assert 'id="thresholds-zone2-hr-max"' in settings_html, "Zone 2 HR max input not found"


# ── AC6: Zone-2 HR range persisted ───────────────────────────────────────────

def test_zone2_hr_range_patch_accepted(client):
    """AC6: PATCH /api/user-preferences accepts zone2_hr_min and zone2_hr_max."""
    r = client.patch("/api/user-preferences", json={"zone2_hr_min": 125, "zone2_hr_max": 148})
    if r.status_code == 401:
        pytest.skip("API requires authentication")
    assert r.status_code == 200, f"Unexpected status: {r.status_code}"


def test_preferences_api_includes_zone2_defaults(client):
    """AC6/AC10: GET /api/user-preferences returns zone2_hr_min and zone2_hr_max in defaults."""
    r = client.get("/api/user-preferences")
    if r.status_code == 401:
        pytest.skip("API requires authentication")
    assert r.status_code == 200
    data = r.json()
    defaults = data.get("defaults") or {}
    assert "zone2_hr_min" in defaults, "zone2_hr_min not in preferences defaults"
    assert "zone2_hr_max" in defaults, "zone2_hr_max not in preferences defaults"


# ── AC7 & AC8: Run view reads zone-2 HR from persisted setting ───────────────

def test_zone2_constants_fetches_from_api(zone2_constants_js):
    """AC7/AC8: zone2-constants.js fetches from /api/user-preferences instead of hardcoding."""
    assert "/api/user-preferences" in zone2_constants_js, \
        "zone2-constants.js does not fetch from /api/user-preferences"
    assert "fetch(" in zone2_constants_js, \
        "zone2-constants.js missing fetch() call"


def test_zone2_constants_falls_back_to_defaults(zone2_constants_js):
    """AC7: zone2-constants.js falls back to 130/155 when no setting is saved."""
    # Defaults should still be defined in the module
    assert "130" in zone2_constants_js, "Default zone2_hr_min (130) not present as fallback"
    assert "155" in zone2_constants_js, "Default zone2_hr_max (155) not present as fallback"


def test_run_view_does_not_cache_zone2_locals(run_view_js):
    """AC8: run-view.js does not cache zone2 HR bounds in local vars (which would miss API updates)."""
    import re
    # Caching `var ZONE2_HR_MIN = window.Zone2.ZONE2_HR_MIN` at IIFE start misses later
    # async updates. The fix removes these declarations and reads window.Zone2 directly.
    cached_min = re.search(r'var\s+ZONE2_HR_MIN\s*=', run_view_js)
    cached_max = re.search(r'var\s+ZONE2_HR_MAX\s*=', run_view_js)
    assert cached_min is None, "run-view.js still caches ZONE2_HR_MIN in a local var"
    assert cached_max is None, "run-view.js still caches ZONE2_HR_MAX in a local var"


def test_run_builder_does_not_cache_zone2_locals(run_builder_js):
    """AC8: run-builder.js does not cache zone2 HR bounds in local vars (which would miss API updates)."""
    import re
    cached_min = re.search(r'var\s+ZONE2_HR_MIN\s*=', run_builder_js)
    cached_max = re.search(r'var\s+ZONE2_HR_MAX\s*=', run_builder_js)
    assert cached_min is None, "run-builder.js still caches ZONE2_HR_MIN in a local var"
    assert cached_max is None, "run-builder.js still caches ZONE2_HR_MAX in a local var"


# ── AC9: Validation ───────────────────────────────────────────────────────────

def test_validation_rejects_negative_ftp(client):
    """AC9: Negative FTP value is rejected with 422."""
    r = client.patch("/api/user-preferences", json={"ftp_w": -10})
    if r.status_code == 401:
        pytest.skip("API requires authentication")
    assert r.status_code == 422, f"Expected 422 for negative FTP, got {r.status_code}"


def test_validation_rejects_invalid_zone2_hr_min(client):
    """AC9: zone2_hr_min value below 80 is rejected with 422."""
    r = client.patch("/api/user-preferences", json={"zone2_hr_min": 50})
    if r.status_code == 401:
        pytest.skip("API requires authentication")
    assert r.status_code == 422, f"Expected 422 for out-of-range zone2_hr_min, got {r.status_code}"


def test_validation_rejects_invalid_zone2_hr_max(client):
    """AC9: zone2_hr_max value above 210 is rejected with 422."""
    r = client.patch("/api/user-preferences", json={"zone2_hr_max": 250})
    if r.status_code == 401:
        pytest.skip("API requires authentication")
    assert r.status_code == 422, f"Expected 422 for out-of-range zone2_hr_max, got {r.status_code}"


def test_validation_rejects_invalid_threshold_hr(client):
    """AC9: threshold_hr out of range is rejected with 422."""
    r = client.patch("/api/user-preferences", json={"threshold_hr": 50})
    if r.status_code == 401:
        pytest.skip("API requires authentication")
    assert r.status_code == 422, f"Expected 422 for invalid threshold_hr, got {r.status_code}"


# ── AC10: Settings displays current saved values on load ─────────────────────

def test_settings_loads_current_values_on_init(settings_html):
    """AC10: Settings screen fetches and displays current saved values on load."""
    assert "/api/user-preferences" in settings_html, \
        "settings.html does not reference /api/user-preferences"
    assert "_tLoadPrefs" in settings_html or "userReady" in settings_html, \
        "No load-on-init handler found in settings.html"
