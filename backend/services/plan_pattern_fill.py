"""Deterministic session content from plan_patterns + plan_exercises (no LLM)."""
from __future__ import annotations

import copy
import random
from typing import Any

from sqlalchemy.orm import Session

from backend.services.plan_pattern_seeds import all_default_patterns, default_exercises
from backend.services.plan_slot import (
    normalize_slot_subtype,
    stamp_session,
    template_content_for_slot,
    validate_slot,
)
from backend.utils.log import get_logger

_log = get_logger(__name__)


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return list(v)


def select_pattern(
    db: Session | None,
    *,
    workout_type: str,
    subtype: str | None,
    duration_min: int,
) -> dict[str, Any] | None:
    """Pick highest-priority active pattern whose duration band contains duration_min."""
    wt = (workout_type or "").lower()
    kind = "run" if wt == "run" else ("strength" if wt in ("strength", "plyo") else None)
    if kind is None:
        return None
    sub = normalize_slot_subtype(wt, subtype) or ""
    dur = int(duration_min or 0)

    rows: list[dict] = []
    if db is not None:
        try:
            from backend.models import PlanPattern

            q = (
                db.query(PlanPattern)
                .filter(
                    PlanPattern.active.is_(True),
                    PlanPattern.kind == kind,
                    PlanPattern.subtype == sub,
                    PlanPattern.duration_min_lo <= dur,
                    PlanPattern.duration_min_hi >= dur,
                )
                .order_by(PlanPattern.priority.desc())
                .all()
            )
            rows = [
                {
                    "id": str(r.id),
                    "kind": r.kind,
                    "subtype": r.subtype,
                    "name": r.name,
                    "priority": r.priority,
                    "recipe": r.recipe or {},
                }
                for r in q
            ]
        except Exception:
            _log.warning("plan_patterns query failed; using seed defaults", exc_info=True)
            rows = []

    if not rows:
        for p in all_default_patterns():
            if (
                p["kind"] == kind
                and p["subtype"] == sub
                and int(p["duration_min_lo"]) <= dur <= int(p["duration_min_hi"])
            ):
                rows.append(p)
        rows.sort(key=lambda x: -int(x.get("priority") or 0))

    return rows[0] if rows else None


def _load_exercise_pool(db: Session | None) -> list[dict]:
    if db is not None:
        try:
            from backend.models import PlanExercise

            rows = db.query(PlanExercise).filter(PlanExercise.active.is_(True)).all()
            if rows:
                return [
                    {
                        "id": str(r.id),
                        "name": r.name,
                        "groups": _as_list(r.groups),
                        "focus_tags": _as_list(r.focus_tags),
                        "body_parts": _as_list(r.body_parts),
                        "tss_weight": float(r.tss_weight or 1.0),
                        "default_sets": r.default_sets,
                        "default_reps": r.default_reps,
                        "default_load": r.default_load,
                    }
                    for r in rows
                ]
        except Exception:
            _log.warning("plan_exercises query failed; using seed defaults", exc_info=True)
    return [dict(e) for e in default_exercises()]


def fill_run(pattern: dict, slot: dict) -> dict:
    recipe = pattern.get("recipe") or {}
    pinned = int(slot.get("duration_minutes") or 0) or 45
    blocks_in = recipe.get("blocks") or []
    blocks: list[dict] = []
    shares = [float(b.get("duration_share") or 0) for b in blocks_in]
    share_sum = sum(shares) or 1.0
    allocated = 0
    for i, b in enumerate(blocks_in):
        bb = {
            "phase": b.get("phase") or "main",
            "repeat": b.get("repeat"),
            "rest_min": b.get("rest_min"),
            "target": b.get("target"),
        }
        if i == len(blocks_in) - 1:
            mins = max(1, pinned - allocated)
        else:
            share = float(b.get("duration_share") or 0) / share_sum
            mins = max(1, int(round(pinned * share)))
            allocated += mins
        # For repeated main, duration_min is per-rep effort; scale carefully
        if bb.get("repeat") and int(bb["repeat"] or 0) > 1:
            # Keep per-rep length modest; total work ≈ duration_min * repeat
            rep = int(bb["repeat"])
            per = max(1, int(round(mins / max(rep * 0.55, 1))))
            bb["duration_min"] = per
        else:
            bb["duration_min"] = mins
        blocks.append(bb)

    intent = (recipe.get("intent_template") or "Run")[:140]
    if (slot.get("subtype") or "") == "long_run" and pinned >= 90:
        intent = "Aerobic long run — fuel mid-run"
    return {
        "intent": intent,
        "notes": recipe.get("notes_template"),
        "blocks": blocks,
        "exercises": None,
        "source": "pattern",
        "pattern_name": pattern.get("name"),
    }


def _pick_exercises(
    pool: list[dict],
    *,
    group_keys: list[str],
    n: int,
    primary_tag: str,
    primary_frac: float,
    avoid_parts: set[str] | None,
    rng: random.Random,
    used_names: set[str],
) -> list[dict]:
    candidates = [
        e for e in pool
        if any(g in _as_list(e.get("groups")) for g in group_keys)
        and e.get("name") not in used_names
    ]
    if not candidates:
        candidates = [e for e in pool if e.get("name") not in used_names] or list(pool)

    def score(e: dict) -> float:
        tags = set(_as_list(e.get("focus_tags")))
        s = 1.0
        if primary_tag and primary_tag in tags:
            s *= 1.0 + primary_frac
        elif primary_tag and primary_tag != "full" and "full" in tags:
            s *= 0.7
        elif primary_tag and primary_tag not in tags and "core" not in tags:
            s *= (1.0 - primary_frac) + 0.15
        if avoid_parts:
            parts = {str(p.get("part") or "") for p in _as_list(e.get("body_parts")) if isinstance(p, dict)}
            overlap = parts & avoid_parts
            if overlap:
                s *= 0.35
        return s * (0.85 + 0.3 * rng.random())

    ranked = sorted(candidates, key=score, reverse=True)
    picked = ranked[: max(1, n)]
    out = []
    for e in picked:
        used_names.add(e["name"])
        out.append({
            "block": None,  # filled by caller
            "name": e["name"],
            "sets": e.get("default_sets") or 3,
            "reps": e.get("default_reps") or "10",
            "load": e.get("default_load") or "moderate",
            "_body_parts": _as_list(e.get("body_parts")),
            "_tss_weight": float(e.get("tss_weight") or 1.0),
        })
    return out


def fill_strength(
    pattern: dict,
    slot: dict,
    pool: list[dict],
    *,
    rng: random.Random | None = None,
    avoid_parts: set[str] | None = None,
) -> dict:
    rng = rng or random.Random()
    recipe = pattern.get("recipe") or {}
    bias = recipe.get("focus_bias") or {}
    primary = str(bias.get("primary_tag") or "full")
    primary_frac = float(bias.get("primary") or 0.8)
    groups = recipe.get("groups") or []
    used: set[str] = set()
    exercises: list[dict] = []

    for g in groups:
        label = g.get("label") or g.get("key") or "Main"
        pick = g.get("pick") or {}
        n = int(pick.get("n") or 1)
        tags = _as_list(pick.get("from_tags")) or [g.get("key") or "standalone"]
        chosen = _pick_exercises(
            pool,
            group_keys=tags,
            n=n,
            primary_tag=primary,
            primary_frac=primary_frac,
            avoid_parts=avoid_parts,
            rng=rng,
            used_names=used,
        )
        for c in chosen:
            c["block"] = label
            exercises.append(c)

    # Clamp to validator 4–10
    if len(exercises) > 10:
        exercises = exercises[:10]
    while len(exercises) < 4 and pool:
        extra = _pick_exercises(
            pool, group_keys=["accessories", "standalone"], n=1,
            primary_tag=primary, primary_frac=primary_frac,
            avoid_parts=avoid_parts, rng=rng, used_names=used,
        )
        if not extra:
            break
        for c in extra:
            c["block"] = c.get("block") or "Accessories"
            exercises.append(c)
        if len(exercises) >= 4:
            break

    clean = []
    footprint: dict[str, float] = {}
    for e in exercises:
        for p in e.pop("_body_parts", []) or []:
            if isinstance(p, dict) and p.get("part"):
                footprint[str(p["part"])] = footprint.get(str(p["part"]), 0.0) + float(p.get("ratio") or 0) * float(e.get("_tss_weight") or 1)
        e.pop("_tss_weight", None)
        clean.append(e)

    return {
        "intent": (recipe.get("intent_template") or "Strength")[:140],
        "notes": recipe.get("notes_template"),
        "blocks": None,
        "exercises": clean,
        "source": "pattern",
        "pattern_name": pattern.get("name"),
        "_muscle_footprint": footprint,
    }


def fill_slot(
    slot: dict,
    *,
    db: Session | None = None,
    week_ctx: dict | None = None,
    current: dict | None = None,
    rng: random.Random | None = None,
    avoid_parts: set[str] | None = None,
) -> dict:
    """Fill one slot from patterns. Falls back to template_content_for_slot."""
    slot = dict(slot)
    slot["subtype"] = normalize_slot_subtype(slot.get("workout_type"), slot.get("subtype"))
    wt = str(slot.get("workout_type") or "").lower()

    if wt == "rest" or slot.get("locked"):
        out = template_content_for_slot(slot)
        out["source"] = "template" if wt == "rest" else (current or {}).get("source") or "user"
        if current and current.get("source") == "user":
            return {**current, "source": "user"}
        return out

    if current and current.get("source") == "user":
        return {**current, "source": "user"}

    pattern = select_pattern(
        db,
        workout_type=wt,
        subtype=slot.get("subtype"),
        duration_min=int(slot.get("duration_minutes") or 0),
    )
    rng = rng or random.Random(hash((slot.get("day_offset"), slot.get("subtype"), slot.get("target_tss"))) & 0xFFFFFFFF)

    content: dict | None = None
    if pattern and wt == "run":
        content = fill_run(pattern, slot)
    elif pattern and wt in ("strength", "plyo"):
        pool = _load_exercise_pool(db)
        content = fill_strength(pattern, slot, pool, rng=rng, avoid_parts=avoid_parts)
    else:
        content = template_content_for_slot(slot)
        content["source"] = "template"

    # Validate; one retry with different RNG seed
    week_ctx = week_ctx or {"skeleton_slots": [slot]}
    errs = validate_slot(content, slot, week_ctx)
    if errs and pattern and wt in ("strength", "plyo"):
        content = fill_strength(
            pattern, slot, _load_exercise_pool(db),
            rng=random.Random(rng.random()),
            avoid_parts=avoid_parts,
        )
        errs = validate_slot(content, slot, week_ctx)
    if errs and wt == "run" and pattern:
        # Fall back to hardcoded template scaling
        content = template_content_for_slot(slot)
        content["source"] = "template"
    elif errs:
        content = template_content_for_slot(slot)
        content["source"] = "template"

    content["source"] = content.get("source") or "pattern"
    return content


def fill_and_stamp(
    slot: dict,
    *,
    db: Session | None = None,
    week_ctx: dict | None = None,
    current: dict | None = None,
    avoid_parts: set[str] | None = None,
) -> dict:
    content = fill_slot(
        slot, db=db, week_ctx=week_ctx, current=current, avoid_parts=avoid_parts,
    )
    footprint = content.pop("_muscle_footprint", None)
    stamped = stamp_session(slot, content)
    stamped["source"] = content.get("source") or "pattern"
    if footprint:
        stamped["_muscle_footprint"] = footprint
    if content.get("pattern_name"):
        stamped["pattern_name"] = content["pattern_name"]
    return stamped


def seed_defaults(db: Session, *, reset: bool = False) -> dict:
    """Upsert seed patterns/exercises. If reset, deactivate non-seed names first (soft)."""
    from backend.models import PlanExercise, PlanPattern
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    n_pat = n_ex = 0
    for p in all_default_patterns():
        row = (
            db.query(PlanPattern)
            .filter_by(kind=p["kind"], subtype=p["subtype"], name=p["name"])
            .first()
        )
        if row is None:
            row = PlanPattern(
                kind=p["kind"],
                subtype=p["subtype"],
                duration_min_lo=p["duration_min_lo"],
                duration_min_hi=p["duration_min_hi"],
                name=p["name"],
                priority=p["priority"],
                recipe=copy.deepcopy(p["recipe"]),
                active=True,
            )
            db.add(row)
            n_pat += 1
        elif reset:
            row.recipe = copy.deepcopy(p["recipe"])
            row.duration_min_lo = p["duration_min_lo"]
            row.duration_min_hi = p["duration_min_hi"]
            row.priority = p["priority"]
            row.active = True
            row.updated_at = now
            n_pat += 1

    for e in default_exercises():
        row = db.query(PlanExercise).filter_by(name=e["name"]).first()
        if row is None:
            db.add(PlanExercise(
                name=e["name"],
                groups=e["groups"],
                focus_tags=e["focus_tags"],
                body_parts=e["body_parts"],
                tss_weight=e["tss_weight"],
                default_sets=e["default_sets"],
                default_reps=e["default_reps"],
                default_load=e["default_load"],
                active=True,
            ))
            n_ex += 1
        elif reset:
            row.groups = e["groups"]
            row.focus_tags = e["focus_tags"]
            row.body_parts = e["body_parts"]
            row.tss_weight = e["tss_weight"]
            row.default_sets = e["default_sets"]
            row.default_reps = e["default_reps"]
            row.default_load = e["default_load"]
            row.active = True
            row.updated_at = now
            n_ex += 1
    db.flush()
    return {"patterns_upserted": n_pat, "exercises_upserted": n_ex}
