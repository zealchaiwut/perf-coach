"""Running economy stimulus from strength and plyometric training load (issue #1146).

Computes a combined economy stimulus signal that rewards sessions where both
strength load and plyometric contact volume appear together within a rolling
window — producing a synergy bonus that neither modality generates alone.

Public API
----------
compute_economy_stimulus(strength_load, plyo_contacts, speed_kmh, fitness_score)
    Pure function. No I/O, no DB calls, no side effects.

Design rationale
----------------
Strength training primes neuromuscular efficiency, and its economy benefit
scales with running speed (faster speeds leverage force production more) and
with the athlete's fitness (higher fitness amplifies neuromuscular adaptations).
The strength weight is therefore a product of a speed factor and a fitness
factor, both monotonically non-decreasing.

Plyometric contacts drive elastic energy return, which is most pronounced at
sub-maximal running speeds (below ~12 km/h). The plyo weight tapers above the
12 km/h boundary to reflect the diminishing elastic energy contribution at
faster speeds.

When both modalities are present simultaneously, a combination bonus multiplier
is applied to the total, rewarding concurrent training stimulus. Each component
is computed identically whether or not the other is present, so the bonus is
strictly additive relative to the sum of individual contributions.

Worked example — combination case
----------------------------------
Inputs: strength_load=500, plyo_contacts=200, speed_kmh=10, fitness_score=50

Strength weight:
    speed_factor   = 1 + 10 / 20  = 1.5
    fitness_factor = 1 + 50 / 100 = 1.5
    s_weight       = 1.5 × 1.5    = 2.25

Plyo weight (speed=10 < 12):
    p_weight = 1 - 0.1 × (10 / 12) ≈ 0.917

Components:
    strength_component = 500 × 2.25  = 1125.0
    plyo_component     = 200 × 0.917 ≈ 183.3

With combination bonus (1.1):
    stimulus = (1125.0 + 183.3) × 1.1 ≈ 1439.2

Computed independently (no bonus):
    stimulus(500, 0)  = 1125.0
    stimulus(0, 200)  ≈ 183.3
    sum               ≈ 1308.3

Combined (1439.2) > individual sum (1308.3) ✓

Worked example — strength-only, speed effect
---------------------------------------------
Inputs: strength_load=500, plyo_contacts=0, fitness_score=50

At speed=8 km/h:
    s_weight = (1 + 8/20) × (1 + 50/100) = 1.4 × 1.5 = 2.10
    stimulus = 500 × 2.10 = 1050.0

At speed=16 km/h:
    s_weight = (1 + 16/20) × (1 + 50/100) = 1.8 × 1.5 = 2.70
    stimulus = 500 × 2.70 = 1350.0

Higher speed → higher stimulus ✓

Worked example — plyo-only, boundary effect
--------------------------------------------
Inputs: strength_load=0, plyo_contacts=200, fitness_score=50

At speed=8 km/h (< 12):
    p_weight = 1 - 0.1 × (8/12) ≈ 0.933
    stimulus = 200 × 0.933 ≈ 186.7

At speed=12 km/h (boundary):
    p_weight = 1 - 0.1 × (12/12) = 0.9
    stimulus = 200 × 0.9 = 180.0

At speed=16 km/h (above boundary):
    p_weight = 0.9 × (1 - (16-12)/12) = 0.9 × 0.667 ≈ 0.6
    stimulus = 200 × 0.6 = 120.0

Order: 8 km/h (186.7) > 12 km/h (180.0) > 16 km/h (120.0) ✓
"""

from __future__ import annotations

# ── Constants ─────────────────────────────────────────────────────────────────

# Strength prior: speed and fitness normalization denominators.
# Chosen so that at typical values (speed ~20 km/h, fitness ~100) the weight
# reaches roughly 2×–4× the baseline (speed=0, fitness=0) weight of 1.0.
_STRENGTH_SPEED_SCALE: float = 20.0     # km/h
_STRENGTH_FITNESS_SCALE: float = 100.0  # arbitrary fitness units

# Plyo prior: boundary speed above which elastic energy return tapers.
_PLYO_SPEED_THRESHOLD: float = 12.0    # km/h

# Fraction of plyo weight lost by the time speed reaches the threshold.
# Below threshold the decrease is gentle (this fraction over the full range).
# Above threshold the remaining weight tapers steeply to zero at 2× threshold.
_PLYO_BELOW_TAPER_FRACTION: float = 0.1

# Combination bonus multiplier applied when both strength_load > 0 and
# plyo_contacts > 0.  A value of 1.1 grants a 10% combined-modality bonus.
_COMBINATION_BONUS: float = 1.1


# ── Internal helpers ─────────────────────────────────────────────────────────

def _strength_weight(speed_kmh: float, fitness_score: float) -> float:
    """Strength weight factor: monotonically non-decreasing in both arguments.

    At speed=0, fitness=0 the weight is 1.0 (baseline).  Both speed and
    fitness factors are ≥ 1.0, so the product is always ≥ 1.0.
    """
    speed_factor = 1.0 + speed_kmh / _STRENGTH_SPEED_SCALE
    fitness_factor = 1.0 + fitness_score / _STRENGTH_FITNESS_SCALE
    return speed_factor * fitness_factor


def _plyo_weight(speed_kmh: float) -> float:
    """Plyo weight factor: peaks below 12 km/h, tapers above.

    Below the 12 km/h threshold there is a gentle linear decrease
    (from 1.0 at 0 km/h to 0.9 at the threshold).  Above the threshold
    the weight tapers steeply to 0.0 at twice the threshold (24 km/h).

    The two pieces meet continuously at speed = 12 km/h (weight = 0.9):
        below: 1 - 0.1 × (speed / 12)  →  at speed=12: 1 - 0.1 = 0.9
        above: 0.9 × (1 - (speed - 12) / 12)  →  at speed=12: 0.9 × 1 = 0.9
    """
    T = _PLYO_SPEED_THRESHOLD
    f = _PLYO_BELOW_TAPER_FRACTION
    if speed_kmh < T:
        return 1.0 - f * (speed_kmh / T)
    else:
        above = speed_kmh - T
        return max(0.0, (1.0 - f) * (1.0 - above / T))


# ── Public API ────────────────────────────────────────────────────────────────

def compute_economy_stimulus(
    strength_load: float,
    plyo_contacts: float,
    speed_kmh: float,
    fitness_score: float,
) -> float:
    """Compute combined running economy stimulus from strength and plyo load.

    Parameters
    ----------
    strength_load:
        Aggregate strength training load for the window (arbitrary units,
        e.g. total volume-load in kg·reps or a TSS-like score). Must be ≥ 0.
    plyo_contacts:
        Cumulative plyometric foot contacts in the window. Must be ≥ 0.
    speed_kmh:
        Representative running speed in km/h used to weight each modality.
        Must be ≥ 0.
    fitness_score:
        Current athlete fitness level (0–100+ scale). Higher values amplify
        the strength prior. Must be ≥ 0.

    Returns
    -------
    float
        Economy stimulus value in [0, ∞).  Returns 0.0 when both
        strength_load and plyo_contacts are zero.

    Properties guaranteed
    ---------------------
    - Non-negative for all valid (≥ 0) inputs.
    - Monotonically non-decreasing in strength_load and plyo_contacts.
    - Strength component is monotonically non-decreasing in speed_kmh and
      fitness_score.
    - Plyo component is highest at low speed (< 12 km/h) and tapers above.
    - When both strength_load > 0 and plyo_contacts > 0, the combined
      stimulus strictly exceeds the sum of each computed independently.
    """
    # Clamp inputs to valid range
    sl = max(0.0, float(strength_load))
    pc = max(0.0, float(plyo_contacts))
    spd = max(0.0, float(speed_kmh))
    fit = max(0.0, float(fitness_score))

    s_weight = _strength_weight(spd, fit)
    p_weight = _plyo_weight(spd)

    strength_component = sl * s_weight
    plyo_component = pc * p_weight

    if sl > 0.0 and pc > 0.0:
        stimulus = (strength_component + plyo_component) * _COMBINATION_BONUS
    else:
        stimulus = strength_component + plyo_component

    return max(0.0, stimulus)
