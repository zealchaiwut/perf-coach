"""Endurance and Speed score cards (revamp P4-9).

Numbers come from the P0-5 reader (``score_reader.get_scores``: score, 28-day
delta, stale) and the existing change decomposition served through
``performance_scores.get_performance_payload`` (``breakdown``: score_then, decay,
efforts, consistency, score_now, anchors) plus the daily snapshot series
(``history_trend``). Nothing is re-derived here except the plain-language reason
and the decay-versus-gains bar split (display of the decomposition's own terms).

Reason rule (from the decomposition only):

- decay outweighs the effort gains  -> "Down from decay, not from slower running:
  the <anchor> from <date> has aged <n> weeks."
- effort gains outweigh decay       -> "Lifted by the effort on <date>."
- otherwise                         -> no sentence.

``to_reach`` and ``formula_line`` come from ``get_performance_payload`` —
``improve_hint`` (pace at the score type's reference effort) and the breakdown's
``anchor_mean_now`` / ``race_floor_now`` / ``consistency_bonus_now`` terms.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from backend.services import performance_scores as _performance_scores
from backend.services import score_reader
from backend.services.revamp_home import format_pace_seconds_per_km

EPS = 0.005
AXES = ("endurance", "speed")
AXIS_LABELS = {"endurance": "Endurance", "speed": "Speed"}


def _anchor_name(anchor: dict[str, Any]) -> str:
    return anchor.get("title") or "anchor effort"


def reason_sentence(breakdown: Optional[dict[str, Any]]) -> Optional[str]:
    """Plain-language reason from the decomposition, or None."""
    if not isinstance(breakdown, dict) or "decay" not in breakdown or "efforts" not in breakdown:
        return None
    decay = float(breakdown.get("decay") or 0.0)
    efforts = float(breakdown.get("efforts") or 0.0)
    anchors = [a for a in (breakdown.get("anchors") or []) if a.get("date")]
    if decay < 0 and -decay > efforts + EPS:
        if not anchors:
            return None
        aged = max(anchors, key=lambda a: float(a.get("age_weeks") or 0.0))
        return (
            "Down from decay, not from slower running: the "
            f"{_anchor_name(aged)} from {aged['date']} has aged {aged.get('age_weeks')} weeks."
        )
    if efforts > EPS and efforts > -decay + EPS:
        if not anchors:
            return None
        newest = min(anchors, key=lambda a: float(a.get("age_weeks") or 0.0))
        return f"Lifted by the effort on {newest['date']}."
    return None


def formula_line(breakdown: Optional[dict[str, Any]], *, top_k: int = 3) -> Optional[str]:
    """Auditable score composition: max(avg of K, race floor) + consistency bonus."""
    if not isinstance(breakdown, dict) or "error" in breakdown:
        return None
    if breakdown.get("anchor_mean_now") is None and breakdown.get("score_now") is None:
        return None
    avg = float(breakdown.get("anchor_mean_now") or 0.0)
    floor = breakdown.get("race_floor_now")
    cons = float(breakdown.get("consistency_bonus_now") or 0.0)
    total = breakdown.get("score_now")
    if total is None:
        return None
    avg_part = f"{round(avg, 1)} avg of {top_k}"
    if floor is not None:
        inner = f"max({avg_part}, {round(float(floor), 1)} race floor)"
    else:
        inner = avg_part
    return f"{inner} + {round(cons, 1)} consistency = {round(float(total), 1)}"


def to_reach_line(axis: str, hint: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(hint, dict) or hint.get("pace_seconds_per_km") is None:
        return None
    pace = format_pace_seconds_per_km(int(hint["pace_seconds_per_km"]))
    if not pace:
        return None
    target = hint.get("target_score")
    mins = hint.get("effort_minutes")
    if target is None or mins is None:
        return None
    mins_i = int(round(float(mins)))
    if axis == "speed":
        return f"To reach {target}: one hard effort at {pace} held about {mins_i} min."
    return f"To reach {target}: hold {pace} for {mins_i} min at threshold."


def split_bar(breakdown: Optional[dict[str, Any]]) -> Optional[dict[str, float]]:
    """Decay versus gains (efforts + consistency) as shares of the moved points."""
    if not isinstance(breakdown, dict) or "decay" not in breakdown:
        return None
    decay = max(0.0, -float(breakdown.get("decay") or 0.0))
    gains = max(0.0, float(breakdown.get("efforts") or 0.0)) + max(0.0, float(breakdown.get("consistency") or 0.0))
    total = decay + gains
    if total <= 0:
        return {"decay": 0.0, "gains": 0.0, "decay_share": 0.0, "gains_share": 0.0}
    return {
        "decay": round(decay, 2),
        "gains": round(gains, 2),
        "decay_share": round(decay / total, 4),
        "gains_share": round(gains / total, 4),
    }


def build_card(axis: str, reader_block: dict[str, Any], perf_block: Optional[dict[str, Any]]) -> dict[str, Any]:
    perf_block = perf_block if isinstance(perf_block, dict) else {}
    breakdown = perf_block.get("breakdown")
    valid = isinstance(breakdown, dict) and "error" not in breakdown
    decomposition = None
    anchors: list[dict[str, Any]] = []
    if valid:
        decomposition = {
            k: breakdown.get(k) for k in ("score_then", "decay", "efforts", "consistency", "score_now")
        }
        anchors = [
            {
                "date": a.get("date"),
                "raw_score": a.get("raw_score"),
                "age_weeks": a.get("age_weeks"),
                "is_stale": bool(a.get("is_stale")),
            }
            for a in (breakdown.get("anchors") or [])
        ]
    dates = perf_block.get("history_trend_dates") or []
    values = perf_block.get("history_trend") or []
    top_k = int((perf_block.get("model") or {}).get("top_k") or 3)
    return {
        "axis": axis,
        "label": AXIS_LABELS[axis],
        "score": reader_block.get("score"),
        "delta_28d": reader_block.get("delta_28d"),
        "stale": bool(reader_block.get("stale")),
        "sparkline": {"dates": list(dates), "values": list(values)} if dates and values else None,
        "decomposition": decomposition,
        "formula_line": formula_line(breakdown, top_k=top_k) if valid else None,
        "split": split_bar(breakdown) if valid else None,
        "reason": reason_sentence(breakdown) if valid else None,
        "to_reach": to_reach_line(axis, perf_block.get("improve_hint")),
        "anchors": anchors,
    }


def build_cards(user_id: uuid.UUID, as_of: Optional[date] = None) -> dict[str, Any]:
    overall = score_reader.get_scores(user_id, as_of=as_of)
    payload = _performance_scores.get_performance_payload(user_id)
    return {
        "state": overall.get("state"),
        "cards": [
            build_card(axis, overall["overall"][axis], payload.get(axis)) for axis in AXES
        ],
    }
