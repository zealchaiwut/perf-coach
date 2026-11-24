"""Long-lived device sessions for the phone PWA (PWA P0-5)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Response
from sqlalchemy.orm import Session

from backend.auth import CSRF_COOKIE_NAME, generate_csrf_token, set_csrf_cookie
from backend.models import DeviceSession, User

DEVICE_COOKIE_NAME = "device_session"
DEVICE_TTL = timedelta(days=90)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_device_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def issue_device_session(
    session: Session,
    user_id,
    *,
    label: Optional[str] = None,
) -> tuple[DeviceSession, str, str]:
    """Create a device session. Returns (row, raw_token, csrf_token)."""
    raw = secrets.token_urlsafe(32)
    csrf = generate_csrf_token()
    row = DeviceSession(
        user_id=user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id)),
        token_hash=hash_device_token(raw),
        label=(label or "Phone")[:100],
        csrf_current=csrf,
        csrf_previous=None,
        last_seen_at=_utc_now(),
    )
    session.add(row)
    session.flush()
    return row, raw, csrf


def set_device_cookie(response: Response, raw_token: str) -> None:
    from backend.auth import _cookie_secure

    response.set_cookie(
        key=DEVICE_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
        max_age=int(DEVICE_TTL.total_seconds()),
    )


def clear_device_cookie(response: Response) -> None:
    response.delete_cookie(key=DEVICE_COOKIE_NAME, path="/")


def lookup_device(session: Session, raw_token: str, *, now: Optional[datetime] = None) -> Optional[DeviceSession]:
    now = now or _utc_now()
    row = (
        session.query(DeviceSession)
        .filter(DeviceSession.token_hash == hash_device_token(raw_token))
        .first()
    )
    if row is None or row.revoked_at is not None:
        return None
    last = row.last_seen_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is not None and now - last > DEVICE_TTL:
        return None
    return row


def touch_device(row: DeviceSession, *, now: Optional[datetime] = None) -> None:
    row.last_seen_at = now or _utc_now()


def rotate_csrf(row: DeviceSession) -> str:
    row.csrf_previous = row.csrf_current
    row.csrf_current = generate_csrf_token()
    return row.csrf_current


def attach_rotated_csrf(response: Response, row: DeviceSession) -> str:
    token = rotate_csrf(row)
    set_csrf_cookie(response, token)
    return token


def csrf_header_ok(row: DeviceSession, header: Optional[str], cookie: Optional[str]) -> bool:
    if not header:
        return False
    candidates = [c for c in (cookie, row.csrf_current, row.csrf_previous) if c]
    return any(hmac.compare_digest(header, c) for c in candidates)


def list_devices(session: Session, user_id) -> list[dict]:
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    rows = (
        session.query(DeviceSession)
        .filter(DeviceSession.user_id == uid, DeviceSession.revoked_at.is_(None))
        .order_by(DeviceSession.last_seen_at.desc())
        .all()
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": str(r.id),
                "label": r.label,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            }
        )
    return out


def revoke_device(session: Session, user_id, device_id) -> bool:
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    did = device_id if isinstance(device_id, uuid.UUID) else uuid.UUID(str(device_id))
    row = session.get(DeviceSession, did)
    if row is None or row.user_id != uid:
        return False
    row.revoked_at = _utc_now()
    session.flush()
    return True


def user_for_device(session: Session, row: DeviceSession) -> Optional[User]:
    return session.get(User, row.user_id)
