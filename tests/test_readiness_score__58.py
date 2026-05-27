"""
Unit tests for issue #58: Compute and store daily readiness score (0-100).

Tests cover:
  - Normal inputs produce a score in [0, 100]
  - Fewer than HRV_MIN_DAYS baseline days (graceful degradation)
  - All-null optional fields return None
  - Boundary scores: 0 and 100
  - Determinism: same inputs always produce the same result
  - Component contributions sum to the final score
"""
import math
import pytest

from services.readiness.calculator import (
    HRV_MIN_DAYS,
    HRV_WINDOW,
    RHR_MIN_DAYS,
    RHR_WINDOW,
    W_ENERGY,
    W_HRV,
    W_RHR,
    W_SLEEP,
    compute_readiness,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hrv_baseline(n: int = HRV_WINDOW, value: float = 60.0) -> list[float]:
    return [value] * n


def _rhr_baseline(n: int = RHR_WINDOW, value: float = 55.0) -> list[float]:
    return [value] * n


def _components_sum(result) -> float:
    c = result.components
    vals = [
        c.hrv_contribution or 0.0,
        c.rhr_contribution or 0.0,
        c.sleep_contribution or 0.0,
        c.energy_contribution or 0.0,
    ]
    return sum(vals)


# ── AC: normal inputs → score in [0, 100] ─────────────────────────────────────

def test_normal_inputs_score_in_range():
    result = compute_readiness(
        hrv=65.0,
        resting_hr=52.0,
        sleep_quality=4.0,
        energy=4.0,
        hrv_baseline=_hrv_baseline(HRV_WINDOW, 60.0),
        rhr_baseline=_rhr_baseline(RHR_WINDOW, 55.0),
    )
    assert result is not None
    assert 0.0 <= result.score <= 100.0


def test_normal_inputs_components_are_not_none():
    result = compute_readiness(
        hrv=60.0,
        resting_hr=55.0,
        sleep_quality=3.0,
        energy=3.0,
        hrv_baseline=_hrv_baseline(HRV_WINDOW, 60.0),
        rhr_baseline=_rhr_baseline(RHR_WINDOW, 55.0),
    )
    assert result is not None
    c = result.components
    assert c.hrv_contribution is not None
    assert c.rhr_contribution is not None
    assert c.sleep_contribution is not None
    assert c.energy_contribution is not None


def test_components_sum_equals_score():
    result = compute_readiness(
        hrv=65.0,
        resting_hr=52.0,
        sleep_quality=4.0,
        energy=4.0,
        hrv_baseline=_hrv_baseline(HRV_WINDOW, 60.0),
        rhr_baseline=_rhr_baseline(RHR_WINDOW, 55.0),
    )
    assert result is not None
    assert math.isclose(_components_sum(result), result.score, abs_tol=0.01)


# ── AC: fewer than HRV_MIN_DAYS baseline days (graceful degradation) ──────────

def test_insufficient_hrv_baseline_excludes_hrv_contribution():
    """With < HRV_MIN_DAYS history, HRV is excluded; other signals still score."""
    result = compute_readiness(
        hrv=60.0,
        resting_hr=55.0,
        sleep_quality=3.0,
        energy=3.0,
        hrv_baseline=_hrv_baseline(HRV_MIN_DAYS - 1, 60.0),
        rhr_baseline=_rhr_baseline(RHR_WINDOW, 55.0),
    )
    assert result is not None, "Score must be computable when only HRV baseline is missing"
    assert 0.0 <= result.score <= 100.0
    assert result.components.hrv_contribution == 0.0


def test_zero_hrv_baseline_days_still_scores():
    result = compute_readiness(
        hrv=60.0,
        resting_hr=55.0,
        sleep_quality=3.0,
        energy=3.0,
        hrv_baseline=[],
        rhr_baseline=_rhr_baseline(RHR_WINDOW, 55.0),
    )
    assert result is not None
    assert result.components.hrv_contribution == 0.0
    assert math.isclose(_components_sum(result), result.score, abs_tol=0.01)


def test_insufficient_rhr_baseline_excludes_rhr_contribution():
    result = compute_readiness(
        hrv=60.0,
        resting_hr=55.0,
        sleep_quality=3.0,
        energy=3.0,
        hrv_baseline=_hrv_baseline(HRV_WINDOW, 60.0),
        rhr_baseline=_rhr_baseline(RHR_MIN_DAYS - 1, 55.0),
    )
    assert result is not None
    assert result.components.rhr_contribution == 0.0


# ── AC: all-null optional fields → None ───────────────────────────────────────

def test_all_null_returns_none():
    result = compute_readiness(
        hrv=None,
        resting_hr=None,
        sleep_quality=None,
        energy=None,
        hrv_baseline=[],
        rhr_baseline=[],
    )
    assert result is None


def test_null_hrv_but_other_signals_scores():
    result = compute_readiness(
        hrv=None,
        resting_hr=55.0,
        sleep_quality=3.0,
        energy=3.0,
        hrv_baseline=_hrv_baseline(),
        rhr_baseline=_rhr_baseline(),
    )
    assert result is not None
    assert result.components.hrv_contribution == 0.0


def test_sleep_quality_only_scores():
    result = compute_readiness(
        hrv=None,
        resting_hr=None,
        sleep_quality=5.0,
        energy=None,
        hrv_baseline=[],
        rhr_baseline=[],
    )
    assert result is not None
    assert result.score == pytest.approx(100.0, abs=0.01)


# ── AC: boundary scores 0 and 100 ─────────────────────────────────────────────

def test_boundary_score_100():
    """All signals at absolute maximum → score = 100."""
    # HRV massively above baseline (z >> 2.5 → clamped at 100)
    hrv_bl = [60.0] * HRV_WINDOW   # mean=60, std≈0 (low CV), denom=max(1,0)=1
    # today hrv 111 → z = (111-60)/1 = 51 → clamped at 100
    result = compute_readiness(
        hrv=111.0,
        resting_hr=1.0,            # far below any baseline → rhr_score=100
        sleep_quality=5.0,
        energy=5.0,
        hrv_baseline=hrv_bl,
        rhr_baseline=[55.0] * RHR_WINDOW,
    )
    assert result is not None
    assert result.score == pytest.approx(100.0, abs=0.01)


def test_boundary_score_0():
    """All signals at absolute minimum → score = 0."""
    hrv_bl = [60.0] * HRV_WINDOW
    # today hrv = 9 → z = (9-60)/1 = -51 → clamped at 0
    result = compute_readiness(
        hrv=9.0,
        resting_hr=200.0,          # far above baseline → rhr_score=0
        sleep_quality=1.0,
        energy=1.0,
        hrv_baseline=hrv_bl,
        rhr_baseline=[55.0] * RHR_WINDOW,
    )
    assert result is not None
    assert result.score == pytest.approx(0.0, abs=0.01)


# ── AC: determinism — same inputs always produce the same result ──────────────

def test_determinism():
    kwargs = dict(
        hrv=62.0,
        resting_hr=54.0,
        sleep_quality=4.0,
        energy=3.0,
        hrv_baseline=_hrv_baseline(HRV_WINDOW, 60.0),
        rhr_baseline=_rhr_baseline(RHR_WINDOW, 55.0),
    )
    r1 = compute_readiness(**kwargs)
    r2 = compute_readiness(**kwargs)
    assert r1 is not None and r2 is not None
    assert r1.score == r2.score
    assert r1.components.hrv_contribution == r2.components.hrv_contribution
    assert r1.components.rhr_contribution == r2.components.rhr_contribution
    assert r1.components.sleep_contribution == r2.components.sleep_contribution
    assert r1.components.energy_contribution == r2.components.energy_contribution


# ── AC: weight redistribution is proportional ─────────────────────────────────

def test_weight_redistribution_when_hrv_missing():
    """When HRV is excluded, remaining weights are renormalised to sum to 1."""
    result = compute_readiness(
        hrv=None,              # excluded
        resting_hr=55.0,
        sleep_quality=3.0,
        energy=3.0,
        hrv_baseline=[],
        rhr_baseline=_rhr_baseline(),
    )
    assert result is not None
    # With HRV excluded, available weights = W_RHR + W_SLEEP + W_ENERGY
    # Each signal's contribution = (w_i / total_w) * raw_i
    # sum of contributions must equal score
    assert math.isclose(_components_sum(result), result.score, abs_tol=0.01)


def test_weights_sum_to_one():
    """Confirm package-level weight constants sum to 1.0."""
    assert math.isclose(W_HRV + W_RHR + W_SLEEP + W_ENERGY, 1.0, rel_tol=1e-9)


# ── AC: HRV exactly at baseline → neutral score of 50 for that component ──────

def test_hrv_at_baseline_contributes_neutral():
    """HRV exactly equal to baseline mean → HRV component = 50, no penalty or bonus."""
    baseline = [60.0, 55.0, 65.0, 58.0, 62.0, 59.0, 63.0]
    mean = sum(baseline) / len(baseline)
    result = compute_readiness(
        hrv=mean,
        resting_hr=None,
        sleep_quality=None,
        energy=None,
        hrv_baseline=baseline,
        rhr_baseline=[],
    )
    assert result is not None
    # Only HRV available, weight = 1.0 after redistribution; raw score = 50
    assert result.score == pytest.approx(50.0, abs=1.0)
