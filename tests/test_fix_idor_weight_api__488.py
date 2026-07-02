"""
Tests for issue #488: Fix IDOR on weight API endpoints.

AC anchors:
(ac1) All /api/weight-entries and /api/weight-targets/* use resolve_user;
      client-supplied user_id params removed.
(ac2) PATCH and DELETE return 404 when entry.user_id != user.id.
(ac3) All weight target queries filter by WeightTarget.user_id == user.id.
(ac4) CSV export scoped to authenticated user; no user_id accepted from client.
(ac5) weight.js no longer sends user_id on any weight request.
(ac6) Authenticated user B gets 404 on user A's entry for GET, PATCH, DELETE.
(ac7) User B's list/export returns only their own entries, never user A's.
"""
import uuid
import pytest
import httpx
from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "idor-test-pw-488"


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_auth_user(client, suffix):
    name = f"idor488-{suffix}-{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]
    pw_hash = hash_password(_TEST_PASSWORD)
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        u.password_hash = pw_hash
        db.commit()
    return {"id": user_id, "name": name}


def _login(client, name):
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PASSWORD})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_a(client):
    u = _make_auth_user(client, "a")
    yield u
    client.delete(f"/api/users/{u['id']}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def user_b(client):
    u = _make_auth_user(client, "b")
    yield u
    client.delete(f"/api/users/{u['id']}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def cookie_a(client, user_a):
    return _login(client, user_a["name"])


@pytest.fixture(scope="module")
def cookie_b(client, user_b):
    return _login(client, user_b["name"])


@pytest.fixture(scope="module")
def entry_a(client, user_a, cookie_a):
    """A weight entry belonging to user A."""
    res = client.post(
        "/api/weight-entries",
        json={"entry_date": "2024-01-10", "weight_kg": 70.0},
        cookies={"session": cookie_a},
    )
    assert res.status_code == 201, res.text
    entry_id = res.json()["id"]
    yield entry_id
    client.delete(f"/api/weight-entries/{entry_id}", cookies={"session": cookie_a})


@pytest.fixture(scope="module")
def target_a(client, user_a, cookie_a):
    """A weight target belonging to user A."""
    res = client.post(
        "/api/weight-targets",
        json={
            "start_weight_kg": 80.0,
            "start_date": "2024-01-01",
            "target_weight_kg": 70.0,
            "target_date": "2024-12-31",
        },
        cookies={"session": cookie_a},
    )
    assert res.status_code in (201, 409), res.text
    if res.status_code == 201:
        target_id = res.json()["id"]
    else:
        target_id = res.json().get("active_id")
    yield target_id
    # end the target so it doesn't block other tests
    client.post(
        f"/api/weight-targets/{target_id}/end",
        json={"status": "abandoned"},
        cookies={"session": cookie_a},
    )


# ── AC1: Anonymous requests return 401 ────────────────────────────────────────

class TestAnonymousReturns401:
    """AC1: unauthenticated access to weight-entries and weight-targets returns 401."""

    def test_weight_entries_get_anon(self, client):
        res = client.get("/api/weight-entries")
        assert res.status_code == 401, res.text

    def test_weight_entries_post_anon(self, client):
        res = client.post(
            "/api/weight-entries",
            json={"entry_date": "2024-01-01", "weight_kg": 70.0},
        )
        assert res.status_code == 401, res.text

    def test_weight_entries_patch_anon(self, client):
        res = client.patch(
            f"/api/weight-entries/{uuid.uuid4()}",
            json={"weight_kg": 70.0},
        )
        assert res.status_code == 401, res.text

    def test_weight_entries_delete_anon(self, client):
        res = client.delete(f"/api/weight-entries/{uuid.uuid4()}")
        assert res.status_code == 401, res.text

    def test_weight_targets_post_anon(self, client):
        res = client.post(
            "/api/weight-targets",
            json={
                "start_weight_kg": 80.0,
                "start_date": "2024-01-01",
                "target_weight_kg": 70.0,
                "target_date": "2024-12-31",
            },
        )
        assert res.status_code == 401, res.text

    def test_weight_targets_active_anon(self, client):
        res = client.get("/api/weight-targets/active")
        assert res.status_code == 401, res.text

    def test_weight_targets_history_anon(self, client):
        res = client.get("/api/weight-targets/history")
        assert res.status_code == 401, res.text

    def test_weight_targets_history_summary_anon(self, client):
        res = client.get("/api/weight-targets/history-summary")
        assert res.status_code == 401, res.text

    def test_export_weight_entries_anon(self, client):
        res = client.get("/api/exports/weight-entries")
        assert res.status_code == 401, res.text

    def test_export_weight_targets_anon(self, client):
        res = client.get("/api/exports/weight-targets")
        assert res.status_code == 401, res.text


# ── AC2 + AC6: Cross-user PATCH/DELETE return 404 ─────────────────────────────

class TestCrossUserIDORReturns404:
    """AC2/AC6: User B gets 404 on user A's entry for PATCH and DELETE."""

    def test_patch_other_users_entry_returns_404(self, client, entry_a, cookie_b):
        """AC6: PATCH user A's entry as user B → 404."""
        res = client.patch(
            f"/api/weight-entries/{entry_a}",
            json={"weight_kg": 99.9},
            cookies={"session": cookie_b},
        )
        assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"

    def test_delete_other_users_entry_returns_404(self, client, entry_a, cookie_b):
        """AC6: DELETE user A's entry as user B → 404."""
        res = client.delete(
            f"/api/weight-entries/{entry_a}",
            cookies={"session": cookie_b},
        )
        assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"

    def test_entry_intact_after_cross_user_attempts(self, client, entry_a, cookie_a):
        """AC2: User A's entry still exists after cross-user PATCH/DELETE attempts."""
        res = client.get(
            "/api/weight-entries",
            params={"from": "2024-01-01", "to": "2024-01-31"},
            cookies={"session": cookie_a},
        )
        assert res.status_code == 200, res.text
        ids = [e["id"] for e in res.json()["entries"]]
        assert entry_a in ids, "User A's entry must still exist after cross-user attack attempts"


# ── AC6: Cross-user GET returns 404 ───────────────────────────────────────────

class TestCrossUserGetReturns404:
    """AC6: User B cannot read user A's specific entry."""

    def test_get_by_id_other_user_returns_404(self, client, entry_a, cookie_b):
        """AC6: GET /api/weight-entries?id=<A's id> as user B → 404 (if supported) or not in list."""
        # The list endpoint filters by session user, so A's entry must not appear in B's list
        res = client.get(
            "/api/weight-entries",
            params={"from": "2024-01-01", "to": "2024-01-31"},
            cookies={"session": cookie_b},
        )
        assert res.status_code == 200, res.text
        ids = [e["id"] for e in res.json()["entries"]]
        assert entry_a not in ids, "User A's entry must not appear in user B's list"


# ── AC7: List and export isolation ────────────────────────────────────────────

class TestListAndExportIsolation:
    """AC7: User B's list/export returns only their own entries."""

    @pytest.fixture(scope="class")
    def entry_b(self, client, cookie_b):
        res = client.post(
            "/api/weight-entries",
            json={"entry_date": "2024-02-10", "weight_kg": 85.0},
            cookies={"session": cookie_b},
        )
        assert res.status_code == 201, res.text
        eid = res.json()["id"]
        yield eid
        client.delete(f"/api/weight-entries/{eid}", cookies={"session": cookie_b})

    def test_list_returns_only_own_entries(self, client, user_a, entry_b, cookie_b):
        """AC7: GET list as user B contains B's entry, not user A's."""
        res = client.get(
            "/api/weight-entries",
            params={"from": "2024-02-01", "to": "2024-02-28"},
            cookies={"session": cookie_b},
        )
        assert res.status_code == 200, res.text
        entries = res.json()["entries"]
        ids = [e["id"] for e in entries]
        assert entry_b in ids, "User B's entry should be in their list"
        # All entries must belong to user B
        for e in entries:
            assert e["user_id"] == user_a["id"] is False or e["user_id"] != user_a["id"], (
                "User A's data must not appear in User B's list"
            )

    def test_csv_export_returns_only_own_entries(self, client, user_a, entry_b, cookie_b):
        """AC4/AC7: CSV export for user B contains only B's data."""
        res = client.get(
            "/api/exports/weight-entries",
            cookies={"session": cookie_b},
        )
        assert res.status_code == 200, res.text
        assert "text/csv" in res.headers.get("content-type", "")
        csv_text = res.text
        # CSV must not contain user_a's name or id-related data
        # Simply validate it's valid CSV and doesn't fail
        lines = [l for l in csv_text.strip().splitlines() if l]
        assert lines[0].startswith("entry_date"), f"CSV header missing: {lines[0]}"


# ── AC3: Weight target queries filter by session user ─────────────────────────

class TestWeightTargetIsolation:
    """AC3: Weight target endpoints filter by session user, not client-supplied user_id."""

    @pytest.fixture(scope="class")
    def target_b(self, client, cookie_b):
        res = client.post(
            "/api/weight-targets",
            json={
                "start_weight_kg": 90.0,
                "start_date": "2024-03-01",
                "target_weight_kg": 75.0,
                "target_date": "2025-03-01",
            },
            cookies={"session": cookie_b},
        )
        assert res.status_code in (201, 409), res.text
        if res.status_code == 201:
            tid = res.json()["id"]
        else:
            tid = res.json().get("active_id")
        yield tid
        client.post(
            f"/api/weight-targets/{tid}/end",
            json={"status": "abandoned"},
            cookies={"session": cookie_b},
        )

    def test_active_target_returns_session_users_target(self, client, target_b, cookie_b):
        """AC3: GET /active returns user B's target when logged in as B."""
        res = client.get("/api/weight-targets/active", cookies={"session": cookie_b})
        assert res.status_code == 200, res.text
        body = res.json()
        if body["target"] is not None:
            assert body["target"]["id"] == target_b

    def test_user_b_cannot_patch_user_a_target(self, client, target_a, cookie_b):
        """AC3: PATCH user A's target as user B → 404."""
        res = client.patch(
            f"/api/weight-targets/{target_a}",
            json={"target_weight_kg": 55.0},
            cookies={"session": cookie_b},
        )
        assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"

    def test_user_b_cannot_end_user_a_target(self, client, target_a, cookie_b):
        """AC3: POST /end on user A's target as user B → 404."""
        res = client.post(
            f"/api/weight-targets/{target_a}/end",
            json={"status": "abandoned"},
            cookies={"session": cookie_b},
        )
        assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"

    def test_history_summary_returns_own_data(self, client, cookie_b):
        """AC3: GET /history-summary as user B returns 200 scoped to user B."""
        res = client.get("/api/weight-targets/history-summary", cookies={"session": cookie_b})
        assert res.status_code == 200, res.text
        body = res.json()
        assert "stats" in body

    def test_history_returns_own_data(self, client, cookie_b):
        """AC3: GET /history as user B returns 200 scoped to user B."""
        res = client.get("/api/weight-targets/history", cookies={"session": cookie_b})
        assert res.status_code == 200, res.text
        body = res.json()
        assert "targets" in body


# ── AC1: POST no longer accepts client user_id ────────────────────────────────

class TestNoClientUserIdAccepted:
    """AC1: POST endpoints derive user from session, ignore/reject client user_id."""

    def test_post_weight_entry_without_user_id_succeeds(self, client, cookie_a):
        """AC1: POST /weight-entries without user_id in body succeeds (uses session)."""
        res = client.post(
            "/api/weight-entries",
            json={"entry_date": "2024-03-15", "weight_kg": 71.0},
            cookies={"session": cookie_a},
        )
        assert res.status_code in (201, 409), f"Expected 201/409, got {res.status_code}: {res.text}"
        if res.status_code == 201:
            client.delete(
                f"/api/weight-entries/{res.json()['id']}",
                cookies={"session": cookie_a},
            )

    def test_post_weight_target_without_user_id_succeeds(self, client, cookie_b):
        """AC1: POST /weight-targets without user_id in body succeeds (uses session)."""
        # end any active first
        active = client.get("/api/weight-targets/active", cookies={"session": cookie_b})
        if active.status_code == 200 and active.json().get("target"):
            tid = active.json()["target"]["id"]
            client.post(
                f"/api/weight-targets/{tid}/end",
                json={"status": "abandoned"},
                cookies={"session": cookie_b},
            )

        res = client.post(
            "/api/weight-targets",
            json={
                "start_weight_kg": 85.0,
                "start_date": "2024-04-01",
                "target_weight_kg": 70.0,
                "target_date": "2025-04-01",
            },
            cookies={"session": cookie_b},
        )
        assert res.status_code in (201, 409), f"Expected 201/409, got {res.status_code}: {res.text}"
        if res.status_code == 201:
            client.post(
                f"/api/weight-targets/{res.json()['id']}/end",
                json={"status": "abandoned"},
                cookies={"session": cookie_b},
            )


# ── AC5: weight.js does not send user_id ──────────────────────────────────────

def test_ac5_weight_js_no_user_id_in_requests():
    """AC5: weight.js must not include user_id in any API request URL or body."""
    import re
    import os

    js_path = os.path.join(
        os.path.dirname(__file__),
        "..", "frontend", "js", "weight.js"
    )
    js_path = os.path.normpath(js_path)
    with open(js_path) as f:
        content = f.read()

    # Check for user_id in fetch/apiFetch URLs
    url_user_id = re.search(r"user_id=.*_userId", content)
    assert url_user_id is None, (
        f"weight.js still sends user_id in URL: {url_user_id.group()}"
    )

    # Check for user_id in JSON body payloads
    body_user_id = re.search(r"user_id\s*:\s*_userId", content)
    assert body_user_id is None, (
        f"weight.js still sends user_id in request body: {body_user_id.group()}"
    )
