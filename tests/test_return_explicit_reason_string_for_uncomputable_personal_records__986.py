"""Tests for issue #986: explicit reason strings for uncomputable personal records.

Acceptance Criteria covered:
  AC1: For any record category that cannot be computed, the API response includes
       an explicit reason string identifying why, rather than a blank or missing entry.
  AC2: The reason string is specific to the missing data type (e.g. distinguishes
       missing power data from missing GPS data).
  AC3: Record categories that can be computed are unaffected — they still return
       value, date, and source workout ID.
  AC4: No logic changes are made inside backend/services/pr_detection.py.
  AC5: Existing unit tests for pr_detection.py continue to pass.
"""

import pytest
import unittest.mock as mock
import uuid


# ── Helper: build typical fetch_and_detect_records outputs ───────────────────

def _make_computed_record(value=300.0, date="2026-01-15", source_id="run-1"):
    return {
        "value": value,
        "date": date,
        "sourceWorkout": {"id": source_id, "workout_date": date},
    }


def _speed_with_top_level_reason(reason="no completed runs provided"):
    return {"reason": reason}


def _power_with_top_level_reason(reason="duration curve is empty"):
    return {"reason": reason}


def _volume_with_top_level_reason(reason="no completed runs provided"):
    return {"reason": reason}


def _raw(speed, power, volume):
    return {
        "speedRecords": speed,
        "powerRecords": power,
        "volumeRecords": volume,
    }


# ── Import the helper ─────────────────────────────────────────────────────────

def _get_helper():
    from backend.main import _enrich_run_pr_reasons
    return _enrich_run_pr_reasons


class TestEnrichHelperIsImportable:
    """AC1: The enrichment helper must be importable from backend.main."""

    def test_importable(self):
        fn = _get_helper()
        assert callable(fn)


# ══════════════════════════════════════════════════════════════════════════════
# AC1: powerRecords top-level reason → per-slot reasons populated
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichPowerRecordsTopLevelReason:
    """When powerRecords is a top-level reason dict, duration slots get explicit reasons."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.enrich = _get_helper()
        self.raw = _raw(
            speed=_speed_with_top_level_reason(),
            power=_power_with_top_level_reason(),
            volume=_volume_with_top_level_reason(),
        )
        self.enrich(self.raw)

    def test_best1min_slot_present(self):
        """AC1: best1Min must be present in powerRecords after enrichment."""
        assert "best1Min" in self.raw["powerRecords"]

    def test_best5min_slot_present(self):
        """AC1: best5Min must be present in powerRecords after enrichment."""
        assert "best5Min" in self.raw["powerRecords"]

    def test_best20min_slot_present(self):
        """AC1: best20Min must be present in powerRecords after enrichment."""
        assert "best20Min" in self.raw["powerRecords"]

    def test_best1min_has_reason_not_value(self):
        """AC1: populated power slot must have reason and not value."""
        slot = self.raw["powerRecords"]["best1Min"]
        assert "reason" in slot
        assert "value" not in slot

    def test_best5min_has_reason_not_value(self):
        slot = self.raw["powerRecords"]["best5Min"]
        assert "reason" in slot
        assert "value" not in slot

    def test_best20min_has_reason_not_value(self):
        slot = self.raw["powerRecords"]["best20Min"]
        assert "reason" in slot
        assert "value" not in slot

    def test_power_reason_is_non_empty_string(self):
        reason = self.raw["powerRecords"]["best1Min"]["reason"]
        assert isinstance(reason, str) and len(reason) > 0


# ══════════════════════════════════════════════════════════════════════════════
# AC1: speedRecords top-level reason → per-slot reasons populated
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichSpeedRecordsTopLevelReason:
    """When speedRecords is a top-level reason dict, distance slots get explicit reasons."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.enrich = _get_helper()
        self.raw = _raw(
            speed=_speed_with_top_level_reason(),
            power={"best1Min": _make_computed_record(value=310.0)},
            volume={"longestByDistance": _make_computed_record(value=10.0)},
        )
        self.enrich(self.raw)

    def test_1km_slot_present(self):
        assert "1km" in self.raw["speedRecords"]

    def test_5km_slot_present(self):
        assert "5km" in self.raw["speedRecords"]

    def test_marathon_slot_present(self):
        assert "marathon" in self.raw["speedRecords"]

    def test_half_marathon_slot_present(self):
        assert "half_marathon" in self.raw["speedRecords"]

    def test_1mile_slot_present(self):
        assert "1mile" in self.raw["speedRecords"]

    def test_10km_slot_present(self):
        assert "10km" in self.raw["speedRecords"]

    def test_1km_has_reason_not_value(self):
        slot = self.raw["speedRecords"]["1km"]
        assert "reason" in slot
        assert "value" not in slot

    def test_speed_reason_is_non_empty_string(self):
        reason = self.raw["speedRecords"]["1km"]["reason"]
        assert isinstance(reason, str) and len(reason) > 0


# ══════════════════════════════════════════════════════════════════════════════
# AC1: volumeRecords missing sub-categories → explicit reasons added
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichVolumeRecordsMissingSubCategories:
    """Absent volume sub-categories get explicit per-slot reason strings."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.enrich = _get_helper()
        # Runs exist (so volumeRecords is not a top-level reason), but only
        # duration data is present — no distance or TSS data.
        self.raw = _raw(
            speed={"5km": _make_computed_record()},
            power={"reason": "duration curve is empty"},
            volume={
                "longestByDuration": _make_computed_record(value=3600.0),
                "debug": {},
                # longestByDistance, weeklyDistanceRecord, weeklyLoadRecord are absent
            },
        )
        self.enrich(self.raw)

    def test_longest_by_distance_added(self):
        """AC1: longestByDistance absent from volume output must be populated with reason."""
        assert "longestByDistance" in self.raw["volumeRecords"]

    def test_weekly_distance_record_added(self):
        """AC1: weeklyDistanceRecord absent from volume output must be populated with reason."""
        assert "weeklyDistanceRecord" in self.raw["volumeRecords"]

    def test_weekly_load_record_added(self):
        """AC1: weeklyLoadRecord absent from volume output must be populated with reason."""
        assert "weeklyLoadRecord" in self.raw["volumeRecords"]

    def test_longest_by_distance_has_reason(self):
        slot = self.raw["volumeRecords"]["longestByDistance"]
        assert "reason" in slot
        assert "value" not in slot

    def test_weekly_distance_record_has_reason(self):
        slot = self.raw["volumeRecords"]["weeklyDistanceRecord"]
        assert "reason" in slot
        assert "value" not in slot

    def test_weekly_load_record_has_reason(self):
        slot = self.raw["volumeRecords"]["weeklyLoadRecord"]
        assert "reason" in slot
        assert "value" not in slot

    def test_longest_by_duration_untouched(self):
        """AC3: longestByDuration was computed and must be unchanged."""
        slot = self.raw["volumeRecords"]["longestByDuration"]
        assert "value" in slot
        assert slot["value"] == 3600.0


class TestEnrichVolumeRecordsTopLevelReason:
    """When volumeRecords itself is a top-level reason dict, all four slots get explicit reasons."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.enrich = _get_helper()
        self.raw = _raw(
            speed=_speed_with_top_level_reason(),
            power=_power_with_top_level_reason(),
            volume=_volume_with_top_level_reason(),
        )
        self.enrich(self.raw)

    def test_longest_by_distance_slot_present(self):
        assert "longestByDistance" in self.raw["volumeRecords"]

    def test_longest_by_duration_slot_present(self):
        assert "longestByDuration" in self.raw["volumeRecords"]

    def test_weekly_distance_record_slot_present(self):
        assert "weeklyDistanceRecord" in self.raw["volumeRecords"]

    def test_weekly_load_record_slot_present(self):
        assert "weeklyLoadRecord" in self.raw["volumeRecords"]

    def test_all_volume_slots_have_reason(self):
        for key in ("longestByDistance", "longestByDuration", "weeklyDistanceRecord", "weeklyLoadRecord"):
            slot = self.raw["volumeRecords"][key]
            assert "reason" in slot, f"{key} must have a reason string"
            assert "value" not in slot, f"{key} must not have a value"


# ══════════════════════════════════════════════════════════════════════════════
# AC2: reason strings are specific to the missing data type
# ══════════════════════════════════════════════════════════════════════════════

class TestReasonStringSpecificity:
    """AC2: reason strings must distinguish power data from GPS data from TSS data."""

    def _enrich_all_empty(self):
        enrich = _get_helper()
        raw = _raw(
            speed=_speed_with_top_level_reason(),
            power=_power_with_top_level_reason(),
            volume={
                "longestByDuration": _make_computed_record(value=3600.0),
                "debug": {},
            },
        )
        enrich(raw)
        return raw

    def _enrich_missing_distance_and_tss(self):
        enrich = _get_helper()
        raw = _raw(
            speed={"5km": _make_computed_record()},
            power={"reason": "duration curve is empty"},
            volume={
                "longestByDuration": _make_computed_record(value=3600.0),
                "debug": {},
            },
        )
        enrich(raw)
        return raw

    def test_power_reason_mentions_power(self):
        """AC2: power slot reason must mention power (not GPS or TSS)."""
        raw = self._enrich_all_empty()
        reason = raw["powerRecords"]["best1Min"]["reason"]
        assert "power" in reason.lower(), f"Expected 'power' in reason, got: {reason!r}"

    def test_speed_reason_distinct_from_power_reason(self):
        """AC2: speed slot reason must differ from power slot reason."""
        raw = self._enrich_all_empty()
        power_reason = raw["powerRecords"]["best1Min"]["reason"]
        speed_reason = raw["speedRecords"]["1km"]["reason"]
        assert power_reason != speed_reason, (
            f"Power and speed reasons must differ; both were: {power_reason!r}"
        )

    def test_longest_by_distance_reason_mentions_distance_or_gps(self):
        """AC2: longestByDistance reason must mention distance or GPS, not TSS."""
        raw = self._enrich_missing_distance_and_tss()
        reason = raw["volumeRecords"]["longestByDistance"]["reason"]
        assert any(kw in reason.lower() for kw in ("distance", "gps")), (
            f"Expected 'distance' or 'gps' in reason, got: {reason!r}"
        )

    def test_weekly_load_record_reason_mentions_tss_or_load(self):
        """AC2: weeklyLoadRecord reason must mention TSS or load, not GPS."""
        raw = self._enrich_missing_distance_and_tss()
        reason = raw["volumeRecords"]["weeklyLoadRecord"]["reason"]
        assert any(kw in reason.lower() for kw in ("tss", "load", "training")), (
            f"Expected 'tss', 'load', or 'training' in reason, got: {reason!r}"
        )

    def test_distance_and_load_reasons_are_distinct(self):
        """AC2: longestByDistance and weeklyLoadRecord must have different reasons."""
        raw = self._enrich_missing_distance_and_tss()
        dist_reason = raw["volumeRecords"]["longestByDistance"]["reason"]
        load_reason = raw["volumeRecords"]["weeklyLoadRecord"]["reason"]
        assert dist_reason != load_reason, (
            f"Distance and load reasons must differ; both were: {dist_reason!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# AC3: computed categories are unaffected
# ══════════════════════════════════════════════════════════════════════════════

class TestComputedCategoriesUnaffected:
    """AC3: records with value/date/sourceWorkout are not modified by enrichment."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.enrich = _get_helper()
        self.five_km = _make_computed_record(value=1200.0, date="2026-03-01", source_id="run-5")
        self.best1min = _make_computed_record(value=310.0, date="2026-02-15", source_id="run-3")
        self.longest = _make_computed_record(value=42.195, date="2026-01-10", source_id="run-m")
        self.raw = _raw(
            speed={"5km": dict(self.five_km), "debug": {}},
            power={"best1Min": dict(self.best1min), "debug": {}},
            volume={
                "longestByDistance": dict(self.longest),
                "longestByDuration": _make_computed_record(value=14400.0),
                "weeklyDistanceRecord": _make_computed_record(value=60.0),
                "weeklyLoadRecord": _make_computed_record(value=350.0),
                "debug": {},
            },
        )
        self.enrich(self.raw)

    def test_5km_value_unchanged(self):
        assert self.raw["speedRecords"]["5km"]["value"] == 1200.0

    def test_5km_date_unchanged(self):
        assert self.raw["speedRecords"]["5km"]["date"] == "2026-03-01"

    def test_5km_source_workout_unchanged(self):
        assert self.raw["speedRecords"]["5km"]["sourceWorkout"]["id"] == "run-5"

    def test_best1min_value_unchanged(self):
        assert self.raw["powerRecords"]["best1Min"]["value"] == 310.0

    def test_best1min_date_unchanged(self):
        assert self.raw["powerRecords"]["best1Min"]["date"] == "2026-02-15"

    def test_longest_by_distance_value_unchanged(self):
        assert abs(self.raw["volumeRecords"]["longestByDistance"]["value"] - 42.195) < 0.001

    def test_longest_by_distance_date_unchanged(self):
        assert self.raw["volumeRecords"]["longestByDistance"]["date"] == "2026-01-10"

    def test_weekly_distance_record_untouched(self):
        rec = self.raw["volumeRecords"]["weeklyDistanceRecord"]
        assert "value" in rec and "reason" not in rec

    def test_weekly_load_record_untouched(self):
        rec = self.raw["volumeRecords"]["weeklyLoadRecord"]
        assert "value" in rec and "reason" not in rec


# ══════════════════════════════════════════════════════════════════════════════
# AC3: partial speed/power records with some computed slots are unaffected
# ══════════════════════════════════════════════════════════════════════════════

class TestPartialSpeedRecordsComputedSlotUnaffected:
    """AC3: when speedRecords has some computed slots and some reason slots, only missing ones change."""

    def test_computed_5km_not_touched_when_marathon_has_reason(self):
        enrich = _get_helper()
        five_km = _make_computed_record(value=1300.0)
        raw = _raw(
            speed={
                "5km": dict(five_km),
                "10km": dict(_make_computed_record(value=2650.0)),
                "marathon": {"reason": "curve has no data for distances at or above 42.1950 km"},
                "half_marathon": {"reason": "curve has no data for distances at or above 21.0975 km"},
                "debug": {},
            },
            power={"best1Min": _make_computed_record(value=320.0)},
            volume={"longestByDistance": _make_computed_record(value=10.0)},
        )
        enrich(raw)
        # Computed slots untouched
        assert raw["speedRecords"]["5km"]["value"] == 1300.0
        assert "reason" not in raw["speedRecords"]["5km"]
        # Reason slots still have a reason (not converted to a record)
        assert "reason" in raw["speedRecords"]["marathon"]
        assert "value" not in raw["speedRecords"]["marathon"]


# ══════════════════════════════════════════════════════════════════════════════
# AC4: pr_detection.py unchanged — smoke tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPrDetectionModuleUnchanged:
    """AC4/AC5: pr_detection.py pure functions are not modified."""

    def test_detect_speed_records_returns_reason_for_empty_input(self):
        from backend.services.pr_detection import detect_speed_records
        result = detect_speed_records([], [])
        assert "reason" in result

    def test_detect_power_records_returns_reason_for_empty_input(self):
        from backend.services.pr_detection import detect_power_records
        result = detect_power_records([])
        assert "reason" in result

    def test_detect_volume_records_returns_reason_for_empty_input(self):
        from backend.services.pr_detection import detect_volume_records
        result = detect_volume_records([])
        assert "reason" in result

    def test_detect_power_records_empty_reason_unchanged(self):
        """The raw reason string from pr_detection is 'duration curve is empty' unchanged."""
        from backend.services.pr_detection import detect_power_records
        result = detect_power_records([])
        assert result["reason"] == "duration curve is empty"

    def test_detect_volume_records_no_distance_key_when_no_runs(self):
        """pr_detection omits longestByDistance when no runs have distance data."""
        from backend.services.pr_detection import detect_volume_records
        # Run with no distance_km
        result = detect_volume_records([{"id": "r1", "workout_date": "2026-01-01", "distance_km": None, "duration_seconds": 3600, "tss": None}])
        assert "longestByDistance" not in result

    def test_detect_volume_records_no_tss_key_when_no_tss(self):
        """pr_detection omits weeklyLoadRecord when no runs have TSS data."""
        from backend.services.pr_detection import detect_volume_records
        result = detect_volume_records([{"id": "r1", "workout_date": "2026-01-01", "distance_km": 10.0, "duration_seconds": 3600, "tss": None}])
        # weeklyLoadRecord may be present with 0.0 since 0.0 is falsy but sum is 0
        # — or absent. Either way the enricher must handle it.
        # This test just confirms pr_detection.py hasn't changed to always populate it.
        if "weeklyLoadRecord" in result:
            assert result["weeklyLoadRecord"]["value"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Endpoint integration: enrich is called in get_athlete_run_personal_records
# ══════════════════════════════════════════════════════════════════════════════

class TestEndpointCallsEnrichment:
    """Verify the enrichment is applied inside get_athlete_run_personal_records."""

    def _call_endpoint_with_empty_data(self, caplog):
        import backend.main as main_mod

        fake_raw = {
            "speedRecords": {"reason": "no completed runs provided"},
            "powerRecords": {"reason": "duration curve is empty"},
            "volumeRecords": {"reason": "no completed runs provided"},
            "_meta": {"duration_curve_populated": False, "runs_considered": 0},
        }

        mock_user = mock.MagicMock()
        mock_user.id = uuid.uuid4()

        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
        mock_session.__exit__ = mock.MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.count.return_value = 0
        mock_session.get.return_value = None

        with mock.patch("backend.main.Session", return_value=mock_session), \
             mock.patch(
                 "backend.services.pr_detection.fetch_and_detect_records",
                 return_value=dict(fake_raw),
             ):
            # athlete_id is a required path param (/api/athletes/{athlete_id}/...);
            # the endpoint 404s unless it matches user.id (#1606).
            response = main_mod.get_athlete_run_personal_records(
                athlete_id=str(mock_user.id), user=mock_user
            )

        import json
        return json.loads(response.body)

    def test_endpoint_power_slots_populated_when_no_power_data(self, caplog):
        """AC1: endpoint response has best1Min in powerRecords when power curve is empty."""
        body = self._call_endpoint_with_empty_data(caplog)
        assert "best1Min" in body["powerRecords"], (
            f"best1Min must be present; powerRecords was: {body['powerRecords']}"
        )

    def test_endpoint_speed_slots_populated_when_no_runs(self, caplog):
        """AC1: endpoint response has 1km in speedRecords when no runs exist."""
        body = self._call_endpoint_with_empty_data(caplog)
        assert "1km" in body["speedRecords"], (
            f"1km must be present; speedRecords was: {body['speedRecords']}"
        )

    def test_endpoint_volume_slots_populated_when_no_runs(self, caplog):
        """AC1: endpoint response has longestByDistance in volumeRecords when no runs exist."""
        body = self._call_endpoint_with_empty_data(caplog)
        assert "longestByDistance" in body["volumeRecords"]

    def test_endpoint_power_slot_has_reason_not_value(self, caplog):
        """AC1: endpoint power slot has reason, not value."""
        body = self._call_endpoint_with_empty_data(caplog)
        slot = body["powerRecords"]["best1Min"]
        assert "reason" in slot
        assert "value" not in slot

    def test_endpoint_power_reason_mentions_power(self, caplog):
        """AC2: endpoint power reason mentions power, not GPS."""
        body = self._call_endpoint_with_empty_data(caplog)
        reason = body["powerRecords"]["best1Min"]["reason"]
        assert "power" in reason.lower(), f"Got: {reason!r}"

    def test_endpoint_meta_not_present(self, caplog):
        """_meta must be stripped before the response is returned."""
        body = self._call_endpoint_with_empty_data(caplog)
        assert "_meta" not in body
