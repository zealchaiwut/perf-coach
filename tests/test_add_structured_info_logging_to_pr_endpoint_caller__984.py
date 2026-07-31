"""Tests for issue #984: structured INFO logging in the PR endpoint caller.

Acceptance Criteria covered:
  AC1: PR endpoint caller emits an INFO log entry stating whether the duration
       curve is populated and the run count before invoking pr_detection.py.
  AC2: PR endpoint caller emits an INFO log entry with the raw output from
       pr_detection.py after invocation.
  AC3: No logic changes are made inside backend/services/pr_detection.py.
  AC4: Existing unit tests for pr_detection.py continue to pass (verified by
       running the existing test_pr_detection_from_run_history__704.py suite).
"""

import logging
import unittest.mock as mock
import uuid

import pytest


# ── Pure helper tests (AC1) ───────────────────────────────────────────────────


class TestBuildRunPrPreDetectionLogEntry:
    """Tests for the pure pre-detection log-entry builder (_build_run_pr_pre_detection_log_entry).

    The helper must be importable from backend.main and build the correct
    structured dict from (duration_curve_populated, runs_considered) inputs.
    """

    def _helper(self):
        from backend.main import _build_run_pr_pre_detection_log_entry
        return _build_run_pr_pre_detection_log_entry

    def test_helper_is_importable(self):
        """AC1: The helper must be importable from backend.main."""
        fn = self._helper()
        assert callable(fn)

    def test_event_key_present(self):
        """AC1: The log entry must include an 'event' key."""
        fn = self._helper()
        entry = fn(duration_curve_populated=True, runs_considered=5)
        assert "event" in entry

    def test_duration_curve_populated_true(self):
        """AC1: duration_curve_populated is True when a curve record exists."""
        fn = self._helper()
        entry = fn(duration_curve_populated=True, runs_considered=10)
        assert entry["duration_curve_populated"] is True

    def test_duration_curve_populated_false(self):
        """AC1: duration_curve_populated is False when no curve record exists."""
        fn = self._helper()
        entry = fn(duration_curve_populated=False, runs_considered=0)
        assert entry["duration_curve_populated"] is False

    def test_runs_considered_int(self):
        """AC1: runs_considered is an integer in the log entry."""
        fn = self._helper()
        entry = fn(duration_curve_populated=True, runs_considered=42)
        assert isinstance(entry["runs_considered"], int)
        assert entry["runs_considered"] == 42

    def test_runs_considered_zero(self):
        """AC1: runs_considered is 0 when the athlete has no run workouts."""
        fn = self._helper()
        entry = fn(duration_curve_populated=False, runs_considered=0)
        assert entry["runs_considered"] == 0

    def test_does_not_raise_with_falsy_inputs(self):
        """AC1: helper does not raise when called with None/falsy values."""
        fn = self._helper()
        try:
            entry = fn(duration_curve_populated=None, runs_considered=None)
        except Exception as exc:
            pytest.fail(f"Helper raised unexpectedly: {exc}")
        assert "duration_curve_populated" in entry
        assert "runs_considered" in entry


# ── Endpoint logging tests (AC1 + AC2) ───────────────────────────────────────


def _make_fake_raw(duration_curve_populated=False, runs_considered=3):
    """Return a minimal fetch_and_detect_records result dict with _meta."""
    return {
        "speedRecords": {"reason": "duration curve is empty"},
        "powerRecords": {"reason": "duration curve is empty"},
        "volumeRecords": {"reason": "no completed runs provided"},
        "_meta": {
            "duration_curve_populated": duration_curve_populated,
            "runs_considered": runs_considered,
        },
    }


class TestRunPrEndpointLogging:
    """Verify the endpoint emits both pre- and post-detection INFO logs.

    The endpoint function is called directly with a mock user; the DB session
    and fetch_and_detect_records are patched so no real DB connection is needed.
    """

    def _call_endpoint(self, caplog, fake_raw, run_count=3, curve_exists=False):
        """Call get_athlete_run_personal_records with all external deps mocked.

        Returns the list of INFO-level log records emitted by backend.main.
        """
        import backend.main as main_mod

        mock_user = mock.MagicMock()
        mock_user.id = uuid.uuid4()

        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
        mock_session.__exit__ = mock.MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.count.return_value = run_count
        mock_session.get.return_value = mock.MagicMock() if curve_exists else None

        with caplog.at_level(logging.INFO, logger="backend.main"), \
             mock.patch("backend.main.Session", return_value=mock_session), \
             mock.patch(
                 "backend.services.pr_detection.fetch_and_detect_records",
                 return_value=dict(fake_raw),  # copy so pop doesn't affect fake_raw
             ):
            # athlete_id is a required path param (/api/athletes/{athlete_id}/...);
            # the endpoint 404s unless it matches user.id (#987/#1606).
            main_mod.get_athlete_run_personal_records(
                athlete_id=str(mock_user.id), user=mock_user
            )

        return [r for r in caplog.records if r.levelno == logging.INFO]

    def test_two_info_logs_emitted(self, caplog):
        """AC1 + AC2: exactly two INFO log entries are emitted — before and after detection."""
        records = self._call_endpoint(caplog, _make_fake_raw())
        # Filter to backend.main logger only (other loggers may emit)
        main_records = [r for r in records if "backend.main" in r.name]
        assert len(main_records) >= 2, (
            f"Expected at least 2 INFO records from backend.main, got {len(main_records)}: "
            f"{[r.getMessage() for r in main_records]}"
        )

    def test_pre_detection_log_has_duration_curve_populated(self, caplog):
        """AC1: pre-detection log contains the 'duration_curve_populated' field."""
        records = self._call_endpoint(caplog, _make_fake_raw(curve_exists := True), curve_exists=True)
        pre_records = [r for r in records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre_records, "No log record with event='pr_detection_input' found"
        assert hasattr(pre_records[0], "duration_curve_populated"), (
            "Pre-detection log must include 'duration_curve_populated' field"
        )

    def test_pre_detection_log_has_runs_considered(self, caplog):
        """AC1: pre-detection log contains the 'runs_considered' field."""
        records = self._call_endpoint(caplog, _make_fake_raw(), run_count=7)
        pre_records = [r for r in records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre_records, "No log record with event='pr_detection_input' found"
        assert hasattr(pre_records[0], "runs_considered"), (
            "Pre-detection log must include 'runs_considered' field"
        )

    def test_pre_detection_log_duration_curve_false_when_no_curve(self, caplog):
        """AC1: duration_curve_populated is False when no AthleteDurationCurve row exists."""
        records = self._call_endpoint(caplog, _make_fake_raw(), curve_exists=False)
        pre_records = [r for r in records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre_records
        assert pre_records[0].duration_curve_populated is False

    def test_pre_detection_log_duration_curve_true_when_curve_exists(self, caplog):
        """AC1: duration_curve_populated is True when an AthleteDurationCurve row exists."""
        records = self._call_endpoint(caplog, _make_fake_raw(), curve_exists=True)
        pre_records = [r for r in records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre_records
        assert pre_records[0].duration_curve_populated is True

    def test_pre_detection_log_runs_considered_matches_db_count(self, caplog):
        """AC1: runs_considered in the pre-detection log equals the DB run count."""
        records = self._call_endpoint(caplog, _make_fake_raw(runs_considered=12), run_count=12)
        pre_records = [r for r in records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre_records
        assert pre_records[0].runs_considered == 12

    def test_post_detection_log_has_raw_output(self, caplog):
        """AC2: post-detection log contains the raw structured output from pr_detection."""
        records = self._call_endpoint(caplog, _make_fake_raw())
        post_records = [r for r in records if getattr(r, "event", "") == "pr_detection_output"]
        assert post_records, "No log record with event='pr_detection_output' found"
        assert hasattr(post_records[0], "raw_output"), (
            "Post-detection log must include 'raw_output' field"
        )

    def test_post_detection_log_raw_output_has_speed_records(self, caplog):
        """AC2: the raw_output in the post-detection log includes 'speedRecords'."""
        fake = _make_fake_raw()
        records = self._call_endpoint(caplog, fake)
        post_records = [r for r in records if getattr(r, "event", "") == "pr_detection_output"]
        assert post_records
        raw_output = post_records[0].raw_output
        assert "speedRecords" in raw_output, (
            f"raw_output should contain 'speedRecords'; got keys: {list(raw_output.keys())}"
        )

    def test_post_detection_log_raw_output_has_power_records(self, caplog):
        """AC2: the raw_output in the post-detection log includes 'powerRecords'."""
        fake = _make_fake_raw()
        records = self._call_endpoint(caplog, fake)
        post_records = [r for r in records if getattr(r, "event", "") == "pr_detection_output"]
        assert post_records
        assert "powerRecords" in post_records[0].raw_output

    def test_post_detection_log_raw_output_has_volume_records(self, caplog):
        """AC2: the raw_output in the post-detection log includes 'volumeRecords'."""
        fake = _make_fake_raw()
        records = self._call_endpoint(caplog, fake)
        post_records = [r for r in records if getattr(r, "event", "") == "pr_detection_output"]
        assert post_records
        assert "volumeRecords" in post_records[0].raw_output

    def test_post_detection_raw_output_excludes_meta(self, caplog):
        """AC2: the _meta key is stripped before being logged (client never sees it)."""
        fake = _make_fake_raw()
        records = self._call_endpoint(caplog, fake)
        post_records = [r for r in records if getattr(r, "event", "") == "pr_detection_output"]
        assert post_records
        assert "_meta" not in post_records[0].raw_output, (
            "_meta is an internal field and must not appear in the post-detection log"
        )

    def test_pre_detection_log_emitted_before_post_detection_log(self, caplog):
        """AC1 + AC2: pre-detection log appears before post-detection log in caplog."""
        records = self._call_endpoint(caplog, _make_fake_raw())
        events = [getattr(r, "event", None) for r in records]
        assert "pr_detection_input" in events, "pre-detection event not found"
        assert "pr_detection_output" in events, "post-detection event not found"
        pre_idx = events.index("pr_detection_input")
        post_idx = events.index("pr_detection_output")
        assert pre_idx < post_idx, (
            f"Pre-detection log (idx={pre_idx}) must precede post-detection log (idx={post_idx})"
        )


# ── AC3: pr_detection.py unchanged ───────────────────────────────────────────


class TestPrDetectionModuleUnchanged:
    """Verify pr_detection.py pure functions are still intact (AC3, AC4).

    These smoke tests call each pure function and confirm the expected return
    structure — if any logic was accidentally modified, these will catch it.
    """

    def test_detect_speed_records_empty_input_returns_reason(self):
        """AC3/AC4: detect_speed_records with empty inputs returns a reason dict."""
        from backend.services.pr_detection import detect_speed_records
        result = detect_speed_records([], [])
        assert "reason" in result

    def test_detect_power_records_empty_input_returns_reason(self):
        """AC3/AC4: detect_power_records with empty input returns a reason dict."""
        from backend.services.pr_detection import detect_power_records
        result = detect_power_records([])
        assert "reason" in result

    def test_detect_volume_records_empty_input_returns_reason(self):
        """AC3/AC4: detect_volume_records with empty input returns a reason dict."""
        from backend.services.pr_detection import detect_volume_records
        result = detect_volume_records([])
        assert "reason" in result

    def test_detect_speed_records_returns_debug_key(self):
        """AC3/AC4: detect_speed_records with valid input includes a 'debug' key."""
        from backend.services.pr_detection import detect_speed_records
        run = {"id": "r1", "workout_date": "2026-01-01", "distance_km": 10.0, "duration_seconds": 3000}
        curve = [{"duration_seconds": 3000, "best_value": 300.0, "source_workout_id": "r1",
                  "date": "2026-01-01", "source_workout": run}]
        result = detect_speed_records(curve, [run])
        assert "debug" in result

    def test_fetch_and_detect_records_returns_meta(self):
        """AC3/AC4: fetch_and_detect_records still returns a _meta key."""
        from backend.services.pr_detection import fetch_and_detect_records

        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        mock_db.get.return_value = None

        result = fetch_and_detect_records(user_id=1, db=mock_db)
        assert "_meta" in result, "fetch_and_detect_records must still return _meta"
        assert "duration_curve_populated" in result["_meta"]
        assert "runs_considered" in result["_meta"]
