import json as _json
import os
import urllib.request as _urllib_request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode as _urlencode

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import StravaToken

_STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
_REFRESH_BUFFER_SECONDS = 300  # 5 minutes


def _call_strava_refresh(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """POST refresh_token grant to Strava and return parsed response."""
    data = _urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    req = _urllib_request.Request(_STRAVA_TOKEN_URL, data=data, method="POST")
    with _urllib_request.urlopen(req) as resp:
        return _json.loads(resp.read())


def refresh_token_if_needed(user_id: str) -> str:
    """Return a valid Strava access token for user_id, refreshing via Strava if < 5 min remaining."""
    with Session(engine) as session:
        token_row = session.query(StravaToken).filter(StravaToken.user_id == user_id).one()
        now = datetime.now(tz=timezone.utc)

        if token_row.expires_at > now + timedelta(seconds=_REFRESH_BUFFER_SECONDS):
            return token_row.access_token

        resp = _call_strava_refresh(
            os.getenv("STRAVA_CLIENT_ID"),
            os.getenv("STRAVA_CLIENT_SECRET"),
            token_row.refresh_token,
        )

        token_row.access_token = resp["access_token"]
        token_row.refresh_token = resp["refresh_token"]
        token_row.expires_at = datetime.fromtimestamp(resp["expires_at"], tz=timezone.utc)
        token_row.updated_at = now
        session.commit()

        return token_row.access_token
