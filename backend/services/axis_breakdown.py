"""Per-axis score breakdown for the Performance Status widget.

Endurance and Speed keep the existing anchor decomposition. Other axes return
their own formula rows. Every score comes from ``score_reader`` so the panel
number matches the radar.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from backend.services.axis_spec import PERFORMANCE_AXES
from backend.services.score_format import display_score

ALL_AXES = PERFORMANCE_AXES
HOW_MEASURED = {
    "endurance": "Measured from recent threshold and race efforts.",
    "speed": "Measured from recent short hard efforts.",
    "economy": "Measured from Stryd form on easy runs.",
    "strength": "Measured from the logged anchor lifts.",
    "mobility": "Measured from a knee-to-wall and sit-and-reach self-test.",
    "power_to_weight": "Measured from critical power and the weight trend.",
    "durability": "Measured from pace or HR drift on an easy run of 90 min or longer.",
}


def _row(key: str, label: str, value: Any, *, muted: bool = False, signed: bool = False,
         display: Any = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "muted": muted,
        "signed": signed,
        "display": display,
    }


def _score_row(score: Optional[float]) -> dict[str, Any]:
    raw = None if score is None else round(float(score), 1)
    return _row("score", "Score", raw, display=display_score(raw))


def power_to_weight_rows(session, user_id: uuid.UUID, as_of: date, score: Optional[float]) -> list[dict[str, Any]]:
    from backend.models import WeightEntry
    from backend.services.cp_staleness import get_cp_status
    from backend.services.weight_ewma import compute_ewma

    cp = get_cp_status(session, user_id, as_of) or {}
    cp_w = cp.get("current_cp_w")
    rows = (
        session.query(WeightEntry.entry_date, WeightEntry.weight_kg)
        .filter(WeightEntry.user_id == user_id, WeightEntry.entry_date <= as_of)
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )
    entries = [{"date": r.entry_date, "weight_kg": float(r.weight_kg)} for r in rows]
    trend = compute_ewma(entries)[-1] if entries else None
    formula = None
    if cp_w is not None and trend:
        formula = f"CP {int(round(float(cp_w)))} W ÷ trend {round(float(trend), 1)} kg"
    out = [
        _row("cp", "Critical power", None if cp_w is None else round(float(cp_w), 1)),
        _row("weight_trend", "Weight trend", None if trend is None else round(float(trend), 1)),
        _score_row(score),
    ]
    if formula:
        out.insert(2, _row("formula", formula, None))
    return out


def build_axis_breakdown(
    session,
    user_id: uuid.UUID,
    axis: str,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    from backend.services import score_cards, score_reader
    from backend.services.performance_scores import get_performance_payload
    from backend.utils.time import today_bangkok

    if axis not in ALL_AXES:
        raise ValueError(f"unknown axis {axis}")
    day = as_of or today_bangkok()
    if axis in ("endurance", "speed"):
        overall = score_reader.get_scores(user_id, as_of=day)
        perf = get_performance_payload(user_id)
        card = score_cards.build_card(axis, overall["overall"][axis], perf.get(axis))
        return {
            "axis": axis,
            "metric": axis,
            "score": card.get("score"),
            "score_display": card.get("score_display"),
            "score_now": card.get("score"),
            "rows": card.get("breakdown_rows") or [],
            "anchors": card.get("anchors") or [],
            "reason": card.get("reason"),
            "to_reach": card.get("to_reach"),
            "target_score": card.get("target_score"),
            "delta_28d": card.get("delta_28d"),
            "stale": card.get("stale"),
            "how_measured": HOW_MEASURED[axis],
            "formula_line": card.get("formula_line"),
        }

    axes = score_reader.get_axis_scores(session, user_id, day)["axes"]
    block = axes.get(axis) or {}
    score = block.get("score")
    rows: list[dict[str, Any]]
    if axis == "power_to_weight":
        rows = power_to_weight_rows(session, user_id, day, score)
        formula = next((r["label"] for r in rows if r["key"] == "formula"), None)
    else:
        rows = [_score_row(score)]
        formula = None
        raw = block.get("raw")
        if raw is not None:
            rows.insert(0, _row("raw", "Raw", round(float(raw), 2)))
    return {
        "axis": axis,
        "metric": axis,
        "score": score,
        "score_display": display_score(None if score is None else round(float(score), 1)),
        "score_now": score,
        "rows": rows,
        "anchors": [],
        "reason": None,
        "to_reach": None,
        "target_score": None,
        "delta_28d": block.get("delta_28d"),
        "stale": bool(block.get("stale")),
        "never_measured": bool(block.get("never_measured") or score is None),
        "how_measured": HOW_MEASURED.get(axis),
        "formula_line": formula,
        "cp_w": (block.get("median_power_w") if axis == "power_to_weight" else None),
        "trend_mass_kg": block.get("trend_mass_kg") if axis == "power_to_weight" else None,
    }


def score_history_for_axis(
    session,
    user_id: uuid.UUID,
    axis: str,
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]]:
    from backend.models import PerformanceScoreHistory as H

    if axis not in ALL_AXES and axis not in ("endurance", "speed"):
        raise ValueError(f"unknown axis {axis}")
    rows = (
        session.query(H)
        .filter(
            H.user_id == user_id,
            H.score_date >= from_date,
            H.score_date <= to_date,
        )
        .order_by(H.score_date.asc(), H.created_at.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    seen: set[date] = set()
    for r in rows:
        if r.score_date in seen:
            continue
        val = getattr(r, axis, None)
        if val is None:
            continue
        seen.add(r.score_date)
        out.append({
            "date": r.score_date.isoformat(),
            "score": round(float(val), 1),
            "score_display": display_score(round(float(val), 1)),
            "formula_version": r.formula_version,
        })
    return out
