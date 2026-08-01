"""The three goal habits — and nothing else in the goal section.

Spec D6: **three goal habits only** — weigh-in, protein-first, long-run fuel.
Everything else the athlete tracks (journaling, skincare, whatever) stays in the
``general`` section, untouched. Stretch, plyo and drills move OUT of habits into
the training plan (D5), because a planned session that verifies itself from a
logged workout is a better instrument than a checkbox.

Why exactly these three
-----------------------
========================  ==================================================
weigh-in                  the one daily measurement the program runs on
protein-first             the mechanism that makes the deficit hold without
                          willpower — one tap, self-reported
long-run fuel             the session-quality habit that protects the training
                          the cut is supposed to preserve
========================  ==================================================

Two of the three **autofill**: the weigh-in from a weight entry (Phase 1) and
long-run fuel from a fuelled long run. Only protein-first asks for a tap, and it
asks once a day at most.

No streaks
----------
Spec D8: no daily verdicts, no streaks anywhere near food. Nothing in this module
computes or exposes a streak, and ``habit_evidence`` deliberately replaces the
streak surface with correlation sentences. A streak on a food habit turns one
missed day into a reason to stop, which is the failure mode the whole program is
designed around.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import Habit

# Autofill sources for the two habits that verify themselves.
WEIGH_IN_SOURCE = "weight.logged"
LONG_RUN_FUEL_SOURCE = "long_run.fuelled"
# Protein-first is self-reported: there is no logging surface that could verify
# "protein at every meal", and inventing one would mean daily food logging —
# exactly what the structural deficit exists to avoid.
PROTEIN_FIRST_SOURCE = None

# A run this long or longer is a "long run" for fuelling purposes. Matches
# training_load's own long-run bucket floor (75 min).
LONG_RUN_MIN_MINUTES = 75

GOAL_HABIT_KEYS = ("weigh_in", "protein_first", "long_run_fuel")

_SPECS: dict[str, dict[str, Any]] = {
    "weigh_in": {
        "name": "Morning weigh-in",
        "habit_type": "binary",
        "schedule_type": "daily",
        "tracking_type": "daily_checkmark",
        "auto_fill_source": WEIGH_IN_SOURCE,
        "icon": "ti-scale",
        "sort_order": 0,
    },
    "protein_first": {
        "name": "Protein first",
        "habit_type": "binary",
        "schedule_type": "daily",
        "tracking_type": "daily_checkmark",
        "auto_fill_source": PROTEIN_FIRST_SOURCE,
        "icon": "ti-meat",
        "sort_order": 1,
    },
    "long_run_fuel": {
        "name": "Long-run fuel",
        "habit_type": "binary",
        "schedule_type": "weekly",
        "schedule_target": 1,
        "tracking_type": "daily_checkmark",
        "auto_fill_source": LONG_RUN_FUEL_SOURCE,
        "icon": "ti-bolt",
        "sort_order": 2,
    },
}


def _find(db: Session, user_id, *, source: str | None, name: str) -> Habit | None:
    """Locate an existing goal habit by autofill source, falling back to name.

    Protein-first has no source, so name is the only handle; the others prefer
    source so a rename doesn't create a duplicate.
    """
    q = db.query(Habit).filter(Habit.user_id == user_id, Habit.is_archived.is_(False))
    if source is not None:
        found = q.filter(Habit.auto_fill_source == source).order_by(
            Habit.sort_order.asc()
        ).first()
        if found is not None:
            return found
    return q.filter(Habit.name == name).order_by(Habit.sort_order.asc()).first()


def ensure_goal_habits(db: Session, user_id) -> dict[str, Habit]:
    """Idempotently create the three goal habits. Returns them keyed by role.

    Existing rows are adopted rather than duplicated, and are marked as focus
    habits so the UI can group them apart from the general section. Nothing here
    archives or edits a habit the athlete created themselves.

    Concurrency (#1604): the ``_find`` pre-check below is a plain read, so two
    near-simultaneous calls for the same user can both see "not found" and
    both try to insert — reproduced live on the UAT DB, where two concurrent
    requests each duplicated all three goal habits. Two partial unique
    indexes on ``habits`` (see
    alembic/versions/becc012af2e6_derive_habit_type_from_tracking_type_.py)
    now make the loser's insert fail with an IntegrityError instead of
    silently succeeding; each insert attempt below runs inside its own
    SAVEPOINT (``db.begin_nested()``) so that failure only unwinds that one
    insert — not any goal habit already created earlier in this same loop, or
    anything a caller staged before calling this function (``main.py`` calls
    ``ensure_coach_tracked_habits`` first, in the same session, before its own
    commit). On conflict, the row is simply re-fetched: the concurrent request
    that won the race already created it.
    """
    out: dict[str, Habit] = {}
    for key in GOAL_HABIT_KEYS:
        spec = dict(_SPECS[key])
        habit = _find(db, user_id, source=spec["auto_fill_source"], name=spec["name"])
        if habit is None:
            import uuid as _uuid

            candidate = Habit(
                # Generated here rather than by the server default so the insert
                # round-trips identically on every backend.
                id=_uuid.uuid4(),
                user_id=user_id,
                name=spec["name"],
                habit_type=spec["habit_type"],
                schedule_type=spec["schedule_type"],
                schedule_target=spec.get("schedule_target"),
                tracking_type=spec["tracking_type"],
                auto_fill_source=spec["auto_fill_source"],
                icon=spec["icon"],
                sort_order=spec["sort_order"],
                display_order=spec["sort_order"],
                section="training",
                active=True,
                is_archived=False,
                is_focus=True,
            )
            try:
                with db.begin_nested():
                    db.add(candidate)
                    db.flush()
                habit = candidate
            except IntegrityError:
                # Lost the race — a concurrent call already created this
                # habit (or one with the same name/auto_fill_source) between
                # our _find() and our insert. Re-fetch rather than trusting
                # the pre-check; do not re-raise and do not retry the insert.
                habit = _find(db, user_id, source=spec["auto_fill_source"], name=spec["name"])
                if habit is None:
                    # Should not happen — the IntegrityError implies a row
                    # matching one of _find's two keys now exists — but never
                    # leave a goal role unresolved if it somehow does.
                    raise
        else:
            # Adopt: an athlete who already had one of these keeps their history.
            habit.is_focus = True
            habit.section = "training"
        out[key] = habit
    return out


def goal_habit_ids(db: Session, user_id) -> dict[str, str]:
    """Role → habit id for the three goal habits that already exist."""
    out: dict[str, str] = {}
    for key in GOAL_HABIT_KEYS:
        spec = _SPECS[key]
        habit = _find(db, user_id, source=spec["auto_fill_source"], name=spec["name"])
        if habit is not None:
            out[key] = str(habit.id)
    return out


def is_food_habit(habit) -> bool:
    """Whether a habit is food-adjacent — the ones streaks must never touch."""
    name = (getattr(habit, "name", "") or "").lower()
    return "protein" in name or "fuel" in name
