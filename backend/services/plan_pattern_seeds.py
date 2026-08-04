"""Default plan_patterns + plan_exercises rows (idempotent seed / admin reset)."""
from __future__ import annotations

from typing import Any


def default_run_patterns() -> list[dict[str, Any]]:
    return [
        {
            "kind": "run",
            "subtype": "easy_run",
            "duration_min_lo": 0,
            "duration_min_hi": 120,
            "name": "Easy aerobic (scaled)",
            "priority": 10,
            "recipe": {
                "intent_template": "Easy aerobic run",
                "notes_template": None,
                "blocks": [
                    {"phase": "warmup", "duration_share": 0.15, "repeat": None, "rest_min": None, "target": "easy"},
                    {"phase": "main", "duration_share": 0.70, "repeat": None, "rest_min": None, "target": "easy, conversational"},
                    {"phase": "cooldown", "duration_share": 0.15, "repeat": None, "rest_min": None, "target": "easy"},
                ],
            },
        },
        {
            "kind": "run",
            "subtype": "long_run",
            "duration_min_lo": 0,
            "duration_min_hi": 200,
            "name": "Long run (scaled)",
            "priority": 10,
            "recipe": {
                "intent_template": "Aerobic long run — fuel mid-run",
                "notes_template": "Keep conversational; fuel from ~40 min if ≥90 min.",
                "blocks": [
                    {"phase": "warmup", "duration_share": 0.10, "repeat": None, "rest_min": None, "target": "easy"},
                    {"phase": "main", "duration_share": 0.80, "repeat": None, "rest_min": None, "target": "easy Z2 — gel/drink from minute 40"},
                    {"phase": "cooldown", "duration_share": 0.10, "repeat": None, "rest_min": None, "target": "easy"},
                ],
            },
        },
        {
            "kind": "run",
            "subtype": "tempo",
            "duration_min_lo": 0,
            "duration_min_hi": 120,
            "name": "Tempo / threshold",
            "priority": 10,
            "recipe": {
                "intent_template": "Tempo / quality run",
                "notes_template": None,
                "blocks": [
                    {"phase": "warmup", "duration_share": 0.20, "repeat": None, "rest_min": None, "target": "easy"},
                    {"phase": "main", "duration_share": 0.55, "repeat": 3, "rest_min": 2, "target": "tempo — comfortably hard"},
                    {"phase": "cooldown", "duration_share": 0.25, "repeat": None, "rest_min": None, "target": "easy"},
                ],
            },
        },
        {
            "kind": "run",
            "subtype": "intervals",
            "duration_min_lo": 0,
            "duration_min_hi": 120,
            "name": "Intervals",
            "priority": 10,
            "recipe": {
                "intent_template": "Interval session",
                "notes_template": None,
                "blocks": [
                    {"phase": "warmup", "duration_share": 0.20, "repeat": None, "rest_min": None, "target": "easy"},
                    {"phase": "main", "duration_share": 0.55, "repeat": 6, "rest_min": 2, "target": "hard — interval effort"},
                    {"phase": "cooldown", "duration_share": 0.25, "repeat": None, "rest_min": None, "target": "easy"},
                ],
            },
        },
    ]


def default_strength_patterns() -> list[dict[str, Any]]:
    groups_std = [
        {"key": "warmup", "label": "Warm-up", "time_share": 0.12, "tss_share": 0.08, "pick": {"n": 2, "from_tags": ["warmup"]}},
        {"key": "heavy_compound", "label": "Heavy compound", "time_share": 0.22, "tss_share": 0.28, "pick": {"n": 1, "from_tags": ["heavy_compound"]}},
        {"key": "superset", "label": "Superset 1", "time_share": 0.18, "tss_share": 0.20, "pick": {"n": 2, "from_tags": ["superset"]}},
        {"key": "superset", "label": "Superset 2", "time_share": 0.18, "tss_share": 0.20, "pick": {"n": 2, "from_tags": ["superset"]}},
        {"key": "standalone", "label": "Standalone", "time_share": 0.12, "tss_share": 0.12, "pick": {"n": 1, "from_tags": ["standalone"]}},
        {"key": "accessories", "label": "Accessories", "time_share": 0.10, "tss_share": 0.08, "pick": {"n": 2, "from_tags": ["accessories"]}},
        {"key": "cooldown", "label": "Stretch", "time_share": 0.08, "tss_share": 0.04, "pick": {"n": 1, "from_tags": ["cooldown"]}},
    ]
    # Light = maintenance / recovery-friendly: no heavy compound. Bodyweight,
    # low-impact plyo, and isometrics keep the session useful without loading.
    groups_light = [
        {"key": "warmup", "label": "Warm-up", "time_share": 0.15, "tss_share": 0.10, "pick": {"n": 2, "from_tags": ["warmup"]}},
        {"key": "bodyweight", "label": "Bodyweight", "time_share": 0.28, "tss_share": 0.30, "pick": {"n": 2, "from_tags": ["bodyweight"]}},
        {"key": "plyo", "label": "Plyometrics", "time_share": 0.22, "tss_share": 0.25, "pick": {"n": 2, "from_tags": ["plyo"]}},
        {"key": "isometric", "label": "Isometrics", "time_share": 0.22, "tss_share": 0.25, "pick": {"n": 2, "from_tags": ["isometric"]}},
        {"key": "cooldown", "label": "Stretch", "time_share": 0.13, "tss_share": 0.10, "pick": {"n": 1, "from_tags": ["cooldown"]}},
    ]
    out = []
    for subtype, primary, name in (
        ("strength_lower", "lower", "Lower body strength"),
        ("strength_upper", "upper", "Upper body strength"),
        ("strength_full", "full", "Full body strength"),
        ("strength_light", "full", "Light strength / maintenance"),
    ):
        bias = {"primary": 0.8, "accessory": 0.2, "primary_tag": primary}
        groups = groups_std
        if subtype == "strength_light":
            bias = {"primary": 0.5, "accessory": 0.5, "primary_tag": "full"}
            groups = groups_light
        out.append({
            "kind": "strength",
            "subtype": subtype,
            "duration_min_lo": 0,
            "duration_min_hi": 120,
            "name": name,
            "priority": 10,
            "recipe": {
                "intent_template": name,
                "notes_template": (
                    "Keep loads easy — bodyweight, light plyo, and holds only."
                    if subtype == "strength_light" else None
                ),
                "groups": groups,
                "focus_bias": bias,
            },
        })
    return out


def default_exercises() -> list[dict[str, Any]]:
    """Pool used by strength pattern fill."""
    def ex(name, groups, focus, parts, sets=3, reps="10", load="moderate", tw=1.0):
        return {
            "name": name,
            "groups": groups,
            "focus_tags": focus,
            "body_parts": parts,
            "tss_weight": tw,
            "default_sets": sets,
            "default_reps": reps,
            "default_load": load,
        }

    return [
        # warmups
        ex("Bodyweight squat", ["warmup", "bodyweight"], ["lower", "full"], [{"part": "quad", "ratio": 0.6}, {"part": "glute", "ratio": 0.4}], 2, "15", "bodyweight", 0.5),
        ex("Spiderman lunge w/ rotation", ["warmup"], ["lower", "full"], [{"part": "hip_flexor", "ratio": 0.5}, {"part": "glute", "ratio": 0.5}], 1, "8", "bodyweight", 0.4),
        ex("Lateral band walk", ["warmup"], ["lower"], [{"part": "glute", "ratio": 0.8}, {"part": "hip", "ratio": 0.2}], 2, "15", "light band", 0.5),
        ex("Arm circles + band pull-apart", ["warmup"], ["upper", "full"], [{"part": "shoulder", "ratio": 0.7}, {"part": "upper_back", "ratio": 0.3}], 1, "15", "light band", 0.4),
        ex("Scapular push-up", ["warmup", "bodyweight"], ["upper"], [{"part": "chest", "ratio": 0.4}, {"part": "shoulder", "ratio": 0.6}], 2, "10", "bodyweight", 0.4),
        # heavy compounds (full / lower / upper — never used by strength_light)
        ex("Back squat", ["heavy_compound"], ["lower", "full"], [{"part": "quad", "ratio": 0.55}, {"part": "glute", "ratio": 0.35}, {"part": "core", "ratio": 0.1}], 4, "8", "moderate", 1.5),
        ex("Romanian deadlift", ["heavy_compound", "superset"], ["lower", "full"], [{"part": "hamstring", "ratio": 0.5}, {"part": "glute", "ratio": 0.35}, {"part": "lower_back", "ratio": 0.15}], 3, "10", "moderate", 1.3),
        ex("Dumbbell bench press", ["heavy_compound"], ["upper", "full"], [{"part": "chest", "ratio": 0.55}, {"part": "triceps", "ratio": 0.25}, {"part": "shoulder", "ratio": 0.2}], 4, "8", "moderate", 1.4),
        ex("Goblet squat", ["heavy_compound", "superset"], ["lower", "full"], [{"part": "quad", "ratio": 0.5}, {"part": "glute", "ratio": 0.4}, {"part": "core", "ratio": 0.1}], 3, "10", "moderate", 1.2),
        # supersets
        ex("Dumbbell overhead press", ["superset"], ["upper", "full"], [{"part": "shoulder", "ratio": 0.6}, {"part": "triceps", "ratio": 0.3}, {"part": "core", "ratio": 0.1}], 3, "10", "moderate", 1.1),
        ex("Dumbbell bent-over row", ["superset"], ["upper", "full"], [{"part": "upper_back", "ratio": 0.55}, {"part": "biceps", "ratio": 0.25}, {"part": "core", "ratio": 0.2}], 3, "10", "moderate", 1.1),
        ex("Walking lunge", ["superset", "bodyweight"], ["lower", "full"], [{"part": "quad", "ratio": 0.45}, {"part": "glute", "ratio": 0.45}, {"part": "hamstring", "ratio": 0.1}], 3, "10", "bodyweight or light DB", 1.1),
        ex("Hip thrust", ["standalone", "superset"], ["lower", "full"], [{"part": "glute", "ratio": 0.75}, {"part": "hamstring", "ratio": 0.25}], 3, "10", "moderate", 1.2),
        # standalone / accessories
        ex("Farmer's carry", ["standalone"], ["full", "upper", "core"], [{"part": "grip", "ratio": 0.3}, {"part": "core", "ratio": 0.4}, {"part": "trapezius", "ratio": 0.3}], 3, "30m", "moderate DB", 1.0),
        ex("Plank", ["accessories", "cooldown", "isometric"], ["core", "full"], [{"part": "core", "ratio": 1.0}], 3, "40s hold", "bodyweight", 0.6),
        ex("Side plank", ["accessories", "isometric"], ["core", "full"], [{"part": "core", "ratio": 0.8}, {"part": "oblique", "ratio": 0.2}], 2, "25-30s hold", "bodyweight", 0.5),
        ex("Dead bug", ["accessories", "bodyweight"], ["core", "full"], [{"part": "core", "ratio": 1.0}], 3, "10", "bodyweight", 0.5),
        ex("Bird dog", ["accessories", "cooldown", "bodyweight"], ["core", "full", "lower"], [{"part": "core", "ratio": 0.5}, {"part": "glute", "ratio": 0.3}, {"part": "lower_back", "ratio": 0.2}], 3, "10", "bodyweight", 0.5),
        ex("World's greatest stretch", ["cooldown"], ["full", "lower"], [{"part": "hip_flexor", "ratio": 0.5}, {"part": "hamstring", "ratio": 0.5}], 1, "5/side", "bodyweight", 0.3),
        # light-session pool — bodyweight / plyo / isometric only
        ex("Push-up", ["bodyweight"], ["upper", "full"], [{"part": "chest", "ratio": 0.5}, {"part": "triceps", "ratio": 0.3}, {"part": "core", "ratio": 0.2}], 3, "8-12", "bodyweight", 0.8),
        ex("Glute bridge", ["bodyweight"], ["lower", "full"], [{"part": "glute", "ratio": 0.7}, {"part": "hamstring", "ratio": 0.3}], 3, "12", "bodyweight", 0.7),
        ex("Reverse lunge", ["bodyweight"], ["lower", "full"], [{"part": "quad", "ratio": 0.45}, {"part": "glute", "ratio": 0.45}, {"part": "hamstring", "ratio": 0.1}], 3, "10/side", "bodyweight", 0.8),
        ex("Pogo jumps", ["plyo"], ["lower", "full"], [{"part": "calf", "ratio": 0.6}, {"part": "achilles", "ratio": 0.4}], 3, "20", "bodyweight", 0.7),
        ex("Squat jump", ["plyo"], ["lower", "full"], [{"part": "quad", "ratio": 0.45}, {"part": "glute", "ratio": 0.4}, {"part": "calf", "ratio": 0.15}], 3, "8", "bodyweight — soft landings", 0.9),
        ex("Low box step-off", ["plyo"], ["lower", "full"], [{"part": "quad", "ratio": 0.4}, {"part": "calf", "ratio": 0.35}, {"part": "glute", "ratio": 0.25}], 3, "6/side", "bodyweight — stick the landing", 0.8),
        ex("Wall sit", ["isometric"], ["lower", "full"], [{"part": "quad", "ratio": 0.7}, {"part": "glute", "ratio": 0.3}], 3, "30-40s hold", "bodyweight", 0.6),
        ex("Hollow hold", ["isometric"], ["core", "full"], [{"part": "core", "ratio": 1.0}], 3, "20-30s hold", "bodyweight", 0.6),
        ex("Calf raise hold", ["isometric"], ["lower", "full"], [{"part": "calf", "ratio": 0.85}, {"part": "achilles", "ratio": 0.15}], 3, "25-30s hold", "bodyweight", 0.5),
    ]


def all_default_patterns() -> list[dict[str, Any]]:
    return default_run_patterns() + default_strength_patterns()
