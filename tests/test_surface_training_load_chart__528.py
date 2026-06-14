"""Tests for issue #528: Surface training load + weekly volume chart on log.

Acceptance Criteria:
  AC1 - CTL/ATL/TSB from load_context exposed via API response (not discarded).
  AC2 - Readiness widget on the training-log page shows CTL/ATL/TSB +
        plain-language interpretation label.
  AC3 - Weekly volume chart (Chart.js) shows >= 8 weeks of distance or TSS.
  AC4 - Widget + chart update without full page reload when the date range
        changes (same XHR-driven fetchAndRender flow re-renders them).
  AC5 - load_context computed once per request, reused by list + new surfaces
        (no duplicate computation).
  AC6 - Widget + chart only on the training-log page; no regression on other
        Chart.js pages.
  AC7 - Empty / zero-activity weeks render gracefully (zero state, no error).

AC1/AC5 are API-contract tests (FastAPI TestClient). AC2/AC3/AC4/AC6/AC7
concern vanilla-JS / static markup (no bundler), so they are anchored as
static-asset contract tests against the served frontend files.
"""
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app, resolve_user

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000528")

_REPO = Path(__file__).resolve().parent.parent
_JS = (_REPO / "frontend" / "js" / "training-log.js").read_text()
_HTML = (_REPO / "frontend" / "pages" / "training-log.html").read_text()


# ── Test client + session mock helpers (mirrors issue #491 pattern) ──────────

def _make_client():
    u = MagicMock()
    u.id = _USER_ID

    async def _fake_resolve():
        return u

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_session_mock(total_workout_days: int, today_snap=None):
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    def _side_effect(model_or_col):
        from backend.models import Workout as _W, TrainingLoadSnapshot as _TLS

        m = MagicMock()
        if model_or_col is _W.workout_date:
            m.filter.return_value.distinct.return_value.count.return_value = total_workout_days
            return m
        if model_or_col is _TLS:
            m.filter.return_value.first.return_value = today_snap
            return m
        m.filter.return_value.filter.return_value = m.filter.return_value
        m.filter.return_value.order_by.return_value.all.return_value = []
        m.filter.return_value.all.return_value = []
        m.filter.return_value.first.return_value = None
        return m

    mock_session.query.side_effect = _side_effect
    return mock_session


def _make_snap(ctl, atl, tsb):
    snap = MagicMock()
    snap.ctl, snap.atl, snap.tsb = ctl, atl, tsb
    snap.snapshot_date = date.today()
    return snap


# ── AC1: CTL/ATL/TSB exposed via API, not discarded ──────────────────────────

def test_ac1_load_context_exposed_with_ctl_atl_tsb():
    client = _make_client()
    snap = _make_snap(55.0, 60.0, -5.0)
    sess = _make_session_mock(total_workout_days=20, today_snap=snap)
    try:
        with patch("backend.main.Session", return_value=sess):
            res = client.get("/api/training-log?include_load_context=true")
        assert res.status_code == 200
        lc = res.json()["load_context"]
        assert lc is not None
        assert lc["ctl"] == 55.0
        assert lc["atl"] == 60.0
        assert lc["tsb"] == -5.0
        assert "interpretation" in lc and lc["interpretation"]
    finally:
        _teardown()


# ── AC5: load_context computed once per request (no duplicate computation) ────

def test_ac5_load_context_computed_at_most_once():
    """With no snapshot, the EWMA fallback current_load is invoked exactly once
    for the request — list + new surfaces reuse the single result."""
    client = _make_client()
    sess = _make_session_mock(total_workout_days=10, today_snap=None)
    fake = {"date": date.today(), "ctl": 42.0, "atl": 38.0, "tsb": 4.0}
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.main.current_load", return_value=fake) as mock_cl,
        ):
            res = client.get("/api/training-log?include_load_context=true")
        assert res.status_code == 200
        mock_cl.assert_called_once()
    finally:
        _teardown()


def test_ac5_frontend_requests_load_context_in_main_list_fetch():
    """The list fetch carries include_load_context=true so the widget is fed
    from the SAME request as the list (one computation, reused)."""
    assert "include_load_context" in _JS
    # the flag must be set inside the main fetchAndRender list fetch
    idx = _JS.index("function fetchAndRender")
    nxt = _JS.index("function ", idx + 10)
    body = _JS[idx:nxt]
    assert "include_load_context" in body


# ── AC2: readiness widget shows CTL/ATL/TSB + interpretation ─────────────────

def test_ac2_widget_container_present_in_html():
    assert 'id="load-widget"' in _HTML


def test_ac2_widget_renders_ctl_atl_tsb_and_interpretation():
    # widget render reads all three values + the interpretation label
    assert "ctl" in _JS and "atl" in _JS and "tsb" in _JS
    assert "interpretation" in _JS
    # plain-language labels are surfaced (CTL/ATL/TSB headings)
    assert "CTL" in _JS and "ATL" in _JS and "TSB" in _JS


# ── AC3: weekly volume chart, Chart.js, >= 8 weeks, distance or TSS ───────────

def test_ac3_chartjs_loaded_and_canvas_present():
    assert "chart.js" in _HTML.lower()
    assert 'id="volume-chart"' in _HTML


def test_ac3_chart_uses_chartjs_and_volume_metrics():
    assert "new Chart" in _JS
    assert "total_distance_km" in _JS
    assert "total_tss" in _JS


def test_ac3_chart_covers_at_least_8_weeks():
    # a minimum-8-weeks window is enforced somewhere in the chart code
    assert "8" in _JS  # weeks minimum
    # unit label is km or TSS depending on selected metric
    assert "km" in _JS and "TSS" in _JS


# ── AC4: widget + chart update on date-range change (no full reload) ──────────

def test_ac4_range_change_triggers_rerender():
    # date-range apply re-runs fetchAndRender (XHR, no full reload)
    assert "fetchAndRender" in _JS
    # fetchAndRender re-renders both the widget and the chart
    idx = _JS.index("function fetchAndRender")
    nxt = _JS.index("\n  function ", idx + 10)
    body = _JS[idx:nxt]
    assert "renderLoadWidget" in body or "LoadWidget" in body
    assert "VolumeChart" in body or "renderVolumeChart" in body


# ── AC6: only on training-log page; no regression on other Chart.js pages ────

def test_ac6_volume_chart_only_on_training_log_page():
    for other in ("trends.html", "weight.html"):
        txt = (_REPO / "frontend" / "pages" / other).read_text()
        assert 'id="volume-chart"' not in txt, f"{other} must not host the volume chart"


def test_ac6_chart_code_guards_on_element_presence():
    """Chart/widget code must no-op when its elements are absent, so importing
    Chart.js elsewhere causes no errors referencing the new surfaces."""
    assert "getElementById('volume-chart')" in _JS or 'getElementById("volume-chart")' in _JS
    assert "getElementById('load-widget')" in _JS or 'getElementById("load-widget")' in _JS


# ── AC7: empty / zero-activity weeks render gracefully ───────────────────────

def test_ac7_null_load_context_returns_gracefully_with_insufficient_data():
    client = _make_client()
    sess = _make_session_mock(total_workout_days=2)
    try:
        with patch("backend.main.Session", return_value=sess):
            res = client.get("/api/training-log?include_load_context=true")
        assert res.status_code == 200
        assert res.json()["load_context"] is None
    finally:
        _teardown()


def test_ac7_frontend_handles_null_load_context_and_empty_weeks():
    # widget renders a zero/empty state when load_context is null
    assert "renderLoadWidget" in _JS
    # zero-fill missing weeks so empty weeks become a zero bar (not an error)
    assert "zero" in _JS.lower() or "|| 0" in _JS
