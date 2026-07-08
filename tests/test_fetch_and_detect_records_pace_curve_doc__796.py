"""
Tests for issue #796: fetch_and_detect_records pace curve documentation.

AC coverage:
- AC2/AC4 (doc-comment path): the function's source documents the overall-average
  simplification by name, describes the sub-distance accuracy trade-off, and
  references AthleteDurationCurve as the future improvement path.
- AC5: detect_speed_records behaviour for full-distance workouts is not regressed.

All tests in this file are unit tests — no database required.
"""
import inspect
import pytest
from backend.services.pr_detection import fetch_and_detect_records, detect_speed_records


# ── Source-text fixtures ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def fn_source():
    return inspect.getsource(fetch_and_detect_records)


# ══════════════════════════════════════════════════════════════════════════════
# AC2 / AC4 — doc-comment requirements
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchAndDetectRecordsPaceCurveComment:
    """Verify that the function source documents the overall-average simplification."""

    def test_names_overall_average_pace_limitation(self, fn_source):
        """AC4: comment must identify the limitation as 'overall average pace'."""
        assert "overall average pace" in fn_source, (
            "fetch_and_detect_records must contain a comment naming the limitation "
            "'overall average pace per workout'"
        )

    def test_mentions_sub_distance_accuracy_tradeoff(self, fn_source):
        """AC4: comment must state what is lost — sub-distance split accuracy."""
        lower = fn_source.lower()
        assert "sub-distance" in lower or "sub distance" in lower, (
            "fetch_and_detect_records must describe the accuracy trade-off for "
            "sub-distance splits"
        )

    def test_references_athlete_duration_curve(self, fn_source):
        """AC4: comment must reference AthleteDurationCurve as the future path."""
        assert "AthleteDurationCurve" in fn_source, (
            "fetch_and_detect_records must reference AthleteDurationCurve as the "
            "data source that would resolve the sub-distance accuracy limitation"
        )


# ══════════════════════════════════════════════════════════════════════════════
# AC5 — no regression for full-distance results
# ══════════════════════════════════════════════════════════════════════════════

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


class TestFullDistanceResultNotRegressed:
    """AC5: for a workout where detected distance equals the full run distance,
    the result from detect_speed_records is unchanged after any refactor."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # 10 km run at 300 sec/km (exactly 10 km distance — full distance match)
        self.run = _run("fd1", "2026-03-15", 10.0, 3000)
        pace = 3000 / 10.0  # 300 sec/km
        self.curve = [_pace_point(3000, pace, "fd1", "2026-03-15", self.run)]
        self.result = detect_speed_records(self.curve, [self.run])

    def test_10km_record_present(self):
        assert "10km" in self.result
        assert "reason" not in self.result["10km"]

    def test_10km_value_converges_to_full_duration(self):
        # At exactly 10 km the estimated time must equal the full run duration.
        val = self.result["10km"]["value"]
        assert abs(val - 3000.0) < 1.0, (
            f"For a full-distance 10 km run, estimated 10 km time should equal "
            f"duration 3000s but got {val}"
        )

    def test_10km_source_workout_id(self):
        assert self.result["10km"]["sourceWorkout"]["id"] == "fd1"

    def test_10km_date(self):
        assert self.result["10km"]["date"] == "2026-03-15"

    def test_5km_also_derivable_from_full_run(self):
        """5 km can be estimated from the 10 km point (overall pace reaches 5 km)."""
        assert "5km" in self.result
        assert "reason" not in self.result["5km"]

    def test_marathon_omitted_when_no_long_run(self):
        """Marathon cannot be estimated from a 10 km run."""
        rec = self.result["marathon"]
        assert "reason" in rec
        assert "value" not in rec


class TestFullDistanceMarathon:
    """AC5: marathon detection converges when the run IS a marathon."""

    def test_marathon_value_equals_duration_when_run_is_marathon(self):
        run = _run("mar1", "2026-04-20", 42.195, 12600)
        pace = 12600 / 42.195
        curve = [_pace_point(12600, pace, "mar1", "2026-04-20", run)]
        result = detect_speed_records(curve, [run])
        assert "marathon" in result
        assert "reason" not in result["marathon"]
        val = result["marathon"]["value"]
        assert abs(val - 12600.0) < 1.0, (
            f"For a full marathon run, estimated marathon time should equal "
            f"duration 12600s but got {val}"
        )
