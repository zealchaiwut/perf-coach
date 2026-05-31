"""Tests for issue #194: strava_activities cache table and detect_stryd_origin helper."""


def test_detect_stryd_origin_device_name_stryd_pod():
    from backend.services.strava import detect_stryd_origin

    assert detect_stryd_origin({"device_name": "Stryd Pod", "type": "Run"}) is True


def test_detect_stryd_origin_external_id_stryd_prefix():
    from backend.services.strava import detect_stryd_origin

    assert detect_stryd_origin({"external_id": "stryd:abc123", "type": "Run"}) is True


def test_detect_stryd_origin_no_indicators():
    from backend.services.strava import detect_stryd_origin

    assert (
        detect_stryd_origin(
            {"device_name": "Apple Watch", "type": "Run", "external_id": "garmin:xyz"}
        )
        is False
    )


def test_detect_stryd_origin_mixed_signals():
    """Power data + Run type present, but device is Apple Watch (not a pod) — returns False.

    Rationale: condition 3 requires all three signals (power + Run + pod device). Partial
    matches are not enough. Two Stryd indicators are independent OR conditions; here none
    of the three routes (device_name, external_id, condition-3) fire, so the result is False.
    """
    from backend.services.strava import detect_stryd_origin

    assert (
        detect_stryd_origin(
            {
                "device_name": "Apple Watch",
                "type": "Run",
                "avg_power_w": 200,
                "external_id": "apple:abc",
            }
        )
        is False
    )


def test_detect_stryd_origin_device_name_case_insensitive():
    from backend.services.strava import detect_stryd_origin

    assert detect_stryd_origin({"device_name": "STRYD ULTRA"}) is True


def test_detect_stryd_origin_external_id_contains_stryd():
    from backend.services.strava import detect_stryd_origin

    assert detect_stryd_origin({"external_id": "abc-stryd-xyz"}) is True


def test_detect_stryd_origin_power_run_pod_device():
    from backend.services.strava import detect_stryd_origin

    assert (
        detect_stryd_origin(
            {
                "device_name": "Garmin Running Dynamics Pod",
                "type": "Run",
                "avg_power_w": 180,
            }
        )
        is True
    )


def test_strava_activity_model_importable():
    from backend.models import StravaActivity

    assert StravaActivity.__tablename__ == "strava_activities"


def test_strava_activity_model_has_required_columns():
    from backend.models import StravaActivity

    col_names = {c.name for c in StravaActivity.__table__.columns}
    required = {
        "id", "user_id", "strava_activity_id", "start_time", "activity_type",
        "name", "distance_km", "duration_seconds", "avg_hr", "max_hr",
        "elevation_m", "avg_power_w", "max_power_w", "device_name", "external_id",
        "is_stryd_synced", "raw_payload", "synced_at",
    }
    assert required.issubset(col_names)


def test_detect_stryd_origin_importable():
    from backend.services.strava import detect_stryd_origin

    assert callable(detect_stryd_origin)
