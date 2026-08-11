"""
Race-time projection for the coach plan — deterministic, zero LLM calls.

ponytail: parked for race finish SoT (Phase D). Production Coach Dream /
coach export use ``race_finish_estimate.estimate_race_finish``. This module's
``race_projection`` (Riegel + CTL-ramp) remains for tests (#1503) and
``_band_seconds`` (export no-race fallback). Do not wire ``race_projection``
into new surfaces.

Maps recent running efforts to two finish-time forecasts:

- current_predicted_sec: Riegel-formula projection from the athlete's best
  recent effort, weight-adjusted to the athlete's present body mass.

- plan_predicted_sec: extends the current prediction forward through the
  coach-plan CTL ramp to race week, applying the CTL→pace improvement model
  and the target-weight adjustment.

Model constants
---------------
RIEGEL_EXPONENT: float = 1.06
    The Riegel fatigue exponent, imported from ``backend.services.riegel``.
    Governs how much harder a longer race is relative to a shorter reference
    effort: T2 = T1 * (D2 / D1) ** 1.06.  Fixed per the original Riegel model.

WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG: float = 1.5
    Pace adjustment for body-mass change, in seconds per km per kg of
    difference between current weight and the weight recorded at effort time.
    Based on biomechanical economy models: running economy improves by
    approximately 1 s/km per km per kilogram of mass lost.  Positive delta_kg
    (heavier now than at effort time) → slower predicted pace (more seconds);
    negative delta_kg (lighter now) → faster predicted pace.

CTL_PACE_IMPROVEMENT_SLOPE: float = 0.07
    Seconds-per-km reduction per unit of CTL gained above the current baseline.
    Coefficient calibrated so that a 10-point CTL gain (e.g. 60 → 70 TSS/day)
    translates to roughly 1.5 % pace improvement for a 4:45/km athlete at
    half-marathon distance: 0.07 s/km × 10 CTL units × 21.1 km ≈ 14.7 s total.
    Applied multiplicatively when converting projected CTL to a pace delta.

BAND_BASE_SEC: float = 300.0
    Confidence-band base (seconds) at half-marathon distance for a single
    qualifying effort.  The actual band is derived as
    max(BAND_MIN_SEC, BAND_BASE_SEC / sqrt(n_efforts)) × (race_km / 21.0975).
    More qualifying efforts narrow the band; sparse data widens it.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from backend.services.riegel import RIEGEL_EXPONENT, HALF_MARATHON_KM  # noqa: F401 (re-exported)
from backend.services.projection import project_fitness
from backend.utils.time import today_bangkok

# ── Model constants ───────────────────────────────────────────────────────────

WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG: float = 1.5
"""Pace change (s/km) per kg of body-mass difference between current and effort weight."""

CTL_PACE_IMPROVEMENT_SLOPE: float = 0.07
"""Pace reduction (s/km) per CTL point gained above the current baseline."""

BAND_BASE_SEC: float = 300.0
"""Base confidence band (seconds) for a single qualifying effort at HM distance."""

BAND_MIN_SEC: float = 30.0
"""Floor for the confidence band regardless of effort count."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _qualifying_efforts(efforts: list[dict]) -> list[dict]:
    """Return efforts that have a positive time_seconds and distance_km."""
    out = []
    for e in efforts:
        t = e.get("time_seconds")
        d = e.get("distance_km")
        try:
            if t and d and float(t) > 0 and float(d) > 0:
                out.append(e)
        except (TypeError, ValueError):
            continue
    return out


def _riegel_predict(
    effort: dict,
    race_distance_km: float,
    current_weight_kg: float | None,
) -> float:
    """Project a single effort to target race distance via Riegel + weight adjustment."""
    t = float(effort["time_seconds"])
    d = float(effort["distance_km"])
    projected = t * math.pow(race_distance_km / d, RIEGEL_EXPONENT)

    effort_weight = effort.get("weight_kg")
    if current_weight_kg is not None and effort_weight is not None:
        delta_kg = float(current_weight_kg) - float(effort_weight)
        projected += delta_kg * WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG * race_distance_km

    return projected


def _band_seconds(n_qualifying: int, race_distance_km: float) -> int:
    """Confidence band in seconds: wider for sparse data, scaled to race distance."""
    if n_qualifying <= 0:
        raw = BAND_BASE_SEC
    else:
        raw = BAND_BASE_SEC / math.sqrt(n_qualifying)
    distance_factor = race_distance_km / HALF_MARATHON_KM
    return round(max(BAND_MIN_SEC, raw * distance_factor))


def _phase_name_for_date(phases: list[dict], day: date) -> str | None:
    for p in phases:
        start = p.get("start_date")
        end = p.get("end_date")
        if start and end and start <= day <= end:
            return p.get("name")
    return None


def _phase_start(phases: list[dict], name: str) -> date | None:
    for p in phases:
        if p.get("name") == name:
            return p.get("start_date")
    return None


def _simulate_plan_ctl(
    plan_phases: list[dict],
    current_ctl: float,
    current_atl: float,
    race_date: date,
    today: date,
) -> float:
    """Roll CTL forward through plan phases to race week; return projected CTL.

    Interprets phase names from ``coach_plan._compute_timeline``:
    - "hold"       → daily TSS = current_ctl (steady-state approximation)
    - "ramp"       → compound 5 %/week from hold level
    - "peak block" → hold the highest TSS reached during the ramp
    - "taper"      → 75 % of peak TSS
    - any other    → treat as hold
    """
    days_to_race = (race_date - today).days
    if days_to_race <= 0:
        return current_ctl

    sorted_phases = sorted(
        plan_phases, key=lambda p: p.get("start_date") or today
    )
    hold_tss = float(current_ctl)
    ramp_start = _phase_start(sorted_phases, "ramp")
    peak_tss = hold_tss

    daily_tss: list[float] = []
    for offset in range(days_to_race):
        day = today + timedelta(days=offset + 1)
        phase = _phase_name_for_date(sorted_phases, day)

        if phase == "ramp" and ramp_start is not None:
            weeks_in = max(0.0, (day - ramp_start).days / 7.0)
            tss = hold_tss * (1.05 ** weeks_in)
            peak_tss = max(peak_tss, tss)
        elif phase == "peak block":
            tss = peak_tss
        elif phase == "taper":
            tss = peak_tss * 0.75
        else:
            tss = hold_tss

        daily_tss.append(tss)

    series = project_fitness(
        planned_load=daily_tss,
        start_ctl=current_ctl,
        start_atl=current_atl,
        start_date=today,
    )
    if not series:
        return current_ctl

    # Return CTL at race week (7 days before race_date).
    race_week = race_date - timedelta(days=7)
    for d in sorted(series.keys(), reverse=True):
        if d <= race_week:
            return series[d]["ctl"]
    return series[max(series.keys())]["ctl"]


# ── Public API ────────────────────────────────────────────────────────────────

def race_projection(
    efforts: list[dict],
    *,
    race_distance_km: float,
    current_weight_kg: float | None = None,
    plan_phases: list[dict] | None = None,
    current_ctl: float = 0.0,
    current_atl: float = 0.0,
    race_date: date | None = None,
    target_weight_kg: float | None = None,
    _today: date | None = None,
) -> dict:
    """Project race finish time from recent efforts and coach-plan trajectory.

    ponytail: parked — prefer ``estimate_race_finish`` for coach/export. Kept
    for ``tests/test_race_time_projection__1503.py`` until that suite migrates.

    Parameters
    ----------
    efforts:
        Recent running efforts.  Each dict must contain ``time_seconds``
        (float) and ``distance_km`` (float); optionally ``weight_kg`` (float)
        for the weight-adjustment model.
    race_distance_km:
        Target race distance in kilometres (e.g. 21.0975 for half marathon).
    current_weight_kg:
        Athlete's current body mass (kg).  Used to adjust predictions for
        mass change since effort date.
    plan_phases:
        Coach-plan timeline from ``coach_plan._compute_timeline()`` — a list
        of phase dicts, each with ``name``, ``start_date`` (date),
        ``end_date`` (date).  When provided, ``plan_predicted_sec`` simulates
        the CTL ramp to race week.  When omitted, ``plan_predicted_sec``
        equals ``current_predicted_sec`` (no improvement modelled).
    current_ctl:
        Current Chronic Training Load (TSS/day) — seed for the CTL simulation.
    current_atl:
        Current Acute Training Load (TSS/day) — seed for the ATL simulation.
    race_date:
        Date of the target race.  Required for the CTL simulation path.
    target_weight_kg:
        Target body mass (kg) at race day.  A weight reduction from current
        to target applies an additional pace improvement in ``plan_predicted_sec``.
    _today:
        Override today's date (for deterministic tests).

    Returns
    -------
    On success::

        {
            "current_predicted_sec": int,   # best Riegel projection from efforts
            "plan_predicted_sec":    int,   # projection after plan CTL ramp
            "band_sec":              int,   # ± confidence band (seconds)
            "basis":                 str,   # human-readable input summary
        }

    When no qualifying efforts exist::

        {"unavailable": True, "reason": str}
    """
    today = _today if _today is not None else today_bangkok()
    qualifying = _qualifying_efforts(efforts)

    if not qualifying:
        return {
            "unavailable": True,
            "reason": (
                "No qualifying running efforts found — at least one effort with "
                "a positive time and distance is required to compute a projection."
            ),
        }

    # ── Current prediction ────────────────────────────────────────────────────
    predictions = [
        _riegel_predict(e, race_distance_km, current_weight_kg)
        for e in qualifying
    ]
    current_predicted_sec = round(min(predictions))

    # ── Confidence band ───────────────────────────────────────────────────────
    band_sec = _band_seconds(len(qualifying), race_distance_km)

    # ── Plan prediction ───────────────────────────────────────────────────────
    plan_predicted_sec = current_predicted_sec
    ctl_at_race: float | None = None
    weight_improvement_kg: float | None = None

    if plan_phases and race_date is not None and race_date > today:
        ctl_at_race = _simulate_plan_ctl(
            plan_phases, current_ctl, current_atl, race_date, today
        )
        delta_ctl = max(0.0, ctl_at_race - current_ctl)

        current_pace_per_km = current_predicted_sec / race_distance_km
        pace_improvement = delta_ctl * CTL_PACE_IMPROVEMENT_SLOPE

        weight_pace_improvement = 0.0
        if target_weight_kg is not None and current_weight_kg is not None:
            delta_w = float(current_weight_kg) - float(target_weight_kg)
            if delta_w > 0:
                weight_improvement_kg = delta_w
                weight_pace_improvement = delta_w * WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG

        plan_pace = current_pace_per_km - pace_improvement - weight_pace_improvement
        plan_predicted_sec = round(max(1.0, plan_pace * race_distance_km))

    # ── Basis string ──────────────────────────────────────────────────────────
    n = len(qualifying)
    distances = sorted({float(e["distance_km"]) for e in qualifying})
    dist_range = (
        f"{distances[0]:.1f}–{distances[-1]:.1f} km"
        if len(distances) > 1
        else f"{distances[0]:.1f} km"
    )
    parts = [f"Riegel from {n} effort{'s' if n != 1 else ''} ({dist_range})"]
    if current_weight_kg is not None:
        parts.append(f"weight {current_weight_kg:.1f} kg")
    if ctl_at_race is not None:
        parts.append(f"plan CTL {current_ctl:.0f}→{ctl_at_race:.0f}")
    if weight_improvement_kg is not None:
        parts.append(f"−{weight_improvement_kg:.1f} kg to race")
    basis = "; ".join(parts)

    return {
        "current_predicted_sec": current_predicted_sec,
        "plan_predicted_sec": plan_predicted_sec,
        "band_sec": band_sec,
        "basis": basis,
    }
