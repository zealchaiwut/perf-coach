"""
TDD tests for issue #439: Add home weight widget with stepper quick-log.

AC anchors:
  (A1)  API: sparkline field present — 7-day actual data points
  (A2)  API: plan field present when target exists, empty when no target
  (A3)  API: gap_kg present — signed gap from expected trajectory (or null)
  (A4)  API: status_label present at top level (null when no target/data)
  (A5)  API: last_entry_kg mirrors current_weight
  (A6)  API: weekly_rate_kg present
  (A7)  API: target.kg_to_go present when target exists
  (F1)  HTML: weight widget container element present in home.html
  (F2)  JS: function to load home weight widget exists in home.js
  (F3)  JS: gap pill — "behind", "ahead", "on plan", hidden for no_data/null
  (F4)  JS: stepper POSTs to /api/weight-entries with today's date
  (F5)  JS: 409 path — PATCH sent to /api/weight-entries/{id}
  (F6)  JS: compact state "Logged today" shown after successful log
  (F7)  JS: edit link in compact state re-opens stepper
  (F8)  JS: empty state shows "Log your first weigh-in" placeholder
  (F9)  JS: widget header "Weight" and "Open →" link to /weight
  (F10) JS: goal foot line with edit target link to /weight/targets
  (F11) JS: progress bar rendered when target exists
  (F12) JS: sparkline includes dashed plan line when plan data present
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
# Shared "current weight" component reused by both the home page and weight tab.
_CARD_JS = (_ROOT / "frontend" / "js" / "lib" / "weight-current-card.js").read_text()

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

# ── F1: HTML widget container ─────────────────────────────────────────────────

def test_f1_weight_widget_container_in_html():
    """AC (F1): home.html has a weight widget container element."""
    assert (
        'id="home-weight-widget"' in _HOME_HTML
        or 'id="weight-widget-row"' in _HOME_HTML
    ), "home.html must include a weight widget container div (home-weight-widget or weight-widget-row)"


# ── F2: JS load function ──────────────────────────────────────────────────────
# The home "current weight" stat block now reuses the shared component
# (frontend/js/lib/weight-current-card.js, WeightCurrentCard) so the home page
# and weight tab share one implementation. home.js owns the entry point that
# mounts the shared block + the quick-log stepper.

def test_f2_render_home_weight_widget_function():
    """AC (F2): home.js defines the weight-widget entry point."""
    assert "_renderHomeWeightWidget" in _HOME_JS, \
        "home.js must define _renderHomeWeightWidget"


def test_f2_render_home_weight_widget_called_in_init():
    """AC (F2): the weight widget is rendered from init()."""
    init_idx = _HOME_JS.find("async function init(")
    assert init_idx != -1
    init_body = _HOME_JS[init_idx:]
    assert "_renderHomeWeightWidget" in init_body, \
        "_renderHomeWeightWidget must be called in init()"


def test_f2_uses_shared_current_weight_component():
    """AC (F2): home reuses the shared WeightCurrentCard component."""
    assert "WeightCurrentCard" in _HOME_JS, \
        "home.js must render via the shared WeightCurrentCard component"


# ── F3: Gap pill logic ────────────────────────────────────────────────────────

def test_f3_gap_pill_behind():
    """AC (F3): JS shows 'behind' text for behind status."""
    assert "behind" in _HOME_JS


def test_f3_gap_pill_ahead():
    """AC (F3): JS shows 'ahead' text for ahead status."""
    assert "ahead" in _HOME_JS


def test_f3_change_pills_via_shared_block():
    """AC (F3, revised): the shared current-weight block renders week/month
    change pills (the home-only gap pill was replaced by the shared component)."""
    assert "hca-pill-week" in _CARD_JS and "hca-pill-month" in _CARD_JS, \
        "shared current-weight block must render week/month change pills"


def test_f3_gap_pill_hidden_no_data():
    """AC (F3): JS hides gap pill for no_data."""
    assert "no_data" in _HOME_JS


# ── F4: POST to /api/weight-entries ──────────────────────────────────────────

def test_f4_posts_to_weight_entries():
    """AC (F4): JS POSTs to /api/weight-entries."""
    assert "/api/weight-entries" in _HOME_JS


def test_f4_includes_entry_date():
    """AC (F4): POST body includes entry_date."""
    assert "entry_date" in _HOME_JS


# ── F5: 409 path — PATCH ─────────────────────────────────────────────────────

def test_f5_handles_409():
    """AC (F5): JS handles 409 conflict response."""
    assert "409" in _HOME_JS


def test_f5_patch_with_existing_id():
    """AC (F5): PATCH uses existing_id from 409 response."""
    assert "existing_id" in _HOME_JS
    assert "PATCH" in _HOME_JS


# ── F6: Compact state ─────────────────────────────────────────────────────────

def test_f6_logged_today_compact_state():
    """AC (F6): JS renders 'Logged today' compact state."""
    assert "Logged today" in _HOME_JS


# ── F7: Edit re-opens stepper ─────────────────────────────────────────────────

def test_f7_edit_reopens_stepper():
    """AC (F7): compact 'edit' re-opens stepper prefilled."""
    assert "edit" in _HOME_JS.lower()


# ── F8: Empty state ───────────────────────────────────────────────────────────

def test_f8_empty_state_via_shared_block():
    """AC (F8, revised): with no data the shared current-weight block shows the
    placeholder weight ('--') and the idle coach prompt (the home-only
    'Log your first weigh-in' copy was replaced by the shared component)."""
    assert "--" in _CARD_JS, "shared block must show '--' placeholder weight"
    assert "No entry yet today" in _CARD_JS, \
        "shared block must show the idle coach prompt when nothing is logged"


# ── F9: Widget header ────────────────────────────────────────────────────────

def test_f9_header_open_link():
    """AC (F9): 'Open →' link to /weight in header."""
    assert "Open" in _HOME_JS


# ── F10: Open-in-weight-tab link ──────────────────────────────────────────────
# The goal foot line / progress bar / sparkline were intentionally removed from
# the home widget (scope: "current-weight block only"). Those live on the full
# weight tab now; the home widget links out to it via the header "Open →".

def test_f10_links_out_to_weight_tab():
    """AC (F10, revised): the home widget header links to the full weight tab."""
    assert '"/weight"' in _HOME_JS or "/weight'" in _HOME_JS, \
        "home weight widget must link to /weight for full detail (goal/progress/trend)"


# ── F11: Shared current-weight stats ──────────────────────────────────────────

def test_f11_shared_block_renders_current_and_avg():
    """AC (F11, revised): the shared block renders current weight + 7-day avg."""
    assert "hca-weight" in _CARD_JS and "hca-avg" in _CARD_JS, \
        "shared current-weight block must render current weight and 7-day avg"


# ── F12: Data sourced from the same endpoints as the weight tab ───────────────

def test_f12_sources_from_weight_chart_endpoint():
    """AC (F12, revised): home populates the shared block from the same
    /api/weight-chart endpoint the weight tab uses, so the two stay identical."""
    assert "/api/weight-chart" in _HOME_JS, \
        "home must source the current-weight block from /api/weight-chart"
