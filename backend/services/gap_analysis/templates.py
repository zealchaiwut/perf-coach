"""Session template registry for gap-analysis add-to-plan (issue #1376).

Maps each gap-analysis rule code to a ``PlannedSession`` template dict.

``get_template(code)`` returns either:
  - A template dict with keys: session_type, name, notes, structure, load_adding
  - ``None`` for codes that explicitly have no add-to-plan action
    (e.g. overuse / intensity reduction rules)
  - ``KeyError`` for completely unknown codes

``structure`` follows the same shape the manual Plan-tab editor writes
(frontend/js/training-plan.js): ``{"blocks": [...]}`` for ``run`` sessions
(each block: ``phase``, ``duration_min``, optional ``repeat``/``rest_min``/
``target``) and ``{"exercises": [...]}`` for ``strength``/``plyo`` sessions
(each: ``name``, ``sets``, ``reps``, optional ``block``/``load``). This lets
the session-detail view render Planned Duration/Distance and the exercise
list instead of "No structure yet." Durations/sets/reps are reasonable
defaults inferred from each rule's own ``notes`` text — always editable
after adding to plan (the existing Edit affordance on the session-detail
modal), so precision here is secondary to not being blank.

Templates for dynamic codes (``muscle_untrained.<group>``, etc.) are resolved
by prefix matching, with ``{group}`` interpolated from the suffix — into
``name``, ``notes``, and now the first ``structure.exercises[].name`` too.

Documented in docs/calculations/gap-analysis.md § Add-to-plan templates.
"""
from __future__ import annotations

import copy
from typing import Optional

# ── Static templates (exact code match) ──────────────────────────────────────

_EXACT: dict[str, Optional[dict]] = {
    # ── Plyo deficit (severity 2) ─────────────────────────────────────────────
    "aerobic_durability_gap": {
        "session_type": "run",
        "name": "Aerobic long run",
        "notes": "Easy aerobic long run, ≥110 min, Z1-Z2 effort. Monitor aerobic "
                 "decoupling: if HR drifts >5 % in the back half, shorten next week. Fuel.",
        "structure": {
            "blocks": [
                {"phase": "main", "duration_min": 110, "target": "Z1-Z2"},
            ]
        },
        "load_adding": True,
    },
    # ── Speed neglected → interval session (severity 2) ──────────────────────
    "speed_neglected": {
        "session_type": "run",
        "name": "Speed interval session",
        "notes": "Speed intervals (≥50 min total): 6×400 m at 5 km effort (or equivalent "
                 "Stryd power), 90 s easy jog recovery. Warm up 15 min, cool down 10 min.",
        "structure": {
            "blocks": [
                {"phase": "warmup", "duration_min": 15},
                {"phase": "main", "duration_min": 2, "repeat": 6, "rest_min": 1.5, "target": "5K effort (400m reps)"},
                {"phase": "cooldown", "duration_min": 10},
            ]
        },
        "load_adding": True,
    },
    # ── Plyo deficit (severity 2) ─────────────────────────────────────────────
    "plyo_deficit": {
        "session_type": "plyo",
        "name": "Plyometric intro session",
        "notes": "Plyo session (~30 min): 2×[10 pogo jumps, 10 low box jumps]. Focus on minimal "
                 "ground contact and reactive stiffness. Rest 60 s between sets.",
        "structure": {
            "exercises": [
                {"block": "Plyo circuit", "name": "Pogo jumps", "sets": 2, "reps": 10, "load": "bodyweight"},
                {"block": "Plyo circuit", "name": "Low box jumps", "sets": 2, "reps": 10, "load": "bodyweight"},
            ]
        },
        "load_adding": True,
    },
    # ── No recent plyo (severity 1) ───────────────────────────────────────────
    "no_recent_plyo": {
        "session_type": "plyo",
        "name": "Plyo re-entry session",
        "notes": "Gentle plyo re-entry (~30 min): 2×[10 pogo jumps, 10 low box jumps]. "
                 "Keep volume low after the break.",
        "structure": {
            "exercises": [
                {"block": "Plyo circuit", "name": "Pogo jumps", "sets": 2, "reps": 10, "load": "bodyweight, low volume"},
                {"block": "Plyo circuit", "name": "Low box jumps", "sets": 2, "reps": 10, "load": "bodyweight, low volume"},
            ]
        },
        "load_adding": True,
    },
    # ── GCT lengthening → calf capacity (severity 2) ─────────────────────────
    "gct_lengthening": {
        "session_type": "strength",
        "name": "Calf capacity strength block",
        "notes": "Calf capacity: eccentric calf raises 3×12 each side. "
                 "Slow 3-second lowering, full range. Can be added to an existing "
                 "strength session.",
        "structure": {
            "exercises": [
                {"name": "Eccentric calf raises (each side)", "sets": 3, "reps": 12, "load": "bodyweight, 3s eccentric"},
            ]
        },
        "load_adding": True,
    },
    # ── Cadence drift → cadence-focus easy run (severity 1) ──────────────────
    "cadence_drift": {
        "session_type": "run",
        "name": "Cadence-focus easy run",
        "notes": "Easy effort (Z1-Z2), target cadence ≥170 spm. Use a metronome or "
                 "watch cadence alert. Keep pace comfortable; cadence is the priority.",
        "structure": {
            "blocks": [
                {"phase": "main", "duration_min": 30, "target": "Z1-Z2, cadence ≥170 spm"},
            ]
        },
        "load_adding": True,
    },
    # ── Base neglected → easy aerobic run (severity 2) ───────────────────────
    "base_neglected": {
        "session_type": "run",
        "name": "Easy aerobic run",
        "notes": "30–60 min at easy conversational pace (Z1-Z2). Keep effort low — "
                 "you should be able to hold a full sentence. This is base-building volume.",
        "structure": {
            "blocks": [
                {"phase": "main", "duration_min": 45, "target": "Z1-Z2 easy"},
            ]
        },
        "load_adding": True,
    },
    # ── Strength lapsed (severity 1) ─────────────────────────────────────────
    "strength_lapsed": {
        "session_type": "strength",
        "name": "General strength session",
        "notes": "Full-body strength return: squat, hinge, push, pull — 3×8–10 each. "
                 "Keep intensity moderate after the break.",
        "structure": {
            "exercises": [
                {"block": "Full body", "name": "Squat", "sets": 3, "reps": "8-10", "load": "moderate"},
                {"block": "Full body", "name": "Hinge (deadlift/RDL)", "sets": 3, "reps": "8-10", "load": "moderate"},
                {"block": "Full body", "name": "Push (bench/press)", "sets": 3, "reps": "8-10", "load": "moderate"},
                {"block": "Full body", "name": "Pull (row)", "sets": 3, "reps": "8-10", "load": "moderate"},
            ]
        },
        "load_adding": True,
    },
    # ── Undertrained area under ramp (severity 2) ─────────────────────────────
    "undertrained_area_under_ramp": {
        "session_type": "strength",
        "name": "Targeted strength block",
        "notes": "Focus on the undertrained area: 3×10–12 reps, controlled tempo "
                 "(2 s down). Progress load next session if this feels easy.",
        "structure": {
            "exercises": [
                {"name": "Targeted accessory work", "sets": 3, "reps": "10-12", "load": "moderate, 2s eccentric"},
            ]
        },
        "load_adding": True,
    },
    # ── Overuse / reduction rules → explicit None (no load-adding action) ────
    "recurrent_niggle_area": None,
    "intensity_too_hard": None,
    # Injured variant of undertrained_area_under_ramp: defers to recovery, not loading
    "undertrained_area_under_ramp_deferred": None,
}

# ── Prefix templates (for dynamic codes like muscle_untrained.<group>) ───────
# ``{group}`` is replaced with the code suffix.

_PREFIX: dict[str, Optional[dict]] = {
    "muscle_untrained": {
        "session_type": "strength",
        "name": "Targeted strength: {group}",
        "notes": "Eccentric-focused strength for {group}: 3×12–15 reps, moderate load. "
                 "Slow lowering phase (3 s) to build tissue tolerance.",
        "structure": {
            "exercises": [
                {"name": "{group} eccentric-focus work", "sets": 3, "reps": "12-15", "load": "moderate, 3s eccentric"},
            ]
        },
        "load_adding": True,
    },
    "muscle_detraining": {
        "session_type": "strength",
        "name": "Maintenance strength: {group}",
        "notes": "Maintenance volume for {group}: 2×12–15, light to moderate load. "
                 "Prioritise form over load after detraining.",
        "structure": {
            "exercises": [
                {"name": "{group} maintenance work", "sets": 2, "reps": "12-15", "load": "light-moderate"},
            ]
        },
        "load_adding": True,
    },
    # Overuse prefix → no load-adding template
    "muscle_overused": None,
}


def get_template(code: str) -> Optional[dict]:
    """Return the template for *code*, or None if the code has no add-to-plan action.

    Raises KeyError for completely unrecognised codes so callers can surface a 404.
    """
    if code in _EXACT:
        tmpl = _EXACT[code]
        return dict(tmpl) if tmpl is not None else None

    for prefix, tmpl in _PREFIX.items():
        if code.startswith(prefix + "."):
            if tmpl is None:
                return None
            group = code[len(prefix) + 1:]
            resolved = {**tmpl}
            resolved["name"] = tmpl["name"].format(group=group)
            resolved["notes"] = tmpl["notes"].format(group=group)
            structure = copy.deepcopy(tmpl.get("structure"))
            if structure and isinstance(structure.get("exercises"), list):
                for ex in structure["exercises"]:
                    if isinstance(ex.get("name"), str):
                        ex["name"] = ex["name"].format(group=group)
            resolved["structure"] = structure
            return resolved

    raise KeyError(f"Unknown gap-analysis rule code: {code!r}")


def is_load_adding(code: str) -> bool:
    """True when the template for *code* adds training load (affected by back_off guard)."""
    try:
        tmpl = get_template(code)
    except KeyError:
        return False
    return tmpl is not None and bool(tmpl.get("load_adding"))


def all_known_codes() -> list[str]:
    """Return all exactly-known codes plus prefix stubs (for test coverage checks)."""
    return list(_EXACT.keys()) + list(_PREFIX.keys())
