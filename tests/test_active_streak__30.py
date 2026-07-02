"""
Tests for issue #30: Cross-tracker active-day streak — backend endpoint + display.
One test per Acceptance Criterion.
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


def _days_ago(n: int) -> str:
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def _post_weight(client, user_id, date_str, kg=70.0):
    res = client.post(
        "/api/weight-entries",
        json={"user_id": user_id, "weight_kg": kg, "entry_date": date_str},
    )
    assert res.status_code in (201, 409), res.text
    if res.status_code == 201:
        return res.json()["id"]
    # On 409, fetch the entry id
    entries = client.get(
        "/api/weight-entries",
        params={"user_id": user_id, "from": date_str, "to": date_str},
    ).json()["entries"]
    for e in entries:
        if e["entry_date"] == date_str:
            return e["id"]
    return None


def _delete_weight(client, entry_id):
    if entry_id:
        client.delete(f"/api/weight-entries/{entry_id}")


def _create_habit(client, user_id, name):
    res = client.post("/api/habits", json={"user_id": user_id, "name": name})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _log_habit(client, user_id, habit_id, date_str):
    res = client.post(
        "/api/habits/logs",
        json={"habit_id": habit_id, "user_id": user_id, "logged_date": date_str},
    )
    assert res.status_code in (201, 409), res.text
    if res.status_code == 201:
        return res.json()["id"]
    return None


def _delete_habit(client, habit_id):
    client.delete(f"/api/habits/{habit_id}")


def _post_workout(client, user_id, date_str):
    res = client.post(
        "/api/workouts",
        json={
            "user_id": user_id,
            "name": "_streak_test",
            "workout_date": date_str,
            "workout_type": "strength",
        },
    )
    assert res.status_code in (201,), res.text
    return res.json()["id"]


def _delete_workout(client, workout_id):
    if workout_id:
        client.delete(f"/api/workouts/{workout_id}")


def _get_streak(client, user_id):
    return client.get("/api/stats/active-streak", params={"user_id": user_id})


# ── AC: Response shape ────────────────────────────────────────────────────────

def test_response_shape(client, alice_id):
    """Endpoint returns current_streak, longest_streak, and last_active_date."""
    res = _get_streak(client, alice_id)
    assert res.status_code == 200, res.text
    data = res.json()
    assert "current_streak" in data
    assert "longest_streak" in data
    assert "last_active_date" in data


# ── AC: User with no entries returns zeros and null ───────────────────────────

def test_new_user_returns_zeros(client):
    """A brand-new user with no entries returns current_streak=0, longest_streak=0, last_active_date=null."""
    # Create a fresh user
    res = client.post("/api/users", json={"name": "_streak_brand_new_user"}, cookies=_admin_cookies())
    assert res.status_code == 201, res.text
    uid = res.json()["id"]
    try:
        streak_res = _get_streak(client, uid)
        assert streak_res.status_code == 200, streak_res.text
        data = streak_res.json()
        assert data["current_streak"] == 0
        assert data["longest_streak"] == 0
        assert data["last_active_date"] is None
    finally:
        client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


# ── AC: Current streak counts from today when today is active ─────────────────

def test_current_streak_includes_today(client, alice_id):
    """current_streak counts today when there is an entry today."""
    habit_id = _create_habit(client, alice_id, "_streak_today_active")
    log_ids = []
    try:
        for i in range(3):
            lid = _log_habit(client, alice_id, habit_id, _days_ago(i))
            log_ids.append(lid)
        res = _get_streak(client, alice_id)
        assert res.status_code == 200
        assert res.json()["current_streak"] >= 3
    finally:
        _delete_habit(client, habit_id)


# ── AC: Forgiving logic — streak starts from yesterday when today has no entry ─

def test_forgiving_streak_starts_yesterday(client):
    """If today has no entry but yesterday does, current_streak starts from yesterday."""
    res = client.post("/api/users", json={"name": "_streak_forgiving_user"}, cookies=_admin_cookies())
    assert res.status_code == 201
    uid = res.json()["id"]
    habit_id = _create_habit(client, uid, "_streak_forgiving")
    try:
        # Log only yesterday and the day before — not today
        _log_habit(client, uid, habit_id, _days_ago(1))
        _log_habit(client, uid, habit_id, _days_ago(2))
        _log_habit(client, uid, habit_id, _days_ago(3))
        res = _get_streak(client, uid)
        assert res.status_code == 200
        data = res.json()
        assert data["current_streak"] == 3
    finally:
        _delete_habit(client, habit_id)
        client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


# ── AC: Streak breaks when there is a gap ─────────────────────────────────────

def test_streak_breaks_on_gap(client):
    """If yesterday and today both have no entry, current_streak is 0."""
    res = client.post("/api/users", json={"name": "_streak_gap_user"}, cookies=_admin_cookies())
    assert res.status_code == 201
    uid = res.json()["id"]
    habit_id = _create_habit(client, uid, "_streak_gap")
    try:
        # Log only 3 and 4 days ago — gap yesterday and today
        _log_habit(client, uid, habit_id, _days_ago(3))
        _log_habit(client, uid, habit_id, _days_ago(4))
        res = _get_streak(client, uid)
        assert res.status_code == 200
        assert res.json()["current_streak"] == 0
    finally:
        _delete_habit(client, habit_id)
        client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


# ── AC: Cross-tracker — weight entry counts as active day ─────────────────────

def test_weight_entry_counts_as_active(client):
    """A weight entry alone on a day makes that day active."""
    res = client.post("/api/users", json={"name": "_streak_weight_only"}, cookies=_admin_cookies())
    assert res.status_code == 201
    uid = res.json()["id"]
    entry_ids = []
    try:
        for i in range(2):
            eid = _post_weight(client, uid, _days_ago(i))
            entry_ids.append(eid)
        streak_res = _get_streak(client, uid)
        assert streak_res.status_code == 200
        assert streak_res.json()["current_streak"] >= 2
    finally:
        for eid in entry_ids:
            _delete_weight(client, eid)
        client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


# ── AC: Cross-tracker — workout entry counts as active day ────────────────────

def test_workout_entry_counts_as_active(client):
    """A workout entry alone on a day makes that day active."""
    res = client.post("/api/users", json={"name": "_streak_workout_only"}, cookies=_admin_cookies())
    assert res.status_code == 201
    uid = res.json()["id"]
    workout_ids = []
    try:
        for i in range(2):
            wid = _post_workout(client, uid, _days_ago(i))
            workout_ids.append(wid)
        streak_res = _get_streak(client, uid)
        assert streak_res.status_code == 200
        assert streak_res.json()["current_streak"] >= 2
    finally:
        for wid in workout_ids:
            _delete_workout(client, wid)
        client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


# ── AC: longest_streak reflects the longest ever run ─────────────────────────

def test_longest_streak_across_all_time(client):
    """longest_streak reflects the longest consecutive run, even if current streak is shorter."""
    res = client.post("/api/users", json={"name": "_streak_longest_user"}, cookies=_admin_cookies())
    assert res.status_code == 201
    uid = res.json()["id"]
    habit_id = _create_habit(client, uid, "_streak_longest")
    try:
        # Old 5-day run: days 10..14 ago
        for i in range(10, 15):
            _log_habit(client, uid, habit_id, _days_ago(i))
        # Current 2-day run: yesterday and day before
        _log_habit(client, uid, habit_id, _days_ago(1))
        _log_habit(client, uid, habit_id, _days_ago(2))

        res = _get_streak(client, uid)
        assert res.status_code == 200
        data = res.json()
        assert data["longest_streak"] == 5
        assert data["current_streak"] == 2
    finally:
        _delete_habit(client, habit_id)
        client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


# ── AC: last_active_date is correct ──────────────────────────────────────────

def test_last_active_date(client):
    """last_active_date is the most recent date across all trackers."""
    res = client.post("/api/users", json={"name": "_streak_last_active_user"}, cookies=_admin_cookies())
    assert res.status_code == 201
    uid = res.json()["id"]
    habit_id = _create_habit(client, uid, "_streak_last_active")
    try:
        _log_habit(client, uid, habit_id, _days_ago(3))
        _log_habit(client, uid, habit_id, _days_ago(5))
        res = _get_streak(client, uid)
        assert res.status_code == 200
        assert res.json()["last_active_date"] == _days_ago(3)
    finally:
        _delete_habit(client, habit_id)
        client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


# ── AC: Invalid user_id returns 400 ──────────────────────────────────────────

def test_invalid_user_id_returns_400(client):
    """An invalid (non-UUID) user_id returns HTTP 400."""
    res = _get_streak(client, "not-a-uuid")
    assert res.status_code == 400
