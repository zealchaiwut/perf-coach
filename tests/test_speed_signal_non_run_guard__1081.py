"""Tests for issue #1081: compute_and_store_speed_signal should guard non-run workout types.

Acceptance criteria covered:

  AC1  - compute_and_store_speed_signal returns (False, "workout is not a run type")
         immediately after the workout-not-found guard for non-run workout types.
  AC2  - Guard uses case-insensitive substring match ("%run%") consistent with
         the filter in backfill_signals.py.
  AC3  - Cycling workout: returns (False, "workout is not a run type"), no DB write.
  AC4  - Strength workout: returns (False, "workout is not a run type"), no DB write.
  AC5  - Run workout: proceeds past the guard and continues normal computation.
  AC6  - Docstring for compute_and_store_speed_signal accurately documents the guard.
"""

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Shared fake session infrastructure (mirrors test_compute_store_speed_signal_per_run__1048.py)
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows_by_model):
        self._rows_by_model = rows_by_model

    def query(self, model):
        return _FakeQuery(self._rows_by_model.get(model.__name__, []))


def _workout(workout_type="run"):
    return SimpleNamespace(
        id="w-test",
        user_id="u-test",
        workout_type=workout_type,
        stryd_activity_pk=None,
        speed_signal=None,
        speed_signal_basis=None,
        speed_signal_window_seconds=None,
        speed_signal_source=None,
    )


def _prefs_row():
    return SimpleNamespace(
        user_id="u-test",
        ftp_w=200,
        threshold_hr=None,
        threshold_pace_seconds_per_km=None,
    )


def _make_session(workout):
    from backend.models import Workout, WorkoutSplit, UserPreferences, StrydActivity
    return _FakeSession({
        "Workout": [workout],
        "WorkoutSplit": [],
        "UserPreferences": [_prefs_row()],
        "StrydActivity": [],
    })


# ---------------------------------------------------------------------------
# AC3 – Cycling workout returns (False, "workout is not a run type"), no DB write
# ---------------------------------------------------------------------------

class TestCyclingWorkoutGuard:

    def test_cycling_returns_false_tuple(self):
        from backend.services.speed_signal import compute_and_store_speed_signal
        wo = _workout(workout_type="cycling")
        session = _make_session(wo)
        result = compute_and_store_speed_signal("w-test", session)
        assert result == (False, "workout is not a run type"), (
            f"Expected (False, 'workout is not a run type'), got {result!r}"
        )

    def test_cycling_no_speed_signal_written(self):
        from backend.services.speed_signal import compute_and_store_speed_signal
        wo = _workout(workout_type="cycling")
        session = _make_session(wo)
        compute_and_store_speed_signal("w-test", session)
        # Sentinel is still None — the function returned early without touching these fields.
        assert wo.speed_signal is None
        assert wo.speed_signal_basis is None
        assert wo.speed_signal_window_seconds is None
        assert wo.speed_signal_source is None

    def test_cycling_reason_message_exact(self):
        from backend.services.speed_signal import compute_and_store_speed_signal
        wo = _workout(workout_type="cycling")
        session = _make_session(wo)
        ok, reason = compute_and_store_speed_signal("w-test", session)
        assert reason == "workout is not a run type"


# ---------------------------------------------------------------------------
# AC4 – Strength workout returns (False, "workout is not a run type"), no DB write
# ---------------------------------------------------------------------------

class TestStrengthWorkoutGuard:

    def test_strength_returns_false_tuple(self):
        from backend.services.speed_signal import compute_and_store_speed_signal
        wo = _workout(workout_type="strength training")
        session = _make_session(wo)
        result = compute_and_store_speed_signal("w-test", session)
        assert result == (False, "workout is not a run type"), (
            f"Expected (False, 'workout is not a run type'), got {result!r}"
        )

    def test_strength_no_speed_signal_written(self):
        from backend.services.speed_signal import compute_and_store_speed_signal
        wo = _workout(workout_type="strength training")
        session = _make_session(wo)
        compute_and_store_speed_signal("w-test", session)
        assert wo.speed_signal is None
        assert wo.speed_signal_basis is None
        assert wo.speed_signal_window_seconds is None
        assert wo.speed_signal_source is None

    def test_strength_reason_message_exact(self):
        from backend.services.speed_signal import compute_and_store_speed_signal
        wo = _workout(workout_type="strength training")
        session = _make_session(wo)
        ok, reason = compute_and_store_speed_signal("w-test", session)
        assert reason == "workout is not a run type"


# ---------------------------------------------------------------------------
# AC2 – Guard uses case-insensitive substring match (equivalent to ilike("%run%"))
# ---------------------------------------------------------------------------

class TestCaseInsensitiveMatch:

    @pytest.mark.parametrize("wtype", [
        "cycling",
        "Cycling",
        "CYCLING",
        "strength training",
        "Strength",
        "yoga",
        "swimming",
        "walk",
    ])
    def test_non_run_type_rejected(self, wtype):
        from backend.services.speed_signal import compute_and_store_speed_signal
        wo = _workout(workout_type=wtype)
        session = _make_session(wo)
        ok, reason = compute_and_store_speed_signal("w-test", session)
        assert not ok, f"Expected False for workout_type={wtype!r}, got {ok!r}"
        assert reason == "workout is not a run type"

    @pytest.mark.parametrize("wtype", [
        "run",
        "Run",
        "RUN",
        "outdoor run",
        "Outdoor Run",
        "trail run",
        "treadmill run",
        "easy run",
    ])
    def test_run_type_passes_guard(self, wtype, monkeypatch):
        from backend.services.speed_signal import compute_and_store_speed_signal
        # Patch compute_speed_signal to avoid needing real splits
        import backend.services.speed_signal as ss
        monkeypatch.setattr(ss, "compute_speed_signal", lambda splits, prefs: {
            "speed_signal": None,
            "speed_signal_basis": None,
            "speed_signal_window_seconds": None,
            "speed_signal_source": None,
        })
        wo = _workout(workout_type=wtype)
        session = _make_session(wo)
        ok, reason = compute_and_store_speed_signal("w-test", session)
        # Must NOT return the non-run guard message
        assert reason != "workout is not a run type", (
            f"workout_type={wtype!r} should pass the run guard but was rejected"
        )


# ---------------------------------------------------------------------------
# AC5 – Run workout proceeds past the guard (happy path — no regression)
# ---------------------------------------------------------------------------

class TestRunWorkoutHappyPath:

    def test_outdoor_run_proceeds_past_guard(self, monkeypatch):
        from backend.services.speed_signal import compute_and_store_speed_signal
        import backend.services.speed_signal as ss
        monkeypatch.setattr(ss, "compute_speed_signal", lambda splits, prefs: {
            "speed_signal": 1.15,
            "speed_signal_basis": "power",
            "speed_signal_window_seconds": 300,
            "speed_signal_source": "power basis; best ratio 1.1500 from 300s window",
        })
        wo = _workout(workout_type="outdoor run")
        session = _make_session(wo)
        ok, reason = compute_and_store_speed_signal("w-test", session)
        assert ok is True
        assert reason is None

    def test_run_workout_fields_written(self, monkeypatch):
        from backend.services.speed_signal import compute_and_store_speed_signal
        import backend.services.speed_signal as ss
        monkeypatch.setattr(ss, "compute_speed_signal", lambda splits, prefs: {
            "speed_signal": 1.15,
            "speed_signal_basis": "power",
            "speed_signal_window_seconds": 300,
            "speed_signal_source": "power basis; best ratio 1.1500 from 300s window",
        })
        wo = _workout(workout_type="run")
        session = _make_session(wo)
        compute_and_store_speed_signal("w-test", session)
        assert wo.speed_signal == 1.15
        assert wo.speed_signal_basis == "power"


# ---------------------------------------------------------------------------
# AC1 – Guard is placed after workout-not-found guard, not before
# ---------------------------------------------------------------------------

class TestGuardOrdering:

    def test_workout_not_found_takes_precedence(self):
        """workout not found → (False, reason about missing workout), not the type guard."""
        from backend.services.speed_signal import compute_and_store_speed_signal
        from backend.models import Workout, WorkoutSplit, UserPreferences, StrydActivity
        session = _FakeSession({
            "Workout": [],  # empty — workout not found
            "WorkoutSplit": [],
            "UserPreferences": [],
            "StrydActivity": [],
        })
        ok, reason = compute_and_store_speed_signal("nonexistent-id", session)
        assert not ok
        # The reason should mention "not found" rather than "not a run type"
        assert "not found" in (reason or ""), (
            f"Expected 'not found' reason when workout missing, got {reason!r}"
        )

    def test_type_guard_fires_after_workout_found(self):
        """Cycling workout that exists → type guard fires, not the not-found guard."""
        from backend.services.speed_signal import compute_and_store_speed_signal
        wo = _workout(workout_type="cycling")
        session = _make_session(wo)
        ok, reason = compute_and_store_speed_signal("w-test", session)
        assert not ok
        assert reason == "workout is not a run type"


# ---------------------------------------------------------------------------
# AC6 – Docstring accurately reflects the implemented guard
# ---------------------------------------------------------------------------

class TestDocstring:

    def test_docstring_mentions_workout_type_guard(self):
        import inspect
        from backend.services.speed_signal import compute_and_store_speed_signal
        doc = inspect.getdoc(compute_and_store_speed_signal) or ""
        assert "run" in doc.lower(), (
            "Docstring should mention the run-type guard case"
        )
