"""Tests for issue #694: Compute power and pace duration curves per workout.

Acceptance criteria verified:
  AC1  — compute_power_curve is a pure function accepting a power stream and
          returning best rolling-average for each duration
  AC2  — compute_pace_curve accepts pace stream, returns best (min) rolling-average
  AC3  — duration list is a single named constant DURATION_LADDER
  AC4  — stream path uses true sliding-window averages
  AC5  — lap/aggregate path returns confidence="approx"
  AC6  — missing/insufficient input returns empty result with human-readable reason
  AC7  — each point has duration_seconds, value, source_workout_id, date, confidence,
          and a debug dict with intermediate values
  AC8  — docstrings contain worked examples in plain prose
  AC10 — fetch_workout_curves is the thin DB caller; pure functions have no DB calls
  AC11 — unit tests: stream ≥3 durations, aggregate ≥2, missing-input with reason,
          workout shorter than longest window
"""

import pytest
from backend.services.per_workout_curves import (
    DURATION_LADDER,
    compute_power_curve,
    compute_pace_curve,
    fetch_workout_curves,
)

WORKOUT_ID = "test-workout-694-001"


# ── Helpers ───────────────────────────────────────────────────────────────────

def flat_stream(value, length):
    return [float(value)] * length


def make_aggregates(duration_seconds=5400, avg_power=230, distance_km=20.0, workout_date="2024-01-01"):
    return {
        "duration_seconds": duration_seconds,
        "avg_power": avg_power,
        "distance_km": float(distance_km),
        "workout_date": workout_date,
    }


def make_laps(*specs):
    """Each spec is (duration_seconds, avg_power, distance_km)."""
    return [
        {"duration_seconds": d, "avg_power": p, "distance_km": dist}
        for d, p, dist in specs
    ]


# ── AC3: DURATION_LADDER constant ─────────────────────────────────────────────

def test_duration_ladder_is_named_constant():
    """AC3: DURATION_LADDER is a module-level named constant, not a literal."""
    assert DURATION_LADDER is not None
    assert isinstance(DURATION_LADDER, list)


def test_duration_ladder_has_12_entries():
    """AC3: standard ladder has exactly 12 duration windows."""
    assert len(DURATION_LADDER) == 12


def test_duration_ladder_values():
    """AC3: ladder spans 1 s through 90 min (5400 s)."""
    expected = [1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 5400]
    assert DURATION_LADDER == expected


# ── AC7: per-point shape ──────────────────────────────────────────────────────

def test_power_point_has_all_required_fields():
    """AC7: each power point has duration_seconds, value, source_workout_id,
    date, confidence, and debug."""
    stream = flat_stream(250, 100)
    points = compute_power_curve(WORKOUT_ID, stream, [], make_aggregates(), [60])
    p = points[0]
    for field in ("duration_seconds", "value", "source_workout_id", "date", "confidence", "debug"):
        assert field in p, f"Missing field: {field}"


def test_pace_point_has_all_required_fields():
    """AC7: each pace point has all required fields."""
    stream = flat_stream(300, 100)
    points = compute_pace_curve(WORKOUT_ID, stream, [], make_aggregates(), [60])
    p = points[0]
    for field in ("duration_seconds", "value", "source_workout_id", "date", "confidence", "debug"):
        assert field in p, f"Missing field: {field}"


def test_power_uses_value_not_best_value():
    """AC7: field is named 'value', not 'best_value'."""
    stream = flat_stream(250, 100)
    points = compute_power_curve(WORKOUT_ID, stream, [], make_aggregates(), [60])
    assert "value" in points[0]
    assert "best_value" not in points[0]


def test_pace_uses_value_not_best_value():
    """AC7: pace field is named 'value', not 'best_value'."""
    stream = flat_stream(300, 100)
    points = compute_pace_curve(WORKOUT_ID, stream, [], make_aggregates(), [60])
    assert "value" in points[0]
    assert "best_value" not in points[0]


def test_power_debug_is_dict():
    """AC7: debug field on each point is a dict."""
    stream = flat_stream(250, 100)
    points = compute_power_curve(WORKOUT_ID, stream, [], make_aggregates(), [60])
    assert isinstance(points[0]["debug"], dict)


def test_power_debug_contains_window_size():
    """AC7: debug includes the window size used for that duration."""
    stream = flat_stream(250, 100)
    points = compute_power_curve(WORKOUT_ID, stream, [], make_aggregates(), [60])
    assert "window_size" in points[0]["debug"]
    assert points[0]["debug"]["window_size"] == 60


def test_power_debug_contains_aggregation_method():
    """AC7: debug includes the aggregation method name."""
    stream = flat_stream(250, 100)
    points = compute_power_curve(WORKOUT_ID, stream, [], make_aggregates(), [60])
    assert "aggregation_method" in points[0]["debug"]


def test_pace_debug_contains_aggregation_method():
    """AC7: pace debug includes aggregation_method."""
    stream = flat_stream(300, 100)
    points = compute_pace_curve(WORKOUT_ID, stream, [], make_aggregates(), [60])
    assert "aggregation_method" in points[0]["debug"]


def test_power_source_workout_id_matches():
    """AC7: source_workout_id in every point equals the passed workout_id."""
    stream = flat_stream(250, 100)
    points = compute_power_curve(WORKOUT_ID, stream, [], make_aggregates(), [5, 60])
    for p in points:
        assert str(p["source_workout_id"]) == str(WORKOUT_ID)


def test_power_date_from_aggregates():
    """AC7: date field matches workout_date in aggregates."""
    stream = flat_stream(250, 100)
    agg = make_aggregates(workout_date="2024-06-15")
    points = compute_power_curve(WORKOUT_ID, stream, [], agg, [60])
    assert points[0]["date"] == "2024-06-15"


def test_power_date_none_when_no_aggregates():
    """AC7: date is None when aggregates is None."""
    stream = flat_stream(250, 100)
    points = compute_power_curve(WORKOUT_ID, stream, [], None, [60])
    assert points[0]["date"] is None


# ── AC1 + AC4: stream-based computation (≥3 durations required) ──────────────

def test_power_stream_3_durations_all_measured():
    """AC11/AC1: stream covering 3 durations → all confidence='measured'."""
    stream = flat_stream(300, 600)
    points = compute_power_curve(WORKOUT_ID, stream, [], None, [5, 60, 300])
    for p in points:
        assert p["confidence"] == "measured", f"Expected measured at {p['duration_seconds']}s"
        assert p["value"] is not None


def test_pace_stream_3_durations_all_measured():
    """AC11/AC2: pace stream covering 3 durations → all confidence='measured'."""
    stream = flat_stream(300, 600)
    points = compute_pace_curve(WORKOUT_ID, stream, [], None, [5, 60, 300])
    for p in points:
        assert p["confidence"] == "measured"
        assert p["value"] is not None


def test_power_stream_rolling_max():
    """AC4: returns the highest rolling average, not the global average."""
    # First 5 samples at 400 W, rest at 200 W → 5-second best = 400
    stream = [400.0] * 5 + [200.0] * 55
    points = compute_power_curve(WORKOUT_ID, stream, [], None, [5])
    assert abs(points[0]["value"] - 400.0) < 0.01


def test_pace_stream_rolling_min():
    """AC4: pace returns the LOWEST rolling average (fastest = best)."""
    # First 5 at 240 s/km (fast), rest at 360 s/km
    stream = [240.0] * 5 + [360.0] * 55
    points = compute_pace_curve(WORKOUT_ID, stream, [], None, [5])
    assert abs(points[0]["value"] - 240.0) < 0.01


def test_power_flat_stream_equals_constant():
    """AC4: flat power stream → rolling max equals the constant value."""
    stream = flat_stream(275, 120)
    points = compute_power_curve(WORKOUT_ID, stream, [], None, [60])
    assert abs(points[0]["value"] - 275.0) < 0.01


def test_pace_flat_stream_equals_constant():
    """AC4: flat pace stream → rolling min equals the constant value."""
    stream = flat_stream(320, 120)
    points = compute_pace_curve(WORKOUT_ID, stream, [], None, [60])
    assert abs(points[0]["value"] - 320.0) < 0.01


def test_power_full_ladder_stream_all_measured():
    """AC1: stream covering all 12 durations → 12 measured points."""
    stream = flat_stream(280, 5500)
    points = compute_power_curve(WORKOUT_ID, stream, [], None, DURATION_LADDER)
    assert len(points) == 12
    assert all(p["confidence"] == "measured" for p in points)


def test_pace_full_ladder_stream_all_measured():
    """AC2: pace stream covering all 12 durations → 12 measured points."""
    stream = flat_stream(300, 5500)
    points = compute_pace_curve(WORKOUT_ID, stream, [], None, DURATION_LADDER)
    assert len(points) == 12
    assert all(p["confidence"] == "measured" for p in points)


# ── AC5: aggregate-based approximation (≥2 durations required) ───────────────

def test_power_aggregate_2_durations_confidence_approx():
    """AC11/AC5: lap fallback for 2 durations → confidence='approx'."""
    laps = make_laps((120, 310, 0.5), (300, 280, 1.2))
    points = compute_power_curve(WORKOUT_ID, None, laps, None, [60, 120])
    assert len(points) == 2
    for p in points:
        assert p["confidence"] == "approx"


def test_pace_aggregate_2_durations_confidence_approx():
    """AC11/AC5: pace lap fallback for 2 durations → confidence='approx'."""
    laps = make_laps((300, None, 1.0), (600, None, 2.0))
    points = compute_pace_curve(WORKOUT_ID, None, laps, None, [60, 120])
    assert len(points) == 2
    for p in points:
        assert p["confidence"] == "approx"


def test_power_lap_fallback_uses_max_avg_power():
    """AC5: when multiple qualifying laps, highest avg_power is chosen."""
    laps = make_laps((120, 300, 0.5), (180, 320, 0.8))
    points = compute_power_curve(WORKOUT_ID, None, laps, None, [60])
    assert points[0]["value"] == 320


def test_pace_lap_fallback_uses_min_pace():
    """AC5: when multiple qualifying laps, fastest (lowest s/km) is chosen.
    lap A: 120 s / 0.4 km = 300 s/km
    lap B: 300 s / 1.2 km = 250 s/km (faster)
    """
    laps = make_laps((120, None, 0.4), (300, None, 1.2))
    points = compute_pace_curve(WORKOUT_ID, None, laps, None, [60])
    assert abs(points[0]["value"] - 250.0) < 0.01


def test_power_workout_aggregate_fallback():
    """AC5: falls back to workout-level avg_power when no lap qualifies."""
    laps = make_laps((30, 400, 0.1))
    agg = make_aggregates(duration_seconds=3600, avg_power=230)
    points = compute_power_curve(WORKOUT_ID, None, laps, agg, [300])
    assert points[0]["value"] == 230
    assert points[0]["confidence"] == "approx"


def test_pace_workout_aggregate_fallback():
    """AC5: pace falls back to workout-level distance/duration when no lap qualifies."""
    laps = make_laps((30, None, 0.1))
    # 1800 s / 6.0 km = 300 s/km
    agg = make_aggregates(duration_seconds=1800, avg_power=None, distance_km=6.0)
    points = compute_pace_curve(WORKOUT_ID, None, laps, agg, [300])
    assert abs(points[0]["value"] - 300.0) < 0.01
    assert points[0]["confidence"] == "approx"


def test_power_aggregate_debug_has_aggregation_method():
    """AC5: aggregate path debug dict includes aggregation_method."""
    laps = make_laps((120, 300, 0.5))
    points = compute_power_curve(WORKOUT_ID, None, laps, None, [60])
    assert "aggregation_method" in points[0]["debug"]


# ── AC6: missing/insufficient input → empty result with reason ────────────────

def test_power_missing_input_no_exception():
    """AC6: no stream, laps, or aggregates → no exception raised."""
    try:
        compute_power_curve(WORKOUT_ID, None, [], None, DURATION_LADDER)
    except Exception as exc:
        raise AssertionError(f"Should not raise: {exc}")


def test_pace_missing_input_no_exception():
    """AC6: pace with no data → no exception raised."""
    try:
        compute_pace_curve(WORKOUT_ID, None, [], None, DURATION_LADDER)
    except Exception as exc:
        raise AssertionError(f"Should not raise: {exc}")


def test_power_missing_all_inputs_value_none():
    """AC6: all 12 durations have value=None when no data is provided."""
    points = compute_power_curve(WORKOUT_ID, None, [], None, DURATION_LADDER)
    assert len(points) == 12
    for p in points:
        assert p["value"] is None


def test_power_missing_all_inputs_has_reason():
    """AC6: each empty point has a non-empty human-readable reason string."""
    points = compute_power_curve(WORKOUT_ID, None, [], None, DURATION_LADDER)
    for p in points:
        assert "reason" in p, f"Missing reason at {p['duration_seconds']}s"
        assert isinstance(p["reason"], str) and len(p["reason"]) > 0


def test_pace_missing_all_inputs_has_reason():
    """AC6: pace empty points all have non-empty reason strings."""
    points = compute_pace_curve(WORKOUT_ID, None, [], None, DURATION_LADDER)
    assert len(points) == 12
    for p in points:
        assert "reason" in p
        assert isinstance(p["reason"], str) and len(p["reason"]) > 0


def test_power_workout_shorter_than_window_reason_mentions_durations():
    """AC6: when workout (480 s) is shorter than window (600 s), reason names both values."""
    agg = make_aggregates(duration_seconds=480, avg_power=250)
    points = compute_power_curve(WORKOUT_ID, None, [], agg, [600])
    p = points[0]
    assert p["value"] is None
    assert "reason" in p
    assert "480" in p["reason"] and "600" in p["reason"]


def test_pace_workout_shorter_than_window_reason_mentions_durations():
    """AC6: pace reason mentions both workout duration and window size."""
    agg = make_aggregates(duration_seconds=480, avg_power=None, distance_km=1.5)
    points = compute_pace_curve(WORKOUT_ID, None, [], agg, [600])
    p = points[0]
    assert p["value"] is None
    assert "reason" in p
    assert "480" in p["reason"] and "600" in p["reason"]


# ── AC11: workout shorter than the longest window ─────────────────────────────

def test_power_8min_workout_short_durations_have_values():
    """AC11/UAT-3: 8-minute aggregate workout → durations ≤ 480 s have values."""
    agg = make_aggregates(duration_seconds=480, avg_power=250, distance_km=2.0)
    points = compute_power_curve(WORKOUT_ID, None, [], agg, DURATION_LADDER)
    by_dur = {p["duration_seconds"]: p for p in points}

    for d in [1, 5, 15, 30, 60, 120, 300]:
        assert by_dur[d]["value"] is not None, f"Expected value at {d}s"

    for d in [600, 1200, 1800, 3600, 5400]:
        assert by_dur[d]["value"] is None, f"Expected empty at {d}s"
        assert "reason" in by_dur[d] and by_dur[d]["reason"]


def test_power_8min_stream_short_durations_measured():
    """AC11: stream of 480 s → durations ≤ 480 s are measured."""
    stream = flat_stream(250, 480)
    points = compute_power_curve(WORKOUT_ID, stream, [], None, [60, 120, 300])
    for p in points:
        assert p["value"] is not None
        assert p["confidence"] == "measured"


def test_power_8min_stream_longer_durations_empty_with_reason():
    """AC11: stream of 480 s with full ladder → durations > 480 s are empty with reason."""
    stream = flat_stream(250, 480)
    points = compute_power_curve(WORKOUT_ID, stream, [], None, DURATION_LADDER)
    by_dur = {p["duration_seconds"]: p for p in points}

    for d in [600, 1200, 1800, 3600, 5400]:
        p = by_dur[d]
        assert p["value"] is None, f"Expected empty at {d}s"
        assert "reason" in p and p["reason"]


def test_pace_8min_workout_short_durations_have_values():
    """AC11: 8-minute pace workout → durations ≤ 480 s have values."""
    # 480 s / 2.0 km = 240 s/km
    agg = make_aggregates(duration_seconds=480, avg_power=None, distance_km=2.0)
    points = compute_pace_curve(WORKOUT_ID, None, [], agg, DURATION_LADDER)
    by_dur = {p["duration_seconds"]: p for p in points}

    for d in [1, 5, 15, 30, 60, 120, 300]:
        assert by_dur[d]["value"] is not None, f"Expected value at {d}s"

    for d in [600, 1200, 1800, 3600, 5400]:
        assert by_dur[d]["value"] is None, f"Expected empty at {d}s"
        assert "reason" in by_dur[d]


# ── AC8: docstrings with plain-prose worked examples ─────────────────────────

def test_power_curve_has_docstring():
    """AC8: compute_power_curve must have a non-empty docstring."""
    assert compute_power_curve.__doc__ is not None
    assert len(compute_power_curve.__doc__.strip()) > 0


def test_pace_curve_has_docstring():
    """AC8: compute_pace_curve must have a non-empty docstring."""
    assert compute_pace_curve.__doc__ is not None
    assert len(compute_pace_curve.__doc__.strip()) > 0


def test_power_docstring_has_worked_example():
    """AC8: docstring includes plain-language worked example."""
    doc = compute_power_curve.__doc__
    assert "example" in doc.lower() or "given" in doc.lower()


def test_pace_docstring_has_worked_example():
    """AC8: pace docstring includes plain-language worked example."""
    doc = compute_pace_curve.__doc__
    assert "example" in doc.lower() or "given" in doc.lower()


# ── AC10: thin DB caller ──────────────────────────────────────────────────────

def _mock_db(stream_power, stream_pace, duration_seconds=5500, distance_km=20.0, avg_power=240):
    """Return a mock db session backed by simple MagicMock objects."""
    from unittest.mock import MagicMock
    from backend.models import ActivityStream, WorkoutSplit, Workout

    stream_row = MagicMock()
    stream_row.power_w = stream_power
    stream_row.pace_seconds_per_km = stream_pace

    workout_row = MagicMock()
    workout_row.duration_seconds = duration_seconds
    workout_row.distance_km = distance_km
    workout_row.avg_power = avg_power
    workout_row.workout_date = "2024-01-01"

    mock_db = MagicMock()

    def _query(model):
        q = MagicMock()
        if model is ActivityStream:
            q.filter.return_value.first.return_value = stream_row
        elif model is WorkoutSplit:
            q.filter.return_value.order_by.return_value.all.return_value = []
        elif model is Workout:
            q.filter.return_value.first.return_value = workout_row
        return q

    mock_db.query.side_effect = _query
    return mock_db


def test_fetch_workout_curves_returns_expected_keys():
    """AC10: fetch_workout_curves returns dict with power_curve and pace_curve."""
    db = _mock_db(flat_stream(250, 5500), flat_stream(300, 5500))
    result = fetch_workout_curves(WORKOUT_ID, db)
    assert "power_curve" in result
    assert "pace_curve" in result
    assert isinstance(result["power_curve"], list)
    assert isinstance(result["pace_curve"], list)


def test_fetch_workout_curves_returns_12_points_each():
    """AC10: each curve has exactly 12 duration points (one per DURATION_LADDER entry)."""
    db = _mock_db(flat_stream(250, 5500), flat_stream(300, 5500))
    result = fetch_workout_curves(WORKOUT_ID, db)
    assert len(result["power_curve"]) == 12
    assert len(result["pace_curve"]) == 12
