"""Phase C — fail-closed thin dyno (sync/export, streams=none, Log window)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAIN = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
COACH = (REPO / "backend" / "routers" / "coach.py").read_text(encoding="utf-8")
NAV = (REPO / "frontend" / "js" / "nav.js").read_text(encoding="utf-8")
LOG = (REPO / "frontend" / "js" / "training-log.js").read_text(encoding="utf-8")


def test_incremental_sync_fail_closed_on_worker_unavailable():
    i = MAIN.find("def _maybe_delegate_incremental")
    assert i >= 0
    chunk = MAIN[i : i + 1200]
    assert "WorkerUnavailable" in chunk
    assert "status_code=503" in chunk
    assert "return None  # http mode" not in chunk


def test_inline_coach_export_rejected_when_queue_enabled():
    assert "def _reject_inline_coach_export_if_queued" in COACH
    assert "_reject_inline_coach_export_if_queued()" in COACH


def test_nav_only_inlines_when_queue_disabled_detail():
    assert "queue disabled" in NAV
    assert "export queue unavailable" in NAV


def test_workout_full_streams_none_skips_activity_stream_hydrate():
    i = MAIN.find("def get_workout_full")
    assert i >= 0
    chunk = MAIN[i : i + 9000]
    assert 'if streams == "none":' in chunk
    assert "_prebuilt_streams = {}" in chunk
    assert 'elif streams == "none":' in chunk
    assert "do not touch deferred streams_payload" in chunk


def test_log_window_is_twelve_months_not_full_history_jump():
    assert "LOG_WINDOW_MONTHS = 12" in LOG
    assert 'loadFullHistory ? "2010-01-01"' not in LOG
    assert 'params.set(\n      "from",\n      loadFullHistory' not in LOG
    assert 'params.set("from", isoMonthsAgo(_logWindowMonths))' in LOG
    assert "function fetchAndRender(extendOlder)" in LOG
