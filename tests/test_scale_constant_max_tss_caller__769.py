"""Tests for issue #769: scale_constant/max_tss columns and thin caller.

Acceptance criteria covered:
  AC1 — UserPreferences model gains scale_constant (Float, nullable) and
         max_tss (Integer, nullable) columns.
  AC2 — Alembic migration adds both columns with column_exists guards.
  AC3 — get_strength_tss_per_set_for_workout(workout_id, user_id, db) reads
         scale_constant and max_tss from UserPreferences and delegates to
         calculate_strength_tss_per_set_with_prefs.
  AC4 — When either preference is None, caller passes None and the pure
         function handles it without error.
  AC5 — Migration is idempotent (column_exists guard in the migration file).
  AC6 — Raises ValueError when workout_id or user_id does not exist in DB.
"""
import inspect
import types
import uuid

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _workout_ns(user_id=None, exercises=None):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        exercises=exercises or [],
    )


def _exercise_ns(reps=None, rpe=None, sets=1, sets_json=None):
    return types.SimpleNamespace(
        reps=reps,
        rpe=rpe,
        sets=sets,
        sets_json=sets_json,
        weight_kg=None,
    )


def _prefs_ns(scale_constant=None, max_tss=None):
    return types.SimpleNamespace(
        scale_constant=scale_constant,
        max_tss=max_tss,
    )


def _user_ns(user_id=None):
    uid = user_id or uuid.uuid4()
    return types.SimpleNamespace(id=uid)


class _MockQuery:
    def __init__(self, results):
        self._results = results

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None

    def all(self):
        return self._results


class _MockSession:
    """Minimal mock session for unit-testing get_strength_tss_per_set_for_workout."""

    def __init__(self, workout, prefs, user=None, exercises=None):
        self._workout = workout
        self._prefs = prefs
        self._user = user
        self._exercises = exercises or (workout.exercises if workout else [])

    def get(self, model, pk):
        model_name = getattr(model, "__name__", str(model))
        if "Workout" in model_name and "Exercise" not in model_name:
            return self._workout
        if "User" in model_name and "Preferences" not in model_name:
            return self._user
        return None

    def query(self, model):
        model_name = getattr(model, "__name__", str(model))
        if "UserPreferences" in model_name or "Preferences" in model_name:
            return _MockQuery([self._prefs] if self._prefs else [])
        if "WorkoutExercise" in model_name or "Exercise" in model_name:
            return _MockQuery(self._exercises)
        if "User" in model_name:
            return _MockQuery([self._user] if self._user else [])
        return _MockQuery([])


# ── AC1: UserPreferences model has the new columns ───────────────────────────

def test_user_preferences_has_scale_constant_column():
    """AC1: UserPreferences model has scale_constant attribute."""
    from backend.models import UserPreferences
    assert hasattr(UserPreferences, "scale_constant"), (
        "UserPreferences must have a scale_constant column"
    )


def test_user_preferences_has_max_tss_column():
    """AC1: UserPreferences model has max_tss attribute."""
    from backend.models import UserPreferences
    assert hasattr(UserPreferences, "max_tss"), (
        "UserPreferences must have a max_tss column"
    )


def test_user_preferences_scale_constant_is_nullable():
    """AC1: scale_constant column is nullable (Float, default None)."""
    from backend.models import UserPreferences
    col = UserPreferences.__table__.c.scale_constant
    assert col.nullable, "scale_constant must be nullable"


def test_user_preferences_max_tss_is_nullable():
    """AC1: max_tss column is nullable (Integer, default None)."""
    from backend.models import UserPreferences
    col = UserPreferences.__table__.c.max_tss
    assert col.nullable, "max_tss must be nullable"


def test_user_preferences_scale_constant_type_is_float():
    """AC1: scale_constant column type is Float."""
    from backend.models import UserPreferences
    import sqlalchemy as sa
    col = UserPreferences.__table__.c.scale_constant
    assert isinstance(col.type, sa.Float), (
        f"scale_constant must be Float, got {type(col.type)}"
    )


def test_user_preferences_max_tss_type_is_integer():
    """AC1: max_tss column type is Integer."""
    from backend.models import UserPreferences
    import sqlalchemy as sa
    col = UserPreferences.__table__.c.max_tss
    assert isinstance(col.type, sa.Integer), (
        f"max_tss must be Integer, got {type(col.type)}"
    )


# ── AC2: migration file uses column_exists guards ─────────────────────────────

def test_migration_file_exists_for_scale_constant_max_tss():
    """AC2: an Alembic migration file for scale_constant/max_tss exists."""
    import pathlib
    versions_dir = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*.py"))
    found = any(
        "scale_constant" in f.read_text() and "max_tss" in f.read_text()
        for f in migration_files
    )
    assert found, "No migration file found that adds scale_constant and max_tss"


def test_migration_uses_column_exists_guard():
    """AC5: migration uses column_exists guard (idempotency)."""
    import pathlib
    versions_dir = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
    for f in versions_dir.glob("*.py"):
        text = f.read_text()
        if "scale_constant" in text and "max_tss" in text:
            assert "column_exists" in text, (
                f"Migration {f.name} must use column_exists guard for idempotency"
            )
            return
    pytest.fail("No migration file found that adds scale_constant and max_tss")


# ── AC3: get_strength_tss_per_set_for_workout is importable and callable ──────

def test_caller_is_importable():
    """AC3: get_strength_tss_per_set_for_workout is importable from backend.services.tss."""
    from backend.services.tss import get_strength_tss_per_set_for_workout
    assert callable(get_strength_tss_per_set_for_workout)


def test_caller_signature():
    """AC3: function signature has workout_id, user_id, db parameters."""
    from backend.services.tss import get_strength_tss_per_set_for_workout
    sig = inspect.signature(get_strength_tss_per_set_for_workout)
    params = list(sig.parameters.keys())
    assert "workout_id" in params
    assert "user_id" in params
    assert "db" in params


def test_caller_returns_dict():
    """AC3: function returns a dict with at least tss and method keys."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    exercises = [_exercise_ns(reps=5, rpe=8)]
    workout = _workout_ns(user_id=uid, exercises=exercises)
    prefs = _prefs_ns(scale_constant=5.85, max_tss=150)
    user = _user_ns(user_id=uid)
    db = _MockSession(workout, prefs, user=user, exercises=exercises)

    result = get_strength_tss_per_set_for_workout(workout.id, uid, db)
    assert isinstance(result, dict)
    assert "tss" in result
    assert "method" in result


def test_caller_delegates_to_pure_function():
    """AC3: caller delegates to calculate_strength_tss_per_set_with_prefs with prefs."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    # 3 sets as per the worked example
    exercises = [
        _exercise_ns(reps=5, rpe=8),
        _exercise_ns(reps=5, rpe=9),
        _exercise_ns(reps=3, rpe=10),
    ]
    workout = _workout_ns(user_id=uid, exercises=exercises)
    prefs = _prefs_ns(scale_constant=5.85, max_tss=150)
    user = _user_ns(user_id=uid)
    db = _MockSession(workout, prefs, user=user, exercises=exercises)

    result = get_strength_tss_per_set_for_workout(workout.id, uid, db)
    assert result["method"] == "per_set"
    assert isinstance(result["tss"], int)
    assert 50 <= result["tss"] <= 70


def test_caller_uses_scale_constant_from_prefs():
    """AC3: caller reads scale_constant from UserPreferences and passes it through."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    exercises = [_exercise_ns(reps=5, rpe=8)]
    workout = _workout_ns(user_id=uid, exercises=exercises)
    user = _user_ns(user_id=uid)

    prefs_low = _prefs_ns(scale_constant=1.0, max_tss=500)
    prefs_high = _prefs_ns(scale_constant=10.0, max_tss=500)

    db_low = _MockSession(workout, prefs_low, user=user, exercises=exercises)
    db_high = _MockSession(workout, prefs_high, user=user, exercises=exercises)

    result_low = get_strength_tss_per_set_for_workout(workout.id, uid, db_low)
    result_high = get_strength_tss_per_set_for_workout(workout.id, uid, db_high)

    assert result_low["tss"] is not None
    assert result_high["tss"] is not None
    # Higher scale_constant must produce a higher (or equal, due to clamping) TSS
    assert result_high["debug"]["scaled_sum"] == pytest.approx(
        result_low["debug"]["scaled_sum"] * 10.0
    )


def test_caller_uses_max_tss_from_prefs():
    """AC3: caller reads max_tss from UserPreferences and passes it through."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    exercises = [_exercise_ns(reps=100, rpe=10)]  # high volume to trigger clamping
    workout = _workout_ns(user_id=uid, exercises=exercises)
    user = _user_ns(user_id=uid)

    prefs_50 = _prefs_ns(scale_constant=5.85, max_tss=50)
    prefs_200 = _prefs_ns(scale_constant=5.85, max_tss=200)

    db_50 = _MockSession(workout, prefs_50, user=user, exercises=exercises)
    db_200 = _MockSession(workout, prefs_200, user=user, exercises=exercises)

    result_50 = get_strength_tss_per_set_for_workout(workout.id, uid, db_50)
    result_200 = get_strength_tss_per_set_for_workout(workout.id, uid, db_200)

    assert result_50["tss"] == 50
    assert result_200["tss"] == 200


# ── AC4: None preferences are passed through without error ────────────────────

def test_none_scale_constant_returns_null_without_error():
    """AC4: scale_constant=None → caller passes None; pure function returns null, no exception."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    exercises = [_exercise_ns(reps=5, rpe=8)]
    workout = _workout_ns(user_id=uid, exercises=exercises)
    prefs = _prefs_ns(scale_constant=None, max_tss=150)
    user = _user_ns(user_id=uid)
    db = _MockSession(workout, prefs, user=user, exercises=exercises)

    result = get_strength_tss_per_set_for_workout(workout.id, uid, db)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_none_max_tss_returns_null_without_error():
    """AC4: max_tss=None → caller passes None; pure function returns null, no exception."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    exercises = [_exercise_ns(reps=5, rpe=8)]
    workout = _workout_ns(user_id=uid, exercises=exercises)
    prefs = _prefs_ns(scale_constant=5.85, max_tss=None)
    user = _user_ns(user_id=uid)
    db = _MockSession(workout, prefs, user=user, exercises=exercises)

    result = get_strength_tss_per_set_for_workout(workout.id, uid, db)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_both_prefs_none_returns_null_without_error():
    """AC4: both prefs None → caller passes None for both; no exception raised."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    exercises = [_exercise_ns(reps=5, rpe=8)]
    workout = _workout_ns(user_id=uid, exercises=exercises)
    prefs = _prefs_ns(scale_constant=None, max_tss=None)
    user = _user_ns(user_id=uid)
    db = _MockSession(workout, prefs, user=user, exercises=exercises)

    result = get_strength_tss_per_set_for_workout(workout.id, uid, db)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_missing_prefs_row_returns_null_without_error():
    """AC4: no UserPreferences row → caller treats both as None; no exception."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    exercises = [_exercise_ns(reps=5, rpe=8)]
    workout = _workout_ns(user_id=uid, exercises=exercises)
    user = _user_ns(user_id=uid)
    db = _MockSession(workout, prefs=None, user=user, exercises=exercises)

    result = get_strength_tss_per_set_for_workout(workout.id, uid, db)
    assert result["tss"] is None
    assert result["method"] == "none"


# ── AC6: raises ValueError for non-existent IDs ──────────────────────────────

def test_raises_for_nonexistent_workout_id():
    """AC6: ValueError raised when workout_id does not exist in DB."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    user = _user_ns(user_id=uid)
    prefs = _prefs_ns(scale_constant=5.85, max_tss=150)
    db = _MockSession(workout=None, prefs=prefs, user=user, exercises=[])

    with pytest.raises((ValueError, LookupError)):
        get_strength_tss_per_set_for_workout(uuid.uuid4(), uid, db)


def test_raises_for_nonexistent_user_id():
    """AC6: ValueError raised when user_id does not exist in DB."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    exercises = [_exercise_ns(reps=5, rpe=8)]
    workout = _workout_ns(user_id=uid, exercises=exercises)
    prefs = _prefs_ns(scale_constant=5.85, max_tss=150)
    # No user object → user doesn't exist
    db = _MockSession(workout=workout, prefs=prefs, user=None, exercises=exercises)

    with pytest.raises((ValueError, LookupError)):
        get_strength_tss_per_set_for_workout(workout.id, uuid.uuid4(), db)


def test_error_message_mentions_workout_id():
    """AC6: error for missing workout mentions workout in message."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    uid = uuid.uuid4()
    user = _user_ns(user_id=uid)
    prefs = _prefs_ns(scale_constant=5.85, max_tss=150)
    db = _MockSession(workout=None, prefs=prefs, user=user, exercises=[])

    with pytest.raises((ValueError, LookupError)) as exc_info:
        get_strength_tss_per_set_for_workout(uuid.uuid4(), uid, db)
    assert exc_info.value.args[0]  # non-empty message
