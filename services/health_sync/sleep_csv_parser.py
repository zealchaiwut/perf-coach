"""
Health Sync sleep CSV parser.

Reads CSVs exported by the Health Sync Android app from Google Drive,
maps columns to the sleep_records schema, and upserts rows idempotently.

Column mapping (Health Sync → sleep_records):
  Start          → start_at
  End            → end_at
  Sleep Duration → total_sleep_minutes
  Deep Sleep     → deep_minutes        (optional, NULL when blank)
  REM Sleep      → rem_minutes         (optional, NULL when blank)
  Light Sleep    → light_minutes       (optional, NULL when blank)
  Awake Time     → awake_minutes       (optional, NULL when blank)
  Heart Rate     → ignored (no schema column)
  SpO2           → ignored (no schema column)

time_in_bed_minutes is derived as (end_at − start_at) in minutes.
external_id      → SHA-256("{user_id}:{sleep_date}:{start_at.isoformat()}")
source           → "health_sync_csv"
"""
import csv
import hashlib
import io
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests as _requests
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.models import SleepRecord

logger = logging.getLogger(__name__)

_SOURCE = "health_sync_csv"

# Google Drive API base URL for listing / downloading files
_DRIVE_API = "https://www.googleapis.com/drive/v3"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


# ── Duration helpers ──────────────────────────────────────────────────────────

def _duration_to_minutes(val: str) -> Optional[int]:
    """Parse 'HH:MM:SS' or 'H:MM:SS' or 'HH:MM' into integer minutes.

    Returns None if val is blank or unparseable.
    """
    if not val or not val.strip():
        return None
    parts = val.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return h * 60 + m + (1 if s >= 30 else 0)
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1])
            return h * 60 + m
    except ValueError:
        pass
    return None


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def _parse_ts(val: str, tz: ZoneInfo) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD HH:MM:SS' in the given local timezone.

    Returns None if val is blank or unparseable.
    """
    if not val or not val.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            naive = datetime.strptime(val.strip(), fmt)
            return naive.replace(tzinfo=tz)
        except ValueError:
            continue
    return None


# ── external_id derivation ────────────────────────────────────────────────────

def _derive_external_id(user_id: Any, sleep_date: Any, start_at: datetime) -> str:
    raw = f"{user_id}:{sleep_date.isoformat()}:{start_at.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Row parser ────────────────────────────────────────────────────────────────

def _parse_row(row: dict, user_id: Any, tz: ZoneInfo) -> Optional[dict]:
    """Convert a raw CSV row dict into a sleep_records-ready dict.

    Returns None and logs a warning if the row is malformed (missing required fields).
    """
    start_at = _parse_ts(row.get("Start", ""), tz)
    end_at = _parse_ts(row.get("End", ""), tz)

    if start_at is None:
        return None
    if end_at is None:
        return None

    total_val = _duration_to_minutes(row.get("Sleep Duration", ""))
    if total_val is None:
        return None

    time_in_bed = int((end_at - start_at).total_seconds() / 60)
    sleep_date = start_at.date()

    return {
        "user_id": user_id,
        "sleep_date": sleep_date,
        "start_at": start_at,
        "end_at": end_at,
        "total_sleep_minutes": total_val,
        "time_in_bed_minutes": time_in_bed,
        "awake_minutes": _duration_to_minutes(row.get("Awake Time", "")),
        "deep_minutes": _duration_to_minutes(row.get("Deep Sleep", "")),
        "rem_minutes": _duration_to_minutes(row.get("REM Sleep", "")),
        "light_minutes": _duration_to_minutes(row.get("Light Sleep", "")),
        "sleep_score": None,
        "sleep_efficiency": None,
        "device": None,
        "source": _SOURCE,
        "external_id": _derive_external_id(user_id, sleep_date, start_at),
    }


# ── Main parse function ───────────────────────────────────────────────────────

def parse_sleep_csv(
    content: str,
    user_id: Any,
    user_timezone: str = "UTC",
) -> dict:
    """Parse a Health Sync sleep CSV string.

    Args:
        content:        Raw CSV text (header + data rows).
        user_id:        UUID of the user who owns these records.
        user_timezone:  IANA timezone name (e.g. 'Asia/Bangkok'). Timestamps in
                        the CSV are treated as local to this timezone.

    Returns a dict with keys:
        rows      – list of dicts ready to pass to upsert_parsed_sleep_rows
        inserted  – always 0 (no DB write happens here)
        updated   – always 0
        skipped   – count of rows that were unparseable / missing required fields
        errors    – list of human-readable error strings for skipped rows
    """
    try:
        tz = ZoneInfo(user_timezone)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone %r — falling back to UTC", user_timezone)
        tz = ZoneInfo("UTC")

    reader = csv.DictReader(io.StringIO(content))
    rows = []
    skipped = 0
    errors = []

    for line_no, raw_row in enumerate(reader, start=2):
        parsed = _parse_row(raw_row, user_id, tz)
        if parsed is None:
            skipped += 1
            start_val = raw_row.get("Start", "<missing>") or "<empty>"
            errors.append(f"Row {line_no}: skipped — unparseable or missing required field (Start={start_val!r})")
            logger.warning("Skipping CSV row %d: %r", line_no, raw_row)
        else:
            rows.append(parsed)

    return {
        "rows": rows,
        "inserted": 0,
        "updated": 0,
        "skipped": skipped,
        "errors": errors,
    }


# ── DB upsert ─────────────────────────────────────────────────────────────────

def upsert_parsed_sleep_rows(rows: list, session: Session) -> dict:
    """Upsert parsed sleep rows into sleep_records via (user_id, external_id) conflict key.

    Renamed from upsert_sleep_records (issue #1065) to avoid a naming collision with
    drive_sleep_sync.upsert_sleep_records, which takes an incompatible (user_id, records, session)
    signature.

    Args:
        rows:    Output of parse_sleep_csv()["rows"].
        session: An active SQLAlchemy Session (caller commits).

    Returns dict with inserted and updated counts.
    """
    if not rows:
        return {"inserted": 0, "updated": 0}

    inserted = 0
    updated = 0

    for row in rows:
        stmt = (
            _pg_insert(SleepRecord)
            .values(**row)
            .on_conflict_do_update(
                constraint="uq_sleep_records_user_external_id",
                set_={
                    "sleep_date": row["sleep_date"],
                    "start_at": row["start_at"],
                    "end_at": row["end_at"],
                    "total_sleep_minutes": row["total_sleep_minutes"],
                    "time_in_bed_minutes": row["time_in_bed_minutes"],
                    "awake_minutes": row["awake_minutes"],
                    "deep_minutes": row["deep_minutes"],
                    "rem_minutes": row["rem_minutes"],
                    "light_minutes": row["light_minutes"],
                    "sleep_score": row["sleep_score"],
                    "sleep_efficiency": row["sleep_efficiency"],
                    "device": row["device"],
                    "source": row["source"],
                    "updated_at": datetime.now(tz=timezone.utc),
                },
            )
        )
        result = session.execute(stmt)
        # rowcount=1 for insert, rowcount=1 for update (postgres returns 1 either way)
        # Use inserted_primary_key to distinguish: insert returns new pk, update returns None
        if result.inserted_primary_key:
            inserted += 1
        else:
            updated += 1

    return {"inserted": inserted, "updated": updated}


# ── Drive integration ─────────────────────────────────────────────────────────

def _refresh_drive_token(encrypted_refresh_token: str) -> str:
    """Exchange an encrypted refresh token for a fresh Drive access token."""
    from backend.services.crypto import decrypt_value
    refresh_token = decrypt_value(encrypted_refresh_token)

    resp = _requests.post(
        _GOOGLE_TOKEN_URL,
        data={
            "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_latest_sleep_csv_from_drive(folder_id: str, access_token: str) -> Optional[str]:
    """Download the most recently modified CSV from a Google Drive folder.

    Returns the CSV content as a string, or None if no CSV files are found.
    """
    list_resp = _requests.get(
        f"{_DRIVE_API}/files",
        params={
            "q": f"'{folder_id}' in parents and mimeType='text/csv' and trashed=false",
            "orderBy": "modifiedTime desc",
            "pageSize": 1,
            "fields": "files(id,name,modifiedTime)",
        },
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    list_resp.raise_for_status()
    files = list_resp.json().get("files", [])

    if not files:
        logger.info("No CSV files found in Drive folder %s", folder_id)
        return None

    file_id = files[0]["id"]
    logger.info("Downloading %s (id=%s) from Drive folder %s", files[0]["name"], file_id, folder_id)

    dl_resp = _requests.get(
        f"{_DRIVE_API}/files/{file_id}",
        params={"alt": "media"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    dl_resp.raise_for_status()
    return dl_resp.text


def import_sleep_csv_for_user(user_id: Any, session: Session, user_timezone: str = "UTC") -> dict:
    """Full orchestrator: fetch CSV from Drive, parse it, upsert into sleep_records.

    Looks up the user's DriveSleepConnection to get folder_id and encrypted token.

    Returns the combined parse + upsert result:
        { inserted, updated, skipped, errors, rows }
    """
    try:
        from backend.models import DriveSleepConnection
    except ImportError:
        raise RuntimeError(
            "DriveSleepConnection model not available — "
            "ensure issue #1033 is merged before calling this function"
        )

    conn = (
        session.query(DriveSleepConnection)
        .filter(DriveSleepConnection.user_id == user_id)
        .one_or_none()
    )
    if conn is None or conn.status != "connected":
        raise ValueError(f"No active Drive connection for user {user_id}")
    if not conn.folder_id:
        raise ValueError(f"No folder_id set for user {user_id}")
    if not conn.refresh_token_encrypted:
        raise ValueError(f"No refresh token stored for user {user_id}")

    access_token = _refresh_drive_token(conn.refresh_token_encrypted)
    csv_content = fetch_latest_sleep_csv_from_drive(conn.folder_id, access_token)

    if csv_content is None:
        return {"inserted": 0, "updated": 0, "skipped": 0, "errors": ["No CSV found in Drive folder"], "rows": []}

    parse_result = parse_sleep_csv(csv_content, user_id, user_timezone)
    upsert_result = upsert_parsed_sleep_rows(parse_result["rows"], session)

    conn.last_sync_at = datetime.now(tz=timezone.utc)

    return {
        "inserted": upsert_result["inserted"],
        "updated": upsert_result["updated"],
        "skipped": parse_result["skipped"],
        "errors": parse_result["errors"],
        "rows": parse_result["rows"],
    }
