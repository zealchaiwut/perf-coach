import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid as _uuid
from typing import Optional

from fastapi import HTTPException, Request, Response, Security
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session, load_only as _load_only

from backend.db import engine
from backend.models import User

_log = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """Return the real client IP, accounting for Render's reverse-proxy hop.

    Render appends the connecting client's IP to X-Forwarded-For, so the
    rightmost entry is authoritative and cannot be spoofed by the client
    (they can only prepend, not modify what Render appends).
    Falls back to request.client.host when the header is absent.
    """
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


COOKIE_NAME = "session"

# Declared purely so the session requirement is visible in the OpenAPI schema.
# auto_error=False means FastAPI never raises on a missing cookie — the routes
# keep returning their own 401 — so this is documentation, not enforcement.
_session_cookie_scheme = APIKeyCookie(name="session", auto_error=False)
ADMIN_COOKIE_NAME = "admin_session"
CSRF_COOKIE_NAME = "csrf-token"
_ADMIN_COOKIE_MAX_AGE = int(os.getenv("ADMIN_COOKIE_MAX_AGE", str(4 * 3600)))  # 4 hours default
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", str(30 * 24 * 3600)))  # 30 days default
_ADMIN_LOCKOUT_MAX = int(os.getenv("ADMIN_LOCKOUT_MAX", "5"))
_ADMIN_LOCKOUT_WINDOW = int(os.getenv("ADMIN_LOCKOUT_WINDOW", "300"))  # 5 minutes
_admin_lockout: dict = {}  # ip -> {"count": int, "window_start": float}
MIN_PASSWORD_LENGTH = 8
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

_secret_raw = os.getenv("SESSION_SECRET")
if _secret_raw:
    SESSION_SECRET: bytes = _secret_raw.encode()
else:
    SESSION_SECRET = secrets.token_bytes(32)
    _log.warning(
        "SESSION_SECRET env var is not set; using ephemeral random secret. "
        "All sessions will be invalidated on restart."
    )


def hash_password(plain: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(
        plain.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return f"{_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${h.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        n_str, r_str, p_str, salt_hex, hash_hex = stored.split("$")
        n, r, p = int(n_str), int(r_str), int(p_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.scrypt(plain.encode(), salt=salt, n=n, r=r, p=p, dklen=len(expected))
    return hmac.compare_digest(candidate, expected)


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_session_cookie(user_id: str, issued_at: float) -> str:
    payload = _b64_encode(json.dumps({"user_id": user_id, "issued_at": issued_at}).encode())
    sig = hmac.new(SESSION_SECRET, payload.encode(), "sha256").digest()
    return f"{payload}.{_b64_encode(sig)}"


def read_session_cookie(token: str) -> dict:
    try:
        payload_b64, sig_b64 = token.rsplit(".", 1)
    except (ValueError, AttributeError):
        raise ValueError("invalid token format")

    expected_sig = hmac.new(SESSION_SECRET, payload_b64.encode(), "sha256").digest()
    try:
        actual_sig = _b64_decode(sig_b64)
    except Exception:
        raise ValueError("invalid token encoding")

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("invalid token signature")

    try:
        data = json.loads(_b64_decode(payload_b64))
    except Exception:
        raise ValueError("invalid token payload")

    issued_at = data.get("issued_at")
    if not isinstance(issued_at, (int, float)) or time.time() - issued_at > SESSION_MAX_AGE:
        raise ValueError("session expired")

    return data


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def _cookie_secure() -> bool:
    """Whether auth cookies should be marked Secure (HTTPS-only).

    Secure cookies are silently dropped by the browser over plain HTTP, which
    logs users out. Only PRD (Render) is served over HTTPS; UAT and local run
    over HTTP (e.g. the Tailscale-routed UAT box), so default Secure to on for
    prd and off elsewhere. Override per-environment with SESSION_COOKIE_SECURE
    (1/0) — e.g. set it to 1 if UAT is ever fronted by HTTPS.
    """
    env = os.getenv("ENVIRONMENT", "local")
    return os.getenv("SESSION_COOKIE_SECURE", "1" if env == "prd" else "0") == "1"


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )


def set_session(response: Response, user_id: str) -> str:
    token = create_session_cookie(user_id, time.time())
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )
    csrf_token = generate_csrf_token()
    set_csrf_cookie(response, csrf_token)
    return csrf_token


def clear_session(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")


def get_admin_secret() -> Optional[str]:
    """Return env-specific admin secret, or None if unset."""
    env = os.getenv("ENVIRONMENT", "local")
    val = os.getenv("ADMIN_SECRET_PRD" if env == "prd" else "ADMIN_SECRET_UAT")
    return val or None


def create_admin_cookie(issued_at: float) -> str:
    payload = _b64_encode(json.dumps({"admin": True, "iat": issued_at}).encode())
    sig = hmac.new(SESSION_SECRET, payload.encode(), "sha256").digest()
    return f"{payload}.{_b64_encode(sig)}"


def read_admin_cookie(token: str) -> dict:
    try:
        payload_b64, sig_b64 = token.rsplit(".", 1)
    except (ValueError, AttributeError):
        raise ValueError("invalid token format")
    expected_sig = hmac.new(SESSION_SECRET, payload_b64.encode(), "sha256").digest()
    try:
        actual_sig = _b64_decode(sig_b64)
    except Exception:
        raise ValueError("invalid token encoding")
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("invalid token signature")
    try:
        data = json.loads(_b64_decode(payload_b64))
    except Exception:
        raise ValueError("invalid token payload")
    if time.time() - data.get("iat", 0) > _ADMIN_COOKIE_MAX_AGE:
        raise ValueError("admin token expired")
    return data


def set_admin_cookie(response: Response) -> None:
    token = create_admin_cookie(time.time())
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        max_age=_ADMIN_COOKIE_MAX_AGE,
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(key=ADMIN_COOKIE_NAME)


def admin_lockout_check(ip: str) -> None:
    entry = _admin_lockout.get(ip)
    if entry is None:
        return
    if time.time() - entry["window_start"] > _ADMIN_LOCKOUT_WINDOW:
        del _admin_lockout[ip]
        return
    if entry["count"] >= _ADMIN_LOCKOUT_MAX:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")


def admin_lockout_record(ip: str) -> None:
    now = time.time()
    entry = _admin_lockout.get(ip)
    if entry is None or now - entry["window_start"] > _ADMIN_LOCKOUT_WINDOW:
        _admin_lockout[ip] = {"count": 1, "window_start": now}
    else:
        entry["count"] += 1


def admin_lockout_clear(ip: str) -> None:
    _admin_lockout.pop(ip, None)


async def require_admin(request: Request) -> None:
    """FastAPI dependency: gates all /admin* routes and admin API endpoints.

    Browser clients (no JSON accept) are redirected to /admin on failure.
    JSON clients get 401. Secret unset → 403 for all clients.
    """
    secret = get_admin_secret()
    if not secret:
        raise HTTPException(status_code=403, detail="Admin access is disabled on this instance")
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if token:
        try:
            read_admin_cookie(token)
            return
        except ValueError:
            pass
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    raise HTTPException(status_code=302, headers={"Location": "/admin"})


async def get_current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = read_session_cookie(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session")

    try:
        uid = _uuid.UUID(data["user_id"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid session")

    with Session(engine) as db:
        user = (
            db.query(User)
            .filter(User.id == uid)
            .options(_load_only(
                User.id, User.name, User.is_admin, User.is_active,
                User.password_hash, User.created_at, User.avatar_mime,
            ))
            .first()
        )

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    return user


async def resolve_user(
    request: Request,
    _scheme: Optional[str] = Security(_session_cookie_scheme),
) -> User:
    """Shared FastAPI dependency: resolve the session user or raise 401.

    `_scheme` is declared but never read — the cookie is still taken off the
    request below, exactly as before. Its only job is to put a security
    requirement into the OpenAPI schema, because a dependency that reads
    `request.cookies` by hand contributes nothing there and every one of these
    routes therefore appeared **public** to anything inspecting `/openapi.json`
    rather than the source.

    `auto_error=False` on the scheme is what keeps behaviour identical: FastAPI
    passes None instead of raising its own 403, so the 401 below is still the
    one callers get.
    """
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return await get_current_user(request)
    raise HTTPException(status_code=401, detail="Not authenticated")
