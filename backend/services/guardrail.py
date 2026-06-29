"""
Rate guardrail — stressor ramp and ACWR watchdog.

Exposes ``compute_guardrail``, a pure function that combines the existing
ACWR computation with a week-over-week stressor ramp check to produce a
structured guardrail result.  The result is intended for downstream services
(monthly summary, notifications) that need to surface timely warnings when
an athlete's training load enters a high-risk zone.

All database work belongs to the calling layer.  This module contains no SQL,
file access, or network calls in the pure function.  The thin DB caller
``get_guardrail_result`` is provided for convenience and is separated from the
pure logic to make the pure function independently testable.

Stressor ramp check
-------------------
Three training stressors are tracked:

1. Running load — TSS accumulated from running workouts.
2. Plyometric volume — session count or equivalent volume proxy for
   plyometric-style training.
3. Weight loss rate — magnitude (kg) of body-weight loss over the week.

A stressor is considered "rising sharply" when its week-over-week change
exceeds ``STRESSOR_RAMP_THRESHOLD_PCT`` (default 20 %).  A previous value of
zero is treated as a zero baseline; any positive current value from a zero
baseline counts as a sharp rise.

Guardrail logic
---------------
``guardrail_state`` is ``"warn"`` when **either** condition holds:
  - ``stressors_ramping > 1`` (two or more stressors rising simultaneously)
  - ``acwr_state == "high_risk"`` (ACWR ratio above HIGH_BOUND)

Otherwise ``guardrail_state`` is ``"ok"``.
"""

from __future__ import annotations

from backend.services.acwr import compute_acwr, HIGH_BOUND

# ── Configurable threshold ────────────────────────────────────────────────────
# Week-over-week percentage increase in a stressor that is considered a sharp
# ramp.  A value of 20.0 means a 20 % rise in a single week triggers the flag.
# Override by passing an explicit ramp_threshold_pct to compute_guardrail.
STRESSOR_RAMP_THRESHOLD_PCT: float = 20.0


def _rose_sharply(prev: float, curr: float, threshold_pct: float) -> bool:
    """Return True when curr exceeds prev by more than threshold_pct percent.

    When prev is zero or negative, any positive curr is treated as a sharp rise
    because a meaningful percentage cannot be computed from a zero baseline.

    Worked example:
        prev=100, curr=121, threshold_pct=20 → (121-100)/100*100 = 21 > 20 → True
        prev=100, curr=120, threshold_pct=20 → (120-100)/100*100 = 20, NOT > 20 → False
        prev=0,   curr=1,   threshold_pct=20 → zero baseline, curr > 0 → True
        prev=0,   curr=0,   threshold_pct=20 → zero baseline, curr == 0 → False
    """
    if prev <= 0:
        return curr > 0
    return (curr - prev) / prev * 100 > threshold_pct


def compute_guardrail(
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
    """Compute a training guardrail from ACWR and stressor ramp data.

    This is a pure function — it performs no database access, file reads, or
    network calls.  All database work belongs to the calling layer.

    Parameters
    ----------
    daily_load_series:
        Ordered sequence of daily training stress values (most recent last),
        passed directly to ``compute_acwr``.  At least 28 values are required
        for a meaningful ACWR result.
    running_load_prev_week:
        Total running training stress (TSS) for the week before the current
        window.
    running_load_curr_week:
        Total running training stress (TSS) for the current window week.
    plyometric_volume_prev_week:
        Plyometric session count or volume proxy for the previous week.
    plyometric_volume_curr_week:
        Plyometric session count or volume proxy for the current week.
    weight_loss_rate_prev_week:
        Magnitude of weight loss (kg) in the previous week.  Pass 0 when the
        athlete gained weight or weight data is unavailable.
    weight_loss_rate_curr_week:
        Magnitude of weight loss (kg) in the current week.  Pass 0 when the
        athlete gained weight or weight data is unavailable.
    ramp_threshold_pct:
        Week-over-week percentage increase that classifies a stressor as rising
        sharply.  Defaults to ``STRESSOR_RAMP_THRESHOLD_PCT`` (20 %).  Pass an
        explicit value to override for testing or user configuration.

    Returns
    -------
    dict with exactly these keys:

    ``acwr``
        The ACWR ratio (float) from ``compute_acwr``, or None when the ratio
        cannot be determined (insufficient data, zero chronic load, invalid input).

    ``acwr_state``
        One of ``"detraining"``, ``"productive"``, or ``"high_risk"``, mapped
        from the ACWR band thresholds (LOWER_BOUND and HIGH_BOUND in acwr.py).
        When the ACWR band is ``"baseline_forming"`` or cannot be computed, this
        defaults to ``"productive"`` (safe, non-alarming default).

    ``stressors_ramping``
        Integer count (0–3) of training stressors whose week-over-week change
        exceeds ramp_threshold_pct.  The three tracked stressors are:
        running load, plyometric volume, and weight loss rate.

    ``guardrail_state``
        ``"warn"`` when ``stressors_ramping > 1`` OR ``acwr_state`` is
        ``"high_risk"``; otherwise ``"ok"``.

    ``guardrail_message``
        A plain-English sentence when ``guardrail_state`` is ``"warn"``;
        an empty string when ``guardrail_state`` is ``"ok"``.
    """
    # ── ACWR — reuse existing computation, no duplicate logic ────────────────
    acwr_result = compute_acwr(daily_load_series)
    acwr = acwr_result.get("ratio")
    band = acwr_result.get("band")

    # Map ACWR band to one of the three defined acwr_state values.
    # "baseline_forming" and None (invalid input) default to "productive" so
    # that incomplete data does not trigger a spurious high_risk warning.
    if band in ("detraining", "productive", "high_risk"):
        acwr_state: str = band
    else:
        acwr_state = "productive"

    # ── Stressor ramp check ───────────────────────────────────────────────────
    stressors_ramping: int = sum([
        _rose_sharply(running_load_prev_week, running_load_curr_week, ramp_threshold_pct),
        _rose_sharply(plyometric_volume_prev_week, plyometric_volume_curr_week, ramp_threshold_pct),
        _rose_sharply(weight_loss_rate_prev_week, weight_loss_rate_curr_week, ramp_threshold_pct),
    ])

    # ── Guardrail classification ──────────────────────────────────────────────
    is_high_risk_acwr = acwr_state == "high_risk"
    is_multi_stressor = stressors_ramping > 1
    guardrail_state = "warn" if (is_high_risk_acwr or is_multi_stressor) else "ok"

    # ── Plain-English message ─────────────────────────────────────────────────
    if guardrail_state == "ok":
        guardrail_message = ""
    elif is_high_risk_acwr and is_multi_stressor:
        guardrail_message = (
            "Your acute:chronic workload ratio is elevated and multiple training "
            "stressors are ramping simultaneously — reduce overall volume this week "
            "to lower injury risk."
        )
    elif is_high_risk_acwr:
        guardrail_message = (
            "Your acute:chronic workload ratio has entered a high-risk zone — "
            "consider reducing training volume this week to protect against overuse injury."
        )
    else:
        guardrail_message = (
            f"{stressors_ramping} training stressors are increasing sharply at the "
            "same time — ease off on one or more to avoid overuse injury."
        )

    return {
        "acwr": acwr,
        "acwr_state": acwr_state,
        "stressors_ramping": stressors_ramping,
        "guardrail_state": guardrail_state,
        "guardrail_message": guardrail_message,
    }


def get_guardrail_result(user_id: str, as_of_date=None) -> dict:
    """Fetch data from the database and compute the guardrail result.

    This is the thin caller layer: it performs all database reads and delegates
    computation to ``compute_guardrail`` (the pure function).

    Parameters
    ----------
    user_id:
        The authenticated user's ID string.
    as_of_date:
        Reference date for the current week (default: today).

    Returns
    -------
    Same dict shape as ``compute_guardrail``:
    ``acwr``, ``acwr_state``, ``stressors_ramping``, ``guardrail_state``,
    ``guardrail_message``.
    """
    from datetime import date, timedelta

    from sqlalchemy import text

    from backend.db import engine
    from backend.services.training_load import daily_tss_series

    today = as_of_date if as_of_date is not None else date.today()

    # Current ISO week: Monday through today
    curr_week_start = today - timedelta(days=today.weekday())
    curr_week_end = today

    # Previous week: the 7 days immediately before the current week
    prev_week_start = curr_week_start - timedelta(days=7)
    prev_week_end = curr_week_start - timedelta(days=1)

    # ACWR requires at least 28 days; use 35 to cover the full prior-week window
    acwr_start = today - timedelta(days=35)
    acwr_series_rows = daily_tss_series(str(user_id), acwr_start, today)
    acwr_series = [tss for _, tss in acwr_series_rows]

    # ── Running load (TSS from Run workouts) per week ─────────────────────────
    run_sql = text(
        """
        SELECT workout_date, COALESCE(SUM(tss), 0)::float AS run_tss
        FROM workouts
        WHERE user_id = :uid
          AND workout_type = 'Run'
          AND tss IS NOT NULL
          AND workout_date BETWEEN :from_date AND :to_date
        GROUP BY workout_date
        """
    )
    with engine.connect() as conn:
        curr_run_rows = conn.execute(
            run_sql,
            {"uid": str(user_id), "from_date": curr_week_start, "to_date": curr_week_end},
        ).fetchall()
        prev_run_rows = conn.execute(
            run_sql,
            {"uid": str(user_id), "from_date": prev_week_start, "to_date": prev_week_end},
        ).fetchall()

    running_load_curr = float(sum(r[1] for r in curr_run_rows))
    running_load_prev = float(sum(r[1] for r in prev_run_rows))

    # ── Plyometric volume (session count for plyometric workout type) ─────────
    plyo_sql = text(
        """
        SELECT COUNT(*)::float
        FROM workouts
        WHERE user_id = :uid
          AND LOWER(workout_type) LIKE '%plyo%'
          AND workout_date BETWEEN :from_date AND :to_date
        """
    )
    with engine.connect() as conn:
        plyo_curr = float(
            conn.execute(
                plyo_sql,
                {"uid": str(user_id), "from_date": curr_week_start, "to_date": curr_week_end},
            ).scalar()
            or 0
        )
        plyo_prev = float(
            conn.execute(
                plyo_sql,
                {"uid": str(user_id), "from_date": prev_week_start, "to_date": prev_week_end},
            ).scalar()
            or 0
        )

    # ── Weight loss rate (magnitude of weekly weight drop) ────────────────────
    weight_sql = text(
        """
        SELECT entry_date, weight_kg
        FROM weight_entries
        WHERE user_id = :uid
          AND entry_date BETWEEN :from_date AND :to_date
        ORDER BY entry_date ASC
        """
    )
    with engine.connect() as conn:
        curr_weight_rows = conn.execute(
            weight_sql,
            {"uid": str(user_id), "from_date": curr_week_start, "to_date": curr_week_end},
        ).fetchall()
        prev_weight_rows = conn.execute(
            weight_sql,
            {"uid": str(user_id), "from_date": prev_week_start, "to_date": prev_week_end},
        ).fetchall()

    def _loss_rate(rows) -> float:
        """Return the magnitude of weight loss over the period (0 if gaining)."""
        if len(rows) < 2:
            return 0.0
        first_kg = float(rows[0][1])
        last_kg = float(rows[-1][1])
        change = last_kg - first_kg
        return max(0.0, -change)

    weight_loss_curr = _loss_rate(curr_weight_rows)
    weight_loss_prev = _loss_rate(prev_weight_rows)

    return compute_guardrail(
        acwr_series,
        running_load_prev_week=running_load_prev,
        running_load_curr_week=running_load_curr,
        plyometric_volume_prev_week=plyo_prev,
        plyometric_volume_curr_week=plyo_curr,
        weight_loss_rate_prev_week=weight_loss_prev,
        weight_loss_rate_curr_week=weight_loss_curr,
    )
