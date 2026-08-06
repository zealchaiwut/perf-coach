"""Plan-library body-part vocabulary (exercise tinybar + bulk import).

Canonical keys match the admin card color map. Import / LLM paste often uses
plurals (glutes, calves) or coarse labels (back, arms) — normalize those
before validate/store so the color chart lights up.
"""
from __future__ import annotations

from typing import Any

# Keep colors in sync with frontend/js/admin-plan-library.js PART_COLORS.
PLAN_BODY_PART_COLORS: dict[str, str] = {
    "quad": "#4f6ef7",
    "glute": "#7c3aed",
    "hamstring": "#0ea5e9",
    "calf": "#f97316",
    "hip": "#14b8a6",
    "hip_flexor": "#06b6d4",
    "chest": "#ec4899",
    "shoulder": "#f59e0b",
    "upper_back": "#8b5cf6",
    "lower_back": "#ef4444",
    "trapezius": "#a855f7",
    "biceps": "#22c55e",
    "triceps": "#10b981",
    "core": "#eab308",
    "oblique": "#facc15",
    "grip": "#64748b",
}

PLAN_BODY_PARTS: frozenset[str] = frozenset(PLAN_BODY_PART_COLORS)

# Alias → canonical plan-library key (lowercase).
PLAN_BODY_PART_ALIASES: dict[str, str] = {
    # identity
    **{k: k for k in PLAN_BODY_PARTS},
    # plurals / common variants
    "quads": "quad",
    "quadriceps": "quad",
    "glutes": "glute",
    "gluteus": "glute",
    "hamstrings": "hamstring",
    "calves": "calf",
    "achilles": "calf",
    "hips": "hip",
    "hip flexor": "hip_flexor",
    "hip flexors": "hip_flexor",
    "hip_flexors": "hip_flexor",
    "shoulders": "shoulder",
    "delts": "shoulder",
    "deltoids": "shoulder",
    "obliques": "oblique",
    "abs": "core",
    "abdominals": "core",
    "traps": "trapezius",
    "pecs": "chest",
    "pectorals": "chest",
    "pectoral": "chest",
    # coarse labels → closest fine key
    "back": "upper_back",
    "lats": "upper_back",
    "arms": "biceps",
    "arm": "biceps",
    "forearms": "grip",
    "forearm": "grip",
}


def normalize_plan_body_part(raw: str | None) -> str | None:
    """Map a free-text part name to a canonical plan-library key, or None."""
    if raw is None:
        return None
    key = str(raw).strip().lower().replace("-", "_")
    key = " ".join(key.split())
    if key in PLAN_BODY_PART_ALIASES:
        return PLAN_BODY_PART_ALIASES[key]
    # space ↔ underscore
    alt = key.replace(" ", "_")
    if alt in PLAN_BODY_PART_ALIASES:
        return PLAN_BODY_PART_ALIASES[alt]
    alt2 = key.replace("_", " ")
    if alt2 in PLAN_BODY_PART_ALIASES:
        return PLAN_BODY_PART_ALIASES[alt2]
    return None


def normalize_body_parts_list(raw: list | None) -> tuple[list[dict] | None, str | None]:
    """Normalize [{part, ratio}] → canonical parts.

    Merges duplicate parts after aliasing. Returns (list, None) or (None, error).
    """
    if not isinstance(raw, list) or not raw:
        return None, "body_parts must be a non-empty list"
    merged: dict[str, float] = {}
    for bp in raw:
        if not isinstance(bp, dict):
            return None, "body_parts entries must be objects"
        canon = normalize_plan_body_part(bp.get("part"))
        if not canon:
            return None, (
                f"invalid body_parts.part: {bp.get('part')!r} "
                f"(allowed: {sorted(PLAN_BODY_PARTS)}; plurals like glutes/calves ok)"
            )
        try:
            ratio = float(bp.get("ratio"))
        except (TypeError, ValueError):
            return None, "body_parts.ratio must be a number"
        if ratio <= 0:
            return None, "body_parts.ratio must be > 0"
        merged[canon] = merged.get(canon, 0.0) + ratio
    part_sum = sum(merged.values())
    if abs(part_sum - 1.0) > 0.05:
        return None, f"body_parts ratios must sum ≈ 1.0 (got {part_sum:.2f})"
    out = [
        {"part": p, "ratio": round(r, 4)}
        for p, r in merged.items()
    ]
    return out, None


def catalog_payload() -> dict[str, Any]:
    """Admin UI: canonical parts + colors + accepted aliases."""
    rev: dict[str, list[str]] = {k: [] for k in PLAN_BODY_PARTS}
    for alias, canon in sorted(PLAN_BODY_PART_ALIASES.items()):
        if alias == canon:
            continue
        rev.setdefault(canon, []).append(alias)
    parts = [
        {
            "key": key,
            "color": PLAN_BODY_PART_COLORS[key],
            "aliases": rev.get(key, []),
        }
        for key in sorted(PLAN_BODY_PARTS)
    ]
    return {"parts": parts}
