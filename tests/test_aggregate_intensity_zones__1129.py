"""Tests for issue #1129: Aggregate session time-in-band into low/moderate/high percentages.

Acceptance Criteria covered:
  AC1: Each session exposes three computed fields: low_pct, moderate_pct, high_pct
  AC2: low_pct = sum of time in easy and steady bands / total session time × 100
  AC3: moderate_pct = time in tempo band / total session time × 100
  AC4: high_pct = sum of time in threshold and hard bands / total session time × 100
  AC5: For any session with lap band data, low_pct + moderate_pct + high_pct == 100 (±0.1)
  AC6: Values derived from existing lap-level band data; no new raw data required
  AC7: Sessions with zero total band time return null (None) rather than division-by-zero
  AC8: Module passes python -m py_compile with no errors
  AC9: Unit tests cover normal session, only one band populated, zero-duration session
"""

import subprocess
import sys
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split(band_via_power, duration_seconds, ftp_w=200):
    """Return a SimpleNamespace split whose band is determined by band_via_power / ftp_w.

    avg_power is set so that avg_power / ftp_w lands in the expected band:
        easy       < 0.80  → avg_power = ftp_w * 0.75
        steady     0.80–0.90 → avg_power = ftp_w * 0.85
        tempo      0.90–1.00 → avg_power = ftp_w * 0.95
        threshold  1.00–1.06 → avg_power = ftp_w * 1.03
        hard       >= 1.06  → avg_power = ftp_w * 1.10
    """
    ratios = {
        "easy":      0.75,
        "steady":    0.85,
        "tempo":     0.95,
        "threshold": 1.03,
        "hard":      1.10,
    }
    avg_power = int(ftp_w * ratios[band_via_power])
    return SimpleNamespace(
        avg_power=avg_power,
        avg_hr=None,
        distance_km=None,
        duration_seconds=duration_seconds,
    )


def _split_no_power(duration_seconds):
    """Return a split with no classifiable metric (band will be None)."""
    return SimpleNamespace(
        avg_power=None,
        avg_hr=None,
        distance_km=None,
        duration_seconds=duration_seconds,
    )


def _prefs(ftp_w=200):
    return {"ftp_w": ftp_w, "threshold_hr": None, "threshold_pace_seconds_per_km": None}


# ---------------------------------------------------------------------------
# AC1 / AC6: aggregate_intensity_zones is importable from lap_classify
# ---------------------------------------------------------------------------

class TestFunctionExists:

    def test_aggregate_intensity_zones_importable(self):
        """aggregate_intensity_zones must be importable from backend.services.lap_classify."""
        from backend.services.lap_classify import aggregate_intensity_zones
        assert callable(aggregate_intensity_zones)

    def test_returns_dict_with_three_keys(self):
        """Return value is a dict with exactly low_pct, moderate_pct, high_pct keys."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("easy", 600)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert isinstance(result, dict)
        assert "low_pct" in result
        assert "moderate_pct" in result
        assert "high_pct" in result


# ---------------------------------------------------------------------------
# AC2: low_pct = (easy + steady) / total × 100
# ---------------------------------------------------------------------------

class TestLowPct:

    def test_easy_only_gives_100_low(self):
        """All easy → low_pct=100, moderate_pct=0, high_pct=0."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("easy", 300), _split("easy", 300)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["low_pct"] == pytest.approx(100.0, abs=0.1)
        assert result["moderate_pct"] == pytest.approx(0.0, abs=0.1)
        assert result["high_pct"] == pytest.approx(0.0, abs=0.1)

    def test_steady_only_gives_100_low(self):
        """All steady → low_pct=100."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("steady", 600)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["low_pct"] == pytest.approx(100.0, abs=0.1)

    def test_easy_and_steady_both_count_to_low(self):
        """Easy and steady together make up low_pct (UAT step 2)."""
        from backend.services.lap_classify import aggregate_intensity_zones
        # 300s easy + 300s steady = 600s low / 600s total = 100%
        splits = [_split("easy", 300), _split("steady", 300)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["low_pct"] == pytest.approx(100.0, abs=0.1)
        assert result["moderate_pct"] == pytest.approx(0.0, abs=0.1)
        assert result["high_pct"] == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# AC3: moderate_pct = tempo / total × 100
# ---------------------------------------------------------------------------

class TestModeratePct:

    def test_tempo_only_gives_100_moderate(self):
        """All tempo → moderate_pct=100."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("tempo", 400)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["moderate_pct"] == pytest.approx(100.0, abs=0.1)
        assert result["low_pct"] == pytest.approx(0.0, abs=0.1)
        assert result["high_pct"] == pytest.approx(0.0, abs=0.1)

    def test_tempo_fraction(self):
        """200s easy + 200s tempo = 50% low, 50% moderate, 0% high."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("easy", 200), _split("tempo", 200)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["low_pct"] == pytest.approx(50.0, abs=0.1)
        assert result["moderate_pct"] == pytest.approx(50.0, abs=0.1)
        assert result["high_pct"] == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# AC4: high_pct = (threshold + hard) / total × 100
# ---------------------------------------------------------------------------

class TestHighPct:

    def test_threshold_only_gives_100_high(self):
        """All threshold → high_pct=100 (UAT step 3 partial)."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("threshold", 500)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["high_pct"] == pytest.approx(100.0, abs=0.1)
        assert result["low_pct"] == pytest.approx(0.0, abs=0.1)
        assert result["moderate_pct"] == pytest.approx(0.0, abs=0.1)

    def test_hard_only_gives_100_high(self):
        """All hard → high_pct=100."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("hard", 300)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["high_pct"] == pytest.approx(100.0, abs=0.1)

    def test_threshold_and_hard_together(self):
        """Threshold + hard together count as high (UAT step 3)."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("threshold", 300), _split("hard", 300)]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["high_pct"] == pytest.approx(100.0, abs=0.1)
        assert result["low_pct"] == pytest.approx(0.0, abs=0.1)
        assert result["moderate_pct"] == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# AC5: low_pct + moderate_pct + high_pct == 100 (±0.1) for sessions with data
# ---------------------------------------------------------------------------

class TestSumTo100:

    def test_five_band_session_sums_to_100(self):
        """Multi-band session: percentages sum to 100 (UAT step 4)."""
        from backend.services.lap_classify import aggregate_intensity_zones
        # 500s easy, 200s tempo, 300s threshold → total=1000
        # low=50%, moderate=20%, high=30%
        splits = [
            _split("easy", 500),
            _split("tempo", 200),
            _split("threshold", 300),
        ]
        result = aggregate_intensity_zones(splits, _prefs())
        total = result["low_pct"] + result["moderate_pct"] + result["high_pct"]
        assert total == pytest.approx(100.0, abs=0.1)

    def test_known_proportions_correct(self):
        """50/20/30 split matches UAT step 4 exactly."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [
            _split("easy", 500),
            _split("tempo", 200),
            _split("threshold", 300),
        ]
        result = aggregate_intensity_zones(splits, _prefs())
        assert result["low_pct"] == pytest.approx(50.0, abs=0.1)
        assert result["moderate_pct"] == pytest.approx(20.0, abs=0.1)
        assert result["high_pct"] == pytest.approx(30.0, abs=0.1)

    def test_all_five_bands_sums_to_100(self):
        """Session with all five bands: percentages still sum to 100."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [
            _split("easy",      200),
            _split("steady",    200),
            _split("tempo",     200),
            _split("threshold", 200),
            _split("hard",      200),
        ]
        result = aggregate_intensity_zones(splits, _prefs())
        total = result["low_pct"] + result["moderate_pct"] + result["high_pct"]
        assert total == pytest.approx(100.0, abs=0.1)

    def test_single_band_sums_to_100(self):
        """Session with only one band still sums to 100 (AC9: one band populated)."""
        from backend.services.lap_classify import aggregate_intensity_zones
        splits = [_split("tempo", 1200)]
        result = aggregate_intensity_zones(splits, _prefs())
        total = result["low_pct"] + result["moderate_pct"] + result["high_pct"]
        assert total == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# AC7: Sessions with zero total band time return null (None)
# ---------------------------------------------------------------------------

class TestZeroDuration:

    def test_no_classified_laps_returns_none(self):
        """Splits with no classifiable metric → all three fields are None (UAT step 5)."""
        from backend.services.lap_classify import aggregate_intensity_zones
        # Empty prefs → no threshold → band=None on all splits
        splits = [_split_no_power(600), _split_no_power(300)]
        result = aggregate_intensity_zones(splits, {})
        assert result["low_pct"] is None
        assert result["moderate_pct"] is None
        assert result["high_pct"] is None

    def test_empty_splits_list_returns_none(self):
        """Empty splits list → all three fields are None (AC9: zero-duration session)."""
        from backend.services.lap_classify import aggregate_intensity_zones
        result = aggregate_intensity_zones([], _prefs())
        assert result["low_pct"] is None
        assert result["moderate_pct"] is None
        assert result["high_pct"] is None

    def test_zero_total_band_time_no_exception(self):
        """Zero-band time must not raise — no division by zero (AC7, AC9)."""
        from backend.services.lap_classify import aggregate_intensity_zones
        try:
            result = aggregate_intensity_zones([], {})
        except ZeroDivisionError:
            pytest.fail("aggregate_intensity_zones raised ZeroDivisionError on empty splits")
        assert result is not None


# ---------------------------------------------------------------------------
# AC8: Module passes py_compile with no errors
# ---------------------------------------------------------------------------

class TestPyCompile:

    def test_lap_classify_compiles(self):
        """python -m py_compile must exit 0 on lap_classify.py (AC8)."""
        import os
        module_path = os.path.join(
            os.path.dirname(__file__), "..", "backend", "services", "lap_classify.py"
        )
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", module_path],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"py_compile failed:\n{result.stderr.decode()}"
        )


# ---------------------------------------------------------------------------
# AC1: API endpoint includes intensity_zones in workout detail response
# ---------------------------------------------------------------------------

class TestApiExposure:

    def test_workout_detail_response_has_intensity_zones_key(self):
        """GET /api/workouts/<id>/detail includes intensity_zones in the response body."""
        import importlib
        try:
            main = importlib.import_module("backend.main")
        except ImportError:
            pytest.skip("backend.main not importable in this environment")

        # Verify the endpoint handler references the intensity_zones field
        import inspect
        src = inspect.getsource(main)
        assert "intensity_zones" in src, (
            "backend/main.py must include 'intensity_zones' in the workout detail response"
        )
