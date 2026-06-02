import json as _json
import urllib.error as _urllib_error
import urllib.request as _urllib_request
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import StrydCredentials
from backend.services.crypto import decrypt_value

_STRYD_SIGNIN_URL = "https://www.stryd.com/b/email/signin"
_STRYD_RUNS_URL = "https://www.stryd.com/b/runs"
_SESSION_LIFETIME_DAYS = 25
_REFRESH_BUFFER_DAYS = 1


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
        with _urllib_request.urlopen(req) as resp:
            return _json.loads(resp.read())
    except _urllib_error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HTTPException(
                status_code=401,
                detail="Stryd authentication failed — check email and password.",
            )
        if exc.code >= 500:
            raise HTTPException(
                status_code=502,
                detail="Stryd is unavailable, try again later.",
            )
        raise


def refresh_stryd_session_if_needed(user_id: str) -> str:
    """Return a valid Stryd session token, re-authenticating when null or expiring within 1 day."""
    with Session(engine) as session:
        cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == user_id).one()
        now = datetime.now(tz=timezone.utc)

        if (
            cred.session_token is not None
            and cred.session_token_expires_at is not None
            and cred.session_token_expires_at > now + timedelta(days=_REFRESH_BUFFER_DAYS)
        ):
            return cred.session_token

        password = decrypt_value(cred.stryd_password_encrypted)
        resp = _call_stryd_signin(cred.stryd_email, password)

        cred.session_token = resp["token"]
        cred.session_token_expires_at = now + timedelta(days=_SESSION_LIFETIME_DAYS)
        if resp.get("id"):
            cred.athlete_id = resp["id"]
        cred.updated_at = now
        session.commit()

        return cred.session_token


def fetch_stryd_activities(user_id: str) -> list[dict]:
    """Fetch all Stryd run activities for user, returning raw API payloads.

    Reuses refresh_stryd_session_if_needed for session handling.
    Raises HTTPException on auth or API failure.
    """
    session_token = refresh_stryd_session_if_needed(user_id)
    req = _urllib_request.Request(
        _STRYD_RUNS_URL,
        headers={"Authorization": f"Bearer {session_token}"},
    )
    try:
        with _urllib_request.urlopen(req) as resp:
            data = _json.loads(resp.read())
    except _urllib_error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HTTPException(
                status_code=401,
                detail="Stryd session rejected — re-connect your Stryd account.",
            )
        raise HTTPException(status_code=502, detail=f"Stryd API error: {exc.code}")

    if isinstance(data, list):
        return data
    return data.get("runs") or []
