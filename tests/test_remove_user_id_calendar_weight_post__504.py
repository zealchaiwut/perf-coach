"""
Tests for issue #504: Remove user_id from calendar.js weight-entries POST body.

AC anchors:
(ac1) calendar.js POST body to /api/weight-entries does not include a user_id field.
(ac2) The weight entry POST in calendar.js succeeds (2xx) without user_id.
(ac3) No other fields in the calendar.js weight-entries POST body are altered.
(ac4) The fix matches the pattern already applied in weight.js by #488
      (user identity derived server-side, not sent from client).
"""
import os
import re
import uuid
import pytest
import httpx
from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session

BASE = "http://127.0.0.1:9001"
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "calendar-weight-test-pw-504"

CALENDAR_JS = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "js", "calendar.js")
)
WEIGHT_JS = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "js", "weight.js")
)


# ── static source checks ──────────────────────────────────────────────────────

def _get_weight_entries_post_bodies(content: str) -> list[str]:
    """Extract the JSON.stringify(...) bodies from weight-entries POST calls."""
    bodies = []
    # Find all /api/weight-entries POST fetch blocks and capture the stringify arg
    for m in re.finditer(
        r"fetch\(['\"]\/api\/weight-entries['\"].*?JSON\.stringify\((\{[^}]+\})\)",
        content,
        re.DOTALL,
    ):
        bodies.append(m.group(1))
    return bodies


class TestCalendarJsStaticChecks:
    """Static source analysis of calendar.js."""

    def test_ac1_no_user_id_in_post_body(self):
        """AC1: calendar.js POST body to /api/weight-entries must not contain user_id."""
        with open(CALENDAR_JS) as f:
            content = f.read()

        # Find the POST to /api/weight-entries and check its body
        # Look for the stringify call that follows the POST to /api/weight-entries
        post_block = re.search(
            r"fetch\(['\"]\/api\/weight-entries['\"].*?body:\s*JSON\.stringify\((\{[^}]+\})\)",
            content,
            re.DOTALL,
        )
        assert post_block is not None, "Could not find the weight-entries POST fetch in calendar.js"
        body_str = post_block.group(1)
        assert "user_id" not in body_str, (
            f"calendar.js POST body still contains user_id: {body_str!r}"
        )

    def test_ac3_required_fields_present_in_post_body(self):
        """AC3: weight_kg and entry_date must still be present in the POST body."""
        with open(CALENDAR_JS) as f:
            content = f.read()

        post_block = re.search(
            r"fetch\(['\"]\/api\/weight-entries['\"].*?body:\s*JSON\.stringify\((\{[^}]+\})\)",
            content,
            re.DOTALL,
        )
        assert post_block is not None, "Could not find the weight-entries POST fetch in calendar.js"
        body_str = post_block.group(1)
        assert "weight_kg" in body_str, f"weight_kg missing from POST body: {body_str!r}"
        assert "entry_date" in body_str, f"entry_date missing from POST body: {body_str!r}"

    def test_ac4_matches_weight_js_pattern(self):
        """AC4: calendar.js POST body structure matches weight.js (no user_id in either)."""
        for path, label in [(CALENDAR_JS, "calendar.js"), (WEIGHT_JS, "weight.js")]:
            with open(path) as f:
                content = f.read()
            post_block = re.search(
                r"fetch\(['\"]\/api\/weight-entries['\"].*?body:\s*JSON\.stringify\((\{[^}]+\})\)",
                content,
                re.DOTALL,
            )
            if post_block is None:
                continue
            body_str = post_block.group(1)
            assert "user_id" not in body_str, (
                f"{label} POST body still contains user_id: {body_str!r}"
            )


# ── integration checks ────────────────────────────────────────────────────────

def _make_auth_user(client, suffix):
    name = f"cal504-{suffix}-{_RUN}"
    res = client.post("/api/users", json={"name": name})
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


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    u = _make_auth_user(client, "main")
    yield u
    client.delete(f"/api/users/{u['id']}")


@pytest.fixture(scope="module")
def auth_cookie(client, auth_user):
    return _login(client, auth_user["name"])


class TestCalendarWeightPostIntegration:
    """AC2: POST /api/weight-entries without user_id in body returns 2xx."""

    def test_ac2_post_without_user_id_succeeds(self, client, auth_cookie):
        """AC2: POST body with only weight_kg and entry_date succeeds (matches calendar.js after fix)."""
        res = client.post(
            "/api/weight-entries",
            json={"weight_kg": 72.5, "entry_date": "2024-05-01"},
            cookies={"session": auth_cookie},
        )
        assert res.status_code in (201, 409), (
            f"Expected 201 or 409, got {res.status_code}: {res.text}"
        )
        if res.status_code == 201:
            entry_id = res.json()["id"]
            client.delete(
                f"/api/weight-entries/{entry_id}",
                cookies={"session": auth_cookie},
            )

    def test_ac2_post_with_user_id_field_still_works(self, client, auth_cookie, auth_user):
        """Server silently ignores extra user_id (Pydantic without extra='forbid')."""
        res = client.post(
            "/api/weight-entries",
            json={
                "weight_kg": 73.0,
                "entry_date": "2024-05-02",
                "user_id": auth_user["id"],
            },
            cookies={"session": auth_cookie},
        )
        # Should still succeed — Pydantic ignores the extra field currently
        assert res.status_code in (201, 409), (
            f"Expected 201 or 409, got {res.status_code}: {res.text}"
        )
        if res.status_code == 201:
            entry_id = res.json()["id"]
            client.delete(
                f"/api/weight-entries/{entry_id}",
                cookies={"session": auth_cookie},
            )
