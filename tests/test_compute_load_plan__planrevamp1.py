"""Unit tests for compute_load_plan (Plan tab revamp, Part 1; ceiling/deload
revised 2026-07-09).

Covers the AC items from the spec's section 1.4:
  AC1 - ramp_weeks + hold_weeks + taper_weeks == weeks_to_race (non-clamped case)
  AC2 - exactly hold_weeks weeks equal peak
  AC3 - every ramp week is strictly less than peak
  AC4 - the ACWR ceiling clamp binds when ramp_rate is large, and MOVES with
        the plan's own trailing 4-week window instead of staying static
  AC5 - hold_weeks + taper_weeks >= weeks_to_race clamps ramp_weeks to 0 and warns
  AC6 - no SQL/file/network access (pure function)
  AC7 - the final taper week is phase "race", not "taper"
  AC8 - taper fractions interpolate correctly when taper_weeks != len(TAPER_CURVE)
  AC9 - deload_enabled cuts every 4th ramp/hold week by 30%, and the FOLLOWING
        week resumes from the pre-cut trajectory (no ramp reset)
"""

import inspect

from backend.services.load_plan import (
    compute_load_plan, TAPER_CURVE, ACWR_CEILING_MULT, DELOAD_CUT_FRACTION,
)


# ── AC1/AC2/AC3: the worked example from the spec ──────────────────────────

def test_worked_example_matches_spec():
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    assert result["ramp_weeks"] == 12
    assert result["hold_weeks"] == 4
    assert result["taper_weeks"] == 3
    assert result["build_weeks"] == 16
    assert result["warning"] is None
    # peak = 316 * 1.05**13
    assert abs(result["peak"] - 595.9) < 0.5

    weeks = result["weeks"]
    assert len(weeks) == 19


def test_ramp_hold_taper_weeks_sum_to_weeks_to_race():
    result = compute_load_plan(
        baseline=300, ramp_rate=0.04, hold_weeks=3, taper_weeks=2, weeks_to_race=14,
    )
    total = result["ramp_weeks"] + result["hold_weeks"] + result["taper_weeks"]
    assert total == 14


def test_exactly_hold_weeks_weeks_equal_peak():
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    hold_bars = [w for w in result["weeks"] if w["phase"] == "hold"]
    assert len(hold_bars) == 4
    for w in hold_bars:
        assert abs(w["target_tss"] - result["peak"]) < 0.01


def test_every_ramp_week_strictly_less_than_peak():
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    ramp_bars = [w for w in result["weeks"] if w["phase"] == "ramp"]
    assert len(ramp_bars) == 12
    for w in ramp_bars:
        assert w["target_tss"] < result["peak"]


def test_ramp_is_monotonically_increasing():
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    ramp_values = [w["target_tss"] for w in result["weeks"] if w["phase"] == "ramp"]
    assert ramp_values == sorted(ramp_values)
    assert len(set(ramp_values)) == len(ramp_values)  # strictly increasing, no ties


# ── AC7: final taper week is "race" phase ───────────────────────────────────

def test_final_taper_week_is_race_phase():
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    taper_and_race = [w for w in result["weeks"] if w["phase"] in ("taper", "race")]
    assert len(taper_and_race) == 3
    assert taper_and_race[-1]["phase"] == "race"
    assert [w["phase"] for w in taper_and_race[:-1]] == ["taper"] * 2
    # race week's fraction is the last (deepest) TAPER_CURVE entry
    assert abs(taper_and_race[-1]["target_tss"] - result["peak"] * TAPER_CURVE[-1]) < 0.5


def test_taper_values_use_documented_curve():
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    taper_bars = [w for w in result["weeks"] if w["phase"] in ("taper", "race")]
    for w, frac in zip(taper_bars, TAPER_CURVE):
        assert abs(w["target_tss"] - result["peak"] * frac) < 0.5


# ── AC8: taper interpolation for non-default taper_weeks ───────────────────

def test_taper_interpolation_single_week():
    result = compute_load_plan(
        baseline=300, ramp_rate=0.05, hold_weeks=4, taper_weeks=1, weeks_to_race=10,
    )
    taper_bars = [w for w in result["weeks"] if w["phase"] in ("taper", "race")]
    assert len(taper_bars) == 1
    assert taper_bars[0]["phase"] == "race"
    # single-week taper uses the deepest (last) curve value
    assert abs(taper_bars[0]["target_tss"] - result["peak"] * TAPER_CURVE[-1]) < 0.5


def test_taper_interpolation_longer_than_curve():
    result = compute_load_plan(
        baseline=300, ramp_rate=0.05, hold_weeks=4, taper_weeks=5, weeks_to_race=15,
    )
    taper_bars = [w for w in result["weeks"] if w["phase"] in ("taper", "race")]
    assert len(taper_bars) == 5
    values = [w["target_tss"] for w in taper_bars]
    # monotonically non-increasing as it tapers down
    assert values == sorted(values, reverse=True)
    assert taper_bars[-1]["phase"] == "race"


# ── AC4: ACWR ceiling clamp — MOVING with the plan's own trailing window ────

def test_acwr_ceiling_clamps_large_ramp():
    # Week 1's ceiling is still the static trailing_avg-seeded value (the
    # rolling window hasn't moved yet) — the very first clamped week must
    # equal exactly that.
    trailing_avg = 200.0
    week1_ceiling = ACWR_CEILING_MULT * trailing_avg
    result = compute_load_plan(
        baseline=200, ramp_rate=0.5, hold_weeks=2, taper_weeks=2, weeks_to_race=10,
        trailing_28d_avg=trailing_avg,
    )
    clamped_weeks = [w for w in result["weeks"] if w["clamped"]]
    assert clamped_weeks, "expected at least one clamped week with a large ramp rate"
    assert abs(clamped_weeks[0]["target_tss"] - week1_ceiling) < 0.01


def test_ceiling_moves_up_across_clamped_weeks_instead_of_flatlining():
    # The bug being fixed: a static ceiling clamps every week after the first
    # to the SAME number, flatlining the chart. The moving ceiling must let
    # later clamped weeks land HIGHER than the first, since the plan's own
    # trailing window keeps rising.
    result = compute_load_plan(
        baseline=200, ramp_rate=0.5, hold_weeks=2, taper_weeks=2, weeks_to_race=10,
        trailing_28d_avg=200.0,
    )
    clamped_values = [w["target_tss"] for w in result["weeks"] if w["clamped"]]
    assert len(clamped_values) >= 2, "need at least 2 clamped weeks to test movement"
    assert len(set(clamped_values)) > 1, "clamped weeks must not all be pinned to one static value"
    assert clamped_values == sorted(clamped_values), "ceiling must rise monotonically, not flatline"


def test_each_week_exposes_its_own_moving_ceiling():
    result = compute_load_plan(
        baseline=200, ramp_rate=0.5, hold_weeks=2, taper_weeks=2, weeks_to_race=10,
        trailing_28d_avg=200.0,
    )
    ceilings = [w["ceiling"] for w in result["weeks"]]
    assert all(c is not None for c in ceilings)
    # Non-decreasing while the ramp is uncut and outpacing the window.
    assert ceilings == sorted(ceilings)


def test_no_ceiling_when_trailing_avg_missing():
    result = compute_load_plan(
        baseline=200, ramp_rate=0.5, hold_weeks=2, taper_weeks=2, weeks_to_race=10,
        trailing_28d_avg=None,
    )
    assert all(not w["clamped"] for w in result["weeks"])
    assert all(w["ceiling"] is None for w in result["weeks"])


def test_no_ceiling_when_trailing_avg_zero():
    result = compute_load_plan(
        baseline=200, ramp_rate=0.5, hold_weeks=2, taper_weeks=2, weeks_to_race=10,
        trailing_28d_avg=0,
    )
    assert all(not w["clamped"] for w in result["weeks"])


def test_target_never_exceeds_its_own_weeks_ceiling():
    result = compute_load_plan(
        baseline=200, ramp_rate=0.3, hold_weeks=3, taper_weeks=3, weeks_to_race=16,
        trailing_28d_avg=250,
    )
    for w in result["weeks"]:
        assert w["ceiling"] is not None
        assert w["target_tss"] <= w["ceiling"] + 0.01


def test_ramp_eventually_escapes_the_ceiling_instead_of_flatlining_forever():
    # A large but not extreme ramp: clamped for the first few weeks, then the
    # moving window catches up and the ramp resumes climbing on its own —
    # never permanently pinned like the old static-ceiling behaviour was.
    # ramp_rate=0.10 (not 0.05): since the baseline cap (BASELINE_CAP_MULT=
    # 1.15) already seeds the ramp within the ceiling's own 1.3x band, a 5%
    # ramp off a capped baseline no longer breaches the ceiling at all — this
    # test needs a steeper ramp to still exercise early clamping.
    result = compute_load_plan(
        baseline=316, ramp_rate=0.10, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
        trailing_28d_avg=200.0,
    )
    weeks = result["weeks"]
    assert any(w["clamped"] for w in weeks), "expected some early clamping"
    assert any(not w["clamped"] for w in weeks[5:]), "ramp must escape the ceiling later in the series"


# ── AC9: deload ("cut 30% every 4th week") ───────────────────────────────────

def test_deload_disabled_by_default():
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    assert all(not w["deload"] for w in result["weeks"])


def test_deload_cuts_every_4th_ramp_week_by_30_percent_but_never_hold():
    # ramp_weeks = build_weeks(16) - hold_weeks(4) = 12, so weeks 4/8/12 are
    # ramp and week 16 is the LAST hold week — exactly the case that used to
    # wrongly deload the final peak-hold week right before taper.
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
        deload_enabled=True,
    )
    by_index = {w["week_index"]: w for w in result["weeks"]}
    for idx in (4, 8, 12):
        w = by_index[idx]
        assert w["deload"] is True
        assert w["phase"] == "ramp"

    # Hold weeks (13-16) are NEVER deloaded, even when week_index % 4 == 0 —
    # taper immediately follows and already IS the recovery reduction.
    non_deload_uncut = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    uncut_by_index = {w["week_index"]: w for w in non_deload_uncut["weeks"]}
    for idx in (13, 14, 15, 16):
        assert by_index[idx]["deload"] is False
        assert by_index[idx]["phase"] == "hold"
        assert by_index[idx]["target_tss"] == uncut_by_index[idx]["target_tss"]

    for idx in (4, 8, 12):
        expected = uncut_by_index[idx]["target_tss"] * (1 - DELOAD_CUT_FRACTION)
        assert abs(by_index[idx]["target_tss"] - expected) < 0.5


def test_deload_never_applied_in_taper_or_race_phase():
    # A short plan where 4/8/12 would land in taper/race if not excluded.
    result = compute_load_plan(
        baseline=300, ramp_rate=0.05, hold_weeks=1, taper_weeks=6, weeks_to_race=12,
        deload_enabled=True,
    )
    for w in result["weeks"]:
        if w["phase"] in ("taper", "race"):
            assert w["deload"] is False


def test_deload_week_resumes_next_week_from_pre_cut_trajectory():
    # The core "return to before cut" requirement: week 5 (right after the
    # week-4 deload) must match the UNCUT ramp trajectory, not compound off
    # week 4's reduced value.
    with_deload = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
        deload_enabled=True,
    )
    without_deload = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    w4_deload = next(w for w in with_deload["weeks"] if w["week_index"] == 4)
    w5_deload = next(w for w in with_deload["weeks"] if w["week_index"] == 5)
    w4_plain = next(w for w in without_deload["weeks"] if w["week_index"] == 4)
    w5_plain = next(w for w in without_deload["weeks"] if w["week_index"] == 5)

    assert w4_deload["target_tss"] < w4_plain["target_tss"]  # week 4 IS cut
    assert abs(w5_deload["target_tss"] - w5_plain["target_tss"]) < 0.5  # week 5 is NOT reduced by the cut


def test_deload_start_week_shifts_the_cycle():
    # start 2 → deloads land on ramp weeks 2, 6, 10 — and NOT on 4, 8, 12.
    result = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
        deload_enabled=True, deload_start_week=2,
    )
    by_index = {w["week_index"]: w for w in result["weeks"]}
    for idx in (2, 6, 10):
        assert by_index[idx]["deload"] is True, idx
        assert by_index[idx]["phase"] == "ramp"
    for idx in (4, 8, 12):
        assert by_index[idx]["deload"] is False, idx

    uncut = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
    )
    uncut_by_index = {w["week_index"]: w for w in uncut["weeks"]}
    for idx in (2, 6, 10):
        expected = uncut_by_index[idx]["target_tss"] * (1 - DELOAD_CUT_FRACTION)
        assert abs(by_index[idx]["target_tss"] - expected) < 0.5


def test_deload_start_week_default_matches_legacy_every_4th():
    # Omitting deload_start_week must be byte-identical to the pre-existing
    # "weeks 4, 8, 12" behaviour (default 4).
    legacy = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
        deload_enabled=True,
    )
    explicit = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
        deload_enabled=True, deload_start_week=4,
    )
    assert legacy["weeks"] == explicit["weeks"]


def test_deload_start_week_clamped_to_cycle_bounds():
    # Out-of-range values clamp to 1..4 rather than erroring or silently
    # producing a never-matching cycle.
    low = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
        deload_enabled=True, deload_start_week=0,
    )
    assert {w["week_index"] for w in low["weeks"] if w["deload"]} == {1, 5, 9}
    high = compute_load_plan(
        baseline=316, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=19,
        deload_enabled=True, deload_start_week=9,
    )
    assert {w["week_index"] for w in high["weeks"] if w["deload"]} == {4, 8, 12}


# ── AC5: hold + taper >= weeks_to_race clamps and warns ─────────────────────

def test_hold_plus_taper_exceeds_weeks_to_race_clamps_and_warns():
    result = compute_load_plan(
        baseline=300, ramp_rate=0.05, hold_weeks=10, taper_weeks=10, weeks_to_race=12,
    )
    assert result["ramp_weeks"] == 0
    assert result["warning"] is not None
    assert "ramp" in result["warning"].lower()
    assert result["peak"] == 300  # baseline, unramped
    no_ramp_bars = [w for w in result["weeks"] if w["phase"] == "ramp"]
    assert no_ramp_bars == []


def test_hold_plus_taper_exactly_equals_weeks_to_race_clamps():
    result = compute_load_plan(
        baseline=300, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=7,
    )
    assert result["ramp_weeks"] == 0
    assert result["warning"] is not None


def test_never_emits_negative_ramp_weeks():
    result = compute_load_plan(
        baseline=300, ramp_rate=0.05, hold_weeks=20, taper_weeks=20, weeks_to_race=5,
    )
    assert result["ramp_weeks"] >= 0


# ── AC6: pure function, no I/O ───────────────────────────────────────────────

def test_no_disallowed_imports_in_module():
    import backend.services.load_plan as mod
    source = inspect.getsource(mod)
    for banned in ("import sqlalchemy", "import requests", "open(", "Session(", "import os"):
        assert banned not in source, f"load_plan.py must stay pure — found {banned!r}"


def test_zero_weeks_to_race_returns_empty_series():
    result = compute_load_plan(
        baseline=300, ramp_rate=0.05, hold_weeks=4, taper_weeks=3, weeks_to_race=0,
    )
    assert result["weeks"] == []
