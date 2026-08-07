"""AC tests for issue #1692 — Body Composition card frontend shape.

compute_composition_trend() must expose `latest` and `verdict` keys so that
weight.js and weight-timeline.js can render correctly.
"""
from __future__ import annotations

import datetime

from backend.services.body_composition import compute_composition_trend

AS_OF = datetime.date(2025, 8, 1)


def _reading(days_ago: int, weight_kg: float, body_fat_pct: float) -> dict:
    return {
        "date": AS_OF - datetime.timedelta(days=days_ago),
        "weight_kg": weight_kg,
        "body_fat_pct": body_fat_pct,
    }


# ── latest key ────────────────────────────────────────────────────────────────


def test_composition_latest_absent_when_not_readable():
    """When fewer than 4 readings exist, latest must be None (card stays in empty state)."""
    readings = [_reading(i * 7, 80.0, 20.0) for i in range(3)]
    result = compute_composition_trend(readings, AS_OF)
    assert result["readable"] is False
    assert result["latest"] is None


def test_composition_latest_present_when_readable():
    """When readable, latest must expose lean_mass_kg, fat_mass_kg, body_fat_pct."""
    readings = [_reading(i * 7, 80.0, 20.0) for i in range(5)]
    result = compute_composition_trend(readings, AS_OF)
    assert result["readable"] is True
    latest = result["latest"]
    assert latest is not None
    assert "lean_mass_kg" in latest
    assert "fat_mass_kg" in latest
    assert "body_fat_pct" in latest
    assert latest["lean_mass_kg"] is not None
    assert latest["fat_mass_kg"] is not None
    assert latest["body_fat_pct"] is not None


def test_composition_latest_matches_trend_values():
    """latest values must equal the 4-week rolling means already in the payload."""
    readings = [_reading(i * 7, 80.0 - i * 0.1, 20.0 - i * 0.1) for i in range(6)]
    result = compute_composition_trend(readings, AS_OF)
    assert result["readable"] is True
    latest = result["latest"]
    assert latest["lean_mass_kg"] == result["lean_mass_kg_trend"]
    assert latest["fat_mass_kg"] == result["fat_mass_kg_trend"]
    assert latest["body_fat_pct"] == result["body_fat_pct_trend"]


# ── verdict key ───────────────────────────────────────────────────────────────


def test_composition_verdict_none_when_not_readable():
    """verdict must be None when there is not enough data to form a trend."""
    readings = [_reading(i * 7, 80.0, 20.0) for i in range(3)]
    result = compute_composition_trend(readings, AS_OF)
    assert result["verdict"] is None


def test_composition_verdict_present_when_lean_mass_stable():
    """A non-None verdict string is returned when lean mass is not falling."""
    readings = [_reading(i * 7, 80.0, 20.0) for i in range(8)]
    result = compute_composition_trend(readings, AS_OF)
    assert result["readable"] is True
    assert result["lean_mass_falling"] is False
    assert isinstance(result["verdict"], str)
    assert len(result["verdict"]) > 0


def test_composition_verdict_none_when_lean_mass_falling():
    """verdict is None when lean mass is genuinely falling — the card shows no 'good' banner."""
    prev_readings = [_reading((7 + i) * 7, 80.0, 20.0) for i in range(4)]
    recent_readings = [_reading(i * 7, 78.9, 20.0) for i in range(4)]
    result = compute_composition_trend(prev_readings + recent_readings, AS_OF)
    assert result["readable"] is True
    assert result["lean_mass_falling"] is True
    assert result["verdict"] is None


# ── timeline overlay ──────────────────────────────────────────────────────────


def test_composition_timeline_overlay_shape():
    """latest.lean_mass_kg and .fat_mass_kg must be non-None so the timeline overlay renders."""
    readings = [_reading(i * 7, 80.0, 20.0) for i in range(5)]
    result = compute_composition_trend(readings, AS_OF)
    latest = result["latest"]
    assert latest is not None
    assert latest["lean_mass_kg"] is not None
    assert latest["fat_mass_kg"] is not None
