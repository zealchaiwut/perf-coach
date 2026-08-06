"""Homework ladder — weekly_focus + required_exercises pre-placement.

Standing homework (required_exercises) has no expiry. Weekly focus expires
after 7 days from ``expires_on`` (ISO date); replan keeps the original expiry.

Follows session **type**, not date. When multiple matching sessions exist,
homework consolidates onto the first matching session in week order.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from backend.services.session_pins import ensure_exercise_pin_fields, exercise_spend


HOMEWORK_WEEK = "homework_week"
HOMEWORK_STANDING = "homework_standing"


def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def normalize_homework_item(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("exercise_name") or raw.get("name") or "").strip()
    eid = raw.get("exercise_id")
    if not name and not eid:
        return None
    types = [str(t).strip().lower() for t in _as_list(raw.get("session_types")) if t]
    if not types:
        types = ["strength"]
    item = {
        "exercise_id": str(eid) if eid else None,
        "exercise_name": name,
        "session_types": types,
        "sets": raw.get("sets") if raw.get("sets") is not None else 3,
        "reps": raw.get("reps") if raw.get("reps") is not None else "10",
        "load": raw.get("load") if raw.get("load") is not None else "moderate",
        "block": raw.get("block") or "Accessories",
        "spend_tss": raw.get("spend_tss"),
        "spend_min": raw.get("spend_min"),
    }
    if raw.get("expires_on"):
        item["expires_on"] = str(raw["expires_on"])[:10]
    return item


def active_homework(
    prefs_payload: dict | None,
    *,
    as_of: date | None = None,
) -> list[dict]:
    """Return active homework rows tagged with source (week vs standing)."""
    today = as_of or date.today()
    payload = prefs_payload or {}
    out: list[dict] = []

    for raw in _as_list(payload.get("required_exercises")):
        item = normalize_homework_item(raw)
        if not item:
            continue
        item["source"] = HOMEWORK_STANDING
        out.append(item)

    for raw in _as_list(payload.get("weekly_focus")):
        item = normalize_homework_item(raw)
        if not item:
            continue
        exp = item.get("expires_on")
        if exp:
            try:
                if date.fromisoformat(exp) < today:
                    continue
            except ValueError:
                continue
        item["source"] = HOMEWORK_WEEK
        if exp:
            try:
                item["homework_days_left"] = max(0, (date.fromisoformat(exp) - today).days)
            except ValueError:
                pass
        out.append(item)
    return out


def matches_session_type(item: dict, workout_type: str | None) -> bool:
    wt = str(workout_type or "").strip().lower()
    if not wt:
        return False
    types = [str(t).lower() for t in _as_list(item.get("session_types"))]
    if wt in types:
        return True
    # strength homework also fits full/upper/lower strength subtypes stored as type
    if wt == "plyo" and "plyo" in types:
        return True
    if wt == "strength" and any(t in ("strength", "upper", "lower", "full") for t in types):
        return True
    return False


def homework_to_exercise_row(item: dict, *, pool: list[dict] | None = None) -> dict:
    """Build a pinned exercise row from a homework pref item."""
    name = item.get("exercise_name") or ""
    if not name and pool and item.get("exercise_id"):
        for e in pool:
            if str(e.get("id")) == str(item["exercise_id"]):
                name = e.get("name") or ""
                if item.get("sets") is None and e.get("default_sets") is not None:
                    item = {**item, "sets": e.get("default_sets")}
                if not item.get("reps") and e.get("default_reps"):
                    item = {**item, "reps": e.get("default_reps")}
                if not item.get("load") and e.get("default_load"):
                    item = {**item, "load": e.get("default_load")}
                break
    row = {
        "block": item.get("block") or "Accessories",
        "name": name or "Homework",
        "sets": item.get("sets") if item.get("sets") is not None else 3,
        "reps": item.get("reps") if item.get("reps") is not None else "10",
        "load": item.get("load") if item.get("load") is not None else "moderate",
        "pinned": True,
        "source": item.get("source") or HOMEWORK_STANDING,
        "state": "done",
    }
    if item.get("exercise_id"):
        row["exercise_id"] = item["exercise_id"]
    if item.get("homework_days_left") is not None:
        row["homework_days_left"] = item["homework_days_left"]
    if item.get("expires_on"):
        row["expires_on"] = item["expires_on"]
    if item.get("spend_tss") is not None:
        row["spend_tss"] = float(item["spend_tss"])
    if item.get("spend_min") is not None:
        row["spend_min"] = float(item["spend_min"])
    else:
        st, sm = exercise_spend(row)
        row.setdefault("spend_tss", st)
        row.setdefault("spend_min", sm)
    return ensure_exercise_pin_fields(row)


def pre_place_for_slot(
    prefs_payload: dict | None,
    workout_type: str | None,
    *,
    as_of: date | None = None,
    pool: list[dict] | None = None,
    existing: list[dict] | None = None,
) -> list[dict]:
    """Homework rows that should land in this slot (deduped by name)."""
    items = [
        i for i in active_homework(prefs_payload, as_of=as_of)
        if matches_session_type(i, workout_type)
    ]
    used = {
        str(e.get("name") or "").strip().lower()
        for e in (existing or [])
        if isinstance(e, dict) and e.get("name")
    }
    out: list[dict] = []
    for item in items:
        row = homework_to_exercise_row(item, pool=pool)
        key = str(row.get("name") or "").strip().lower()
        if key and key in used:
            continue
        out.append(row)
        if key:
            used.add(key)
    return out


def week_expiry(*, today: date | None = None, keep: str | None = None) -> str:
    """ISO date for weekly_focus expiry. Keep original on replan when still valid."""
    today = today or date.today()
    if keep:
        try:
            exp = date.fromisoformat(str(keep)[:10])
            if exp >= today:
                return exp.isoformat()
        except ValueError:
            pass
    return (today + timedelta(days=7)).isoformat()


def append_homework_item(
    payload: dict,
    field: str,
    item: dict,
    *,
    today: date | None = None,
) -> dict:
    """Return a new prefs payload with ``item`` appended to weekly_focus or required_exercises."""
    out = deepcopy(payload or {})
    if field not in ("weekly_focus", "required_exercises"):
        raise ValueError(f"homework field must be weekly_focus or required_exercises, got {field}")
    norm = normalize_homework_item(item)
    if not norm:
        raise ValueError("invalid homework item")
    if field == "weekly_focus":
        norm["expires_on"] = week_expiry(today=today, keep=norm.get("expires_on"))
        # Standing list must not carry expires_on
    else:
        norm.pop("expires_on", None)
    cur = list(_as_list(out.get(field)))
    # Replace same exercise_id / name if already present
    key_id = norm.get("exercise_id")
    key_name = (norm.get("exercise_name") or "").strip().lower()
    filtered = []
    for raw in cur:
        n = normalize_homework_item(raw)
        if not n:
            continue
        if key_id and n.get("exercise_id") == key_id:
            continue
        if key_name and (n.get("exercise_name") or "").strip().lower() == key_name:
            continue
        filtered.append(raw if isinstance(raw, dict) else n)
    filtered.append(norm)
    out[field] = filtered
    return out


def pick_exercise_for_muscle(
    pool: list[dict],
    muscle_group: str,
    *,
    avoid_names: set[str] | None = None,
) -> dict | None:
    """Deterministic: highest body_parts ratio for ``muscle_group``, then name."""
    group = str(muscle_group or "").strip().lower()
    if not group:
        return None
    avoid = {n.strip().lower() for n in (avoid_names or set())}
    scored: list[tuple[float, str, dict]] = []
    for e in pool or []:
        name = str(e.get("name") or "").strip()
        if not name or name.lower() in avoid:
            continue
        best = 0.0
        for p in _as_list(e.get("body_parts")):
            if isinstance(p, dict):
                part = str(p.get("part") or "").strip().lower()
                ratio = float(p.get("ratio") or 0)
            else:
                part = str(p).strip().lower()
                ratio = 1.0
            if part == group or group in part or part in group:
                best = max(best, ratio)
        if best > 0:
            scored.append((best, name.lower(), e))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored[0][2]
