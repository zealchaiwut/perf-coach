"""
Forward CTL/ATL/TSB projection module.

Rolls Chronic Training Load (CTL), Acute Training Load (ATL), and Training
Stress Balance (TSB) forward from a known fitness state using a sequence of
planned daily loads.  This is a pure function module — no database access, no
side effects.

Math
----
CTL and ATL are updated each day via exponential decay:

    new_ctl = prev_ctl * CTL_DECAY + load * (1 - CTL_DECAY)
    new_atl = prev_atl * ATL_DECAY + load * (1 - ATL_DECAY)
    tsb     = new_ctl - new_atl

where the decay factors are:

    CTL_DECAY = exp(-1 / 42)  ≈ 0.9763
    ATL_DECAY = exp(-1 /  7)  ≈ 0.8668

This is mathematically equivalent to the EWMA alpha form used in
``fitness_model.compute_fitness_series`` — the decay factor is simply
``1 - alpha``.

Time constants are imported from ``backend.services.fitness_model`` (Layer-1)
so no values are duplicated here.

Worked example
--------------
Start: CTL=50, ATL=70 (form = -20).  Planned load = 20 TSS/day for 14 days.

Because ATL has a shorter time constant (7-day) than CTL (42-day) it decays
faster toward 20.  After 14 rest days ATL approaches 20 while CTL remains
higher than ATL.  TSB (CTL - ATL) rises and becomes positive well before
day 14, illustrating how a taper window improves form.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

from backend.services.fitness_model import (
    ATL_TIME_CONSTANT,
    CTL_TIME_CONSTANT,
    TSB_FRESH_MIN,
    TSB_OPTIMAL_MIN,
)

# ── Decay factors derived from Layer-1 time constants ────────────────────────
# These are the per-day persistence fractions: how much of yesterday's load
# metric carries forward before today's load is blended in.
CTL_DECAY: float = math.exp(-1 / CTL_TIME_CONSTANT)
ATL_DECAY: float = math.exp(-1 / ATL_TIME_CONSTANT)

# ── Expressible score constants ─────────────────────────────────────────
# Linear scale factor applied to the TSB/ceiling ratio when computing the
# expressible form factor.  A value of 1.0 means the factor ranges from 0.0
# (TSB = −ceiling) through 1.0 (TSB = 0) to 2.0 (TSB = ceiling).
EXPRESSIBLE_FORM_FACTOR_SCALE: float = 1.0

# ── B-race tightening constants ─────────────────────────────────────────
# After crossing a B-race date, the athlete has a real race result to anchor
# the projection, so the confidence band is multiplied by this factor (<1.0)
# to reflect the increased certainty.  Full recalibration math is deferred to
# the calibration milestone; see _recalibrate_from_race.
B_RACE_TIGHTENING_FACTOR: float = 0.6


def _recalibrate_from_race() -> None:
    """Stub for full race-result recalibration of the projection model.

    When a B-race result is available the band should be recalibrated using
    the actual performance delta to update the underlying fitness estimates.
    That calculation is intentionally left for a dedicated milestone.

    # TODO: calibration milestone — implement race-result recalibration
    """
    # TODO: calibration milestone — compute delta between predicted and actual
    # race performance and propagate corrections into CTL/ATL estimates.
    raise NotImplementedError(
        "_recalibrate_from_race is reserved for the calibration milestone")


# Scale factor for the square-root confidence band model.  Tune this to
# control the overall magnitude: band(7) ≈ 1.3 days, band(90) ≈ 4.7 days.
CONFIDENCE_BAND_RATE: float = 0.5


def confidence_band_days(horizon: int, b_race_passed: bool = False) -> float:
    """Compute the ± confidence band width (in days) for a projected entry.

    The band models compounding forecast uncertainty that grows with the
    projection horizon.  A square-root growth model is used:

        band = CONFIDENCE_BAND_RATE * sqrt(max(horizon, 0))

    where ``CONFIDENCE_BAND_RATE`` is a scale factor (default 0.5) tuned so
    that a 7-day horizon yields ≈ 1.3 days and a 90-day horizon yields ≈ 4.7
    days of uncertainty.  The square-root function ensures:

    - horizon = 0  → band = 0 exactly (zero uncertainty at the anchor day)
    - band is monotonically non-decreasing for all non-negative horizons
    - growth is concave (uncertainty accumulates rapidly early, then slows)
      which matches the intuition that a 90-day forecast is not 90× worse
      than a 1-day forecast

    B-race tightening
    -----------------
    When *b_race_passed* is ``True`` the raw band is multiplied by
    ``B_RACE_TIGHTENING_FACTOR`` (< 1.0).  Crossing the B-race date gives the
    athlete a real race anchor that reduces forecast uncertainty — the narrower
    band reflects that increased certainty.  Full recalibration from the race
    result is deferred to a dedicated milestone; see
    ``_recalibrate_from_race``.

    Parameters
    ----------
    horizon:
        Number of days into the future from the anchor (start_date).  Values
        ≤ 0 return 0.
    b_race_passed:
        When ``True`` the band is tightened by ``B_RACE_TIGHTENING_FACTOR``
        to reflect reduced uncertainty after a B-race result is available.

    Returns
    -------
    float — the ± band width in days (always ≥ 0).
    """
    if horizon <= 0:
        return 0
    band = CONFIDENCE_BAND_RATE * math.sqrt(horizon)
    if b_race_passed:
        band *= B_RACE_TIGHTENING_FACTOR
    return band


def project_fitness(
    planned_load: list[float],
    start_ctl: float,
    start_atl: float,
    start_date: date,
    b_race_date: Optional[date] = None,
) -> dict[date, dict[str, float]]:
    """Roll CTL/ATL/TSB forward from *start_date* using *planned_load*.

    Parameters
    ----------
    planned_load:
        Ordered list of TSS values, one per day.  Day 1 of the projection uses
        ``planned_load[0]``, day 2 uses ``planned_load[1]``, and so on.
        An empty list returns an empty dict.
    start_ctl:
        CTL value on *start_date* (the day before the first projected day).
    start_atl:
        ATL value on *start_date* (the day before the first projected day).
    start_date:
        Anchor date.  The first entry in the returned series is
        ``start_date + 1 day``; the last is
        ``start_date + len(planned_load) days``.
    b_race_date:
        Optional date of a B-race.  For projected days that fall strictly after
        this date the confidence band is tightened via
        ``B_RACE_TIGHTENING_FACTOR`` to reflect reduced uncertainty from
        having a real race anchor.
        Pass ``None`` (the default) to leave the band unchanged.

    Returns
    -------
    dict mapping ``date`` → ``{"ctl": float, "atl": float, "tsb": float,
    "confidence_band": float}``.
    The dict contains exactly ``len(planned_load)`` entries, one per day, with
    no gaps.  An empty *planned_load* returns an empty dict.
    """
    series: dict[date, dict[str, float]] = {}
    ctl = start_ctl
    atl = start_atl
    for i, load in enumerate(planned_load):
        ctl = ctl * CTL_DECAY + load * (1 - CTL_DECAY)
        atl = atl * ATL_DECAY + load * (1 - ATL_DECAY)
        tsb = ctl - atl
        horizon = i + 1
        day = start_date + timedelta(days=horizon)
        # Tighten the band on days that fall strictly after the B-race; the
        # race result provides an anchor that reduces forecast uncertainty.
        b_race_passed = b_race_date is not None and day > b_race_date
        series[day] = {
            "ctl": ctl,
            "atl": atl,
            "tsb": tsb,
            "confidence_band": confidence_band_days(
                horizon,
                b_race_passed=b_race_passed,
            ),
        }
    return series


def tsb_form_factor(projected_tsb: float, ceiling_tsb: float) -> float:
    """Compute the TSB form factor for the expressible score.

    The factor scales linearly with the ratio of projected_tsb to ceiling_tsb:

        factor = 1.0 + (projected_tsb / ceiling_tsb) \
            * EXPRESSIBLE_FORM_FACTOR_SCALE

    Properties:
    - TSB = 0          → factor = 1.0   (neutral; expressible = base score)
    - TSB = ceiling    → factor > 1.0   (supercompensation peak)
    - TSB < 0          → factor < 1.0   (fatigue suppression)

    Parameters
    ----------
    projected_tsb:
        The TSB value on a given projected date (CTL − ATL).
    ceiling_tsb:
        The maximum TSB the athlete can realistically achieve.  Must be > 0;
        if not, the function returns a neutral factor of 1.0 to avoid
        division by zero.

    Returns
    -------
    float — the multiplicative form factor.
    """
    if ceiling_tsb <= 0:
        return 1.0
    return 1.0 + (projected_tsb / ceiling_tsb) * EXPRESSIBLE_FORM_FACTOR_SCALE


def compute_expressible_score(
    base_score: float,
    projected_tsb: float,
    ceiling_tsb: float,
) -> float:
    """Apply the TSB form factor to a base Endurance/Speed score.

    Multiplies *base_score* by the TSB form factor derived from
    *projected_tsb* and *ceiling_tsb*.  When projected_tsb = 0 the result
    equals base_score exactly; positive TSB amplifies, negative suppresses.

    Parameters
    ----------
    base_score:
        The raw Endurance or Speed score before applying form adjustment.
    projected_tsb:
        The TSB value on the date being evaluated.
    ceiling_tsb:
        The athlete's ceiling TSB — the maximum achievable TSB for use as the
        normalisation denominator.

    Returns
    -------
    float — the expressible score for that date.
    """
    return base_score * tsb_form_factor(projected_tsb, ceiling_tsb)


def apply_expressible_scores(
    projection_series: "dict[date, dict[str, float]]",
    base_score: float,
    ceiling_tsb: float,
) -> "dict[date, dict[str, float]]":
    """Annotate each day in a projection series with an expressible_score.

    Iterates over the output of :func:`project_fitness` and adds an
    ``expressible_score`` key to each day's dict, computed by calling
    :func:`compute_expressible_score` with the day's projected TSB.

    The original projection_series is not mutated; a new dict is returned.

    Parameters
    ----------
    projection_series:
        The output of project_fitness: a dict mapping date → {ctl, atl, tsb}.
    base_score:
        The athlete's base Endurance/Speed score (constant across all dates).
    ceiling_tsb:
        The athlete's ceiling TSB for form-factor normalisation.

    Returns
    -------
    dict mapping date → {ctl, atl, tsb, expressible_score}.  The
    ``expressible_score`` values are rounded to 2 decimal places.
    """
    result: dict[date, dict[str, float]] = {}
    for day, data in projection_series.items():
        expressible = compute_expressible_score(
            base_score, data["tsb"], ceiling_tsb)
        result[day] = {**data, "expressible_score": round(expressible, 2)}
    return result


# ── Riegel race-equivalence ─────────────────────────────────────────────

# Riegel exponent used for cross-distance time prediction.
# t2 = t1 * (d2/d1)^RIEGEL_EXPONENT
RIEGEL_EXPONENT: float = 1.06


def compute_half_equivalent(
    estimated_finish_seconds: "Optional[int]",
    distance_km: "Optional[float]",
) -> "Optional[int]":
    """Predict finish time for half the race distance using the Riegel formula.

    Applies the Riegel race-equivalence exponent so that longer distances are
    proportionally harder:

        half_time = finish_time * 0.5^RIEGEL_EXPONENT

    Parameters
    ----------
    estimated_finish_seconds:
        Predicted full-race finish time in seconds.  None returns None.
    distance_km:
        Race distance in kilometres.  Must be positive; None or ≤0 returns
        None.

    Returns
    -------
    Rounded integer seconds for half the race distance, or None on invalid
    input.
    """
    if estimated_finish_seconds is None or distance_km is None:
        return None
    if distance_km <= 0:
        return None
    return int(round(estimated_finish_seconds * (0.5 ** RIEGEL_EXPONENT)))


# ── Fitness band ────────────────────────────────────────────────────────

def fitness_band_from_tsb(tsb: float) -> str:
    """Classify TSB into a fitness band label using readiness thresholds.

    Uses the same TSB band constants as ``fitness_model._readiness_label`` so
    projection and fitness-model layers agree on band boundaries.

    Parameters
    ----------
    tsb:
        Training Stress Balance (CTL − ATL) value.

    Returns
    -------
    One of "Fresh", "Optimal", or "Fatigued".
    """
    if tsb >= TSB_FRESH_MIN:
        return "Fresh"
    if tsb >= TSB_OPTIMAL_MIN:
        return "Optimal"
    return "Fatigued"


# ── Plan projection payload assembly ─────────────────────────────────────────

def _format_hhmmss(total_seconds: int) -> str:
    """Format non-negative integer seconds as 'HH:MM:SS'."""
    seconds = abs(total_seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_plan_projection_payload(
    start_ctl: float,
    start_atl: float,
    start_date: date,
    planned_load: "list[float]",
    races: "list[dict]",
    thresholds: "Optional[dict]",
    body_modifier: float = 1.0,
    b_race_result: "Optional[dict]" = None,
    current_score: "Optional[float]" = None,
) -> dict:
    """Assemble the full projection payload for /plans/{plan_id}/projection.

    Pure function — no database access.  All data must be pre-fetched by the
    calling layer (router or service).

    Parameters
    ----------
    start_ctl:
        Athlete's CTL on start_date (the day before the first projected day).
    start_atl:
        Athlete's ATL on start_date.
    start_date:
        Anchor date.  The projection runs from start_date+1 for
        len(planned_load) days.
    planned_load:
        Ordered list of TSS values, one per projected day.
    races:
        List of race dicts, each containing at minimum:
        ``"date"`` (date or ISO string), ``"distance_km"`` (float or None),
        ``"name"`` (str, optional).
    thresholds:
        User preference dict.  Must contain ``"threshold_pace_seconds_per_km"``
        to compute non-null estimated times.  None yields null estimates.
    body_modifier:
        Multiplicative factor applied to the power-to-weight score used in
        race finish-time estimation.  1.0 is neutral (default — no regression
        for athletes without body composition data).  Values > 1.0 improve
        (lighter athlete, better power-to-weight); < 1.0 reduce it.  Use
        ``backend.services.body_modifier.compute_body_modifier`` to derive
        this value.
    b_race_result:
        Optional dict representing the most recent past B race with an actual
        result.  When provided, race projections for dates strictly after
        ``b_race_result["race_date"]`` use the ceiling derived from the actual
        B race performance rather than the CTL-based ceiling.  This re-anchors
        forward projections to the athlete's expressed race-day fitness.
        Expected keys: ``race_date`` (date), ``actual_time_seconds`` (int),
        ``distance_km`` (float).  Pass ``None`` (the default) to use the
        CTL-based ceiling for all dates (AC4 — deleting the B race reverts).

    Returns
    -------
    dict with keys:
        ``ctl``   — list of floats (one per projected day)
        ``atl``   — list of floats
        ``tsb``   — list of floats
        ``races`` — list of dicts, one per race, each with
                    ``estimated_time``, ``estimated_finish_seconds``,
                    ``half_equivalent``, ``half_equivalent_seconds``,
                    ``date``, ``distance_km``, ``name``
        ``band``  — fitness band string from TSB (start_ctl − start_atl)
    """
    from backend.services.score_ceiling import (
        projected_ctl_to_score_ceiling,
        ceiling_from_b_race_result,
    )
    from backend.services.race_finish_estimator import (
        score_to_estimated_finish_time,
    )

    # Pre-compute B-race ceiling if a past B race result is available
    # (#1162). The ceiling is derived by inverting the score-to-pace mapping,
    # anchoring projections after the B race date to the expressed result.
    _b_race_date: Optional[date] = None
    _b_race_ceiling: Optional[dict] = None
    if b_race_result is not None and isinstance(thresholds, dict):
        tp = thresholds.get("threshold_pace_seconds_per_km")
        if tp is not None and float(tp) > 0:
            raw_date = b_race_result.get("race_date")
            if raw_date is not None:
                _b_race_date = (
                    raw_date if isinstance(raw_date, date)
                    else date.fromisoformat(str(raw_date))
                )
                _b_race_ceiling = ceiling_from_b_race_result(
                    b_race_result["actual_time_seconds"],
                    b_race_result["distance_km"],
                    float(tp),
                )

    series = project_fitness(planned_load, start_ctl, start_atl, start_date)

    sorted_dates = sorted(series.keys())
    ctl_list = [round(series[d]["ctl"], 2) for d in sorted_dates]
    atl_list = [round(series[d]["atl"], 2) for d in sorted_dates]
    tsb_list = [round(series[d]["tsb"], 2) for d in sorted_dates]

    last_proj_date = sorted_dates[-1] if sorted_dates else start_date

    race_projections = []
    for race in races:
        race_date = race["date"]
        if isinstance(race_date, str):
            race_date = date.fromisoformat(race_date)
        dist = race.get("distance_km")

        if race_date in series:
            projected_ctl = series[race_date]["ctl"]
        elif sorted_dates:
            projected_ctl = series[last_proj_date]["ctl"]
        else:
            projected_ctl = start_ctl

        # Use B-race-anchored ceiling for dates strictly after the B race date
        # (AC2 — re-anchor from the race date); fall back to CTL-based ceiling
        # for dates on or before the B race date (AC3 — no retroactive change).
        if (
            _b_race_ceiling is not None
            and _b_race_date is not None
            and race_date > _b_race_date
        ):
            ceiling = _b_race_ceiling
        else:
            # VDOT-aware CTL ceiling: kept sane relative to the athlete's current
            # demonstrated score and any real race result.
            _race_ceil_val = (
                _b_race_ceiling["endurance_ceiling"]
                if isinstance(_b_race_ceiling, dict) else None
            )
            ceiling = projected_ctl_to_score_ceiling(
                projected_ctl,
                current_score=current_score,
                race_ceiling=_race_ceil_val,
            )
        # Apply the power-to-weight body modifier to the projected endurance
        # score before converting to a race finish time estimate.
        score = ceiling["endurance_ceiling"] * body_modifier

        est = score_to_estimated_finish_time(score, thresholds, dist)
        est_seconds = est["estimated_finish_seconds"]
        est_time = est["estimated_finish_time"]

        half_seconds = compute_half_equivalent(est_seconds, dist)
        half_time = _format_hhmmss(
            half_seconds) if half_seconds is not None else None

        race_projections.append({
            "date": str(race_date),
            "name": race.get("name") or "",
            "distance_km": dist,
            "estimated_time": est_time,
            "estimated_finish_seconds": est_seconds,
            "half_equivalent": half_time,
            "half_equivalent_seconds": half_seconds,
        })

    current_tsb = start_ctl - start_atl
    band = fitness_band_from_tsb(current_tsb)

    return {
        "ctl": ctl_list,
        "atl": atl_list,
        "tsb": tsb_list,
        "races": race_projections,
        "band": band,
    }
