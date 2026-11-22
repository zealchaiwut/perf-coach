"""Per-provider sync status for revamp training toolbar (P1-2)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import StravaToken, StrydCredentials, SyncJob


# Rows left in pending/running after a crash (UAT has June 2026 Stryd
# zombies) must not paint the toolbar as "Syncing…" forever. Incremental
# pulls finish in seconds; 15 minutes is well past a live job.
RUNNING_MAX_AGE = timedelta(minutes=15)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def job_is_live(started_at: Optional[datetime], created_at: Optional[datetime], *, now: Optional[datetime] = None) -> bool:
    """True when a pending/running SyncJob is young enough to still be executing."""
    now = now or _utc_now()
    ts = _as_utc(started_at) or _as_utc(created_at)
    if ts is None:
        return False
    return (now - ts) < RUNNING_MAX_AGE


def _provider_running(session: Session, user_id: uuid.UUID, source: str) -> bool:
    row = session.execute(
        select(SyncJob)
        .where(SyncJob.user_id == user_id)
        .where(SyncJob.source == source)
        .where(SyncJob.status.in_(("pending", "running")))
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return False
    return job_is_live(row.started_at, row.created_at)


def _last_completed(session: Session, user_id: uuid.UUID, source: str) -> Optional[SyncJob]:
    return session.execute(
        select(SyncJob)
        .where(SyncJob.user_id == user_id)
        .where(SyncJob.source == source)
        .where(SyncJob.status == "completed")
        .order_by(SyncJob.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _last_failed(session: Session, user_id: uuid.UUID, source: str) -> Optional[SyncJob]:
    return session.execute(
        select(SyncJob)
        .where(SyncJob.user_id == user_id)
        .where(SyncJob.source == source)
        .where(SyncJob.status == "failed")
        .order_by(SyncJob.completed_at.desc(), SyncJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _pending_count(session: Session, user_id: uuid.UUID, source: str) -> int:
    return int(
        session.execute(
            select(func.count(SyncJob.id))
            .where(SyncJob.user_id == user_id)
            .where(SyncJob.source == source)
            .where(SyncJob.status == "pending")
        ).scalar()
        or 0
    )


_REAUTH_HINTS = (
    "unauthorized",
    "401",
    "credentials",
    "login failed",
    "reauth",
    "password",
    "reconnect",
)
_TEMP_UNAVAILABLE = "temporarily unavailable"


def _snapshot_running(job_snapshot: Optional[dict], source: str) -> bool:
    """True when the in-memory / worker snapshot is actively pulling this source."""
    if not job_snapshot:
        return False
    st = (job_snapshot.get("status") or "").lower()
    if st not in ("running", "pending"):
        return False
    phase = (job_snapshot.get("phase") or "").lower()
    if phase == "pulling_strava":
        return source == "strava"
    if phase == "pulling_stryd":
        return source == "stryd"
    provider = (job_snapshot.get("provider") or "").lower()
    if provider in ("strava", "stryd") and not phase:
        return source == provider
    return True


def _needs_reauth(source: str, last_error: Optional[str]) -> bool:
    if source != "stryd" or not last_error:
        return False
    blob = last_error.lower()
    return any(hint in blob for hint in _REAUTH_HINTS)


def _one_provider(
    session: Session,
    user_id: uuid.UUID,
    source: str,
    *,
    connected: bool,
    job_snapshot: Optional[dict] = None,
) -> dict[str, Any]:
    running = _snapshot_running(job_snapshot, source) or _provider_running(session, user_id, source)
    last_ok = _last_completed(session, user_id, source)
    last_fail = _last_failed(session, user_id, source)
    last_error = None
    if last_fail is not None and (last_ok is None or (_as_utc(last_fail.completed_at) or last_fail.created_at)
                                >= (_as_utc(last_ok.completed_at) if last_ok else datetime.min.replace(tzinfo=timezone.utc))):
        last_error = last_fail.error_message or "Sync failed"

    last_success_at = None
    if last_ok is not None and last_ok.completed_at is not None:
        last_success_at = _as_utc(last_ok.completed_at).isoformat()

    return {
        "connected": connected,
        "last_success_at": last_success_at,
        "pending_count": _pending_count(session, user_id, source),
        "last_error": last_error,
        "running": running,
        "needs_reauth": _needs_reauth(source, last_error),
    }


def build_providers(
    session: Session,
    user_id: uuid.UUID,
    *,
    job_snapshot: Optional[dict] = None,
) -> dict[str, Any]:
    """Strava + Stryd provider rows for ``GET /api/sync/status``."""
    uid = uuid.UUID(str(user_id))
    strava_connected = (
        session.query(StravaToken).filter(StravaToken.user_id == uid).first() is not None
    )
    stryd_cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == uid).first()
    stryd_connected = stryd_cred is not None
    stryd_needs_reauth = stryd_cred is not None and getattr(stryd_cred, "auth_failed_at", None) is not None
    strava = _one_provider(
        session,
        uid,
        "strava",
        connected=strava_connected,
        job_snapshot=job_snapshot,
    )
    stryd = _one_provider(
        session,
        uid,
        "stryd",
        connected=stryd_connected,
        job_snapshot=job_snapshot,
    )
    if stryd_needs_reauth:
        stryd["needs_reauth"] = True
    return {"strava": strava, "stryd": stryd}


def dot_state(provider: dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """green | amber | red for UI tests."""
    now = now or _utc_now()
    if not provider.get("connected"):
        return "red"
    if provider.get("needs_reauth"):
        return "amber"
    err = provider.get("last_error") or ""
    if err:
        if _TEMP_UNAVAILABLE in str(err).lower():
            return "amber"
        return "red"
    ts = provider.get("last_success_at")
    if not ts:
        return "amber"
    try:
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return "amber"
    age = now - last
    if age >= timedelta(hours=48):
        return "amber"
    return "green"


def provider_ui_state(provider: dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """syncing | failed | stale | ok — same rules as frontend/js/v2-sync-status.js."""
    if provider.get("running"):
        return "syncing"
    if provider.get("needs_reauth"):
        return "failed"
    err = str(provider.get("last_error") or "")
    if err and _TEMP_UNAVAILABLE not in err.lower():
        return "failed"
    if not provider.get("connected"):
        return "failed"
    colour = dot_state(provider, now=now)
    if colour == "red":
        return "failed"
    if colour == "amber":
        return "stale"
    return "ok"