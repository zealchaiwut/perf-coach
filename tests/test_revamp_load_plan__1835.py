"""Issue #1835 — revamp block load plan phases and snapshots."""

from datetime import date, timedelta

import pytest

from backend.services.revamp_load_plan import (
    REVAMP_PLAN_DEFAULTS,
    LoadPlanLayoutError,
    block_start_for_race,
    compute_revamp_block_series,
    validate_block_layout,
    week_starts_in_block,
    weeks_from_block_start_to_race,
)


def test_build_peak_taper_race_recover_rebuild_sequence():
    settings = {
        **REVAMP_PLAN_DEFAULTS,
        "build_weeks": 2,
        "peak_hold_weeks": 1,
        "taper_factors": [0.75],
        "recover_weeks": 1,
        "rebuild_weeks": 2,
    }
    peak, weeks = compute_revamp_block_series(chronic_baseline=100.0, settings=settings)
    assert peak == pytest.approx(100 * 1.05**2, rel=1e-3)
    phases = [w["phase"] for w in weeks]
    assert phases == ["build", "build", "peak_hold", "taper", "race_week", "recover", "rebuild", "rebuild"]
    assert weeks[0]["target_tss"] == pytest.approx(105.0, rel=1e-3)
    assert weeks[2]["target_tss"] == pytest.approx(peak, rel=1e-3)
    assert weeks[3]["target_tss"] == pytest.approx(peak * 0.75, rel=1e-3)
    assert weeks[4]["target_tss"] == pytest.approx(peak * 0.40, rel=1e-3)


def test_validate_raises_when_layout_too_short():
    race = date(2026, 6, 1)  # Monday
    block_start = race - timedelta(weeks=3)
    with pytest.raises(LoadPlanLayoutError):
        validate_block_layout(
            chronic_baseline=200.0,
            block_start=block_start,
            race_date=race,
            settings={**REVAMP_PLAN_DEFAULTS, "build_weeks": 8},
        )


def test_block_start_fits_race():
    race = date(2026, 8, 10)
    bs = block_start_for_race(race, REVAMP_PLAN_DEFAULTS)
    need = weeks_from_block_start_to_race(bs, race)
    _peak, series = validate_block_layout(
        chronic_baseline=250.0,
        block_start=bs,
        race_date=race,
        settings=REVAMP_PLAN_DEFAULTS,
    )
    assert len(series) == need
    assert len(week_starts_in_block(bs, race)) == need