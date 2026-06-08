"""Tests for issue #352: Add GET /api/home/weekly-summary endpoint (runs against UAT)."""
import os
import datetime

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9008")

# Mockie user with workout data seeded in UAT DB
VALID_UID = "c7dc1176-9023-4055-97b2-460a2a6eef5e"
# Week with 2 workouts: 1 run (2026-06-01), 1 lift (2026-06-02)
SEEDED_WEEK = "2026-06-01"
FAKE_UID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC1: returns 200 with correct schema ─────────────────────────────────────

def test_weekly_summary__response_shape(client):
    r = client.get(f"/api/home/weekly-summary?user_id={VALID_UID}&week_start={SEEDED_WEEK}")
    assert r.status_code == 200
    body = r.json()
    for key in ("week_start", "week_end", "workouts", "distance_km",
                "duration_minutes", "total_tss", "elevation_m", "rest_days",
                "vs_prev_week", "daily_load"):
        assert key in body, f"missing key: {key}"
    assert "total" in body["workouts"]
    assert "by_type" in body["workouts"]
    for btype in ("run", "lift", "wod", "bike"):
        assert btype in body["workouts"]["by_type"]
    assert len(body["daily_load"]) == 7
    for entry in body["daily_load"]:
        assert "date" in entry
        assert "tss" in entry
        assert "is_rest" in entry
    for delta_key in ("total_delta", "distance_km_delta", "tss_delta"):
        assert delta_key in body["vs_prev_week"]


# ── AC2: missing/unknown user_id returns 404 ─────────────────────────────────

def test_weekly_summary__missing_user_id_returns_404(client):
    r = client.get("/api/home/weekly-summary")
    assert r.status_code == 404


def test_weekly_summary__unknown_user_id_returns_404(client):
    r = client.get(f"/api/home/weekly-summary?user_id={FAKE_UID}")
    assert r.status_code == 404


# ── AC3 + AC4: default week_start is Monday of current Bangkok week; week_end = +6 days ──

def test_weekly_summary__default_week_start_is_monday_bangkok(client):
    r = client.get(f"/api/home/weekly-summary?user_id={VALID_UID}")
    assert r.status_code == 200
    body = r.json()
    ws = datetime.date.fromisoformat(body["week_start"])
    we = datetime.date.fromisoformat(body["week_end"])
    assert ws.weekday() == 0, f"week_start {ws} is not a Monday"
    assert we == ws + datetime.timedelta(days=6)
    assert len(body["daily_load"]) == 7


# ── AC5 + AC6: workouts.total and by_type counts ─────────────────────────────

def test_weekly_summary__workout_total_and_by_type(client):
    # Seeded week: 2 workouts — 1 run on June 1, 1 lift on June 2
    r = client.get(f"/api/home/weekly-summary?user_id={VALID_UID}&week_start={SEEDED_WEEK}")
    assert r.status_code == 200
    body = r.json()
    assert body["workouts"]["total"] == 2
    assert body["workouts"]["by_type"]["run"] == 1
    assert body["workouts"]["by_type"]["lift"] == 1
    assert body["workouts"]["by_type"]["wod"] == 0
    assert body["workouts"]["by_type"]["bike"] == 0


# ── AC7: distance_km, duration_minutes, total_tss, elevation_m sums ──────────

def test_weekly_summary__aggregate_sums(client):
    r = client.get(f"/api/home/weekly-summary?user_id={VALID_UID}&week_start={SEEDED_WEEK}")
    assert r.status_code == 200
    body = r.json()
    assert body["distance_km"] == pytest.approx(10.2, abs=0.01)
    assert body["total_tss"] == pytest.approx(109.2, abs=0.1)
    assert body["elevation_m"] == 121
    assert body["duration_minutes"] is not None and body["duration_minutes"] > 0


# ── AC8: rest_days = days in window with no workout ───────────────────────────

def test_weekly_summary__rest_days(client):
    # 2 workouts in 7-day window → 5 rest days
    r = client.get(f"/api/home/weekly-summary?user_id={VALID_UID}&week_start={SEEDED_WEEK}")
    assert r.status_code == 200
    assert r.json()["rest_days"] == 5


# ── AC9: vs_prev_week deltas ──────────────────────────────────────────────────

def test_weekly_summary__vs_prev_week_deltas(client):
    r = client.get(f"/api/home/weekly-summary?user_id={VALID_UID}&week_start={SEEDED_WEEK}")
    assert r.status_code == 200
    vp = r.json()["vs_prev_week"]
    # All delta keys are numeric (int or float)
    assert isinstance(vp["total_delta"], int)
    assert isinstance(vp["distance_km_delta"], (int, float))
    assert isinstance(vp["tss_delta"], (int, float))
    # Current week TSS = 109.2; if prev week had more TSS, tss_delta should be negative
    assert vp["tss_delta"] == pytest.approx(-178.7, abs=0.5)


# ── AC10: daily_load has exactly 7 entries, one per day ──────────────────────

def test_weekly_summary__daily_load_7_entries(client):
    r = client.get(f"/api/home/weekly-summary?user_id={VALID_UID}&week_start={SEEDED_WEEK}")
    assert r.status_code == 200
    daily = r.json()["daily_load"]
    assert len(daily) == 7
    dates = [e["date"] for e in daily]
    expected = [(datetime.date(2026, 6, 1) + datetime.timedelta(days=i)).isoformat() for i in range(7)]
    assert dates == expected
    # Days with workouts are not rest
    assert daily[0]["is_rest"] is False  # June 1 — run
    assert daily[1]["is_rest"] is False  # June 2 — lift
    assert daily[2]["is_rest"] is True   # June 3 — no workout


# ── AC11: graceful null for absent columns ────────────────────────────────────

def test_weekly_summary__absent_columns_no_500(client):
    pytest.skip("manual — requires staging DB without distance_km/duration_seconds/tss columns")


# ── UAT step 3: week_end is always week_start + 6 regardless of anchor day ───

def test_weekly_summary__week_end_is_start_plus_6(client):
    # AC: week_end = week_start + 6 days even for non-Monday anchors
    r = client.get(f"/api/home/weekly-summary?user_id={VALID_UID}&week_start=2026-06-03")
    assert r.status_code == 200
    body = r.json()
    assert body["week_start"] == "2026-06-03"
    assert body["week_end"] == "2026-06-09"
