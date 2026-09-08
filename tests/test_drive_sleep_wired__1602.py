"""The sleep import is connected to the parser that was already written — #1602.

The dominant defect class in this codebase is "built, tested, never called."
This feature is its purest instance, three tickets deep:

    #1032  sleep_records table + migration          built, tested
    #1033  DriveSleepConnection model               built
    #1034  services/health_sync/sleep_csv_parser.py built, 29 tests passing —
           340 lines: CSV parse, duration/timestamp helpers, external_id
           derivation, DB upsert, Drive token refresh, Drive fetch, and a full
           import_sleep_csv_for_user orchestrator
    #1035  backend/services/drive_sleep_sync.py     a STUB that returned []

#1035's `parse_sleep_file_content` carried the docstring "This is a stub — full
parsing is implemented in Ticket 3." Ticket 3 IS #1034, and it had been
implemented. It landed in the top-level `services/` package while #1035 lived in
`backend/services/`; the import was never written, and so a complete OAuth flow,
folder picker, hourly scheduler and first-connect backfill all fed a function
that threw every file away. Silently, for months.

The reachability audit that produced #1602 nearly deleted the whole feature —
the recommendation was "remove the integration and the table", on the reading
that the parser did not exist. It did.

## What was actually missing

One thing, and not the parser: nothing merged `sleep_records` into
`daily_metrics.sleep_hours`. Readiness, `deficit_guard`'s 7-day sleep average,
`habit_evidence`'s sleep metric and `readiness_explanation`'s "sleep" factor all
read `daily_metrics`; none of them has ever read `sleep_records`. So even a
perfectly working import would have changed nothing an athlete could see.
"""
from __future__ import annotations

import datetime
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[1]


# ── The stub is gone ──────────────────────────────────────────────────────────

def test_parser_is_no_longer_a_stub():
    from backend.services import drive_sleep_sync as dss

    src = inspect.getsource(dss.parse_sleep_file_content)
    assert "return []" not in src.split('"""')[-1], "parse_sleep_file_content still returns []"
    assert "parse_sleep_csv" in src


def test_it_calls_the_parser_that_already_existed():
    """Rather than a second implementation. A fourth copy of CSV parsing is how
    this codebase got here."""
    from backend.services import drive_sleep_sync as dss

    src = inspect.getsource(dss.parse_sleep_file_content)
    assert "from services.health_sync.sleep_csv_parser import parse_sleep_csv" in src


def test_the_orphaned_parser_still_passes_its_own_tests():
    """If #1034's module is ever moved or renamed, this is the tripwire — the
    cross-package import is exactly what failed the first time."""
    from services.health_sync.sleep_csv_parser import (
        parse_sleep_csv,
        upsert_parsed_sleep_rows,
    )

    assert callable(parse_sleep_csv)
    assert callable(upsert_parsed_sleep_rows)


def test_real_csv_bytes_produce_real_rows():
    """End-to-end through the previously-stubbed function: bytes in, rows out."""
    from backend.services.drive_sleep_sync import parse_sleep_file_content

    # The real Health Sync column set, taken from #1034's own fixture — the
    # required duration column is "Sleep Duration", not "Duration".
    csv = (
        "Start,End,Sleep Duration,Deep Sleep,REM Sleep,Light Sleep,Awake Time\n"
        "2026-07-20 23:15:00,2026-07-21 07:05:00,07:20:00,01:30:00,01:40:00,04:10:00,00:30:00\n"
    ).encode("utf-8")
    rows = parse_sleep_file_content(csv, "11111111-1111-1111-1111-111111111111")
    assert len(rows) == 1
    row = rows[0]
    assert row["total_sleep_minutes"] == 440
    assert row["source"] == "health_sync_csv"
    assert row["external_id"]


def test_bad_bytes_cost_one_row_not_the_file():
    from backend.services.drive_sleep_sync import parse_sleep_file_content

    csv = (
        b"Start,End,Sleep Duration,Deep Sleep,REM Sleep,Light Sleep,Awake Time\n"
        b"\xff\xfe garbage row,,,,,,\n"
        b"2026-07-20 23:15:00,2026-07-21 07:05:00,07:20:00,01:30:00,01:40:00,04:10:00,00:30:00\n"
    )
    rows = parse_sleep_file_content(csv, "11111111-1111-1111-1111-111111111111")
    assert len(rows) == 1, "a single undecodable row should not lose the whole file"


def test_timestamps_are_parsed_as_bangkok():
    """There is no per-user timezone column — this is a single-timezone app
    (#1600/#1603). Parsing Health Sync's local wall-clock as anything else would
    shift every night silently."""
    from backend.services import drive_sleep_sync as dss

    assert dss.SLEEP_CSV_TIMEZONE == "Asia/Bangkok"
    assert "SLEEP_CSV_TIMEZONE" in inspect.getsource(dss.parse_sleep_file_content)


# ── The merge — the piece that was genuinely absent ───────────────────────────

def test_merge_function_exists_and_is_called_by_both_sync_paths():
    """Reachability is the point of this ticket. An implemented merge with no
    caller would be the same bug in a new place."""
    from backend.services import drive_sleep_sync as dss

    assert hasattr(dss, "merge_sleep_records_into_daily_metrics")
    for fn in (dss.sync_drive_sleep_for_user, dss.backfill_drive_sleep_for_user):
        assert "merge_sleep_records_into_daily_metrics" in inspect.getsource(fn), (
            f"{fn.__name__} imports sleep but never merges it into daily_metrics"
        )


def test_nothing_downstream_reads_sleep_records_directly():
    """Why the merge is required at all: every consumer reads daily_metrics.
    If that ever changes, this test should be revisited rather than deleted."""
    consumers = [
        REPO / "backend" / "services" / "deficit_guard.py",
        REPO / "backend" / "services" / "habit_evidence.py",
        REPO / "backend" / "services" / "readiness_explanation.py",
    ]
    for path in consumers:
        src = path.read_text()
        assert "SleepRecord" not in src, f"{path.name} now reads sleep_records directly"


def _rec(date_, minutes):
    r = MagicMock()
    r.sleep_date = date_
    r.total_sleep_minutes = minutes
    return r


def test_merge_fills_only_empty_nights(monkeypatch):
    """Manual entry wins. A typed value is a deliberate statement about the
    night; an imported one is a device's guess. Overwriting the former with the
    latter makes the app argue with its user."""
    from backend.services import drive_sleep_sync as dss

    d1, d2 = datetime.date(2026, 7, 20), datetime.date(2026, 7, 21)
    manual = MagicMock(metric_date=d1, sleep_hours=6.0)   # already answered
    empty = MagicMock(metric_date=d2, sleep_hours=None)   # gap to fill

    session = MagicMock()
    q = session.query.return_value.filter.return_value
    q.all.side_effect = [[_rec(d1, 480), _rec(d2, 420)], [manual, empty]]

    out = dss.merge_sleep_records_into_daily_metrics("u", session)

    assert manual.sleep_hours == 6.0, "a manually entered night was overwritten"
    assert empty.sleep_hours == 7.0
    assert out == {"filled": 1, "created": 0, "skipped": 1}


def test_merge_creates_a_row_when_the_date_has_none(monkeypatch):
    from backend.services import drive_sleep_sync as dss

    d = datetime.date(2026, 7, 20)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.side_effect = [[_rec(d, 465)], []]

    out = dss.merge_sleep_records_into_daily_metrics("u", session)
    assert out == {"filled": 0, "created": 1, "skipped": 0}
    session.add.assert_called_once()


def test_a_fragmented_night_collapses_to_its_longest_segment(monkeypatch):
    """Health Sync emits several rows for a broken night. Summing them would
    over-report; taking the last would be arbitrary."""
    from backend.services import drive_sleep_sync as dss

    d = datetime.date(2026, 7, 20)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.side_effect = [
        [_rec(d, 60), _rec(d, 400), _rec(d, 120)], []
    ]
    dss.merge_sleep_records_into_daily_metrics("u", session)
    created = session.add.call_args[0][0]
    assert float(created.sleep_hours) == pytest.approx(400 / 60, abs=0.05)


def test_no_records_is_not_an_error(monkeypatch):
    from backend.services import drive_sleep_sync as dss

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    assert dss.merge_sleep_records_into_daily_metrics("u", session) == {
        "filled": 0, "created": 0, "skipped": 0
    }


def test_merge_failure_does_not_discard_imported_rows():
    """The import is the expensive part — a network round trip per file. A
    merge bug must not throw that away."""
    from backend.services import drive_sleep_sync as dss

    src = inspect.getsource(dss.sync_drive_sleep_for_user)
    block = src[src.index("merge_sleep_records_into_daily_metrics") - 300:]
    assert "except Exception" in block


# ── The Drive scan is scoped ──────────────────────────────────────────────────

def test_unset_folder_id_refuses_to_scan_rather_than_matching_every_csv(monkeypatch, caplog):
    """Previously an unset HEALTH_SYNC_DRIVE_FOLDER_ID fell through to a query
    matching EVERY CSV in the user's Drive. That was harmless only while the
    parser was a stub; now that it parses for real, it is a privacy problem."""
    from backend.services import drive_sleep_sync as dss

    monkeypatch.delenv("HEALTH_SYNC_DRIVE_FOLDER_ID", raising=False)
    assert dss.list_drive_sleep_files("token") == []


def test_the_env_var_is_documented():
    """It was undocumented, which is how it came to be unset in the first
    place."""
    assert "HEALTH_SYNC_DRIVE_FOLDER_ID" in (REPO / ".env.example").read_text()
