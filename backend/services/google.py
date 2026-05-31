import os
from datetime import datetime, timedelta, timezone

import requests as _requests
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import GoogleOAuthCredentials
from backend.utils.errors import ExternalServiceError

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REFRESH_BUFFER_SECONDS = 300  # 5 minutes


def refresh_token_if_needed(user_id: str) -> str:
    """Return a valid Google access token for user_id, refreshing via Google if < 5 min remaining.

    Raises ExternalServiceError if no credentials row exists, refresh_token is NULL, or refresh fails.
    """
    with Session(engine) as session:
        cred = (
            session.query(GoogleOAuthCredentials)
            .filter(GoogleOAuthCredentials.user_id == user_id)
            .one_or_none()
        )
        if cred is None:
            raise ExternalServiceError(
                user_message="No Google credentials found for this user",
                details={"user_id": user_id},
            )

        now = datetime.now(tz=timezone.utc)

        if cred.expires_at > now + timedelta(seconds=_REFRESH_BUFFER_SECONDS):
            return cred.access_token

        if cred.refresh_token is None:
            raise ExternalServiceError(
                user_message="Google refresh token is missing — user must re-authorize",
                details={"user_id": user_id},
            )

        resp = _requests.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "refresh_token": cred.refresh_token,
                "grant_type": "refresh_token",
            },
        )

        if not resp.ok:
            raise ExternalServiceError(
                user_message="Google token refresh failed",
                details={"status": resp.status_code},
            )

        token_resp = resp.json()

        cred.access_token = token_resp["access_token"]
        cred.expires_at = now + timedelta(seconds=token_resp.get("expires_in", 3600))
        if token_resp.get("refresh_token"):
            cred.refresh_token = token_resp["refresh_token"]
        cred.updated_at = now
        session.commit()

        return cred.access_token
