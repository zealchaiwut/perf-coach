"""Fast-poll window config, shared by the worker's idle poll backoff and the
webapp's /api/coach/export/queue-window status endpoint.

Neon's compute autosuspend is blocked by any periodic query, so having the
worker poll job_queue at a fast cadence 24/7 keeps the database "awake" (and
billed) around the clock. QUEUE_POLL_FAST_WINDOWS restricts the fast cadence
to one or more small daily windows — e.g. "10:00-12:00,21:00-23:00", Bangkok
local time — set on BOTH the webapp and the worker so they agree on when a
check-in should expect a fast (~10s) response vs. the slow idle-poll fallback.

Outside the configured window(s) the worker keeps using
QUEUE_POLL_IDLE_INTERVAL_SECONDS unchanged, and this module reports
in_window=False so the UI can warn the athlete before they wait.
"""
from __future__ import annotations

import os
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")


def _parse_hhmm(raw: str) -> dtime:
    hh, mm = raw.strip().split(":")
    return dtime(int(hh), int(mm))


def parse_fast_windows(raw: str | None) -> list[tuple[dtime, dtime]]:
    """Parse "10:00-12:00,21:00-23:00" into [(start, end), ...].

    A malformed entry is skipped rather than raising — a typo in this env var
    must never crash the worker or the webapp; it should just behave as if
    that window weren't configured."""
    windows: list[tuple[dtime, dtime]] = []
    if not raw:
        return windows
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or "-" not in chunk:
            continue
        start_s, end_s = chunk.split("-", 1)
        try:
            start, end = _parse_hhmm(start_s), _parse_hhmm(end_s)
        except (ValueError, IndexError):
            continue
        if start < end:
            windows.append((start, end))
    return windows


def get_fast_windows() -> list[tuple[dtime, dtime]]:
    return parse_fast_windows(os.getenv("QUEUE_POLL_FAST_WINDOWS", ""))


def is_in_fast_window(
    now: datetime | None = None,
    windows: list[tuple[dtime, dtime]] | None = None,
) -> bool:
    """True if `now` (converted to Bangkok local) falls inside any configured
    window. Windows are same-day (start < end, enforced by parse_fast_windows) —
    a window spanning midnight isn't supported, keep windows within one day."""
    if windows is None:
        windows = get_fast_windows()
    if not windows:
        return False
    now = datetime.now(BANGKOK_TZ) if now is None else now.astimezone(BANGKOK_TZ)
    t = now.time()
    return any(start <= t < end for start, end in windows)


def window_status() -> dict:
    """JSON-serializable status for the webapp's queue-window endpoint."""
    windows = get_fast_windows()
    return {
        "tz": "Asia/Bangkok",
        "fast_windows": [
            f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s, e in windows
        ],
        "in_window": is_in_fast_window(windows=windows),
    }
