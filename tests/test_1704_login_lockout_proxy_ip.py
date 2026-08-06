"""
Tests for issue #1704: login lockout must use real client IP from X-Forwarded-For
rather than request.client.host, which is Render's internal proxy IP.

Unit tests validate the get_client_ip() helper; integration tests confirm the
lockout keys differ across XFF IPs (so one IP's failures don't lock out another).
"""
import uuid

import httpx
import pytest
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import Scope

from backend.auth import get_client_ip

BASE = "http://127.0.0.1:9001"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_request(xff: str | None = None, client_host: str = "10.0.0.1") -> Request:
    """Build a minimal Starlette Request with optional X-Forwarded-For header."""
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_host, 12345),
    }
    return Request(scope)


# ── Unit: get_client_ip() behaviour ──────────────────────────────────────────

def test_get_client_ip_single_xff_entry():
    """Single IP in X-Forwarded-For: return that IP."""
    req = _make_request(xff="203.0.113.42")
    assert get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_uses_rightmost_xff_entry():
    """Multiple IPs in X-Forwarded-For: return the last (Render-appended) one."""
    req = _make_request(xff="192.0.2.1, 10.10.0.5, 203.0.113.99")
    assert get_client_ip(req) == "203.0.113.99"


def test_get_client_ip_strips_whitespace():
    """Whitespace around IPs in X-Forwarded-For is stripped."""
    req = _make_request(xff="  192.168.1.1 ,  172.16.0.1  ")
    assert get_client_ip(req) == "172.16.0.1"


def test_get_client_ip_falls_back_to_client_host():
    """No X-Forwarded-For header: fall back to request.client.host."""
    req = _make_request(xff=None, client_host="198.51.100.7")
    assert get_client_ip(req) == "198.51.100.7"


def test_get_client_ip_no_client_and_no_xff():
    """No X-Forwarded-For and no client: return 'unknown'."""
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "query_string": b"",
        "headers": [],
        "client": None,
    }
    req = Request(scope)
    assert get_client_ip(req) == "unknown"


# ── Integration: lockout is per real IP, not per shared proxy IP ──────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def test_lockout_keyed_on_xff_ip(client):
    """After 5 failures from XFF IP A, a request from XFF IP B is not locked out."""
    username = f"xff-lockout-{uuid.uuid4().hex[:8]}"
    ip_a = "203.0.113.10"
    ip_b = "203.0.113.20"

    # Trigger lockout on ip_a
    for i in range(5):
        res = client.post(
            "/api/auth/login",
            json={"username": username, "password": "wrong"},
            headers={"X-Forwarded-For": ip_a},
        )
        assert res.status_code == 401, f"Attempt {i + 1} from {ip_a}: expected 401"

    # 6th attempt from ip_a → locked out
    res = client.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong"},
        headers={"X-Forwarded-For": ip_a},
    )
    assert res.status_code == 429, f"6th from {ip_a}: expected 429 (locked), got {res.status_code}"

    # ip_b has zero failures → must still get 401, not 429
    res = client.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong"},
        headers={"X-Forwarded-For": ip_b},
    )
    assert res.status_code == 401, (
        f"Request from {ip_b} got {res.status_code}; "
        "expected 401 — lockout must be per-IP, not shared across all IPs"
    )


def test_admin_lockout_keyed_on_xff_ip(client):
    """Admin lockout: after 5 failures from XFF IP C, XFF IP D is not locked out."""
    ip_c = "198.51.100.30"
    ip_d = "198.51.100.40"

    for i in range(5):
        res = client.post(
            "/api/admin/login",
            json={"secret": "definitely-wrong-secret"},
            headers={"X-Forwarded-For": ip_c},
        )
        assert res.status_code == 401, f"Admin attempt {i + 1} from {ip_c}: expected 401"

    res = client.post(
        "/api/admin/login",
        json={"secret": "definitely-wrong-secret"},
        headers={"X-Forwarded-For": ip_c},
    )
    assert res.status_code == 429, f"6th admin from {ip_c}: expected 429"

    res = client.post(
        "/api/admin/login",
        json={"secret": "definitely-wrong-secret"},
        headers={"X-Forwarded-For": ip_d},
    )
    assert res.status_code == 401, (
        f"Admin request from {ip_d} got {res.status_code}; "
        "expected 401 — admin lockout must be per-IP"
    )
