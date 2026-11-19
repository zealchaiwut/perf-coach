from datetime import date
from types import SimpleNamespace

from backend.services.plan_match_payload import (
    is_missed_planned,
    plan_kept_ratio,
    planned_item_status,
    planned_source,
)


def test_planned_source_run_is_coach():
    assert planned_source("run") == "coach"
    assert planned_source("strength") == "support"


def test_plan_kept_excludes_zero_denominator():
    assert plan_kept_ratio(0, 0) is None
    assert plan_kept_ratio(3, 1) == 0.75


def test_missed_and_skipped_states():
    today = date(2026, 11, 18)
    skipped = SimpleNamespace(
        status="skipped",
        matched_workout_id=None,
        planned_date=date(2026, 11, 10),
    )
    assert planned_item_status(skipped, today) == "skipped"
    assert is_missed_planned(skipped, today) is False
    missed = SimpleNamespace(
        status="missed_auto",
        matched_workout_id=None,
        planned_date=date(2026, 11, 10),
    )
    assert planned_item_status(missed, today) == "missed"