"""Tests for issue #993: check curve_data non-emptiness (not just row existence)
in the PR endpoint rebuild guard.

Acceptance Criteria covered:
  - When a row exists but curve_data is empty ({}), curve_populated must be False
    and the rebuild must be re-triggered.
  - When a row exists with non-empty curve_data, curve_populated must be True
    and no rebuild is triggered.
  - The pre-detection log must reflect the correct curve_populated value in all
    cases (row-missing, row-empty, row-populated).
"""

import logging
import unittest.mock as mock

import pytest


def _make_curve_row(curve_data):
    """Return a mock AthleteDurationCurve row with the given curve_data."""
    row = mock.MagicMock()
    row.curve_data = curve_data
    return row


def _call_endpoint_with_curve(caplog, *, first_curve_data, second_curve_data=None, run_count=5):
    """Call get_athlete_run_personal_records with controlled curve row state.

    - first_curve_data: the curve_data value on the row returned by the first
      session.get call (before any rebuild). Pass None to simulate no row.
    - second_curve_data: the curve_data value returned by the second session.get
      call (after rebuild). Defaults to first_curve_data if not provided.
    - run_count: synthetic DB run count.

    Returns (info_records, rebuild_call_count) where info_records is the list
    of INFO log records from backend.main and rebuild_call_count is the number
    of times _rebuild_athlete_duration_curve was called.
    """
    import backend.main as main_mod

    if second_curve_data is None:
        second_curve_data = first_curve_data

    def _make_row_or_none(curve_data):
        if curve_data is None:
            return None
        return _make_curve_row(curve_data)

    first_row = _make_row_or_none(first_curve_data)
    second_row = _make_row_or_none(second_curve_data)

    call_count = {"n": 0}
    def _side_effect(*args, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx == 0:
            return first_row
        return second_row

    import uuid as _uuid_mod
    athlete_uuid = _uuid_mod.UUID("00000000-0000-0000-0000-000000000001")

    mock_user = mock.MagicMock()
    mock_user.id = athlete_uuid

    mock_session = mock.MagicMock()
    mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
    mock_session.__exit__ = mock.MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.count.return_value = run_count
    mock_session.get.side_effect = _side_effect

    fake_raw = {
        "speedRecords": {"reason": "test"},
        "powerRecords": {"reason": "test"},
        "volumeRecords": {"reason": "test"},
        "_meta": {"duration_curve_populated": False, "runs_considered": run_count},
    }

    rebuild_calls = {"n": 0}
    def _fake_rebuild(*args, **kwargs):
        rebuild_calls["n"] += 1

    with (
        caplog.at_level(logging.INFO, logger="backend.main"),
        mock.patch("backend.main.Session", return_value=mock_session),
        mock.patch(
            "backend.services.pr_detection.fetch_and_detect_records",
            return_value=dict(fake_raw),
        ),
        mock.patch(
            "backend.main._rebuild_athlete_duration_curve",
            side_effect=_fake_rebuild,
        ),
    ):
        main_mod.get_athlete_run_personal_records(
            athlete_id=str(athlete_uuid), user=mock_user
        )

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    return info_records, rebuild_calls["n"]


class TestCurveDataEmptyRowTriggersRebuild:
    """When a curve row exists but curve_data is empty, the rebuild guard must
    fire — the old row-existence check incorrectly skipped this case."""

    def test_empty_curve_data_dict_triggers_rebuild(self, caplog):
        """Issue #993 core: row exists with curve_data={} → rebuild IS triggered."""
        _, rebuild_count = _call_endpoint_with_curve(
            caplog, first_curve_data={}, run_count=3
        )
        assert rebuild_count == 1, (
            f"Expected rebuild to be called once for empty curve_data, got {rebuild_count}"
        )

    def test_empty_curve_data_none_triggers_rebuild(self, caplog):
        """Row exists but curve_data is None → rebuild IS triggered."""
        _, rebuild_count = _call_endpoint_with_curve(
            caplog, first_curve_data=None, run_count=3
        )
        assert rebuild_count == 1, (
            f"Expected rebuild to be called once for None curve_data, got {rebuild_count}"
        )

    def test_no_row_triggers_rebuild(self, caplog):
        """No row at all (None return) → rebuild IS triggered (pre-existing behaviour)."""
        _, rebuild_count = _call_endpoint_with_curve(
            caplog, first_curve_data=None, run_count=3
        )
        assert rebuild_count == 1


class TestCurveDataPopulatedRowSkipsRebuild:
    """When curve_data is non-empty, no rebuild should be triggered."""

    def test_populated_curve_data_skips_rebuild(self, caplog):
        """Row exists with non-empty curve_data → rebuild is NOT triggered."""
        _, rebuild_count = _call_endpoint_with_curve(
            caplog,
            first_curve_data={60: {"best_value": 300.0}},
            run_count=5,
        )
        assert rebuild_count == 0, (
            f"Expected no rebuild for populated curve_data, got {rebuild_count}"
        )

    def test_populated_curve_data_logs_curve_populated_true(self, caplog):
        """When curve_data is non-empty, the pre-detection log reports True."""
        info_records, _ = _call_endpoint_with_curve(
            caplog,
            first_curve_data={60: {"best_value": 300.0}},
            run_count=5,
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record"
        assert pre[0].duration_curve_populated is True


class TestCurveDataEmptyRowLogsCorrectly:
    """The pre-detection log must reflect curve_populated=False when curve_data
    is empty, even though a row exists (the old bug logged True in this case)."""

    def test_empty_curve_data_dict_logs_curve_populated_false(self, caplog):
        """curve_data={} → pre-detection log must report duration_curve_populated=False."""
        info_records, _ = _call_endpoint_with_curve(
            caplog, first_curve_data={}, second_curve_data={}, run_count=3
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record"
        assert pre[0].duration_curve_populated is False, (
            "curve_data={} is falsy — duration_curve_populated must be False, "
            f"got {pre[0].duration_curve_populated}"
        )

    def test_empty_curve_data_after_rebuild_still_logs_false(self, caplog):
        """After rebuild, if curve_data is still empty, log remains False."""
        info_records, _ = _call_endpoint_with_curve(
            caplog, first_curve_data={}, second_curve_data={}, run_count=3
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre
        assert pre[0].duration_curve_populated is False

    def test_empty_curve_then_rebuilt_with_data_logs_true(self, caplog):
        """After rebuild produces non-empty curve_data, log reports True."""
        info_records, _ = _call_endpoint_with_curve(
            caplog,
            first_curve_data={},
            second_curve_data={60: {"best_value": 280.0}},
            run_count=4,
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record"
        assert pre[0].duration_curve_populated is True, (
            "After rebuild, non-empty curve_data must yield duration_curve_populated=True"
        )


class TestRowMissingLogsCorrectly:
    """Regression: when no row exists at all, behaviour is unchanged (still
    triggers rebuild and logs False initially)."""

    def test_no_row_logs_curve_populated_false_initially(self, caplog):
        """No row → pre-detection log reports False before rebuild."""
        info_records, _ = _call_endpoint_with_curve(
            caplog, first_curve_data=None, second_curve_data=None, run_count=2
        )
        pre = [r for r in info_records if getattr(r, "event", "") == "pr_detection_input"]
        assert pre, "Expected a pr_detection_input log record"
        assert pre[0].duration_curve_populated is False
