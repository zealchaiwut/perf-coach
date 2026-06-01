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

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import User

_log = logging.getLogger(__name__)

COOKIE_NAME = "session"
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

    return data


def set_session(response: Response, user_id: str) -> None:
    token = create_session_cookie(user_id, time.time())
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME)


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
        user = db.get(User, uid)

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user
