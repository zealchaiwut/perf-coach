"""Canonical score reader (revamp P0-5).

All consumers of aggregate/session scores should call this module so overall,
race-specific, and per-session values use consistent names and numbers.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.services import performance_scores as _performance_scores
from backend.services.performance_scores import _latest_race_perf


def _axis_from_payload_block(block: Optional[dict]) -> dict[str, Any]:
    if not isinstance(block, dict):
        return {
            "score": None,
            "delta_28d": None,
            "anchor_date": None,
            "anchor_title": None,
            "stale": False,
        }
    anchors = block.get("anchors") or []
    anchor = anchors[0] if anchors else {}
    stale = bool(anchor.get("is_stale"))
    return {
        "score": block.get("score"),
        "delta_28d": block.get("block_delta"),
        "anchor_date": anchor.get("date"),
        "anchor_title": anchor.get("title"),
        "stale": stale,
    }


def _axis_from_history(score: Optional[float]) -> dict[str, Any]:
    if score is None:
        return {
            "score": None,
            "delta_28d": None,
            "anchor_date": None,
            "anchor_title": None,
            "stale": False,
        }
    return {
        "score": score,
        "delta_28d": None,
        "anchor_date": None,
        "anchor_title": None,
        "stale": False,
    }


def get_scores(user_id: uuid.UUID, as_of: Optional[date] = None) -> dict[str, Any]:
    """Return overall endurance/speed scores for the athlete."""
    from backend.db import engine
    from backend.services import axis_snapshot
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    if as_of is None or as_of >= today:
        payload = _performance_scores.get_performance_payload(user_id)
        state = payload.get("state")
        overall = {
            "endurance": _axis_from_payload_block(payload.get("endurance")),
            "speed": _axis_from_payload_block(payload.get("speed")),
        }
        return {"state": state, "overall": overall, "generated_at": payload.get("generated_at")}

    with Session(engine) as session:
        row = axis_snapshot.snapshot_row_on_or_before(session, user_id, as_of)
        if row is None or (row.endurance is None and row.speed is None):
            empty = _axis_from_history(None)
            return {
                "state": "unavailable",
                "overall": {"endurance": empty, "speed": dict(empty)},
                "generated_at": None,
                "reason": "no snapshot on or before as_of",
            }
        state = "scored" if row.endurance is not None or row.speed is not None else "unavailable"
        return {
            "state": state,
            "overall": {
                "endurance": _axis_from_history(row.endurance),
                "speed": _axis_from_history(row.speed),
            },
            "generated_at": row.score_date.isoformat() if row.score_date else None,
        }


def get_axis_scores(session: Session, user_id: uuid.UUID, as_of: Optional[date] = None) -> dict[str, Any]:
    """Phase 4 axes (durability, economy, strength, mobility, power_to_weight).

    Same block conventions as ``get_scores`` (``score``, ``delta_28d``,
    ``anchor_date``, ``anchor_title``, ``stale``) plus ``never_measured`` and a
    ``raw`` value. ``delta_28d`` comes from the shared daily snapshot table.
    """
    from backend.services import axis_snapshot
    from backend.utils.time import today_bangkok

    day = as_of or today_bangkok()
    blocks = axis_snapshot.compute_axes(session, user_id, day)
    for axis, block in blocks.items():
        past = axis_snapshot.score_n_days_ago(session, user_id, day, axis)
        score = block.get("score")
        block["delta_28d"] = (
            round(float(score) - float(past), 1) if score is not None and past is not None else None
        )
    return {"axes": blocks}


def get_race_scores(
    session: Session,
    user_id: uuid.UUID,
    race,
    *,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """Race-distance-specific scores (anchor metadata from the target race)."""
    scores = get_scores(user_id, as_of=as_of)
    if scores.get("state") == "unavailable":
        return {"race_specific": None, "overall": scores.get("overall")}
    overall = scores["overall"]
    speed_overall = (overall.get("speed") or {}).get("score")
    race_specific = {
        "endurance": dict(overall["endurance"]),
        "speed": dict(overall["speed"]),
        "speed_overall": speed_overall,
    }
    race_date = getattr(race, "race_date", None)
    if race_date is not None:
        d = race_date.isoformat() if hasattr(race_date, "isoformat") else str(race_date)
        race_specific["endurance"]["anchor_date"] = d
        race_specific["speed"]["anchor_date"] = d
    anchor = _latest_race_perf(session, user_id, as_of=as_of)
    if anchor and anchor.get("perf") is not None:
        race_specific["speed"] = dict(race_specific["speed"])
        race_specific["speed"]["score"] = round(float(anchor["perf"]), 1)
        race_specific["speed_race_specific"] = round(float(anchor["perf"]), 1)
    else:
        race_specific["speed_race_specific"] = race_specific["speed"].get("score")
    return {"race_specific": race_specific, "overall": overall}


def session_signal(workout) -> dict[str, Any]:
    """Per-session signal block (not the 0–100 aggregate score)."""
    end = getattr(workout, "endurance_signal", None)
    spd = getattr(workout, "speed_signal", None)
    dur = getattr(workout, "duration_seconds", None) or 0
    if end is None and dur <= 40 * 60:
        end_reason = "run_under_40_min"
    elif end is None:
        end_reason = "insufficient_data"
    else:
        end_reason = None
    spd_reason = "no_hard_effort" if spd is None else None
    return {
        "session_signal": {
            "endurance": {"value": float(end) if end is not None else None, "reason": end_reason},
            "speed": {"value": float(spd) if spd is not None else None, "reason": spd_reason},
        }
    }


def consult_score_reader(session: Session, user_id: uuid.UUID, as_of: date) -> dict:
    """Default session consult score reader — same numbers as performance cards."""
    _na = "N/A"
    scores = get_scores(user_id, as_of=as_of)
    overall = scores["overall"]
    anchor = _latest_race_perf(session, user_id, as_of=as_of)
    return {
        "overall": overall,
        "endurance": overall["endurance"].get("score"),
        "speed": overall["speed"].get("score"),
        "as_of_date": scores.get("generated_at") or _na,
        "anchor_date": anchor.get("date") if anchor else _na,
        "anchor_effort": (
            round(anchor["perf"], 1) if anchor and anchor.get("perf") is not None else _na
        ),
    }