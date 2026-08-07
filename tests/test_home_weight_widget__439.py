"""
TDD tests for issue #439: Add home weight widget with stepper quick-log.

Home revamp v2 (docs/mocks/home-revamp-v2.html) retired the original
full-width #home-weight-widget (and its shared-component reuse of
frontend/js/lib/weight-current-card.js) from Home. Its two jobs split in
two: the quick weigh-in stepper moved into #home-morning's weigh-in row
(frontend/js/home-morning.js — same POST /api/weight-entries + PATCH-on-409
logic, ported), and the trend/rate/coverage display became its own slim
#home-weight-trend card (frontend/js/home-weight-trend.js, sourced from
/api/weight-chart). The goal-gap pill and progress bar (F3/F11's original
scope) were dropped from Home entirely — that detail now lives only on the
full /weight page. The (F1/F2/F3/F4/F5/F6/F7/F8/F9/F10/F11/F12) anchors below
have been updated in place to describe that split; anchor numbering is kept
stable so this docstring still matches its own test names. The API section
(A1-A7, GET /api/home/weight-summary) is untouched — that backend endpoint
still exists and is unaffected by this frontend-only refactor.

AC anchors:
  (A1)  API: sparkline field present — 7-day actual data points
  (A2)  API: plan field present when target exists, empty when no target
  (A3)  API: gap_kg present — signed gap from expected trajectory (or null)
  (A4)  API: status_label present at top level (null when no target/data)
  (A5)  API: last_entry_kg mirrors current_weight
  (A6)  API: weekly_rate_kg present
  (A7)  API: target.kg_to_go present when target exists
  (F1)  HTML: #home-weight-trend container present (superseded #home-weight-widget)
  (F2)  JS: HomeWeightTrend + home-morning.js's weigh-in row are wired from home.js
  (F3)  JS: gap pill retired from Home — behind/ahead now render only on race gap
        (home-race-card.js), not weight; weight coverage warning is its replacement
  (F4)  JS: home-morning.js's stepper POSTs to /api/weight-entries with today's date
  (F5)  JS: 409 path — home-morning.js PATCHes /api/weight-entries/{id}
  (F6)  JS: the weigh-in row is marked done (hm-row--done) after a successful log
  (F7)  JS: retired — the always-visible stepper (prefilled from last_entry_kg) has
        no separate compact/edit states to toggle between
  (F8)  JS: home-weight-trend.js's empty state links to /weight to log a first entry
  (F9)  JS: home-weight-trend.js header "Weight trend" and "Open →" link to /weight
  (F10) JS: home-weight-trend.js links out to /weight for full goal/target detail
  (F11) JS: home-weight-trend.js renders trend kg + rate ± CI (replaces the shared
        current/7-day-avg stat pair)
  (F12) JS: home-weight-trend.js sources its data from /api/weight-chart
"""
import contextlib
import datetime
import pathlib
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user

# ── Root detection ─────────────────────────────────────────────────────────────

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()
# Shared "current weight" component — still used by weight.html, but no
# longer by Home (see module docstring); kept here only for the reader who
# wants to compare the old shared-block approach to the new split below.
_CARD_JS = (_ROOT / "frontend" / "js" / "lib" / "weight-current-card.js").read_text()
# The two modules that now split the old weight widget's jobs on Home.
_MORNING_JS = (_ROOT / "frontend" / "js" / "home-morning.js").read_text()
_TREND_JS = (_ROOT / "frontend" / "js" / "home-weight-trend.js").read_text()
_RACE_JS = (_ROOT / "frontend" / "js" / "home-race-card.js").read_text()

client = TestClient(app)
_TODAY = datetime.date.today()
_UID = uuid.uuid4()


# ── Fixtures / helpers ─────────────────────────────────────────────────────────

def _mock_user(uid=None):
    u = MagicMock()
    u.id = uid or _UID
    return u


@contextlib.contextmanager
def _authed_session(entries, target):
    """Override resolve_user + patch Session so weight-summary sees controlled data."""
    mock_user = _mock_user()

    async def _fake_resolve():
        return mock_user

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.all.return_value = entries
    query_mock.first.return_value = target
    mock_session.query.return_value = query_mock

    app.dependency_overrides[resolve_user] = _fake_resolve
    with patch("backend.main.Session", return_value=mock_session):
        yield
    app.dependency_overrides.pop(resolve_user, None)


def _make_entry(entry_date, weight_kg):
    e = MagicMock()
    e.entry_date = (
        entry_date if isinstance(entry_date, datetime.date)
        else datetime.date.fromisoformat(entry_date)
    )
    e.weight_kg = weight_kg
    e.entry_time = None
    return e


def _make_target(start_w=85.0, target_w=78.0, start_d=None, target_d=None):
    t = MagicMock()
    t.status = "active"
    t.start_weight_kg = start_w
    t.target_weight_kg = target_w
    t.start_date = start_d or (_TODAY - datetime.timedelta(days=50))
    t.target_date = target_d or (_TODAY + datetime.timedelta(days=50))
    return t


# ════════════════════════════════════════════════════════════════════════════════
# API TESTS
# ════════════════════════════════════════════════════════════════════════════════

# ── A1: sparkline field ────────────────────────────────────────────────────────

def test_a1_sparkline_field_present():
    """AC (A1): GET /api/home/weight-summary includes a `sparkline` list."""
    entries = [
        _make_entry(_TODAY - datetime.timedelta(days=i), 82.0 + i * 0.1)
        for i in range(7, 0, -1)
    ]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    assert r.status_code == 200
    data = r.json()
    assert "sparkline" in data, "sparkline field must be in weight-summary response"
    assert isinstance(data["sparkline"], list)


def test_a1_sparkline_items_have_date_and_value():
    """AC (A1): sparkline items have {date, value} shape."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    for pt in data["sparkline"]:
        assert "date" in pt and "value" in pt


def test_a1_sparkline_at_most_7_points():
    """AC (A1): sparkline covers at most 7 days."""
    entries = [
        _make_entry(_TODAY - datetime.timedelta(days=i), 82.0)
        for i in range(14, 0, -1)
    ]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert len(data["sparkline"]) <= 7


# ── A2: plan field ─────────────────────────────────────────────────────────────

def test_a2_plan_present_when_target_exists():
    """AC (A2): `plan` is non-empty list when active target exists."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, _make_target()):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert "plan" in data
    assert isinstance(data["plan"], list)
    assert len(data["plan"]) > 0


def test_a2_plan_empty_when_no_target():
    """AC (A2): `plan` is empty list when no active target."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert data.get("plan") == [], "plan must be [] when no target"


def test_a2_plan_items_have_date_value():
    """AC (A2): plan items have {date, value} shape."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, _make_target()):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    for pt in data["plan"]:
        assert "date" in pt and "value" in pt


# ── A3: gap_kg ─────────────────────────────────────────────────────────────────

def test_a3_gap_kg_present():
    """AC (A3): `gap_kg` field present in response."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, _make_target()):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert "gap_kg" in data


def test_a3_gap_kg_null_when_no_target():
    """AC (A3): gap_kg is null when no active target."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert data["gap_kg"] is None


# ── A4: status_label at top level ─────────────────────────────────────────────

def test_a4_status_label_at_top_level():
    """AC (A4): status_label present at top level."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert "status_label" in data


def test_a4_status_label_null_when_no_target():
    """AC (A4): status_label is null when no target (gap pill hidden)."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert data["status_label"] is None


def test_a4_status_label_no_data_when_no_entries():
    """AC (A4): status_label is no_data when no entries, even with target."""
    with _authed_session([], _make_target()):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert data["status_label"] in (None, "no_data")


# ── A5: last_entry_kg ─────────────────────────────────────────────────────────

def test_a5_last_entry_kg_mirrors_current_weight():
    """AC (A5): last_entry_kg == current_weight."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.3)]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert "last_entry_kg" in data
    assert data["last_entry_kg"] == data["current_weight"]


def test_a5_last_entry_kg_null_when_no_entries():
    """AC (A5): last_entry_kg is null when no entries."""
    with _authed_session([], None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert data["last_entry_kg"] is None


# ── A6: weekly_rate_kg ────────────────────────────────────────────────────────

def test_a6_weekly_rate_kg_present():
    """AC (A6): weekly_rate_kg field present in response."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, None):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert "weekly_rate_kg" in data


# ── A7: target.kg_to_go ───────────────────────────────────────────────────────

def test_a7_target_has_kg_to_go():
    """AC (A7): target block includes kg_to_go when target exists."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    with _authed_session(entries, _make_target(start_w=85.0, target_w=78.0)):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    assert data["target"] is not None
    assert "kg_to_go" in data["target"]


def test_a7_kg_to_go_equals_gap_to_target():
    """AC (A7): kg_to_go = abs(current_weight - target_weight_kg)."""
    entries = [_make_entry(_TODAY - datetime.timedelta(days=1), 82.5)]
    target = _make_target(start_w=85.0, target_w=78.0)
    with _authed_session(entries, target):
        r = client.get("/api/home/weight-summary")
    data = r.json()
    expected = abs(data["current_weight"] - 78.0)
    assert abs(data["target"]["kg_to_go"] - expected) < 0.1


# ════════════════════════════════════════════════════════════════════════════════
# FRONTEND TESTS
# ════════════════════════════════════════════════════════════════════════════════

# ── F1: HTML container ────────────────────────────────────────────────────────

def test_f1_weight_widget_container_in_html():
    """AC (F1): home.html has the #home-weight-trend container that superseded
    #home-weight-widget (the quick-log row itself is rendered inside
    #home-morning, not a separate host div — see home-morning.js)."""
    assert 'id="home-weight-trend"' in _HOME_HTML, \
        "home.html must include the #home-weight-trend container"
    assert 'id="home-weight-widget"' not in _HOME_HTML, \
        "the old #home-weight-widget container must be removed"


# ── F2: JS entry points ────────────────────────────────────────────────────────
# The home "current weight" stat block no longer reuses the shared
# weight-current-card.js component — it split into HomeWeightTrend (trend
# card) + home-morning.js's weigh-in row (quick-log stepper).

def test_f2_home_weight_trend_wired_from_home_js():
    """AC (F2): home.js renders HomeWeightTrend into #home-weight-trend."""
    assert "HomeWeightTrend" in _HOME_JS, \
        "home.js must reference window.HomeWeightTrend"
    assert "home-weight-trend" in _HOME_JS, \
        "home.js must look up the #home-weight-trend container"


def test_f2_home_morning_renders_weighin_row():
    """AC (F2): home.js renders HomeMorning (which owns the weigh-in row) into
    #home-morning."""
    assert "HomeMorning" in _HOME_JS
    assert "home-morning" in _HOME_JS


def test_f2_no_longer_uses_shared_current_weight_component():
    """AC (F2, revised): Home no longer reuses WeightCurrentCard — that
    component is retired from Home's JS (still used by weight.html)."""
    assert "WeightCurrentCard" not in _HOME_JS, \
        "home.js must not reference WeightCurrentCard — Home split into " \
        "HomeWeightTrend + home-morning.js's own stepper"


# ── F3: Gap pill — retired from Home ──────────────────────────────────────────

def test_f3_weight_gap_pill_retired_from_home():
    """AC (F3, revised): the weight goal-gap pill (behind/ahead/on plan) is
    retired from Home — that comparison now lives only on the full /weight
    page. Home's weight card shows a coverage warning instead (see A6/A7's
    backend fields, still exposed for /weight to use)."""
    assert "behind" not in _TREND_JS and "ahead" not in _TREND_JS, \
        "home-weight-trend.js must not render a weight goal-gap pill"
    assert "gated" in _TREND_JS or "coverage" in _TREND_JS, \
        "home-weight-trend.js must surface a coverage warning instead"


def test_f3_race_card_owns_behind_ahead_language_now():
    """The only 'behind'/'ahead' language left on Home describes the RACE
    goal-vs-estimate gap (home-race-card.js), not weight."""
    assert "behind" in _RACE_JS and "ahead" in _RACE_JS


# ── F4: POST to /api/weight-entries (now in home-morning.js) ─────────────────

def test_f4_posts_to_weight_entries():
    """AC (F4): home-morning.js's weigh-in row POSTs to /api/weight-entries."""
    assert "/api/weight-entries" in _MORNING_JS


def test_f4_includes_entry_date():
    """AC (F4): POST body includes entry_date (via AppCommon.todayISO())."""
    assert "entry_date" in _MORNING_JS


# ── F5: 409 path — PATCH (now in home-morning.js) ─────────────────────────────

def test_f5_handles_409():
    """AC (F5): home-morning.js handles the 409 conflict response."""
    assert "409" in _MORNING_JS


def test_f5_patch_with_existing_id():
    """AC (F5): PATCH uses existing_id from the 409 response body."""
    assert "existing_id" in _MORNING_JS
    assert "PATCH" in _MORNING_JS


# ── F6: Row marked done after a successful log ────────────────────────────────

def test_f6_weight_row_marked_done_after_log():
    """AC (F6, revised): after a successful log, home-morning.js marks the
    weigh-in row done (hm-row--done, via the shared `done.weight` +
    `_paint()` state machine) — replaces the old standalone 'Logged today'
    compact-card copy, which had no equivalent in the three-row morning
    strip's design."""
    assert "hm-row--done" in _MORNING_JS
    assert "done.weight = true" in _MORNING_JS


# ── F7: Edit re-opens stepper — retired ───────────────────────────────────────

def test_f7_stepper_always_visible_no_edit_toggle():
    """AC (F7, retired): home-morning.js's weigh-in stepper is always visible
    and prefilled from last_entry_kg — there is no separate compact/edit
    state to toggle between (unlike the old widget's post-log collapse)."""
    assert "_renderStepper" in _MORNING_JS
    assert "prefill" in _MORNING_JS


# ── F8: Empty state ───────────────────────────────────────────────────────────

def test_f8_empty_state_links_to_weight_tab():
    """AC (F8, revised): with no weight data, home-weight-trend.js's empty
    state links to /weight to log a first entry (the standalone home widget's
    'Log your first weigh-in' placeholder moved there)."""
    assert "No weight data yet" in _TREND_JS
    assert "/weight" in _TREND_JS


# ── F9: Widget header ────────────────────────────────────────────────────────

def test_f9_header_open_link():
    """AC (F9): home-weight-trend.js's header reads 'Weight trend' with an
    'Open →' link."""
    assert "Weight trend" in _TREND_JS
    assert "Open" in _TREND_JS


# ── F10: Open-in-weight-tab link ──────────────────────────────────────────────
# The goal foot line / progress bar were intentionally dropped from Home
# (revamp v2 scope: trend + rate + coverage only). Full goal/target detail
# lives on the full weight tab; the card links out to it via "Open →".

def test_f10_links_out_to_weight_tab():
    """AC (F10, revised): home-weight-trend.js's header links to the full
    weight tab for goal/target/progress detail."""
    assert '"/weight"' in _TREND_JS, \
        "home-weight-trend.js must link to /weight for full detail (goal/progress/trend)"


# ── F11: Trend + rate stats (replaces the shared current/7-day-avg pair) ─────

def test_f11_renders_trend_and_rate():
    """AC (F11, revised): home-weight-trend.js renders the 30-day trend kg
    value and rate ± CI (kg/wk) — the shared block's current+7-day-avg pair
    doesn't apply to Home anymore since WeightCurrentCard is retired here."""
    assert "hwt-big" in _TREND_JS, "must render the headline trend value"
    assert "hwt-rate" in _TREND_JS, "must render the rate ± CI"


# ── F12: Data sourced from the same endpoint as the weight tab ────────────────

def test_f12_sources_from_weight_chart_endpoint():
    """AC (F12): home-weight-trend.js populates itself from the same
    /api/weight-chart endpoint the weight tab uses, so the two never disagree."""
    assert "/api/weight-chart" in _TREND_JS
