"""Revamp performance axes — order, marathon goal profile, staleness (P4-1).

Pure helpers and constants; consumers include score_reader extensions and the
Performance v2 page. See docs/revamp/SPEC.md appendix «Performance axes».
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from backend.services.riegel import HALF_MARATHON_KM, riegel_project
from backend.services.vdot import GRACE_WEEKS

MARATHON_DISTANCE_KM = 42.195

# Fixed radar order (clockwise from top).
PERFORMANCE_AXES: tuple[str, ...] = (
    "endurance",
    "speed",
    "economy",
    "strength",
    "mobility",
    "power_to_weight",
    "durability",
)

MARATHON_PROFILE_MIN_SECONDS = 3 * 3600 + 30 * 60  # 3:30
MARATHON_PROFILE_MAX_SECONDS = 5 * 3600  # 5:00
MARATHON_PROFILE_STEP_SECONDS = 15 * 60

AxisRaw = Mapping[str, float]

# Discrete rows: marathon finish time (seconds) → raw target per axis.
# Values are illustrative anchors; interpolation fills between rows.
_MARATHON_PROFILE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "marathon_seconds": 12600,  # 3:30
        "endurance_target_score": 74.0,
        "speed_target_score": 72.0,
        "leg_spring_stiffness_kn_m": 10.2,
        "ground_contact_time_ms": 248.0,
        "form_power_ratio": 0.23,
        "strength_mean_ratio": 1.0,
        "mobility_target_score": 62.0,
        "power_to_weight_w_per_kg": 3.2,
        "durability_decoupling_median_pct": 3.0,
    },
    {
        "marathon_seconds": 13500,  # 3:45
        "endurance_target_score": 70.0,
        "speed_target_score": 68.0,
        "leg_spring_stiffness_kn_m": 9.8,
        "ground_contact_time_ms": 252.0,
        "form_power_ratio": 0.24,
        "strength_mean_ratio": 0.97,
        "mobility_target_score": 60.0,
        "power_to_weight_w_per_kg": 3.05,
        "durability_decoupling_median_pct": 3.4,
    },
    {
        "marathon_seconds": 14400,  # 4:00
        "endurance_target_score": 66.0,
        "speed_target_score": 64.0,
        "leg_spring_stiffness_kn_m": 9.4,
        "ground_contact_time_ms": 256.0,
        "form_power_ratio": 0.245,
        "strength_mean_ratio": 0.94,
        "mobility_target_score": 58.0,
        "power_to_weight_w_per_kg": 2.9,
        "durability_decoupling_median_pct": 3.8,
    },
    {
        "marathon_seconds": 15300,  # 4:15
        "endurance_target_score": 62.0,
        "speed_target_score": 60.0,
        "leg_spring_stiffness_kn_m": 9.0,
        "ground_contact_time_ms": 260.0,
        "form_power_ratio": 0.25,
        "strength_mean_ratio": 0.91,
        "mobility_target_score": 56.0,
        "power_to_weight_w_per_kg": 2.75,
        "durability_decoupling_median_pct": 4.2,
    },
    {
        "marathon_seconds": 16200,  # 4:30
        "endurance_target_score": 58.0,
        "speed_target_score": 56.0,
        "leg_spring_stiffness_kn_m": 8.6,
        "ground_contact_time_ms": 265.0,
        "form_power_ratio": 0.255,
        "strength_mean_ratio": 0.88,
        "mobility_target_score": 54.0,
        "power_to_weight_w_per_kg": 2.6,
        "durability_decoupling_median_pct": 4.6,
    },
    {
        "marathon_seconds": 17100,  # 4:45
        "endurance_target_score": 54.0,
        "speed_target_score": 52.0,
        "leg_spring_stiffness_kn_m": 8.2,
        "ground_contact_time_ms": 270.0,
        "form_power_ratio": 0.26,
        "strength_mean_ratio": 0.86,
        "mobility_target_score": 52.0,
        "power_to_weight_w_per_kg": 2.45,
        "durability_decoupling_median_pct": 5.0,
    },
    {
        "marathon_seconds": 18000,  # 5:00
        "endurance_target_score": 50.0,
        "speed_target_score": 48.0,
        "leg_spring_stiffness_kn_m": 7.8,
        "ground_contact_time_ms": 275.0,
        "form_power_ratio": 0.265,
        "strength_mean_ratio": 0.84,
        "mobility_target_score": 50.0,
        "power_to_weight_w_per_kg": 2.3,
        "durability_decoupling_median_pct": 5.4,
    },
)

_PROFILE_FIELD_KEYS = tuple(
    k for k in _MARATHON_PROFILE_ROWS[0] if k != "marathon_seconds"
)


def marathon_profile_rows() -> Sequence[dict[str, Any]]:
    """Return the discrete marathon goal profile table (copy-safe for readers)."""
    return _MARATHON_PROFILE_ROWS


def _clamp_marathon_seconds(seconds: int) -> int:
    return max(MARATHON_PROFILE_MIN_SECONDS, min(MARATHON_PROFILE_MAX_SECONDS, seconds))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def interpolate_marathon_profile(marathon_seconds: int) -> dict[str, float]:
    """Linearly interpolate raw axis targets for a marathon finish time (seconds)."""
    sec = _clamp_marathon_seconds(int(marathon_seconds))
    rows = _MARATHON_PROFILE_ROWS
    if sec <= rows[0]["marathon_seconds"]:
        return {k: float(rows[0][k]) for k in _PROFILE_FIELD_KEYS}
    if sec >= rows[-1]["marathon_seconds"]:
        return {k: float(rows[-1][k]) for k in _PROFILE_FIELD_KEYS}
    for lo, hi in zip(rows, rows[1:]):
        lo_s, hi_s = lo["marathon_seconds"], hi["marathon_seconds"]
        if lo_s <= sec <= hi_s:
            if hi_s == lo_s:
                t = 0.0
            else:
                t = (sec - lo_s) / (hi_s - lo_s)
            return {k: _lerp(float(lo[k]), float(hi[k]), t) for k in _PROFILE_FIELD_KEYS}
    return {k: float(rows[-1][k]) for k in _PROFILE_FIELD_KEYS}


def goal_time_to_marathon_seconds(
    goal_time_seconds: int | None,
    distance_km: float | None,
) -> int | None:
    """Map an A-race goal to marathon-equivalent seconds for profile lookup."""
    if goal_time_seconds is None or goal_time_seconds <= 0:
        return None
    if distance_km is None or distance_km <= 0:
        return None
    if abs(distance_km - MARATHON_DISTANCE_KM) < 0.5:
        return _clamp_marathon_seconds(int(goal_time_seconds))
    projected = riegel_project(goal_time_seconds, distance_km, MARATHON_DISTANCE_KM)
    if projected is None:
        return None
    return _clamp_marathon_seconds(projected)


def profile_for_race_goal(
    goal_time_seconds: int | None,
    distance_km: float | None,
) -> dict[str, float] | None:
    """Active target profile from race goal time and distance."""
    marathon_sec = goal_time_to_marathon_seconds(goal_time_seconds, distance_km)
    if marathon_sec is None:
        return None
    return interpolate_marathon_profile(marathon_sec)


def profile_label_marathon_time(marathon_seconds: int) -> str:
    """Human marathon time for profile subtitle (e.g. 3:30 marathon profile)."""
    sec = _clamp_marathon_seconds(int(marathon_seconds))
    h, rem = divmod(sec, 3600)
    m = rem // 60
    return f"{h}:{m:02d}"


# ---------------------------------------------------------------------------
# Staleness (distinct from never-measured — see SPEC appendix)
# ---------------------------------------------------------------------------


def anchor_effort_is_stale(anchor_date: date | None, as_of: date) -> bool:
    """Endurance / speed: reuse running_performance anchor rule (GRACE_WEEKS)."""
    if anchor_date is None:
        return True
    age_days = (as_of - anchor_date).days
    return age_days / 7.0 > GRACE_WEEKS


def staleness_durability(qualifying_long_runs_45d: int) -> bool:
    return qualifying_long_runs_45d < 2


def staleness_economy(easy_runs_with_form_28d: int) -> bool:
    return easy_runs_with_form_28d < 5


def staleness_power_to_weight(days_since_weigh_in: int | None) -> bool:
    if days_since_weigh_in is None:
        return True
    return days_since_weigh_in > 14


def staleness_strength(has_anchor_lift_logged_45d: bool) -> bool:
    return not has_anchor_lift_logged_45d


def staleness_mobility(days_since_last_test: int | None) -> bool:
    if days_since_last_test is None:
        return True
    return days_since_last_test > 45


def is_never_measured(score: float | int | None) -> bool:
    return score is None


def axis_radar_eligible(
    *,
    score: float | int | None,
    stale: bool,
) -> bool:
    """Measured (non-null) axes join the radar; never-measured are omitted."""
    return score is not None and not is_never_measured(score)


def axis_focus_ranking_eligible(
    *,
    score: float | int | None,
    stale: bool,
) -> bool:
    """Focus ranking ignores never-measured and stale axes."""
    return score is not None and not stale


def half_marathon_km() -> float:
    """Exported for tests that cross-check riegel half mapping."""
    return HALF_MARATHON_KM