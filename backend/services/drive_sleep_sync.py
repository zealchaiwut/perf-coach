"""Drive/Health Sync sleep file sync service (issue #1035).

Provides:
- sync_drive_sleep_for_user(user_id): full pipeline for one user.
- run_scheduled_sleep_sync(): runs all users with Google creds (called by scheduler).
- upsert_sleep_records(user_id, records, session): idempotent DB write.
- list_drive_sleep_files(access_token, modified_after=None): Drive API listing.
- parse_sleep_file_content(content_bytes, user_id): delegates to
  services.health_sync.sleep_csv_parser (#1034), which was already written.
- merge_sleep_records_into_daily_metrics(user_id, session): copies imported
  durations onto daily_metrics.sleep_hours, which is what readiness reads.
- _get_all_google_credential_user_ids(): helper for scheduler.
"""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

import requests as _requests
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import GoogleOAuthCredentials, SleepRecord
from backend.services.google import refresh_token_if_needed

_log = logging.getLogger("backend.services.drive_sleep_sync")

SLEEP_SYNC_INTERVAL_SECONDS = 3600  # 1 hour

_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_DRIVE_DOWNLOAD_URL = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

# Health Sync typically drops CSV files; adjust the q-filter for your naming convention.
_DRIVE_QUERY_BASE = "mimeType='text/csv' and trashed=false"
# Health Sync writes local wall-clock timestamps. This is a single-timezone
# app (#1600/#1603), so parsing them as anything else would shift every night.
SLEEP_CSV_TIMEZONE = "Asia/Bangkok"

_DRIVE_HEALTH_SYNC_FOLDER_ENV = "HEALTH_SYNC_DRIVE_FOLDER_ID"


@contextmanager
def _get_session():
    with Session(engine) as session:
        yield session


def _get_all_google_credential_user_ids() -> list:
    """Return list of user_id strings for all users with a Google OAuth credential row."""
    with _get_session() as session:
        rows = session.query(GoogleOAuthCredentials.user_id).all()
    return [str(row.user_id) for row in rows]


def list_drive_sleep_files(access_token: str, modified_after: Optional[datetime] = None) -> list:
    """List CSV files in the user's Health Sync Drive folder, optionally filtering by modifiedTime.

    Returns a list of Drive file metadata dicts (id, name, modifiedTime).
    Returns an empty list if the folder env var is not set or no files match.
    """
    import os

    folder_id = os.getenv(_DRIVE_HEALTH_SYNC_FOLDER_ENV, "")

    # Scoped or nothing. Unset, this used to fall back to a query matching EVERY
    # CSV in the user's Drive — tax returns, exports, anything — and hand each
    # one to the sleep parser. That was harmless only because the parser was a
    # stub returning []; now that it parses for real, an unscoped scan is a
    # privacy problem, so it is a hard stop instead of a silent wildcard.
    if not folder_id:
        _log.warning(
            "drive_sleep_sync: %s is not set — refusing to scan the whole Drive; "
            "set it to the Health Sync export folder to enable sleep import",
            _DRIVE_HEALTH_SYNC_FOLDER_ENV,
        )
        return []

    q = _DRIVE_QUERY_BASE + f" and '{folder_id}' in parents"
    if modified_after is not None:
        # RFC 3339 format required by Drive API
        ts = modified_after.strftime("%Y-%m-%dT%H:%M:%SZ")
        q += f" and modifiedTime > '{ts}'"

    params = {
        "q": q,
        "fields": "files(id,name,modifiedTime)",
        "orderBy": "modifiedTime desc",
        "pageSize": 100,
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    resp = _requests.get(_DRIVE_FILES_URL, params=params, headers=headers, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Drive API list error: {resp.status_code} {resp.text[:200]}")

    return resp.json().get("files", [])


def _download_drive_file(file_id: str, access_token: str) -> bytes:
    """Download raw file content from Google Drive."""
    url = _DRIVE_DOWNLOAD_URL.format(file_id=file_id)
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = _requests.get(url, headers=headers, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"Drive download error ({file_id}): {resp.status_code}")
    return resp.content


def parse_sleep_file_content(content_bytes: bytes, user_id) -> list:
    """Parse raw Health Sync CSV bytes into a list of sleep record dicts.

    Delegates to `services.health_sync.sleep_csv_parser.parse_sleep_csv`.

    This function used to be a stub returning `[]`, with a docstring reading
    "full parsing is implemented in Ticket 3". Ticket 3 is #1034 — and it WAS
    implemented, 340 lines of it, with 29 passing tests. It landed in the
    top-level `services/` package while this module lives in
    `backend/services/`, so the import was never made and every Drive sync
    imported nothing, silently, for months. The OAuth flow, the folder picker,
    the hourly scheduler and the first-connect backfill all worked; they just
    fed a function that threw the file away.

    Timestamps are parsed as Asia/Bangkok. There is no per-user timezone
    column — this is a single-timezone app (see #1600/#1603) — so passing
    anything else here would silently shift every sleep record.

    Returned rows are shaped for `upsert_sleep_records` below; the two were
    verified field-for-field before wiring:
        {
            "sleep_date": "YYYY-MM-DD",
            "start_at": "<ISO datetime>",
            "end_at": "<ISO datetime>",
            "total_sleep_minutes": int,
            "time_in_bed_minutes": int,
            "awake_minutes": int,
            "light_minutes": int,
            "deep_minutes": int,
            "rem_minutes": int,
            "sleep_score": int | None,
            "sleep_efficiency": float | None,
            "source": str,
            "device": str | None,
            "external_id": str,
        }
    """
    from services.health_sync.sleep_csv_parser import parse_sleep_csv

    if isinstance(content_bytes, (bytes, bytearray)):
        # errors="replace" rather than strict: one bad byte in a month of
        # exports should cost that row, not the whole file.
        text = content_bytes.decode("utf-8", errors="replace")
    else:
        text = str(content_bytes)

    result = parse_sleep_csv(text, user_id, user_timezone=SLEEP_CSV_TIMEZONE)

    # Unparseable rows are already skipped and described by the parser. Surface
    # them — a silent skip here is what this whole feature has been doing.
    for err in result.get("errors") or []:
        _log.warning("drive_sleep_sync: %s", err, extra={"user_id": str(user_id)})

    return result["rows"]


def upsert_sleep_records(user_id: str, records: list, session: Session) -> dict:
    """Upsert sleep records into sleep_records table, keyed on (user_id, external_id).

    Uses Postgres INSERT ... ON CONFLICT DO UPDATE so re-running is always safe.
    Determines new vs existing by checking which external_ids exist before inserting.

    Returns {"imported": int, "updated": int, "skipped": int}.
    """
    if not records:
        return {"imported": 0, "updated": 0, "skipped": 0}

    from sqlalchemy import select

    external_ids = [rec["external_id"] for rec in records]

    # Check which external_ids already exist for this user
    existing_ids = set()
    try:
        rows = session.execute(
            select(SleepRecord.external_id).where(
                SleepRecord.user_id == user_id,
                SleepRecord.external_id.in_(external_ids),
            )
        ).scalars().all()
        existing_ids = set(rows)
    except Exception:
        # Fallback for mock sessions: treat as all new
        pass

    imported = 0
    updated = 0
    skipped = 0
    now = datetime.now(tz=timezone.utc)

    for rec in records:
        ext_id = rec["external_id"]
        is_existing = ext_id in existing_ids

        stmt = (
            _pg_insert(SleepRecord)
            .values(
                user_id=user_id,
                sleep_date=rec["sleep_date"],
                start_at=rec["start_at"],
                end_at=rec["end_at"],
                total_sleep_minutes=rec["total_sleep_minutes"],
                time_in_bed_minutes=rec["time_in_bed_minutes"],
                awake_minutes=rec["awake_minutes"],
                light_minutes=rec["light_minutes"],
                deep_minutes=rec["deep_minutes"],
                rem_minutes=rec["rem_minutes"],
                sleep_score=rec.get("sleep_score"),
                sleep_efficiency=rec.get("sleep_efficiency"),
                source=rec.get("source", "health_sync_csv"),
                device=rec.get("device"),
                external_id=ext_id,
            )
            .on_conflict_do_update(
                constraint="uq_sleep_records_user_external_id",
                set_={
                    "sleep_date": rec["sleep_date"],
                    "start_at": rec["start_at"],
                    "end_at": rec["end_at"],
                    "total_sleep_minutes": rec["total_sleep_minutes"],
                    "time_in_bed_minutes": rec["time_in_bed_minutes"],
                    "awake_minutes": rec["awake_minutes"],
                    "light_minutes": rec["light_minutes"],
                    "deep_minutes": rec["deep_minutes"],
                    "rem_minutes": rec["rem_minutes"],
                    "sleep_score": rec.get("sleep_score"),
                    "sleep_efficiency": rec.get("sleep_efficiency"),
                    "source": rec.get("source", "health_sync_csv"),
                    "device": rec.get("device"),
                    "updated_at": now,
                },
            )
        )
        session.execute(stmt)

        if is_existing:
            updated += 1
        else:
            imported += 1

    return {"imported": imported, "updated": updated, "skipped": skipped}


def sync_drive_sleep_for_user(user_id: str) -> dict:
    """Run full Drive sleep sync pipeline for a single user.

    1. Refresh Google token if needed.
    2. List Drive CSV files modified after last_sync_at (if set).
    3. Parse each file (stub until Ticket 3).
    4. Upsert sleep records.
    5. Update last_sync_at on the credential row.

    Returns {"files_seen": int, "rows_imported": int, "rows_updated": int, "rows_skipped": int}.
    """
    with _get_session() as session:
        creds = (
            session.query(GoogleOAuthCredentials)
            .filter(GoogleOAuthCredentials.user_id == user_id)
            .one_or_none()
        )
        if creds is None:
            raise ValueError(f"No Google credentials for user {user_id}")

        last_sync_at = creds.last_sync_at

        access_token = refresh_token_if_needed(user_id)

        files = list_drive_sleep_files(access_token, modified_after=last_sync_at)
        files_seen = len(files)

        all_records = []
        for f in files:
            try:
                content = _download_drive_file(f["id"], access_token)
                parsed = parse_sleep_file_content(content, user_id)
                all_records.extend(parsed)
            except Exception as exc:
                _log.error(
                    "drive_sleep_sync: file parse error",
                    extra={"user_id": user_id, "file_id": f.get("id"), "error": str(exc)},
                )

        counts = upsert_sleep_records(user_id, all_records, session)
        session.commit()

        # Reachable, not merely implemented: without this, imported sleep never
        # reaches readiness, deficit_guard or habit_evidence, which all read
        # daily_metrics.sleep_hours. Best-effort — a merge failure must not
        # discard rows that were successfully imported above.
        try:
            merge_sleep_records_into_daily_metrics(user_id, session)
        except Exception as _merge_exc:  # pragma: no cover - defensive
            _log.warning(
                "drive_sleep_sync: daily_metrics merge failed",
                extra={"user_id": str(user_id), "error": str(_merge_exc)},
            )

        # Update last_sync_at
        creds = (
            session.query(GoogleOAuthCredentials)
            .filter(GoogleOAuthCredentials.user_id == user_id)
            .one_or_none()
        )
        if creds is not None:
            creds.last_sync_at = datetime.now(tz=timezone.utc)
            session.commit()

    return {
        "files_seen": files_seen,
        "rows_imported": counts["imported"],
        "rows_updated": counts["updated"],
        "rows_skipped": counts["skipped"],
    }


def backfill_drive_sleep_for_user(user_id: str) -> dict:
    """Process ALL sleep files in Drive for user_id, regardless of last_sync_at.

    Called once on first connect to import the full historical archive.
    Per-file errors are logged and skipped; processing continues for remaining files.

    Returns {"files_seen": int, "rows_imported": int, "rows_updated": int, "rows_skipped": int}.
    """
    with _get_session() as session:
        creds = (
            session.query(GoogleOAuthCredentials)
            .filter(GoogleOAuthCredentials.user_id == user_id)
            .one_or_none()
        )
        if creds is None:
            raise ValueError(f"No Google credentials for user {user_id}")

        access_token = refresh_token_if_needed(user_id)

        # No modified_after filter — enumerate every file in the folder.
        files = list_drive_sleep_files(access_token, modified_after=None)
        files_seen = len(files)

        all_records = []
        for f in files:
            try:
                content = _download_drive_file(f["id"], access_token)
                parsed = parse_sleep_file_content(content, user_id)
                all_records.extend(parsed)
            except Exception as exc:
                _log.error(
                    "drive_sleep_sync backfill: file error",
                    extra={"user_id": user_id, "file_id": f.get("id"), "error": str(exc)},
                )

        counts = upsert_sleep_records(user_id, all_records, session)
        session.commit()

        # Reachable, not merely implemented: without this, imported sleep never
        # reaches readiness, deficit_guard or habit_evidence, which all read
        # daily_metrics.sleep_hours. Best-effort — a merge failure must not
        # discard rows that were successfully imported above.
        try:
            merge_sleep_records_into_daily_metrics(user_id, session)
        except Exception as _merge_exc:  # pragma: no cover - defensive
            _log.warning(
                "drive_sleep_sync: daily_metrics merge failed",
                extra={"user_id": str(user_id), "error": str(_merge_exc)},
            )

    return {
        "files_seen": files_seen,
        "rows_imported": counts["imported"],
        "rows_updated": counts["updated"],
        "rows_skipped": counts["skipped"],
    }


def run_scheduled_sleep_sync() -> None:
    """Scheduled runner: sync Drive sleep files for every user with Google credentials.

    Called by the background scheduler thread in main.py. Errors for individual
    users are logged and swallowed so one failure never aborts the whole run.
    """
    user_ids = _get_all_google_credential_user_ids()
    _log.info("drive_sleep_sync: scheduled run starting", extra={"user_count": len(user_ids)})

    for uid in user_ids:
        try:
            result = sync_drive_sleep_for_user(uid)
            _log.info(
                "drive_sleep_sync: user sync complete",
                extra={"user_id": uid, **result},
            )
        except Exception as exc:
            _log.error(
                f"drive_sleep_sync: sync failed for user {uid}: {exc}",
                extra={"user_id": uid, "error": str(exc)},
                exc_info=True,
            )


# ── Merge into daily_metrics ──────────────────────────────────────────────────
#
# The piece that was genuinely missing. Everything downstream — readiness
# (main.py), deficit_guard's 7-day sleep average, habit_evidence's sleep metric,
# readiness_explanation's "sleep" factor — reads DailyMetric.sleep_hours, and
# NOTHING read sleep_records. So even a fully working Drive import would have
# left every one of those untouched.

def merge_sleep_records_into_daily_metrics(user_id, session: Session) -> dict:
    """Copy imported sleep durations onto daily_metrics.sleep_hours.

    Manual entry wins. A value the athlete typed is a deliberate statement about
    their night; an imported one is a device's guess, and silently overwriting
    the former with the latter would make the app argue with its user. So this
    only fills rows where sleep_hours IS NULL, and only creates a daily_metrics
    row when none exists for that date.

    Returns {"filled": int, "created": int, "skipped": int} — skipped counts
    dates that already had a manual value.
    """
    from backend.models import DailyMetric

    records = (
        session.query(SleepRecord)
        .filter(
            SleepRecord.user_id == user_id,
            SleepRecord.total_sleep_minutes.isnot(None),
        )
        .all()
    )
    if not records:
        return {"filled": 0, "created": 0, "skipped": 0}

    # One night per date. Health Sync can emit several rows for a fragmented
    # night; the longest is the one that represents the sleep.
    by_date: dict = {}
    for r in records:
        prev = by_date.get(r.sleep_date)
        if prev is None or (r.total_sleep_minutes or 0) > (prev.total_sleep_minutes or 0):
            by_date[r.sleep_date] = r

    existing = {
        m.metric_date: m
        for m in session.query(DailyMetric)
        .filter(
            DailyMetric.user_id == user_id,
            DailyMetric.metric_date.in_(list(by_date.keys())),
        )
        .all()
    }

    filled = created = skipped = 0
    for sleep_date, rec in by_date.items():
        hours = round((rec.total_sleep_minutes or 0) / 60.0, 1)
        row = existing.get(sleep_date)
        if row is None:
            session.add(DailyMetric(user_id=user_id, metric_date=sleep_date, sleep_hours=hours))
            created += 1
        elif row.sleep_hours is None:
            row.sleep_hours = hours
            filled += 1
        else:
            skipped += 1

    session.commit()
    _log.info(
        "drive_sleep_sync: merged sleep into daily_metrics",
        # NB: not "created" — logging.LogRecord already defines that attribute
        # and passing it via extra raises KeyError at emit time.
        extra={
            "user_id": str(user_id),
            "rows_filled": filled,
            "rows_created": created,
            "rows_skipped": skipped,
        },
    )
    return {"filled": filled, "created": created, "skipped": skipped}
