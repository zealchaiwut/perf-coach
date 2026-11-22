"""Issue #1904 — per-provider syncing / failed / ok for the v2 nav + Log pill."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from backend.services.sync_provider_status import (
    build_providers,
    job_is_live,
    provider_ui_state,
    _snapshot_running,
)

REPO = Path(__file__).resolve().parents[1]
CSS = (REPO / "frontend" / "css" / "revamp.css").read_text(encoding="utf-8")
STATUS_JS = (REPO / "frontend" / "js" / "v2-sync-status.js").read_text(encoding="utf-8")
TOOLBAR_JS = (REPO / "frontend" / "js" / "lib" / "v2-sync-toolbar.js").read_text(encoding="utf-8")
LOG_HTML = (REPO / "frontend" / "pages" / "v2-training-log.html").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def _connected_session():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = object()
    return session


def test_provider_ui_state_running_failed_ok():
    assert provider_ui_state({"connected": True, "running": True}, now=NOW) == "syncing"
    assert provider_ui_state(
        {"connected": True, "running": False, "last_error": "boom"}, now=NOW
    ) == "failed"
    assert provider_ui_state(
        {
            "connected": True,
            "running": False,
            "last_error": None,
            "last_success_at": (NOW - timedelta(hours=1)).isoformat(),
        },
        now=NOW,
    ) == "ok"


def test_provider_ui_state_stale_and_reauth():
    assert provider_ui_state(
        {
            "connected": True,
            "running": False,
            "last_error": None,
            "last_success_at": (NOW - timedelta(hours=72)).isoformat(),
        },
        now=NOW,
    ) == "stale"
    assert provider_ui_state(
        {"connected": True, "running": False, "needs_reauth": True}, now=NOW
    ) == "failed"
    assert provider_ui_state({"connected": False, "running": False}, now=NOW) == "failed"


def test_zombie_running_job_is_not_live():
    june = datetime(2026, 6, 27, 8, 20, tzinfo=timezone.utc)
    assert job_is_live(june, june, now=NOW) is False
    fresh = NOW - timedelta(minutes=5)
    assert job_is_live(fresh, fresh, now=NOW) is True
    assert job_is_live(None, None, now=NOW) is False


def test_snapshot_running_uses_phase():
    snap = {"status": "running", "phase": "pulling_strava"}
    assert _snapshot_running(snap, "strava") is True
    assert _snapshot_running(snap, "stryd") is False
    snap["phase"] = "pulling_stryd"
    assert _snapshot_running(snap, "stryd") is True
    assert _snapshot_running(snap, "strava") is False


@patch("backend.services.sync_provider_status._provider_running", return_value=False)
@patch("backend.services.sync_provider_status._last_completed", return_value=None)
@patch("backend.services.sync_provider_status._last_failed", return_value=None)
@patch("backend.services.sync_provider_status._pending_count", return_value=0)
def test_build_providers_running(_pending, _fail, _ok, _run):
    out = build_providers(
        _connected_session(),
        uuid4(),
        job_snapshot={"status": "running", "phase": "pulling_strava"},
    )
    assert out["strava"]["running"] is True
    assert out["stryd"]["running"] is False
    assert "needs_reauth" in out["strava"]
    assert provider_ui_state(out["strava"], now=NOW) == "syncing"


@patch("backend.services.sync_provider_status._provider_running", return_value=False)
@patch("backend.services.sync_provider_status._pending_count", return_value=0)
def test_build_providers_failed(_pending, _run):
    fail = MagicMock()
    fail.error_message = "token expired"
    fail.completed_at = NOW
    fail.created_at = NOW
    with patch("backend.services.sync_provider_status._last_completed", return_value=None), patch(
        "backend.services.sync_provider_status._last_failed", return_value=fail
    ):
        out = build_providers(_connected_session(), uuid4(), job_snapshot={"status": "idle"})
    assert out["strava"]["last_error"] == "token expired"
    assert out["strava"]["running"] is False
    assert provider_ui_state(out["strava"], now=NOW) == "failed"


@patch("backend.services.sync_provider_status._provider_running", return_value=False)
@patch("backend.services.sync_provider_status._last_failed", return_value=None)
@patch("backend.services.sync_provider_status._pending_count", return_value=0)
def test_build_providers_ok(_pending, _fail, _run):
    ok = MagicMock()
    ok.completed_at = NOW - timedelta(minutes=20)
    with patch("backend.services.sync_provider_status._last_completed", return_value=ok):
        out = build_providers(_connected_session(), uuid4())
    assert out["strava"]["last_error"] is None
    assert out["strava"]["running"] is False
    assert out["strava"]["last_success_at"]
    assert provider_ui_state(out["strava"], now=NOW) == "ok"


def test_nav_has_syncing_class():
    assert "rv-sync-dot--syncing" in CSS
    assert "rv-sync-dot--syncing" in STATUS_JS
    assert "background: #3b6fe0" in CSS
    assert "prefers-reduced-motion" in CSS
    assert "sr-only" in STATUS_JS
    assert "sr-only" in CSS


def test_status_module_polls_and_emits():
    assert 'fetch("/api/sync/status"' in STATUS_JS
    assert "rv:sync-status" in STATUS_JS
    assert "var FAST_MS = 3000" in STATUS_JS
    assert "var SLOW_MS = 60000" in STATUS_JS
    assert "visibilitychange" in STATUS_JS
    assert "document.hidden" in STATUS_JS


def test_log_page_loads_status_module_and_pill_markup():
    assert "v2-sync-status.js" in LOG_HTML
    assert "rv-sync-pill--syncing" in TOOLBAR_JS
    assert "rv-sync-pill--failed" in TOOLBAR_JS
    assert "rv-sync-pill--stale" in TOOLBAR_JS
    assert "Log a strength session" in TOOLBAR_JS
    assert "Syncing " in TOOLBAR_JS
    assert "Stryd needs reconnecting" in TOOLBAR_JS
    assert "last synced " in TOOLBAR_JS
    assert "/v2/settings#integrations" in TOOLBAR_JS
    assert "onRefresh" in TOOLBAR_JS
    assert "/api/strava/sync" in TOOLBAR_JS
    assert "/api/stryd/sync" in TOOLBAR_JS
    assert "v2-sync-panel" in TOOLBAR_JS
    assert "v2-sync-btn-stryd" in TOOLBAR_JS
    assert "aria-controls=\"v2-sync-panel\"" in TOOLBAR_JS
    assert "rv-sync-panel" in CSS
    assert "rv-sync-row-btn" in CSS


def test_stale_sync_is_named_not_all_synced():
    assert "tap to sync" in STATUS_JS
    assert "days ago" in STATUS_JS
    assert "rv-sync-dot-label" in STATUS_JS
    assert "rv-sync-pill--stale" in CSS
    detail = (REPO / "frontend" / "js" / "lib" / "run-detail-view.js").read_text(encoding="utf-8")
    assert "No Stryd on this session" in detail
    assert "No Stryd data on this session" in detail
