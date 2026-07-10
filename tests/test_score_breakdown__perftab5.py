"""Tests for the score-change decomposition (Performance tab):

    score_then + decay + efforts + consistency == score_now   (±0.05)

asserted across pure-decay, pure-gain (displacement), and mixed fixtures,
plus anchor/non-anchor semantics and the residual-raises contract. Pure
functions except the single-source live test at the bottom.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.db import engine
from backend.models import User, UserPreferences, Workout, WorkoutSplit
from backend.services.running_performance import (
    BREAKDOWN_RESIDUAL_TOLERANCE,
    compute_speed_score,
)
from backend.services.vdot import GRACE_WEEKS

BASE_URL = os.environ.get("UAT_BASE_URL") or (
    "http://127.0.0.1:" + os.environ.get("UAT_PORT", "9001")
)

_PREFS = {"threshold_pace_seconds_per_km": 280}


def _run(rid: str, days_ago: int, pace: float) -> dict:
    return {
        "run_id": rid,
        "workout_date": (date.today() - timedelta(days=days_ago)).isoformat(),
        "laps": [{"band": "hard", "distance_km": 1.0, "duration_seconds": pace, "avg_hr": 165}],
    }


def _bd(runs):
    res = compute_speed_score(runs, _PREFS, None)
    assert res.get("breakdown"), res
    return res["breakdown"], res


def _assert_invariant(b):
    assert abs(b["score_then"] + b["decay"] + b["efforts"] + b["consistency"] - b["score_now"]) < 0.05, b


def test_invariant_pure_decay_no_new_efforts():
    """All efforts predate the window: efforts == 0, delta == decay + consistency."""
    runs = [_run(f"o{i}", 40 + i * 3, 280 + i) for i in range(4)]
    b, _ = _bd(runs)
    _assert_invariant(b)
    assert b["efforts"] == 0.0
    assert b["decay"] <= 0
    assert b["delta"] == pytest.approx(b["decay"] + b["consistency"], abs=0.05)


def test_invariant_pure_gain_new_anchor_displaces_old():
    """A strong new effort inside the window displaces an old anchor — the
    whole swing lands on `efforts`, none of it misattributed to decay
    (decay is measured on the OLD pool alone)."""
    old = [_run(f"o{i}", 35 + i, 300) for i in range(3)]
    new = [_run("new", 3, 240)]  # far stronger, inside the window
    b_old, _ = _bd(old)
    b, _ = _bd(old + new)
    _assert_invariant(b)
    assert b["efforts"] > 0
    # Decay identical to the old-pool-only run of the same window.
    assert b["decay"] == pytest.approx(b_old["decay"], abs=0.05)


def test_invariant_mixed():
    runs = [_run(f"o{i}", 40 + i, 285) for i in range(3)] + [
        _run("mid", 10, 290),  # window, below anchors
        _run("big", 4, 255),   # window, displaces
    ]
    b, _ = _bd(runs)
    _assert_invariant(b)
    assert b["efforts"] > 0
    assert b["decay"] <= 0


def test_anchor_within_grace_has_zero_decay_applied():
    runs = [_run("fresh", 5, 260), _run("o1", 30, 290), _run("o2", 33, 291)]
    b, _ = _bd(runs)
    fresh = next(a for a in b["anchors"] if a["run_id"] == "fresh")
    assert fresh["age_weeks"] <= GRACE_WEEKS
    assert fresh["decay_applied"] == 0.0
    assert fresh["is_stale"] is False
    stale = next(a for a in b["anchors"] if a["run_id"] == "o1")
    assert stale["is_stale"] is True
    assert stale["decay_applied"] < 0


def test_gap_to_weakest_anchor_negative_for_every_non_anchor():
    runs = [_run(f"a{i}", 3 + i, 260 + i) for i in range(3)] + [
        _run("na1", 6, 300),
        _run("na2", 8, 320),
    ]
    b, _ = _bd(runs)
    assert {r["run_id"] for r in b["non_anchors"]} == {"na1", "na2"}
    assert all(r["gap_to_weakest_anchor"] < 0 for r in b["non_anchors"])
    # A session with gap 0 would BE an anchor: the weakest anchor's own
    # contribution minus itself is exactly 0, and anything ≥ it is in top-3.
    weakest = min(a["current_contribution"] for a in b["anchors"])
    assert b["weakest_anchor_now"] == pytest.approx(weakest, abs=0.01)


def test_breakdown_score_matches_card_score():
    """Single source: the breakdown's score_now IS the card score."""
    runs = [_run(f"a{i}", 3 + i, 270 + i) for i in range(4)]
    b, res = _bd(runs)
    assert b["score_now"] == res["score"]


def test_residual_beyond_tolerance_withheld_not_rendered():
    """The telescoped sum is exact by construction — the ONE way the
    invariant can break is the 0-100 display clamp binding (sum lands above
    100, display shows 100). In that case the payload must refuse to render
    a decomposition (error marker instead of authoritative-looking parts)."""
    # Efforts at the plausibility limit → per-point perf saturates at 100 →
    # mean 100 + consistency bonus pushes the unclamped sum past 100.
    runs = [_run(f"max{i}", 3 + i, 150) for i in range(3)]
    res = compute_speed_score(runs, _PREFS, None)
    assert res["score"] == 100.0  # display clamped
    b = res.get("breakdown")
    assert b is not None
    assert b.get("error") == "residual"
    assert abs(b["residual"]) > BREAKDOWN_RESIDUAL_TOLERANCE
    assert "anchors" not in b


# ── Live single-source regression (62/58-vs-70/43 class) ────────────────────

@pytest.fixture()
def breakdown_athlete():
    pwd = "perftab5pass!"
    uid = uuid.uuid4()
    uname = f"perftab5_{uid.hex[:8]}"
    today = date.today()
    with Session(engine) as db:
        db.add(User(id=uid, name=uname, password_hash=hash_password(pwd),
                    is_admin=False, is_active=True))
        db.add(UserPreferences(user_id=uid, threshold_hr=172,
                               threshold_pace_seconds_per_km=330))
        db.commit()
        for i in range(6):
            w = Workout(user_id=uid, workout_date=today - timedelta(days=3 + i * 7),
                        name=f"intervals {i}", workout_type="run", tss=60,
                        distance_km=8, duration_seconds=8 * 330, avg_hr=160)
            db.add(w)
            db.flush()
            db.add(WorkoutSplit(workout_id=w.id, split_index=1, distance_km=1.0,
                                 duration_seconds=290, avg_hr=168))
            # ~0.79 pace ratio vs threshold → "easy" band, so the endurance
            # score qualifies too (tempo laps are excluded from both scores).
            db.add(WorkoutSplit(workout_id=w.id, split_index=2, distance_km=7.0,
                                 duration_seconds=7 * 420, avg_hr=138))
        db.commit()

    client = httpx.Client(base_url=BASE_URL, timeout=60.0)
    r = client.post("/api/auth/login", json={"username": uname, "password": pwd})
    assert r.status_code == 200, r.text
    yield client, uid
    client.close()
    with Session(engine) as db:
        wids = [w.id for w in db.query(Workout).filter(Workout.user_id == uid).all()]
        if wids:
            db.query(WorkoutSplit).filter(WorkoutSplit.workout_id.in_(wids)).delete(synchronize_session=False)
        db.query(Workout).filter(Workout.user_id == uid).delete()
        db.query(UserPreferences).filter(UserPreferences.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_breakdown_endpoint_matches_performance_card(breakdown_athlete):
    client, uid = breakdown_athlete
    perf = client.get(f"/api/athletes/{uid}/performance")
    assert perf.status_code == 200, perf.text
    pdata = perf.json()
    if pdata.get("state") != "scored":
        pytest.skip(f"fixture not scored: {pdata.get('state')} {pdata.get('reason')}")
    for metric in ("endurance", "speed"):
        card_score = (pdata.get(metric) or {}).get("score")
        if card_score is None:
            continue
        bd = client.get(f"/api/performance/score-breakdown?metric={metric}&window=28d")
        assert bd.status_code == 200, bd.text
        assert bd.json()["score_now"] == card_score


def test_breakdown_endpoint_rejects_bad_params(breakdown_athlete):
    client, _ = breakdown_athlete
    assert client.get("/api/performance/score-breakdown?metric=power").status_code == 422
    assert client.get("/api/performance/score-breakdown?metric=speed&window=7d").status_code == 422
