"""Plan-prefs accessor — single swap point for versioned training_preferences.

On branches where `training_prefs` is not yet merged, falls back to the
request/facts fields (rest days, strength_emphasis, notes). When the prefs
store lands, only this module needs to change.
"""
from __future__ import annotations

from typing import Any


_DEFAULTS = {
    "preferred_rest_days": [],
    "strength_emphasis": "same",
    "notes": "",
    "prefs_version": 0,
    "plyo_mode": "off",
    "plyo_sessions_per_week": 0,
    "long_run_mp_segment_min": 0,
    "stretch_daily_min": 0,
    "zone2_weekly_min": 0,
}


def get_plan_prefs(
    db=None,
    user_id=None,
    *,
    preferred_rest_days: list[int] | None = None,
    strength_emphasis: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Return plan-relevant prefs. Explicit overrides win when not None."""
    stored: dict[str, Any] = dict(_DEFAULTS)

    if db is not None and user_id is not None:
        try:
            from backend.services.training_prefs import prefs_for_assemble_facts
            stored.update(prefs_for_assemble_facts(db, user_id) or {})
        except Exception:
            # prefs_for_assemble_facts can write (carry-forward); a failure
            # mid-write leaves the caller's session in an aborted transaction
            # unless we roll it back here.
            try:
                db.rollback()
            except Exception:
                pass

    if preferred_rest_days is not None:
        stored["preferred_rest_days"] = list(preferred_rest_days)
    if strength_emphasis is not None:
        stored["strength_emphasis"] = strength_emphasis
    if notes is not None:
        stored["notes"] = notes

    emphasis = str(stored.get("strength_emphasis") or "same").strip().lower()
    if emphasis not in ("less", "same", "more"):
        emphasis = "same"
    stored["strength_emphasis"] = emphasis
    stored["preferred_rest_days"] = sorted({
        int(d) for d in (stored.get("preferred_rest_days") or []) if 0 <= int(d) <= 6
    })
    stored["notes"] = str(stored.get("notes") or "")[:300]
    return stored
