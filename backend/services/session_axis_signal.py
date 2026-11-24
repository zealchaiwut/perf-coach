"""Per-session fitness-signal rows for the session drawer (7 radar axes).

One source per row: status, delta and reason come from the same qualification
or session_contribution result. Scores come from score_reader / radar
display_score so they match the Performance tab.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.services.axis_spec import PERFORMANCE_AXES
from backend.services.radar_payload import AXIS_LABELS
from backend.services.score_format import display_score
from backend.utils.workout_types import is_strength_workout

MOVED_STATUSES = frozenset({"raised", "lowered", "first"})
DELTA_STATUSES = frozenset({"raised", "lowered", "counted"})
NO_DELTA_STATUSES = frozenset({"not_counted", "not_this_kind", "not_measured", "first"})

_LIFT_TYPES = frozenset({"strength", "lift", "plyo", "plyometrics", "mobility"})


def session_kind(workout) -> str:
    wt = (getattr(workout, "workout_type", None) or "").strip().lower()
    if "run" in wt:
        return "run"
    if is_strength_workout(wt) or any(wt.startswith(t) or t in wt for t in _LIFT_TYPES):
        return "lift"
    return "other"


def axis_signal_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    moved = sum(1 for r in rows if r.get("status") in MOVED_STATUSES)
    return {"moved": moved, "total": 7}


def _minutes(seconds: Any) -> int:
    try:
        return int(round(float(seconds) / 60.0))
    except (TypeError, ValueError):
        return 0


def _fmt_pace(sec_per_km: Any) -> str:
    try:
        s = int(round(float(sec_per_km)))
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    return f"{s // 60}:{s % 60:02d}"


def _status_from_delta(delta: Any) -> tuple[str, float]:
    d = round(float(delta), 1)
    if d > 0.05:
        return "raised", d
    if d < -0.05:
        return "lowered", d
    return "counted", 0.0


def _radar_display_scores(session: Session, user_id, today: date) -> dict[str, Optional[int]]:
    """Today's integer scores — identical to the Performance radar."""
    empty = {name: None for name in PERFORMANCE_AXES}
    try:
        from backend.services.radar_payload import build_axes
        from backend.services import score_reader

        overall = score_reader.get_scores(user_id, as_of=today)["overall"]
        axis_blocks = score_reader.get_axis_scores(session, user_id, as_of=today)["axes"]
        past = {name: None for name in PERFORMANCE_AXES}
        axes = build_axes(overall, axis_blocks, past)
        out = {a["axis"]: a.get("score_display") for a in axes}
        for name in PERFORMANCE_AXES:
            out.setdefault(name, None)
        return out
    except Exception:
        return empty


def _wid(workout) -> str:
    return str(getattr(workout, "id", "") or "")


def _endurance_row(
    workout, kind: str, result: Optional[dict], score: Optional[int]
) -> tuple[str, Optional[float], str]:
    if kind != "run":
        return "not_this_kind", None, "Endurance moves with runs."
    result = result or {}
    wid = _wid(workout)
    skip = (result.get("run_skip_reasons") or {}).get(wid)
    detail = (result.get("run_skip_detail") or {}).get(wid) or {}
    contrib = (result.get("run_contributions") or {}).get(wid)
    if skip == "too_short":
        n = _minutes(detail.get("duration_seconds", getattr(workout, "duration_seconds", None)))
        return "not_counted", None, f"Endurance uses runs over 40 min; this one was {n} min."
    if skip == "planned_cut_short":
        return "not_counted", None, "This run was cut short of the planned duration."
    if skip == "has_hard_efforts":
        desc = detail.get("hard_desc") or "hard efforts"
        return "not_counted", None, f"Endurance uses steady runs; this one had {desc}."
    if skip == "insufficient_data":
        return "not_counted", None, "Not enough easy-lap data to count toward Endurance."
    if skip:
        return "not_counted", None, "This run did not qualify for Endurance."
    if contrib is not None:
        status, delta = _status_from_delta(contrib)
        if status == "raised":
            reason = f"Steady aerobic work raised the score by {delta}."
        elif status == "lowered":
            reason = f"This run lowered the score by {abs(delta)}."
        else:
            mins = _minutes(getattr(workout, "duration_seconds", None))
            reason = f"Steady {mins} min, but below your 3 best anchors."
        return status, delta, reason
    if result.get("state") == "needs_thresholds":
        return "not_counted", None, "Endurance needs threshold HR before sessions can count."
    # Qualified but the axis has not scored yet (need ≥3 runs).
    return "first", None, "First qualifying easy run; Endurance needs more before it scores."


def _speed_row(
    workout, kind: str, result: Optional[dict], score: Optional[int]
) -> tuple[str, Optional[float], str]:
    if kind != "run":
        return "not_this_kind", None, "Speed moves with hard run efforts."
    result = result or {}
    wid = _wid(workout)
    skip = (result.get("run_skip_reasons") or {}).get(wid)
    contrib = (result.get("run_contributions") or {}).get(wid)
    effort = (result.get("run_effort") or {}).get(wid) or {}
    pace = _fmt_pace(effort.get("pace_s_per_km"))
    mins = _minutes(effort.get("duration_seconds"))
    effort_bit = f"{mins} min at {pace} /km" if pace and mins else "This hard effort"

    if skip == "no_hard_effort" or (skip and contrib is None):
        return "not_counted", None, "No hard effort in this run."
    if contrib is not None:
        status, delta = _status_from_delta(contrib)
        if status == "raised":
            reason = f"{effort_bit} is a new Speed anchor and raised the score by {delta}."
        elif status == "lowered":
            reason = f"{effort_bit} lowered the score by {abs(delta)}."
        else:
            reason = f"{effort_bit} counted but did not move the score."
        return status, delta, reason
    if result.get("state") == "needs_thresholds":
        return "not_counted", None, "Speed needs a threshold pace before sessions can count."
    return "first", None, "First qualifying hard effort; Speed needs more before it scores."


def _row(
    axis: str,
    status: str,
    delta: Optional[float],
    reason: str,
    score: Optional[int],
) -> dict[str, Any]:
    if score is None and status == "not_this_kind" and axis == "mobility":
        status = "not_measured"
        if not reason:
            reason = "Mobility comes from tests, not sessions."
    if status in NO_DELTA_STATUSES:
        delta = None
    elif status in DELTA_STATUSES and delta is None:
        delta = 0.0
    else:
        delta = round(float(delta), 1) if delta is not None else None
    if not (reason or "").strip():
        reason = "No detail for this axis."
    return {
        "axis": axis,
        "label": AXIS_LABELS.get(axis, axis),
        "score": score if score is not None else None,
        "status": status,
        "delta": delta,
        "reason": reason.strip(),
    }


def session_axis_signal(
    session: Session,
    workout,
    today: date,
    *,
    endurance_result: Optional[dict] = None,
    speed_result: Optional[dict] = None,
    exercises: Optional[list] = None,
    scores: Optional[dict[str, Optional[int]]] = None,
) -> list[dict[str, Any]]:
    """Return 7 axis dicts in radar order for the session drawer card."""
    kind = session_kind(workout)
    if scores is None:
        scores = _radar_display_scores(session, getattr(workout, "user_id", None), today)
    # Coerce any leftover 1-dp floats through the same integer rounding the radar uses.
    display = {
        name: (display_score(scores.get(name)) if scores.get(name) is not None else None)
        for name in PERFORMANCE_AXES
    }

    from backend.services import axis_economy, axis_durability, axis_mobility, axis_strength
    from backend.services import power_to_weight as p2w

    e_status, e_delta, e_reason = _endurance_row(
        workout, kind, endurance_result, display["endurance"]
    )
    s_status, s_delta, s_reason = _speed_row(
        workout, kind, speed_result, display["speed"]
    )
    eco_status, eco_delta, eco_reason = axis_economy.session_contribution(
        workout, today, session=session
    )
    st_status, st_delta, st_reason = axis_strength.session_contribution(
        workout, today, session=session, exercises=exercises
    )
    mob_status, mob_delta, mob_reason = axis_mobility.session_contribution(
        workout, today, session=session
    )
    pw_status, pw_delta, pw_reason = p2w.session_contribution(
        workout, today, session=session
    )
    dur_status, dur_delta, dur_reason = axis_durability.session_contribution(
        workout, today, session=session
    )

    packed = [
        ("endurance", e_status, e_delta, e_reason),
        ("speed", s_status, s_delta, s_reason),
        ("economy", eco_status, eco_delta, eco_reason),
        ("strength", st_status, st_delta, st_reason),
        ("mobility", mob_status, mob_delta, mob_reason),
        ("power_to_weight", pw_status, pw_delta, pw_reason),
        ("durability", dur_status, dur_delta, dur_reason),
    ]
    return [_row(axis, status, delta, reason, display.get(axis)) for axis, status, delta, reason in packed]
