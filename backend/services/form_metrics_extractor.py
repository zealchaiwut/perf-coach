"""Extract per-run Stryd running-dynamics from a stryd_activities row.

Key mapping (calendar summary verified 2026-06-17; form power verified against
a live UAT streams payload 2026-11-24 — the calendar JSON has no
``average_form_power`` / ``form_power`` key):

    form_metrics key              | run_form_metrics column
    ──────────────────────────────┼─────────────────────────
    "ground_contact_time_ms"      | gct_ms
    "leg_spring_stiffness"        | lss_kn_m   (kN/m, Stryd native)
    "vertical_oscillation_cm"     | vertical_oscillation_cm
    "cadence_spm"                 | cadence_spm
    (stryd_activities.avg_power_w)| power_w
    "form_power_w" / avg_power_w  | form_power_ratio  (dimensionless, P4-3)
    (or a stored "form_power_ratio" key when the payload carries it directly)

``form_power_w`` is the mean of the Stryd streams ``vertical_power_list``
(Stryd's form-power channel). Summary keys are accepted if they ever appear.

All values are nullable; a missing / unparseable payload is silently skipped
(returns None) and never causes a sync failure.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def form_power_w_from_streams(streams: dict | None) -> float | None:
    """Mean of Stryd ``vertical_power_list`` (form power), ignoring zeros."""
    if not isinstance(streams, dict):
        return None
    series = streams.get("vertical_power_list")
    if not isinstance(series, list):
        return None
    nums = [_coerce_float(x) for x in series]
    nums = [x for x in nums if x is not None and x > 0]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 2)


def _derive_form_power_ratio(form_metrics: dict, power_w: float | None) -> float | None:
    """Form power / running power. A direct ``form_power_ratio`` key wins."""
    direct = _coerce_float(form_metrics.get("form_power_ratio"))
    if direct is not None and direct > 0:
        return round(direct, 4)
    form_power_w = _coerce_float(form_metrics.get("form_power_w"))
    if form_power_w is None or power_w is None or power_w <= 0 or form_power_w < 0:
        return None
    return round(form_power_w / power_w, 4)


def extract_form_metrics_row(
    *,
    user_id: str,
    stryd_activity_pk: str,
    run_date,
    form_metrics: dict | None,
    avg_power_w: int | None,
    workout_id: str | None = None,
) -> dict | None:
    """Map a stryd_activities row to a run_form_metrics insert dict.

    Returns None when the payload yields no extractable metric (all columns
    would be NULL except identity columns) so callers can skip the row.
    """
    if not isinstance(form_metrics, dict):
        form_metrics = {}

    gct_ms = _coerce_float(form_metrics.get("ground_contact_time_ms"))
    lss_kn_m = _coerce_float(form_metrics.get("leg_spring_stiffness"))
    vertical_oscillation_cm = _coerce_float(form_metrics.get("vertical_oscillation_cm"))
    cadence_spm = _coerce_float(form_metrics.get("cadence_spm"))
    power_w = _coerce_float(avg_power_w)
    form_power_ratio = _derive_form_power_ratio(form_metrics, power_w)

    if all(
        v is None
        for v in (gct_ms, lss_kn_m, vertical_oscillation_cm, cadence_spm, power_w, form_power_ratio)
    ):
        return None

    return {
        "user_id": str(user_id),
        "stryd_activity_pk": str(stryd_activity_pk),
        "workout_id": str(workout_id) if workout_id else None,
        "run_date": run_date,
        "gct_ms": gct_ms,
        "lss_kn_m": lss_kn_m,
        "vertical_oscillation_cm": vertical_oscillation_cm,
        "cadence_spm": cadence_spm,
        "power_w": power_w,
        "form_power_ratio": form_power_ratio,
    }
