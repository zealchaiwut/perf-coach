"""Strava activity sync orchestrator: pulls activities into strava_activities cache."""
import calendar
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import StravaActivity, SyncJob
from backend.services.strava import detect_stryd_origin
from backend.services.strava_client import get_athlete_activities
from backend.utils.log import get_logger

logger = get_logger(__name__)

_FLUSH_EVERY = 10
_DEFAULT_LOOKBACK_DAYS = 90


def _to_epoch(d: date) -> int:
    return int(calendar.timegm(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timetuple()))


def _parse_start_time(raw: dict) -> datetime:
    sd = raw.get("start_date") or raw.get("start_date_local") or ""
    if sd:
        try:
            return datetime.fromisoformat(sd.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


def _map_fields(raw: dict, user_id: str, is_stryd: bool) -> dict:
    dist = raw.get("distance")
    return {
        "user_id": user_id,
        "strava_activity_id": raw["id"],
        "start_time": _parse_start_time(raw),
        "activity_type": raw.get("sport_type") or raw.get("type") or "Unknown",
        "name": raw.get("name") or "",
        "distance_km": round(dist / 1000, 3) if dist else None,
        "duration_seconds": raw.get("moving_time"),
        "avg_hr": raw.get("average_heartrate"),
        "max_hr": raw.get("max_heartrate"),
        "elevation_m": raw.get("total_elevation_gain"),
        "avg_power_w": raw.get("average_watts"),
        "max_power_w": raw.get("max_watts"),
        "device_name": raw.get("device_name"),
        "external_id": raw.get("external_id"),
        "is_stryd_synced": is_stryd,
        "raw_payload": raw,
        "synced_at": datetime.now(tz=timezone.utc),
    }


def _job_summary(job: SyncJob) -> dict:
    return {
        "id": str(job.id),
        "user_id": str(job.user_id),
        "source": job.source,
        "job_type": job.job_type,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "activities_created": job.activities_created,
        "activities_updated": job.activities_updated,
        "activities_fetched": job.activities_fetched,
        "activities_skipped": job.activities_skipped,
        "error_message": job.error_message,
        "since_date": job.since_date.isoformat() if job.since_date else None,
    }


def sync_strava_activities(
    user_id: str,
    since_date: date | None = None,
    job_id: str | None = None,
) -> dict:
    """Pull Strava activities into the strava_activities cache.

    Idempotent: re-running produces the same end state (upsert by strava_activity_id).
    Does NOT create workouts rows.

    Returns a summary dict matching the SyncJob shape.
    """
    now_utc = datetime.now(tz=timezone.utc)
    explicit_since = since_date is not None

    # Resolve since_date and job_type
    if not explicit_since:
        with Session(engine) as session:
            latest_synced = session.execute(
                select(StravaActivity.synced_at)
                .where(StravaActivity.user_id == user_id)
                .order_by(StravaActivity.synced_at.desc())
                .limit(1)
            ).scalar()

        if latest_synced is not None:
            since_date = latest_synced.date()
            job_type = "incremental"
        else:
            since_date = (datetime.now(tz=timezone.utc) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)).date()
            job_type = "full"
    else:
        job_type = "manual"

    # Setup SyncJob
    with Session(engine) as session:
        if job_id is not None:
            job = session.get(SyncJob, job_id)
            if job is None:
                raise ValueError(f"SyncJob {job_id} not found")
            job.status = "running"
            job.started_at = now_utc
        else:
            job = SyncJob(
                user_id=user_id,
                source="strava",
                job_type=job_type,
                status="running",
                started_at=now_utc,
                since_date=since_date,
            )
            session.add(job)
        session.commit()
        session.refresh(job)
        job_db_id = job.id

    after_epoch = _to_epoch(since_date)
    activities_created = 0
    activities_updated = 0
    loop_count = 0

    try:
        for raw in get_athlete_activities(user_id, after_epoch=after_epoch, before_epoch=None):
            is_stryd = detect_stryd_origin(raw)
            fields = _map_fields(raw, user_id, is_stryd)

            with Session(engine) as session:
                existing = session.execute(
                    select(StravaActivity).where(
                        StravaActivity.strava_activity_id == raw["id"]
                    )
                ).scalar_one_or_none()

                if existing is not None:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                    activities_updated += 1
                else:
                    session.add(StravaActivity(**fields))
                    activities_created += 1

                session.commit()

            loop_count += 1

            if loop_count % _FLUSH_EVERY == 0:
                with Session(engine) as session:
                    job_row = session.get(SyncJob, job_db_id)
                    job_row.activities_created = activities_created
                    job_row.activities_updated = activities_updated
                    session.commit()

        # Mark complete
        with Session(engine) as session:
            job_row = session.get(SyncJob, job_db_id)
            job_row.status = "completed"
            job_row.completed_at = datetime.now(tz=timezone.utc)
            job_row.activities_created = activities_created
            job_row.activities_updated = activities_updated
            session.commit()
            session.refresh(job_row)
            return _job_summary(job_row)

    except Exception as exc:
        with Session(engine) as session:
            job_row = session.get(SyncJob, job_db_id)
            if job_row is not None:
                job_row.status = "failed"
                job_row.error_message = str(exc)
                job_row.completed_at = datetime.now(tz=timezone.utc)
                job_row.activities_created = activities_created
                job_row.activities_updated = activities_updated
                session.commit()
        raise
