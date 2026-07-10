"""Tests for the CTL/ATL/TSB/ACWR single-source-of-truth fix (Part A).

The bug: the readiness cards and the weekly coach report showed DIFFERENT
CTL/ATL/TSB/ACWR for the same date (readiness via compute_fitness_series, no
calibration, no cache; the coach report via current_load, calibration-aware,
cache-backed) — two independent computations, not a display bug. The
report's ATL (17.44) was mathematically implausible for the week's actual
load (187 TSS ≈ 27 TSS/day decaying from ATL 48.9 should land near 34).

training_load_snapshots is now the sole producer (daily_update() the sole
writer; current_load()/get_snapshot_series() the sole read paths). Every
consumer — readiness, the fitness/fatigue/form chart, the weekly coach
report ("Weekly summary" and the athlete "Summary" digest card), monthly
summary — reads through one of those two functions. See
docs/calculations/training-load.md.

Real-Postgres for the DB-backed tests (assemble_facts-style seeded users);
pure unit tests for the EWMA/ACWR math checks (no DB).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import backend.services.training_load as training_load
from backend.db import engine
from backend.models import TrainingLoadSnapshot, User, Workout
from backend.services.acwr import compute_acwr
from backend.services.training_load import (
    _ewma_alpha,
    compute_load_curves,
    current_load,
    daily_tss_series,
    get_snapshot_series,
)
from tests._admin_helpers import admin_cookies

BASE_URL = "http://127.0.0.1:9001"
_TEST_PW = "loadmetric1!"


# ── AC: TSB == CTL - ATL always holds in the snapshot (pure) ────────────────

def test_tsb_equals_ctl_minus_atl_across_a_realistic_series():
    start = date(2026, 1, 1)
    # Varied load, not flat — exercises the invariant under real movement.
    tss_pattern = [80, 0, 60, 120, 0, 40, 200, 0, 30, 90]
    series = [(start + timedelta(days=i), tss_pattern[i % len(tss_pattern)]) for i in range(120)]
    curves = compute_load_curves(series)
    for row in curves:
        # tsb is rounded from the pre-rounded ctl-atl difference, so
        # round(ctl,2)-round(atl,2) can be off by the last decimal from
        # rounding order — a real float quirk, not a broken invariant.
        assert row["tsb"] == pytest.approx(row["ctl"] - row["atl"], abs=0.02), row


# ── AC: ATL decay sanity check — the exact scenario from the bug report ─────
# Starting ATL=48.9, a week at 27 TSS/day must land ATL in [32, 36]. This is
# the calculation that proves the reported ATL=17.44 was impossible.

def test_atl_decay_sanity_matches_bug_report_math():
    atl_alpha = _ewma_alpha(training_load.ATL_DAYS)
    atl = 48.9
    for _ in range(7):
        atl = atl + (27.0 - atl) * atl_alpha
    assert 32.0 <= atl <= 36.0, f"ATL after a week at 27 TSS/day = {atl:.2f}, expected [32, 36]"


def test_atl_of_17_44_is_unreachable_from_48_9_at_27_tss_per_day():
    """The specific bad value from the bug report — confirms it could only
    have come from a stale/wrong cached snapshot, not a correct recompute."""
    atl_alpha = _ewma_alpha(training_load.ATL_DAYS)
    atl = 48.9
    for _ in range(7):
        atl = atl + (27.0 - atl) * atl_alpha
    assert abs(atl - 17.44) > 5.0


# ── AC: ACWR matches acwr.compute_acwr's own formula (the documented one) ───

@pytest.fixture()
def acwr_user():
    with Session(engine) as s:
        u = User(name=f"loadmetric-acwr-{uuid.uuid4().hex[:8]}", is_active=True)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    yield uid
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        s.commit()


def test_snapshot_acwr_matches_direct_compute_acwr_call(acwr_user):
    today = date.today()
    with Session(engine) as s:
        # Varied load over 40 days so acute != chronic (a real ratio, not 1.0).
        for i in range(40):
            tss = 60 if i < 33 else 20  # recent week lighter than the base
            s.add(Workout(
                user_id=acwr_user, workout_date=today - timedelta(days=39 - i),
                name="run", workout_type="run", tss=tss,
            ))
        s.commit()

    snap = current_load(str(acwr_user), as_of=today)

    # Independently recompute ACWR the same way acwr.py defines it, from the
    # raw daily series — must match the snapshot's stored value exactly.
    series = daily_tss_series(str(acwr_user), today - timedelta(days=34), today)
    direct = compute_acwr([tss for _, tss in series])

    assert snap["acwr"] is not None
    assert direct["ratio"] is not None
    assert snap["acwr"] == pytest.approx(direct["ratio"], abs=1e-6)


# ── AC: readiness cards and the weekly coach report render identical values ─
# for the same date — the actual bug. Live-Postgres, real endpoints.

def _make_client(prefix):
    uname = f"{prefix}-{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname}, cookies=admin_cookies())
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = r.json()["id"]

    from backend.auth import hash_password
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        u.password_hash = hash_password(_TEST_PW)
        db.commit()

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
        assert r.status_code == 200, f"login failed: {r.text}"
        session_cookie = r.cookies.get("session")
        csrf_token = r.cookies.get("csrf-token")

    client = httpx.Client(
        base_url=BASE_URL, timeout=10.0,
        cookies={"session": session_cookie, "csrf-token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return client, user_id


def _cleanup_user(user_id):
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture()
def seeded_client():
    client, user_id = _make_client("loadmetric-consumer")
    today = date.today()
    # A realistic, varied 90-day history so building_baseline never gates the
    # readiness response, and so CTL/ATL/TSB are non-trivial. Direct bulk DB
    # insert, not 90 sequential POST /api/workouts calls — each of those
    # triggers its own daily_update() (180-day recompute), which is both slow
    # and needless here: this test exercises the READ paths, not the
    # workout-creation hook.
    with Session(engine) as db:
        for i in range(90):
            tss = [80, 0, 60, 120, 0, 40, 200][i % 7]
            db.add(Workout(
                user_id=uuid.UUID(user_id), workout_date=today - timedelta(days=89 - i),
                name="seed run", workout_type="run", tss=tss,
            ))
        db.commit()
    yield client, user_id
    client.close()
    _cleanup_user(user_id)


def test_readiness_matches_current_load_for_today(seeded_client):
    client, user_id = seeded_client
    today = date.today()

    r = client.get("/api/readiness")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["building_baseline"] is False

    direct = current_load(user_id, as_of=today)

    assert body["ctl"] == pytest.approx(round(direct["ctl"], 1), abs=0.05)
    assert body["atl"] == pytest.approx(round(direct["atl"], 1), abs=0.05)
    assert body["tsb"] == pytest.approx(round(direct["tsb"], 1), abs=0.05)


def test_weekly_coach_report_matches_current_load(seeded_client):
    """GET /api/weekly-summary — the "Weekly coach report" from the bug
    report — must derive ctl_end/atl_end/tsb_end from the SAME engine as
    readiness (current_load), not an independently-cached/recomputed value."""
    client, user_id = seeded_client
    today = date.today()
    # A week fully in the past, not the current week — the endpoint's
    # week_end isn't capped at today (it can legitimately project a
    # zero-load future for the CURRENT week), so only a past week's
    # week_end is guaranteed to equal a real date current_load() can be
    # compared against directly.
    last_monday = today - timedelta(days=today.weekday() + 7)
    week_end = last_monday + timedelta(days=6)

    r = client.get(f"/api/weekly-summary?week={last_monday.isoformat()}")
    assert r.status_code == 200, r.text
    facts = r.json()["facts"]

    direct = current_load(user_id, as_of=week_end)

    assert facts["ctl_end"] == pytest.approx(round(direct["ctl"], 2), abs=0.05)
    assert facts["atl_end"] == pytest.approx(round(direct["atl"], 2), abs=0.05)
    assert facts["tsb_end"] == pytest.approx(round(direct["tsb"], 2), abs=0.05)


def test_athlete_summary_widget_matches_current_load(seeded_client):
    """GET /api/athletes/{id}/summary/weekly — the "Summary" digest card —
    must derive its TSB-at-week-end from the SAME engine as readiness and
    the weekly coach report."""
    client, user_id = seeded_client
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    week_end = min(this_monday + timedelta(days=6), today)

    r = client.get(f"/api/athletes/{user_id}/summary/weekly?week={this_monday.isoformat()}")
    assert r.status_code == 200, r.text
    body = r.json()

    direct = current_load(user_id, as_of=week_end)
    readiness_r = client.get("/api/readiness")
    assert readiness_r.status_code == 200

    # form_tsb_change = tsb_end - tsb_start; tsb_end alone isn't in the
    # payload, but readiness_next_week's label must be consistent with the
    # SAME tsb_end current_load() computes.
    assert body["readiness_next_week"] == training_load.readiness_label(round(direct["tsb"], 2))


# ── AC: get_snapshot_series — row count, idempotency, real values ───────────
# (equivalent coverage to the old scripts/backfill_training_load.py pure-
# function tests, which no longer exist post-consolidation — see
# tests/test_training_load.py's note.)

@pytest.fixture()
def series_user():
    with Session(engine) as s:
        u = User(name=f"loadmetric-series-{uuid.uuid4().hex[:8]}", is_active=True)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    yield uid
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        s.commit()


def test_get_snapshot_series_creates_a_row_per_day(series_user):
    today = date.today()
    start = today - timedelta(days=9)
    with Session(engine) as s:
        for i in range(10):
            s.add(Workout(
                user_id=series_user, workout_date=start + timedelta(days=i),
                name="run", workout_type="run", tss=80,
            ))
        s.commit()

    rows = get_snapshot_series(str(series_user), start, today)

    assert len(rows) == 10
    assert rows[0]["date"] == start
    assert rows[-1]["date"] == today
    for r in rows:
        assert "ctl" in r and "atl" in r and "tsb" in r and "tss" in r
    assert all(r["ctl"] > 0 for r in rows)

    with Session(engine) as s:
        stored = (
            s.query(TrainingLoadSnapshot)
            .filter(TrainingLoadSnapshot.user_id == series_user)
            .all()
        )
    assert len(stored) == 10
    assert all(row.formula_version == training_load._FORMULA_VERSION for row in stored)


def test_get_snapshot_series_is_idempotent(series_user):
    today = date.today()
    start = today - timedelta(days=4)
    with Session(engine) as s:
        for i in range(5):
            s.add(Workout(
                user_id=series_user, workout_date=start + timedelta(days=i),
                name="run", workout_type="run", tss=60,
            ))
        s.commit()

    rows1 = get_snapshot_series(str(series_user), start, today)
    rows2 = get_snapshot_series(str(series_user), start, today)

    assert rows1 == rows2


# ── AC: a stale formula_version is treated as a cache miss and recomputed ───

def test_stale_formula_version_forces_recompute(series_user):
    today = date.today()
    with Session(engine) as s:
        s.add(Workout(
            user_id=series_user, workout_date=today,
            name="run", workout_type="run", tss=50,
        ))
        s.commit()
        # Simulate a row written by a pre-consolidation code path: correct-
        # looking numbers, but no formula_version (or an old one) and no
        # ACWR — exactly what the 3 old rogue writers could have produced.
        s.execute(
            text(
                """
                INSERT INTO training_load_snapshots
                    (user_id, snapshot_date, tss_for_day, ctl, atl, tsb, acwr, formula_version)
                VALUES (:uid, :d, 50, 999.0, 999.0, 0.0, NULL, 'pre-consolidation')
                ON CONFLICT (user_id, snapshot_date) DO UPDATE SET
                    ctl = 999.0, atl = 999.0, tsb = 0.0, acwr = NULL,
                    formula_version = 'pre-consolidation'
                """
            ),
            {"uid": series_user, "d": today},
        )
        s.commit()

    result = current_load(str(series_user), as_of=today)

    # The bogus 999.0 placeholder must NOT be trusted — current_load must
    # detect the stale formula_version and recompute for real.
    assert result["ctl"] != 999.0
    assert result["atl"] != 999.0

    with Session(engine) as s:
        row = (
            s.query(TrainingLoadSnapshot)
            .filter(TrainingLoadSnapshot.user_id == series_user, TrainingLoadSnapshot.snapshot_date == today)
            .first()
        )
    assert row.formula_version == training_load._FORMULA_VERSION
