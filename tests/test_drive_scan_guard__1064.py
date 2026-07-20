"""Tests for issue #1064: Guard against unconstrained Drive scan when folder ID env var is unset.

Acceptance criteria verified:
- AC1: When HEALTH_SYNC_DRIVE_FOLDER_ID is absent/empty, list_drive_sleep_files() must NOT
       make any Drive API call (unbounded scan is forbidden).
- AC2: When HEALTH_SYNC_DRIVE_FOLDER_ID is absent/empty, function returns an empty list.
- AC3: When HEALTH_SYNC_DRIVE_FOLDER_ID is absent/empty, a WARNING is logged with a clear
       message indicating the env var is not configured.
- AC4: When HEALTH_SYNC_DRIVE_FOLDER_ID is set, function proceeds normally and includes the
       folder constraint in the Drive query.
"""
import logging
from unittest.mock import MagicMock, patch


class TestNoFolderIdGuard:
    """AC1 + AC2 + AC3: empty/absent folder_id must bail out early."""

    def test_no_api_call_when_folder_id_missing(self):
        """AC1: Drive API is never called when HEALTH_SYNC_DRIVE_FOLDER_ID is unset."""
        from backend.services import drive_sleep_sync as dss

        with (
            patch.dict("os.environ", {}, clear=False),
            patch.object(dss, "_DRIVE_HEALTH_SYNC_FOLDER_ENV", "HEALTH_SYNC_DRIVE_FOLDER_ID"),
        ):
            import os
            os.environ.pop("HEALTH_SYNC_DRIVE_FOLDER_ID", None)

            with patch("backend.services.drive_sleep_sync._requests") as mock_requests:
                dss.list_drive_sleep_files("fake-access-token")

        mock_requests.get.assert_not_called()

    def test_no_api_call_when_folder_id_empty_string(self):
        """AC1: Drive API is never called when HEALTH_SYNC_DRIVE_FOLDER_ID is set to empty string."""
        from backend.services import drive_sleep_sync as dss

        with patch.dict("os.environ", {"HEALTH_SYNC_DRIVE_FOLDER_ID": ""}):
            with patch("backend.services.drive_sleep_sync._requests") as mock_requests:
                dss.list_drive_sleep_files("fake-access-token")

        mock_requests.get.assert_not_called()

    def test_returns_empty_list_when_folder_id_missing(self):
        """AC2: function returns [] when HEALTH_SYNC_DRIVE_FOLDER_ID is not configured."""
        from backend.services import drive_sleep_sync as dss

        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("HEALTH_SYNC_DRIVE_FOLDER_ID", None)
            with patch("backend.services.drive_sleep_sync._requests"):
                result = dss.list_drive_sleep_files("fake-access-token")

        assert result == [], f"Expected [], got {result!r}"

    def test_returns_empty_list_when_folder_id_empty_string(self):
        """AC2: function returns [] when HEALTH_SYNC_DRIVE_FOLDER_ID is an empty string."""
        from backend.services import drive_sleep_sync as dss

        with patch.dict("os.environ", {"HEALTH_SYNC_DRIVE_FOLDER_ID": ""}):
            with patch("backend.services.drive_sleep_sync._requests"):
                result = dss.list_drive_sleep_files("fake-access-token")

        assert result == [], f"Expected [], got {result!r}"

    def test_returns_empty_list_when_folder_id_whitespace_only(self):
        """AC2: function returns [] when HEALTH_SYNC_DRIVE_FOLDER_ID is whitespace only."""
        from backend.services import drive_sleep_sync as dss

        with patch.dict("os.environ", {"HEALTH_SYNC_DRIVE_FOLDER_ID": "   "}):
            with patch("backend.services.drive_sleep_sync._requests"):
                result = dss.list_drive_sleep_files("fake-access-token")

        assert result == [], f"Expected [], got {result!r}"

    def test_logs_warning_when_folder_id_missing(self, caplog):
        """AC3: a WARNING is emitted when folder ID is not configured."""
        from backend.services import drive_sleep_sync as dss

        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("HEALTH_SYNC_DRIVE_FOLDER_ID", None)
            with (
                patch("backend.services.drive_sleep_sync._requests"),
                caplog.at_level(logging.WARNING, logger="backend.services.drive_sleep_sync"),
            ):
                dss.list_drive_sleep_files("fake-access-token")

        warn_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warn_records, "No WARNING log emitted when folder_id is missing"

    def test_log_message_mentions_env_var(self, caplog):
        """AC3: log message references HEALTH_SYNC_DRIVE_FOLDER_ID so ops can diagnose it."""
        from backend.services import drive_sleep_sync as dss

        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("HEALTH_SYNC_DRIVE_FOLDER_ID", None)
            with (
                patch("backend.services.drive_sleep_sync._requests"),
                caplog.at_level(logging.WARNING, logger="backend.services.drive_sleep_sync"),
            ):
                dss.list_drive_sleep_files("fake-access-token")

        combined = " ".join(r.getMessage() for r in caplog.records)
        assert "HEALTH_SYNC_DRIVE_FOLDER_ID" in combined, (
            f"Env var name not mentioned in log: {combined!r}"
        )


class TestFolderIdPresentProceeds:
    """AC4: when folder_id is set, Drive API is called with the folder constraint."""

    def test_makes_api_call_when_folder_id_set(self):
        """AC4: Drive API is called when HEALTH_SYNC_DRIVE_FOLDER_ID is configured."""
        from backend.services import drive_sleep_sync as dss

        fake_folder_id = "fake-folder-abc123"
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"files": []}

        with patch.dict("os.environ", {"HEALTH_SYNC_DRIVE_FOLDER_ID": fake_folder_id}):
            with patch("backend.services.drive_sleep_sync._requests") as mock_requests:
                mock_requests.get.return_value = mock_resp
                dss.list_drive_sleep_files("fake-access-token")

        mock_requests.get.assert_called_once()

    def test_query_includes_folder_constraint_when_set(self):
        """AC4: the Drive query includes the folder id in 'in parents' when env var is set."""
        from backend.services import drive_sleep_sync as dss

        fake_folder_id = "my-health-sync-folder-id"
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"files": []}

        with patch.dict("os.environ", {"HEALTH_SYNC_DRIVE_FOLDER_ID": fake_folder_id}):
            with patch("backend.services.drive_sleep_sync._requests") as mock_requests:
                mock_requests.get.return_value = mock_resp
                dss.list_drive_sleep_files("fake-access-token")

        call_kwargs = mock_requests.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
        if not params and call_kwargs.kwargs.get("params"):
            params = call_kwargs.kwargs["params"]
        q = params.get("q", "")
        assert fake_folder_id in q, f"Folder id not in query: {q!r}"
        assert "in parents" in q, f"'in parents' not in query: {q!r}"

    def test_returns_files_from_drive_response(self):
        """AC4: function returns the files list from the Drive API response."""
        from backend.services import drive_sleep_sync as dss

        fake_folder_id = "folder-xyz"
        fake_files = [
            {"id": "file1", "name": "sleep.csv", "modifiedTime": "2026-01-01T00:00:00Z"},
        ]
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"files": fake_files}

        with patch.dict("os.environ", {"HEALTH_SYNC_DRIVE_FOLDER_ID": fake_folder_id}):
            with patch("backend.services.drive_sleep_sync._requests") as mock_requests:
                mock_requests.get.return_value = mock_resp
                result = dss.list_drive_sleep_files("fake-access-token")

        assert result == fake_files
