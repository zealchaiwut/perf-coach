"""Plan page warnings: layout errors and post-race clashes (P3-11)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import Race, RaceCheckpoint
from backend.services.revamp_load_plan import (
    REVAMP_PLAN_DEFAULTS,
    LoadPlanLayoutError,
    chronic_weekly_tss,
    compute_revamp_block_series,
    validate_block_layout,
    weeks_from_block_start_to_race,
)
from backend.services import revamp_plan_settings as _rps
from backend.utils.time import today_bangkok

MARATHON_DISTANCE_KM = 41.0
HALF_DISTANCE_KM = 20.0
POST_RACE_RULES = (
    ("marathon", MARATHON_DISTANCE_KM, 6, 15.0),
    ("half", HALF_DISTANCE_KM, 4, 10.0),
)

_HINT_ORDER = (
    ("rebuild_weeks", "rebuild weeks"),
    ("recover_weeks", "recover weeks"),
    ("peak_hold_weeks", "peak-hold weeks"),
    ("build_weeks", "build weeks"),
    ("taper_factors", "taper weeks"),
)


def _series_week_count(settings: dict[str, Any]) -> int:
    _peak, weeks = compute_revamp_block_series(chronic_baseline=100.0, settings=settings)
    return len(weeks)


def _layout_hint(settings: dict[str, Any], excess: int) -> str:
    s = {**REVAMP_PLAN_DEFAULTS, **settings}
    for key, label in _HINT_ORDER:
        cur = s.get(key)
        if key == "taper_factors" and isinstance(cur, list) and len(cur) > 1 and excess > 0:
            return f"Shorten {label} (currently {len(cur)} taper weeks) by {excess}."
        if isinstance(cur, int) and cur > 0 and excess > 0:
            drop = min(int(cur), excess)
            return f"Shorten {label} (currently {cur}) by at least {drop}."
    return "Shorten build, peak-hold, taper, recover, or rebuild weeks so the block fits the A race."


def layout_error(
    session: Session,
    user_id: uuid.UUID,
    settings: Optional[dict[str, Any]] = None,
    *,
    today: Optional[date] = None,
    ctx: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    today = today or today_bangkok()
    if ctx is None:
        if settings is not None:
            ctx = _rps.plan_context(session, user_id, today=today, draft=settings)
        else:
            ctx = _rps.plan_context(session, user_id, today=today)
    if ctx is None:
        return None
    race = ctx["race"]
    s = ctx["settings"]
    block_start = ctx["block_start"]
    chronic = ctx["chronic_baseline"]
    need = weeks_from_block_start_to_race(block_start, race.race_date)
    have = _series_week_count(s)
    try:
        validate_block_layout(
            chronic_baseline=chronic,
            block_start=block_start,
            race_date=race.race_date,
            settings=s,
        )
        return None
    except LoadPlanLayoutError as exc:
        excess = abs(have - need)
        return {
            "code": "layout_mismatch",
            "level": "error",
            "message": str(exc),
            "need_weeks": need,
            "have_weeks": have,
            "hint_setting": _layout_hint(s, excess),
            "blocks_settings_save": True,
        }


def _anchor_kind(distance_km: Optional[float]) -> Optional[str]:
    if distance_km is None:
        return None
    d = float(distance_km)
    if d >= MARATHON_DISTANCE_KM:
        return "marathon"
    if d >= HALF_DISTANCE_KM:
        return "half"
    return None


def _distance_km(row) -> float:
    if hasattr(row, "target_distance_km"):
        return float(getattr(row, "target_distance_km", None) or 0)
    return float(getattr(row, "distance_km", None) or 0)


def _clashes_from_rows(
    anchors: list,
    others: list,
    checkpoints: list,
) -> list[dict[str, Any]]:
    clashes: list[dict[str, Any]] = []
    for anchor in anchors:
        kind = _anchor_kind(anchor.distance_km)
        if kind is None:
            continue
        rule = next(r for r in POST_RACE_RULES if r[0] == kind)
        _label, _min_dist, window_days, min_effort_km = rule
        for r in others:
            if r.id == anchor.id:
                continue
            delta = (r.race_date - anchor.race_date).days
            if 0 < delta <= window_days and _distance_km(r) >= min_effort_km:
                suggested = r.race_date + timedelta(days=7)
                clashes.append(
                    {
                        "id": f"clash:race:{r.id}",
                        "level": "warn",
                        "message": (
                            f"{r.name} ({_distance_km(r):.0f} km) is {delta} days after "
                            f"{anchor.name}; move it at least a week later."
                        ),
                        "entity_type": "race",
                        "entity_id": str(r.id),
                        "suggested_date": suggested.isoformat(),
                    }
                )
        for cp in checkpoints:
            delta = (cp.target_date - anchor.race_date).days
            if 0 < delta <= window_days and _distance_km(cp) >= min_effort_km:
                suggested = cp.target_date + timedelta(days=7)
                clashes.append(
                    {
                        "id": f"clash:checkpoint:{cp.id}",
                        "level": "warn",
                        "message": (
                            f"Checkpoint {cp.label} ({_distance_km(cp):.0f} km) is {delta} days "
                            f"after {anchor.name}; move it to the same weekday one week later."
                        ),
                        "entity_type": "checkpoint",
                        "entity_id": str(cp.id),
                        "race_id": str(cp.race_id),
                        "suggested_date": suggested.isoformat(),
                    }
                )
    return clashes


def post_race_clashes(
    session: Session,
    user_id: uuid.UUID,
    *,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    today = today or today_bangkok()
    anchors = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "planned",
            Race.priority == "A",
            Race.race_date >= today - timedelta(days=365),
        )
        .order_by(Race.race_date)
        .all()
    )
    others = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.status == "planned")
        .order_by(Race.race_date)
        .all()
    )
    checkpoints = (
        session.query(RaceCheckpoint)
        .filter(RaceCheckpoint.user_id == user_id)
        .order_by(RaceCheckpoint.target_date)
        .all()
    )
    return _clashes_from_rows(anchors, others, checkpoints)


def revamp_warnings_payload(
    session: Session,
    user_id: uuid.UUID,
    settings: Optional[dict[str, Any]] = None,
    *,
    today: Optional[date] = None,
    ctx: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    layout = layout_error(session, user_id, settings, today=today, ctx=ctx)
    clashes = post_race_clashes(session, user_id, today=today)
    race_week_note = (
        "Weekly training target excludes race-day load; race TSS is counted separately."
    )
    return {
        "layout_error": layout,
        "clashes": clashes,
        "race_week_note": race_week_note,
    }


def apply_clash_suggestion(
    session: Session,
    user_id: uuid.UUID,
    warning_id: str,
) -> dict[str, Any]:
    """Move a clashing race or checkpoint to its suggested_date (+7d)."""
    if warning_id.startswith("clash:race:"):
        rid = uuid.UUID(warning_id.split(":")[-1])
        race = session.get(Race, rid)
        if race is None or race.user_id != user_id:
            raise ValueError("race not found")
        new_date = race.race_date + timedelta(days=7)
        race.race_date = new_date
        return {"entity_type": "race", "entity_id": str(rid), "planned_date": new_date.isoformat()}
    if warning_id.startswith("clash:checkpoint:"):
        cid = uuid.UUID(warning_id.split(":")[-1])
        cp = session.get(RaceCheckpoint, cid)
        if cp is None or cp.user_id != user_id:
            raise ValueError("checkpoint not found")
        new_date = cp.target_date + timedelta(days=7)
        cp.target_date = new_date
        return {
            "entity_type": "checkpoint",
            "entity_id": str(cid),
            "race_id": str(cp.race_id),
            "planned_date": new_date.isoformat(),
        }
    raise ValueError("unknown warning id")


def settings_save_allowed(session: Session, user_id: uuid.UUID, settings: dict[str, Any]) -> bool:
    """P3-12 should call before persisting revamp load settings."""
    return layout_error(session, user_id, settings) is None