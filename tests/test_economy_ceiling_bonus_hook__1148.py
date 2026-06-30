"""Tests for wiring economy ceiling bonus into projected_ctl_to_score_ceiling (issue #1148).

AC coverage:
  AC1 — P8 hook calls compute_ceiling_bonus (not load-only stub) when stimulus data is supplied
  AC2 — When non-zero economy bonus exists, projected ceiling increases by the correct bonus amount
  AC3 — When no stimulus data is supplied, output is identical to previous load-only stub output
  AC4 — py_compile reports no errors on all modified files
  AC5 — No existing passing tests are broken (structural; enforced by running the full suite)
"""

import py_compile
from datetime import date, timedelta

from backend.services.ceiling_bonus import compute_ceiling_bonus, LAG_PEAK_DAYS
from backend.services.score_ceiling import (
    SCORE_CEILING_MAX,
    projected_ctl_to_score_ceiling,
)

REF_DATE = date(2026, 1, 1)


# ── AC1: P8 hook calls compute_ceiling_bonus ─────────────────────────────────

def test_stimulus_history_activates_bonus():
    """Non-empty stimulus history at peak lag produces a ceiling higher than load-only."""
    history = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 10.0)]
    base = projected_ctl_to_score_ceiling(60.0)
    boosted = projected_ctl_to_score_ceiling(60.0, stimulus_history=history, reference_date=REF_DATE)
    assert boosted["endurance_ceiling"] > base["endurance_ceiling"]


def test_speed_ceiling_also_increases_with_bonus():
    """Speed ceiling rises alongside endurance ceiling when bonus is applied."""
    history = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 10.0)]
    base = projected_ctl_to_score_ceiling(60.0)
    boosted = projected_ctl_to_score_ceiling(60.0, stimulus_history=history, reference_date=REF_DATE)
    assert boosted["speed_ceiling"] > base["speed_ceiling"]


# ── AC2: ceiling increases by the correct bonus amount ───────────────────────

def test_endurance_ceiling_increases_by_exact_bonus():
    """Endurance ceiling equals base ceiling + compute_ceiling_bonus output."""
    ctl = 60.0
    history = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 10.0)]

    base = projected_ctl_to_score_ceiling(ctl)
    boosted = projected_ctl_to_score_ceiling(ctl, stimulus_history=history, reference_date=REF_DATE)
    expected_bonus = compute_ceiling_bonus(history, REF_DATE)

    expected_ceiling = min(SCORE_CEILING_MAX, round(base["endurance_ceiling"] + expected_bonus, 2))
    assert boosted["endurance_ceiling"] == expected_ceiling


def test_speed_ceiling_increases_by_exact_bonus():
    """Speed ceiling equals base ceiling + compute_ceiling_bonus output."""
    ctl = 60.0
    history = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 10.0)]

    base = projected_ctl_to_score_ceiling(ctl)
    boosted = projected_ctl_to_score_ceiling(ctl, stimulus_history=history, reference_date=REF_DATE)
    expected_bonus = compute_ceiling_bonus(history, REF_DATE)

    expected_ceiling = min(SCORE_CEILING_MAX, round(base["speed_ceiling"] + expected_bonus, 2))
    assert boosted["speed_ceiling"] == expected_ceiling


def test_zero_bonus_no_change():
    """Zero-valued stimulus produces no change to the ceiling."""
    ctl = 60.0
    history = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 0.0)]

    base = projected_ctl_to_score_ceiling(ctl)
    with_zero_bonus = projected_ctl_to_score_ceiling(ctl, stimulus_history=history, reference_date=REF_DATE)
    assert with_zero_bonus["endurance_ceiling"] == base["endurance_ceiling"]
    assert with_zero_bonus["speed_ceiling"] == base["speed_ceiling"]


def test_bonus_capped_at_score_ceiling_max():
    """Ceiling never exceeds SCORE_CEILING_MAX even when bonus is very large."""
    ctl = 145.0  # near the 150 reference → base ceiling near 96.67
    history = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 1000.0)]  # huge stimulus

    result = projected_ctl_to_score_ceiling(ctl, stimulus_history=history, reference_date=REF_DATE)
    assert result["endurance_ceiling"] <= SCORE_CEILING_MAX
    assert result["speed_ceiling"] <= SCORE_CEILING_MAX


def test_different_stimulus_magnitudes_give_proportional_bonus_increase():
    """Doubling stimulus doubles the bonus, which should double the ceiling increase."""
    ctl = 40.0
    history_1x = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 5.0)]
    history_2x = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 10.0)]

    base = projected_ctl_to_score_ceiling(ctl)
    result_1x = projected_ctl_to_score_ceiling(ctl, stimulus_history=history_1x, reference_date=REF_DATE)
    result_2x = projected_ctl_to_score_ceiling(ctl, stimulus_history=history_2x, reference_date=REF_DATE)

    delta_1x = result_1x["endurance_ceiling"] - base["endurance_ceiling"]
    delta_2x = result_2x["endurance_ceiling"] - base["endurance_ceiling"]

    assert delta_1x > 0
    assert abs(delta_2x - 2 * delta_1x) < 0.01  # proportional within rounding


# ── AC3: no data → load-only output (backward compatibility) ─────────────────

def test_no_stimulus_args_gives_load_only_output():
    """Calling without stimulus_history/reference_date matches load-only stub output."""
    ctl = 60.0
    baseline = projected_ctl_to_score_ceiling(ctl)
    without_data = projected_ctl_to_score_ceiling(ctl, stimulus_history=None, reference_date=None)
    assert without_data == baseline


def test_empty_stimulus_history_gives_load_only_output():
    """Empty stimulus_history list gives the same output as the load-only baseline."""
    ctl = 60.0
    baseline = projected_ctl_to_score_ceiling(ctl)
    with_empty = projected_ctl_to_score_ceiling(ctl, stimulus_history=[], reference_date=REF_DATE)
    assert with_empty == baseline


def test_stimulus_history_only_no_ref_date_gives_load_only():
    """stimulus_history without reference_date → no bonus computed (load-only output)."""
    ctl = 60.0
    history = [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), 10.0)]
    baseline = projected_ctl_to_score_ceiling(ctl)
    result = projected_ctl_to_score_ceiling(ctl, stimulus_history=history, reference_date=None)
    assert result == baseline


def test_ref_date_only_no_stimulus_gives_load_only():
    """reference_date without stimulus_history → no bonus computed (load-only output)."""
    ctl = 60.0
    baseline = projected_ctl_to_score_ceiling(ctl)
    result = projected_ctl_to_score_ceiling(ctl, stimulus_history=None, reference_date=REF_DATE)
    assert result == baseline


def test_future_sessions_give_load_only_output():
    """Sessions after reference_date contribute no bonus; output matches load-only."""
    ctl = 60.0
    future_history = [(REF_DATE + timedelta(days=1), 100.0) for _ in range(10)]
    baseline = projected_ctl_to_score_ceiling(ctl)
    result = projected_ctl_to_score_ceiling(ctl, stimulus_history=future_history, reference_date=REF_DATE)
    assert result == baseline


def test_backward_compat_economy_kwarg_still_noop():
    """economy kwarg remains a noop — backward-compat tests from AC3 of #1106 still hold."""
    without_economy = projected_ctl_to_score_ceiling(ctl=40)
    with_economy = projected_ctl_to_score_ceiling(ctl=40, economy=0.85)
    assert with_economy["endurance_ceiling"] == without_economy["endurance_ceiling"]
    assert with_economy["speed_ceiling"] == without_economy["speed_ceiling"]


def test_various_ctl_values_match_load_only_without_stimulus():
    """Without stimulus data, output across various CTL values matches load-only stub."""
    for ctl in [0, 10, 40, 70, 100, 150, 200]:
        baseline = projected_ctl_to_score_ceiling(ctl)
        result = projected_ctl_to_score_ceiling(ctl, stimulus_history=None, reference_date=None)
        assert result == baseline, f"Mismatch at CTL={ctl}"


# ── AC4: py_compile ──────────────────────────────────────────────────────────

def test_py_compile_score_ceiling():
    import backend.services.score_ceiling as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


def test_py_compile_ceiling_bonus():
    import backend.services.ceiling_bonus as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)
