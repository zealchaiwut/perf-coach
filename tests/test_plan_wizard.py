"""Plan setup wizard: fit_phases, draft preview, rest-day check."""
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.plan_rules_engine import typical_week_check
from backend.services.revamp_load_plan import (
    LoadPlanLayoutError,
    MIN_BLOCK_WEEKS,
    compute_revamp_block_series,
    pre_race_week_count,
)
from backend.services.revamp_plan_settings import fit_phases, preview_settings_change

REPO = Path(__file__).resolve().parents[1]
PLAN_JS = (REPO / "frontend" / "js" / "v2-training-plan.js").read_text(encoding="utf-8")
WIZ_JS = (REPO / "frontend" / "js" / "v2-plan-wizard.js").read_text(encoding="utf-8")
SETTINGS_JS = (REPO / "frontend" / "js" / "v2-settings-plan.js").read_text(encoding="utf-8")
PERF_JS = (REPO / "frontend" / "js" / "v2-performance.js").read_text(encoding="utf-8")
CSS = (REPO / "frontend" / "css" / "revamp.css").read_text(encoding="utf-8")
PLAN_HTML = (REPO / "frontend" / "pages" / "v2-training-plan.html").read_text(encoding="utf-8")


def _sum_phases(out: dict) -> int:
    return out["build_weeks"] + out["peak_hold_weeks"] + out["taper_weeks"] + out["race_week"]


@pytest.mark.parametrize("weeks", [6, 8, 13, 20])
@pytest.mark.parametrize("shape", ["standard", "short"])
def test_fit_phases_sums_to_available(weeks, shape):
    out = fit_phases(weeks, shape, taper_weeks=2)
    assert _sum_phases(out) == weeks
    assert out["build_weeks"] >= 3
    if shape == "short":
        assert out["peak_hold_weeks"] == 0
    if weeks >= 8 and shape == "standard":
        assert out["peak_hold_weeks"] == 2
        assert out["taper_weeks"] == 2


def test_fit_phases_standard_6_reduces_peak_hold():
    out = fit_phases(6, "standard", taper_weeks=2)
    assert out["peak_hold_weeks"] == 0
    assert out["build_weeks"] == 3
    assert _sum_phases(out) == 6


def test_fit_phases_custom_mismatch():
    with pytest.raises(LoadPlanLayoutError, match="sum to"):
        fit_phases(
            13,
            "custom",
            taper_weeks=2,
            overrides={"build_weeks": 5, "peak_hold_weeks": 2, "taper_weeks": 2},
        )


def test_fit_phases_below_min_block():
    with pytest.raises(LoadPlanLayoutError, match="at least"):
        fit_phases(MIN_BLOCK_WEEKS - 1, "standard")


def test_peak_by_ramp_matches_saved_plan_math():
    chronic = 334.0
    fitted = fit_phases(13, "standard", taper_weeks=2)
    settings = {
        "ramp_pct": 0.05,
        "build_weeks": fitted["build_weeks"],
        "peak_hold_weeks": fitted["peak_hold_weeks"],
        "taper_factors": fitted["taper_factors"],
        "race_week_factor": 0.40,
        "recover_weeks": 1,
        "rebuild_weeks": 4,
    }
    peak, series = compute_revamp_block_series(chronic_baseline=chronic, settings=settings)
    expected = round(chronic * (1.05 ** fitted["build_weeks"]), 1)
    assert peak == pytest.approx(expected, rel=1e-3)
    hold = next(w for w in series if w["phase"] == "peak_hold")
    assert hold["target_tss"] == pytest.approx(expected, rel=1e-3)

    draft_preview_peaks = {}
    for pct in (3, 5, 7):
        ramp = pct / 100.0
        p, _ = compute_revamp_block_series(
            chronic_baseline=chronic,
            settings={**settings, "ramp_pct": ramp, "peak_tss": None},
        )
        draft_preview_peaks[str(pct)] = p
    from backend.services.revamp_plan_settings import _peak_by_ramp

    assert _peak_by_ramp(chronic, fitted["build_weeks"]) == draft_preview_peaks


def test_preview_draft_with_no_saved_row():
    uid = "00000000-0000-0000-0000-000000000099"
    start = date(2026, 11, 30)
    race = date(2027, 2, 28)
    fitted = fit_phases(13, "standard", taper_weeks=2)
    draft = {
        "race_date": race.isoformat(),
        "distance_km": 42.195,
        "block_start": start.isoformat(),
        "shape": "standard",
        "weeks_available": 13,
        "taper_weeks": 2,
        "ramp_pct": 0.05,
        "build_weeks": fitted["build_weeks"],
        "peak_hold_weeks": fitted["peak_hold_weeks"],
        "taper_factors": fitted["taper_factors"],
        "rest_days": [0, 4],
        "max_consecutive_days": 3,
    }
    sess = MagicMock()
    with patch("backend.services.revamp_plan_settings.plan_context", return_value=None), \
         patch("backend.services.revamp_plan_settings.get_row", return_value=None), \
         patch("backend.services.revamp_plan_settings.chronic_weekly_tss", return_value=334.0), \
         patch("backend.services.revamp_plan_settings._prefs_rest_days", return_value=[0, 4]):
        out = preview_settings_change(sess, uid, draft, today=date(2026, 11, 24))
    assert out["allowed"] is True
    assert len(out["weeks"]) == 13
    assert {w["phase"] for w in out["weeks"]} <= {"build", "peak_hold", "taper", "race_week"}
    assert "ceiling_tss" in out["weeks"][0]
    assert "over_ceiling" in out["weeks"][0]
    assert "3" in out["peak_by_ramp"] and "5" in out["peak_by_ramp"] and "7" in out["peak_by_ramp"]
    assert out["peak_by_ramp"]["5"] == pytest.approx(out["peak_tss"], rel=1e-3)
    assert pre_race_week_count({
        "build_weeks": fitted["build_weeks"],
        "peak_hold_weeks": fitted["peak_hold_weeks"],
        "taper_factors": fitted["taper_factors"],
    }) == 13


def test_typical_week_check_mon_fri_limit_3_then_2():
    ok = typical_week_check([0, 4], 3)
    assert ok["longest"] == 3
    assert ok["fits"] is True
    assert "Fits your limit" in ok["message"]
    bad = typical_week_check([0, 4], 2)
    assert bad["longest"] == 3
    assert bad["fits"] is False
    assert "Over your 2-day limit" in bad["message"]


def test_wizard_entry_points():
    assert "V2PlanWizard" in PLAN_JS or "v2-plan-wizard.js" in PLAN_HTML
    assert "/v2/training/plan?setup=1" in PERF_JS
    assert "v2-plan-wizard.js" in PLAN_HTML
    assert "comma-separated" not in SETTINGS_JS
    assert "ps-taper-custom" in SETTINGS_JS or "taper chips" in SETTINGS_JS.lower() or "chipb" in SETTINGS_JS or "rv-wiz-chip" in SETTINGS_JS


def test_wizard_markup_contracts():
    assert "rv-wiz" in WIZ_JS
    assert "role=\"dialog\"" in WIZ_JS or "role='dialog'" in WIZ_JS
    assert "Create plan" in WIZ_JS
    assert "/api/plan/revamp-settings/fit" in WIZ_JS
    assert "/api/plan/revamp-settings/week-check" in WIZ_JS
    assert "/api/races" in WIZ_JS
    assert "Escape" in WIZ_JS
    assert "rv-wiz" in CSS
    assert "@media (max-width: 600px)" in CSS
