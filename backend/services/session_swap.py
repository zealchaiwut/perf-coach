"""Swap / add-exercise candidate ranking for the session modal.

Eligibility (applied in order):
1. Block scope — only exercises tagged with this block's group (unless
   ``search_all_blocks``).
2. Already in this session → disabled, not hidden.
3. Active avoid-filters (body_parts) → disabled, not hidden.

Eligible rows rank by body-part overlap with the replaced exercise, then TSS
proximity. Disabled rows sink below a ``not available`` divider.
"""
from __future__ import annotations

from typing import Any

from backend.services.session_pins import block_key


# Map display block labels → plan_exercises.groups keys.
_BLOCK_ALIASES: dict[str, list[str]] = {
    "warmup": ["warmup", "warm_up", "warm-up"],
    "warm_up": ["warmup", "warm_up", "warm-up"],
    "heavy_compound": ["heavy_compound", "compound"],
    "superset": ["superset", "superset_1", "superset_2"],
    "superset_1": ["superset", "superset_1"],
    "superset_2": ["superset", "superset_2"],
    "accessories": ["accessories", "accessory", "standalone", "bodyweight"],
    "accessory": ["accessories", "accessory", "standalone"],
    "standalone": ["standalone", "accessories"],
    "plyo": ["plyo"],
    "cooldown": ["cooldown", "cool_down"],
}


def group_keys_for_block(block_label: str | None) -> list[str]:
    bk = block_key(block_label)
    if not bk:
        return []
    if bk in _BLOCK_ALIASES:
        return list(_BLOCK_ALIASES[bk])
    # Soft match: any alias key contained in bk or vice versa
    for key, aliases in _BLOCK_ALIASES.items():
        if key in bk or bk in key:
            return list(aliases)
    return [bk]


def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _parts_map(body_parts: list | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in _as_list(body_parts):
        if isinstance(p, dict) and p.get("part"):
            out[str(p["part"]).strip().lower()] = float(p.get("ratio") or 0)
        elif isinstance(p, str):
            out[p.strip().lower()] = 1.0
    return out


def body_part_overlap(a: list | None, b: list | None) -> float:
    """Sum of min(ratio_a, ratio_b) over shared parts (0–1-ish)."""
    ma, mb = _parts_map(a), _parts_map(b)
    if not ma or not mb:
        return 0.0
    shared = set(ma) & set(mb)
    return sum(min(ma[k], mb[k]) for k in shared)


def estimate_row_tss(ex: dict, *, sets: int | None = None) -> float:
    """Rough TSS for a library exercise given optional sets override."""
    weight = float(ex.get("tss_weight") or 1.0)
    s = int(sets if sets is not None else (ex.get("default_sets") or 3))
    # Align with fill _spend_for_pick accessories default (~2.5 min/set × weight)
    return round(max(1.0, s * 1.0 * weight), 1)


def _rx_line(ex: dict) -> str:
    sets = ex.get("default_sets")
    reps = ex.get("default_reps") or ""
    load = ex.get("default_load") or ""
    bits = []
    if sets is not None and reps:
        bits.append(f"{sets} × {reps}")
    elif sets is not None:
        bits.append(f"{sets} sets")
    if load:
        bits.append(str(load))
    return " · ".join(bits) if bits else ""


def _loads_avoided(ex: dict, avoid_parts: set[str]) -> str | None:
    if not avoid_parts:
        return None
    parts = _parts_map(ex.get("body_parts"))
    hits = [p for p in avoid_parts if p in parts and parts[p] > 0.15]
    if not hits:
        return None
    # Prefer a readable label
    label = hits[0].replace("_", " ")
    return f"loads {label}"


def rank_swap_candidates(
    *,
    pool: list[dict],
    block: str,
    current_name: str | None,
    current_body_parts: list | None,
    current_tss: float,
    session_names: dict[str, str],
    avoid_parts: set[str] | None = None,
    query: str = "",
    search_all_blocks: bool = False,
) -> dict[str, Any]:
    """Return ranked eligible + disabled candidates for the swap picker."""
    avoid = {str(p).strip().lower() for p in (avoid_parts or set()) if p}
    keys = group_keys_for_block(block)
    q = (query or "").strip().lower()

    in_library = list(pool)
    if search_all_blocks or not keys:
        scoped = list(in_library)
        scope_note = "all blocks"
    else:
        keyset = set(keys)
        scoped = [
            e for e in in_library
            if keyset.intersection({str(g).lower() for g in _as_list(e.get("groups"))})
        ]
        scope_note = keys[0] if keys else "block"

    matched = []
    for e in scoped:
        name = str(e.get("name") or "")
        if not name:
            continue
        if current_name and name.strip().lower() == current_name.strip().lower():
            continue
        if q and q not in name.lower():
            continue
        matched.append(e)

    eligible: list[dict] = []
    disabled: list[dict] = []

    for e in matched:
        name = str(e["name"])
        tss = estimate_row_tss(e)
        row = {
            "id": e.get("id"),
            "name": name,
            "groups": _as_list(e.get("groups")),
            "body_parts": _as_list(e.get("body_parts")),
            "prescription": _rx_line(e),
            "default_sets": e.get("default_sets"),
            "default_reps": e.get("default_reps"),
            "default_load": e.get("default_load"),
            "tss": tss,
            "tss_delta": round(tss - float(current_tss or 0), 1),
            "overlap": round(body_part_overlap(current_body_parts, e.get("body_parts")), 3),
        }
        in_block = session_names.get(name.strip().lower())
        if in_block:
            row["disabled"] = True
            row["why"] = "already in session"
            row["where"] = in_block
            row["why_cls"] = "used"
            disabled.append(row)
            continue
        avoid_why = _loads_avoided(e, avoid)
        if avoid_why:
            row["disabled"] = True
            row["why"] = avoid_why
            row["why_cls"] = "risk"
            disabled.append(row)
            continue
        row["disabled"] = False
        eligible.append(row)

    # Rank: body-part overlap desc, then |tss delta| asc
    eligible.sort(key=lambda r: (-r["overlap"], abs(r["tss_delta"]), r["name"].lower()))
    disabled.sort(key=lambda r: r["name"].lower())

    return {
        "block": block,
        "block_keys": keys,
        "scope": scope_note,
        "search_all_blocks": bool(search_all_blocks),
        "library_count": len(in_library),
        "scoped_count": len(scoped),
        "eligible": eligible,
        "disabled": disabled,
        "offer_all_blocks": (not search_all_blocks) and len(eligible) == 0 and bool(keys),
    }
