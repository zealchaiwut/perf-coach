"""Worker-driven precompute: warm durable caches so the web request never pays a
heavy recompute (Phase 2 of the smart-worker migration).

Today this warms the **training-load snapshot** — the 180-day EWMA in
`training_load.daily_update()` is the single heaviest recompute on the web hot
path, run inline both when a workout is written and (as a fallback) when
`current_load()` reads a missing/stale snapshot. Moving it to the worker keeps
workout writes fast and makes the post-sync dashboard read a pure cache hit.

Performance scores and the weekly/monthly summaries are already cached inline in
`summary_cache` (invalidated by a workout-set signature), and the form/weight
projections are cheap once the load snapshot is warm, so they are intentionally
left on their existing inline-on-miss caches.

Kept **worker-importable**: this module imports only `training_load` + `db`,
never `backend.main` (which starts daemon threads at import time).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from backend.services import training_load
from backend.utils.log import get_logger

_log = get_logger(__name__)


def _coerce_date(value: Any) -> Optional[date]:
    """Accept a date, a datetime, or an ISO 'YYYY-MM-DD' string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def precompute_user(
    user_id: str,
    *,
    dates: Optional[Iterable[Any]] = None,
    as_of: Optional[date] = None,
) -> dict:
    """Warm the training-load snapshot for `user_id`.

    Always warms today and yesterday (what `current_load()` reads on the hot
    path). Any extra `dates` (e.g. the date of an edited/deleted workout) are
    warmed too, so a historical edit's own snapshot is refreshed as well.

    Idempotent — `daily_update` upserts on `(user_id, snapshot_date)`. Users with
    a custom EWMA calibration bypass the snapshot cache by design (see
    `daily_update`), so this is a cheap no-write recompute for them.
    """
    end = as_of or date.today()
    targets = {end, end - timedelta(days=1)}
    for d in dates or []:
        cd = _coerce_date(d)
        if cd is not None:
            targets.add(cd)

    warmed: dict[str, dict] = {}
    for d in sorted(targets):
        r = training_load.daily_update(user_id, target_date=d)
        warmed[d.isoformat()] = {"ctl": r["ctl"], "atl": r["atl"], "tsb": r["tsb"]}

    _log.info("precompute warmed load snapshots for %s: %s", user_id, list(warmed))
    return {"user_id": str(user_id), "warmed": warmed}
