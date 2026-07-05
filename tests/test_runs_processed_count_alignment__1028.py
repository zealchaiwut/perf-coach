"""Tests for issue #1028: runs_processed count must match workouts actually processed by
recompute_user_running_tss.

Acceptance Criteria:
  AC1: runs_processed reflects the count of workouts actually processed by
       recompute_user_running_tss, not an independently computed pre-filter count.
  AC2: The filter expression used to count runs is identical to the filter
       applied inside recompute_user_running_tss (no divergence).
  AC3: If recompute_user_running_tss returns a processed count, that value is
       used directly as runs_processed; if not, a shared filter constant/helper
       is extracted and used in both places.
  AC4: Workouts of type "Trail Run" or "Treadmill Run" are either consistently
       included or consistently excluded by both the count and the recompute
       function — no partial matching.
  AC5: The backfill API response for a user with mixed workout types returns a
       runs_processed value matching the number of workouts TSS was actually
       recomputed for.
"""

import inspect
from types import SimpleNamespace
from unittest import mock


def _make_prefs(ftp_w=200, threshold_hr=165, threshold_pace=300):
    return SimpleNamespace(
        ftp_w=ftp_w,
        threshold_hr=threshold_hr,
        threshold_pace_seconds_per_km=threshold_pace,
    )


# ---------------------------------------------------------------------------
# AC1: runs_processed comes from recompute_user_running_tss, not a separate query
# ---------------------------------------------------------------------------

class TestRunsProcessedSourceAC1:
    """AC1: runs_processed reflects the count from recompute_user_running_tss."""

    def test_recompute_user_running_tss_returns_int(self):
        """recompute_user_running_tss must return an int (count of workouts processed)."""
        from backend.services.tss import recompute_user_running_tss

        # Verify it returns int at runtime by mocking a minimal call
        mock_session = mock.MagicMock()
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = recompute_user_running_tss("user-1", mock_session)
        assert isinstance(result, int), (
            f"recompute_user_running_tss must return int, got {type(result)}"
        )

    def test_recompute_user_running_tss_returns_zero_for_no_workouts(self):
        """Returns 0 when no run workouts exist for the user."""
        from backend.services.tss import recompute_user_running_tss

        mock_session = mock.MagicMock()
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = recompute_user_running_tss("user-1", mock_session)
        assert result == 0

    def test_recompute_user_running_tss_returns_correct_count(self):
        """Returns the number of workouts it actually iterated over."""
        from backend.services.tss import recompute_user_running_tss

        fake_workouts = [
            SimpleNamespace(id=f"w{i}", workout_type="Run") for i in range(5)
        ]
        mock_session = mock.MagicMock()
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = (
            fake_workouts
        )

        with mock.patch("backend.services.tss.persist_running_tss"):
            result = recompute_user_running_tss("user-1", mock_session)

        assert result == 5, f"Expected 5 workouts processed, got {result}"

    def test_backfill_uses_return_value_of_recompute_not_separate_count(self):
        """backfill_performance_for_athlete must NOT run its own count() query for runs.

        It must rely on the value returned by recompute_user_running_tss.
        """
        from backend.services import backfill_performance

        src = inspect.getsource(backfill_performance)
        # There must NOT be a standalone .count() call for run_count separate from the
        # recompute function.  The runs_processed should come from recompute's return value.
        # We check that the old pattern (ilike + .count()) is gone.
        assert 'run_count' not in src, (
            "backfill_performance.py must not use a separate run_count variable; "
            "derive runs_processed from recompute_user_running_tss return value"
        )

    def test_backfill_runs_processed_equals_recompute_return(self):
        """runs_processed in backfill result equals what recompute_user_running_tss returned."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss",
            return_value=7,
        ) as mock_tss, mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve",
            return_value=({}, None),
        ):
            result = backfill_performance_for_athlete("user-1", mock_db)

        assert result["runs_processed"] == 7, (
            f"runs_processed must equal the return value of recompute_user_running_tss (7), "
            f"got {result['runs_processed']}"
        )
        mock_tss.assert_called_once()


# ---------------------------------------------------------------------------
# AC2: No divergence between the filter in backfill and in recompute
# ---------------------------------------------------------------------------

class TestFilterAlignmentAC2:
    """AC2: The filter used to count runs is identical to the filter in recompute."""

    def test_backfill_does_not_contain_independent_ilike_run_filter(self):
        """backfill_performance.py must not contain a standalone ilike run filter query."""
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)

        # The old divergent filter was ilike("%run%") for counting only.
        # It should no longer exist as a standalone query separate from recompute.
        # We check the count() pattern is absent.
        assert ".count()" not in src, (
            "backfill_performance.py must not use .count() to derive runs_processed; "
            "it should use the return value from recompute_user_running_tss instead"
        )

    def test_recompute_filter_is_consistent_with_itself(self):
        """recompute_user_running_tss uses exactly one filter for workout_type."""
        from backend.services.tss import recompute_user_running_tss
        src = inspect.getsource(recompute_user_running_tss)
        # Exactly one ilike call for workout_type filtering
        ilike_count = src.count("ilike(")
        assert ilike_count == 1, (
            f"recompute_user_running_tss should have exactly one ilike filter, found {ilike_count}"
        )


# ---------------------------------------------------------------------------
# AC3: Return value path — recompute returns count, backfill uses it directly
# ---------------------------------------------------------------------------

class TestReturnValuePathAC3:
    """AC3: recompute_user_running_tss returns a count; backfill uses it directly."""

    def test_backfill_captures_return_value_of_recompute(self):
        """backfill_performance_for_athlete must assign the return of recompute to a variable."""
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        # The return value of recompute_user_running_tss must be captured
        assert "recompute_user_running_tss(" in src, (
            "backfill_performance.py must call recompute_user_running_tss"
        )
        # It should not call it as a fire-and-forget (void call); the result should be stored
        lines = src.splitlines()
        for line in lines:
            stripped = line.strip()
            if "recompute_user_running_tss(" in stripped:
                # The call must be assigned (not a bare expression)
                assert stripped.startswith("recompute_user_running_tss(") is False, (
                    "The return value of recompute_user_running_tss must be assigned, "
                    "not called as a bare expression"
                )
                break

    def test_backfill_runs_processed_zero_when_recompute_returns_zero(self):
        """When recompute returns 0, runs_processed is 0."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss",
            return_value=0,
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve",
            return_value=({}, None),
        ):
            result = backfill_performance_for_athlete("user-1", mock_db)

        assert result["runs_processed"] == 0

    def test_backfill_runs_processed_nonzero_when_recompute_returns_nonzero(self):
        """When recompute returns 3, runs_processed is 3."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss",
            return_value=3,
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve",
            return_value=({}, None),
        ):
            result = backfill_performance_for_athlete("user-1", mock_db)

        assert result["runs_processed"] == 3


# ---------------------------------------------------------------------------
# AC4: Trail Run / Treadmill Run — consistent inclusion or exclusion
# ---------------------------------------------------------------------------

class TestTrailTreadmillConsistencyAC4:
    """AC4: Trail Run and Treadmill Run are consistently included or excluded."""

    def test_trail_run_included_only_if_recompute_includes_it(self):
        """If recompute processes Trail Run workouts, runs_processed includes them."""
        from backend.services.tss import recompute_user_running_tss

        trail_workout = SimpleNamespace(id="trail-1", workout_type="Trail Run")
        mock_session = mock.MagicMock()
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = (
            [trail_workout]
        )

        with mock.patch("backend.services.tss.persist_running_tss") as mock_persist:
            count = recompute_user_running_tss("user-1", mock_session)

        # If the recompute function's filter includes Trail Run, count is 1 and persist called.
        # If the filter excludes Trail Run, count is 0 and persist not called.
        # Either is acceptable, but they must be consistent (count matches what was processed).
        if mock_persist.called:
            assert count == 1, (
                "Trail Run was processed by persist_running_tss but count is not 1"
            )
        else:
            assert count == 0, (
                "Trail Run was NOT processed but count is non-zero"
            )

    def test_treadmill_run_included_only_if_recompute_includes_it(self):
        """If recompute processes Treadmill Run workouts, runs_processed includes them."""
        from backend.services.tss import recompute_user_running_tss

        treadmill_workout = SimpleNamespace(id="tm-1", workout_type="Treadmill Run")
        mock_session = mock.MagicMock()
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = (
            [treadmill_workout]
        )

        with mock.patch("backend.services.tss.persist_running_tss") as mock_persist:
            count = recompute_user_running_tss("user-1", mock_session)

        if mock_persist.called:
            assert count == 1, (
                "Treadmill Run was processed but count is not 1"
            )
        else:
            assert count == 0, (
                "Treadmill Run was NOT processed but count is non-zero"
            )

    def test_backfill_no_double_counting_trail_and_plain_run(self):
        """A user with Trail Run + Run: runs_processed equals only what recompute touches."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj

        # recompute says it processed 1 (only plain "Run", not "Trail Run")
        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss",
            return_value=1,
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve",
            return_value=({}, None),
        ):
            result = backfill_performance_for_athlete("user-1", mock_db)

        assert result["runs_processed"] == 1, (
            "runs_processed must match exactly what recompute processed (1), "
            f"got {result['runs_processed']}"
        )


# ---------------------------------------------------------------------------
# AC5: Mixed workout types — response matches actual recomputed count
# ---------------------------------------------------------------------------

class TestMixedWorkoutTypesAC5:
    """AC5: Backfill response for mixed types matches actual TSS recomputed count."""

    def test_cycling_not_matched_by_recompute_filter(self):
        """The filter in recompute_user_running_tss (ilike 'run%') does not match 'Cycling'."""
        from backend.services.tss import recompute_user_running_tss

        src = inspect.getsource(recompute_user_running_tss)
        # The filter must start-anchor at 'run' so that types like 'Cycling' cannot match.
        # ilike("%run%") would incorrectly match anything containing 'run' anywhere.
        # ilike("run%") only matches types that start with 'run'.
        assert 'ilike("%run%")' not in src, (
            "recompute_user_running_tss must not use ilike('%run%') — "
            "that would match 'Trail Run', 'Treadmill Run' etc. from the wrong direction"
        )
        # Verify the filter string used does NOT match 'Cycling' via Python string logic
        filter_patterns = [
            token.strip().strip('"\'')
            for token in src.split("ilike(")
            if ")" in token
        ]
        # Each pattern extracted should not match 'Cycling' case-insensitively
        for pat in filter_patterns:
            pat_lower = pat.rstrip(")").strip('"\'').lower()
            if pat_lower:
                import fnmatch
                assert not fnmatch.fnmatch("cycling", pat_lower), (
                    f"Filter pattern '{pat_lower}' in recompute would match 'Cycling'"
                )

    def test_strength_not_matched_by_recompute_filter(self):
        """The filter in recompute_user_running_tss does not match 'Strength'."""
        from backend.services.tss import recompute_user_running_tss

        src = inspect.getsource(recompute_user_running_tss)
        # Same reasoning: 'Strength' does not start with 'run', so ilike('run%') excludes it
        import fnmatch
        filter_patterns = [
            token.strip().strip('"\'')
            for token in src.split("ilike(")
            if ")" in token
        ]
        for pat in filter_patterns:
            pat_lower = pat.rstrip(")").strip('"\'').lower()
            if pat_lower:
                assert not fnmatch.fnmatch("strength", pat_lower), (
                    f"Filter pattern '{pat_lower}' in recompute would match 'Strength'"
                )

    def test_backfill_mixed_types_runs_processed_from_recompute(self):
        """Mixed user: runs_processed equals recompute return regardless of other types."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj

        # Simulate recompute processed 2 runs out of a mixed set
        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss",
            return_value=2,
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve",
            return_value=({}, None),
        ):
            result = backfill_performance_for_athlete("user-1", mock_db)

        assert result["runs_processed"] == 2
        assert result["tss_recomputed"] is True
        assert result["thresholds_found"] is True

    def test_backfill_tss_error_still_uses_recompute_count(self):
        """Even when recompute raises, runs_processed should be 0 (not from a stale query)."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss",
            side_effect=RuntimeError("DB error"),
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve",
            return_value=({}, None),
        ):
            result = backfill_performance_for_athlete("user-1", mock_db)

        # When recompute fails, tss_recomputed is False and runs_processed must be 0
        assert result["tss_recomputed"] is False
        assert result["runs_processed"] == 0, (
            "When recompute fails, runs_processed must be 0 — not from a pre-filter count"
        )
