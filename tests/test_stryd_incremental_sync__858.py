"""Incremental Stryd sync: since-date resolution and scoped reconcile."""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from backend.services import stryd_sync


def test_sync_stryd_incremental_uses_last_completed_job():
    uid = uuid.uuid4()
    completed_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)

    class FakeSession:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, stmt):
            sql = str(stmt)
            if "sync_jobs" in sql:
                return MagicMock(scalar=lambda: completed_at)
            return MagicMock(scalar=lambda: None)

        def query(self, *args):
            cred = MagicMock(athlete_id="123")
            return MagicMock(
                filter=MagicMock(return_value=MagicMock(one=MagicMock(return_value=cred)))
            )

        def add(self, _job):
            pass

        def commit(self):
            pass

        def refresh(self, job):
            job.id = uuid.uuid4()

        def get(self, _model, _id):
            job = MagicMock()
            return job

    captured = {}

    def fake_fetch(token, athlete_id, since_date=None, before_date=None):
        captured["since_date"] = since_date
        return []

    with patch.object(stryd_sync, "Session", FakeSession), \
         patch.object(stryd_sync, "refresh_stryd_session_if_needed", return_value="tok"), \
         patch.object(stryd_sync, "fetch_stryd_activities", side_effect=fake_fetch):
        result = stryd_sync.sync_stryd_activities(str(uid))

    assert captured["since_date"] == date(2026, 6, 17)
    assert result["upserted"] == 0
    assert result["stryd_activity_ids"] == []
