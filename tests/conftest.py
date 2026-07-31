"""Shared pytest fixtures for the full test suite.

require_admin bypass (fix-loopholes Task 1): GET/POST/PATCH/DELETE
/api/users were gated behind require_admin after being found unauthenticated
(anyone could enumerate/create/rename/delete any user). ~90 existing test
files across the suite use unauthenticated POST /api/users purely as fixture
plumbing to create a throwaway test user — they were never testing that
endpoint's auth. Rather than touch every one of those files, bypass
require_admin for the whole suite by default here.

The real auth behavior (401/403 unauthenticated, 200 with a valid admin
cookie) is covered by its own tests that explicitly clear this override —
see tests/test_users_admin_auth__loophole1.py.
"""
from backend.auth import require_admin
from backend.main import app


def _admin_bypass():
    return None


app.dependency_overrides[require_admin] = _admin_bypass


# ── Automatic integration marking (issue #1606) ───────────────────────────────
#
# The suite had no way to separate tests that need live services from tests that
# do not. `pytest.mark.integration` existed on exactly 2 of 780 files and was
# unregistered. So a full run produced ~2,800 failures dominated by
# `httpx.ConnectError` (no server on :9001) and `no such table` (the SQLite
# fallback that #1606 found cannot build this schema at all — JSONB and UUID are
# Postgres-only, and create_all dies after 3 of 67 tables).
#
# Nobody could tell a real regression from that noise. Three features have been
# silently reverted by merges in this repo and every one stayed invisible for
# weeks because of it.
#
# Marking is DERIVED, not hand-applied. ~400 files already declare their own
# dependency by referencing UAT_BASE_URL or DATABASE_URL_UAT; reading that is
# more honest than 400 decorator edits, and it cannot drift out of date when
# someone adds a file. A test that starts needing a live service gets marked the
# moment it references one.
#
# CI runs `-m "not integration"`. Nothing here skips anything on its own — the
# marker only makes the split expressible.

import re as _re
from pathlib import Path as _Path

# Signals that a module needs something this process cannot provide itself.
_LIVE_SERVICE_MARKERS = (
    # --- live HTTP server on :9001 ---
    # Spelled several ways across the suite; all of them mean the same thing.
    # Measured: BASE_URL 1068x, BASE_URL_UAT 335x, the literal host 270x.
    "BASE_URL",            # covers UAT_BASE_URL / BASE_URL_UAT / BASE_URL_PRD too
    "127.0.0.1:9001",
    "localhost:9001",
    # --- live Postgres ---
    "DATABASE_URL_UAT",
    "DATABASE_URL_PRD",
    "_uat_engine",         # the shared live-Postgres engine helper
    # --- real Postgres via the app's own engine ---
    # The SQLite fallback root conftest.py advertises CANNOT build this schema:
    # models.py uses JSONB 50x plus UUID on effectively every table, so
    # create_all dies after 3 of 67 tables (#1606). Any module that opens a
    # session on backend.db.engine and writes therefore needs real Postgres,
    # even when it never names a DATABASE_URL.
    "from backend.db import",
    "Session(engine)",
    "backend.db.engine",
)

_LIVE_RE = _re.compile("|".join(_re.escape(m) for m in _LIVE_SERVICE_MARKERS))

_needs_live_service_cache: dict[str, bool] = {}


def _needs_live_service(path: str) -> bool:
    cached = _needs_live_service_cache.get(path)
    if cached is None:
        try:
            cached = bool(_LIVE_RE.search(_Path(path).read_text()))
        except OSError:
            cached = False
        _needs_live_service_cache[path] = cached
    return cached


def _excluding_integration(config) -> bool:
    """True when this run asked NOT to include integration tests."""
    expr = config.getoption("-m", default="") or ""
    return "not integration" in expr.replace("  ", " ")


def pytest_ignore_collect(collection_path, config):
    """Skip live-service modules BEFORE importing them.

    Marking alone is not enough. pytest_collection_modifyitems runs AFTER every
    module has been imported, so a module that raises at IMPORT time — because
    it reads DATABASE_URL_UAT at module scope, say — produces a collection error
    before there is an item to mark. It then breaks the very `--collect-only`
    step that is supposed to prove the suite is importable.

    CI caught this on its own first run: 17 collection errors there against 0
    locally, because a local .env supplies DATABASE_URL_UAT and a clean runner
    does not. The marker was correct and useless at the same time.

    So when a run excludes integration, those files are never imported at all.
    """
    if not _excluding_integration(config):
        return None
    path = str(collection_path)
    if path.endswith(".py") and _needs_live_service(path):
        return True
    return None


def pytest_collection_modifyitems(config, items):
    """Mark every test in a module that references a live service.

    Still needed even with the ignore hook above: a run that does NOT exclude
    integration (a full local run, or `-m integration`) imports these modules
    normally and needs them labelled.
    """
    import pytest

    for item in items:
        path = str(getattr(item, "fspath", "") or "")
        if path and _needs_live_service(path):
            item.add_marker(pytest.mark.integration)
