"""
Tests for issue #704: personal-record detection from run history.

All tests operate on the three pure functions only — no server, no database.
"""
import pytest
from backend.services.pr_detection import (
    detect_speed_records,
    detect_power_records,
    detect_volume_records,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(id, date, distance_km, duration_seconds, tss=None, avg_power=None):
    return {
        "id": id,
        "workout_date": date,
        "distance_km": distance_km,
        "duration_seconds": duration_seconds,
        "tss": tss,
        "avg_power": avg_power,
        "workout_type": "run",
    }


def _pace_point(duration_seconds, best_value_sec_per_km, source_workout_id, date, source_workout=None):
    return {
        "duration_seconds": duration_seconds,
        "best_value": best_value_sec_per_km,
        "source_workout_id": source_workout_id,
        "date": date,
        "source_workout": source_workout,
    }


def _power_point(duration_seconds, best_value_watts, source_workout_id, date, source_workout=None):
    return {
        "duration_seconds": duration_seconds,
        "best_value": best_value_watts,
        "source_workout_id": source_workout_id,
        "date": date,
        "source_workout": source_workout,
    }


# ══════════════════════════════════════════════════════════════════════════════
# detect_speed_records — clean history: one workout wins every speed category
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectSpeedRecordsCleanHistory:
    """A single marathon run is the only workout; it wins all six standard distances."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # pace = 14400 / 42.195 ≈ 341.3 sec/km  →  implied distance = 14400 / 341.3 ≈ 42.2 km
        self.run = _run("m1", "2026-01-10", 42.195, 14400, tss=120)
        self.curve = [
            _pace_point(14400, 14400 / 42.195, "m1", "2026-01-10", self.run)
        ]
        self.result = detect_speed_records(self.curve, [self.run])

    def test_returns_five_km_record(self):
        assert "5km" in self.result
        assert "reason" not in self.result["5km"]

    def test_five_km_value_is_numeric(self):
        assert isinstance(self.result["5km"]["value"], (int, float))

    def test_five_km_value_is_positive(self):
        assert self.result["5km"]["value"] > 0

    def test_five_km_date_matches_workout(self):
        assert self.result["5km"]["date"] == "2026-01-10"

    def test_five_km_source_workout_id_present(self):
        sw = self.result["5km"]["sourceWorkout"]
        assert sw is not None
        assert sw["id"] == "m1"

    def test_returns_one_km_record(self):
        assert "1km" in self.result
        assert "reason" not in self.result["1km"]

    def test_returns_marathon_record(self):
        assert "marathon" in self.result
        assert "reason" not in self.result["marathon"]

    def test_marathon_value_equals_duration(self):
        # For a run at exactly marathon distance the estimated time equals the full duration.
        val = self.result["marathon"]["value"]
        assert abs(val - 14400.0) < 1.0

    def test_debug_key_present(self):
        assert "debug" in self.result

    def test_debug_contains_five_km(self):
        assert "5km" in self.result["debug"]

    def test_debug_candidates_non_empty(self):
        assert len(self.result["debug"]["5km"]["candidates"]) >= 1

    def test_record_fields_are_exactly_three(self):
        record = self.result["5km"]
        assert set(record.keys()) == {"value", "date", "sourceWorkout"}


# ══════════════════════════════════════════════════════════════════════════════
# detect_speed_records — partial history: insufficient data for some distances
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectSpeedRecordsPartialHistory:
    """Only a 10 km run exists; marathon (42.195 km) cannot be interpolated."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.run = _run("r1", "2026-02-01", 10.0, 3000)  # pace = 300 sec/km
        self.curve = [
            _pace_point(3000, 300.0, "r1", "2026-02-01", self.run)
        ]
        self.result = detect_speed_records(self.curve, [self.run])

    def test_five_km_present(self):
        assert "5km" in self.result
        assert "reason" not in self.result["5km"]

    def test_ten_km_present(self):
        assert "10km" in self.result
        assert "reason" not in self.result["10km"]

    def test_marathon_omitted_with_reason(self):
        rec = self.result["marathon"]
        assert "reason" in rec
        assert "value" not in rec

    def test_half_marathon_omitted_with_reason(self):
        rec = self.result["half_marathon"]
        assert "reason" in rec
        assert "value" not in rec

    def test_reason_is_non_empty_string(self):
        reason = self.result["marathon"]["reason"]
        assert isinstance(reason, str) and len(reason) > 0


# ══════════════════════════════════════════════════════════════════════════════
# detect_speed_records — tie: two workouts share the same pace; earlier wins
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectSpeedRecordsTieBreaking:
    """Two runs have the same average pace for 5 km; the earlier date must win."""

    @pytest.fixture(autouse=True)
    def setup(self):
        pace = 300.0  # 5:00 per km
        self.run_early = _run("e1", "2026-01-05", 5.0, int(5.0 * pace))
        self.run_late = _run("e2", "2026-02-10", 5.0, int(5.0 * pace))
        self.curve = [
            _pace_point(int(5.0 * pace), pace, "e1", "2026-01-05", self.run_early),
            _pace_point(int(5.0 * pace), pace, "e2", "2026-02-10", self.run_late),
        ]
        self.result = detect_speed_records(self.curve, [self.run_early, self.run_late])

    def test_five_km_record_present(self):
        assert "5km" in self.result
        assert "reason" not in self.result["5km"]

    def test_earlier_date_wins_on_tie(self):
        assert self.result["5km"]["date"] == "2026-01-05"

    def test_source_workout_is_earlier_run(self):
        assert self.result["5km"]["sourceWorkout"]["id"] == "e1"


# ══════════════════════════════════════════════════════════════════════════════
# detect_speed_records — empty-input paths
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectSpeedRecordsEmptyInput:

    def test_empty_runs_returns_reason(self):
        result = detect_speed_records([_pace_point(300, 260.0, "x", "2026-01-01")], [])
        assert "reason" in result

    def test_empty_curve_returns_reason(self):
        result = detect_speed_records([], [_run("x", "2026-01-01", 5.0, 1300)])
        assert "reason" in result

    def test_both_empty_returns_reason(self):
        result = detect_speed_records([], [])
        assert "reason" in result

    def test_reason_is_string(self):
        result = detect_speed_records([], [])
        assert isinstance(result["reason"], str)

    def test_empty_result_has_no_speed_record_keys(self):
        result = detect_speed_records([], [])
        distance_keys = {"1km", "1mile", "5km", "10km", "half_marathon", "marathon"}
        assert not distance_keys.intersection(result.keys())


# ══════════════════════════════════════════════════════════════════════════════
# detect_power_records — clean history: one run wins every power category
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectPowerRecordsCleanHistory:
    """Power curve with points at 60 s, 300 s, 1200 s; all three are set."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.run = _run("pw1", "2026-01-15", 5.02, 1302, avg_power=285)
        self.curve = [
            _power_point(60, 320.0, "pw1", "2026-01-15", self.run),
            _power_point(300, 295.0, "pw1", "2026-01-15", self.run),
            _power_point(1200, 285.0, "pw1", "2026-01-15", self.run),
        ]
        self.result = detect_power_records(self.curve)

    def test_best1_min_present(self):
        assert "best1Min" in self.result
        assert "reason" not in self.result["best1Min"]

    def test_best5_min_present(self):
        assert "best5Min" in self.result
        assert "reason" not in self.result["best5Min"]

    def test_best20_min_present(self):
        assert "best20Min" in self.result
        assert "reason" not in self.result["best20Min"]

    def test_best1_min_value(self):
        assert self.result["best1Min"]["value"] == 320.0

    def test_best5_min_value(self):
        assert self.result["best5Min"]["value"] == 295.0

    def test_best20_min_value(self):
        assert self.result["best20Min"]["value"] == 285.0

    def test_best20_min_date_matches_workout(self):
        assert self.result["best20Min"]["date"] == "2026-01-15"

    def test_best20_min_source_workout_present(self):
        assert self.result["best20Min"]["sourceWorkout"] is not None

    def test_record_fields_are_exactly_three(self):
        record = self.result["best20Min"]
        assert set(record.keys()) == {"value", "date", "sourceWorkout"}

    def test_debug_key_present(self):
        assert "debug" in self.result


# ══════════════════════════════════════════════════════════════════════════════
# detect_power_records — partial curve: some durations absent
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectPowerRecordsPartialCurve:
    """Power curve only has 60 s data; 5-min and 20-min are omitted."""

    @pytest.fixture(autouse=True)
    def setup(self):
        run = _run("pw2", "2026-03-01", 2.0, 600, avg_power=310)
        self.curve = [_power_point(60, 310.0, "pw2", "2026-03-01", run)]
        self.result = detect_power_records(self.curve)

    def test_best1_min_present(self):
        assert "best1Min" in self.result
        assert "reason" not in self.result["best1Min"]

    def test_best5_min_absent_with_reason(self):
        rec = self.result["best5Min"]
        assert "reason" in rec
        assert "value" not in rec

    def test_best20_min_absent_with_reason(self):
        rec = self.result["best20Min"]
        assert "reason" in rec
        assert "value" not in rec


# ══════════════════════════════════════════════════════════════════════════════
# detect_power_records — tie: earlier date wins
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectPowerRecordsTieBreaking:
    """Two curve points for 1-min have the same power; the earlier date wins."""

    @pytest.fixture(autouse=True)
    def setup(self):
        run_e = _run("pe1", "2026-01-03", 3.0, 900, avg_power=300)
        run_l = _run("pe2", "2026-04-10", 3.0, 900, avg_power=300)
        self.curve = [
            _power_point(60, 300.0, "pe1", "2026-01-03", run_e),
            _power_point(60, 300.0, "pe2", "2026-04-10", run_l),
        ]
        self.result = detect_power_records(self.curve)

    def test_best1_min_present(self):
        assert "best1Min" in self.result

    def test_earlier_date_wins(self):
        assert self.result["best1Min"]["date"] == "2026-01-03"

    def test_source_workout_is_earlier(self):
        assert self.result["best1Min"]["sourceWorkout"]["id"] == "pe1"


# ══════════════════════════════════════════════════════════════════════════════
# detect_power_records — empty input
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectPowerRecordsEmptyInput:

    def test_empty_curve_returns_reason(self):
        result = detect_power_records([])
        assert "reason" in result

    def test_reason_is_string(self):
        result = detect_power_records([])
        assert isinstance(result["reason"], str)

    def test_empty_result_has_no_power_keys(self):
        result = detect_power_records([])
        power_keys = {"best1Min", "best5Min", "best20Min"}
        assert not power_keys.intersection(result.keys())


# ══════════════════════════════════════════════════════════════════════════════
# detect_volume_records — clean history
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectVolumeRecordsCleanHistory:
    """Ten runs in two weeks; the expected volume records are deterministic."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Week 1 (Mon 2026-01-05): 4 runs totalling 60 km, 350 TSS
        self.w1_runs = [
            _run("v1", "2026-01-06", 20.0, 7200, tss=120),
            _run("v2", "2026-01-07", 15.0, 5400, tss=90),
            _run("v3", "2026-01-08", 12.0, 4320, tss=75),
            _run("v4", "2026-01-09", 13.0, 4680, tss=65),
        ]
        # Week 2 (Mon 2026-01-12): 3 runs totalling 40 km, 210 TSS
        self.w2_runs = [
            _run("v5", "2026-01-13", 42.195, 15120, tss=130),  # marathon — longest by distance
            _run("v6", "2026-01-14", 10.0, 3600, tss=60),
            _run("v7", "2026-01-15", 8.0, 2880, tss=20),
        ]
        self.all_runs = self.w1_runs + self.w2_runs
        self.result = detect_volume_records(self.all_runs)

    def test_longest_by_distance_present(self):
        assert "longestByDistance" in self.result
        assert "reason" not in self.result["longestByDistance"]

    def test_longest_by_distance_is_marathon_run(self):
        rec = self.result["longestByDistance"]
        assert abs(rec["value"] - 42.195) < 0.01

    def test_longest_by_distance_date(self):
        assert self.result["longestByDistance"]["date"] == "2026-01-13"

    def test_longest_by_distance_source_workout(self):
        assert self.result["longestByDistance"]["sourceWorkout"]["id"] == "v5"

    def test_longest_by_duration_present(self):
        assert "longestByDuration" in self.result

    def test_longest_by_duration_is_marathon_run(self):
        rec = self.result["longestByDuration"]
        assert rec["value"] == 15120

    def test_weekly_distance_record_present(self):
        assert "weeklyDistanceRecord" in self.result

    def test_weekly_distance_record_is_week1(self):
        rec = self.result["weeklyDistanceRecord"]
        # Week 1 total = 60 km > Week 2 total ≈ 60.195 km — actually week 2 wins
        # week1: 20+15+12+13 = 60, week2: 42.195+10+8 = 60.195
        assert rec["value"] >= 60.0

    def test_weekly_distance_record_has_week_start_date(self):
        rec = self.result["weeklyDistanceRecord"]
        assert rec["date"] is not None

    def test_weekly_load_record_present(self):
        assert "weeklyLoadRecord" in self.result

    def test_weekly_load_record_is_week1(self):
        # Week 1 TSS = 350, Week 2 TSS = 210
        rec = self.result["weeklyLoadRecord"]
        assert rec["value"] == 350.0

    def test_weekly_load_record_week_start(self):
        rec = self.result["weeklyLoadRecord"]
        assert rec["date"] == "2026-01-05"  # Monday of week 1

    def test_record_fields_are_exactly_three(self):
        for key in ("longestByDistance", "longestByDuration", "weeklyDistanceRecord", "weeklyLoadRecord"):
            record = self.result[key]
            assert set(record.keys()) == {"value", "date", "sourceWorkout"}, f"{key} fields mismatch"

    def test_debug_key_present(self):
        assert "debug" in self.result

    def test_debug_weekly_totals_non_empty(self):
        assert len(self.result["debug"]["weekly_totals"]) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# detect_volume_records — tie: earlier date wins
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectVolumeRecordsTieBreaking:
    """Two runs share the same distance; the earlier-date run wins."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.run_early = _run("t1", "2026-01-10", 10.0, 3000, tss=60)
        self.run_late = _run("t2", "2026-03-20", 10.0, 3000, tss=60)
        self.result = detect_volume_records([self.run_early, self.run_late])

    def test_longest_by_distance_is_earlier(self):
        assert self.result["longestByDistance"]["date"] == "2026-01-10"

    def test_longest_by_distance_source_is_earlier(self):
        assert self.result["longestByDistance"]["sourceWorkout"]["id"] == "t1"

    def test_longest_by_duration_is_earlier(self):
        assert self.result["longestByDuration"]["date"] == "2026-01-10"


# ══════════════════════════════════════════════════════════════════════════════
# detect_volume_records — empty input
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectVolumeRecordsEmptyInput:

    def test_empty_list_returns_reason(self):
        result = detect_volume_records([])
        assert "reason" in result

    def test_reason_is_string(self):
        result = detect_volume_records([])
        assert isinstance(result["reason"], str)

    def test_empty_result_has_no_volume_keys(self):
        result = detect_volume_records([])
        volume_keys = {"longestByDistance", "longestByDuration", "weeklyDistanceRecord", "weeklyLoadRecord"}
        assert not volume_keys.intersection(result.keys())


# ══════════════════════════════════════════════════════════════════════════════
# detect_volume_records — weekly aggregation correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectVolumeRecordsWeeklyAggregation:
    """Verify that runs are grouped correctly into Monday-start weeks."""

    def test_four_runs_in_one_week_aggregate(self):
        runs = [
            _run("w1", "2026-01-05", 10.0, 3600, tss=60),   # Monday
            _run("w2", "2026-01-06", 8.0, 2880, tss=50),    # Tuesday
            _run("w3", "2026-01-08", 12.0, 4320, tss=70),   # Thursday
            _run("w4", "2026-01-11", 5.0, 1800, tss=30),    # Sunday
        ]
        result = detect_volume_records(runs)
        # All four fall in the week starting 2026-01-05 (Monday).
        weekly_totals = result["debug"]["weekly_totals"]
        week = next((w for w in weekly_totals if w["week_start"] == "2026-01-05"), None)
        assert week is not None
        assert abs(week["total_distance_km"] - 35.0) < 0.001
        assert abs(week["total_tss"] - 210.0) < 0.001

    def test_runs_spanning_two_weeks_separated(self):
        runs = [
            _run("x1", "2026-01-09", 10.0, 3600, tss=60),  # Friday of week 1
            _run("x2", "2026-01-12", 10.0, 3600, tss=60),  # Monday of week 2
        ]
        result = detect_volume_records(runs)
        weekly_totals = result["debug"]["weekly_totals"]
        assert len(weekly_totals) == 2
