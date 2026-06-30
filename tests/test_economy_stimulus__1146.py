"""Tests for issue #1146: Compute economy stimulus from strength and plyo load.

Each test is anchored to a specific acceptance criterion.

Acceptance criteria covered:
  AC-1  — compute_economy_stimulus exists and is importable
  AC-2  — Strength prior: monotonically non-decreasing in speed_kmh
  AC-2b — Strength prior: monotonically non-decreasing in fitness_score
  AC-3  — Plyo prior: higher when speed_kmh < 12, tapers above threshold
  AC-4  — Combination bonus: combined > sum of each computed independently
  AC-5  — Monotonicity: doubling strength_load increases stimulus
  AC-5b — Monotonicity: doubling plyo_contacts increases stimulus
  AC-6  — Non-negative for all valid inputs
  AC-7  — py_compile passes on touched files
  AC-8  — Unit tests: strength-only, plyo-only, combined, zero, boundary at 12 km/h
"""

import py_compile
import pathlib


# ── AC-1: importable ──────────────────────────────────────────────────────────

def test_compute_economy_stimulus_importable():
    """AC-1: compute_economy_stimulus is importable from backend.services.economy_stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    assert callable(compute_economy_stimulus)


def test_function_accepts_four_args():
    """AC-1: function signature accepts strength_load, plyo_contacts, speed_kmh, fitness_score."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    result = compute_economy_stimulus(100.0, 50.0, 10.0, 50.0)
    assert result is not None


# ── AC-2: strength prior monotone in speed_kmh ───────────────────────────────

def test_strength_stimulus_increases_with_speed():
    """AC-2: with fixed strength_load and fitness_score, higher speed → higher stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    low_speed = compute_economy_stimulus(500.0, 0.0, 8.0, 50.0)
    high_speed = compute_economy_stimulus(500.0, 0.0, 16.0, 50.0)
    assert high_speed > low_speed, (
        f"Stimulus at 16 km/h ({high_speed}) must exceed stimulus at 8 km/h ({low_speed})"
    )


def test_strength_stimulus_monotone_speed_fine_grained():
    """AC-2: strength-only stimulus increases at each speed step."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    speeds = [0.0, 4.0, 8.0, 12.0, 16.0, 20.0]
    stimuli = [compute_economy_stimulus(500.0, 0.0, s, 50.0) for s in speeds]
    for i in range(1, len(stimuli)):
        assert stimuli[i] >= stimuli[i - 1], (
            f"Stimulus must be non-decreasing in speed: {speeds[i-1]} km/h "
            f"({stimuli[i-1]}) → {speeds[i]} km/h ({stimuli[i]})"
        )


# ── AC-2b: strength prior monotone in fitness_score ──────────────────────────

def test_strength_stimulus_increases_with_fitness():
    """AC-2b: with fixed strength_load and speed_kmh, higher fitness → higher stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    low_fit = compute_economy_stimulus(500.0, 0.0, 10.0, 30.0)
    high_fit = compute_economy_stimulus(500.0, 0.0, 10.0, 80.0)
    assert high_fit > low_fit, (
        f"Stimulus at fitness=80 ({high_fit}) must exceed fitness=30 ({low_fit})"
    )


def test_strength_stimulus_monotone_fitness_fine_grained():
    """AC-2b: strength-only stimulus increases at each fitness step."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    scores = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    stimuli = [compute_economy_stimulus(500.0, 0.0, 10.0, f) for f in scores]
    for i in range(1, len(stimuli)):
        assert stimuli[i] >= stimuli[i - 1], (
            f"Stimulus must be non-decreasing in fitness_score: "
            f"fitness={scores[i-1]} ({stimuli[i-1]}) → fitness={scores[i]} ({stimuli[i]})"
        )


# ── AC-3: plyo prior tapers above 12 km/h ────────────────────────────────────

def test_plyo_stimulus_highest_at_low_speed():
    """AC-3: pure plyo stimulus at 8 km/h > 12 km/h."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    at_8 = compute_economy_stimulus(0.0, 200.0, 8.0, 50.0)
    at_12 = compute_economy_stimulus(0.0, 200.0, 12.0, 50.0)
    assert at_8 > at_12, (
        f"Plyo stimulus at 8 km/h ({at_8}) must exceed stimulus at 12 km/h boundary ({at_12})"
    )


def test_plyo_stimulus_tapers_above_threshold():
    """AC-3: pure plyo stimulus at 12 km/h >= 16 km/h (tapers above boundary)."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    at_12 = compute_economy_stimulus(0.0, 200.0, 12.0, 50.0)
    at_16 = compute_economy_stimulus(0.0, 200.0, 16.0, 50.0)
    assert at_12 >= at_16, (
        f"Plyo stimulus at boundary 12 km/h ({at_12}) must be >= 16 km/h ({at_16})"
    )


def test_plyo_stimulus_strictly_lower_at_16_than_12():
    """AC-3: pure plyo stimulus at 16 km/h is strictly less than at 12 km/h (taper is active)."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    at_12 = compute_economy_stimulus(0.0, 200.0, 12.0, 50.0)
    at_16 = compute_economy_stimulus(0.0, 200.0, 16.0, 50.0)
    assert at_16 < at_12, (
        f"Taper above 12 km/h must reduce stimulus: 12 km/h ({at_12}), 16 km/h ({at_16})"
    )


def test_plyo_stimulus_order_8_12_16():
    """AC-3 / UAT step 2: stimulus at 8 > 12 >= 16 for plyo-only session."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    at_8 = compute_economy_stimulus(0.0, 200.0, 8.0, 50.0)
    at_12 = compute_economy_stimulus(0.0, 200.0, 12.0, 50.0)
    at_16 = compute_economy_stimulus(0.0, 200.0, 16.0, 50.0)
    assert at_8 > at_12 >= at_16, (
        f"Expected 8km/h ({at_8}) > 12km/h ({at_12}) >= 16km/h ({at_16})"
    )


# ── AC-4: combination bonus ───────────────────────────────────────────────────

def test_combined_exceeds_sum_of_individuals():
    """AC-4: combined stimulus > stimulus(strength_only) + stimulus(plyo_only)."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    strength_only = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    plyo_only = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0)
    combined = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0)
    assert combined > strength_only + plyo_only, (
        f"Combined ({combined}) must exceed sum of individuals "
        f"({strength_only} + {plyo_only} = {strength_only + plyo_only})"
    )


def test_combination_bonus_not_present_for_strength_only():
    """AC-4: no combination bonus when plyo_contacts == 0."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    # Verify the strength-only stimulus is exactly the raw strength component (no bonus)
    strength_only = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    # For this to hold, doubling strength_load must double the stimulus (linearity test)
    double_strength = compute_economy_stimulus(1000.0, 0.0, 10.0, 50.0)
    # The ratio must be 2.0 (linear, no bonus)
    ratio = double_strength / strength_only
    assert abs(ratio - 2.0) < 1e-9, f"Expected linear scaling (ratio=2.0), got {ratio}"


def test_combination_bonus_not_present_for_plyo_only():
    """AC-4: no combination bonus when strength_load == 0."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    plyo_only = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0)
    double_plyo = compute_economy_stimulus(0.0, 400.0, 10.0, 50.0)
    ratio = double_plyo / plyo_only
    assert abs(ratio - 2.0) < 1e-9, f"Expected linear scaling (ratio=2.0), got {ratio}"


# ── AC-5: monotonicity in strength_load ──────────────────────────────────────

def test_doubling_strength_load_increases_stimulus():
    """AC-5 / UAT step 5: doubling strength_load strictly increases stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    base = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    doubled = compute_economy_stimulus(1000.0, 0.0, 10.0, 50.0)
    assert doubled > base, f"Doubled load ({doubled}) must exceed base ({base})"


def test_strength_stimulus_monotone_load_steps():
    """AC-5: strength stimulus is non-decreasing as load increases."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    loads = [0.0, 100.0, 250.0, 500.0, 750.0, 1000.0]
    stimuli = [compute_economy_stimulus(l, 0.0, 10.0, 50.0) for l in loads]
    for i in range(1, len(stimuli)):
        assert stimuli[i] >= stimuli[i - 1], (
            f"Stimulus must be non-decreasing in strength_load: "
            f"load={loads[i-1]} ({stimuli[i-1]}) → load={loads[i]} ({stimuli[i]})"
        )


# ── AC-5b: monotonicity in plyo_contacts ─────────────────────────────────────

def test_doubling_plyo_contacts_increases_stimulus():
    """AC-5b: doubling plyo_contacts strictly increases stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    base = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0)
    doubled = compute_economy_stimulus(0.0, 400.0, 10.0, 50.0)
    assert doubled > base, f"Doubled plyo ({doubled}) must exceed base ({base})"


def test_plyo_stimulus_monotone_contact_steps():
    """AC-5b: plyo stimulus is non-decreasing as plyo_contacts increases."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    contacts = [0.0, 50.0, 100.0, 200.0, 400.0, 800.0]
    stimuli = [compute_economy_stimulus(0.0, c, 10.0, 50.0) for c in contacts]
    for i in range(1, len(stimuli)):
        assert stimuli[i] >= stimuli[i - 1], (
            f"Stimulus must be non-decreasing in plyo_contacts: "
            f"contacts={contacts[i-1]} ({stimuli[i-1]}) → contacts={contacts[i]} ({stimuli[i]})"
        )


# ── AC-6: non-negative output ─────────────────────────────────────────────────

def test_zero_inputs_return_zero_or_floor():
    """AC-6 / UAT step 4: all inputs zero → stimulus is 0 (or defined floor), no exception."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    result = compute_economy_stimulus(0.0, 0.0, 0.0, 0.0)
    assert result >= 0.0, f"Stimulus must be non-negative; got {result}"


def test_zero_inputs_do_not_raise():
    """AC-6: zero inputs do not raise any exception."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    try:
        compute_economy_stimulus(0.0, 0.0, 0.0, 0.0)
    except Exception as exc:
        raise AssertionError(f"Zero inputs raised exception: {exc}") from exc


def test_non_negative_for_various_valid_inputs():
    """AC-6: stimulus is non-negative across a range of valid inputs."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    test_cases = [
        (0.0, 0.0, 0.0, 0.0),
        (500.0, 0.0, 8.0, 50.0),
        (0.0, 200.0, 16.0, 50.0),
        (500.0, 200.0, 10.0, 50.0),
        (1000.0, 500.0, 24.0, 100.0),
        (100.0, 100.0, 0.0, 0.0),
    ]
    for sl, pc, spd, fit in test_cases:
        result = compute_economy_stimulus(sl, pc, spd, fit)
        assert result >= 0.0, (
            f"Stimulus must be non-negative for inputs "
            f"(strength={sl}, plyo={pc}, speed={spd}, fitness={fit}); got {result}"
        )


# ── AC-7: syntax check (py_compile) ──────────────────────────────────────────

def test_py_compile_economy_stimulus_module():
    """AC-7: economy_stimulus.py compiles with zero errors."""
    module_path = pathlib.Path(__file__).parent.parent / "backend" / "services" / "economy_stimulus.py"
    assert module_path.exists(), f"Module not found at {module_path}"
    # py_compile.compile raises py_compile.PyCompileError on syntax errors
    py_compile.compile(str(module_path), doraise=True)


# ── AC-8: explicit scenario tests ────────────────────────────────────────────

def test_strength_only_positive():
    """AC-8 / UAT step 1: strength_load=500, plyo_contacts=0 → positive stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    result = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    assert result > 0.0, f"Strength-only stimulus must be positive; got {result}"


def test_plyo_only_positive():
    """AC-8: strength_load=0, plyo_contacts=200 → positive stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    result = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0)
    assert result > 0.0, f"Plyo-only stimulus must be positive; got {result}"


def test_combined_positive():
    """AC-8: both loads present → positive combined stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    result = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0)
    assert result > 0.0, f"Combined stimulus must be positive; got {result}"


def test_zero_all_inputs_returns_nonnegative_floor():
    """AC-8: all inputs zero → non-negative output (0 or defined floor)."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    result = compute_economy_stimulus(0.0, 0.0, 10.0, 50.0)
    assert result == 0.0, f"Zero loads should return 0; got {result}"


def test_boundary_exactly_at_12_kmh_plyo():
    """AC-8: plyo-only at exactly 12 km/h returns non-negative and less than at 8 km/h."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    at_12 = compute_economy_stimulus(0.0, 200.0, 12.0, 50.0)
    at_8 = compute_economy_stimulus(0.0, 200.0, 8.0, 50.0)
    assert at_12 >= 0.0, f"Stimulus at 12 km/h must be non-negative; got {at_12}"
    assert at_8 > at_12, f"Stimulus at 8 km/h ({at_8}) must exceed boundary at 12 km/h ({at_12})"


def test_uat_step1_strength_speed_increases_stimulus():
    """AC-8 / UAT step 1: strength=500, plyo=0; speed 8→16 increases stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    at_8 = compute_economy_stimulus(500.0, 0.0, 8.0, 50.0)
    at_16 = compute_economy_stimulus(500.0, 0.0, 16.0, 50.0)
    assert at_16 > at_8, f"Speed 16 ({at_16}) must exceed speed 8 ({at_8}) for strength-only"


def test_uat_step2_plyo_highest_at_low_speed():
    """AC-8 / UAT step 2: plyo=200; stimulus highest at 8, lower at 12, lower at 16."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    at_8 = compute_economy_stimulus(0.0, 200.0, 8.0, 50.0)
    at_12 = compute_economy_stimulus(0.0, 200.0, 12.0, 50.0)
    at_16 = compute_economy_stimulus(0.0, 200.0, 16.0, 50.0)
    assert at_8 > at_12, f"Stimulus at 8 km/h ({at_8}) must exceed 12 km/h ({at_12})"
    assert at_12 >= at_16, f"Stimulus at 12 km/h ({at_12}) must be >= 16 km/h ({at_16})"


def test_uat_step3_combined_bonus_present():
    """AC-8 / UAT step 3: combined(500, 200) > stimulus(500, 0) + stimulus(0, 200)."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    s = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    p = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0)
    combined = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0)
    assert combined > s + p, (
        f"Combined ({combined}) must strictly exceed sum ({s} + {p} = {s + p})"
    )


def test_uat_step4_zero_inputs_no_exception():
    """AC-8 / UAT step 4: zero inputs return 0 or floor, no exception."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    result = compute_economy_stimulus(0.0, 0.0, 0.0, 0.0)
    assert result >= 0.0


def test_uat_step5_doubled_strength_load_increases():
    """AC-8 / UAT step 5: strength 500→1000 increases stimulus."""
    from backend.services.economy_stimulus import compute_economy_stimulus
    base = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    doubled = compute_economy_stimulus(1000.0, 0.0, 10.0, 50.0)
    assert doubled > base, f"Double strength ({doubled}) must exceed base ({base})"
