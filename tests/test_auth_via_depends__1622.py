"""Auth is declared, not called inline — issue #1622.

Four routers authenticated by calling the dependency as a plain function in the
handler body:

    user = await resolve_user(request)     # instead of Depends(resolve_user)

That works. Anonymous callers were rejected before this change and still are.
It cost two things that only show up from outside the source:

1. `app.dependency_overrides` could not reach those routes. FastAPI resolves
   overrides through the dependency graph, and an inline call is not in it.
   This was found by smoke-testing the three athlete scenarios: overriding
   `resolve_user` authenticated every other router, and the fuel routes alone
   still returned 401.

2. The routes carried no security requirement in the OpenAPI schema.

`coach.py` had it both ways in one file: 5 inline, 3 declared.

On (2) the ticket was wrong, and the fix is bigger than it claimed. Converting
to `Depends` does NOT by itself make auth visible: `resolve_user` reads
`request.cookies` by hand, so it declares nothing to FastAPI's schema
generator. Measured after the conversion, `/api/decisions` — which had used
`Depends(resolve_user)` all along — showed no security either. **Every
authenticated route in the app read as public in `/openapi.json`, not just the
30 inline ones.**

So `auth.py` now also declares an `APIKeyCookie` scheme via `Security(...)`.
It is never read; the cookie is still taken off the request exactly as before,
and `auto_error=False` keeps FastAPI from raising its own 403 in place of our
401. It exists so the schema tells the truth.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ROUTERS = REPO / "backend" / "routers"

# Routes that are deliberately open: no session required by design.
_PUBLIC_PREFIXES = ("/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/health")


def _router_files() -> list[Path]:
    return sorted(p for p in ROUTERS.glob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("path", _router_files(), ids=lambda p: p.name)
def test_no_router_calls_resolve_user_inline(path: Path):
    """The ratchet. Nothing may go back to calling the dependency by hand."""
    src = path.read_text()
    assert "await resolve_user(request)" not in src, (
        f"{path.name} calls resolve_user() inside a handler body. Declare it as "
        "`user: User = Depends(resolve_user)` so overrides and the OpenAPI "
        "schema can see it."
    )


@pytest.mark.parametrize("path", _router_files(), ids=lambda p: p.name)
def test_no_router_calls_require_admin_inline(path: Path):
    src = path.read_text()
    assert "await require_admin(request)" not in src


def test_dependency_override_now_reaches_every_router():
    """The property the fix exists for.

    Before: overriding `resolve_user` authenticated `decisions`, `projection`
    and `preferences` but silently missed `fuel`, `coach`, `injury_log` and
    `strength_sessions` — the four that called it inline.
    """
    from fastapi.testclient import TestClient

    from backend.auth import resolve_user
    from backend.main import app

    class _StubUser:
        id = "00000000-0000-0000-0000-000000000001"
        name = "override-probe"
        is_admin = False
        is_active = True

    app.dependency_overrides[resolve_user] = lambda: _StubUser()
    try:
        c = TestClient(app, raise_server_exceptions=False)
        # One route from each previously-inline router. A 401 here means the
        # override was bypassed, which is the exact bug.
        for route in (
            "/api/fuel/settings",
            "/api/coach/goal",
            "/api/injury-log",
            "/api/strength-sessions",
        ):
            r = c.get(route)
            assert r.status_code != 401, (
                f"{route} ignored dependency_overrides — it is still "
                "resolving the user outside the dependency graph"
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_the_converted_routes_declare_security_in_openapi():
    """What an external auditor sees. Previously these 30 operations looked
    public in the generated schema."""
    from backend.main import app

    schema = app.openapi()
    probes = [
        "/api/fuel/settings",
        "/api/fuel/today",
        "/api/coach/goal",
        "/api/injury-log",
        "/api/strength-sessions",
        "/api/plyo-sessions",
    ]
    missing = []
    for path in probes:
        op = (schema["paths"].get(path) or {}).get("get")
        if op is None:
            missing.append(f"{path} (no GET operation in schema)")
            continue
        params = op.get("parameters") or []
        # The session dependency contributes the cookie parameter; an inline
        # call contributed nothing at all.
        declared = bool(op.get("security")) or any(p.get("in") == "cookie" for p in params)
        if not declared:
            missing.append(path)
    assert not missing, f"no declared auth visible in OpenAPI for: {missing}"


def test_anonymous_still_gets_401():
    """The behaviour that must NOT change. This was never broken; the point of
    the ticket was that it was invisible, not that it was absent."""
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app, raise_server_exceptions=False)
    for route in ("/api/fuel/settings", "/api/coach/goal", "/api/injury-log",
                  "/api/strength-sessions", "/api/plyo-sessions"):
        assert c.get(route).status_code == 401, f"{route} became reachable anonymously"


def test_request_param_dropped_only_where_it_was_unused():
    """Each converted handler used `request` for nothing but the auth call, so
    the parameter went with it. A handler that genuinely needs the Request must
    keep it — asserted here so a later conversion doesn't strip one blindly."""
    for path in _router_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            args = {a.arg for a in node.args.args + node.args.kwonlyargs}
            uses = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if "request" in uses:
                assert "request" in args, (
                    f"{path.name}:{node.name} uses `request` but no longer "
                    "declares it"
                )


def test_every_authenticated_route_declares_security_not_just_the_converted_ones():
    """The wider finding.

    The ticket framed OpenAPI invisibility as a symptom of the inline calls. It
    was not — it was app-wide, because `resolve_user` reads the cookie off the
    request itself. Any route depending on it, however it was declared, looked
    public. This asserts the scheme reaches all of them.
    """
    from backend.main import app

    schema = app.openapi()
    unsecured = []
    for path, ops in schema["paths"].items():
        if path.startswith(_PUBLIC_PREFIXES):
            continue
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if not op.get("security"):
                unsecured.append(f"{method.upper()} {path}")
    # Not every route is authenticated (page routes, admin-cookie routes, the
    # login flow), so this asserts the scheme is reaching a large majority
    # rather than demanding a number that would need editing on every new route.
    total = sum(
        1 for p, ops in schema["paths"].items()
        for m in ops if m in ("get", "post", "put", "patch", "delete")
    )
    assert total - len(unsecured) > total * 0.5, (
        f"only {total - len(unsecured)} of {total} operations declare security; "
        "the APIKeyCookie scheme is not reaching the dependency graph"
    )


def test_the_scheme_does_not_enforce_anything():
    """auto_error=False is load-bearing. Flip it and FastAPI raises its own 403
    before our handler runs, changing the status code every anonymous caller
    sees — including the frontend's redirect-to-login logic."""
    from backend.auth import _session_cookie_scheme

    assert _session_cookie_scheme.auto_error is False
