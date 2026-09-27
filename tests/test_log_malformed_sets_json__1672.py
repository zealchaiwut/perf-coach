"""Tests for issue #1672: log instead of silently swallowing malformed sets_json.

Acceptance criteria covered:
  AC1 — When sets_json is malformed (not valid JSON), a WARNING or DEBUG log is
         emitted that includes the workout_id (or exercise identifier) and the
         exception message, so bad per-set data is diagnosable.
  AC2 — The malformed exercise is skipped (not counted toward TSS), so TSS is
         lower than it would be for a valid set, not an exception.
  AC3 — Valid exercises in the same workout still contribute to TSS normally.
"""
import logging
import types
import uuid


# ── helpers ───────────────────────────────────────────────────────────────────

def _exercise_ns(reps=None, rpe=None, sets=1, sets_json=None):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        reps=reps,
        rpe=rpe,
        sets=sets,
        sets_json=sets_json,
        weight_kg=None,
    )


def _prefs_ns(scale_constant=5.85, max_tss=150):
    return types.SimpleNamespace(scale_constant=scale_constant, max_tss=max_tss)


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
    def __init__(self, workout, prefs, user=None, exercises=None):
        self._workout = workout
        self._prefs = prefs
        self._user = user
        self._exercises = exercises or []

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


def _make_db(exercises, prefs=None, user_id=None):
    uid = user_id or uuid.uuid4()
    user = _user_ns(user_id=uid)
    workout = types.SimpleNamespace(id=uuid.uuid4(), user_id=uid)
    p = prefs if prefs is not None else _prefs_ns()
    return _MockSession(workout, p, user=user, exercises=exercises), workout, uid


# ── AC1: warning/debug log emitted for malformed sets_json ────────────────────

def test_log_emitted_for_invalid_json(caplog):
    """AC1: A warning/debug log is emitted when sets_json is not valid JSON."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    bad_ex = _exercise_ns(sets_json="NOT VALID JSON {{{{")
    db, workout, uid = _make_db([bad_ex])

    with caplog.at_level(logging.DEBUG, logger="backend.services.tss"):
        get_strength_tss_per_set_for_workout(workout.id, uid, db)

    logs = [r for r in caplog.records if r.levelno >= logging.DEBUG]
    assert logs, (
        "Expected at least one log record when sets_json is malformed, got none. "
        f"Records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


def test_log_emitted_for_type_error_in_sets_json(caplog):
    """AC1: A warning/debug log is emitted when processing sets_json raises TypeError."""
    import unittest.mock
    from backend.services.tss import get_strength_tss_per_set_for_workout

    # Force json.loads to raise TypeError to simulate an unexpected type scenario
    bad_ex = _exercise_ns(sets_json='[{"reps": 5}]')
    db, workout, uid = _make_db([bad_ex])

    with caplog.at_level(logging.DEBUG, logger="backend.services.tss"), \
         unittest.mock.patch("backend.services.tss.json.loads", side_effect=TypeError("unexpected type")):
        get_strength_tss_per_set_for_workout(workout.id, uid, db)

    logs = [r for r in caplog.records if r.levelno >= logging.DEBUG]
    assert logs, (
        "Expected a log record when json.loads raises TypeError, got none. "
        f"Records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


def test_log_contains_workout_id(caplog):
    """AC1: Log message includes the workout_id so the bad record is diagnosable."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    bad_ex = _exercise_ns(sets_json="INVALID")
    db, workout, uid = _make_db([bad_ex])

    with caplog.at_level(logging.DEBUG, logger="backend.services.tss"):
        get_strength_tss_per_set_for_workout(workout.id, uid, db)

    combined = " ".join(r.getMessage() for r in caplog.records)
    assert str(workout.id) in combined, (
        f"Expected workout_id {workout.id} in log output, got: {combined!r}"
    )


# ── AC2: malformed exercise is skipped (returns lower TSS, no exception) ──────

def test_malformed_sets_json_skipped_returns_result(caplog):
    """AC2: Malformed sets_json row is skipped; function returns a dict without raising."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    bad_ex = _exercise_ns(sets_json="{bad json}")
    db, workout, uid = _make_db([bad_ex])

    with caplog.at_level(logging.DEBUG, logger="backend.services.tss"):
        result = get_strength_tss_per_set_for_workout(workout.id, uid, db)

    assert isinstance(result, dict), "Expected a dict result even with malformed sets_json"
    assert "tss" in result


# ── AC3: valid exercises in the same workout still contribute ─────────────────

def test_valid_exercise_contributes_despite_malformed_peer(caplog):
    """AC3: A valid exercise alongside a malformed one still produces non-None TSS."""
    from backend.services.tss import get_strength_tss_per_set_for_workout

    bad_ex = _exercise_ns(sets_json="GARBAGE")
    # Valid sets_json for the second exercise
    valid_ex = _exercise_ns(sets_json='[{"reps": 5, "rpe": 8}]')
    db, workout, uid = _make_db([bad_ex, valid_ex])

    with caplog.at_level(logging.DEBUG, logger="backend.services.tss"):
        result = get_strength_tss_per_set_for_workout(workout.id, uid, db)

    assert result["tss"] is not None, (
        "Valid exercise should still contribute TSS even when a sibling exercise has malformed sets_json"
    )
    assert result["tss"] > 0, (
        f"Expected positive TSS from valid exercise; got {result['tss']}"
    )
