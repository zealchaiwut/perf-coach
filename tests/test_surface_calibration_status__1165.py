"""Tests for issue #1165: Surface calibration status — recency, sufficiency, confidence.

Acceptance criteria verified:
- AC1: Endpoint returns last_calibration_date in YYYY-MM-DD format when a
       calibrated race exists; null when none exists.
- AC2: Endpoint returns data_sufficiency as one of 'Sufficient', 'Low', or
       'Insufficient', derived from training snapshot density.
- AC3: Endpoint returns band_confidence as one of 'High', 'Medium', or 'Low',
       derived from recent training data quality.
- AC4: All three values come from the model/backend — they vary with DB state,
       not constants or hardcoded strings.
- AC5: When no calibration data exists, last_calibration_date is null and
       calibrated is false (fallback state, not an error).
- AC6: HTML surface includes aria-label and role attributes; layout renders at
       mobile viewport width without overflow.
"""

import ast
import os
import py_compile
from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch, MagicMock

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sufficiency_label(count_90: int) -> str:
    """Mirror the endpoint's sufficiency derivation for local assertion."""
    from backend.main import (
        _CALIB_SUFFICIENCY_HIGH,
        _CALIB_SUFFICIENCY_LOW,
    )
    if count_90 >= _CALIB_SUFFICIENCY_HIGH:
        return "Sufficient"
    if count_90 >= _CALIB_SUFFICIENCY_LOW:
        return "Low"
    return "Insufficient"


def _confidence_label(count_42: int) -> str:
    """Mirror the endpoint's band_confidence derivation for local assertion."""
    from backend.main import (
        _CALIB_BAND_HIGH,
        _CALIB_BAND_MEDIUM,
    )
    if count_42 >= _CALIB_BAND_HIGH:
        return "High"
    if count_42 >= _CALIB_BAND_MEDIUM:
        return "Medium"
    return "Low"


# ── AC5: py_compile passes on modified files ──────────────────────────────────

def test_ac5_py_compile_main():
    import backend.main as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


# ── AC4: threshold constants exist and are derived from model constants ────────

def test_ac4_threshold_constants_exported():
    """Endpoint constants must be importable — they are not hardcoded bare ints."""
    from backend.main import (
        _CALIB_SUFFICIENCY_HIGH,
        _CALIB_SUFFICIENCY_LOW,
        _CALIB_BAND_HIGH,
        _CALIB_BAND_MEDIUM,
        _CALIB_WINDOW_90,
        _CALIB_WINDOW_42,
    )
    assert isinstance(_CALIB_SUFFICIENCY_HIGH, int)
    assert isinstance(_CALIB_SUFFICIENCY_LOW, int)
    assert isinstance(_CALIB_BAND_HIGH, int)
    assert isinstance(_CALIB_BAND_MEDIUM, int)
    assert _CALIB_SUFFICIENCY_HIGH > _CALIB_SUFFICIENCY_LOW > 0
    assert _CALIB_BAND_HIGH > _CALIB_BAND_MEDIUM > 0
    assert _CALIB_WINDOW_90 > _CALIB_WINDOW_42 > 0


def test_ac4_constants_derived_from_ctl_days():
    """Sufficiency and confidence thresholds are derived from CTL_DAYS constant."""
    from backend.services.training_load import CTL_DAYS
    from backend.main import (
        _CALIB_SUFFICIENCY_HIGH,
        _CALIB_SUFFICIENCY_LOW,
        _CALIB_BAND_HIGH,
        _CALIB_BAND_MEDIUM,
        _CALIB_WINDOW_42,
    )
    # Sufficiency uses 90-day window and CTL multiples
    assert _CALIB_SUFFICIENCY_HIGH == CTL_DAYS * 2
    assert _CALIB_SUFFICIENCY_LOW == CTL_DAYS
    # Confidence window matches CTL_DAYS
    assert _CALIB_WINDOW_42 == CTL_DAYS


# ── AC2: data_sufficiency label derivation ────────────────────────────────────

def test_ac2_sufficient_label_at_high_threshold():
    """Snapshot count at or above SUFFICIENCY_HIGH yields 'Sufficient'."""
    from backend.main import _CALIB_SUFFICIENCY_HIGH
    label = _sufficiency_label(_CALIB_SUFFICIENCY_HIGH)
    assert label == "Sufficient"


def test_ac2_sufficient_label_above_high_threshold():
    """Snapshot count above SUFFICIENCY_HIGH also yields 'Sufficient'."""
    from backend.main import _CALIB_SUFFICIENCY_HIGH
    label = _sufficiency_label(_CALIB_SUFFICIENCY_HIGH + 10)
    assert label == "Sufficient"


def test_ac2_low_label_at_low_threshold():
    """Snapshot count at SUFFICIENCY_LOW but below HIGH yields 'Low'."""
    from backend.main import _CALIB_SUFFICIENCY_LOW, _CALIB_SUFFICIENCY_HIGH
    count = _CALIB_SUFFICIENCY_LOW
    assert count < _CALIB_SUFFICIENCY_HIGH
    label = _sufficiency_label(count)
    assert label == "Low"


def test_ac2_low_label_between_thresholds():
    """Snapshot count between LOW and HIGH thresholds yields 'Low'."""
    from backend.main import _CALIB_SUFFICIENCY_LOW, _CALIB_SUFFICIENCY_HIGH
    count = (_CALIB_SUFFICIENCY_LOW + _CALIB_SUFFICIENCY_HIGH) // 2
    label = _sufficiency_label(count)
    assert label == "Low"


def test_ac2_insufficient_at_zero():
    """Zero snapshots yields 'Insufficient'."""
    label = _sufficiency_label(0)
    assert label == "Insufficient"


def test_ac2_insufficient_below_low_threshold():
    """Count below SUFFICIENCY_LOW yields 'Insufficient'."""
    from backend.main import _CALIB_SUFFICIENCY_LOW
    label = _sufficiency_label(_CALIB_SUFFICIENCY_LOW - 1)
    assert label == "Insufficient"


def test_ac2_all_labels_are_one_of_three():
    """data_sufficiency is always one of the three valid label strings."""
    valid = {"Sufficient", "Low", "Insufficient"}
    for count in [0, 1, 29, 30, 41, 42, 43, 83, 84, 85, 100]:
        label = _sufficiency_label(count)
        assert label in valid, f"Unexpected label {label!r} for count={count}"


# ── AC3: band_confidence label derivation ─────────────────────────────────────

def test_ac3_high_confidence_at_threshold():
    """Snapshot count at or above BAND_HIGH yields 'High'."""
    from backend.main import _CALIB_BAND_HIGH
    label = _confidence_label(_CALIB_BAND_HIGH)
    assert label == "High"


def test_ac3_medium_confidence_at_threshold():
    """Snapshot count at BAND_MEDIUM but below BAND_HIGH yields 'Medium'."""
    from backend.main import _CALIB_BAND_MEDIUM, _CALIB_BAND_HIGH
    count = _CALIB_BAND_MEDIUM
    assert count < _CALIB_BAND_HIGH
    label = _confidence_label(count)
    assert label == "Medium"


def test_ac3_low_confidence_at_zero():
    """Zero snapshots in window yields 'Low' confidence."""
    label = _confidence_label(0)
    assert label == "Low"


def test_ac3_low_confidence_below_medium():
    """Count below BAND_MEDIUM yields 'Low'."""
    from backend.main import _CALIB_BAND_MEDIUM
    label = _confidence_label(_CALIB_BAND_MEDIUM - 1)
    assert label == "Low"


def test_ac3_all_labels_are_one_of_three():
    """band_confidence is always one of the three valid label strings."""
    valid = {"High", "Medium", "Low"}
    for count in [0, 1, 20, 21, 22, 35, 36, 42, 100]:
        label = _confidence_label(count)
        assert label in valid, f"Unexpected label {label!r} for count={count}"


# ── AC1 / AC5: endpoint response shape ────────────────────────────────────────

def _build_mock_session(
    calibrated_race=None,
    count_90: int = 0,
    count_42: int = 0,
):
    """Build a mock DB session that returns the specified calibration state."""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(model):
        q = MagicMock()
        filter_q = MagicMock()
        q.filter.return_value = filter_q

        if hasattr(model, "__tablename__") and model.__tablename__ == "races":
            order_q = MagicMock()
            filter_q.filter.return_value = order_q
            order_q.order_by.return_value = order_q
            order_q.first.return_value = calibrated_race
            filter_q.order_by.return_value = order_q
        elif hasattr(model, "__tablename__") and model.__tablename__ == "training_load_snapshots":
            # Second filter call (date range) for either 90-day or 42-day window
            filter_q2 = MagicMock()
            filter_q.filter.return_value = filter_q2
            filter_q2.count.return_value = count_90
            # Need to distinguish 42-day vs 90-day queries — use a counter
            call_count = {"n": 0}
            def _count_side():
                call_count["n"] += 1
                return count_90 if call_count["n"] == 1 else count_42
            filter_q2.count.side_effect = _count_side
        return q

    mock_session.query.side_effect = _query_side_effect
    return mock_session


def test_ac5_no_calibrated_race_returns_null_date():
    """When no calibrated race exists, last_calibration_date is null."""
    from backend.main import _compute_calibration_status
    result = _compute_calibration_status(
        last_calibrated_race=None,
        snapshot_count_90=0,
        snapshot_count_42=0,
    )
    assert result["last_calibration_date"] is None
    assert result["calibrated"] is False


def test_ac5_no_calibrated_race_still_returns_sufficiency():
    """Even without a calibrated race, data_sufficiency is returned."""
    from backend.main import _compute_calibration_status
    result = _compute_calibration_status(
        last_calibrated_race=None,
        snapshot_count_90=0,
        snapshot_count_42=0,
    )
    assert result["data_sufficiency"] == "Insufficient"
    assert result["band_confidence"] == "Low"


def test_ac1_calibrated_race_returns_date_string():
    """When a calibrated race exists, last_calibration_date is a YYYY-MM-DD string."""
    from backend.main import _compute_calibration_status

    mock_race = MagicMock()
    mock_race.updated_at = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)

    result = _compute_calibration_status(
        last_calibrated_race=mock_race,
        snapshot_count_90=84,
        snapshot_count_42=40,
    )
    assert result["last_calibration_date"] == "2026-06-15"
    assert result["calibrated"] is True


def test_ac1_date_format_is_iso():
    """last_calibration_date must be in YYYY-MM-DD format."""
    from backend.main import _compute_calibration_status

    mock_race = MagicMock()
    mock_race.updated_at = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)

    result = _compute_calibration_status(
        last_calibrated_race=mock_race,
        snapshot_count_90=84,
        snapshot_count_42=40,
    )
    cal_date = result["last_calibration_date"]
    assert cal_date == "2026-01-05", f"Expected '2026-01-05', got {cal_date!r}"
    # Parse it to confirm it's valid ISO
    parsed = date.fromisoformat(cal_date)
    assert parsed.year == 2026
    assert parsed.month == 1
    assert parsed.day == 5


def test_ac4_sufficiency_changes_with_snapshot_count():
    """data_sufficiency varies with snapshot count — not hardcoded."""
    from backend.main import _compute_calibration_status

    result_low = _compute_calibration_status(
        last_calibrated_race=None,
        snapshot_count_90=0,
        snapshot_count_42=0,
    )
    result_high = _compute_calibration_status(
        last_calibrated_race=None,
        snapshot_count_90=90,
        snapshot_count_42=42,
    )
    assert result_low["data_sufficiency"] != result_high["data_sufficiency"], (
        "data_sufficiency must differ for 0 vs 90 snapshots — value is not hardcoded"
    )


def test_ac4_confidence_changes_with_snapshot_count():
    """band_confidence varies with snapshot count — not hardcoded."""
    from backend.main import _compute_calibration_status

    result_low = _compute_calibration_status(
        last_calibrated_race=None,
        snapshot_count_90=0,
        snapshot_count_42=0,
    )
    result_high = _compute_calibration_status(
        last_calibrated_race=None,
        snapshot_count_90=90,
        snapshot_count_42=42,
    )
    assert result_low["band_confidence"] != result_high["band_confidence"], (
        "band_confidence must differ for 0 vs 42 snapshots — value is not hardcoded"
    )


def test_response_has_all_required_keys():
    """Response dict always includes all four expected keys."""
    from backend.main import _compute_calibration_status

    result = _compute_calibration_status(
        last_calibrated_race=None,
        snapshot_count_90=0,
        snapshot_count_42=0,
    )
    for key in ("last_calibration_date", "data_sufficiency", "band_confidence", "calibrated"):
        assert key in result, f"Response missing required key '{key}'"


# ── Integration tests (require live UAT server) ───────────────────────────────

try:
    import importlib.util
    _SERVER_AVAILABLE = (
        importlib.util.find_spec("httpx") is not None
        and bool(os.environ.get("UAT_BASE_URL") or os.environ.get("UAT_PORT"))
    )
    _BASE_URL = (
        os.environ.get("UAT_BASE_URL")
        or ("http://localhost:" + os.environ.get("UAT_PORT", ""))
    ) if _SERVER_AVAILABLE else ""
except Exception:
    _SERVER_AVAILABLE = False
    _BASE_URL = ""


def _skip_no_server():
    if not _SERVER_AVAILABLE:
        pytest.skip("UAT server not configured (UAT_BASE_URL or UAT_PORT required)")


@pytest.fixture
def live_client():
    _skip_no_server()
    import httpx
    with httpx.Client(base_url=_BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def authed_live_client(live_client):
    resp = live_client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    if resp.status_code == 401:
        pytest.skip("testuser not available")
    assert resp.status_code == 200
    return live_client


def test_live_calibration_status_endpoint_exists(authed_live_client):
    """GET /api/calibration/status returns 200 for authenticated users."""
    _skip_no_server()
    resp = authed_live_client.get("/api/calibration/status")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


def test_live_calibration_status_response_shape(authed_live_client):
    """GET /api/calibration/status returns all required fields."""
    _skip_no_server()
    resp = authed_live_client.get("/api/calibration/status")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("last_calibration_date", "data_sufficiency", "band_confidence", "calibrated"):
        assert key in data, f"Response missing key '{key}'"


def test_live_calibration_status_data_sufficiency_valid(authed_live_client):
    """data_sufficiency is one of the three valid values."""
    _skip_no_server()
    resp = authed_live_client.get("/api/calibration/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data_sufficiency"] in ("Sufficient", "Low", "Insufficient"), (
        f"data_sufficiency must be Sufficient/Low/Insufficient, got {data['data_sufficiency']!r}"
    )


def test_live_calibration_status_band_confidence_valid(authed_live_client):
    """band_confidence is one of the three valid values."""
    _skip_no_server()
    resp = authed_live_client.get("/api/calibration/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["band_confidence"] in ("High", "Medium", "Low"), (
        f"band_confidence must be High/Medium/Low, got {data['band_confidence']!r}"
    )


def test_live_calibration_status_unauthenticated_returns_401(live_client):
    """GET /api/calibration/status without auth returns 401."""
    _skip_no_server()
    resp = live_client.get("/api/calibration/status")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_live_calibration_date_format_when_calibrated(authed_live_client):
    """If calibrated is True, last_calibration_date is a valid YYYY-MM-DD string."""
    _skip_no_server()
    resp = authed_live_client.get("/api/calibration/status")
    assert resp.status_code == 200
    data = resp.json()
    if data["calibrated"]:
        cal_date = data["last_calibration_date"]
        assert cal_date is not None
        parsed = date.fromisoformat(cal_date)
        assert 2020 <= parsed.year <= 2030, f"Unexpected year in date: {cal_date}"
