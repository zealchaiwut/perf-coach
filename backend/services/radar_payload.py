"""Radar payload (revamp P4-6): one reader for the Home and Performance radars.

Per axis: score now, score 28 days ago (from the shared daily snapshot table),
stale, never_measured, focus, plus a short status label and an accessible
summary sentence — all built server-side so both pages show identical text.
Scores come from ``score_reader`` (never recomputed here).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from backend.services.axis_spec import PERFORMANCE_AXES

AXIS_LABELS: dict[str, str] = {
    "endurance": "Endurance",
    "speed": "Speed",
    "economy": "Economy",
    "strength": "Strength",
    "mobility": "Mobility",
    "power_to_weight": "Power/wt",
    "durability": "Durability",
}

MINUS = "\u2212"


def fmt_score(score: Optional[float]) -> str:
    return "–" if score is None else str(int(round(float(score))))


def fmt_delta(delta: Optional[float]) -> Optional[str]:
    if delta is None:
        return None
    n = int(round(float(delta)))
    if n == 0:
        return "0"
    return f"+{n}" if n > 0 else f"{MINUS}{abs(n)}"


def axis_status(axis: dict[str, Any]) -> str:
    """Short status: focus, stale, test due, or the signed 28-day delta ('' when none)."""
    if axis["never_measured"]:
        return ""
    if axis.get("focus"):
        return "focus"
    if axis.get("axis") == "mobility" and axis.get("days_since_test") is not None:
        return f"test {int(axis['days_since_test'])} d ago"
    if axis["stale"]:
        return "test due" if axis.get("test_due") else "stale"
    return fmt_delta(axis.get("delta_28d")) or ""


def summary_sentence(axes: list[dict[str, Any]]) -> str:
    measured, missing = [], []
    for a in axes:
        label = AXIS_LABELS[a["axis"]]
        if a["never_measured"]:
            missing.append(label)
            continue
        bits = [f"{label} {fmt_score(a['score'])}"]
        if a["stale"]:
            bits.append("stale" if not a.get("test_due") else "test due")
        if a.get("focus"):
            bits.append("focus")
        measured.append(" ".join(bits[:1]) + (f" ({', '.join(bits[1:])})" if len(bits) > 1 else ""))
    out = "Performance radar. " + (", ".join(measured) + "." if measured else "No axis measured yet.")
    if missing:
        out += " Not yet measured: " + ", ".join(missing) + "."
    out += " Dashed outline is four weeks ago."
    return out


def build_axes(
    overall: dict[str, dict],
    axis_blocks: dict[str, dict],
    past_scores: dict[str, Optional[float]],
    focus_axis: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Pure assembly (fixture-friendly): ordered per P4-1, one dict per axis."""
    axes: list[dict[str, Any]] = []
    for name in PERFORMANCE_AXES:
        block = overall.get(name) if name in ("endurance", "speed") else axis_blocks.get(name)
        block = block or {}
        score = block.get("score")
        never = score is None
        past = past_scores.get(name)
        delta = block.get("delta_28d")
        if delta is None and score is not None and past is not None:
            delta = round(float(score) - float(past), 1)
        axis = {
            "axis": name,
            "label": AXIS_LABELS[name],
            "score": None if never else round(float(score), 1),
            "score_28d_ago": None if past is None else round(float(past), 1),
            "delta_28d": delta,
            "stale": False if never else bool(block.get("stale")),
            "never_measured": never,
            "focus": (name == focus_axis) and not never,
            "test_due": bool(block.get("test_due")) if name == "mobility" else False,
            "days_since_test": block.get("days_since_test") if name == "mobility" else None,
        }
        axis["status"] = axis_status(axis)
        axes.append(axis)
    return axes


def build_radar(
    session,
    user_id: uuid.UUID,
    as_of: date,
    focus_axis: Optional[str] = None,
    focus_ranker=None,
) -> dict[str, Any]:
    """``focus_ranker(axes) -> Optional[str]`` picks the focus axis from the unflagged axes."""
    from backend.services import axis_snapshot, score_reader

    overall = score_reader.get_scores(user_id, as_of=as_of)["overall"]
    axis_blocks = score_reader.get_axis_scores(session, user_id, as_of)["axes"]
    row = axis_snapshot.snapshot_row_on_or_before(session, user_id, as_of - timedelta(days=28))
    past = {name: (getattr(row, name, None) if row is not None else None) for name in PERFORMANCE_AXES}
    axes = build_axes(overall, axis_blocks, past, focus_axis)
    if focus_axis is None and focus_ranker is not None:
        picked = focus_ranker(axes)
        if picked:
            axes = build_axes(overall, axis_blocks, past, picked)
    return {
        "as_of": as_of.isoformat(),
        "axis_order": list(PERFORMANCE_AXES),
        "axes": axes,
        "not_yet_measured": [a["label"] for a in axes if a["never_measured"]],
        "summary": summary_sentence(axes),
    }
