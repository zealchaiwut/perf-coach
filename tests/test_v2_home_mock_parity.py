"""Prompt 1 — Home mock parity (display-only)."""
from pathlib import Path

HOME_JS = Path("frontend/js/v2-home.js").read_text(encoding="utf-8")
HOME_HTML = Path("frontend/pages/v2-home.html").read_text(encoding="utf-8")
NAV_JS = Path("frontend/js/v2-nav.js").read_text(encoding="utf-8")
CSS = Path("frontend/css/revamp.css").read_text(encoding="utf-8")


def test_daily_basics_live_in_hero():
    assert "dailyBasicsHtml(data.daily_basics)" in HOME_JS
    assert "bindDailyBasics(host, reload || load)" in HOME_JS
    assert "under 10 s" in HOME_JS


def test_greeting_follows_time_of_day():
    assert "function greetingText" in HOME_JS
    assert "Good morning" in HOME_JS
    assert "Good afternoon" in HOME_JS
    assert "Good evening" in HOME_JS


def test_alert_titles_and_ctas():
    assert "Weekly check-in." in HOME_JS
    assert "Week is over the ceiling." in HOME_JS
    assert "Open check-in" in HOME_JS
    assert "Record outcome" in HOME_JS


def test_header_pill_uses_weeks_when_far():
    assert "dtr >= 14" in HOME_JS
    assert '" week"' in HOME_JS


def test_ladder_is_svg():
    assert 'class="rv-ladder-svg"' in HOME_JS
    assert "<rect" in HOME_JS


def test_empty_states_not_stuck_on_loading():
    assert "Could not load this week." in HOME_JS
    assert "No A race on the calendar yet." in HOME_JS
    assert "No recent sessions." in HOME_JS
    assert "Could not load this card." in HOME_JS


def test_week_notes_render():
    assert "rv-week-day-note" in HOME_JS


def test_road_uses_existing_plan_chart():
    assert "/api/plan/revamp-road-chart" in HOME_JS
    assert 'id="rv-home-road"' in HOME_HTML


def test_sync_dot_starts_idle():
    assert "rv-sync-dot--idle" in NAV_JS
    assert "rv-sync-dot--idle" in CSS


def test_escape_uses_app_common():
    assert "escapeHtml.bind" in HOME_JS
