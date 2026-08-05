"""Tests for issue #351: Add GET /api/home/readiness daily readiness endpoint (runs against UAT).

Server under test: http://127.0.0.1:9007 (feature/351 branch, fresh server)
Risk: MEDIUM — new read-only endpoint, score formula + label logic, no auth/deletion changes.
"""
import datetime
import os

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9007")

# Mockie (c7dc1176): has daily_metrics rows on multiple dates
VALID_UID = "c7dc1176-9023-4055-97b2-460a2a6eef5e"
# Date with complete daily_metrics row → score=52, label="OK"
DATA_DATE = "2026-06-01"
# Date with no daily_metrics row → score=null
NO_DATA_DATE = "2026-06-09"
# UUID that does not exist in the DB
FAKE_UID = "00000000-0000-0000-0000-000000000000"
TODAY = datetime.date.today().isoformat()


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC 1 + 4: endpoint reachable and response has expected shape ──────────────

def test_home_readiness__endpoint_reachable_and_shape(client):
    # AC: GET /api/home/readiness reachable; response has date, score, score_label,
    # contributors (5 items), rolling_baseline
    r = client.get(f"/api/home/readiness?user_id={VALID_UID}&date={DATA_DATE}")
    assert r.status_code == 200
    body = r.json()
    for key in ("date", "score", "score_label", "contributors", "rolling_baseline"):
        assert key in body, f"missing key: {key}"
    assert len(body["contributors"]) == 5
    assert body["date"] == DATA_DATE


# ── AC 5: contributor objects have required fields ────────────────────────────

def test_home_readiness__contributor_fields(client):
    # AC: each contributor has factor, value, weight, and impact
    r = client.get(f"/api/home/readiness?user_id={VALID_UID}&date={DATA_DATE}")
    assert r.status_code == 200
    for c in r.json()["contributors"]:
        for field in ("factor", "value", "weight", "impact"):
            assert field in c, f"contributor missing field: {field}"


# ── AC 2: missing user_id returns 404 ─────────────────────────────────────────

def test_home_readiness__missing_user_id_returns_404(client):
    # AC: no user_id param → 404
    r = client.get("/api/home/readiness")
    assert r.status_code == 404


def test_home_readiness__nonexistent_user_returns_404(client):
    # AC: user_id that maps to no DB row → 404
    r = client.get(f"/api/home/readiness?user_id={FAKE_UID}")
    assert r.status_code == 404


# ── AC 3: date defaults to today ──────────────────────────────────────────────

def test_home_readiness__date_defaults_to_today(client):
    # AC: omitting date param → response.date equals today's server date
    r = client.get(f"/api/home/readiness?user_id={VALID_UID}")
    assert r.status_code == 200
    assert r.json()["date"] == TODAY


# ── AC 8 + 9: score is int 0-100 and score_label matches threshold ────────────

def test_home_readiness__score_in_range_and_label_match(client):
    # AC: score is int 0-100 (DATA_DATE has score=52 → label="OK")
    r = client.get(f"/api/home/readiness?user_id={VALID_UID}&date={DATA_DATE}")
    assert r.status_code == 200
    body = r.json()
    score = body["score"]
    assert isinstance(score, int)
    assert 0 <= score <= 100
    # score=52 → "OK" (40-59 range)
    assert body["score_label"] == "OK"


# ── AC 10: no daily_metrics → score null, contributor values null ─────────────

def test_home_readiness__no_data_score_null(client):
    # AC: no daily_metrics row for queried date → score is null, score_label "No data"
    r = client.get(f"/api/home/readiness?user_id={VALID_UID}&date={NO_DATA_DATE}")
    assert r.status_code == 200
    body = r.json()
    assert body["score"] is None
    assert body["score_label"] == "No data"


def test_home_readiness__no_data_contributor_values_null(client):
    # AC: when score is null all contributor value fields must be null
    r = client.get(f"/api/home/readiness?user_id={VALID_UID}&date={NO_DATA_DATE}")
    assert r.status_code == 200
    for c in r.json()["contributors"]:
        assert c["value"] is None, f"contributor {c['factor']} value should be null"


# ── AC 12: rolling_baseline fields present ────────────────────────────────────

def test_home_readiness__rolling_baseline_fields(client):
    # AC: rolling_baseline contains hrv_7d_avg, rhr_7d_avg, sleep_7d_avg_hours
    r = client.get(f"/api/home/readiness?user_id={VALID_UID}&date={DATA_DATE}")
    assert r.status_code == 200
    rb = r.json()["rolling_baseline"]
    for key in ("hrv_7d_avg", "rhr_7d_avg", "sleep_7d_avg_hours"):
        assert key in rb, f"rolling_baseline missing: {key}"


# ── AC 7: contributors contain exactly the 5 expected factors ─────────────────

def test_home_readiness__contributors_5_factors(client):
    # AC: contributors array has exactly sleep_hours, hrv, rhr, mood, energy
    r = client.get(f"/api/home/readiness?user_id={VALID_UID}&date={DATA_DATE}")
    factors = {c["factor"] for c in r.json()["contributors"]}
    assert factors == {"sleep_hours", "hrv", "rhr", "mood", "energy"}
