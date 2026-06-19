"""TDD tests for issue #601: Show both Strava and Stryd badges on merged workouts.

Each test class is anchored to one Acceptance Criterion item.
Integration tests hit a live server at http://127.0.0.1:9001.
"""
import uuid
from datetime import date
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.auth import generate_csrf_token, hash_password
from backend.models import User

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "dsbadge601-int-pw"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_REPO_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=15, follow_redirects=True) as c:
        yield c


def _make_authed_client(username: str, user_id: str) -> httpx.Client:
    temp = httpx.Client(base_url=BASE, timeout=15, follow_redirects=True)
    login = temp.post("/api/auth/login", json={"username": username, "password": _TEST_PASSWORD})
    assert login.status_code == 200, f"Login failed: {login.text}"
    session_val = temp.cookies.get("session", "")
    temp.close()
    assert session_val, "Login must set session cookie"
    csrf = generate_csrf_token()
    c = httpx.Client(
        base_url=BASE,
        timeout=15,
        follow_redirects=True,
        cookies={"session": session_val, "csrf-token": csrf},
        headers={"X-CSRF-Token": csrf},
    )
    c._user_id = user_id
    return c


@pytest.fixture(scope="module")
def authed_client():
    username = f"s601_{uuid.uuid4().hex[:8]}"
    temp = httpx.Client(base_url=BASE, timeout=15, follow_redirects=True)
    res = temp.post("/api/users", json={"name": username})
    assert res.status_code == 201, f"User create failed: {res.text}"
    user_id = res.json()["id"]
    temp.close()
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        assert u is not None
        u.password_hash = hash_password(_TEST_PASSWORD)
        db.commit()
    c = _make_authed_client(username, user_id)
    yield c
    c.delete(f"/api/users/{user_id}")
    c.close()


def _create_workout(client, source: str, name: str = "Test Run") -> dict:
    today = date.today().isoformat()
    payload = {
        "workout_date": today,
        "name": name,
        "workout_type": "run",
        "source": source,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Create workout failed: {res.text}"
    return res.json()


# ── AC1: _workout_list_dict exposes has_strava and has_stryd ──────────────────

class TestACWorkoutListDictFields:
    """AC1: _workout_list_dict exposes has_strava and has_stryd on every workout dict."""

    def test_merged_workout_has_strava_true(self, authed_client):
        """GET /api/workouts returns has_strava=True for source='strava,stryd'."""
        w = _create_workout(authed_client, "strava,stryd", "Merged Run")
        today = date.today().isoformat()
        res = authed_client.get(f"/api/workouts?from={today}&to={today}")
        assert res.status_code == 200, res.text
        workouts = res.json()
        match = next((x for x in workouts if x["id"] == w["id"]), None)
        assert match is not None, "Created workout not found in list"
        assert match.get("has_strava") is True, (
            f"has_strava must be True for source='strava,stryd', got {match}"
        )
        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_merged_workout_has_stryd_true(self, authed_client):
        """GET /api/workouts returns has_stryd=True for source='strava,stryd'."""
        w = _create_workout(authed_client, "strava,stryd", "Merged Run 2")
        today = date.today().isoformat()
        res = authed_client.get(f"/api/workouts?from={today}&to={today}")
        assert res.status_code == 200, res.text
        workouts = res.json()
        match = next((x for x in workouts if x["id"] == w["id"]), None)
        assert match is not None
        assert match.get("has_stryd") is True, (
            f"has_stryd must be True for source='strava,stryd', got {match}"
        )
        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_strava_only_workout_flags(self, authed_client):
        """GET /api/workouts returns has_strava=True, has_stryd=False for source='strava'."""
        w = _create_workout(authed_client, "strava", "Strava Run")
        today = date.today().isoformat()
        res = authed_client.get(f"/api/workouts?from={today}&to={today}")
        workouts = res.json()
        match = next((x for x in workouts if x["id"] == w["id"]), None)
        assert match is not None
        assert match.get("has_strava") is True, f"has_strava must be True for source='strava'"
        assert match.get("has_stryd") is False, f"has_stryd must be False for source='strava'"
        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_stryd_only_workout_flags(self, authed_client):
        """GET /api/workouts returns has_strava=False, has_stryd=True for source='stryd'."""
        w = _create_workout(authed_client, "stryd", "Stryd Run")
        today = date.today().isoformat()
        res = authed_client.get(f"/api/workouts?from={today}&to={today}")
        workouts = res.json()
        match = next((x for x in workouts if x["id"] == w["id"]), None)
        assert match is not None
        assert match.get("has_strava") is False, f"has_strava must be False for source='stryd'"
        assert match.get("has_stryd") is True, f"has_stryd must be True for source='stryd'"
        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_manual_workout_flags(self, authed_client):
        """GET /api/workouts returns has_strava=False, has_stryd=False for manual workout."""
        w = _create_workout(authed_client, "manual", "Manual Run")
        today = date.today().isoformat()
        res = authed_client.get(f"/api/workouts?from={today}&to={today}")
        workouts = res.json()
        match = next((x for x in workouts if x["id"] == w["id"]), None)
        assert match is not None
        assert match.get("has_strava") is False, f"has_strava must be False for manual"
        assert match.get("has_stryd") is False, f"has_stryd must be False for manual"
        authed_client.delete(f"/api/workouts/{w['id']}")


# ── AC2: training-log endpoint exposes has_strava / has_stryd ─────────────────

class TestACTrainingLogFields:
    """AC2: /api/training-log entries expose has_strava and has_stryd for list-row rendering."""

    def _get_entry(self, client, workout_id: str, today: str) -> dict | None:
        res = client.get(f"/api/training-log?from={today}&to={today}")
        assert res.status_code == 200, res.text
        for week in res.json().get("weeks", []):
            for entry in week.get("entries", []):
                if entry.get("id") == workout_id:
                    return entry
        return None

    def test_merged_workout_has_strava_in_log(self, authed_client):
        """GET /api/training-log entry has has_strava=True for source='strava,stryd'."""
        w = _create_workout(authed_client, "strava,stryd", "Merged TL Run")
        today = date.today().isoformat()
        entry = self._get_entry(authed_client, w["id"], today)
        assert entry is not None, "Workout entry not found in training-log"
        assert entry.get("has_strava") is True, (
            f"has_strava must be True for merged workout, got {entry}"
        )
        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_merged_workout_has_stryd_in_log(self, authed_client):
        """GET /api/training-log entry has has_stryd=True for source='strava,stryd'."""
        w = _create_workout(authed_client, "strava,stryd", "Merged TL Run 2")
        today = date.today().isoformat()
        entry = self._get_entry(authed_client, w["id"], today)
        assert entry is not None
        assert entry.get("has_stryd") is True, (
            f"has_stryd must be True for merged workout, got {entry}"
        )
        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_strava_only_in_log(self, authed_client):
        """GET /api/training-log: Strava-only entry has has_strava=True, has_stryd=False."""
        w = _create_workout(authed_client, "strava", "Strava TL Run")
        today = date.today().isoformat()
        entry = self._get_entry(authed_client, w["id"], today)
        assert entry is not None
        assert entry.get("has_strava") is True
        assert entry.get("has_stryd") is False
        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_stryd_only_in_log(self, authed_client):
        """GET /api/training-log: Stryd-only entry has has_strava=False, has_stryd=True."""
        w = _create_workout(authed_client, "stryd", "Stryd TL Run")
        today = date.today().isoformat()
        entry = self._get_entry(authed_client, w["id"], today)
        assert entry is not None
        assert entry.get("has_strava") is False
        assert entry.get("has_stryd") is True
        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_manual_in_log(self, authed_client):
        """GET /api/training-log: Manual entry has has_strava=False, has_stryd=False."""
        w = _create_workout(authed_client, "manual", "Manual TL Run")
        today = date.today().isoformat()
        entry = self._get_entry(authed_client, w["id"], today)
        assert entry is not None
        assert entry.get("has_strava") is False
        assert entry.get("has_stryd") is False
        authed_client.delete(f"/api/workouts/{w['id']}")


# ── AC3: isStravaWorkout uses substring match ─────────────────────────────────

class TestACIsStravaWorkoutSubstring:
    """AC3: isStravaWorkout() treats 'strava' as a substring of source."""

    def test_is_strava_workout_uses_includes(self, client):
        """training-log.js must use includes('strava') for substring match in isStravaWorkout."""
        js_path = Path(__file__).resolve().parents[1] / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert 'includes("strava")' in content or "includes('strava')" in content, (
            "isStravaWorkout() must use includes('strava') for substring match; "
            "found exact-match pattern instead"
        )

    def test_no_exact_strava_match_in_is_strava_fn(self, client):
        """isStravaWorkout() must NOT use exact source === 'strava' match."""
        js_path = Path(__file__).resolve().parents[1] / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        # Isolate the isStravaWorkout function body
        start = content.find("function isStravaWorkout(")
        assert start >= 0, "isStravaWorkout function not found"
        brace_depth = 0
        i = start
        fn_body = ""
        in_fn = False
        while i < len(content):
            ch = content[i]
            if ch == "{":
                brace_depth += 1
                in_fn = True
            elif ch == "}":
                brace_depth -= 1
                if in_fn and brace_depth == 0:
                    fn_body = content[start:i+1]
                    break
            i += 1
        assert 'source === "strava"' not in fn_body and "source === 'strava'" not in fn_body, (
            "isStravaWorkout() must not use exact match source === 'strava'"
        )


# ── AC4: Merged workout shows both badges in list row ────────────────────────

class TestACMergedWorkoutListBadges:
    """AC4: training-log.js renders both Strava and Stryd badges for merged workouts."""

    def test_build_entry_row_uses_has_strava(self, client):
        """buildEntryRow must use w.has_strava (not isStravaWorkout) for the list row badge."""
        js_path = Path(__file__).resolve().parents[1] / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        # Find buildEntryRow
        start = content.find("function buildEntryRow(")
        assert start >= 0
        # Extract fn body
        brace_depth = 0
        i = start
        fn_body = ""
        in_fn = False
        while i < len(content):
            ch = content[i]
            if ch == "{":
                brace_depth += 1
                in_fn = True
            elif ch == "}":
                brace_depth -= 1
                if in_fn and brace_depth == 0:
                    fn_body = content[start:i+1]
                    break
            i += 1
        assert "w.has_strava" in fn_body, (
            "buildEntryRow must use w.has_strava for Strava badge, not isStravaWorkout()"
        )

    def test_build_entry_row_uses_has_stryd(self, client):
        """buildEntryRow must use w.has_stryd (not w.is_stryd_synced) for the Stryd badge."""
        js_path = Path(__file__).resolve().parents[1] / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        start = content.find("function buildEntryRow(")
        assert start >= 0
        brace_depth = 0
        i = start
        fn_body = ""
        in_fn = False
        while i < len(content):
            ch = content[i]
            if ch == "{":
                brace_depth += 1
                in_fn = True
            elif ch == "}":
                brace_depth -= 1
                if in_fn and brace_depth == 0:
                    fn_body = content[start:i+1]
                    break
            i += 1
        assert "w.has_stryd" in fn_body, (
            "buildEntryRow must use w.has_stryd for Stryd badge, not w.is_stryd_synced"
        )

    def test_build_entry_row_does_not_use_is_stryd_synced(self, client):
        """buildEntryRow must NOT reference the old is_stryd_synced field."""
        js_path = Path(__file__).resolve().parents[1] / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        start = content.find("function buildEntryRow(")
        assert start >= 0
        brace_depth = 0
        i = start
        fn_body = ""
        in_fn = False
        while i < len(content):
            ch = content[i]
            if ch == "{":
                brace_depth += 1
                in_fn = True
            elif ch == "}":
                brace_depth -= 1
                if in_fn and brace_depth == 0:
                    fn_body = content[start:i+1]
                    break
            i += 1
        assert "is_stryd_synced" not in fn_body, (
            "buildEntryRow must not use is_stryd_synced — use has_stryd instead"
        )


# ── AC5: Run-view detail retains existing substring logic ─────────────────────

class TestACRunViewSubstringRetained:
    """AC5: renderRunView uses substring logic (indexOf) — not changed."""

    def test_render_run_view_uses_indexof_for_strava(self, client):
        """Run detail view must use source.indexOf('strava') (substring logic)."""
        js_path = Path(__file__).resolve().parents[1] / "frontend" / "js" / "lib" / "run-detail-view.js"
        content = js_path.read_text()
        assert 'indexOf("strava")' in content or "indexOf('strava')" in content, (
            "run-detail-view.js must use substring indexOf check for strava source"
        )

    def test_render_run_view_uses_indexof_for_stryd(self, client):
        """Run detail view must use source.indexOf('stryd') (substring logic)."""
        js_path = Path(__file__).resolve().parents[1] / "frontend" / "js" / "lib" / "run-detail-view.js"
        content = js_path.read_text()
        assert 'indexOf("stryd")' in content or "indexOf('stryd')" in content, (
            "run-detail-view.js must use substring indexOf check for stryd source"
        )


# ── AC6 & AC7: Single-source and manual badge exclusivity ─────────────────────

class TestACSingleSourceAndManual:
    """AC6 & AC7: Single-source and manual workouts show only the correct badge."""

    def test_strava_only_no_stryd_flag(self, authed_client):
        """Strava-only workout: has_strava=True, has_stryd=False in both list endpoints."""
        w = _create_workout(authed_client, "strava", "Strava Only Badge Test")
        today = date.today().isoformat()

        # /api/workouts list
        r1 = authed_client.get(f"/api/workouts?from={today}&to={today}")
        match = next((x for x in r1.json() if x["id"] == w["id"]), None)
        assert match is not None
        assert match["has_strava"] is True and match["has_stryd"] is False

        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_stryd_only_no_strava_flag(self, authed_client):
        """Stryd-only workout: has_strava=False, has_stryd=True in both list endpoints."""
        w = _create_workout(authed_client, "stryd", "Stryd Only Badge Test")
        today = date.today().isoformat()

        r1 = authed_client.get(f"/api/workouts?from={today}&to={today}")
        match = next((x for x in r1.json() if x["id"] == w["id"]), None)
        assert match is not None
        assert match["has_strava"] is False and match["has_stryd"] is True

        authed_client.delete(f"/api/workouts/{w['id']}")

    def test_manual_neither_badge(self, authed_client):
        """Manual workout: has_strava=False, has_stryd=False in list."""
        w = _create_workout(authed_client, "manual", "Manual Only Badge Test")
        today = date.today().isoformat()

        r1 = authed_client.get(f"/api/workouts?from={today}&to={today}")
        match = next((x for x in r1.json() if x["id"] == w["id"]), None)
        assert match is not None
        assert match["has_strava"] is False and match["has_stryd"] is False

        authed_client.delete(f"/api/workouts/{w['id']}")


# ── AC8: Metric values unchanged ─────────────────────────────────────────────

class TestACMetricValuesUnchanged:
    """AC8: No metric values change as a result of this work."""

    def test_distance_km_unchanged(self, authed_client):
        """distance_km returned by /api/workouts is unaffected by source badge changes."""
        today = date.today().isoformat()
        payload = {
            "workout_date": today,
            "name": "Metric Unchanged Test",
            "workout_type": "run",
            "source": "strava,stryd",
            "distance_km": 10.5,
            "duration_seconds": 3600,
        }
        res = authed_client.post("/api/workouts", json=payload)
        assert res.status_code == 201, res.text
        w_id = res.json()["id"]

        r = authed_client.get(f"/api/workouts?from={today}&to={today}")
        match = next((x for x in r.json() if x["id"] == w_id), None)
        assert match is not None
        assert abs((match.get("distance_km") or 0) - 10.5) < 0.001, (
            f"distance_km must be 10.5, got {match.get('distance_km')}"
        )
        assert match.get("duration_seconds") == 3600, (
            f"duration_seconds must be 3600, got {match.get('duration_seconds')}"
        )
        authed_client.delete(f"/api/workouts/{w_id}")
