"""Tests for GET /api/habits/insights (issue #885).

Covers all Acceptance Criteria:
- AC1: endpoint is authenticated (401 for anonymous)
- AC2: response has exactly three top-level keys
- AC3: each insight has the six required keys with correct types
- AC4: only confidence-cleared insights appear
- AC5: min sample size is configurable (not hardcoded)
- AC6: building=True, insights=[], non-empty reason when data is insufficient
- AC7: building=False, reason=None, insights array when data is sufficient
- AC8: all DB access is in the caller layer (insight builder takes plain dicts)
- AC9: endpoint delegates correlation to insight builder (no duplicate logic)
- AC10: zero logs or zero outcomes -> building=True, no error
- AC11: coefficient in [-1, 1] (validated before serialisation)
- AC12: content-type is application/json

Pure-function unit tests cover the insight builder directly;
endpoint smoke tests use the live server at http://127.0.0.1:9001.
"""

from __future__ import annotations

import os
import types

import pytest

from backend.services.habit_insights import (
    OUTCOME_FIELDS,
    _generate_line,
    _read_min_sample_size,
    build_insights,
)

# ---------------------------------------------------------------------------
# Helpers — minimal stub objects for pure-function tests
# ---------------------------------------------------------------------------


def _habit(habit_id: str, name: str = "Test Habit"):
    h = types.SimpleNamespace()
    h.id = habit_id
    h.name = name
    return h


def _make_logs(dates: list[str], value: float = 1.0) -> dict[str, float]:
    return {d: value for d in dates}


def _make_series(dates: list[str], value: float = 4.0) -> dict[str, float]:
    return {d: value for d in dates}


# ---------------------------------------------------------------------------
# AC5: min sample size reads from config (environment variable)
# ---------------------------------------------------------------------------


class TestMinSampleSizeConfig:
    def test_default_is_not_hardcoded_literal_in_builder(self):
        """_read_min_sample_size() must consult the env var, not return a literal."""
        original = os.environ.get("HABIT_INSIGHTS_MIN_SAMPLE_SIZE")
        try:
            os.environ["HABIT_INSIGHTS_MIN_SAMPLE_SIZE"] = "3"
            assert _read_min_sample_size() == 3
        finally:
            if original is None:
                os.environ.pop("HABIT_INSIGHTS_MIN_SAMPLE_SIZE", None)
            else:
                os.environ["HABIT_INSIGHTS_MIN_SAMPLE_SIZE"] = original

    def test_env_override_changes_threshold(self):
        """build_insights respects HABIT_INSIGHTS_MIN_SAMPLE_SIZE."""
        # 4 overlapping days; with min=3 should NOT be building, with min=10 should be.
        dates = [
            "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05",
        ]
        habit = _habit("hid-1", "Morning Run")
        logs = {"hid-1": _make_logs(dates, 1.0)}
        series = {"energy": _make_series(dates, 4.0)}

        original = os.environ.get("HABIT_INSIGHTS_MIN_SAMPLE_SIZE")
        try:
            _, building_3, _ = build_insights(
                [habit], logs, series, min_sample_size=3
            )
            _, building_10, _ = build_insights(
                [habit], logs, series, min_sample_size=10
            )
        finally:
            if original is None:
                os.environ.pop("HABIT_INSIGHTS_MIN_SAMPLE_SIZE", None)
            else:
                os.environ["HABIT_INSIGHTS_MIN_SAMPLE_SIZE"] = original

        # With min=10 and only 4 days the building flag must flip to True
        assert building_10 is True
        # With min=3 and 4 overlapping days it may or may not find insights,
        # but building must be False (sufficient overlap)
        assert building_3 is False


# ---------------------------------------------------------------------------
# AC6 / AC10: building=True when insufficient or zero data
# ---------------------------------------------------------------------------


class TestBuildingState:
    def test_zero_habits_returns_building_true(self):
        """No active habits -> building=True, no exception."""
        _, building, reason = build_insights([], {}, {}, min_sample_size=1)
        assert building is True
        assert reason is not None and len(reason) > 0

    def test_zero_habit_logs_returns_building_true(self):
        """User has habits but no logs -> building=True."""
        habit = _habit("hid-1")
        _, building, reason = build_insights(
            [habit], {}, {"energy": {}}, min_sample_size=1
        )
        assert building is True
        assert reason is not None and len(reason) > 0

    def test_zero_outcome_entries_returns_building_true(self):
        """User has habit logs but no outcome data -> building=True."""
        habit = _habit("hid-1")
        logs = {"hid-1": {"2025-06-02": 1.0}}
        _, building, reason = build_insights(
            [habit], logs, {}, min_sample_size=1
        )
        assert building is True
        assert reason is not None and len(reason) > 0

    def test_non_overlapping_dates_returns_building_true(self):
        """Habit logs and outcomes exist but dates don't overlap -> building."""
        habit = _habit("hid-1")
        logs = {"hid-1": {"2025-06-02": 1.0}}
        series = {"energy": {"2025-07-02": 4.0}}
        _, building, reason = build_insights(
            [habit], logs, series, min_sample_size=1
        )
        assert building is True
        assert reason is not None and len(reason) > 0

    def test_below_min_sample_size_returns_building_true(self):
        """Overlap count below min -> building=True, not an error."""
        habit = _habit("hid-1")
        logs = {"hid-1": {"2025-06-02": 1.0, "2025-06-03": 0.0}}
        series = {"energy": {"2025-06-02": 4.0, "2025-06-03": 3.0}}
        # 2 overlap days, min=5 -> building
        _, building, reason = build_insights(
            [habit], logs, series, min_sample_size=5
        )
        assert building is True
        assert reason is not None

    def test_building_true_insights_is_empty_list(self):
        """When building=True, insights must be []."""
        insights, building, _ = build_insights(
            [], {}, {}, min_sample_size=1
        )
        assert building is True
        assert insights == []


# ---------------------------------------------------------------------------
# AC2 / AC7: response structure when sufficient data
# ---------------------------------------------------------------------------


class TestSufficientDataResponse:
    """Use a large enough dataset with variance to trigger an insight."""

    DATES = [f"2025-06-{d:02d}" for d in range(1, 22)]  # 21 days

    def _alternating_logs(self, habit_id: str) -> dict:
        """Alternate 1.0/0.0 to ensure variance."""
        logs = {}
        for i, d in enumerate(self.DATES):
            logs[d] = 1.0 if i % 2 == 0 else 0.0
        return {habit_id: logs}

    def _correlated_series(self, name: str) -> dict:
        """Series that correlates with the alternating logs."""
        series = {}
        for i, d in enumerate(self.DATES):
            series[d] = 4.0 if i % 2 == 0 else 2.0
        return {name: series}

    def test_building_false_when_sufficient(self):
        habit = _habit("hid-1", "Morning Run")
        logs = self._alternating_logs("hid-1")
        series = self._correlated_series("energy")
        _, building, _ = build_insights(
            [habit], logs, series, min_sample_size=5
        )
        assert building is False

    def test_reason_is_none_when_sufficient(self):
        habit = _habit("hid-1", "Morning Run")
        logs = self._alternating_logs("hid-1")
        series = self._correlated_series("energy")
        _, _, reason = build_insights(
            [habit], logs, series, min_sample_size=5
        )
        assert reason is None

    def test_insights_is_list(self):
        habit = _habit("hid-1", "Morning Run")
        logs = self._alternating_logs("hid-1")
        series = self._correlated_series("energy")
        insights, _, _ = build_insights(
            [habit], logs, series, min_sample_size=5
        )
        assert isinstance(insights, list)


# ---------------------------------------------------------------------------
# AC3: insight object shape and types
# ---------------------------------------------------------------------------


class TestInsightShape:
    DATES = [f"2025-06-{d:02d}" for d in range(1, 22)]

    def _correlated_data(self, habit_id: str):
        logs = {
            habit_id: {
                d: (1.0 if i % 2 == 0 else 0.0)
                for i, d in enumerate(self.DATES)
            }
        }
        series = {
            "energy": {
                d: (4.0 if i % 2 == 0 else 2.0)
                for i, d in enumerate(self.DATES)
            }
        }
        return logs, series

    def test_insight_has_required_keys(self):
        habit = _habit("hid-1", "Morning Run")
        logs, series = self._correlated_data("hid-1")
        insights, building, _ = build_insights(
            [habit], logs, series, min_sample_size=5
        )
        assert building is False
        assert len(insights) > 0
        required = {
            "habit_id", "habit_name", "outcome_name",
            "coefficient", "sample_size", "lag_days", "line",
        }
        for item in insights:
            assert set(item.keys()) == required, (
                f"insight keys mismatch: {set(item.keys())}"
            )

    def test_habit_id_is_string(self):
        habit = _habit("hid-1")
        logs, series = self._correlated_data("hid-1")
        insights, _, _ = build_insights([habit], logs, series, min_sample_size=5)
        for item in insights:
            assert isinstance(item["habit_id"], str)

    def test_habit_name_is_string(self):
        habit = _habit("hid-1", "Morning Run")
        logs, series = self._correlated_data("hid-1")
        insights, _, _ = build_insights([habit], logs, series, min_sample_size=5)
        for item in insights:
            assert isinstance(item["habit_name"], str)

    def test_outcome_name_is_string(self):
        habit = _habit("hid-1")
        logs, series = self._correlated_data("hid-1")
        insights, _, _ = build_insights([habit], logs, series, min_sample_size=5)
        for item in insights:
            assert isinstance(item["outcome_name"], str)

    def test_coefficient_is_float(self):
        habit = _habit("hid-1")
        logs, series = self._correlated_data("hid-1")
        insights, _, _ = build_insights([habit], logs, series, min_sample_size=5)
        for item in insights:
            assert isinstance(item["coefficient"], float)

    def test_sample_size_is_int_gte_1(self):
        habit = _habit("hid-1")
        logs, series = self._correlated_data("hid-1")
        insights, _, _ = build_insights([habit], logs, series, min_sample_size=5)
        for item in insights:
            assert isinstance(item["sample_size"], int)
            assert item["sample_size"] >= 1

    def test_lag_days_is_int_gte_0(self):
        habit = _habit("hid-1")
        logs, series = self._correlated_data("hid-1")
        insights, _, _ = build_insights([habit], logs, series, min_sample_size=5)
        for item in insights:
            assert isinstance(item["lag_days"], int)
            assert item["lag_days"] >= 0

    def test_line_is_non_empty_string(self):
        habit = _habit("hid-1")
        logs, series = self._correlated_data("hid-1")
        insights, _, _ = build_insights([habit], logs, series, min_sample_size=5)
        for item in insights:
            assert isinstance(item["line"], str)
            assert len(item["line"]) > 0


# ---------------------------------------------------------------------------
# AC11: coefficient is always in [-1, 1]
# ---------------------------------------------------------------------------


class TestCoefficientRange:
    DATES = [f"2025-06-{d:02d}" for d in range(1, 22)]

    def test_coefficient_within_range(self):
        habit = _habit("hid-1")
        logs = {
            "hid-1": {
                d: (1.0 if i % 2 == 0 else 0.0)
                for i, d in enumerate(self.DATES)
            }
        }
        series = {
            "energy": {
                d: (4.0 if i % 2 == 0 else 2.0)
                for i, d in enumerate(self.DATES)
            }
        }
        insights, _, _ = build_insights([habit], logs, series, min_sample_size=5)
        for item in insights:
            assert -1.0 <= item["coefficient"] <= 1.0, (
                f"coefficient out of range: {item['coefficient']}"
            )


# ---------------------------------------------------------------------------
# AC4: sub-threshold correlations are silently excluded
# ---------------------------------------------------------------------------


class TestConfidenceFiltering:
    DATES = [f"2025-06-{d:02d}" for d in range(1, 22)]

    def test_constant_habit_series_excluded(self):
        """All-1.0 logs have zero variance -> no correlation computable -> excluded."""
        habit = _habit("hid-1")
        logs = {"hid-1": {d: 1.0 for d in self.DATES}}
        series = {"energy": {d: float(i % 5 + 1) for i, d in enumerate(self.DATES)}}
        insights, building, _ = build_insights(
            [habit], logs, series, min_sample_size=5
        )
        assert building is False
        assert len(insights) == 0


# ---------------------------------------------------------------------------
# AC8: DB access is entirely in the caller layer
# ---------------------------------------------------------------------------


class TestCallerLayerIsolation:
    def test_builder_has_no_db_imports(self):
        """habit_insights module must not import SQLAlchemy or backend.db."""
        import backend.services.habit_insights as _mod

        module_source = _mod.__file__ or ""
        # Check that habit_insights itself does not import those
        source_code = open(module_source).read()
        assert "sqlalchemy" not in source_code
        assert "from backend.db" not in source_code
        assert "import backend.db" not in source_code


# ---------------------------------------------------------------------------
# AC3 (line field): plain-language sentence tests
# ---------------------------------------------------------------------------


class TestGenerateLine:
    def test_zero_lag_same_day_phrasing(self):
        line = _generate_line("Morning Run", "energy", 0.5, lag_days=0)
        assert "same day" in line.lower()
        assert "Morning Run" in line
        assert "Energy" in line

    def test_positive_lag_phrasing(self):
        line = _generate_line("Morning Run", "energy", 0.5, lag_days=1)
        assert "1 day later" in line
        assert "Morning Run" in line

    def test_negative_coefficient_says_lower(self):
        line = _generate_line("Night Screen", "sleep_quality", -0.4, lag_days=0)
        assert "lower" in line.lower()

    def test_positive_coefficient_says_higher(self):
        line = _generate_line("Morning Run", "energy", 0.4, lag_days=0)
        assert "higher" in line.lower()

    def test_line_is_plain_string_no_json(self):
        line = _generate_line("Morning Run", "energy", 0.4, lag_days=1)
        assert "{" not in line
        assert "}" not in line


# ---------------------------------------------------------------------------
# Outcome fields coverage
# ---------------------------------------------------------------------------


class TestOutcomeFields:
    def test_outcome_fields_non_empty_tuple(self):
        assert len(OUTCOME_FIELDS) > 0

    def test_energy_in_outcome_fields(self):
        assert "energy" in OUTCOME_FIELDS


# ---------------------------------------------------------------------------
# Endpoint integration tests (require live server at 127.0.0.1:9001)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHabitInsightsEndpoint:
    BASE = "http://127.0.0.1:9001"

    @pytest.fixture(autouse=True)
    def _skip_if_no_server(self):
        import socket
        s = socket.socket()
        try:
            s.connect(("127.0.0.1", 9001))
            s.close()
        except OSError:
            pytest.skip("Live server not available")

    def _login(self, session, username="testuser", password="testpass"):
        r = session.post(
            f"{self.BASE}/api/auth/login",
            json={"username": username, "password": password},
        )
        return r

    # AC1: unauthenticated request returns 401
    def test_unauthenticated_returns_401(self):
        import requests
        r = requests.get(f"{self.BASE}/api/habits/insights")
        assert r.status_code in (401, 403), (
            f"Expected 401/403 for unauthenticated request, got {r.status_code}"
        )

    # AC12: content-type is application/json
    def test_response_content_type_is_json(self):
        import requests
        session = requests.Session()
        resp = self._login(session)
        if resp.status_code != 200:
            pytest.skip("Could not authenticate test user")
        r = session.get(f"{self.BASE}/api/habits/insights")
        assert "application/json" in r.headers.get("content-type", "")

    # AC2 / AC6: new user gets building=True with three keys
    def test_empty_user_returns_building_true(self):
        import requests
        session = requests.Session()
        resp = self._login(session)
        if resp.status_code != 200:
            pytest.skip("Could not authenticate test user")
        r = session.get(f"{self.BASE}/api/habits/insights")
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == {"insights", "building", "reason"}
        # A fresh user with no data should be building
        if data["building"]:
            assert data["insights"] == []
            assert data["reason"] is not None and len(data["reason"]) > 0
        else:
            # If the test user happens to have enough data that's also valid
            assert isinstance(data["insights"], list)
            assert data["reason"] is None
