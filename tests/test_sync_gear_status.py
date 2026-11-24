"""Settings-gear sync ring: overall / ui_state fixtures and nav markup."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.services.sync_provider_status import decorate_sync_status, nav_ui_state

REPO = Path(__file__).resolve().parents[1]
NAV = (REPO / "frontend" / "js" / "v2-nav.js").read_text(encoding="utf-8")
STATUS = (REPO / "frontend" / "js" / "v2-sync-status.js").read_text(encoding="utf-8")
CSS = (REPO / "frontend" / "css" / "revamp.css").read_text(encoding="utf-8")
TOOLBAR = (REPO / "frontend" / "js" / "lib" / "v2-sync-toolbar.js").read_text(encoding="utf-8")

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)  # 19:00 BKK


def _ok(**extra):
    row = {
        "connected": True,
        "running": False,
        "needs_reauth": False,
        "last_error": None,
        "last_success_at": (NOW - timedelta(hours=1)).isoformat(),
    }
    row.update(extra)
    return row


def _decorate(strava, stryd, status="idle"):
    return decorate_sync_status(
        {"status": status, "providers": {"strava": strava, "stryd": stryd}},
        now=NOW,
    )


def test_all_ok_is_green_with_clock():
    out = _decorate(_ok(), _ok())
    assert out["overall"] == "ok"
    assert out["providers"]["strava"]["ui_state"] == "ok"
    assert out["providers"]["strava"]["ui_action"] is None
    assert out["providers"]["strava"]["ui_label"] == "18:00"
    assert out["overall_label"].startswith("Settings · all synced")


def test_one_syncing():
    out = _decorate(_ok(running=True), _ok())
    assert out["overall"] == "syncing"
    assert out["providers"]["strava"]["ui_state"] == "syncing"
    assert out["providers"]["strava"]["ui_label"] == "Syncing…"
    assert out["providers"]["strava"]["ui_action"] is None
    assert out["overall_label"] == "Settings · syncing"


def test_stryd_reauth_is_attention():
    out = _decorate(_ok(), _ok(needs_reauth=True, last_error="unauthorized"))
    assert nav_ui_state(out["providers"]["stryd"], now=NOW) == "attention"
    assert out["overall"] == "attention"
    assert out["providers"]["stryd"]["ui_state"] == "attention"
    assert out["providers"]["stryd"]["ui_action"] == "reauth"
    assert out["providers"]["stryd"]["ui_label"] == "Sign in again"
    assert "Stryd needs your password" in out["overall_label"]


def test_strava_error_is_failed_retry():
    out = _decorate(_ok(last_error="token expired", last_success_at=None), _ok())
    assert out["overall"] == "failed"
    assert out["providers"]["strava"]["ui_state"] == "failed"
    assert out["providers"]["strava"]["ui_action"] == "retry"
    assert out["providers"]["strava"]["ui_label"] == "Retry"
    assert "Strava sync failed" in out["overall_label"]


def test_strava_not_connected_is_failed_reconnect():
    out = _decorate(
        {"connected": False, "running": False, "needs_reauth": False, "last_error": None, "last_success_at": None},
        _ok(),
    )
    assert out["overall"] == "failed"
    assert out["providers"]["strava"]["ui_state"] == "failed"
    assert out["providers"]["strava"]["ui_action"] == "reconnect"
    assert out["providers"]["strava"]["ui_label"] == "Reconnect"
    assert "Strava not connected" in out["overall_label"]


def test_last_success_over_48h_is_attention():
    stale = _ok(last_success_at=(NOW - timedelta(hours=72)).isoformat())
    out = _decorate(stale, _ok())
    assert out["overall"] == "attention"
    assert out["providers"]["strava"]["ui_state"] == "attention"
    assert out["providers"]["strava"]["ui_action"] is None
    assert out["providers"]["strava"]["ui_label"]  # still a clock / date
    assert "needs attention" in out["overall_label"]


def test_js_has_no_colour_or_state_logic():
    assert "function dotFromProvider" not in STATUS
    assert "function worstDot" not in STATUS
    assert "function dotFromProvider" not in NAV
    assert "function worstDot" not in NAV
    assert "rv-sync-dot-link" not in NAV
    assert "rv-sync-dot-label" not in STATUS
    assert "ageH >= 48" not in STATUS
    assert "ageH >= 48" not in NAV


def test_nav_is_gear_not_dot():
    assert 'id="rv-sync-gear"' in NAV
    assert "rv-sync-gear" in CSS
    assert "aria-haspopup=\"dialog\"" in NAV
    assert "rv-settings-label" not in NAV
    assert "box-shadow: inset 0 0 0 2px #4ade80" in CSS
    assert "box-shadow: inset 0 0 0 2px #fbbf24" in CSS
    assert "box-shadow: inset 0 0 0 2px #f87171" in CSS
    assert ".rv-tab.rv-sync-gear--attention" in CSS
    assert ".rv-tab.rv-sync-gear--failed" in CSS
    assert ".rv-tab.rv-sync-gear--syncing" in CSS
    assert "#93c5fd" in CSS
    assert "width: 36px" in CSS
    assert ".rv-settings-gear {\n  width: 18px;\n  height: 18px;\n  display: block;" in CSS or (
        "width: 18px" in CSS and "height: 18px" in CSS and "display: block" in CSS
    )


def test_route_decorates_status():
    main = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
    assert "_decorate_sync_status(out)" in main


def test_popover_contract():
    assert 'aria-label", "Sync status and settings"' in STATUS
    assert "Sync now" in STATUS
    assert "Settings \\u203a" in STATUS or "Settings \u203a" in STATUS
    assert "/v2/settings#integrations" in STATUS
    assert "data-sync-retry" in STATUS
    assert "startAll" in STATUS
    assert "startSync" in STATUS
    assert "V2SyncStatus.startSync" in TOOLBAR
    assert "var FAST_MS = 5000" in STATUS
    assert "var SLOW_MS = 60000" in STATUS
    assert 'ev.key === "Escape"' in STATUS
    assert "max-width: 280px" in CSS
    assert "left: 16px !important" in CSS
