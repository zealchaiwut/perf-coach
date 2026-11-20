"""Canonical session TSS reader (revamp P0-3).

Stores power-method and Stryd values separately; picks one counted value per
user default, per-session override, and availability rules.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

from backend.models import UserPreferences, Workout

_log = logging.getLogger(__name__)

TSS_METHODS = frozenset({"power", "stryd"})
DEFAULT_TSS_METHOD = "power"


def resolve_tss_method_default(prefs: Optional[UserPreferences]) -> str:
    if prefs is None:
        return DEFAULT_TSS_METHOD
    method = getattr(prefs, "tss_method_default", None) or DEFAULT_TSS_METHOD
    if method not in TSS_METHODS:
        return DEFAULT_TSS_METHOD
    return method


def session_tss(
    workout: Workout,
    *,
    prefs: Optional[UserPreferences] = None,
    stryd_tss: Optional[int] = None,
    session=None,
    exercises: Optional[list] = None,
) -> dict[str, Any]:
    """Return counted TSS and method for a session.

    Order: session override → user default → whichever value exists → null.
    Manual athlete TSS always wins and is returned as method ``manual``.
    """
    from backend.services.strength_tss import is_strength_workout, strength_tss_block

    if is_strength_workout(workout):
        block = strength_tss_block(workout, session=session, exercises=exercises)
        if workout.tss_source == "manual" and workout.tss is not None:
            block = {**block, "tss": float(workout.tss), "method": "manual"}
        return block

    if workout.tss_source == "manual" and workout.tss is not None:
        return {
            "tss": float(workout.tss),
            "method": "manual",
            "tss_power": _float_or_none(getattr(workout, "tss_power", None)),
            "tss_stryd": _float_or_none(getattr(workout, "tss_stryd", None) or stryd_tss),
        }

    power = _float_or_none(getattr(workout, "tss_power", None))
    stryd = _float_or_none(getattr(workout, "tss_stryd", None))
    if stryd is None and stryd_tss is not None:
        stryd = float(stryd_tss)

    override = getattr(workout, "tss_method_override", None)
    if override in TSS_METHODS:
        picked = _pick_method(override, power, stryd)
        if picked is not None:
            val, method = picked
            return {"tss": val, "method": method, "tss_power": power, "tss_stryd": stryd}

    default_method = resolve_tss_method_default(prefs)
    picked = _pick_method(default_method, power, stryd)
    if picked is not None:
        val, method = picked
        return {"tss": val, "method": method, "tss_power": power, "tss_stryd": stryd}

    # Legacy fallback: counted column on workout row (pre-migration / strength).
    if workout.tss is not None:
        method = workout.tss_method or workout.tss_source or "unknown"
        return {
            "tss": float(workout.tss),
            "method": method,
            "tss_power": power,
            "tss_stryd": stryd,
        }

    return {"tss": None, "method": None, "tss_power": power, "tss_stryd": stryd}


def tss_dual_values_differ_notice(power: Optional[float], stryd: Optional[float]) -> bool:
    """True when both TSS values exist and differ by ≥10% of the larger (P1-7)."""
    if power is None or stryd is None:
        return False
    larger = max(abs(power), abs(stryd))
    if larger <= 0:
        return False
    return abs(power - stryd) / larger >= 0.10


def _pick_method(
    method: str,
    power: Optional[float],
    stryd: Optional[float],
) -> Optional[Tuple[float, str]]:
    if method == "power" and power is not None:
        return power, "power"
    if method == "stryd" and stryd is not None:
        return stryd, "stryd"
    if power is not None:
        return power, "power"
    if stryd is not None:
        return stryd, "stryd"
    return None


def _float_or_none(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def apply_counted_tss_to_workout(
    workout: Workout,
    *,
    prefs: Optional[UserPreferences],
    stryd_tss: Optional[int] = None,
) -> dict[str, Any]:
    """Write dual-method columns and sync workouts.tss from session_tss (unless manual)."""
    result = session_tss(workout, prefs=prefs, stryd_tss=stryd_tss)
    if workout.tss_source != "manual" and result.get("tss") is not None:
        workout.tss = int(round(result["tss"]))
        if result.get("method") and result["method"] != "manual":
            workout.tss_method = result["method"]
            workout.tss_source = "calculated"
    return result


def load_stryd_tss(session, workout: Workout) -> Optional[int]:
    pk = getattr(workout, "stryd_activity_pk", None)
    if not pk:
        return None
    from backend.models import StrydActivity

    sta = session.get(StrydActivity, pk)
    if sta is None or sta.tss is None:
        return None
    return int(sta.tss)


def refresh_workout_tss_storage(
    session,
    workout: Workout,
    *,
    power_tss: Optional[int] = None,
) -> None:
    """Persist tss_power / tss_stryd and sync counted tss after a compute/sync."""
    if power_tss is not None:
        workout.tss_power = float(power_tss)
    stryd = load_stryd_tss(session, workout)
    if stryd is not None:
        workout.tss_stryd = float(stryd)
    prefs = (
        session.query(UserPreferences)
        .filter(UserPreferences.user_id == workout.user_id)
        .first()
    )
    apply_counted_tss_to_workout(workout, prefs=prefs, stryd_tss=stryd)


def recompute_counted_tss_for_user(session, user_id, *, from_date=None) -> int:
    """Re-apply session_tss for every workout after default/override change."""
    from datetime import date as _date

    from backend.models import Workout

    q = session.query(Workout).filter(Workout.user_id == user_id)
    if from_date is not None:
        q = q.filter(Workout.workout_date >= from_date)
    rows = q.order_by(Workout.workout_date.asc()).all()
    prefs = (
        session.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )
    n = 0
    for w in rows:
        if w.tss_source == "manual":
            continue
        stryd = load_stryd_tss(session, w)
        apply_counted_tss_to_workout(w, prefs=prefs, stryd_tss=stryd)
        n += 1
    if n and from_date is None:
        _log.info("recompute_counted_tss_for_user: updated %s workouts for %s", n, user_id)
    return n