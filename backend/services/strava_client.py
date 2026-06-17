"""Strava API client: paginated activity fetch with rate-limit handling."""
import json
import time
import urllib.error
import urllib.request
from typing import Iterator
from urllib.parse import urlencode

from backend.services.strava import refresh_token_if_needed
from backend.utils.errors import RateLimited
from backend.utils.log import get_logger

_STRAVA_BASE = "https://www.strava.com/api/v3"
_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 2, 4]

logger = get_logger(__name__)

# Module-level alias so tests can patch without touching urllib globally
_urlopen = urllib.request.urlopen


def _check_rate_limit(resp) -> None:
    usage_str = resp.getheader("X-RateLimit-Usage", "") or ""
    limit_str = resp.getheader("X-RateLimit-Limit", "") or ""
    if not usage_str or not limit_str:
        return
    try:
        usage = int(usage_str.split(",")[0])
        limit = int(limit_str.split(",")[0])
        if limit and (usage / limit) > 0.8:
            logger.warning(
                "Strava rate limit usage exceeds 80%",
                extra={"rate_limit_usage": usage, "rate_limit_limit": limit},
            )
    except (ValueError, IndexError, ZeroDivisionError):
        pass


def _fetch(req: urllib.request.Request):
    """Execute request with retry on transient errors. Returns parsed JSON."""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with _urlopen(req) as resp:
                body = resp.read()
                _check_rate_limit(resp)
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = None
                try:
                    raw = e.hdrs.get("Retry-After")
                    if raw:
                        retry_after = int(raw)
                except Exception:
                    pass
                raise RateLimited(
                    user_message="Strava rate limit exceeded",
                    details={"retry_after": retry_after},
                )
            if e.code == 401:
                raise
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAYS[attempt])
            else:
                raise
        except urllib.error.URLError:
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAYS[attempt])
            else:
                raise


def get_athlete_activities(
    user_id: str,
    after_epoch: int | None,
    before_epoch: int | None,
    page_size: int = 30,
) -> Iterator[dict]:
    """Yield raw Strava activity dicts for user_id, paginating until exhausted."""
    token = refresh_token_if_needed(user_id)
    page = 1

    while True:
        params: dict = {"per_page": page_size, "page": page}
        if after_epoch is not None:
            params["after"] = after_epoch
        if before_epoch is not None:
            params["before"] = before_epoch

        url = f"{_STRAVA_BASE}/athlete/activities?{urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

        activities: list = _fetch(req)
        yield from activities

        if len(activities) < page_size:
            break
        page += 1


def get_activity_detail(user_id: str, activity_id: int | str) -> dict:
    """Return raw Strava activity dict (includes splits_metric, laps, segment_efforts)."""
    token = refresh_token_if_needed(user_id)
    req = urllib.request.Request(
        f"{_STRAVA_BASE}/activities/{activity_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return _fetch(req)


# All stream types Strava exposes. key_by_type returns a dict keyed by stream name.
_STREAM_KEYS = (
    "time,latlng,distance,altitude,velocity_smooth,heartrate,"
    "cadence,watts,temp,moving,grade_smooth"
)


def get_activity_streams(
    user_id: str, activity_id: int | str, keys: str = _STREAM_KEYS
) -> dict:
    """Return per-point streams for an activity (GPS latlng, HR, pace, watts, …).

    Response is keyed by stream type (key_by_type=true). Returns {} when the
    activity has no streams (e.g. manually-entered, no recorded track).
    """
    token = refresh_token_if_needed(user_id)
    params = urlencode({"keys": keys, "key_by_type": "true"})
    req = urllib.request.Request(
        f"{_STRAVA_BASE}/activities/{activity_id}/streams?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return _fetch(req)
