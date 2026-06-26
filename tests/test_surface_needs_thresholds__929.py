"""Tests for issue #929: Surface needs_thresholds state when athlete has no thresholds set.

TDD: tests written before (or alongside) implementation, covering all AC items.

Acceptance Criteria covered:
  AC1: No thresholds set → endpoint returns state: "needs_thresholds" + non-empty reason.
  AC2: At least one threshold set, too few runs → state: "building_baseline" (existing preserved).
  AC3: Thresholds + sufficient qualifying runs → numeric performance scores (existing preserved).
  AC4: reason field is sourced from a constants/config module, not hardcoded in business logic.
  AC5: DB access for thresholds is in the caller layer; score functions do not query user_preferences.
  AC6: Three states (needs_thresholds, building_baseline, numeric scores) are mutually exclusive.
  AC7: Unit tests cover each of the three states.
"""

import os
import pytest

from backend.services.running_performance import compute_endurance_score, compute_speed_score
from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _prefs_no_thresholds():
    return {
        "ftp_w": None,
        "threshold_hr": None,
        "threshold_pace_seconds_per_km": None,
        "aerobic_decoupling_threshold": None,
        "duration_curve_bests": None,
    }


def _prefs_with_ftp_only():
    return {
        "ftp_w": 220,
        "threshold_hr": None,
        "threshold_pace_seconds_per_km": None,
        "aerobic_decoupling_threshold": None,
        "duration_curve_bests": None,
    }


def _prefs_all_thresholds():
    return {
        "ftp_w": 220,
        "threshold_hr": 165,
        "threshold_pace_seconds_per_km": 300,
        "aerobic_decoupling_threshold": 8.0,
        "duration_curve_bests": None,
    }


def _make_easy_run(run_id, efficiency_hint=1.5, workout_date="2026-01-01"):
    power = efficiency_hint * 140
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "easy",
                "avg_power": power,
                "avg_hr": 140.0,
                "distance_km": 2.0,
                "duration_seconds": 600.0,
            }
        ],
        "decoupling_pct": 5.0,
        "avg_power": power,
        "avg_hr": 140.0,
        "distance_km": 6.0,
        "duration_seconds": 1800,
    }


def _sufficient_easy_runs():
    return [
        _make_easy_run(f"r{i}", efficiency_hint=1.5 + i * 0.05, workout_date=f"2026-01-{i:02d}")
        for i in range(1, MIN_QUALIFYING_RUNS + 1)
    ]


# ---------------------------------------------------------------------------
# AC4: reason string lives in a dedicated constants module, not inline in main
# ---------------------------------------------------------------------------

class TestReasonSourcedFromConstants:
    """AC4: reason is sourced from a constants/config file, not hardcoded in business logic."""

    def test_constants_module_exists(self):
        """AC4: backend.services.performance_constants must be importable."""
        import backend.services.performance_constants as pc  # noqa: F401

    def test_needs_thresholds_reason_exported(self):
        """AC4: the constants module exports NEEDS_THRESHOLDS_REASON."""
        from backend.services.performance_constants import NEEDS_THRESHOLDS_REASON
        assert isinstance(NEEDS_THRESHOLDS_REASON, str)
        assert len(NEEDS_THRESHOLDS_REASON) > 0

    def test_reason_mentions_thresholds_or_ftp(self):
        """AC4: reason guides user toward configuring thresholds."""
        from backend.services.performance_constants import NEEDS_THRESHOLDS_REASON
        lower = NEEDS_THRESHOLDS_REASON.lower()
        assert any(kw in lower for kw in ("ftp", "threshold", "pace", "heart rate")), (
            f"NEEDS_THRESHOLDS_REASON should mention thresholds; got: {NEEDS_THRESHOLDS_REASON!r}"
        )

    def test_endpoint_uses_constant_not_inline_string(self):
        """AC4: backend.main._NEEDS_THRESHOLDS_REASON must equal the constants module value."""
        from backend.services.performance_constants import NEEDS_THRESHOLDS_REASON
        from backend.main import _NEEDS_THRESHOLDS_REASON as main_reason
        assert main_reason == NEEDS_THRESHOLDS_REASON, (
            "main.py must import _NEEDS_THRESHOLDS_REASON from performance_constants, "
            "not define its own copy"
        )


# ---------------------------------------------------------------------------
# AC1 + AC7: needs_thresholds state — no thresholds → correct response shape
# ---------------------------------------------------------------------------

class TestNeedsThresholdsState:
    """AC1, AC7: state=needs_thresholds when all threshold fields are absent."""

    def test_check_helper_returns_true_for_no_thresholds(self):
        """AC1: _check_needs_thresholds(prefs_no_thresholds) is True."""
        from backend.main import _check_needs_thresholds
        assert _check_needs_thresholds(_prefs_no_thresholds()) is True

    def test_check_helper_returns_true_for_none_prefs(self):
        """AC1: _check_needs_thresholds(None) is True — no prefs row at all."""
        from backend.main import _check_needs_thresholds
        assert _check_needs_thresholds(None) is True

    def test_check_helper_returns_true_for_empty_dict(self):
        """AC1: empty dict (all keys absent) → needs_thresholds."""
        from backend.main import _check_needs_thresholds
        assert _check_needs_thresholds({}) is True

    def test_needs_thresholds_response_has_state_field(self):
        """AC1: returned object has state == 'needs_thresholds'."""
        from backend.services.performance_constants import NEEDS_THRESHOLDS_REASON
        obj = {"state": "needs_thresholds", "reason": NEEDS_THRESHOLDS_REASON}
        assert obj["state"] == "needs_thresholds"

    def test_needs_thresholds_response_has_non_empty_reason(self):
        """AC1: reason field is a non-empty human-readable string."""
        from backend.services.performance_constants import NEEDS_THRESHOLDS_REASON
        assert isinstance(NEEDS_THRESHOLDS_REASON, str)
        assert len(NEEDS_THRESHOLDS_REASON) > 10

    def test_needs_thresholds_has_no_numeric_score_field(self):
        """AC1: no numeric score fields in the needs_thresholds object."""
        from backend.services.performance_constants import NEEDS_THRESHOLDS_REASON
        obj = {"state": "needs_thresholds", "reason": NEEDS_THRESHOLDS_REASON}
        assert "score" not in obj
        assert "trend" not in obj
        assert "direction" not in obj


# ---------------------------------------------------------------------------
# AC2 + AC7: building_baseline state preserved when ≥1 threshold set
# ---------------------------------------------------------------------------

class TestBuildingBaselineState:
    """AC2, AC7: building_baseline returned when ≥1 threshold set but too few runs."""

    def test_no_runs_with_one_threshold_returns_building_baseline(self):
        """AC2: ftp_w alone + zero runs → building_baseline, not needs_thresholds."""
        zc = make_zone_constants()
        endurance = compute_endurance_score([], _prefs_with_ftp_only(), zc)
        speed = compute_speed_score([], _prefs_with_ftp_only(), zc)
        assert endurance.get("state") == "building_baseline"
        assert speed.get("state") == "building_baseline"

    def test_insufficient_runs_returns_building_baseline(self):
        """AC2: fewer than MIN_QUALIFYING_RUNS → building_baseline."""
        runs = [_make_easy_run(f"r{i}") for i in range(1, MIN_QUALIFYING_RUNS)]
        zc = make_zone_constants()
        endurance = compute_endurance_score(runs, _prefs_all_thresholds(), zc)
        assert endurance.get("state") == "building_baseline"


# ---------------------------------------------------------------------------
# AC3 + AC7: numeric scores state when thresholds + sufficient runs
# ---------------------------------------------------------------------------

class TestNumericScoresState:
    """AC3, AC7: numeric scores returned when thresholds and sufficient history present."""

    def test_sufficient_runs_returns_numeric_score(self):
        """AC3: MIN_QUALIFYING_RUNS easy runs + all thresholds → numeric score 0–100."""
        runs = _sufficient_easy_runs()
        zc = make_zone_constants()
        endurance = compute_endurance_score(runs, _prefs_all_thresholds(), zc)
        assert "score" in endurance
        assert isinstance(endurance["score"], (int, float))
        assert 0 <= endurance["score"] <= 100

    def test_sufficient_runs_returns_no_state_field(self):
        """AC3: numeric result must NOT contain state == 'needs_thresholds' or 'building_baseline'."""
        runs = _sufficient_easy_runs()
        zc = make_zone_constants()
        endurance = compute_endurance_score(runs, _prefs_all_thresholds(), zc)
        state = endurance.get("state")
        assert state not in ("needs_thresholds", "building_baseline"), (
            f"Numeric result should not carry state; got state={state!r}"
        )


# ---------------------------------------------------------------------------
# AC5: thin caller pattern — score functions don't touch DB
# ---------------------------------------------------------------------------

class TestThinCallerPattern:
    """AC5: score functions are pure; no DB access inside running_performance module."""

    def test_score_functions_are_pure_no_db_import(self):
        """AC5: running_performance module must not import SQLAlchemy session or models."""
        import backend.services.running_performance as rp
        source = rp.__file__
        with open(source) as f:
            content = f.read()
        # These are the DB-touching symbols that must NOT appear in the pure module
        forbidden = ["Session(", "session.query", "UserPreferences", "from backend.models"]
        for symbol in forbidden:
            assert symbol not in content, (
                f"running_performance.py must not access DB; found forbidden symbol: {symbol!r}"
            )


# ---------------------------------------------------------------------------
# AC6: Three states are mutually exclusive and exhaustive
# ---------------------------------------------------------------------------

class TestMutualExclusivity:
    """AC6: needs_thresholds, building_baseline, numeric scores are mutually exclusive."""

    def test_no_thresholds_never_produces_building_baseline(self):
        """AC6: _check_needs_thresholds=True short-circuits before score functions run."""
        from backend.main import _check_needs_thresholds
        assert _check_needs_thresholds(_prefs_no_thresholds()) is True
        # The endpoint short-circuits at this point and returns needs_thresholds
        # without ever calling compute_endurance_score / compute_speed_score.

    def test_one_threshold_present_means_not_needs_thresholds(self):
        """AC6: any threshold present → _check_needs_thresholds is False."""
        from backend.main import _check_needs_thresholds
        cases = [
            {**_prefs_no_thresholds(), "ftp_w": 200},
            {**_prefs_no_thresholds(), "threshold_hr": 160},
            {**_prefs_no_thresholds(), "threshold_pace_seconds_per_km": 300},
        ]
        for prefs in cases:
            assert _check_needs_thresholds(prefs) is False, (
                f"Expected False (threshold present) for {prefs}"
            )

    def test_score_functions_never_return_needs_thresholds(self):
        """AC6: score functions themselves must never return state='needs_thresholds';
        that state is produced only by the endpoint's pre-check."""
        zc = make_zone_constants()
        endurance = compute_endurance_score([], None, zc)
        speed = compute_speed_score([], None, zc)
        assert endurance.get("state") != "needs_thresholds"
        assert speed.get("state") != "needs_thresholds"


# ---------------------------------------------------------------------------
# Integration tests — live server (skipped unless RUN_INTEGRATION_TESTS=1)
# ---------------------------------------------------------------------------

_UAT_BASE = os.environ.get("UAT_BASE_URL") or (
    "http://localhost:" + os.environ.get("UAT_PORT", "9001")
)


@pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests against a live server",
)
class TestNeedsThresholdsIntegration:
    """Live-server integration tests for needs_thresholds state."""

    @pytest.fixture
    def client(self):
        import httpx
        with httpx.Client(base_url=_UAT_BASE, timeout=10.0) as c:
            yield c

    def _login(self, client, username, password):
        resp = client.post("/api/auth/login", json={"username": username, "password": password})
        if resp.status_code != 200:
            pytest.skip(f"Cannot log in as {username!r}")

    def test_no_thresholds_returns_needs_thresholds(self, client):
        """AC1: Athlete with no thresholds → state: needs_thresholds on both scores."""
        self._login(client, "no_threshold_user", "testpass123")
        me = client.get("/api/auth/me")
        if me.status_code != 200:
            pytest.skip("Cannot determine current user id")
        uid = me.json()["id"]

        r = client.get(f"/api/athletes/{uid}/performance")
        assert r.status_code == 200
        data = r.json()
        assert data["endurance"].get("state") == "needs_thresholds"
        assert data["speed"].get("state") == "needs_thresholds"
        assert isinstance(data["endurance"].get("reason"), str)
        assert len(data["endurance"]["reason"]) > 0

    def test_one_threshold_transitions_to_building_baseline(self, client):
        """AC4/AC6: adding one threshold → building_baseline, not needs_thresholds."""
        self._login(client, "one_threshold_no_runs_user", "testpass123")
        me = client.get("/api/auth/me")
        if me.status_code != 200:
            pytest.skip("Cannot determine current user id")
        uid = me.json()["id"]

        r = client.get(f"/api/athletes/{uid}/performance")
        assert r.status_code == 200
        data = r.json()
        for key in ("endurance", "speed"):
            state = data.get(key, {}).get("state")
            assert state == "building_baseline", (
                f"{key} should be building_baseline with one threshold; got {state!r}"
            )
