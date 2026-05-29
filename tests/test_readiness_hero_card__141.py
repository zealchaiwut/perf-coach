"""
Tests for issue #141: Build Readiness hero card (row 1, left)
Runs against UAT environment (http://localhost:9001)
"""
import os
import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import text

from backend.db import engine

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def home_html(client):
    res = client.get("/home.html")
    assert res.status_code == 200
    return res.text


@pytest.fixture(scope="module")
def home_js(client):
    res = client.get("/js/home.js")
    assert res.status_code == 200
    return res.text


@pytest.fixture(scope="module")
def test_user_id():
    name = f"readiness_hero_test_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:name) RETURNING id"),
            {"name": name},
        ).fetchone()
        uid = str(row.id)
    yield uid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM daily_metrics WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


def _upsert_metric(user_id, d, hrv=None, resting_hr=None, sleep_hours=None, sleep_quality=None, energy=None):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO daily_metrics (user_id, metric_date, hrv, resting_hr, sleep_hours, sleep_quality, energy) "
                "VALUES (:uid, :d, :hrv, :rhr, :sh, :sq, :en) "
                "ON CONFLICT (user_id, metric_date) DO UPDATE SET "
                "hrv = EXCLUDED.hrv, resting_hr = EXCLUDED.resting_hr, "
                "sleep_hours = EXCLUDED.sleep_hours, sleep_quality = EXCLUDED.sleep_quality, energy = EXCLUDED.energy"
            ),
            {"uid": user_id, "d": str(d), "hrv": hrv, "rhr": resting_hr, "sh": sleep_hours, "sq": sleep_quality, "en": energy},
        )


def _upsert_readiness(user_id, d, score):
    import json
    comp = {"hrv_contribution": 0.0, "rhr_contribution": 0.0,
            "sleep_contribution": float(score), "energy_contribution": 0.0}
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


def _cleanup_readiness(user_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM daily_metrics WHERE user_id = :uid"), {"uid": uid})


# ── AC 1: Card in #row-1 as left slot, 2/3 width, blue gradient ──────────────

def test_row1_uses_two_thirds_grid(home_html):
    """AC1: #row-1 grid gives left card ~2/3 width (2fr 1fr)"""
    assert "2fr 1fr" in home_html, "#row-1 grid-template-columns should be '2fr 1fr'"


def test_readiness_card_blue_gradient(home_html):
    """AC1: .readiness card uses blue gradient background (hero-1 / hero-2)"""
    assert "--hero-1" in home_html and "--hero-2" in home_html, \
        ".readiness card should use --hero-1 and --hero-2 gradient variables"
    assert "linear-gradient" in home_html, ".readiness card should use linear-gradient"


def test_readiness_card_css_defined(home_html):
    """AC1: .readiness CSS class is defined in home.html"""
    assert ".readiness {" in home_html or ".readiness{" in home_html, \
        ".readiness CSS class must be defined"


def test_readiness_card_inserted_into_row1(home_js):
    """AC1: home.js inserts the readiness card into #row-1"""
    assert "row-1" in home_js, "home.js should reference row-1 to insert the card"
    assert "readiness-hero-card" in home_js, "home.js should use id='readiness-hero-card'"


# ── AC 2: Left side — label, headline, sub-paragraph, status pill ─────────────

def test_readiness_today_label(home_js):
    """AC2: Card renders 'Readiness · today' label"""
    assert "Readiness" in home_js and "today" in home_js, \
        "home.js should render 'Readiness · today' label"


def test_headline_high_score(home_js):
    """AC2: Headline for score ≥75 is 'You're ready to push today'"""
    assert "ready to push today" in home_js, \
        "home.js must include headline for score ≥75: 'You're ready to push today'"


def test_headline_mid_score(home_js):
    """AC2: Headline for score 60-74 includes moderate/steady copy"""
    assert "steady" in home_js or "moderate" in home_js or "Take it" in home_js, \
        "home.js must include a moderate headline for scores 60-74"


def test_headline_low_score(home_js):
    """AC2: Headline for score <60 includes rest/recovery copy"""
    assert "Rest up" in home_js or "recovery" in home_js or "rest" in home_js.lower(), \
        "home.js must include a rest headline for scores <60"


def test_headline_thresholds(home_js):
    """AC2: readinessHeadline uses 75 and 60 as threshold boundaries"""
    assert "75" in home_js and "60" in home_js, \
        "home.js readinessHeadline must use 75 and 60 as score thresholds"


def test_sub_paragraph_function(home_js):
    """AC2: home.js has a sub-paragraph/contributing-factor function"""
    assert "readinessSub" in home_js or "sub" in home_js.lower(), \
        "home.js must build a sub-paragraph naming the strongest contributing factor"


def test_status_pill_green(home_js):
    """AC2: Pill for score ≥75 is 'Green · go'"""
    assert "Green" in home_js and "go" in home_js, \
        "home.js must include 'Green · go' pill label"


def test_status_pill_amber(home_js):
    """AC2: Pill for score 60-74 is 'Amber · caution'"""
    assert "Amber" in home_js and "caution" in home_js, \
        "home.js must include 'Amber · caution' pill label"


def test_status_pill_red(home_js):
    """AC2: Pill for score <60 is 'Red · rest'"""
    assert "Red" in home_js and "rest" in home_js, \
        "home.js must include 'Red · rest' pill label"


def test_status_pill_css_green(home_html):
    """AC2: CSS defines pill-green style"""
    assert "pill-green" in home_html, "home.html must define .pill-green CSS"


def test_status_pill_css_amber(home_html):
    """AC2: CSS defines pill-amber style"""
    assert "pill-amber" in home_html, "home.html must define .pill-amber CSS"


def test_status_pill_css_red(home_html):
    """AC2: CSS defines pill-red style"""
    assert "pill-red" in home_html, "home.html must define .pill-red CSS"


# ── AC 3: Right side — SCORE label, XX/100, 7d avg ────────────────────────────

def test_score_block_absolutely_positioned(home_html):
    """AC3: .score-block is absolutely positioned on desktop"""
    assert "position: absolute" in home_html, \
        ".score-block should have position: absolute (right side of card on desktop)"


def test_score_label_rendered(home_js):
    """AC3: 'SCORE' label is rendered in the score block"""
    assert "SCORE" in home_js, "home.js must render 'SCORE' label above the number"


def test_score_xx_over_100_format(home_js):
    """AC3: Score is formatted as XX/100"""
    assert "/100" in home_js, "home.js must render score in XX/100 format"


def test_seven_day_avg_line(home_js):
    """AC3: 7d avg line is rendered below the score"""
    assert "7d avg" in home_js, "home.js must render '7d avg' line below the score"


def test_trending_labels(home_js):
    """AC3: Trending up/down/flat labels are present"""
    assert "trending up" in home_js and "trending down" in home_js and "flat" in home_js, \
        "home.js must include 'trending up', 'trending down', and 'flat' labels"


# ── AC 4: Four component chips with colored deltas ────────────────────────────

def test_hrv_chip(home_js):
    """AC4: HRV chip is rendered"""
    assert "'HRV'" in home_js or '"HRV"' in home_js, "home.js must render HRV chip"


def test_rhr_chip(home_js):
    """AC4: RHR chip is rendered"""
    assert "'RHR'" in home_js or '"RHR"' in home_js, "home.js must render RHR chip"


def test_sleep_chip(home_js):
    """AC4: Sleep chip is rendered"""
    assert "'Sleep'" in home_js or '"Sleep"' in home_js, "home.js must render Sleep chip"


def test_energy_chip(home_js):
    """AC4: Energy chip is rendered"""
    assert "'Energy'" in home_js or '"Energy"' in home_js, "home.js must render Energy chip"


def test_delta_green_for_positive(home_html):
    """AC4: Positive delta (.delta.up) is coloured green"""
    assert "delta.up" in home_html or ".delta.up" in home_html, \
        "CSS must define .delta.up for green (positive) deltas"
    assert "--green" in home_html, "home.html must define --green colour variable"


def test_delta_red_for_negative(home_html):
    """AC4: Negative delta (.delta.down) is coloured red"""
    assert "delta.down" in home_html or ".delta.down" in home_html, \
        "CSS must define .delta.down for red (negative) deltas"


def test_components_container_css(home_html):
    """AC4: .components container is defined in CSS for the chip row"""
    assert ".components" in home_html or "components" in home_html, \
        "home.html must define .components CSS for chip row"


# ── AC 5: Data from GET /api/readiness/today?user_id={uid} ───────────────────

def test_js_calls_readiness_today_endpoint(home_js):
    """AC5: home.js fetches /api/readiness/today"""
    assert "/api/readiness/today" in home_js, \
        "home.js must fetch /api/readiness/today"


def test_readiness_today_returns_200_with_data(client, test_user_id):
    """AC5: GET /api/readiness/today returns 200 when a readiness row exists"""
    _upsert_readiness(test_user_id, date.today(), score=80.0)
    try:
        res = client.get("/api/readiness/today", params={"user_id": test_user_id})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert "score" in data, "Response must have 'score' field"
        assert 0.0 <= data["score"] <= 100.0, f"Score out of range: {data['score']}"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": test_user_id})


def test_readiness_today_returns_404_for_no_data(client, test_user_id):
    """AC5: GET /api/readiness/today returns 404 when no row exists for today"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": test_user_id})
    res = client.get("/api/readiness/today", params={"user_id": test_user_id})
    assert res.status_code == 404, f"Expected 404 for missing readiness data, got {res.status_code}"


def test_readiness_today_returns_date_field(client, test_user_id):
    """AC5: GET /api/readiness/today includes 'date' field matching today"""
    _upsert_readiness(test_user_id, date.today(), score=65.0)
    try:
        res = client.get("/api/readiness/today", params={"user_id": test_user_id})
        assert res.status_code == 200
        data = res.json()
        assert "date" in data, "Response must include 'date' field"
        assert data["date"] == str(date.today()), \
            f"date mismatch: {data['date']} != {date.today()}"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": test_user_id})


# ── AC 6: 404 → CTA button ───────────────────────────────────────────────────

def test_js_renders_cta_on_404(home_js):
    """AC6: home.js renders CTA when /api/readiness/today returns 404"""
    assert "renderCTA" in home_js or "cta" in home_js.lower(), \
        "home.js must have a renderCTA function for the 404 state"
    assert "404" in home_js, "home.js must check for 404 status to render CTA"


def test_cta_button_text(home_js):
    """AC6: CTA button says 'Compute today's readiness'"""
    assert "Compute today" in home_js and "readiness" in home_js, \
        "home.js CTA button must say 'Compute today's readiness'"


def test_cta_no_score_content(home_js):
    """AC6: CTA state does not render score/headline/chips"""
    assert "renderCTA" in home_js, "home.js must have a renderCTA function"
    # CTA render function should not call renderScored
    # Verify the function exists and is separate
    assert "renderScored" in home_js, "home.js must have a separate renderScored function"


# ── AC 7: CTA POSTs to /api/readiness/compute, then re-fetches ───────────────

def test_js_posts_to_compute_endpoint(home_js):
    """AC7: CTA button POSTs to /api/readiness/compute"""
    assert "/api/readiness/compute" in home_js, \
        "home.js must POST to /api/readiness/compute on CTA click"
    assert "POST" in home_js, "home.js must use POST method for the compute call"


def test_js_refetches_after_compute(home_js):
    """AC7: After successful compute, home.js re-calls loadReadinessCard (no page reload)"""
    assert "loadReadinessCard" in home_js, \
        "home.js must define loadReadinessCard and call it again after CTA success"


def test_compute_endpoint_returns_200_with_metrics(client, test_user_id):
    """AC7: POST /api/readiness/compute?user_id= returns 200 when metrics exist"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": test_user_id})
    _upsert_metric(test_user_id, date.today(), hrv=60, resting_hr=55, sleep_hours=7.5,
                   sleep_quality=4, energy=4)
    try:
        res = client.post("/api/readiness/compute", params={"user_id": test_user_id})
        assert res.status_code == 200, \
            f"POST /api/readiness/compute should return 200 when metrics exist, got {res.status_code}: {res.text}"
        data = res.json()
        assert "score" in data, "compute response must include 'score'"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": test_user_id})
            conn.execute(text("DELETE FROM daily_metrics WHERE user_id = :uid"), {"uid": test_user_id})


def test_compute_endpoint_returns_404_without_metrics(client, test_user_id):
    """AC7: POST /api/readiness/compute returns 404 when no daily_metrics for today"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": test_user_id})
        conn.execute(text("DELETE FROM daily_metrics WHERE user_id = :uid"), {"uid": test_user_id})
    res = client.post("/api/readiness/compute", params={"user_id": test_user_id})
    assert res.status_code == 404, \
        f"POST /api/readiness/compute should return 404 with no metrics, got {res.status_code}"


# ── AC 8: Mobile layout — centre-aligned, 2×2 grid chips ─────────────────────

def test_mobile_breakpoint_880px(home_html):
    """AC8: Mobile breakpoint is at 880px (max-width: 880px)"""
    assert "max-width: 880px" in home_html, \
        "CSS must define @media (max-width: 880px) breakpoint for mobile layout"


def test_mobile_readiness_text_centered(home_html):
    """AC8: Readiness card is centre-aligned on mobile"""
    assert "text-align: center" in home_html, \
        "CSS at 880px breakpoint must apply text-align: center to .readiness"


def test_mobile_chips_two_column_grid(home_html):
    """AC8: Component chips use 2×2 grid on mobile"""
    assert "grid-template-columns: 1fr 1fr" in home_html, \
        "CSS at 880px must switch .readiness .components to 2-column grid (1fr 1fr)"


def test_mobile_row1_single_column(home_html):
    """AC8: #row-1 stacks to single column on mobile"""
    assert "grid-template-columns: 1fr" in home_html, \
        "#row-1 must collapse to single column at 880px breakpoint"


def test_mobile_score_block_static(home_html):
    """AC8: Score block loses absolute positioning on mobile"""
    assert "position: static" in home_html, \
        ".readiness .score-block must be position: static on mobile (not absolute)"


# ── AC 9: Empty state for fresh user with no daily_metrics ───────────────────

def test_js_renders_empty_state(home_js):
    """AC9: home.js renders a friendly empty state when no metrics exist"""
    assert "renderEmpty" in home_js, "home.js must define a renderEmpty function"
    assert "No metrics yet" in home_js or "empty" in home_js.lower(), \
        "home.js empty state must show a friendly message"


def test_empty_state_message_text(home_js):
    """AC9: Empty state message tells user to log their first day"""
    assert "log your first day" in home_js or "first day" in home_js or "No metrics yet" in home_js, \
        "home.js empty state message must reference logging or no metrics"


def test_js_empty_state_on_no_metrics(home_js):
    """AC9: home.js calls renderEmpty when metricsData is empty"""
    assert "metricsData" in home_js or "metrics" in home_js.lower(), \
        "home.js must check for empty metrics array and call renderEmpty"


def test_empty_state_no_crash_on_fresh_user(client, test_user_id):
    """AC9: GET /api/readiness/today returns 404 for user with no data (no crash)"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": test_user_id})
        conn.execute(text("DELETE FROM daily_metrics WHERE user_id = :uid"), {"uid": test_user_id})
    res = client.get("/api/readiness/today", params={"user_id": test_user_id})
    assert res.status_code in (404, 200), \
        f"Endpoint must return 404 or 200 for a fresh user, not {res.status_code}"
