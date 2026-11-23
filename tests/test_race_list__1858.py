"""P4-11 (#1858) — race list: needs-result matching, upcoming and completed rows."""
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.models import Race
from backend.services import projection_view as pv
from backend.services import race_list as rl

UID = uuid.uuid4()
TODAY = date(2026, 11, 8)


def race(**kw):
    base = dict(id=uuid.uuid4(), name="Saucony BKK 10K", race_date=date(2026, 10, 25), distance_km=10.0,
                goal_time_seconds=3240, goal_pace_seconds_per_km=324, priority="C", race_type="race",
                status="planned", actual_time_seconds=None, user_id=UID)
    base.update(kw)
    return SimpleNamespace(**base)


def run(d, km, secs=3300, wtype="run"):
    return SimpleNamespace(id=uuid.uuid4(), workout_date=d, distance_km=km, duration_seconds=secs,
                           workout_type=wtype, name="Race day")


RACE_DAY = date(2026, 10, 25)


# ── matching ─────────────────────────────────────────────────────────────────

def test_match_same_day_and_one_day_either_side():
    assert rl.match_run(RACE_DAY, 10.0, [run(RACE_DAY, 10.02)])["moving_seconds"] == 3300
    assert rl.match_run(RACE_DAY, 10.0, [run(date(2026, 10, 24), 10.0)]) is not None
    assert rl.match_run(RACE_DAY, 10.0, [run(date(2026, 10, 26), 10.0)]) is not None


def test_match_refuses_wrong_day():
    assert rl.match_run(RACE_DAY, 10.0, [run(date(2026, 10, 27), 10.0), run(date(2026, 10, 23), 10.0)]) is None


def test_match_refuses_wrong_distance():
    assert rl.match_run(RACE_DAY, 10.0, [run(RACE_DAY, 10.6)]) is None  # 6%
    assert rl.match_run(RACE_DAY, 10.0, [run(RACE_DAY, 9.4)]) is None
    assert rl.match_run(RACE_DAY, 10.0, [run(RACE_DAY, 5.0)]) is None
    assert rl.match_run(RACE_DAY, 10.0, [run(RACE_DAY, 10.5)]) is not None  # exactly 5%
    assert rl.match_run(RACE_DAY, 10.0, [run(RACE_DAY, 9.5)]) is not None


def test_match_refuses_non_runs_and_missing_data():
    assert rl.match_run(RACE_DAY, 10.0, [run(RACE_DAY, 10.0, wtype="ride")]) is None
    assert rl.match_run(RACE_DAY, 10.0, [run(RACE_DAY, None)]) is None
    assert rl.match_run(RACE_DAY, None, [run(RACE_DAY, 10.0)]) is None
    assert rl.match_run(RACE_DAY, 10.0, []) is None


def test_match_prefers_closest_distance_then_nearest_day():
    near = run(date(2026, 10, 26), 10.01)
    far = run(RACE_DAY, 10.3)
    assert rl.match_run(RACE_DAY, 10.0, [far, near])["workout_id"] == str(near.id)
    same_dist_far_day = run(date(2026, 10, 24), 10.0)
    same_dist_same_day = run(RACE_DAY, 10.0)
    assert rl.match_run(RACE_DAY, 10.0, [same_dist_far_day, same_dist_same_day])["workout_id"] == str(same_dist_same_day.id)


def test_needs_result_row_suggestion_and_no_match_text():
    r = race()
    row = rl.needs_result_row(r, [run(RACE_DAY, 10.0, 3299)])
    assert row["suggested_actual"]["moving_seconds"] == 3299 and row["suggestion_reason"] is None
    row = rl.needs_result_row(r, [run(date(2026, 10, 30), 10.0)])
    assert row["suggested_actual"] is None and row["suggestion_reason"] == "No synced run matched"
    assert row["role"] == "fun" and row["role_label"] == "Fun run" and row["role_target"].startswith("Target")


def test_completed_row_chip_time_first_moving_second_and_goal_delta():
    r = race(status="done", actual_time_seconds=3190, priority="B")
    row = rl.completed_row(r, [run(RACE_DAY, 10.0, 3201)])
    assert row["chip_time_sec"] == 3190 and row["moving_time_sec"] == 3201
    assert row["goal_minus_actual_sec"] == 3240 - 3190 and row["role"] == "pb"
    assert rl.completed_row(r, [])["moving_time_sec"] is None


# ── assembled list ───────────────────────────────────────────────────────────

def fake_session(races, runs):
    db = MagicMock()

    def query(arg):
        q = MagicMock()
        if arg is Race:
            q.filter.return_value.order_by.return_value.all.return_value = races
        else:
            q.filter.return_value.all.return_value = runs
        return q

    db.query.side_effect = query
    return db


def test_build_race_list_sections_target_and_recalibrates_note():
    a = race(name="Bangsaen42", race_date=date(2026, 11, 15), distance_km=42.195, priority="A",
             goal_time_seconds=16200, goal_pace_seconds_per_km=384)
    b = race(name="Bangsaen21", race_date=date(2026, 12, 20), distance_km=21.1, priority="B", goal_time_seconds=7200)
    c = race(name="Park run", race_date=date(2026, 11, 30), distance_km=5.0, priority="C")
    pending = race()
    done = race(name="Chiang Mai", race_date=date(2026, 9, 27), distance_km=21.1, priority="B", status="done",
                actual_time_seconds=6600)
    est = {"unavailable": False, "est_sec": 14893, "band_sec": 510, "source": "x"}
    scores = {"race_specific": {"endurance": {"score": 41.0, "delta_28d": -2.0}, "speed": {"score": 51.0, "delta_28d": -4.0}}}
    db = fake_session([done, pending, a, c, b], [run(RACE_DAY, 10.0)])
    with patch.object(rl, "next_a_race", return_value=a), \
            patch.object(rl, "estimate_race_finish", return_value=est), \
            patch("backend.services.score_reader.get_race_scores", return_value=scores):
        out = rl.build_race_list(db, UID, TODAY)
    assert [r["name"] for r in out["needs_result"]] == ["Saucony BKK 10K"]
    assert out["needs_result"][0]["suggested_actual"]["moving_seconds"] == 3300
    assert [r["name"] for r in out["upcoming"]] == ["Bangsaen42", "Park run", "Bangsaen21"]
    up = {r["name"]: r for r in out["upcoming"]}
    assert up["Bangsaen42"]["is_target"] and not up["Bangsaen21"]["is_target"]
    assert up["Bangsaen42"]["recalibrates_here"] and up["Bangsaen21"]["recalibrates_here"]
    assert not up["Park run"]["recalibrates_here"]
    assert up["Bangsaen42"]["race_specific"]["endurance"] == {"score": 41.0, "delta_28d": -2.0}
    assert [r["name"] for r in out["completed"]] == ["Chiang Mai"]
    assert out["total_upcoming"] == 3


def test_a_race_row_estimate_equals_chain_final_before_and_after_recording():
    a = race(name="Bangsaen42", race_date=date(2026, 11, 15), distance_km=42.195, priority="A", goal_time_seconds=16200)
    for est_sec in (14893, 14610):  # before / after a recorded result moves the estimate
        est = {"unavailable": False, "est_sec": est_sec, "band_sec": 510}
        db = fake_session([a], [])
        with patch.object(rl, "next_a_race", return_value=a), \
                patch.object(rl, "estimate_race_finish", return_value=est), \
                patch("backend.services.score_reader.get_race_scores", return_value={}):
            row = rl.build_race_list(db, UID, TODAY)["upcoming"][0]
        chain = pv.build_chain(est, None, None, 42.195, {"time_sec": 16200}, a.name)
        assert row["estimate"]["est_sec"] == chain["final"]["est_sec"] == est_sec
        assert row["estimate"]["range_low_sec"] == est_sec - 510
        chart = pv.build_chart(start=date(2026, 9, 1), today=TODAY, race=a, est=est, goal_sec=16200,
                               history=[], recalibrations=[], ticks=[], pending=[])
        assert pv.check_invariants({"chain": chain, "chart": chart}, hero_est_sec=row["estimate"]["est_sec"]) == []


def test_recording_uses_existing_calibrate_flow_and_projection_ensures_calibration():
    js = Path("frontend/js/v2-performance.js").read_text()
    assert '"/api/races/" + encodeURIComponent(raceId) + "/calibrate"' in js
    assert "/calibrate/accept" in js and "reloadProjectionViews" in js
    src = Path("backend/main.py").read_text()
    assert "ensure_calibrations" in src  # recorded result becomes a calibration row on the write path (#1937)


# ── endpoint / page ──────────────────────────────────────────────────────────

def test_endpoint_requires_session():
    from backend.auth import resolve_user
    from backend.main import app
    from backend.models import User

    assert TestClient(app).get("/api/performance/races").status_code == 401
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        with patch("backend.services.race_list.build_race_list", return_value={"needs_result": [], "upcoming": []}):
            r = TestClient(app).get("/api/performance/races")
        assert r.status_code == 200 and r.json()["upcoming"] == []
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_page_wiring_drawer_and_rows():
    html = Path("frontend/pages/v2-performance.html").read_text()
    js = Path("frontend/js/v2-performance.js").read_text()
    assert 'id="v2-perf-races"' in html
    for needle in ("data-needs-result", "data-suggested-actual", "data-no-match", "data-race-target", "data-recalibrates-here",
                   "data-race-role", "data-chip-time", "data-moving-time", "Record and recalibrate", "openRaceDrawer",
                   '"PATCH", "/api/races/"', '"POST", "/api/races"'):
        assert needle in js
