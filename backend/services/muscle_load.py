"""muscle_load — TSS-weighted muscle-group ledger writer for strength workouts (issue #1367).

Canonical muscle groups
-----------------------
calf, quad, hamstring, glute, hip, core, back, shoulder, chest, arm, other

Distribution algorithm (strength)
----------------------------------
For a strength workout/session with total TSS = T:
  1. Compute each exercise's raw volume:
       volume_i = sets_i × reps_i × weight_kg_i
     Fallbacks (named constants below):
       - missing weight_kg → sets_i × reps_i   (weight treated as 1)
       - missing reps → sets_i × DEFAULT_REPS
       - all missing (no sets, reps, weight) → each exercise gets an equal share
  2. exercise_share_i = volume_i / Σ volume_j   (equal share when all volumes == 0)
  3. For each exercise look up catalog body_parts ratios {part: ratio}.
     Normalize each part to a canonical muscle group (unmapped → "other").
  4. muscle_load[group] += T × exercise_share_i × ratio_k

The writer then upserts one row per muscle group into muscle_load_daily, replacing
any prior strength contribution for that (user, date) so re-runs never double-count.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date as _date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.db import engine

_log = logging.getLogger(__name__)

# ── Fallback constants ─────────────────────────────────────────────────────────

DEFAULT_REPS: int = 10
"""Substitute reps value when the exercise has sets but no reps."""

DEFAULT_WEIGHT: float = 1.0
"""Substitute weight when computing volume but no weight was logged (sets × reps only)."""

# ── Canonical muscle groups ────────────────────────────────────────────────────

MUSCLE_GROUPS: frozenset[str] = frozenset({
    "calf", "quad", "hamstring", "glute", "hip",
    "core", "back", "shoulder", "chest", "arm", "other",
})

# Maps catalog `part` strings → canonical group.
# Keys are lowercase (matching exercise_classifier VALID_BODY_PARTS + common variants).
MUSCLE_GROUP_MAP: dict[str, str] = {
    # calf
    "calves": "calf",
    "calf": "calf",
    "soleus": "calf",
    "gastrocnemius": "calf",
    # quad
    "quads": "quad",
    "quad": "quad",
    "quadriceps": "quad",
    # hamstring
    "hamstrings": "hamstring",
    "hamstring": "hamstring",
    # glute
    "glutes": "glute",
    "glute": "glute",
    "gluteus": "glute",
    "gluteus maximus": "glute",
    # hip
    "hip": "hip",
    "hip flexors": "hip",
    "hip flexor": "hip",
    # core
    "core": "core",
    "abs": "core",
    "abdominals": "core",
    "obliques": "core",
    "oblique": "core",
    # back
    "back": "back",
    "lats": "back",
    "latissimus": "back",
    "latissimus dorsi": "back",
    "rhomboids": "back",
    "rhomboid": "back",
    "traps": "back",
    "trapezius": "back",
    "lower back": "back",
    "erector spinae": "back",
    # shoulder
    "shoulders": "shoulder",
    "shoulder": "shoulder",
    "deltoids": "shoulder",
    "delts": "shoulder",
    "rotator cuff": "shoulder",
    # chest
    "chest": "chest",
    "pecs": "chest",
    "pectorals": "chest",
    "pectoral": "chest",
    # arm
    "biceps": "arm",
    "triceps": "arm",
    "forearms": "arm",
    "forearm": "arm",
    "arms": "arm",
    "arm": "arm",
    "brachialis": "arm",
}

# Maps injury-log body_area strings → canonical muscle group (issue #1373).
# Covers left/right variants for lower-body areas most relevant to running.
BODY_AREA_TO_MUSCLE_GROUP: dict[str, str] = {
    # calf
    "calf": "calf",
    "left_calf": "calf",
    "right_calf": "calf",
    # hamstring
    "hamstring": "hamstring",
    "left_hamstring": "hamstring",
    "right_hamstring": "hamstring",
    # glute
    "glute": "glute",
    "left_glute": "glute",
    "right_glute": "glute",
    "gluteus": "glute",
    # quad
    "quad": "quad",
    "left_quad": "quad",
    "right_quad": "quad",
    "quadriceps": "quad",
    # hip
    "hip": "hip",
    "left_hip": "hip",
    "right_hip": "hip",
    # knee
    "knee": "quad",
    "left_knee": "quad",
    "right_knee": "quad",
    # shin / lower leg
    "shin": "calf",
    "left_shin": "calf",
    "right_shin": "calf",
    "achilles": "calf",
    "left_achilles": "calf",
    "right_achilles": "calf",
    # plantar
    "plantar": "calf",
    "left_plantar": "calf",
    "right_plantar": "calf",
    # back
    "lower_back": "back",
    "back": "back",
    # shoulder / arm
    "shoulder": "shoulder",
    "left_shoulder": "shoulder",
    "right_shoulder": "shoulder",
}


def normalize_part(part: str) -> str:
    """Normalize a catalog body-part string to a canonical muscle group.

    Unknown parts map to 'other' — never dropped.
    """
    return MUSCLE_GROUP_MAP.get(part.strip().lower(), "other")


# ── Volume calculation ─────────────────────────────────────────────────────────

def _exercise_volume(sets: Any, reps: Any, weight_kg: Any) -> float:
    """Compute raw volume for one exercise with fallback constants.

    Fallback order:
      sets × reps × weight_kg   (all present)
      sets × reps               (missing weight)
      sets × DEFAULT_REPS       (missing reps)
      DEFAULT_REPS              (no sets either; equal split handled upstream)
    """
    s = int(sets) if sets is not None else None
    r = int(reps) if reps is not None else None
    w = float(weight_kg) if weight_kg is not None else None

    if s is None and r is None and w is None:
        return 0.0  # caller treats 0 volume as equal-share

    effective_sets = s if s is not None else 1
    effective_reps = r if r is not None else DEFAULT_REPS
    effective_weight = w if w is not None else DEFAULT_WEIGHT
    return float(effective_sets) * float(effective_reps) * effective_weight


# ── Core distribution logic (pure, no DB) ─────────────────────────────────────

def distribute_strength_tss(
    tss: float,
    exercises: list[dict],
    catalog: dict[str, list[dict]],
) -> tuple[dict[str, float], list[str]]:
    """Distribute `tss` across canonical muscle groups using catalog ratios.

    Parameters
    ----------
    tss:
        Total TSS to distribute (may be 0).
    exercises:
        List of exercise dicts, each with keys: ``name`` (str), ``sets``
        (int|None), ``reps`` (int|None), ``weight_kg`` (float|None).
    catalog:
        Mapping of normalized exercise name → list of {part, ratio} dicts
        from exercise_catalog. Missing entries are treated as unclassified.

    Returns
    -------
    (group_loads, unclassified)
        group_loads: dict mapping canonical group → load (float)
        unclassified: list of exercise names not found in catalog
    """
    if not exercises or tss <= 0:
        return {}, []

    # Step 1: compute raw volume per exercise
    volumes = []
    for ex in exercises:
        v = _exercise_volume(ex.get("sets"), ex.get("reps"), ex.get("weight_kg"))
        volumes.append(v)

    total_volume = sum(volumes)

    # Step 2: compute exercise shares (equal split when all volumes == 0)
    n = len(exercises)
    if total_volume == 0:
        shares = [1.0 / n] * n
    else:
        shares = [v / total_volume for v in volumes]

    # Step 3: distribute TSS across muscle groups
    group_loads: dict[str, float] = {}
    unclassified: list[str] = []

    for ex, share in zip(exercises, shares):
        name = (ex.get("name") or "").strip().lower()
        body_parts = catalog.get(name)

        if not body_parts:
            if name:
                unclassified.append(name)
            # exercise contributes nothing to the ledger when unclassified
            continue

        exercise_tss = tss * share
        for bp in body_parts:
            group = normalize_part(bp["part"])
            ratio = float(bp.get("ratio", 0))
            group_loads[group] = group_loads.get(group, 0.0) + exercise_tss * ratio

    return group_loads, unclassified


# ── Catalog lookup helpers ─────────────────────────────────────────────────────

def _lookup_catalog(names: list[str], db: Session) -> dict[str, list[dict]]:
    """Return catalog body_parts for the given normalized exercise names (DB read).

    Returns a dict: normalized_name → [{part, ratio}] or absent if not in catalog.
    Does NOT call the LLM — only returns already-classified entries.
    """
    from backend.models import ExerciseCatalog

    if not names:
        return {}

    rows = (
        db.query(ExerciseCatalog)
        .filter(ExerciseCatalog.name.in_(names))
        .all()
    )
    return {row.name: row.body_parts for row in rows}


# ── StrengthSession TSS estimation ────────────────────────────────────────────

def _estimate_session_tss(session_rows: list[Any]) -> float:
    """Estimate TSS for a group of StrengthSession rows on the same date.

    Uses session_rpe × duration_minutes when available (any row); falls back to
    equal per-row duration_only estimate (IF = 0.7 per tss.md convention).
    Returns 0 when no usable data exists.
    """
    rpes = [r.session_rpe for r in session_rows if r.session_rpe is not None]
    durations_min = [r.duration_minutes for r in session_rows if r.duration_minutes is not None]

    total_duration_min = sum(durations_min) if durations_min else 0

    if rpes and total_duration_min:
        session_rpe = sum(rpes) / len(rpes)
        si = session_rpe / 10.0
        return round(si ** 2 * (total_duration_min / 60.0) * 100)

    if total_duration_min:
        # duration-only fallback: IF = 0.7
        return round(0.7 ** 2 * (total_duration_min / 60.0) * 100)

    return 0


# ── Main writer ───────────────────────────────────────────────────────────────

def recompute_strength_load_for_date(
    user_id: _uuid.UUID,
    load_date: _date,
) -> None:
    """Recompute and persist `muscle_load_daily` rows for strength on the given date.

    Collects all strength workouts (Workout.workout_type == 'strength') and all
    StrengthSession rows for the user on that date, distributes their TSS across
    muscle groups via catalog ratios, then replaces existing strength rows for
    (user, date) with the new values — idempotent on re-run.
    """
    from backend.models import (
        MuscleLoadDaily,
        StrengthSession,
        Workout,
        WorkoutExercise,
    )

    with Session(engine) as db:
        # ── Collect workout exercises ──────────────────────────────────────────
        workouts = (
            db.query(Workout)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date == load_date,
                Workout.workout_type == "strength",
            )
            .all()
        )

        all_exercises: list[dict] = []
        total_workout_tss: float = 0.0

        for wo in workouts:
            wo_tss = float(wo.tss) if wo.tss is not None else 0.0
            if wo_tss <= 0:
                continue
            exs = (
                db.query(WorkoutExercise)
                .filter(WorkoutExercise.workout_id == wo.id)
                .order_by(WorkoutExercise.display_order)
                .all()
            )
            if not exs:
                continue
            for ex in exs:
                all_exercises.append({
                    "name": (ex.name or "").strip().lower(),
                    "sets": ex.sets,
                    "reps": ex.reps,
                    "weight_kg": float(ex.weight_kg) if ex.weight_kg is not None else None,
                    "_tss": wo_tss / len(exs),  # pre-allocated per exercise
                })
            total_workout_tss += wo_tss

        # ── Collect strength sessions ──────────────────────────────────────────
        session_rows = (
            db.query(StrengthSession)
            .filter(
                StrengthSession.user_id == user_id,
                StrengthSession.session_date == load_date,
            )
            .all()
        )

        session_exercises: list[dict] = []
        session_tss: float = 0.0

        if session_rows:
            session_tss = float(_estimate_session_tss(session_rows))
            for sr in session_rows:
                session_exercises.append({
                    "name": (sr.exercise_name or "").strip().lower(),
                    "sets": sr.sets,
                    "reps": sr.reps,
                    "weight_kg": float(sr.load) if sr.load is not None else None,
                })

        # ── Build combined catalog lookup ──────────────────────────────────────
        all_names = list({
            ex["name"] for ex in (all_exercises + session_exercises) if ex["name"]
        })
        catalog = _lookup_catalog(all_names, db)

        # ── Distribute TSS for workout exercises ───────────────────────────────
        combined_loads: dict[str, float] = {}
        all_unclassified: list[str] = []

        if all_exercises and total_workout_tss > 0:
            # Distribute each workout's TSS independently then sum
            # (already broken out above via _tss per exercise)
            # Re-distribute using the correct per-workout TSS share
            wo_group_loads, wo_unclass = distribute_strength_tss(
                total_workout_tss, all_exercises, catalog
            )
            for g, v in wo_group_loads.items():
                combined_loads[g] = combined_loads.get(g, 0.0) + v
            all_unclassified.extend(wo_unclass)

        # ── Distribute TSS for strength sessions ──────────────────────────────
        if session_exercises and session_tss > 0:
            ss_group_loads, ss_unclass = distribute_strength_tss(
                session_tss, session_exercises, catalog
            )
            for g, v in ss_group_loads.items():
                combined_loads[g] = combined_loads.get(g, 0.0) + v
            all_unclassified.extend(ss_unclass)

        # ── Replace existing strength rows for this user/date ──────────────────
        db.query(MuscleLoadDaily).filter(
            MuscleLoadDaily.user_id == user_id,
            MuscleLoadDaily.load_date == load_date,
            MuscleLoadDaily.source == "strength",
        ).delete(synchronize_session=False)

        for group, load_val in combined_loads.items():
            if load_val <= 0:
                continue
            row = MuscleLoadDaily(
                user_id=user_id,
                load_date=load_date,
                muscle_group=group,
                load=Decimal(str(round(load_val, 4))),
                source="strength",
            )
            db.add(row)

        db.commit()

        if all_unclassified:
            _log.debug(
                "muscle_load: unclassified exercises on %s for user %s: %s",
                load_date, user_id, sorted(set(all_unclassified)),
            )


def backfill_strength_load(user_id: _uuid.UUID) -> int:
    """Recompute strength muscle load for all dates that have strength workouts
    or strength sessions for this user. Returns count of dates processed."""
    from backend.models import StrengthSession, Workout

    with Session(engine) as db:
        workout_dates = {
            row.workout_date
            for row in db.query(Workout.workout_date)
            .filter(Workout.user_id == user_id, Workout.workout_type == "strength")
            .all()
        }
        session_dates = {
            row.session_date
            for row in db.query(StrengthSession.session_date)
            .filter(StrengthSession.user_id == user_id)
            .all()
        }

    all_dates = sorted(workout_dates | session_dates)
    for d in all_dates:
        recompute_strength_load_for_date(user_id, d)
    return len(all_dates)
