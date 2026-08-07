"""Training preference field catalog — single source of truth for bounds & stages."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

PREF_FIELDS: dict[str, dict[str, Any]] = {
    "rest_days": {
        "type": "list[weekday]",
        "reads": ["skeleton"],
        "default": [],
    },
    "strength_emphasis": {
        "type": "enum:less|same|more",
        "reads": ["content"],
        "default": "same",
        # Training-stress-relevant in both directions (more strength work adds
        # load; less strength work removes a structural stimulus) — use the
        # same 3-week persistence bar as the other load_adding fields rather
        # than the 2-week default, whichever direction it moves.
        "persist_weeks": 3,
        "load_adding": True,
    },
    "plyo_mode": {
        "type": "enum:standalone|superset|off",
        "reads": ["skeleton", "content"],
        "default": "off",
    },
    "plyo_sessions_per_week": {
        "type": "int",
        "min": 0,
        "max": 2,
        "step": 1,
        "persist_weeks": 3,  # load_adding → 3 consecutive weeks before proposal
        "load_adding": True,
        "reads": ["skeleton"],
        "default": 0,
    },
    "long_run.mp_segment_min": {
        "type": "int",
        "min": 0,
        "max": 30,
        "step": 10,
        "persist_weeks": 3,
        "load_adding": True,
        "reads": ["content"],
        "default": 0,
    },
    # Daily mobility target, in minutes. Lean-program D5 moved stretch OUT of
    # habits and into the plan: `plan_extras` attaches it to every day of the
    # week from this value. zone2_weekly_min still lives on Habits.
    #
    # Migration note: the value used to be stored as the "Daily stretch" habit's
    # target_value. `prefs_for_assemble_facts` still falls back to that habit
    # when this pref is unset, so nobody loses their target — but the habit is
    # no longer created for new athletes.
    "stretch_daily_min": {
        "type": "int",
        "min": 0,
        "max": 60,
        "step": 5,
        "reads": ["skeleton"],
        "default": 0,
    },
    "notes": {
        "type": "str",
        "max_len": 200,
        "reads": ["content"],
        "default": "",
    },
    # High-volume dishes the athlete already cooks. The consult suggests FROM
    # this list instead of inventing a meal plan — a recipe database is out of
    # scope; this is a list of dish names and nothing more.
    "volume_plays": {
        "type": "list[str]",
        "max_items": 10,
        "max_len": 80,
        "reads": ["content"],
        "default": [],
    },
    # Homework ladder (session modal Pass 5). Standing required_exercises never
    # expire; weekly_focus items carry expires_on (ISO date, typically +7d).
    # Shape per item: {exercise_id?, exercise_name, session_types, sets, reps,
    # load, expires_on?, block?}. Pre-placed as pinned rows on matching
    # session types — see session_homework.py.
    "weekly_focus": {
        "type": "list[homework]",
        "max_items": 8,
        "persist_weeks": 2,
        "reads": ["content"],
        "default": [],
    },
    "required_exercises": {
        "type": "list[homework]",
        "max_items": 12,
        "persist_weeks": 2,
        "reads": ["content"],
        "default": [],
    },
}

_ENUM_MAP = {
    "strength_emphasis": ("less", "same", "more"),
    "plyo_mode": ("standalone", "superset", "off"),
}


def default_payload() -> dict:
    """Fresh prefs payload with catalog defaults (nested for dotted keys)."""
    out: dict[str, Any] = {}
    for key, meta in PREF_FIELDS.items():
        set_field(out, key, deepcopy(meta.get("default")))
    return out


def get_field(payload: dict, field: str) -> Any:
    if "." not in field:
        return payload.get(field)
    cur: Any = payload
    for part in field.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def set_field(payload: dict, field: str, value: Any) -> None:
    if "." not in field:
        payload[field] = value
        return
    parts = field.split(".")
    cur = payload
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def field_meta(field: str) -> dict[str, Any] | None:
    return PREF_FIELDS.get(field)


def persist_weeks_for(field: str) -> int:
    meta = PREF_FIELDS.get(field) or {}
    if meta.get("load_adding"):
        return int(meta.get("persist_weeks") or 3)
    return int(meta.get("persist_weeks") or 2)


def validate_payload(
    payload: dict,
    *,
    enforce_step_from: dict | None = None,
) -> dict[str, str]:
    """Return field → error. Empty dict means valid.

    enforce_step_from: when set (proposal accept), each changed field must move
    by at most one catalog step from that baseline. User UI/import skip this.
    """
    errors: dict[str, str] = {}
    if not isinstance(payload, dict):
        return {"": "payload must be an object"}

    for field, meta in PREF_FIELDS.items():
        val = get_field(payload, field)
        if val is None and meta.get("default") is not None:
            continue  # missing → filled by normalize
        err = _validate_one(field, meta, val)
        if err:
            errors[field] = err
            continue
        if enforce_step_from is not None and field in (
            "plyo_sessions_per_week",
            "long_run.mp_segment_min",
        ):
            step = meta.get("step")
            if step is not None and val is not None:
                prev = get_field(enforce_step_from, field)
                if prev is None:
                    prev = meta.get("default", 0)
                try:
                    delta = abs(int(val) - int(prev))
                except (TypeError, ValueError):
                    continue
                if delta not in (0, int(step)):
                    errors[field] = (
                        f"proposal step must be ±{step} from current "
                        f"({prev} → {val})"
                    )

    # Reject unknown top-level keys (except nested containers we own).
    # stretch/zone2 were migrated to Habits — tolerate legacy payloads.
    _migrated = {"zone2_weekly_min"}
    known_top = {k.split(".")[0] for k in PREF_FIELDS} | _migrated
    for k in payload.keys():
        if k not in known_top:
            errors[k] = "unknown preference field"

    return errors


def strip_migrated_habit_fields(payload: dict) -> dict:
    """Drop keys that live on Habits rather than in this catalog.

    Only zone2_weekly_min now — stretch_daily_min moved INTO the catalog when
    the lean program moved stretch out of habits and into the plan (D5).
    """
    out = dict(payload or {})
    out.pop("zone2_weekly_min", None)
    return out


def _validate_one(field: str, meta: dict, val: Any) -> str | None:
    if val is None:
        return None
    t = meta.get("type") or ""
    if t == "list[weekday]":
        if not isinstance(val, list):
            return "must be a list of weekdays 0-6"
        for d in val:
            try:
                i = int(d)
            except (TypeError, ValueError):
                return "weekdays must be integers 0-6"
            if i < 0 or i > 6:
                return "weekdays must be integers 0-6"
        return None
    if t.startswith("enum:"):
        allowed = tuple(t.split(":", 1)[1].split("|"))
        if val not in allowed:
            return f"must be one of {allowed}"
        return None
    if t == "int":
        try:
            n = int(val)
        except (TypeError, ValueError):
            return "must be an integer"
        if "min" in meta and n < int(meta["min"]):
            return f"{n} < min {meta['min']}"
        if "max" in meta and n > int(meta["max"]):
            return f"{n} > max {meta['max']}"
        return None
    if t == "str":
        if not isinstance(val, str):
            return "must be a string"
        max_len = int(meta.get("max_len") or 200)
        if len(val) > max_len:
            return f"max length {max_len}"
        return None
    if t == "list[str]":
        if not isinstance(val, list):
            return "must be a list of strings"
        max_items = int(meta.get("max_items") or 10)
        if len(val) > max_items:
            return f"at most {max_items} items"
        max_len = int(meta.get("max_len") or 80)
        for item in val:
            if not isinstance(item, str):
                return "every item must be a string"
            if len(item) > max_len:
                return f"each item is at most {max_len} characters"
        return None
    if t == "list[homework]":
        if not isinstance(val, list):
            return "must be a list of homework objects"
        max_items = int(meta.get("max_items") or 8)
        if len(val) > max_items:
            return f"at most {max_items} items"
        for item in val:
            if not isinstance(item, dict):
                return "every homework item must be an object"
            name = item.get("exercise_name") or item.get("name")
            eid = item.get("exercise_id")
            if not name and not eid:
                return "homework item needs exercise_name or exercise_id"
            types = item.get("session_types")
            if types is not None and not isinstance(types, list):
                return "session_types must be a list"
            if item.get("expires_on") is not None:
                try:
                    from datetime import date as _date
                    _date.fromisoformat(str(item["expires_on"])[:10])
                except (TypeError, ValueError):
                    return "expires_on must be YYYY-MM-DD"
        return None
    return None


def normalize_payload(payload: dict | None) -> dict:
    """Fill defaults and coerce types; caller should validate first or after."""
    base = default_payload()
    if not payload:
        return base
    raw = strip_migrated_habit_fields(payload)
    out = deepcopy(base)
    for field in PREF_FIELDS:
        if get_field(raw, field) is not None:
            set_field(out, field, get_field(raw, field))
    # Coerce rest_days
    days = get_field(out, "rest_days") or []
    set_field(out, "rest_days", sorted({int(d) for d in days if 0 <= int(d) <= 6}))
    # Coerce ints
    for field, meta in PREF_FIELDS.items():
        if meta.get("type") == "int":
            v = get_field(out, field)
            try:
                set_field(out, field, int(v))
            except (TypeError, ValueError):
                set_field(out, field, int(meta.get("default") or 0))
    notes = get_field(out, "notes")
    set_field(out, "notes", str(notes or "")[:200])
    # Coerce list[str] fields: drop blanks, trim to the item cap, clip each item.
    for field, meta in PREF_FIELDS.items():
        if meta.get("type") != "list[str]":
            continue
        raw_items = get_field(out, field) or []
        if not isinstance(raw_items, list):
            raw_items = []
        item_len = int(meta.get("max_len") or 80)
        max_items = int(meta.get("max_items") or 10)
        cleaned = [
            str(item).strip()[:item_len]
            for item in raw_items
            if str(item).strip()
        ]
        set_field(out, field, cleaned[:max_items])
    # Coerce list[homework]: keep dict items that normalize, drop junk.
    for field, meta in PREF_FIELDS.items():
        if meta.get("type") != "list[homework]":
            continue
        raw_items = get_field(out, field) or []
        if not isinstance(raw_items, list):
            raw_items = []
        max_items = int(meta.get("max_items") or 8)
        cleaned_hw = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("exercise_name") or item.get("name") or "").strip()
            eid = item.get("exercise_id")
            if not name and not eid:
                continue
            row = dict(item)
            if name and not row.get("exercise_name"):
                row["exercise_name"] = name
            if row.get("session_types") is None:
                row["session_types"] = ["strength"]
            cleaned_hw.append(row)
        set_field(out, field, cleaned_hw[:max_items])
    return out


def apply_step(payload: dict, field: str, step: int) -> dict | None:
    """Return a new payload with field moved by step, or None if clamped at bound / invalid."""
    meta = PREF_FIELDS.get(field)
    if not meta or meta.get("type") != "int":
        return None
    cur = get_field(payload, field)
    try:
        cur_i = int(cur if cur is not None else meta.get("default") or 0)
    except (TypeError, ValueError):
        return None
    cat_step = int(meta.get("step") or 1)
    direction = 1 if step > 0 else -1
    nxt = cur_i + direction * cat_step
    lo = int(meta.get("min") or 0)
    hi = int(meta.get("max") or 0)
    if nxt < lo or nxt > hi:
        return None
    out = deepcopy(payload)
    set_field(out, field, nxt)
    return out


def enum_options(field: str) -> tuple[str, ...] | None:
    """Ordered enum values for *field* (catalog order = step order), or None
    if the field isn't enum-typed."""
    return _ENUM_MAP.get(field)


def apply_enum_step(payload: dict, field: str, direction: int) -> dict | None:
    """Return a new payload with an enum field moved one position in
    _ENUM_MAP[field], or None if already at the extreme in that direction,
    the value isn't a recognised option, or the field isn't enum-typed.

    Mirrors apply_step()'s clamp-at-bound → None behavior, but for enum
    fields (e.g. strength_emphasis: less/same/more) instead of int fields.
    """
    meta = PREF_FIELDS.get(field)
    if not meta or not str(meta.get("type") or "").startswith("enum:"):
        return None
    options = _ENUM_MAP.get(field)
    if not options:
        return None
    cur = get_field(payload, field)
    cur_s = str(cur) if cur is not None else str(meta.get("default") or options[0])
    if cur_s not in options:
        return None
    idx = options.index(cur_s)
    step_dir = 1 if direction > 0 else -1
    nxt = idx + step_dir
    if nxt < 0 or nxt >= len(options):
        return None
    out = deepcopy(payload)
    set_field(out, field, options[nxt])
    return out


def catalog_docs_for_template() -> str:
    """Human-readable catalog block for the external-LLM copy template."""
    lines = ["Field catalog (obey these bounds):"]
    for field, meta in PREF_FIELDS.items():
        t = meta.get("type")
        bits = [f"- {field}: type={t}"]
        if "min" in meta:
            bits.append(f"min={meta['min']}")
        if "max" in meta:
            bits.append(f"max={meta['max']}")
        if "step" in meta:
            bits.append(f"step={meta['step']}")
        lines.append(" ".join(bits))
    return "\n".join(lines)
