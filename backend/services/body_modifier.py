"""Body-composition modifier with sign-flip around deficit threshold (issue #1158).

A small caloric deficit can improve power-to-weight ratio, but once the weekly
bodyweight-loss rate exceeds roughly 0.5–0.75 % BW/week — or the energy-
availability (EA) proxy falls below a safe threshold — the modifier flips from
a positive uplift to a meaningful penalty on both power and endurance outputs.

Public API
----------
compute_body_modifier(weekly_pct_bw_rate, ea_proxy, *, ...) -> dict

    weekly_pct_bw_rate : float
        Weekly percent bodyweight rate of change from ``compute_weekly_pct_bw_rate_of_change``.
        Sign convention: negative = weight loss, positive = weight gain.
    ea_proxy : float
        Energy-availability proxy in [0, 1], where 1.0 = fully fuelled and
        0.0 = severely under-fuelled.  Values below ``EA_LOW_THRESHOLD``
        trigger the penalty branch regardless of loss rate.

Returns a dict::

    {
        "modifier": float,   # fractional modifier, e.g. 0.02 means +2 %
        "branch":   str,     # "uplift" | "penalty" | "neutral"
    }

Math
----
The loss rate as a signed magnitude (positive = losing weight) is:

    loss_rate = -weekly_pct_bw_rate   (so a loss of 0.3 %/wk gives loss_rate=0.3)

The modifier is computed via two linear segments with a common zero-crossing at the
threshold midpoint RATE_ZERO_CROSSING = (RATE_THRESHOLD_LOW + RATE_THRESHOLD_HIGH) / 2:

1. Uplift zone  (loss_rate < RATE_ZERO_CROSSING):
       modifier = MAX_UPLIFT * (1 - loss_rate / RATE_ZERO_CROSSING)
       Linear from MAX_UPLIFT at rate=0 down to exactly 0 at RATE_ZERO_CROSSING.

2. Penalty zone (loss_rate >= RATE_ZERO_CROSSING):
       modifier = -PENALTY_SLOPE * (loss_rate - RATE_ZERO_CROSSING)
       Linear from 0 at RATE_ZERO_CROSSING, growing more negative with excess loss.

4. Low-EA override: when ea_proxy < EA_LOW_THRESHOLD, the EA-penalty component
       ea_penalty = EA_PENALTY_SCALE * (EA_LOW_THRESHOLD - ea_proxy) / EA_LOW_THRESHOLD
   is subtracted from the modifier (always drives it more negative).

All outputs are clamped to [MODIFIER_MIN, MODIFIER_MAX].
"""

from __future__ import annotations

# ── Configurable thresholds ───────────────────────────────────────────────────

# Loss rate band (percent BW/week): the modifier sign-flip occurs within this range.
# RATE_THRESHOLD_LOW  — below this, the athlete is in the safe uplift zone.
# RATE_THRESHOLD_HIGH — above this, the full penalty slope is active.
# The modifier is exactly zero at the midpoint (RATE_THRESHOLD_LOW + RATE_THRESHOLD_HIGH) / 2.
RATE_THRESHOLD_LOW: float = 0.50
RATE_THRESHOLD_HIGH: float = 0.75

# Maximum fractional uplift at a very small deficit (e.g. 0.05 = +5 %).
MAX_UPLIFT: float = 0.05

# Fractional penalty applied per percentage point of loss rate beyond RATE_ZERO_CROSSING.
# With PENALTY_SLOPE=0.10 a 1.0 %/week loss rate yields -(1.0-0.625)*0.10 = -3.75 %.
PENALTY_SLOPE: float = 0.10

# EA proxy value below which the low-EA penalty branch activates.
EA_LOW_THRESHOLD: float = 0.40

# Maximum additional penalty when EA proxy is at 0.0 (fully depleted).
EA_PENALTY_SCALE: float = 0.08

# Hard bounds on the final modifier value.
MODIFIER_MIN: float = -0.15
MODIFIER_MAX: float = 0.05

# Derived zero-crossing (not configurable directly; adjust LOW/HIGH to move it).
RATE_ZERO_CROSSING: float = (RATE_THRESHOLD_LOW + RATE_THRESHOLD_HIGH) / 2.0


def compute_body_modifier(
    weekly_pct_bw_rate: float,
    ea_proxy: float,
    *,
    rate_threshold_low: float = RATE_THRESHOLD_LOW,
    rate_threshold_high: float = RATE_THRESHOLD_HIGH,
    max_uplift: float = MAX_UPLIFT,
    penalty_slope: float = PENALTY_SLOPE,
    ea_low_threshold: float = EA_LOW_THRESHOLD,
    ea_penalty_scale: float = EA_PENALTY_SCALE,
    modifier_min: float = MODIFIER_MIN,
    modifier_max: float = MODIFIER_MAX,
) -> dict:
    """Compute the body-composition modifier.

    Parameters
    ----------
    weekly_pct_bw_rate:
        Output of ``compute_weekly_pct_bw_rate_of_change``.  Negative values
        indicate weight loss; positive values indicate weight gain.
    ea_proxy:
        Energy-availability proxy in [0, 1].  Below ``ea_low_threshold`` the
        low-EA penalty branch is activated independently of the loss rate.

    Returns
    -------
    dict with keys:
        ``modifier`` — fractional modifier to apply to power/endurance outputs.
        ``branch``   — which branch was dominant: ``"uplift"``, ``"penalty"``,
                       or ``"neutral"`` (at the transition midpoint).
    """
    # Convert loss sign: we reason in terms of positive loss_rate (losing body weight).
    loss_rate = -float(weekly_pct_bw_rate)

    # Derived zero-crossing for these (potentially overridden) thresholds.
    zero_crossing = (rate_threshold_low + rate_threshold_high) / 2.0

    # ── Rate-based modifier ───────────────────────────────────────────────────
    if loss_rate < zero_crossing:
        # Uplift zone: linear from max_uplift (at rate=0) to 0 (at zero_crossing).
        scale = 1.0 - loss_rate / zero_crossing if zero_crossing > 0 else 0.0
        rate_modifier = max_uplift * scale
    else:
        # Penalty zone: grows linearly past the zero-crossing.
        rate_modifier = -penalty_slope * (loss_rate - zero_crossing)

    # ── EA-proxy penalty ──────────────────────────────────────────────────────
    ea_modifier = 0.0
    if float(ea_proxy) < ea_low_threshold and ea_low_threshold > 0:
        deficit_fraction = (ea_low_threshold - float(ea_proxy)) / ea_low_threshold
        ea_modifier = -ea_penalty_scale * deficit_fraction

    # ── Combine and clamp ─────────────────────────────────────────────────────
    combined = rate_modifier + ea_modifier
    modifier = max(modifier_min, min(modifier_max, combined))

    # ── Branch label ─────────────────────────────────────────────────────────
    if modifier > 0.001:
        branch = "uplift"
    elif modifier < -0.001:
        branch = "penalty"
    else:
        branch = "neutral"

    return {"modifier": round(modifier, 6), "branch": branch}
