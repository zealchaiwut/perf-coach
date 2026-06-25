"""Tests for issue #307: sync architecture docs and cancel hook."""
import os
import re
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services import sync_jobs


# ── helpers ───────────────────────────────────────────────────────────────────

def _clear_registry():
    with sync_jobs._lock:
        sync_jobs._registry.clear()


REPO_ROOT = Path(__file__).parent.parent


# ── AC1: docs/sync.md covers all six topics ───────────────────────────────────

def test_sync_md_exists():
    assert (REPO_ROOT / "docs" / "sync.md").exists(), "docs/sync.md not found"


def test_sync_md_covers_job_model():
    text = (REPO_ROOT / "docs" / "sync.md").read_text()
    assert "one-job-per-user" in text.lower() or "_registry" in text, \
        "docs/sync.md missing one-job-per-user model section"


def test_sync_md_covers_phases():
    text = (REPO_ROOT / "docs" / "sync.md").read_text()
    for phase in ("pulling_strava", "pulling_stryd", "reconciling"):
        assert phase in text, f"docs/sync.md missing phase '{phase}'"


def test_sync_md_covers_409_guard():
    text = (REPO_ROOT / "docs" / "sync.md").read_text()
    assert "409" in text, "docs/sync.md missing 409 single-flight guard"


def test_sync_md_covers_restart_behaviour():
    text = (REPO_ROOT / "docs" / "sync.md").read_text()
    lower = text.lower()
    assert "restart" in lower, "docs/sync.md missing restart behaviour section"
    assert "idempotent" in lower or "on conflict" in lower or "upsert" in lower, \
        "docs/sync.md missing idempotent / re-sync-is-safe explanation"


def test_sync_md_covers_status_bar():
    text = (REPO_ROOT / "docs" / "sync.md").read_text()
    lower = text.lower()
    assert "status bar" in lower or "status-bar" in lower, \
        "docs/sync.md missing global status bar section"


def test_sync_md_covers_polling_cadence():
    text = (REPO_ROOT / "docs" / "sync.md").read_text()
    lower = text.lower()
    assert "poll" in lower, "docs/sync.md missing polling cadence section"


def test_sync_md_sections_not_stubs():
    """Every H2 section must have at least one non-empty paragraph."""
    text = (REPO_ROOT / "docs" / "sync.md").read_text()
    sections = re.split(r"\n## ", text)
    for section in sections[1:]:
        lines = [l.strip() for l in section.splitlines() if l.strip()]
        # First line is the heading; remaining must have content
        assert len(lines) > 1, f"Section appears to be a stub: {lines[0]}"


# ── AC2: is_cancel_requested helper exists and works ──────────────────────────

def test_is_cancel_requested_false_when_not_set():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")
    assert sync_jobs.is_cancel_requested(uid) is False
    _clear_registry()


def test_is_cancel_requested_true_after_flag_set():
    _clear_registry()
    uid = uuid.uuid4()
    job = sync_jobs.start(uid, "strava")
    with sync_jobs._lock:
        job["cancel_requested"] = True
    assert sync_jobs.is_cancel_requested(uid) is True
    _clear_registry()


def test_is_cancel_requested_false_for_unknown_user():
    assert sync_jobs.is_cancel_requested(uuid.uuid4()) is False


# ── AC3: worker exits cleanly with status=error, message='cancelled' ──────────

def test_strava_worker_cancel_at_page_loop():
    """cancel_requested set before first page → worker exits with error='cancelled'."""
    _clear_registry()
    uid = uuid.uuid4()
    job = sync_jobs.start(uid, "strava")
    with sync_jobs._lock:
        job["cancel_requested"] = True

    import backend.main as main_mod

    with patch.object(main_mod, "refresh_token_if_needed", return_value="tok"):
        main_mod._strava_sync_worker(str(uid))

    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "error", f"Expected error, got {snap['status']}"
    assert snap["error"] == "cancelled", f"Expected 'cancelled', got {snap['error']}"
    _clear_registry()


def test_strava_worker_cancel_during_activity_loop():
    """cancel_requested set after one page is fetched → cancels mid-batch."""
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")

    import backend.main as main_mod

    fake_batch = [
        {
            "id": "111",
            "start_date": "2024-01-01T08:00:00Z",
            "type": "Run",
            "name": "Morning Run",
            "distance": 5000,
            "moving_time": 1800,
            "average_heartrate": None,
            "max_heartrate": None,
            "total_elevation_gain": None,
            "average_watts": None,
            "max_watts": None,
            "device_name": None,
            "external_id": None,
        }
    ]

    call_count = {"n": 0}

    def fake_urlopen(req):
        # First call returns one activity; after that set cancel flag
        call_count["n"] += 1
        ctx = MagicMock()
        ctx.__enter__ = lambda s: s
        ctx.__exit__ = MagicMock(return_value=False)
        import json
        ctx.read = MagicMock(return_value=json.dumps(fake_batch).encode())
        return ctx

    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.execute = MagicMock()
    mock_session.commit = MagicMock()

    def set_cancel_on_activity(*args, **kwargs):
        with sync_jobs._lock:
            if uid in sync_jobs._registry:
                sync_jobs._registry[uid]["cancel_requested"] = True
        return MagicMock()

    with patch.object(main_mod, "refresh_token_if_needed", return_value="tok"), \
         patch.object(main_mod, "_urllib_request") as mock_req, \
         patch("backend.main.Session", return_value=mock_session):
        mock_req.Request = MagicMock(return_value=MagicMock())
        mock_req.urlopen = fake_urlopen
        # Trigger cancel flag at the per-activity check by patching is_cancel_requested
        # to return True after the first activity
        original_is_cancel = sync_jobs.is_cancel_requested
        toggle = {"fired": False}

        def patched_is_cancel(u):
            if u == uid:
                if toggle["fired"]:
                    return True
                toggle["fired"] = True
                return False
            return original_is_cancel(u)

        with patch.object(sync_jobs, "is_cancel_requested", side_effect=patched_is_cancel):
            main_mod._strava_sync_worker(str(uid))

    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "error"
    assert snap["error"] == "cancelled"
    _clear_registry()


# ── AC4: no stop/cancel HTTP routes added ─────────────────────────────────────

def test_no_cancel_or_stop_routes_in_main():
    text = (REPO_ROOT / "backend" / "main.py").read_text()
    # Find all @app.X("/api/...") route registrations
    routes = re.findall(r'@app\.\w+\(["\']([^"\']+)["\']', text)
    bad = [r for r in routes if "cancel" in r or "stop" in r]
    assert not bad, f"Unexpected cancel/stop routes found: {bad}"


# ── AC5: CLAUDE.md has pointer to docs/sync.md and names all three endpoints ──

def test_claude_md_references_sync_md():
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    assert "docs/sync.md" in text, "CLAUDE.md missing reference to docs/sync.md"


def test_claude_md_names_sync_status_endpoint():
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    assert "/api/sync/status" in text, "CLAUDE.md missing /api/sync/status"


def test_claude_md_names_strava_sync_endpoint():
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    assert "/api/strava/sync" in text, "CLAUDE.md missing /api/strava/sync"


def test_claude_md_names_stryd_sync_endpoint():
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    assert "/api/stryd/sync" in text, "CLAUDE.md missing /api/stryd/sync"
