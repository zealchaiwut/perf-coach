"""Tests for issue #705: PR storage, on-ingest comparison, and records feed.

Structure:
  Part 1 — pure unit tests for backend/services/strength_pr.py (no server, no DB)
  Part 2 — integration tests against the live UAT server at http://127.0.0.1:9001
"""

import pytest
pytest.importorskip("backend.services.strength_pr")

import json
import os
import sys
import uuid
import httpx
from sqlalchemy.orm import Session as _OrmSess

# Resolve to UAT repo for imports
_uat_path = os.path.join(os.path.dirname(__file__), "../../uat")
if _uat_path not in sys.path:
    sys.path.insert(0, _uat_path)

# ── Pure-function tests are always runnable ────────────────────────────────────
from backend.services.strength_pr import (  # noqa: E402
    normalize_exercise_key,
    get_rep_band,
    beats_record,
    compare_sets_to_records,
)
from tests._admin_helpers import admin_cookies as _admin_cookies

# ── Integration tests need a live server ──────────────────────────────────────
BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "pr705-test-password"

# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — Pure function unit tests (AC3, AC4)
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeExerciseKey:
    """AC3: comparison logic uses no hardcoded thresholds — normalisation is pure."""

    def test_lowercases_name(self):
        assert normalize_exercise_key("Bench Press") == "bench press"

    def test_strips_leading_trailing_whitespace(self):
        assert normalize_exercise_key("  squat  ") == "squat"

    def test_collapses_internal_whitespace(self):
        assert normalize_exercise_key("bench  press") == "bench press"

    def test_already_normalised_is_idempotent(self):
        key = normalize_exercise_key("deadlift")
        assert normalize_exercise_key(key) == key


class TestGetRepBand:
    """AC3: rep-band boundary is a parameter, not a hardcoded literal."""

    def test_reps_1_with_width_5_gives_band_1_5(self):
        b = get_rep_band(1, band_width=5)
        assert b["label"] == "1-5"
        assert b["min"] == 1
        assert b["max"] == 5

    def test_reps_5_with_width_5_is_same_band_as_1(self):
        assert get_rep_band(5, 5)["label"] == get_rep_band(1, 5)["label"]

    def test_reps_6_with_width_5_gives_band_6_10(self):
        b = get_rep_band(6, band_width=5)
        assert b["label"] == "6-10"
        assert b["min"] == 6
        assert b["max"] == 10

    def test_reps_10_with_width_5_is_same_band_as_6(self):
        assert get_rep_band(10, 5)["label"] == get_rep_band(6, 5)["label"]

    def test_reps_11_with_width_5_gives_band_11_15(self):
        assert get_rep_band(11, 5)["label"] == "11-15"

    def test_custom_band_width_1(self):
        # width=1 → each rep count is its own band
        b = get_rep_band(3, band_width=1)
        assert b["min"] == 3
        assert b["max"] == 3
        assert b["label"] == "3-3"

    def test_custom_band_width_10(self):
        b = get_rep_band(7, band_width=10)
        assert b["label"] == "1-10"

    def test_invalid_reps_raises(self):
        with pytest.raises(ValueError):
            get_rep_band(0)

    def test_invalid_band_width_raises(self):
        with pytest.raises(ValueError):
            get_rep_band(5, band_width=0)


class TestBeatsRecord:
    """AC3: comparison is plain arithmetic."""

    def test_no_prior_record_always_beats(self):
        assert beats_record(80.0, None) is True

    def test_strictly_higher_beats_record(self):
        assert beats_record(100.0, 90.0) is True

    def test_equal_does_not_beat(self):
        assert beats_record(90.0, 90.0) is False

    def test_lower_does_not_beat(self):
        assert beats_record(80.0, 90.0) is False


class TestCompareSetsToRecords:
    """AC2 + AC3 + AC4: pure comparison receives plain values, returns plain values."""

    def _stored(self, weight_kg, achieved_on="2026-01-01"):
        return {"weight_kg": weight_kg, "achieved_on": achieved_on}

    def test_set_beats_stored_record_is_flagged(self):
        results = compare_sets_to_records(
            "Bench Press",
            [{"reps": 5, "weight_kg": 100.0}],
            {"1-5": self._stored(90.0)},
        )
        assert results[0]["is_pr"] is True

    def test_previous_record_carries_old_weight(self):
        results = compare_sets_to_records(
            "Bench Press",
            [{"reps": 5, "weight_kg": 100.0}],
            {"1-5": self._stored(90.0, "2026-01-01")},
        )
        assert results[0]["previous_record"] == 90.0
        assert results[0]["previous_achieved_on"] == "2026-01-01"

    def test_set_equal_to_record_not_flagged(self):
        results = compare_sets_to_records(
            "Squat",
            [{"reps": 5, "weight_kg": 90.0}],
            {"1-5": self._stored(90.0)},
        )
        assert results[0]["is_pr"] is False

    def test_set_below_record_not_flagged(self):
        results = compare_sets_to_records(
            "Deadlift",
            [{"reps": 3, "weight_kg": 80.0}],
            {"1-5": self._stored(100.0)},
        )
        assert results[0]["is_pr"] is False

    def test_first_ever_set_is_pr_with_null_previous(self):
        """AC9: first-ever effort creates initial record; no previous value stored."""
        results = compare_sets_to_records(
            "Overhead Press",
            [{"reps": 5, "weight_kg": 60.0}],
            {},  # no stored records
        )
        assert results[0]["is_pr"] is True
        assert results[0]["previous_record"] is None

    def test_set_missing_reps_skipped(self):
        results = compare_sets_to_records(
            "Curl",
            [{"weight_kg": 20.0}],  # no reps
            {},
        )
        assert results[0]["is_pr"] is False

    def test_set_missing_weight_skipped(self):
        results = compare_sets_to_records(
            "Pull-up",
            [{"reps": 8}],  # no weight_kg
            {},
        )
        assert results[0]["is_pr"] is False

    def test_multiple_sets_different_bands(self):
        results = compare_sets_to_records(
            "Row",
            [
                {"reps": 3, "weight_kg": 80.0},   # band 1-5
                {"reps": 8, "weight_kg": 60.0},   # band 6-10
            ],
            {
                "1-5": self._stored(70.0),   # 80 > 70 → PR
                "6-10": self._stored(65.0),  # 60 < 65 → no PR
            },
        )
        assert results[0]["is_pr"] is True
        assert results[1]["is_pr"] is False

    def test_rep_band_info_present_on_scored_set(self):
        results = compare_sets_to_records(
            "Lunge",
            [{"reps": 10, "weight_kg": 40.0}],
            {},
        )
        band = results[0]["rep_band"]
        assert band is not None
        assert "label" in band
        assert "min" in band
        assert "max" in band

    def test_set_index_matches_position(self):
        results = compare_sets_to_records(
            "Bench",
            [
                {"reps": 5, "weight_kg": 80.0},
                {"reps": 5, "weight_kg": 90.0},
            ],
            {},
        )
        assert results[0]["set_index"] == 0
        assert results[1]["set_index"] == 1

    def test_within_session_second_heavier_set_also_flagged(self):
        """Two sets in same workout, second heavier than first and both above stored."""
        results = compare_sets_to_records(
            "Squat",
            [
                {"reps": 5, "weight_kg": 100.0},
                {"reps": 5, "weight_kg": 110.0},  # also a PR within the session
            ],
            {"1-5": self._stored(90.0)},
        )
        assert results[0]["is_pr"] is True
        assert results[1]["is_pr"] is True

    def test_within_session_second_lighter_set_not_flagged(self):
        results = compare_sets_to_records(
            "Squat",
            [
                {"reps": 5, "weight_kg": 100.0},
                {"reps": 5, "weight_kg": 95.0},  # lighter than first, not a PR
            ],
            {"1-5": self._stored(90.0)},
        )
        assert results[0]["is_pr"] is True
        assert results[1]["is_pr"] is False

    def test_exercise_name_normalised_before_comparison(self):
        """AC3: normalisation is part of the pure logic, not caller responsibility."""
        results_upper = compare_sets_to_records(
            "BENCH PRESS",
            [{"reps": 5, "weight_kg": 100.0}],
            {},
        )
        results_lower = compare_sets_to_records(
            "bench press",
            [{"reps": 5, "weight_kg": 100.0}],
            {},
        )
        assert results_upper[0]["is_pr"] == results_lower[0]["is_pr"]

    def test_configurable_band_width_parameter(self):
        """AC3: band boundary comes from parameter, not hardcoded constant."""
        # With width=3: reps=3 is in band 1-3; reps=4 is in band 4-6
        results = compare_sets_to_records(
            "Squat",
            [{"reps": 3, "weight_kg": 80.0}, {"reps": 4, "weight_kg": 70.0}],
            {},
            band_width=3,
        )
        assert results[0]["rep_band"]["label"] == "1-3"
        assert results[1]["rep_band"]["label"] == "4-6"


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — Integration tests (AC1, AC2, AC5, AC6, AC7, AC8, AC9, AC10)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as c:
        yield c


def _extract_set_cookie(resp: httpx.Response, name: str) -> str | None:
    """Extract a cookie value from Set-Cookie headers (works even if Secure flag present)."""
    for header in resp.headers.get_list("set-cookie"):
        parts = [p.strip() for p in header.split(";")]
        if parts and "=" in parts[0]:
            k, v = parts[0].split("=", 1)
            if k.strip() == name:
                return v.strip()
    return None


@pytest.fixture(scope="module")
def authed_client(client):
    """Return an httpx Client with a live session cookie and CSRF handling."""
    from backend.auth import hash_password as _hp
    from backend.db import engine as _engine
    from backend.models import User as _User

    username = f"tester705_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": username}, cookies=_admin_cookies())
    assert r.status_code == 201, f"Could not create test user: {r.text}"
    uid = r.json()["id"]

    pw_hash = _hp(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_User, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()

    _csrf_holder: list[str | None] = [None]

    def _inject_csrf(request: httpx.Request) -> None:
        if request.method not in ("GET", "HEAD", "OPTIONS") and _csrf_holder[0]:
            request.headers["X-CSRF-Token"] = _csrf_holder[0]

    with httpx.Client(
        base_url=BASE_URL,
        timeout=15.0,
        event_hooks={"request": [_inject_csrf]},
    ) as ac:
        login = ac.post("/api/auth/login", json={"username": username, "password": _TEST_PW})
        assert login.status_code == 200, f"Login failed: {login.text}"

        csrf_val = _extract_set_cookie(login, "csrf-token")
        if csrf_val:
            ac.cookies.set("csrf-token", csrf_val, domain="127.0.0.1")
            _csrf_holder[0] = csrf_val

        yield ac

    # teardown
    with _OrmSess(_engine) as db:
        u = db.get(_User, uuid.UUID(uid))
        if u:
            db.delete(u)
            db.commit()


# ── AC10: unauthenticated requests return 401 ─────────────────────────────────

def test_unauthenticated_get_records_returns_401(client):
    """AC10: GET /api/records without auth returns 401."""
    r = client.get("/api/records")
    assert r.status_code == 401


def test_unauthenticated_get_achievements_returns_401(client):
    """AC10: GET /api/records/achievements/recent without auth returns 401."""
    r = client.get("/api/records/achievements/recent")
    assert r.status_code == 401


# ── AC5: GET /api/records ─────────────────────────────────────────────────────

def test_get_records_empty_before_any_workouts(authed_client):
    """AC5: authenticated user with no strength workouts sees empty records list."""
    r = authed_client.get("/api/records")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_get_records_filterable_by_exercise(authed_client):
    """AC5: GET /api/records?exercise=<key> filters by exercise."""
    r = authed_client.get("/api/records", params={"exercise": "bench press"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


# ── AC6: GET /api/records/achievements/recent ─────────────────────────────────

def test_get_achievements_empty_before_any_workouts(authed_client):
    """AC6: authenticated user with no PRs sees empty achievements list."""
    r = authed_client.get("/api/records/achievements/recent")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


# ── AC2 + AC9: ingest creates record + achievement ────────────────────────────

@pytest.fixture(scope="module")
def workout_with_pr(authed_client):
    """Create a workout containing a strength exercise.  Returns the workout id."""
    payload = {
        "name": "PR Test Workout",
        "workout_date": "2026-01-15",
        "workout_type": "strength",
        "exercises": [
            {
                "name": "Bench Press",
                "sets": 1,
                "reps": 5,
                "weight_kg": 100.0,
                "sets_json": json.dumps([{"reps": 5, "weight_kg": 100.0, "rpe": 8}]),
            }
        ],
    }
    r = authed_client.post("/api/workouts", json=payload)
    assert r.status_code == 201, f"Failed to create workout: {r.text}"
    return r.json()["id"]


def test_ingest_creates_record_row(authed_client, workout_with_pr):
    """AC2 + AC9: POST /api/workouts with a strength exercise creates a PR record."""
    r = authed_client.get("/api/records", params={"exercise": "bench press"})
    assert r.status_code == 200
    records = r.json()
    matching = [rec for rec in records if rec["exercise_key"] == "bench press"]
    assert len(matching) == 1, f"Expected 1 bench press record, got: {matching}"


def test_ingest_first_record_has_null_previous(authed_client, workout_with_pr):
    """AC9: first-ever ingest — no previous_weight_kg in the record."""
    r = authed_client.get("/api/records", params={"exercise": "bench press"})
    records = r.json()
    matching = [rec for rec in records if rec["exercise_key"] == "bench press"]
    assert matching[0]["previous_weight_kg"] is None


def test_ingest_creates_achievement_entry(authed_client, workout_with_pr):
    """AC2: on ingest, an achievement row is created for the PR-setting set."""
    r = authed_client.get("/api/records/achievements/recent")
    assert r.status_code == 200
    achievements = r.json()
    bench_hits = [a for a in achievements if a["exercise_key"] == "bench press"]
    assert len(bench_hits) >= 1


def test_achievement_has_required_fields(authed_client, workout_with_pr):
    """AC6: achievement entry includes new_value, previous_value, and date."""
    r = authed_client.get("/api/records/achievements/recent")
    achievements = r.json()
    bench = next((a for a in achievements if a["exercise_key"] == "bench press"), None)
    assert bench is not None
    assert "new_weight_kg" in bench
    assert "previous_weight_kg" in bench  # may be null for first ever
    assert "achieved_on" in bench


def test_achievements_in_reverse_chronological_order(authed_client, workout_with_pr):
    """AC6: achievements feed is reverse-chronological."""
    r = authed_client.get("/api/records/achievements/recent")
    items = r.json()
    if len(items) >= 2:
        dates = [i["achieved_on"] for i in items]
        assert dates == sorted(dates, reverse=True), "Feed should be reverse-chronological"


# ── AC2: second ingest with lower weight leaves record unchanged ───────────────

@pytest.fixture(scope="module")
def second_workout_lower_weight(authed_client, workout_with_pr):
    """Create a second workout with a lower weight for the same exercise."""
    payload = {
        "name": "Lower Weight Workout",
        "workout_date": "2026-01-16",
        "workout_type": "strength",
        "exercises": [
            {
                "name": "Bench Press",
                "sets": 1,
                "reps": 5,
                "weight_kg": 80.0,
                "sets_json": json.dumps([{"reps": 5, "weight_kg": 80.0, "rpe": 7}]),
            }
        ],
    }
    r = authed_client.post("/api/workouts", json=payload)
    assert r.status_code == 201, f"Failed to create second workout: {r.text}"
    return r.json()["id"]


def test_lower_weight_does_not_update_record(authed_client, second_workout_lower_weight):
    """AC2: a set that doesn't beat the record leaves current record unchanged."""
    r = authed_client.get("/api/records", params={"exercise": "bench press"})
    records = r.json()
    bench = next((rec for rec in records if rec["exercise_key"] == "bench press"), None)
    assert bench is not None
    assert float(bench["weight_kg"]) == 100.0, (
        f"Record should still be 100.0 kg, got {bench['weight_kg']}"
    )


def test_lower_weight_no_new_achievement(authed_client, workout_with_pr, second_workout_lower_weight):
    """AC2: no new achievement created when the set doesn't beat the record."""
    r = authed_client.get("/api/records/achievements/recent")
    achievements = r.json()
    bench_hits = [a for a in achievements if a["exercise_key"] == "bench press"]
    # There should be exactly 1 achievement (from the first workout), not 2
    assert len(bench_hits) == 1, (
        f"Expected 1 bench press achievement, got {len(bench_hits)}"
    )


# ── AC2: third ingest with higher weight updates the record ───────────────────

@pytest.fixture(scope="module")
def third_workout_higher_weight(authed_client, second_workout_lower_weight):
    """Create a third workout beating the record."""
    payload = {
        "name": "New PR Workout",
        "workout_date": "2026-01-17",
        "workout_type": "strength",
        "exercises": [
            {
                "name": "Bench Press",
                "sets": 1,
                "reps": 5,
                "weight_kg": 110.0,
                "sets_json": json.dumps([{"reps": 5, "weight_kg": 110.0, "rpe": 9}]),
            }
        ],
    }
    r = authed_client.post("/api/workouts", json=payload)
    assert r.status_code == 201, f"Failed to create third workout: {r.text}"
    return r.json()["id"]


def test_higher_weight_updates_record(authed_client, third_workout_higher_weight):
    """AC2: beating the record updates the record row with new weight."""
    r = authed_client.get("/api/records", params={"exercise": "bench press"})
    records = r.json()
    bench = next((rec for rec in records if rec["exercise_key"] == "bench press"), None)
    assert bench is not None
    assert float(bench["weight_kg"]) == 110.0


def test_higher_weight_preserves_previous_value(authed_client, third_workout_higher_weight):
    """AC1: when record is beaten, old value is stored in previous_weight_kg."""
    r = authed_client.get("/api/records", params={"exercise": "bench press"})
    records = r.json()
    bench = next((rec for rec in records if rec["exercise_key"] == "bench press"), None)
    assert bench is not None
    assert float(bench["previous_weight_kg"]) == 100.0


def test_new_achievement_created_for_new_pr(authed_client, third_workout_higher_weight):
    """AC2: a new achievement is created when the record is beaten."""
    r = authed_client.get("/api/records/achievements/recent")
    achievements = r.json()
    bench_hits = [a for a in achievements if a["exercise_key"] == "bench press"]
    assert len(bench_hits) == 2, (
        f"Expected 2 bench press achievements total, got {len(bench_hits)}"
    )


# ── AC7 + AC8: GET /api/workouts/{id}/full includes is_pr on sets ─────────────

def test_workout_full_pr_set_is_marked(authed_client, workout_with_pr):
    """AC7: GET /api/workouts/{id}/full marks PR-setting sets with is_pr=True."""
    r = authed_client.get(f"/api/workouts/{workout_with_pr}/full")
    assert r.status_code == 200
    body = r.json()
    exercises = body.get("workout", {}).get("exercises", [])
    assert len(exercises) > 0

    bench = next((e for e in exercises if "bench" in e["name"].lower()), None)
    assert bench is not None

    sets_data = bench.get("sets_data")
    assert sets_data is not None, "exercises should have sets_data in full response"
    assert len(sets_data) > 0

    pr_set = sets_data[0]
    assert pr_set.get("is_pr") is True, f"First set should be marked is_pr=True, got: {pr_set}"


def test_workout_full_pr_set_includes_previous_record(authed_client, workout_with_pr):
    """AC7: the PR-setting set includes previous_record (null for first-ever)."""
    r = authed_client.get(f"/api/workouts/{workout_with_pr}/full")
    body = r.json()
    exercises = body["workout"]["exercises"]
    bench = next(e for e in exercises if "bench" in e["name"].lower())
    sets_data = bench["sets_data"]
    # First ever PR → previous_record is None
    assert "previous_record" in sets_data[0]
    assert sets_data[0]["previous_record"] is None


def test_workout_full_no_pr_sets_no_clutter(authed_client, second_workout_lower_weight):
    """AC8: workout with no PR-setting sets returns clean response."""
    r = authed_client.get(f"/api/workouts/{second_workout_lower_weight}/full")
    assert r.status_code == 200
    body = r.json()
    exercises = body.get("workout", {}).get("exercises", [])
    bench = next((e for e in exercises if "bench" in e["name"].lower()), None)
    assert bench is not None

    sets_data = bench.get("sets_data", [])
    for s in sets_data:
        # None of these sets should be a PR (80kg < 100kg record)
        assert s.get("is_pr") is not True, f"Non-PR set incorrectly marked as PR: {s}"


def test_workout_full_higher_weight_pr_set_marked(authed_client, third_workout_higher_weight):
    """AC7: the new PR workout correctly marks its set as is_pr=True."""
    r = authed_client.get(f"/api/workouts/{third_workout_higher_weight}/full")
    assert r.status_code == 200
    body = r.json()
    exercises = body["workout"]["exercises"]
    bench = next(e for e in exercises if "bench" in e["name"].lower())
    sets_data = bench["sets_data"]
    assert sets_data[0]["is_pr"] is True
    # previous_record should reflect the 100.0 kg that was beaten
    assert sets_data[0]["previous_record"] == pytest.approx(100.0)


# ── AC1: GET /api/records response shape ──────────────────────────────────────

def test_records_response_shape(authed_client, workout_with_pr):
    """AC1: record row includes current value, previous value, and achieved_on date."""
    r = authed_client.get("/api/records")
    records = r.json()
    bench = next((rec for rec in records if rec["exercise_key"] == "bench press"), None)
    assert bench is not None
    assert "weight_kg" in bench
    assert "previous_weight_kg" in bench
    assert "achieved_on" in bench
    assert "exercise_key" in bench
    assert "exercise_name" in bench
    assert "rep_band_label" in bench
