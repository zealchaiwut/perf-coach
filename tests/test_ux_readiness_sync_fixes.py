"""Static contracts for the UX / readiness / sync honesty pass.

Covers: Log Today posts sleep_quality and weight; ring refresh after save;
sync poller treats pending as in-flight; dismiss × does not stop polling;
morning includes a wellness row; reconciling copy.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOME_HTML = (ROOT / "frontend" / "pages" / "home.html").read_text()
HOME_JS = (ROOT / "frontend" / "js" / "home.js").read_text()
MORNING_JS = (ROOT / "frontend" / "js" / "home-morning.js").read_text()
NAV_JS = (ROOT / "frontend" / "js" / "nav.js").read_text()
POLLER_JS = (ROOT / "frontend" / "js" / "lib" / "sync-poller.js").read_text()
SETTINGS_HTML = (ROOT / "frontend" / "pages" / "settings.html").read_text()
LOAD_CSS = (ROOT / "frontend" / "css" / "load-readiness-tiles.css").read_text()
LOG_JS = (ROOT / "frontend" / "js" / "training-log.js").read_text()
LOG_HTML = (ROOT / "frontend" / "pages" / "training-log.html").read_text()


def test_fast_log_has_sleep_quality_pills():
    assert 'id="fm-sleep-quality-pills"' in HOME_HTML
    assert 'id="fm-sleep-quality-val"' in HOME_HTML


def test_fast_log_payload_includes_sleep_quality():
    assert "payload.sleep_quality" in HOME_JS


def test_fast_log_posts_weight_entries():
    assert "/api/weight-entries" in HOME_JS
    assert "_fmSaveWeight" in HOME_JS


def test_fast_log_has_cancel():
    assert 'id="fm-cancel"' in HOME_HTML
    assert "fm-cancel" in HOME_JS


def test_fast_log_energy_mood_have_poor_great_labels():
    assert "Poor" in HOME_HTML
    assert "Great" in HOME_HTML


def test_metrics_save_refreshes_home_summary():
    assert "_afterMetricsSave" in HOME_JS
    assert "HomeRTS.render" in HOME_JS


def test_stale_banner_survives_failed_sync_now():
    assert "Load numbers below are still stale" in HOME_JS
    catch_idx = HOME_JS.find("strava-stale-refresh")
    snippet = HOME_JS[catch_idx : catch_idx + 1800]
    assert "container.hidden = true" not in snippet


def test_poller_treats_pending_as_active():
    assert "status === 'pending'" in POLLER_JS
    assert "_isActive" in POLLER_JS


def test_wait_for_idle_does_not_resolve_on_pending():
    wait = POLLER_JS[POLLER_JS.find("function waitForIdle") :]
    # pending must keep waiting, not fall through as done
    assert "_isActive(data.status)" in wait
    assert "data.status !== 'running'" not in wait


def test_running_dismiss_does_not_stop_poller():
    running = NAV_JS[NAV_JS.find("function _ssbRunning") : NAV_JS.find("function _ssbSuccess")]
    assert "SyncPoller.stop()" not in running
    assert "_ssbMutedWhileActive" in running


def test_nav_shows_pending_and_matching_copy():
    assert "Waiting to sync" in NAV_JS
    assert "Matching workouts" in NAV_JS
    assert "Reconciling activities" not in NAV_JS


def test_morning_tracks_metrics_as_fourth_row():
    assert "of 4 done" in MORNING_JS
    assert "_metricsRowHtml" in MORNING_JS
    assert "readiness.logged" in MORNING_JS


def test_load_tiles_stay_visible_on_narrow_screens():
    mobile = LOAD_CSS[LOAD_CSS.find("@media (max-width: 479px)") :]
    assert "display: none" not in mobile


def test_integrations_log_is_collapsed_details():
    assert '<details class="integration-log"' in SETTINGS_HTML
    assert "Connect Strava or Stryd" in SETTINGS_HTML


def test_stryd_fields_have_labels():
    assert 'for="stryd-email"' in SETTINGS_HTML
    assert 'for="stryd-password"' in SETTINGS_HTML
    assert 'aria-label="Stryd email"' in SETTINGS_HTML


def test_training_log_poller_treats_pending_as_busy():
    fn = LOG_JS[LOG_JS.find("function _onSyncPollerUpdate") :]
    assert 'data.status === "running" || data.status === "pending"' in fn


def test_training_log_has_page_heading():
    assert "<h1" in LOG_HTML
    assert "Training log" in LOG_HTML


def test_home_has_no_leftover_sleep_card_css():
    assert ".sleep-card" not in HOME_HTML


def test_pr_labels_are_readable():
    assert "font-size: 8px" not in HOME_HTML[HOME_HTML.find(".pr-lbl") : HOME_HTML.find(".pr-lbl") + 80]
