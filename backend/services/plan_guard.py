"""plan_guard — muscle-aware planning guard: footprint estimator + plan check (issue #1383).

Footprint estimator
-------------------
Estimates per-group load *shares* (0–1) for a planned session draft.
Uses the same profiles as the ledger writers (issues #1367, #1379).

NOTE: RUN_PROFILE and PLYO_PROFILE below mirror the constants added to
muscle_load.py by issue #1379.  Once #1379 is merged into the sprint branch,
they should be consolidated: import from muscle_load instead of redefined here.
The distribute_strength_tss function for the strength path already lives in
muscle_load.py and is imported directly.

Plan check
----------
Compares the footprint against current muscle classifications (from
muscle_load_acwr.compute()) and returns:

  warnings   — each dominant group (share >= DOMINANT_SHARE_THRESHOLD) that is
               classified ``overused`` OR has ``injured == True`` (any
               classification).  Elevated alone does NOT warn.
  suggestions — untrained priority groups (calf/hamstring/glute/hip) that:
               (a) are not injured,
               (b) are not already dominantly targeted by the session.
               For run/plyo the warning is sufficient; suggestions are strength-only.
"""
from __future__ import annotations

from typing import Optional

# ── Threshold constant ─────────────────────────────────────────────────────────

DOMINANT_SHARE_THRESHOLD: float = 0.15
"""A group whose share in the session footprint exceeds this is 'dominant' for
the purpose of the plan check."""

# ── Run / plyo recruitment profiles ───────────────────────────────────────────
# Mirror of issue #1379 constants. Consolidate into muscle_load.py once #1379
# is merged into the sprint.

RUN_PROFILE: dict[str, float] = {
    "calf":      0.20,
    "quad":      0.25,
    "hamstring": 0.20,
    "glute":     0.20,
    "hip":       0.05,
    "core":      0.10,
}

PLYO_PROFILE: dict[str, float] = {
    "calf":  0.70,
    "quad":  0.15,
    "glute": 0.15,
}

# ── Footprint estimator ────────────────────────────────────────────────────────

def estimate_session_footprint(
    session_type: str,
    structure: Optional[dict],
    catalog: Optional[dict[str, list[dict]]] = None,
) -> dict[str, float]:
    """Estimate per-group load shares for a planned session.

    Parameters
    ----------
    session_type:
        One of 'run', 'plyo', 'strength', 'rest', 'stretch'.
    structure:
        The planned session's structure dict (may be None).  Used for
        strength sessions to extract exercise names.
    catalog:
        Pre-fetched exercise catalog: {normalized_name: [{part, ratio}]}.
        Required for strength footprint; if None, strength returns empty dict.

    Returns
    -------
    dict mapping canonical muscle group → share (0–1). Shares sum to ~1.0
    for run/plyo; may sum to <1.0 for strength (unclassified exercises dropped).
    Returns {} for rest/stretch or when no useful data is available.
    """
    stype = (session_type or "").strip().lower()

    if stype == "run":
        return dict(RUN_PROFILE)

    if stype == "plyo":
        return dict(PLYO_PROFILE)

    if stype == "strength":
        return _strength_footprint(structure, catalog)

    # rest / stretch / unknown
    return {}


def _strength_footprint(
    structure: Optional[dict],
    catalog: Optional[dict[str, list[dict]]],
) -> dict[str, float]:
    """Compute strength footprint shares from planned exercise list + catalog.

    Uses distribute_strength_tss with a notional TSS=100 so the result is
    purely a ratio — divides by 100 at the end to get 0–1 shares.
    """
    if not structure or not catalog:
        return {}

    exercises = structure.get("exercises")
    if not exercises or not isinstance(exercises, list):
        return {}

    # Build exercise dicts compatible with distribute_strength_tss
    # The planned session may have sets/reps as ints or strings; weight is a
    # string ("78% 1RM") so treat as None → DEFAULT_WEIGHT fallback.
    ex_dicts: list[dict] = []
    for ex in exercises:
        if not isinstance(ex, dict):
            continue
        name = (ex.get("name") or "").strip().lower()
        if not name:
            continue
        sets_raw = ex.get("sets")
        reps_raw = ex.get("reps")
        try:
            sets_val = int(sets_raw) if sets_raw is not None else None
        except (ValueError, TypeError):
            sets_val = None
        try:
            reps_val = int(reps_raw) if reps_raw is not None else None
        except (ValueError, TypeError):
            reps_val = None
        ex_dicts.append({"name": name, "sets": sets_val, "reps": reps_val, "weight_kg": None})

    if not ex_dicts:
        return {}

    from backend.services.muscle_load import distribute_strength_tss

    NOTIONAL_TSS = 100.0
    group_loads, _unclass = distribute_strength_tss(NOTIONAL_TSS, ex_dicts, catalog)

    if not group_loads:
        return {}

    total = sum(group_loads.values())
    if total <= 0:
        return {}

    return {g: v / total for g, v in group_loads.items()}


# ── Plan check ────────────────────────────────────────────────────────────────

from backend.services.muscle_load_acwr import PRIORITY_GROUPS  # noqa: E402


def check_session(
    session_type: str,
    footprint: dict[str, float],
    group_stats: dict[str, dict],
) -> dict:
    """Check a planned session's muscle footprint against current classifications.

    Parameters
    ----------
    session_type:
        One of the _PLANNED_SESSION_TYPES.
    footprint:
        Per-group share dict from estimate_session_footprint.
    group_stats:
        Per-group stats dict from muscle_load_acwr.compute() — expects keys
        ``classification`` (str) and ``injured`` (bool) per group.

    Returns
    -------
    {
        "warnings":    [{muscle_group, classification, message}],
        "suggestions": [{muscle_group, reason}],
    }
    """
    warnings: list[dict] = []
    suggestions: list[dict] = []

    if not footprint or not group_stats:
        return {"warnings": warnings, "suggestions": suggestions}

    stype = (session_type or "").strip().lower()

    # ── Warnings: dominant groups that are overused or injured ────────────────

    for group, share in footprint.items():
        if share < DOMINANT_SHARE_THRESHOLD:
            continue
        stats = group_stats.get(group)
        if stats is None:
            continue
        classification = stats.get("classification", "")
        injured = bool(stats.get("injured", False))

        warn_overused = (classification == "overused")
        warn_injured = injured  # injured regardless of classification

        if not (warn_overused or warn_injured):
            continue

        if warn_overused and warn_injured:
            msg = (
                f"Your {group} is both overused and currently injured — "
                f"avoid loading it until it recovers."
            )
        elif warn_overused:
            msg = (
                f"Your {group} is overused (ACWR too high) — "
                f"this session loads it significantly."
            )
        else:
            msg = (
                f"Your {group} is currently injured — "
                f"this session loads it significantly."
            )

        # For injured groups, report the underlying classification in the payload
        reported_classification = "injured" if (injured and not warn_overused) else classification
        warnings.append({
            "muscle_group": group,
            "classification": reported_classification,
            "message": msg,
        })

    # ── Suggestions: untrained priority groups the session could target ───────
    # For strength sessions only: suggest untrained priority groups not already
    # dominantly targeted by this session.
    # Run/plyo sessions already load lower-body through their fixed profiles;
    # the warning above is sufficient for those — no suggestions overlap.

    if stype == "strength":
        for group in PRIORITY_GROUPS:
            stats = group_stats.get(group)
            if stats is None:
                continue
            if stats.get("injured", False):
                continue  # never prescribe loading an injured area
            if stats.get("classification") != "untrained":
                continue
            if footprint.get(group, 0.0) >= DOMINANT_SHARE_THRESHOLD:
                continue  # already well-targeted by this session
            suggestions.append({
                "muscle_group": group,
                "reason": (
                    f"{group} has had little training load recently — "
                    f"consider adding {group} exercises to this session."
                ),
            })

    return {"warnings": warnings, "suggestions": suggestions}


# ── Catalog lookup helper (DB-backed) ─────────────────────────────────────────

def fetch_catalog_for_exercises(
    exercise_names: list[str],
) -> dict[str, list[dict]]:
    """Fetch catalog body_parts for the given normalized exercise names.

    Returns {name: [{part, ratio}]} for names present in exercise_catalog.
    Names not in the catalog are simply absent from the returned dict.
    """
    from backend.db import engine
    from backend.models import ExerciseCatalog
    from sqlalchemy.orm import Session

    if not exercise_names:
        return {}

    normalized = [n.strip().lower() for n in exercise_names if n]
    if not normalized:
        return {}

    with Session(engine) as db:
        rows = (
            db.query(ExerciseCatalog)
            .filter(ExerciseCatalog.name.in_(normalized))
            .all()
        )
        return {row.name: row.body_parts for row in rows}


def extract_strength_exercise_names(structure: Optional[dict]) -> list[str]:
    """Extract normalized exercise names from a planned session structure."""
    if not structure:
        return []
    exercises = structure.get("exercises")
    if not exercises or not isinstance(exercises, list):
        return []
    return [
        (ex.get("name") or "").strip().lower()
        for ex in exercises
        if isinstance(ex, dict) and (ex.get("name") or "").strip()
    ]
