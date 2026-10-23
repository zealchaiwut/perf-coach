"""Stryd sync must reconcile when Stryd rows already exist (Strava synced first)."""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from backend.services import sync_runner


def test_run_stryd_sync_reconciles_db_rows_when_api_upserted_zero():
    uid = uuid.uuid4()
    recorder = MagicMock()
    since = date(2026, 6, 17)
    db_ids = ["stryd-existing-1"]

    sync_result = {
        "upserted": 0,
        "stryd_activity_ids": [],
        "since_date": since,
    }

    with patch("backend.services.stryd_sync.sync_stryd_activities", return_value=sync_result), \
         patch.object(sync_runner, "_stryd_activity_ids_since", return_value=db_ids) as mock_db_ids, \
         patch.object(sync_runner._reconcile, "reconcile_workouts") as mock_reconcile, \
         patch.object(sync_runner, "run_plan_matcher"), \
         patch.object(sync_runner, "_upsert_form_metrics_incremental"):
        sync_runner.run_stryd_sync(str(uid), full=False, recorder=recorder)

    mock_db_ids.assert_called_once_with(uid, since)
    mock_reconcile.assert_called_once_with(
        uid,
        uid,
        stryd_activity_ids=db_ids,
    )
    recorder.mark_success.assert_called_once()
