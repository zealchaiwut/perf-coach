"""Focus ranking and the work queue into Plan (revamp P4-7).

Ranking
    Eligible axes are fresh and measured only. Focus = highest
    ``(100 - score) x weight``; weights depend on the A-race distance. The
    why-not card lists the next three with a one-line reason each.

Work mapping (constants)
    Each axis maps to the work that moves it. ``economy``, ``durability``,
    ``strength`` and ``mobility`` are queueable; ``endurance``, ``speed`` and
    ``power_to_weight`` are coach-owned — shown as advice, never queued.

Queue
    ``queue_focus_work`` writes a suggestion record (axis, template tags, TSS
    estimate, earliest week) dated to the next build or rebuild week — never a
    taper or race week — that the P3-10 suggest-sessions preview consumes.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Iterable, Optional

from backend.services.axis_spec import PERFORMANCE_AXES, axis_focus_ranking_eligible
from backend.services.score_format import display_score

# ---------------------------------------------------------------------------
# Weights (by A-race distance) — must sum to 1, asserted at import.
# ---------------------------------------------------------------------------

WEIGHTS_MARATHON: dict[str, float] = {
    "durability": 0.25,
    "economy": 0.20,
    "endurance": 0.20,
    "power_to_weight": 0.15,
    "strength": 0.10,
    "speed": 0.05,
    "mobility": 0.05,
}
# Half: speed and durability 0.15 each; the others keep their marathon share
# (the 0.30 that speed + durability hold in both tables is unchanged).
WEIGHTS_HALF: dict[str, float] = {
    "durability": 0.15,
    "economy": 0.20,
    "endurance": 0.20,
    "power_to_weight": 0.15,
    "strength": 0.10,
    "speed": 0.15,
    "mobility": 0.05,
}

for _name, _w in (("marathon", WEIGHTS_MARATHON), ("half", WEIGHTS_HALF)):
    assert abs(sum(_w.values()) - 1.0) < 1e-9, f"{_name} focus weights must sum to 1"

MARATHON_MIN_KM = 30.0

BUILD_PHASES = ("build", "rebuild")
MAX_WEEKS_AHEAD = 26

# ---------------------------------------------------------------------------
# Work mapping per axis.
# ---------------------------------------------------------------------------

WORK_MAP: dict[str, dict[str, Any]] = {
    "economy": {
        "queueable": True, "kind": "session", "session_type": "plyo",
        "template_tags": ["plyo", "heavy_calf_raise", "drills"],
        "name": "Economy block: plyo, heavy calf raise, drills",
        "advice": "Plyo, heavy calf raises and drills move running economy.",
        "tss_estimate": 22.0,
    },
    "durability": {
        "queueable": True, "kind": "notes", "session_type": None,
        "template_tags": ["long_run_length", "fuel_practice"],
        "name": "Durability: long-run length and fuel practice",
        "advice": "Extend the long run and practise fuelling in it to cut late-run drift.",
        "tss_estimate": 0.0,
    },
    "strength": {
        "queueable": True, "kind": "session", "session_type": "strength",
        "template_tags": ["anchor_lift_block"],
        "name": "Strength: anchor-lift block",
        "advice": "Load the anchor lifts (single-leg deadlift, calf raise).",
        "tss_estimate": 28.0,
    },
    "mobility": {
        "queueable": True, "kind": "session", "session_type": "stretch",
        "template_tags": ["stretch_block"],
        "name": "Mobility: stretch block",
        "advice": "A short stretch block, then retest knee-to-wall and sit-and-reach.",
        "tss_estimate": 8.0,
    },
    "endurance": {
        "queueable": False, "kind": "advice", "session_type": None, "template_tags": [],
        "name": "Endurance",
        "advice": "Coach-owned work: it moves with the plan's long and steady runs.",
        "tss_estimate": 0.0,
    },
    "speed": {
        "queueable": False, "kind": "advice", "session_type": None, "template_tags": [],
        "name": "Speed",
        "advice": "Coach-owned work: it moves with the plan's quality sessions.",
        "tss_estimate": 0.0,
    },
    "power_to_weight": {
        "queueable": False, "kind": "advice", "session_type": None, "template_tags": [],
        "name": "Power-to-weight",
        "advice": "Coach-owned work: it follows the weight plan and easy-run power.",
        "tss_estimate": 0.0,
    },
}
COACH_OWNED_AXES = frozenset(a for a, w in WORK_MAP.items() if not w["queueable"])
QUEUEABLE_AXES = frozenset(a for a, w in WORK_MAP.items() if w["queueable"])

AXIS_LABELS = {
    "endurance": "Endurance", "speed": "Speed", "economy": "Economy", "strength": "Strength",
    "mobility": "Mobility", "power_to_weight": "Power-to-weight", "durability": "Durability",
}


def weights_for_distance(distance_km: Optional[float]) -> tuple[str, dict[str, float]]:
    if distance_km is not None and 0 < float(distance_km) < MARATHON_MIN_KM:
        return "half", WEIGHTS_HALF
    return "marathon", WEIGHTS_MARATHON


def weighted_gap(score: float, weight: float) -> float:
    return (100.0 - float(score)) * weight


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def rank_axes(axes: Iterable[dict[str, Any]], distance_km: Optional[float] = None) -> dict[str, Any]:
    """``axes``: radar-style dicts (axis, score, stale, never_measured)."""
    klass, weights = weights_for_distance(distance_km)
    by = {a["axis"]: a for a in axes}
    scored = []
    for name, a in by.items():
        if a.get("never_measured") or a.get("score") is None:
            continue
        eligible = axis_focus_ranking_eligible(score=a["score"], stale=bool(a.get("stale")))
        scored.append({
            "axis": name,
            "label": AXIS_LABELS.get(name, name),
            "score": float(a["score"]),
            "weight": weights[name],
            "gap": 100.0 - float(a["score"]),
            "weighted_gap": weighted_gap(a["score"], weights[name]),
            "eligible": eligible,
            "stale": bool(a.get("stale")),
        })
    eligible = sorted((s for s in scored if s["eligible"]), key=lambda s: (-s["weighted_gap"], s["axis"]))
    stale = sorted((s for s in scored if not s["eligible"]), key=lambda s: (-s["weighted_gap"], s["axis"]))
    focus = eligible[0] if eligible else None
    scored_by = {s["axis"]: s for s in scored}

    def _reason_for(axis_name: str, s: Optional[dict[str, Any]], a: dict[str, Any]) -> tuple[str, str]:
        """Short phrase + status. No label/score prefix — the table prints those."""
        if a.get("never_measured") or a.get("score") is None:
            if axis_name == "mobility":
                return "Not measured · log a test", "never_measured"
            return "Not measured yet", "never_measured"
        if s is None:
            return "Not ranked", "stale"
        if s["stale"]:
            return "Not ranked · anchor stale", "stale"
        if focus is not None and s["gap"] >= focus["gap"]:
            return "Lower priority for this distance", "ranked"
        if focus is not None:
            return "Smaller weighted gap", "ranked"
        return "Not ranked", "ranked"

    why_not: list[dict[str, Any]] = []
    focus_axis = focus["axis"] if focus else None
    for name in PERFORMANCE_AXES:
        if name == focus_axis:
            continue
        a = by.get(name) or {}
        s = scored_by.get(name)
        never = bool(a.get("never_measured") or a.get("score") is None)
        reason, status = _reason_for(name, s, a)
        ranked = status == "ranked"
        why_not.append({
            "axis": name,
            "label": AXIS_LABELS.get(name, name),
            "score": None if never else a.get("score"),
            "score_display": None if never else display_score(a.get("score")),
            "weight_pct": int(round(s["weight"] * 100)) if ranked and s else None,
            "weighted_gap": round(s["weighted_gap"], 1) if ranked and s else None,
            "stale": bool(s and s["stale"]),
            "never_measured": never,
            "status": status,
            "reason": reason,
        })
    why_not.sort(
        key=lambda w: (
            2 if w.get("never_measured") else (1 if w.get("stale") else 0),
            -(w["weighted_gap"] or 0),
            w["axis"],
        )
    )

    focus_rationale = None
    if focus is not None:
        focus_rationale = "Lowest that's fresh and matters"

    work = WORK_MAP[focus["axis"]] if focus else None
    why_line = None
    if eligible:
        top = eligible[0]
        why_line = f"Biggest weighted gap among fresh axes: {top['weighted_gap']:.1f}"
        if len(eligible) > 1:
            nxt = eligible[1]
            why_line += f", next is {nxt['label']} at {nxt['weighted_gap']:.1f}"
    return {
        "distance_class": klass,
        "weights": dict(weights),
        "focus": (
            {
                "axis": focus["axis"], "label": focus["label"], "score": focus["score"],
                "score_display": display_score(focus["score"]),
                "weight": focus["weight"],
                "weight_pct": int(round(focus["weight"] * 100)),
                "weighted_gap": round(focus["weighted_gap"], 1),
                "status": "focus",
                "reason": focus_rationale,
                "why_line": why_line,
                "work": {k: work[k] for k in ("name", "advice", "queueable", "kind", "template_tags", "tss_estimate")},
            }
            if focus else None
        ),
        "why_not": why_not,
        "focus_rationale": focus_rationale,
        "why_line": why_line,
    }


# ---------------------------------------------------------------------------
# Queue: earliest eligible week + record
# ---------------------------------------------------------------------------


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def earliest_queue_week(phase_for_week, today: date, max_weeks: int = MAX_WEEKS_AHEAD) -> Optional[date]:
    """First week (from the current one) whose phase is build or rebuild.

    ``phase_for_week(week_monday) -> Optional[str]`` is injected so this stays pure.
    """
    ws = week_monday(today)
    for i in range(max_weeks + 1):
        w = ws + timedelta(days=7 * i)
        if phase_for_week(w) in BUILD_PHASES:
            return w
    return None


class QueueError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def validate_queue_axis(axis: str) -> dict[str, Any]:
    if axis not in WORK_MAP:
        raise QueueError(422, f"unknown axis '{axis}'")
    if axis in COACH_OWNED_AXES:
        raise QueueError(422, f"{AXIS_LABELS[axis]} is coach-owned work: advice only, it is never queued")
    return WORK_MAP[axis]


def item_dict(row) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "axis": row.axis,
        "template_tags": list(row.template_tags or []),
        "tss_estimate": float(row.tss_estimate) if row.tss_estimate is not None else None,
        "earliest_week": row.earliest_week.isoformat(),
        "status": row.status,
        "notes": row.notes,
    }


def _phase_lookup(session, user_id: uuid.UUID, today: date):
    from backend.services.revamp_load_plan import week_target_and_phase

    def phase(ws: date) -> Optional[str]:
        meta = week_target_and_phase(user_id, ws, session=session, today=today)
        return (meta or {}).get("phase")

    return phase


def queued_items(session, user_id: uuid.UUID) -> list[Any]:
    from backend.models import PerformanceQueueItem as Q

    return (
        session.query(Q)
        .filter(Q.user_id == user_id, Q.status == "queued")
        .order_by(Q.created_at.asc())
        .all()
    )


def queue_focus_work(session, user_id: uuid.UUID, axis: str, today: date, phase_for_week=None) -> tuple[Any, bool]:
    """Create (or return the existing) queued record. Returns (row, created)."""
    from backend.models import PerformanceQueueItem as Q

    work = validate_queue_axis(axis)
    existing = (
        session.query(Q).filter(Q.user_id == user_id, Q.axis == axis, Q.status == "queued").first()
    )
    if existing is not None:
        return existing, False
    phase_for_week = phase_for_week or _phase_lookup(session, user_id, today)
    week = earliest_queue_week(phase_for_week, today)
    if week is None:
        raise QueueError(409, "No build or rebuild week ahead to queue this work into")
    row = Q(
        user_id=user_id,
        axis=axis,
        template_tags=list(work["template_tags"]),
        tss_estimate=work["tss_estimate"],
        earliest_week=week,
        status="queued",
        notes=work["advice"],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, True


def cancel_item(session, user_id: uuid.UUID, item_id: uuid.UUID) -> bool:
    from backend.models import PerformanceQueueItem as Q

    row = session.get(Q, item_id)
    if row is None or row.user_id != user_id:
        return False
    row.status = "cancelled"
    session.commit()
    return True


# ---------------------------------------------------------------------------
# P3-10 hook: queued work as suggest-sessions candidates / notes
# ---------------------------------------------------------------------------


def candidates_for_week(session, user_id: uuid.UUID, week_start: date, phase: Optional[str]):
    """(session candidates, note items) for a week. Only build/rebuild weeks consume the queue."""
    if phase not in BUILD_PHASES:
        return [], []
    cands, notes = [], []
    for row in queued_items(session, user_id):
        if row.earliest_week > week_start:
            continue
        work = WORK_MAP.get(row.axis)
        if work is None:
            continue
        if work["kind"] == "session" and work["session_type"]:
            cands.append({
                "candidate_id": f"queue:{row.id}",
                "name": work["name"],
                "session_type": work["session_type"],
                "structure": {
                    "suggested": True, "axis": row.axis,
                    "template_tags": list(row.template_tags or []), "notes": work["advice"],
                },
                "estimated_tss": float(row.tss_estimate if row.tss_estimate is not None else work["tss_estimate"]),
                "race_week_safe": False,
                "queue_item_id": str(row.id),
            })
        elif work["kind"] == "notes":
            notes.append({
                "queue_item_id": str(row.id), "axis": row.axis, "name": work["name"],
                "template_tags": list(row.template_tags or []), "notes": work["advice"],
            })
    return cands, notes
