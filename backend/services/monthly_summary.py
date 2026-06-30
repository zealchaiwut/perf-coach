"""
Monthly summary service.

Thin composition layer that assembles a monthly training summary including
the guardrail result from ``backend.services.guardrail``.  Importing this
module creates no circular dependency because ``guardrail`` depends only on
``acwr`` (a pure-function module with no DB or app imports).

Downstream callers (API endpoints, notification jobs) should call
``compute_monthly_summary`` for a pre-assembled dict that includes
``guardrail_state`` and ``guardrail_message`` alongside any other summary
fields this module accumulates over time.
"""

from __future__ import annotations

from backend.services.guardrail import compute_guardrail, STRESSOR_RAMP_THRESHOLD_PCT


def compute_monthly_summary(
    daily_load_series,
    *,
    running_load_prev_week: float = 0.0,
    running_load_curr_week: float = 0.0,
    plyometric_volume_prev_week: float = 0.0,
    plyometric_volume_curr_week: float = 0.0,
    weight_loss_rate_prev_week: float = 0.0,
    weight_loss_rate_curr_week: float = 0.0,
    ramp_threshold_pct: float = STRESSOR_RAMP_THRESHOLD_PCT,
) -> dict:
    """Compute a monthly training summary including guardrail watchdog fields.

    This is a pure, side-effect-free function.  Database access belongs to the
    calling layer, which should supply pre-computed stressor values.

    Parameters
    ----------
    daily_load_series:
        Ordered sequence of daily TSS values (most recent last), covering at
        least 28 days for a meaningful ACWR result.
    running_load_prev_week, running_load_curr_week:
        Total running TSS for the previous and current week.
    plyometric_volume_prev_week, plyometric_volume_curr_week:
        Plyometric session count or volume proxy for each week.
    weight_loss_rate_prev_week, weight_loss_rate_curr_week:
        Magnitude of body-weight loss (kg) in each week; 0 when gaining or
        data is unavailable.
    ramp_threshold_pct:
        Week-over-week percentage increase threshold for stressor ramp
        detection.  Defaults to ``STRESSOR_RAMP_THRESHOLD_PCT`` (20 %).

    Returns
    -------
    dict with at minimum:

    ``guardrail_state``
        ``"warn"`` or ``"ok"`` — see ``compute_guardrail`` for full logic.
    ``guardrail_message``
        Plain-English warning sentence, or empty string when state is ``"ok"``.
    ``acwr``
        Numeric ACWR ratio or None.
    ``acwr_state``
        One of ``"detraining"``, ``"productive"``, ``"high_risk"``.
    ``stressors_ramping``
        Integer count (0–3) of stressors that rose sharply this week.
    """
    guardrail = compute_guardrail(
        daily_load_series,
        running_load_prev_week=running_load_prev_week,
        running_load_curr_week=running_load_curr_week,
        plyometric_volume_prev_week=plyometric_volume_prev_week,
        plyometric_volume_curr_week=plyometric_volume_curr_week,
        weight_loss_rate_prev_week=weight_loss_rate_prev_week,
        weight_loss_rate_curr_week=weight_loss_rate_curr_week,
        ramp_threshold_pct=ramp_threshold_pct,
    )
    return {
        "guardrail_state": guardrail["guardrail_state"],
        "guardrail_message": guardrail["guardrail_message"],
        "acwr": guardrail["acwr"],
        "acwr_state": guardrail["acwr_state"],
        "stressors_ramping": guardrail["stressors_ramping"],
    }
