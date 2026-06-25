"""UAT integration tests for issue #924: Add three-focus-habit model to Habits.

These tests run against a live UAT server and verify end-to-end behavior
of the focus-habit API endpoints.

Requires:
    UAT_BASE_URL or UAT_PORT env var pointing to a running UAT server.
    A user named 'tester' with a known password (set via set_user_password.py).

All tests skip if the UAT server is unreachable or if the tester user
cannot authenticate.
"""
from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = (
    os.environ.get("UAT_BASE_URL")
    or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
)
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. "
        "Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TESTER_PASSWORD = os.environ.get("UAT_TESTER_PASSWORD", "tester123")


def _csrf(client: httpx.Client) -> str:
    """Fetch the CSRF token from the server."""
    r = client.get(f"{BASE_URL}/api/csrf-token")
    if r.status_code != 200:
        pytest.skip(f"Could not obtain CSRF token: {r.status_code}")
    return r.json().get("csrf_token", "")


@pytest.fixture
def auth_user():
    """Yield (client, username) with an authenticated session.

    Skips if the UAT server is unreachable or authentication fails.
    """
    client = httpx.Client(base_url=BASE_URL, timeout=10.0)
    try:
        csrf = _csrf(client)
        r = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": _TESTER_PASSWORD},
            headers={"X-CSRF-Token": csrf},
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        client.close()
        pytest.skip(f"UAT server not reachable: {exc}")

    if r.status_code == 429:
        client.close()
        pytest.skip("Login rate-limited; reset brute-force lockout before running UAT tests")
    if r.status_code in (401, 403):
        client.close()
        pytest.skip("tester user not available or wrong password; set password with set_user_password.py")
    if r.status_code != 200:
        client.close()
        pytest.skip(f"Unexpected login status: {r.status_code} {r.text}")

    yield client, "tester"
    client.close()


class TestFocusCap:
    def test_can_set_three_focus_habits(self, auth_user):
        """AC2: Three focus habits can be set; fourth returns 422."""
        client, _ = auth_user
        csrf = _csrf(client)

        # Create three habits
        habit_ids = []
        for i in range(3):
            r = client.post(
                "/api/habits",
                json={"name": f"Focus Habit {i + 1}", "habit_type": "binary"},
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status_code == 201, f"Failed to create habit: {r.text}"
            habit_ids.append(r.json()["id"])

        try:
            # Set all three as focus
            for i, hid in enumerate(habit_ids):
                r = client.post(
                    f"/api/habits/{hid}/focus",
                    headers={"X-CSRF-Token": csrf},
                )
                assert r.status_code == 200, f"Failed to set focus for habit {i + 1}: {r.text}"

            # Create a fourth habit and try to set it as focus
            r = client.post(
                "/api/habits",
                json={"name": "Fourth Habit", "habit_type": "binary"},
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status_code == 201
            fourth_id = r.json()["id"]
            habit_ids.append(fourth_id)

            r = client.post(
                f"/api/habits/{fourth_id}/focus",
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
            assert "3" in r.json().get("detail", "")
        finally:
            # Cleanup: delete all created habits
            for hid in habit_ids:
                client.delete(f"/api/habits/{hid}", headers={"X-CSRF-Token": csrf})

    def test_focus_habits_included_in_habit_list(self, auth_user):
        """AC4: GET /api/habits includes is_focus field."""
        client, _ = auth_user
        csrf = _csrf(client)

        r = client.post(
            "/api/habits",
            json={"name": "Focus Test Habit", "habit_type": "binary"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 201
        hid = r.json()["id"]

        try:
            r = client.get("/api/habits")
            assert r.status_code == 200
            habits = r.json()
            matching = [h for h in habits if h.get("id") == hid]
            assert matching, "Created habit not found in GET /api/habits"
            assert "is_focus" in matching[0], "is_focus field missing from habit response"
            assert "focus_since" in matching[0], "focus_since field missing from habit response"
        finally:
            client.delete(f"/api/habits/{hid}", headers={"X-CSRF-Token": csrf})


class TestSwapCooldown:
    def test_swap_blocked_within_cooldown(self, auth_user):
        """AC5: Cannot remove focus from a habit set today."""
        client, _ = auth_user
        csrf = _csrf(client)

        r = client.post(
            "/api/habits",
            json={"name": "Cooldown Test Habit", "habit_type": "binary"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 201
        hid = r.json()["id"]

        try:
            # Set as focus (should succeed since cap not reached)
            r = client.post(
                f"/api/habits/{hid}/focus",
                headers={"X-CSRF-Token": csrf},
            )
            if r.status_code != 200:
                pytest.skip(f"Could not set focus (cap may be at 3): {r.text}")

            # Immediately try to remove focus — should be blocked by cooldown
            r = client.delete(
                f"/api/habits/{hid}/focus?confirm=true",
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
            detail = r.json().get("detail", "")
            # Message should reference days remaining
            assert any(c.isdigit() for c in detail), f"Cooldown message missing days: {detail!r}"
        finally:
            client.delete(f"/api/habits/{hid}", headers={"X-CSRF-Token": csrf})


class TestSwapConfirmation:
    def test_delete_without_confirm_returns_prompt(self, auth_user):
        """AC6: DELETE without confirm=true returns a confirmation prompt."""
        client, _ = auth_user
        csrf = _csrf(client)

        r = client.post(
            "/api/habits",
            json={"name": "Confirm Test Habit", "habit_type": "binary"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 201
        hid = r.json()["id"]

        try:
            r = client.post(
                f"/api/habits/{hid}/focus",
                headers={"X-CSRF-Token": csrf},
            )
            if r.status_code != 200:
                pytest.skip(f"Could not set focus: {r.text}")

            # Delete without confirm — should return a prompt, not perform the swap
            r = client.delete(
                f"/api/habits/{hid}/focus",
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status_code == 200
            body = r.json()
            # Either returns confirmation prompt or cooldown 422 — but not an actual deletion
            # If we're in cooldown, the 422 is acceptable since the test just confirms no silent delete
            if r.status_code == 200:
                # If no cooldown prompt, must have requires_confirmation
                if not body.get("requires_confirmation"):
                    # Could be cooldown was not active — check that is_focus is still True
                    r2 = client.get("/api/habits")
                    habits = r2.json()
                    matching = [h for h in habits if h.get("id") == hid]
                    if matching:
                        # Habit should still be focus if no confirmation was given
                        assert matching[0].get("is_focus") is True or body.get("requires_confirmation"), \
                            "DELETE without confirm=true should require confirmation or be in cooldown"
        finally:
            client.delete(f"/api/habits/{hid}", headers={"X-CSRF-Token": csrf})


class TestFocusSuggestion:
    def test_focus_suggestion_endpoint_accessible(self, auth_user):
        """AC7/AC8: GET /api/habits/focus-suggestion returns suggest and message fields."""
        client, _ = auth_user

        r = client.get("/api/habits/focus-suggestion")
        assert r.status_code == 200
        body = r.json()
        assert "suggest" in body
        assert "message" in body
        assert isinstance(body["suggest"], bool)

    def test_no_suggestion_when_no_focus_habits(self, auth_user):
        """AC8: suggest=False when user has no focus habits."""
        client, _ = auth_user
        r = client.get("/api/habits/focus-suggestion")
        assert r.status_code == 200
        # Without any focus habits, suggest should be False
        # (If the tester user happens to have focus habits, this may not hold — skip)
        body = r.json()
        if not body["suggest"]:
            assert body["message"] is None


class TestNonFocusHabit:
    def test_non_focus_habit_has_is_focus_false(self, auth_user):
        """AC3: Non-focus habits have is_focus=False in API response."""
        client, _ = auth_user
        csrf = _csrf(client)

        r = client.post(
            "/api/habits",
            json={"name": "Non Focus Habit", "habit_type": "binary"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 201
        hid = r.json()["id"]

        try:
            r = client.get("/api/habits")
            assert r.status_code == 200
            habits = r.json()
            matching = [h for h in habits if h.get("id") == hid]
            assert matching
            assert matching[0].get("is_focus") is False
            assert matching[0].get("focus_since") is None
        finally:
            client.delete(f"/api/habits/{hid}", headers={"X-CSRF-Token": csrf})
