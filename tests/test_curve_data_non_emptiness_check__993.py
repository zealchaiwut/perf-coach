"""Tests for issue #993 (updated for the PRD-memory hotfix): curve_data
non-emptiness check in the PR endpoint rebuild guard.

Original #993 contract: an existing row with empty curve_data must count as
NOT populated (the old row-existence check logged populated=True and never
retried).

Updated contract (PRD OOM incident 2026-07-22): the retry is no longer an
inline rebuild in the GET request — it enqueues the worker performance
backfill via _trigger_performance_backfill_background. The new
runs_considered stamp prevents re-enqueueing for an athlete whose runs
legitimately produce an empty curve (no power data) until a new run appears.

Acceptance Criteria covered:
  - Row exists but curve_data is empty ({} or None) → curve_populated False,
    backfill IS enqueued (when run_count differs from runs_considered).
  - Row exists with non-empty curve_data → curve_populated True, no enqueue.
  - Empty curve whose runs_considered == current run_count → no enqueue
    (kills the rebuild-on-every-view loop).
  - run_count == 0 → no enqueue regardless of curve state.
  - The pre-detection log reflects the correct curve_populated value in all
    cases (row-missing, row-empty, row-populated).
"""

import logging
import unittest.mock as mock


def _make_curve_row(curve_data, runs_considered=None):
    """Return a mock AthleteDurationCurve row with explicit attribute values."""
    row = mock.MagicMock()
    row.curve_data = curve_data
    row.runs_considered = runs_considered
    return row


def _call_endpoint_with_curve(
    caplog, *, curve_data, runs_considered=None, has_row=True, run_count=5
):
    """Call get_athlete_run_personal_records with controlled curve row state.

    - curve_data / runs_considered: attributes of the (single) curve row read
      by the endpoint. has_row=False simulates no row at all.
    - run_count: synthetic DB run count.

    Returns (info_records, enqueue_call_count) where enqueue_call_count is the
    number of times _trigger_performance_backfill_background was called.
    """
    import backend.main as main_mod

    row = _make_curve_row(curve_data, runs_considered) if has_row else None

    import uuid as _uuid_mod
    athlete_uuid = _uuid_mod.UUID("00000000-0000-0000-0000-000000000001")

    mock_user = mock.MagicMock()
    mock_user.id = athlete_uuid

    mock_session = mock.MagicMock()
    mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
    mock_session.__exit__ = mock.MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.count.return_value = run_count
    mock_session.get.return_value = row

    fake_raw = {
        "speedRecords": {"reason": "test"},
        "powerRecords": {"reason": "test"},
        "volumeRecords": {"reason": "test"},
        "_meta": {"duration_curve_populated": False, "runs_considered": run_count},
    }

    enqueue_calls = {"n": 0}
    def _fake_enqueue(*args, **kwargs):
        enqueue_calls["n"] += 1

    with (
        caplog.at_level(logging.INFO, logger="backend.main"),
        mock.patch("backend.main.Session", return_value=mock_session),
        mock.patch(
            "backend.services.pr_detection.fetch_and_detect_records",
            return_value=dict(fake_raw),
        ),
        mock.patch(
            "backend.main._trigger_performance_backfill_background",
            side_effect=_fake_enqueue,
        ),
    ):
        main_mod.get_athlete_run_personal_records(
            athlete_id=str(athlete_uuid), user=mock_user
        )

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    return info_records, enqueue_calls["n"]


class TestCurveDataEmptyRowTriggersEnqueue:
    """When a curve row exists but curve_data is empty, the retry guard must
    fire — as a worker-queue enqueue, never an inline rebuild."""

    def test_empty_curve_data_dict_enqueues_backfill(self, caplog):
        """Issue #993 core: row with curve_data={} → backfill IS enqueued."""
        _, enqueue_count = _call_endpoint_with_curve(
            caplog, curve_data={}, runs_considered=None, run_count=3
        )
        assert enqueue_count == 1, (
            f"Expected one backfill enqueue for empty curve_data, got {enqueue_count}"
        )

    def test_empty_curve_data_none_enqueues_backfill(self, caplog):
        """Row exists but curve_data is None → backfill IS enqueued."""
        _, enqueue_count = _call_endpoint_with_curve(
            caplog, curve_data=None, runs_considered=None, run_count=3
        )
        assert enqueue_count == 1

    def test_no_row_enqueues_backfill(self, caplog):
        """No row at all → backfill IS enqueued."""
        _, enqueue_count = _call_endpoint_with_curve(
            caplog, curve_data=None, has_row=False, run_count=3
        )
        assert enqueue_count == 1

    def test_stale_runs_considered_enqueues_backfill(self, caplog):
        """Empty curve last built from 2 runs, athlete now has 3 → enqueue."""
        _, enqueue_count = _call_endpoint_with_curve(
            caplog, curve_data={}, runs_considered=2, run_count=3
        )
        assert enqueue_count == 1


class TestEnqueueGuards:
    """Cases where the retry must NOT fire."""

    def test_populated_curve_data_skips_enqueue(self, caplog):
        """Row exists with non-empty curve_data → no enqueue."""
        _, enqueue_count = _call_endpoint_with_curve(
            caplog,
            curve_data={60: {"best_value": 300.0}},
            runs_considered=5,
            run_count=5,
        )
        assert enqueue_count == 0, (
            f"Expected no enqueue for populated curve_data, got {enqueue_count}"
        )

    def test_empty_curve_with_matching_runs_considered_skips_enqueue(self, caplog):
        """runs_considered == run_count → the empty curve is a settled result
        (no power data in those runs); no re-enqueue on every page view."""
        _, enqueue_count = _call_endpoint_with_curve(
            caplog, curve_data={}, runs_considered=3, run_count=3
        )
        assert enqueue_count == 0, (
            "Empty curve already rebuilt from the same run count must not "
            f"re-enqueue, got {enqueue_count} enqueue(s)"
        )

    def test_zero_runs_skips_enqueue(self, caplog):
        """No run history → nothing to rebuild, no enqueue."""
        _, enqueue_count = _call_endpoint_with_curve(
            caplog, curve_data=None, has_row=False, run_count=0
        )
        assert enqueue_count == 0


class TestPreDetectionLog:
    """The pre-detection log must reflect curve_populated at read time."""

    def test_populated_curve_data_logs_curve_populated_true(self, caplog):
        info_records, _ = _call_endpoint_with_curve(
            caplog,
            curve_data={60: {"best_value": 300.0}},
            runs_considered=5,
            run_count=5,
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record"
        assert pre[0].duration_curve_populated is True

    def test_empty_curve_data_dict_logs_curve_populated_false(self, caplog):
        """curve_data={} → duration_curve_populated=False (the original #993 bug
        logged True because only row existence was checked)."""
        info_records, _ = _call_endpoint_with_curve(
            caplog, curve_data={}, runs_considered=None, run_count=3
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record"
        assert pre[0].duration_curve_populated is False

    def test_no_row_logs_curve_populated_false(self, caplog):
        info_records, _ = _call_endpoint_with_curve(
            caplog, curve_data=None, has_row=False, run_count=2
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record"
        assert pre[0].duration_curve_populated is False
