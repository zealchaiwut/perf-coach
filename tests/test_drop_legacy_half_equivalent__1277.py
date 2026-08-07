"""Tests for issue #1277: Drop legacy half_equivalent* payload keys and compute_half_equivalent alias.

Context: #1176 renamed the function and payload field to half_race_equivalent* but kept
backward-compat shims (alias + duplicate payload keys). This ticket eliminates those shims.

AC coverage:
  AC1 — compute_half_equivalent alias is removed from projection.py module scope
  AC2 — projection payload does NOT emit half_equivalent key
  AC3 — projection payload does NOT emit half_equivalent_seconds key
  AC4 — test_projection_endpoint__1112.py imports compute_half_race_equivalent directly,
         not via a 'as compute_half_equivalent' alias
"""
from __future__ import annotations

import pathlib
from datetime import date, timedelta

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PROJECTION_PY = _ROOT / "backend" / "services" / "projection.py"
_TEST_1112 = _ROOT / "tests" / "test_projection_endpoint__1112.py"

_TODAY = date(2026, 8, 5)


def _make_payload(**overrides):
    from backend.services.projection import build_plan_projection_payload

    defaults = {
        "start_ctl": 40.0,
        "start_atl": 45.0,
        "start_date": _TODAY,
        "planned_load": [50.0] * 30,
        "races": [{"date": _TODAY + timedelta(days=14), "distance_km": 42.195, "name": "Marathon"}],
        "thresholds": {"threshold_pace_seconds_per_km": 300},
    }
    defaults.update(overrides)
    return build_plan_projection_payload(**defaults)


# ── AC1: compute_half_equivalent alias is gone ───────────────────────────────

def test_compute_half_equivalent_alias_absent_from_source():
    """AC1: 'compute_half_equivalent =' must not appear in projection.py source."""
    source = _PROJECTION_PY.read_text()
    assert "compute_half_equivalent =" not in source, (
        "Legacy alias 'compute_half_equivalent = compute_half_race_equivalent' "
        "must be removed from projection.py (issue #1277)"
    )


def test_compute_half_equivalent_not_importable():
    """AC1: compute_half_equivalent must not be a name exported from projection.py."""
    import importlib
    import backend.services.projection as proj
    assert not hasattr(proj, "compute_half_equivalent"), (
        "compute_half_equivalent should no longer exist as a module-level name "
        "in backend.services.projection (issue #1277)"
    )


# ── AC2: payload omits half_equivalent key ───────────────────────────────────

def test_payload_race_omits_legacy_half_equivalent_key():
    """AC2: race entry must NOT contain the legacy half_equivalent key."""
    result = _make_payload()
    assert len(result["races"]) == 1
    assert "half_equivalent" not in result["races"][0], (
        "Legacy key 'half_equivalent' must be removed from projection payload (issue #1277)"
    )


# ── AC3: payload omits half_equivalent_seconds key ───────────────────────────

def test_payload_race_omits_legacy_half_equivalent_seconds_key():
    """AC3: race entry must NOT contain the legacy half_equivalent_seconds key."""
    result = _make_payload()
    assert len(result["races"]) == 1
    assert "half_equivalent_seconds" not in result["races"][0], (
        "Legacy key 'half_equivalent_seconds' must be removed from projection payload (issue #1277)"
    )


# ── AC4: test_projection_endpoint__1112 imports without 'as' alias ───────────

def test_1112_test_file_imports_without_alias():
    """AC4: test_projection_endpoint__1112.py must not import compute_half_race_equivalent
    under the old alias name 'compute_half_equivalent'."""
    source = _TEST_1112.read_text()
    assert "compute_half_race_equivalent as compute_half_equivalent" not in source, (
        "test_projection_endpoint__1112.py still uses the 'as compute_half_equivalent' alias "
        "import — migrate it to import compute_half_race_equivalent directly (issue #1277)"
    )


# ── Sanity: new keys still present after migration ───────────────────────────

def test_payload_race_still_has_half_race_equivalent():
    """Sanity: half_race_equivalent is still emitted after legacy keys removed."""
    result = _make_payload()
    assert "half_race_equivalent" in result["races"][0]


def test_payload_race_still_has_half_race_equivalent_seconds():
    """Sanity: half_race_equivalent_seconds is still emitted after legacy keys removed."""
    result = _make_payload()
    assert "half_race_equivalent_seconds" in result["races"][0]
