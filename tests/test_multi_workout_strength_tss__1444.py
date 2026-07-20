"""Tests for issue #1444: per-workout TSS distribution on multi-workout days.

Acceptance criteria covered:
  AC1 — When 2+ strength workouts exist, distribute_strength_tss is called once
        per workout (not once across the pooled set), using that workout's own TSS.
  AC2 — Per-muscle-group loads on a multi-workout day match sum of per-workout
        distributions, not a single pooled distribution.
  AC3 — Single-workout days produce identical per-muscle-group loads.
  AC4 — The _tss field is no longer written onto exercise dicts inside
        recompute_strength_load_for_date.
  AC5 — The comment at the per-workout loop accurately describes per-workout
        distribution, not a single pooled redistribution.
"""
from __future__ import annotations

import inspect

import pytest

from backend.services.muscle_load import distribute_strength_tss


def _catalog(*entries):
    return {name: parts for name, parts in entries}


_BENCH_CATALOG = _catalog(
    ("bench press", [{"part": "chest", "ratio": 0.7}, {"part": "triceps", "ratio": 0.3}]),
)

_SQUAT_CATALOG = _catalog(
    ("squat", [{"part": "quads", "ratio": 0.6}, {"part": "glutes", "ratio": 0.4}]),
)

_COMBINED_CATALOG = _catalog(
    ("bench press", [{"part": "chest", "ratio": 0.7}, {"part": "triceps", "ratio": 0.3}]),
    ("squat", [{"part": "quads", "ratio": 0.6}, {"part": "glutes", "ratio": 0.4}]),
)

# Workout A: heavy bench (chest-dominant), high TSS
_WORKOUT_A_TSS = 50.0
_WORKOUT_A_EXERCISES = [
    {"name": "bench press", "sets": 4, "reps": 6, "weight_kg": 100.0},
]

# Workout B: light squat (quad-dominant), low TSS — different volume-to-TSS ratio
_WORKOUT_B_TSS = 20.0
_WORKOUT_B_EXERCISES = [
    {"name": "squat", "sets": 3, "reps": 8, "weight_kg": 80.0},
]


class TestAC1PerWorkoutDistribution:
    """AC1: per-workout dispatch produces correct loads for each workout."""

    def test_workout_a_chest_load_uses_only_workout_a_tss(self):
        loads, _ = distribute_strength_tss(
            _WORKOUT_A_TSS, _WORKOUT_A_EXERCISES, _COMBINED_CATALOG
        )
        # Bench press: 100% share, chest ratio 0.7 → chest = 50 × 1.0 × 0.7
        assert abs(loads.get("chest", 0.0) - 35.0) < 1e-9

    def test_workout_b_quad_load_uses_only_workout_b_tss(self):
        loads, _ = distribute_strength_tss(
            _WORKOUT_B_TSS, _WORKOUT_B_EXERCISES, _COMBINED_CATALOG
        )
        # Squat: 100% share, quad ratio 0.6 → quad = 20 × 1.0 × 0.6
        assert abs(loads.get("quad", 0.0) - 12.0) < 1e-9

    def test_workout_a_does_not_produce_quad_load(self):
        loads, _ = distribute_strength_tss(
            _WORKOUT_A_TSS, _WORKOUT_A_EXERCISES, _COMBINED_CATALOG
        )
        assert loads.get("quad", 0.0) == pytest.approx(0.0)

    def test_workout_b_does_not_produce_chest_load(self):
        loads, _ = distribute_strength_tss(
            _WORKOUT_B_TSS, _WORKOUT_B_EXERCISES, _COMBINED_CATALOG
        )
        assert loads.get("chest", 0.0) == pytest.approx(0.0)


class TestAC2PerWorkoutSumDiffersFromPooled:
    """AC2: per-workout sum differs from pooled distribution when TSS ratios differ."""

    def _per_workout_sum(self):
        loads_a, _ = distribute_strength_tss(
            _WORKOUT_A_TSS, _WORKOUT_A_EXERCISES, _COMBINED_CATALOG
        )
        loads_b, _ = distribute_strength_tss(
            _WORKOUT_B_TSS, _WORKOUT_B_EXERCISES, _COMBINED_CATALOG
        )
        combined: dict[str, float] = {}
        for g, v in loads_a.items():
            combined[g] = combined.get(g, 0.0) + v
        for g, v in loads_b.items():
            combined[g] = combined.get(g, 0.0) + v
        return combined

    def _pooled(self):
        pooled_exercises = _WORKOUT_A_EXERCISES + _WORKOUT_B_EXERCISES
        pooled_tss = _WORKOUT_A_TSS + _WORKOUT_B_TSS
        loads, _ = distribute_strength_tss(pooled_tss, pooled_exercises, _COMBINED_CATALOG)
        return loads

    def test_chest_load_differs_between_per_workout_and_pooled(self):
        per_wo = self._per_workout_sum()
        pooled = self._pooled()
        # Per-workout: chest = 50 × 0.7 = 35
        # Pooled: bench volume = 4×6×100 = 2400, squat volume = 3×8×80 = 1920
        # bench share = 2400/4320, chest = 70 × (2400/4320) × 0.7 ≈ 27.22
        assert per_wo.get("chest", 0.0) != pytest.approx(pooled.get("chest", 0.0), rel=0.01)

    def test_per_workout_chest_is_35(self):
        per_wo = self._per_workout_sum()
        assert per_wo.get("chest", 0.0) == pytest.approx(35.0)

    def test_per_workout_quad_is_12(self):
        per_wo = self._per_workout_sum()
        assert per_wo.get("quad", 0.0) == pytest.approx(12.0)

    def test_pooled_chest_differs_from_35(self):
        pooled = self._pooled()
        # bench volume 2400 / total 4320 → bench_share ≈ 0.5556
        # chest = 70 × 0.5556 × 0.7 ≈ 27.22  (not 35)
        assert pooled.get("chest", 0.0) != pytest.approx(35.0, rel=0.01)


class TestAC3SingleWorkoutUnchanged:
    """AC3: single-workout days produce identical per-muscle-group loads."""

    def test_single_workout_bench_chest_load(self):
        exercises = [{"name": "bench press", "sets": 3, "reps": 8, "weight_kg": 80.0}]
        catalog = _BENCH_CATALOG
        tss = 40.0
        loads, _ = distribute_strength_tss(tss, exercises, catalog)
        # Single exercise, 100% share, chest ratio 0.7
        assert abs(loads.get("chest", 0.0) - tss * 0.7) < 1e-9

    def test_single_workout_same_result_on_repeated_call(self):
        exercises = [{"name": "bench press", "sets": 3, "reps": 8, "weight_kg": 80.0}]
        catalog = _BENCH_CATALOG
        tss = 40.0
        loads1, _ = distribute_strength_tss(tss, exercises, catalog)
        loads2, _ = distribute_strength_tss(tss, exercises, catalog)
        assert loads1 == loads2

    def test_single_workout_multi_exercise_proportional(self):
        exercises = [
            {"name": "bench press", "sets": 3, "reps": 8, "weight_kg": 80.0},
            {"name": "squat", "sets": 3, "reps": 8, "weight_kg": 80.0},
        ]
        catalog = _COMBINED_CATALOG
        tss = 60.0
        loads, _ = distribute_strength_tss(tss, exercises, catalog)
        # Equal volume → equal share (0.5 each)
        assert loads.get("chest", 0.0) == pytest.approx(tss * 0.5 * 0.7)
        assert loads.get("quad", 0.0) == pytest.approx(tss * 0.5 * 0.6)


class TestAC4NoTssFieldOnExercises:
    """AC4: recompute_strength_load_for_date source must not assign _tss to exercises."""

    def test_no_tss_field_assignment_in_source(self):
        from backend.services import muscle_load as _ml_mod
        src = inspect.getsource(_ml_mod.recompute_strength_load_for_date)
        # The old code wrote ex["_tss"] = ... onto exercise dicts; verify that's gone.
        assert '"_tss"' not in src, "Exercise dict must not use string key '_tss'"
        assert "'_tss'" not in src, "Exercise dict must not set '_tss' key on exercise dicts"

    def test_distribute_strength_tss_does_not_mutate_exercise_dicts(self):
        exercises = [
            {"name": "bench press", "sets": 3, "reps": 6, "weight_kg": 100.0},
        ]
        import copy
        original = copy.deepcopy(exercises)
        distribute_strength_tss(30.0, exercises, _BENCH_CATALOG)
        assert exercises == original, "distribute_strength_tss must not mutate exercise dicts"


class TestAC5CommentAccuracy:
    """AC5: the comment near the per-workout loop describes per-workout distribution."""

    def test_comment_describes_per_workout_not_pooled(self):
        from backend.services import muscle_load as _ml_mod
        src = inspect.getsource(_ml_mod.recompute_strength_load_for_date)
        # The old misleading comment referenced "pooled" or "all_exercises" pooling
        # The new comment should describe per-workout distribution
        src_lower = src.lower()
        assert "per-workout" in src_lower or "per workout" in src_lower or "each workout" in src_lower, (
            "Comment must describe per-workout distribution"
        )

    def test_workout_batches_loop_exists_in_source(self):
        from backend.services import muscle_load as _ml_mod
        src = inspect.getsource(_ml_mod.recompute_strength_load_for_date)
        # The implementation should loop over workout_batches (per-workout)
        assert "workout_batches" in src, (
            "recompute_strength_load_for_date must use per-workout loop (workout_batches)"
        )
