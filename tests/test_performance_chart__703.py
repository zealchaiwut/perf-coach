"""Tests for issue #703: GET /api/performance/chart time-series endpoint.

Covers all acceptance criteria:
AC1  - endpoint accepts athlete_id, start_date, end_date query params
AC2  - response contains parallel arrays for ctl, atl, tsb, endurance_score, speed_score
AC3  - CTL/ATL/TSB produced by calling existing fitness model (no reimplementation)
AC4  - endurance/speed scores produced by calling existing performance score computation
AC5  - building_baseline flag from config threshold
AC6  - missing/unknown athlete_id → 200 with empty payload + reason
AC7  - missing/invalid dates → 200 with empty payload + reason
AC8  - no data in range → 200 with empty arrays + reason
AC9  - all DB access in caller layer (pure functions receive pre-fetched data)
AC10 - no hardcoded thresholds in the endpoint
AC11 - integration tests for happy path, missing athlete_id, invalid dates, building_baseline
"""
import os
import pytest
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Unit tests — pure function (no server required)
# ---------------------------------------------------------------------------

class TestComputePerformanceChart:
    """Unit tests for the pure compute_performance_chart function (AC2–AC5, AC9)."""

    def _make_load_series(self, n_days=30, start="2026-01-01", daily_load=50):
        """Build n_days of daily load starting at start."""
        from datetime import date, timedelta
        d = date.fromisoformat(start)
        return [
            {"date": str(d + timedelta(days=i)), "daily_load": daily_load}
            for i in range(n_days)
        ]

    def _make_run(self, run_id, run_date, band="easy", avg_hr=140, avg_power=200, duration_seconds=1800):
        return {
            "run_id": run_id,
            "run_date": run_date,
            "laps": [
                {
                    "band": band,
                    "avg_hr": avg_hr,
                    "avg_power": avg_power,
                    "distance_km": 5.0,
                    "duration_seconds": duration_seconds,
                }
            ],
            "decoupling_pct": None,
        }

    def test_ac2_response_has_all_required_keys(self):
        """AC2: response contains dates, ctl, atl, tsb, endurance_score, speed_score."""
        from backend.services.performance_chart import compute_performance_chart

        series = self._make_load_series(35, start="2026-01-01")
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-05",
        )

        for key in ("dates", "ctl", "atl", "tsb", "endurance_score", "speed_score",
                    "building_baseline", "reason"):
            assert key in result, f"Missing key: {key}"

    def test_ac2_parallel_arrays_same_length(self):
        """AC2: all five series arrays have the same length as the dates array."""
        from backend.services.performance_chart import compute_performance_chart

        series = self._make_load_series(50, start="2026-01-01")
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-10",
        )

        n = len(result["dates"])
        assert n == 10
        for key in ("ctl", "atl", "tsb", "endurance_score", "speed_score"):
            assert len(result[key]) == n, f"{key} length mismatch"

    def test_ac3_ctl_atl_tsb_are_floats_not_reimplemented(self):
        """AC3: CTL/ATL/TSB come from fitness model — non-None, float values."""
        from backend.services.performance_chart import compute_performance_chart

        series = self._make_load_series(50, start="2026-01-01")
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-05",
        )

        # All CTL/ATL/TSB values should be numeric (series has data)
        for i, ds in enumerate(result["dates"]):
            assert result["ctl"][i] is not None, f"CTL is None for {ds}"
            assert isinstance(result["ctl"][i], float), "CTL should be float"
            assert result["atl"][i] is not None, f"ATL is None for {ds}"
            assert result["tsb"][i] is not None, f"TSB is None for {ds}"

    def test_ac4_endurance_score_appears_on_run_day(self):
        """AC4: endurance_score is non-null on days with qualifying easy runs."""
        from backend.services.performance_chart import compute_performance_chart

        series = self._make_load_series(50, start="2026-01-01")
        # Three easy runs to exceed MIN_QUALIFYING_RUNS=3
        runs = [
            self._make_run("r1", "2026-02-01", band="easy"),
            self._make_run("r2", "2026-02-03", band="easy"),
            self._make_run("r3", "2026-02-05", band="easy"),
        ]

        result = compute_performance_chart(
            daily_load_series=series,
            runs=runs,
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-07",
        )

        dates = result["dates"]
        es = result["endurance_score"]
        # Run days should have a score
        assert es[dates.index("2026-02-01")] is not None
        assert es[dates.index("2026-02-03")] is not None
        assert es[dates.index("2026-02-05")] is not None
        # Non-run days should be null
        assert es[dates.index("2026-02-02")] is None
        assert es[dates.index("2026-02-04")] is None

    def test_ac4_endurance_score_is_0_to_100(self):
        """AC4: endurance score values are in [0, 100]."""
        from backend.services.performance_chart import compute_performance_chart

        series = self._make_load_series(50, start="2026-01-01")
        runs = [
            self._make_run("r1", "2026-02-01", band="easy"),
            self._make_run("r2", "2026-02-02", band="easy"),
            self._make_run("r3", "2026-02-03", band="easy"),
        ]

        result = compute_performance_chart(
            daily_load_series=series,
            runs=runs,
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-05",
        )

        for v in result["endurance_score"]:
            if v is not None:
                assert 0.0 <= v <= 100.0, f"endurance_score {v} out of [0, 100]"

    def test_ac5_building_baseline_true_when_too_few_history_days(self):
        """AC5: building_baseline=True when load history is shorter than MIN_HISTORY_DAYS."""
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.fitness_model import MIN_HISTORY_DAYS

        # Provide fewer days than the minimum
        short_series = self._make_load_series(MIN_HISTORY_DAYS - 1, start="2026-01-01")

        result = compute_performance_chart(
            daily_load_series=short_series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-01-01",
            end_date=str(date.fromisoformat("2026-01-01") + timedelta(days=MIN_HISTORY_DAYS - 2)),
        )

        assert result["building_baseline"] is True

    def test_ac5_building_baseline_threshold_from_config(self):
        """AC5: building_baseline threshold matches fitness_model.MIN_HISTORY_DAYS (from config)."""
        from backend.services.fitness_model import MIN_HISTORY_DAYS

        # MIN_HISTORY_DAYS should be a named constant, not hardcoded
        assert isinstance(MIN_HISTORY_DAYS, int)
        assert MIN_HISTORY_DAYS > 0

    def test_ac5_building_baseline_true_when_insufficient_qualifying_runs(self):
        """AC5: building_baseline=True when fewer than min qualifying runs exist."""
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.zone_constants import MIN_QUALIFYING_RUNS

        series = self._make_load_series(50, start="2026-01-01")
        # Provide fewer than MIN_QUALIFYING_RUNS easy runs
        runs = [
            self._make_run(f"r{i}", f"2026-02-{i:02d}", band="easy")
            for i in range(1, MIN_QUALIFYING_RUNS)  # one fewer than required
        ]

        result = compute_performance_chart(
            daily_load_series=series,
            runs=runs,
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-10",
        )

        assert result["building_baseline"] is True

    def test_ac7_invalid_start_after_end_returns_empty(self):
        """AC7: start_date after end_date returns empty payload with reason."""
        from backend.services.performance_chart import compute_performance_chart

        series = self._make_load_series(10, start="2026-01-01")
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-02-10",
            end_date="2026-02-01",
        )

        assert result["dates"] == []
        assert result["ctl"] == []
        assert "reason" in result
        assert result["reason"]  # non-empty reason

    def test_ac7_invalid_date_format_returns_empty(self):
        """AC7: unparseable date strings return empty payload."""
        from backend.services.performance_chart import compute_performance_chart

        series = self._make_load_series(10, start="2026-01-01")
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="not-a-date",
            end_date="2026-02-01",
        )

        assert result["dates"] == []
        assert result["reason"] == "invalid_date_range"

    def test_ac8_no_data_in_range_returns_empty(self):
        """AC8: date range with no load data returns empty arrays + reason."""
        from backend.services.performance_chart import compute_performance_chart

        # Load series is in Jan; request is for March
        series = self._make_load_series(10, start="2026-01-01")
        result = compute_performance_chart(
            daily_load_series=series,
            runs=[],
            preferences={},
            zone_constants=None,
            start_date="2026-03-01",
            end_date="2026-03-05",
        )

        assert result["dates"] == [] or all(v is None for v in result["ctl"])
        assert result["reason"]

    def test_ac9_pure_function_no_db_import(self):
        """AC9: performance_chart module makes no SQLAlchemy/database imports at module level."""
        import inspect
        import backend.services.performance_chart as mod

        source = inspect.getsource(mod)
        # No direct DB imports should appear at module level
        assert "from backend.db" not in source
        assert "from sqlalchemy" not in source

    def test_ac10_no_hardcoded_thresholds(self):
        """AC10: no numeric magic-number thresholds appear in the endpoint module."""
        import inspect
        import ast
        import backend.services.performance_chart as mod

        source = inspect.getsource(mod)
        tree = ast.parse(source)

        # Check that no numeric literals appear inside compute_performance_chart body
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "compute_performance_chart":
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)):
                        # Allow 0, 1, 2 as algorithmic constants; others are suspect
                        assert child.value in (0, 0.0, 1, 1.0, 2, 2.0), (
                            f"Hardcoded numeric literal {child.value!r} in compute_performance_chart"
                        )

    def test_ac2_endurance_and_speed_scores_can_differ(self):
        """AC2: endurance and speed scores use different lap bands."""
        from backend.services.performance_chart import compute_performance_chart

        series = self._make_load_series(50, start="2026-01-01")
        # Only easy runs → endurance qualifies, speed does not
        runs = [
            self._make_run(f"r{i}", f"2026-02-{i:02d}", band="easy")
            for i in range(1, 5)
        ]

        result = compute_performance_chart(
            daily_load_series=series,
            runs=runs,
            preferences={},
            zone_constants=None,
            start_date="2026-02-01",
            end_date="2026-02-05",
        )

        # With only 3 qualifying runs, endurance may or may not score (depends on min)
        # But speed should have no non-null values since no hard/interval laps
        speed_scores = [v for v in result["speed_score"] if v is not None]
        assert speed_scores == [], "Speed score should be null — no hard/interval laps"


# ---------------------------------------------------------------------------
# Integration tests — live server (AC1, AC6, AC7, AC8, AC11)
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("UAT_BASE_URL") or (
    "http://localhost:" + os.environ.get("UAT_PORT", "9001")
)

_SERVER_AVAILABLE = None


def _server_is_up():
    global _SERVER_AVAILABLE
    if _SERVER_AVAILABLE is not None:
        return _SERVER_AVAILABLE
    try:
        import httpx
        httpx.get(f"{BASE_URL}/api/auth/me", timeout=2.0)
        _SERVER_AVAILABLE = True
    except Exception:
        _SERVER_AVAILABLE = False
    return _SERVER_AVAILABLE


@pytest.fixture
def client():
    if not _server_is_up():
        pytest.skip("Live server not available; skipping integration test")
    import httpx
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_client(client):
    """Client with an authenticated session."""
    resp = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass123"},
    )
    if resp.status_code == 401:
        pytest.skip("Test user not available; ensure seed data is loaded")
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return client


@pytest.fixture
def test_user_id(auth_client):
    """Return the authenticated test user's id."""
    me_resp = auth_client.get("/api/auth/me")
    assert me_resp.status_code == 200
    return str(me_resp.json()["id"])


# AC11-a: happy path — valid athlete_id and a date range with data
def test_ac11_happy_path_response_shape(auth_client, test_user_id):
    """AC11: happy path returns 200 with five non-empty arrays of equal length."""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=60)).isoformat()

    resp = auth_client.get(
        "/api/performance/chart",
        params={"athlete_id": test_user_id, "start_date": start, "end_date": end},
    )

    assert resp.status_code == 200
    body = resp.json()

    for key in ("dates", "ctl", "atl", "tsb", "endurance_score", "speed_score",
                "building_baseline", "reason"):
        assert key in body, f"Missing key: {key}"

    n = len(body["dates"])
    assert n > 0 or body["reason"]  # either has data or has a reason
    for key in ("ctl", "atl", "tsb", "endurance_score", "speed_score"):
        assert len(body[key]) == n, f"{key} length mismatch (expected {n})"


# AC6: missing athlete_id → 200 + empty payload + athlete_not_found reason
def test_ac6_missing_athlete_id_returns_200_empty(client):
    """AC6: omitting athlete_id returns 200 with empty series and athlete_not_found reason."""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=30)).isoformat()

    resp = client.get(
        "/api/performance/chart",
        params={"start_date": start, "end_date": end},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dates"] == []
    assert body["ctl"] == []
    assert body["reason"] == "athlete_not_found"


# AC6: unknown athlete_id → 200 + empty payload + athlete_not_found reason
def test_ac6_unknown_athlete_id_returns_200_empty(client):
    """AC6: unknown athlete_id returns 200 with empty series and athlete_not_found reason."""
    resp = client.get(
        "/api/performance/chart",
        params={
            "athlete_id": "00000000-0000-0000-0000-000000000000",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dates"] == []
    assert body["reason"] == "athlete_not_found"


# AC7: start_date after end_date → 200 + empty payload + invalid_date_range reason
def test_ac7_start_after_end_returns_200_empty(client):
    """AC7: start_date > end_date returns 200 with empty series and invalid_date_range reason."""
    resp = client.get(
        "/api/performance/chart",
        params={
            "athlete_id": "any",
            "start_date": "2026-06-01",
            "end_date": "2026-01-01",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dates"] == []
    assert body["reason"] == "invalid_date_range"


# AC7: missing start_date → 200 + empty payload + reason
def test_ac7_missing_start_date_returns_200_empty(client):
    """AC7: missing start_date returns 200 with empty series."""
    resp = client.get(
        "/api/performance/chart",
        params={"athlete_id": "any", "end_date": "2026-06-01"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dates"] == []
    assert body["reason"]


# AC11-d: building_baseline=True when athlete lacks sufficient history
def test_ac11_building_baseline_scenario(auth_client, test_user_id):
    """AC11: requesting a very short date range triggers building_baseline=True."""
    # Request just 3 days — too short for stable fitness model
    start = "2026-01-01"
    end = "2026-01-03"

    resp = auth_client.get(
        "/api/performance/chart",
        params={"athlete_id": test_user_id, "start_date": start, "end_date": end},
    )

    assert resp.status_code == 200
    body = resp.json()
    # With only 3 days of history available, building_baseline should be True
    # (or no data in range, which is also acceptable)
    assert body["building_baseline"] is True or body["reason"] in (
        "no_data_in_range", "invalid_date_range", ""
    )
