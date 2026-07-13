"""Extract per-run Stryd running-dynamics from a stryd_activities row.

Key mapping (verified against live Stryd calendar API 2026-06-17 via stryd_sync.py
map_stryd_activity — these are the keys stored in stryd_activities.form_metrics JSONB):

    form_metrics key              | run_form_metrics column
    ──────────────────────────────┼─────────────────────────
    "ground_contact_time_ms"      | gct_ms
    "leg_spring_stiffness"        | lss_kn_m   (kN/m, Stryd native)
    "vertical_oscillation_cm"     | vertical_oscillation_cm
    "cadence_spm"                 | cadence_spm
    (stryd_activities.avg_power_w)| power_w

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

    if all(v is None for v in (gct_ms, lss_kn_m, vertical_oscillation_cm, cadence_spm, power_w)):
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
    }
