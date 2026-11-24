"""Sprint 149 #1951 — derivation chain reconstructs est_sec; next-race chart goal."""
from datetime import date
from types import SimpleNamespace

from backend.services import projection_view as pv

BASIS = {
    "endurance_score": 41.0, "endurance_pace_seconds_per_km": 387,
    "speed_score": 45.0, "speed_pace_seconds_per_km": 363,
    "speed_weight": 0.38, "blended_pace_seconds_per_km": 378,
}
GOAL = {"time_sec": 16200, "pace_seconds_per_km": 384, "state": "provisional", "reason": "x", "editable": True}


def race_obj(**kw):
    base = dict(id="r1", name="Bangsaen21", race_date=date(2026, 12, 20), distance_km=21.0975,
                goal_time_seconds=6600, priority="B", role="pb")
    base.update(kw)
    return SimpleNamespace(**base)


def test_chain_steps_multiply_to_est_sec_within_one_second():
    pre, corr = 6700, 1.011
    est_sec = int(round(pre * corr))
    est = {
        "unavailable": False, "est_sec": est_sec, "band_sec": 176,
        "form_factor": 0.939, "correction": corr, "pre_correction_sec": pre,
        "post_correction_sec": est_sec, "projected_ctl": 52.0,
    }
    goal = {**GOAL, "time_sec": 6600}
    chain = pv.build_chain(est, BASIS, {"correction": corr, "n": 4}, 21.0975, goal, "Bangsaen21")
    assert chain["correction"]["formatted"] == "×1.011"
    assert abs(chain["product_sec"] - chain["final"]["est_sec"]) <= 1
    assert chain["final"]["est_sec"] == est_sec
    assert chain["final"]["vs_goal"] == "slower"
    keys = [s["key"] for s in chain["steps"]]
    assert keys == ["endurance", "speed", "blend", "fitness", "correction", "final"]
    assert chain["fitness"]["formatted"] == "×0.939"

    faster = pv.build_chain(
        {**est, "est_sec": 6500, "post_correction_sec": 6500},
        BASIS, {"correction": corr, "n": 4}, 21.0975, goal, "Bangsaen21",
    )
    assert faster["final"]["vs_goal"] == "faster"


def test_chart_uses_next_race_goal_and_offsets_close_tags():
    half = race_obj(
        name="Bangsaen21", race_date=date(2026, 12, 20), distance_km=21.0975,
        goal_time_seconds=6600, priority="B", role="pb",
    )
    est = {"unavailable": False, "est_sec": 6782, "band_sec": 176}
    start = date(2026, 9, 27)
    today = date(2026, 11, 23)
    a = date(2026, 11, 15)
    b = date(2026, 11, 21)
    ch = pv.build_chart(
        start=start, today=today, race=half, est=est, goal_sec=6600,
        history=[(today, 6782)],
        recalibrations=[{"date": a, "race_id": "r1", "name": "Bangsaen42", "role": "a_race"}],
        ticks=[{"date": b, "race_id": "r2", "name": "KFC 10K", "role": "fun"}],
        pending=[],
    )
    assert ch["goal_sec"] == 6600
    assert ch["goal_label"] == "1:50"
    lanes = {m["name"]: m["tag_lane"] for m in ch["recalibrations"] + ch["ticks"]}
    assert lanes["Bangsaen42"] != lanes["KFC 10K"]


def test_next_upcoming_race_prefers_soonest_not_only_a():
    today = date(2026, 11, 23)
    half = SimpleNamespace(id="h", race_date=date(2026, 12, 20), status="planned")
    a = SimpleNamespace(id="a", race_date=date(2027, 3, 1), status="planned")

    class Q:
        def filter(self, *a, **k):
            return self
        def order_by(self, *a, **k):
            return self
        def first(self):
            return half

    class Sess:
        def query(self, *a, **k):
            return Q()

    assert pv.next_upcoming_race(Sess(), "u", today) is half
    assert half.race_date < a.race_date
