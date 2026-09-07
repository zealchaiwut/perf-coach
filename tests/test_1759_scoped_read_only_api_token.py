"""Issue #1759 — Scoped read-only API token for machine callers.

Acceptance criteria:

AC1. A token model exists that binds a token to one user and a read-only
     scope; tokens are stored hashed, never in plaintext.

AC2. Authorization: Bearer <token> authenticates read routes as that user;
     the existing cookie flow is unchanged and browser sessions still work.

AC3. A write route rejects a read-only token with 403, covered by a test.

AC4. Token creation and revocation are documented, including where the secret
     lives in Render and how to rotate it.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import State

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# AC1 — Token model exists, hashed storage
# ---------------------------------------------------------------------------

def test_api_token_model_exists():
    """APIToken class must exist in backend.models."""
    from backend import models
    assert hasattr(models, "APIToken"), (
        "APIToken is not defined in backend/models.py. "
        "Add the model class for the api_tokens table."
    )


def test_api_token_model_has_user_id_column():
    """APIToken must have a user_id FK column."""
    from backend.models import APIToken
    cols = {c.name for c in APIToken.__table__.columns}
    assert "user_id" in cols, "APIToken is missing the user_id column"


def test_api_token_model_has_token_hash_column():
    """APIToken must have a token_hash column (plaintext is never stored)."""
    from backend.models import APIToken
    cols = {c.name for c in APIToken.__table__.columns}
    assert "token_hash" in cols, (
        "APIToken is missing the token_hash column. "
        "Store a SHA-256 hex digest, never the raw token."
    )


def test_api_token_model_has_scope_column():
    """APIToken must have a scope column."""
    from backend.models import APIToken
    cols = {c.name for c in APIToken.__table__.columns}
    assert "scope" in cols, "APIToken is missing the scope column"


def test_api_token_model_has_revoked_at_column():
    """APIToken must have a revoked_at nullable column for soft-revoke."""
    from backend.models import APIToken
    cols = {c.name for c in APIToken.__table__.columns}
    assert "revoked_at" in cols, (
        "APIToken is missing revoked_at. Revocation must be recordable without "
        "deleting the row — keep the audit trail."
    )


def test_api_token_model_no_plaintext_token_column():
    """APIToken must NOT have a column named 'token' (plaintext)."""
    from backend.models import APIToken
    cols = {c.name for c in APIToken.__table__.columns}
    assert "token" not in cols, (
        "APIToken has a 'token' column. Never store the raw token — "
        "store only the hash in token_hash."
    )


def test_hash_api_token_returns_hex_string():
    """hash_api_token must return a 64-character hex SHA-256 digest."""
    from backend.auth import hash_api_token
    result = hash_api_token("mysecrettoken123")
    assert isinstance(result, str)
    assert len(result) == 64, f"Expected 64-char hex, got {len(result)}"
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_api_token_matches_sha256():
    """hash_api_token output must match stdlib SHA-256."""
    from backend.auth import hash_api_token
    plaintext = "test-token-value"
    expected = hashlib.sha256(plaintext.encode()).hexdigest()
    assert hash_api_token(plaintext) == expected


def test_hash_api_token_does_not_return_plaintext():
    """hash_api_token must not return the input unchanged."""
    from backend.auth import hash_api_token
    plaintext = "myrandomtoken"
    assert hash_api_token(plaintext) != plaintext


def test_hash_api_token_is_deterministic():
    """hash_api_token must return the same value for the same input."""
    from backend.auth import hash_api_token
    tok = "stable-token-xyz"
    assert hash_api_token(tok) == hash_api_token(tok)


# ---------------------------------------------------------------------------
# AC2 — Cookie session still works; 401 without auth
# ---------------------------------------------------------------------------

def test_cookie_session_still_works():
    """Existing cookie-based session must still resolve to a user via resolve_user (AC2).

    Verifies that resolve_user skips the Bearer path when no Authorization header
    is present, falling through to the cookie path.
    """
    import asyncio
    from backend.auth import resolve_user, get_current_user, COOKIE_NAME
    from backend.models import User as UserModel

    fake_user = MagicMock(spec=UserModel)
    fake_user.id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    fake_user.is_active = True

    mock_request = MagicMock()
    # No Bearer token — only a cookie
    mock_request.headers.get.return_value = ""  # Authorization header is absent
    mock_request.cookies.get.return_value = "fake-cookie-value"
    mock_request.state = State()

    with patch("backend.auth.get_current_user", return_value=fake_user):
        user = asyncio.get_event_loop().run_until_complete(resolve_user(mock_request))

    assert user is fake_user, (
        "Cookie-based session flow is broken — resolve_user should delegate "
        "to get_current_user when no Bearer token is present."
    )


def test_no_auth_returns_401():
    """With no cookie and no Bearer header, protected routes return 401."""
    from backend.main import app
    from starlette.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/weight-entries")
    assert resp.status_code == 401, (
        "Expected 401 for unauthenticated request, got "
        f"{resp.status_code}"
    )


# ---------------------------------------------------------------------------
# AC2 — Bearer token resolves user via DB lookup (logic test, no live DB)
# ---------------------------------------------------------------------------

def test_resolve_user_accepts_bearer_token_format():
    """resolve_user must inspect the Authorization header for Bearer tokens.

    This tests that the function signature and implementation route through
    a Bearer-specific branch. The DB lookup is mocked so no Postgres is needed.
    """
    import asyncio
    from unittest.mock import AsyncMock

    from backend.auth import hash_api_token, resolve_user
    from backend.models import APIToken, User as UserModel

    plaintext = "test-token-abc123"
    token_hash = hash_api_token(plaintext)
    user_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    fake_api_token = MagicMock(spec=APIToken)
    fake_api_token.scope = "read"
    fake_api_token.user_id = user_id
    fake_api_token.revoked_at = None

    fake_user = MagicMock(spec=UserModel)
    fake_user.id = user_id
    fake_user.is_active = True
    fake_user.name = "testuser"

    # Simulate what FastAPI provides as the Session context manager
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    # First query: APIToken lookup; second query: User lookup
    call_count = [0]

    def _query_side_effect(model):
        q = MagicMock()
        call_count[0] += 1
        if model is APIToken or (isinstance(model, type) and issubclass(model, APIToken)):
            q.filter.return_value.first.return_value = fake_api_token
        else:
            # User query uses .options() chaining
            q.filter.return_value.options.return_value.first.return_value = fake_user
            q.filter.return_value.first.return_value = fake_user
        return q

    mock_session.query = _query_side_effect

    mock_request = MagicMock()
    mock_request.cookies.get.return_value = None
    mock_request.headers.get.return_value = f"Bearer {plaintext}"
    mock_request.state = State()

    with patch("backend.auth.Session", return_value=mock_session):
        user = asyncio.get_event_loop().run_until_complete(
            resolve_user(mock_request)
        )

    assert user is fake_user, "resolve_user should return the user resolved from the Bearer token"
    assert getattr(mock_request.state, "token_scope", None) == "read", (
        "resolve_user must set request.state.token_scope to the token's scope "
        "so that require_write can enforce read-only restrictions"
    )


def test_resolve_user_rejects_unknown_bearer_token():
    """resolve_user must raise 401 for a Bearer token not found in the DB."""
    import asyncio
    from backend.auth import resolve_user
    from backend.models import APIToken

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.first.return_value = None

    mock_request = MagicMock()
    mock_request.cookies.get.return_value = None
    mock_request.headers.get.return_value = "Bearer unknown-token-xyz"
    mock_request.state = State()

    with patch("backend.auth.Session", return_value=mock_session):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(resolve_user(mock_request))

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# AC3 — Write route rejects read-only token with 403
# ---------------------------------------------------------------------------

def test_require_write_raises_403_for_read_only_token():
    """require_write must raise HTTP 403 when token_scope is 'read' (AC3)."""
    from backend.auth import require_write

    mock_state = State()
    mock_state.token_scope = "read"

    mock_request = MagicMock()
    mock_request.state = mock_state

    mock_user = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        require_write(mock_request, mock_user)

    assert exc_info.value.status_code == 403, (
        f"Expected 403 for read-only token on write route, got "
        f"{exc_info.value.status_code}"
    )


def test_require_write_allows_cookie_session():
    """require_write must pass through for cookie-authenticated requests (AC2/AC3)."""
    from backend.auth import require_write

    mock_state = State()
    # No token_scope set — simulates cookie-based auth

    mock_request = MagicMock()
    mock_request.state = mock_state

    mock_user = MagicMock()

    result = require_write(mock_request, mock_user)
    assert result is mock_user, (
        "require_write should return the user unchanged for cookie-authenticated requests"
    )


def test_require_write_is_applied_to_at_least_one_write_route():
    """At least one POST/PUT/PATCH/DELETE route must use require_write (AC3).

    This ensures the dependency is actually wired into a real route, not just
    defined and unused.
    """
    import inspect
    from backend.auth import require_write
    from backend.main import app

    routes_with_require_write = []
    for route in app.routes:
        if not hasattr(route, "methods"):
            continue
        if not route.methods.intersection({"POST", "PUT", "PATCH", "DELETE"}):
            continue
        # Inspect dependencies on the route
        if hasattr(route, "dependant") and route.dependant:
            dep_names = []
            for dep in route.dependant.dependencies:
                fn = getattr(dep.cache_key[0], "__func__", dep.cache_key[0])
                if fn is require_write or dep.cache_key[0] is require_write:
                    routes_with_require_write.append(route.path)
                    break
            # Also check the endpoint itself
            endpoint = route.endpoint
            sig = inspect.signature(endpoint)
            for param in sig.parameters.values():
                if hasattr(param.default, "dependency"):
                    if param.default.dependency is require_write:
                        routes_with_require_write.append(route.path)
                        break

    assert routes_with_require_write, (
        "No write route uses require_write as a dependency. "
        "Apply `user: User = Depends(require_write)` to at least one "
        "POST/PUT/PATCH/DELETE endpoint to enforce the read-only token restriction."
    )


def test_write_endpoint_returns_403_for_read_only_bearer_token():
    """POST /api/weight-entries returns 403 when require_write blocks the request (AC3).

    Overrides require_write with a zero-arg stub that always raises 403,
    simulating what require_write does for a real read-only Bearer token.
    (test_require_write_raises_403_for_read_only_token already proves require_write
    itself produces 403 when token_scope is 'read'; this test proves the endpoint
    actually wires the dependency and propagates the 403.)
    """
    from backend.auth import require_write
    from backend.main import app
    from fastapi import HTTPException

    def _always_403():
        raise HTTPException(
            status_code=403,
            detail="Read-only token cannot perform write operations",
        )

    app.dependency_overrides[require_write] = _always_403

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/weight-entries",
            json={"entry_date": "2026-01-01", "weight_kg": 70.0},
        )
        assert resp.status_code == 403, (
            f"Expected 403 when require_write blocks the request, "
            f"got {resp.status_code} ({resp.json()}). "
            "Ensure POST /api/weight-entries uses Depends(require_write)."
        )
    finally:
        app.dependency_overrides.pop(require_write, None)


# ---------------------------------------------------------------------------
# AC4 — Documentation exists
# ---------------------------------------------------------------------------

def test_api_token_documentation_file_exists():
    """A documentation file for API tokens must exist (AC4)."""
    doc_path = REPO / "docs" / "api-tokens.md"
    assert doc_path.exists(), (
        f"Missing documentation file at docs/api-tokens.md. "
        "Create it with instructions for token creation, revocation, "
        "and where the token lives in Render."
    )


def test_api_token_doc_mentions_render():
    """Token doc must mention Render (where the env var lives in production, AC4)."""
    doc_path = REPO / "docs" / "api-tokens.md"
    if not doc_path.exists():
        pytest.skip("docs/api-tokens.md not yet created")
    text = doc_path.read_text()
    assert "render" in text.lower() or "Render" in text, (
        "docs/api-tokens.md does not mention Render. "
        "Add a section explaining where the bearer token credential is stored "
        "(Render environment variable dashboard) and how to rotate it."
    )


def test_api_token_doc_mentions_revocation():
    """Token doc must mention revocation (AC4)."""
    doc_path = REPO / "docs" / "api-tokens.md"
    if not doc_path.exists():
        pytest.skip("docs/api-tokens.md not yet created")
    text = doc_path.read_text()
    assert "revok" in text.lower(), (
        "docs/api-tokens.md does not mention revocation. "
        "Add a section explaining how to revoke a token via the API."
    )


def test_api_token_doc_mentions_rotation():
    """Token doc must describe how to rotate a token (AC4)."""
    doc_path = REPO / "docs" / "api-tokens.md"
    if not doc_path.exists():
        pytest.skip("docs/api-tokens.md not yet created")
    text = doc_path.read_text()
    assert "rotat" in text.lower() or "replac" in text.lower(), (
        "docs/api-tokens.md does not describe token rotation. "
        "Add a section on how to rotate (create a new token, update the "
        "caller's config, then revoke the old one)."
    )


# ---------------------------------------------------------------------------
# AC1/AC2 — Token management endpoints exist
# ---------------------------------------------------------------------------

def test_create_token_endpoint_exists():
    """POST /api/auth/tokens endpoint must exist."""
    from backend.main import app
    post_paths = [
        r.path
        for r in app.routes
        if "POST" in (getattr(r, "methods", None) or set())
    ]
    assert "/api/auth/tokens" in post_paths, (
        "POST /api/auth/tokens endpoint is not registered. "
        "Add a token creation endpoint in backend/main.py."
    )


def test_revoke_token_endpoint_exists():
    """DELETE /api/auth/tokens/{token_id} endpoint must exist."""
    from backend.main import app
    delete_paths = [
        r.path
        for r in app.routes
        if "DELETE" in (getattr(r, "methods", None) or set())
    ]
    assert "/api/auth/tokens/{token_id}" in delete_paths, (
        "DELETE /api/auth/tokens/{token_id} endpoint is not registered. "
        "Add a token revocation endpoint in backend/main.py."
    )
