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


def refresh_token_if_needed(user_id: str) -> str | None:
    """Return a valid Strava access token for user_id, refreshing via Strava if < 5 min remaining.

    Returns None if no Strava token row exists for the user (OAuth not yet completed).
    """
    with Session(engine) as session:
        token_row = session.query(StravaToken).filter(StravaToken.user_id == user_id).one_or_none()
        if token_row is None:
            return None
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


def detect_stryd_origin(strava_activity_dict: dict) -> bool:
    # Strava API fields: device_name (activity.device_name), external_id (activity.external_id),
    # avg_power_w / max_power_w (activity.average_watts / activity.max_watts), type (activity.type).
    # Heuristic: any single signal is sufficient — Stryd device name, stryd-prefixed external ID,
    # or power-on-run from a pod-class device. Order: cheapest checks first.
    device = (strava_activity_dict.get("device_name") or "").lower()
    ext_id = (strava_activity_dict.get("external_id") or "").lower()

    if "stryd" in device:
        return True

    if ext_id.startswith("stryd:") or "stryd" in ext_id:
        return True

    has_power = bool(
        strava_activity_dict.get("avg_power_w") or strava_activity_dict.get("max_power_w")
    )
    is_run = strava_activity_dict.get("activity_type") == "Run" or strava_activity_dict.get("type") == "Run"
    is_pod_device = "pod" in device

    if has_power and is_run and is_pod_device:
        return True

    return False


def get_strava_power_data(activity_dict: dict) -> dict | None:
    """Extract power fields from a Strava activity dict (raw API payload or raw_payload column).

    # TSS formula priority: power > pace > HR > duration_only
    Returns None if no power data present (average_watts absent or falsy).
    """
    avg_watts = activity_dict.get("average_watts")
    if not avg_watts:
        return None

    max_w = activity_dict.get("max_watts")
    np_w = activity_dict.get("weighted_average_watts")
    kj = activity_dict.get("kilojoules")

    return {
        "avg_power_w": int(avg_watts),
        "max_power_w": int(max_w) if max_w is not None else None,
        "normalized_power_w": int(np_w) if np_w is not None else None,
        "kilojoules": float(kj) if kj is not None else None,
    }
