"""Canonical session exercise JSON: parse, validate, format, resolve names."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlanExercise

MAX_EXERCISES = 20
MAX_SETS_PER_EXERCISE = 30
MAX_ERRORS = 10
KG_MIN, KG_MAX = 0, 500
REPS_INT_MIN, REPS_INT_MAX = 1, 200

_REPS_PATTERN = re.compile(r"^\d+(/(side|each))?$", re.IGNORECASE)
_DURATION_PATTERN = re.compile(
    r"^\d+(\.\d+)?(s|sec|secs|min|mins|m)(/(side|each))?$",
    re.IGNORECASE,
)

_SET_KG_REPS = frozenset({"kg", "reps"})
_SET_REPS = frozenset({"reps"})
_SET_HOLD = frozenset({"hold"})
_SET_TIME = frozenset({"time"})


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            row.append(min(row[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = row
    return prev[-1]


def _closest_library_name(name: str, names: list[str]) -> Optional[str]:
    if not names:
        return None
    key = name.strip().lower()
    best = None
    best_d = 10**9
    for n in names:
        d = _levenshtein(key, n.lower())
        if d < best_d:
            best_d = d
            best = n
    return best


def _load_library_names(session: Session) -> tuple[dict[str, PlanExercise], list[str]]:
    rows = session.query(PlanExercise).filter(PlanExercise.active.is_(True)).all()
    by_lower: dict[str, PlanExercise] = {}
    names: list[str] = []
    for r in rows:
        names.append(r.name)
        by_lower[r.name.strip().lower()] = r
    return by_lower, names


def expand_shorthand(exercise: dict[str, Any]) -> dict[str, Any]:
    """Expand exercise-level sets count + reps/kg/hold/time into a sets list."""
    sets_val = exercise.get("sets")
    if isinstance(sets_val, list):
        out = {"name": exercise.get("name"), "sets": sets_val}
        return out
    if not isinstance(sets_val, int):
        return dict(exercise)

    n = sets_val
    if n < 1:
        return {"name": exercise.get("name"), "sets": []}

    template: dict[str, Any] = {}
    if "hold" in exercise:
        template = {"hold": exercise["hold"]}
    elif "time" in exercise:
        template = {"time": exercise["time"]}
    elif "reps" in exercise:
        template = {"reps": exercise["reps"]}
        if "kg" in exercise:
            template["kg"] = exercise["kg"]
    elif "kg" in exercise:
        template = {"kg": exercise["kg"]}
    else:
        return {"name": exercise.get("name"), "sets": []}

    return {
        "name": exercise.get("name"),
        "sets": [dict(template) for _ in range(n)],
    }


def _canonicalize_set(raw: dict[str, Any]) -> dict[str, Any]:
    keys = set(raw.keys())
    if keys == _SET_KG_REPS:
        out: dict[str, Any] = {"kg": raw["kg"], "reps": raw["reps"]}
        return out
    if keys == _SET_REPS:
        return {"reps": raw["reps"]}
    if keys == _SET_HOLD:
        return {"hold": str(raw["hold"])}
    if keys == _SET_TIME:
        return {"time": str(raw["time"])}
    raise ValueError("mixed_or_unknown_set_form")


def _validate_reps_value(val: Any) -> Optional[str]:
    if isinstance(val, bool) or val is None:
        return "reps must be a number or pattern like 8/side"
    if isinstance(val, int):
        if val < REPS_INT_MIN or val > REPS_INT_MAX:
            return f"reps must be between {REPS_INT_MIN} and {REPS_INT_MAX}"
        return None
    if isinstance(val, str):
        if _REPS_PATTERN.match(val.strip()):
            base = val.split("/")[0]
            try:
                n = int(base)
            except ValueError:
                return "reps pattern is invalid"
            if n < REPS_INT_MIN or n > REPS_INT_MAX:
                return f"reps must be between {REPS_INT_MIN} and {REPS_INT_MAX}"
            return None
        return "reps must be a number or pattern like 8/side"
    return "reps must be a number or pattern like 8/side"


def _validate_duration_string(val: Any, field: str) -> Optional[str]:
    if not isinstance(val, str) or not _DURATION_PATTERN.match(val.strip()):
        return f'{field} must be a duration string like 45s or 5min'
    return None


def _validate_set_object(raw: Any) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not isinstance(raw, dict):
        return None, "each set must be an object"
    keys = set(raw.keys())
    if keys not in (_SET_KG_REPS, _SET_REPS, _SET_HOLD, _SET_TIME):
        if keys & _SET_HOLD and keys & _SET_REPS:
            return None, "a set cannot mix hold/time with reps or kg"
        if keys & _SET_TIME and len(keys) > 1:
            return None, "a set cannot mix time with other fields"
        if keys & _SET_KG_REPS and (keys - _SET_KG_REPS):
            return None, "a set cannot mix kg/reps with hold or time"
        return None, "each set must be exactly one of: kg+reps, reps, hold, or time"

    try:
        canon = _canonicalize_set(raw)
    except ValueError:
        return None, "mixed set fields are not allowed"

    if "kg" in canon:
        kg = canon["kg"]
        if not isinstance(kg, (int, float)) or isinstance(kg, bool):
            return None, "kg must be a number"
        if kg < KG_MIN or kg > KG_MAX:
            return None, f"kg must be between {KG_MIN} and {KG_MAX}"
        if float(kg) != int(kg) and abs(kg) > KG_MAX:
            pass
        canon["kg"] = int(kg) if float(kg) == int(kg) else float(kg)

    if "reps" in canon:
        err = _validate_reps_value(canon["reps"])
        if err:
            return None, err
        if isinstance(canon["reps"], str):
            canon["reps"] = canon["reps"].strip()

    if "hold" in canon:
        err = _validate_duration_string(canon["hold"], "hold")
        if err:
            return None, err
        canon["hold"] = canon["hold"].strip()

    if "time" in canon:
        err = _validate_duration_string(canon["time"], "time")
        if err:
            return None, err
        canon["time"] = canon["time"].strip()

    return canon, None


def format_set_object(st: dict[str, Any]) -> str:
    keys = set(st.keys())
    if keys == _SET_KG_REPS:
        rep = json.dumps(st["reps"]) if isinstance(st["reps"], str) else str(st["reps"])
        return '{ "kg": ' + str(st["kg"]) + ', "reps": ' + rep + " }"
    if keys == _SET_REPS:
        rep = json.dumps(st["reps"]) if isinstance(st["reps"], str) else str(st["reps"])
        return '{ "reps": ' + rep + " }"
    if keys == _SET_HOLD:
        return '{ "hold": ' + json.dumps(st["hold"]) + " }"
    return '{ "time": ' + json.dumps(st["time"]) + " }"


def format_exercises(exercises: list[dict[str, Any]]) -> str:
    """Pretty canonical JSON text — stable across repeated formatting."""
    lines = ["["]
    for ei, ex in enumerate(exercises):
        lines.append("  {")
        lines.append('    "name": ' + json.dumps(ex["name"]) + ",")
        lines.append('    "sets": [')
        sets_list = ex.get("sets") or []
        for si, st in enumerate(sets_list):
            suffix = "," if si < len(sets_list) - 1 else ""
            lines.append("      " + format_set_object(st) + suffix)
        lines.append("    ]")
        suffix = "," if ei < len(exercises) - 1 else ""
        lines.append("  }" + suffix)
    lines.append("]")
    return "\n".join(lines)


def _line_hint_from_text(text: str, exercise_index: int, set_index: Optional[int] = None) -> int:
    if not text:
        return 1
    lines = text.splitlines()
    if exercise_index < 0:
        return 1
    seen = 0
    for i, line in enumerate(lines, start=1):
        if '"name"' in line:
            if seen == exercise_index:
                if set_index is None:
                    return i
                base = i
                for j in range(i, min(len(lines), i + 80)):
                    if '"sets"' in lines[j - 1]:
                        base = j
                        break
                return min(len(lines), base + 1 + (set_index or 0))
            seen += 1
    return min(len(lines), 1 + exercise_index * 4)


def normalize_exercises(
    raw_list: list[Any],
    *,
    source_text: Optional[str] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (canonical exercises, errors). Stops after MAX_ERRORS."""
    errors: list[dict[str, Any]] = []

    def add(line: int, message: str) -> bool:
        errors.append({"line": line, "message": message})
        return len(errors) >= MAX_ERRORS

    if not isinstance(raw_list, list):
        add(1, "exercises must be a JSON array")
        return [], errors

    if len(raw_list) > MAX_EXERCISES:
        add(_line_hint_from_text(source_text or "", 0), f"at most {MAX_EXERCISES} exercises allowed")
        return [], errors

    canonical: list[dict[str, Any]] = []
    for ei, raw_ex in enumerate(raw_list):
        line = _line_hint_from_text(source_text or "", ei)
        if not isinstance(raw_ex, dict):
            if add(line, "each exercise must be an object"):
                break
            continue
        name = raw_ex.get("name")
        if not isinstance(name, str) or not name.strip():
            if add(line, "exercise name is required"):
                break
            continue

        expanded = expand_shorthand(raw_ex)
        sets_raw = expanded.get("sets")
        if not isinstance(sets_raw, list):
            if add(line, "exercise sets must be a list or shorthand count"):
                break
            continue
        if len(sets_raw) > MAX_SETS_PER_EXERCISE:
            if add(line, f"at most {MAX_SETS_PER_EXERCISE} sets per exercise"):
                break
            continue

        canon_sets: list[dict[str, Any]] = []
        exercise_failed = False
        for si, st in enumerate(sets_raw):
            st_line = _line_hint_from_text(source_text or "", ei, si)
            parsed, err = _validate_set_object(st)
            if err:
                exercise_failed = True
                if add(st_line, err):
                    break
                continue
            if parsed:
                canon_sets.append(parsed)
        if len(errors) >= MAX_ERRORS:
            break
        if exercise_failed:
            continue
        canonical.append({"name": name.strip(), "sets": canon_sets})

    return canonical, errors


def resolve_exercise_names(
    session: Session,
    exercises: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_lower, all_names = _load_library_names(session)
    out: list[dict[str, Any]] = []
    for ex in exercises:
        name = ex["name"]
        key = name.strip().lower()
        row = by_lower.get(key)
        if row is not None:
            out.append(
                {
                    "name": name,
                    "custom": False,
                    "library_name": row.name,
                    "tss_weight": float(row.tss_weight),
                }
            )
        else:
            out.append(
                {
                    "name": name,
                    "custom": True,
                    "library_name": None,
                    "closest_match": _closest_library_name(name, all_names),
                    "tss_weight": 1.0,
                }
            )
    return out


def parse_exercises_text(text: str) -> tuple[Any, Optional[str], Optional[int]]:
    try:
        data = json.loads(text)
        return data, None, None
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e.msg}", e.lineno


def validate_session_exercises(
    session: Session,
    *,
    text: Optional[str] = None,
    exercises: Optional[list[Any]] = None,
) -> dict[str, Any]:
    source_text = text
    raw: Any
    if text is not None and text.strip():
        parsed, err, line = parse_exercises_text(text)
        if err:
            return {
                "valid": False,
                "errors": [{"line": line or 1, "message": err}],
                "exercises": [],
                "formatted": None,
                "resolutions": [],
            }
        raw = parsed
    elif exercises is not None:
        raw = exercises
        source_text = None
    else:
        return {
            "valid": False,
            "errors": [{"line": 1, "message": "provide text or exercises"}],
            "exercises": [],
            "formatted": None,
            "resolutions": [],
        }

    if not isinstance(raw, list):
        return {
            "valid": False,
            "errors": [{"line": 1, "message": "root must be a JSON array"}],
            "exercises": [],
            "formatted": None,
            "resolutions": [],
        }

    canonical, errors = normalize_exercises(raw, source_text=source_text)
    if errors:
        return {
            "valid": False,
            "errors": errors[:MAX_ERRORS],
            "exercises": canonical,
            "formatted": format_exercises(canonical) if canonical else None,
            "resolutions": resolve_exercise_names(session, canonical) if canonical else [],
        }

    formatted = format_exercises(canonical)
    resolutions = resolve_exercise_names(session, canonical)
    return {
        "valid": True,
        "errors": [],
        "exercises": canonical,
        "formatted": formatted,
        "resolutions": resolutions,
    }