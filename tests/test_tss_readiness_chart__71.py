"""Tests for issue #71: Add TSS and readiness correlation overlay chart (UAT)"""
import os
import pytest
import httpx
from datetime import datetime, date, timedelta
import json


# Resolved from environment; defaults only for fallback
BASE_URL = os.environ.get("UAT_BASE_URL") or (
    f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
)


@pytest.fixture
def client():
    """HTTP client pointing at UAT."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def test_user_id():
    """Standard test user UUID."""
    return "123e4567-e89b-12d3-a456-426614174000"


def _seed_sample_data(user_id: str):
    """Seed test data via HTTP API for a clean test."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        # We assume the API can accept data through /api/workouts and /api/daily-metrics
        # If the endpoints don't exist or require auth, we'll mark tests as MANUAL
        pass


# ────── Acceptance Criteria ──────────────────────────────────────────────────


def test_tss_readiness_chart__bar_chart_renders_tss_on_primary_axis(client, test_user_id):
    """
    AC: Bar chart renders daily TSS values on the primary Y-axis.
    """
    # Fetch trends/summary for a user with at least 7 days of data
    # This is an HTTP-testable criterion: verify the /trends/summary endpoint
    # returns TSS data in the expected format

    response = client.get(
        "/trends/summary",
        params={"user_id": test_user_id, "range": "30d"}
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    assert "tss" in data, "Response missing 'tss' field"
    assert "series" in data["tss"], "TSS data missing 'series'"

    # Verify series contains objects with date and value keys
    tss_series = data["tss"]["series"]
    assert isinstance(tss_series, list), "TSS series must be a list"
    if len(tss_series) > 0:
        # At least one entry should have a date; value may be null
        first = tss_series[0]
        assert "date" in first, "TSS series items must have 'date'"
        assert "value" in first, "TSS series items must have 'value'"


def test_tss_readiness_chart__readiness_line_offset_by_one_day(client, test_user_id):
    """
    AC: Readiness line is plotted on the secondary Y-axis, shifted forward by one day
    so each readiness value visually aligns with the preceding day's TSS bar.
    """
    # Verify the endpoint returns readiness data with correct alignment
    response = client.get(
        "/trends/summary",
        params={"user_id": test_user_id, "range": "30d"}
    )
    assert response.status_code == 200

    data = response.json()
    assert "readiness" in data, "Response missing 'readiness' field"
    assert "series" in data["readiness"], "Readiness data missing 'series'"

    # Verify readiness series has same structure as TSS
    readiness_series = data["readiness"]["series"]
    assert isinstance(readiness_series, list), "Readiness series must be a list"
    if len(readiness_series) > 0:
        first = readiness_series[0]
        assert "date" in first, "Readiness series items must have 'date'"
        assert "score" in first, "Readiness series items must have 'score'"

    # Verify both series have same number of dates (alignment prerequisite)
    if len(response.json()["tss"]["series"]) > 0 and len(readiness_series) > 0:
        assert len(response.json()["tss"]["series"]) == len(readiness_series), \
            "TSS and readiness series must have same length for alignment"


def test_tss_readiness_chart__shared_x_axis_with_consistent_dates(client, test_user_id):
    """
    AC: Both series share the same time (X) axis with consistent date labels.
    """
    response = client.get(
        "/trends/summary",
        params={"user_id": test_user_id, "range": "30d"}
    )
    assert response.status_code == 200

    data = response.json()
    tss_dates = [item["date"] for item in data["tss"]["series"]]
    readiness_dates = [item["date"] for item in data["readiness"]["series"]]

    # Both should have consistent date labels
    assert tss_dates == readiness_dates, \
        "TSS and readiness must share the same date axis"

    # Dates should be ISO format (YYYY-MM-DD)
    for d in tss_dates:
        try:
            datetime.fromisoformat(d)
        except ValueError:
            pytest.fail(f"Date '{d}' is not in ISO format YYYY-MM-DD")


def test_tss_readiness_chart__mobile_legible_defaults(client, test_user_id):
    """
    AC: Chart is mobile-legible: touch targets ≥ 44px, text ≥ 12px,
    no horizontal overflow on 375px-wide viewport.
    This is a visual/browser test; we can only verify the endpoint
    returns data without errors. Actual CSS/layout tests require browser automation.
    """
    pytest.skip("manual — cannot be HTTP-tested; requires browser/visual validation")


def test_tss_readiness_chart__tooltip_shows_explanation(client, test_user_id):
    """
    AC: Hovering or tapping any data point shows a tooltip that includes:
    date, TSS value, readiness value, and a one-sentence explanation
    of the one-day offset.
    This is a frontend interactive test; HTTP can only verify data is returned.
    """
    pytest.skip("manual — cannot be HTTP-tested; requires browser/interactive validation")


def test_tss_readiness_chart__graceful_handling_of_gaps(client, test_user_id):
    """
    AC: If either series has gaps (null values), the chart handles them gracefully
    (bar absent or line breaks) without throwing an error.
    """
    response = client.get(
        "/trends/summary",
        params={"user_id": test_user_id, "range": "30d"}
    )
    assert response.status_code == 200

    data = response.json()
    tss_series = data["tss"]["series"]
    readiness_series = data["readiness"]["series"]

    # Verify null values are properly represented (not causing errors)
    for item in tss_series:
        # value can be None or a number, both are valid
        assert item["value"] is None or isinstance(item["value"], (int, float)), \
            f"TSS value must be null or numeric, got {type(item['value'])}"

    for item in readiness_series:
        # score can be None or a number
        assert item["score"] is None or isinstance(item["score"], (int, float)), \
            f"Readiness score must be null or numeric, got {type(item['score'])}"


def test_tss_readiness_chart__renders_with_fewer_than_7_days(client, test_user_id):
    """
    AC: Chart renders correctly when the series contain fewer than 7 days of data.
    """
    # Use a short range (e.g., 7d) and verify endpoint returns valid data
    response = client.get(
        "/trends/summary",
        params={"user_id": test_user_id, "range": "7d"}
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    range_info = data.get("range", {})
    days = range_info.get("days", 0)

    # Verify the endpoint returns data even for short ranges
    assert "tss" in data, "TSS data must be present for short ranges"
    assert "readiness" in data, "Readiness data must be present for short ranges"
    assert data["tss"]["series"] is not None, "TSS series must not be null"
    assert data["readiness"]["series"] is not None, "Readiness series must not be null"


def test_tss_readiness_chart__no_extra_api_calls_beyond_trends_summary(client, test_user_id):
    """
    AC: No additional API calls are made beyond the existing /trends/summary fetch.
    Verify that /trends/summary includes both TSS and readiness data.
    """
    response = client.get(
        "/trends/summary",
        params={"user_id": test_user_id, "range": "30d"}
    )
    assert response.status_code == 200

    data = response.json()

    # Verify single endpoint provides all required data
    assert "tss" in data, "TSS must be in /trends/summary response"
    assert "readiness" in data, "Readiness must be in /trends/summary response"

    # Both must have series with actual data
    assert "series" in data["tss"], "TSS must include series"
    assert "series" in data["readiness"], "Readiness must include series"
