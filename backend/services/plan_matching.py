"""plan_matching.py — match planned_sessions against reconciled workouts.

This is the planned_session→workout matcher for the new Plan tab. It is
SEPARATE from reconcile.py (which merges raw Strava/Stryd activities into the
``workouts`` truth table). Here we compare a user's hand-entered
``planned_sessions`` against those already-reconciled ``workouts`` and set a
reconciliation status per planned session.

Link-only: we set ``planned_sessions.matched_workout_id`` → ``workouts.id``; the
workout stays its own row and the Log tab is unchanged.

Thresholds are a documented FIRST PASS (see docs/calculations/plan-matching.md),
tunable later — keep the constants here as the single source of truth.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta, timezone as _timezone

from sqlalchemy.orm import Session as _Session

# ── Tunable thresholds (documented in docs/calculations/plan-matching.md) ──────
DAY_WINDOW = 1            # candidate workouts within ±1 day of planned_date
DURATION_AUTO = 0.20      # ±20% duration → high-confidence (done_auto)
DURATION_REVIEW = 0.40    # ±40% duration → still a review candidate (else drop)

_RUN_TYPES = {"run"}


def _now():
    return _datetime.now(_timezone.utc)


def _planned_duration_seconds(structure) -> int | None:
    """Best-effort planned duration (seconds) from a run/strength structure.

    Runs: sum block ``duration_min`` (× ``repeat`` when present, + rest × (repeat-1)).
    Strength/plyo: no reliable duration in the exercise schema → None.
    Returns None when nothing usable is present.
    """
    if not structure or not isinstance(structure, dict):
        return None
    blocks = structure.get("blocks")
    if not isinstance(blocks, list):
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
            repeat = int(repeat) if repeat is not None else 1
        except (TypeError, ValueError):
            repeat = 1
        repeat = max(1, repeat)
        rest = b.get("rest_min")
        try:
            rest = float(rest) if rest is not None else 0.0
        except (TypeError, ValueError):
            rest = 0.0
        total += dur * repeat + rest * max(0, repeat - 1)
        saw = True
    if not saw:
        return None
    return int(round(total * 60))


def _is_run_workout(workout) -> bool:
    return (workout.workout_type or "").lower() == "run"


def _type_family_matches(session_type: str, workout) -> bool:
    """planned run ↔ run-family workout; planned strength/plyo ↔ non-run workout."""
    st = (session_type or "").lower()
    if st == "run":
        return _is_run_workout(workout)
    if st in ("strength", "plyo"):
        return not _is_run_workout(workout)
    return False


def _duration_ratio(planned_secs: int | None, workout) -> float | None:
    """abs relative duration diff, or None when planned duration is unknown."""
    if not planned_secs or planned_secs <= 0:
        return None
    actual = workout.duration_seconds
    if not actual or actual <= 0:
        return None
    return abs(actual - planned_secs) / float(planned_secs)


def reconcile_user(session: _Session, user_id) -> dict:
    """Run the matcher for one user against their reconciled workouts.

    Idempotent: never overwrites a ``done_manual`` link or an existing
    ``done_auto`` link; only fills ``planned`` / ``missed`` / ``needs_review``
    slots. A user unmatch/miss is respected until the underlying data changes.

    Returns ``{"updated": n, "statuses": {status: count}}``.
    """
    from backend.models import PlannedSession, Workout

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    today = _date.today()

    planned = (
        session.query(PlannedSession)
        .filter(PlannedSession.user_id == uid)
        .all()
    )
    if not planned:
        return {"updated": 0, "statuses": {}}

    dates = [p.planned_date for p in planned if p.planned_date is not None]
    if not dates:
        return {"updated": 0, "statuses": {}}
    lo = min(dates) - _timedelta(days=DAY_WINDOW)
    hi = max(dates) + _timedelta(days=DAY_WINDOW)

    workouts = (
        session.query(Workout)
        .filter(
            Workout.user_id == uid,
            Workout.workout_date >= lo,
            Workout.workout_date <= hi,
        )
        .all()
    )

    # Workouts already claimed by a done_auto / done_manual planned session are
    # off the table for new matches (one workout fulfils at most one session).
    claimed = {
        p.matched_workout_id
        for p in planned
        if p.matched_workout_id is not None
        and p.status in ("done_auto", "done_manual")
    }

    updated = 0
    for p in planned:
        st = (p.session_type or "").lower()
        if st == "rest":
            continue
        # Respect resolved/locked links — idempotent re-run.
        if p.status in ("done_auto", "done_manual"):
            continue

        planned_secs = _planned_duration_seconds(p.structure)

        same_day, off_day = [], []
        for w in workouts:
            if w.id in claimed:
                continue
            if not _type_family_matches(st, w):
                continue
            if w.workout_date is None or p.planned_date is None:
                continue
            delta = abs((w.workout_date - p.planned_date).days)
            if delta > DAY_WINDOW:
                continue
            ratio = _duration_ratio(planned_secs, w)
            # Drop candidates that are wildly off on duration (> ±40%).
            if ratio is not None and ratio > DURATION_REVIEW:
                continue
            (same_day if delta == 0 else off_day).append((w, ratio))

        new_status = None
        new_match = None

        if len(same_day) == 1 and not off_day:
            w, ratio = same_day[0]
            if ratio is None or ratio <= DURATION_AUTO:
                new_status, new_match = "done_auto", w.id
            else:
                new_status, new_match = "needs_review", None
        elif same_day or off_day:
            # 2+ same-day, a single day±1, or a same-day outside ±20% (≤ ±40%)
            new_status, new_match = "needs_review", None
        else:
            # No candidate at all.
            if p.planned_date < today:
                new_status = "missed"
            else:
                new_status = None  # future/today with nothing yet → leave planned

        # Apply only when it changes something meaningful.
        target_status = new_status if new_status is not None else "planned"
        changed = False
        if new_status == "done_auto":
            if p.matched_workout_id != new_match or p.status != "done_auto":
                p.matched_workout_id = new_match
                p.status = "done_auto"
                claimed.add(new_match)
                changed = True
        else:
            # needs_review / missed / planned: clear any stale (non-manual) link.
            if p.matched_workout_id is not None:
                p.matched_workout_id = None
                changed = True
            if p.status != target_status:
                p.status = target_status
                changed = True

        if changed:
            p.updated_at = _now()
            updated += 1

    session.commit()

    counts: dict = {}
    for p in planned:
        counts[p.status] = counts.get(p.status, 0) + 1
    return {"updated": updated, "statuses": counts}


def unplanned_workout_ids(session: _Session, user_id, start: _date, end: _date) -> set:
    """Workout ids in [start,end] NOT linked to any planned session — ghosts.

    Only workouts on a day that HAS at least one planned session of a compatible
    type-family count as ghosts (an unmatched activity the user might map).
    """
    from backend.models import PlannedSession, Workout

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))

    planned = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == uid,
            PlannedSession.planned_date >= start,
            PlannedSession.planned_date <= end,
        )
        .all()
    )
    matched_ids = {p.matched_workout_id for p in planned if p.matched_workout_id is not None}
    # planned sessions by date (excluding rest) for the compatibility check
    by_date: dict = {}
    for p in planned:
        if (p.session_type or "").lower() == "rest":
            continue
        by_date.setdefault(p.planned_date, []).append(p)

    workouts = (
        session.query(Workout)
        .filter(
            Workout.user_id == uid,
            Workout.workout_date >= start,
            Workout.workout_date <= end,
        )
        .all()
    )
    ghosts = set()
    for w in workouts:
        if w.id in matched_ids:
            continue
        sessions_that_day = by_date.get(w.workout_date)
        if not sessions_that_day:
            continue
        if any(_type_family_matches(p.session_type, w) for p in sessions_that_day):
            ghosts.add(w.id)
    return ghosts
