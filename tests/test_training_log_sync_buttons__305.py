"""Tests for issue #305: Training Log sync buttons wired to background sync and status bar."""
import pathlib
import re

_ROOT = pathlib.Path(__file__).parent.parent
JS = (_ROOT / "frontend" / "js" / "training-log.js").read_text()
HTML = (_ROOT / "frontend" / "pages" / "training-log.html").read_text()


# ── AC1: Sync Strava POSTs to /api/strava/sync ────────────────────────────────

def test_strava_sync_endpoint_called():
    assert "/api/strava/sync" in JS


def test_strava_sync_uses_post():
    idx = JS.index("/api/strava/sync")
    snippet = JS[max(0, idx - 200): idx + 50]
    assert "POST" in snippet


# ── AC2: 202 triggers syncBarRefresh ─────────────────────────────────────────

def test_202_calls_sync_bar_refresh():
    idx = JS.index("202")
    snippet = JS[idx: idx + 200]
    assert "syncBarRefresh" in snippet


# ── AC3: 409 triggers syncBarRefresh, no error ───────────────────────────────

def test_409_and_202_share_same_branch():
    """Both 202 and 409 should be in the same condition — no separate error for 409."""
    idx = JS.index("202")
    snippet = JS[idx: idx + 100]
    assert "409" in snippet


def test_no_error_display_on_409():
    """No alert() or error element shown — 409 handled silently (status bar only)."""
    # Check there's no alert() in the sync click handler
    handler_idx = JS.index("_onSyncStravaClick")
    handler_body = JS[handler_idx: handler_idx + 500]
    assert "alert(" not in handler_body


# ── AC4: Buttons disabled while sync is running ──────────────────────────────

def test_set_busy_disables_strava_button():
    assert "_syncSetBusy" in JS
    idx = JS.index("_syncSetBusy")
    # Find the function body
    fn_idx = JS.index("function _syncSetBusy")
    fn_body = JS[fn_idx: fn_idx + 200]
    assert "disabled" in fn_body
    assert "sync-strava-btn" in fn_body


def test_poll_status_calls_set_busy_true_on_running():
    fn_idx = JS.index("function _syncPollStatus")
    fn_body = JS[fn_idx: fn_idx + 400]
    assert "running" in fn_body
    assert "_syncSetBusy(true)" in fn_body


def test_stryd_button_disabled_in_html():
    assert 'id="sync-stryd-btn"' in HTML
    idx = HTML.index('id="sync-stryd-btn"')
    snippet = HTML[idx: idx + 150]
    assert "disabled" in snippet


# ── AC5: Buttons re-enable when idle/finished ────────────────────────────────

def test_poll_status_calls_set_busy_false_on_idle():
    fn_idx = JS.index("function _syncPollStatus")
    fn_body = JS[fn_idx: fn_idx + 500]
    assert "_syncSetBusy(false)" in fn_body


def test_poll_timer_stopped_on_idle():
    fn_idx = JS.index("function _syncPollStatus")
    fn_body = JS[fn_idx: fn_idx + 500]
    assert "_syncStopStatusPoll" in fn_body


# ── AC6: No inline feedback span in HTML ─────────────────────────────────────

def test_no_inline_sync_feedback_span():
    """Old 'Synced N activities' feedback span must not be present."""
    assert "synced" not in HTML.lower() or "Synced" not in HTML


def test_no_sync_feedback_id_in_html():
    assert "sync-feedback" not in HTML
    assert "sync-result" not in HTML


# ── AC7: Stryd coming-soon visual state ──────────────────────────────────────

def test_stryd_has_coming_soon_class():
    idx = HTML.index('id="sync-stryd-btn"')
    snippet = HTML[idx: idx + 150]
    assert "btn-coming-soon" in snippet


def test_coming_soon_badge_css_defined():
    assert ".btn-coming-soon" in HTML
    assert "::after" in HTML or "content:" in HTML


def test_stryd_title_attribute():
    idx = HTML.index('id="sync-stryd-btn"')
    snippet = HTML[idx: idx + 150]
    assert "coming soon" in snippet.lower()


# ── AC8: No layout regressions ───────────────────────────────────────────────

def test_export_button_still_present():
    assert 'id="log-export-btn"' in HTML


def test_new_workout_button_still_present():
    assert 'id="log-new-btn"' in HTML


def test_strava_button_in_html():
    assert 'id="sync-strava-btn"' in HTML


# ── Init: poll called on page load ───────────────────────────────────────────

def test_sync_poll_called_on_domcontentloaded():
    dl_idx = JS.index("DOMContentLoaded")
    init_body = JS[dl_idx: dl_idx + 500]
    assert "_syncPollStatus" in init_body


def test_strava_click_handler_wired_on_domcontentloaded():
    dl_idx = JS.index("DOMContentLoaded")
    init_body = JS[dl_idx: dl_idx + 500]
    assert "_onSyncStravaClick" in init_body


# ── Polling mechanics ────────────────────────────────────────────────────────

def test_poll_uses_setinterval():
    assert "setInterval" in JS
    idx = JS.index("setInterval")
    snippet = JS[idx: idx + 50]
    assert "_syncPollStatus" in snippet or "syncPollStatus" in snippet


def test_poll_stops_via_clearinterval():
    assert "clearInterval" in JS


def test_poll_queries_sync_status_endpoint():
    assert "/api/sync/status" in JS
