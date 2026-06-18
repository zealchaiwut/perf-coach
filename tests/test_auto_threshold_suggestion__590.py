"""Tests for issue #590: Add auto-threshold suggestion from duration curve (runs against UAT)"""
import os


# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


# ── Pure function tests (no HTTP, no database) ──────────────────────────────────


def test_suggest_thresholds__300w_20min_ftp_285w():
    """AC: 300 W → 285 W (best 20-minute power × 0.95)."""
    from backend.services.suggest_thresholds import suggest_thresholds

    # duration_curve maps duration_seconds → best_value (watts)
    duration_curve = {1200: 300}  # 1200 seconds = 20 minutes
    recent_runs = []

    result = suggest_thresholds(duration_curve, recent_runs)

    assert "suggestions" in result
    assert result["suggestions"]["ftp_w"]["value"] == 285
    assert result["suggestions"]["ftp_w"]["high_confidence"] is True


def test_suggest_thresholds__fallback_25min_to_20_60min_range():
    """AC: Fallback from missing 20-min point to best in 20–60 min range."""
    from backend.services.suggest_thresholds import suggest_thresholds

    # No 20-minute point; best sustained is 30 minutes @ 250 W
    duration_curve = {1800: 250}  # 1800 seconds = 30 minutes
    recent_runs = []

    result = suggest_thresholds(duration_curve, recent_runs)

    assert result["suggestions"]["ftp_w"]["value"] == 250 * 0.95  # 237.5
    # Fallback should have lower confidence than exact 20-min match
    assert result["suggestions"]["ftp_w"]["high_confidence"] is False


def test_suggest_thresholds__pace_hr_from_same_run():
    """AC: Pace and HR derived from the same qualifying run effort (20–30 min)."""
    from backend.services.suggest_thresholds import suggest_thresholds

    duration_curve = {}
    # Two runs: one 15-min (outside range), one 25-min (qualifies)
    recent_runs = [
        {
            "duration_seconds": 900,  # 15 minutes — too short
            "avg_pace_seconds_per_km": 300,
            "avg_hr_bpm": 160,
        },
        {
            "duration_seconds": 1500,  # 25 minutes — qualifies
            "avg_pace_seconds_per_km": 280,
            "avg_hr_bpm": 168,
        },
    ]

    result = suggest_thresholds(duration_curve, recent_runs)

    assert result["suggestions"]["threshold_pace_seconds_per_km"]["value"] == 280
    assert result["suggestions"]["threshold_hr"]["value"] == 168
    # Both should have high_confidence only if >= 2 qualifying runs
    assert result["suggestions"]["threshold_pace_seconds_per_km"]["high_confidence"] is False
    assert result["suggestions"]["threshold_hr"]["high_confidence"] is False


def test_suggest_thresholds__high_confidence_pace_hr_two_runs():
    """AC: Pace/HR high_confidence only when >= 2 qualifying 20–30 min efforts."""
    from backend.services.suggest_thresholds import suggest_thresholds

    duration_curve = {}
    recent_runs = [
        {"duration_seconds": 1200, "avg_pace_seconds_per_km": 280, "avg_hr_bpm": 168},  # 20 min
        {"duration_seconds": 1500, "avg_pace_seconds_per_km": 285, "avg_hr_bpm": 170},  # 25 min
    ]

    result = suggest_thresholds(duration_curve, recent_runs)

    assert result["suggestions"]["threshold_pace_seconds_per_km"]["high_confidence"] is True
    assert result["suggestions"]["threshold_hr"]["high_confidence"] is True


def test_suggest_thresholds__thin_history():
    """AC: Return empty with reason when < required qualifying data."""
    from backend.services.suggest_thresholds import suggest_thresholds

    duration_curve = {}
    recent_runs = []

    result = suggest_thresholds(duration_curve, recent_runs)

    assert result["suggestions"] == {}
    assert "reason" in result
    assert "not enough history" in result["reason"].lower()


def test_suggest_thresholds__none_inputs():
    """AC: None inputs return empty dict with reason, no exception."""
    from backend.services.suggest_thresholds import suggest_thresholds

    result = suggest_thresholds(None, None)

    assert result["suggestions"] == {}
    assert "reason" in result


def test_suggest_thresholds__empty_dicts():
    """AC: Empty dict inputs return empty with reason."""
    from backend.services.suggest_thresholds import suggest_thresholds

    result = suggest_thresholds({}, [])

    assert result["suggestions"] == {}
    assert "reason" in result


def test_suggest_thresholds__debug_object_present():
    """AC: Debug object exposes source effort for each suggestion."""
    from backend.services.suggest_thresholds import suggest_thresholds

    duration_curve = {1200: 300}
    recent_runs = [
        {"duration_seconds": 1500, "avg_pace_seconds_per_km": 280, "avg_hr_bpm": 168},
    ]

    result = suggest_thresholds(duration_curve, recent_runs)

    assert "debug" in result
    # Debug should describe how each threshold was derived
    assert "ftp_w" in result["debug"]
    assert "threshold_pace_seconds_per_km" in result["debug"]
    assert "threshold_hr" in result["debug"]


def test_suggest_thresholds__no_20min_point_no_fallback_candidate():
    """AC: No fallback when duration_curve lacks 20–60 min range."""
    from backend.services.suggest_thresholds import suggest_thresholds

    # Only very short duration
    duration_curve = {60: 400}  # 1 minute
    recent_runs = []

    result = suggest_thresholds(duration_curve, recent_runs)

    # No FTP suggestion should be present
    assert "ftp_w" not in result["suggestions"] or result["suggestions"]["ftp_w"]["value"] is None


def test_suggest_thresholds__pace_range_boundary_inclusive():
    """AC: Pace range 20–30 min (1200–1800 sec) inclusive at both ends."""
    from backend.services.suggest_thresholds import suggest_thresholds

    duration_curve = {}
    recent_runs = [
        {"duration_seconds": 1200, "avg_pace_seconds_per_km": 280, "avg_hr_bpm": 168},  # exactly 20 min
        {"duration_seconds": 1800, "avg_pace_seconds_per_km": 285, "avg_hr_bpm": 170},  # exactly 30 min
    ]

    result = suggest_thresholds(duration_curve, recent_runs)

    # Both should qualify; fastest pace selected
    assert result["suggestions"]["threshold_pace_seconds_per_km"]["value"] == 280
    assert result["suggestions"]["threshold_pace_seconds_per_km"]["high_confidence"] is True


def test_suggest_thresholds__manual_override_not_in_function():
    """AC: Function never reads/writes user_preferences; caller handles precedence."""
    from backend.services.suggest_thresholds import suggest_thresholds

    # This function should not access any user_preferences table
    # and should not raise if manual threshold exists
    duration_curve = {1200: 300}
    recent_runs = []

    # Should complete without error or DB access
    result = suggest_thresholds(duration_curve, recent_runs)
    assert result["suggestions"]["ftp_w"]["value"] == 285
