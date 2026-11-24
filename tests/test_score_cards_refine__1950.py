"""Sprint 149 #1950 — breakdown rows sum to raw score; headline agrees with delta."""
from backend.services import score_cards as sc
from tests.test_score_cards__1856 import anchor, breakdown


def _bd(avg, floor, bonus, score_now, *, decay=-1.0, efforts=4.0, anchors=None):
    bd = breakdown(decay=decay, efforts=efforts, consistency=bonus, anchors=anchors)
    bd["anchor_mean_now"] = avg
    bd["race_floor_now"] = floor
    bd["consistency_bonus_now"] = bonus
    bd["score_now"] = score_now
    return bd


def test_breakdown_rows_sum_to_raw_score():
    rows = sc.breakdown_rows(_bd(53.4, 25.6, 2.1, 55.5))
    by = {r["key"]: r for r in rows}
    inner = by["anchor_mean"]["value"]  # floor unused
    assert by["race_floor"]["muted"] is True
    assert round(inner + by["consistency"]["value"], 1) == by["score"]["value"] == 55.5
    assert by["score"]["display"] == 56

    used = sc.breakdown_rows(_bd(30.0, 40.0, 1.5, 41.5))
    by = {r["key"]: r for r in used}
    assert by["race_floor"]["muted"] is False
    assert round(by["race_floor"]["value"] + by["consistency"]["value"], 1) == by["score"]["value"]


def test_headline_never_says_down_when_delta_positive():
    stale = [
        anchor("2026-10-15", 5.6, stale=True),
        anchor("2026-10-12", 6.0, stale=True),
        anchor("2026-11-18", 0.7, stale=False),
    ]
    bd = _bd(53.4, 25.6, 2.1, 55.5, decay=-8.0, efforts=1.0, anchors=stale)
    up = sc.reason_sentence(bd, delta_28d=15)
    assert up and "down" not in up.lower()
    assert up.startswith("Up 15, but")

    down = sc.reason_sentence(bd, delta_28d=-4)
    assert down and down.lower().startswith("down")

    zero = sc.reason_sentence(breakdown(decay=-4.5, efforts=1.0), delta_28d=0)
    assert zero and "down" in zero.lower()


def test_anchor_display_date_and_stale_flag():
    card = sc.build_card(
        "endurance",
        {"score": 56.0, "delta_28d": 15.0, "stale": False},
        {"breakdown": _bd(53.4, 25.6, 2.1, 55.5, anchors=[
            anchor("2026-11-18", 0.7, raw=49.6, stale=False),
            anchor("2026-10-15", 5.6, raw=65.2, stale=True),
        ]), "model": {"top_k": 3}},
    )
    assert card["anchors"][0]["display_date"] == "18 Nov"
    assert card["anchors"][0]["is_stale"] is False
    assert card["anchors"][1]["is_stale"] is True
    assert card["split"] is None
