"""Issue #1846 — revamp plan settings preview and save gates."""

from datetime import date, timedelta

import pytest

from backend.services.revamp_load_plan import (
    REVAMP_PLAN_DEFAULTS,
    LoadPlanLayoutError,
    block_start_for_race,
    compute_revamp_block_series,
    validate_block_layout,
    week_starts_in_block,
)
from backend.services.revamp_plan_settings import preview_settings_change
from backend.utils.time import today_bangkok


class _Race:
    def __init__(self, race_date: date, priority: str = "A", status: str = "planned"):
        self.id = "00000000-0000-0000-0000-000000000001"
        self.user_id = "00000000-0000-0000-0000-000000000099"
        self.name = "Test A"
        self.race_date = race_date
        self.priority = priority
        self.status = status


class _Sess:
    def get(self, model, pk):
        return None


def _preview_pure(old_settings, new_settings, *, today: date, chronic: float = 200.0):
    race = date(2026, 6, 1)  # Monday
    block_start = block_start_for_race(race, new_settings)
    current_ws = today - timedelta(days=today.weekday())
    old_peak, old_series = validate_block_layout(
        chronic_baseline=chronic,
        block_start=block_start,
        race_date=race,
        settings=old_settings,
    )
    new_peak, new_series = validate_block_layout(
        chronic_baseline=chronic,
        block_start=block_start,
        race_date=race,
        settings=new_settings,
    )
    week_dates = week_starts_in_block(block_start, race)
    weeks_out = []
    for ws, old_spec, new_spec in zip(week_dates, old_series, new_series):
        if ws < current_ws:
            continue
        before = round(float(old_spec["target_tss"]), 1)
        after = round(float(new_spec["target_tss"]), 1)
        weeks_out.append(
            {
                "week_start": ws.isoformat(),
                "before_target_tss": before,
                "after_target_tss": after,
                "changes": before != after,
            }
        )
    return {
        "allowed": True,
        "weeks": weeks_out,
        "old_peak": old_peak,
        "new_peak": new_peak,
    }


def test_ramp_change_shifts_only_current_and_future_weeks():
    today = date(2026, 1, 6)  # Tuesday early in block → future build weeks remain
    old = {**REVAMP_PLAN_DEFAULTS, "ramp_pct": 0.05}
    new = {**REVAMP_PLAN_DEFAULTS, "ramp_pct": 0.07}
    out = _preview_pure(old, new, today=today)
    assert out["allowed"]
    changed = [w for w in out["weeks"] if w["changes"]]
    assert changed, "future weeks should shift when ramp changes"
    for w in out["weeks"]:
        if date.fromisoformat(w["week_start"]) < today - timedelta(days=today.weekday()):
            pytest.fail("preview must not include past weeks")


def test_invalid_layout_raises_named_error():
    race = date(2026, 6, 1)
    block_start = race - timedelta(weeks=3)
    with pytest.raises(LoadPlanLayoutError, match="phase layout"):
        validate_block_layout(
            chronic_baseline=150.0,
            block_start=block_start,
            race_date=race,
            settings={**REVAMP_PLAN_DEFAULTS, "build_weeks": 8},
        )


def test_peak_tss_override_changes_peak_hold_targets():
    chronic = 100.0
    _, base_series = compute_revamp_block_series(chronic_baseline=chronic, settings=REVAMP_PLAN_DEFAULTS)
    _, override_series = compute_revamp_block_series(
        chronic_baseline=chronic,
        settings={**REVAMP_PLAN_DEFAULTS, "peak_tss": 400.0},
    )
    base_peak = next(w for w in base_series if w["phase"] == "peak_hold")["target_tss"]
    over_peak = next(w for w in override_series if w["phase"] == "peak_hold")["target_tss"]
    assert over_peak == pytest.approx(400.0, rel=1e-3)
    assert over_peak != pytest.approx(base_peak, rel=1e-2)


def test_preview_settings_change_no_race_returns_blocked():
    import uuid
    from unittest.mock import patch

    uid = uuid.uuid4()
    with patch("backend.services.revamp_plan_settings.plan_context", return_value=None):
        with patch("backend.services.revamp_plan_settings.get_row", return_value=None):
            out = preview_settings_change(_Sess(), uid, {"ramp_pct": 0.06})
    assert not out["allowed"]