"""Tests for issue #304: global sync status bar injected below nav via nav.js."""
import pathlib
import re

NAV_JS = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "nav.js").read_text()


# ── DOM structure ─────────────────────────────────────────────────────────────

def test_sync_bar_element_created():
    assert "sync-status-bar" in NAV_JS


def test_sync_bar_inserted_after_global_nav():
    """Bar is inserted after .global-nav, not prepended to body."""
    insert_idx = NAV_JS.index("nav.nextSibling")
    assert insert_idx > 0, "sync bar must be inserted as nav.nextSibling"


def test_sync_bar_has_role_status():
    assert 'setAttribute' in NAV_JS
    assert '"role"' in NAV_JS or "'role'" in NAV_JS
    assert '"status"' in NAV_JS or "'status'" in NAV_JS


def test_sync_bar_has_aria_live():
    assert 'aria-live' in NAV_JS


# ── CSS scoping ───────────────────────────────────────────────────────────────

def test_sync_bar_styles_scoped_to_id():
    """All sync bar styles are prefixed with #sync-status-bar."""
    # Extract SYNC_BAR_CSS content between its array brackets
    match = re.search(r"var SYNC_BAR_CSS\s*=\s*\[(.+?)\]\.join", NAV_JS, re.DOTALL)
    assert match, "SYNC_BAR_CSS variable not found"
    css_block = match.group(1)
    # Every rule should be scoped — no unscoped selectors
    assert "#sync-status-bar" in css_block
    assert ".global-nav" not in css_block, "sync bar CSS must not reference .global-nav"


def test_sync_bar_hidden_by_default():
    """Base rule has display:none."""
    assert "display:none" in NAV_JS


# ── Phase labels ──────────────────────────────────────────────────────────────

def test_phase_label_pulling_strava():
    assert "Pulling Strava history" in NAV_JS


def test_phase_label_pulling_stryd():
    assert "Pulling Stryd history" in NAV_JS


def test_phase_label_reconciling():
    assert "Reconciling activities" in NAV_JS


# ── Polling logic ─────────────────────────────────────────────────────────────

def test_polls_sync_status_endpoint():
    assert "/api/sync/status" in NAV_JS


def test_polling_interval_is_4_seconds():
    assert "setInterval" in NAV_JS
    assert "4000" in NAV_JS


def test_polling_stops_on_non_running_status():
    assert "clearInterval" in NAV_JS


def test_sync_bar_refresh_exposed_globally():
    assert "window.syncBarRefresh" in NAV_JS


def test_sync_bar_refresh_stops_and_restarts_poll():
    refresh_idx = NAV_JS.index("window.syncBarRefresh")
    snippet = NAV_JS[refresh_idx: refresh_idx + 200]
    assert "_syncStopPoll" in snippet or "clearInterval" in snippet
    assert "_doPoll" in snippet


# ── Running state ─────────────────────────────────────────────────────────────

def test_running_state_shows_spinner():
    assert "ssb-spinner" in NAV_JS


def test_running_state_shows_provider():
    # provider is capitalised and rendered in the running display
    assert "data.provider" in NAV_JS


def test_running_state_shows_phase():
    assert "_PHASE_LABELS" in NAV_JS


def test_running_state_shows_progress_count():
    assert "data.current" in NAV_JS


# ── Success state ─────────────────────────────────────────────────────────────

def test_success_state_shows_synced_count():
    assert "items_synced" in NAV_JS
    assert "Synced" in NAV_JS


def test_success_auto_hides():
    assert "setTimeout" in NAV_JS
    assert "ssb-state-success" in NAV_JS


# ── Error state ───────────────────────────────────────────────────────────────

def test_error_state_shows_dismiss_button():
    assert "ssb-dismiss" in NAV_JS


def test_error_state_not_auto_hidden():
    # setTimeout should not reference error state
    timeout_matches = [m.start() for m in re.finditer(r"setTimeout", NAV_JS)]
    for idx in timeout_matches:
        snippet = NAV_JS[idx: idx + 200]
        assert "ssb-state-error" not in snippet, (
            "Error state must not be auto-hidden via setTimeout"
        )


# ── Network resilience ────────────────────────────────────────────────────────

def test_network_error_caught():
    """.catch() handler present so 404/network errors don't throw."""
    assert ".catch(" in NAV_JS


# ── Init integration ──────────────────────────────────────────────────────────

def test_build_sync_bar_called_in_init():
    init_idx = NAV_JS.index("function init()")
    init_body = NAV_JS[init_idx: init_idx + 400]
    assert "buildSyncBar" in init_body


def test_do_poll_called_in_init():
    init_idx = NAV_JS.index("function init()")
    init_body = NAV_JS[init_idx: init_idx + 400]
    assert "_doPoll" in init_body
