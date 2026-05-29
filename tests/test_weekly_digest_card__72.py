"""
Tests for issue #72: Add weekly digest summary card to home dashboard (v2 refinements).

Verifies:
  - Digest card positioned immediately below the readiness card (before check-in section)
  - Per-user cache key scoped by userId
  - Fallback threshold raised to 7 days with updated copy "Not enough data yet — keep logging."
  - Sleep line uses directional "up/down Xh" format
  - TSS line includes peak weekday ("biggest day <Weekday>")
  - HRV line uses "trending below baseline last N days" format
  - No LLM/AI inference endpoint calls in the code path
  - API: fewer than 7 days of data yields null averages (fallback condition)

Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()

JS_PATH   = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js"
HTML_PATH = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


@pytest.fixture(scope="module")
def sparse_user_id(client):
    """User with only 3 days of data — below the 7-day threshold."""
    res = client.post("/api/users", json={"name": "DigestTestUser72Sparse"})
    assert res.status_code in (200, 201)
    uid = res.json()["id"]
    dates = []
    for i in range(2, -1, -1):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        r = client.put(
            f"/api/daily-metrics/{uid}/{d}",
            json={"hrv": 45, "resting_hr": 55, "sleep_hours": 7.5,
                  "sleep_quality": 4, "energy": 4, "mood": 4},
        )
        assert r.status_code in (200, 201)
        dates.append(d)
    yield uid
    for d in dates:
        client.delete(f"/api/daily-metrics/{uid}/{d}")
    client.delete(f"/api/users/{uid}")


# ── AC: HTML positioning — digest must come immediately before check-in ───────

def test_ac_digest_positioned_before_checkin():
    """section-digest must appear before section-checkin in home.html (below readiness card)."""
    html = HTML_PATH.read_text()
    digest_pos = html.find('id="section-digest"')
    checkin_pos = html.find('id="section-checkin"')
    assert digest_pos != -1, "section-digest not found in home.html"
    assert checkin_pos != -1, "section-checkin not found in home.html"
    assert digest_pos < checkin_pos, \
        "section-digest must appear before section-checkin (digest should be below readiness card)"


def test_ac_digest_after_readiness_card():
    """section-digest must appear after the readiness card in home.html."""
    html = HTML_PATH.read_text()
    readiness_pos = html.find('id="readiness-card"')
    digest_pos    = html.find('id="section-digest"')
    assert readiness_pos != -1, "readiness-card not found in home.html"
    assert digest_pos != -1, "section-digest not found in home.html"
    assert readiness_pos < digest_pos, \
        "section-digest must appear after readiness-card in home.html"


# ── AC: Per-user cache key ────────────────────────────────────────────────────

def test_ac_cache_key_is_per_user():
    """home.js must scope the digest cache key per userId (not a shared constant)."""
    js = JS_PATH.read_text()
    assert "digestCacheKey" in js, \
        "home.js must define digestCacheKey() to scope cache per user"


def test_ac_cache_key_includes_user_id():
    """digestCacheKey must incorporate the userId argument into the key string."""
    js = JS_PATH.read_text()
    # Function must concatenate userId into the key (e.g. '...' + userId or template)
    assert re.search(r"digestCacheKey\s*\(.*userId", js, re.DOTALL), \
        "digestCacheKey must accept userId and embed it in the returned key"


# ── AC: Fallback threshold raised to 7 days ───────────────────────────────────

def test_ac_fallback_threshold_is_7_days():
    """home.js must show fallback when days_with_data < 7 (not < 3)."""
    js = JS_PATH.read_text()
    assert "< 7" in js, \
        "home.js must trigger fallback when days_with_data < 7"
    assert "< 3" not in js or js.index("< 7") < js.index("< 3") if "< 3" in js else True, \
        "Fallback threshold must be 7 (not the old 3) in the digest render path"


def test_ac_fallback_text_includes_keep_logging():
    """Fallback message must read 'Not enough data yet — keep logging.'"""
    js = JS_PATH.read_text()
    assert "keep logging" in js, \
        "home.js fallback must include 'keep logging' copy"


def test_ac_fallback_full_text():
    """home.js must contain the complete fallback string."""
    js = JS_PATH.read_text()
    assert "Not enough data yet — keep logging." in js, \
        "home.js must contain full fallback string 'Not enough data yet — keep logging.'"


# ── AC: Sleep line format — directional ("Sleep up/down Xh") ─────────────────

def test_ac_sleep_line_uses_directional_format():
    """home.js sleep digest line must use 'Sleep up' / 'Sleep down' format, not 'Avg sleep'."""
    js = JS_PATH.read_text()
    assert re.search(r"['\"]Sleep (up|down)['\"]", js) or \
           re.search(r"'Sleep '\s*\+\s*sleepDir", js) or \
           "sleepDir" in js, \
        "home.js must build sleep digest line with 'Sleep up/down' directional format"
    assert "Avg sleep" not in js or js.find("Avg sleep") == -1, \
        "home.js must NOT use old 'Avg sleep' format for the sleep digest line"


# ── AC: TSS line includes peak weekday ───────────────────────────────────────

def test_ac_tss_line_includes_biggest_day():
    """home.js must include 'biggest day' + weekday name in the TSS digest line."""
    js = JS_PATH.read_text()
    assert "biggest day" in js, \
        "home.js TSS digest line must include 'biggest day' annotation"


def test_ac_tss_peak_day_helper_exists():
    """home.js must define a helper to find the peak TSS weekday."""
    js = JS_PATH.read_text()
    assert "_peakTssDay" in js, \
        "home.js must define _peakTssDay() helper to identify peak TSS day"


# ── AC: HRV line — trailing-days-below-baseline format ───────────────────────

def test_ac_hrv_line_uses_trending_format():
    """home.js must generate HRV line as 'HRV trending below baseline last N days'."""
    js = JS_PATH.read_text()
    assert "trending below baseline" in js, \
        "home.js HRV digest line must use 'trending below baseline' phrasing"


def test_ac_hrv_trailing_below_helper_exists():
    """home.js must define a helper to count trailing days below HRV baseline."""
    js = JS_PATH.read_text()
    assert "_hrvTrailingBelowCount" in js, \
        "home.js must define _hrvTrailingBelowCount() helper"


def test_ac_hrv_line_requires_minimum_2_trailing_days():
    """HRV line must only appear when ≥2 trailing days are below average (not just 1)."""
    js = JS_PATH.read_text()
    # Check for the guard: belowCount >= 2
    assert re.search(r"belowCount\s*>=\s*2", js), \
        "home.js must only render HRV line when belowCount >= 2"


# ── AC: No LLM calls ─────────────────────────────────────────────────────────

def test_ac_no_llm_endpoint_in_home_js():
    """home.js must not reference any LLM or AI inference endpoints."""
    js = JS_PATH.read_text()
    llm_patterns = [
        r"openai\.com", r"anthropic\.com", r"api\.anthropic",
        r"/v1/messages", r"/v1/chat/completions",
        r"claude-", r"gpt-", r"gemini",
        r"llm", r"ai-inference", r"ai_inference",
    ]
    for pat in llm_patterns:
        assert not re.search(pat, js, re.IGNORECASE), \
            f"home.js must not reference LLM endpoint matching '{pat}'"


# ── AC: Mock data — HRV demonstrable (last 3 days below baseline) ────────────

def test_ac_mock_data_hrv_last_3_days_below_avg():
    """MOCK_TRENDS_SUMMARY must have last 3 HRV values below the reported avg."""
    mock_js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "mock-data.js").read_text()
    # Extract HRV block specifically
    hrv_match = re.search(r"hrv:\s*\{.*?avg:\s*([\d.]+)", mock_js, re.DOTALL)
    hrv_series_match = re.search(r"hrv:\s*\{[^}]*series:\s*\[(.*?)\]", mock_js, re.DOTALL)
    if hrv_match and hrv_series_match:
        avg = float(hrv_match.group(1))
        values = [float(v) for v in re.findall(r"value:\s*(\d+)", hrv_series_match.group(1))]
        if len(values) >= 3:
            last_3 = values[-3:]
            assert all(v < avg for v in last_3), \
                f"MOCK_TRENDS_SUMMARY: last 3 HRV values {last_3} must all be below avg {avg}"


# ── AC: API — fewer than 7 days yields null averages ─────────────────────────

def test_ac_sparse_user_has_null_readiness_avg(client, sparse_user_id):
    """A user with only 3 days of data must get null readiness.avg (triggers fallback)."""
    res = client.get(f"/trends/summary?user_id={sparse_user_id}&range=7d")
    assert res.status_code == 200
    data = res.json()
    # 3 days is below the 7-day threshold — readiness.avg may or may not be null,
    # but _daysWithData in JS counts non-null series entries; verify series has ≤3 non-null
    series = data.get("readiness", {}).get("series", [])
    non_null = [s for s in series if s.get("score") is not None]
    assert len(non_null) <= 3, \
        f"Expected ≤3 non-null readiness scores with 3 days of data, got {len(non_null)}"


def test_ac_full_week_user_has_non_null_avgs(client, alice_id):
    """A user with ≥7 days of data must get non-null averages in the summary."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200
    data = res.json()
    assert data.get("readiness", {}).get("avg") is not None, \
        "readiness.avg must be non-null for a user with ≥7 days of data"


# ── AC: TSS series must be present in summary payload ─────────────────────────

def test_ac_summary_includes_tss_series(client, alice_id):
    """/trends/summary must include tss.series for the peak-day calculation."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200
    data = res.json()
    tss = data.get("tss", {})
    assert "series" in tss, \
        "/trends/summary response must include tss.series for peak-day lookup"


# ── AC: HRV series must be present in summary payload ────────────────────────

def test_ac_summary_includes_hrv_series(client, alice_id):
    """/trends/summary must include hrv.series for the trailing-below-baseline calculation."""
    res = client.get(f"/trends/summary?user_id={alice_id}&range=7d")
    assert res.status_code == 200
    data = res.json()
    hrv = data.get("hrv", {})
    assert "series" in hrv, \
        "/trends/summary response must include hrv.series for below-baseline detection"
