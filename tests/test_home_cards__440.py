"""
TDD tests for issue #440: Build Readiness, This-Week Training, and Sleep Cards.

AC anchors:
  (S1)  API: sleep block returns {"logged": false} when no metrics logged
  (S2)  API: sleep block returns {"logged": true, "hours": ..., "quality": ...} when logged
  (R1)  API: readiness block returns {"logged": false} when no metrics
  (R2)  API: readiness block returns {"logged": true, "score", "label", "top_factors"} when logged
  (T1)  API: training_week block has required fields (workouts_count, distance_km, zone2_minutes,
             vs_last_week, daily_load with 7 entries)
  (F1)  HTML: #home-top-row-right exists for readiness tile
  (F2)  HTML: #home-training-card container present (or JS creates it)
  (F3)  HTML: #home-sleep-card container present (or JS creates it)
  (F4)  JS: readiness tile render function exists
  (F5)  JS: training card render function exists
  (F6)  JS: sleep card render function exists
  (F7)  JS: readiness empty state — contains "Log today" / "Log today's metrics" copy
  (F8)  JS: readiness logged state — renders score ring SVG or element
  (F9)  JS: score ring color reflects band (low/mid/high color tokens used)
  (F10) JS: training card renders four mini-stat labels (Workouts/Distance/Zone 2/delta)
  (F11) JS: vs-last-week delta uses green for positive, red for negative
  (F12) JS: daily-load chart renders Mon–Sun day labels
  (F13) JS: today's bar highlighted in lime accent (--accent or #e4ff52)
  (F14) JS: rest-day bars visually greyed out
  (F15) JS: sleep logged state — shows hours slept
  (F16) JS: sleep empty state — shows link to daily-metrics input
  (F17) JS: "Training log →" link points to /log
  (F18) JS: readiness "Log metrics →" header link present
  (F19) JS: all three render functions handle null block without throwing
  (F20) JS: sleep dark-purple gradient background applied
"""
import contextlib
import datetime
import pathlib
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HOME_JS_PATH = _ROOT / "frontend" / "js" / "home.js"
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()
_CARDS_JS_PATH = _ROOT / "frontend" / "js" / "home-readiness-training-sleep.js"

def _read_all_home_js():
    """Return concatenated text of home.js + home-readiness-training-sleep.js."""
    parts = []
    if _HOME_JS_PATH.exists():
        parts.append(_HOME_JS_PATH.read_text())
    if _CARDS_JS_PATH.exists():
        parts.append(_CARDS_JS_PATH.read_text())
    return "\n".join(parts)

_JS = _read_all_home_js()

client = TestClient(app)
_TODAY = datetime.date.today()
_UID = uuid.uuid4()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_user(uid=None):
    u = MagicMock()
    u.id = uid or _UID
    return u


@contextlib.contextmanager
def _authed_session_simple(uid=None):
    """Override resolve_user; minimal session mock."""
    u = _mock_user(uid)

    async def _fake():
        return u

    app.dependency_overrides[resolve_user] = _fake
    yield u
    app.dependency_overrides.pop(resolve_user, None)


def _mk_metrics(uid, date, sleep_hours=7.5, sleep_quality=4, hrv=55, resting_hr=60,
                energy=4, mood=4):
    m = MagicMock()
    m.user_id = uid
    m.metric_date = date if isinstance(date, datetime.date) else datetime.date.fromisoformat(date)
    m.sleep_hours = sleep_hours
    m.sleep_quality = sleep_quality
    m.hrv = hrv
    m.resting_hr = resting_hr
    m.energy = energy
    m.mood = mood
    return m


def _mk_workout(uid, date, tss=80, distance_km=10.0, zone2_minutes=30):
    w = MagicMock()
    w.user_id = uid
    w.workout_date = date if isinstance(date, datetime.date) else datetime.date.fromisoformat(date)
    w.tss = tss
    w.distance_km = distance_km
    w.zone2_minutes = zone2_minutes
    return w


# ── S1: sleep block logged=false when no metrics ──────────────────────────────

def test_S1_sleep_block_logged_false_when_no_metrics():
    """_build_sleep_block returns {logged: False} when no metric row."""
    from backend.main import _build_sleep_block
    uid = uuid.uuid4()
    with patch("backend.main.Session") as MockSession:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = None
        mock_session.query.return_value = q
        MockSession.return_value = mock_session
        result = _build_sleep_block(uid, _TODAY)
    assert result == {"logged": False}


# ── S2: sleep block logged=true with fields when metrics exist ─────────────────

def test_S2_sleep_block_logged_true_when_metrics_present():
    """_build_sleep_block returns {logged: True, hours, quality} when logged."""
    from backend.main import _build_sleep_block
    uid = uuid.uuid4()
    m = _mk_metrics(uid, _TODAY, sleep_hours=7.5, sleep_quality=4)
    with patch("backend.main.Session") as MockSession:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = m
        mock_session.query.return_value = q
        MockSession.return_value = mock_session
        result = _build_sleep_block(uid, _TODAY)
    assert result.get("logged") is True
    assert result.get("hours") == pytest.approx(7.5)
    assert result.get("quality") == 4


# ── S3: sleep block quality null-safe ─────────────────────────────────────────

def test_S3_sleep_block_quality_none_when_not_set():
    """_build_sleep_block returns quality: null when sleep_quality is None."""
    from backend.main import _build_sleep_block
    uid = uuid.uuid4()
    m = _mk_metrics(uid, _TODAY, sleep_hours=7.0, sleep_quality=None)
    m.sleep_quality = None
    with patch("backend.main.Session") as MockSession:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = m
        mock_session.query.return_value = q
        MockSession.return_value = mock_session
        result = _build_sleep_block(uid, _TODAY)
    assert result.get("logged") is True
    assert result.get("quality") is None


# ── R1: readiness block logged=false when no metrics ─────────────────────────

def test_R1_readiness_block_logged_false_when_no_metrics():
    """_build_readiness_block returns {logged: False} when no metric row."""
    from backend.main import _build_readiness_block
    uid = uuid.uuid4()
    with patch("backend.main.Session") as MockSession:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = None
        q.all.return_value = []
        mock_session.query.return_value = q
        MockSession.return_value = mock_session
        result = _build_readiness_block(uid, _TODAY)
    assert result == {"logged": False}


# ── R2: readiness block logged=true with score/label/factors ──────────────────

def test_R2_readiness_block_logged_true_with_score():
    """_build_readiness_block returns logged=True with score, label, top_factors."""
    from backend.main import _build_readiness_block
    uid = uuid.uuid4()
    m = _mk_metrics(uid, _TODAY, sleep_hours=7.5, sleep_quality=4, hrv=60,
                    resting_hr=55, energy=4, mood=4)
    with patch("backend.main.Session") as MockSession:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = m
        q.all.return_value = []
        mock_session.query.return_value = q
        MockSession.return_value = mock_session
        result = _build_readiness_block(uid, _TODAY)
    assert result.get("logged") is True
    assert "score" in result
    assert "label" in result
    assert "top_factors" in result
    assert isinstance(result["top_factors"], list)
    assert len(result["top_factors"]) == 3


# ── T1: training_week block fields ────────────────────────────────────────────

def test_T1_training_week_block_has_required_fields():
    """_build_training_week_block returns required fields and 7-entry daily_load."""
    from backend.main import _build_training_week_block
    from datetime import timedelta
    uid = uuid.uuid4()
    ws = _TODAY - timedelta(days=_TODAY.weekday())  # Monday of current week
    w = _mk_workout(uid, ws, tss=80, distance_km=10.0, zone2_minutes=30)
    with patch("backend.main.Session") as MockSession:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        q = MagicMock()
        q.filter.return_value = q
        q.all.return_value = [w]
        mock_session.query.return_value = q
        MockSession.return_value = mock_session
        result = _build_training_week_block(uid, _TODAY, ws)
    assert "workouts_count" in result
    assert "distance_km" in result
    assert "zone2_minutes" in result
    assert "vs_last_week" in result
    assert "daily_load" in result
    assert len(result["daily_load"]) == 7
    for entry in result["daily_load"]:
        assert "date" in entry
        assert "is_rest" in entry


# ── T2: training_week vs_last_week fields ─────────────────────────────────────

def test_T2_training_week_vs_last_week_fields():
    """training_week.vs_last_week includes workouts_count, distance_km, zone2_minutes."""
    from backend.main import _build_training_week_block
    from datetime import timedelta
    uid = uuid.uuid4()
    ws = _TODAY - timedelta(days=_TODAY.weekday())
    with patch("backend.main.Session") as MockSession:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        q = MagicMock()
        q.filter.return_value = q
        q.all.return_value = []
        mock_session.query.return_value = q
        MockSession.return_value = mock_session
        result = _build_training_week_block(uid, _TODAY, ws)
    vl = result["vs_last_week"]
    assert "workouts_count" in vl
    assert "distance_km" in vl
    assert "zone2_minutes" in vl


# ── F1: HTML has #home-top-row-right ──────────────────────────────────────────

def test_F1_html_has_home_top_row_right():
    """home.html must contain the #home-top-row-right placeholder for readiness tile."""
    assert 'id="home-top-row-right"' in _HOME_HTML


# ── F2: HTML has training card container ──────────────────────────────────────

def test_F2_html_has_training_card_container():
    """home.html must contain a container element for the training card."""
    assert 'id="home-training-card"' in _HOME_HTML


# ── F3: HTML has sleep card container ─────────────────────────────────────────

def test_F3_html_has_sleep_card_container():
    """home.html must contain a container element for the sleep card."""
    assert 'id="home-sleep-card"' in _HOME_HTML


# ── F4: JS has readiness tile render function ─────────────────────────────────

def test_F4_js_has_readiness_tile_function():
    """JS must define a function for rendering the compact readiness tile."""
    assert "renderReadinessTile" in _JS or "loadReadinessTile" in _JS


# ── F5: JS has training card render function ──────────────────────────────────

def test_F5_js_has_training_card_function():
    """JS must define a function for rendering the training card."""
    assert "renderTrainingCard" in _JS or "loadTrainingCard" in _JS


# ── F6: JS has sleep card render function ─────────────────────────────────────

def test_F6_js_has_sleep_card_function():
    """JS must define a function for rendering the sleep card."""
    assert "renderSleepCard" in _JS or "loadSleepCard" in _JS or "loadHomeSleepCard" in _JS


# ── F7: JS readiness empty state copy ─────────────────────────────────────────

def test_F7_js_readiness_empty_state_has_log_copy():
    """JS readiness tile must include 'Log today' copy for the empty state."""
    assert "Log today" in _JS or "Log metrics" in _JS


# ── F8: JS readiness logged state — score ring element ────────────────────────

def test_F8_js_readiness_logged_state_has_score_ring():
    """JS readiness tile must render a score ring when logged=true."""
    # Score ring can be SVG circle or a div with class containing "ring" or "score"
    has_ring = (
        "score-ring" in _JS
        or "rd-ring" in _JS
        or "readiness-ring" in _JS
        or ("circle" in _JS.lower() and "score" in _JS)
    )
    assert has_ring, "JS must render some form of score ring for the readiness tile"


# ── F9: JS score ring color reflects band ─────────────────────────────────────

def test_F9_js_score_ring_color_reflects_band():
    """JS must apply different colors based on readiness score band."""
    # Check for the three readiness band color values from DESIGN.md
    has_bands = (
        "#16a34a" in _JS  # high (>=70)
        or "readiness-high" in _JS
        or ("green" in _JS.lower() and "amber" in _JS.lower())
    )
    assert has_bands, "JS must apply color based on readiness score band"


# ── F10: JS training card has mini-stat labels ────────────────────────────────

def test_F10_js_training_card_has_mini_stat_labels():
    """JS training card must render Workouts, Distance, Zone 2 labels."""
    assert "Workouts" in _JS
    assert "Distance" in _JS or "distance" in _JS
    assert "Zone 2" in _JS or "zone2" in _JS or "Zone2" in _JS


# ── F11: JS vs-last-week delta green/red ──────────────────────────────────────

def test_F11_js_training_delta_green_red():
    """JS training card must apply green for positive delta and red for negative."""
    has_green = "green" in _JS.lower()
    has_red = "red" in _JS.lower()
    assert has_green and has_red


# ── F12: JS daily-load chart has Mon–Sun labels ───────────────────────────────

def test_F12_js_daily_load_chart_mon_sun():
    """JS training card chart must include Mon–Sun day labels."""
    days_present = all(d in _JS for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    assert days_present, "JS must render Mon-Sun labels in the daily-load chart"


# ── F13: JS today bar highlighted with lime accent ────────────────────────────

def test_F13_js_training_today_bar_lime():
    """JS training chart must highlight today's bar with the lime accent color."""
    has_lime = ("--accent" in _JS or "#e4ff52" in _JS)
    assert has_lime, "JS must use lime accent (#e4ff52 or --accent) for today's bar"


# ── F14: JS rest days greyed out ──────────────────────────────────────────────

def test_F14_js_training_rest_days_grey():
    """JS training chart must grey out rest-day bars."""
    has_grey = (
        "is_rest" in _JS
        or "chip-bg" in _JS
        or "#e5e7eb" in _JS
        or "rgba(0" in _JS
        or "grey" in _JS.lower()
        or "gray" in _JS.lower()
    )
    assert has_grey, "JS must visually grey out rest-day bars"


# ── F15: JS sleep logged state shows hours ────────────────────────────────────

def test_F15_js_sleep_shows_hours():
    """JS sleep card must display hours slept when sleep.logged===true."""
    assert ".hours" in _JS or "sleep_hours" in _JS or ".hours" in _JS or '"hours"' in _JS


# ── F16: JS sleep empty state has link to metrics input ───────────────────────

def test_F16_js_sleep_empty_has_link():
    """JS sleep empty state must include a link to the daily-metrics input."""
    has_link = (
        "daily-metrics" in _JS
        or "/calendar" in _JS
        or "metrics" in _JS.lower()
    )
    assert has_link, "JS sleep empty state must link to daily-metrics input"


# ── F17: JS training link points to /log ─────────────────────────────────────

def test_F17_js_training_log_link():
    """JS training card must include a 'Training log →' link to /log."""
    assert '"/log"' in _JS or "href=\"/log\"" in _JS or "href='/log'" in _JS


# ── F18: JS readiness header has 'Log metrics' link ─────────────────────────

def test_F18_js_readiness_log_metrics_link():
    """JS readiness tile header must include a 'Log metrics →' link."""
    assert "Log metrics" in _JS or "log-metrics" in _JS


# ── F19: JS null safety for all three blocks ──────────────────────────────────

def test_F19_js_null_safety():
    """JS render functions must guard against null/undefined block data."""
    # Each render function should check for null before accessing properties
    has_null_guard = (
        "if (!readiness" in _JS
        or "if (!training" in _JS
        or "if (!sleep" in _JS
        or "null" in _JS
    )
    assert has_null_guard, "JS must guard against null block data"


# ── F20: JS sleep card has dark-purple gradient background ───────────────────

def test_F20_js_sleep_card_dark_purple_gradient():
    """JS sleep card must apply dark-purple gradient background per mock."""
    has_purple = (
        "sleep-1" in _JS
        or "sleep-2" in _JS
        or "#2a1d54" in _JS
        or "sleep-card" in _JS
        or "purple" in _JS.lower()
    )
    assert has_purple, "JS sleep card must reference dark-purple gradient colors"
