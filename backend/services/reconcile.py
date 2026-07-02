"""Reconcile source activities (Strava, Stryd) into unified workout rows."""
from __future__ import annotations

import uuid as _uuid
from datetime import date, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import and_ as _and, or_ as _or
from sqlalchemy.orm import Session as _Session, defer as _defer


_TOLERANCE = timedelta(minutes=5)


def _build_workout_index(workouts: list) -> dict:
    """Index workouts by date for O(1) date lookup instead of O(n) full scan."""
    index: dict = {}
    for w in workouts:
        if w.start_time is not None:
            index.setdefault(w.start_time.date(), []).append(w)
    return index


def _find_in_index(start_time, index: dict, tolerance: timedelta):
    """Match a workout using the date-bucketed index.

    Checks same date and adjacent dates so activities near midnight are found
    even when the tolerance window crosses a day boundary.
    """
    if start_time is None:
        return None
    lower = start_time - tolerance
    upper = start_time + tolerance
    candidates = []
    for d in {lower.date(), start_time.date(), upper.date()}:
        candidates.extend(index.get(d, []))
    matches = [w for w in candidates if w.start_time and lower <= w.start_time <= upper]
    if not matches:
        return None
    return min(matches, key=lambda w: abs((w.start_time - start_time).total_seconds()))


def _make_proxy(
    act,
    source_type: str,
    existing_workout=None,
    *,
    strava_by_id: dict | None = None,
    stryd_by_id: dict | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace compatible with compute_best_values.

    When reconciling a second source onto an existing workout, attach both
    source activities so field precedence (e.g. Strava distance before Stryd)
    is evaluated correctly in a single pass.
    """
    ow = existing_workout
    strava = act if source_type == "strava" else None
    stryd = act if source_type == "stryd" else None
    if ow is not None:
        if strava is None and getattr(ow, "strava_activity_pk", None) and strava_by_id:
            strava = strava_by_id.get(ow.strava_activity_pk)
        if stryd is None and getattr(ow, "stryd_activity_pk", None) and stryd_by_id:
            stryd = stryd_by_id.get(ow.stryd_activity_pk)
    return SimpleNamespace(
        manual_overrides=getattr(ow, "manual_overrides", None) if ow else None,
        strava_activity=strava,
        stryd_activity=stryd,
        distance_km=float(ow.distance_km) if ow and getattr(ow, "distance_km", None) is not None else None,
        duration_seconds=getattr(ow, "duration_seconds", None) if ow else None,
        avg_hr=getattr(ow, "avg_hr", None) if ow else None,
        avg_power_w=None,
        tss=getattr(ow, "tss", None) if ow else None,
        name=getattr(ow, "name", None) if ow else None,
    )


def _apply_best(workout, best: dict) -> None:
    if best.get("best_name"):
        workout.name = best["best_name"]
    if best.get("best_distance_km") is not None:
        workout.distance_km = best["best_distance_km"]
    if best.get("best_duration_seconds") is not None:
        workout.duration_seconds = best["best_duration_seconds"]
    if best.get("best_avg_hr") is not None:
        from backend.services.workout_merge import clean_hr

        hr = clean_hr(best["best_avg_hr"])
        if hr is not None:
            workout.avg_hr = hr
    if best.get("best_tss") is not None:
        workout.tss = best["best_tss"]


def _apply_stryd_metrics(workout, act) -> None:
    """Copy workout-level Stryd power/cadence/stride aggregates onto the workout."""
    fm = getattr(act, "form_metrics", None) or {}
    if getattr(act, "avg_power_w", None) is not None:
        workout.avg_power = int(act.avg_power_w)
    if fm.get("max_power_w") is not None:
        workout.max_power = int(fm["max_power_w"])
    if fm.get("np_w") is not None:
        workout.np = int(fm["np_w"])
    if fm.get("cadence_spm") is not None:
        workout.avg_cadence_spm = int(round(fm["cadence_spm"]))
    if fm.get("stride_length_m") is not None:
        workout.avg_stride_m = round(float(fm["stride_length_m"]), 2)


def _sync_splits(session, workout, act) -> None:
    """Replace a workout's splits from the Stryd activity's computed km-splits."""
    from backend.models import WorkoutSplit
    splits = getattr(act, "splits", None)
    if not isinstance(splits, list) or not splits or not isinstance(splits[0], dict):
        return
    session.query(WorkoutSplit).filter(WorkoutSplit.workout_id == workout.id).delete()
    session.flush()
    # Index by position (1-based) so it is always unique, regardless of the
    # source dict's own index field. Fields read defensively across split shapes.
    session.add_all([
        WorkoutSplit(
            workout_id=workout.id,
            split_index=i,
            distance_km=s.get("distance_km") or 0,
            duration_seconds=s.get("duration_seconds") or 0,
            avg_hr=s.get("avg_hr"),
            avg_power=s.get("avg_power") if s.get("avg_power") is not None else s.get("avg_power_w"),
            cadence_spm=s.get("cadence_spm"),
            stride_length_m=s.get("stride_length_m"),
        )
        for i, s in enumerate(splits, start=1)
    ])


def _ingest_streams(session, all_acts, existing_workouts) -> None:
    """Write activity_streams rows for every workout that has stream data.

    Called after session.flush() so all workouts have UUIDs.  Failures on
    individual activities are logged and skipped — they must not abort the
    surrounding reconcile transaction.

    Also computes and persists Normalized Power from the power_w channel when
    present, using compute_normalized_power (pure; no DB access inside that fn).
    """
    from backend.services.activity_streams import (
        extract_strava_streams,
        extract_stryd_streams,
        write_activity_stream,
    )
    from backend.services.normalized_power import compute_normalized_power
    import logging
    _log = logging.getLogger(__name__)

    for source_type, act in all_acts:
        try:
            streams_payload = getattr(act, "streams_payload", None)
            if not streams_payload:
                continue
            if source_type == "strava":
                row_data, reason = extract_strava_streams(streams_payload, source="strava")
            else:
                row_data, reason = extract_stryd_streams(streams_payload, source="stryd")

            if reason:
                _log.debug("streams skipped", extra={"source": source_type, "reason": reason})
                continue

            # Find the workout that corresponds to this activity
            workout = _find_workout_for_activity(act, source_type, existing_workouts)
            if workout is None or workout.id is None:
                continue

            write_activity_stream(workout.id, row_data, session)

            # Compute NP from the power stream and persist on the workout.
            # sample_interval_seconds comes from row_data (never hardcoded here).
            power_samples = row_data.get("power_w")
            if power_samples:
                sample_interval = row_data.get("sample_interval_seconds", 1)
                np_val, _ = compute_normalized_power(power_samples, sample_interval)
                if np_val is not None:
                    workout.np = np_val

        except Exception as exc:
            _log.warning(
                "activity_streams ingest failed",
                extra={"source": source_type, "activity_id": getattr(act, "id", None), "error": str(exc)},
            )
        finally:
            # streams_payload is a deferred column lazy-loaded by the getattr
            # above; without expiring it every payload stays in the session's
            # identity map for the whole reconcile (~600 MB on a full sync).
            # Expire keeps peak memory at one payload at a time. No-op for
            # non-ORM stand-ins (unit tests pass SimpleNamespace activities).
            if hasattr(act, "_sa_instance_state"):
                try:
                    session.expire(act, ["streams_payload"])
                except Exception:  # noqa: BLE001 — cleanup must never fail ingest
                    pass


def _find_workout_for_activity(act, source_type: str, existing_workouts: list):
    """Return the workout matched to this activity, or None."""
    pk = act.id
    if source_type == "strava":
        for w in existing_workouts:
            if getattr(w, "strava_activity_pk", None) == pk:
                return w
    else:
        for w in existing_workouts:
            if getattr(w, "stryd_activity_pk", None) == pk:
                return w
    return None


def _merge_source(current: str | None, new_source: str) -> str:
    if not current or current == new_source:
        return new_source
    if current == "manual":
        return current
    # Both strava and stryd present
    return "strava,stryd"


def reconcile_workouts(
    job_id,
    user_id,
    *,
    stryd_activity_ids: list[str] | None = None,
    strava_activity_ids: list[int] | None = None,
) -> None:
    """Merge strava_activities (and stryd_activities) into workouts.

    When stryd_activity_ids / strava_activity_ids are provided, only those source
    rows are merged (incremental sync). Otherwise every cached activity is processed.

    Phase transitions: sets 'reconciling'. Caller is responsible for mark_success.
    """
    from backend.db import engine
    from backend.models import Workout, StravaActivity, StrydActivity
    from backend.services import sync_jobs
    from backend.services.workout_merge import compute_best_values

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    sync_jobs.set_phase(uid, "reconciling")
    incremental = stryd_activity_ids is not None or strava_activity_ids is not None
    affected_workout_ids: set = set()

    with _Session(engine) as session:
        # -- Source activity load --
        # Strategy: load the source with explicit IDs first (incremental), then
        # derive a time window from those activities to scope the OTHER source.
        # This prevents a Stryd-only incremental sync from loading the entire
        # Strava table (and vice-versa).  Full syncs defer heavy JSONB columns.

        def _time_window(acts):
            times = [a.start_time for a in (acts or []) if a.start_time]
            if not times:
                return None, None
            return min(times) - _TOLERANCE, max(times) + _TOLERANCE

        if strava_activity_ids is not None:
            strava_acts = (
                session.query(StravaActivity)
                .filter(
                    StravaActivity.user_id == uid,
                    StravaActivity.strava_activity_id.in_(strava_activity_ids),
                )
                .options(
                    _defer(StravaActivity.streams_payload),
                    _defer(StravaActivity.detail_payload),
                )
                .all()
            )
        else:
            # Resolved after Stryd load when doing a Stryd-only incremental sync.
            strava_acts = None if stryd_activity_ids is not None else (
                session.query(StravaActivity)
                .filter(StravaActivity.user_id == uid)
                .options(
                    _defer(StravaActivity.streams_payload),
                    _defer(StravaActivity.detail_payload),
                )
                .all()
            )

        try:
            if stryd_activity_ids is not None:
                stryd_acts = (
                    session.query(StrydActivity)
                    .filter(
                        StrydActivity.user_id == uid,
                        StrydActivity.stryd_activity_id.in_(stryd_activity_ids),
                    )
                    .options(_defer(StrydActivity.streams_payload))
                    .all()
                )
            else:
                # Resolved after Strava load when doing a Strava-only incremental sync.
                stryd_acts = None if strava_activity_ids is not None else (
                    session.query(StrydActivity)
                    .filter(StrydActivity.user_id == uid)
                    .options(_defer(StrydActivity.streams_payload))
                    .all()
                )
        except Exception:
            stryd_acts = []

        # Resolve deferred sources by scoping to the time window of the loaded source.
        if strava_acts is None:
            try:
                lo, hi = _time_window(stryd_acts)
                q = session.query(StravaActivity).filter(StravaActivity.user_id == uid)
                if lo is not None:
                    q = q.filter(StravaActivity.start_time.between(lo, hi))
                q = q.options(
                    _defer(StravaActivity.streams_payload),
                    _defer(StravaActivity.detail_payload),
                )
                strava_acts = q.all()
            except Exception:
                strava_acts = []

        if stryd_acts is None:
            try:
                lo, hi = _time_window(strava_acts)
                q = session.query(StrydActivity).filter(StrydActivity.user_id == uid)
                if lo is not None:
                    q = q.filter(StrydActivity.start_time.between(lo, hi))
                q = q.options(_defer(StrydActivity.streams_payload))
                stryd_acts = q.all()
            except Exception:
                stryd_acts = []

        all_acts = [("strava", a) for a in strava_acts] + [("stryd", a) for a in stryd_acts]

        # Drop activities the user manually removed so we never recreate the
        # workout. Keyed by external id (strava bigint / stryd string) as text.
        from backend.models import RemovedActivity

        removed = set(
            session.query(RemovedActivity.source, RemovedActivity.external_id)
            .filter(RemovedActivity.user_id == uid)
            .all()
        )
        if removed:
            all_acts = [
                (st, a) for (st, a) in all_acts
                if (st, str(a.strava_activity_id if st == "strava" else a.stryd_activity_id)) not in removed
            ]

        strava_by_id = {a.id: a for a in strava_acts}
        stryd_by_id = {a.id: a for a in stryd_acts}

        # -- Existing workout load --
        # Incremental: scope the query to workouts that are already linked to
        # these source activities or fall within their time window (±tolerance).
        # This avoids loading every workout for daily syncs of 10 activities.
        # Full: load all workouts (no JSONB payloads, so this is manageable).
        if incremental and all_acts:
            strava_pks = [a.id for a in strava_acts]
            stryd_pks = [a.id for a in stryd_acts]
            start_times = [a.start_time for _, a in all_acts if a.start_time]
            conditions: list = []
            if strava_pks:
                conditions.append(Workout.strava_activity_pk.in_(strava_pks))
            if stryd_pks:
                conditions.append(Workout.stryd_activity_pk.in_(stryd_pks))
            if start_times:
                lo = min(start_times) - _TOLERANCE
                hi = max(start_times) + _TOLERANCE
                conditions.append(_and(Workout.start_time >= lo, Workout.start_time <= hi))
            existing_workouts: list = (
                session.query(Workout)
                .filter(Workout.user_id == uid, _or(*conditions))
                .all()
                if conditions else []
            )
        else:
            existing_workouts: list = session.query(Workout).filter(Workout.user_id == uid).all()

        sync_jobs.reset_progress(uid, total=len(all_acts))

        workout_index = _build_workout_index(existing_workouts)
        stryd_pairs = []
        touched_workouts: list = []
        for source_type, act in all_acts:
            matched = _find_in_index(act.start_time, workout_index, _TOLERANCE)
            proxy = _make_proxy(
                act,
                source_type,
                matched,
                strava_by_id=strava_by_id,
                stryd_by_id=stryd_by_id,
            )
            best = compute_best_values(proxy)

            if matched:
                if source_type == "strava":
                    matched.strava_activity_pk = act.id
                    matched.source = _merge_source(matched.source, "strava")
                else:
                    matched.stryd_activity_pk = act.id
                    matched.source = _merge_source(matched.source, "stryd")
                _apply_best(matched, best)
                target = matched
            else:
                wdate = act.start_time.astimezone(timezone.utc).date() if act.start_time else date.today()
                # Map the raw Strava sport_type to our canonical workout_type
                # (e.g. WeightTraining/Workout -> "strength"). Stryd activities
                # are always runs. Without this, a Strava strength session lands
                # as the raw "WeightTraining" string and the UI never shows the
                # exercise editor.
                if source_type == "strava":
                    from backend.services.workout_reconcile import _map_workout_type
                    wtype = _map_workout_type(getattr(act, "activity_type", None) or "")
                else:
                    wtype = "run"
                w = Workout(
                    user_id=uid,
                    workout_date=wdate,
                    name=best["best_name"] or getattr(act, "name", None) or "Untitled",
                    workout_type=wtype,
                    source=source_type,
                    start_time=act.start_time,
                )
                if source_type == "strava":
                    w.strava_activity_pk = act.id
                else:
                    w.stryd_activity_pk = act.id
                _apply_best(w, best)
                session.add(w)
                existing_workouts.append(w)
                if w.start_time is not None:
                    workout_index.setdefault(w.start_time.date(), []).append(w)
                target = w

            if source_type == "stryd":
                _apply_stryd_metrics(target, act)
                stryd_pairs.append((target, act))

            touched_workouts.append(target)

            sync_jobs.increment(uid, current=1)

        # Flush so newly-created workouts have ids, then (re)build their splits
        # and ingest activity streams into activity_streams.
        session.flush()
        # Collect IDs while the session is still open — accessing ORM attributes
        # after session.commit() raises DetachedInstanceError (SQLAlchemy expires
        # all instance state on commit).
        affected_workout_ids = {w.id for w in touched_workouts if w.id is not None}
        for workout, act in stryd_pairs:
            _sync_splits(session, workout, act)

        _ingest_streams(session, all_acts, existing_workouts)

        session.commit()

    # Derive TSS (fallback) + Zone-2 minutes for runs from the now-current splits.
    compute_run_metrics(
        user_id,
        workout_ids=affected_workout_ids if incremental else None,
    )

    # Update the per-athlete best-effort duration curve for touched runs only.
    _update_duration_curves(
        uid,
        workout_ids=affected_workout_ids if incremental else None,
    )


def compute_run_metrics(user_id, workout_ids: set | list | None = None) -> None:
    """Per-run: fill zone2_minutes (time in the user's Zone-2 HR band) from the
    km-splits, and TSS via tss.py when a run has none (no Stryd stress).

    Thresholds + Zone-2 band come from user_preferences (defaults applied here).
    When workout_ids is set, only those runs are updated (incremental sync)."""
    from backend.db import engine
    from backend.models import UserPreferences, Workout, WorkoutSplit
    from backend.services.tss import estimate_tss_for_workout
    from types import SimpleNamespace

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    with _Session(engine) as session:
        prefs = session.query(UserPreferences).filter(UserPreferences.user_id == uid).first()
        z_min = (prefs.zone2_hr_min if prefs and prefs.zone2_hr_min is not None else 130)
        z_max = (prefs.zone2_hr_max if prefs and prefs.zone2_hr_max is not None else 155)

        q = session.query(Workout).filter(Workout.user_id == uid, Workout.workout_type.ilike("run"))
        if workout_ids is not None:
            allowed = [wid if isinstance(wid, _uuid.UUID) else _uuid.UUID(str(wid)) for wid in workout_ids]
            q = q.filter(Workout.id.in_(allowed))
        runs = q.all()
        run_ids = [w.id for w in runs]
        splits_by: dict = {}
        if run_ids:
            for s in session.query(WorkoutSplit).filter(WorkoutSplit.workout_id.in_(run_ids)).all():
                splits_by.setdefault(s.workout_id, []).append(s)

        for w in runs:
            sp = splits_by.get(w.id, [])
            if sp:
                z2s = sum((s.duration_seconds or 0) for s in sp
                          if s.avg_hr is not None and z_min <= s.avg_hr <= z_max)
                w.zone2_minutes = round(z2s / 60)
            elif w.avg_hr is not None and w.duration_seconds and z_min <= w.avg_hr <= z_max:
                w.zone2_minutes = round(w.duration_seconds / 60)

            if w.tss is None and w.duration_seconds:
                proxy = SimpleNamespace(
                    duration_seconds=w.duration_seconds,
                    avg_power_w=w.avg_power,
                    avg_hr=w.avg_hr,
                    distance_km=float(w.distance_km) if w.distance_km is not None else None,
                    avg_pace_seconds_per_km=None,
                )
                tss, src = estimate_tss_for_workout(proxy, uid, session)
                w.tss = tss
                w.tss_source = src

        # Weeks touched by these runs — collected while attributes are still
        # loaded (before commit expires them).
        touched_weeks = {
            w.workout_date - timedelta(days=w.workout_date.weekday())
            for w in runs
            if w.workout_date is not None
        }

        session.commit()

    # Sync writes runs directly via reconcile, bypassing the workout CRUD
    # endpoints that normally trigger habit autofill. Re-run autofill for the
    # touched weeks so workout-sourced habits (e.g. Zone-2 minutes) pick up the
    # freshly-computed zone2_minutes. Runs after the commit above so autofill's
    # own session sees the persisted values.
    if touched_weeks:
        import logging
        from backend.services.habit_autofill import recompute_autofill_for_week

        _log = logging.getLogger(__name__)
        for ws in touched_weeks:
            try:
                recompute_autofill_for_week(uid, ws)
            except Exception:
                _log.warning(
                    "habit autofill failed after run-metrics for user %s week %s",
                    uid,
                    ws,
                    exc_info=True,
                )


def _update_duration_curves(user_id, workout_ids: set | list | None = None) -> None:
    """Rebuild the stored best-effort duration curve for run workouts of one athlete.

    Called automatically by reconcile_workouts after each sync completes. When
    workout_ids is set, only those runs are updated (incremental sync).
    """
    from backend.db import engine
    from backend.models import Workout
    from backend.services.duration_curve_best_effort import update_athlete_power_curve

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    with _Session(engine) as session:
        q = session.query(Workout.id).filter(
            Workout.user_id == uid, Workout.workout_type.ilike("run")
        )
        if workout_ids is not None:
            allowed = [wid if isinstance(wid, _uuid.UUID) else _uuid.UUID(str(wid)) for wid in workout_ids]
            q = q.filter(Workout.id.in_(allowed))
        run_ids = [row[0] for row in q.all()]

    for workout_id in run_ids:
        with _Session(engine) as session:
            update_athlete_power_curve(uid, workout_id, session)
