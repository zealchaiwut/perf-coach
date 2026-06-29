"""
Tests for issue #1110: Add widening confidence band to projection horizon.

Acceptance criteria verified:
- AC1: Each projected entry exposes a `confidence_band` field representing
       ± days of uncertainty.
- AC2: Band width increases monotonically as days-to-projected-date increases
       (no entry further in the future has a narrower band than a closer one).
- AC3: Band width of zero is valid only for the current day / zero-horizon
       entries.
- AC4: Growth formula is documented in code (docstring or inline comment).
- AC5: py_compile passes on all modified files.
- AC6: Unit tests assert monotonic widening across at least 5 horizon values
       (1, 7, 14, 30, 90 days).
- AC7: Existing projection output is not broken; band is additive, not a
       replacement.
"""
import inspect
import py_compile
from datetime import date


from backend.services.projection import (
    CTL_DECAY,
    confidence_band_days,
    project_fitness,
)

TODAY = date(2026, 6, 29)


# ── AC5: py_compile passes ────────────────────────────────────────────────────

def test_ac5_py_compile_projection():
    import backend.services.projection as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


# ── AC4: growth formula documented in source ─────────────────────────────────

def test_ac4_formula_documented():
    """confidence_band_days must have a docstring explaining the growth model."""
    src = inspect.getsource(confidence_band_days)
    assert len(src) > 0
    # The function must have a docstring
    fn = confidence_band_days
    assert fn.__doc__ is not None and len(fn.__doc__.strip()) > 0, (
        "confidence_band_days must have a docstring explaining the growth formula"
    )


# ── AC3: zero horizon yields zero band ────────────────────────────────────────

def test_ac3_zero_horizon_zero_band():
    assert confidence_band_days(0) == 0


def test_ac3_negative_horizon_zero_band():
    """Negative horizon (past dates) should also return 0."""
    assert confidence_band_days(-5) == 0


# ── AC6: monotonic widening across 5+ horizon values ─────────────────────────

def test_ac6_monotonic_widening():
    """Band must be non-decreasing for horizons 1, 7, 14, 30, 90."""
    horizons = [1, 7, 14, 30, 90]
    bands = [confidence_band_days(h) for h in horizons]
    for i in range(len(bands) - 1):
        assert bands[i] <= bands[i + 1], (
            f"Band for horizon={horizons[i]} ({bands[i]}) is wider than "
            f"horizon={horizons[i+1]} ({bands[i+1]}) — must be monotonically non-decreasing"
        )


def test_ac6_strictly_increasing_for_positive_horizons():
    """Longer horizons must produce strictly wider bands (not just non-decreasing)."""
    h1, h7, h14, h30, h90 = (
        confidence_band_days(1),
        confidence_band_days(7),
        confidence_band_days(14),
        confidence_band_days(30),
        confidence_band_days(90),
    )
    assert h1 < h7 < h14 < h30 < h90, (
        f"Expected strict increase: {h1} < {h7} < {h14} < {h30} < {h90}"
    )


def test_ac6_positive_band_for_positive_horizons():
    """All positive horizons must yield a positive band (> 0)."""
    for horizon in [1, 7, 14, 30, 90]:
        band = confidence_band_days(horizon)
        assert band > 0, f"Expected positive band for horizon={horizon}, got {band}"


# ── AC1: project_fitness entries include confidence_band ──────────────────────

def test_ac1_confidence_band_in_projection_output():
    """Every entry returned by project_fitness must have a confidence_band key."""
    result = project_fitness(
        planned_load=[50.0] * 14,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
    )
    assert len(result) == 14
    for day, entry in result.items():
        assert "confidence_band" in entry, (
            f"Entry for {day} is missing 'confidence_band': {entry}"
        )


def test_ac1_confidence_band_is_numeric():
    """confidence_band values must be numeric (int or float)."""
    result = project_fitness(
        planned_load=[30.0] * 5,
        start_ctl=40.0,
        start_atl=50.0,
        start_date=TODAY,
    )
    for day, entry in result.items():
        assert isinstance(entry["confidence_band"], (int, float)), (
            f"confidence_band for {day} is not numeric: {entry['confidence_band']}"
        )


# ── AC2: projection entries monotonically widen with horizon ─────────────────

def test_ac2_projection_bands_monotonic():
    """Bands in the projection series must be non-decreasing by date."""
    result = project_fitness(
        planned_load=[50.0] * 30,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
    )
    sorted_days = sorted(result.keys())
    bands = [result[d]["confidence_band"] for d in sorted_days]
    for i in range(len(bands) - 1):
        assert bands[i] <= bands[i + 1], (
            f"Band at {sorted_days[i]} ({bands[i]}) is wider than "
            f"band at {sorted_days[i+1]} ({bands[i+1]})"
        )


def test_ac2_later_entries_strictly_wider():
    """The last entry must have a strictly wider band than the first."""
    result = project_fitness(
        planned_load=[50.0] * 90,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
    )
    sorted_days = sorted(result.keys())
    first_band = result[sorted_days[0]]["confidence_band"]
    last_band = result[sorted_days[-1]]["confidence_band"]
    assert last_band > first_band, (
        f"Expected last-day band ({last_band}) > first-day band ({first_band})"
    )


# ── AC7: existing fields still present (additive, not replacement) ────────────

def test_ac7_existing_ctl_atl_tsb_unchanged():
    """project_fitness must still return ctl, atl, tsb alongside confidence_band."""
    result = project_fitness(
        planned_load=[40.0] * 7,
        start_ctl=50.0,
        start_atl=60.0,
        start_date=TODAY,
    )
    for day, entry in result.items():
        assert "ctl" in entry, f"Missing 'ctl' for {day}"
        assert "atl" in entry, f"Missing 'atl' for {day}"
        assert "tsb" in entry, f"Missing 'tsb' for {day}"
        assert "confidence_band" in entry, f"Missing 'confidence_band' for {day}"


def test_ac7_ctl_values_correct():
    """CTL computation must not be affected by the confidence band addition."""
    planned = [60.0] * 5
    result = project_fitness(
        planned_load=planned,
        start_ctl=50.0,
        start_atl=50.0,
        start_date=TODAY,
    )
    ctl = 50.0
    for day in sorted(result.keys()):
        ctl = ctl * CTL_DECAY + 60.0 * (1 - CTL_DECAY)
        assert abs(result[day]["ctl"] - ctl) < 1e-9, (
            f"CTL mismatch on {day}: expected {ctl}, got {result[day]['ctl']}"
        )


def test_ac7_empty_planned_load_returns_empty():
    """Empty planned_load must still return an empty dict (no regression)."""
    result = project_fitness(
        planned_load=[],
        start_ctl=50.0,
        start_atl=60.0,
        start_date=TODAY,
    )
    assert result == {}
