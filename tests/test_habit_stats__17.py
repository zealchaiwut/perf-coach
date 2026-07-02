"""
Tests for issue #17: Habits – show current streak and 30-day completion rate per habit.
One test per Acceptance Criterion (AC-1 through AC-12).
Server under test: http://127.0.0.1:9001
"""
import datetime

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


@pytest.fixture(scope="module")
def bob_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    bob = next((u for u in res.json() if u["name"] == "Bob"), None)
    assert bob is not None, "Bob not found in /api/users"
    return bob["id"]


def _date(offset: int) -> str:
    return (TODAY - datetime.timedelta(days=offset)).isoformat()


def _create_habit(client, user_id, name):
    res = client.post("/api/habits", json={"user_id": user_id, "name": name})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _log(client, user_id, habit_id, date_str):
    res = client.post("/api/habits/logs", json={
        "habit_id": habit_id, "user_id": user_id, "logged_date": date_str
    })
    # 409 is OK (already logged)
    assert res.status_code in (201, 409), res.text
    if res.status_code == 201:
        return res.json()["id"]
    return None


def _delete_habit(client, habit_id):
    client.delete(f"/api/habits/{habit_id}")


def _get_stats(client, user_id, habit_id, days=30):
    return client.get(
        f"/api/habits/stats",
        params={"user_id": user_id, "habit_id": habit_id, "days": days},
    )


# ── AC-1 / AC-2: Stats endpoint returns correct shape ────────────────────────

def test_ac1_stats_endpoint_returns_correct_shape(client, alice_id):
    """GET /api/habits/stats returns streak, completion_rate, days_completed, days_total."""
    habit_id = _create_habit(client, alice_id, "_stats_shape_test")
    try:
        res = _get_stats(client, alice_id, habit_id)
        assert res.status_code == 200, res.text
        data = res.json()
        assert "streak" in data
        assert "completion_rate" in data
        assert "days_completed" in data
        assert "days_total" in data
    finally:
        _delete_habit(client, habit_id)


def test_ac2_no_logs_returns_zero_streak_and_zero_rate(client, alice_id):
    """Habit with no log entries returns streak=0, completion_rate=0, days_completed=0."""
    habit_id = _create_habit(client, alice_id, "_stats_no_logs")
    try:
        res = _get_stats(client, alice_id, habit_id)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["streak"] == 0
        assert data["completion_rate"] == 0.0
        assert data["days_completed"] == 0
    finally:
        _delete_habit(client, habit_id)


# ── AC-3: Streak includes today when today is logged ─────────────────────────

def test_ac3_streak_includes_today_when_logged(client, alice_id):
    """Streak counts today when it is logged."""
    habit_id = _create_habit(client, alice_id, "_stats_streak_today")
    try:
        _log(client, alice_id, habit_id, TODAY_STR)
        _log(client, alice_id, habit_id, _date(1))
        _log(client, alice_id, habit_id, _date(2))
        res = _get_stats(client, alice_id, habit_id)
        assert res.status_code == 200, res.text
        assert res.json()["streak"] == 3
    finally:
        _delete_habit(client, habit_id)


# ── AC-3 (pending): today not logged, yesterday logged → streak still active ─

def test_ac3_streak_active_when_today_pending_yesterday_logged(client, alice_id):
    """Streak is active (yesterday counts) when today is not yet logged."""
    habit_id = _create_habit(client, alice_id, "_stats_streak_pending")
    try:
        _log(client, alice_id, habit_id, _date(1))
        _log(client, alice_id, habit_id, _date(2))
        _log(client, alice_id, habit_id, _date(3))
        res = _get_stats(client, alice_id, habit_id)
        assert res.status_code == 200, res.text
        assert res.json()["streak"] == 3
    finally:
        _delete_habit(client, habit_id)


# ── AC-3 (zero): today and yesterday not logged → streak = 0 ─────────────────

def test_ac3_streak_zero_when_neither_today_nor_yesterday_logged(client, alice_id):
    """Streak is 0 when neither today nor yesterday has a log entry."""
    habit_id = _create_habit(client, alice_id, "_stats_streak_zero")
    try:
        _log(client, alice_id, habit_id, _date(3))
        _log(client, alice_id, habit_id, _date(4))
        res = _get_stats(client, alice_id, habit_id)
        assert res.status_code == 200, res.text
        assert res.json()["streak"] == 0
    finally:
        _delete_habit(client, habit_id)


# ── AC-4: Streak milestone thresholds ────────────────────────────────────────

def test_ac4_streak_counts_consecutive_days_correctly(client, alice_id):
    """Streak value reflects exact count of consecutive logged days."""
    habit_id = _create_habit(client, alice_id, "_stats_streak_count")
    try:
        for i in range(5):
            _log(client, alice_id, habit_id, _date(i))
        res = _get_stats(client, alice_id, habit_id)
        assert res.status_code == 200, res.text
        assert res.json()["streak"] == 5
    finally:
        _delete_habit(client, habit_id)


# ── AC-5: Streak of 0 (displayed as "—" by frontend, but backend returns 0) ──

def test_ac5_zero_streak_habit_with_no_logs(client, alice_id):
    """Backend returns streak=0 for a habit that has never been logged."""
    habit_id = _create_habit(client, alice_id, "_stats_zero_streak_display")
    try:
        res = _get_stats(client, alice_id, habit_id)
        assert res.status_code == 200, res.text
        assert res.json()["streak"] == 0
    finally:
        _delete_habit(client, habit_id)


# ── AC-6: 30-day completion rate ─────────────────────────────────────────────

def test_ac6_thirty_day_completion_rate(client, alice_id):
    """30-day rate = days_completed / 30, today inclusive."""
    habit_id = _create_habit(client, alice_id, "_stats_30day_rate")
    try:
        # Log 15 of last 30 days
        for i in range(15):
            _log(client, alice_id, habit_id, _date(i * 2))
        res = _get_stats(client, alice_id, habit_id, days=30)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["days_total"] == 30
        assert data["days_completed"] == 15
        assert abs(data["completion_rate"] - 0.5) < 0.01
    finally:
        _delete_habit(client, habit_id)


# ── AC-7: Badge colour thresholds (backend returns correct rate) ──────────────

def test_ac7_rate_above_80_percent(client, alice_id):
    """Rate >= 80% returns completion_rate >= 0.8."""
    habit_id = _create_habit(client, alice_id, "_stats_rate_green")
    try:
        for i in range(25):
            _log(client, alice_id, habit_id, _date(i))
        res = _get_stats(client, alice_id, habit_id, days=30)
        assert res.status_code == 200, res.text
        assert res.json()["completion_rate"] >= 0.8
    finally:
        _delete_habit(client, habit_id)


def test_ac7_rate_between_50_and_79_percent(client, alice_id):
    """Rate 50-79% returns 0.5 <= completion_rate < 0.8."""
    habit_id = _create_habit(client, alice_id, "_stats_rate_yellow")
    try:
        for i in range(18):
            _log(client, alice_id, habit_id, _date(i))
        res = _get_stats(client, alice_id, habit_id, days=30)
        assert res.status_code == 200, res.text
        rate = res.json()["completion_rate"]
        assert 0.5 <= rate < 0.8
    finally:
        _delete_habit(client, habit_id)


# ── AC-8: Stats endpoint accepts days param and returns correct days_total ─────

def test_ac8_stats_endpoint_accepts_days_param(client, alice_id):
    """GET /api/habits/stats?days=30 returns days_total=30."""
    habit_id = _create_habit(client, alice_id, "_stats_days_param")
    try:
        res = _get_stats(client, alice_id, habit_id, days=30)
        assert res.status_code == 200, res.text
        assert res.json()["days_total"] == 30
    finally:
        _delete_habit(client, habit_id)


# ── AC-9: Invalid UUIDs return 400 ───────────────────────────────────────────

def test_ac9_invalid_user_id_returns_400(client, alice_id):
    """Invalid user_id UUID returns HTTP 400."""
    res = _get_stats(client, "not-a-uuid", "not-a-uuid")
    assert res.status_code == 400


def test_ac9_invalid_habit_id_returns_400(client, alice_id):
    """Invalid habit_id UUID (valid user) returns HTTP 400."""
    res = _get_stats(client, alice_id, "not-a-uuid")
    assert res.status_code == 400


# ── AC-10 / AC-11: Stats refresh after toggle (state tested via API) ──────────

def test_ac10_stats_update_after_logging_today(client, alice_id):
    """Stats change after logging today: streak and days_completed increase."""
    habit_id = _create_habit(client, alice_id, "_stats_toggle_refresh")
    try:
        # Before logging today
        res_before = _get_stats(client, alice_id, habit_id)
        assert res_before.status_code == 200
        before = res_before.json()

        _log(client, alice_id, habit_id, TODAY_STR)

        res_after = _get_stats(client, alice_id, habit_id)
        assert res_after.status_code == 200
        after = res_after.json()

        assert after["days_completed"] > before["days_completed"]
        assert after["streak"] >= 1
    finally:
        _delete_habit(client, habit_id)


# ── AC-12: Stats refresh when user switches (endpoint is user-scoped) ─────────

def test_ac12_stats_are_user_scoped(client, alice_id, bob_id):
    """Same habit_id but different user returns independent stats."""
    # Create habit under alice
    habit_id = _create_habit(client, alice_id, "_stats_user_scope")
    try:
        # Bob has no logs for this habit
        _log(client, alice_id, habit_id, TODAY_STR)

        alice_res = _get_stats(client, alice_id, habit_id)
        bob_res = _get_stats(client, bob_id, habit_id)

        assert alice_res.status_code == 200
        assert bob_res.status_code == 200

        assert alice_res.json()["streak"] >= 1
        assert bob_res.json()["streak"] == 0
    finally:
        _delete_habit(client, habit_id)
