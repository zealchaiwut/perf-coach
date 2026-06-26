"""Tests for issue #987: unit tests for PR endpoint caller — logging and empty-curve branch.

Acceptance Criteria covered:
  AC1: At least three new tests covering (1) populated-curve logging,
       (2) empty-curve logging and explicit reason output,
       (3) raw detector output logging.
  AC2: All new tests pass; existing tests for pr_detection.py continue to pass.
  AC3: Tests mock pr_detection.py at the caller boundary; no changes to
       backend/services/pr_detection.py.
  AC4: No hardcoded numeric thresholds or distance values; fixtures use
       STANDARD_DISTANCES_KM and STANDARD_POWER_DURATIONS_SECONDS from the codebase.
"""

import json
import logging
import unittest.mock as mock

import pytest

from backend.services.pr_detection import (
    STANDARD_DISTANCES_KM,
    STANDARD_POWER_DURATIONS_SECONDS,
)


# ── Shared fixtures ─────────────────────────────────────────────────────────


def _make_populated_raw(run_count=5):
    """Build a minimal fetch_and_detect_records result for a populated curve.

    Speed record keys are taken from STANDARD_DISTANCES_KM; power record keys
    from STANDARD_POWER_DURATIONS_SECONDS — no numeric distance or threshold
    values are hardcoded (AC4).
    """
    speed_label = next(iter(STANDARD_DISTANCES_KM))
    power_label = next(iter(STANDARD_POWER_DURATIONS_SECONDS))

    return {
        "speedRecords": {
            speed_label: {"value": 1200.0, "date": "2026-01-15", "sourceWorkout": {"id": "r1"}},
            "debug": {},
        },
        "powerRecords": {
            power_label: {"value": 280.0, "date": "2026-01-15", "sourceWorkout": {"id": "r1"}},
            "debug": {},
        },
        "volumeRecords": {
            "longestByDistance": {"value": 10.0, "date": "2026-01-15", "sourceWorkout": {"id": "r1"}},
            "debug": {},
        },
        "_meta": {
            "duration_curve_populated": True,
            "runs_considered": run_count,
        },
    }


def _make_empty_curve_raw():
    """Build a minimal fetch_and_detect_records result for an empty curve.

    Every record category carries an explicit reason string — this is the shape
    the real pr_detection functions return when no curve data is available.
    """
    return {
        "speedRecords": {"reason": "duration curve is empty"},
        "powerRecords": {"reason": "duration curve is empty"},
        "volumeRecords": {"reason": "no completed runs provided"},
        "_meta": {
            "duration_curve_populated": False,
            "runs_considered": 0,
        },
    }


def _call_endpoint(caplog, fake_raw, run_count=5, curve_exists=True):
    """Invoke get_athlete_run_personal_records with all external deps mocked.

    Patches:
    - backend.main.Session           — prevents real DB access
    - backend.services.pr_detection.fetch_and_detect_records
                                     — returns fake_raw instead of hitting DB (AC3)

    Returns (info_records, response) where info_records is the filtered list of
    INFO-level log records from backend.main and response is the JSONResponse.
    """
    import backend.main as main_mod

    mock_user = mock.MagicMock()
    mock_user.id = 1

    mock_session = mock.MagicMock()
    mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
    mock_session.__exit__ = mock.MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.count.return_value = run_count
    mock_session.get.return_value = mock.MagicMock() if curve_exists else None

    with (
        caplog.at_level(logging.INFO, logger="backend.main"),
        mock.patch("backend.main.Session", return_value=mock_session),
        mock.patch(
            "backend.services.pr_detection.fetch_and_detect_records",
            return_value=dict(fake_raw),
        ),
    ):
        response = main_mod.get_athlete_run_personal_records(user=mock_user)

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    return info_records, response


# ══════════════════════════════════════════════════════════════════════════════
# Test group 1: Populated duration curve — pre-detection log entries
# AC1(1): The INFO log records the correct run count and non-empty curve status.
# ══════════════════════════════════════════════════════════════════════════════


class TestPopulatedCurveLogging:
    """When the duration curve is populated, the pre-detection INFO log must
    report duration_curve_populated=True and the exact run count from the DB."""

    def test_pre_detection_log_curve_populated_true(self, caplog):
        """AC1(1): duration_curve_populated must be True for a populated curve."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), run_count=5, curve_exists=True)
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record; none found"
        assert pre[0].duration_curve_populated is True

    def test_pre_detection_log_run_count_matches_db(self, caplog):
        """AC1(1): runs_considered must match the DB count passed to the mock."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(run_count=9), run_count=9, curve_exists=True)
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record; none found"
        assert pre[0].runs_considered == 9

    def test_pre_detection_log_runs_considered_is_int(self, caplog):
        """AC1(1): runs_considered must be stored as an int, not a string or float."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), run_count=3, curve_exists=True)
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre
        assert isinstance(pre[0].runs_considered, int)

    def test_populated_response_strips_meta(self, caplog):
        """AC1(1): The _meta key must be absent from the JSON response body."""
        _, response = _call_endpoint(caplog, _make_populated_raw(), curve_exists=True)
        body = json.loads(response.body)
        assert "_meta" not in body


# ══════════════════════════════════════════════════════════════════════════════
# Test group 2: Empty duration curve — log entry and explicit reason output
# AC1(2): The INFO log records the curve as empty AND the response carries an
#         explicit reason string for every record category.
# ══════════════════════════════════════════════════════════════════════════════


class TestEmptyCurveLoggingAndExplicitReason:
    """When the duration curve is empty, the endpoint must:
    (a) log duration_curve_populated=False in the pre-detection entry, and
    (b) return an explicit non-empty reason string for each record category."""

    def test_pre_detection_log_curve_populated_false(self, caplog):
        """AC1(2): duration_curve_populated must be False when no curve exists."""
        info_records, _ = _call_endpoint(
            caplog, _make_empty_curve_raw(), run_count=0, curve_exists=False
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record; none found"
        assert pre[0].duration_curve_populated is False

    def test_pre_detection_log_run_count_zero_when_empty(self, caplog):
        """AC1(2): runs_considered must be 0 when the DB reports no run workouts."""
        info_records, _ = _call_endpoint(
            caplog, _make_empty_curve_raw(), run_count=0, curve_exists=False
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre
        assert pre[0].runs_considered == 0

    def test_empty_curve_speed_records_has_explicit_reason(self, caplog):
        """AC1(2): speedRecords must carry an explicit reason key, not be absent."""
        _, response = _call_endpoint(
            caplog, _make_empty_curve_raw(), run_count=0, curve_exists=False
        )
        body = json.loads(response.body)
        assert "speedRecords" in body, "speedRecords must be present in the response"
        speed = body["speedRecords"]
        assert "reason" in speed, "speedRecords must include a 'reason' key when curve is empty"
        assert isinstance(speed["reason"], str) and speed["reason"]

    def test_empty_curve_power_records_has_explicit_reason(self, caplog):
        """AC1(2): powerRecords must carry an explicit reason key, not be absent."""
        _, response = _call_endpoint(
            caplog, _make_empty_curve_raw(), run_count=0, curve_exists=False
        )
        body = json.loads(response.body)
        assert "powerRecords" in body, "powerRecords must be present in the response"
        power = body["powerRecords"]
        assert "reason" in power, "powerRecords must include a 'reason' key when curve is empty"
        assert isinstance(power["reason"], str) and power["reason"]

    def test_empty_curve_volume_records_has_explicit_reason(self, caplog):
        """AC1(2): volumeRecords must carry an explicit reason key, not be absent."""
        _, response = _call_endpoint(
            caplog, _make_empty_curve_raw(), run_count=0, curve_exists=False
        )
        body = json.loads(response.body)
        assert "volumeRecords" in body, "volumeRecords must be present in the response"
        volume = body["volumeRecords"]
        assert "reason" in volume, "volumeRecords must include a 'reason' key when curve is empty"
        assert isinstance(volume["reason"], str) and volume["reason"]

    def test_empty_curve_response_strips_meta(self, caplog):
        """AC1(2): The _meta key must not appear in the response for an empty curve."""
        _, response = _call_endpoint(
            caplog, _make_empty_curve_raw(), run_count=0, curve_exists=False
        )
        body = json.loads(response.body)
        assert "_meta" not in body


# ══════════════════════════════════════════════════════════════════════════════
# Test group 3: Raw detector output — post-detection log captures known output
# AC1(3): The caller's INFO log captures the raw output from pr_detection.
# ══════════════════════════════════════════════════════════════════════════════


class TestRawDetectorOutputLogging:
    """When pr_detection returns a known structured dict, the post-detection INFO
    log must capture it intact — including all category keys — with _meta stripped."""

    def test_post_detection_log_event_present(self, caplog):
        """AC1(3): A pr_detection_output log record must be emitted."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), curve_exists=True)
        post = [r for r in info_records if getattr(r, "event", "") == "pr_detection_output"]
        assert post, "Expected a pr_detection_output log record; none found"

    def test_post_detection_log_has_raw_output_field(self, caplog):
        """AC1(3): The post-detection log record must have a raw_output attribute."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), curve_exists=True)
        post = [r for r in info_records if getattr(r, "event", "") == "pr_detection_output"]
        assert post
        assert hasattr(post[0], "raw_output"), "Post-detection log must include 'raw_output'"

    def test_post_detection_raw_output_has_speed_records(self, caplog):
        """AC1(3): raw_output must carry the speedRecords key from pr_detection."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), curve_exists=True)
        post = [r for r in info_records if getattr(r, "event", "") == "pr_detection_output"]
        assert post
        assert "speedRecords" in post[0].raw_output

    def test_post_detection_raw_output_has_power_records(self, caplog):
        """AC1(3): raw_output must carry the powerRecords key."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), curve_exists=True)
        post = [r for r in info_records if getattr(r, "event", "") == "pr_detection_output"]
        assert post
        assert "powerRecords" in post[0].raw_output

    def test_post_detection_raw_output_has_volume_records(self, caplog):
        """AC1(3): raw_output must carry the volumeRecords key."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), curve_exists=True)
        post = [r for r in info_records if getattr(r, "event", "") == "pr_detection_output"]
        assert post
        assert "volumeRecords" in post[0].raw_output

    def test_post_detection_raw_output_meta_stripped(self, caplog):
        """AC1(3): _meta must be absent from raw_output — it is an internal field."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), curve_exists=True)
        post = [r for r in info_records if getattr(r, "event", "") == "pr_detection_output"]
        assert post
        assert "_meta" not in post[0].raw_output, (
            "_meta is stripped before logging; it must not appear in raw_output"
        )

    def test_post_detection_raw_output_matches_mock_speed_records(self, caplog):
        """AC1(3): raw_output speedRecords must exactly match what the mock returned."""
        fake = _make_populated_raw()
        expected_speed = dict(fake["speedRecords"])
        info_records, _ = _call_endpoint(caplog, fake, curve_exists=True)
        post = [r for r in info_records if getattr(r, "event", "") == "pr_detection_output"]
        assert post
        assert post[0].raw_output.get("speedRecords") == expected_speed

    def test_pre_detection_log_precedes_post_detection_log(self, caplog):
        """AC1(3): The pr_detection_input log must appear before pr_detection_output."""
        info_records, _ = _call_endpoint(caplog, _make_populated_raw(), curve_exists=True)
        events = [getattr(r, "event", None) for r in info_records]
        assert "pr_detection_input" in events, "pr_detection_input event not logged"
        assert "pr_detection_output" in events, "pr_detection_output event not logged"
        assert events.index("pr_detection_input") < events.index("pr_detection_output")


# ══════════════════════════════════════════════════════════════════════════════
# AC2 + AC3: pr_detection.py smoke tests — verify no logic was modified
# ══════════════════════════════════════════════════════════════════════════════


class TestPrDetectionModuleIntact:
    """AC2 + AC3: The three pure functions in pr_detection.py must remain intact.

    Constants (STANDARD_DISTANCES_KM, STANDARD_POWER_DURATIONS_SECONDS) are
    imported and inspected rather than hardcoding any numeric values (AC4).
    """

    def test_detect_speed_records_empty_input_returns_reason(self):
        """AC3: detect_speed_records still returns a reason dict for empty input."""
        from backend.services.pr_detection import detect_speed_records
        result = detect_speed_records([], [])
        assert "reason" in result

    def test_detect_power_records_empty_input_returns_reason(self):
        """AC3: detect_power_records still returns a reason dict for empty input."""
        from backend.services.pr_detection import detect_power_records
        result = detect_power_records([])
        assert "reason" in result

    def test_detect_volume_records_empty_input_returns_reason(self):
        """AC3: detect_volume_records still returns a reason dict for empty input."""
        from backend.services.pr_detection import detect_volume_records
        result = detect_volume_records([])
        assert "reason" in result

    def test_standard_distances_has_expected_keys(self):
        """AC4: STANDARD_DISTANCES_KM exposes the six canonical distance labels."""
        expected = {"1km", "1mile", "5km", "10km", "half_marathon", "marathon"}
        assert set(STANDARD_DISTANCES_KM.keys()) == expected

    def test_standard_power_durations_has_expected_keys(self):
        """AC4: STANDARD_POWER_DURATIONS_SECONDS exposes the three canonical labels."""
        expected = {"best1Min", "best5Min", "best20Min"}
        assert set(STANDARD_POWER_DURATIONS_SECONDS.keys()) == expected
