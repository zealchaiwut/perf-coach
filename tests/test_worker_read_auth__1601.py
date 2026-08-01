"""The Hermes read API requires a token — issue #1601.

Six routes on the compute worker had NO authentication of any kind:

    GET /api/training/load      GET /api/weight/recent
    GET /api/plan/today         GET /api/weight/status
    GET /api/plan/draft-notify  GET /api/weight/nudge

``_resolve_read_user`` selected the account by ``User.name == <the request's
?user= param>`` and returned it. No token, no session, no proof of identity.

``docs/worker.md`` justified this as "the tailnet/localhost binding is the
access boundary", but the same document reaches the service at
``http://zeal-server:9100`` — a hostname on the tailnet, not loopback. Anyone
who could route to that port could read any athlete's weight, training load and
plan by guessing a username.

RESIDUAL, deliberately still open: the token is a SERVICE credential. It proves
the caller is Hermes, never *which* athlete, so a token holder can still read
any user via ``?user=``. Closing that needs per-user tokens and is tracked in
#1601's remaining scope. This turns "anyone on the tailnet" into "anyone holding
the service token" — the difference that matters today.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

import backend.worker_app as worker
from backend.worker_app import app

TOKEN = "test-worker-token"

# Every route that reads per-user data.
READ_ROUTES = [
    "/api/training/load",
    "/api/plan/today",
    "/api/plan/draft-notify",
    "/api/weight/recent",
    "/api/weight/status",
    "/api/weight/nudge",
]

# Write routes that already had the guard — asserted so a refactor cannot
# quietly drop it from them while adding it to the reads.
WRITE_ROUTES = ["/weight-entry", "/feel-entry"]


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("WORKER_API_TOKEN", TOKEN)
    return TOKEN


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ── The hole is closed ────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", READ_ROUTES)
def test_no_token_is_rejected(route, client, token):
    """The vulnerability in one assertion: this used to return data."""
    assert client.get(route).status_code == 401


@pytest.mark.parametrize("route", READ_ROUTES)
def test_wrong_token_is_rejected(route, client, token):
    r = client.get(route, headers={"Authorization": f"Bearer not-{TOKEN}"})
    assert r.status_code == 401


@pytest.mark.parametrize("route", READ_ROUTES)
def test_malformed_authorization_header_is_rejected(route, client, token):
    for header in (TOKEN, f"Basic {TOKEN}", "Bearer", "Bearer "):
        r = client.get(route, headers={"Authorization": header})
        assert r.status_code == 401, f"{route} accepted {header!r}"


@pytest.mark.parametrize("route", READ_ROUTES)
def test_user_param_cannot_bypass_the_token(route, client, token):
    """`?user=` was the whole attack. It must not be a way in on its own."""
    assert client.get(f"{route}?user=someone-else").status_code == 401


# ── It fails closed ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", READ_ROUTES)
def test_unset_token_is_503_not_open(route, client, monkeypatch):
    """A missing WORKER_API_TOKEN must disable the API, never expose it.

    The dangerous shape of this bug is `if token: check()` — which silently
    serves everything when the operator forgets to set the variable.
    """
    monkeypatch.delenv("WORKER_API_TOKEN", raising=False)
    assert client.get(route).status_code == 503


# ── A valid token still works ─────────────────────────────────────────────────

def test_valid_token_is_accepted(client, token):
    """draft-notify is parked and returns a static payload, so it exercises the
    guard without needing a database."""
    r = client.get("/api/plan/draft-notify", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["pipeline_off"] is True


# ── The guard itself ──────────────────────────────────────────────────────────

def test_token_comparison_is_constant_time():
    """`==` on secrets short-circuits at the first differing byte, leaking the
    token a character at a time to anyone who can time the response."""
    src = inspect.getsource(worker._require_worker_api_token)
    assert "compare_digest" in src
    assert "!= token" not in src


def test_guard_is_defined_before_the_routes_that_use_it():
    """A dependency must exist at decoration time. The guard originally lived
    BELOW these routes, which is why they could not have used it."""
    src = (inspect.getsource(worker)).replace("\r\n", "\n")
    guard_at = src.index("def _require_worker_api_token")
    first_read_route = min(src.index(f'@app.get("{r}"') for r in READ_ROUTES)
    assert guard_at < first_read_route


@pytest.mark.parametrize("route", READ_ROUTES + WRITE_ROUTES)
def test_every_user_data_route_declares_the_dependency(route):
    """Asserted on the source rather than by calling, so a route added without
    the guard fails here even if nothing exercises it yet."""
    src = inspect.getsource(worker)
    idx = src.index(f'"{route}"')
    decorator = src[idx: src.index(")\n", idx) + 1]
    assert "_require_worker_api_token" in decorator, (
        f"{route} does not require the worker API token"
    )
