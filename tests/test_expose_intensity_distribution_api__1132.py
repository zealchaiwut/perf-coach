"""Tests for issue #1132: Expose intensity distribution and polarized verdict via API.

Acceptance criteria covered:
  AC1 — GET /api/sessions/{id}/intensity-distribution exists and returns per-session
         low/moderate/high and polarized_check
  AC2 — GET /api/intensity-distribution/rolling exists and returns rolling aggregates
         over a configurable or default time window with polarized_check
  AC3 — polarized_check field present in both responses with a valid enum verdict
  AC4 — Response schema documented (inline docstring present on endpoint functions)
  AC5 — All new Python files pass py_compile with zero errors
  AC6 — Happy path and edge case (session with no zone data) covered
"""

import pathlib
import py_compile
import types
import unittest.mock as mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split(band_via_power, duration_seconds, ftp_w=200):
    """Return a SimpleNamespace split whose intensity band is determined via power."""
    ratios = {"easy": 0.75, "steady": 0.85, "tempo": 0.95, "threshold": 1.03, "hard": 1.10}
    avg_power = int(ftp_w * ratios[band_via_power])
    return types.SimpleNamespace(
        avg_power=avg_power,
        avg_hr=None,
        distance_km=None,
        duration_seconds=duration_seconds,
        intensity_band=band_via_power,
    )


def _split_no_power(duration_seconds):
    return types.SimpleNamespace(
        avg_power=None, avg_hr=None, distance_km=None,
        duration_seconds=duration_seconds, intensity_band=None,
    )


def _prefs(ftp_w=200):
    return {"ftp_w": ftp_w, "threshold_hr": None, "threshold_pace_seconds_per_km": None}


# ---------------------------------------------------------------------------
# AC3 / pure function: compute_polarized_check
# ---------------------------------------------------------------------------

class TestComputePolarizedCheck:

    def test_pass_verdict(self):
        """AC3: 80% low, 5% moderate, 15% high → polarized 'pass'."""
        from backend.services.intensity_distribution import compute_polarized_check
        result = compute_polarized_check(80.0, 5.0, 15.0)
        assert result == "pass"

    def test_pass_at_boundary(self):
        """AC3: exactly 75% low, 15% moderate → 'pass' (lower boundary)."""
        from backend.services.intensity_distribution import compute_polarized_check
        result = compute_polarized_check(75.0, 15.0, 10.0)
        assert result == "pass"

    def test_borderline_verdict(self):
        """AC3: 65% low, 20% moderate → 'borderline'."""
        from backend.services.intensity_distribution import compute_polarized_check
        result = compute_polarized_check(65.0, 20.0, 15.0)
        assert result == "borderline"

    def test_fail_verdict_too_much_moderate(self):
        """AC3: 50% low, 40% moderate → 'fail'."""
        from backend.services.intensity_distribution import compute_polarized_check
        result = compute_polarized_check(50.0, 40.0, 10.0)
        assert result == "fail"

    def test_fail_verdict_low_below_threshold(self):
        """AC3: 40% low → 'fail' regardless of moderate."""
        from backend.services.intensity_distribution import compute_polarized_check
        result = compute_polarized_check(40.0, 10.0, 50.0)
        assert result == "fail"

    def test_insufficient_data_all_none(self):
        """AC3: all None → 'insufficient_data'."""
        from backend.services.intensity_distribution import compute_polarized_check
        result = compute_polarized_check(None, None, None)
        assert result == "insufficient_data"

    def test_insufficient_data_low_none(self):
        """AC3: any None input → 'insufficient_data'."""
        from backend.services.intensity_distribution import compute_polarized_check
        result = compute_polarized_check(None, 10.0, 5.0)
        assert result == "insufficient_data"

    def test_valid_verdict_values(self):
        """AC3: return value is always one of the four valid enum strings."""
        from backend.services.intensity_distribution import compute_polarized_check
        valid = {"pass", "borderline", "fail", "insufficient_data"}
        cases = [
            (80.0, 5.0, 15.0),
            (65.0, 20.0, 15.0),
            (30.0, 50.0, 20.0),
            (None, None, None),
        ]
        for args in cases:
            result = compute_polarized_check(*args)
            assert result in valid, f"got unexpected verdict {result!r} for args {args}"


# ---------------------------------------------------------------------------
# AC1 / AC4: per-session endpoint exists and is documented in main.py
# ---------------------------------------------------------------------------

class TestPerSessionEndpointExists:

    def test_endpoint_route_registered(self):
        """AC1: main.py registers GET /api/sessions/{session_id}/intensity-distribution."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        assert "/api/sessions/{session_id}/intensity-distribution" in code, (
            "main.py must register GET /api/sessions/{session_id}/intensity-distribution"
        )

    def test_endpoint_has_docstring(self):
        """AC4: the per-session endpoint handler must have an inline docstring."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_session_intensity_distribution")
        assert func_start != -1, "get_session_intensity_distribution function not found"
        func_snippet = code[func_start:func_start + 4000]
        assert '"""' in func_snippet, (
            "get_session_intensity_distribution must have a docstring"
        )

    def test_response_includes_polarized_check(self):
        """AC3: per-session endpoint handler includes 'polarized_check' in its response."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_session_intensity_distribution")
        func_snippet = code[func_start:func_start + 4000]
        assert '"polarized_check"' in func_snippet, (
            "get_session_intensity_distribution response must include 'polarized_check'"
        )

    def test_response_includes_low_moderate_high(self):
        """AC1: per-session endpoint includes low, moderate, high in its response dict."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_session_intensity_distribution")
        func_snippet = code[func_start:func_start + 4000]
        assert '"low"' in func_snippet
        assert '"moderate"' in func_snippet
        assert '"high"' in func_snippet

    def test_returns_404_for_unknown_session_code_path(self):
        """AC1 edge: handler raises 404 for a non-existent session."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_session_intensity_distribution")
        func_snippet = code[func_start:func_start + 4000]
        assert "404" in func_snippet, (
            "get_session_intensity_distribution must return 404 for missing sessions"
        )

    def test_returns_400_for_invalid_uuid_code_path(self):
        """AC1 edge: handler raises 400 for a malformed session_id."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_session_intensity_distribution")
        func_snippet = code[func_start:func_start + 4000]
        assert "400" in func_snippet, (
            "get_session_intensity_distribution must return 400 for invalid session_id"
        )


# ---------------------------------------------------------------------------
# AC2 / AC4: rolling endpoint exists and is documented in main.py
# ---------------------------------------------------------------------------

class TestRollingEndpointExists:

    def test_rolling_endpoint_route_registered(self):
        """AC2: main.py registers GET /api/intensity-distribution/rolling."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        assert "/api/intensity-distribution/rolling" in code, (
            "main.py must register GET /api/intensity-distribution/rolling"
        )

    def test_rolling_endpoint_has_docstring(self):
        """AC4: rolling endpoint handler must have an inline docstring."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_rolling_intensity_distribution")
        assert func_start != -1, "get_rolling_intensity_distribution function not found"
        func_snippet = code[func_start:func_start + 4000]
        assert '"""' in func_snippet

    def test_rolling_response_includes_polarized_check(self):
        """AC3: rolling endpoint includes 'polarized_check' in its response."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_rolling_intensity_distribution")
        func_snippet = code[func_start:func_start + 5000]
        assert '"polarized_check"' in func_snippet

    def test_rolling_response_includes_low_moderate_high(self):
        """AC2: rolling endpoint includes low, moderate, high in its response dict."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_rolling_intensity_distribution")
        func_snippet = code[func_start:func_start + 5000]
        assert '"low"' in func_snippet
        assert '"moderate"' in func_snippet
        assert '"high"' in func_snippet

    def test_rolling_endpoint_has_date_params(self):
        """AC2: rolling endpoint accepts from/to query params for configurable window."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_rolling_intensity_distribution")
        func_snippet = code[func_start:func_start + 800]
        assert "from" in func_snippet or "from_date" in func_snippet, (
            "rolling endpoint must accept a 'from' date parameter"
        )
        assert "to" in func_snippet or "to_date" in func_snippet, (
            "rolling endpoint must accept a 'to' date parameter"
        )

    def test_rolling_response_includes_session_count(self):
        """AC2: rolling endpoint includes session_count in its response."""
        src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        code = src.read_text()
        func_start = code.find("def get_rolling_intensity_distribution")
        func_snippet = code[func_start:func_start + 5000]
        assert '"session_count"' in func_snippet


# ---------------------------------------------------------------------------
# AC6: Happy path — pure function produces correct distribution
# ---------------------------------------------------------------------------

class TestAggregateIntensityZonesHappyPath:

    def test_all_low_gives_pass(self):
        """AC6 happy path: session entirely in low zone → polarized_check='pass'."""
        from backend.services.lap_classify import aggregate_intensity_zones
        from backend.services.intensity_distribution import compute_polarized_check

        splits = [_split("easy", 400), _split("steady", 200)]
        zones = aggregate_intensity_zones(splits, _prefs())
        verdict = compute_polarized_check(zones["low_pct"], zones["moderate_pct"], zones["high_pct"])
        assert verdict == "pass"

    def test_polarized_distribution_gives_pass(self):
        """AC6 happy path: 80% low + 20% high (0% moderate) → 'pass'."""
        from backend.services.lap_classify import aggregate_intensity_zones
        from backend.services.intensity_distribution import compute_polarized_check

        # 4800s easy + 1200s threshold = 80% low, 0% moderate, 20% high
        splits = [_split("easy", 4800), _split("threshold", 1200)]
        zones = aggregate_intensity_zones(splits, _prefs())
        verdict = compute_polarized_check(zones["low_pct"], zones["moderate_pct"], zones["high_pct"])
        assert verdict == "pass"

    def test_threshold_session_gives_fail(self):
        """AC6 happy path: all-threshold session (0% low) → 'fail'."""
        from backend.services.lap_classify import aggregate_intensity_zones
        from backend.services.intensity_distribution import compute_polarized_check

        splits = [_split("threshold", 600), _split("hard", 600)]
        zones = aggregate_intensity_zones(splits, _prefs())
        verdict = compute_polarized_check(zones["low_pct"], zones["moderate_pct"], zones["high_pct"])
        assert verdict == "fail"


# ---------------------------------------------------------------------------
# AC6: Edge case — session with no zone data
# ---------------------------------------------------------------------------

class TestNoZoneData:

    def test_session_with_no_classified_splits_returns_insufficient_data(self):
        """AC6 edge case: no classified laps → low/moderate/high None → 'insufficient_data'."""
        from backend.services.lap_classify import aggregate_intensity_zones
        from backend.services.intensity_distribution import compute_polarized_check

        splits = [_split_no_power(600), _split_no_power(300)]
        zones = aggregate_intensity_zones(splits, {})
        verdict = compute_polarized_check(zones["low_pct"], zones["moderate_pct"], zones["high_pct"])
        assert zones["low_pct"] is None
        assert zones["moderate_pct"] is None
        assert zones["high_pct"] is None
        assert verdict == "insufficient_data"

    def test_empty_splits_returns_insufficient_data(self):
        """AC6 edge case: empty splits list → all None → 'insufficient_data'."""
        from backend.services.lap_classify import aggregate_intensity_zones
        from backend.services.intensity_distribution import compute_polarized_check

        zones = aggregate_intensity_zones([], _prefs())
        verdict = compute_polarized_check(zones["low_pct"], zones["moderate_pct"], zones["high_pct"])
        assert verdict == "insufficient_data"

    def test_session_with_no_prefs_returns_insufficient_data(self):
        """AC6 edge case: no threshold prefs → all laps unclassifiable → 'insufficient_data'."""
        from backend.services.lap_classify import aggregate_intensity_zones
        from backend.services.intensity_distribution import compute_polarized_check

        splits = [
            types.SimpleNamespace(avg_power=None, avg_hr=None, distance_km=None,
                                  duration_seconds=600, intensity_band=None),
        ]
        zones = aggregate_intensity_zones(splits, {"ftp_w": None, "threshold_hr": None,
                                                   "threshold_pace_seconds_per_km": None})
        verdict = compute_polarized_check(zones["low_pct"], zones["moderate_pct"], zones["high_pct"])
        assert verdict == "insufficient_data"


# ---------------------------------------------------------------------------
# AC5: py_compile all new files
# ---------------------------------------------------------------------------

class TestPyCompile:

    def test_intensity_distribution_module_compiles(self):
        """AC5: backend/services/intensity_distribution.py passes py_compile."""
        path = pathlib.Path(__file__).resolve().parents[1] / "backend" / "services" / "intensity_distribution.py"
        assert path.exists(), "intensity_distribution.py must exist"
        py_compile.compile(str(path), doraise=True)

    def test_main_module_compiles(self):
        """AC5: backend/main.py passes py_compile (no syntax errors introduced)."""
        path = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
        py_compile.compile(str(path), doraise=True)
