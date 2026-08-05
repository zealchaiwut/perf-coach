"""Structure→target parsing lives in one shared helper — issue #1601 AC6.

``_extract_target`` was duplicated as a module-private function in both
``backend/worker_app.py`` (Hermes read API) and ``backend/services/daily_brief.py``
(coaching brief builder).  Because it was never exported, a schema change
validated against one caller silently broke the other — the exact failure mode
the issue called out.

The fix: promote it to ``extract_session_target`` in ``daily_brief.py`` (the
canonical home for plan-session helpers) and have ``worker_app.py`` import it
from there instead of owning a copy.  A schema change now only has to happen
in one place.
"""
from __future__ import annotations

import inspect

import pytest


# ── Both callers use the same object ─────────────────────────────────────────

def test_worker_imports_from_daily_brief_not_its_own_copy():
    """The implementation lives in daily_brief.  worker_app must import it —
    any local definition re-introduces the duplication."""
    import backend.worker_app as worker

    src = inspect.getsource(worker)
    # The private alias is fine, but it must be built from the import, not
    # from an inline def.
    assert "from backend.services.daily_brief import extract_session_target" in src, (
        "worker_app still defines its own _extract_target; delete the local def "
        "and import extract_session_target from backend.services.daily_brief"
    )
    # Confirm no local re-definition shadowing the import.
    assert "def _extract_target" not in src, (
        "worker_app defines a local _extract_target that shadows the shared import"
    )


def test_daily_brief_exports_the_shared_function():
    from backend.services import daily_brief

    assert hasattr(daily_brief, "extract_session_target"), (
        "extract_session_target not found in daily_brief; "
        "the canonical function must be importable from there"
    )
    assert callable(daily_brief.extract_session_target)


def test_both_callers_resolve_to_the_same_function_object():
    """Identity check: importing from worker_app and from daily_brief yields
    the same callable — not two copies that happen to look alike.

    Compare by origin (module + qualname) rather than ``is``: a full suite
    can reload ``daily_brief`` between imports, which produces two function
    objects with identical source and would flake a pure identity assert.
    """
    import backend.worker_app as worker
    from backend.services.daily_brief import extract_session_target

    # worker uses the alias _extract_target; grab the underlying function.
    worker_fn = getattr(worker, "_extract_target", None)
    assert worker_fn is not None, "worker_app has no _extract_target at module level"
    assert worker_fn.__module__ == extract_session_target.__module__, (
        "_extract_target in worker_app is not from daily_brief — the duplication is back"
    )
    assert worker_fn.__qualname__ == extract_session_target.__qualname__, (
        "_extract_target in worker_app is a different function from "
        "extract_session_target in daily_brief — the duplication is back"
    )


# ── The function itself ───────────────────────────────────────────────────────

@pytest.fixture
def fn():
    from backend.services.daily_brief import extract_session_target
    return extract_session_target


def test_returns_all_null_for_none(fn):
    assert fn(None) == {"distance_km": None, "duration_min": None, "intensity": None}


def test_returns_all_null_for_empty_dict(fn):
    assert fn({}) == {"distance_km": None, "duration_min": None, "intensity": None}


def test_top_level_keys_take_precedence(fn):
    structure = {"distance_km": 10.0, "duration_min": 60, "intensity": "easy"}
    assert fn(structure) == {"distance_km": 10.0, "duration_min": 60, "intensity": "easy"}


def test_falls_back_to_first_block(fn):
    structure = {
        "blocks": [
            {"distance_km": 5.0, "duration_min": 30, "intensity": "moderate"},
            {"distance_km": 99.0},
        ]
    }
    result = fn(structure)
    assert result["distance_km"] == 5.0
    assert result["duration_min"] == 30
    assert result["intensity"] == "moderate"


def test_top_level_overrides_block(fn):
    """A top-level key wins even when blocks have different values."""
    structure = {
        "distance_km": 8.0,
        "blocks": [{"distance_km": 3.0, "duration_min": 20}],
    }
    result = fn(structure)
    assert result["distance_km"] == 8.0
    # duration_min not at top level → falls through to the block
    assert result["duration_min"] == 20


def test_partial_null_when_key_missing_everywhere(fn):
    structure = {"distance_km": 7.5}
    result = fn(structure)
    assert result["distance_km"] == 7.5
    assert result["duration_min"] is None
    assert result["intensity"] is None


def test_non_dict_structure_returns_all_null(fn):
    for bad in ([], "string", 42, True):
        r = fn(bad)
        assert r == {"distance_km": None, "duration_min": None, "intensity": None}, bad


def test_returns_independent_dict_each_call(fn):
    """Each call returns a fresh dict — mutating the output must not affect the
    next call."""
    r1 = fn({"distance_km": 5.0})
    r1["distance_km"] = 999
    r2 = fn({"distance_km": 5.0})
    assert r2["distance_km"] == 5.0


# ── AC9: no unauthenticated route can read or write another user's data ───────
#
# The audit found two open paths:
#  1. GET /api/users/{user_id}/avatar — no auth, anyone with a guessed UUID
#     could fetch any user's photo. Fixed: now requires a valid session.
#  2. Six worker read routes (GET /api/training/load, /api/plan/today, …) —
#     no auth at all. Fixed: now require Bearer <WORKER_API_TOKEN>.
#
# Both families are verified at the call level below.  The worker family is
# covered exhaustively in tests/test_worker_read_auth__1601.py; the avatar
# route is covered in tests/test_s2_remainder__1601.py.  This test cross-
# references both to confirm the combined picture.

def test_webapp_avatar_returns_401_without_session():
    """The webapp avatar route was the only one with no auth. Anonymous GET
    must 401, not 200."""
    from fastapi.testclient import TestClient
    from backend.main import app

    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/users/00000000-0000-0000-0000-000000000001/avatar")
    assert r.status_code == 401, (
        f"avatar returned {r.status_code} without a session — unauthenticated "
        "cross-user read is back"
    )


def test_worker_read_routes_return_401_without_token(monkeypatch):
    """The six worker routes that had no auth must all reject anonymous calls.
    WORKER_API_TOKEN must be set; the endpoint must check it."""
    from fastapi.testclient import TestClient
    from backend.worker_app import app as worker_app

    monkeypatch.setenv("WORKER_API_TOKEN", "test-sentinel")
    c = TestClient(worker_app, raise_server_exceptions=False)

    for route in (
        "/api/training/load",
        "/api/plan/today",
        "/api/plan/draft-notify",
        "/api/weight/recent",
        "/api/weight/status",
        "/api/weight/nudge",
    ):
        r = c.get(route)
        assert r.status_code == 401, (
            f"worker {route} returned {r.status_code} without a token — "
            "unauthenticated cross-user read is back"
        )


def test_worker_read_routes_return_503_when_token_not_configured():
    """An unset WORKER_API_TOKEN must disable the API (503), not open it."""
    import os
    from fastapi.testclient import TestClient
    from backend.worker_app import app as worker_app

    env_backup = os.environ.pop("WORKER_API_TOKEN", None)
    try:
        c = TestClient(worker_app, raise_server_exceptions=False)
        r = c.get("/api/plan/draft-notify")
        assert r.status_code == 503, (
            f"worker returned {r.status_code} with no token configured — "
            "should be 503 (fails closed)"
        )
    finally:
        if env_backup is not None:
            os.environ["WORKER_API_TOKEN"] = env_backup
