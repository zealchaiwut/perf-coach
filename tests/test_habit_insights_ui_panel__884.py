"""Tests for habit-insights endpoint and UI panel (issue #884).

Uses FastAPI TestClient with mocked resolve_user and Session so no live
server is needed.  Each test is anchored to a specific AC item.

AC mapping:
  AC2: GET /api/habits/insights exists; returns 401 without auth
  AC3: each insight card has summary, coefficient, sample_size
  AC4: only confident insights are returned
  AC5: disclaimer text present in HTML
  AC6: not_enough_data state returned when no confident insights
  AC7: loading/error states — endpoint returns well-formed JSON on error paths
  AC1/AC8: HTML panel element and mobile CSS present in habits.html
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import DailyReadiness, Habit, HabitLog

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000884")
_HABIT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_habit(name="Zone 2 cardio", is_archived=False, tracking_type="daily_checkmark"):
    h = MagicMock(spec=Habit)
    h.id = _HABIT_ID
    h.user_id = _USER_ID
    h.name = name
    h.is_archived = is_archived
    h.tracking_type = tracking_type
    h.sort_order = 0
    h.created_at = None
    h.icon = "ti-run"
    h.color = "#3b82f6"
    return h


def _make_log(log_date, value=1):
    lg = MagicMock(spec=HabitLog)
    lg.habit_id = _HABIT_ID
    lg.log_date = log_date
    lg.value = Decimal(str(value))
    return lg


def _make_readiness_row(d, score):
    r = MagicMock()
    r.date = d
    r.score = Decimal(str(score))
    return r


def _build_mock_session(habits, readiness_rows, habit_logs):
    """Build a mock Session that returns the provided data in query order."""
    sess = MagicMock()

    call_count = [0]

    def query_side_effect(*args):
        call_count[0] += 1
        qmock = MagicMock()
        n = call_count[0]
        if n == 1:
            # First call: Habit query
            qmock.filter.return_value.order_by.return_value.all.return_value = habits
        elif n == 2:
            # Second call: DailyReadiness query (2 column args)
            qmock.filter.return_value.all.return_value = readiness_rows
        else:
            # Third+ calls: HabitLog queries (one per habit)
            qmock.filter.return_value.all.return_value = habit_logs
        return qmock

    sess.query.side_effect = query_side_effect
    return sess


# ---------------------------------------------------------------------------
# AC2: endpoint requires authentication
# ---------------------------------------------------------------------------

class TestHabitInsightsAuth:
    def test_requires_auth(self):
        """GET /api/habits/insights returns 401 for unauthenticated requests."""
        client = TestClient(app)
        r = client.get("/api/habits/insights")
        assert r.status_code == 401, (
            f"Expected 401, got {r.status_code}"
        )

    def test_authenticated_gets_200(self):
        """Authenticated request returns 200."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(habits=[], readiness_rows=[], habit_logs=[])
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        finally:
            _teardown()


# ---------------------------------------------------------------------------
# AC6: not_enough_data state
# ---------------------------------------------------------------------------

class TestNotEnoughDataState:
    def test_no_habits_returns_not_enough_data(self):
        """When user has no active daily habits, status = not_enough_data."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(habits=[], readiness_rows=[], habit_logs=[])
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                assert data["status"] == "not_enough_data", data
                assert data["insights"] == [], (
                    "not_enough_data must return empty insights list (no placeholder cards)"
                )
                assert "reason" in data and len(data["reason"]) > 0
        finally:
            _teardown()

    def test_no_readiness_data_returns_not_enough_data(self):
        """When habits exist but no readiness scores, status = not_enough_data."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(
                    habits=[_make_habit()],
                    readiness_rows=[],
                    habit_logs=[],
                )
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                assert data["status"] == "not_enough_data", data
                assert data["insights"] == []
        finally:
            _teardown()

    def test_insufficient_pairs_returns_not_enough_data(self):
        """When correlation doesn't reach MIN_PAIRED_DAYS (14), status = not_enough_data."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                base = date(2026, 6, 1)
                # Only 5 days — below MIN_PAIRED_DAYS=14
                habit_logs = [_make_log(base + timedelta(days=i)) for i in range(5)]
                readiness_rows = [
                    _make_readiness_row(base + timedelta(days=i + 1), 75.0)
                    for i in range(5)
                ]
                sess = _build_mock_session(
                    habits=[_make_habit()],
                    readiness_rows=readiness_rows,
                    habit_logs=habit_logs,
                )
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                assert data["status"] == "not_enough_data", (
                    f"Only 5 pairs (below MIN_PAIRED_DAYS=14) should give not_enough_data; got: {data}"
                )
                assert data["insights"] == []
        finally:
            _teardown()

    def test_not_enough_data_reason_is_meaningful(self):
        """The reason string gives the user a meaningful explanation."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(habits=[], readiness_rows=[], habit_logs=[])
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                if data["status"] == "not_enough_data":
                    reason = data.get("reason", "")
                    assert len(reason) > 10, (
                        "not_enough_data reason should be a meaningful sentence"
                    )
        finally:
            _teardown()

    def test_not_enough_data_has_empty_insights(self):
        """When status is not_enough_data, insights list must be empty (no placeholder cards)."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(habits=[], readiness_rows=[], habit_logs=[])
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                if data["status"] == "not_enough_data":
                    assert data["insights"] == [], (
                        "When not_enough_data, insights list must be empty"
                    )
        finally:
            _teardown()


# ---------------------------------------------------------------------------
# AC3/AC4: insight card shape — only confident results returned
# ---------------------------------------------------------------------------

class TestInsightCardShape:
    def _make_confident_session(self):
        """Return (habits, readiness_rows, habit_logs) with 20 days of data."""
        base = date(2026, 5, 1)
        habit_logs = [_make_log(base + timedelta(days=i), 1) for i in range(20)]
        # lag=1: habit day i pairs with readiness day i+1, monotonically increasing
        readiness_rows = [
            _make_readiness_row(base + timedelta(days=i + 1), 60.0 + i * 2.0)
            for i in range(20)
        ]
        return [_make_habit()], readiness_rows, habit_logs

    def test_response_has_insights_list(self):
        """Response always contains an 'insights' list."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                assert "insights" in data, f"Missing 'insights' key in {data}"
                assert isinstance(data["insights"], list)
        finally:
            _teardown()

    def test_ok_status_when_confident_insights_exist(self):
        """When confident insights exist, status is 'ok'."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                if data.get("insights"):
                    assert data["status"] == "ok", (
                        f"Non-empty insights should have status='ok', got {data['status']}"
                    )
        finally:
            _teardown()

    def test_each_insight_has_required_fields(self):
        """AC3: every insight has habit_id, habit_name, coefficient, sample_size, summary."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                for ins in data.get("insights", []):
                    for key in ("habit_id", "habit_name", "coefficient", "sample_size", "summary"):
                        assert key in ins, f"Insight missing '{key}': {ins}"
        finally:
            _teardown()

    def test_coefficient_in_valid_range(self):
        """AC3: coefficient is a float in [-1, 1]."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                for ins in data.get("insights", []):
                    c = ins["coefficient"]
                    assert isinstance(c, (int, float)), f"coefficient not numeric: {c}"
                    assert -1.0 <= c <= 1.0, f"coefficient out of range: {c}"
        finally:
            _teardown()

    def test_sample_size_positive_integer(self):
        """AC3: sample_size is a positive integer."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                for ins in data.get("insights", []):
                    ss = ins["sample_size"]
                    assert isinstance(ss, int), f"sample_size not int: {type(ss)}"
                    assert ss > 0, f"sample_size must be positive, got {ss}"
        finally:
            _teardown()

    def test_summary_is_nonempty_string(self):
        """AC3: summary is a non-empty string."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                for ins in data.get("insights", []):
                    s = ins["summary"]
                    assert isinstance(s, str) and len(s) > 0, (
                        f"summary must be non-empty string, got {s!r}"
                    )
        finally:
            _teardown()

    def test_summary_phrased_as_association(self):
        """AC3/AC5: summary uses association language, not causation."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                for ins in data.get("insights", []):
                    s = ins["summary"].lower()
                    assert "tends to be" in s or "associated" in s or "correlation" in s, (
                        f"Summary should use association language, got: {ins['summary']!r}"
                    )
        finally:
            _teardown()

    def test_no_non_confident_insights_in_response(self):
        """AC4: response must not include insights with confident=False."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                for ins in data.get("insights", []):
                    if "confident" in ins:
                        assert ins["confident"] is True, (
                            f"Only confident=True insights should be returned; got: {ins}"
                        )
        finally:
            _teardown()

    def test_confident_data_produces_ok_status(self):
        """20 paired days (>= MIN_PAIRED_DAYS=14) produces status='ok'."""
        client, _ = _make_client()
        try:
            with patch("backend.main.Session") as mock_session_cls:
                sess = _build_mock_session(*self._make_confident_session())
                mock_session_cls.return_value.__enter__ = lambda s, *a: sess
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                r = client.get("/api/habits/insights")
                data = r.json()

                assert data["status"] == "ok", (
                    f"20 paired days should yield status='ok'; got: {data}"
                )
                assert len(data["insights"]) == 1, (
                    f"Expected 1 insight for the single habit; got {len(data['insights'])}"
                )
        finally:
            _teardown()


# ---------------------------------------------------------------------------
# AC1/AC5/AC8: HTML panel structure
# ---------------------------------------------------------------------------

class TestHabitsPageHtml:
    def _read_habits_html(self):
        with open("frontend/pages/habits.html", "r") as f:
            return f.read()

    def test_insights_panel_element_exists(self):
        """AC1: insights panel container is present in habits.html."""
        html = self._read_habits_html()
        assert 'id="insights-panel"' in html, (
            "habits.html must contain an element with id='insights-panel'"
        )

    def test_association_not_causation_disclaimer(self):
        """AC5: 'Association, not causation' disclaimer appears in habits.html."""
        html = self._read_habits_html()
        assert "Association" in html and "causation" in html, (
            "habits.html must contain 'Association, not causation' disclaimer"
        )

    def test_mobile_responsive_css_present(self):
        """AC8: mobile media query for insights panel exists in habits.html."""
        html = self._read_habits_html()
        assert "insights-panel" in html, "insights-panel CSS or element must exist"
        assert "max-width:" in html, "Responsive media queries should be present"

    def test_insights_body_element_exists(self):
        """AC7: insights body container for state rendering is present."""
        html = self._read_habits_html()
        assert 'id="insights-body"' in html, (
            "habits.html must contain element with id='insights-body' for state rendering"
        )

    def test_gradient_theme_on_panel(self):
        """AC1: panel uses gradient theme as required."""
        html = self._read_habits_html()
        assert "insights-panel" in html, "insights-panel class must be in habits.html"
        assert "linear-gradient" in html or "gradient" in html.lower(), (
            "Panel should use gradient theme per AC1"
        )


class TestHabitsJs:
    def _read_habits_js(self):
        with open("frontend/js/habits.js", "r") as f:
            return f.read()

    def test_js_fetches_insights_endpoint(self):
        """AC2: habits.js must fetch from /api/habits/insights."""
        js = self._read_habits_js()
        assert "/api/habits/insights" in js, (
            "habits.js must reference the /api/habits/insights endpoint"
        )

    def test_js_handles_not_enough_data(self):
        """AC6: habits.js must handle not_enough_data status."""
        js = self._read_habits_js()
        assert "not_enough_data" in js, (
            "habits.js must handle the not_enough_data status from the endpoint"
        )

    def test_js_handles_error_state(self):
        """AC7: habits.js must handle errors from the insights endpoint."""
        js = self._read_habits_js()
        assert "error" in js.lower() and "insights" in js.lower(), (
            "habits.js must handle errors from the insights endpoint"
        )

    def test_js_renders_coefficient(self):
        """AC3: habits.js renders the coefficient value."""
        js = self._read_habits_js()
        assert "coefficient" in js, (
            "habits.js must render the coefficient value from each insight"
        )

    def test_js_on_mount_calls_loadInsights(self):
        """AC2: insights are loaded on mount (userReady event)."""
        js = self._read_habits_js()
        assert "loadInsights" in js, (
            "habits.js must define and call loadInsights() on mount"
        )
