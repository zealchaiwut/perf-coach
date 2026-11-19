from backend.services.plan_match_payload import who_label
from backend.services.training_month import _week_target_meta


def test_who_label_coach_locked_planned():
    assert who_label(kind="run", source="coach", status="planned") == "COACH · LOCKED"


def test_who_label_missed():
    assert who_label(kind="run", source="coach", status="missed") == "MISSED"


def test_week_target_meta_on_target_within_five_percent():
    meta = _week_target_meta({"tss_total": 102, "target_tss": 100, "partial": False})
    assert meta["on_target"] is True
    assert meta["bar_pct"] == 100


def test_week_target_meta_over_target():
    meta = _week_target_meta({"tss_total": 136, "target_tss": 100, "partial": False})
    assert meta["on_target"] is False
    assert meta["delta"] == 36.0