"""Week-level muscle variation for pattern-filled draft sessions (no LLM)."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from backend.services.plan_pattern_fill import fill_and_stamp
from backend.utils.log import get_logger

_log = get_logger(__name__)


def _primary_parts(footprint: dict[str, float], top_n: int = 2) -> set[str]:
    if not footprint:
        return set()
    ranked = sorted(footprint.items(), key=lambda kv: -kv[1])
    return {p for p, _ in ranked[:top_n] if p}


def _session_footprint(sess: dict) -> dict[str, float]:
    if isinstance(sess.get("_muscle_footprint"), dict):
        return {str(k): float(v) for k, v in sess["_muscle_footprint"].items()}
    out: dict[str, float] = {}
    for ex in sess.get("exercises") or []:
        # Without stored parts, approximate from name is skipped — balancer
        # relies on fill_and_stamp attaching _muscle_footprint.
        pass
    return out


def balance_week_sessions(
    sessions: list[dict],
    *,
    db: Session | None = None,
    week_ctx: dict | None = None,
    sore_parts: set[str] | None = None,
) -> tuple[list[dict], dict]:
    """Reorder/refill strength days that stack the same primary muscle groups.

    Never changes pins (day/type/tss/duration). Only swaps strength exercise
    content when day N and N+1 overload the same primary parts.
    """
    sessions = [copy.deepcopy(s) for s in sessions if isinstance(s, dict)]
    sore_parts = set(sore_parts or ())
    by_day: dict[int, dict] = {}
    for s in sessions:
        try:
            d = int(s.get("day_offset", -1))
        except (TypeError, ValueError):
            continue
        if 0 <= d <= 6:
            by_day[d] = s

    swaps = 0
    for d in range(6):
        a = by_day.get(d)
        b = by_day.get(d + 1)
        if not a or not b:
            continue
        if (a.get("workout_type") or "") != "strength" and (b.get("workout_type") or "") != "strength":
            continue
        fa = _primary_parts(_session_footprint(a))
        fb = _primary_parts(_session_footprint(b))
        overlap = (fa & fb) | (fa & sore_parts) | (fb & sore_parts)
        if not overlap:
            continue
        # Refill the later strength day avoiding overlapped parts
        target = b if (b.get("workout_type") or "") == "strength" else a
        avoid = set(overlap)
        pins = {
            "day_offset": target["day_offset"],
            "workout_type": target.get("workout_type"),
            "target_tss": target.get("target_tss"),
            "duration_minutes": target.get("duration_minutes"),
            "subtype": target.get("subtype"),
            "locked": target.get("locked"),
        }
        try:
            stamped = fill_and_stamp(
                pins, db=db, week_ctx=week_ctx, avoid_parts=avoid,
            )
            # Preserve slot_id / pending flags
            for k in ("slot_id", "locked", "pending", "structure_hints"):
                if k in target:
                    stamped[k] = target[k]
            stamped["pending"] = False
            by_day[int(target["day_offset"])] = stamped
            swaps += 1
        except Exception:
            _log.warning("week balance refill failed day=%s", target.get("day_offset"), exc_info=True)

    out = sorted(by_day.values(), key=lambda s: int(s.get("day_offset", 0)))
    # Keep any non-day sessions (shouldn't happen)
    for s in sessions:
        d = s.get("day_offset")
        try:
            di = int(d)
        except (TypeError, ValueError):
            out.append(s)
            continue
        if di not in by_day:
            out.append(s)

    summary = build_muscle_summary(out)
    summary["swaps"] = swaps
    return out, summary


def build_muscle_summary(sessions: list[dict]) -> dict[str, Any]:
    per_day: list[dict] = []
    week: dict[str, float] = {}
    for s in sessions:
        if (s.get("workout_type") or "") == "rest":
            continue
        fp = _session_footprint(s)
        for k, v in fp.items():
            week[k] = week.get(k, 0.0) + v
        top = sorted(fp.items(), key=lambda kv: -kv[1])[:3]
        per_day.append({
            "day_offset": s.get("day_offset"),
            "workout_type": s.get("workout_type"),
            "subtype": s.get("subtype"),
            "top_parts": [{"part": p, "load": round(v, 2)} for p, v in top],
        })
    heatmap = [
        {"part": p, "load": round(v, 2)}
        for p, v in sorted(week.items(), key=lambda kv: -kv[1])[:8]
    ]
    return {"per_day": per_day, "week_heatmap": heatmap}


def sore_parts_for_user(db: Session | None, user_id, today) -> set[str]:
    """Soft input from muscle_load_acwr high-risk / elevated groups."""
    if db is None or user_id is None or today is None:
        return set()
    try:
        from backend.services.muscle_load_acwr import compute as compute_ml

        payload = compute_ml(user_id, today)
        out: set[str] = set()
        for name, g in (payload.get("groups") or {}).items():
            cls = str((g or {}).get("classification") or "").lower()
            if cls in ("high", "high_risk", "elevated", "overreaching"):
                out.add(str(name))
        return out
    except Exception:
        _log.debug("sore_parts lookup skipped", exc_info=True)
        return set()
