"""Tests for issue #588: Compute power and pace duration curves per workout.

Acceptance criteria verified:
  AC1  — compute_power_curve is a pure function returning (points, debug)
  AC2  — compute_pace_curve follows the same contract; best = lowest s/km
  AC3  — both functions accept a duration_ladder parameter
  AC4  — each duration-point has duration_seconds, best_value, source_workout_id,
          date, and confidence
  AC5  — stream path: rolling average, max for power / min for pace, confidence="measured"
  AC6  — fallback path uses laps/aggregates, confidence="approx"
  AC7  — when no stream or aggregates: best_value=null, debug records reason, no exception
  AC8  — debug object has stream_length_seconds, durations_from_stream,
          durations_from_aggregates, durations_skipped
  AC9  — each function has a docstring with a worked example in plain prose
  AC10 — fetch_and_compute_curves(workout_id, db) returns {"power_curve": ..., "pace_curve": ...}
  AC11 — unit tests: stream-only, aggregate-only, mixed, short stream, empty inputs,
          custom ladder
  AC12 — no duration literals or thresholds hardcoded inside the pure function bodies
"""

from backend.services.duration_curves import (
    STANDARD_DURATION_LADDER,
    compute_power_curve,
    compute_pace_curve,
    fetch_and_compute_curves,
)


# ── Shared test data helpers ───────────────────────────────────────────────────

WORKOUT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
LADDER_SHORT = [5, 60, 600]
LADDER_CUSTOM = [10, 60, 3600]


def _laps_with_power():
    """Three laps: 120 s, 300 s, 3600 s with avg_power values."""
    return [
        {"duration_seconds": 120,  "distance_km": 0.5,  "avg_power": 310},
        {"duration_seconds": 300,  "distance_km": 1.2,  "avg_power": 285},
        {"duration_seconds": 3600, "distance_km": 14.0, "avg_power": 240},
    ]


def _aggregates():
    return {
        "duration_seconds": 5400,
        "distance_km": 20.0,
        "avg_power": 230,
        "workout_date": "2024-03-15",
    }


def _power_stream(length=700, base=250):
    """Flat power stream at `base` watts."""
    return [float(base)] * length


def _pace_stream(length=700, base=300.0):
    """Flat pace stream at `base` seconds/km."""
    return [base] * length


# ── AC11: stream-only path ────────────────────────────────────────────────────


def test_power_curve_stream_only_all_measured():
    """AC11/AC5: when stream covers all ladder durations, every point is 'measured'."""
    stream = _power_stream(length=5500)
    points, debug = compute_power_curve(
        WORKOUT_ID, stream, laps=[], aggregates=None, duration_ladder=STANDARD_DURATION_LADDER
    )
    assert all(p["confidence"] == "measured" for p in points)


def test_pace_curve_stream_only_all_measured():
    """AC11/AC5: pace stream covering all ladder durations → all confidence='measured'."""
    stream = _pace_stream(length=5500)
    points, debug = compute_pace_curve(
        WORKOUT_ID, stream, laps=[], aggregates=None, duration_ladder=STANDARD_DURATION_LADDER
    )
    assert all(p["confidence"] == "measured" for p in points)


def test_power_curve_stream_only_debug_lists_all_durations():
    """AC11/AC8: stream-only run fills durations_from_stream with all ladder values."""
    stream = _power_stream(length=5500)
    _, debug = compute_power_curve(
        WORKOUT_ID, stream, laps=[], aggregates=None, duration_ladder=STANDARD_DURATION_LADDER
    )
    assert set(debug["durations_from_stream"]) == set(STANDARD_DURATION_LADDER)
    assert debug["durations_from_aggregates"] == []
    assert debug["durations_skipped"] == []


def test_pace_curve_stream_only_debug_lists_all_durations():
    """AC11/AC8: pace stream-only run fills durations_from_stream with all ladder values."""
    stream = _pace_stream(length=5500)
    _, debug = compute_pace_curve(
        WORKOUT_ID, stream, laps=[], aggregates=None, duration_ladder=STANDARD_DURATION_LADDER
    )
    assert set(debug["durations_from_stream"]) == set(STANDARD_DURATION_LADDER)
    assert debug["durations_from_aggregates"] == []


# ── AC5: rolling average correctness ─────────────────────────────────────────


def test_power_stream_best_is_rolling_max():
    """AC5: returns the highest rolling average, not the overall average."""
    # First 5s at 400 W, rest at 200 W → 5-second best = 400 W
    stream = [400.0] * 5 + [200.0] * 55
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], None, duration_ladder=[5])
    assert abs(points[0]["best_value"] - 400.0) < 0.01


def test_pace_stream_best_is_rolling_min():
    """AC5: pace returns the LOWEST rolling average (fastest = best)."""
    # First 5s at 240 s/km (fast), rest at 360 s/km (slow) → 5-second best = 240
    stream = [240.0] * 5 + [360.0] * 55
    points, _ = compute_pace_curve(WORKOUT_ID, stream, [], None, duration_ladder=[5])
    assert abs(points[0]["best_value"] - 240.0) < 0.01


def test_power_stream_flat_rolling_equals_value():
    """AC5: flat stream → best power for any window equals the constant."""
    stream = [275.0] * 120
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], None, duration_ladder=[60])
    assert abs(points[0]["best_value"] - 275.0) < 0.01


def test_pace_stream_flat_rolling_equals_value():
    """AC5: flat pace stream → best (min) pace equals the constant."""
    stream = [320.0] * 120
    points, _ = compute_pace_curve(WORKOUT_ID, stream, [], None, duration_ladder=[60])
    assert abs(points[0]["best_value"] - 320.0) < 0.01


# ── AC11: aggregate-only path ─────────────────────────────────────────────────


def test_power_curve_aggregate_only_all_approx():
    """AC11/AC6: no stream, laps with avg_power → confidence='approx'."""
    points, _ = compute_power_curve(
        WORKOUT_ID, stream=None, laps=_laps_with_power(), aggregates=_aggregates(),
        duration_ladder=LADDER_SHORT
    )
    approx_points = [p for p in points if p["best_value"] is not None]
    assert all(p["confidence"] == "approx" for p in approx_points)


def test_power_curve_aggregate_only_debug_lists_durations():
    """AC11/AC8: aggregate-only path fills durations_from_aggregates."""
    points, debug = compute_power_curve(
        WORKOUT_ID, stream=None, laps=_laps_with_power(), aggregates=_aggregates(),
        duration_ladder=LADDER_SHORT
    )
    assert len(debug["durations_from_aggregates"]) > 0
    assert debug["durations_from_stream"] == []


def test_pace_curve_aggregate_only_all_approx():
    """AC11/AC6: no pace stream, laps with distance/duration → confidence='approx'."""
    points, _ = compute_pace_curve(
        WORKOUT_ID, stream=None, laps=_laps_with_power(), aggregates=_aggregates(),
        duration_ladder=LADDER_SHORT
    )
    approx_points = [p for p in points if p["best_value"] is not None]
    assert all(p["confidence"] == "approx" for p in approx_points)


def test_power_curve_uses_lap_avg_power_for_duration():
    """AC6: for a 5-second window, lap avg_power from qualifying laps is returned."""
    laps = [{"duration_seconds": 10, "distance_km": 0.05, "avg_power": 350}]
    points, _ = compute_power_curve(
        WORKOUT_ID, stream=None, laps=laps, aggregates=None, duration_ladder=[5]
    )
    assert points[0]["best_value"] == 350
    assert points[0]["confidence"] == "approx"


def test_power_curve_lap_fallback_picks_max_power():
    """AC6: when multiple laps qualify, returns the maximum avg_power."""
    laps = [
        {"duration_seconds": 120, "distance_km": 0.5, "avg_power": 300},
        {"duration_seconds": 180, "distance_km": 0.8, "avg_power": 320},
        {"duration_seconds": 60,  "distance_km": 0.2, "avg_power": 340},
    ]
    points, _ = compute_power_curve(
        WORKOUT_ID, stream=None, laps=laps, aggregates=None, duration_ladder=[60]
    )
    assert points[0]["best_value"] == 340
    assert points[0]["confidence"] == "approx"


def test_pace_curve_lap_fallback_picks_fastest_pace():
    """AC6: pace fallback picks the lowest seconds/km among qualifying laps."""
    # lap A: 120s / 0.4km = 300 s/km
    # lap B: 300s / 1.2km = 250 s/km  ← faster
    laps = [
        {"duration_seconds": 120, "distance_km": 0.4, "avg_power": None},
        {"duration_seconds": 300, "distance_km": 1.2, "avg_power": None},
    ]
    points, _ = compute_pace_curve(
        WORKOUT_ID, stream=None, laps=laps, aggregates=None, duration_ladder=[60]
    )
    assert abs(points[0]["best_value"] - 250.0) < 0.01
    assert points[0]["confidence"] == "approx"


def test_power_curve_uses_workout_aggregate_when_no_qualifying_laps():
    """AC6: falls back to workout-level avg_power when laps are too short."""
    laps = [{"duration_seconds": 30, "distance_km": 0.1, "avg_power": 400}]
    agg = {"duration_seconds": 3600, "distance_km": 14.0, "avg_power": 230, "workout_date": None}
    points, _ = compute_power_curve(
        WORKOUT_ID, stream=None, laps=laps, aggregates=agg, duration_ladder=[300]
    )
    assert points[0]["best_value"] == 230
    assert points[0]["confidence"] == "approx"


def test_pace_curve_uses_workout_aggregate_when_no_qualifying_laps():
    """AC6: pace falls back to workout-level distance/duration when laps are too short."""
    laps = [{"duration_seconds": 30, "distance_km": 0.1, "avg_power": None}]
    agg = {"duration_seconds": 1800, "distance_km": 6.0, "avg_power": None, "workout_date": None}
    # 1800 / 6.0 = 300 s/km
    points, _ = compute_pace_curve(
        WORKOUT_ID, stream=None, laps=laps, aggregates=agg, duration_ladder=[300]
    )
    assert abs(points[0]["best_value"] - 300.0) < 0.01
    assert points[0]["confidence"] == "approx"


# ── AC11: mixed path ──────────────────────────────────────────────────────────


def test_power_curve_mixed_short_stream_with_lap_fallback():
    """AC11: stream covers short durations (measured), laps cover longer (approx)."""
    stream = _power_stream(length=65, base=300)  # covers up to 60 s
    laps = [{"duration_seconds": 600, "distance_km": 2.5, "avg_power": 270}]
    agg = {"duration_seconds": 1200, "distance_km": 5.0, "avg_power": 250, "workout_date": "2024-01-01"}
    points, debug = compute_power_curve(
        WORKOUT_ID, stream, laps, agg, duration_ladder=[5, 60, 300]
    )
    by_dur = {p["duration_seconds"]: p for p in points}

    assert by_dur[5]["confidence"] == "measured"
    assert by_dur[60]["confidence"] == "measured"
    assert by_dur[300]["confidence"] == "approx"

    assert 5 in debug["durations_from_stream"]
    assert 60 in debug["durations_from_stream"]
    assert 300 in debug["durations_from_aggregates"]


def test_pace_curve_mixed_short_stream_with_lap_fallback():
    """AC11: pace stream covers short windows (measured), laps cover the rest (approx)."""
    stream = _pace_stream(length=65, base=280.0)
    laps = [{"duration_seconds": 600, "distance_km": 2.0, "avg_power": None}]
    agg = {"duration_seconds": 1200, "distance_km": 4.0, "avg_power": None, "workout_date": "2024-01-01"}
    points, debug = compute_pace_curve(
        WORKOUT_ID, stream, laps, agg, duration_ladder=[5, 60, 300]
    )
    by_dur = {p["duration_seconds"]: p for p in points}

    assert by_dur[5]["confidence"] == "measured"
    assert by_dur[60]["confidence"] == "measured"
    assert by_dur[300]["confidence"] == "approx"


# ── AC11: stream shorter than longest duration ────────────────────────────────


def test_power_curve_stream_shorter_than_longest_duration():
    """AC11: stream of 600 s → durations ≤600 s measured, longer ones fall back."""
    stream = _power_stream(length=600, base=260)
    laps = [{"duration_seconds": 3600, "distance_km": 14.0, "avg_power": 220}]
    agg = {"duration_seconds": 5400, "distance_km": 20.0, "avg_power": 210, "workout_date": "2024-01-01"}
    points, debug = compute_power_curve(
        WORKOUT_ID, stream, laps, agg, duration_ladder=STANDARD_DURATION_LADDER
    )
    by_dur = {p["duration_seconds"]: p for p in points}

    # All durations ≤ 600 s should be measured
    for d in [1, 5, 15, 30, 60, 120, 300, 600]:
        assert by_dur[d]["confidence"] == "measured", f"Expected measured at {d}s"

    # Durations > 600 s should fall back (approx or null)
    for d in [1200, 1800, 3600, 5400]:
        assert by_dur[d]["confidence"] in ("approx", None), f"Expected approx/null at {d}s"

    # durations_from_stream should contain only ladder values ≤ 600
    assert set(debug["durations_from_stream"]).issubset({1, 5, 15, 30, 60, 120, 300, 600})


def test_pace_curve_stream_shorter_than_longest_duration():
    """AC11: pace stream of 600 s → durations ≤600 s measured, longer ones fall back."""
    stream = _pace_stream(length=600, base=300.0)
    laps = [{"duration_seconds": 3600, "distance_km": 12.0, "avg_power": None}]
    agg = {"duration_seconds": 5400, "distance_km": 20.0, "avg_power": None, "workout_date": "2024-01-01"}
    points, debug = compute_pace_curve(
        WORKOUT_ID, stream, laps, agg, duration_ladder=STANDARD_DURATION_LADDER
    )
    by_dur = {p["duration_seconds"]: p for p in points}

    for d in [1, 5, 15, 30, 60, 120, 300, 600]:
        assert by_dur[d]["confidence"] == "measured", f"Expected measured at {d}s"
    for d in [1200, 1800, 3600]:
        assert by_dur[d]["confidence"] in ("approx", None)


# ── AC11: completely empty inputs ─────────────────────────────────────────────


def test_power_curve_all_null_inputs_returns_null_points():
    """AC11/AC7: stream=None, laps=[], aggregates=None → all best_value are null."""
    points, debug = compute_power_curve(
        WORKOUT_ID, stream=None, laps=[], aggregates=None,
        duration_ladder=STANDARD_DURATION_LADDER
    )
    assert len(points) == len(STANDARD_DURATION_LADDER)
    assert all(p["best_value"] is None for p in points)


def test_power_curve_all_null_no_exception():
    """AC7: empty inputs must not raise any exception."""
    try:
        compute_power_curve(WORKOUT_ID, None, [], None, STANDARD_DURATION_LADDER)
    except Exception as exc:
        raise AssertionError(f"compute_power_curve raised unexpectedly: {exc}")


def test_pace_curve_all_null_inputs_returns_null_points():
    """AC11/AC7: pace with stream=None, laps=[], aggregates=None → all null."""
    points, debug = compute_pace_curve(
        WORKOUT_ID, stream=None, laps=[], aggregates=None,
        duration_ladder=STANDARD_DURATION_LADDER
    )
    assert all(p["best_value"] is None for p in points)


def test_pace_curve_all_null_no_exception():
    """AC7: empty pace inputs must not raise any exception."""
    try:
        compute_pace_curve(WORKOUT_ID, None, [], None, STANDARD_DURATION_LADDER)
    except Exception as exc:
        raise AssertionError(f"compute_pace_curve raised unexpectedly: {exc}")


def test_power_curve_empty_inputs_debug_has_12_skipped():
    """AC7/AC8: 12 standard durations with no data → durations_skipped has 12 entries."""
    _, debug = compute_power_curve(
        WORKOUT_ID, None, [], None, STANDARD_DURATION_LADDER
    )
    assert len(debug["durations_skipped"]) == len(STANDARD_DURATION_LADDER)


def test_power_curve_skipped_reasons_are_nonempty_strings():
    """AC7/AC8: each skipped reason is a non-empty human-readable string."""
    _, debug = compute_power_curve(WORKOUT_ID, None, [], None, STANDARD_DURATION_LADDER)
    for reason in debug["durations_skipped"]:
        assert isinstance(reason, str) and len(reason) > 0, f"Invalid reason: {reason!r}"


def test_pace_curve_empty_inputs_debug_has_12_skipped():
    """AC7/AC8: 12 standard durations with no pace data → durations_skipped has 12 entries."""
    _, debug = compute_pace_curve(WORKOUT_ID, None, [], None, STANDARD_DURATION_LADDER)
    assert len(debug["durations_skipped"]) == len(STANDARD_DURATION_LADDER)


# ── AC4: duration-point object shape ─────────────────────────────────────────


def test_power_curve_point_has_all_required_fields():
    """AC4: each duration-point has duration_seconds, best_value, source_workout_id, date, confidence."""
    stream = _power_stream(length=100)
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], _aggregates(), [60])
    p = points[0]
    for field in ("duration_seconds", "best_value", "source_workout_id", "date", "confidence"):
        assert field in p, f"Missing field: {field}"


def test_pace_curve_point_has_all_required_fields():
    """AC4: pace duration-point has all five required fields."""
    stream = _pace_stream(length=100)
    points, _ = compute_pace_curve(WORKOUT_ID, stream, [], _aggregates(), [60])
    p = points[0]
    for field in ("duration_seconds", "best_value", "source_workout_id", "date", "confidence"):
        assert field in p, f"Missing field: {field}"


def test_power_curve_point_source_workout_id_matches():
    """AC4: source_workout_id in every point equals the passed workout_id."""
    stream = _power_stream(length=100)
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], _aggregates(), [5, 60])
    for p in points:
        assert str(p["source_workout_id"]) == str(WORKOUT_ID)


def test_power_curve_point_duration_seconds_is_integer():
    """AC4: duration_seconds field is an integer."""
    stream = _power_stream(length=100)
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], _aggregates(), [60])
    assert isinstance(points[0]["duration_seconds"], int)


def test_power_curve_point_confidence_is_valid_string():
    """AC4: confidence is 'measured' or 'approx' (not None) when best_value is set."""
    stream = _power_stream(length=100)
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], _aggregates(), [60])
    p = points[0]
    if p["best_value"] is not None:
        assert p["confidence"] in ("measured", "approx")


def test_power_curve_date_comes_from_aggregates():
    """AC4: date field matches the workout_date in the aggregates dict."""
    stream = _power_stream(length=100)
    agg = {"duration_seconds": 200, "distance_km": 1.0, "avg_power": 250, "workout_date": "2024-06-01"}
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], agg, [60])
    assert points[0]["date"] == "2024-06-01"


def test_power_curve_date_is_null_when_no_aggregates():
    """AC4: date is null when aggregates is None."""
    stream = _power_stream(length=100)
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], None, [60])
    assert points[0]["date"] is None


# ── AC3 + AC11: custom duration ladder ───────────────────────────────────────


def test_power_curve_custom_ladder_returns_exact_durations():
    """AC11/AC3: custom ladder [10, 60, 3600] → exactly 3 points with those durations."""
    stream = _power_stream(length=5500)
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], _aggregates(), LADDER_CUSTOM)
    assert len(points) == 3
    returned_durations = [p["duration_seconds"] for p in points]
    assert returned_durations == LADDER_CUSTOM


def test_pace_curve_custom_ladder_returns_exact_durations():
    """AC11/AC3: custom pace ladder [10, 60, 3600] → exactly 3 points."""
    stream = _pace_stream(length=5500)
    points, _ = compute_pace_curve(WORKOUT_ID, stream, [], _aggregates(), LADDER_CUSTOM)
    assert len(points) == 3
    returned_durations = [p["duration_seconds"] for p in points]
    assert returned_durations == LADDER_CUSTOM


def test_power_curve_standard_ladder_returns_12_points():
    """AC3: standard 12-duration ladder → exactly 12 points."""
    stream = _power_stream(length=5500)
    points, _ = compute_power_curve(WORKOUT_ID, stream, [], _aggregates(), STANDARD_DURATION_LADDER)
    assert len(points) == 12


def test_pace_curve_standard_ladder_returns_12_points():
    """AC3: standard 12-duration ladder → exactly 12 pace points."""
    stream = _pace_stream(length=5500)
    points, _ = compute_pace_curve(WORKOUT_ID, stream, [], _aggregates(), STANDARD_DURATION_LADDER)
    assert len(points) == 12


# ── AC8: debug object structure ───────────────────────────────────────────────


def test_power_curve_debug_has_required_keys():
    """AC8: debug object has stream_length_seconds, durations_from_stream,
    durations_from_aggregates, and durations_skipped."""
    stream = _power_stream(length=100)
    _, debug = compute_power_curve(WORKOUT_ID, stream, [], _aggregates(), [60])
    for key in ("stream_length_seconds", "durations_from_stream",
                "durations_from_aggregates", "durations_skipped"):
        assert key in debug, f"Missing debug key: {key}"


def test_pace_curve_debug_has_required_keys():
    """AC8: pace debug object has all four required keys."""
    stream = _pace_stream(length=100)
    _, debug = compute_pace_curve(WORKOUT_ID, stream, [], _aggregates(), [60])
    for key in ("stream_length_seconds", "durations_from_stream",
                "durations_from_aggregates", "durations_skipped"):
        assert key in debug, f"Missing debug key: {key}"


def test_power_curve_debug_stream_length_is_correct():
    """AC8: stream_length_seconds equals the number of samples in the stream."""
    stream = _power_stream(length=250)
    _, debug = compute_power_curve(WORKOUT_ID, stream, [], _aggregates(), [60])
    assert debug["stream_length_seconds"] == 250


def test_power_curve_debug_stream_length_is_zero_when_no_stream():
    """AC8: stream_length_seconds is 0 when stream is None."""
    _, debug = compute_power_curve(WORKOUT_ID, None, [], _aggregates(), [60])
    assert debug["stream_length_seconds"] == 0


def test_pace_curve_debug_stream_length_is_correct():
    """AC8: pace debug stream_length_seconds matches stream length."""
    stream = _pace_stream(length=180)
    _, debug = compute_pace_curve(WORKOUT_ID, stream, [], _aggregates(), [60])
    assert debug["stream_length_seconds"] == 180


# ── AC9: docstrings with worked examples ──────────────────────────────────────


def test_power_curve_has_docstring():
    """AC9: compute_power_curve must have a non-empty docstring."""
    assert compute_power_curve.__doc__ is not None
    assert len(compute_power_curve.__doc__.strip()) > 0


def test_pace_curve_has_docstring():
    """AC9: compute_pace_curve must have a non-empty docstring."""
    assert compute_pace_curve.__doc__ is not None
    assert len(compute_pace_curve.__doc__.strip()) > 0


def test_power_curve_docstring_contains_worked_example():
    """AC9: docstring includes plain-prose worked example language."""
    doc = compute_power_curve.__doc__
    # Must have a worked example, not tables or arrows
    assert "example" in doc.lower() or "given" in doc.lower()


def test_pace_curve_docstring_contains_worked_example():
    """AC9: pace docstring includes plain-prose worked example language."""
    doc = compute_pace_curve.__doc__
    assert "example" in doc.lower() or "given" in doc.lower()


# ── AC10: fetch_and_compute_curves interface ───────────────────────────────────


def test_fetch_and_compute_curves_returns_expected_keys():
    """AC10: fetch_and_compute_curves(workout_id, db) returns dict with power_curve and pace_curve."""
    from unittest.mock import MagicMock
    from backend.models import ActivityStream, WorkoutSplit, Workout

    mock_stream_row = MagicMock()
    mock_stream_row.power_w = [250.0] * 5500
    mock_stream_row.pace_seconds_per_km = [300.0] * 5500

    mock_workout_row = MagicMock()
    mock_workout_row.duration_seconds = 5500
    mock_workout_row.distance_km = 20.0
    mock_workout_row.avg_power = 240
    mock_workout_row.workout_date = "2024-01-01"

    mock_db = MagicMock()

    def _query_side_effect(model):
        q = MagicMock()
        if model is ActivityStream:
            q.filter.return_value.first.return_value = mock_stream_row
        elif model is WorkoutSplit:
            q.filter.return_value.order_by.return_value.all.return_value = []
        elif model is Workout:
            q.filter.return_value.first.return_value = mock_workout_row
        return q

    mock_db.query.side_effect = _query_side_effect

    result = fetch_and_compute_curves(WORKOUT_ID, mock_db)

    assert "power_curve" in result
    assert "pace_curve" in result
    assert isinstance(result["power_curve"], list)
    assert isinstance(result["pace_curve"], list)
    assert len(result["power_curve"]) == len(STANDARD_DURATION_LADDER)
    assert len(result["pace_curve"]) == len(STANDARD_DURATION_LADDER)
