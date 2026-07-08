"""Garmin source scaffold (Phase 3).

OFF by default (`GARMIN_SYNC_ENABLED`). This is a placeholder so the sync-routing
plumbing — queue `garmin_sync` job type, worker handler, source list, status
endpoint — has a home for when the Garmin Connect integration is actually built.
It pulls NO data yet: `sync_garmin` raises, and every call site guards on
`is_enabled()`, so nothing runs while the flag is off. Mirrors the surface of
`strava.py` / `stryd.py` just enough to slot the real implementation in later.
"""

from __future__ import annotations

import os

GARMIN_SOURCE = "garmin"


def is_enabled() -> bool:
    """Whether the Garmin source is turned on. Default off — this is a scaffold."""
    return os.getenv("GARMIN_SYNC_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


class GarminNotConfigured(Exception):
    """Raised when Garmin sync is requested before the integration exists."""


def sync_garmin(user_id: str, *, full: bool = False, recorder=None) -> dict:
    """Scaffold entry point. Raises until the real integration lands — callers
    must guard on `is_enabled()` first, so this never fires with the flag off."""
    raise GarminNotConfigured(
        "Garmin sync is not implemented yet (GARMIN_SYNC_ENABLED scaffold)."
    )
