"""Strava/Stryd sync worker logic, extracted from backend/main.py.

This module MUST NOT import backend.main — main.py starts daemon threads at
import time, and a standalone worker process needs to run syncs without
triggering that. Only import from backend.db, backend.models,
backend.services.*, and stdlib/sqlalchemy.
"""

import calendar as _calendar
import json as _json
import logging as _logging
import urllib.error as _urllib_error
import urllib.request as _urllib_request
import uuid as _uuid
from datetime import date as _date_cls, datetime as _datetime, timezone as _timezone
from typing import Optional, Protocol
from urllib.parse import urlencode as _urlencode

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import StravaActivity
from backend.services import reconcile as _reconcile
from backend.services.strava import refresh_token_if_needed
from backend.services.workout_merge import clean_hr


class SyncRecorder(Protocol):
    def set_phase(self, uid, phase: str) -> None: ...
    def increment(self, uid, current: int = 0, items_synced: int = 0) -> None: ...
    def mark_success(self, uid) -> None: ...
    def mark_error(self, uid, message: str) -> None: ...


_STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
_STRAVA_SYNC_PER_PAGE = 100
_STRAVA_DEFAULT_LOOKBACK_DAYS = 90
_DAILY_RECONCILE_LIMIT = 10  # max activities reconciled per incremental (daily) sync


def default_strava_since_date(user_id: _uuid.UUID) -> str:
    """Return YYYY-MM-DD lower bound for incremental Strava pulls."""
    from datetime import timedelta as _timedelta

    try:
        with Session(engine) as session:
            latest_synced = session.execute(
                select(func.max(StravaActivity.synced_at))
                .where(StravaActivity.user_id == user_id)
            ).scalar()
        if latest_synced is not None and hasattr(latest_synced, "date"):
            return (latest_synced.date() - _timedelta(days=1)).isoformat()
    except (AttributeError, TypeError, ValueError):
        pass
    return (_date_cls.today() - _timedelta(days=_STRAVA_DEFAULT_LOOKBACK_DAYS)).isoformat()


def run_plan_matcher(uid) -> None:
    """Post-sync pass: match planned_sessions against the freshly reconciled
    workouts. Runs after reconcile_workouts, before mark_success. Failures never
    fail the sync — the on-demand /api/planned-sessions/reconcile is the backstop.
    """
    try:
        from backend.services import plan_matching as _pm
        with Session(engine) as _s:
            _pm.reconcile_user(_s, uid)
    except Exception as _pm_exc:  # noqa: BLE001
        _logging.getLogger(__name__).warning(
            "plan matcher failed for user %s: %s", uid, _pm_exc, exc_info=True
        )


def run_strava_sync(
    user_id: str,
    since_date: Optional[str] = None,
    *,
    full: bool = False,
    recorder: SyncRecorder,
) -> None:
    """Pull Strava activities (optionally since since_date) and upsert."""
    uid = _uuid.UUID(user_id)
    since_epoch: Optional[int] = None
    if full:
        since_epoch = None
    else:
        if since_date is None:
            since_date = default_strava_since_date(uid)
        if since_date:
            try:
                d = _date_cls.fromisoformat(since_date)
                since_epoch = int(_calendar.timegm(_datetime(d.year, d.month, d.day, tzinfo=_timezone.utc).timetuple()))
            except ValueError:
                pass
    try:
        recorder.set_phase(uid, "pulling_strava")

        access_token = refresh_token_if_needed(user_id)
        if access_token is None:
            recorder.mark_error(uid, "Strava account not connected")
            return

        page = 1
        synced_strava_ids: list[int] = []
        while True:
            params: dict = {"per_page": _STRAVA_SYNC_PER_PAGE, "page": page}
            if since_epoch is not None:
                params["after"] = since_epoch
            url = _STRAVA_ACTIVITIES_URL + "?" + _urlencode(params)
            req = _urllib_request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
            try:
                with _urllib_request.urlopen(req) as resp:
                    batch = _json.loads(resp.read())
            except _urllib_error.HTTPError as exc:
                recorder.mark_error(uid, f"Strava API error: {exc.code}")
                return

            if not batch:
                break

            now = _datetime.now(tz=_timezone.utc)
            rows = []
            for act in batch:
                start_dt = _datetime.strptime(act["start_date"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=_timezone.utc
                )
                synced_strava_ids.append(int(act["id"]))
                rows.append({
                    "user_id": user_id,
                    "strava_activity_id": int(act["id"]),
                    "start_time": start_dt,
                    "activity_type": act.get("type") or act.get("sport_type") or "Unknown",
                    "name": act.get("name") or "Untitled",
                    "distance_km": round(float(act["distance"]) / 1000, 3) if act.get("distance") else None,
                    "duration_seconds": int(act["moving_time"]) if act.get("moving_time") else None,
                    "avg_hr": clean_hr(act.get("average_heartrate")),
                    "max_hr": clean_hr(act.get("max_heartrate")),
                    "elevation_m": int(act["total_elevation_gain"]) if act.get("total_elevation_gain") else None,
                    "avg_power_w": int(act["average_watts"]) if act.get("average_watts") else None,
                    "max_power_w": int(act["max_watts"]) if act.get("max_watts") else None,
                    "device_name": act.get("device_name"),
                    "external_id": act.get("external_id"),
                    "is_stryd_synced": False,
                    "raw_payload": act,
                    "synced_at": now,
                })

            with Session(engine) as session:
                ins = _pg_insert(StravaActivity).values(rows)
                stmt = ins.on_conflict_do_update(
                    index_elements=["strava_activity_id"],
                    set_={
                        "name": ins.excluded.name,
                        "activity_type": ins.excluded.activity_type,
                        "distance_km": ins.excluded.distance_km,
                        "duration_seconds": ins.excluded.duration_seconds,
                        "avg_hr": ins.excluded.avg_hr,
                        "max_hr": ins.excluded.max_hr,
                        "elevation_m": ins.excluded.elevation_m,
                        "avg_power_w": ins.excluded.avg_power_w,
                        "max_power_w": ins.excluded.max_power_w,
                        "raw_payload": ins.excluded.raw_payload,
                        "synced_at": now,
                    },
                )
                session.execute(stmt)
                session.commit()

            recorder.increment(uid, current=len(rows), items_synced=len(rows))

            if len(batch) < _STRAVA_SYNC_PER_PAGE:
                break
            page += 1

        if full:
            _reconcile.reconcile_workouts(uid, uid)
        else:
            _reconcile.reconcile_workouts(
                uid,
                uid,
                strava_activity_ids=synced_strava_ids[-_DAILY_RECONCILE_LIMIT:],
            )
        run_plan_matcher(uid)
        recorder.mark_success(uid)
    except Exception as exc:  # noqa: BLE001
        recorder.mark_error(uid, str(exc))


def run_stryd_sync(
    user_id: str,
    since_date: Optional[str] = None,
    *,
    full: bool = False,
    recorder: SyncRecorder,
) -> None:
    """Pull Stryd activities, upsert, then reconcile."""
    from backend.services import stryd_sync as _stryd_sync
    uid = _uuid.UUID(user_id)
    since = None
    if since_date and not full:
        try:
            since = _date_cls.fromisoformat(since_date)
        except ValueError:
            pass
    try:
        recorder.set_phase(uid, "pulling_stryd")
        result = _stryd_sync.sync_stryd_activities(str(uid), since_date=since, full=full, heal=full)
        recorder.increment(uid, current=result["upserted"], items_synced=result["upserted"])
        if result["upserted"] == 0 and not full:
            recorder.mark_success(uid)
            return
        recorder.set_phase(uid, "reconciling")
        if full:
            _reconcile.reconcile_workouts(uid, uid)
        else:
            all_ids = result.get("stryd_activity_ids") or []
            _reconcile.reconcile_workouts(
                uid,
                uid,
                stryd_activity_ids=all_ids[-_DAILY_RECONCILE_LIMIT:],
            )
        run_plan_matcher(uid)
        recorder.mark_success(uid)
    except Exception as exc:  # noqa: BLE001
        recorder.mark_error(uid, str(exc))
