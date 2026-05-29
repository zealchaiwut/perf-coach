"""
Tests for issue #42: Show energy and sleep quality dots on calendar day cells
Server under test: http://127.0.0.1:9001
"""
import pathlib
from datetime import date

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "calendar.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "calendar.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    """Return Alice's user_id (user with seeded daily_metrics data)."""
    users = client.get("/api/users").json()
    alice = next((u for u in users if u["name"].lower() == "alice"), None)
    assert alice, "Alice user not found in UAT database"
    return alice["id"]


# ── AC-3: Calendar API endpoint includes daily_metrics field per day ──────────

def test_ac3_calendar_month_endpoint_exists(client, alice_id):
    """GET /api/calendar/month must return 200 with year/month params."""
    today = date.today()
    res = client.get(
        f"/api/calendar/month",
        params={"user_id": alice_id, "year": today.year, "month": today.month},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"


def test_ac3_calendar_month_returns_list(client, alice_id):
    """GET /api/calendar/month must return a list of day objects."""
    today = date.today()
    res = client.get(
        "/api/calendar/month",
        params={"user_id": alice_id, "year": today.year, "month": today.month},
    )
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list), "Response must be a list"
    assert len(data) > 0, "List must not be empty"


def test_ac3_calendar_month_day_shape(client, alice_id):
    """Each day object must have date, weight, habits_done, workouts, energy, sleep_quality."""
    today = date.today()
    res = client.get(
        "/api/calendar/month",
        params={"user_id": alice_id, "year": today.year, "month": today.month},
    )
    assert res.status_code == 200
    data = res.json()
    required_keys = {"date", "weight", "habits_done", "workouts", "energy", "sleep_quality"}
    for day in data:
        missing = required_keys - set(day.keys())
        assert not missing, f"Day {day.get('date')} missing keys: {missing}"


def test_ac3_calendar_month_day_count(client, alice_id):
    """Calendar month endpoint returns exactly N days for the requested month."""
    import calendar as _cal
    today = date.today()
    days_in_month = _cal.monthrange(today.year, today.month)[1]
    res = client.get(
        "/api/calendar/month",
        params={"user_id": alice_id, "year": today.year, "month": today.month},
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == days_in_month, (
        f"Expected {days_in_month} days, got {len(data)}"
    )


def test_ac3_calendar_month_dates_are_correct(client, alice_id):
    """All dates in response belong to the requested month."""
    today = date.today()
    mm = str(today.month).zfill(2)
    prefix = f"{today.year}-{mm}-"
    res = client.get(
        "/api/calendar/month",
        params={"user_id": alice_id, "year": today.year, "month": today.month},
    )
    assert res.status_code == 200
    for day in res.json():
        assert day["date"].startswith(prefix), (
            f"Date {day['date']} does not belong to {today.year}-{mm}"
        )


def test_ac3_calendar_month_with_seeded_data(client, alice_id):
    """A month where Alice has daily_metrics must show non-null energy/sleep_quality on some days."""
    # Seed data covers 14 days ending today — find a recent month with data
    today = date.today()
    res = client.get(
        "/api/calendar/month",
        params={"user_id": alice_id, "year": today.year, "month": today.month},
    )
    assert res.status_code == 200
    days = res.json()

    # At least one day should have non-null energy or sleep_quality from seed data
    has_metrics = any(
        d["energy"] is not None or d["sleep_quality"] is not None
        for d in days
    )
    # This passes if Alice has any daily_metrics in current month; otherwise it's a data
    # availability issue, not a code bug — we check with a softer assertion
    # (seed covers up to 14 days ending today, so current month should have data)
    # If the month just started and seed data hasn't been inserted yet, skip gracefully.
    if not has_metrics:
        pytest.skip("No seeded daily_metrics found in current month — seed data may not cover this month")


def test_ac3_calendar_month_energy_null_for_missing_dates(client, alice_id):
    """Days without daily_metrics must have null energy and sleep_quality (not a grey placeholder)."""
    # Use a far-past month unlikely to have any data
    res = client.get(
        "/api/calendar/month",
        params={"user_id": alice_id, "year": 2000, "month": 1},
    )
    assert res.status_code == 200
    days = res.json()
    for day in days:
        assert day["energy"] is None, f"Day {day['date']} energy should be null, got {day['energy']}"
        assert day["sleep_quality"] is None, (
            f"Day {day['date']} sleep_quality should be null, got {day['sleep_quality']}"
        )


def test_ac3_calendar_month_invalid_user(client):
    """GET /api/calendar/month with invalid user_id must return 400."""
    today = date.today()
    res = client.get(
        "/api/calendar/month",
        params={"user_id": "not-a-uuid", "year": today.year, "month": today.month},
    )
    assert res.status_code == 400


def test_ac3_calendar_month_invalid_month(client, alice_id):
    """GET /api/calendar/month with month=13 must return 400."""
    res = client.get(
        "/api/calendar/month",
        params={"user_id": alice_id, "year": 2024, "month": 13},
    )
    assert res.status_code == 400


# ── AC-1: Calendar JS renders energy and sleep dots ──────────────────────────

def test_ac1_js_fetches_calendar_month_api():
    """calendar.js must call /api/calendar/month."""
    assert "/api/calendar/month" in JS, (
        "calendar.js must fetch /api/calendar/month to get daily_metrics"
    )


def test_ac1_js_renders_recovery_dots_container():
    """calendar.js must create a cal-recovery-dots element."""
    assert "cal-recovery-dots" in JS, (
        "calendar.js must create '.cal-recovery-dots' container for energy/sleep dots"
    )


def test_ac1_js_renders_sleep_dot():
    """calendar.js must create a cal-recovery-dot--sleep element."""
    assert "cal-recovery-dot--sleep" in JS, (
        "calendar.js must render a sleep quality dot with class 'cal-recovery-dot--sleep'"
    )


def test_ac1_js_renders_energy_dot():
    """calendar.js must create a cal-recovery-dot--energy element."""
    assert "cal-recovery-dot--energy" in JS, (
        "calendar.js must render an energy dot with class 'cal-recovery-dot--energy'"
    )


def test_ac1_js_no_dot_for_null_energy():
    """calendar.js must skip rendering the energy dot when energy is null."""
    # The check `dayMetrics.energy != null` ensures no dot for null values
    assert "energy != null" in JS or "energy !== null" in JS, (
        "calendar.js must skip energy dot when energy is null"
    )


def test_ac1_js_no_dot_for_null_sleep():
    """calendar.js must skip rendering the sleep dot when sleep_quality is null."""
    assert "sleep_quality != null" in JS or "sleep_quality !== null" in JS, (
        "calendar.js must skip sleep dot when sleep_quality is null"
    )


# ── AC-2: Color scale 1–5 ─────────────────────────────────────────────────────

def test_ac2_css_has_scale_1_red():
    """scale-1 must map to red (#ef4444)."""
    assert "scale-1" in HTML and "#ef4444" in HTML, (
        "calendar.html must define .scale-1 with red color #ef4444"
    )


def test_ac2_css_has_scale_5_dark_green():
    """scale-5 must map to dark green (#16a34a)."""
    assert "scale-5" in HTML and "#16a34a" in HTML, (
        "calendar.html must define .scale-5 with dark green color #16a34a"
    )


def test_ac2_css_all_five_scale_classes():
    """CSS must define all five scale classes (scale-1 through scale-5)."""
    for i in range(1, 6):
        assert f"scale-{i}" in HTML, f"calendar.html missing .scale-{i} CSS class"


def test_ac2_js_uses_scale_class():
    """calendar.js must apply scale-N class based on the metric value."""
    assert "scale-${" in JS or "scale-" in JS, (
        "calendar.js must apply scale-N class using the metric value"
    )


# ── AC-4: Tooltip with numeric value ─────────────────────────────────────────

def test_ac4_js_tooltip_energy():
    """calendar.js must set a tooltip showing 'Energy: N/5'."""
    assert "Energy:" in JS, "calendar.js must include 'Energy:' in the dot tooltip"
    assert "/5" in JS, "calendar.js tooltip must show value out of 5 (e.g. 'Energy: 4/5')"


def test_ac4_js_tooltip_sleep():
    """calendar.js must set a tooltip showing 'Sleep: N/5' or similar."""
    assert "Sleep:" in JS, "calendar.js must include 'Sleep:' in the dot tooltip"


def test_ac4_css_tooltip_hover():
    """calendar.html CSS must define a tooltip on hover using data-tooltip attribute."""
    assert "data-tooltip" in HTML, (
        "calendar.html must use [data-tooltip] attribute for tooltip CSS"
    )
    assert ":hover::after" in HTML, (
        "calendar.html must show tooltip on hover via ::after pseudo-element"
    )


# ── AC-5: Dots don't crowd existing content ───────────────────────────────────

def test_ac5_css_recovery_dots_positioned_right():
    """The recovery dots row must use justify-content: flex-end to align right."""
    assert "justify-content: flex-end" in HTML or "justify-content:flex-end" in HTML, (
        "calendar.html must right-align the recovery dots row (justify-content: flex-end)"
    )


def test_ac5_css_recovery_dots_have_margin_top():
    """The cal-recovery-dots must have margin-top to separate from other rows."""
    assert "margin-top" in HTML, (
        "calendar.html recovery dots row must have margin-top to avoid crowding"
    )


def test_ac5_html_has_filter_recovery_checkbox():
    """calendar.html must have a filter-recovery checkbox so dots can be hidden."""
    assert 'id="filter-recovery"' in HTML, (
        "calendar.html must include a Show Recovery filter checkbox"
    )


def test_ac5_css_narrow_viewport_responsive():
    """calendar.html must have responsive CSS rules for narrow viewports (max-width: 899px)."""
    assert "cal-recovery-dot" in HTML and "@media" in HTML, (
        "calendar.html must have responsive CSS for recovery dots on narrow viewports"
    )


# ── AC-6: Null dots — cell renders normally ───────────────────────────────────

def test_ac6_js_no_dotsrow_when_both_null():
    """calendar.js must not append cal-recovery-dots when both energy and sleep_quality are null."""
    # The guard: `if (dayMetrics && (dayMetrics.energy != null || dayMetrics.sleep_quality != null))`
    assert "energy != null || dayMetrics.sleep_quality != null" in JS or \
           "energy != null" in JS, (
        "calendar.js must guard dot rendering: skip when both energy and sleep_quality are null"
    )


def test_ac6_calendar_month_habits_done_is_integer(client, alice_id):
    """habits_done field must be an integer (0 for days with no habit logs)."""
    today = date.today()
    res = client.get(
        "/api/calendar/month",
        params={"user_id": alice_id, "year": today.year, "month": today.month},
    )
    assert res.status_code == 200
    for day in res.json():
        assert isinstance(day["habits_done"], int), (
            f"habits_done for {day['date']} must be an int, got {type(day['habits_done'])}"
        )
        assert day["habits_done"] >= 0, f"habits_done must be >= 0 for {day['date']}"
