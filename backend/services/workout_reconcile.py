"""Reconcile strava_activities cache into unified workout rows."""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session as _Session
from backend.utils.time import today_bangkok

_TOLERANCE = timedelta(minutes=5)

_WORKOUT_TYPE_MAP = {
    "Run": "run",
    "Ride": "bike",
    # Strava strength sessions -> our "strength" so the exercise editor shows.
    "WeightTraining": "strength",
    "Workout": "strength",
}


def _map_workout_type(activity_type: str) -> str:
    return _WORKOUT_TYPE_MAP.get(activity_type, "other")


def _find_match(activity, workouts: list, tolerance: timedelta):
    """Return closest existing workout on same date within tolerance, or None."""
    if activity.start_time is None:
        return None
    act_date = activity.start_time.astimezone(timezone.utc).date()
    act_ts = activity.start_time
    lower = act_ts - tolerance
    upper = act_ts + tolerance
    candidates = [
        w for w in workouts
        if w.workout_date == act_date
        and w.start_time is not None
        and lower <= w.start_time <= upper
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda w: abs((w.start_time - act_ts).total_seconds()))


def reconcile_strava_to_workouts(
    user_id,
    tolerance: timedelta = _TOLERANCE,
) -> dict:
    """Convert unlinked strava_activities rows into workout records.

    Skips activities that are already linked (strava_activity_pk set on a workout).
    On match: fills null columns from the cache row, sets source to 'both' if
    the existing workout was manual.
    On no match: creates a new workout row with source='strava'.

    Returns: {"matched_to_existing": N, "created_new": N, "total_processed": N}
    """
    from backend.db import engine
    from backend.models import StravaActivity, Workout
    from backend.services.tss import estimate_tss_for_workout

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    matched = 0
    created = 0

    with _Session(engine) as session:
        all_strava = (
            session.query(StravaActivity)
            .filter(StravaActivity.user_id == uid)
            .all()
        )
        existing_workouts = (
            session.query(Workout)
            .filter(Workout.user_id == uid)
            .all()
        )

        linked_ids = {
            w.strava_activity_pk
            for w in existing_workouts
            if w.strava_activity_pk is not None
        }
        # Skip activities the user manually removed so we never recreate them.
        from backend.models import RemovedActivity

        removed_external = {
            ext for (ext,) in
            session.query(RemovedActivity.external_id)
            .filter(RemovedActivity.user_id == uid, RemovedActivity.source == "strava")
            .all()
        }
        unlinked = [
            a for a in all_strava
            if a.id not in linked_ids
            and str(a.strava_activity_id) not in removed_external
        ]

        for act in unlinked:
            # TSS formula priority: power > pace > HR > duration_only.
            # Only route to power formula when Stryd-synced AND raw_payload confirms power data.
            raw = act.raw_payload or {}
            use_power = bool(act.is_stryd_synced) and bool(raw.get("average_watts"))
            tss_proxy = SimpleNamespace(
                avg_power_w=act.avg_power_w if use_power else None,
                avg_hr=act.avg_hr,
                duration_seconds=act.duration_seconds,
                distance_km=float(act.distance_km) if act.distance_km is not None else None,
                avg_pace_seconds_per_km=None,
            )
            tss_val, tss_src = estimate_tss_for_workout(tss_proxy, uid, session)
            hit = _find_match(act, existing_workouts, tolerance)

            if hit:
                hit.strava_activity_pk = act.id
                hit.source = "both" if hit.source == "manual" else "strava"
                if hit.distance_km is None:
                    hit.distance_km = act.distance_km
                if hit.duration_seconds is None:
                    hit.duration_seconds = act.duration_seconds
                if hit.avg_hr is None:
                    from backend.services.workout_merge import clean_hr

                    hit.avg_hr = clean_hr(act.avg_hr)
                if hit.tss is None:
                    hit.tss = tss_val
                    hit.tss_source = tss_src
                matched += 1
            else:
                wdate = (
                    act.start_time.astimezone(timezone.utc).date()
                    if act.start_time
                    else today_bangkok()
                )
                w = Workout(
                    user_id=uid,
                    workout_date=wdate,
                    name=act.name or "Untitled",
                    workout_type=_map_workout_type(act.activity_type),
                    source="strava",
                    strava_activity_pk=act.id,
                    start_time=act.start_time,
                    distance_km=act.distance_km,
                    duration_seconds=act.duration_seconds,
                    avg_hr=act.avg_hr,
                    max_hr=act.max_hr,
                    elevation_m=act.elevation_m,
                    tss=tss_val,
                    tss_source=tss_src,
                )
                session.add(w)
                existing_workouts.append(w)
                created += 1

        session.commit()

    return {
        "matched_to_existing": matched,
        "created_new": created,
        "total_processed": matched + created,
    }


def strava_activities_dry_run(
    user_id,
    since_date: date | None = None,
    limit: int = 20,
) -> dict:
    """Read-only preview of what reconcile_strava_to_workouts would produce.

    Queries strava_activities (already cached), applies since_date filter,
    runs match logic against workouts in read-only mode — no DB writes.

    Returns:
      {
        "would_fetch_estimate": "N+" | "N",
        "preview": [
          {
            "strava_activity_id": int,
            "name": str,
            "activity_type": str,
            "start_time": ISO str,
            "distance_km": float | None,
            "would_match_existing_workout_id": str | None,
            "would_match_workout_date": str | None,
            "would_create_new": bool,
            "is_stryd_synced": bool,
          }
        ]
      }
    """
    from backend.db import engine
    from backend.models import StravaActivity, Workout

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))

    since_ts: datetime | None = None
    if since_date is not None:
        if isinstance(since_date, str):
            since_date = date.fromisoformat(since_date)
        since_ts = datetime(since_date.year, since_date.month, since_date.day, tzinfo=timezone.utc)

    with _Session(engine) as session:
        q = session.query(StravaActivity).filter(StravaActivity.user_id == uid)
        if since_ts is not None:
            q = q.filter(StravaActivity.start_time >= since_ts)
        rows = q.order_by(StravaActivity.start_time.desc()).limit(limit + 1).all()

        has_more = len(rows) > limit
        rows = rows[:limit]
        would_fetch_estimate = f"{limit}+" if has_more else str(len(rows))

        existing_workouts = (
            session.query(Workout)
            .filter(Workout.user_id == uid)
            .all()
        )

        preview = []
        for act in rows:
            hit = _find_match(act, existing_workouts, _TOLERANCE)
            start_iso = (
                act.start_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if act.start_time
                else None
            )
            dist = float(act.distance_km) if act.distance_km is not None else None
            preview.append({
                "strava_activity_id": act.strava_activity_id,
                "name": act.name,
                "activity_type": act.activity_type,
                "start_time": start_iso,
                "distance_km": dist,
                "would_match_existing_workout_id": str(hit.id) if hit else None,
                "would_match_workout_date": hit.workout_date.isoformat() if hit else None,
                "would_create_new": hit is None,
                "is_stryd_synced": bool(act.is_stryd_synced),
            })

    return {
        "would_fetch_estimate": would_fetch_estimate,
        "preview": preview,
    }
