"""
Tests for issue #178: Refactor strength workout count query in seed.py to use ORM.

The thin_strength check previously used text() / raw SQL. It must now use
session.query(Workout) with ORM filters so the module is consistent.
"""
import inspect
import sys

import pytest

sys.path.insert(0, ".")


def _seed_source() -> str:
    import importlib.util
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "backend", "seed.py")
    with open(os.path.normpath(path)) as f:
        return f.read()


# ── AC-1: thin_strength block no longer uses raw SQL text() ──────────────────

def test_thin_strength_uses_no_raw_sql():
    """The thin_strength query must not contain raw SQL via text()."""
    src = _seed_source()
    # Isolate just the thin_strength block (everything before workout_count line)
    block = src.split("workout_count")[0]
    assert "ILIKE 'strength'" not in block, (
        "thin_strength query must not contain raw SQL ILIKE string"
    )
    assert "workout_exercises we WHERE we.workout_id" not in block, (
        "thin_strength query must not use raw SQL subquery for exercise count"
    )


# ── AC-2: seed.py imports Workout and WorkoutExercise ORM models ──────────────

def test_seed_imports_workout_model():
    src = _seed_source()
    assert "from models import" in src and "Workout" in src, (
        "seed.py must import Workout ORM model"
    )
    assert "WorkoutExercise" in src, (
        "seed.py must import WorkoutExercise ORM model"
    )


# ── AC-3: thin_strength block uses session.query(Workout) ────────────────────

def test_thin_strength_uses_orm_query():
    src = _seed_source()
    assert "session.query(Workout)" in src, (
        "thin_strength must use session.query(Workout) ORM query"
    )


# ── AC-4: thin_strength uses ilike ORM filter ────────────────────────────────

def test_thin_strength_uses_ilike_filter():
    src = _seed_source()
    assert ".ilike(" in src, (
        "thin_strength must use .ilike() ORM filter instead of ILIKE raw SQL"
    )


# ── AC-5: thin_strength uses notin_ ORM filter ───────────────────────────────

def test_thin_strength_uses_notin_filter():
    src = _seed_source()
    assert ".notin_(" in src, (
        "thin_strength must use .notin_() ORM filter for name exclusion"
    )


# ── AC-6: thin_strength uses scalar_subquery for exercise count ───────────────

def test_thin_strength_uses_scalar_subquery():
    src = _seed_source()
    assert "scalar_subquery()" in src, (
        "thin_strength must use .scalar_subquery() for the exercise count subquery"
    )


# ── AC-7: seed.py imports func from sqlalchemy ───────────────────────────────

def test_seed_imports_func():
    src = _seed_source()
    assert "func" in src, (
        "seed.py must import func from sqlalchemy for ORM aggregate count"
    )
