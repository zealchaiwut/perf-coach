"""Economy stimulus from strength and plyometric training load (issue #1146).

Computes a combined economy stimulus signal that rewards sessions where both
strength load and plyometric contact volume appear together within a rolling
window — producing a synergy bonus that neither modality generates alone.

Public API
----------
compute_economy_stimulus(
    strength_load, plyo_contacts, speed_kmh, fitness_score, *, config=None)
    Pure function. No I/O, no DB calls, no side effects.

Design rationale
----------------
Strength training primes neuromuscular efficiency, and its economy benefit
scales with running speed (faster speeds leverage force production more) and
with the athlete's fitness (fitness amplifies neuromuscular adaptations).
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

All tunable parameters (speed-dependence weights, combination bonus) are read
from ``EconomyPriorConfig`` — see ``backend.services.economy_config``.

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

from typing import Optional

from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG, EconomyPriorConfig


# ── Internal helpers ──────────────────────────────────────────────────────────

def _strength_weight(
    speed_kmh: float,
    fitness_score: float,
    speed_scale: float,
    fitness_scale: float,
) -> float:
    """Strength weight factor: monotonically non-decreasing in both arguments.

    At speed=0, fitness=0 the weight is 1.0 (baseline).  Both speed and
    fitness factors are ≥ 1.0, so the product is always ≥ 1.0.
    """
    speed_factor = 1.0 + speed_kmh / speed_scale
    fitness_factor = 1.0 + fitness_score / fitness_scale
    return speed_factor * fitness_factor


def _plyo_weight(
    speed_kmh: float,
    threshold: float,
    below_taper_fraction: float,
) -> float:
    """Plyo weight factor: peaks below threshold, tapers above.

    Below the threshold there is a gentle linear decrease (from 1.0 at 0 km/h
    to (1 - below_taper_fraction) at the threshold).  Above the threshold the
    weight tapers steeply to 0.0 at twice the threshold.

    The two pieces meet continuously at speed = threshold.
    """
    T = threshold
    f = below_taper_fraction
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
    config: Optional[EconomyPriorConfig] = None,
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
    config:
        Economy prior configuration.  When ``None`` the singleton
        ``DEFAULT_ECONOMY_CONFIG`` is used.  Pass a custom
        ``EconomyPriorConfig`` to experiment with different parameter values.

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
    - Plyo component is highest at low speed (below plyo_speed_threshold)
      and tapers above.
    - When both strength_load > 0 and plyo_contacts > 0, the combined
      stimulus strictly exceeds the sum of each computed independently
      (when combination_bonus > 1.0).
    """
    if config is None:
        config = DEFAULT_ECONOMY_CONFIG

    sw = config.speed_weights

    # Clamp inputs to valid range
    sl = max(0.0, float(strength_load))
    pc = max(0.0, float(plyo_contacts))
    spd = max(0.0, float(speed_kmh))
    fit = max(0.0, float(fitness_score))

    s_weight = _strength_weight(
        spd, fit,
        speed_scale=sw["strength_speed_scale"],
        fitness_scale=sw["strength_fitness_scale"],
    )
    p_weight = _plyo_weight(
        spd,
        threshold=sw["plyo_speed_threshold"],
        below_taper_fraction=sw["plyo_below_taper_fraction"],
    )

    strength_component = sl * s_weight
    plyo_component = pc * p_weight

    if sl > 0.0 and pc > 0.0:
        stimulus = (strength_component + plyo_component) * config.combination_bonus
    else:
        stimulus = strength_component + plyo_component

    return max(0.0, stimulus)
