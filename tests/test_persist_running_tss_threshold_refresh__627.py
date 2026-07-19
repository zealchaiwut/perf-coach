"""Tests for issue #627: persist_running_tss should refresh computed TSS on threshold change.

Context: when recompute_user_running_tss is called after a threshold change, workouts
that already have a computed TSS (tss_source="calculated") must have their stored value
refreshed. The old guard ``if workout.tss is None`` was too strict — it prevented refresh
of previously-computed values. The fix changes the guard to:
    if workout.tss is None or workout.tss_source == "calculated"

Acceptance criteria:
  AC1 - persist_running_tss overwrites workout.tss when tss_source == "calculated"
        (threshold-refresh path works)
  AC2 - persist_running_tss does NOT overwrite workout.tss when tss_source is "manual"
        (manual entries are still protected)
  AC3 - persist_running_tss does NOT overwrite workout.tss when tss_source is any other
        non-"calculated" value (defensive: treat unknown source as protected)
  AC4 - recompute_user_running_tss causes tss to reflect new threshold on all running
        workouts with tss_source == "calculated"
"""
import types
import uuid

import pytest


# ── Helpers (mirror test_persist_expose_running_tss__582.py) ─────────────────

def _workout_ns(tss=None, tss_source=None, np=None, avg_hr=None,
                distance_km=None, duration_seconds=2700,
                workout_type="Run", user_id=None):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        tss=tss,
        tss_source=tss_source,
        tss_method=None,
        np=np,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        workout_type=workout_type,
    )


def _prefs_ns(ftp_w=None, threshold_pace_seconds_per_km=None, threshold_hr=None):
    return types.SimpleNamespace(
        ftp_w=ftp_w,
        threshold_pace_seconds_per_km=threshold_pace_seconds_per_km,
        threshold_hr=threshold_hr,
    )


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
    def __init__(self, workout, splits, prefs):
        self._workout = workout
        self._splits = splits
        self._prefs = prefs

    def get(self, model, workout_id):
        return self._workout

    def query(self, model):
        model_name = getattr(model, "__name__", str(model))
        if "WorkoutSplit" in model_name or "Split" in model_name:
            return _MockQuery(self._splits)
        if "UserPreferences" in model_name or "Preferences" in model_name:
            return _MockQuery([self._prefs] if self._prefs else [])
        return _MockQuery([])

    def expire(self, obj):
        pass


# ── AC1: overwrites when tss_source == "calculated" ──────────────────────────

def test_overwrites_calculated_tss_with_new_computation():
    """AC1: persist_running_tss must refresh workout.tss when tss_source == 'calculated'."""
    from backend.services.tss import persist_running_tss

    # Workout previously had TSS=50 computed with old threshold; now FTP=280 → TSS=100
    workout = _workout_ns(tss=50, tss_source="calculated", np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss == 100, (
        f"expected tss refreshed to 100 (new threshold), got {workout.tss}"
    )


def test_overwrites_calculated_tss_to_lower_value():
    """AC1: refresh also works when new computation yields a lower TSS than stored."""
    from backend.services.tss import persist_running_tss

    # High stored value, lower threshold now → lower TSS
    workout = _workout_ns(tss=200, tss_source="calculated", np=140, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    # computed: (3600 * (140/280)^2) / 36 = (3600 * 0.25) / 36 = 25
    assert workout.tss == 25, (
        f"expected tss refreshed to 25, got {workout.tss}"
    )


def test_tss_source_remains_calculated_after_refresh():
    """AC1: tss_source stays 'calculated' after a threshold-triggered refresh."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=50, tss_source="calculated", np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss_source == "calculated"


# ── AC2: does NOT overwrite when tss_source == "manual" ──────────────────────

def test_does_not_overwrite_manual_tss_source():
    """AC2: persist_running_tss must NOT overwrite workout.tss when tss_source == 'manual'."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=75, tss_source="manual", np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss == 75, "manual TSS must not be overwritten"


def test_manual_tss_source_unchanged():
    """AC2: tss_source remains 'manual' after a call to persist_running_tss."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=75, tss_source="manual", np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss_source == "manual"


# ── AC3: does NOT overwrite when tss_source is unknown / None-with-value ──────

def test_does_not_overwrite_when_tss_set_and_source_is_none():
    """AC3: tss is not overwritten when it has a value but tss_source is None (ambiguous)."""
    from backend.services.tss import persist_running_tss

    # Ambiguous state: tss set but source unknown → treat as protected
    workout = _workout_ns(tss=60, tss_source=None, np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss == 60, "TSS with unknown source must not be overwritten"


def test_does_not_overwrite_when_tss_source_is_strava():
    """AC3: tss is not overwritten when tss_source == 'strava' (external source)."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=80, tss_source="strava", np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss == 80, "Strava-sourced TSS must not be overwritten"


# ── AC4: recompute_user_running_tss refreshes calculated workouts ─────────────

def test_recompute_user_running_tss_refreshes_calculated_workouts():
    """AC4: recompute_user_running_tss causes tss to reflect new threshold for 'calculated' workouts."""
    from backend.services.tss import recompute_user_running_tss

    user_id = uuid.uuid4()
    # Two run workouts with previously computed TSS
    w1 = _workout_ns(tss=50, tss_source="calculated", np=280, duration_seconds=3600,
                     workout_type="Run", user_id=user_id)
    w2 = _workout_ns(tss=30, tss_source="calculated", np=140, duration_seconds=3600,
                     workout_type="Run", user_id=user_id)
    prefs = _prefs_ns(ftp_w=280)

    class _MultiWorkoutSession:
        def __init__(self):
            self._workouts = {w1.id: w1, w2.id: w2}
            self._prefs = prefs

        def get(self, model, workout_id):
            return self._workouts.get(workout_id)

        def query(self, model):
            model_name = getattr(model, "__name__", str(model))
            if "Workout" in model_name and "Split" not in model_name:
                return _WorkoutQuery([w1, w2])
            if "WorkoutSplit" in model_name or "Split" in model_name:
                return _MockQuery([])
            if "UserPreferences" in model_name or "Preferences" in model_name:
                return _MockQuery([self._prefs])
            return _MockQuery([])

        def expire(self, obj):
            pass

    class _WorkoutQuery:
        def __init__(self, workouts):
            self._workouts = workouts

        def filter(self, *args, **kwargs):
            return self

        def ilike(self, *args, **kwargs):
            return self

        def all(self):
            return self._workouts

    session = _MultiWorkoutSession()
    count = recompute_user_running_tss(user_id, session)

    assert count == 2
    # w1: np=280, ftp=280 → IF=1.0, duration=3600 → TSS=100
    assert w1.tss == 100, f"w1.tss should be refreshed to 100, got {w1.tss}"
    # w2: np=140, ftp=280 → IF=0.5, duration=3600 → TSS=25
    assert w2.tss == 25, f"w2.tss should be refreshed to 25, got {w2.tss}"
