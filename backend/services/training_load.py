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
import os
import uuid as _uuid_mod
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import TrainingLoadSnapshot, UserPreferences, Workout
from backend.services.acwr import compute_acwr
from backend.utils.time import today_bangkok

# ── EWMA time constants ───────────────────────────────────────────────────────
# Chronic Training Load time constant (days).  The standard Banister value.
CTL_DAYS: int = 42
# Acute Training Load time constant (days).  Must be less than CTL_DAYS.
ATL_DAYS: int = 7

# ── Single source of truth ────────────────────────────────────────────────────
# training_load_snapshots is the SOLE persisted CTL/ATL/TSB/ACWR record.
# daily_update() is the sole writer; current_load()/get_snapshot_series() are
# the sole read paths every consumer (readiness, the fitness/fatigue/form
# chart, the weekly coach report, monthly summary, Plan-tab targets) must go
# through. Bumped whenever the EWMA/ACWR math or seeding changes — a stored
# row whose formula_version doesn't match is treated as a cache miss and
# recomputed, so a formula change can't silently keep serving stale rows.
# See docs/calculations/training-load.md.
_FORMULA_VERSION: str = "2026-07-10.1"

# Window length (days) for the ACWR figure stored on each snapshot — matches
# acwr.compute_acwr's own acute(7d)+chronic(4x7d prior) requirement.
_ACWR_WINDOW_DAYS: int = 35


def resolve_user_ewma_days(user_id: str) -> tuple[int, int]:
    """Return (ctl_days, atl_days) for a user: their saved calibration prefs
    if set, else the module defaults (CTL_DAYS, ATL_DAYS)."""
    uid = _uuid_mod.UUID(str(user_id))
    with Session(engine) as session:
        prefs = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == uid)
            .first()
        )
    ctl_days = prefs.ctl_days if prefs and prefs.ctl_days else CTL_DAYS
    atl_days = prefs.atl_days if prefs and prefs.atl_days else ATL_DAYS
    return ctl_days, atl_days


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
# Standard full taper for an A-priority (goal) race: two calendar weeks.
A_RACE_TAPER_DAYS: int = 14
# Abbreviated mini-taper for a B-priority tune-up race: one calendar week.
B_RACE_TAPER_DAYS: int = 7

# ── Peak tracking constants ───────────────────────────────────────────────────
# Tolerance band (in TSB units) within which an athlete is considered "on track"
# with the projected taper curve.  Outside this band, status is "ahead" or "behind".
PEAK_TRACKING_TOLERANCE: float = 5.0

# ── Post-race calibration constants ──────────────────────────────────────────
TIMING_TOLERANCE_WEEKS: int = 1
CTL_ADJUSTMENT_DAYS_PER_WEEK: int = 2
MIN_CTL_DAYS: int = 14
MAX_CTL_DAYS: int = 84
_LEVEL_DELTA_PRECISION: int = 1

# ── Readiness label constants ──────────────────────────────────────────────────
# Human-readable labels assigned to TSB ranges for the readiness endpoint.
READINESS_LABEL_FATIGUED: str = "Fatigued"   # TSB below FORM_BURIED_CEILING
READINESS_LABEL_OPTIMAL: str = "Optimal"     # TSB in the neutral band
READINESS_LABEL_FRESH: str = "Fresh"         # TSB at or above FORM_FRESH_FLOOR

# ── Baseline detection constants ───────────────────────────────────────────────
# Days to look back when checking for sufficient training history.
BASELINE_WINDOW_DAYS: int = 42
# Minimum number of days with TSS > 0 within the window before metrics are reliable.
BASELINE_MIN_WORKOUT_DAYS: int = 7


def _load_read_from_snapshot() -> bool:
    """Whether current_load() reads the training_load_snapshots cache (default on).
    Set LOAD_READ_FROM_SNAPSHOT=0 to force an inline recompute every call — a
    debug/rollback escape hatch. The inline recompute is the same fallback path
    taken on a cache miss, so turning this off is always safe, just slower."""
    return os.getenv("LOAD_READ_FROM_SNAPSHOT", "1").strip().lower() not in (
        "0", "false", "no", "off", "",
    )


def _ewma_alpha(days: int) -> float:
    """Exponential weighted moving average alpha factor."""
    return 1 - math.exp(-1 / days)


def _acwr_ratio_for_window(tss_tail: list) -> Optional[float]:
    """ACWR for the day the window ends on — tss_tail must be the last
    _ACWR_WINDOW_DAYS daily TSS values (oldest first, ending on that day).
    None when there isn't enough history (mirrors acwr.py's own guard) or
    chronic load is zero. Always the SAME acwr.compute_acwr formula every
    other ACWR consumer (guardrail.py, plan_suggestions.py) already uses —
    never reimplemented here."""
    return compute_acwr(tss_tail).get("ratio")


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
    today = today_bangkok()
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


def _snap_matches_calibration(snap, ctl_days: int, atl_days: int) -> bool:
    """True when a snapshot row was computed with the given time constants.

    A NULL ctl_days/atl_days on the snapshot means the row was written before
    per-user calibration was recorded — treat it as the module defaults.
    """
    snap_ctl = snap.ctl_days if snap.ctl_days is not None else CTL_DAYS
    snap_atl = snap.atl_days if snap.atl_days is not None else ATL_DAYS
    return snap_ctl == ctl_days and snap_atl == atl_days


def current_load(
    user_id: str,
    as_of: Optional[date] = None,
) -> dict:
    """Return CTL, ATL, TSB, ACWR as of a given date (default: today) — THE
    single source of truth every consumer (readiness, the fitness/fatigue/
    form chart, the weekly coach report, monthly summary, Plan-tab targets)
    must call instead of recomputing independently. See
    docs/calculations/training-load.md.

    Reads today's row from training_load_snapshots when present, fresh
    (snapshot_date == end date, formula_version matches, and ctl_days/atl_days
    match the user's current calibration), to avoid a 180-day recompute on the
    hot path. Falls back to the live recompute when the snapshot is missing,
    stale, version-mismatched, or computed with different calibration constants.

    Args:
        user_id: the user's ID.
        as_of: restrict series to this date (default: today).

    Returns:
        dict with keys date, ctl, atl, tsb, acwr for the last day of the series.
    """
    end = as_of if as_of is not None else today_bangkok()

    ctl_days, atl_days = resolve_user_ewma_days(user_id)

    if _load_read_from_snapshot():
        uid = _uuid_mod.UUID(str(user_id))
        with Session(engine) as session:
            snap = (
                session.query(TrainingLoadSnapshot)
                .filter(
                    TrainingLoadSnapshot.user_id == uid,
                    TrainingLoadSnapshot.snapshot_date == end,
                )
                .first()
            )
            if (
                snap is not None
                and snap.formula_version == _FORMULA_VERSION
                and _snap_matches_calibration(snap, ctl_days, atl_days)
            ):
                return {
                    "date": snap.snapshot_date,
                    "ctl": snap.ctl,
                    "atl": snap.atl,
                    "tsb": snap.tsb,
                    "acwr": snap.acwr,
                }

    computed = daily_update(user_id, target_date=end, ctl_days=ctl_days, atl_days=atl_days)
    return {
        "date": computed["date"],
        "ctl": computed["ctl"],
        "atl": computed["atl"],
        "tsb": computed["tsb"],
        "acwr": computed["acwr"],
    }


def _day_workout_signature(session: Session, user_id, d: date) -> str:
    """Cheap fingerprint of a single date's workout rows — same idea as
    main.py's _summary_signature, scoped to one day instead of the whole
    user, since CTL/ATL/TSB snapshots are keyed per date.

    Deliberately per-day, not per-180-day-window: the bug this exists to
    catch is a snapshot computed before that date's own workout was
    logged/synced, which is what actually happened live (tss_for_day stuck
    at 0 for weeks that had real workouts). A workout edited far outside the
    target date only shifts the EWMA by a fraction of a fraction — real, but
    not what caused the observed failure, and checking the full window on
    every read would be a much heavier query for a case that isn't the one
    that broke. If retroactive-edit drift ever turns out to matter in
    practice, that's a separate, additive check on top of this one.
    """
    row = (
        session.query(
            func.count(Workout.id),
            func.max(Workout.created_at),
            func.max(Workout.updated_at),
        )
        .filter(Workout.user_id == user_id, Workout.workout_date == d)
        .one()
    )
    return "%s|%s|%s" % (row[0], row[1], row[2])


_NO_WORKOUTS_SIGNATURE = "0|None|None"


def _workout_signatures_for_range(
    session: Session, user_id, from_date: date, to_date: date
) -> dict[date, str]:
    """Same fingerprint as _day_workout_signature, batched across a date
    range in one GROUP BY query instead of one query per day — get_snapshot_series
    checks staleness for a whole range at once, and N individual queries would
    undo the "one batch, not N daily_update() calls" property its own
    docstring promises.

    A date with zero workouts is absent from the GROUP BY result; filled in
    with the same default _day_workout_signature would compute for it, so
    range and single-day lookups never disagree on a rest day's signature.
    """
    rows = (
        session.query(
            Workout.workout_date,
            func.count(Workout.id),
            func.max(Workout.created_at),
            func.max(Workout.updated_at),
        )
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= from_date,
            Workout.workout_date <= to_date,
        )
        .group_by(Workout.workout_date)
        .all()
    )
    out = {r[0]: "%s|%s|%s" % (r[1], r[2], r[3]) for r in rows}
    d = from_date
    while d <= to_date:
        out.setdefault(d, _NO_WORKOUTS_SIGNATURE)
        d += timedelta(days=1)
    return out


def daily_update(
    user_id: str,
    target_date: Optional[date] = None,
    ctl_days: Optional[int] = None,
    atl_days: Optional[int] = None,
) -> dict:
    """Compute CTL/ATL/TSB for target_date and UPSERT into training_load_snapshots.

    Uses a 6-month warmup window for EWMA convergence. Safe to re-run (idempotent).

    ctl_days/atl_days default to the user's saved calibration (UserPreferences)
    when not passed explicitly. The snapshot row records the constants that
    produced it so the cache can be invalidated when the user accepts a new
    calibration (ctl_days/atl_days mismatch → treated as a cache miss).

    Args:
        user_id: the user's ID.
        target_date: date to compute and store (default: today).
        ctl_days: EWMA time constant for CTL (default: user's calibration, or CTL_DAYS).
        atl_days: EWMA time constant for ATL (default: user's calibration, or ATL_DAYS).

    Returns:
        dict with keys: date, tss, ctl, atl, tsb, acwr.
    """
    target = target_date if target_date is not None else today_bangkok()
    if ctl_days is None or atl_days is None:
        default_ctl, default_atl = resolve_user_ewma_days(user_id)
        ctl_days = ctl_days if ctl_days is not None else default_ctl
        atl_days = atl_days if atl_days is not None else default_atl

    start = target - timedelta(days=180)
    series = daily_tss_series(user_id, start, target)
    curves = compute_load_curves(series, ctl_days=ctl_days, atl_days=atl_days)
    last = curves[-1]
    # series already spans [target-180, target]; reuse its tail instead of a
    # second DB query for the ACWR window.
    acwr = _acwr_ratio_for_window([tss for _, tss in series[-_ACWR_WINDOW_DAYS:]])

    uid = _uuid_mod.UUID(str(user_id))

    with Session(engine) as session:
        signature = _day_workout_signature(session, uid, target)
        row = {
            "user_id": uid,
            "snapshot_date": target,
            "tss_for_day": last["tss"],
            "ctl": round(last["ctl"], 2),
            "atl": round(last["atl"], 2),
            "tsb": round(last["tsb"], 2),
            "acwr": acwr,
            "formula_version": _FORMULA_VERSION,
            "ctl_days": ctl_days,
            "atl_days": atl_days,
            "workout_signature": signature,
        }
        stmt = _pg_insert(TrainingLoadSnapshot).values([row])
        upsert = stmt.on_conflict_do_update(
            index_elements=["user_id", "snapshot_date"],
            set_={
                "tss_for_day": stmt.excluded.tss_for_day,
                "ctl": stmt.excluded.ctl,
                "atl": stmt.excluded.atl,
                "tsb": stmt.excluded.tsb,
                "acwr": stmt.excluded.acwr,
                "formula_version": stmt.excluded.formula_version,
                "ctl_days": stmt.excluded.ctl_days,
                "atl_days": stmt.excluded.atl_days,
                "workout_signature": stmt.excluded.workout_signature,
                "computed_at": datetime.now(tz=timezone.utc),
            },
        )
        session.execute(upsert)
        session.commit()

    return {
        "date": target,
        "tss": last["tss"],
        "ctl": row["ctl"],
        "atl": row["atl"],
        "tsb": row["tsb"],
        "acwr": row["acwr"],
    }


def get_snapshot_series(
    user_id: str,
    from_date: date,
    to_date: date,
    ctl_days: Optional[int] = None,
    atl_days: Optional[int] = None,
) -> list[dict]:
    """Range read-through-cache — the single source of truth for any
    consumer that needs CTL/ATL/TSB/ACWR across multiple days (the fitness/
    fatigue/form chart, readiness's trend series, monthly summary), instead
    of an independent recompute per consumer. Every day in [from_date,
    to_date] is guaranteed a snapshot on return (fresh cache rows reused;
    missing, stale-formula-version, or wrong-calibration days computed and
    upserted in ONE batch, not N individual daily_update() calls).

    ctl_days/atl_days default to the user's saved calibration
    (resolve_user_ewma_days), same as current_load(). Snapshot rows record
    the constants used; a mismatch between the stored ctl_days/atl_days and
    the user's current calibration is treated as a cache miss.

    Returns:
        list of dicts (ascending by date), each with keys: date, tss, ctl,
        atl, tsb, acwr. acwr is None for early days without enough trailing
        history (see acwr.py's _MIN_DAYS guard).
    """
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} must not be after to_date {to_date}")

    if ctl_days is None or atl_days is None:
        default_ctl, default_atl = resolve_user_ewma_days(user_id)
        ctl_days = ctl_days if ctl_days is not None else default_ctl
        atl_days = atl_days if atl_days is not None else default_atl

    all_dates = [from_date + timedelta(days=i) for i in range((to_date - from_date).days + 1)]

    def _compute_range():
        # One 180-day-warmup pass covers the whole range; one extra
        # _ACWR_WINDOW_DAYS-1 days of lookback so the FIRST requested day
        # also gets a real ACWR window, not just days _ACWR_WINDOW_DAYS+
        # after from_date.
        warmup_start = from_date - timedelta(days=180)
        acwr_lookback_start = from_date - timedelta(days=_ACWR_WINDOW_DAYS - 1)
        series_start = min(warmup_start, acwr_lookback_start)
        series = daily_tss_series(user_id, series_start, to_date)
        curves = compute_load_curves(series, ctl_days=ctl_days, atl_days=atl_days)
        curve_by_date = {c["date"]: c for c in curves}
        tss_by_date = {d: t for d, t in series}
        out = []
        for d in all_dates:
            c = curve_by_date.get(d)
            if c is None:
                continue
            window = [
                tss_by_date.get(d - timedelta(days=_ACWR_WINDOW_DAYS - 1 - i), 0)
                for i in range(_ACWR_WINDOW_DAYS)
            ]
            out.append({
                "date": d, "tss": c["tss"], "ctl": c["ctl"], "atl": c["atl"],
                "tsb": c["tsb"], "acwr": _acwr_ratio_for_window(window),
            })
        return out

    if not _load_read_from_snapshot():
        return _compute_range()

    uid = _uuid_mod.UUID(str(user_id))
    with Session(engine) as session:
        existing = {
            s.snapshot_date: s
            for s in session.query(TrainingLoadSnapshot).filter(
                TrainingLoadSnapshot.user_id == uid,
                TrainingLoadSnapshot.snapshot_date >= from_date,
                TrainingLoadSnapshot.snapshot_date <= to_date,
            ).all()
        }
        current_signatures = _workout_signatures_for_range(session, uid, from_date, to_date)

    stale_or_missing = {
        d for d in all_dates
        if d not in existing
        or existing[d].formula_version != _FORMULA_VERSION
        or not _snap_matches_calibration(existing[d], ctl_days, atl_days)
        # A row with no recorded signature predates this check (migration
        # 63d019bb0d5b) — treat as stale so it self-heals on next read rather
        # than needing a one-time bulk backfill. A row whose stored signature
        # no longer matches the date's current workout data was cached before
        # that day's workout existed/was edited and never recomputed since —
        # the actual bug this whole check exists to close (found live: 3 of
        # the last 4 weeks had tss_for_day stuck at 0 despite real workouts).
        or existing[d].workout_signature != current_signatures.get(d, _NO_WORKOUTS_SIGNATURE)
    }

    computed_by_date: dict = {}
    if stale_or_missing:
        rows = []
        for c in _compute_range():
            if c["date"] not in stale_or_missing:
                continue
            row = {
                "user_id": uid, "snapshot_date": c["date"], "tss_for_day": c["tss"],
                "ctl": c["ctl"], "atl": c["atl"], "tsb": c["tsb"], "acwr": c["acwr"],
                "formula_version": _FORMULA_VERSION,
                "ctl_days": ctl_days,
                "atl_days": atl_days,
                "workout_signature": current_signatures.get(c["date"], _NO_WORKOUTS_SIGNATURE),
            }
            rows.append(row)
            computed_by_date[c["date"]] = c
        if rows:
            stmt = _pg_insert(TrainingLoadSnapshot).values(rows)
            upsert = stmt.on_conflict_do_update(
                index_elements=["user_id", "snapshot_date"],
                set_={
                    "tss_for_day": stmt.excluded.tss_for_day,
                    "ctl": stmt.excluded.ctl,
                    "atl": stmt.excluded.atl,
                    "tsb": stmt.excluded.tsb,
                    "acwr": stmt.excluded.acwr,
                    "formula_version": stmt.excluded.formula_version,
                    "ctl_days": stmt.excluded.ctl_days,
                    "atl_days": stmt.excluded.atl_days,
                    "workout_signature": stmt.excluded.workout_signature,
                    "computed_at": datetime.now(tz=timezone.utc),
                },
            )
            with Session(engine) as session:
                session.execute(upsert)
                session.commit()

    out = []
    for d in all_dates:
        if d in computed_by_date:
            out.append(computed_by_date[d])
        elif d in existing:
            s = existing[d]
            out.append({
                "date": d, "tss": s.tss_for_day, "ctl": s.ctl, "atl": s.atl,
                "tsb": s.tsb, "acwr": s.acwr,
            })
    return out


def recompute_user_snapshots(user_id: str) -> int:
    """Recompute and persist all training-load snapshots for a user from their
    earliest TSS workout to today, using the user's current calibration constants.

    Called after accepting a new calibration so the snapshot history reflects
    the updated ctl_days/atl_days. Reuses get_snapshot_series() — the single
    source of truth — which treats any snapshot whose stored constants differ
    from the user's current calibration as stale and rewrites it.

    Returns:
        Number of snapshot rows computed (0 when the user has no TSS workouts).
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT MIN(workout_date) FROM workouts "
                "WHERE user_id = :uid AND tss IS NOT NULL"
            ),
            {"uid": str(user_id)},
        ).first()
    if row is None or row[0] is None:
        return 0
    earliest = row[0]
    today = today_bangkok()
    rows = get_snapshot_series(user_id, earliest, today)
    return len(rows)


def _classify_zone(tsb: float) -> str:
    """Return the zone name for a single TSB value using named band constants.

    Canonical zone vocabulary (authoritative for this codebase):
        buried  — TSB below FORM_BURIED_CEILING (athlete is over-reached)
        neutral — TSB at or above FORM_BURIED_CEILING and below FORM_FRESH_FLOOR
        fresh   — TSB at or above FORM_FRESH_FLOOR (athlete is well-rested)

    All callers that classify TSB zones (performance_curve, _rdns_classify_zone
    in main.py, and any future additions) must use this vocabulary exclusively.
    """
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

    today = today_bangkok()
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
    today = today_bangkok()
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

    A taper means reducing training load to zero for the priority-appropriate
    number of days before the race.  This lets fatigue (ATL) decay faster than
    fitness (CTL), raising form (TSB = CTL − ATL) into the positive band.  The
    function projects form forward with zero load and checks whether race-day
    form will reach TARGET_FORM_LOWER.

    Args:
        fitness_state:
            Dict containing at minimum ``ctl``, ``atl``, and ``date``.  ``date``
            is the anchor day for the projection (typically today).  An optional
            ``priority`` key ("A" or "B") selects the taper length constant:
            A-race uses A_RACE_TAPER_DAYS; B-race uses B_RACE_TAPER_DAYS.
            Defaults to "A" when the key is absent.
        race_date:
            The target race date.  Must be in the future (strictly after today).
        target_form:
            The athlete's desired TSB value on race day.  Must not be None.
            The achievability check compares projected race-day form against
            this value: achievable is True when projected form >= target_form.

    Returns:
        On invalid input:
            Dict with ``taper_start_date=None``, ``message=None``,
            ``achievable=None``, and a non-empty ``reason`` string.
        On valid input with achievable=True:
            Dict with:
            ``taper_start_date`` -- date to begin easing load (race_date minus
                                    priority taper length constant).
            ``message``          -- plain-language guidance string.
            ``achievable``       -- True; projected race-day form reaches
                                    target_form.
            ``reason``           -- empty string.
        On valid input with achievable=False (race too close):
            Dict with:
            ``taper_start_date`` -- None; a positive form band cannot be reached.
            ``message``          -- honest plain-language statement.
            ``achievable``       -- False.
            ``reason``           -- empty string.

    Worked example 1 — Normal A-race taper:
        Inputs:
            fitness_state = {"ctl": 50.0, "atl": 60.0, "date": 2024-11-23,
                             "priority": "A"}
            race_date     = 2024-12-14  (21 days away)
            target_form   = 10.0

        With zero load for 21 days, ATL (time constant 7 days) decays from 60
        to roughly 3 (exp(-21/7) ≈ 0.05); CTL (time constant 42 days) decays
        from 50 to roughly 30 (exp(-21/42) ≈ 0.61).  Race-day form ≈ 30 − 3 = 27,
        which is above target_form (10.0), so achievable is True.

        Expected output:
            taper_start_date = 2024-11-30  (A_RACE_TAPER_DAYS before race)
            message = "Begin your taper on Nov 30 to arrive at race day in peak form."
            achievable = True

    Worked example 2 — Race too close to reach the positive form band:
        Inputs:
            fitness_state = {"ctl": 50.0, "atl": 90.0, "date": 2024-12-09}
            race_date     = 2024-12-13  (4 days away)
            target_form   = 10.0

        With zero load for 4 days, ATL decays from 90 to roughly 51 (each day
        ATL drops by alpha_atl ≈ 0.133 of the gap to zero).  CTL decays from 50
        to roughly 45.  Race-day form ≈ 45 − 51 = −6, which is below
        target_form (10.0), so achievable is False and the positive form band
        cannot be reached in time.

        Expected output:
            taper_start_date = None  (too close; cannot reach the positive band)
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

    today = today_bangkok()
    # Race must be in the future; a past or today race cannot be tapered into
    if race_date <= today:
        return {**_empty, "reason": "race_date must be in the future"}

    # Select taper length by race priority; default to A-race when unspecified
    priority = fitness_state.get("priority", "A") if isinstance(fitness_state, dict) else "A"
    taper_days = B_RACE_TAPER_DAYS if priority == "B" else A_RACE_TAPER_DAYS
    candidate_start = race_date - timedelta(days=taper_days)

    # Project form to race_date assuming zero load — simulates a full taper where
    # the athlete trains nothing from today until race day.  Fatigue (ATL) decays
    # with a short time constant while fitness (CTL) decays more slowly, so form
    # (CTL − ATL) rises over the taper window.  Delegates all math to project_form.
    projection = project_form(fitness_state, 0.0, race_date)
    if projection["reason"]:
        # project_form reported a validation error; surface it as our reason
        return {**_empty, "reason": projection["reason"]}

    # Race-day form is the last projected day in the series
    projected_race_form = projection["days"][-1]["form"]

    # Achievable when projected form reaches the caller's target; below target_form
    # the athlete will not be in the desired peaked state on race day
    achievable = projected_race_form >= target_form

    if achievable:
        # Format dates for readability: "Nov 30", "Dec 14"
        start_str = candidate_start.strftime("%b %-d")
        race_str = race_date.strftime("%b %-d")
        taper_label = "mini-taper" if priority == "B" else "taper"
        message = (
            f"Begin your {taper_label} on {start_str} "
            f"to arrive at race day in peak form on {race_str}."
        )
        return {
            "taper_start_date": candidate_start,
            "message": message,
            "achievable": True,
            "reason": "",
        }
    else:
        # Honest assessment: the positive band is out of reach given time remaining
        message = (
            "Race is too soon to reach a positive form band; "
            "manage fatigue rather than targeting a peak"
        )
        return {
            "taper_start_date": None,
            "message": message,
            "achievable": False,
            "reason": "",
        }


def get_taper_recommendation(
    user_id: str,
    race_date: date,
    target_form: float,
    priority: str = "A",
) -> dict:
    """Thin caller: fetch fitness state from DB, then compute taper recommendation.

    Responsibilities:
    - Calls current_load(user_id) to obtain today's CTL, ATL, and anchor date.
    - Delegates all recommendation logic to taper_recommendation (pure function).

    Args:
        user_id: the authenticated user's ID.
        race_date: the target race date.
        target_form: the athlete's desired TSB value on race day.
        priority: "A" for a goal race (A_RACE_TAPER_DAYS) or "B" for a tune-up
                  race (B_RACE_TAPER_DAYS). Defaults to "A".

    Returns:
        Same dict shape as taper_recommendation: {taper_start_date, message,
        achievable, reason}.
    """
    load_state = current_load(user_id)
    fitness_state = {
        "ctl": load_state["ctl"],
        "atl": load_state["atl"],
        "date": load_state["date"],
        "priority": priority,
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


def compute_calibration_suggestions(
    race_id,
    actual_time_seconds,
    user_constants,
    population_constants,
) -> dict:
    """Suggest adjusted fitness and fatigue time constants after a completed race.

    This is a pure function — it performs no database access and makes no writes.
    The calling layer is responsible for all DB reads (race row, user preferences,
    training-load snapshots) and for writing status and actual_time_seconds to the
    race row before invoking this function.

    The function compares two dimensions:
    - **Peak timing**: when the athlete's fitness peaked (actual_peak_week) versus
      when the model predicted it would peak (predicted_peak_week).  A timing_delta
      (actual minus predicted) that is negative means the athlete peaked EARLIER than
      the model expected; positive means later.
    - **Peak level**: how the athlete's finishing time compares to their goal time,
      expressed as a percentage (positive = faster than goal, negative = slower).

    Suggestion logic (timing dimension only drives constant changes):
    - Early peak (timing_delta more negative than timing_tolerance_weeks):
      shorten the fitness time constant so future predictions reflect faster peaking.
    - Late peak (timing_delta more positive than timing_tolerance_weeks):
      lengthen the fitness time constant so future predictions reflect slower peaking.
    - On target (|timing_delta| <= timing_tolerance_weeks): no adjustment.

    All numeric parameters are read from user_constants and population_constants; no
    bare literal thresholds appear in the function body.
    """
    _empty = {
        "suggested_ctl_days": None,
        "suggested_atl_days": None,
        "timing_delta_weeks": None,
        "peak_level_delta_pct": None,
        "explanation": None,
        "adjustment_direction": None,
        "reason": "",
    }

    if actual_time_seconds is None:
        return {**_empty, "reason": "actual_time_seconds is required to compute calibration"}

    if not population_constants:
        population_constants = {}
    if not user_constants:
        return {**_empty, "reason": "user_constants is required"}

    goal_time = user_constants.get("goal_time_seconds")
    if goal_time is None:
        return {**_empty, "reason": "race has no target time; cannot compute calibration"}

    predicted_peak_week = user_constants.get("predicted_peak_week")
    if predicted_peak_week is None:
        return {**_empty, "reason": "predicted_peak_week is required in user_constants"}

    actual_peak_week = user_constants.get("actual_peak_week")
    if actual_peak_week is None:
        return {**_empty, "reason": "actual_peak_week is required in user_constants"}

    ctl_days = user_constants.get("ctl_days") or population_constants.get("ctl_days", CTL_DAYS)
    atl_days = user_constants.get("atl_days") or population_constants.get("atl_days", ATL_DAYS)
    timing_tolerance = population_constants.get("timing_tolerance_weeks", TIMING_TOLERANCE_WEEKS)
    ctl_adj_per_week = population_constants.get("ctl_adjustment_days_per_week", CTL_ADJUSTMENT_DAYS_PER_WEEK)
    min_ctl = population_constants.get("min_ctl_days", MIN_CTL_DAYS)
    max_ctl = population_constants.get("max_ctl_days", MAX_CTL_DAYS)

    timing_delta = actual_peak_week - predicted_peak_week
    peak_level_delta_pct = round((goal_time - actual_time_seconds) / goal_time * 100, _LEVEL_DELTA_PRECISION)

    if timing_delta < -timing_tolerance:
        adjustment_days = abs(timing_delta) * ctl_adj_per_week
        suggested_ctl = max(min_ctl, ctl_days - adjustment_days)
        direction = "shorten"
        explanation = (
            f"Your fitness peaked approximately {abs(timing_delta)} week(s) earlier than "
            f"predicted (week {actual_peak_week} vs predicted week {predicted_peak_week}). "
            f"Shortening the fitness time constant from {ctl_days} to {suggested_ctl} days "
            f"will bring future peak predictions earlier to match your training response. "
            f"Performance was {abs(peak_level_delta_pct)}% "
            f"{'below' if peak_level_delta_pct < 0 else 'above'} your goal time."
        )
    elif timing_delta > timing_tolerance:
        adjustment_days = timing_delta * ctl_adj_per_week
        suggested_ctl = min(max_ctl, ctl_days + adjustment_days)
        direction = "lengthen"
        explanation = (
            f"Your fitness peaked approximately {timing_delta} week(s) later than "
            f"predicted (week {actual_peak_week} vs predicted week {predicted_peak_week}). "
            f"Lengthening the fitness time constant from {ctl_days} to {suggested_ctl} days "
            f"will shift future peak predictions later to match your training response. "
            f"Performance was {abs(peak_level_delta_pct)}% "
            f"{'below' if peak_level_delta_pct < 0 else 'above'} your goal time."
        )
    else:
        suggested_ctl = ctl_days
        direction = "none"
        explanation = (
            f"Your fitness peaked within {timing_tolerance} week(s) of the predicted week "
            f"(week {actual_peak_week} vs predicted week {predicted_peak_week}). "
            f"No adjustment to the fitness time constant is suggested. "
            f"Performance was {abs(peak_level_delta_pct)}% "
            f"{'below' if peak_level_delta_pct < 0 else 'above'} your goal time."
        )

    return {
        "suggested_ctl_days": int(suggested_ctl),
        "suggested_atl_days": int(atl_days),
        "timing_delta_weeks": timing_delta,
        "peak_level_delta_pct": peak_level_delta_pct,
        "explanation": explanation,
        "adjustment_direction": direction,
        "reason": "",
    }


def readiness_label(tsb: float) -> str:
    """Return a human-readable label for a TSB value using named constants.

    Labels are anchored to FORM_BURIED_CEILING and FORM_FRESH_FLOOR so that
    threshold values live only in those named constants, never as magic numbers
    inside the comparison logic.

    Returns one of READINESS_LABEL_FATIGUED, READINESS_LABEL_OPTIMAL, or
    READINESS_LABEL_FRESH.

    Worked example:
        FORM_BURIED_CEILING = -10.0, FORM_FRESH_FLOOR = 5.0

        tsb = -15  →  "Fatigued"   (below buried ceiling)
        tsb =   0  →  "Optimal"    (in the neutral band)
        tsb =  10  →  "Fresh"      (at or above fresh floor)
    """
    if tsb < FORM_BURIED_CEILING:
        return READINESS_LABEL_FATIGUED
    if tsb >= FORM_FRESH_FLOOR:
        return READINESS_LABEL_FRESH
    return READINESS_LABEL_OPTIMAL


def compute_fitness_series(
    user_id: str,
    from_date: date,
    to_date: date,
) -> list[dict]:
    """Fetch daily TSS from the database and compute the CTL/ATL/TSB series.

    This is the caller-layer function used by the readiness endpoint. It
    performs all database reads (via daily_tss_series) and delegates the
    computation to compute_load_curves. The endpoint must call this function
    rather than re-implementing the series calculation.

    Args:
        user_id: the authenticated user's ID string.
        from_date: start of the series window (inclusive). Use a 6-month
            lookback from today so that the EWMA has time to converge before
            the date range the caller actually needs.
        to_date: end of the series window (inclusive, typically today).

    Returns:
        List of dicts ordered ascending by date, each containing:
            date  -- the calendar day (date object)
            tss   -- daily TSS (int, 0 for rest days)
            ctl   -- Chronic Training Load (float, rounded to 2 dp)
            atl   -- Acute Training Load (float, rounded to 2 dp)
            tsb   -- Training Stress Balance, CTL − ATL (float, rounded to 2 dp)
    """
    daily_series = daily_tss_series(user_id, from_date, to_date)
    return compute_load_curves(daily_series)


def get_weekly_volume(user_id: str, week_start: date, week_end: date) -> dict:
    """Return aggregated weekly volume for a user over the given date range.

    Encapsulates the Workout query so endpoints do not re-aggregate from raw
    records (AC requirement from issue #1120 / original AC8 from #1055).

    Args:
        user_id: the authenticated user's UUID as a string.
        week_start: first day of the window (inclusive).
        week_end: last day of the window (inclusive).

    Returns:
        dict with keys:
            distance_km      -- total distance in km (float, 0.0 when none)
            total_tss        -- sum of TSS across all workouts (float, 0.0 when none)
            session_count    -- number of workouts in the window (int)
            duration_seconds -- summed workout duration in seconds (float, 0.0 when none)
            workout_types    -- list of workout_type strings (one per workout)
    """
    uid = _uuid_mod.UUID(str(user_id))

    def _to_float(v):
        try:
            return float(v) if v is not None else None
        except Exception:
            return None

    def _sum_float_attr(workouts, attr):
        vals = [_to_float(getattr(w, attr)) for w in workouts if getattr(w, attr, None) is not None]
        return round(sum(vals), 3) if vals else None

    with Session(engine) as session:
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= week_start,
                Workout.workout_date <= week_end,
            )
            .all()
        )

    session_count = len(workouts)
    raw_distance = _sum_float_attr(workouts, "distance_km")
    raw_tss = _sum_float_attr(workouts, "tss")
    raw_duration = _sum_float_attr(workouts, "duration_seconds")
    workout_types = [w.workout_type for w in workouts]

    return {
        "distance_km": raw_distance if raw_distance is not None else 0.0,
        "total_tss": round(raw_tss, 2) if raw_tss is not None else 0.0,
        "session_count": session_count,
        "duration_seconds": raw_duration if raw_duration is not None else 0.0,
        "workout_types": workout_types,
    }


# ── Planned-session TSS/distance estimation (rough, formula-only, no LLM) ─────
# Calendar/Plan progress bars want a sense of "TSS and km still coming this
# week" from PLANNED sessions, not just what's already logged — but
# PlannedSession has no duration/TSS columns (target_tss only ever existed
# ephemerally in the AI-suggestions flow, never persisted). Rather than a
# model call, derive it from the athlete's OWN recent pace/TSS-per-minute and
# scale it by the planned session's duration. Deliberately coarse ("roughly
# estimate", not a real TSS calc) — the real compute_running_tss/pace-IF
# machinery in tss.py needs a target pace or actual splits, neither of which
# a plan has.
_PLANNED_ESTIMATE_LOOKBACK_DAYS = 90
# Run sessions bucketed by duration — a long run and an interval session are
# typically run at meaningfully different paces, so one overall average would
# misrepresent both. Strength/plyo get a single combined TSS-per-minute rate
# (no distance concept).
_RUN_DURATION_BUCKETS = (("short", 0, 35), ("moderate", 35, 75), ("long", 75, None))
# Structure's exercise entries carry no duration — 5min/exercise (rest
# included) is a rough stand-in so a strength session still gets an estimate.
_STRENGTH_MIN_PER_EXERCISE = 5.0


def estimate_historical_pace_and_tss(user_id, db=None) -> dict:
    """Rough per-user baseline for estimate_planned_session_metrics(): average
    run pace (min/km) bucketed by duration, plus average TSS-per-minute for
    run and for strength/plyo, each from the trailing
    _PLANNED_ESTIMATE_LOOKBACK_DAYS of logged workouts. Any bucket with no
    supporting data returns None for that piece — callers must handle that
    (no data ⇒ no estimate, never a fabricated number).
    """
    uid = user_id if isinstance(user_id, _uuid_mod.UUID) else _uuid_mod.UUID(str(user_id))
    cutoff = today_bangkok() - timedelta(days=_PLANNED_ESTIMATE_LOOKBACK_DAYS)

    def _query(session):
        return (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= cutoff,
                Workout.duration_seconds.isnot(None),
                Workout.duration_seconds > 0,
            )
            .all()
        )

    if db is not None:
        workouts = _query(db)
    else:
        with Session(engine) as session:
            workouts = _query(session)

    run_pace_buckets = {b[0]: {"dur_min": 0.0, "dist_km": 0.0} for b in _RUN_DURATION_BUCKETS}
    run_tss = {"dur_min": 0.0, "tss": 0.0}
    strength_tss = {"dur_min": 0.0, "tss": 0.0}

    for w in workouts:
        dur_min = float(w.duration_seconds) / 60.0
        wt = (w.workout_type or "").lower()
        if wt == "run":
            if w.distance_km:
                for name, lo, hi in _RUN_DURATION_BUCKETS:
                    if dur_min >= lo and (hi is None or dur_min < hi):
                        run_pace_buckets[name]["dur_min"] += dur_min
                        run_pace_buckets[name]["dist_km"] += float(w.distance_km)
                        break
            if w.tss:
                run_tss["dur_min"] += dur_min
                run_tss["tss"] += float(w.tss)
        elif wt in ("strength", "plyo") and w.tss:
            strength_tss["dur_min"] += dur_min
            strength_tss["tss"] += float(w.tss)

    run_pace_min_per_km = {
        name: (v["dur_min"] / v["dist_km"]) if v["dist_km"] > 0 else None
        for name, v in run_pace_buckets.items()
    }
    return {
        "run_pace_min_per_km": run_pace_min_per_km,
        "run_tss_per_min": (run_tss["tss"] / run_tss["dur_min"]) if run_tss["dur_min"] > 0 else None,
        "strength_tss_per_min": (strength_tss["tss"] / strength_tss["dur_min"]) if strength_tss["dur_min"] > 0 else None,
    }


def _planned_duration_minutes(workout_type: str, structure) -> Optional[float]:
    """Best-effort planned duration in minutes from a session's structure —
    run: sum of block durations (see plan_matching._planned_duration_seconds,
    duplicated here in minutes to avoid a service-to-service import cycle);
    strength/plyo: exercise count × _STRENGTH_MIN_PER_EXERCISE proxy."""
    if not structure or not isinstance(structure, dict):
        return None
    wt = (workout_type or "").lower()
    if wt == "run":
        blocks = structure.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            return None
        total = 0.0
        saw = False
        for b in blocks:
            if not isinstance(b, dict):
                continue
            dur = b.get("duration_min")
            if dur is None:
                continue
            try:
                dur = float(dur)
            except (TypeError, ValueError):
                continue
            repeat = b.get("repeat")
            try:
                repeat = max(1, int(repeat)) if repeat is not None else 1
            except (TypeError, ValueError):
                repeat = 1
            rest = b.get("rest_min")
            try:
                rest = float(rest) if rest is not None else 0.0
            except (TypeError, ValueError):
                rest = 0.0
            total += dur * repeat + rest * max(0, repeat - 1)
            saw = True
        return total if saw else None
    if wt in ("strength", "plyo"):
        exercises = structure.get("exercises")
        if not isinstance(exercises, list) or not exercises:
            return None
        return len(exercises) * _STRENGTH_MIN_PER_EXERCISE
    return None


def estimate_planned_session_metrics(baseline: dict, workout_type: str, structure) -> dict:
    """Apply an estimate_historical_pace_and_tss() baseline to ONE planned
    session's structure. Returns {"estimated_tss": int|None,
    "estimated_distance_km": float|None} — both None when there's nothing to
    estimate from (no duration derivable, or no matching history)."""
    out = {"estimated_tss": None, "estimated_distance_km": None}
    dur_min = _planned_duration_minutes(workout_type, structure)
    if not dur_min:
        return out
    wt = (workout_type or "").lower()

    if wt == "run":
        for name, lo, hi in _RUN_DURATION_BUCKETS:
            if dur_min >= lo and (hi is None or dur_min < hi):
                pace = baseline.get("run_pace_min_per_km", {}).get(name)
                break
        else:
            pace = None
        if pace is None:
            # This duration bucket has no history of its own — fall back to
            # averaging whichever buckets DO have data rather than giving up.
            available = [v for v in baseline.get("run_pace_min_per_km", {}).values() if v]
            pace = (sum(available) / len(available)) if available else None
        if pace:
            out["estimated_distance_km"] = round(dur_min / pace, 1)
        if baseline.get("run_tss_per_min"):
            out["estimated_tss"] = round(dur_min * baseline["run_tss_per_min"])
    elif wt in ("strength", "plyo"):
        if baseline.get("strength_tss_per_min"):
            out["estimated_tss"] = round(dur_min * baseline["strength_tss_per_min"])

    return out
