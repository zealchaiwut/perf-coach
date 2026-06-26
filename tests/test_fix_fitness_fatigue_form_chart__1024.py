"""Tests for issue #1024: Fix Fitness Fatigue Form chart showing empty baseline state.

The Fitness Fatigue Form chart (CTL/ATL/TSB) was incorrectly showing the
"building a baseline" empty state for athletes who have existing fitness,
fatigue, and freshness data. Root cause: building_baseline was being set True
when endurance/speed scores lacked qualifying runs, even though CTL/ATL/TSB
data was fully available.

Acceptance Criteria:
AC1 - Chart renders CTL/ATL/TSB for athletes with non-zero fitness/fatigue/freshness.
AC2 - building_baseline=True only when data is genuinely below the plotting threshold.
AC3 - Chart CTL/ATL/TSB values match what the fitness model produces for the same data.
AC4 - Athletes with truly insufficient data (no load history) still get building_baseline=True.
"""
from datetime import date, timedelta


class TestFitnessFatigueFormChartBaselineFlag:

    def _make_load_series(self, n_days, start="2026-01-01", daily_load=50):
        d = date.fromisoformat(start)
        return [
            {"date": str(d + timedelta(days=i)), "daily_load": daily_load}
            for i in range(n_days)
        ]

    def _make_run(self, run_id, run_date, band="easy"):
        return {
            "run_id": run_id,
            "run_date": run_date,
            "laps": [{
                "band": band,
                "avg_hr": 140,
                "avg_power": 200,
                "distance_km": 5.0,
                "duration_seconds": 1800,
            }],
            "decoupling_pct": None,
        }

    def test_ac1_building_baseline_false_with_sufficient_load_despite_few_qualifying_runs(self):
        """AC1: building_baseline=False when load history is sufficient for CTL/ATL/TSB,
        even when endurance/speed scores don't have enough qualifying runs.

        This was the primary bug: an athlete with non-zero CTL/ATL/TSB (visible in the
        Log Readiness card) saw the building-baseline empty state on the Fitness Fatigue
        Form chart because the endurance/speed score 'building_baseline' was being
        propagated to the chart's own flag.
        """
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.fitness_model import MIN_HISTORY_DAYS
        from backend.services.zone_constants import MIN_QUALIFYING_RUNS

        # Provide a series with well more than MIN_HISTORY_DAYS worth of non-zero load
        series = self._make_load_series(MIN_HISTORY_DAYS + 10, daily_load=50)

        # Provide fewer than MIN_QUALIFYING_RUNS qualifying runs (endurance score will be
        # in building_baseline state, but CTL/ATL/TSB data is fully available)
        runs = [
            self._make_run(f"r{i}", f"2026-02-{i:02d}", band="easy")
            for i in range(1, MIN_QUALIFYING_RUNS)  # one fewer than required
        ]

        result = compute_performance_chart(
            daily_load_series=series,
            runs=runs,
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-05",
        )

        assert result["building_baseline"] is False, (
            "building_baseline must be False when load history >= MIN_HISTORY_DAYS, "
            "even if endurance/speed scoring has insufficient qualifying runs"
        )

    def test_ac1_ctl_atl_tsb_arrays_populated_for_athlete_with_load_history(self):
        """AC1: CTL/ATL/TSB arrays have non-null values whenever load history exists."""
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.fitness_model import MIN_HISTORY_DAYS

        series = self._make_load_series(MIN_HISTORY_DAYS + 10, daily_load=50)
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-05",
        )

        assert result["dates"], "dates array must not be empty when load data exists"
        assert any(v is not None for v in result["ctl"]), "ctl must have non-null values"
        assert any(v is not None for v in result["atl"]), "atl must have non-null values"
        assert any(v is not None for v in result["tsb"]), "tsb must have non-null values"

    def test_ac2_building_baseline_false_for_athlete_with_training_history_and_no_runs(self):
        """AC2: building_baseline=False for an established athlete even with zero qualifying runs."""
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.fitness_model import MIN_HISTORY_DAYS

        series = self._make_load_series(MIN_HISTORY_DAYS * 3, daily_load=50)
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-03-01",
            end_date="2026-03-10",
        )

        assert result["building_baseline"] is False

    def test_ac3_ctl_values_match_fitness_model_for_same_input(self):
        """AC3: CTL/ATL/TSB from compute_performance_chart match compute_fitness_series output.

        The chart data must be consistent with what the Log Readiness card uses — both
        derive from the same fitness model on the same load series.
        """
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.fitness_model import compute_fitness_series

        series = self._make_load_series(60, start="2026-01-01", daily_load=50)
        target_date = "2026-03-01"

        chart_result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date=target_date,
            end_date=target_date,
        )

        fitness_result = compute_fitness_series(series)
        fitness_by_date = {row["date"]: row for row in fitness_result.get("days", [])}

        assert target_date in fitness_by_date, f"{target_date} not in fitness model output"
        assert chart_result["dates"] and target_date in chart_result["dates"], \
            f"{target_date} not in chart dates"

        idx = chart_result["dates"].index(target_date)
        fm = fitness_by_date[target_date]

        assert chart_result["ctl"][idx] == fm["ctl"], (
            f"CTL mismatch: chart={chart_result['ctl'][idx]}, fitness_model={fm['ctl']}"
        )
        assert chart_result["atl"][idx] == fm["atl"], (
            f"ATL mismatch: chart={chart_result['atl'][idx]}, fitness_model={fm['atl']}"
        )
        assert chart_result["tsb"][idx] == fm["tsb"], (
            f"TSB mismatch: chart={chart_result['tsb'][idx]}, fitness_model={fm['tsb']}"
        )

    def test_ac4_building_baseline_true_for_athlete_with_no_workout_load(self):
        """AC4: building_baseline=True for a brand-new athlete with no training load.

        Athletes who have never logged a workout should still see the building-baseline
        message, not a flat-zero chart.
        """
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.fitness_model import MIN_HISTORY_DAYS

        # Series with all-zero load — simulates an athlete who has never trained
        series = self._make_load_series(MIN_HISTORY_DAYS + 10, daily_load=0)
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-05",
        )

        assert result["building_baseline"] is True, (
            "building_baseline must be True when all daily_load is 0 "
            "(athlete has never trained)"
        )

    def test_ac4_building_baseline_true_when_load_history_too_short(self):
        """AC4: building_baseline=True when load series is shorter than MIN_HISTORY_DAYS.

        Regression guard: athletes with genuinely too little history must still see
        the baseline message.
        """
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.fitness_model import MIN_HISTORY_DAYS

        # Fewer days than the minimum threshold
        series = self._make_load_series(MIN_HISTORY_DAYS - 1, daily_load=50)
        end = str(date.fromisoformat("2026-01-01") + timedelta(days=MIN_HISTORY_DAYS - 2))
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-01-01",
            end_date=end,
        )

        assert result["building_baseline"] is True
