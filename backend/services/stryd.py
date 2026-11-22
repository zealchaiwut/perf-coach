import base64
import json as _json
import threading
import urllib.error as _urllib_error
import urllib.request as _urllib_request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import StrydCredentials
from backend.services.crypto import decrypt_value

_STRYD_SIGNIN_URL = "https://www.stryd.com/b/email/signin"
STRYD_SIGNIN_TIMEOUT_SEC = 20
STRYD_SESSION_LIFETIME_DAYS = 25
_REFRESH_BUFFER_DAYS = 1

_meta_lock = threading.Lock()
_user_refresh_locks: dict[str, threading.Lock] = {}


class StrydError(Exception):
    """Base for Stryd integration failures."""

    def __init__(self, detail: str = "") -> None:
        self.detail = detail or "Stryd error"
        super().__init__(self.detail)


class StrydAuthError(StrydError):
    """Sign-in rejected (bad credentials or rejected session token)."""


class StrydUnavailable(StrydError):
    """Stryd or the network is temporarily unreachable."""


def _user_lock(user_id: str) -> threading.Lock:
    with _meta_lock:
        lock = _user_refresh_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _user_refresh_locks[user_id] = lock
        return lock


def _expiry_from_signin(resp: dict[str, Any], token: str, now: datetime) -> datetime:
    for key in ("expires_at", "session_token_expires_at", "expires"):
        raw = resp.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(raw, str):
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    exp = resp.get("exp")
    if isinstance(exp, (int, float)):
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    if token and token.count(".") == 2:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            data = _json.loads(base64.urlsafe_b64decode(payload))
            if "exp" in data:
                return datetime.fromtimestamp(int(data["exp"]), tz=timezone.utc)
        except Exception:
            pass
    return now + timedelta(days=STRYD_SESSION_LIFETIME_DAYS)


def _call_stryd_signin(email: str, password: str) -> dict:
    """POST credentials to Stryd signin API and return parsed response."""
    data = _json.dumps({"email": email, "password": password}).encode()
    req = _urllib_request.Request(
        _STRYD_SIGNIN_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urllib_request.urlopen(req, timeout=STRYD_SIGNIN_TIMEOUT_SEC) as resp:
            return _json.loads(resp.read())
    except _urllib_error.HTTPError as exc:
        if exc.code in (401, 403):
            raise StrydAuthError("Stryd authentication failed — check email and password.")
        if exc.code == 404:
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            raise StrydAuthError(
                body or "Stryd authentication failed — check email and password.",
            )
        if exc.code >= 500:
            raise StrydUnavailable("Stryd is unavailable, try again later.")
        raise StrydUnavailable(f"Stryd sign-in failed (HTTP {exc.code}).")
    except _urllib_error.URLError:
        raise StrydUnavailable("Stryd is unavailable, try again later.")


def mark_stryd_auth_failed(user_id: str) -> None:
    now = datetime.now(tz=timezone.utc)
    with Session(engine) as session:
        cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == user_id).first()
        if cred is not None:
            cred.auth_failed_at = now
            cred.updated_at = now
            session.commit()


def refresh_stryd_session_if_needed(user_id: str, *, force: bool = False) -> str:
    """Return a valid Stryd session token, re-authenticating when needed."""
    with _user_lock(user_id):
        with Session(engine) as session:
            token_out: Optional[str] = None
            with session.begin():
                cred = (
                    session.query(StrydCredentials)
                    .filter(StrydCredentials.user_id == user_id)
                    .with_for_update()
                    .one()
                )
                now = datetime.now(tz=timezone.utc)

                if (
                    not force
                    and cred.session_token is not None
                    and cred.session_token_expires_at is not None
                    and cred.session_token_expires_at > now + timedelta(days=_REFRESH_BUFFER_DAYS)
                ):
                    token_out = cred.session_token
                else:
                    password = decrypt_value(cred.stryd_password_encrypted)
                    resp = _call_stryd_signin(cred.stryd_email, password)
                    token = str(resp.get("token") or resp.get("session_token") or "")
                    cred.session_token = token
                    cred.session_token_expires_at = _expiry_from_signin(resp, token, now)
                    if resp.get("id"):
                        cred.athlete_id = resp["id"]
                    cred.auth_failed_at = None
                    cred.updated_at = now
                    token_out = token
            if token_out is None:
                raise StrydAuthError("Stryd credentials missing")
            return token_out