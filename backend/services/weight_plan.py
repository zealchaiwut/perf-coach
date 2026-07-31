"""Weight plan math: interpolation, gap analysis, milestone generation (issue #420)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional


def compute_planned_series(plan, as_of_date) -> dict:
    """Build a daily planned-weight series from a weight plan row.

    Pure function — no DB calls, no I/O, no mutation of inputs.

    Parameters
    ----------
    plan : mapping
        Must supply: ``start_date``, ``start_weight``.
        Rate resolution (first match wins):
        1. ``target_rate_kg_per_week`` — explicit weekly change.
        2. ``goal_weight`` + ``goal_date`` — straight line; rate is implied.
    as_of_date : date
        Upper bound of the generated series.

    Returns
    -------
    dict
        ``{"dates": {date: planned_weight, ...}, "debug": {...}}``

        *dates* covers every day from ``start_date`` up to and including
        ``min(as_of_date, goal_date)``.  String or date keys are consistent
        with the date-key type resolved from ``as_of_date``.

        *debug* always contains ``method`` (``"explicit"`` or ``"implied"``),
        ``rate``, ``start_date``, ``start_weight``.

        On any validation failure the function returns
        ``{"dates": {}, "debug": {"reason": "<explanation>"}}`` and never
        raises.

    Worked example
    --------------
    start_weight=90 kg, target_rate_kg_per_week=-0.4::

        After 14 days (2 full weeks):
            planned = 90 + (14 / 7) * (-0.4) = 90 + 2 * (-0.4) = 89.2 kg

    Plain-words summary of the math
    --------------------------------
    Each day's planned weight = start weight + (days elapsed / 7) × weekly rate.
    The weekly rate is either read directly from the plan or derived from the
    slope of the straight line that connects (start_date, start_weight) and
    (goal_date, goal_weight).  Dividing elapsed days by 7 converts the integer
    day count into fractional weeks so the rate stays in kg-per-week units.
    """
    def _err(reason: str) -> dict:
        return {"dates": {}, "debug": {"reason": reason}}

    # ── validate required fields ──────────────────────────────────────────────
    raw_start_date = plan.get("start_date") if hasattr(plan, "get") else getattr(plan, "start_date", None)
    raw_start_weight = plan.get("start_weight") if hasattr(plan, "get") else getattr(plan, "start_weight", None)

    if raw_start_date is None:
        return _err("start_date is required")
    if raw_start_weight is None:
        return _err("start_weight is required")

    try:
        start_date = _as_date(raw_start_date)
    except (ValueError, TypeError):
        return _err(f"start_date is invalid: {raw_start_date!r}")

    try:
        start_weight = float(raw_start_weight)
    except (ValueError, TypeError):
        return _err(f"start_weight is invalid: {raw_start_weight!r}")

    # ── resolve rate ──────────────────────────────────────────────────────────
    def _get(key):
        return plan.get(key) if hasattr(plan, "get") else getattr(plan, key, None)

    raw_rate = _get("target_rate_kg_per_week")
    raw_goal_weight = _get("goal_weight")
    raw_goal_date = _get("goal_date")

    rate: Optional[float] = None
    method: str
    goal_date: Optional[datetime.date] = None

    if raw_rate is not None:
        try:
            rate = float(raw_rate)
        except (ValueError, TypeError):
            return _err(f"target_rate_kg_per_week is invalid: {raw_rate!r}")
        method = "explicit"
        if raw_goal_date is not None:
            try:
                goal_date = _as_date(raw_goal_date)
            except (ValueError, TypeError):
                pass
    elif raw_goal_weight is not None and raw_goal_date is not None:
        try:
            goal_weight = float(raw_goal_weight)
            goal_date = _as_date(raw_goal_date)
        except (ValueError, TypeError) as exc:
            return _err(f"goal_weight or goal_date is invalid: {exc}")
        total_days = (goal_date - start_date).days
        if total_days == 0:
            return _err("goal_date equals start_date; cannot derive rate")
        rate = (goal_weight - start_weight) / total_days * 7
        method = "implied"
    else:
        return _err(
            "cannot determine planned weight: target_rate_kg_per_week is not set "
            "and goal_weight/goal_date are incomplete"
        )

    # ── determine end date ────────────────────────────────────────────────────
    try:
        end_date = _as_date(as_of_date)
    except (ValueError, TypeError):
        return _err(f"as_of_date is invalid: {as_of_date!r}")

    if goal_date is not None and goal_date < end_date:
        end_date = goal_date

    if end_date < start_date:
        return {
            "dates": {},
            "debug": {
                "method": method,
                "rate": rate,
                "start_date": str(start_date),
                "start_weight": start_weight,
            },
        }

    # ── build series ──────────────────────────────────────────────────────────
    dates: dict = {}
    total_days = (end_date - start_date).days
    for i in range(total_days + 1):
        d = start_date + datetime.timedelta(days=i)
        planned = start_weight + (i / 7) * rate
        dates[d] = round(planned, 6)

    return {
        "dates": dates,
        "debug": {
            "method": method,
            "rate": rate,
            "start_date": str(start_date),
            "start_weight": start_weight,
        },
    }


# ── pure plan-line functions (issue #863) ────────────────────────────────────

def compute_plan_line(plan, today: datetime.date) -> list:
    """Generate the original daily plan line from plan.start_date to yesterday.

    Each point is a dict with keys: date (ISO string), weight_kg (float),
    segment (always "original").  The line covers every calendar day from
    plan.start_date up to but not including today.  Weight at each day is
    linearly interpolated between plan.start_weight_kg and plan.goal_weight_kg
    over the full period from plan.start_date to plan.goal_date.
    """
    start_d = _as_date(plan.start_date)
    goal_d = _as_date(plan.goal_date)
    yesterday = today - datetime.timedelta(days=1)
    end_d = min(yesterday, goal_d)

    points = []
    current = start_d
    while current <= end_d:
        points.append({
            "date": str(current),
            "weight_kg": float(round(_plan_weight_at(plan, current), 4)),
            "segment": "original",
        })
        current += datetime.timedelta(days=1)
    return points


def recompute_plan_from_progress(plan, actual_trend, today: datetime.date) -> tuple:
    """Anchor a new forward plan segment at today's actual trend weight.

    The original segment (plan.start_date to yesterday) is preserved as-is
    from compute_plan_line.  The recomputed segment (today onward) starts at
    actual_trend and advances at the plan rate until plan.goal_date.

    Worked example — user is behind by 1 kg at week four
    ----------------------------------------------------
    Plan: start_weight_kg=90, goal_weight_kg=86, start_date=2026-01-05,
    goal_date=2026-03-30 (12 weeks), target_rate_kg_per_week=0.33.
    today = 2026-02-02 (week 4); plan value at today = 88.67.
    actual_trend = 89.67 (1 kg above plan — behind on a loss plan).

    The forward line restarts from 89.67 on 2026-02-02 and advances at
    minus 0.33 kg per week (loss direction).  It reaches 86 kg on or near
    2026-03-30.  debug.gap_kg is +1.0 (actual minus plan at today).
    debug.rate_source is "plan".

    Math in words
    -------------
    1. Determine rate direction: if goal_weight_kg is less than start_weight_kg
       the plan is a loss plan, so the effective rate is negative; otherwise
       positive.
    2. rate_per_day = effective_rate divided by 7.
    3. For each date from today to goal_date, weight equals actual_trend plus
       rate_per_day multiplied by the number of days elapsed since today.
    4. gap_kg = actual_trend minus the original plan value at today (positive
       means heavier than planned, i.e. behind on a loss plan).

    Parameters
    ----------
    plan
        An object with attributes: start_date, start_weight_kg, goal_weight_kg,
        goal_date (may be None), target_rate_kg_per_week (may be None).
    actual_trend
        Today's actual trend weight in kg (float), or None if unavailable.
    today
        The reference date as datetime.date.

    Returns
    -------
    (points, debug) where:
        points is a list of dicts, each with date, weight_kg, and segment.
        debug is a dict with: actual_trend_used, rate_used_kg_per_week,
        rate_source ("plan" or "derived"), gap_kg, and reason.
    When any required input is missing, returns ([], {"reason": "<description>"}).
    """
    # --- validate required inputs ---
    if actual_trend is None:
        return [], {"reason": "actual_trend is required"}

    if getattr(plan, "goal_date", None) is None:
        return [], {"reason": "plan.goal_date is required"}

    if getattr(plan, "start_date", None) is None:
        return [], {"reason": "plan.start_date is required"}

    if getattr(plan, "start_weight_kg", None) is None:
        return [], {"reason": "plan.start_weight_kg is required"}

    if getattr(plan, "goal_weight_kg", None) is None:
        return [], {"reason": "plan.goal_weight_kg is required"}

    start_d = _as_date(plan.start_date)
    goal_d = _as_date(plan.goal_date)
    start_w = Decimal(str(plan.start_weight_kg))
    goal_w = Decimal(str(plan.goal_weight_kg))

    # --- determine effective rate ---
    raw_rate = getattr(plan, "target_rate_kg_per_week", None)
    if raw_rate is not None:
        rate = Decimal(str(raw_rate))
        rate_source = "plan"
    else:
        total_weeks = Decimal((goal_d - start_d).days) / Decimal(7)
        if total_weeks == 0:
            return [], {"reason": "plan.start_date and plan.goal_date must not be the same"}
        rate = (goal_w - start_w) / total_weeks
        rate_source = "derived"

    # Apply direction: loss plan → rate must be negative; gain plan → positive.
    if goal_w < start_w:
        effective_rate = -abs(rate)
    else:
        effective_rate = abs(rate)

    rate_per_day = effective_rate / Decimal(7)

    # --- original segment (start to yesterday) via compute_plan_line ---
    original_points = compute_plan_line(plan, today)

    # --- gap: actual trend vs plan value at today ---
    plan_today = _plan_weight_at(plan, today)
    gap_kg = float(round(Decimal(str(actual_trend)) - plan_today, 4))

    # --- recomputed forward segment (today to goal_date) ---
    forward_points = []
    actual_dec = Decimal(str(actual_trend))
    current = today
    days_elapsed = 0
    while current <= goal_d:
        w = actual_dec + rate_per_day * days_elapsed
        forward_points.append({
            "date": str(current),
            "weight_kg": float(round(w, 4)),
            "segment": "recomputed",
        })
        current += datetime.timedelta(days=1)
        days_elapsed += 1

    debug = {
        "actual_trend_used": float(actual_trend),
        "rate_used_kg_per_week": float(round(effective_rate, 6)),
        "rate_source": rate_source,
        "gap_kg": gap_kg,
        "reason": "",
    }

    return original_points + forward_points, debug


def _plan_weight_at(plan, on_date: datetime.date) -> Decimal:
    """Linear interpolation of plan weight at a date (clamped at boundaries)."""
    start_d = _as_date(plan.start_date)
    goal_d = _as_date(plan.goal_date)
    start_w = Decimal(str(plan.start_weight_kg))
    goal_w = Decimal(str(plan.goal_weight_kg))

    if on_date <= start_d:
        return start_w
    if on_date >= goal_d:
        return goal_w

    total_days = Decimal((goal_d - start_d).days)
    elapsed = Decimal((on_date - start_d).days)
    t = elapsed / total_days
    return start_w + (goal_w - start_w) * t


def plan_at(target, on_date: datetime.date) -> Decimal:
    """Linear interpolation between start and target weight; clamped at both ends."""
    start_d = _as_date(target.start_date)
    target_d = _as_date(target.target_date)
    start_w = Decimal(str(target.start_weight_kg))
    target_w = Decimal(str(target.target_weight_kg))

    if on_date <= start_d:
        return start_w
    if on_date >= target_d:
        return target_w

    total_days = (target_d - start_d).days
    elapsed = (on_date - start_d).days
    t = Decimal(elapsed) / Decimal(total_days)
    return start_w + (target_w - start_w) * t


def compute_gap(target, session, as_of_date: datetime.date) -> dict:
    """Return gap analysis dict for the given target and date.

    Shape: {plan_today_kg, current_basis_kg, basis, gap_kg, gap_direction}

    ``current_basis_kg`` is resolved by delegating to ``_weight_rollup`` —
    the same "current weight" rule used by the Hermes weight brief
    (``compute_weight_status``) and, via this function, every gap/pace/
    progress consumer in the app. This used to be its own rule (3+ entries
    in the trailing 7 days else the single latest entry within 14 days),
    which could disagree with ``_weight_rollup``'s rule (2+ entries in 7
    days else a wider-window average over up to ``_ROLLUP_LOOKBACK_DAYS``
    days) on identical data. They are now unified on ``_weight_rollup``'s
    rule — the more conservative of the two — see that function's docstring
    for the full contract, including why the label below has three non-null
    values rather than two.

    ``basis`` truthfully reports which branch produced the number:
        'avg_7d'       — the trailing 7-day window itself had >= 2 entries.
        'avg_wide'     — fewer than 2 in 7 days, but >= 2 entries exist
                         somewhere in the wider ``_ROLLUP_LOOKBACK_DAYS``-day
                         lookback; a genuine multi-entry average.
        'single_entry' — exactly one entry exists in the entire lookback;
                         current_basis_kg is that entry's raw value (there
                         is nothing to average against) — this is reported
                         honestly rather than mislabeled 'avg_wide'.
        None           — no entries at all within the lookback (gap_direction
                         is 'no_data' in this case).
    gap_direction: 'behind' | 'ahead' | 'on_plan' | 'no_data'
    """
    from backend.models import WeightEntry  # local import to avoid circular dep

    plan_today = plan_at(target, as_of_date)

    lookback_start = as_of_date - datetime.timedelta(days=_ROLLUP_LOOKBACK_DAYS)
    rows = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == target.user_id,
            WeightEntry.entry_date >= lookback_start,
            WeightEntry.entry_date <= as_of_date,
        )
        .all()
    )
    weight_rows = [(e.entry_date, float(e.weight_kg)) for e in rows]
    rollup = _weight_rollup(weight_rows, as_of_date)
    current_kg = rollup["current_kg"]
    basis_label = rollup["basis"]

    if current_kg is None:
        return {
            "plan_today_kg": float(round(plan_today, 1)),
            "current_basis_kg": None,
            "basis": None,
            "gap_kg": None,
            "gap_direction": "no_data",
        }

    current_basis = Decimal(str(current_kg))
    gap = current_basis - plan_today
    gap_direction = _gap_direction(gap, target)

    return {
        "plan_today_kg": float(round(plan_today, 1)),
        "current_basis_kg": round(current_kg, 2),
        "basis": basis_label,
        "gap_kg": float(round(gap, 2)),
        "gap_direction": gap_direction,
    }


def generate_milestones(target, as_of_date: datetime.date) -> list:
    """Return milestone list: today + 0-2 intermediate stones + goal.

    Each stone: {date, plan_kg, kind}
    Intermediate stones are at 1/3 and 2/3 of remaining days, rounded to 1st of nearest month.
    Collisions are deduped.
    """
    target_d = _as_date(target.target_date)
    remaining_days = (target_d - as_of_date).days

    today_stone = {
        "date": str(as_of_date),
        "plan_kg": float(round(plan_at(target, as_of_date), 1)),
        "kind": "today",
    }
    goal_stone = {
        "date": str(target_d),
        "plan_kg": float(round(Decimal(str(target.target_weight_kg)), 1)),
        "kind": "goal",
    }

    if remaining_days <= 0:
        return [today_stone, goal_stone]

    # Intermediate stones at 1/3 and 2/3 of remaining days
    d1 = as_of_date + datetime.timedelta(days=remaining_days // 3)
    d2 = as_of_date + datetime.timedelta(days=remaining_days * 2 // 3)

    m1 = _snap_to_month_start(d1)
    m2 = _snap_to_month_start(d2)

    seen_dates = {str(as_of_date), str(target_d)}
    intermediates = []
    for ms in [m1, m2]:
        key = str(ms)
        if key in seen_dates:
            continue
        seen_dates.add(key)
        intermediates.append({
            "date": key,
            "plan_kg": float(round(plan_at(target, ms), 1)),
            "kind": "intermediate",
        })

    return [today_stone] + intermediates + [goal_stone]


# ── private helpers ───────────────────────────────────────────────────────────

def _as_date(d) -> datetime.date:
    if isinstance(d, datetime.date):
        return d
    return datetime.date.fromisoformat(str(d))


def _gap_direction(gap: Decimal, target) -> str:
    """Determine gap direction accounting for target type (loss vs gain)."""
    is_loss = Decimal(str(target.target_weight_kg)) < Decimal(str(target.start_weight_kg))
    if abs(gap) <= Decimal("0.2"):
        return "on_plan"
    if is_loss:
        return "behind" if gap > 0 else "ahead"
    return "ahead" if gap > 0 else "behind"


def project_hit_date(target, session, as_of_date: datetime.date) -> Optional[datetime.date]:
    """Extrapolate 7-day pace to project when goal weight will be reached.

    Returns None if pace is zero, insufficient data (<2 entries in window),
    or pace is moving away from the goal.
    """
    from backend.models import WeightEntry  # local import to avoid circular dep

    window_start = as_of_date - datetime.timedelta(days=6)
    entries = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == target.user_id,
            WeightEntry.entry_date >= window_start,
            WeightEntry.entry_date <= as_of_date,
        )
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )

    if len(entries) < 2:
        return None

    first_e = entries[0]
    last_e = entries[-1]
    days_span = (last_e.entry_date - first_e.entry_date).days
    if days_span == 0:
        return None

    # Positive = losing weight; negative = gaining
    kg_change_per_week = (
        Decimal(str(first_e.weight_kg)) - Decimal(str(last_e.weight_kg))
    ) / Decimal(days_span) * 7

    target_w = Decimal(str(target.target_weight_kg))
    is_loss = target_w < Decimal(str(target.start_weight_kg))
    current_w = Decimal(str(last_e.weight_kg))

    if is_loss:
        if kg_change_per_week <= 0:
            return None
        kg_to_go = current_w - target_w
        if kg_to_go <= 0:
            return None
        weeks_needed = kg_to_go / kg_change_per_week
    else:
        if kg_change_per_week >= 0:
            return None
        kg_to_go = target_w - current_w
        if kg_to_go <= 0:
            return None
        weeks_needed = kg_to_go / abs(kg_change_per_week)

    days_needed = int(weeks_needed * 7)
    return as_of_date + datetime.timedelta(days=days_needed)


# ── Hermes weight-brief status (issue: Hermes weight block) ─────────────────
#
# The functions below back the worker's GET /api/weight/status read endpoint.
# They are DB-read functions (like compute_gap/project_hit_date above) rather
# than strictly pure — same established pattern in this module — but they
# never mutate anything and never raise for missing data; every branch has an
# explicit null/None fallback so the read endpoint can always return HTTP 200.
#
# Design rule (do not relax): the brief must never surface a single day's
# weight. current_kg is always a rolling average over several days, and
# trend_7d/trend_28d are always window-average deltas, never a point-to-point
# day-over-day delta.

_ROLLUP_LOOKBACK_DAYS: int = 55
"""Wide enough to cover two full trailing 28-day windows (current + prior)."""


def _weight_rollup(rows: list, as_of_date: datetime.date) -> dict:
    """Pure helper: rows is a list of (entry_date, weight_kg) tuples, any order,
    expected to span at least the trailing _ROLLUP_LOOKBACK_DAYS days from
    as_of_date (callers fetch that window from the DB before calling this).

    Returns {"current_kg", "basis", "trend_7d", "trend_28d"}.

    current_kg: average weight_kg over the trailing 7-day window
    [as_of_date-6, as_of_date]. Falls back to the average of every row given
    (i.e. "whatever's available" over the wider lookback) when the 7-day
    window has fewer than 2 entries, and to None when there are no rows at
    all.

    The rule's whole point is that current_kg is never computed by
    PREFERRING the single most recent entry over other available context —
    when >= 2 entries exist anywhere in the lookback, it is always a genuine
    multi-entry average, never just "whichever reading happened last." That
    said, when the ENTIRE lookback truly contains only one reading, there is
    no other data to average against, and current_kg necessarily equals that
    reading's raw value — no rule can average what isn't there. `basis`
    reports this case honestly (see below) rather than mislabeling it as an
    average that didn't happen.

    basis: which branch produced current_kg —
        "avg_7d"       — the trailing 7-day window itself had >= 2 entries.
        "avg_wide"     — fewer than 2 in 7 days, but >= 2 entries exist
                         somewhere in the wider lookback; current_kg is a
                         genuine average across them.
        "single_entry" — exactly one entry exists in the entire lookback
                         (the trailing 7 days included); current_kg is that
                         entry's raw value — there is nothing to average.
        None           — no entries at all (current_kg is also None).
    This is the single source of truth every other "current weight" call
    site in the app (weight_plan.compute_gap, backend/main.py's Home/
    Weight-page summaries) is unified on, so the label a caller surfaces
    always describes what was actually computed — never "avg_*" when only
    one raw reading exists anywhere.

    trend_7d / trend_28d: (average over the current N-day window) minus
    (average over the immediately preceding N-day window), in kg. None
    whenever either window is empty — always a window-to-window delta, never
    a single day-over-day comparison.
    """
    def _window(start_days_ago: int, end_days_ago: int) -> list:
        lo = as_of_date - datetime.timedelta(days=end_days_ago)
        hi = as_of_date - datetime.timedelta(days=start_days_ago)
        return [w for (d, w) in rows if lo <= d <= hi]

    def _avg(vals: list) -> Optional[float]:
        return round(sum(vals) / len(vals), 2) if vals else None

    window_7 = _window(0, 6)
    if len(window_7) >= 2:
        current_kg = _avg(window_7)
        basis = "avg_7d"
    else:
        # Fallback: fewer than 2 readings in the last week — average whatever
        # is available in the wider lookback rather than surfacing one entry
        # ... unless the wider lookback ALSO has only one entry total, in
        # which case there is nothing to average and the label must say so.
        all_vals = [w for (_, w) in rows]
        current_kg = _avg(all_vals)
        if len(all_vals) >= 2:
            basis = "avg_wide"
        elif len(all_vals) == 1:
            basis = "single_entry"
        else:
            basis = None

    prior_7 = _window(7, 13)
    trend_7d = None
    if window_7 and prior_7:
        trend_7d = round(sum(window_7) / len(window_7) - sum(prior_7) / len(prior_7), 2)

    window_28 = _window(0, 27)
    prior_28 = _window(28, 55)
    trend_28d = None
    if window_28 and prior_28:
        trend_28d = round(sum(window_28) / len(window_28) - sum(prior_28) / len(prior_28), 2)

    return {"current_kg": current_kg, "basis": basis, "trend_7d": trend_7d, "trend_28d": trend_28d}


def compute_current_pace_kg_per_week(target, session, as_of_date: datetime.date) -> Optional[float]:
    """Kg/week pace from weigh-ins logged since the target was created.

    Mirrors the pace calc in backend/main.py's _compute_weight_target_active
    (14-day window, filtered to entries created since the target's creation
    time) so the worker read-API reports the same number the webapp's active-
    target view shows. Kept here as its own directly-callable function rather
    than imported from backend.main, which starts daemon threads at import
    time and must never be imported by the worker (see worker_app.py's module
    docstring).

    Positive = losing weight over the window; negative = gaining. None when
    there's fewer than 1 entry in the window, or a single entry logged on the
    same day the target started (zero elapsed days).
    """
    from backend.models import WeightEntry  # local import to avoid circular dep

    cutoff_14 = as_of_date - datetime.timedelta(days=14)
    entries_14 = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == target.user_id,
            WeightEntry.entry_date >= cutoff_14,
            WeightEntry.created_at >= target.created_at,
        )
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )

    if len(entries_14) >= 2:
        first_e, last_e = entries_14[0], entries_14[-1]
        days_span = (last_e.entry_date - first_e.entry_date).days
        if days_span <= 0:
            return None
        kg_change = float(first_e.weight_kg) - float(last_e.weight_kg)
        return round(kg_change / days_span * 7, 4)

    if len(entries_14) == 1:
        start_date = _as_date(target.start_date)
        days_elapsed = (as_of_date - start_date).days
        if days_elapsed <= 0:
            return None
        kg_change = float(target.start_weight_kg) - float(entries_14[0].weight_kg)
        return round(kg_change / days_elapsed * 7, 4)

    return None


def compute_required_pace_kg_per_week(target, session, as_of_date: datetime.date) -> Optional[float]:
    """Required kg/week pace to reach target.target_date, based on the same
    current-basis (_weight_rollup's rule: 7d avg when >= 2 entries, else a
    wider-lookback average) compute_gap already uses. None once target_date
    has passed (weeks_remaining <= 0).
    """
    target_date = _as_date(target.target_date)
    days_remaining = (target_date - as_of_date).days
    weeks_remaining = days_remaining / 7.0
    if weeks_remaining <= 0:
        return None

    gap_data = compute_gap(target, session, as_of_date)
    current_basis_kg = gap_data.get("current_basis_kg")
    current_weight = current_basis_kg if current_basis_kg is not None else float(target.start_weight_kg)
    kg_to_go = current_weight - float(target.target_weight_kg)
    return round(kg_to_go / weeks_remaining, 4)


def compute_on_track(
    target,
    current_pace_kg_per_week: Optional[float],
    required_pace_kg_per_week: Optional[float],
) -> Optional[bool]:
    """True when current pace is moving toward the target at or ahead of the
    pace required to hit target_date on time. Direction-aware:

    - Loss target (target_weight_kg < start_weight_kg): required/current pace
      are both positive while the goal isn't yet reached; on_track requires
      current_pace_kg_per_week >= required_pace_kg_per_week.
    - Gain target: required/current pace are both negative (per this module's
      "positive = losing" sign convention) while the goal isn't yet reached;
      on_track requires current_pace_kg_per_week <= required_pace_kg_per_week
      (i.e. gaining at least as fast, expressed as a more-negative pace).
    - Either way, once required_pace_kg_per_week implies the goal is already
      met/exceeded (<=0 for a loss target, >=0 for a gain target), returns
      True regardless of current pace.

    Returns None when either pace is unavailable (insufficient weigh-in data
    to judge) — never guesses.
    """
    if current_pace_kg_per_week is None or required_pace_kg_per_week is None:
        return None

    is_loss = float(target.target_weight_kg) < float(target.start_weight_kg)
    if is_loss:
        if required_pace_kg_per_week <= 0:
            return True
        return current_pace_kg_per_week >= required_pace_kg_per_week
    else:
        if required_pace_kg_per_week >= 0:
            return True
        return current_pace_kg_per_week <= required_pace_kg_per_week


def compute_weight_status(session, user_id, as_of_date: datetime.date) -> dict:
    """Assemble the Hermes-brief weight block for a user: 7-day rolling-average
    current weight, 7d/28d trend deltas, active target info, current vs.
    required pace, on-track flag, and a hit-date projection.

    Always returns a fully-keyed dict — never raises for a user with zero
    weigh-ins or no active WeightTarget; every field is simply None in those
    cases (see _weight_rollup's fallback rules for current_kg specifically).

    Returns
    -------
    dict with keys: current_kg, trend_7d, trend_28d, target_kg, target_date
    (ISO string or None), pace_kg_per_week, on_track (bool or None),
    projection_date (ISO string or None).
    """
    from backend.models import WeightEntry, WeightTarget  # local import to avoid circular dep

    rollup_window_start = as_of_date - datetime.timedelta(days=_ROLLUP_LOOKBACK_DAYS)
    rows = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= rollup_window_start,
            WeightEntry.entry_date <= as_of_date,
        )
        .all()
    )
    weight_rows = [(r.entry_date, float(r.weight_kg)) for r in rows]
    rollup = _weight_rollup(weight_rows, as_of_date)

    target = (
        session.query(WeightTarget)
        .filter(WeightTarget.user_id == user_id, WeightTarget.status == "active")
        .first()
    )

    if target is None:
        return {
            "current_kg": rollup["current_kg"],
            "trend_7d": rollup["trend_7d"],
            "trend_28d": rollup["trend_28d"],
            "target_kg": None,
            "target_date": None,
            "pace_kg_per_week": None,
            "on_track": None,
            "projection_date": None,
        }

    current_pace = compute_current_pace_kg_per_week(target, session, as_of_date)
    required_pace = compute_required_pace_kg_per_week(target, session, as_of_date)
    on_track = compute_on_track(target, current_pace, required_pace)
    hit_date = project_hit_date(target, session, as_of_date)

    return {
        "current_kg": rollup["current_kg"],
        "trend_7d": rollup["trend_7d"],
        "trend_28d": rollup["trend_28d"],
        "target_kg": float(target.target_weight_kg),
        "target_date": str(_as_date(target.target_date)),
        "pace_kg_per_week": current_pace,
        "on_track": on_track,
        "projection_date": hit_date.isoformat() if hit_date is not None else None,
    }


def _snap_to_month_start(d: datetime.date) -> datetime.date:
    """Round date to nearest 1st-of-month."""
    # First of current month
    first_this = d.replace(day=1)
    # First of next month
    if d.month == 12:
        first_next = datetime.date(d.year + 1, 1, 1)
    else:
        first_next = datetime.date(d.year, d.month + 1, 1)

    days_to_this = abs((d - first_this).days)
    days_to_next = abs((first_next - d).days)

    return first_this if days_to_this <= days_to_next else first_next
