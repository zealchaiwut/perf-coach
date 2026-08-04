"""Deterministic session content from plan_patterns + plan_exercises (no LLM)."""
from __future__ import annotations

import copy
import random
from typing import Any

from sqlalchemy.orm import Session

from backend.services.plan_pattern_seeds import all_default_patterns, default_exercises
from backend.services.plan_slot import (
    insert_mp_segment,
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

    # Pref long_run.mp_segment_min → last quality block before cooldown
    mp_min = int(
        slot.get("mp_segment_min")
        or (slot.get("structure_hints") or {}).get("mp_segment_min")
        or 0
    )
    notes = recipe.get("notes_template")
    intent = (recipe.get("intent_template") or "Run")[:140]
    if (slot.get("subtype") or "") == "long_run" and pinned >= 90:
        intent = "Aerobic long run — fuel mid-run"
    if (slot.get("subtype") or "") == "long_run" and mp_min > 0:
        blocks = insert_mp_segment(blocks, mp_min)
        intent = f"Aerobic long run — {mp_min} min MP before cooldown"
        notes = (notes or "")
        extra = f"Finish with {mp_min} min at marathon pace before cooldown."
        notes = f"{notes} {extra}".strip() if notes else extra

    return {
        "intent": intent,
        "notes": notes,
        "blocks": blocks,
        "exercises": None,
        "source": "pattern",
        "pattern_name": pattern.get("name"),
    }


_STRENGTH_REF_MIN = 45.0  # recipe pick.n is authored for ~this duration
# Rough minutes per exercise (sets + rest) used to turn time_share × duration
# into a pick count — so 25 min and 70 min don't land the same roster.
_MIN_PER_EX_BY_KEY: dict[str, float] = {
    "warmup": 3.0,
    "cooldown": 3.0,
    "heavy_compound": 8.0,
    "superset": 5.5,
    "standalone": 6.0,
    "accessories": 4.5,
    "bodyweight": 5.0,
    "plyo": 5.0,
    "isometric": 4.0,
}


def _scale_group_pick_n(group: dict, duration_min: int) -> tuple[int, dict]:
    """Map recipe pick.n + time_share onto this slot's duration.

    Returns (n, meta). n may be 0 → skip the group (short sessions drop
    trailing accessories first via low time_share allotments).
    """
    pick = group.get("pick") or {}
    base_n = max(1, int(pick.get("n") or 1))
    key = str(group.get("key") or "")
    share = float(group.get("time_share") or 0)
    pinned = max(15, int(duration_min or _STRENGTH_REF_MIN))
    scale = pinned / _STRENGTH_REF_MIN
    per = _MIN_PER_EX_BY_KEY.get(key, 6.0)

    if share > 0:
        allot = pinned * share
        from_time = int(round(allot / per))
    else:
        allot = None
        from_time = int(round(base_n * scale))

    # Near the authored duration: keep recipe n. Otherwise prefer time budget,
    # clamped so we don't explode past base_n+2.
    if abs(scale - 1.0) < 0.12:
        n = base_n
        reason = "near_ref"
    else:
        n = min(base_n + 2, max(0, from_time))
        # Always keep a minimal warm-up / stretch if the recipe has them
        if n == 0 and key in ("warmup", "cooldown"):
            n = 1
        # Keep at least one main lift / bodyweight block when present
        if n == 0 and key in ("heavy_compound", "bodyweight"):
            n = 1
        reason = "time_budget"

    n = min(4, int(n))
    return n, {
        "base_n": base_n,
        "scaled_n": n,
        "duration_min": pinned,
        "time_share": share,
        "allot_min": round(allot, 1) if allot is not None else None,
        "min_per_ex": per,
        "scale": round(scale, 2),
        "reason": reason,
    }


def _scale_sets(default_sets: int, duration_min: int) -> int:
    pinned = max(15, int(duration_min or _STRENGTH_REF_MIN))
    sets = int(default_sets or 3)
    if pinned < 35:
        return max(2, sets - 1)
    if pinned >= 60:
        return min(5, sets + 1)
    return sets


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
    duration_min: int | None = None,
) -> list[dict]:
    if n <= 0:
        return []
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
        sets = e.get("default_sets") or 3
        if duration_min is not None:
            sets = _scale_sets(int(sets), duration_min)
        out.append({
            "block": None,  # filled by caller
            "name": e["name"],
            "sets": sets,
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
    duration_min = int(slot.get("duration_minutes") or _STRENGTH_REF_MIN)
    used: set[str] = set()
    exercises: list[dict] = []
    pick_log: list[dict] = []

    for g in groups:
        label = g.get("label") or g.get("key") or "Main"
        pick = g.get("pick") or {}
        tags = _as_list(pick.get("from_tags")) or [g.get("key") or "standalone"]
        n, scale_meta = _scale_group_pick_n(g, duration_min)
        if n <= 0:
            pick_log.append({
                "label": label,
                "from_tags": tags,
                "n": 0,
                "picked": [],
                "skipped": True,
                **scale_meta,
            })
            continue
        chosen = _pick_exercises(
            pool,
            group_keys=tags,
            n=n,
            primary_tag=primary,
            primary_frac=primary_frac,
            avoid_parts=avoid_parts,
            rng=rng,
            used_names=used,
            duration_min=duration_min,
        )
        pick_log.append({
            "label": label,
            "from_tags": tags,
            "n": n,
            "picked": [c["name"] for c in chosen],
            **scale_meta,
        })
        for c in chosen:
            c["block"] = label
            exercises.append(c)

    # Clamp to validator 4–10
    if len(exercises) > 10:
        exercises = exercises[:10]
    while len(exercises) < 4 and pool:
        extra = _pick_exercises(
            pool, group_keys=["accessories", "standalone", "bodyweight"], n=1,
            primary_tag=primary, primary_frac=primary_frac,
            avoid_parts=avoid_parts, rng=rng, used_names=used,
            duration_min=duration_min,
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
        "_pick_log": pick_log,
        "_duration_min": duration_min,
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
    log: dict = {"steps": []}
    raw_sub = slot.get("subtype")
    slot = dict(slot)
    slot["subtype"] = normalize_slot_subtype(slot.get("workout_type"), slot.get("subtype"))
    wt = str(slot.get("workout_type") or "").lower()
    log["steps"].append({
        "op": "normalize_subtype",
        "workout_type": wt,
        "from": raw_sub,
        "to": slot.get("subtype"),
        "duration_minutes": slot.get("duration_minutes"),
        "target_tss": slot.get("target_tss"),
    })

    if wt == "rest" or slot.get("locked"):
        out = template_content_for_slot(slot)
        out["source"] = "template" if wt == "rest" else (current or {}).get("source") or "user"
        if current and current.get("source") == "user":
            kept = {**current, "source": "user"}
            kept["fill_log"] = {
                "steps": log["steps"] + [{"op": "keep_user", "reason": "source=user"}],
            }
            return kept
        log["steps"].append({"op": "template", "reason": "rest_or_locked"})
        out["fill_log"] = log
        return out

    if current and current.get("source") == "user":
        kept = {**current, "source": "user"}
        kept["fill_log"] = {
            "steps": log["steps"] + [{"op": "keep_user", "reason": "source=user"}],
        }
        return kept

    pattern = select_pattern(
        db,
        workout_type=wt,
        subtype=slot.get("subtype"),
        duration_min=int(slot.get("duration_minutes") or 0),
    )
    if pattern:
        log["steps"].append({
            "op": "select_pattern",
            "name": pattern.get("name"),
            "subtype": pattern.get("subtype"),
            "duration_band": [
                pattern.get("duration_min_lo"),
                pattern.get("duration_min_hi"),
            ],
            "priority": pattern.get("priority"),
        })
    else:
        log["steps"].append({
            "op": "select_pattern",
            "picked": None,
            "reason": "no matching active pattern for type/subtype/duration",
        })

    rng = rng or random.Random(hash((slot.get("day_offset"), slot.get("subtype"), slot.get("target_tss"))) & 0xFFFFFFFF)

    content: dict | None = None
    if pattern and wt == "run":
        content = fill_run(pattern, slot)
        phases = [
            {"phase": b.get("phase"), "duration_min": b.get("duration_min"),
             "repeat": b.get("repeat"), "target": b.get("target")}
            for b in (content.get("blocks") or [])
        ]
        log["steps"].append({
            "op": "fill_run",
            "pattern_name": content.get("pattern_name"),
            "phases": phases,
        })
    elif pattern and wt in ("strength", "plyo"):
        pool = _load_exercise_pool(db)
        content = fill_strength(pattern, slot, pool, rng=rng, avoid_parts=avoid_parts)
        pick_log = content.pop("_pick_log", None) or []
        log["steps"].append({
            "op": "fill_strength",
            "pattern_name": content.get("pattern_name"),
            "groups": pick_log,
            "exercise_count": len(content.get("exercises") or []),
            "blocks": sorted({
                str(e.get("block") or "") for e in (content.get("exercises") or [])
            }),
        })
    else:
        content = template_content_for_slot(slot)
        content["source"] = "template"
        log["steps"].append({
            "op": "template",
            "reason": "no_pattern",
            "intent": content.get("intent"),
        })

    # Validate; one retry with different RNG seed
    week_ctx = week_ctx or {"skeleton_slots": [slot]}
    errs = validate_slot(content, slot, week_ctx)
    if errs and pattern and wt in ("strength", "plyo"):
        log["steps"].append({"op": "validate", "ok": False, "errors": list(errs), "retry": True})
        content = fill_strength(
            pattern, slot, _load_exercise_pool(db),
            rng=random.Random(rng.random()),
            avoid_parts=avoid_parts,
        )
        pick_log = content.pop("_pick_log", None) or []
        log["steps"].append({
            "op": "fill_strength",
            "attempt": 2,
            "pattern_name": content.get("pattern_name"),
            "groups": pick_log,
            "exercise_count": len(content.get("exercises") or []),
            "blocks": sorted({
                str(e.get("block") or "") for e in (content.get("exercises") or [])
            }),
        })
        errs = validate_slot(content, slot, week_ctx)
    if errs and wt == "run" and pattern:
        log["steps"].append({"op": "validate", "ok": False, "errors": list(errs)})
        log["steps"].append({
            "op": "fallback",
            "to": "template",
            "reason": "validate_failed",
            "errors": list(errs),
        })
        content = template_content_for_slot(slot)
        content["source"] = "template"
    elif errs:
        log["steps"].append({"op": "validate", "ok": False, "errors": list(errs)})
        log["steps"].append({
            "op": "fallback",
            "to": "template",
            "reason": "validate_failed",
            "errors": list(errs),
        })
        content = template_content_for_slot(slot)
        content["source"] = "template"
    else:
        log["steps"].append({"op": "validate", "ok": True})

    content["source"] = content.get("source") or "pattern"
    content["fill_log"] = log
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
    fill_log = content.pop("fill_log", None)
    stamped = stamp_session(slot, content)
    stamped["source"] = content.get("source") or "pattern"
    if footprint:
        stamped["_muscle_footprint"] = footprint
    if content.get("pattern_name"):
        stamped["pattern_name"] = content["pattern_name"]
    if fill_log:
        stamped["fill_log"] = fill_log
    return stamped


def seed_defaults(db: Session, *, reset: bool = False) -> dict:
    """Upsert seed patterns/exercises. Always refreshes recipe/content for
    known seed keys so ship-default changes (e.g. light session recipe) land
    without requiring reset. If reset, also reactivates those rows."""
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
        else:
            row.recipe = copy.deepcopy(p["recipe"])
            row.duration_min_lo = p["duration_min_lo"]
            row.duration_min_hi = p["duration_min_hi"]
            row.priority = p["priority"]
            if reset:
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
        else:
            row.groups = e["groups"]
            row.focus_tags = e["focus_tags"]
            row.body_parts = e["body_parts"]
            row.tss_weight = e["tss_weight"]
            row.default_sets = e["default_sets"]
            row.default_reps = e["default_reps"]
            row.default_load = e["default_load"]
            if reset:
                row.active = True
            row.updated_at = now
            n_ex += 1
    db.flush()
    return {"patterns_upserted": n_pat, "exercises_upserted": n_ex}
