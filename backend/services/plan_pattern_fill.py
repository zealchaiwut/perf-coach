"""Deterministic session content from plan_patterns + plan_exercises (no LLM)."""
from __future__ import annotations

import copy
import random
from typing import Any

from sqlalchemy.orm import Session

from backend.services.plan_pattern_seeds import all_default_patterns, default_exercises
from backend.services.muscle_load import normalize_part
from backend.services.plan_slot import (
    insert_mp_segment,
    normalize_slot_subtype,
    stamp_session,
    template_content_for_slot,
    validate_slot,
)
from backend.utils.log import get_logger

_log = get_logger(__name__)

# Pool is "thin" when matched candidates < pick_n × this multiplier.
THIN_POOL_MULTIPLIER = 2


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return list(v)


def match_exercises_for_tags(
    pool: list[dict],
    group_keys: list[str],
    *,
    used_names: set[str] | None = None,
) -> list[dict]:
    """Candidate filter shared by fill picks and pool-counts.

    An exercise matches when any of its ``groups`` intersects ``group_keys``.
    ``used_names`` excludes already-picked names (fill path only).
    """
    keys = [str(g) for g in group_keys if g]
    if not keys:
        return []
    used = used_names or set()
    return [
        e for e in pool
        if e.get("name") not in used
        and any(g in _as_list(e.get("groups")) for g in keys)
    ]


def _group_pool_tags(group: dict) -> list[str]:
    """Tags a recipe group draws from (union across format_choices when present)."""
    pick = group.get("pick") or {}
    key = str(group.get("key") or "")
    base = _as_list(pick.get("from_tags")) or ([key] if key else ["standalone"])
    base = [str(t) for t in base if t]
    choices = [str(c) for c in _as_list(group.get("format_choices")) if c]
    fixed = group.get("format")
    formats = choices or ([str(fixed)] if fixed else [])
    if not formats:
        return base
    tags: set[str] = set(base)
    for fmt in formats:
        tags.update(_format_tags(fmt, base))
    return sorted(tags)


def compute_pool_counts(
    pattern: dict,
    pool: list[dict],
    *,
    duration_min: int,
) -> dict[str, Any]:
    """Per-block matched counts using the same tag matcher as fill.

    ``matched_total`` is the unique union across active-band groups.
    """
    recipe = pattern.get("recipe") or {}
    groups, band_meta = resolve_groups_for_duration(recipe, duration_min)
    blocks: list[dict] = []
    seen: set[str] = set()
    for g in groups:
        key = str(g.get("key") or "")
        label = str(g.get("label") or key or "Main")
        pick = g.get("pick") or {}
        pick_n = max(0, int(pick.get("n") or 0))
        tags = _group_pool_tags(g)
        matched = match_exercises_for_tags(pool, tags)
        for e in matched:
            name = e.get("name")
            if name:
                seen.add(str(name))
        count = len(matched)
        thin = bool(pick_n > 0 and count < pick_n * THIN_POOL_MULTIPLIER)
        blocks.append({
            "key": key,
            "label": label,
            "from_tags": tags,
            "pick_n": pick_n,
            "matched_count": count,
            "thin": thin,
        })
    thin_blocks = [b for b in blocks if b["thin"]]
    return {
        "pattern_name": pattern.get("name"),
        "subtype": pattern.get("subtype"),
        "duration_min": int(duration_min),
        "band": band_meta.get("band"),
        "thin_pool_multiplier": THIN_POOL_MULTIPLIER,
        "matched_total": len(seen),
        "blocks": blocks,
        "thin_blocks": [
            {"key": b["key"], "label": b["label"], "matched_count": b["matched_count"],
             "pick_n": b["pick_n"]}
            for b in thin_blocks
        ],
    }


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
    """Scale a run recipe to pinned duration; annotate per-block TSS + muscle load.

    Repeated mains: ``duration_min`` is **per-rep work**. Wall time for the
    phase is ``duration_min × repeat + rest_min × (repeat − 1)``, carved out of
    the phase's duration_share bucket (so rest is not free).
    """
    recipe = pattern.get("recipe") or {}
    pinned = int(slot.get("duration_minutes") or 0) or 45
    subtype = str(slot.get("subtype") or pattern.get("subtype") or "")
    target_tss = float(slot.get("target_tss") or 0)
    blocks_in = recipe.get("blocks") or []
    blocks: list[dict] = []
    shares = [float(b.get("duration_share") or 0) for b in blocks_in]
    share_sum = sum(shares) or 1.0
    allocated = 0
    for i, b in enumerate(blocks_in):
        phase = str(b.get("phase") or "main")
        bb: dict[str, Any] = {
            "phase": phase,
            "repeat": b.get("repeat"),
            "rest_min": b.get("rest_min"),
            "target": b.get("target"),
            "pace_mult": _resolve_pace_mult(b, phase=phase, subtype=subtype),
        }
        if i == len(blocks_in) - 1:
            phase_min = max(1, pinned - allocated)
        else:
            share = float(b.get("duration_share") or 0) / share_sum
            phase_min = max(1, int(round(pinned * share)))
            allocated += phase_min

        rep = int(bb.get("repeat") or 0)
        rest = float(bb.get("rest_min") or 0)
        if rep > 1:
            rest_total = rest * max(0, rep - 1)
            work_budget = max(rep, int(phase_min - rest_total))
            per = max(1, int(round(work_budget / rep)))
            # Prefer staying inside the phase bucket when rounding overshoots.
            while per > 1 and per * rep + rest_total > phase_min + 1:
                per -= 1
            bb["duration_min"] = per
            bb["block_min"] = per * rep + rest_total
        else:
            bb["duration_min"] = phase_min
            bb["block_min"] = phase_min
            bb["repeat"] = None
        blocks.append(bb)

    # Pref long_run.mp_segment_min → last quality block before cooldown
    mp_min = int(
        slot.get("mp_segment_min")
        or (slot.get("structure_hints") or {}).get("mp_segment_min")
        or 0
    )
    notes = recipe.get("notes_template")
    intent = (recipe.get("intent_template") or "Run")[:140]
    if subtype == "long_run" and pinned >= 90:
        intent = "Aerobic long run — fuel mid-run"
    if subtype == "long_run" and mp_min > 0:
        blocks = insert_mp_segment(blocks, mp_min)
        for b in blocks:
            if b.get("phase") == "mp" and b.get("pace_mult") is None:
                b["pace_mult"] = 1.05
            rep = max(1, int(b.get("repeat") or 1))
            rest_t = float(b.get("rest_min") or 0) * max(0, rep - 1)
            b["block_min"] = float(b.get("duration_min") or 0) * rep + rest_t
        intent = f"Aerobic long run — {mp_min} min MP before cooldown"
        notes = (notes or "")
        extra = f"Finish with {mp_min} min at marathon pace before cooldown."
        notes = f"{notes} {extra}".strip() if notes else extra

    _annotate_run_block_tss(blocks, target_tss)
    footprint = _run_muscle_footprint(subtype, target_tss)

    # Telemetry-only trace of scaled phases (no selection RNG — runs are deterministic).
    remain_tss = float(target_tss)
    remain_min = float(pinned)
    budget_trace: list[dict] = [{
        "op": "budget_start",
        "remain_tss": round(remain_tss, 1),
        "remain_min": round(remain_min, 1),
        "target_tss": round(target_tss, 1),
        "duration_min": pinned,
        "kind": "run",
    }]
    for b in blocks:
        phase = str(b.get("phase") or "main")
        spend_tss = float(b.get("spend_tss") or 0)
        spend_min = float(b.get("block_min") or b.get("duration_min") or 0)
        rep = int(b.get("repeat") or 0) or 1
        budget_trace.append({
            "op": "group_open",
            "key": phase,
            "label": phase,
            "n": rep,
            "group_tss": round(spend_tss, 1),
            "group_min": round(spend_min, 1),
            "from_tags": [],
        })
        remain_tss = max(0.0, remain_tss - spend_tss)
        remain_min = max(0.0, remain_min - spend_min)
        budget_trace.append({
            "op": "budget_pick",
            "name": phase,
            "block": phase,
            "kind": "run",
            "duration_min": b.get("duration_min"),
            "block_min": spend_min,
            "repeat": b.get("repeat"),
            "rest_min": b.get("rest_min"),
            "target": b.get("target"),
            "pace_mult": b.get("pace_mult"),
            "spend_tss": round(spend_tss, 1),
            "spend_min": round(spend_min, 1),
            "remain_tss_after": round(remain_tss, 1),
            "remain_min_after": round(remain_min, 1),
        })
    budget_trace.append({
        "op": "budget_end",
        "remain_tss": round(remain_tss, 1),
        "remain_min": round(remain_min, 1),
        "exercise_count": len(blocks),
        "kind": "run",
    })

    return {
        "intent": intent,
        "notes": notes,
        "blocks": blocks,
        "exercises": None,
        "source": "pattern",
        "pattern_name": pattern.get("name"),
        "_muscle_footprint": footprint,
        "_budget_trace": budget_trace,
    }


# Pace vs threshold (min/km multiplier — higher = slower). Used in Preview copy
# and as the intensity proxy for per-block TSS weights.
_DEFAULT_PACE_BY_PHASE: dict[str, float] = {
    "warmup": 1.20,
    "cooldown": 1.20,
    "mp": 1.05,
}
_DEFAULT_PACE_MAIN_BY_SUBTYPE: dict[str, float] = {
    "easy_run": 1.20,
    "easy": 1.20,
    "long_run": 1.18,
    "tempo": 1.02,
    "intervals": 0.92,
}

# Session muscle shares for runs — intervals tilt toward calf/shin.
_RUN_MUSCLE_BY_SUBTYPE: dict[str, dict[str, float]] = {
    "easy_run": {
        "calf": 0.20, "quad": 0.25, "hamstring": 0.20,
        "glute": 0.20, "hip": 0.05, "core": 0.10,
    },
    "easy": {
        "calf": 0.20, "quad": 0.25, "hamstring": 0.20,
        "glute": 0.20, "hip": 0.05, "core": 0.10,
    },
    "long_run": {
        "calf": 0.22, "quad": 0.24, "hamstring": 0.20,
        "glute": 0.20, "hip": 0.05, "core": 0.09,
    },
    "tempo": {
        "calf": 0.24, "quad": 0.24, "hamstring": 0.22,
        "glute": 0.18, "hip": 0.05, "core": 0.07,
    },
    "intervals": {
        "calf": 0.30, "quad": 0.26, "hamstring": 0.18,
        "glute": 0.14, "hip": 0.05, "core": 0.07,
    },
}


def _resolve_pace_mult(block: dict, *, phase: str, subtype: str) -> float:
    raw = block.get("pace_mult")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    if phase in _DEFAULT_PACE_BY_PHASE:
        return _DEFAULT_PACE_BY_PHASE[phase]
    return _DEFAULT_PACE_MAIN_BY_SUBTYPE.get(subtype, 1.20)


def _if_from_pace_mult(pace_mult: float) -> float:
    """Map threshold-pace multiplier → approx intensity factor (tempo ≈ 0.90)."""
    pm = max(0.5, float(pace_mult))
    return max(0.50, min(1.15, 0.9 * 1.02 / pm))


def _annotate_run_block_tss(blocks: list[dict], target_tss: float) -> None:
    """Distribute session TSS across blocks by IF² × minutes (work + easy rest)."""
    if target_tss <= 0 or not blocks:
        for b in blocks:
            b["spend_tss"] = 0.0
        return
    weights: list[float] = []
    for b in blocks:
        rep = max(1, int(b.get("repeat") or 1))
        work = float(b.get("duration_min") or 0) * rep
        rest_t = float(b.get("rest_min") or 0) * max(0, rep - 1)
        if_work = _if_from_pace_mult(float(b.get("pace_mult") or 1.20))
        if_rest = _if_from_pace_mult(1.20)
        weights.append((if_work ** 2) * work + (if_rest ** 2) * rest_t)
    total_w = sum(weights) or 1.0
    for b, w in zip(blocks, weights):
        b["spend_tss"] = round(target_tss * w / total_w, 1)
    # Fix rounding drift on the largest block
    drift = round(target_tss - sum(float(b.get("spend_tss") or 0) for b in blocks), 1)
    if drift and blocks:
        big = max(blocks, key=lambda x: float(x.get("spend_tss") or 0))
        big["spend_tss"] = round(float(big["spend_tss"]) + drift, 1)


def _run_muscle_footprint(subtype: str, target_tss: float) -> dict[str, float]:
    if target_tss <= 0:
        return {}
    profile = _RUN_MUSCLE_BY_SUBTYPE.get(subtype) or _RUN_MUSCLE_BY_SUBTYPE["easy_run"]
    return {k: round(float(v) * target_tss, 2) for k, v in profile.items() if v > 0}


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
    "finisher": 5.0,
    "emom": 1.0,  # sets ≈ minutes
}
# Minutes charged per set when spending the session time budget.
_MIN_PER_SET_BY_KEY: dict[str, float] = {
    "warmup": 1.5,
    "cooldown": 1.5,
    "heavy_compound": 3.5,
    "superset": 2.5,
    "standalone": 2.8,
    "accessories": 2.2,
    "bodyweight": 2.2,
    "plyo": 2.0,
    "isometric": 2.0,
    "finisher": 1.0,
    "emom": 1.0,
}

_FORMAT_LABELS = {
    "emom": "EMOM",
    "40_20": "40/20",
    "intervals_40_20": "40/20",
    "plyo": "Plyometrics",
}


def resolve_groups_for_duration(recipe: dict, duration_min: int) -> tuple[list[dict], dict]:
    """Pick the active group list for this slot duration.

    Prefer ``recipe.bands`` (cut / add whole blocks). Fall back to
    ``recipe.groups`` when bands are absent (legacy / admin-edited patterns).
    """
    pinned = max(1, int(duration_min or _STRENGTH_REF_MIN))
    bands = recipe.get("bands")
    if not isinstance(bands, list) or not bands:
        return list(recipe.get("groups") or []), {
            "source": "groups",
            "band": None,
            "duration_min": pinned,
        }
    for b in bands:
        if not isinstance(b, dict):
            continue
        lo = int(b.get("duration_min_lo") or 0)
        hi = int(b.get("duration_min_hi") or 10**9)
        if lo <= pinned <= hi:
            return list(b.get("groups") or []), {
                "source": "bands",
                "band": [lo, hi],
                "duration_min": pinned,
            }
    last = bands[-1] if isinstance(bands[-1], dict) else {}
    return list(last.get("groups") or recipe.get("groups") or []), {
        "source": "bands_fallback",
        "band": [
            last.get("duration_min_lo"),
            last.get("duration_min_hi"),
        ],
        "duration_min": pinned,
    }


def _resolve_group_format(group: dict, rng: random.Random) -> tuple[str | None, str]:
    """Return (format_key, display_label) for a recipe group."""
    choices = [str(c) for c in _as_list(group.get("format_choices")) if c]
    fmt = group.get("format")
    if choices:
        fmt = rng.choice(choices)
    elif fmt is not None:
        fmt = str(fmt)
    else:
        fmt = None
    base = str(group.get("label") or group.get("key") or "Main")
    if not fmt:
        return None, base
    pretty = _FORMAT_LABELS.get(fmt)
    if pretty and base.lower() in ("finisher", "main", "finisher block"):
        return fmt, pretty
    if pretty:
        return fmt, f"{base} · {pretty}"
    return fmt, base


def _format_tags(fmt: str | None, default_tags: list[str]) -> list[str]:
    if fmt == "emom":
        return ["emom"]
    if fmt in ("40_20", "intervals_40_20"):
        return ["emom", "bodyweight", "plyo"]
    if fmt == "plyo":
        return ["plyo"]
    return default_tags


def _apply_format_prescription(
    row: dict,
    fmt: str | None,
    *,
    block_min: float,
    n_picks: int,
) -> None:
    """Mutate sets/reps/load for timed finisher formats."""
    if not fmt:
        return
    if fmt == "emom":
        total = max(4, int(round(block_min)))
        mins = max(2, total // max(1, n_picks)) if n_picks > 1 else total
        row["sets"] = mins
        base_load = row.get("load") or "moderate"
        row["load"] = f"{base_load} — EMOM {total} min (work @ :00)"
        return
    if fmt in ("40_20", "intervals_40_20"):
        rounds = max(4, int(round(block_min)))
        each = max(2, rounds // max(1, n_picks)) if n_picks > 1 else rounds
        row["sets"] = each
        row["reps"] = "40s work"
        base_load = row.get("load") or "bodyweight"
        row["load"] = f"{base_load} — 20s rest ({rounds} rounds)"
        return


def _scale_group_pick_n(
    group: dict,
    duration_min: int,
    *,
    banded: bool = False,
) -> tuple[int, dict]:
    """Map recipe pick.n + time_share onto this slot's duration.

    When ``banded`` is True the recipe already chose which groups exist for
    this duration — keep authored ``pick.n`` (no skip/expand via time budget).

    Returns (n, meta). n may be 0 → skip the group (legacy non-banded only).
    """
    pick = group.get("pick") or {}
    base_n = max(1, int(pick.get("n") or 1))
    key = str(group.get("key") or "")
    share = float(group.get("time_share") or 0)
    pinned = max(15, int(duration_min or _STRENGTH_REF_MIN))

    if banded:
        # Warm-up / stretch / rotating finishers (EMOM·40/20·plyo): allow 2–4.
        # Authored pick.n is the target; clamp into that band so short recipes
        # stay modest and long ones can land a fuller circuit.
        flex = (
            key in ("warmup", "cooldown", "finisher")
            or bool(_as_list(group.get("format_choices")))
        )
        if flex:
            if pinned < 55:
                floor = 2
            elif pinned < 90:
                floor = 3
            else:
                floor = 4 if (
                    key == "finisher" or bool(_as_list(group.get("format_choices")))
                ) else 3
            n = min(4, max(floor, base_n))
        else:
            n = min(4, base_n)
        return n, {
            "base_n": base_n,
            "scaled_n": n,
            "duration_min": pinned,
            "time_share": share,
            "allot_min": round(pinned * share, 1) if share > 0 else None,
            "min_per_ex": _MIN_PER_EX_BY_KEY.get(key, 6.0),
            "scale": 1.0,
            "reason": "band_recipe",
        }

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
    # Warm-up / stretch / finishers: keep at least 2–3 even when time-budget scales down.
    if key in ("warmup", "cooldown", "finisher") or bool(_as_list(group.get("format_choices"))):
        floor = 2 if pinned < 55 else 3
        if n > 0:
            n = min(4, max(floor, n))
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


def _candidate_score(
    e: dict,
    *,
    primary_tag: str,
    primary_frac: float,
    avoid_parts: set[str] | None,
    rng: random.Random,
) -> tuple[float, float, float]:
    """Return (final_score, bias_score, random_factor)."""
    tags = set(_as_list(e.get("focus_tags")))
    bias = 1.0
    if primary_tag and primary_tag in tags:
        bias *= 1.0 + primary_frac
    elif primary_tag and primary_tag != "full" and "full" in tags:
        bias *= 0.7
    elif primary_tag and primary_tag not in tags and "core" not in tags:
        bias *= (1.0 - primary_frac) + 0.15
    if avoid_parts:
        parts = {str(p.get("part") or "") for p in _as_list(e.get("body_parts")) if isinstance(p, dict)}
        if parts & avoid_parts:
            bias *= 0.35
    jitter = 0.85 + 0.3 * rng.random()  # ~U(0.85, 1.15)
    return bias * jitter, bias, jitter


def _pick_one_exercise(
    pool: list[dict],
    *,
    group_keys: list[str],
    primary_tag: str,
    primary_frac: float,
    avoid_parts: set[str] | None,
    rng: random.Random,
    used_names: set[str],
    duration_min: int | None = None,
) -> tuple[dict | None, dict]:
    """Pick a single exercise; return (row_or_None, pick_meta with scores)."""
    candidates = match_exercises_for_tags(pool, group_keys, used_names=used_names)
    if not candidates:
        candidates = [e for e in pool if e.get("name") not in used_names] or list(pool)
    if not candidates:
        return None, {"candidates": 0}

    scored: list[tuple[dict, float, float, float]] = []
    for e in candidates:
        final, bias, jitter = _candidate_score(
            e, primary_tag=primary_tag, primary_frac=primary_frac,
            avoid_parts=avoid_parts, rng=rng,
        )
        scored.append((e, final, bias, jitter))
    scored.sort(key=lambda t: t[1], reverse=True)
    e, final, bias, jitter = scored[0]
    used_names.add(e["name"])
    sets = e.get("default_sets") or 3
    if duration_min is not None:
        sets = _scale_sets(int(sets), duration_min)
    row = {
        "block": None,
        "name": e["name"],
        "sets": sets,
        "reps": e.get("default_reps") or "10",
        "load": e.get("default_load") or "moderate",
        "_body_parts": _as_list(e.get("body_parts")),
        "_tss_weight": float(e.get("tss_weight") or 1.0),
    }
    top = [
        {
            "name": x[0]["name"],
            "score": round(x[1], 3),
            "bias": round(x[2], 3),
            "random": round(x[3], 3),
        }
        for x in scored[:3]
    ]
    return row, {
        "candidates": len(scored),
        "score": round(final, 3),
        "bias": round(bias, 3),
        "random": round(jitter, 3),
        "top": top,
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
    duration_min: int | None = None,
) -> list[dict]:
    """Pick up to n exercises one-by-one (re-roll random each time)."""
    if n <= 0:
        return []
    out: list[dict] = []
    for _ in range(n):
        row, _meta = _pick_one_exercise(
            pool,
            group_keys=group_keys,
            primary_tag=primary_tag,
            primary_frac=primary_frac,
            avoid_parts=avoid_parts,
            rng=rng,
            used_names=used_names,
            duration_min=duration_min,
        )
        if row is None:
            break
        out.append(row)
    return out


def _spend_for_pick(
    *,
    key: str,
    sets: int,
    tss_weight: float,
    remain_tss: float,
    remain_min: float,
    picks_left_in_group: int,
    group_tss_left: float,
    group_min_left: float,
) -> tuple[float, float]:
    """Estimate TSS + minutes this pick spends from the remaining budgets.

    Both TSS and minutes fair-share the remaining group budget across the
    picks still to take — otherwise pick #1 eats the whole time_share and
    later picks land at 0 min (still carrying TSS).
    """
    per_set = _MIN_PER_SET_BY_KEY.get(key, 2.5)
    raw_min = max(2.0, float(sets) * per_set)
    picks_left = max(1, int(picks_left_in_group))

    if picks_left <= 1:
        spend_tss = min(remain_tss, group_tss_left)
        # Last pick in the group takes whatever time is left (capped by session).
        spend_min = min(remain_min, group_min_left) if remain_min > 0 else group_min_left
    else:
        fair_tss = group_tss_left / picks_left
        spend_tss = fair_tss * max(0.5, float(tss_weight))
        spend_tss = min(remain_tss, group_tss_left, max(1.0, spend_tss))

        fair_min = group_min_left / picks_left
        # Prefer sets-based cost when it fits the fair share; otherwise take
        # the fair share so later picks still get time.
        spend_min = min(remain_min, group_min_left, max(1.0, min(raw_min, fair_min)))
        if remain_min <= 0:
            spend_min = max(1.0, min(raw_min, fair_min))

    return round(spend_tss, 1), round(spend_min, 1)


def fill_strength(
    pattern: dict,
    slot: dict,
    pool: list[dict],
    *,
    rng: random.Random | None = None,
    avoid_parts: set[str] | None = None,
    pre_placed: list[dict] | None = None,
) -> dict:
    """Fill a strength/plyo slot. Optional ``pre_placed`` pinned rows reduce
    per-block pick counts and remaining budget; scoring is unchanged.
    """
    from backend.services.session_pins import (
        count_pinned_in_block,
        ensure_exercise_pin_fields,
        exercise_spend,
        spend_pinned_in_block,
    )

    rng = rng or random.Random()
    recipe = pattern.get("recipe") or {}
    bias = recipe.get("focus_bias") or {}
    primary = str(bias.get("primary_tag") or "full")
    primary_frac = float(bias.get("primary") or 0.8)
    duration_min = int(slot.get("duration_minutes") or _STRENGTH_REF_MIN)
    target_tss = float(slot.get("target_tss") or 40)
    groups, band_meta = resolve_groups_for_duration(recipe, duration_min)
    banded = band_meta.get("source") in ("bands", "bands_fallback")

    placed = [ensure_exercise_pin_fields(e) for e in (pre_placed or []) if isinstance(e, dict)]
    exercises: list[dict] = [copy.deepcopy(e) for e in placed]
    used: set[str] = {
        str(e.get("name") or "").strip()
        for e in exercises if e.get("name")
    }
    pick_log: list[dict] = []
    budget_trace: list[dict] = []

    pinned_tss = 0.0
    pinned_min = 0.0
    for e in exercises:
        st, sm = exercise_spend(e)
        if e.get("spend_tss") is None:
            e["spend_tss"] = round(st, 1)
        if e.get("spend_min") is None:
            e["spend_min"] = round(sm, 1)
        pinned_tss += float(e["spend_tss"])
        pinned_min += float(e["spend_min"])

    remain_tss = float(target_tss) - pinned_tss
    remain_min = float(duration_min) - pinned_min
    budget_trace.append({
        "op": "budget_start",
        "remain_tss": round(max(0.0, remain_tss), 1),
        "remain_min": round(max(0.0, remain_min), 1),
        "target_tss": round(target_tss, 1),
        "duration_min": duration_min,
        "pre_placed": len(placed),
        "pinned_tss": round(pinned_tss, 1),
        "pinned_min": round(pinned_min, 1),
        "band": band_meta.get("band"),
        "groups_source": band_meta.get("source"),
    })

    for g in groups:
        fmt, label = _resolve_group_format(g, rng)
        key = str(g.get("key") or "")
        spend_key = fmt if fmt in ("emom", "40_20", "intervals_40_20") else key
        if spend_key in ("40_20", "intervals_40_20"):
            spend_key = "emom"
        pick = g.get("pick") or {}
        tags = _format_tags(fmt, _as_list(pick.get("from_tags")) or [key or "standalone"])
        n, scale_meta = _scale_group_pick_n(g, duration_min, banded=banded)
        pre_n = count_pinned_in_block(placed, key, label)
        n = max(0, n - pre_n)
        tss_share = float(g.get("tss_share") or 0)
        time_share = float(g.get("time_share") or 0)
        group_tss_left = target_tss * tss_share if tss_share > 0 else (target_tss / max(len(groups), 1))
        group_min_left = duration_min * time_share if time_share > 0 else (duration_min / max(len(groups), 1))
        pre_tss, pre_min = spend_pinned_in_block(placed, key, label)
        group_tss_left = max(0.0, group_tss_left - pre_tss)
        group_min_left = max(0.0, group_min_left - pre_min)
        block_min_budget = float(group_min_left)

        if n <= 0:
            pick_log.append({
                "label": label,
                "format": fmt,
                "from_tags": tags,
                "n": 0,
                "picked": [],
                "skipped": True,
                "pre_placed": pre_n,
                **scale_meta,
            })
            budget_trace.append({
                "op": "group_skip",
                "key": key,
                "label": label,
                "format": fmt,
                "reason": scale_meta.get("reason") or ("pre_placed_covers" if pre_n else None),
                "pre_placed": pre_n,
            })
            continue

        budget_trace.append({
            "op": "group_open",
            "key": key,
            "label": label,
            "format": fmt,
            "n": n,
            "pre_placed": pre_n,
            "group_tss": round(group_tss_left, 1),
            "group_min": round(group_min_left, 1),
            "from_tags": tags,
        })

        picked_names: list[str] = []
        pick_details: list[dict] = []
        for i in range(n):
            if remain_min < 2 and remain_tss < 1:
                budget_trace.append({
                    "op": "budget_exhausted",
                    "remain_tss": round(remain_tss, 1),
                    "remain_min": round(remain_min, 1),
                })
                break

            budget_trace.append({
                "op": "budget_remain",
                "remain_tss": round(max(0.0, remain_tss), 1),
                "remain_min": round(max(0.0, remain_min), 1),
            })

            # Timed formats own sets (= minutes / rounds); don't also bump via duration.
            row, meta = _pick_one_exercise(
                pool,
                group_keys=tags,
                primary_tag=primary,
                primary_frac=primary_frac,
                avoid_parts=avoid_parts,
                rng=rng,
                used_names=used,
                duration_min=None if fmt in ("emom", "40_20", "intervals_40_20") else duration_min,
            )
            if row is None:
                break

            _apply_format_prescription(
                row, fmt, block_min=block_min_budget, n_picks=n,
            )

            picks_left = n - i
            spend_tss, spend_min = _spend_for_pick(
                key=spend_key or key,
                sets=int(row["sets"] or 3),
                tss_weight=float(row.get("_tss_weight") or 1.0),
                remain_tss=max(remain_tss, 0.0),
                remain_min=max(remain_min, 0.0),
                picks_left_in_group=picks_left,
                group_tss_left=group_tss_left,
                group_min_left=group_min_left,
            )
            remain_tss = max(0.0, remain_tss - spend_tss)
            remain_min = max(0.0, remain_min - spend_min)
            group_tss_left = max(0.0, group_tss_left - spend_tss)
            group_min_left = max(0.0, group_min_left - spend_min)

            row["block"] = label
            row["spend_tss"] = spend_tss
            row["spend_min"] = spend_min
            row["source"] = "generated"
            row["pinned"] = False
            row["state"] = "done"
            exercises.append(row)
            picked_names.append(row["name"])
            pick_details.append({
                "name": row["name"],
                "sets": row["sets"],
                "reps": row["reps"],
                "load": row["load"],
                "spend_tss": spend_tss,
                "spend_min": spend_min,
                **meta,
            })
            budget_trace.append({
                "op": "budget_pick",
                "block": label,
                "format": fmt,
                "name": row["name"],
                "sets": row["sets"],
                "reps": row["reps"],
                "load": row["load"],
                "spend_tss": spend_tss,
                "spend_min": spend_min,
                "score": meta.get("score"),
                "bias": meta.get("bias"),
                "random": meta.get("random"),
                "top": meta.get("top"),
                "remain_tss_after": round(remain_tss, 1),
                "remain_min_after": round(remain_min, 1),
            })

        pick_log.append({
            "label": label,
            "format": fmt,
            "from_tags": tags,
            "n": n,
            "pre_placed": pre_n,
            "picked": picked_names,
            "picks": pick_details,
            **scale_meta,
        })

    # Clamp to validator 4–16 — never drop pre-placed pinned rows.
    if len(exercises) > 16:
        pinned_part = exercises[:len(placed)]
        generated_part = exercises[len(placed):]
        keep_gen = max(0, 16 - len(pinned_part))
        exercises = pinned_part + generated_part[:keep_gen]
    while len(exercises) < 4 and pool:
        budget_trace.append({
            "op": "budget_remain",
            "remain_tss": round(max(0.0, remain_tss), 1),
            "remain_min": round(max(0.0, remain_min), 1),
            "note": "pad_to_min_4",
        })
        row, meta = _pick_one_exercise(
            pool,
            group_keys=["accessories", "standalone", "bodyweight"],
            primary_tag=primary,
            primary_frac=primary_frac,
            avoid_parts=avoid_parts,
            rng=rng,
            used_names=used,
            duration_min=duration_min,
        )
        if row is None:
            break
        spend_tss, spend_min = _spend_for_pick(
            key="accessories",
            sets=int(row["sets"] or 3),
            tss_weight=float(row.get("_tss_weight") or 1.0),
            remain_tss=max(remain_tss, 1.0),
            remain_min=max(remain_min, 2.0),
            picks_left_in_group=1,
            group_tss_left=max(remain_tss, 1.0),
            group_min_left=max(remain_min, 2.0),
        )
        remain_tss = max(0.0, remain_tss - spend_tss)
        remain_min = max(0.0, remain_min - spend_min)
        row["block"] = row.get("block") or "Accessories"
        row["spend_tss"] = spend_tss
        row["spend_min"] = spend_min
        row["source"] = "generated"
        row["pinned"] = False
        row["state"] = "done"
        exercises.append(row)
        budget_trace.append({
            "op": "budget_pick",
            "block": "Accessories",
            "name": row["name"],
            "sets": row["sets"],
            "reps": row["reps"],
            "load": row["load"],
            "spend_tss": spend_tss,
            "spend_min": spend_min,
            "score": meta.get("score"),
            "bias": meta.get("bias"),
            "random": meta.get("random"),
            "top": meta.get("top"),
            "remain_tss_after": round(remain_tss, 1),
            "remain_min_after": round(remain_min, 1),
            "note": "pad_to_min_4",
        })
        if len(exercises) >= 4:
            break

    budget_trace.append({
        "op": "budget_end",
        "remain_tss": round(remain_tss, 1),
        "remain_min": round(remain_min, 1),
        "exercise_count": len(exercises),
    })

    clean = []
    footprint: dict[str, float] = {}
    for e in exercises:
        spend = float(e.get("spend_tss") if e.get("spend_tss") is not None else (e.get("_tss_weight") or 1.0))
        for p in e.pop("_body_parts", []) or []:
            if isinstance(p, dict) and p.get("part"):
                group = normalize_part(str(p["part"]))
                footprint[group] = footprint.get(group, 0.0) + float(p.get("ratio") or 0) * spend
        e.pop("_tss_weight", None)
        clean.append(e)
    footprint = {k: round(v, 2) for k, v in footprint.items() if v > 0}

    return {
        "intent": (recipe.get("intent_template") or "Strength")[:140],
        "notes": recipe.get("notes_template"),
        "blocks": None,
        "exercises": clean,
        "source": "pattern",
        "pattern_name": pattern.get("name"),
        "_muscle_footprint": footprint,
        "_pick_log": pick_log,
        "_budget_trace": budget_trace,
        "_duration_min": duration_min,
        "_band": band_meta,
    }


def fill_slot(
    slot: dict,
    *,
    db: Session | None = None,
    week_ctx: dict | None = None,
    current: dict | None = None,
    rng: random.Random | None = None,
    avoid_parts: set[str] | None = None,
    respect_exercise_pins: bool = False,
) -> dict:
    """Fill one slot from patterns. Falls back to template_content_for_slot.

    When ``respect_exercise_pins`` is True (session-modal Refill), pinned
    exercise rows are pre-placed and only unpinned rows are replaced. The
    whole-session ``source=user`` keep is skipped so Refill can run.
    """
    from backend.services.session_pins import refill_contract, split_pinned_exercises

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
        if current and current.get("source") == "user" and not respect_exercise_pins:
            kept = {**current, "source": "user"}
            kept["fill_log"] = {
                "steps": log["steps"] + [{"op": "keep_user", "reason": "source=user"}],
            }
            return kept
        log["steps"].append({"op": "template", "reason": "rest_or_locked"})
        out["fill_log"] = log
        return out

    if current and current.get("source") == "user" and not respect_exercise_pins:
        kept = {**current, "source": "user"}
        kept["fill_log"] = {
            "steps": log["steps"] + [{"op": "keep_user", "reason": "source=user"}],
        }
        return kept

    pre_placed: list[dict] = []
    if respect_exercise_pins and current:
        contract = refill_contract(
            target_tss=slot.get("target_tss"),
            duration_minutes=slot.get("duration_minutes"),
            exercises=current.get("exercises"),
        )
        log["steps"].append({"op": "refill_contract", **contract})
        if not contract["ok"]:
            # Surface as a soft failure — callers map refill_blocked → 422.
            blocked = {
                "intent": current.get("intent"),
                "notes": current.get("notes"),
                "blocks": current.get("blocks"),
                "exercises": current.get("exercises"),
                "source": current.get("source") or "user",
                "refill_blocked": True,
                "refill_reason": contract["reason"],
                "refill_contract": contract,
                "fill_log": log,
            }
            return blocked
        pre_placed, _unpinned = split_pinned_exercises(current.get("exercises"))

    # Homework ladder: always pre-place active weekly_focus / required_exercises
    # that match this session type (Pass 5). Merged into whatever pins Refill
    # already kept — does not change fill scoring.
    if wt in ("strength", "plyo"):
        try:
            from backend.services.session_homework import pre_place_for_slot
            prefs_payload = (week_ctx or {}).get("prefs_payload") or (week_ctx or {}).get("prefs")
            as_of = (week_ctx or {}).get("as_of")
            hw_rows = pre_place_for_slot(
                prefs_payload,
                wt,
                as_of=as_of,
                pool=_load_exercise_pool(db) if db is not None else None,
                existing=pre_placed,
            )
            if hw_rows:
                pre_placed = list(pre_placed) + hw_rows
                log["steps"].append({
                    "op": "homework_pre_place",
                    "count": len(hw_rows),
                    "names": [r.get("name") for r in hw_rows],
                })
        except Exception:
            _log.warning("homework pre_place failed", exc_info=True)

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
        budget_trace = content.pop("_budget_trace", None) or []
        log["budget_trace"] = budget_trace
        log["steps"].append({
            "op": "fill_run",
            "pattern_name": content.get("pattern_name"),
            "phases": phases,
            "budget_trace": budget_trace,
        })
    elif pattern and wt in ("strength", "plyo"):
        pool = _load_exercise_pool(db)
        content = fill_strength(
            pattern, slot, pool, rng=rng, avoid_parts=avoid_parts,
            pre_placed=pre_placed or None,
        )
        pick_log = content.pop("_pick_log", None) or []
        budget_trace = content.pop("_budget_trace", None) or []
        band_meta = content.pop("_band", None) or {}
        log["budget_trace"] = budget_trace
        log["steps"].append({
            "op": "fill_strength",
            "pattern_name": content.get("pattern_name"),
            "band": band_meta.get("band"),
            "groups_source": band_meta.get("source"),
            "groups": pick_log,
            "budget_trace": budget_trace,
            "exercise_count": len(content.get("exercises") or []),
            "pre_placed": len(pre_placed),
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
            pre_placed=pre_placed or None,
        )
        pick_log = content.pop("_pick_log", None) or []
        budget_trace = content.pop("_budget_trace", None) or []
        log["budget_trace"] = budget_trace
        log["steps"].append({
            "op": "fill_strength",
            "attempt": 2,
            "pattern_name": content.get("pattern_name"),
            "groups": pick_log,
            "budget_trace": budget_trace,
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
