"""Unit tests for body-composition modifier with sign-flip logic (issue #1158).

AC coverage:
(a) small-deficit uplift: rate < 0.5% BW/week, EA above threshold → positive modifier
(b) above-threshold penalty: rate > 0.75% BW/week → negative modifier
(c) low-EA penalty: rate < 0.5% but EA proxy below threshold → negative modifier
(d) boundary value at exactly the threshold → near-zero modifier (transition point)
(e) continuous transition: no step discontinuities through the threshold region
(f) modifier bounded to [-15%, +5%]
(g) py_compile passes (tested by importing the module successfully)
"""
import math
import py_compile
import os


from backend.services.body_modifier import compute_body_modifier, RATE_THRESHOLD_LOW, RATE_THRESHOLD_HIGH


# ---------------------------------------------------------------------------
# (a) Small-deficit uplift
# ---------------------------------------------------------------------------

def test_small_deficit_produces_positive_modifier():
    """Rate < 0.5% BW/week with normal EA → positive modifier uplift (AC-a)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-0.3, ea_proxy=1.0)
    assert result["modifier"] > 0.0, (
        f"Expected positive modifier for small deficit, got {result['modifier']}"
    )


def test_small_deficit_modifier_within_uplift_range():
    """Small deficit modifier is in +1% to +5% range (AC-a, bounded)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-0.3, ea_proxy=1.0)
    assert 0.01 <= result["modifier"] <= 0.05, (
        f"Modifier {result['modifier']} outside expected +1–5% uplift range"
    )


def test_zero_rate_no_significant_penalty():
    """Zero rate (maintenance) with normal EA → modifier near zero or slightly positive."""
    result = compute_body_modifier(weekly_pct_bw_rate=0.0, ea_proxy=1.0)
    assert result["modifier"] >= 0.0, (
        f"Expected non-negative modifier at zero rate, got {result['modifier']}"
    )


# ---------------------------------------------------------------------------
# (b) Above-threshold penalty
# ---------------------------------------------------------------------------

def test_above_threshold_rate_produces_negative_modifier():
    """Rate > 0.75% BW/week → negative modifier penalty (AC-b)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-1.0, ea_proxy=1.0)
    assert result["modifier"] < 0.0, (
        f"Expected negative modifier for aggressive cut, got {result['modifier']}"
    )


def test_aggressive_cut_penalty_magnitude():
    """Aggressive cut (1.0% BW/week) with normal EA → meaningful penalty (AC-b)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-1.0, ea_proxy=1.0)
    assert result["modifier"] <= -0.03, (
        f"Expected penalty of at least -3% for aggressive cut, got {result['modifier']}"
    )


def test_very_aggressive_cut_penalty_bounded():
    """Very aggressive cut (2.0% BW/week) → modifier bounded to -15% floor (AC-f)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-2.0, ea_proxy=1.0)
    assert result["modifier"] >= -0.15, (
        f"Modifier {result['modifier']} exceeds -15% lower bound"
    )


# ---------------------------------------------------------------------------
# (c) Low-EA penalty
# ---------------------------------------------------------------------------

def test_low_ea_produces_negative_modifier_regardless_of_rate():
    """EA proxy below threshold flips to penalty even with small loss rate (AC-c)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-0.3, ea_proxy=0.0)
    assert result["modifier"] < 0.0, (
        f"Expected negative modifier for low EA, got {result['modifier']}"
    )


def test_low_ea_penalty_independent_of_small_rate():
    """Low EA penalty applies even at very small deficit (AC-c)."""
    result_low_ea = compute_body_modifier(weekly_pct_bw_rate=-0.1, ea_proxy=0.0)
    result_normal = compute_body_modifier(weekly_pct_bw_rate=-0.1, ea_proxy=1.0)
    assert result_low_ea["modifier"] < result_normal["modifier"], (
        "Low EA should produce lower (more penalising) modifier than normal EA"
    )


def test_low_ea_explicit_branch():
    """Moderate loss rate but EA below threshold → penalty (AC-c)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-0.4, ea_proxy=0.2)
    assert result["modifier"] < 0.0, (
        f"Expected penalty at low EA (0.2), got {result['modifier']}"
    )


# ---------------------------------------------------------------------------
# (d) Boundary value at exactly the threshold
# ---------------------------------------------------------------------------

def test_boundary_rate_modifier_near_zero():
    """Rate at exact threshold midpoint → modifier near zero (AC-d)."""
    # The transition midpoint is (RATE_THRESHOLD_LOW + RATE_THRESHOLD_HIGH) / 2
    mid = -(RATE_THRESHOLD_LOW + RATE_THRESHOLD_HIGH) / 2.0
    result = compute_body_modifier(weekly_pct_bw_rate=mid, ea_proxy=1.0)
    assert abs(result["modifier"]) < 0.04, (
        f"Modifier at transition midpoint {mid}% should be near zero, got {result['modifier']}"
    )


def test_boundary_low_rate_is_positive():
    """At exactly RATE_THRESHOLD_LOW (low threshold) → modifier is still positive (AC-d)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-RATE_THRESHOLD_LOW, ea_proxy=1.0)
    assert result["modifier"] >= 0.0, (
        f"Expected non-negative modifier at lower threshold boundary, got {result['modifier']}"
    )


def test_boundary_high_rate_is_negative():
    """At exactly RATE_THRESHOLD_HIGH (high threshold) → modifier is non-positive (AC-d)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-RATE_THRESHOLD_HIGH, ea_proxy=1.0)
    assert result["modifier"] <= 0.0, (
        f"Expected non-positive modifier at upper threshold boundary, got {result['modifier']}"
    )


# ---------------------------------------------------------------------------
# (e) Continuous transition — no step discontinuities
# ---------------------------------------------------------------------------

def test_continuous_transition_no_jumps():
    """Sweep loss rate from 0.0 to 1.5%; adjacent steps differ by < 2% (AC-e)."""
    rates = [-r / 100.0 for r in range(0, 155, 5)]  # 0.0, -0.05, -0.10, ..., -1.50
    modifiers = [compute_body_modifier(weekly_pct_bw_rate=r, ea_proxy=1.0)["modifier"] for r in rates]

    for i in range(1, len(modifiers)):
        diff = abs(modifiers[i] - modifiers[i - 1])
        assert diff < 0.02, (
            f"Step discontinuity detected at rate {rates[i]:.2f}%: "
            f"modifier jumped {diff:.4f} from {modifiers[i-1]:.4f} to {modifiers[i]:.4f}"
        )


def test_no_nan_in_transition():
    """No NaN values at any point in the threshold sweep (AC-e)."""
    rates = [-r / 1000.0 for r in range(0, 1501, 10)]
    for rate in rates:
        result = compute_body_modifier(weekly_pct_bw_rate=rate, ea_proxy=1.0)
        assert not math.isnan(result["modifier"]), (
            f"NaN modifier at rate={rate}"
        )


# ---------------------------------------------------------------------------
# (f) Modifier bounded to [-15%, +5%]
# ---------------------------------------------------------------------------

def test_modifier_never_exceeds_upper_bound():
    """Even with extreme weight gain, modifier stays at or below +5% (AC-f)."""
    result = compute_body_modifier(weekly_pct_bw_rate=3.0, ea_proxy=1.0)
    assert result["modifier"] <= 0.05, (
        f"Modifier {result['modifier']} exceeds +5% upper bound"
    )


def test_modifier_never_below_lower_bound():
    """Even at extreme loss rate, modifier stays at or above -15% (AC-f)."""
    result = compute_body_modifier(weekly_pct_bw_rate=-5.0, ea_proxy=0.0)
    assert result["modifier"] >= -0.15, (
        f"Modifier {result['modifier']} exceeds -15% lower bound"
    )


def test_bounds_apply_at_all_ea_levels():
    """Bounds apply at both high and low EA (AC-f)."""
    for ea in [0.0, 0.5, 1.0]:
        r_high = compute_body_modifier(weekly_pct_bw_rate=5.0, ea_proxy=ea)
        r_low = compute_body_modifier(weekly_pct_bw_rate=-5.0, ea_proxy=ea)
        assert r_high["modifier"] <= 0.05, f"Upper bound violated at ea={ea}"
        assert r_low["modifier"] >= -0.15, f"Lower bound violated at ea={ea}"


# ---------------------------------------------------------------------------
# (g) Syntax / compile check
# ---------------------------------------------------------------------------

def test_module_compiles_cleanly():
    """py_compile passes on the body_modifier module (AC-g)."""
    module_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "backend",
        "services",
        "body_modifier.py",
    )
    module_path = os.path.normpath(module_path)
    py_compile.compile(module_path, doraise=True)


# ---------------------------------------------------------------------------
# Return shape
# ---------------------------------------------------------------------------

def test_result_contains_modifier_key():
    """compute_body_modifier always returns a dict with 'modifier' key."""
    result = compute_body_modifier(weekly_pct_bw_rate=-0.3, ea_proxy=1.0)
    assert "modifier" in result


def test_result_contains_branch_key():
    """compute_body_modifier returns a 'branch' key describing the active branch."""
    result = compute_body_modifier(weekly_pct_bw_rate=-0.3, ea_proxy=1.0)
    assert "branch" in result
    assert result["branch"] in ("uplift", "penalty", "neutral")
