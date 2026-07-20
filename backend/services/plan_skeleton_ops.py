"""Deterministic structure ops on a draft week (no LLM).

Precedence: safety (ACWR ceiling, past days) > user edits > prefs > presets > LLM.
User edits → WARNINGS (overridable). Safety → BLOCKS (not overridable).
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

from backend.services.plan_suggestions import (
    _HARD_INTENT_KEYWORDS,
    _MAX_CONSECUTIVE_TRAINING_DAYS,
    _is_hard_intent,
)
from backend.services.plan_skeleton import _clamp_tss, _structure_hints_for

# Per-slot TSS clamp when redistributing (absolute).
_PER_SLOT_TSS_CAP = 180
_PER_SLOT_TSS_FLOOR = 15

_ADD_KINDS = {
    "light_strength": {
        "workout_type": "strength",
        "subtype": "strength_lower",
        "duration_minutes": 30,
        "target_tss": 25,
        "needs_content": True,
    },
    "stretch": {
        "workout_type": "stretch",
        "subtype": "stretch",
        "duration_minutes": 10,
        "target_tss": 0,
        "needs_content": False,  # template instantly, never LLM
    },
    "easy_run": {
        "workout_type": "run",
        "subtype": "easy_run",
        "duration_minutes": 30,
        "target_tss": 30,
        "needs_content": True,
    },
}


def ensure_slot_ids(sessions: list[dict]) -> list[dict]:
    """Stamp stable slot_id on every session (mutates + returns)."""
    for s in sessions:
        if not isinstance(s, dict):
            continue
        if not s.get("slot_id"):
            s["slot_id"] = str(uuid.uuid4())
    return sessions


def _round_tss_pin(v: float) -> int:
    return int(round(float(v or 0) / 5.0) * 5)


def _is_training(s: dict) -> bool:
    return (s.get("workout_type") or "").lower() not in ("rest", "", "none")


def _is_hard(s: dict) -> bool:
    """Hard = tempo/interval subtype or hard-intent keywords / high TSS run."""
    if not _is_training(s):
        return False
    sub = (s.get("subtype") or "").lower()
    if sub in ("tempo", "interval", "speed", "vo2", "threshold"):
        return True
    # Adapt validation helper shape
    fake = {
        "intent": s.get("intent") or "",
        "notes": s.get("notes") or "",
        "workout_type": s.get("workout_type"),
        "target_tss": s.get("target_tss"),
    }
    try:
        return bool(_is_hard_intent(str(fake.get("intent") or "")))
    except Exception:
        text = f"{fake['intent']} {fake['notes']}".lower()
        return any(kw in text for kw in _HARD_INTENT_KEYWORDS)


def _is_long(s: dict) -> bool:
    return (s.get("subtype") or "").lower() == "long_run"


def _by_day(sessions: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for s in sessions:
        if not isinstance(s, dict):
            continue
        d = s.get("day_offset")
        if d is None:
            continue
        out[int(d)] = s
    return out


def _find(sessions: list[dict], slot_id: str | None = None, day: int | None = None) -> dict | None:
    for s in sessions:
        if not isinstance(s, dict):
            continue
        if slot_id and s.get("slot_id") == slot_id:
            return s
        if day is not None and int(s.get("day_offset", -1)) == int(day):
            return s
    return None


def _consecutive_training_ok(by_day: dict[int, dict], placing_day: int, placing_is_train: bool) -> bool:
    if not placing_is_train:
        return True
    occupied: dict[int, str] = {}
    for d, s in by_day.items():
        occupied[d] = "train" if _is_training(s) else "rest"
    occupied[placing_day] = "train"
    streak_before = 0
    for d in range(placing_day - 1, -1, -1):
        if occupied.get(d) != "train":
            break
        streak_before += 1
    streak_after = 0
    for d in range(placing_day + 1, 7):
        if occupied.get(d) != "train":
            break
        streak_after += 1
    return streak_before + 1 + streak_after <= _MAX_CONSECUTIVE_TRAINING_DAYS


def _hard_long_warnings(by_day: dict[int, dict], day: int, sess: dict) -> list[str]:
    warnings: list[str] = []
    if not _is_hard(sess):
        # Moving/placing a hard session is what we care about; also check neighbors
        # when a long sits adjacent to an existing hard
        pass
    # Hard day before long run
    nxt = by_day.get(day + 1)
    if _is_hard(sess) and nxt and _is_long(nxt):
        warnings.append("Hard session the day before the long run")
    # Hard day after long run
    prev = by_day.get(day - 1)
    if _is_hard(sess) and prev and _is_long(prev):
        warnings.append("Hard session the day after the long run")
    # If placing next to hard when this is long
    if _is_long(sess):
        if prev and _is_hard(prev):
            warnings.append("Hard session the day before the long run")
        if nxt and _is_hard(nxt):
            warnings.append("Hard session the day after the long run")
    return warnings


def preview_move_target(
    sessions: list[dict],
    *,
    slot_id: str,
    to_day: int,
    preferred_rest_days: list[int] | None = None,
    today_offset: int | None = None,
) -> dict[str, Any]:
    """Drop-state preview for UI (ok / warn / blocked) without mutating."""
    ensure_slot_ids(sessions)
    sess = _find(sessions, slot_id=slot_id)
    if sess is None:
        return {"state": "blocked", "reason": "slot not found", "blocked": True}
    if today_offset is not None and to_day < today_offset:
        return {"state": "blocked", "reason": "past day", "blocked": True}
    if int(sess.get("day_offset", -1)) == int(to_day):
        return {"state": "ok", "reason": "same day", "blocked": False, "warnings": []}

    rest = set(int(d) for d in (preferred_rest_days or []) if 0 <= int(d) <= 6)
    by_day = _by_day(sessions)
    warnings: list[str] = []
    occupant = by_day.get(int(to_day))
    swap_with = None
    if occupant and occupant.get("slot_id") != slot_id and _is_training(occupant):
        swap_with = occupant.get("intent") or occupant.get("workout_type") or "session"
        # Simulate swap for consecutive check
        sim = copy.deepcopy(by_day)
        from_d = int(sess["day_offset"])
        sim[int(to_day)] = {**sess, "day_offset": int(to_day)}
        sim[from_d] = {**occupant, "day_offset": from_d}
    else:
        sim = {d: s for d, s in by_day.items() if d != int(sess["day_offset"])}
        sim[int(to_day)] = {**sess, "day_offset": int(to_day)}

    if int(to_day) in rest:
        warnings.append("Target is a preferred rest day")
    warnings.extend(_hard_long_warnings(sim, int(to_day), sess))
    if _is_training(sess) and not _consecutive_training_ok(sim, int(to_day), True):
        warnings.append(f"Would create >{_MAX_CONSECUTIVE_TRAINING_DAYS} consecutive training days")

    state = "warn" if warnings else "ok"
    return {
        "state": state,
        "blocked": False,
        "warnings": warnings,
        "swap_with": swap_with,
        "reason": "; ".join(warnings) if warnings else ("swap with " + str(swap_with) if swap_with else "ok"),
    }


def move(
    sessions: list[dict],
    *,
    slot_id: str,
    to_day: int,
    preferred_rest_days: list[int] | None = None,
    today_offset: int | None = None,
    confirm_warnings: bool = False,
) -> dict[str, Any]:
    """Move slot to to_day; content travels. Swap if target occupied."""
    ensure_slot_ids(sessions)
    sessions = copy.deepcopy(sessions)
    sess = _find(sessions, slot_id=slot_id)
    if sess is None:
        return {"slots": sessions, "warnings": [], "blocked": True, "block_reason": "slot not found", "affected_slot_ids": []}

    preview = preview_move_target(
        sessions, slot_id=slot_id, to_day=to_day,
        preferred_rest_days=preferred_rest_days, today_offset=today_offset,
    )
    if preview.get("blocked"):
        return {
            "slots": sessions,
            "warnings": [],
            "blocked": True,
            "block_reason": preview.get("reason") or "blocked",
            "affected_slot_ids": [],
        }
    warnings = list(preview.get("warnings") or [])
    if warnings and not confirm_warnings:
        return {
            "slots": sessions,
            "warnings": warnings,
            "blocked": False,
            "needs_confirm": True,
            "affected_slot_ids": [],
            "swap_with": preview.get("swap_with"),
        }

    from_day = int(sess["day_offset"])
    to_day = int(to_day)
    if from_day == to_day:
        return {"slots": sessions, "warnings": [], "blocked": False, "affected_slot_ids": []}

    by_day = _by_day(sessions)
    other = by_day.get(to_day)
    if other and other.get("slot_id") != slot_id:
        # Swap day pins only — content travels with each slot_id
        other["day_offset"] = from_day
        sess["day_offset"] = to_day
    else:
        sess["day_offset"] = to_day

    return {
        "slots": sessions,
        "warnings": warnings,
        "blocked": False,
        "affected_slot_ids": [],  # content unchanged
        "moved_cache_rewrite": [
            {"slot_id": sess["slot_id"], "from_day": from_day, "to_day": to_day},
        ],
    }


def swap(
    sessions: list[dict],
    *,
    day_a: int,
    day_b: int,
    preferred_rest_days: list[int] | None = None,
    today_offset: int | None = None,
    confirm_warnings: bool = False,
) -> dict[str, Any]:
    ensure_slot_ids(sessions)
    sessions = copy.deepcopy(sessions)
    a = _find(sessions, day=day_a)
    b = _find(sessions, day=day_b)
    if a is None or b is None:
        return {"slots": sessions, "warnings": [], "blocked": True, "block_reason": "day empty", "affected_slot_ids": []}
    # Reuse move toward day_b
    return move(
        sessions,
        slot_id=a["slot_id"],
        to_day=day_b,
        preferred_rest_days=preferred_rest_days,
        today_offset=today_offset,
        confirm_warnings=confirm_warnings,
    )


def remove(
    sessions: list[dict],
    *,
    slot_id: str,
    mode: str = "drop",
    acwr_ceiling: float | None = None,
    weekly_target: float | None = None,
) -> dict[str, Any]:
    """Remove a slot. mode=drop|redistribute."""
    ensure_slot_ids(sessions)
    sessions = copy.deepcopy(sessions)
    sess = _find(sessions, slot_id=slot_id)
    if sess is None:
        return {"slots": sessions, "warnings": [], "blocked": True, "block_reason": "slot not found", "affected_slot_ids": []}

    dropped_tss = float(sess.get("target_tss") or 0)
    day = int(sess["day_offset"])

    # Replace with rest
    rest_slot = {
        "slot_id": str(uuid.uuid4()),
        "day_offset": day,
        "workout_type": "rest",
        "subtype": "rest",
        "target_tss": 0,
        "duration_minutes": 0,
        "intent": "Rest",
        "notes": None,
        "blocks": None,
        "exercises": None,
        "source": "template",
        "structure_hints": {},
        "locked": False,
    }
    # Remove original
    sessions = [s for s in sessions if s.get("slot_id") != slot_id]
    sessions.append(rest_slot)

    redistribute_meta = None
    affected: list[str] = []

    if mode == "redistribute" and dropped_tss > 0:
        train = [
            s for s in sessions
            if _is_training(s) and not _is_long(s) and not s.get("locked")
        ]
        if not train:
            redistribute_meta = {
                "replaced_tss": 0.0,
                "dropped_tss": dropped_tss,
                "per_slot_deltas": {},
            }
        else:
            ceiling = float(acwr_ceiling) if acwr_ceiling is not None else None
            current_sum = sum(float(s.get("target_tss") or 0) for s in sessions if _is_training(s))
            room = None
            if ceiling is not None:
                room = max(0.0, ceiling - current_sum)
            target_add = dropped_tss if room is None else min(dropped_tss, room)
            weights = [max(1.0, float(s.get("target_tss") or 1)) for s in train]
            wsum = sum(weights) or 1.0
            deltas: dict[str, float] = {}
            placed = 0.0
            for i, s in enumerate(train):
                if i == len(train) - 1:
                    add = target_add - placed
                else:
                    add = target_add * (weights[i] / wsum)
                    placed += add
                old = float(s.get("target_tss") or 0)
                new = min(_PER_SLOT_TSS_CAP, max(_PER_SLOT_TSS_FLOOR, old + add))
                # Cap by remaining room
                if ceiling is not None:
                    # rough: don't exceed cap individually beyond room share
                    new = min(new, old + max(0.0, add))
                new_pin = _round_tss_pin(new)
                old_pin = _round_tss_pin(old)
                s["target_tss"] = new_pin
                # Duration nudge proportional
                if old > 0 and s.get("duration_minutes"):
                    s["duration_minutes"] = int(round(float(s["duration_minutes"]) * (new_pin / old) / 5) * 5)
                delta = new_pin - old_pin
                deltas[s["slot_id"]] = delta
                if abs(delta) >= 5:  # rounded-to-5 pin moved
                    affected.append(s["slot_id"])
            replaced = sum(max(0, d) for d in deltas.values())
            redistribute_meta = {
                "replaced_tss": round(replaced, 1),
                "dropped_tss": round(max(0.0, dropped_tss - replaced), 1),
                "per_slot_deltas": deltas,
            }

    return {
        "slots": sessions,
        "warnings": [],
        "blocked": False,
        "affected_slot_ids": affected,
        "redistribute": redistribute_meta,
        "removed_slot_id": slot_id,
    }


def add(
    sessions: list[dict],
    *,
    day: int,
    kind: str,
    preferred_rest_days: list[int] | None = None,
    today_offset: int | None = None,
    acwr_ceiling: float | None = None,
    custom: dict | None = None,
    confirm_warnings: bool = False,
) -> dict[str, Any]:
    """Add a session on day. Rest-day additions warn; ACWR / past block."""
    ensure_slot_ids(sessions)
    sessions = copy.deepcopy(sessions)
    day = int(day)

    if today_offset is not None and day < today_offset:
        return {
            "slots": sessions,
            "warnings": [],
            "blocked": True,
            "block_reason": "past day",
            "affected_slot_ids": [],
        }

    if kind == "custom":
        custom = custom or {}
        wt = (custom.get("workout_type") or "run").lower()
        if wt not in ("run", "strength", "plyo", "stretch"):
            return {
                "slots": sessions,
                "warnings": [],
                "blocked": True,
                "block_reason": "invalid workout_type",
                "affected_slot_ids": [],
            }
        spec = {
            "workout_type": wt,
            "subtype": custom.get("subtype") or wt,
            "duration_minutes": int(custom.get("duration_minutes") or 30),
            "target_tss": _clamp_tss(float(custom.get("target_tss") or 0)),
            "needs_content": wt != "stretch",
        }
    else:
        if kind not in _ADD_KINDS:
            return {
                "slots": sessions,
                "warnings": [],
                "blocked": True,
                "block_reason": f"unknown kind {kind}",
                "affected_slot_ids": [],
            }
        spec = dict(_ADD_KINDS[kind])

    # ACWR block
    current_sum = sum(float(s.get("target_tss") or 0) for s in sessions if _is_training(s))
    add_tss = float(spec["target_tss"])
    if acwr_ceiling is not None and current_sum + add_tss > float(acwr_ceiling) + 1e-6:
        return {
            "slots": sessions,
            "warnings": [],
            "blocked": True,
            "block_reason": "add would cross ACWR ceiling",
            "affected_slot_ids": [],
        }

    rest = set(int(d) for d in (preferred_rest_days or []) if 0 <= int(d) <= 6)
    warnings: list[str] = []
    if day in rest:
        warnings.append("Adding on a preferred rest day")

    by_day = _by_day(sessions)
    existing = by_day.get(day)
    # If day has a rest, replace it; if training, block (use swap/move)
    if existing and _is_training(existing):
        return {
            "slots": sessions,
            "warnings": [],
            "blocked": True,
            "block_reason": "day already has a training session — move or swap first",
            "affected_slot_ids": [],
        }

    new_sess = {
        "slot_id": str(uuid.uuid4()),
        "day_offset": day,
        "workout_type": spec["workout_type"],
        "subtype": spec["subtype"],
        "target_tss": int(spec["target_tss"]),
        "duration_minutes": int(spec["duration_minutes"]),
        "intent": "",
        "notes": None,
        "blocks": None,
        "exercises": None,
        "source": "template" if not spec["needs_content"] else "pending",
        "structure_hints": _structure_hints_for(spec["subtype"]),
        "locked": False,
        "pending": bool(spec["needs_content"]),
    }

    # Stretch: materialize template content immediately
    if kind == "stretch" or (kind == "custom" and spec["workout_type"] == "stretch"):
        from backend.services.plan_slot import template_content_for_slot, stamp_session
        content = template_content_for_slot(new_sess)
        stamped = stamp_session(new_sess, content)
        stamped["slot_id"] = new_sess["slot_id"]
        stamped["pending"] = False
        new_sess = stamped

    sim = {d: s for d, s in by_day.items() if d != day}
    sim[day] = new_sess
    warnings.extend(_hard_long_warnings(sim, day, new_sess))
    if not _consecutive_training_ok(sim, day, _is_training(new_sess)):
        warnings.append(f"Would create >{_MAX_CONSECUTIVE_TRAINING_DAYS} consecutive training days")

    if warnings and not confirm_warnings:
        return {
            "slots": sessions,
            "warnings": warnings,
            "blocked": False,
            "needs_confirm": True,
            "affected_slot_ids": [],
            "proposed": new_sess,
        }

    # Replace rest on that day or append
    sessions = [s for s in sessions if int(s.get("day_offset", -1)) != day]
    sessions.append(new_sess)
    affected = [new_sess["slot_id"]] if new_sess.get("pending") else []

    return {
        "slots": sessions,
        "warnings": warnings,
        "blocked": False,
        "affected_slot_ids": affected,
        "added_slot_id": new_sess["slot_id"],
    }


def sync_slots_from_sessions(sessions: list[dict]) -> list[dict]:
    """Derive skeleton-shaped slots list from sessions (for payload.slots)."""
    slots = []
    for s in sorted(sessions, key=lambda x: int(x.get("day_offset", 0))):
        slots.append({
            "day_offset": s["day_offset"],
            "workout_type": s.get("workout_type"),
            "target_tss": s.get("target_tss"),
            "duration_minutes": s.get("duration_minutes"),
            "subtype": s.get("subtype"),
            "structure_hints": s.get("structure_hints") or {},
            "locked": bool(s.get("locked")),
            "slot_id": s.get("slot_id"),
        })
    return slots
