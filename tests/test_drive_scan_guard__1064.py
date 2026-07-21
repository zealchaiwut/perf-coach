"""Tests for issue #1064: Guard against unconstrained Drive scan when folder ID env var is unset"""
import os
from unittest import mock


from backend.services.drive_sleep_sync import list_drive_sleep_files


class TestDriveScanGuard:
    """Test that list_drive_sleep_files guards against unconstrained Drive scan."""

    def test_empty_folder_id_returns_empty_list(self):
        """AC: When HEALTH_SYNC_DRIVE_FOLDER_ID is unset/empty, return [] without Drive API call."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("backend.services.drive_sleep_sync._requests.get") as mock_get:
                result = list_drive_sleep_files("fake-token")

                # No API call should occur
                mock_get.assert_not_called()
                # Result should be empty
                assert result == []

    def test_whitespace_only_folder_id_returns_empty_list(self):
        """AC: When HEALTH_SYNC_DRIVE_FOLDER_ID is whitespace-only, return [] and skip scan."""
        with mock.patch.dict(os.environ, {"HEALTH_SYNC_DRIVE_FOLDER_ID": "   "}, clear=True):
            with mock.patch("backend.services.drive_sleep_sync._requests.get") as mock_get:
                result = list_drive_sleep_files("fake-token")

                # No API call should occur
                mock_get.assert_not_called()
                # Result should be empty
                assert result == []

    def test_folder_id_set_includes_folder_constraint(self):
        """AC: When HEALTH_SYNC_DRIVE_FOLDER_ID is set, the folder constraint is in the query."""
        folder_id = "test-folder-123"
        with mock.patch.dict(
            os.environ, {"HEALTH_SYNC_DRIVE_FOLDER_ID": folder_id}, clear=True
        ):
            with mock.patch(
                "backend.services.drive_sleep_sync._requests.get"
            ) as mock_get:
                mock_get.return_value.ok = True
                mock_get.return_value.json.return_value = {"files": []}

                list_drive_sleep_files("fake-token")

                # Verify API was called
                mock_get.assert_called_once()
                # Verify folder constraint is in the query
                call_args = mock_get.call_args
                params = call_args.kwargs.get("params")
                assert params is not None
                query = params.get("q")
                assert query is not None
                assert f"'{folder_id}' in parents" in query
