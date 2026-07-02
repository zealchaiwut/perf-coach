"""Tests for issue #307: sync architecture docs (job model, phases, etc)."""
import os
import re
from pathlib import Path

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
