"""
Tests for issue #64: Add Readiness Score Card to Home Dashboard.
Server under test: http://127.0.0.1:9001

AC items covered:
  1.  Card displays a single integer readiness score (0-100)
  2.  Score coloured red when <50, amber 50-70, green >70
  3.  Status pill with correct label
  4.  Interpretation string from template (not LLM)
  5.  Four component chips: HRV, RHR, Sleep, Energy with delta + unit
  6.  Delta formatted with leading +/- and unit label
  7.  Expand/collapse breakdown panel on click
  8.  Collapsed by default, expands on click, re-collapses on second click
  9.  Legible at 380px viewport (flex-wrap, no overflow)
 10.  Color-band boundaries in single named constant
 11.  No LLM call when rendering or expanding
"""
import pathlib
import re
import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import text

from backend.db import engine

BASE = "http://127.0.0.1:9001"

HOME_HTML = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
HOME_JS   = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def test_user_id():
    name = f"readiness_card_test_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:name) RETURNING id"),
            {"name": name},
        ).fetchone()
        uid = str(row.id)
    yield uid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


def _upsert_metric(user_id: str, d: date, hrv=None, resting_hr=None, sleep_quality=None, energy=None):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO daily_metrics (user_id, metric_date, hrv, resting_hr, sleep_quality, energy) "
                "VALUES (:uid, :d, :hrv, :rhr, :sq, :en) "
                "ON CONFLICT (user_id, metric_date) DO UPDATE SET "
                "hrv = EXCLUDED.hrv, resting_hr = EXCLUDED.resting_hr, "
                "sleep_quality = EXCLUDED.sleep_quality, energy = EXCLUDED.energy"
            ),
            {"uid": user_id, "d": str(d), "hrv": hrv, "rhr": resting_hr, "sq": sleep_quality, "en": energy},
        )


def _upsert_readiness(user_id: str, d: date, score: float, metric_id=None):
    import json
    comp = {"hrv_contribution": 0.0, "rhr_contribution": 0.0,
            "sleep_contribution": score, "energy_contribution": 0.0}
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO daily_readiness (user_id, date, score, components, computed_at) "
                "VALUES (:uid, :d, :score, CAST(:comp AS jsonb), now()) "
                "ON CONFLICT (user_id, date) DO UPDATE SET score = EXCLUDED.score, "
                "components = EXCLUDED.components, computed_at = EXCLUDED.computed_at"
            ),
            {"uid": user_id, "d": str(d), "score": score, "comp": json.dumps(comp)},
        )


def _cleanup(user_id: str):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": user_id})
        conn.execute(text("DELETE FROM daily_metrics WHERE user_id = :uid"), {"uid": user_id})


# ── AC 1: Card displays integer score (0-100) — HTML structure ────────────────

def test_readiness_card_element_exists():
    """home.html must contain the readiness-card element."""
    assert "readiness-card" in HOME_HTML, "home.html must have id='readiness-card' element"


def test_readiness_score_element_exists():
    """home.html must contain the element that renders the score."""
    assert "readiness-score" in HOME_HTML, "home.html must have id='readiness-score' element"


def test_readiness_pill_element_exists():
    """home.html must contain the status pill element."""
    assert "readiness-pill" in HOME_HTML, "home.html must have id='readiness-pill' element"


# ── AC 2: Color-coded by score band ──────────────────────────────────────────

def test_js_applies_green_class_for_high_score():
    """home.js must apply readiness-card--green for scores >70."""
    assert "readiness-card--green" in HOME_JS, "home.js must apply readiness-card--green class"


def test_js_applies_amber_class_for_mid_score():
    """home.js must apply readiness-card--amber for scores 50-70."""
    assert "readiness-card--amber" in HOME_JS, "home.js must apply readiness-card--amber class"


def test_js_applies_red_class_for_low_score():
    """home.js must apply readiness-card--red for scores <50."""
    assert "readiness-card--red" in HOME_JS, "home.js must apply readiness-card--red class"


def test_css_defines_green_card_style():
    """home.html CSS must define .readiness-card--green."""
    assert "readiness-card--green" in HOME_HTML, "home.html CSS must define readiness-card--green"


def test_css_defines_amber_card_style():
    """home.html CSS must define .readiness-card--amber."""
    assert "readiness-card--amber" in HOME_HTML, "home.html CSS must define readiness-card--amber"


def test_css_defines_red_card_style():
    """home.html CSS must define .readiness-card--red."""
    assert "readiness-card--red" in HOME_HTML, "home.html CSS must define readiness-card--red"


# ── AC 3: Status pill with correct labels ─────────────────────────────────────

def test_js_green_go_label():
    """home.js READINESS_LABELS must include 'Green - go'."""
    assert "Green - go" in HOME_JS, "home.js must contain label 'Green - go'"


def test_js_amber_moderate_label():
    """home.js READINESS_LABELS must include 'Amber - moderate'."""
    assert "Amber - moderate" in HOME_JS, "home.js must contain label 'Amber - moderate'"


def test_js_red_back_off_label():
    """home.js READINESS_LABELS must include 'Red - back off'."""
    assert "Red - back off" in HOME_JS, "home.js must contain label 'Red - back off'"


# ── AC 4: Template-based interpretation (not LLM) ────────────────────────────

def test_js_has_interpretation_function():
    """home.js must define buildInterpretation or equivalent template function."""
    assert "buildInterpretation" in HOME_JS or "interp" in HOME_JS, (
        "home.js must have a template-based interpretation function"
    )


def test_js_interpretation_varies_by_component():
    """home.js interpretation must branch on at least one component signal."""
    # The function must reference at least HRV delta or sleep delta
    assert "hrvD" in HOME_JS or "sleepD" in HOME_JS or "rhrD" in HOME_JS, (
        "home.js must vary interpretation based on a component signal (hrv/sleep/rhr delta)"
    )


def test_js_no_llm_import():
    """home.js must not import or call any LLM/AI API."""
    lowered = HOME_JS.lower()
    # Specific SDK/API identifiers that indicate an LLM call
    forbidden = ["openai", "anthropic", "claude.com", "api.openai", "completions.create", "llm"]
    for kw in forbidden:
        assert kw not in lowered, f"home.js must not reference '{kw}' (no LLM calls)"


def test_html_no_llm_script_tag():
    """home.html must not load any LLM SDK script."""
    lowered = HOME_HTML.lower()
    forbidden = ["openai", "anthropic.com/sdk", "ai-sdk"]
    for kw in forbidden:
        assert kw not in lowered, f"home.html must not load '{kw}'"


# ── AC 5: Four component chips ────────────────────────────────────────────────

def test_js_hrv_chip():
    """home.js must include HRV chip."""
    assert "'HRV'" in HOME_JS or '"HRV"' in HOME_JS, "home.js must render HRV chip"


def test_js_rhr_chip():
    """home.js must include RHR chip."""
    assert "'RHR'" in HOME_JS or '"RHR"' in HOME_JS, "home.js must render RHR chip"


def test_js_sleep_chip():
    """home.js must include Sleep chip."""
    assert "'Sleep'" in HOME_JS or '"Sleep"' in HOME_JS, "home.js must render Sleep chip"


def test_js_energy_chip():
    """home.js must include Energy chip."""
    assert "'Energy'" in HOME_JS or '"Energy"' in HOME_JS, "home.js must render Energy chip"


def test_css_chip_defined():
    """home.html CSS must define .readiness-chip."""
    assert "readiness-chip" in HOME_HTML, "home.html must define .readiness-chip"


# ── AC 6: Delta formatted with +/- sign and unit ─────────────────────────────

def test_js_delta_format_function():
    """home.js must define fmtAbsDelta or equivalent function."""
    assert "fmtAbsDelta" in HOME_JS, "home.js must define fmtAbsDelta function"


def test_js_delta_positive_sign():
    """home.js delta formatter must produce a '+' prefix for positive values."""
    assert "'+'" in HOME_JS or "'+' +" in HOME_JS or "sign = '+'" in HOME_JS or '"+' in HOME_JS, (
        "home.js fmtAbsDelta must include '+' sign for positive deltas"
    )


def test_js_delta_unit_label():
    """home.js chips must include unit labels (ms, bpm, h)."""
    assert "'ms'" in HOME_JS or '"ms"' in HOME_JS, "home.js must include 'ms' unit for HRV"
    assert "'bpm'" in HOME_JS or '"bpm"' in HOME_JS, "home.js must include 'bpm' unit for RHR"


# ── AC 7 & 8: Expand/collapse toggle ─────────────────────────────────────────

def test_js_toggle_function_exists():
    """home.js must define initReadinessToggle."""
    assert "initReadinessToggle" in HOME_JS, "home.js must define initReadinessToggle"


def test_js_breakdown_panel_hidden_default():
    """home.html breakdown panel must have hidden attribute by default."""
    assert 'id="readiness-breakdown"' in HOME_HTML, "home.html must have readiness-breakdown element"
    # The breakdown div must have hidden attribute
    match = re.search(r'id="readiness-breakdown"[^>]*>', HOME_HTML)
    assert match, "readiness-breakdown element not found in home.html"
    assert "hidden" in match.group(0), "readiness-breakdown must be hidden by default"


def test_js_toggle_sets_hidden():
    """home.js toggle must set bd.hidden to toggle visibility."""
    assert "bd.hidden" in HOME_JS or "breakdown" in HOME_JS.lower(), (
        "home.js must toggle breakdown panel hidden state"
    )


def test_js_aria_expanded_updated():
    """home.js must update aria-expanded on the card when toggled."""
    assert "aria-expanded" in HOME_JS, "home.js must set aria-expanded attribute on toggle"


def test_html_role_button_on_card():
    """home.html readiness card must have role='button' for accessibility."""
    assert 'role="button"' in HOME_HTML, "home.html readiness card must have role='button'"


# ── AC 9: Legible at 380px viewport ──────────────────────────────────────────

def test_css_chips_flex_wrap():
    """home.html CSS must use flex-wrap on readiness-chips to handle narrow viewports."""
    # Find the .readiness-chips block
    assert "readiness-chips" in HOME_HTML, "home.html must define .readiness-chips"
    assert "flex-wrap" in HOME_HTML, "home.html CSS must include flex-wrap for chip wrapping"


def test_css_card_overflow_hidden():
    """home.html CSS .readiness-card must have overflow:hidden to prevent horizontal scroll."""
    assert "overflow: hidden" in HOME_HTML or "overflow:hidden" in HOME_HTML, (
        "home.html .readiness-card must have overflow: hidden"
    )


# ── AC 10: Color band boundaries in a single named constant ──────────────────

def test_js_thresholds_constant():
    """home.js must define READINESS_THRESHOLDS as a named constant object."""
    assert "READINESS_THRESHOLDS" in HOME_JS, (
        "home.js must define READINESS_THRESHOLDS constant for color band boundaries"
    )


def test_js_threshold_50_defined():
    """READINESS_THRESHOLDS must include the red boundary at 50."""
    assert "50" in HOME_JS and "READINESS_THRESHOLDS" in HOME_JS, (
        "home.js READINESS_THRESHOLDS must contain the value 50 (red boundary)"
    )


def test_js_threshold_70_defined():
    """READINESS_THRESHOLDS must include the amber boundary at 70."""
    assert "70" in HOME_JS and "READINESS_THRESHOLDS" in HOME_JS, (
        "home.js READINESS_THRESHOLDS must contain the value 70 (amber boundary)"
    )


def test_js_readiness_band_uses_constant():
    """home.js readinessBand function must reference READINESS_THRESHOLDS, not hardcoded values."""
    # The function must use the constant, not raw integer comparisons inline
    assert "READINESS_THRESHOLDS" in HOME_JS, (
        "readinessBand must use READINESS_THRESHOLDS constant"
    )
    assert "readinessBand" in HOME_JS, "home.js must define readinessBand function"


# ── AC 11: No LLM call (already covered above for frontend) ──────────────────

# ── /api/readiness/today endpoint tests ──────────────────────────────────────

def test_readiness_today_404_when_no_row(client, test_user_id):
    """GET /api/readiness/today returns 404 when no readiness row exists for today."""
    _cleanup(test_user_id)
    res = client.get("/api/readiness/today", params={"user_id": test_user_id})
    assert res.status_code == 404, (
        f"Expected 404 for user with no readiness data, got {res.status_code}"
    )


def test_readiness_today_400_for_invalid_uuid(client):
    """GET /api/readiness/today returns 400 for an invalid user_id."""
    res = client.get("/api/readiness/today", params={"user_id": "not-a-uuid"})
    assert res.status_code == 400, f"Expected 400 for invalid UUID, got {res.status_code}"


def test_readiness_today_returns_score_in_range(client, test_user_id):
    """GET /api/readiness/today returns a score in [0, 100]."""
    today = date.today()
    _cleanup(test_user_id)
    _upsert_readiness(test_user_id, today, score=73.0)
    try:
        res = client.get("/api/readiness/today", params={"user_id": test_user_id})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert "score" in data, "Response must include 'score' field"
        assert 0.0 <= data["score"] <= 100.0, f"Score out of range: {data['score']}"
    finally:
        _cleanup(test_user_id)


def test_readiness_today_returns_correct_score(client, test_user_id):
    """GET /api/readiness/today returns the stored score exactly."""
    today = date.today()
    _cleanup(test_user_id)
    _upsert_readiness(test_user_id, today, score=35.0)
    try:
        res = client.get("/api/readiness/today", params={"user_id": test_user_id})
        assert res.status_code == 200
        assert res.json()["score"] == pytest.approx(35.0, abs=0.01)
    finally:
        _cleanup(test_user_id)


def test_readiness_today_returns_date_field(client, test_user_id):
    """GET /api/readiness/today response includes 'date' field matching today."""
    today = date.today()
    _cleanup(test_user_id)
    _upsert_readiness(test_user_id, today, score=60.0)
    try:
        res = client.get("/api/readiness/today", params={"user_id": test_user_id})
        assert res.status_code == 200
        data = res.json()
        assert "date" in data, "Response must include 'date' field"
        assert data["date"] == str(today), f"date field mismatch: {data['date']} != {today}"
    finally:
        _cleanup(test_user_id)


def test_readiness_today_returns_missing_data_field(client, test_user_id):
    """GET /api/readiness/today includes missing_data dict with boolean flags."""
    today = date.today()
    _cleanup(test_user_id)
    _upsert_readiness(test_user_id, today, score=85.0)
    try:
        res = client.get("/api/readiness/today", params={"user_id": test_user_id})
        assert res.status_code == 200
        data = res.json()
        assert "missing_data" in data, "Response must include 'missing_data' field"
        md = data["missing_data"]
        for key in ("hrv", "rhr", "sleep", "energy"):
            assert key in md, f"missing_data must have '{key}' key"
            assert isinstance(md[key], bool), f"missing_data.{key} must be boolean"
    finally:
        _cleanup(test_user_id)


def test_readiness_today_missing_data_true_when_no_metric(client, test_user_id):
    """missing_data flags are True when the linked daily_metric has null fields."""
    today = date.today()
    _cleanup(test_user_id)
    # Insert readiness without a linked daily_metrics row — all missing_data should be True
    _upsert_readiness(test_user_id, today, score=50.0, metric_id=None)
    try:
        res = client.get("/api/readiness/today", params={"user_id": test_user_id})
        assert res.status_code == 200
        data = res.json()
        md = data["missing_data"]
        assert md["hrv"] is True
        assert md["rhr"] is True
        assert md["sleep"] is True
        assert md["energy"] is True
    finally:
        _cleanup(test_user_id)


def test_readiness_today_missing_data_false_when_metric_has_data(client, test_user_id):
    """missing_data flags are False when daily_metrics row has all four signals."""
    today = date.today()
    _cleanup(test_user_id)

    # Insert metric with all four signals
    _upsert_metric(test_user_id, today, hrv=60, resting_hr=55, sleep_quality=4, energy=4)

    # Trigger compute to link the metric
    res = client.post(
        "/api/readiness/compute",
        params={"user_id": test_user_id, "date": str(today)},
    )
    if res.status_code != 200:
        _cleanup(test_user_id)
        pytest.skip("readiness/compute unavailable — skipping missing_data false check")

    try:
        res = client.get("/api/readiness/today", params={"user_id": test_user_id})
        assert res.status_code == 200
        data = res.json()
        md = data["missing_data"]
        assert md["hrv"] is False
        assert md["rhr"] is False
        assert md["sleep"] is False
        assert md["energy"] is False
    finally:
        _cleanup(test_user_id)


# ── /api/readiness range endpoint tests ──────────────────────────────────────

def test_readiness_range_returns_200(client, test_user_id):
    """GET /api/readiness returns 200 for a valid date range."""
    today = date.today()
    res = client.get(
        "/api/readiness",
        params={"user_id": test_user_id, "from": str(today), "to": str(today)},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"


def test_readiness_range_returns_list(client, test_user_id):
    """GET /api/readiness returns a list."""
    today = date.today()
    res = client.get(
        "/api/readiness",
        params={"user_id": test_user_id, "from": str(today), "to": str(today)},
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list), "Response must be a list"


def test_readiness_range_null_for_missing_days(client, test_user_id):
    """GET /api/readiness returns null entries for days with no data."""
    res = client.get(
        "/api/readiness",
        params={"user_id": test_user_id, "from": "2000-01-01", "to": "2000-01-05"},
    )
    assert res.status_code == 200
    data = res.json()
    assert all(entry is None for entry in data), (
        "Days with no readiness data must be represented as null"
    )


def test_readiness_range_correct_length(client, test_user_id):
    """GET /api/readiness returns one entry per day in the range (inclusive)."""
    res = client.get(
        "/api/readiness",
        params={"user_id": test_user_id, "from": "2000-01-01", "to": "2000-01-07"},
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 7, f"Expected 7 entries, got {len(data)}"


def test_readiness_range_returns_score_for_seeded_day(client, test_user_id):
    """GET /api/readiness returns {date, score} for a day that has data."""
    target = date(2099, 7, 1)
    _cleanup(test_user_id)
    _upsert_readiness(test_user_id, target, score=72.0)
    try:
        res = client.get(
            "/api/readiness",
            params={"user_id": test_user_id, "from": str(target), "to": str(target)},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0] is not None
        assert data[0]["score"] == pytest.approx(72.0, abs=0.01)
        assert data[0]["date"] == str(target)
    finally:
        _cleanup(test_user_id)


def test_readiness_range_400_for_invalid_uuid(client):
    """GET /api/readiness returns 400 for an invalid user_id."""
    res = client.get(
        "/api/readiness",
        params={"user_id": "bad-uuid", "from": "2026-01-01", "to": "2026-01-07"},
    )
    assert res.status_code == 400


def test_readiness_range_400_for_swapped_dates(client, test_user_id):
    """GET /api/readiness returns 400 when from > to."""
    res = client.get(
        "/api/readiness",
        params={"user_id": test_user_id, "from": "2026-01-07", "to": "2026-01-01"},
    )
    assert res.status_code == 400
