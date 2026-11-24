"""P4-10 (#1857) — calibration tiles, projection chain and time-scaled chart."""
import re
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.models import Race
from backend.services import projection_view as pv
from backend.services import race_hero
from backend.services.race_roles import race_role, recalibrates

UID = uuid.uuid4()
TODAY = date(2026, 11, 8)
RACE_DATE = date(2026, 11, 15)
START = date(2026, 9, 1)
EST = {"unavailable": False, "est_sec": 14893, "band_sec": 510, "source": "performance_time_curve"}
BASIS = {
    "endurance_score": 41.0, "endurance_pace_seconds_per_km": 387,
    "speed_score": 45.0, "speed_pace_seconds_per_km": 363,
    "speed_weight": 0.38, "blended_pace_seconds_per_km": 378,
}
BLEND = {"correction": 0.917, "n": 3, "raw_correction": 0.917}
GOAL = {"time_sec": 16200, "pace_seconds_per_km": 384, "state": "provisional", "reason": "x", "editable": True}


def race_obj(**kw):
    base = dict(id=uuid.uuid4(), name="Bangsaen42", race_date=RACE_DATE, distance_km=42.195,
                goal_time_seconds=16200, goal_pace_seconds_per_km=384, priority="A",
                race_type="race", status="planned", actual_time_seconds=None, user_id=UID,
                role="a_race")
    base.update(kw)
    if "role" not in kw:
        if base.get("race_type") == "checkpoint":
            base["role"] = "long_run"
        elif base.get("priority") == "A":
            base["role"] = "a_race"
        elif base.get("priority") == "B":
            base["role"] = "pb"
        else:
            base["role"] = "fun"
    return SimpleNamespace(**base)


def payload(est=EST, history=None):
    race = race_obj()
    chain = pv.build_chain(est, BASIS, BLEND, 42.195, GOAL, race.name)
    chart = pv.build_chart(
        start=START, today=TODAY, race=race, est=est, goal_sec=GOAL["time_sec"],
        history=history if history is not None else [(date(2026, 9, 1), 16100), (date(2026, 9, 27), 15300), (TODAY, 14950)],
        recalibrations=[{"date": date(2026, 9, 27), "race_id": "r1", "name": "Chiang Mai", "role": "pb"}],
        ticks=[{"date": date(2026, 10, 4), "race_id": "r2", "name": "Long run", "role": "long_run"}],
        pending=[{"date": date(2026, 10, 25), "race_id": "r3", "name": "Saucony BKK 10K", "role": "fun"}],
    )
    return {"chain": chain, "chart": chart}


# ── invariants ───────────────────────────────────────────────────────────────

def test_invariant_chain_final_equals_hero_estimate():
    p = payload()
    hero_est = race_hero.build_estimate_block(EST, 42.195)
    assert p["chain"]["final"]["est_sec"] == hero_est["est_sec"] == EST["est_sec"]
    assert pv.check_invariants(p, hero_est_sec=hero_est["est_sec"]) == []
    # a drifting chain is reported
    p["chain"]["final"]["est_sec"] += 1
    assert any("hero" in v for v in pv.check_invariants(p, hero_est_sec=EST["est_sec"]))


def test_invariant_band_labels_are_estimate_minus_and_plus_band():
    band = payload()["chart"]["band"]
    est, b = EST["est_sec"], EST["band_sec"]
    assert band["low_sec"] == est - b and band["high_sec"] == est + b
    assert band["low_label"] == "3:59:43" and band["high_label"] == "4:16:43"  # 14893 -/+ 510
    assert re.fullmatch(r"\d:\d\d:\d\d", band["low_label"])
    p = payload()
    p["chart"]["band"]["high_label"] = "4:16:44"
    assert any("labels" in v for v in pv.check_invariants(p))


def test_chain_stages_come_from_payload_values_only():
    chain = payload()["chain"]
    assert chain["endurance"]["pace_seconds_per_km"] == 387 and chain["endurance"]["score"] == 41.0
    assert chain["speed"]["pace_seconds_per_km"] == 363
    assert chain["blended"] == {"available": True, "pace_seconds_per_km": 378, "speed_weight_pct": 38}
    assert chain["correction"]["pct"] == -8.3 and chain["correction"]["n_races"] == 3
    assert chain["final"]["pace_seconds_per_km"] == round(14893 / 42.195) and chain["final"]["band_sec"] == 510
    assert chain["final"]["goal"]["time_sec"] == 16200


# ── chart fixture: one recalibration, one pending race ──────────────────────

def test_chart_time_scaled_fixture_with_one_recalibration_and_one_pending():
    ch = payload()["chart"]
    assert ch["available"] and ch["start"] == "2026-09-01" and ch["end"] == "2026-11-15"
    span = (RACE_DATE - START).days
    assert ch["now_x"] == round((TODAY - START).days / span, 4)
    assert [m["x"] for m in ch["recalibrations"]] == [round(26 / span, 4)]
    assert [m["name"] for m in ch["pending"]] == ["Saucony BKK 10K"]
    assert [m["role"] for m in ch["ticks"]] == ["long_run"]
    assert ch["history"][0]["x"] == 0.0 and ch["projection"]["to_x"] == 1.0
    assert ch["y_min_sec"] <= 14893 - 510 and ch["y_max_sec"] >= 16200  # goal and band inside the range


def test_chart_script_renders_all_marks():
    js = Path("frontend/js/v2-performance.js").read_text()
    for needle in ("data-chart-recal", "data-chart-pending", "data-chart-tick", 'data-chart="band"',
                   'data-chart="history"', 'data-chart="projection"', "data-band-label", "Now"):
        assert needle in js


# ── degrade to not available ────────────────────────────────────────────────

def test_missing_calibration_fields_degrade_to_not_available():
    tiles = pv.build_tiles(None, [], None, None)
    assert all(t["available"] is False and t["reason"] == "not available" for t in tiles.values())
    partial = pv.build_tiles({"data_sufficiency": "Low", "band_confidence": None, "last_calibration_date": None},
                             [], None, {"correction": 1.0, "n": 0})
    assert partial["data_sufficiency"] == {"available": True, "value": "Low"}
    assert partial["band_confidence"]["available"] is False
    assert partial["last_recalibrated"]["available"] is False
    assert partial["model_correction"]["available"] is False


def test_tiles_with_sources():
    tiles = pv.build_tiles(
        {"last_calibration_date": "2026-09-27", "data_sufficiency": "Sufficient", "band_confidence": "High"},
        [], "Chiang Mai", BLEND)
    assert tiles["last_recalibrated"] == {"available": True, "date": "2026-09-27", "race_name": "Chiang Mai"}
    mc = tiles["model_correction"]
    assert mc["pct"] == -8.3 and mc["n_races"] == 3 and mc["reading"] == "ran pessimistic"


def test_unavailable_estimate_keeps_card_and_chain_stages():
    est = {"unavailable": True, "est_sec": None, "reason": "no training-load history"}
    p = payload(est=est)
    assert p["chain"]["final"]["available"] is False
    assert p["chain"]["blended"]["available"] is True  # stage values still shown
    assert p["chart"]["available"] is False and p["chart"]["reason"] == "not available"
    assert pv.check_invariants(p) == []
    p2 = pv.build_chain(est, None, None, 42.195, GOAL, "X")
    assert all(p2[k]["available"] is False for k in ("endurance", "speed", "blended", "correction"))


# ── roles: only pb / a_race recalibrate ──────────────────────────────────────

def test_roles_derived_and_explicit():
    assert race_role(race_obj(priority="A", role="a_race")) == "a_race"
    assert race_role(race_obj(priority="B", role="pb")) == "pb"
    assert race_role(race_obj(priority="C", role="fun")) == "fun"
    assert race_role(race_obj(priority="B", race_type="checkpoint", role="long_run")) == "long_run"
    assert race_role(race_obj(priority="C", role="pb")) == "pb"
    assert race_role(race_obj(priority="A", role=None)) == "fun"  # missing column does not recalibrate
    assert recalibrates(race_obj(role="pb")) and not recalibrates(race_obj(priority="C", role="fun"))
    assert not recalibrates(race_obj(priority="A", role=None))


def test_ensure_calibrations_skips_long_run_and_fun():
    from backend.services.race_calibration import ensure_calibrations

    pb = SimpleNamespace(
        id=uuid.uuid4(), status="done", actual_time_seconds=6000, distance_km=21.1,
        priority="B", race_type="race", role="pb",
    )
    lr = SimpleNamespace(
        id=uuid.uuid4(), status="done", actual_time_seconds=5000, distance_km=18.0,
        priority="B", race_type="checkpoint", role="long_run",
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = [
        [pb, lr],  # done races
        [],  # existing calibrations
    ]
    with patch("backend.services.race_calibration.recalibrate_race", return_value={"race_id": str(pb.id)}) as recal:
        n = ensure_calibrations(str(UID), db)
    assert n == 1
    assert recal.call_count == 1
    assert recal.call_args[0][1] is pb


def test_long_run_result_leaves_blend_unchanged_pb_moves_it():
    """AC: only pb/a_race calibrations enter the blend (long_run rows are dropped upstream)."""
    from backend.services.race_calibration import combined_correction, load_calibrations

    def row(prio, rtype="race"):
        rid = uuid.uuid4()
        cal = SimpleNamespace(
            race_id=rid, race_date=date(2026, 10, 4), distance_km=18.0, correction=0.80,
            predicted_seconds=5000, actual_seconds=4000, created_at=None,
        )
        return cal, SimpleNamespace(id=rid, priority=prio, race_type=rtype, role="long_run")

    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = [
        row("B", "checkpoint"),
    ]
    assert load_calibrations(str(UID), db) == []
    assert combined_correction([], 42.195, today=TODAY)["correction"] == 1.0

    pb_cal = [{"race_date": date(2026, 9, 27), "distance_km": 21.1, "correction": 0.917}]
    moved = combined_correction(pb_cal, 42.195, today=TODAY)
    assert moved["n"] == 1 and moved["correction"] != 1.0


def test_built_from_latest_calibration_and_cp_stale():
    cal_rows = [{
        "race_id": str(uuid.uuid4()),
        "race_date": date(2026, 9, 27),
        "actual_seconds": 6300,
    }]
    session = MagicMock()
    session.get.return_value = race_obj(name="Chiang Mai", priority="B")
    cp_status = {"current_cp_w": 280, "stale": True}
    with patch("backend.services.cp_staleness.get_cp_status", return_value=cp_status):
        out = pv.build_built_from(session, UID, TODAY, cal_rows)
    assert out["race_name"] == "Chiang Mai" and out["race_time_sec"] == 6300
    assert out["cp_w"] == 280 and out["cp_stale"] is True and out["available"]


def test_load_calibrations_excludes_long_run_and_fun():
    from backend.services.race_calibration import load_calibrations

    def row(prio, rtype="race"):
        rid = uuid.uuid4()
        cal = SimpleNamespace(race_id=rid, race_date=date(2026, 9, 27), distance_km=21.1, correction=0.95,
                              predicted_seconds=7000, actual_seconds=6650, created_at=None)
        role = "long_run" if rtype == "checkpoint" else {"A": "a_race", "B": "pb"}.get(prio, "fun")
        return cal, SimpleNamespace(id=rid, priority=prio, race_type=rtype, role=role)

    rows = [row("B"), row("A"), row("C"), row("B", "checkpoint")]
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = rows
    out = load_calibrations(str(UID), db)
    assert [c["race_id"] for c in out] == [str(rows[0][0].race_id), str(rows[1][0].race_id)]


def test_markers_split_recalibrations_ticks_and_pending():
    pb = race_obj(name="Chiang Mai", priority="B", status="done", actual_time_seconds=6600, race_date=date(2026, 9, 27))
    lr = race_obj(name="Long run", priority="B", race_type="checkpoint", status="done", actual_time_seconds=5000, race_date=date(2026, 10, 4))
    fun_done = race_obj(name="Fun run", priority="C", status="done", actual_time_seconds=3000, race_date=date(2026, 10, 11))
    pend = race_obj(name="Saucony BKK 10K", priority="C", status="planned", race_date=date(2026, 10, 25))
    upcoming_planned_pb = race_obj(name="Later", priority="B", status="planned", race_date=date(2026, 11, 8))  # today, not past
    a = race_obj()
    db = MagicMock()

    def query(arg):
        q = MagicMock()
        if arg is Race:
            q.filter.return_value.order_by.return_value.all.return_value = [pb, lr, fun_done, pend, upcoming_planned_pb]
        else:
            q.filter.return_value.all.return_value = [SimpleNamespace(race_id=pb.id)]
        return q

    db.query.side_effect = query
    recal, ticks, pending = pv._markers(db, UID, a, START, TODAY)
    assert [m["name"] for m in recal] == ["Chiang Mai"]
    assert [m["name"] for m in ticks] == ["Long run", "Fun run"]
    assert {m["role"] for m in ticks} <= {"long_run", "fun"}
    assert [m["name"] for m in pending] == ["Saucony BKK 10K"]


# ── goal: provisional / locked ───────────────────────────────────────────────

def _goal_db(races):
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = races
    return db


def test_goal_provisional_until_last_pb_has_result_then_locked():
    a = race_obj()
    pending_pb = race_obj(name="Bangsaen21", priority="B", status="planned", race_date=date(2026, 10, 20))
    g = pv.goal_state(_goal_db([pending_pb]), UID, a)
    assert g["state"] == "provisional" and g["editable"] and "Bangsaen21" in g["reason"]
    done_pb = race_obj(name="Bangsaen21", priority="B", status="done", actual_time_seconds=6500, race_date=date(2026, 10, 20))
    g = pv.goal_state(_goal_db([done_pb]), UID, a)
    assert g["state"] == "locked" and g["editable"] and g["time_sec"] == 16200
    # only the LAST pb matters: an earlier done pb does not lock while a later one waits
    early = race_obj(name="Early", priority="B", status="done", actual_time_seconds=6500, race_date=date(2026, 9, 10))
    late = race_obj(name="Late", priority="B", status="planned", race_date=date(2026, 10, 30))
    assert pv.goal_state(_goal_db([late, early]), UID, a)["state"] == "provisional"
    # non-pb races never lock it
    fun = race_obj(priority="C", status="done", actual_time_seconds=3000, race_date=date(2026, 10, 1))
    assert pv.goal_state(_goal_db([fun]), UID, a)["state"] == "provisional"


# ── assembled payload: one estimate call feeds hero, chain, chart ────────────

def test_build_projection_one_estimate_feeds_chain_chart_and_hero():
    a = race_obj()
    prefs = SimpleNamespace(threshold_pace_seconds_per_km=330)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = prefs
    scores = {"overall": {"endurance": {"score": 41.0}, "speed": {"score": 45.0}}}
    with patch.object(pv, "next_upcoming_race", return_value=a), \
            patch.object(pv, "estimate_race_finish", return_value=EST) as est_call, \
            patch("backend.services.race_calibration.load_calibrations", return_value=[]), \
            patch("backend.services.race_calibration.record_prediction") as snap, \
            patch.object(pv, "build_built_from", return_value={"available": False}), \
            patch.object(pv, "_calibration_tiles", return_value=pv.build_tiles(None, [], None, None)), \
            patch.object(pv, "goal_state", return_value=GOAL), \
            patch.object(pv, "_block_start", return_value=START), \
            patch.object(pv, "_markers", return_value=([], [], [])), \
            patch.object(pv, "_history", return_value=[(TODAY, 14950)]), \
            patch("backend.services.score_reader.get_scores", return_value=scores):
        out = pv.build_projection(db, UID, TODAY)
    snap.assert_not_called()
    assert est_call.call_count == 1
    assert out["invariants"] == {"ok": True, "violations": []}
    assert out["chain"]["final"]["est_sec"] == out["chart"]["projection"]["est_sec"] == EST["est_sec"]
    assert out["chain"]["blended"]["available"] is True  # real basis computed from the patched scores

    with patch.object(race_hero, "next_a_race", return_value=a), \
            patch.object(race_hero, "estimate_race_finish", return_value=EST), \
            patch.object(race_hero, "build_after_race", return_value={}), \
            patch.object(race_hero, "get_race_scores", return_value={}), \
            patch("backend.services.a_race_readiness_checklist.build_checklist", return_value={"summary": None}):
        hero = race_hero.build_hero(MagicMock(), UID, TODAY)
    assert hero["estimate"]["est_sec"] == out["chain"]["final"]["est_sec"]


def test_no_a_race_still_returns_tiles():
    with patch.object(pv, "next_upcoming_race", return_value=None), \
            patch("backend.services.race_calibration.load_calibrations", return_value=[]), \
            patch.object(pv, "_calibration_tiles", return_value=pv.build_tiles(None, [], None, None)), \
            patch.object(pv, "_reference_race_for_history", return_value=None), \
            patch("backend.services.score_reader.get_scores", side_effect=RuntimeError("skip chain")):
        out = pv.build_projection(MagicMock(), UID, TODAY)
    assert out["chain"] is None and out["chart"] is None and "tiles" in out


def test_no_a_race_returns_partial_chain_and_history_chart():
    a = race_obj(status="done", race_date=date(2026, 10, 1), actual_time_seconds=15000)
    scores = {"overall": {"endurance": {"score": 41.0}, "speed": {"score": 45.0}}}
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    with patch.object(pv, "next_upcoming_race", return_value=None), \
            patch("backend.services.race_calibration.load_calibrations", return_value=[{
                "race_id": str(a.id), "race_date": a.race_date, "actual_seconds": 15000,
            }]), \
            patch.object(pv, "_calibration_tiles", return_value=pv.build_tiles(None, [], None, BLEND)), \
            patch.object(pv, "_reference_race_for_history", return_value=a), \
            patch.object(pv, "_block_start", return_value=START), \
            patch.object(pv, "_markers", return_value=([], [], [])), \
            patch.object(pv, "_history", return_value=[(START, 16100), (TODAY, 14950)]), \
            patch("backend.services.score_reader.get_scores", return_value=scores):
        out = pv.build_projection(db, UID, TODAY)
    assert out["chain"] is not None
    assert out["chain"]["blended"]["available"] is True
    assert out["chain"]["final"]["available"] is False
    assert out["chart"]["available"] is True and out["chart"]["history_only"] is True
    assert out["chart"]["projection"] is None


# ── endpoint / page ──────────────────────────────────────────────────────────

def test_endpoint_requires_session_and_returns_payload():
    from backend.auth import resolve_user
    from backend.main import app
    from backend.models import User

    assert TestClient(app).get("/api/performance/projection").status_code == 401
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        with patch("backend.services.projection_view.build_projection", return_value={"tiles": {}, "chain": None}):
            r = TestClient(app).get("/api/performance/projection")
        assert r.status_code == 200 and r.json()["chain"] is None
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_page_wiring():
    html = Path("frontend/pages/v2-performance.html").read_text()
    js = Path("frontend/js/v2-performance.js").read_text()
    assert "v2-perf-projection" in html
    assert "applyProjection" in js and "data-chain-final" in js
    assert "data-chain-na" in js and "not available" in js
    assert "data-projection-built-from" in js
