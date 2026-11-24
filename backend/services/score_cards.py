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
from backend.services.score_format import display_score

EPS = 0.005
AXES = ("endurance", "speed")
AXIS_LABELS = {"endurance": "Endurance", "speed": "Speed"}


def _anchor_name(anchor: dict[str, Any]) -> str:
    return anchor.get("title") or "anchor effort"


def _fmt_anchor_date(iso: Optional[str]) -> Optional[str]:
    if not iso:
        return None
    try:
        from datetime import date as _date

        d = _date.fromisoformat(str(iso)[:10])
        return f"{d.day} {d.strftime('%b')}"
    except ValueError:
        return str(iso)


def reason_sentence(
    breakdown: Optional[dict[str, Any]],
    *,
    delta_28d: Optional[float] = None,
) -> Optional[str]:
    """Plain-language reason from the decomposition and the 28-day delta."""
    if not isinstance(breakdown, dict) or "decay" not in breakdown or "efforts" not in breakdown:
        return None
    decay = float(breakdown.get("decay") or 0.0)
    efforts = float(breakdown.get("efforts") or 0.0)
    anchors = [a for a in (breakdown.get("anchors") or []) if a.get("date")]
    delta = None if delta_28d is None else int(round(float(delta_28d)))
    stale_n = sum(1 for a in anchors if a.get("is_stale"))
    if delta is not None and delta > 0 and stale_n >= 2 and len(anchors) >= 3:
        old = [a for a in anchors if float(a.get("age_weeks") or 0) >= 5]
        n_old = len(old) if old else stale_n
        return (
            f"Up {delta}, but {n_old} of {len(anchors)} anchors are over five weeks old and decaying."
        )
    if decay < 0 and -decay > efforts + EPS:
        if delta is not None and delta > 0:
            newest = min(anchors, key=lambda a: float(a.get("age_weeks") or 0.0)) if anchors else None
            if newest:
                return f"Up {delta}. Lifted by the effort on {newest['date']}."
            return f"Up {delta}."
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
        return f"Lifted by the hard effort on {newest['date']}."
    if delta is not None and delta > 0:
        return f"Up {delta}."
    return None


def breakdown_rows(breakdown: Optional[dict[str, Any]], *, top_k: int = 3) -> Optional[list[dict[str, Any]]]:
    """Structured 'Where N comes from' rows. Score row is max(avg, floor) + bonus."""
    if not isinstance(breakdown, dict) or "error" in breakdown:
        return None
    if breakdown.get("anchor_mean_now") is None and breakdown.get("score_now") is None:
        return None
    avg = float(breakdown.get("anchor_mean_now") or 0.0)
    floor = breakdown.get("race_floor_now")
    floor_f = None if floor is None else float(floor)
    bonus = float(breakdown.get("consistency_bonus_now") or 0.0)
    used_floor = floor_f is not None and floor_f > avg + EPS
    inner = floor_f if used_floor else avg
    raw = round(inner + bonus, 1)
    shown = breakdown.get("score_now")
    if shown is not None:
        raw = round(float(shown), 1)
    rows = [
        {
            "key": "anchor_mean",
            "label": f"Average of {top_k} anchor efforts, after decay",
            "value": round(avg, 1),
            "muted": used_floor,
        },
        {
            "key": "race_floor",
            "label": "Race floor, used only if higher",
            "value": None if floor_f is None else round(floor_f, 1),
            "muted": not used_floor,
        },
        {
            "key": "consistency",
            "label": "Consistency bonus",
            "value": round(bonus, 1),
            "muted": False,
            "signed": True,
        },
        {
            "key": "score",
            "label": "Score",
            "value": raw,
            "display": display_score(raw),
            "muted": False,
        },
    ]
    return rows


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
        "score_display": display_score(
            None if reader_block.get("score") is None else round(float(reader_block["score"]), 1)
        ),
        "delta_28d": reader_block.get("delta_28d"),
        "stale": bool(reader_block.get("stale")),
        "sparkline": {"dates": list(dates), "values": list(values)} if dates and values else None,
        "decomposition": decomposition,
        "formula_line": formula_line(breakdown, top_k=top_k) if valid else None,
        "split": None,
        "breakdown_rows": breakdown_rows(breakdown, top_k=top_k) if valid else None,
        "reason": reason_sentence(breakdown, delta_28d=reader_block.get("delta_28d")) if valid else None,
        "to_reach": to_reach_line(axis, perf_block.get("improve_hint")),
        "target_score": (perf_block.get("improve_hint") or {}).get("target_score") if isinstance(perf_block.get("improve_hint"), dict) else None,
        "anchors": [
            {**a, "display_date": _fmt_anchor_date(a.get("date"))}
            for a in anchors
        ],
    }


def build_cards(
    user_id: uuid.UUID,
    as_of: Optional[date] = None,
    *,
    overall: Optional[dict[str, Any]] = None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    overall = overall if overall is not None else score_reader.get_scores(user_id, as_of=as_of)
    payload = payload if payload is not None else _performance_scores.get_performance_payload(user_id)
    return {
        "state": overall.get("state"),
        "cards": [
            build_card(axis, overall["overall"][axis], payload.get(axis)) for axis in AXES
        ],
    }
