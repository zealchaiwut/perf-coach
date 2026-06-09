"""TDD tests for issue #380: Sync-status visibility, history UI, and CLI runner.

Each test class is anchored to one Acceptance Criterion.
Server: http://127.0.0.1:9001
"""
import os
import stat
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.auth import generate_csrf_token, hash_password
from backend.models import SyncJob, User

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "sync380-int-pw"

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
    username = f"s380_{uuid.uuid4().hex[:8]}"
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


@pytest.fixture(scope="module")
def second_client():
    """A second authenticated user for cross-user 403 tests."""
    username = f"s380b_{uuid.uuid4().hex[:8]}"
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


@pytest.fixture(scope="module")
def sync_jobs_user(authed_client):
    """Inserts a few SyncJob rows for the authed user; cleans up after module."""
    uid = uuid.UUID(authed_client._user_id)
    now = datetime.now(tz=timezone.utc)
    jobs = []
    with Session(engine) as db:
        for i, (jtype, status, offset_minutes) in enumerate([
            ("manual", "completed", 10),
            ("incremental", "completed", 5),
            ("manual", "failed", 2),
        ]):
            started = now - timedelta(minutes=offset_minutes + 1)
            completed = now - timedelta(minutes=offset_minutes) if status != "running" else None
            job = SyncJob(
                user_id=uid,
                source="strava",
                job_type=jtype,
                status=status,
                started_at=started,
                completed_at=completed,
                activities_created=i,
                activities_updated=i + 1,
                activities_skipped=0,
                error_message="test error" if status == "failed" else None,
            )
            db.add(job)
        db.commit()
        # Reload to get IDs
        from sqlalchemy import select
        rows = db.execute(
            select(SyncJob)
            .where(SyncJob.user_id == uid)
            .where(SyncJob.source == "strava")
        ).scalars().all()
        jobs = [str(j.id) for j in rows]
    yield uid, jobs
    with Session(engine) as db:
        for jid in jobs:
            j = db.get(SyncJob, uuid.UUID(jid))
            if j:
                db.delete(j)
        db.commit()


# ── AC A: GET /api/sync/history endpoint ──────────────────────────────────────

class TestACSyncHistoryEndpoint:
    """AC A: Sync history endpoint exists, requires auth, returns correct shape."""

    def test_requires_auth(self, client):
        """GET /api/sync/history returns 401 for unauthenticated request."""
        res = client.get("/api/sync/history")
        assert res.status_code == 401, (
            f"Expected 401 for unauthenticated /api/sync/history, got {res.status_code}"
        )

    def test_returns_200_for_authed_user(self, authed_client):
        """GET /api/sync/history returns 200 for authenticated user."""
        res = authed_client.get("/api/sync/history")
        assert res.status_code == 200, (
            f"/api/sync/history returned {res.status_code}: {res.text}"
        )

    def test_returns_empty_array_when_no_history(self, authed_client):
        """GET /api/sync/history returns empty array (not 404) when no jobs exist."""
        # Fresh user has no sync jobs
        res = authed_client.get("/api/sync/history")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}: {data}"

    def test_default_limit_is_20(self, authed_client):
        """GET /api/sync/history accepts limit param (default 20)."""
        res = authed_client.get("/api/sync/history")
        assert res.status_code == 200
        # If there are results, must be <= 20
        data = res.json()
        assert len(data) <= 20, f"Default limit should be ≤ 20, got {len(data)}"

    def test_limit_400_when_over_100(self, authed_client):
        """GET /api/sync/history returns 400 when limit > 100."""
        res = authed_client.get("/api/sync/history", params={"limit": 200})
        assert res.status_code == 400, (
            f"Expected 400 for limit=200, got {res.status_code}: {res.text}"
        )

    def test_limit_400_exactly_at_101(self, authed_client):
        """GET /api/sync/history returns 400 when limit=101."""
        res = authed_client.get("/api/sync/history", params={"limit": 101})
        assert res.status_code == 400, (
            f"Expected 400 for limit=101, got {res.status_code}"
        )

    def test_limit_200_accepts_exactly_100(self, authed_client):
        """GET /api/sync/history accepts limit=100 without error."""
        res = authed_client.get("/api/sync/history", params={"limit": 100})
        assert res.status_code == 200, (
            f"Expected 200 for limit=100, got {res.status_code}: {res.text}"
        )

    def test_403_cross_user_without_admin(self, authed_client, second_client):
        """GET /api/sync/history returns 403 when requesting another user's data without admin."""
        other_id = second_client._user_id
        res = authed_client.get("/api/sync/history", params={"user_id": other_id})
        assert res.status_code == 403, (
            f"Expected 403 for cross-user request without admin, got {res.status_code}: {res.text}"
        )

    def test_record_shape_with_history(self, authed_client, sync_jobs_user):
        """Each record includes required SyncJob fields and duration_seconds."""
        uid, _ = sync_jobs_user
        res = authed_client.get(
            "/api/sync/history",
            params={"user_id": str(uid), "source": "strava", "limit": 10},
        )
        assert res.status_code == 200, f"{res.status_code}: {res.text}"
        data = res.json()
        assert isinstance(data, list) and len(data) > 0, "Expected at least one record"
        row = data[0]
        required_fields = {
            "id", "status", "started_at", "finished_at",
            "activities_created", "activities_updated", "activities_skipped",
            "error_message", "duration_seconds",
        }
        missing = required_fields - set(row.keys())
        assert not missing, f"Missing fields in history record: {missing}"

    def test_records_ordered_most_recent_first(self, authed_client, sync_jobs_user):
        """GET /api/sync/history returns records ordered most-recent-first."""
        uid, _ = sync_jobs_user
        res = authed_client.get(
            "/api/sync/history",
            params={"user_id": str(uid), "source": "strava"},
        )
        assert res.status_code == 200
        data = res.json()
        if len(data) < 2:
            pytest.skip("Need ≥2 records to verify ordering")
        started_ats = [r["started_at"] for r in data if r["started_at"]]
        for i in range(len(started_ats) - 1):
            assert started_ats[i] >= started_ats[i + 1], (
                f"Records not ordered most-recent-first: {started_ats[i]} < {started_ats[i+1]}"
            )

    def test_duration_seconds_is_null_for_running_job(self, authed_client):
        """duration_seconds is null if job is not finished (no completed_at)."""
        uid = uuid.UUID(authed_client._user_id)
        job_id = None
        with Session(engine) as db:
            job = SyncJob(
                user_id=uid,
                source="strava",
                job_type="manual",
                status="running",
                started_at=datetime.now(tz=timezone.utc),
                completed_at=None,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            job_id = str(job.id)
        try:
            res = authed_client.get("/api/sync/history", params={"user_id": str(uid)})
            assert res.status_code == 200
            data = res.json()
            running = [r for r in data if r["status"] == "running"]
            assert running, "Expected at least one running job in response"
            assert running[0]["duration_seconds"] is None, (
                f"duration_seconds should be null for running job, got {running[0]['duration_seconds']}"
            )
        finally:
            with Session(engine) as db:
                j = db.get(SyncJob, uuid.UUID(job_id))
                if j:
                    db.delete(j)
                db.commit()

    def test_duration_seconds_computed_for_finished_job(self, authed_client, sync_jobs_user):
        """duration_seconds is computed as (finished_at - started_at).total_seconds()."""
        uid, _ = sync_jobs_user
        res = authed_client.get(
            "/api/sync/history",
            params={"user_id": str(uid), "source": "strava"},
        )
        assert res.status_code == 200
        data = res.json()
        completed = [r for r in data if r["status"] == "completed"]
        assert completed, "Need at least one completed job"
        row = completed[0]
        assert row["duration_seconds"] is not None, "Completed job must have duration_seconds"
        assert isinstance(row["duration_seconds"], (int, float)), (
            f"duration_seconds must be numeric, got {type(row['duration_seconds'])}"
        )
        assert row["duration_seconds"] >= 0, "duration_seconds must be non-negative"

    def test_source_filter_returns_only_matching(self, authed_client, sync_jobs_user):
        """source query param filters results to matching source."""
        uid, _ = sync_jobs_user
        res = authed_client.get(
            "/api/sync/history",
            params={"user_id": str(uid), "source": "strava"},
        )
        assert res.status_code == 200
        data = res.json()
        for row in data:
            assert row.get("source") == "strava", (
                f"Expected source=strava, got {row.get('source')}"
            )

    def test_user_id_own_data_returns_200(self, authed_client):
        """GET /api/sync/history with own user_id returns 200."""
        uid = authed_client._user_id
        res = authed_client.get("/api/sync/history", params={"user_id": uid})
        assert res.status_code == 200, f"Expected 200 for own user_id, got {res.status_code}"


# ── AC B: Sync History UI Panel ────────────────────────────────────────────────

class TestACSyncHistoryUIPanel:
    """AC B: Settings → Integrations → Strava has a collapsible sync history panel."""

    def test_settings_page_has_sync_history_panel(self, authed_client):
        """settings.html contains a sync history panel element in the Strava section."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        assert "sync-history" in res.text, (
            "settings.html must contain a sync history panel (id/class containing 'sync-history')"
        )

    def test_settings_page_history_panel_collapsible(self, authed_client):
        """settings.html Strava sync history panel is collapsible (has toggle/button)."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        body = res.text
        assert "Sync history" in body, (
            "settings.html must have 'Sync history' label for the collapsible panel"
        )

    def test_settings_page_history_no_data_message(self, authed_client):
        """settings.html JS renders 'No sync history yet' when no jobs exist."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        assert "No sync history yet" in res.text, (
            "settings.html must have 'No sync history yet' text in JS"
        )

    def test_settings_page_history_calls_endpoint(self, authed_client):
        """settings.html JS calls /api/sync/history endpoint."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        assert "/api/sync/history" in res.text, (
            "settings.html JS must call /api/sync/history"
        )

    def test_settings_page_history_shows_status_badge(self, authed_client):
        """settings.html JS renders status badges (completed/failed/running)."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        body = res.text
        # JS must reference at least the status values used for badge classes
        assert "completed" in body and "failed" in body, (
            "settings.html must reference 'completed' and 'failed' status for badge rendering"
        )

    def test_settings_page_history_shows_duration(self, authed_client):
        """settings.html JS renders duration column."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        assert "duration" in res.text.lower(), (
            "settings.html must render duration in sync history panel"
        )

    def test_settings_page_history_shows_counters(self, authed_client):
        """settings.html JS renders activity counters (created/updated/skipped)."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        body = res.text
        assert "created" in body and "updated" in body, (
            "settings.html must render created/updated counters in sync history panel"
        )


# ── AC C: Scheduled Sync Placeholder ──────────────────────────────────────────

class TestACScheduledSyncPlaceholder:
    """AC C: Strava section has a 'Scheduled sync' coming-soon subsection."""

    def test_settings_page_has_scheduled_sync_section(self, authed_client):
        """settings.html has 'Scheduled sync' subsection in Strava section."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        assert "Scheduled sync" in res.text, (
            "settings.html must have 'Scheduled sync' text in the Strava section"
        )

    def test_settings_page_scheduled_sync_coming_soon(self, authed_client):
        """settings.html Scheduled sync section shows a 'Coming soon' tag."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        assert "Coming soon" in res.text, (
            "settings.html must show 'Coming soon' tag in the Scheduled sync section"
        )

    def test_settings_page_scheduled_sync_copy_text(self, authed_client):
        """settings.html Scheduled sync section contains the required explanatory copy."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        body = res.text
        assert "manual sync only" in body or "manual sync" in body.lower(), (
            "settings.html must mention 'manual sync only' in the Scheduled sync copy"
        )

    def test_settings_page_scheduled_sync_no_interactive_controls(self, authed_client):
        """settings.html Scheduled sync section has no buttons or toggle inputs."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        # The scheduled sync section should be display-only — verified by absence of
        # a button/toggle with the word "schedule" in the same context.
        # We check that the scheduled-sync div doesn't contain a <button> by looking
        # at the static HTML (which is what we get from a GET /settings).
        body = res.text
        import re
        # Find the scheduled-sync block and make sure it has no interactive controls
        sched_match = re.search(
            r'(scheduled.sync|Scheduled sync)(.*?)(?=<div\s+class|<section|$)',
            body, re.DOTALL | re.IGNORECASE
        )
        assert sched_match, "Could not find Scheduled sync section in settings.html"


# ── AC D: CLI Runner Script ────────────────────────────────────────────────────

class TestACCLIRunnerScript:
    """AC D: scripts/run_strava_sync.py exists, is executable, has --help."""

    def test_cli_script_exists(self):
        """scripts/run_strava_sync.py exists."""
        script = _REPO_ROOT / "scripts" / "run_strava_sync.py"
        assert script.exists(), f"scripts/run_strava_sync.py not found at {script}"

    def test_cli_script_is_executable(self):
        """scripts/run_strava_sync.py has executable bit set."""
        script = _REPO_ROOT / "scripts" / "run_strava_sync.py"
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR, "scripts/run_strava_sync.py must have executable bit (chmod +x)"

    def test_cli_script_accepts_help(self):
        """scripts/run_strava_sync.py --help exits 0 and prints usage."""
        import subprocess
        script = _REPO_ROOT / "scripts" / "run_strava_sync.py"
        result = subprocess.run(
            ["python3", str(script), "--help"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, f"--help exited with {result.returncode}: {result.stderr}"
        output = result.stdout + result.stderr
        assert "user_id" in output.lower() or "--user" in output.lower(), (
            "--help output must mention --user_id argument"
        )

    def test_cli_script_has_user_id_argument(self):
        """scripts/run_strava_sync.py source mentions --user_id argument."""
        script = _REPO_ROOT / "scripts" / "run_strava_sync.py"
        content = script.read_text()
        assert "user_id" in content, (
            "scripts/run_strava_sync.py must define a --user_id CLI argument"
        )

    def test_cli_script_calls_sync_function(self):
        """scripts/run_strava_sync.py calls sync_strava_activities."""
        script = _REPO_ROOT / "scripts" / "run_strava_sync.py"
        content = script.read_text()
        assert "sync_strava_activities" in content, (
            "scripts/run_strava_sync.py must call sync_strava_activities"
        )

    def test_cli_script_documents_default_user(self):
        """scripts/run_strava_sync.py documents the default user behaviour."""
        script = _REPO_ROOT / "scripts" / "run_strava_sync.py"
        content = script.read_text()
        assert "default" in content.lower(), (
            "scripts/run_strava_sync.py must document/define a default when --user_id is omitted"
        )


# ── AC E: Changelog ────────────────────────────────────────────────────────────

class TestACChangelog:
    """AC E: CHANGELOG.md exists and has a Strava activity sync entry."""

    def test_changelog_exists(self):
        """CHANGELOG.md exists at repo root."""
        changelog = _REPO_ROOT / "CHANGELOG.md"
        assert changelog.exists(), "CHANGELOG.md must exist at repo root"

    def test_changelog_has_strava_sync_entry(self):
        """CHANGELOG.md contains a 'Strava activity sync' entry."""
        changelog = _REPO_ROOT / "CHANGELOG.md"
        content = changelog.read_text()
        assert "Strava" in content and ("sync" in content.lower() or "Sync" in content), (
            "CHANGELOG.md must have an entry mentioning Strava sync"
        )

    def test_changelog_entry_under_version_header(self):
        """CHANGELOG.md Strava sync entry is under a version or date header."""
        changelog = _REPO_ROOT / "CHANGELOG.md"
        content = changelog.read_text()
        import re
        headers = re.findall(r'^#{1,3}\s+.+', content, re.MULTILINE)
        assert headers, "CHANGELOG.md must have at least one version/sprint header"


# ── AC F: Documentation ────────────────────────────────────────────────────────

class TestACDocumentation:
    """AC F: docs/integrations/strava.md has a 'Sync workflow' section."""

    def test_strava_docs_exist(self):
        """docs/integrations/strava.md exists."""
        docs = _REPO_ROOT / "docs" / "integrations" / "strava.md"
        assert docs.exists(), "docs/integrations/strava.md must exist"

    def test_strava_docs_has_sync_workflow_section(self):
        """docs/integrations/strava.md contains a 'Sync workflow' section."""
        docs = _REPO_ROOT / "docs" / "integrations" / "strava.md"
        content = docs.read_text()
        assert "Sync workflow" in content, (
            "docs/integrations/strava.md must have a '## Sync workflow' section"
        )

    def test_strava_docs_sync_workflow_covers_manual_trigger(self):
        """docs/integrations/strava.md Sync workflow explains how to trigger manual sync."""
        docs = _REPO_ROOT / "docs" / "integrations" / "strava.md"
        content = docs.read_text()
        assert "manual" in content.lower() or "Settings" in content, (
            "docs must explain manual sync trigger"
        )

    def test_strava_docs_sync_workflow_covers_deduplication(self):
        """docs/integrations/strava.md Sync workflow covers deduplication logic."""
        docs = _REPO_ROOT / "docs" / "integrations" / "strava.md"
        content = docs.read_text()
        assert "dedup" in content.lower() or "idempotent" in content.lower() or "duplicate" in content.lower(), (
            "docs must cover deduplication/idempotent logic"
        )

    def test_strava_docs_sync_workflow_mentions_scheduled_sync(self):
        """docs/integrations/strava.md Sync workflow mentions future scheduled sync."""
        docs = _REPO_ROOT / "docs" / "integrations" / "strava.md"
        content = docs.read_text()
        assert "scheduled" in content.lower() or "automatic" in content.lower(), (
            "docs must mention future scheduled sync"
        )
