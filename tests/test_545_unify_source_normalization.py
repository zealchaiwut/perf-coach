"""Tests for issue #545: Unify source normalization between _workout_list_dict
and training-log list endpoint.

AC: _workout_list_dict must apply the same source normalization as the
training-log endpoint: `w.source or w.tss_source or "manual"`, so a workout
with source=None but tss_source='strava' is never returned as null-source
from GET /api/workouts.
"""
from __future__ import annotations

import types
import uuid
from datetime import date

import pytest


def _make_workout(**kwargs) -> object:
    """Return a minimal workout stub with the given attributes."""
    defaults = {
        "id": uuid.uuid4(),
        "workout_date": date.today(),
        "name": "Test Run",
        "workout_type": "run",
        "run_subtype": None,
        "remarks": None,
        "tss": None,
        "tss_source": None,
        "source": None,
        "strava_activity_url": None,
        "strava_activity_pk": None,
        "stryd_activity_pk": None,
        "distance_km": None,
        "duration_seconds": None,
        "avg_hr": None,
        "max_hr": None,
        "elevation_m": None,
        "zone2_minutes": None,
        "feeling": None,
        "fuelled": None,
        "drills_minutes": None,
        "created_at": None,
        "manual_overrides": None,
        # _best_values_dict fields (all nullable)
        "best_1km_pace": None,
        "best_5km_pace": None,
        "best_10km_pace": None,
        "best_21km_pace": None,
        "best_42km_pace": None,
    }
    defaults.update(kwargs)
    obj = types.SimpleNamespace(**defaults)
    return obj


def _call_list_dict(w):
    """Import _workout_list_dict lazily to avoid top-level DB connection."""
    from backend.main import _workout_list_dict
    return _workout_list_dict(w, exercise_count=0)


# ── AC1: source=None, tss_source set ──────────────────────────────────────────

class TestSourceNormalization:
    """_workout_list_dict must apply `w.source or w.tss_source or "manual"`."""

    def test_source_none_tss_source_strava_returns_strava(self):
        """AC: source=None, tss_source='strava' → dict['source'] == 'strava'."""
        w = _make_workout(source=None, tss_source="strava")
        result = _call_list_dict(w)
        assert result["source"] == "strava", (
            f"_workout_list_dict must fall back to tss_source when source is None; "
            f"got {result['source']!r}"
        )

    def test_source_none_tss_source_stryd_returns_stryd(self):
        """AC: source=None, tss_source='stryd' → dict['source'] == 'stryd'."""
        w = _make_workout(source=None, tss_source="stryd")
        result = _call_list_dict(w)
        assert result["source"] == "stryd", (
            f"_workout_list_dict must fall back to tss_source when source is None; "
            f"got {result['source']!r}"
        )

    def test_source_none_tss_source_none_returns_manual(self):
        """AC: source=None, tss_source=None → dict['source'] == 'manual'."""
        w = _make_workout(source=None, tss_source=None)
        result = _call_list_dict(w)
        assert result["source"] == "manual", (
            f"_workout_list_dict must default to 'manual' when both source and "
            f"tss_source are None; got {result['source']!r}"
        )

    def test_source_set_is_returned_unchanged(self):
        """AC: source='strava' → dict['source'] == 'strava' (no change when set)."""
        w = _make_workout(source="strava", tss_source=None)
        result = _call_list_dict(w)
        assert result["source"] == "strava"

    def test_source_set_takes_precedence_over_tss_source(self):
        """AC: source='manual', tss_source='strava' → dict['source'] == 'manual'."""
        w = _make_workout(source="manual", tss_source="strava")
        result = _call_list_dict(w)
        assert result["source"] == "manual"


# ── AC2: consistency between _workout_list_dict and training-log normalization ─

class TestConsistencyWithTrainingLog:
    """Normalization in _workout_list_dict must match the training-log formula."""

    @pytest.mark.parametrize("source,tss_source,expected", [
        (None,     "strava",  "strava"),
        (None,     "stryd",   "stryd"),
        (None,     "manual",  "manual"),
        (None,     None,      "manual"),
        ("strava", "stryd",   "strava"),
        ("stryd",  None,      "stryd"),
        ("manual", None,      "manual"),
    ])
    def test_normalization_matches_training_log_formula(self, source, tss_source, expected):
        """_workout_list_dict['source'] matches `w.source or w.tss_source or 'manual'`."""
        w = _make_workout(source=source, tss_source=tss_source)
        result = _call_list_dict(w)
        training_log_value = source or tss_source or "manual"
        assert result["source"] == training_log_value, (
            f"source={source!r}, tss_source={tss_source!r}: "
            f"_workout_list_dict returned {result['source']!r}, "
            f"training-log formula gives {training_log_value!r}"
        )
        assert result["source"] == expected
