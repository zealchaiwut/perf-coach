"""P4-9 (#1856) — Endurance and Speed cards with a plain-language reason."""
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.services import score_cards as sc

UID = uuid.uuid4()


def anchor(date, age_weeks, *, raw=60.0, stale=False, title=None):
    a = {"date": date, "raw_score": raw, "age_weeks": age_weeks, "is_stale": stale}
    if title:
        a["title"] = title
    return a


def breakdown(decay, efforts, consistency=0.0, anchors=None, then=50.0):
    now = then + decay + efforts + consistency
    return {
        "score_then": then, "decay": decay, "efforts": efforts, "consistency": consistency,
        "score_now": now, "residual": 0.0, "window_days": 28,
        "anchors": anchors if anchors is not None else [
            anchor("2026-10-30", 1.5, raw=64.0),
            anchor("2026-08-02", 15.0, raw=58.0, stale=True, title="10K race"),
            anchor("2026-09-14", 9.0, raw=61.0, stale=True),
        ],
    }


def test_decay_branch_reads_down_from_decay_naming_aged_anchor_and_date():
    s = sc.reason_sentence(breakdown(decay=-4.5, efforts=1.0))
    assert s == (
        "Down from decay, not from slower running: the 10K race from 2026-08-02 has aged 15.0 weeks."
    )


def test_decay_branch_falls_back_to_generic_anchor_name():
    anchors = [anchor("2026-09-14", 9.0, stale=True)]
    s = sc.reason_sentence(breakdown(decay=-3.0, efforts=0.0, anchors=anchors))
    assert "the anchor effort from 2026-09-14" in s


def test_effort_branch_reads_lifted_by_effort_on_date():
    s = sc.reason_sentence(breakdown(decay=-1.0, efforts=5.5))
    assert s == "Lifted by the effort on 2026-10-30."


def test_no_sentence_when_balanced_or_zero_or_missing():
    assert sc.reason_sentence(breakdown(decay=-2.0, efforts=2.0)) is None
    assert sc.reason_sentence(breakdown(decay=0.0, efforts=0.0)) is None
    assert sc.reason_sentence(breakdown(decay=-2.0, efforts=2.004)) is None
    assert sc.reason_sentence(None) is None
    assert sc.reason_sentence({"error": "residual"}) is None
    assert sc.reason_sentence(breakdown(decay=-4.0, efforts=0.0, anchors=[])) is None


def test_formula_line_reads_breakdown_terms():
    bd = breakdown(decay=0, efforts=0, consistency=0)
    bd["anchor_mean_now"] = 55.0
    bd["race_floor_now"] = None
    bd["consistency_bonus_now"] = 2.5
    bd["score_now"] = 57.5
    assert sc.formula_line(bd) == "55.0 avg of 3 + 2.5 consistency = 57.5"


def test_split_bar_shares_use_the_decomposition_terms():
    out = sc.split_bar(breakdown(decay=-3.0, efforts=1.0, consistency=0.5))
    assert out["decay"] == 3.0 and out["gains"] == 1.5
    assert out["decay_share"] == round(3 / 4.5, 4) and out["gains_share"] == round(1.5 / 4.5, 4)
    assert sc.split_bar(breakdown(decay=0.0, efforts=0.0))["decay_share"] == 0.0
    assert sc.split_bar(None) is None


def _perf_payload():
    bd_end = breakdown(decay=-4.5, efforts=1.0)
    bd_end["anchor_mean_now"] = 39.0
    bd_end["race_floor_now"] = 38.3
    bd_end["consistency_bonus_now"] = 1.9
    return {
        "state": "scored",
        "generated_at": "2026-11-20T00:00:00+00:00",
        "endurance": {
            "score": 41.0, "block_delta": -2.0,
            "anchors": [{"date": "2026-08-02", "is_stale": True, "title": "10K race"}],
            "history_trend": [43.0, 42.0, 41.0], "history_trend_dates": ["2026-11-01", "2026-11-10", "2026-11-20"],
            "breakdown": bd_end,
            "model": {"top_k": 3},
            "improve_hint": {
                "target_score": 45,
                "pace_seconds_per_km": 322,
                "effort_minutes": 30,
            },
        },
        "speed": {
            "score": 47.0, "block_delta": 3.0,
            "anchors": [{"date": "2026-10-30", "is_stale": False}],
            "breakdown": breakdown(decay=-1.0, efforts=5.5),
            "improve_hint": {
                "target_score": 49,
                "pace_seconds_per_km": 300,
                "effort_minutes": 8,
            },
        },
    }


def test_all_numbers_flow_from_the_patched_readers():
    fake_scores = {
        "state": "scored",
        "overall": {
            "endurance": {"score": 99.0, "delta_28d": 7.0, "stale": True},
            "speed": {"score": 98.0, "delta_28d": -1.0, "stale": False},
        },
    }
    with patch.object(sc.score_reader, "get_scores", return_value=fake_scores), \
            patch.object(sc._performance_scores, "get_performance_payload", return_value=_perf_payload()):
        out = sc.build_cards(UID)
    end, spd = out["cards"]
    assert (end["axis"], spd["axis"]) == ("endurance", "speed")
    # score and delta from the P0-5 reader, not the decomposition payload
    assert end["score"] == 99.0 and end["delta_28d"] == 7.0 and end["stale"] is True
    assert spd["score"] == 98.0 and spd["delta_28d"] == -1.0
    # decomposition terms and snapshot sparkline straight from the existing payload
    assert end["decomposition"] == {
        "score_then": 50.0, "decay": -4.5, "efforts": 1.0, "consistency": 0.0, "score_now": 46.5}
    assert end["sparkline"] == {"dates": ["2026-11-01", "2026-11-10", "2026-11-20"], "values": [43.0, 42.0, 41.0]}
    assert spd["sparkline"] is None
    assert end["reason"].startswith("Down from decay") and spd["reason"].startswith("Lifted by the effort")
    assert end["formula_line"] and "38.3 race floor" in end["formula_line"]
    assert end["to_reach"].startswith("To reach 45:")
    assert spd["to_reach"].startswith("To reach 49:")
    assert [a["date"] for a in end["anchors"]][:1] == ["2026-10-30"]
    assert set(end["anchors"][0]) == {"date", "raw_score", "age_weeks", "is_stale"}


def test_invalid_breakdown_still_returns_a_card_without_reason():
    block = {"score": 40.0, "breakdown": {"error": "residual", "residual": 1.2}}
    card = sc.build_card("endurance", {"score": 40.0, "delta_28d": None, "stale": False}, block)
    assert card["reason"] is None and card["decomposition"] is None and card["split"] is None
    card = sc.build_card("speed", {"score": None, "delta_28d": None, "stale": False}, None)
    assert card["score"] is None and card["anchors"] == []


def test_endpoint_session_and_shape():
    from backend.main import app
    from backend.auth import resolve_user
    from backend.models import User

    assert TestClient(app).get("/api/performance/score-cards").status_code == 401
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        with patch("backend.services.score_cards.build_cards", return_value={"state": "scored", "cards": []}):
            r = TestClient(app).get("/api/performance/score-cards")
        assert r.status_code == 200 and r.json()["cards"] == []
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_page_wiring():
    html = Path("frontend/pages/v2-performance.html").read_text()
    js = Path("frontend/js/v2-performance.js").read_text()
    assert "v2-perf-score-cards" in html
    for needle in ("applyScoreCards", "data-card-reason", "data-card-split", "data-card-formula", "data-card-to-reach",
                   "<summary>Anchor efforts and other runs</summary>", "data-sparkline"):
        assert needle in js
