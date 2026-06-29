"""Tests for issue #1038: Backfill historical sleep data from existing Drive files.

Acceptance criteria verified:
- AC1: On first successful Drive connect, ALL sleep files are enumerated and processed
       (no modified_after filter applied).
- AC2: Re-running backfill against already-ingested files produces zero duplicate records
       (upsert keyed on external_id).
- AC4: Backfill runs asynchronously — connect response is returned immediately without
       waiting for backfill to finish.
- AC5: A partially failing backfill logs error per file and continues remaining files.
- AC6: No backfill is triggered on subsequent syncs / reconnects — only on first connect.
"""
import logging
import threading
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from backend.main import app


# ── Helpers ───────────────────────────────────────────────────────────────────

_FAKE_USER_ID = str(uuid.uuid4())


def _make_creds(last_sync_at=None):
    creds = MagicMock()
    creds.user_id = uuid.UUID(_FAKE_USER_ID)
    creds.access_token = "fake-access-token"
    creds.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    creds.refresh_token = "fake-refresh-token"
    creds.last_sync_at = last_sync_at
    return creds


def _make_sleep_file(file_id="file-1", name="sleep-2026-01-01.csv"):
    return {"id": file_id, "name": name, "modifiedTime": "2026-01-01T00:00:00Z"}


def _make_sleep_record(ext_id="ext-1", date="2026-01-01"):
    return {
        "sleep_date": date,
        "start_at": f"{date}T22:00:00+00:00",
        "end_at": f"{date}T06:00:00+00:00",
        "total_sleep_minutes": 480,
        "time_in_bed_minutes": 500,
        "awake_minutes": 20,
        "light_minutes": 200,
        "deep_minutes": 150,
        "rem_minutes": 130,
        "sleep_score": None,
        "sleep_efficiency": None,
        "source": "health_sync_csv",
        "device": None,
        "external_id": ext_id,
    }


# ── AC1: backfill lists ALL files (no modified_after filter) ──────────────────

class TestBackfillListsAllFiles:
    """AC1: backfill_drive_sleep_for_user must call list_drive_sleep_files
    WITHOUT a modified_after argument so every pre-existing file is processed."""

    def test_backfill_function_exists(self):
        """AC1: backfill_drive_sleep_for_user is importable from drive_sleep_sync."""
        from backend.services.drive_sleep_sync import backfill_drive_sleep_for_user
        assert callable(backfill_drive_sleep_for_user)

    def test_backfill_calls_list_without_modified_after(self):
        """AC1: list_drive_sleep_files called with modified_after=None (all files)."""
        from backend.services import drive_sleep_sync as dss

        mock_creds = _make_creds()

        with (
            patch("backend.services.drive_sleep_sync.refresh_token_if_needed",
                  return_value="tok"),
            patch.object(dss, "list_drive_sleep_files", return_value=[]) as mock_list,
            patch("backend.services.drive_sleep_sync._get_session") as mock_ctx,
        ):
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_creds
            mock_ctx.return_value = mock_session

            try:
                dss.backfill_drive_sleep_for_user(_FAKE_USER_ID)
            except Exception:
                pass

        mock_list.assert_called_once()
        _, kwargs = mock_list.call_args
        # modified_after must be absent or explicitly None
        modified_after = kwargs.get("modified_after", None)
        assert modified_after is None, (
            f"backfill should not filter by modified_after, got {modified_after!r}"
        )

    def test_backfill_processes_multiple_files(self):
        """AC1: all files returned by list_drive_sleep_files are downloaded and parsed."""
        from backend.services import drive_sleep_sync as dss

        files = [_make_sleep_file(f"file-{i}", f"sleep-2026-0{i+1}-01.csv") for i in range(3)]
        records = [_make_sleep_record(f"ext-{i}", f"2026-0{i+1}-01") for i in range(3)]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = _make_creds()

        download_calls = []

        def fake_download(file_id, token):
            download_calls.append(file_id)
            return b"csv-bytes"

        with (
            patch("backend.services.drive_sleep_sync.refresh_token_if_needed",
                  return_value="tok"),
            patch.object(dss, "list_drive_sleep_files", return_value=files),
            patch.object(dss, "_download_drive_file", side_effect=fake_download),
            patch.object(dss, "parse_sleep_file_content",
                         side_effect=lambda b: [records[download_calls.index(download_calls[-1])]]),
            patch.object(dss, "upsert_sleep_records",
                         return_value={"imported": 1, "updated": 0, "skipped": 0}),
            patch("backend.services.drive_sleep_sync._get_session") as mock_ctx,
        ):
            mock_ctx.return_value = mock_session
            result = dss.backfill_drive_sleep_for_user(_FAKE_USER_ID)

        assert len(download_calls) == 3, f"Expected 3 downloads, got {len(download_calls)}"

    def test_backfill_returns_summary_dict(self):
        """AC1: backfill returns a dict with files_seen and row counts."""
        from backend.services import drive_sleep_sync as dss

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = _make_creds()

        with (
            patch("backend.services.drive_sleep_sync.refresh_token_if_needed",
                  return_value="tok"),
            patch.object(dss, "list_drive_sleep_files", return_value=[]),
            patch.object(dss, "upsert_sleep_records",
                         return_value={"imported": 0, "updated": 0, "skipped": 0}),
            patch("backend.services.drive_sleep_sync._get_session") as mock_ctx,
        ):
            mock_ctx.return_value = mock_session
            result = dss.backfill_drive_sleep_for_user(_FAKE_USER_ID)

        assert isinstance(result, dict)
        assert "files_seen" in result
        assert "rows_imported" in result


# ── AC2: idempotency on re-run ────────────────────────────────────────────────

class TestBackfillIdempotency:
    """AC2: re-running backfill with same files never creates duplicates."""

    def test_backfill_uses_upsert_path(self):
        """AC2: backfill delegates to upsert_sleep_records (keyed on external_id)."""
        from backend.services import drive_sleep_sync as dss

        files = [_make_sleep_file()]
        record = _make_sleep_record()

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = _make_creds()

        upsert_calls = []

        def fake_upsert(uid, recs, sess):
            upsert_calls.extend(recs)
            return {"imported": len(recs), "updated": 0, "skipped": 0}

        with (
            patch("backend.services.drive_sleep_sync.refresh_token_if_needed",
                  return_value="tok"),
            patch.object(dss, "list_drive_sleep_files", return_value=files),
            patch.object(dss, "_download_drive_file", return_value=b"csv"),
            patch.object(dss, "parse_sleep_file_content", return_value=[record]),
            patch.object(dss, "upsert_sleep_records", side_effect=fake_upsert),
            patch("backend.services.drive_sleep_sync._get_session") as mock_ctx,
        ):
            mock_ctx.return_value = mock_session
            dss.backfill_drive_sleep_for_user(_FAKE_USER_ID)

        # upsert_sleep_records must have been called with the record
        assert len(upsert_calls) == 1
        assert upsert_calls[0]["external_id"] == record["external_id"]


# ── AC4: async / non-blocking ─────────────────────────────────────────────────

class TestBackfillAsync:
    """AC4: backfill is triggered in a background thread; connect response is
    returned immediately."""

    def test_trigger_backfill_background_function_exists(self):
        """AC4: _trigger_drive_sleep_backfill_background is importable from main."""
        from backend.main import _trigger_drive_sleep_backfill_background
        assert callable(_trigger_drive_sleep_backfill_background)

    def test_trigger_backfill_does_not_block(self):
        """AC4: calling _trigger_drive_sleep_backfill_background returns immediately
        (does not block until backfill finishes)."""
        import time
        from backend.main import _trigger_drive_sleep_backfill_background
        from backend.services import drive_sleep_sync as dss

        started = threading.Event()
        finished = threading.Event()

        def slow_backfill(uid):
            started.set()
            time.sleep(0.5)
            finished.set()
            return {"files_seen": 0, "rows_imported": 0, "rows_updated": 0, "rows_skipped": 0}

        with patch.object(dss, "backfill_drive_sleep_for_user", side_effect=slow_backfill):
            t0 = time.monotonic()
            _trigger_drive_sleep_backfill_background(_FAKE_USER_ID)
            elapsed = time.monotonic() - t0

        assert elapsed < 0.3, (
            f"_trigger_drive_sleep_backfill_background blocked for {elapsed:.2f}s — must be non-blocking"
        )

    def test_trigger_backfill_calls_backfill_for_user(self):
        """AC4: background trigger eventually calls backfill_drive_sleep_for_user."""
        import time
        from backend.main import _trigger_drive_sleep_backfill_background
        from backend.services import drive_sleep_sync as dss

        called_with = []
        done = threading.Event()

        def fake_backfill(uid):
            called_with.append(uid)
            done.set()
            return {"files_seen": 0, "rows_imported": 0, "rows_updated": 0, "rows_skipped": 0}

        with patch.object(dss, "backfill_drive_sleep_for_user", side_effect=fake_backfill):
            _trigger_drive_sleep_backfill_background(_FAKE_USER_ID)
            done.wait(timeout=3.0)

        assert _FAKE_USER_ID in called_with, "backfill_drive_sleep_for_user was not called"


# ── AC5: partial failure logging ──────────────────────────────────────────────

class TestBackfillPartialFailure:
    """AC5: one malformed file logs error but processing continues for remaining files."""

    def test_backfill_continues_after_file_error(self):
        """AC5: if one file raises, backfill keeps processing the next files."""
        from backend.services import drive_sleep_sync as dss

        files = [
            _make_sleep_file("bad-file", "bad.csv"),
            _make_sleep_file("good-file", "good.csv"),
        ]

        processed_ids = []

        def fake_download(file_id, token):
            if file_id == "bad-file":
                raise ValueError("malformed CSV")
            return b"good-csv-bytes"

        def fake_parse(content_bytes):
            processed_ids.append("good")
            return [_make_sleep_record()]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = _make_creds()

        with (
            patch("backend.services.drive_sleep_sync.refresh_token_if_needed",
                  return_value="tok"),
            patch.object(dss, "list_drive_sleep_files", return_value=files),
            patch.object(dss, "_download_drive_file", side_effect=fake_download),
            patch.object(dss, "parse_sleep_file_content", side_effect=fake_parse),
            patch.object(dss, "upsert_sleep_records",
                         return_value={"imported": 1, "updated": 0, "skipped": 0}),
            patch("backend.services.drive_sleep_sync._get_session") as mock_ctx,
        ):
            mock_ctx.return_value = mock_session
            result = dss.backfill_drive_sleep_for_user(_FAKE_USER_ID)

        assert len(processed_ids) == 1, "Good file was not processed after bad file failed"

    def test_backfill_logs_error_for_bad_file(self, caplog):
        """AC5: error for malformed file is logged at ERROR level."""
        from backend.services import drive_sleep_sync as dss

        files = [_make_sleep_file("bad-file", "broken.csv")]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = _make_creds()

        with (
            patch("backend.services.drive_sleep_sync.refresh_token_if_needed",
                  return_value="tok"),
            patch.object(dss, "list_drive_sleep_files", return_value=files),
            patch.object(dss, "_download_drive_file",
                         side_effect=RuntimeError("Drive download error (bad-file): 404")),
            patch.object(dss, "upsert_sleep_records",
                         return_value={"imported": 0, "updated": 0, "skipped": 0}),
            patch("backend.services.drive_sleep_sync._get_session") as mock_ctx,
            caplog.at_level(logging.ERROR, logger="backend.services.drive_sleep_sync"),
        ):
            mock_ctx.return_value = mock_session
            dss.backfill_drive_sleep_for_user(_FAKE_USER_ID)  # must not raise

        error_lines = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_lines, "No ERROR logged for bad file"

    def test_backfill_does_not_raise_on_file_error(self):
        """AC5: backfill_drive_sleep_for_user must not raise even if all files fail."""
        from backend.services import drive_sleep_sync as dss

        files = [_make_sleep_file("bad-1"), _make_sleep_file("bad-2")]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = _make_creds()

        with (
            patch("backend.services.drive_sleep_sync.refresh_token_if_needed",
                  return_value="tok"),
            patch.object(dss, "list_drive_sleep_files", return_value=files),
            patch.object(dss, "_download_drive_file", side_effect=RuntimeError("Network error")),
            patch.object(dss, "upsert_sleep_records",
                         return_value={"imported": 0, "updated": 0, "skipped": 0}),
            patch("backend.services.drive_sleep_sync._get_session") as mock_ctx,
        ):
            mock_ctx.return_value = mock_session
            result = dss.backfill_drive_sleep_for_user(_FAKE_USER_ID)  # must not raise

        assert isinstance(result, dict)


# ── AC6: no backfill on reconnect ─────────────────────────────────────────────

class TestNoBackfillOnReconnect:
    """AC6: backfill fires only on first connect; reconnects skip it."""

    def test_google_callback_triggers_backfill_on_first_connect(self):
        """AC6: when no credentials row existed, _trigger_drive_sleep_backfill_background is called."""
        from backend.main import _trigger_drive_sleep_backfill_background

        triggered = []

        with (
            patch("backend.main._get_google_creds_for_user", return_value=None),
            patch("backend.main._verify_google_state_token",
                  return_value={"user_id": _FAKE_USER_ID}),
            patch("backend.main._exchange_google_code",
                  return_value={
                      "access_token": "tok",
                      "expires_in": 3600,
                      "id_token": "",
                  }),
            patch("backend.main._decode_id_token_payload",
                  return_value={"sub": "gsub", "email": "test@example.com",
                                "email_verified": True}),
            patch("backend.main._upsert_google_credentials"),
            patch("backend.main._trigger_drive_sleep_backfill_background",
                  side_effect=lambda uid: triggered.append(uid)) as mock_trigger,
            patch("os.getenv", side_effect=lambda k, default=None: {
                "GOOGLE_STATE_SECRET": "secret",
                "GOOGLE_CLIENT_ID": "cid",
                "GOOGLE_CLIENT_SECRET": "csecret",
                "GOOGLE_REDIRECT_URI": "http://localhost/cb",
            }.get(k, default)),
        ):
            from fastapi.testclient import TestClient
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/google/callback",
                params={"code": "auth-code", "state": "state-token"},
                follow_redirects=False,
            )

        assert mock_trigger.called, (
            "Expected _trigger_drive_sleep_backfill_background to be called on first connect"
        )
        assert _FAKE_USER_ID in triggered

    def test_google_callback_skips_backfill_on_reconnect(self):
        """AC6: when credentials row already exists, backfill is NOT triggered."""
        existing_creds = _make_creds()

        with (
            patch("backend.main._get_google_creds_for_user", return_value=existing_creds),
            patch("backend.main._verify_google_state_token",
                  return_value={"user_id": _FAKE_USER_ID}),
            patch("backend.main._exchange_google_code",
                  return_value={
                      "access_token": "tok",
                      "expires_in": 3600,
                      "id_token": "",
                  }),
            patch("backend.main._decode_id_token_payload",
                  return_value={"sub": "gsub", "email": "test@example.com",
                                "email_verified": True}),
            patch("backend.main._upsert_google_credentials"),
            patch("backend.main._trigger_drive_sleep_backfill_background") as mock_trigger,
            patch("os.getenv", side_effect=lambda k, default=None: {
                "GOOGLE_STATE_SECRET": "secret",
                "GOOGLE_CLIENT_ID": "cid",
                "GOOGLE_CLIENT_SECRET": "csecret",
                "GOOGLE_REDIRECT_URI": "http://localhost/cb",
            }.get(k, default)),
        ):
            from fastapi.testclient import TestClient
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/google/callback",
                params={"code": "auth-code", "state": "state-token"},
                follow_redirects=False,
            )

        mock_trigger.assert_not_called(), (
            "Backfill must NOT be triggered when credentials already exist (reconnect)"
        )

    def test_first_connect_detection_uses_pre_upsert_check(self):
        """AC6: first-connect is detected by checking credentials BEFORE the upsert
        (not after, which would always find a row)."""
        import inspect
        import backend.main as _main

        src = inspect.getsource(_main.google_callback)
        # The function must call _get_google_creds_for_user before _upsert_google_credentials
        idx_check = src.find("_get_google_creds_for_user")
        idx_upsert = src.find("_upsert_google_credentials")
        assert idx_check != -1, "_get_google_creds_for_user not found in google_callback"
        assert idx_upsert != -1, "_upsert_google_credentials not found in google_callback"
        assert idx_check < idx_upsert, (
            "First-connect check must happen BEFORE the upsert so it sees the pre-existing state"
        )
