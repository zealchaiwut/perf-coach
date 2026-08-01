"""`workout.lift_count` counts strength sessions — issue #1607.

`_normalize_workout_type` canonicalises strength sessions to lowercase
`"strength"` (deliberately — `structural_dose` and the gap-analysis
`strength_lapsed` rule query on it, #1369 follow-up). Three readers instead
matched the substring `"lift"`:

    >>> "lift" in "strength"
    False

So a habit using `workout.lift_count` — offered as a valid autofill source at
`main.py:3898` — could never tick for a strength session logged the normal way.
The athlete picks the source, logs the session, and the habit stays blank.

The operator found this from the outside, saying strength and lift ought to be
the same thing. They were meant to be; the vocabulary had split between what
writes produce and what reads look for, with each site carrying its own copy of
the check.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.utils.workout_types import (
    STRENGTH_SQL_PATTERNS,
    is_strength_workout,
)

REPO = Path(__file__).resolve().parents[1]


# ── The predicate ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "workout_type",
    ["strength", "Strength", "STRENGTH", "lift", "Lift", "weights", "weight", "wod", "crossfit"],
)
def test_strength_spellings_all_count(workout_type):
    assert is_strength_workout(workout_type)


def test_the_canonical_value_counts():
    """The regression in one line: this is what writes actually store."""
    assert is_strength_workout("strength")


@pytest.mark.parametrize("workout_type", ["run", "plyo", "stretch", "rest", "bike", None, "", "  "])
def test_non_strength_types_do_not_count(workout_type):
    assert not is_strength_workout(workout_type)


def test_match_is_anchored():
    """Anchored so a type merely CONTAINING the word doesn't match — a
    "strength-endurance run" is a run."""
    assert not is_strength_workout("endurance-strength run")
    assert not is_strength_workout("run with lifting finisher")


def test_whitespace_is_tolerated():
    assert is_strength_workout("  strength  ")


# ── Every call site uses it ───────────────────────────────────────────────────

def test_no_substring_lift_checks_remain():
    """The bug was three independent copies of `"lift" in workout_type`. One
    shared predicate, or this regrows."""
    offenders = []
    for rel in ("backend/main.py", "backend/services/habit_autofill.py"):
        for i, line in enumerate((REPO / rel).read_text().splitlines(), 1):
            if "lift" not in line.lower():
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if '"lift" in' in line or "'lift' in" in line:
                offenders.append(f"{rel}:{i}")
            if 'ilike("%lift%")' in line:
                offenders.append(f"{rel}:{i}")
    assert not offenders, (
        "substring 'lift' matching is back; it misses every row written as "
        "'strength':\n  " + "\n  ".join(offenders)
    )


def test_python_side_autofill_uses_the_predicate():
    for rel in ("backend/main.py", "backend/services/habit_autofill.py"):
        src = (REPO / rel).read_text()
        assert "is_strength_workout" in src, f"{rel} does not use the shared predicate"


def test_sql_side_filter_covers_the_canonical_value():
    """The DB-side filter is a separate code path from the Python one and had
    the identical bug — ilike('%lift%') never matched a 'strength' row."""
    assert any(p.startswith("strength") for p in STRENGTH_SQL_PATTERNS)
    src = (REPO / "backend" / "main.py").read_text()
    assert "_STRENGTH_SQL_PATTERNS" in src


def test_sql_and_python_cover_the_same_vocabulary():
    """Two implementations of one question. They must agree, or the habit grid
    and the stored autofill rows disagree about the same workout."""
    for pattern in STRENGTH_SQL_PATTERNS:
        assert is_strength_workout(pattern.rstrip("%")), (
            f"SQL matches {pattern!r} but the Python predicate does not"
        )


# ── The source stays offered ──────────────────────────────────────────────────

def test_lift_count_is_still_a_valid_autofill_source():
    """Keeping the source name is the compatible choice — existing habits
    reference `workout.lift_count` in the DB, so renaming it would orphan them.
    Only the matching was broken, not the name."""
    src = (REPO / "backend" / "main.py").read_text()
    assert "workout.lift_count" in src
