"""
Training load aggregation service — Banister impulse-response model.

Math:
    CTL (Chronic Training Load) and ATL (Acute Training Load) are computed via
    exponential weighted moving averages (EWMA) of daily TSS:

        new = prev + (tss - prev) * (1 - exp(-1 / days))

    where `days` is the time constant (default: CTL=42, ATL=7).

    TSB (Training Stress Balance) = CTL - ATL.

Reference: Banister EW (1991) "Modeling elite athletic performance" in
    MacDougall JD et al. (eds) Physiological Testing of Elite Athletes.

Cold-start assumption (noted in compute_load_curves): CTL=0 and ATL=0 on day 0
(the day before the series begins). This means early values are underestimated
until the EWMA "charges up" over several weeks.
"""

from __future__ import annotations

import math
import uuid as _uuid_mod
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import TrainingLoadSnapshot

# ── EWMA time constants ───────────────────────────────────────────────────────
# Chronic Training Load time constant (days).  The standard Banister value.
CTL_DAYS: int = 42
# Acute Training Load time constant (days).  Must be less than CTL_DAYS.
ATL_DAYS: int = 7

# ── Form-zone band constants ───────────────────────────────────────────────────
# TSB (Training Stress Balance) below this threshold = overreached / buried.
FORM_BURIED_CEILING: float = -10.0
# TSB above this threshold = well-rested / fresh.
FORM_FRESH_FLOOR: float = 5.0

# ── Taper recommendation constants ────────────────────────────────────────────
# Lower bound of the "positive form band" — the minimum TSB an athlete should
# hit on race day to benefit from a taper peak.
TARGET_FORM_LOWER: float = 5.0
# Upper bound of the positive form band — TSB above this means the athlete
# is over-rested and has likely shed too much fitness.
TARGET_FORM_UPPER: float = 25.0
# Default taper window length in days (two calendar weeks).
DEFAULT_TAPER_DAYS: int = 14

# ── Peak tracking constants ───────────────────────────────────────────────────
# Tolerance band (in TSB units) within which an athlete is considered "on track"
# with the projected taper curve.  Outside this band, status is "ahead" or "behind".
PEAK_TRACKING_TOLERANCE: float = 5.0


def _ewma_alpha(days: int) -> float:
    """Exponential weighted moving average alpha factor."""
    return 1 - math.exp(-1 / days)


def daily_tss_series(
    user_id: str,
    from_date: date,
    to_date: date,
) -> list[tuple[date, int]]:
    """Query workouts table, sum TSS per day, fill zero-TSS days.

    Returns list of (date, tss) tuples ordered ascending from from_date to
    to_date inclusive. Days with no workout get tss=0.

    Raises:
        ValueError: if from_date > to_date or from_date is in the future.
    """
    today = date.today()
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} must not be after to_date {to_date}")
    if from_date > today:
        raise ValueError(f"from_date {from_date} is in the future")

    sql = text(
        """
        SELECT workout_date, COALESCE(SUM(tss), 0)::int AS total_tss
        FROM workouts
        WHERE user_id = :user_id
          AND workout_date BETWEEN :from_date AND :to_date
          AND tss IS NOT NULL
        GROUP BY workout_date
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"user_id": str(user_id), "from_date": from_date, "to_date": to_date},
        ).fetchall()

    tss_by_date: dict[date, int] = {row[0]: row[1] for row in rows}

    series: list[tuple[date, int]] = []
    current = from_date
    while current <= to_date:
        series.append((current, tss_by_date.get(current, 0)))
        current += timedelta(days=1)
    return series


def compute_load_curves(
    daily_series: list[tuple[date, int]],
    ctl_days: int = CTL_DAYS,
    atl_days: int = ATL_DAYS,
) -> list[dict]:
    """Compute CTL, ATL, TSB for each day in daily_series using EWMA.

    Cold-start assumption: CTL=0 and ATL=0 before the first day in the series.
    Early values will be underestimated until the EWMA has enough history.

    Args:
        daily_series: list of (date, tss) tuples ordered ascending.
        ctl_days: EWMA time constant for CTL (default 42). Must be > atl_days.
        atl_days: EWMA time constant for ATL (default 7). Must be > 0.

    Returns:
        list of dicts with keys: date, tss, ctl, atl, tsb.

    Raises:
        ValueError: if ctl_days <= atl_days or atl_days <= 0.
    """
    if atl_days <= 0:
        raise ValueError(f"atl_days must be > 0, got {atl_days}")
    if ctl_days <= atl_days:
        raise ValueError(
            f"ctl_days ({ctl_days}) must be greater than atl_days ({atl_days})"
        )

    ctl_alpha = _ewma_alpha(ctl_days)
    atl_alpha = _ewma_alpha(atl_days)

    ctl = 0.0
    atl = 0.0
    result = []
    for day, tss in daily_series:
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        tsb = ctl - atl
        result.append({"date": day, "tss": tss, "ctl": round(ctl, 2), "atl": round(atl, 2), "tsb": round(tsb, 2)})
    return result


def current_load(
    user_id: str,
    as_of: Optional[date] = None,
) -> dict:
    """Return CTL, ATL, TSB as of a given date (default: today).

    Queries workouts from 6 months before as_of to give the EWMA time to
    charge up. Returns a dict with keys: date, ctl, atl, tsb.

    Args:
        user_id: the user's ID.
        as_of: restrict series to this date (default: today).

    Returns:
        dict with keys date, ctl, atl, tsb for the last day of the series.
    """
    end = as_of if as_of is not None else date.today()
    # 6-month warm-up window so EWMA is reasonably converged by end date
    start = end - timedelta(days=180)

    series = daily_tss_series(user_id, start, end)
    curves = compute_load_curves(series)
    last = curves[-1]
    return {
        "date": last["date"],
        "ctl": last["ctl"],
        "atl": last["atl"],
        "tsb": last["tsb"],
    }


def daily_update(
    user_id: str,
    target_date: Optional[date] = None,
) -> dict:
    """Compute CTL/ATL/TSB for target_date and UPSERT into training_load_snapshots.

    Uses a 6-month warmup window for EWMA convergence. Safe to re-run (idempotent).

    Args:
        user_id: the user's ID.
        target_date: date to compute and store (default: today).

    Returns:
        dict with keys: date, tss, ctl, atl, tsb.
    """
    target = target_date if target_date is not None else date.today()
    start = target - timedelta(days=180)
    series = daily_tss_series(user_id, start, target)
    curves = compute_load_curves(series)
    last = curves[-1]

    uid = _uuid_mod.UUID(str(user_id))
    row = {
        "user_id": uid,
        "snapshot_date": target,
        "tss_for_day": last["tss"],
        "ctl": round(last["ctl"], 2),
        "atl": round(last["atl"], 2),
        "tsb": round(last["tsb"], 2),
    }

    stmt = _pg_insert(TrainingLoadSnapshot).values([row])
    upsert = stmt.on_conflict_do_update(
        index_elements=["user_id", "snapshot_date"],
        set_={
            "tss_for_day": stmt.excluded.tss_for_day,
            "ctl": stmt.excluded.ctl,
            "atl": stmt.excluded.atl,
            "tsb": stmt.excluded.tsb,
            "computed_at": datetime.now(tz=timezone.utc),
        },
    )
    with Session(engine) as session:
        session.execute(upsert)
        session.commit()

    return {
        "date": target,
        "tss": last["tss"],
        "ctl": row["ctl"],
        "atl": row["atl"],
        "tsb": row["tsb"],
    }


def _classify_zone(tsb: float) -> str:
    """Return the zone name for a single TSB value using named band constants."""
    if tsb < FORM_BURIED_CEILING:
        return "buried"
    if tsb >= FORM_FRESH_FLOOR:
        return "fresh"
    return "neutral"


def performance_curve(fitness_series) -> dict:
    """Reinterpret a fitness series into per-day form zones and today's summary.

    This is a pure function: it reads the TSB values already present in
    fitness_series and classifies each day into a zone. It does not recompute
    CTL, ATL, or TSB, and it does not access the database.

    Zone bands (defined by FORM_BURIED_CEILING and FORM_FRESH_FLOOR):
        buried  -- form is below the buried ceiling (athlete is over-reached)
        neutral -- form is at or above the buried ceiling and below the fresh floor
        fresh   -- form is at or above the fresh floor (athlete is well-rested)

    Args:
        fitness_series: a list of dicts, each containing at least 'date' and
            'tsb' keys -- typically the output of compute_load_curves(). The
            'ctl' and 'atl' fields are accepted but not required for zone
            classification. A thin caller can perform the DB access and series
            computation, then pass the result directly to this function.

    Returns:
        A dict with:
            curve       -- list of per-day records, each with 'date', 'form'
                          (the TSB value, unmodified), and 'zone' (one of
                          'buried', 'neutral', 'fresh').
            today_form  -- TSB value for today's date, or None if today is not
                          present in the series.
            today_zone  -- zone string for today's date, or None if today is not
                          present in the series.
            reason      -- empty string on success; a human-readable explanation
                          when the input was invalid or missing.

        On any invalid input (None, empty list, or missing required columns) the
        function returns an empty result with a non-empty reason string. It never
        raises an exception.

    Worked example:

        Suppose three consecutive days have TSB values of -15, 0, and 10.
        FORM_BURIED_CEILING is -10 and FORM_FRESH_FLOOR is 5.

        Day 1: TSB is -15, which is below the buried ceiling of -10.
               Zone is 'buried'.
        Day 2: TSB is 0, which is at or above the buried ceiling and below the
               fresh floor of 5.
               Zone is 'neutral'.
        Day 3: TSB is 10, which is at or above the fresh floor of 5.
               Zone is 'fresh'.

        If Day 3 is today, today_form is 10 and today_zone is 'fresh'.
    """
    _empty = {"curve": [], "today_form": None, "today_zone": None, "reason": ""}

    if not fitness_series:
        return {**_empty, "reason": "fitness_series is None or empty"}

    first = fitness_series[0]
    if not isinstance(first, dict):
        return {**_empty, "reason": "fitness_series items must be dicts"}
    if "tsb" not in first:
        return {**_empty, "reason": "fitness_series items are missing required 'tsb' column"}
    if "date" not in first:
        return {**_empty, "reason": "fitness_series items are missing required 'date' column"}

    today = date.today()
    today_form = None
    today_zone = None
    curve = []

    for row in fitness_series:
        try:
            day = row["date"]
            tsb = row["tsb"]
        except (KeyError, TypeError):
            return {**_empty, "reason": "fitness_series contains rows with missing date or tsb"}
        zone = _classify_zone(tsb)
        curve.append({"date": day, "form": tsb, "zone": zone})
        if day == today:
            today_form = tsb
            today_zone = zone

    return {
        "curve": curve,
        "today_form": today_form,
        "today_zone": today_zone,
        "reason": "",
    }


def project_form(
    fitness_state,
    planned_daily_load,
    target_date,
    *,
    recent_avg_load=None,
) -> dict:
    """Project CTL, ATL, and form (TSB) forward to a target date.

    This is a pure function — it performs no database access and raises no
    exceptions for invalid input.  The calling layer is responsible for
    supplying fitness_state and recent_avg_load (when needed) from the database.

    The same exponential update rule used by compute_load_curves applies here:

        new = prev + (load - prev) * alpha

    where alpha is derived from the shared CTL_DAYS and ATL_DAYS constants via
    _ewma_alpha.  form (TSB) is ctl minus atl on each projected day.

    Args:
        fitness_state:
            Dict containing at minimum ``ctl``, ``atl``, and ``date``.  ``date``
            is the anchor day; the projection starts from anchor + 1.
        planned_daily_load:
            A single scalar applied uniformly each day, an ordered list of
            per-day load values (one element per projected day, padded with 0
            if shorter than needed), or None to use ``recent_avg_load``.
        target_date:
            The last day of the projection window (inclusive).  Must be after
            ``fitness_state["date"]``.
        recent_avg_load:
            Caller-supplied recent average daily load.  Required when
            ``planned_daily_load`` is None; ignored otherwise.

    Returns:
        Dict with two keys:

        ``days``
            List of day objects from anchor + 1 through target_date, each with
            ``date``, ``ctl``, ``atl``, ``form`` (CTL minus ATL), and
            ``assumed_load`` (True when load was not explicitly planned).
        ``reason``
            Empty string on success; a machine-readable explanation when the
            input was invalid or missing.

    Worked example:

        Starting state: ctl=50.0, atl=60.0, anchor_date=2024-01-01.
        assumed_load=30 (below both ctl and atl).

        ATL_DAYS is shorter than CTL_DAYS, so ATL adjusts toward the load
        value faster than CTL.  Since the load is below atl, both values
        decrease over time, but ATL decreases faster — the gap (ctl minus atl)
        therefore grows, which means form rises.

        Anchor: ctl=50.0, atl=60.0, form=-10.0.

        Day 1 (2024-01-02):
            ctl decreases by roughly (50 minus 30) times alpha_ctl, about 0.47,
            reaching approximately 49.5.
            atl decreases by roughly (60 minus 30) times alpha_atl, about 4.0,
            reaching approximately 56.0.
            form rises to approximately minus 6.5.

        Day 2 (2024-01-03):
            ctl decreases a further 0.46 to approximately 49.1.
            atl decreases a further 3.5 to approximately 52.5.
            form rises to approximately minus 3.4.

        Day 3 (2024-01-04):
            ctl approximately 48.6, atl approximately 49.5.
            form rises to approximately minus 0.9.

        As fatigue (atl) decays faster than fitness (ctl), form continues to
        rise each day until the assumed load matches ctl and the system reaches
        a new equilibrium.
    """
    _empty: dict = {"days": [], "reason": ""}

    if fitness_state is None:
        return {**_empty, "reason": "fitness_state is required"}
    if target_date is None:
        return {**_empty, "reason": "target_date is required"}

    try:
        anchor_ctl = float(fitness_state["ctl"])
        anchor_atl = float(fitness_state["atl"])
        anchor_date = fitness_state["date"]
    except (KeyError, TypeError, ValueError):
        return {**_empty, "reason": "fitness_state must contain ctl, atl, and date"}

    if not isinstance(anchor_date, date):
        return {**_empty, "reason": "fitness_state.date must be a date object"}

    if target_date <= anchor_date:
        return {**_empty, "reason": "target_date must be after fitness_state.date (anchor date)"}

    n_days = (target_date - anchor_date).days

    if planned_daily_load is None:
        if recent_avg_load is None:
            return {**_empty, "reason": "recent_avg_load is required when planned_daily_load is None"}
        load_schedule = [float(recent_avg_load)] * n_days
        assumed = [True] * n_days
    elif isinstance(planned_daily_load, (int, float)):
        load_schedule = [float(planned_daily_load)] * n_days
        assumed = [False] * n_days
    else:
        try:
            loads = [float(v) for v in planned_daily_load]
        except (TypeError, ValueError):
            return {**_empty, "reason": "planned_daily_load list contains invalid values"}
        n_provided = len(loads)
        if n_provided >= n_days:
            load_schedule = loads[:n_days]
            assumed = [False] * n_days
        else:
            load_schedule = loads + [0.0] * (n_days - n_provided)
            assumed = [False] * n_provided + [True] * (n_days - n_provided)

    ctl_alpha = _ewma_alpha(CTL_DAYS)
    atl_alpha = _ewma_alpha(ATL_DAYS)

    ctl = anchor_ctl
    atl = anchor_atl
    days = []

    for i in range(n_days):
        day_date = anchor_date + timedelta(days=i + 1)
        tss = load_schedule[i]
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        days.append({
            "date": day_date,
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "form": round(ctl - atl, 2),
            "assumed_load": assumed[i],
        })

    return {"days": days, "reason": ""}


def get_projected_form(
    user_id: str,
    planned_daily_load,
    target_date: date,
) -> dict:
    """Thin caller: fetch fitness state and recent avg load from DB, then project form.

    Responsibilities:
    - Calls current_load(user_id) to obtain today's CTL, ATL, and anchor date.
    - When planned_daily_load is None, queries the last 28 days of TSS to
      compute a recent average daily load for the assumed-load fallback.
    - Delegates all projection math to project_form (pure function).

    Args:
        user_id: the authenticated user's ID.
        planned_daily_load: scalar, per-day list, or None for assumed load.
        target_date: projection horizon (must be after today).

    Returns:
        Same dict shape as project_form: {days, reason}.
    """
    today = date.today()
    load_state = current_load(user_id)
    fitness_state = {
        "ctl": load_state["ctl"],
        "atl": load_state["atl"],
        "date": load_state["date"],
    }

    recent_avg: Optional[float] = None
    if planned_daily_load is None:
        window_start = today - timedelta(days=27)
        series = daily_tss_series(user_id, window_start, today)
        if series:
            recent_avg = sum(tss for _, tss in series) / len(series)
        else:
            recent_avg = 0.0

    return project_form(
        fitness_state,
        planned_daily_load,
        target_date,
        recent_avg_load=recent_avg,
    )


def taper_recommendation(fitness_state, race_date, target_form) -> dict:
    """Recommend when to begin tapering so form peaks on race day.

    This is a pure function — it performs no database access and raises no
    exceptions for invalid input.  The calling layer is responsible for
    supplying fitness_state from the database.

    A "taper" means reducing training load to zero for DEFAULT_TAPER_DAYS
    before the race.  This lets fatigue (ATL) decay faster than fitness (CTL),
    which raises form (TSB = CTL − ATL) into the positive band.  The function
    projects form forward with zero load and checks whether race-day form will
    reach TARGET_FORM_LOWER.

    Args:
        fitness_state:
            Dict containing at minimum ``ctl``, ``atl``, and ``date``.  ``date``
            is the anchor day for the projection (typically today).
        race_date:
            The target race date.  Must be in the future (strictly after today).
        target_form:
            The athlete's desired TSB value on race day.  Must not be None.
            Used to validate that the caller has specified a form target.

    Returns:
        On invalid input:
            Dict with ``taper_start_date=None``, ``message=None``,
            ``achievable=None``, and a non-empty ``reason`` string.
        On valid input:
            Dict with:
            ``taper_start_date`` -- date to begin easing load (race_date minus
                                    DEFAULT_TAPER_DAYS).
            ``message``          -- plain-language guidance string.
            ``achievable``       -- True when projected race-day form reaches
                                    TARGET_FORM_LOWER; False otherwise.
            ``reason``           -- empty string on success.

    Worked example 1 — Normal 2-week taper:
        Inputs:
            fitness_state = {"ctl": 50.0, "atl": 60.0, "date": 2024-11-23}
            race_date     = 2024-12-14  (21 days away)
            target_form   = 10.0

        With zero load for 21 days, ATL (time constant 7 days) decays from 60
        to roughly 3 (exp(-21/7) ≈ 0.05); CTL (time constant 42 days) decays
        from 50 to roughly 30 (exp(-21/42) ≈ 0.61).  Race-day form ≈ 30 − 3 = 27,
        which is above TARGET_FORM_LOWER (5.0), so achievable is True.

        Expected output:
            taper_start_date = 2024-11-30  (14 days before race)
            message = "begin easing load around Nov 30 to peak on Dec 14"
            achievable = True

    Worked example 2 — Race too close to peak:
        Inputs:
            fitness_state = {"ctl": 50.0, "atl": 90.0, "date": 2024-12-09}
            race_date     = 2024-12-13  (4 days away)
            target_form   = 10.0

        With zero load for 4 days, ATL decays from 90 to roughly 51 (each day
        ATL drops by alpha_atl ≈ 0.133 of the gap to zero).  CTL decays from 50
        to roughly 45.  Race-day form ≈ 45 − 51 = −6, which is below
        TARGET_FORM_LOWER (5.0), so achievable is False.

        Expected output:
            taper_start_date = 2024-11-29  (14 days before race, now in the past)
            message = "Race is too soon to reach a positive form band; manage
                       fatigue rather than targeting a peak"
            achievable = False
    """
    _empty = {"taper_start_date": None, "message": None, "achievable": None, "reason": ""}

    # Validate required inputs; return null result with explanation on failure
    if fitness_state is None:
        return {**_empty, "reason": "fitness_state is required"}
    if race_date is None:
        return {**_empty, "reason": "race_date is required"}
    if target_form is None:
        return {**_empty, "reason": "target_form is required"}

    today = date.today()
    # Race must be in the future; a past or today race cannot be tapered into
    if race_date <= today:
        return {**_empty, "reason": "race_date must be in the future"}

    # Taper start = DEFAULT_TAPER_DAYS before race day.  If this falls before
    # today the race is already within the taper window (or past it).
    taper_start_date = race_date - timedelta(days=DEFAULT_TAPER_DAYS)

    # Project form to race_date assuming zero load — this simulates a full taper
    # where the athlete trains nothing from today until race day.  Fatigue (ATL)
    # decays with a short time constant (7 days) while fitness (CTL) decays more
    # slowly (42 days), so form (CTL − ATL) rises over the taper window.
    projection = project_form(fitness_state, 0.0, race_date)
    if projection["reason"]:
        # project_form reported a validation error; surface it as our reason
        return {**_empty, "reason": projection["reason"]}

    # Race-day form is the last projected day in the series
    projected_race_form = projection["days"][-1]["form"]

    # Achievable when projected form reaches the lower bound of the positive band;
    # below TARGET_FORM_LOWER the athlete will not be in a peaked state on race day
    achievable = projected_race_form >= TARGET_FORM_LOWER

    if achievable:
        # Format dates for readability: "Nov 30", "Dec 14"
        start_str = taper_start_date.strftime("%b %-d")
        race_str = race_date.strftime("%b %-d")
        message = f"begin easing load around {start_str} to peak on {race_str}"
    else:
        # Honest assessment: the positive band is out of reach given time remaining
        message = (
            "Race is too soon to reach a positive form band; "
            "manage fatigue rather than targeting a peak"
        )

    return {
        "taper_start_date": taper_start_date,
        "message": message,
        "achievable": achievable,
        "reason": "",
    }


def get_taper_recommendation(
    user_id: str,
    race_date: date,
    target_form: float,
) -> dict:
    """Thin caller: fetch fitness state from DB, then compute taper recommendation.

    Responsibilities:
    - Calls current_load(user_id) to obtain today's CTL, ATL, and anchor date.
    - Delegates all recommendation logic to taper_recommendation (pure function).

    Args:
        user_id: the authenticated user's ID.
        race_date: the target race date.
        target_form: the athlete's desired TSB value on race day.

    Returns:
        Same dict shape as taper_recommendation: {taper_start_date, message,
        achievable, reason}.
    """
    load_state = current_load(user_id)
    fitness_state = {
        "ctl": load_state["ctl"],
        "atl": load_state["atl"],
        "date": load_state["date"],
    }
    return taper_recommendation(fitness_state, race_date, target_form)


def peak_tracking(
    current_form,
    projected_form_for_today_from_plan,
    *,
    tolerance: float = PEAK_TRACKING_TOLERANCE,
) -> dict:
    """Compare actual form (TSB) to today's expected value from the taper plan.

    This is a pure, side-effect-free function — it accepts only the two
    pre-resolved numeric inputs and a tolerance value.  No database access
    is performed here; the calling layer is responsible for supplying both
    values from the appropriate sources (current_load for actual form;
    project_form applied to the taper-start fitness state for the projected
    value).

    The ``gap`` is defined as ``current_form minus projected_form_for_today_from_plan``.
    A positive gap means the athlete is ahead of the plan; a negative gap means
    they are behind.

    The ``tolerance`` band defines the width (in TSB units) within which the
    athlete is considered "on track".  Outside this band, status is "ahead" or
    "behind" depending on the sign of the gap.  The tolerance defaults to the
    module-level ``PEAK_TRACKING_TOLERANCE`` constant — never a bare literal
    in the function body.

    Status labels:
        "on track" — gap is within the tolerance band (|gap| <= tolerance)
        "ahead"    — gap is above the tolerance band (gap > tolerance)
        "behind"   — gap is below the tolerance band (gap < -tolerance)

    Args:
        current_form: today's actual TSB value (float or int).  Returns a null
            result with a reason string when None or non-numeric.
        projected_form_for_today_from_plan: today's expected TSB according to
            the taper plan projection.  Returns a null result when None.
        tolerance: the half-width of the "on track" band in TSB units.
            Defaults to PEAK_TRACKING_TOLERANCE (5.0).  Callers that read
            this value from configuration must pass it explicitly.

    Returns:
        On invalid input:
            Dict with ``status=None``, ``gap=None``, and a non-empty
            ``reason`` string.
        On valid input:
            Dict with:
            ``status``  -- "on track", "ahead", or "behind"
            ``gap``     -- float, current_form minus projected_form_for_today_from_plan
            ``reason``  -- empty string on success

    Worked example 1 — Athlete ahead of plan:
        current_form = 85, projected_form_for_today_from_plan = 70, tolerance = 5
        gap = 85 - 70 = 15
        gap (15) > tolerance (5) → status = "ahead"
        Expected output: {"status": "ahead", "gap": 15.0, "reason": ""}

    Worked example 2 — Athlete on track:
        current_form = 72, projected_form_for_today_from_plan = 70, tolerance = 5
        gap = 72 - 70 = 2
        |gap| (2) <= tolerance (5) → status = "on track"
        Expected output: {"status": "on track", "gap": 2.0, "reason": ""}

    Worked example 3 — Athlete at lower on-track boundary:
        current_form = 65, projected_form_for_today_from_plan = 70, tolerance = 5
        gap = 65 - 70 = -5
        |gap| (5) <= tolerance (5) → status = "on track"
        Expected output: {"status": "on track", "gap": -5.0, "reason": ""}

    Worked example 4 — Athlete behind plan:
        current_form = 55, projected_form_for_today_from_plan = 70, tolerance = 5
        gap = 55 - 70 = -15
        gap (-15) < -tolerance (-5) → status = "behind"
        Expected output: {"status": "behind", "gap": -15.0, "reason": ""}
    """
    _null = {"status": None, "gap": None, "reason": ""}

    if current_form is None:
        return {**_null, "reason": "current_form is required"}
    if projected_form_for_today_from_plan is None:
        return {**_null, "reason": "projected_form_for_today_from_plan is required"}

    try:
        cf = float(current_form)
        pf = float(projected_form_for_today_from_plan)
    except (TypeError, ValueError):
        return {**_null, "reason": "current_form and projected_form_for_today_from_plan must be numeric"}

    # gap: positive = ahead of plan, negative = behind plan
    gap = cf - pf

    if gap > tolerance:
        status = "ahead"
    elif gap < -tolerance:
        status = "behind"
    else:
        status = "on track"

    return {"status": status, "gap": round(gap, 2), "reason": ""}
