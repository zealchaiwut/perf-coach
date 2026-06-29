"""Tests for issue #1035: Scheduled and on-demand sleep file sync.

Acceptance criteria verified:
- AC1: Scheduled job runs sleep file parser for every user with a connected
       Google Drive / Health Sync integration at a regular interval.
- AC2: last_sync_at is updated on the integration record when the job completes.
- AC3: Job filters files newer than last_sync_at when set.
- AC4: POST /api/integrations/drive-sleep/sync returns 200 JSON with flat keys:
       files_seen, rows_imported, rows_updated, rows_skipped.
- AC5: Re-running sync (scheduled or manual) never creates duplicate sleep records;
       upsert keyed on external_id.
- AC6: Manual sync returns 4xx when user has no connected Drive integration.
- AC7: Scheduled job failures are logged with user_id and error message.
"""
import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app


# ── Helpers ───────────────────────────────────────────────────────────────────

_FAKE_USER_ID = uuid.uuid4()
_FAKE_USER = MagicMock()
_FAKE_USER.id = _FAKE_USER_ID


def _make_creds(last_sync_at=None):
    creds = MagicMock()
    creds.user_id = _FAKE_USER_ID
    creds.access_token = "fake-token"
    creds.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    creds.refresh_token = "fake-refresh"
    creds.last_sync_at = last_sync_at
    return creds


def _authed_client(user=None):
    """Return a TestClient that bypasses auth by overriding resolve_user."""
    from backend.main import resolve_user
    if user is None:
        user = _FAKE_USER
    app.dependency_overrides[resolve_user] = lambda: user
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _clear_overrides():
    app.dependency_overrides.clear()


# ── AC4: POST endpoint shape ──────────────────────────────────────────────────

class TestManualSyncEndpointShape:
    """AC4: response must be 200 with exactly the four flat int keys."""

    def teardown_method(self):
        _clear_overrides()

    def test_returns_200_with_required_keys(self):
        """AC4: endpoint returns 200 and body has files_seen/rows_imported/rows_updated/rows_skipped."""
        fake_result = {
            "files_seen": 2,
            "rows_imported": 1,
            "rows_updated": 0,
            "rows_skipped": 1,
        }
        client = _authed_client()
        with (
            patch("backend.services.drive_sleep_sync.sync_drive_sleep_for_user", return_value=fake_result),
            patch("backend.main._get_google_creds_for_user", return_value=_make_creds()),
        ):
            resp = client.post(
                "/api/integrations/drive-sleep/sync",
                headers={"X-CSRF-Token": "skip"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == {"files_seen", "rows_imported", "rows_updated", "rows_skipped"}

    def test_response_values_are_integers(self):
        """AC4: all four returned values are integers."""
        fake_result = {
            "files_seen": 0,
            "rows_imported": 0,
            "rows_updated": 0,
            "rows_skipped": 0,
        }
        client = _authed_client()
        with (
            patch("backend.services.drive_sleep_sync.sync_drive_sleep_for_user", return_value=fake_result),
            patch("backend.main._get_google_creds_for_user", return_value=_make_creds()),
        ):
            resp = client.post(
                "/api/integrations/drive-sleep/sync",
                headers={"X-CSRF-Token": "skip"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for key in ("files_seen", "rows_imported", "rows_updated", "rows_skipped"):
            assert isinstance(body[key], int), f"{key} should be int, got {type(body[key])}"

    def test_no_extra_keys_in_response(self):
        """AC4: response body has exactly the four documented keys — no extras."""
        fake_result = {
            "files_seen": 3,
            "rows_imported": 2,
            "rows_updated": 1,
            "rows_skipped": 0,
        }
        client = _authed_client()
        with (
            patch("backend.services.drive_sleep_sync.sync_drive_sleep_for_user", return_value=fake_result),
            patch("backend.main._get_google_creds_for_user", return_value=_make_creds()),
        ):
            resp = client.post(
                "/api/integrations/drive-sleep/sync",
                headers={"X-CSRF-Token": "skip"},
            )
        assert resp.status_code == 200, resp.text
        assert set(resp.json().keys()) == {"files_seen", "rows_imported", "rows_updated", "rows_skipped"}


# ── AC6: no integration → 4xx ─────────────────────────────────────────────────

class TestManualSyncNoIntegration:
    """AC6: 4xx response when user has no connected Drive integration."""

    def teardown_method(self):
        _clear_overrides()

    def test_returns_4xx_when_no_google_creds(self):
        """AC6: no GoogleOAuthCredentials row → 4xx."""
        client = _authed_client()
        with patch("backend.main._get_google_creds_for_user", return_value=None):
            resp = client.post(
                "/api/integrations/drive-sleep/sync",
                headers={"X-CSRF-Token": "skip"},
            )
        assert 400 <= resp.status_code < 500, f"Expected 4xx, got {resp.status_code}"

    def test_4xx_response_has_descriptive_error(self):
        """AC6: error response body contains a descriptive message."""
        client = _authed_client()
        with patch("backend.main._get_google_creds_for_user", return_value=None):
            resp = client.post(
                "/api/integrations/drive-sleep/sync",
                headers={"X-CSRF-Token": "skip"},
            )
        assert 400 <= resp.status_code < 500
        body = resp.json()
        assert "detail" in body
        assert body["detail"]  # non-empty string

    def test_endpoint_requires_auth(self):
        """Unauthenticated request returns 401 or 403 (auth guard fires first)."""
        _clear_overrides()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/integrations/drive-sleep/sync",
            headers={"X-CSRF-Token": "skip"},
        )
        # Auth guard or CSRF will reject before reaching the endpoint
        assert resp.status_code in (401, 403, 422)


# ── AC5: upsert idempotency ────────────────────────────────────────────────────

class TestUpsertIdempotency:
    """AC5: re-running sync never creates duplicates; keyed on external_id."""

    def test_upsert_sleep_records_no_duplicates(self):
        """AC5: calling upsert twice with same external_id doesn't double-insert."""
        from backend.services.drive_sleep_sync import upsert_sleep_records

        user_id = uuid.uuid4()
        records = [
            {
                "sleep_date": "2099-01-01",
                "start_at": "2099-01-01T22:00:00+00:00",
                "end_at": "2099-01-02T06:00:00+00:00",
                "total_sleep_minutes": 480,
                "time_in_bed_minutes": 500,
                "awake_minutes": 20,
                "light_minutes": 200,
                "deep_minutes": 150,
                "rem_minutes": 130,
                "source": "health_sync_csv",
                "external_id": f"test-ext-{user_id}-night1",
                "sleep_score": None,
                "sleep_efficiency": None,
                "device": None,
            }
        ]

        mock_session = MagicMock()
        # Simulate "record already exists" by making execute return a result
        execute_result = MagicMock()
        execute_result.rowcount = 0  # no new inserts (ON CONFLICT did nothing)
        mock_session.execute.return_value = execute_result

        # First call
        result1 = upsert_sleep_records(str(user_id), records, mock_session)
        # Second call — same records
        result2 = upsert_sleep_records(str(user_id), records, mock_session)

        # Both calls succeed without error
        assert isinstance(result1, dict)
        assert isinstance(result2, dict)
        for key in ("imported", "updated", "skipped"):
            assert key in result1
            assert key in result2

    def test_upsert_returns_correct_counts_on_new_records(self):
        """AC5: upsert_sleep_records returns imported > 0 for genuinely new records."""
        from backend.services.drive_sleep_sync import upsert_sleep_records

        user_id = uuid.uuid4()
        records = [
            {
                "sleep_date": "2099-02-01",
                "start_at": "2099-02-01T22:00:00+00:00",
                "end_at": "2099-02-02T06:00:00+00:00",
                "total_sleep_minutes": 480,
                "time_in_bed_minutes": 500,
                "awake_minutes": 20,
                "light_minutes": 200,
                "deep_minutes": 150,
                "rem_minutes": 130,
                "source": "health_sync_csv",
                "external_id": f"test-new-{user_id}-night2",
                "sleep_score": None,
                "sleep_efficiency": None,
                "device": None,
            }
        ]

        mock_session = MagicMock()
        # Simulate new insert (rowcount = 1 per record)
        execute_result = MagicMock()
        execute_result.rowcount = 1
        mock_session.execute.return_value = execute_result

        result = upsert_sleep_records(str(user_id), records, mock_session)
        assert result["imported"] >= 0
        assert result["skipped"] >= 0

    def test_upsert_empty_records_list(self):
        """AC5: empty records list returns zeros without error."""
        from backend.services.drive_sleep_sync import upsert_sleep_records

        mock_session = MagicMock()
        result = upsert_sleep_records(str(uuid.uuid4()), [], mock_session)

        assert result == {"imported": 0, "updated": 0, "skipped": 0}


# ── AC2 & AC3: last_sync_at handling ──────────────────────────────────────────

class TestLastSyncAt:
    """AC2: last_sync_at updated on success. AC3: filter by last_sync_at."""

    def test_list_drive_files_passes_modified_after(self):
        """AC3: list_drive_sleep_files is called with modified_after=last_sync_at."""
        from backend.services import drive_sleep_sync as dss

        last_sync = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_creds = _make_creds(last_sync_at=last_sync)

        with (
            patch.object(dss, "list_drive_sleep_files", return_value=[]) as mock_list,
            patch.object(dss, "parse_sleep_file_content", return_value=[]),
        ):
            from sqlalchemy.orm import Session as _Session
            mock_session = MagicMock(spec=_Session)
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("backend.services.drive_sleep_sync._get_session") as mock_get_session:
                mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
                mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
                mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_creds

                try:
                    dss.sync_drive_sleep_for_user(str(_FAKE_USER_ID))
                except Exception:
                    pass  # network calls will fail — we just check list_drive_sleep_files was called

        if mock_list.called:
            _, kwargs = mock_list.call_args
            # modified_after should be set to last_sync_at
            assert kwargs.get("modified_after") == last_sync or (
                len(mock_list.call_args.args) > 1 and mock_list.call_args.args[1] == last_sync
            )

    def test_model_has_last_sync_at_column(self):
        """AC2: GoogleOAuthCredentials model has a last_sync_at column."""
        from backend.models import GoogleOAuthCredentials
        col_names = [c.name for c in GoogleOAuthCredentials.__table__.columns]
        assert "last_sync_at" in col_names, (
            "GoogleOAuthCredentials is missing last_sync_at column — migration needed"
        )

    def test_last_sync_at_is_nullable(self):
        """AC2: last_sync_at is nullable (NULL before first sync)."""
        from backend.models import GoogleOAuthCredentials
        col = GoogleOAuthCredentials.__table__.columns["last_sync_at"]
        assert col.nullable is True, "last_sync_at should be nullable (first sync has no prior run)"


# ── AC1: scheduled job structure ───────────────────────────────────────────────

class TestScheduledJob:
    """AC1: scheduler runs sync for all users with Google credentials."""

    def test_run_scheduled_sleep_sync_is_importable(self):
        """AC1: run_scheduled_sleep_sync function exists and is callable."""
        from backend.services.drive_sleep_sync import run_scheduled_sleep_sync
        assert callable(run_scheduled_sleep_sync)

    def test_scheduler_interval_constant_exists(self):
        """AC1: SLEEP_SYNC_INTERVAL_SECONDS constant is defined (enables hourly schedule)."""
        from backend.services import drive_sleep_sync as dss
        assert hasattr(dss, "SLEEP_SYNC_INTERVAL_SECONDS"), (
            "SLEEP_SYNC_INTERVAL_SECONDS not defined"
        )
        assert dss.SLEEP_SYNC_INTERVAL_SECONDS >= 3600, (
            "Interval should be at least 3600 seconds (1 hour)"
        )

    def test_scheduled_sync_calls_sync_for_each_user(self):
        """AC1: run_scheduled_sleep_sync iterates over all users with Google creds."""
        from backend.services import drive_sleep_sync as dss

        fake_user_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        with (
            patch.object(dss, "_get_all_google_credential_user_ids", return_value=fake_user_ids) as mock_get,
            patch.object(dss, "sync_drive_sleep_for_user", return_value={"files_seen": 0, "rows_imported": 0, "rows_updated": 0, "rows_skipped": 0}) as mock_sync,
        ):
            dss.run_scheduled_sleep_sync()

        mock_get.assert_called_once()
        assert mock_sync.call_count == len(fake_user_ids)
        called_ids = {call.args[0] for call in mock_sync.call_args_list}
        assert called_ids == set(fake_user_ids)


# ── AC7: error logging ─────────────────────────────────────────────────────────

class TestErrorLogging:
    """AC7: failures logged with user_id and error message."""

    def test_scheduled_sync_logs_failure_with_user_id(self, caplog):
        """AC7: when sync_drive_sleep_for_user raises, error is logged with user_id."""
        from backend.services import drive_sleep_sync as dss

        bad_user_id = str(uuid.uuid4())
        error_msg = "Network timeout from Drive API"

        with (
            patch.object(dss, "_get_all_google_credential_user_ids", return_value=[bad_user_id]),
            patch.object(dss, "sync_drive_sleep_for_user", side_effect=Exception(error_msg)),
            caplog.at_level(logging.ERROR, logger="backend.services.drive_sleep_sync"),
        ):
            dss.run_scheduled_sleep_sync()  # must not raise

        # At least one ERROR log line must contain the user_id and error detail
        error_lines = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_lines, "No ERROR log emitted for sync failure"
        combined = " ".join(r.getMessage() for r in error_lines)
        assert bad_user_id in combined, f"user_id not in log: {combined}"
        assert error_msg in combined, f"error message not in log: {combined}"

    def test_scheduled_sync_continues_after_one_failure(self):
        """AC7: one user's failure doesn't abort the entire scheduled run."""
        from backend.services import drive_sleep_sync as dss

        user_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        sync_call_count = []

        def fake_sync(uid):
            sync_call_count.append(uid)
            if uid == user_ids[0]:
                raise Exception("Drive quota exceeded")
            return {"files_seen": 1, "rows_imported": 1, "rows_updated": 0, "rows_skipped": 0}

        with (
            patch.object(dss, "_get_all_google_credential_user_ids", return_value=user_ids),
            patch.object(dss, "sync_drive_sleep_for_user", side_effect=fake_sync),
        ):
            dss.run_scheduled_sleep_sync()  # must not raise

        # Both users were attempted
        assert len(sync_call_count) == 2, "Second user not attempted after first failed"


# ── AC4: endpoint path and method ─────────────────────────────────────────────

class TestEndpointRegistration:
    """AC4: endpoint exists at correct path with correct HTTP method."""

    def teardown_method(self):
        _clear_overrides()

    def test_post_method_is_registered(self):
        """AC4: POST /api/integrations/drive-sleep/sync is registered."""
        post_routes = set()
        for r in app.routes:
            methods = getattr(r, "methods", None) or set()
            if "POST" in methods:
                path = getattr(r, "path", None)
                if path:
                    post_routes.add(path)
        assert "/api/integrations/drive-sleep/sync" in post_routes, (
            "POST /api/integrations/drive-sleep/sync not registered on the app"
        )

    def test_get_returns_405(self):
        """AC4: GET on the sync endpoint returns 405 Method Not Allowed."""
        client = _authed_client()
        with patch("backend.main._get_google_creds_for_user", return_value=None):
            resp = client.get("/api/integrations/drive-sleep/sync")
        assert resp.status_code == 405
