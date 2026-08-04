"""One place that decides what a workout type *is* — issue #1607.

``_normalize_workout_type`` canonicalises strength sessions to lowercase
``"strength"``, deliberately, so strength-scoped queries in ``structural_dose``
and the gap-analysis ``strength_lapsed`` rule match (#1369 follow-up).

Several readers were instead matching the substring ``"lift"``:

    >>> "lift" in "strength"
    False

So ``workout.lift_count`` — offered as a valid habit autofill source — could
never tick for a strength session logged through the normal path. The vocabulary
had split between what writes produce and what reads look for, and each site
had its own copy of the check.

``lift`` survives here only as a legacy alias: rows predating the normalisation,
and the ``wod`` / ``crossfit`` values the weekly rollup already recognised.
"""

from __future__ import annotations

import re

# Canonical value written by _normalize_workout_type.
STRENGTH = "strength"

# Every spelling that means "a strength session". `strength` is canonical;
# the rest are legacy rows and adjacent modalities the weekly rollup already
# counted as lifting. Anchored so a type merely *containing* one of these
# words (e.g. "strength-endurance run") does not match.
_STRENGTH_RE = re.compile(r"^(strength|lift|weights?|wod|crossfit)", re.IGNORECASE)

# SQL-side equivalent for the same set, for queries that filter in the DB
# rather than in Python. Kept beside the regex so the two cannot drift.
STRENGTH_SQL_PATTERNS = ("strength%", "lift%", "weight%", "wod%", "crossfit%")


def is_strength_workout(workout_type: str | None) -> bool:
    """True when this workout_type counts as a strength session.

    >>> is_strength_workout("strength")
    True
    >>> is_strength_workout("Lift")
    True
    >>> is_strength_workout("run")
    False
    >>> is_strength_workout(None)
    False
    """
    if not workout_type:
        return False
    return _STRENGTH_RE.match(workout_type.strip()) is not None
