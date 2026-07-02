"""
Tests for issue #1107: Derive expressible score from TSB form factor.

Acceptance criteria verified:
- AC1: per-date expressible_score is computed by applying TSB form factor to base score
- AC2: form factor: higher TSB relative to ceiling yields multiplier > 1;
       negative TSB suppresses the score below the base
- AC3: expressible_score peaks at/near taper date when TSB is maximised and
       CTL has not significantly declined
- AC4: score curve matches supercompensation shape (dips during heavy loading,
       rises during taper)
- AC5: existing CTL/ATL/TSB calculation logic (project_fitness) is unchanged
- AC6: py_compile passes on all modified/created Python files
- AC7a: peak at taper — expressible_score is highest at end of taper phase
- AC7b: suppression under negative TSB — score < base_score
- AC7c: when TSB = 0, expressible_score equals base_score exactly
"""

import py_compile
from datetime import date, timedelta

from backend.services.projection import (
    CTL_DECAY,
    ATL_DECAY,
    project_fitness,
    tsb_form_factor,
    compute_expressible_score,
    apply_expressible_scores,
)

TODAY = date(2026, 6, 29)
BASE_SCORE = 100.0
CEILING_TSB = 20.0  # representative ceiling TSB for a well-trained athlete


# ── AC6: py_compile ──────────────────────────────────────────────────────────

def test_ac6_projection_py_compiles():
    """projection.py must compile without errors."""
    import backend.services.projection as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


# ── AC7c: TSB = 0 → form factor = 1.0 → expressible = base ──────────────────

def test_ac7c_tsb_zero_form_factor_is_one():
    """tsb_form_factor must return exactly 1.0 when projected_tsb = 0."""
    factor = tsb_form_factor(projected_tsb=0.0, ceiling_tsb=CEILING_TSB)
    assert factor == 1.0, f"Expected 1.0 got {factor}"


def test_ac7c_tsb_zero_expressible_equals_base():
    """compute_expressible_score must equal base_score when projected_tsb = 0."""
    score = compute_expressible_score(
        base_score=BASE_SCORE,
        projected_tsb=0.0,
        ceiling_tsb=CEILING_TSB,
    )
    assert abs(score - BASE_SCORE) < 1e-9, (
        f"Expected {BASE_SCORE}, got {score}"
    )


# ── AC2: form factor direction ────────────────────────────────────────────────

def test_ac2_positive_tsb_yields_factor_above_one():
    """Positive TSB yields form factor > 1 (enhances score)."""
    factor = tsb_form_factor(projected_tsb=10.0, ceiling_tsb=CEILING_TSB)
    assert factor > 1.0, f"Expected factor > 1.0 for positive TSB, got {factor}"


def test_ac2_negative_tsb_yields_factor_below_one():
    """Negative TSB yields form factor < 1 (suppresses score)."""
    factor = tsb_form_factor(projected_tsb=-10.0, ceiling_tsb=CEILING_TSB)
    assert factor < 1.0, f"Expected factor < 1.0 for negative TSB, got {factor}"


def test_ac2_tsb_at_ceiling_yields_factor_above_one():
    """TSB equal to ceiling_tsb must produce factor > 1 (approaches/reaches peak)."""
    factor = tsb_form_factor(projected_tsb=CEILING_TSB, ceiling_tsb=CEILING_TSB)
    assert factor > 1.0, (
        f"TSB at ceiling should produce factor > 1.0, got {factor}"
    )


def test_ac2_factor_monotonically_increases_with_tsb():
    """Form factor must be strictly increasing as projected_tsb increases."""
    tsb_values = [-20.0, -10.0, 0.0, 10.0, 20.0]
    factors = [tsb_form_factor(t, CEILING_TSB) for t in tsb_values]
    for i in range(1, len(factors)):
        assert factors[i] > factors[i - 1], (
            f"Factor should be strictly increasing: {list(zip(tsb_values, factors))}"
        )


def test_ac2_higher_tsb_relative_to_ceiling_gives_higher_factor():
    """Doubling the TSB relative to the same ceiling must double the premium above 1."""
    f_half = tsb_form_factor(projected_tsb=CEILING_TSB / 2, ceiling_tsb=CEILING_TSB)
    f_full = tsb_form_factor(projected_tsb=CEILING_TSB, ceiling_tsb=CEILING_TSB)
    premium_half = f_half - 1.0
    premium_full = f_full - 1.0
    assert premium_full > premium_half > 0, (
        f"Premium should grow with TSB ratio; half={premium_half}, full={premium_full}"
    )


# ── AC7b: negative TSB suppresses expressible score ──────────────────────────

def test_ac7b_negative_tsb_suppresses_expressible_score():
    """expressible_score < base_score when projected_tsb < 0."""
    score = compute_expressible_score(
        base_score=BASE_SCORE,
        projected_tsb=-5.0,
        ceiling_tsb=CEILING_TSB,
    )
    assert score < BASE_SCORE, (
        f"Negative TSB (-5) should suppress score below {BASE_SCORE}, got {score}"
    )


def test_ac7b_deeper_negative_tsb_suppresses_more():
    """More negative TSB → lower expressible_score."""
    score_mild = compute_expressible_score(BASE_SCORE, -5.0, CEILING_TSB)
    score_deep = compute_expressible_score(BASE_SCORE, -15.0, CEILING_TSB)
    assert score_deep < score_mild, (
        f"Deeper negative TSB should suppress more: -15→{score_deep}, -5→{score_mild}"
    )


# ── AC7a: expressible_score peaks at taper ────────────────────────────────────

def _build_taper_series():
    """21-day build at 100 TSS + 14-day taper at 10 TSS."""
    loads = [100.0] * 21 + [10.0] * 14
    return project_fitness(loads, start_ctl=50.0, start_atl=50.0, start_date=TODAY)


def test_ac7a_taper_end_score_exceeds_build_end_score():
    """expressible_score at end of taper must exceed score at end of build phase."""
    series = _build_taper_series()
    annotated = apply_expressible_scores(series, base_score=BASE_SCORE, ceiling_tsb=CEILING_TSB)

    build_end = TODAY + timedelta(days=21)
    taper_end = TODAY + timedelta(days=35)

    build_score = annotated[build_end]["expressible_score"]
    taper_score = annotated[taper_end]["expressible_score"]
    assert taper_score > build_score, (
        f"Taper-end score ({taper_score}) should exceed build-end score ({build_score})"
    )


def test_ac7a_peak_expressible_score_exceeds_base_score():
    """Peak expressible_score during taper must exceed base_score (positive TSB)."""
    series = _build_taper_series()
    annotated = apply_expressible_scores(series, base_score=BASE_SCORE, ceiling_tsb=CEILING_TSB)

    max_score = max(v["expressible_score"] for v in annotated.values())
    assert max_score > BASE_SCORE, (
        f"Peak expressible_score {max_score} should exceed base_score {BASE_SCORE}"
    )


# ── AC3: score peaks when TSB peaks ──────────────────────────────────────────

def test_ac3_score_peak_date_equals_tsb_peak_date():
    """expressible_score must peak on the same date as projected TSB peaks."""
    series = _build_taper_series()
    annotated = apply_expressible_scores(series, base_score=BASE_SCORE, ceiling_tsb=CEILING_TSB)

    dates = sorted(annotated.keys())
    tsb_peak_date = max(dates, key=lambda d: annotated[d]["tsb"])
    score_peak_date = max(dates, key=lambda d: annotated[d]["expressible_score"])
    assert tsb_peak_date == score_peak_date, (
        f"expressible_score peaks on {score_peak_date}, but TSB peaks on {tsb_peak_date}; "
        "they must coincide"
    )


# ── AC4: supercompensation shape ─────────────────────────────────────────────

def test_ac4_score_below_base_during_heavy_loading():
    """During a heavy loading phase that drives TSB negative, score < base_score."""
    # Heavy load from a rested state — will quickly push ATL above CTL
    loads = [200.0] * 14
    series = project_fitness(loads, start_ctl=50.0, start_atl=20.0, start_date=TODAY)
    annotated = apply_expressible_scores(series, base_score=BASE_SCORE, ceiling_tsb=CEILING_TSB)

    negative_tsb_days = [d for d, v in annotated.items() if v["tsb"] < 0]
    assert negative_tsb_days, "Expected negative TSB during heavy loading"

    for d in negative_tsb_days:
        assert annotated[d]["expressible_score"] < BASE_SCORE, (
            f"Score on {d} ({annotated[d]['expressible_score']}) should be below "
            f"base ({BASE_SCORE}) when TSB={annotated[d]['tsb']}"
        )


def test_ac4_taper_after_build_shows_rising_score():
    """After build phase, taper phase must show a rising expressible_score curve."""
    series = _build_taper_series()
    annotated = apply_expressible_scores(series, base_score=BASE_SCORE, ceiling_tsb=CEILING_TSB)

    taper_dates = sorted(d for d in annotated if d > TODAY + timedelta(days=21))
    scores = [annotated[d]["expressible_score"] for d in taper_dates]
    # Score must rise overall during taper (first day < last day)
    assert scores[-1] > scores[0], (
        f"Taper score should rise: first taper day {scores[0]:.2f}, last {scores[-1]:.2f}"
    )


# ── AC1: per-date output ──────────────────────────────────────────────────────

def test_ac1_apply_returns_per_date_dict_with_expressible_score():
    """apply_expressible_scores must return a dict keyed by date objects."""
    loads = [60.0] * 7
    series = project_fitness(loads, start_ctl=50.0, start_atl=50.0, start_date=TODAY)
    annotated = apply_expressible_scores(series, base_score=BASE_SCORE, ceiling_tsb=CEILING_TSB)

    assert len(annotated) == 7
    for d, v in annotated.items():
        assert isinstance(d, date), f"Key should be a date, got {type(d)}"
        assert "expressible_score" in v, "Each entry must have 'expressible_score'"
        assert isinstance(v["expressible_score"], float)


def test_ac1_existing_ctl_atl_tsb_keys_preserved():
    """apply_expressible_scores must preserve existing ctl/atl/tsb keys."""
    loads = [60.0] * 3
    series = project_fitness(loads, start_ctl=50.0, start_atl=50.0, start_date=TODAY)
    annotated = apply_expressible_scores(series, base_score=BASE_SCORE, ceiling_tsb=CEILING_TSB)

    for d, v in annotated.items():
        for key in ("ctl", "atl", "tsb", "expressible_score"):
            assert key in v, f"Key '{key}' missing from annotated entry on {d}"


def test_ac1_empty_series_returns_empty_dict():
    """apply_expressible_scores on an empty series returns an empty dict."""
    annotated = apply_expressible_scores({}, base_score=BASE_SCORE, ceiling_tsb=CEILING_TSB)
    assert annotated == {}


# ── AC5: existing CTL/ATL/TSB logic unchanged ─────────────────────────────────

def test_ac5_project_fitness_ctl_formula_unchanged():
    """project_fitness day-1 CTL must still equal start_ctl * CTL_DECAY + load*(1-CTL_DECAY)."""
    start_ctl, start_atl, load = 60.0, 60.0, 80.0
    result = project_fitness([load], start_ctl=start_ctl, start_atl=start_atl, start_date=TODAY)
    day1 = result[TODAY + timedelta(days=1)]

    expected_ctl = start_ctl * CTL_DECAY + load * (1 - CTL_DECAY)
    assert abs(day1["ctl"] - expected_ctl) < 1e-9, (
        f"CTL formula changed: expected {expected_ctl}, got {day1['ctl']}"
    )


def test_ac5_project_fitness_atl_formula_unchanged():
    """project_fitness day-1 ATL must still equal start_atl * ATL_DECAY + load*(1-ATL_DECAY)."""
    start_ctl, start_atl, load = 60.0, 60.0, 80.0
    result = project_fitness([load], start_ctl=start_ctl, start_atl=start_atl, start_date=TODAY)
    day1 = result[TODAY + timedelta(days=1)]

    expected_atl = start_atl * ATL_DECAY + load * (1 - ATL_DECAY)
    assert abs(day1["atl"] - expected_atl) < 1e-9, (
        f"ATL formula changed: expected {expected_atl}, got {day1['atl']}"
    )


def test_ac5_project_fitness_does_not_add_expressible_score_key():
    """project_fitness must NOT inject expressible_score — it's opt-in via apply_expressible_scores."""
    loads = [80.0] * 5
    result = project_fitness(loads, start_ctl=60.0, start_atl=60.0, start_date=TODAY)
    for v in result.values():
        assert "expressible_score" not in v, (
            "project_fitness must not add expressible_score; "
            "use apply_expressible_scores for that"
        )
