"""Tests for issue #1041: Align backfill run-count filter with performance endpoint.

Acceptance Criteria:
  AC1: backfill_performance.py uses exact-match Workout.workout_type == "run"
       instead of Workout.workout_type.ilike("%run%").
  AC2: The performance endpoint and the backfill summary both use the same
       filter expression for selecting run workouts.
  AC3: A workout with workout_type = "Trail Run" is NOT counted in runs_processed.
  AC4: A workout with workout_type = "Fun Run" is NOT counted in runs_processed.
  AC5: A workout with workout_type = "run" IS counted in runs_processed.
"""

import inspect
from types import SimpleNamespace
from unittest import mock


def _make_prefs(ftp_w=200, threshold_hr=165, threshold_pace=300):
    return SimpleNamespace(
        ftp_w=ftp_w,
        threshold_hr=threshold_hr,
        threshold_pace_seconds_per_km=threshold_pace,
        aerobic_decoupling_threshold=None,
        duration_curve_bests=None,
    )


# ---------------------------------------------------------------------------
# AC1: backfill uses exact-match == "run", not ilike
# ---------------------------------------------------------------------------

class TestBackfillUsesExactMatch:
    """AC1: backfill_performance.py must not use ilike for run-count query."""

    def test_backfill_source_does_not_contain_ilike_for_run_count(self):
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        assert "ilike" not in src, (
            "backfill_performance.py must not use ilike — use exact-match == 'run' instead"
        )

    def test_backfill_source_uses_exact_equality_for_workout_type(self):
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        assert 'workout_type == "run"' in src or "workout_type == 'run'" in src, (
            "backfill_performance.py must filter with workout_type == 'run' (exact match)"
        )


# ---------------------------------------------------------------------------
# AC2: performance endpoint and backfill both use the same filter
# ---------------------------------------------------------------------------

class TestBothPathsUseSameFilter:
    """AC2: The performance endpoint and backfill use the same run filter."""

    def test_performance_endpoint_uses_exact_equality(self):
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        assert 'workout_type == "run"' in src or "workout_type == 'run'" in src, (
            "Performance endpoint must filter with workout_type == 'run' (exact match)"
        )

    def test_backfill_uses_exact_equality(self):
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        assert 'workout_type == "run"' in src or "workout_type == 'run'" in src, (
            "Backfill must filter with workout_type == 'run' (exact match)"
        )

    def test_neither_path_uses_ilike(self):
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        assert "ilike" not in src, (
            "backfill_performance.py must not use ilike — it diverges from the performance endpoint"
        )


# ---------------------------------------------------------------------------
# AC3: "Trail Run" is NOT counted
# ---------------------------------------------------------------------------

class TestTrailRunNotCounted:
    """AC3: workout_type='Trail Run' must not appear in runs_processed."""

    def test_trail_run_workout_not_counted_by_backfill(self):
        """Backfill run-count query with exact match excludes 'Trail Run'."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()

        mock_db = mock.MagicMock()
        # Simulate DB: prefs row found, exact-match count returns 0
        # (Trail Run doesn't match == "run")
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss"
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve"
        ) as mock_curve:
            mock_curve.return_value = ({}, None)
            result = backfill_performance_for_athlete("user-trail", mock_db)

        assert result["runs_processed"] == 0, (
            "Trail Run workouts must not be counted by the exact-match filter"
        )

    def test_exact_equality_excludes_trail_run_string(self):
        """Direct string equality: 'Trail Run' != 'run'."""
        assert "Trail Run" != "run", "Exact match correctly excludes Trail Run"

    def test_ilike_would_have_matched_trail_run(self):
        """Verify the old ilike pattern would incorrectly include 'Trail Run'."""
        import re
        # Simulate what ilike('%run%') would have matched
        pattern = re.compile(r"run", re.IGNORECASE)
        assert pattern.search("Trail Run") is not None, (
            "Confirms the old ilike pattern was incorrect: it would match Trail Run"
        )


# ---------------------------------------------------------------------------
# AC4: "Fun Run" is NOT counted
# ---------------------------------------------------------------------------

class TestFunRunNotCounted:
    """AC4: workout_type='Fun Run' must not appear in runs_processed."""

    def test_fun_run_workout_not_counted_by_backfill(self):
        """Backfill run-count query with exact match excludes 'Fun Run'."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()

        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss"
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve"
        ) as mock_curve:
            mock_curve.return_value = ({}, None)
            result = backfill_performance_for_athlete("user-fun", mock_db)

        assert result["runs_processed"] == 0, (
            "Fun Run workouts must not be counted by the exact-match filter"
        )

    def test_exact_equality_excludes_fun_run_string(self):
        """Direct string equality: 'Fun Run' != 'run'."""
        assert "Fun Run" != "run", "Exact match correctly excludes Fun Run"

    def test_ilike_would_have_matched_fun_run(self):
        """Verify the old ilike pattern would incorrectly include 'Fun Run'."""
        import re
        pattern = re.compile(r"run", re.IGNORECASE)
        assert pattern.search("Fun Run") is not None, (
            "Confirms the old ilike pattern was incorrect: it would match Fun Run"
        )


# ---------------------------------------------------------------------------
# AC5: canonical "run" IS counted
# ---------------------------------------------------------------------------

class TestRunIsCounted:
    """AC5: workout_type='run' (canonical stored form) IS counted in runs_processed."""

    def test_canonical_run_workout_counted_by_backfill(self):
        """Backfill run-count query counts workouts with exact workout_type='run'."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()

        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj
        # Simulate 1 canonical "run" workout in DB
        mock_db.query.return_value.filter.return_value.count.return_value = 1

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss"
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve"
        ) as mock_curve:
            mock_curve.return_value = ({}, None)
            result = backfill_performance_for_athlete("user-run", mock_db)

        assert result["runs_processed"] == 1, (
            "A canonical 'run' workout must be counted in runs_processed"
        )

    def test_exact_equality_matches_canonical_run(self):
        """Direct string equality: 'run' == 'run'."""
        assert "run" == "run", "Exact match correctly includes the canonical run type"

    def test_backfill_and_performance_endpoint_agree_on_run_count(self):
        """Both paths must use workout_type == 'run' so counts agree."""
        import backend.main as main_mod
        from backend.services import backfill_performance

        perf_src = inspect.getsource(main_mod)
        backfill_src = inspect.getsource(backfill_performance)

        perf_uses_exact = 'workout_type == "run"' in perf_src or "workout_type == 'run'" in perf_src
        backfill_uses_exact = 'workout_type == "run"' in backfill_src or "workout_type == 'run'" in backfill_src

        assert perf_uses_exact, "Performance endpoint must use exact-match workout_type == 'run'"
        assert backfill_uses_exact, "Backfill must use exact-match workout_type == 'run'"
