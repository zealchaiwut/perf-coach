"""
Tests for issue #174: Document /api/health response schema change.

The fix adds a docstring to health() that enumerates the current response
fields and explicitly calls out the breaking changes from the prior schema:
"database" renamed to "db", "version" and "uptime_seconds" added.
"""
import inspect
import sys

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

sys.path.insert(0, ".")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def _health_source() -> str:
    import backend.main as m
    return inspect.getsource(m.health)


# ── AC-1: health() has a docstring ────────────────────────────────────────────

def test_health_has_docstring():
    """health() must have a non-empty docstring."""
    import backend.main as m
    assert m.health.__doc__ is not None and m.health.__doc__.strip(), (
        "health() must have a docstring documenting the response schema"
    )


# ── AC-2: Docstring enumerates all current response keys ─────────────────────

@pytest.mark.parametrize("field", ["status", "environment", "version", "db", "uptime_seconds"])
def test_docstring_mentions_current_field(field):
    """The health() docstring must mention each current response field."""
    source = _health_source()
    assert field in source, (
        f"health() docstring must mention the '{field}' response field"
    )


# ── AC-3: Docstring documents the breaking change (database → db) ─────────────

def test_docstring_mentions_old_key_database():
    """The docstring must mention the old 'database' key to document the rename."""
    source = _health_source()
    assert "database" in source, (
        "health() docstring must reference the old 'database' key to document "
        "the breaking rename to 'db'"
    )


def test_docstring_mentions_breaking_changes():
    """The docstring must explicitly describe the breaking changes."""
    source = _health_source()
    lower = source.lower()
    assert "breaking" in lower or "renamed" in lower or "added" in lower, (
        "health() docstring must use 'breaking', 'renamed', or 'added' language "
        "to describe schema changes"
    )


# ── AC-4: Actual endpoint uses new schema (db, not database) ─────────────────

def test_health_endpoint_uses_db_key(client):
    """GET /api/health must return 'db' key (not the old 'database' key)."""
    res = client.get("/api/health")
    body = res.json()
    assert "db" in body, f"'db' key missing from /api/health response: {body}"
    assert "database" not in body, (
        f"Old 'database' key must not appear in /api/health response: {body}"
    )


def test_health_endpoint_has_version_field(client):
    """GET /api/health must include 'version' field (added in #155/#156)."""
    res = client.get("/api/health")
    body = res.json()
    assert "version" in body, f"'version' field missing from /api/health: {body}"


def test_health_endpoint_has_uptime_seconds(client):
    """GET /api/health must include 'uptime_seconds' field (added in #155/#156)."""
    res = client.get("/api/health")
    body = res.json()
    assert "uptime_seconds" in body, (
        f"'uptime_seconds' field missing from /api/health: {body}"
    )


def test_health_endpoint_has_all_documented_fields(client):
    """GET /api/health must return all five fields documented in the docstring."""
    res = client.get("/api/health")
    body = res.json()
    for field in ("status", "environment", "version", "db", "uptime_seconds"):
        assert field in body, f"'{field}' missing from /api/health response: {body}"


# ── AC-5: Docstring references origin issues ──────────────────────────────────

def test_docstring_references_origin_issue():
    """The docstring should reference #155 or #156 where the change was introduced."""
    source = _health_source()
    assert "#155" in source or "#156" in source, (
        "health() docstring should reference #155 or #156 to trace the schema change origin"
    )
