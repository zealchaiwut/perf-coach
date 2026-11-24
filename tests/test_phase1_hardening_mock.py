from backend.services.plan_match_payload import who_label
from backend.services.training_month import _week_target_meta


def test_who_label_coach_locked_planned():
    assert who_label(kind="run", source="coach", status="planned") == "COACH · LOCKED"


def test_who_label_missed():
    assert who_label(kind="run", source="coach", status="missed") == "MISSED"


def test_who_label_tagged_race_workout():
    assert who_label(kind="race", source="unplanned", status="done") == "RACE"
    assert who_label(kind="race", source="coach", status="done") == "RACE"
    assert who_label(kind="race", source="plan", status="planned") == "B RACE"


def test_week_target_meta_on_target_within_five_percent():
    meta = _week_target_meta({"tss_total": 102, "target_tss": 100, "partial": False})
    assert meta["on_target"] is True
    assert meta["bar_pct"] == 100
    assert meta["tone"] == "good"
    assert meta["target_pct"] < 100
    assert meta["fill_pct"] > meta["target_pct"]


def test_week_target_meta_over_target():
    meta = _week_target_meta({"tss_total": 136, "target_tss": 100, "partial": False})
    assert meta["on_target"] is False
    assert meta["delta"] == 36.0
    assert meta["tone"] == "bad"
    assert meta["fill_pct"] == 100
    assert 0 < meta["target_pct"] < 100


def test_week_target_meta_under_is_yellow():
    meta = _week_target_meta({"tss_total": 262, "target_tss": 334, "partial": False})
    assert meta["tone"] == "warn"
    assert meta["fill_pct"] < meta["target_pct"]


def test_week_target_meta_within_ten_percent_is_green():
    # 352 vs 334 is +5.4% — outside the old 5% flag, inside the 10% colour band.
    meta = _week_target_meta({"tss_total": 352, "target_tss": 334, "partial": False})
    assert meta["on_target"] is False
    assert meta["tone"] == "good"