"""Configurable session presets derived from gap-analysis findings.

Gap diagnosis stays rule-based. These presets are the **rule base** that
daily Claude must pick from, and that Ask AI / Add / lighter-harder must
respect (duration floors, TSS floors/ceilings, load guardrail).

Defaults are code-config (v1); a user-facing editor can come later.
"""
from __future__ import annotations

import copy
from typing import Any, Optional

# Default constraints by finding family / exact code.
# min_duration_min / min_tss are floors; max_* optional.
# must_respect_load_ceiling: clamp against ACWR week ceiling when materializing.

_PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "aerobic_durability_gap": {
        "kind": "long_run",
        "session_type": "run",
        "constraints": {
            "min_duration_min": 110,
            "max_duration_min": 150,
            "min_tss": 80,
            "max_tss": None,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"effort": "Z1-Z2", "fueling": True},
    },
    "speed_neglected": {
        "kind": "intervals",
        "session_type": "run",
        "constraints": {
            "min_duration_min": 50,
            "max_duration_min": 90,
            "min_tss": 60,
            "max_tss": None,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"effort": "intervals", "quality_block": True},
    },
    "plyo_deficit": {
        "kind": "plyo",
        "session_type": "plyo",
        "constraints": {
            "min_duration_min": 30,
            "max_duration_min": 45,
            "min_tss": 20,
            "max_tss": 45,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"effort": "plyo"},
    },
    "no_recent_plyo": {
        "kind": "plyo",
        "session_type": "plyo",
        "constraints": {
            "min_duration_min": 30,
            "max_duration_min": 40,
            "min_tss": 15,
            "max_tss": 35,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"effort": "plyo", "low_volume": True},
    },
    "base_neglected": {
        "kind": "easy_run",
        "session_type": "run",
        "constraints": {
            "min_duration_min": 40,
            "max_duration_min": 75,
            "min_tss": 35,
            "max_tss": None,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"effort": "Z1-Z2"},
    },
    "cadence_drift": {
        "kind": "easy_run",
        "session_type": "run",
        "constraints": {
            "min_duration_min": 30,
            "max_duration_min": 50,
            "min_tss": 25,
            "max_tss": None,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"effort": "Z1-Z2", "cadence_spm": 170},
    },
    "gct_lengthening": {
        "kind": "strength",
        "session_type": "strength",
        "constraints": {
            "min_duration_min": 25,
            "max_duration_min": 45,
            "min_tss": 15,
            "max_tss": 40,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"focus": "calf"},
    },
    "strength_lapsed": {
        "kind": "strength",
        "session_type": "strength",
        "constraints": {
            "min_duration_min": 35,
            "max_duration_min": 60,
            "min_tss": 25,
            "max_tss": 55,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"focus": "full_body"},
    },
    "undertrained_area_under_ramp": {
        "kind": "strength",
        "session_type": "strength",
        "constraints": {
            "min_duration_min": 25,
            "max_duration_min": 45,
            "min_tss": 15,
            "max_tss": 40,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"focus": "accessory"},
    },
}

_PREFIX_DEFAULTS: dict[str, dict[str, Any]] = {
    "muscle_untrained": {
        "kind": "strength",
        "session_type": "strength",
        "constraints": {
            "min_duration_min": 25,
            "max_duration_min": 45,
            "min_tss": 15,
            "max_tss": 40,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"focus": "eccentric"},
    },
    "muscle_detraining": {
        "kind": "strength",
        "session_type": "strength",
        "constraints": {
            "min_duration_min": 20,
            "max_duration_min": 40,
            "min_tss": 12,
            "max_tss": 35,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"focus": "maintenance"},
    },
}


def _lookup_defaults(code: str) -> Optional[dict[str, Any]]:
    if code in _PRESET_DEFAULTS:
        return copy.deepcopy(_PRESET_DEFAULTS[code])
    if "." in code:
        prefix, _suffix = code.split(".", 1)
        if prefix in _PREFIX_DEFAULTS:
            return copy.deepcopy(_PREFIX_DEFAULTS[prefix])
    return None


def get_presets(user_id=None, db=None) -> dict[str, dict[str, Any]]:
    """Built-in defaults merged with user:* custom presets (import MVP).

    Replaces direct `_PRESET_DEFAULTS` reads for materialization paths that
    must honour user-authored presets. Unknown user codes are ignored.
    """
    out = {k: copy.deepcopy(v) for k, v in _PRESET_DEFAULTS.items()}
    if user_id is None:
        return out
    own = db is None
    if own:
        try:
            from sqlalchemy.orm import Session
            from backend.db import engine
            from backend.models import UserCustomPreset
            db = Session(engine)
        except Exception:
            return out
    else:
        try:
            from backend.models import UserCustomPreset
        except Exception:
            return out
    try:
        rows = (
            db.query(UserCustomPreset)
            .filter(UserCustomPreset.user_id == user_id)
            .all()
        )
        for r in rows:
            code = r.code
            if not isinstance(code, str) or not code.startswith("user:"):
                continue
            payload = copy.deepcopy(r.payload) if isinstance(r.payload, dict) else {}
            constraints = dict(payload.get("constraints") or {})
            constraints["must_respect_load_ceiling"] = True
            payload["constraints"] = constraints
            out[code] = payload
    except Exception:
        pass
    finally:
        if own and db is not None:
            try:
                db.close()
            except Exception:
                pass
    return out


def get_preset_for_code(
    code: str,
    *,
    priority: int | None = None,
    user_id=None,
    db=None,
) -> Optional[dict[str, Any]]:
    """Return a session preset dict for a gap code, or None if no add-to-plan action."""
    # user:* custom presets — no template registry entry required
    if isinstance(code, str) and code.startswith("user:"):
        presets = get_presets(user_id, db=db)
        raw = presets.get(code)
        if not raw:
            return None
        constraints = dict(raw.get("constraints") or {})
        constraints["must_respect_load_ceiling"] = True
        return {
            "code": code,
            "session_type": raw.get("session_type") or "run",
            "kind": raw.get("kind") or "session",
            "name": raw.get("name") or code,
            "notes": raw.get("notes"),
            "structure": copy.deepcopy(raw.get("structure") or {}),
            "constraints": constraints,
            "structure_hints": raw.get("structure_hints") or {},
            "priority": int(priority) if priority is not None else 2,
            "summary": _preset_summary(raw.get("kind"), constraints),
        }

    from backend.services.gap_analysis.templates import get_template

    try:
        tmpl = get_template(code)
    except KeyError:
        return None
    if tmpl is None:
        return None

    defaults = _lookup_defaults(code) or {
        "kind": tmpl.get("session_type") or "session",
        "session_type": tmpl.get("session_type") or "run",
        "constraints": {
            "min_duration_min": _template_duration_min(tmpl) or 30,
            "max_duration_min": None,
            "min_tss": None,
            "max_tss": None,
            "must_respect_load_ceiling": True,
            "load_adding": bool(tmpl.get("load_adding", True)),
        },
        "structure_hints": {},
    }

    constraints = defaults.get("constraints") or {}
    # Align load_adding with template registry.
    constraints["load_adding"] = bool(tmpl.get("load_adding", constraints.get("load_adding", True)))

    return {
        "code": code,
        "session_type": defaults.get("session_type") or tmpl.get("session_type"),
        "kind": defaults.get("kind") or tmpl.get("session_type"),
        "name": tmpl.get("name"),
        "notes": tmpl.get("notes"),
        "structure": copy.deepcopy(tmpl.get("structure") or {}),
        "constraints": constraints,
        "structure_hints": defaults.get("structure_hints") or {},
        "priority": int(priority) if priority is not None else 2,
        "summary": _preset_summary(defaults.get("kind"), constraints),
    }


def _template_duration_min(tmpl: dict) -> int | None:
    structure = tmpl.get("structure") or {}
    blocks = structure.get("blocks") or []
    total = 0
    for b in blocks:
        if not isinstance(b, dict):
            continue
        d = float(b.get("duration_min") or 0)
        rep = int(b.get("repeat") or 1)
        rest = float(b.get("rest_min") or 0)
        total += d * rep + rest * max(0, rep - 1)
    return int(round(total)) if total > 0 else None


def _preset_summary(kind: str | None, constraints: dict) -> str:
    parts: list[str] = []
    label = (kind or "session").replace("_", " ")
    parts.append(label.title())
    min_d = constraints.get("min_duration_min")
    if min_d:
        parts.append(f"≥{int(min_d)} min")
    min_t = constraints.get("min_tss")
    max_t = constraints.get("max_tss")
    if min_t is not None and max_t is not None:
        parts.append(f"TSS {int(min_t)}–{int(max_t)}")
    elif min_t is not None:
        parts.append(f"TSS ≥{int(min_t)}")
    if constraints.get("must_respect_load_ceiling"):
        parts.append("≤ ceiling")
    return " · ".join(parts)


def presets_from_findings(findings: list[dict] | list[Any]) -> list[dict]:
    """Build active presets from gap findings (dicts or objects with .code)."""
    out: list[dict] = []
    seen: set[str] = set()
    for f in findings or []:
        if isinstance(f, dict):
            code = f.get("code")
            sev = f.get("severity")
            status = f.get("status") or "active"
        else:
            code = getattr(f, "code", None)
            sev = getattr(f, "severity", None)
            status = getattr(f, "status", "active")
        if not code or status != "active" or code in seen:
            continue
        preset = get_preset_for_code(code, priority=sev)
        if preset is None:
            continue
        seen.add(code)
        out.append(preset)
    # Higher severity first
    out.sort(key=lambda p: (-int(p.get("priority") or 0), p.get("code") or ""))
    return out


def pick_preset_by_code(presets: list[dict], code: str | None) -> Optional[dict]:
    if not code:
        return None
    for p in presets or []:
        if p.get("code") == code:
            return p
    return None


def clamp_duration_tss(
    *,
    duration_min: float | None,
    tss: float | None,
    preset: dict | None,
    load_ceiling_tss: float | None = None,
    remaining_week_tss: float | None = None,
) -> tuple[float | None, float | None]:
    """Clamp duration/TSS into preset floors/ceilings and optional load ceiling."""
    if preset is None:
        return duration_min, tss
    c = preset.get("constraints") or {}
    d = duration_min
    t = tss

    if d is not None:
        min_d = c.get("min_duration_min")
        max_d = c.get("max_duration_min")
        if min_d is not None:
            d = max(float(d), float(min_d))
        if max_d is not None:
            d = min(float(d), float(max_d))

    if t is not None:
        min_t = c.get("min_tss")
        max_t = c.get("max_tss")
        if min_t is not None:
            t = max(float(t), float(min_t))
        if max_t is not None:
            t = min(float(t), float(max_t))
        if c.get("must_respect_load_ceiling"):
            caps = [x for x in (load_ceiling_tss, remaining_week_tss) if x is not None]
            if caps:
                t = min(float(t), min(float(x) for x in caps))

    return d, t


def scale_structure_to_duration(structure: dict | None, target_min: float | None) -> dict:
    """Scale run block durations proportionally toward target_min (best-effort)."""
    structure = copy.deepcopy(structure or {})
    if not target_min:
        return structure
    blocks = structure.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return structure
    current = 0.0
    for b in blocks:
        if isinstance(b, dict):
            current += float(b.get("duration_min") or 0) * int(b.get("repeat") or 1)
    if current <= 0:
        return structure
    factor = float(target_min) / current
    for b in blocks:
        if isinstance(b, dict) and b.get("duration_min") is not None:
            b["duration_min"] = round(float(b["duration_min"]) * factor, 1)
    return structure


def is_incomplete_gap_session(
    structure: dict | None,
    preset: dict | None = None,
) -> bool:
    """True when a gap-tagged planned session is a hollow stub or below preset floors.

    Early add-to-plan wrote ``structure={_gap_code}`` when templates had
    ``structure: None``. Those rows still trip the weekly duplicate guard and
    block a real add — treat them as upgradeable.
    """
    structure = structure if isinstance(structure, dict) else {}
    blocks = structure.get("blocks")
    exercises = structure.get("exercises")
    has_blocks = isinstance(blocks, list) and len(blocks) > 0
    has_exercises = isinstance(exercises, list) and len(exercises) > 0
    if not has_blocks and not has_exercises:
        return True

    constraints = (preset or {}).get("constraints") or {}
    min_d = constraints.get("min_duration_min")
    min_t = constraints.get("min_tss")

    if has_blocks and min_d is not None:
        dur = structure.get("duration_min")
        if dur is None:
            dur = _template_duration_min({"structure": structure})
        if dur is None or float(dur) < float(min_d) - 0.5:
            return True

    if min_t is not None:
        tss = structure.get("target_tss")
        if tss is None:
            # Run-like sessions with blocks need a TSS floor when the preset sets one.
            if has_blocks:
                return True
        elif float(tss) < float(min_t) - 0.5:
            return True
    return False


def materialize_planned_fields(
    preset: dict,
    *,
    load_ceiling_tss: float | None = None,
    remaining_week_tss: float | None = None,
) -> dict:
    """Produce PlannedSession fields from a preset, clamped to constraints."""
    c = preset.get("constraints") or {}
    duration = float(c.get("min_duration_min") or _template_duration_min(preset) or 30)
    tss = c.get("min_tss")
    if tss is not None:
        tss = float(tss)
    duration, tss = clamp_duration_tss(
        duration_min=duration,
        tss=tss,
        preset=preset,
        load_ceiling_tss=load_ceiling_tss,
        remaining_week_tss=remaining_week_tss,
    )
    structure = scale_structure_to_duration(preset.get("structure"), duration)
    structure["_gap_code"] = preset.get("code")
    structure["_preset_code"] = preset.get("code")
    structure["_preset_kind"] = preset.get("kind")
    structure["_preset_constraints"] = c
    if duration is not None:
        structure["duration_min"] = duration
    if tss is not None:
        structure["target_tss"] = tss
    return {
        "session_type": preset.get("session_type") or "run",
        "name": preset.get("name"),
        "notes": preset.get("notes"),
        "structure": structure,
        "duration_min": duration,
        "target_tss": tss,
        "preset_constraints": c,
    }
