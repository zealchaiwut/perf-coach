"""Per-provider sync status for revamp training toolbar (P1-2)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import StravaToken, StrydCredentials, SyncJob


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _provider_running(session: Session, user_id: uuid.UUID, source: str) -> bool:
    row = session.execute(
        select(SyncJob)
        .where(SyncJob.user_id == user_id)
        .where(SyncJob.source == source)
        .where(SyncJob.status.in_(("pending", "running")))
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row is not None


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


def _one_provider(
    session: Session,
    user_id: uuid.UUID,
    source: str,
    *,
    connected: bool,
    global_running: bool,
) -> dict[str, Any]:
    running = global_running or _provider_running(session, user_id, source)
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
    stryd_needs_reauth = stryd_cred is not None and stryd_cred.auth_failed_at is not None
    global_running = False
    if job_snapshot is not None:
        st = (job_snapshot.get("status") or "").lower()
        global_running = st in ("running", "pending")
    return {
        "strava": _one_provider(
            session,
            uid,
            "strava",
            connected=strava_connected,
            global_running=global_running,
        ),
        "stryd": {
            **_one_provider(
                session,
                uid,
                "stryd",
                connected=stryd_connected,
                global_running=global_running,
            ),
            "needs_reauth": stryd_needs_reauth,
        },
    }


def dot_state(provider: dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """green | amber | red for UI tests."""
    now = now or _utc_now()
    if not provider.get("connected"):
        return "red"
    if provider.get("needs_reauth"):
        return "amber"
    if provider.get("last_error"):
        err = (provider.get("last_error") or "").lower()
        if "temporarily unavailable" in err:
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