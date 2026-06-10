import base64 as _base64
import csv as _csv
import hashlib as _hashlib
import hmac as _hmac
import io as _io
import json as _json
import logging as _logging
import math as _math
import os
import secrets as _secrets
import threading as _threading
import time
import uuid as _uuid
from datetime import date as _date, datetime as _datetime, timezone as _timezone, timedelta as _timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode as _urlencode
import urllib.request as _urllib_request
import urllib.error as _urllib_error

_start_time = time.monotonic()

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import check_db, engine, environment
from backend.models import AppConfig, DailyMetric, GoogleOAuthCredentials, Habit, HabitLog, PersonalRecord, SleepImport, StravaActivity, StravaToken, StrydCredentials, SyncJob, TrainingLoadSnapshot, User, UserPreferences, WeightEntry, WeightTarget, Workout, WorkoutExercise, WorkoutFeel, WorkoutSplit, WorkoutTemplate
from backend.services.workout_merge import compute_best_values
from backend.services.training_load import _ewma_alpha, compute_load_curves, current_load, daily_tss_series, daily_update
from backend.services.feel_link import auto_link_feel_entries
from backend.services.weight_status import compute_status_label as _compute_status_label
from backend.services import sync_jobs as _sync_jobs
from backend.services import reconcile as _reconcile
from backend.services import workout_reconcile as _workout_reconcile

app = FastAPI()

# Serve static files (index.html, weight.html, habits.html, css/, js/)
_static_root = Path(__file__).parent.parent
app.mount("/css", StaticFiles(directory=str(_static_root / "frontend" / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(_static_root / "frontend" / "js")), name="js")


@app.middleware("http")
async def _no_cache_frontend(request, call_next):
    """Force browsers to revalidate HTML/JS/CSS instead of using heuristic
    caching. Without this, UAT keeps serving a stale page/script after a fix
    (e.g. an old disabled button) until the user manually hard-refreshes.
    `no-cache` still permits 304s via ETag, so unchanged files aren't re-sent.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _is_guarded_path(path: str) -> bool:
    """Return True if this path requires authentication (HTML page guard only)."""
    if path == "/":
        return True
    clean = path.lstrip("/")
    if clean in _PAGES:
        return True
    if clean.endswith(".html") and clean[:-5] in _PAGES:
        return True
    return False


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    """Redirect unauthenticated browser requests to /login; return 401 for JSON clients."""
    if not _is_guarded_path(request.url.path):
        return await call_next(request)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            read_session_cookie(token)
            return await call_next(request)
        except ValueError:
            pass
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return RedirectResponse(url="/login", status_code=302)


_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@app.middleware("http")
async def _csrf_protect(request: Request, call_next):
    """Require X-CSRF-Token header on all mutating requests that carry a session cookie."""
    if request.method not in _CSRF_SAFE_METHODS:
        session_cookie = request.cookies.get(COOKIE_NAME)
        if session_cookie:
            expected = request.cookies.get(CSRF_COOKIE_NAME)
            actual = request.headers.get("X-CSRF-Token")
            if not expected or not actual or not _hmac.compare_digest(expected, actual):
                return JSONResponse(
                    {"detail": "CSRF token missing or invalid"},
                    status_code=403,
                )
    return await call_next(request)


@app.get("/api/health")
def health():
    """Return service liveness and environment metadata.

    Response schema (current — introduced in #155/#156):
        {
            "status":          "ok",
            "environment":     "uat" | "prd" | "local"  (ENVIRONMENT env var, defaults to "local"),
            "version":         "<GIT_SHA>" | "unknown"   (GIT_SHA env var, defaults to "unknown"),
            "db":              "ok" | "error",
            "uptime_seconds":  <int>
        }

    Always returns HTTP 200. "db" is "error" when SELECT 1 fails or times out
    (hard cap: 2 s). "status" is always "ok" regardless of db state.
    No authentication or user_id required.

    Breaking changes from the previous schema:
        - "database" key renamed to "db"
        - "version" field added (git SHA injected at deploy time via GIT_SHA env var)
        - "uptime_seconds" field added
    """
    return JSONResponse({
        "status": "ok",
        "environment": environment,
        "version": os.getenv("GIT_SHA", "unknown"),
        "db": check_db(),
        "uptime_seconds": int(time.monotonic() - _start_time),
    })


@app.get("/api/env")
def get_env():
    return JSONResponse({"environment": environment})


@app.get("/api/environment")
def get_environment():
    return JSONResponse({"environment": environment})


@app.get("/api/about")
def get_about():
    """Return app metadata for the Settings About section.

    Response schema:
        {
            "app_version":        str  — contents of VERSION file; fallback "v0.0.1-dev"
            "git_sha":            str  — GIT_SHA env var; fallback "local-dev"
            "environment":        str  — current environment ("uat"/"prd"/"local")
            "changelog_available": bool — True when CHANGELOG.md exists in repo root
        }
    """
    version_file = _static_root / "VERSION"
    try:
        app_version = version_file.read_text().strip() if version_file.exists() else "v0.0.1-dev"
    except OSError:
        app_version = "v0.0.1-dev"

    changelog_file = _static_root / "CHANGELOG.md"
    changelog_available = changelog_file.exists()

    return JSONResponse({
        "app_version": app_version,
        "git_sha": os.getenv("GIT_SHA", "local-dev"),
        "environment": environment,
        "changelog_available": changelog_available,
    })


@app.get("/api/users")
def get_users():
    try:
        from sqlalchemy import func, outerjoin, select
        with Session(engine) as session:
            wcount_sub = (
                select(WeightEntry.user_id, func.count().label("wcount"))
                .group_by(WeightEntry.user_id)
                .subquery()
            )
            hcount_sub = (
                select(Habit.user_id, func.count().label("hcount"))
                .where(Habit.archived_at.is_(None))
                .group_by(Habit.user_id)
                .subquery()
            )
            strava_sub = (
                select(StravaToken.user_id)
                .subquery()
            )
            now = _datetime.now(_timezone.utc)
            stryd_sub = (
                select(StrydCredentials.user_id)
                .where(
                    StrydCredentials.session_token.isnot(None),
                    StrydCredentials.session_token_expires_at.isnot(None),
                    StrydCredentials.session_token_expires_at > now,
                )
                .subquery()
            )
            rows = (
                session.query(
                    User,
                    func.coalesce(wcount_sub.c.wcount, 0),
                    func.coalesce(hcount_sub.c.hcount, 0),
                    strava_sub.c.user_id.isnot(None).label("strava_connected"),
                    stryd_sub.c.user_id.isnot(None).label("stryd_connected"),
                )
                .outerjoin(wcount_sub, User.id == wcount_sub.c.user_id)
                .outerjoin(hcount_sub, User.id == hcount_sub.c.user_id)
                .outerjoin(strava_sub, User.id == strava_sub.c.user_id)
                .outerjoin(stryd_sub, User.id == stryd_sub.c.user_id)
                .order_by(User.name)
                .all()
            )
            result = [
                {
                    "id": str(u.id),
                    "name": u.name,
                    "is_admin": bool(u.is_admin),
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "weight_count": wc,
                    "habits_count": hc,
                    "strava_connected": bool(sc),
                    "stryd_connected": bool(syc),
                }
                for u, wc, hc, sc, syc in rows
            ]
            return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable: " + str(exc))


# ── User management endpoints ─────────────────────────────────────────────────

class UserIn(BaseModel):
    name: str


@app.post("/api/users", status_code=201)
def create_user(body: UserIn):
    name = body.name.strip()
    if not (1 <= len(name) <= 100):
        raise HTTPException(status_code=400, detail="Name must be 1–100 characters")
    with Session(engine) as session:
        user = User(name=name)
        session.add(user)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(status_code=409, content={"error": "Name already exists"})
        session.refresh(user)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(user.id),
                "name": user.name,
                "is_admin": bool(user.is_admin),
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
        )


@app.patch("/api/users/{user_id}")
def rename_user(user_id: str, body: UserIn):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    name = body.name.strip()
    if not (1 <= len(name) <= 100):
        raise HTTPException(status_code=400, detail="Name must be 1–100 characters")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.name = name
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(status_code=409, content={"error": "Name already exists"})
        session.refresh(user)
        return JSONResponse({
            "id": str(user.id),
            "name": user.name,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        })


@app.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        total = session.query(User).count()
        if total <= 1:
            return JSONResponse(
                status_code=409,
                content={"error": "At least one user must exist"},
            )
        habit_ids = [h.id for h in session.query(Habit.id).filter(Habit.user_id == uid).all()]
        if habit_ids:
            session.query(HabitLog).filter(HabitLog.habit_id.in_(habit_ids)).delete(synchronize_session=False)
        session.query(HabitLog).filter(HabitLog.user_id == uid).delete(synchronize_session=False)
        session.query(Habit).filter(Habit.user_id == uid).delete(synchronize_session=False)
        session.query(WeightEntry).filter(WeightEntry.user_id == uid).delete(synchronize_session=False)
        session.delete(user)
        session.commit()
    return Response(status_code=204)


# ── Auth endpoints ────────────────────────────────────────────────────────────

from backend.auth import (  # noqa: E402
    ADMIN_COOKIE_NAME,
    admin_lockout_check,
    admin_lockout_clear,
    admin_lockout_record,
    clear_admin_cookie,
    clear_session,
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    get_admin_secret,
    get_current_user,
    hash_password,
    MIN_PASSWORD_LENGTH,
    read_admin_cookie,
    read_session_cookie,
    require_admin,
    set_admin_cookie,
    set_csrf_cookie,
    set_session,
    verify_password,
)

_resolve_user_log = _logging.getLogger(__name__)

LEGACY_USER_ID_SHIM_ENABLED = False


async def resolve_user(
    request: Request,
    user_id: Optional[str] = Query(None),
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return await get_current_user(request)
    if LEGACY_USER_ID_SHIM_ENABLED and user_id is not None:
        _resolve_user_log.warning(
            "Deprecated: user resolved via ?user_id query param. Migrate to session auth."
        )
        with Session(engine) as db:
            try:
                uid = _uuid.UUID(user_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid user_id")
            user = db.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    raise HTTPException(status_code=401, detail="Not authenticated")


_LOCKOUT_MAX_ATTEMPTS = 5
_LOCKOUT_WINDOW_SECONDS = 300  # 5 minutes
_lockout: dict = {}  # (username_lower, ip) -> {"count": int, "window_start": float}


def _lockout_key(username: str, ip: str) -> tuple:
    return (username.lower(), ip)


def _check_lockout(username: str, ip: str) -> None:
    key = _lockout_key(username, ip)
    entry = _lockout.get(key)
    if entry is None:
        return
    if time.time() - entry["window_start"] > _LOCKOUT_WINDOW_SECONDS:
        del _lockout[key]
        return
    if entry["count"] >= _LOCKOUT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many failed login attempts. Try again later.")


def _record_failure(username: str, ip: str) -> None:
    key = _lockout_key(username, ip)
    now = time.time()
    entry = _lockout.get(key)
    if entry is None or now - entry["window_start"] > _LOCKOUT_WINDOW_SECONDS:
        _lockout[key] = {"count": 1, "window_start": now}
    else:
        entry["count"] += 1


def _clear_lockout(username: str, ip: str) -> None:
    _lockout.pop(_lockout_key(username, ip), None)


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "unknown"
    _check_lockout(body.username, ip)
    try:
        with Session(engine) as session:
            user = session.query(User).filter(User.name == body.username).first()
    except sa_exc.SQLAlchemyError:
        raise HTTPException(status_code=500, detail="Database error")
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        _record_failure(body.username, ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _clear_lockout(body.username, ip)
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    resp = JSONResponse({"id": str(user.id), "name": user.name, "is_admin": bool(user.is_admin)})
    set_session(resp, str(user.id))
    return resp


@app.post("/api/auth/logout", status_code=204)
def logout():
    resp = Response(status_code=204)
    clear_session(resp)
    return resp


def _user_dict(user: User) -> dict:
    with Session(engine) as session:
        has_active = session.query(WeightTarget).filter(
            WeightTarget.user_id == user.id,
            WeightTarget.status == "active",
        ).first() is not None
    return {
        "id": str(user.id),
        "name": user.name,
        "is_admin": bool(user.is_admin),
        "has_active_weight_target": has_active,
    }


@app.get("/api/auth/me")
async def me(request: Request):
    user = await get_current_user(request)
    return JSONResponse(_user_dict(user))


@app.get("/api/csrf-token")
async def get_csrf_token(request: Request):
    """Return the current CSRF token, setting a fresh one if the cookie is absent."""
    existing = request.cookies.get(CSRF_COOKIE_NAME)
    if existing:
        return JSONResponse({"csrf_token": existing})
    token = generate_csrf_token()
    resp = JSONResponse({"csrf_token": token})
    set_csrf_cookie(resp, token)
    return resp


# ── Avatar endpoints ──────────────────────────────────────────────────────────

_ALLOWED_AVATAR_MIMES = {"image/jpeg", "image/png", "image/webp"}
_MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB


@app.post("/api/users/me/avatar")
async def upload_avatar(request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    if file.content_type not in _ALLOWED_AVATAR_MIMES:
        raise HTTPException(status_code=415, detail="Unsupported media type. Allowed: JPEG, PNG, WebP")
    data = await file.read()
    if len(data) > _MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 2 MB")
    with Session(engine) as session:
        db_user = session.get(User, user.id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        db_user.avatar = data
        db_user.avatar_mime = file.content_type
        session.commit()
    return JSONResponse({"ok": True})


@app.get("/api/users/{user_id}/avatar")
def get_avatar(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None or not user.avatar:
            raise HTTPException(status_code=404, detail="No avatar set")
        return Response(
            content=bytes(user.avatar),
            media_type=user.avatar_mime or "image/jpeg",
            headers={"Cache-Control": "max-age=3600"},
        )


@app.delete("/api/users/me/avatar", status_code=204)
async def delete_avatar(request: Request):
    user = await get_current_user(request)
    with Session(engine) as session:
        db_user = session.get(User, user.id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        db_user.avatar = None
        db_user.avatar_mime = None
        session.commit()
    return Response(status_code=204)


# ── Weight endpoints (AC-1 through AC-4) ─────────────────────────────────────

class WeightEntryIn(BaseModel):
    weight_kg: float
    recorded_date: str  # YYYY-MM-DD


@app.get("/api/weight")
def get_weight(user: User = Depends(resolve_user)):
    with Session(engine) as session:
        rows = (
            session.query(WeightEntry)
            .filter(WeightEntry.user_id == user.id)
            .order_by(WeightEntry.recorded_date)
            .all()
        )
        return JSONResponse([
            {
                "id": str(r.id),
                "weight_kg": float(r.weight_kg),
                "recorded_date": str(r.recorded_date),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ])


@app.post("/api/weight", status_code=201)
def post_weight(body: WeightEntryIn, user: User = Depends(resolve_user)):
    with Session(engine) as session:
        entry = WeightEntry(
            user_id=user.id,
            weight_kg=body.weight_kg,
            recorded_date=body.recorded_date,
        )
        session.add(entry)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "Entry exists for this date"},
            )
        session.refresh(entry)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(entry.id),
                "weight_kg": float(entry.weight_kg),
                "recorded_date": str(entry.recorded_date),
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            },
        )


@app.delete("/api/weight/{entry_id}", status_code=204)
def delete_weight(entry_id: str, user: User = Depends(resolve_user)):
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id")
    with Session(engine) as session:
        entry = session.get(WeightEntry, eid)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        if entry.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        session.delete(entry)
        session.commit()
    return Response(status_code=204)


class WeightEntryPatch(BaseModel):
    weight_kg: Optional[float] = None
    recorded_date: Optional[str] = None  # YYYY-MM-DD


@app.patch("/api/weight/{entry_id}")
def patch_weight(entry_id: str, body: WeightEntryPatch, user: User = Depends(resolve_user)):
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id")
    if body.weight_kg is not None and body.weight_kg <= 0:
        raise HTTPException(status_code=422, detail="weight_kg must be positive")
    with Session(engine) as session:
        entry = session.get(WeightEntry, eid)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        if entry.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        if body.weight_kg is not None:
            entry.weight_kg = body.weight_kg
        if body.recorded_date is not None:
            entry.recorded_date = body.recorded_date
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "Entry exists for this date"},
            )
        session.refresh(entry)
        return JSONResponse({
            "id": str(entry.id),
            "weight_kg": float(entry.weight_kg),
            "recorded_date": str(entry.recorded_date),
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        })


# ── Weight entries CRUD endpoints ─────────────────────────────────────────────

class WeightEntriesCreateIn(BaseModel):
    user_id: str
    entry_date: str  # YYYY-MM-DD
    entry_time: Optional[str] = None  # HH:MM or HH:MM:SS
    weight_kg: float
    notes: Optional[str] = None


class WeightEntriesPatchIn(BaseModel):
    user_id: Optional[str] = None    # forbidden — 422 if present in model_fields_set
    entry_date: Optional[str] = None  # forbidden — 422 if present in model_fields_set
    weight_kg: Optional[float] = None
    entry_time: Optional[str] = None
    notes: Optional[str] = None


def _weight_entry_dict(e: WeightEntry) -> dict:
    return {
        "id": str(e.id),
        "user_id": str(e.user_id),
        "entry_date": str(e.entry_date),
        "entry_time": str(e.entry_time) if e.entry_time is not None else None,
        "weight_kg": float(e.weight_kg),
        "notes": e.notes,
        "source": e.source,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _parse_entry_time(entry_time_str: str):
    """Parse HH:MM or HH:MM:SS string to datetime.time; raises HTTPException on bad format."""
    from datetime import time as _time
    try:
        parts = entry_time_str.split(":")
        if len(parts) == 2:
            return _time(int(parts[0]), int(parts[1]))
        elif len(parts) == 3:
            return _time(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, AttributeError):
        pass
    raise HTTPException(status_code=422, detail="Invalid entry_time; use HH:MM or HH:MM:SS")


@app.post("/api/weight-entries", status_code=201)
def create_weight_entry(body: WeightEntriesCreateIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if not (20 <= body.weight_kg <= 300):
        raise HTTPException(status_code=422, detail="weight_kg must be between 20 and 300")
    if body.notes is not None and len(body.notes) > 500:
        raise HTTPException(status_code=422, detail="notes must not exceed 500 characters")

    try:
        entry_date = _date.fromisoformat(body.entry_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid entry_date; use YYYY-MM-DD")
    if entry_date > _date.today() + _timedelta(days=1):
        raise HTTPException(status_code=422, detail="entry_date cannot be more than 1 day in the future")

    entry_time = _parse_entry_time(body.entry_time) if body.entry_time is not None else None

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        entry = WeightEntry(
            user_id=uid,
            entry_date=entry_date,
            entry_time=entry_time,
            weight_kg=body.weight_kg,
            notes=body.notes,
            source="manual",
        )
        session.add(entry)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            q = session.query(WeightEntry).filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date == entry_date,
            )
            if entry_time is None:
                q = q.filter(WeightEntry.entry_time.is_(None))
            else:
                q = q.filter(WeightEntry.entry_time == entry_time)
            existing = q.first()
            return JSONResponse(
                status_code=409,
                content={
                    "error_code": "duplicate",
                    "existing_id": str(existing.id) if existing else None,
                },
            )
        session.refresh(entry)
        return JSONResponse(status_code=201, content=_weight_entry_dict(entry))


@app.get("/api/weight-entries")
def list_weight_entries(
    user_id: str = Query(...),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = _date.today()
    if from_date is None and to_date is None:
        from_d = today - _timedelta(days=89)
        to_d = today
    else:
        try:
            from_d = _date.fromisoformat(from_date) if from_date else today - _timedelta(days=89)
            to_d = _date.fromisoformat(to_date) if to_date else today
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format; use YYYY-MM-DD")

    if from_d > to_d:
        raise HTTPException(status_code=422, detail="from must not be after to")
    days_in_range = (to_d - from_d).days + 1
    if days_in_range > 365:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 365 days")

    from sqlalchemy import nullslast
    with Session(engine) as session:
        rows = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date >= from_d,
                WeightEntry.entry_date <= to_d,
            )
            .order_by(WeightEntry.entry_date.desc(), nullslast(WeightEntry.entry_time.desc()))
            .all()
        )

        entries = [_weight_entry_dict(r) for r in rows]
        count = len(entries)

        if count > 0:
            unique_dates = {r.entry_date for r in rows}
            weights = [float(r.weight_kg) for r in rows]
            first_date = str(min(unique_dates))
            last_date = str(max(unique_dates))
            min_kg = min(weights)
            max_kg = max(weights)
            avg_kg = round(sum(weights) / count, 4)
            days_logged_pct = round(len(unique_dates) / days_in_range * 100, 2)
        else:
            first_date = last_date = None
            min_kg = max_kg = avg_kg = None
            days_logged_pct = 0.0

        summary = {
            "first_date": first_date,
            "last_date": last_date,
            "min_kg": min_kg,
            "max_kg": max_kg,
            "avg_kg": avg_kg,
            "entries_logged": count,
            "days_in_range": days_in_range,
            "days_logged_pct": days_logged_pct,
        }

        return JSONResponse({"entries": entries, "count": count, "summary": summary})


@app.patch("/api/weight-entries/{entry_id}")
def patch_weight_entry(entry_id: str, body: WeightEntriesPatchIn):
    if "user_id" in body.model_fields_set or "entry_date" in body.model_fields_set:
        raise HTTPException(status_code=422, detail="user_id and entry_date cannot be changed")

    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id")

    with Session(engine) as session:
        entry = session.get(WeightEntry, eid)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")

        if "weight_kg" in body.model_fields_set and body.weight_kg is not None:
            if not (20 <= body.weight_kg <= 300):
                raise HTTPException(status_code=422, detail="weight_kg must be between 20 and 300")
            entry.weight_kg = body.weight_kg

        if "notes" in body.model_fields_set:
            if body.notes is not None and len(body.notes) > 500:
                raise HTTPException(status_code=422, detail="notes must not exceed 500 characters")
            entry.notes = body.notes

        if "entry_time" in body.model_fields_set:
            entry.entry_time = _parse_entry_time(body.entry_time) if body.entry_time is not None else None

        entry.updated_at = _datetime.now(_timezone.utc)

        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(status_code=409, content={"error": "Duplicate entry for this user/date/time"})

        session.refresh(entry)
        return JSONResponse(_weight_entry_dict(entry))


@app.delete("/api/weight-entries/{entry_id}")
def delete_weight_entry(entry_id: str):
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id")

    with Session(engine) as session:
        entry = session.get(WeightEntry, eid)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        session.delete(entry)
        session.commit()
    return JSONResponse({"deleted": True})


# ── Weight target endpoints ───────────────────────────────────────────────────

class WeightTargetCreateIn(BaseModel):
    user_id: str
    start_weight_kg: float
    start_date: str        # YYYY-MM-DD
    target_weight_kg: float
    target_date: str       # YYYY-MM-DD
    notes: Optional[str] = None


class WeightTargetPatchIn(BaseModel):
    start_weight_kg: Optional[float] = None   # forbidden — 422 if present
    start_date: Optional[str] = None          # forbidden — 422 if present
    target_weight_kg: Optional[float] = None
    target_date: Optional[str] = None
    notes: Optional[str] = None


class WeightTargetEndIn(BaseModel):
    status: str   # "achieved" | "abandoned"


def _weight_target_dict(t: WeightTarget) -> dict:
    return {
        "id": str(t.id),
        "user_id": str(t.user_id),
        "start_weight_kg": float(t.start_weight_kg),
        "start_date": str(t.start_date),
        "target_weight_kg": float(t.target_weight_kg),
        "target_date": str(t.target_date),
        "status": t.status,
        "notes": t.notes,
        "end_weight_kg": float(t.end_weight_kg) if t.end_weight_kg is not None else None,
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _compute_weight_target_active(t: WeightTarget, session) -> dict:
    """Return _weight_target_dict augmented with computed fields for the active target view."""
    base = _weight_target_dict(t)

    today = _date.today()
    target_date = t.target_date if isinstance(t.target_date, _date) else _date.fromisoformat(str(t.target_date))
    start_date = t.start_date if isinstance(t.start_date, _date) else _date.fromisoformat(str(t.start_date))

    days_remaining = (target_date - today).days
    total_kg = float(t.start_weight_kg) - float(t.target_weight_kg)

    # Most recent weight entry for this user
    recent_entry = (
        session.query(WeightEntry)
        .filter(WeightEntry.user_id == t.user_id)
        .order_by(WeightEntry.entry_date.desc(), WeightEntry.created_at.desc())
        .first()
    )
    current_avg_kg = float(recent_entry.weight_kg) if recent_entry else None
    current_weight = current_avg_kg if current_avg_kg is not None else float(t.start_weight_kg)

    kg_lost = float(t.start_weight_kg) - current_weight
    kg_to_go = current_weight - float(t.target_weight_kg)

    if total_kg != 0:
        progress_pct = round(min(max(kg_lost / total_kg * 100, 0), 100), 2)
    else:
        progress_pct = 100.0

    weeks_remaining = days_remaining / 7.0
    required_pace = round(kg_to_go / weeks_remaining, 4) if weeks_remaining > 0 else None

    # Current pace from last 14 days of weight entries (linear regression or avg)
    cutoff_14 = today - _timedelta(days=14)
    entries_14 = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == t.user_id,
            WeightEntry.entry_date >= cutoff_14,
        )
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )

    current_pace = None
    projected_end_date = None
    if len(entries_14) >= 2:
        first_e = entries_14[0]
        last_e = entries_14[-1]
        days_span = (last_e.entry_date - first_e.entry_date).days
        if days_span > 0:
            kg_change = float(first_e.weight_kg) - float(last_e.weight_kg)
            current_pace = round(kg_change / days_span * 7, 4)
    elif len(entries_14) == 1:
        days_elapsed = (today - start_date).days
        if days_elapsed > 0:
            kg_change = float(t.start_weight_kg) - float(entries_14[0].weight_kg)
            current_pace = round(kg_change / days_elapsed * 7, 4)

    if current_pace is not None and current_pace > 0 and kg_to_go > 0:
        weeks_to_go = kg_to_go / current_pace
        projected_end_date = (today + _timedelta(weeks=weeks_to_go)).isoformat()

    status_label = _compute_status_label(t, current_avg_kg, today)

    base.update({
        "progress_pct": progress_pct,
        "kg_to_go": round(kg_to_go, 2),
        "days_remaining": days_remaining,
        "required_pace_kg_per_week": required_pace,
        "current_pace_kg_per_week": current_pace,
        "projected_end_date": projected_end_date,
        "status_label": status_label,
    })
    return base


def _weight_target_history_dict(t: WeightTarget) -> dict:
    """Return _weight_target_dict augmented with history computed fields."""
    base = _weight_target_dict(t)
    start_date = t.start_date if isinstance(t.start_date, _date) else _date.fromisoformat(str(t.start_date))

    achieved_weight_kg = float(t.end_weight_kg) if t.end_weight_kg is not None else None
    total_kg = float(t.start_weight_kg) - float(t.target_weight_kg)
    if achieved_weight_kg is not None and total_kg != 0:
        achieved_kg = float(t.start_weight_kg) - achieved_weight_kg
        achieved_pct = round(min(achieved_kg / total_kg * 100, 100), 2)
    else:
        achieved_pct = None

    if t.ended_at:
        ended_date = t.ended_at.date() if hasattr(t.ended_at, "date") else t.ended_at
        duration_days = (ended_date - start_date).days
    else:
        duration_days = None

    base.update({
        "achieved_weight_kg": achieved_weight_kg,
        "achieved_pct": achieved_pct,
        "duration_days": duration_days,
    })
    return base


@app.post("/api/weight-targets", status_code=201)
def create_weight_target(body: WeightTargetCreateIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if not (20 <= body.start_weight_kg <= 300):
        raise HTTPException(status_code=422, detail="start_weight_kg must be between 20 and 300")
    if not (20 <= body.target_weight_kg <= 300):
        raise HTTPException(status_code=422, detail="target_weight_kg must be between 20 and 300")

    try:
        start_date = _date.fromisoformat(body.start_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid start_date; use YYYY-MM-DD")
    if start_date > _date.today():
        raise HTTPException(status_code=422, detail="start_date cannot be in the future")

    try:
        target_date = _date.fromisoformat(body.target_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid target_date; use YYYY-MM-DD")
    if target_date <= start_date:
        raise HTTPException(status_code=422, detail="target_date must be after start_date")
    max_target = start_date.replace(year=start_date.year + 5)
    if target_date > max_target:
        raise HTTPException(status_code=422, detail="target_date cannot be more than 5 years after start_date")

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        existing_active = (
            session.query(WeightTarget)
            .filter(WeightTarget.user_id == uid, WeightTarget.status == "active")
            .first()
        )
        if existing_active is not None:
            return JSONResponse(
                status_code=409,
                content={
                    "error_code": "active_target_exists",
                    "active_id": str(existing_active.id),
                    "message": "End or replace the active target first",
                },
            )

        target = WeightTarget(
            user_id=uid,
            start_weight_kg=body.start_weight_kg,
            start_date=start_date,
            target_weight_kg=body.target_weight_kg,
            target_date=target_date,
            notes=body.notes,
            status="active",
        )
        session.add(target)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            existing = (
                session.query(WeightTarget)
                .filter(WeightTarget.user_id == uid, WeightTarget.status == "active")
                .first()
            )
            return JSONResponse(
                status_code=409,
                content={
                    "error_code": "active_target_exists",
                    "active_id": str(existing.id) if existing else None,
                    "message": "End or replace the active target first",
                },
            )
        session.refresh(target)
        return JSONResponse(status_code=201, content=_weight_target_dict(target))


@app.get("/api/weight-targets/active")
def get_active_weight_target(user_id: str = Query(...)):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        target = (
            session.query(WeightTarget)
            .filter(WeightTarget.user_id == uid, WeightTarget.status == "active")
            .first()
        )
        if target is None:
            return JSONResponse({"target": None})

        return JSONResponse({"target": _compute_weight_target_active(target, session)})


@app.get("/api/weight-targets/history")
def get_weight_target_history(
    user_id: str = Query(...),
    status: Optional[str] = Query(default=None),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        q = session.query(WeightTarget).filter(
            WeightTarget.user_id == uid,
            WeightTarget.status != "active",
        )
        if status is not None:
            q = q.filter(WeightTarget.status == status)
        targets = q.order_by(WeightTarget.ended_at.desc()).all()

        return JSONResponse({"targets": [_weight_target_history_dict(t) for t in targets]})


@app.patch("/api/weight-targets/{target_id}")
def patch_weight_target(target_id: str, body: WeightTargetPatchIn):
    if "start_weight_kg" in body.model_fields_set or "start_date" in body.model_fields_set:
        raise HTTPException(status_code=422, detail="start_weight_kg and start_date cannot be changed")

    try:
        tid = _uuid.UUID(target_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target_id")

    with Session(engine) as session:
        target = session.get(WeightTarget, tid)
        if target is None:
            raise HTTPException(status_code=404, detail="Target not found")
        if target.status != "active":
            raise HTTPException(status_code=422, detail="Only active targets can be edited")

        if "target_weight_kg" in body.model_fields_set and body.target_weight_kg is not None:
            if not (20 <= body.target_weight_kg <= 300):
                raise HTTPException(status_code=422, detail="target_weight_kg must be between 20 and 300")
            target.target_weight_kg = body.target_weight_kg

        if "target_date" in body.model_fields_set and body.target_date is not None:
            try:
                target.target_date = _date.fromisoformat(body.target_date)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid target_date; use YYYY-MM-DD")

        if "notes" in body.model_fields_set:
            target.notes = body.notes

        target.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(target)
        return JSONResponse(_weight_target_dict(target))


@app.post("/api/weight-targets/{target_id}/end")
def end_weight_target(target_id: str, body: WeightTargetEndIn):
    if body.status not in ("achieved", "abandoned"):
        raise HTTPException(status_code=422, detail="status must be 'achieved' or 'abandoned'")

    try:
        tid = _uuid.UUID(target_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target_id")

    with Session(engine) as session:
        target = session.get(WeightTarget, tid)
        if target is None:
            raise HTTPException(status_code=404, detail="Target not found")
        if target.status != "active":
            raise HTTPException(status_code=422, detail="Only active targets can be ended")

        cutoff = _date.today() - _timedelta(days=7)
        recent_weight = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == target.user_id,
                WeightEntry.entry_date >= cutoff,
            )
            .order_by(WeightEntry.entry_date.desc(), WeightEntry.created_at.desc())
            .first()
        )
        if recent_weight is None:
            raise HTTPException(
                status_code=422,
                detail="Log a recent weight before ending the target",
            )

        target.status = body.status
        target.end_weight_kg = recent_weight.weight_kg
        target.ended_at = _datetime.now(_timezone.utc)
        target.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(target)
        return JSONResponse(_weight_target_dict(target))


# ── Weight chart endpoint ──────────────────────────────────────────────────────

def _advance_one_month(d: _date) -> _date:
    """Return same day-of-month in the next calendar month, clamped to month end."""
    month = d.month + 1
    year = d.year
    if month > 12:
        month = 1
        year += 1
    if month == 12:
        last_day = (_date(year + 1, 1, 1) - _timedelta(days=1)).day
    else:
        last_day = (_date(year, month + 1, 1) - _timedelta(days=1)).day
    return _date(year, month, min(d.day, last_day))


@app.get("/api/weight-chart")
def get_weight_chart(
    user_id: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    include_target: bool = Query(default=True),
):
    if user_id is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = _date.today()
    if from_date is None and to_date is None:
        from_d = today - _timedelta(days=89)
        to_d = today
    else:
        try:
            from_d = _date.fromisoformat(from_date) if from_date else today - _timedelta(days=89)
            to_d = _date.fromisoformat(to_date) if to_date else today
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format; use YYYY-MM-DD")

    if (to_d - from_d).days > 365:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 365 days")

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Fetch entries wide enough for trend MA (6 days before from) and delta stats (36 days before to)
        fetch_start = min(from_d - _timedelta(days=6), to_d - _timedelta(days=36))
        all_entries = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date >= fetch_start,
                WeightEntry.entry_date <= to_d,
            )
            .order_by(WeightEntry.entry_date.asc(), WeightEntry.entry_time.asc())
            .all()
        )

        # Map date → list of weights for MA computation
        date_weights: dict = {}
        for e in all_entries:
            d = e.entry_date if isinstance(e.entry_date, _date) else _date.fromisoformat(str(e.entry_date))
            date_weights.setdefault(d, []).append(float(e.weight_kg))

        def _ma_for_day(day: _date):
            window_start = day - _timedelta(days=6)
            vals = []
            for offset in range(7):
                di = window_start + _timedelta(days=offset)
                if di in date_weights:
                    vals.extend(date_weights[di])
            if not vals:
                return None
            return round(sum(vals) / len(vals), 2)

        # Actuals: one object per real weight_entry row in [from_d, to_d]
        actuals = []
        for e in all_entries:
            d = e.entry_date if isinstance(e.entry_date, _date) else _date.fromisoformat(str(e.entry_date))
            if d < from_d:
                continue
            actuals.append({"date": str(d), "weight_kg": float(e.weight_kg)})

        # Trend: dense, one point per day in [from_d, to_d]; null when window is empty
        num_days = (to_d - from_d).days + 1
        trend = []
        for i in range(num_days):
            day = from_d + _timedelta(days=i)
            trend.append({"date": str(day), "weight_kg": _ma_for_day(day)})

        # Stats
        in_range = [e for e in all_entries if (
            (e.entry_date if isinstance(e.entry_date, _date) else _date.fromisoformat(str(e.entry_date))) >= from_d
        )]
        current_weight_kg = float(in_range[-1].weight_kg) if in_range else None

        current_avg_kg = None
        for t in reversed(trend):
            if t["weight_kg"] is not None:
                current_avg_kg = t["weight_kg"]
                break

        delta_7d_kg = None
        if current_avg_kg is not None:
            ma_7d_ago = _ma_for_day(to_d - _timedelta(days=7))
            if ma_7d_ago is not None:
                delta_7d_kg = round(current_avg_kg - ma_7d_ago, 2)

        delta_30d_kg = None
        if current_avg_kg is not None:
            ma_30d_ago = _ma_for_day(to_d - _timedelta(days=30))
            if ma_30d_ago is not None:
                delta_30d_kg = round(current_avg_kg - ma_30d_ago, 2)

        stats = {
            "current_weight_kg": current_weight_kg,
            "current_avg_kg": current_avg_kg,
            "delta_7d_kg": delta_7d_kg,
            "delta_30d_kg": delta_30d_kg,
        }

        # Target block
        result = {
            "range": {"from": str(from_d), "to": str(to_d)},
            "actuals": actuals,
            "trend": trend,
            "stats": stats,
        }

        if include_target:
            active_target = (
                session.query(WeightTarget)
                .filter(WeightTarget.user_id == uid, WeightTarget.status == "active")
                .first()
            )
            target_block = None
            if active_target is not None:
                target_weight = float(active_target.target_weight_kg)
                target_date = (
                    active_target.target_date
                    if isinstance(active_target.target_date, _date)
                    else _date.fromisoformat(str(active_target.target_date))
                )
                proj_start_weight = current_weight_kg if current_weight_kg is not None else float(active_target.start_weight_kg)
                proj_start = today
                total_days = (target_date - proj_start).days

                if total_days <= 0:
                    projected_path = [{"date": str(target_date), "weight_kg": round(target_weight, 2)}]
                else:
                    projected_path = []
                    d = proj_start
                    while d <= target_date:
                        frac = (d - proj_start).days / total_days
                        w = proj_start_weight + (target_weight - proj_start_weight) * frac
                        projected_path.append({"date": str(d), "weight_kg": round(w, 2)})
                        d = _advance_one_month(d)
                    if projected_path[-1]["date"] != str(target_date):
                        projected_path.append({"date": str(target_date), "weight_kg": round(target_weight, 2)})

                target_block = {
                    "target_weight_kg": target_weight,
                    "target_date": str(target_date),
                    "projected_path": projected_path,
                }
            result["target"] = target_block

        return JSONResponse(result)


# ── Home weight-summary endpoint ──────────────────────────────────────────────

_WEIGHT_SUMMARY_EMPTY = {
    "current_weight": None,
    "avg_7d": None,
    "delta_week": None,
    "delta_month": None,
    "target": None,
    "ma30": [],
}


@app.get("/api/home/weight-summary")
def get_home_weight_summary(user: User = Depends(resolve_user)):
    uid = user.id
    today = _date.today()
    # today-36 covers 7-day MA windows for all 30 sparkline days and delta_month
    fetch_from = today - _timedelta(days=36)

    try:
        with Session(engine) as session:
            entries = (
                session.query(WeightEntry)
                .filter(
                    WeightEntry.user_id == uid,
                    WeightEntry.entry_date >= fetch_from,
                )
                .order_by(WeightEntry.entry_date.asc())
                .all()
            )

            active_target = (
                session.query(WeightTarget)
                .filter(
                    WeightTarget.user_id == uid,
                    WeightTarget.status == "active",
                )
                .first()
            )
    except sa_exc.OperationalError:
        return JSONResponse(_WEIGHT_SUMMARY_EMPTY)

    # Build date → [weights] map for moving-average computation
    date_weights: dict = {}
    for e in entries:
        d = e.entry_date if isinstance(e.entry_date, _date) else _date.fromisoformat(str(e.entry_date))
        date_weights.setdefault(d, []).append(float(e.weight_kg))

    def _ma(day: _date):
        """7-day moving average ending on day (inclusive window [day-6, day])."""
        vals = []
        for offset in range(7):
            di = day - _timedelta(days=6 - offset)
            if di in date_weights:
                vals.extend(date_weights[di])
        return round(sum(vals) / len(vals), 2) if vals else None

    # ma30: 30-day window of {date, value} items, nulls filtered out, oldest first
    ma30 = []
    for i in range(30):
        day = today - _timedelta(days=29 - i)
        v = _ma(day)
        if v is not None:
            ma30.append({"date": str(day), "value": v})

    # Current weight from most recent entry
    if entries:
        last = entries[-1]
        current_weight: Optional[float] = round(float(last.weight_kg), 2)
    else:
        current_weight = None

    avg_7d = _ma(today)

    delta_week = None
    if avg_7d is not None:
        ma_7d_ago = _ma(today - _timedelta(days=7))
        if ma_7d_ago is not None:
            delta_week = round(avg_7d - ma_7d_ago, 2)

    delta_month = None
    if avg_7d is not None:
        ma_30d_ago = _ma(today - _timedelta(days=30))
        if ma_30d_ago is not None:
            delta_month = round(avg_7d - ma_30d_ago, 2)

    target_info = None
    if active_target:
        status_label = _compute_status_label(active_target, avg_7d, today)
        target_w = float(active_target.target_weight_kg)
        start_w = float(active_target.start_weight_kg)
        direction = "down" if target_w < start_w else "up"
        total_kg = abs(start_w - target_w)
        if total_kg != 0:
            kg_changed = abs(start_w - (current_weight if current_weight is not None else start_w))
            progress_pct = round(min(max(kg_changed / total_kg * 100, 0), 100), 2)
        else:
            progress_pct = 100.0
        td = active_target.target_date if isinstance(active_target.target_date, _date) else _date.fromisoformat(str(active_target.target_date))
        target_info = {
            "direction": direction,
            "target_weight_kg": target_w,
            "target_date": str(td),
            "progress_pct": progress_pct,
            "status_label": status_label,
        }

    return JSONResponse({
        "current_weight": current_weight,
        "avg_7d": avg_7d,
        "delta_week": delta_week,
        "delta_month": delta_month,
        "target": target_info,
        "ma30": ma30,
    })


# ── Home recent-workouts endpoint ─────────────────────────────────────────────

@app.get("/api/home/recent-workouts")
def get_home_recent_workouts(
    user_id: str = Query(...),
    limit: int = Query(default=5, ge=1, le=10),
):
    try:
        uid = _uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="User not found")

    with Session(engine) as session:
        user = session.get(User, uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        rows = (
            session.query(Workout)
            .filter(Workout.user_id == uid)
            .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
            .limit(limit + 1)
            .all()
        )

    has_more = len(rows) > limit
    rows = rows[:limit]

    today = _date.today()

    def _rel(d):
        delta = (today - d).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Yesterday"
        if delta < 7:
            return f"{delta} days ago"
        return d.isoformat()

    def _to_dict(w):
        d = {}
        try:
            d["id"] = str(w.id)
        except Exception:
            pass
        try:
            d["workout_date"] = w.workout_date.isoformat()
        except Exception:
            pass
        try:
            d["workout_type"] = w.workout_type
        except Exception:
            pass
        try:
            d["name"] = w.name
        except Exception:
            pass
        try:
            if w.distance_km is not None:
                d["distance_km"] = float(w.distance_km)
        except Exception:
            pass
        try:
            if w.duration_seconds is not None:
                d["duration_seconds"] = int(w.duration_seconds)
        except Exception:
            pass
        try:
            if w.avg_hr is not None:
                d["avg_hr"] = int(w.avg_hr)
        except Exception:
            pass
        try:
            if w.tss is not None:
                d["tss"] = float(w.tss)
        except Exception:
            pass
        try:
            if w.source is not None:
                d["source"] = w.source
        except Exception:
            pass
        try:
            d["is_stryd_synced"] = w.stryd_activity_pk is not None
        except Exception:
            pass
        try:
            d["relative_date"] = _rel(w.workout_date)
        except Exception:
            pass
        return d

    return JSONResponse({
        "workouts": [_to_dict(w) for w in rows],
        "count": len(rows),
        "has_more": has_more,
    })


# ── Home personal-records endpoint ────────────────────────────────────────────

_PR_TRACK_META = {
    "half_marathon": {"name": "Half Marathon", "track_type": "time"},
    "10k": {"name": "10K", "track_type": "time"},
    "squat_1rm": {"name": "Squat 1RM", "track_type": "weight"},
}
_PR_DEFAULT_TRACKS = ["half_marathon", "10k", "squat_1rm"]


def _format_pr_time(seconds: float) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _format_pr_weight(kg: float) -> str:
    if kg == int(kg):
        return f"{int(kg)} kg"
    return f"{kg} kg"


def _pr_trend(records, track_type: str) -> str:
    if len(records) < 2:
        return "no_data"
    latest = float(records[0].value_numeric)
    previous = float(records[1].value_numeric)
    if previous == 0:
        return "no_data"
    diff_pct = abs(latest - previous) / previous
    if diff_pct <= 0.01:
        return "stable"
    if track_type == "time":
        return "improving" if latest < previous else "declining"
    return "improving" if latest > previous else "declining"


@app.get("/api/home/personal-records")
def get_home_personal_records(
    user_id: str = Query(...),
    tracks: str = Query(default=None),
):
    try:
        uid = _uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="User not found")

    track_list = [t.strip() for t in tracks.split(",")] if tracks else _PR_DEFAULT_TRACKS

    with Session(engine) as session:
        user = session.get(User, uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        try:
            all_records = (
                session.query(PersonalRecord)
                .filter(
                    PersonalRecord.user_id == uid,
                    PersonalRecord.track_key.in_(track_list),
                )
                .order_by(PersonalRecord.track_key, PersonalRecord.achieved_on.desc())
                .all()
            )
        except Exception:
            return JSONResponse({"tracks": []})

    grouped: dict = {}
    for r in all_records:
        grouped.setdefault(r.track_key, []).append(r)

    result = []
    for tk in track_list:
        meta = _PR_TRACK_META.get(tk, {})
        recs = grouped.get(tk, [])

        if not recs:
            result.append({
                "track_key": tk,
                "track_name": meta.get("name", tk),
                "track_type": meta.get("track_type", None),
                "current_value": None,
                "current_value_formatted": None,
                "achieved_on": None,
                "predicted_value": None,
                "predicted_value_formatted": None,
                "predicted_method": None,
                "trend": "no_data",
            })
            continue

        latest = recs[0]
        track_type = latest.track_type
        current_value = float(latest.value_numeric)
        formatted = _format_pr_time(current_value) if track_type == "time" else _format_pr_weight(current_value)

        result.append({
            "track_key": tk,
            "track_name": latest.track_name,
            "track_type": track_type,
            "current_value": current_value,
            "current_value_formatted": formatted,
            "achieved_on": latest.achieved_on.isoformat() if latest.achieved_on else None,
            "predicted_value": None,
            "predicted_value_formatted": None,
            "predicted_method": None,
            "trend": _pr_trend(recs, track_type),
        })

    return JSONResponse({"tracks": result})


# ── Home readiness endpoint ───────────────────────────────────────────────────


def _readiness_score_label(score: Optional[int]) -> str:
    """Score label thresholds: ≥80 Excellent, 60-79 Good, 40-59 OK, 20-39 Caution, <20 Recovery."""
    if score is None:
        return "No data"
    if score >= 80:
        return "Excellent"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "OK"
    if score >= 20:
        return "Caution"
    return "Recovery"


@app.get("/api/home/readiness")
def get_home_readiness(
    user_id: Optional[str] = Query(default=None),
    date: Optional[str] = Query(default=None),
):
    # Score formula: sleep_hours 30%, hrv 25%, rhr 20%, mood 15%, energy 10%
    # Per-factor: sleep/HRV/RHR compare vs 7d rolling avg; mood/energy: raw value × 20
    if user_id is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        uid = _uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="User not found")

    try:
        query_date = _date.fromisoformat(date) if date else _date.today()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format")

    baseline_end = query_date - _timedelta(days=1)
    baseline_start = query_date - _timedelta(days=7)

    with Session(engine) as session:
        user = session.get(User, uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        metrics = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date == query_date,
            )
            .first()
        )

        baseline_rows = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= baseline_start,
                DailyMetric.metric_date <= baseline_end,
            )
            .all()
        )

    def _avg(vals):
        non_null = [v for v in vals if v is not None]
        return round(sum(non_null) / len(non_null), 2) if non_null else None

    hrv_7d_avg = _avg([float(r.hrv) for r in baseline_rows if r.hrv is not None])
    rhr_7d_avg = _avg([float(r.resting_hr) for r in baseline_rows if r.resting_hr is not None])
    sleep_7d_avg_hours = _avg([float(r.sleep_hours) for r in baseline_rows if r.sleep_hours is not None])

    rolling_baseline = {
        "hrv_7d_avg": hrv_7d_avg,
        "rhr_7d_avg": rhr_7d_avg,
        "sleep_7d_avg_hours": sleep_7d_avg_hours,
    }

    if metrics is None:
        contributors = [
            {"factor": "sleep_hours", "value": None, "weight": 0.30, "impact": "neutral"},
            {"factor": "hrv", "value": None, "weight": 0.25, "impact": "neutral"},
            {"factor": "rhr", "value": None, "weight": 0.20, "impact": "neutral"},
            {"factor": "mood", "value": None, "weight": 0.15, "impact": "neutral"},
            {"factor": "energy", "value": None, "weight": 0.10, "impact": "neutral"},
        ]
        return JSONResponse({
            "date": query_date.isoformat(),
            "score": None,
            "score_label": "No data",
            "contributors": contributors,
            "rolling_baseline": rolling_baseline,
        })

    def _bscore(value, baseline, higher_is_better: bool) -> float:
        """Score 0-100; returns 50 when value equals baseline or baseline unavailable."""
        if value is None:
            return 50.0
        v = float(value)
        if baseline is None or baseline == 0:
            return 50.0
        b = float(baseline)
        delta_pct = (v - b) / b * 100.0
        raw = 50.0 + delta_pct if higher_is_better else 50.0 - delta_pct
        return min(100.0, max(0.0, raw))

    def _impact(factor_score: float) -> str:
        if factor_score > 50:
            return "positive"
        if factor_score < 50:
            return "negative"
        return "neutral"

    sleep_score = _bscore(metrics.sleep_hours, sleep_7d_avg_hours, higher_is_better=True)
    hrv_score = _bscore(metrics.hrv, hrv_7d_avg, higher_is_better=True)
    rhr_score = _bscore(metrics.resting_hr, rhr_7d_avg, higher_is_better=False)
    mood_score = float(metrics.mood) * 20.0 if metrics.mood is not None else 50.0
    energy_score = float(metrics.energy) * 20.0 if metrics.energy is not None else 50.0

    contributors = [
        {
            "factor": "sleep_hours",
            "value": float(metrics.sleep_hours) if metrics.sleep_hours is not None else None,
            "weight": 0.30,
            "impact": _impact(sleep_score),
        },
        {
            "factor": "hrv",
            "value": float(metrics.hrv) if metrics.hrv is not None else None,
            "weight": 0.25,
            "impact": _impact(hrv_score),
        },
        {
            "factor": "rhr",
            "value": float(metrics.resting_hr) if metrics.resting_hr is not None else None,
            "weight": 0.20,
            "impact": _impact(rhr_score),
        },
        {
            "factor": "mood",
            "value": float(metrics.mood) if metrics.mood is not None else None,
            "weight": 0.15,
            "impact": _impact(mood_score),
        },
        {
            "factor": "energy",
            "value": float(metrics.energy) if metrics.energy is not None else None,
            "weight": 0.10,
            "impact": _impact(energy_score),
        },
    ]

    total = (
        sleep_score * 0.30
        + hrv_score * 0.25
        + rhr_score * 0.20
        + mood_score * 0.15
        + energy_score * 0.10
    )
    score = int(round(min(100.0, max(0.0, total))))

    return JSONResponse({
        "date": query_date.isoformat(),
        "score": score,
        "score_label": _readiness_score_label(score),
        "contributors": contributors,
        "rolling_baseline": rolling_baseline,
    })


# ── Home weekly-summary endpoint ──────────────────────────────────────────────

_WK_TYPE_BUCKETS = ("run", "lift", "wod", "bike")


@app.get("/api/home/weekly-summary")
def get_home_weekly_summary(
    user_id: Optional[str] = Query(default=None),
    week_start: Optional[str] = Query(default=None),
):
    if user_id is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        uid = _uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="User not found")

    if week_start is None:
        from zoneinfo import ZoneInfo
        _bkk = ZoneInfo("Asia/Bangkok")
        today_bkk = _datetime.now(_bkk).date()
        ws = today_bkk - _timedelta(days=today_bkk.weekday())
    else:
        try:
            ws = _date.fromisoformat(week_start)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid week_start format")

    we = ws + _timedelta(days=6)
    prev_ws = ws - _timedelta(days=7)
    prev_we = ws - _timedelta(days=1)

    with Session(engine) as session:
        user = session.get(User, uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        all_workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= prev_ws,
                Workout.workout_date <= we,
            )
            .all()
        )

    current_week = [w for w in all_workouts if ws <= w.workout_date <= we]
    prev_week = [w for w in all_workouts if prev_ws <= w.workout_date <= prev_we]

    by_type = {k: 0 for k in _WK_TYPE_BUCKETS}
    for w in current_week:
        try:
            wt = (w.workout_type or "").lower()
            if wt in by_type:
                by_type[wt] += 1
        except Exception:
            pass

    def _safe_float(val):
        try:
            return float(val) if val is not None else None
        except Exception:
            return None

    def _safe_int(val):
        try:
            return int(val) if val is not None else None
        except Exception:
            return None

    def _sum_attr(workouts, attr, cast):
        try:
            vals = [cast(getattr(w, attr)) for w in workouts if getattr(w, attr, None) is not None]
            return sum(vals) if vals else None
        except Exception:
            return None

    distance_km = _sum_attr(current_week, "distance_km", _safe_float)
    if distance_km is not None:
        distance_km = round(distance_km, 3)

    dur_sec = _sum_attr(current_week, "duration_seconds", _safe_int)
    duration_minutes = round(dur_sec / 60.0, 1) if dur_sec is not None else None

    total_tss = _sum_attr(current_week, "tss", _safe_float)
    if total_tss is not None:
        total_tss = round(total_tss, 2)

    elevation_m = _sum_attr(current_week, "elevation_m", _safe_int)

    workout_dates_current = set(w.workout_date for w in current_week)
    rest_days = sum(
        1 for i in range(7)
        if (ws + _timedelta(days=i)) not in workout_dates_current
    )

    prev_distance = _sum_attr(prev_week, "distance_km", _safe_float) or 0.0
    prev_tss = _sum_attr(prev_week, "tss", _safe_float) or 0.0
    curr_distance_for_delta = distance_km if distance_km is not None else 0.0
    curr_tss_for_delta = total_tss if total_tss is not None else 0.0

    vs_prev_week = {
        "total_delta": len(current_week) - len(prev_week),
        "distance_km_delta": round(curr_distance_for_delta - prev_distance, 3),
        "tss_delta": round(curr_tss_for_delta - prev_tss, 2),
    }

    daily_load = []
    for i in range(7):
        day = ws + _timedelta(days=i)
        day_workouts = [w for w in current_week if w.workout_date == day]
        day_tss = _sum_attr(day_workouts, "tss", _safe_float)
        if day_tss is not None:
            day_tss = round(day_tss, 2)
        daily_load.append({
            "date": day.isoformat(),
            "tss": day_tss,
            "is_rest": day not in workout_dates_current,
        })

    return JSONResponse({
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "workouts": {
            "total": len(current_week),
            "by_type": by_type,
        },
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "total_tss": total_tss,
        "elevation_m": elevation_m,
        "rest_days": rest_days,
        "vs_prev_week": vs_prev_week,
        "daily_load": daily_load,
    })


# ── Habit endpoints ───────────────────────────────────────────────────────────

_VALID_TRACKING_TYPES = frozenset({
    "daily_checkmark", "weekly_count", "weekly_minutes", "weekly_quantity",
})
_VALID_AUTO_FILL_SOURCES = frozenset({
    "workout.zone2_minutes", "workout.run_count", "workout.lift_count",
    "workout.total_duration_minutes", "workout.distance_km",
})


def _habit_dict(h: Habit) -> dict:
    return {
        "id": str(h.id),
        "user_id": str(h.user_id),
        "name": h.name,
        "description": h.description,
        "tracking_type": h.tracking_type,
        "weekly_target": float(h.weekly_target) if h.weekly_target is not None else None,
        "unit": h.unit,
        "auto_fill_source": h.auto_fill_source,
        "icon": h.icon,
        "color": h.color,
        "sort_order": h.sort_order,
        "is_archived": h.is_archived,
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
    }


def _validate_habit_business_rules(
    tracking_type: Optional[str],
    weekly_target: Optional[float],
    auto_fill_source: Optional[str],
) -> None:
    if tracking_type is not None and tracking_type not in _VALID_TRACKING_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"tracking_type must be one of {sorted(_VALID_TRACKING_TYPES)}",
        )
    if weekly_target is not None and tracking_type is not None:
        if tracking_type == "daily_checkmark":
            if not (1 <= weekly_target <= 7):
                raise HTTPException(
                    status_code=422,
                    detail="weekly_target for daily_checkmark must be between 1 and 7",
                )
        elif tracking_type.startswith("weekly_"):
            if weekly_target <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="weekly_target for weekly_* types must be > 0",
                )
    if auto_fill_source is not None and auto_fill_source not in _VALID_AUTO_FILL_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"auto_fill_source must be one of {sorted(_VALID_AUTO_FILL_SOURCES)}",
        )


class HabitIn(BaseModel):
    name: str = Field(..., max_length=100)
    tracking_type: str
    description: Optional[str] = None
    weekly_target: Optional[float] = None
    unit: Optional[str] = None
    auto_fill_source: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class HabitPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    weekly_target: Optional[float] = None
    unit: Optional[str] = None
    auto_fill_source: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


class HabitReorderIn(BaseModel):
    sort_order: int


class HabitLogIn(BaseModel):
    habit_id: str
    user_id: Optional[str] = None
    logged_date: str  # YYYY-MM-DD


@app.get("/api/habits")
def get_habits(
    include_archived: bool = False,
    user: User = Depends(resolve_user),
):
    with Session(engine) as session:
        q = session.query(Habit).filter(Habit.user_id == user.id)
        if not include_archived:
            q = q.filter(Habit.is_archived.is_(False))
        rows = q.order_by(Habit.sort_order).all()
        return JSONResponse([_habit_dict(r) for r in rows])


@app.post("/api/habits", status_code=201)
def post_habit(body: HabitIn, user: User = Depends(resolve_user)):
    _validate_habit_business_rules(
        tracking_type=body.tracking_type,
        weekly_target=body.weekly_target,
        auto_fill_source=body.auto_fill_source,
    )
    from sqlalchemy import func as _sa_func
    with Session(engine) as session:
        max_order = (
            session.query(_sa_func.max(Habit.sort_order))
            .filter(Habit.user_id == user.id)
            .scalar()
        )
        habit = Habit(
            user_id=user.id,
            name=body.name.strip(),
            tracking_type=body.tracking_type,
            description=body.description,
            weekly_target=body.weekly_target,
            unit=body.unit,
            auto_fill_source=body.auto_fill_source,
            icon=body.icon,
            color=body.color,
            sort_order=(max_order or 0) + 1,
            is_archived=False,
        )
        session.add(habit)
        session.commit()
        session.refresh(habit)
        return JSONResponse(status_code=201, content=_habit_dict(habit))


@app.patch("/api/habits/{habit_id}")
async def patch_habit(habit_id: str, request: Request, user: User = Depends(resolve_user)):
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if "user_id" in raw or "tracking_type" in raw:
        raise HTTPException(status_code=422, detail="user_id and tracking_type cannot be updated")
    try:
        body = HabitPatch(**raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if body.auto_fill_source is not None:
        _validate_habit_business_rules(
            tracking_type=None, weekly_target=None, auto_fill_source=body.auto_fill_source
        )
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    with Session(engine) as session:
        habit = session.get(Habit, hid)
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        if habit.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        if body.name is not None:
            habit.name = body.name.strip()
        if body.description is not None:
            habit.description = body.description
        if body.weekly_target is not None:
            habit.weekly_target = body.weekly_target
        if body.unit is not None:
            habit.unit = body.unit
        if body.auto_fill_source is not None:
            habit.auto_fill_source = body.auto_fill_source
        if body.icon is not None:
            habit.icon = body.icon
        if body.color is not None:
            habit.color = body.color
        if body.sort_order is not None:
            habit.sort_order = body.sort_order
        habit.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(habit)
        return JSONResponse(_habit_dict(habit))


@app.delete("/api/habits/{habit_id}")
def delete_habit(
    habit_id: str,
    hard: bool = False,
    user: User = Depends(resolve_user),
):
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    with Session(engine) as session:
        habit = session.get(Habit, hid)
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        if habit.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        if hard:
            session.query(HabitLog).filter(HabitLog.habit_id == hid).delete(
                synchronize_session=False
            )
            session.delete(habit)
        else:
            habit.is_archived = True
            habit.updated_at = _datetime.now(_timezone.utc)
        session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/habits/{habit_id}/reorder")
def reorder_habit(
    habit_id: str,
    body: HabitReorderIn,
    user: User = Depends(resolve_user),
):
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    with Session(engine) as session:
        habit = session.get(Habit, hid)
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        if habit.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        habit.sort_order = body.sort_order
        habit.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(habit)
        return JSONResponse(_habit_dict(habit))


@app.get("/api/habits/logs")
def get_habit_logs(
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    user: User = Depends(resolve_user),
):
    try:
        from_d = _date.fromisoformat(from_date)
        to_d = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    with Session(engine) as session:
        rows = (
            session.query(HabitLog)
            .filter(
                HabitLog.user_id == user.id,
                HabitLog.logged_date >= from_d,
                HabitLog.logged_date <= to_d,
            )
            .all()
        )
        return JSONResponse([
            {
                "id": str(r.id),
                "habit_id": str(r.habit_id),
                "user_id": str(r.user_id),
                "logged_date": str(r.logged_date),
            }
            for r in rows
        ])


@app.post("/api/habits/logs", status_code=201)
def post_habit_log(body: HabitLogIn, user: User = Depends(resolve_user)):
    try:
        hid = _uuid.UUID(body.habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    with Session(engine) as session:
        habit = session.get(Habit, hid)
        if habit is None or habit.user_id != user.id:
            raise HTTPException(status_code=404, detail="Habit not found")
        log = HabitLog(habit_id=hid, user_id=user.id, logged_date=body.logged_date)
        session.add(log)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "Log already exists for this habit on this date"},
            )
        session.refresh(log)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(log.id),
                "habit_id": str(log.habit_id),
                "user_id": str(log.user_id),
                "logged_date": str(log.logged_date),
            },
        )


def _compute_habit_streak(session, hid, uid, window_dates, today):
    """Walk backwards from today (or yesterday if today is pending) to count the streak."""
    from datetime import timedelta
    check = today
    if check not in window_dates:
        yesterday = today - timedelta(days=1)
        if yesterday not in window_dates:
            return 0
        check = yesterday
    all_logs = (
        session.query(HabitLog.logged_date)
        .filter(HabitLog.habit_id == hid, HabitLog.user_id == uid)
        .all()
    )
    all_dates = {row.logged_date for row in all_logs}
    streak = 0
    while check in all_dates:
        streak += 1
        check = check - timedelta(days=1)
    return streak


@app.get("/api/habits/stats")
def get_habit_stats(
    habit_id: Optional[str] = None,
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(resolve_user),
):
    uid = user.id

    from datetime import timedelta
    today = _date.today()
    window_start = today - timedelta(days=days - 1)

    # List mode: return stats for all active habits when habit_id is omitted
    if habit_id is None:
        with Session(engine) as session:
            habits = (
                session.query(Habit)
                .filter(Habit.user_id == uid, Habit.archived_at.is_(None))
                .order_by(Habit.display_order, Habit.created_at)
                .all()
            )
            result = []
            for habit in habits:
                hid = habit.id
                window_logs = (
                    session.query(HabitLog.logged_date)
                    .filter(
                        HabitLog.habit_id == hid,
                        HabitLog.user_id == uid,
                        HabitLog.logged_date >= window_start,
                        HabitLog.logged_date <= today,
                    )
                    .all()
                )
                window_dates = {row.logged_date for row in window_logs}
                days_completed = len(window_dates)
                completion_rate = round(days_completed / days, 4)
                streak = _compute_habit_streak(session, hid, uid, window_dates, today)
                result.append({
                    "habit_id": str(hid),
                    "habit_name": habit.name,
                    "streak": streak,
                    "completion_rate": completion_rate,
                    "days_completed": days_completed,
                    "days_total": days,
                })
            return JSONResponse(result)

    # Single-habit mode (existing behaviour)
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")

    with Session(engine) as session:
        window_logs = (
            session.query(HabitLog.logged_date)
            .filter(
                HabitLog.habit_id == hid,
                HabitLog.user_id == uid,
                HabitLog.logged_date >= window_start,
                HabitLog.logged_date <= today,
            )
            .all()
        )
        window_dates = {row.logged_date for row in window_logs}
        days_completed = len(window_dates)
        completion_rate = round(days_completed / days, 4)

        streak = _compute_habit_streak(session, hid, uid, window_dates, today)

        return JSONResponse({
            "streak": streak,
            "completion_rate": completion_rate,
            "days_completed": days_completed,
            "days_total": days,
        })


@app.delete("/api/habits/logs/{log_id}", status_code=204)
def delete_habit_log(log_id: str, user: User = Depends(resolve_user)):
    try:
        lid = _uuid.UUID(log_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid log_id")
    with Session(engine) as session:
        log = session.get(HabitLog, lid)
        if log is None:
            raise HTTPException(status_code=404, detail="Log not found")
        if log.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        session.delete(log)
        session.commit()
    return Response(status_code=204)


@app.get("/api/stats/active-streak")
def get_active_streak(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    from datetime import timedelta
    from sqlalchemy import text as _sql_text
    today = _date.today()

    with Session(engine) as session:
        rows = session.execute(
            _sql_text("""
                SELECT DISTINCT d FROM (
                    SELECT recorded_date AS d FROM weight_entries WHERE user_id = :uid
                    UNION
                    SELECT logged_date AS d FROM habit_logs WHERE user_id = :uid
                    UNION
                    SELECT workout_date AS d FROM workouts WHERE user_id = :uid
                ) sub
                ORDER BY d
            """),
            {"uid": str(uid)},
        ).fetchall()

    if not rows:
        return JSONResponse({"current_streak": 0, "longest_streak": 0, "last_active_date": None})

    sorted_asc = [row[0] for row in rows]
    all_dates = set(sorted_asc)
    last_active = sorted_asc[-1]

    # Longest streak across all time
    longest = run = 1
    for i in range(1, len(sorted_asc)):
        if (sorted_asc[i] - sorted_asc[i - 1]).days == 1:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 1

    # Current streak (forgiving: if today has no entry, start from yesterday)
    check = today if today in all_dates else today - timedelta(days=1)
    current_streak = 0
    while check in all_dates:
        current_streak += 1
        check -= timedelta(days=1)

    return JSONResponse({
        "current_streak": current_streak,
        "longest_streak": longest,
        "last_active_date": str(last_active),
    })


# ── Page routes ───────────────────────────────────────────────────────────────
# Every page is served at a clean path (e.g. /home) AND its legacy .html path
# (/home.html), both backed by the same file. Add new pages here only.
_PAGES = {
    "home": "home.html",
    "weight": "weight.html",
    "habits": "habits.html",
    "users": "users.html",
    "calendar": "calendar.html",
    "log": "training-log.html",
    "training": "training.html",
    "trends": "trends.html",
    "settings": "settings.html",
}


def _make_page_handler(filename: str):
    def _serve_page():
        return FileResponse(str(_static_root / "frontend" / "pages" / filename))
    return _serve_page


for _clean, _file in _PAGES.items():
    _handler = _make_page_handler(_file)
    app.add_api_route("/" + _clean, _handler, include_in_schema=False)
    app.add_api_route("/" + _clean + ".html", _handler, include_in_schema=False)


def _serve_login():
    return FileResponse(str(_static_root / "frontend" / "pages" / "login.html"))

app.add_api_route("/login", _serve_login, include_in_schema=False)
app.add_api_route("/login.html", _serve_login, include_in_schema=False)


def _serve_weight_targets():
    return FileResponse(str(_static_root / "frontend" / "pages" / "weight-targets.html"))

app.add_api_route("/weight/targets", _serve_weight_targets, include_in_schema=False)


@app.get("/")
def index():
    # Bare domain → the home dashboard (clean URL).
    return RedirectResponse(url="/home")


@app.get("/api/calendar/month")
def get_calendar_month(
    year: int = Query(...),
    month: int = Query(...),
    user: User = Depends(resolve_user),
):
    """Return per-day calendar data for the given month.

    Response shape: a list of objects, one per calendar day in the month:
      {
        date: "YYYY-MM-DD",
        weight: float | null,
        habits_done: int,
        workouts: int,
        energy: int | null,        # 1–5
        sleep_quality: int | null  # 1–5
      }
    """
    from datetime import date as _date, timedelta
    import calendar as _cal

    uid = user.id

    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1–12")

    days_in_month = _cal.monthrange(year, month)[1]
    from_d = _date(year, month, 1)
    to_d = _date(year, month, days_in_month)

    with Session(engine) as session:
        # Weight entries
        weight_rows = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.recorded_date >= from_d,
                WeightEntry.recorded_date <= to_d,
            )
            .all()
        )
        weight_by_date = {str(w.recorded_date): float(w.weight_kg) for w in weight_rows}

        # Habit log counts per date
        log_rows = (
            session.query(HabitLog.logged_date)
            .filter(
                HabitLog.user_id == uid,
                HabitLog.logged_date >= from_d,
                HabitLog.logged_date <= to_d,
            )
            .all()
        )
        habits_by_date: dict = {}
        for (ld,) in log_rows:
            key = str(ld)
            habits_by_date[key] = habits_by_date.get(key, 0) + 1

        # Workout counts per date
        workout_rows = (
            session.query(Workout.workout_date)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
            )
            .all()
        )
        workouts_by_date: dict = {}
        for (wd,) in workout_rows:
            key = str(wd)
            workouts_by_date[key] = workouts_by_date.get(key, 0) + 1

        # Daily metrics (energy + sleep_quality)
        metric_rows = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= from_d,
                DailyMetric.metric_date <= to_d,
            )
            .all()
        )
        metrics_by_date: dict = {}
        for m in metric_rows:
            metrics_by_date[str(m.metric_date)] = {
                "energy": m.energy,
                "sleep_quality": m.sleep_quality,
            }

    days = []
    for day in range(1, days_in_month + 1):
        d = str(_date(year, month, day))
        m = metrics_by_date.get(d, {})
        days.append({
            "date": d,
            "weight": weight_by_date.get(d),
            "habits_done": habits_by_date.get(d, 0),
            "workouts": workouts_by_date.get(d, 0),
            "energy": m.get("energy"),
            "sleep_quality": m.get("sleep_quality"),
        })

    return JSONResponse(days)


# ── Workout endpoints ─────────────────────────────────────────────────────────

class ExerciseIn(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration: Optional[str] = None
    rpe: Optional[int] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_hr: Optional[int] = None


# Compound sources (e.g. 'strava,stryd') are supported so a single workout can carry data from multiple integrations.
_VALID_SOURCES = frozenset({"manual", "strava", "stryd", "strava,stryd", "stryd,strava"})


class WorkoutIn(BaseModel):
    user_id: Optional[str] = None
    name: str
    workout_date: str  # YYYY-MM-DD
    workout_type: str
    remarks: Optional[str] = None
    tss: Optional[float] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    elevation_m: Optional[int] = None
    zone2_minutes: Optional[int] = None
    source: Optional[str] = None
    strava_activity_url: Optional[str] = None
    exercises: list[ExerciseIn] = []


class WorkoutPatch(BaseModel):
    name: Optional[str] = None
    workout_date: Optional[str] = None
    workout_type: Optional[str] = None
    remarks: Optional[str] = None
    tss: Optional[float] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    elevation_m: Optional[int] = None
    zone2_minutes: Optional[int] = None
    source: Optional[str] = None
    strava_activity_url: Optional[str] = None


class ExercisePatchIn(BaseModel):
    name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration: Optional[str] = None
    rpe: Optional[int] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_hr: Optional[int] = None


class ExerciseReorderIn(BaseModel):
    ordered_ids: list[str]


def _validate_exercise(ex: ExerciseIn) -> None:
    name = ex.name.strip() if ex.name else ""
    if not name:
        raise HTTPException(status_code=422, detail="Exercise name is required")
    if ex.sets is not None and ex.sets <= 0:
        raise HTTPException(status_code=422, detail="sets must be > 0")
    if ex.rpe is not None and not (1 <= ex.rpe <= 10):
        raise HTTPException(status_code=422, detail="rpe must be between 1 and 10")
    if ex.distance_km is not None and ex.distance_km < 0:
        raise HTTPException(status_code=422, detail="distance_km must be >= 0")
    if ex.duration_seconds is not None and ex.duration_seconds < 0:
        raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
    if ex.avg_hr is not None and not (20 <= ex.avg_hr <= 250):
        raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")


def _exercise_dict(e: WorkoutExercise) -> dict:
    return {
        "id": str(e.id),
        "display_order": e.display_order,
        "name": e.name,
        "sets": e.sets,
        "reps": e.reps,
        "weight_kg": float(e.weight_kg) if e.weight_kg is not None else None,
        "duration": e.duration,
        "rpe": e.rpe,
        "distance_km": str(e.distance_km) if e.distance_km is not None else None,
        "duration_seconds": e.duration_seconds,
        "avg_hr": e.avg_hr,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _best_values_dict(w: Workout) -> dict:
    bv = compute_best_values(w)
    dist = bv["best_distance_km"]
    return {
        "best_distance_km": float(dist) if dist is not None else None,
        "best_duration_seconds": bv["best_duration_seconds"],
        "best_avg_hr": bv["best_avg_hr"],
        "best_avg_power_w": bv["best_avg_power_w"],
        "best_tss": float(bv["best_tss"]) if bv["best_tss"] is not None else None,
        "best_name": bv["best_name"],
    }


def _workout_dict(w: Workout, exercises: list) -> dict:
    strava_act = getattr(w, "strava_activity", None)
    return {
        "id": str(w.id),
        "user_id": str(w.user_id),
        "name": w.name,
        "workout_date": str(w.workout_date),
        "workout_type": w.workout_type,
        "remarks": w.remarks,
        "tss": w.tss,
        "tss_source": w.tss_source,
        "source": w.source,
        "strava_activity_pk": str(w.strava_activity_pk) if w.strava_activity_pk else None,
        "stryd_activity_pk": str(w.stryd_activity_pk) if w.stryd_activity_pk else None,
        "strava_activity_url": w.strava_activity_url,
        "distance_km": float(w.distance_km) if w.distance_km is not None else None,
        "duration_seconds": w.duration_seconds,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "elevation_m": w.elevation_m,
        "zone2_minutes": w.zone2_minutes,
        "avg_power_w": strava_act.avg_power_w if strava_act else None,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "exercises": [_exercise_dict(e) for e in exercises],
        **_best_values_dict(w),
    }


def _workout_list_dict(w: Workout, exercise_count: int) -> dict:
    return {
        "id": str(w.id),
        "workout_date": str(w.workout_date),
        "name": w.name,
        "workout_type": w.workout_type,
        "remarks": w.remarks,
        "tss": w.tss,
        "tss_source": w.tss_source,
        "strava_activity_url": w.strava_activity_url,
        "distance_km": float(w.distance_km) if w.distance_km is not None else None,
        "duration_seconds": w.duration_seconds,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "elevation_m": w.elevation_m,
        "zone2_minutes": w.zone2_minutes,
        "exercise_count": exercise_count,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        **_best_values_dict(w),
    }


@app.get("/api/workouts")
def get_workouts(
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    user: User = Depends(resolve_user),
):
    uid = user.id
    try:
        from_d = _date.fromisoformat(from_date)
        to_d = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    with Session(engine) as session:
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
            )
            .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
            .all()
        )
        result = []
        for w in workouts:
            count = (
                session.query(WorkoutExercise)
                .filter(WorkoutExercise.workout_id == w.id)
                .count()
            )
            result.append(_workout_list_dict(w, count))
        return JSONResponse(result)


@app.get("/api/workouts/{workout_id}")
def get_workout(workout_id: str, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        exercises = (
            session.query(WorkoutExercise)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order)
            .all()
        )
        return JSONResponse(_workout_dict(workout, exercises))


@app.post("/api/workouts", status_code=201)
def post_workout(body: WorkoutIn, user: User = Depends(resolve_user)):
    uid = user.id
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workout name is required")
    if not body.workout_type or not body.workout_type.strip():
        raise HTTPException(status_code=422, detail="workout_type is required")
    try:
        workout_date = _date.fromisoformat(body.workout_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid workout_date; use YYYY-MM-DD")
    if workout_date > _date.today():
        raise HTTPException(status_code=422, detail="workout_date cannot be in the future")
    if body.tss is not None and body.tss < 0:
        raise HTTPException(status_code=422, detail="tss must be >= 0")
    if body.distance_km is not None and body.distance_km < 0:
        raise HTTPException(status_code=422, detail="distance_km must be >= 0")
    if body.duration_seconds is not None and body.duration_seconds < 0:
        raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
    if body.avg_hr is not None and not (20 <= body.avg_hr <= 250):
        raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")
    if body.max_hr is not None and not (20 <= body.max_hr <= 250):
        raise HTTPException(status_code=422, detail="max_hr must be between 20 and 250")
    if body.zone2_minutes is not None and not (0 <= body.zone2_minutes <= 600):
        raise HTTPException(status_code=422, detail="zone2_minutes must be between 0 and 600")
    if body.source is not None and body.source not in _VALID_SOURCES:
        raise HTTPException(status_code=422, detail="source must be one of: " + ", ".join(sorted(_VALID_SOURCES)))
    for ex in body.exercises:
        _validate_exercise(ex)
    with Session(engine) as session:
        workout = Workout(
            user_id=uid,
            name=name,
            workout_date=workout_date,
            workout_type=body.workout_type.strip(),
            remarks=body.remarks.strip() if body.remarks else None,
            tss=body.tss,
            tss_source='manual' if body.tss is not None else None,
            distance_km=body.distance_km,
            duration_seconds=body.duration_seconds,
            avg_hr=body.avg_hr,
            max_hr=body.max_hr,
            elevation_m=body.elevation_m,
            zone2_minutes=body.zone2_minutes,
            source=body.source,
            strava_activity_url=body.strava_activity_url,
        )
        session.add(workout)
        session.flush()
        exercises = []
        for i, ex in enumerate(body.exercises):
            e = WorkoutExercise(
                workout_id=workout.id,
                display_order=i,
                name=ex.name.strip(),
                sets=ex.sets,
                reps=ex.reps,
                weight_kg=ex.weight_kg,
                duration=ex.duration,
                rpe=ex.rpe,
                distance_km=ex.distance_km,
                duration_seconds=ex.duration_seconds,
                avg_hr=ex.avg_hr,
            )
            session.add(e)
            exercises.append(e)
        session.commit()
        session.refresh(workout)
        for e in exercises:
            session.refresh(e)
        try:
            daily_update(str(uid), workout_date)
        except Exception as _exc:
            _logging.getLogger(__name__).warning(
                "daily_update failed for user %s date %s: %s", uid, workout_date, _exc, exc_info=True
            )
        return JSONResponse(status_code=201, content=_workout_dict(workout, exercises))


@app.patch("/api/workouts/{workout_id}")
def patch_workout(workout_id: str, body: WorkoutPatch, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="Workout name is required")
            workout.name = name
        if body.workout_date is not None:
            try:
                d = _date.fromisoformat(body.workout_date)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid workout_date; use YYYY-MM-DD")
            if d > _date.today():
                raise HTTPException(status_code=422, detail="workout_date cannot be in the future")
            workout.workout_date = d
        if body.workout_type is not None:
            t = body.workout_type.strip()
            if not t:
                raise HTTPException(status_code=422, detail="workout_type is required")
            workout.workout_type = t
        if body.remarks is not None:
            workout.remarks = body.remarks.strip() or None
        if 'tss' in body.model_fields_set:
            if body.tss is None:
                workout.tss = None
                workout.tss_source = None
            else:
                if body.tss < 0:
                    raise HTTPException(status_code=422, detail="tss must be >= 0")
                workout.tss = body.tss
                workout.tss_source = 'manual'
        if 'distance_km' in body.model_fields_set:
            if body.distance_km is not None and body.distance_km < 0:
                raise HTTPException(status_code=422, detail="distance_km must be >= 0")
            workout.distance_km = body.distance_km
        if 'duration_seconds' in body.model_fields_set:
            if body.duration_seconds is not None and body.duration_seconds < 0:
                raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
            workout.duration_seconds = body.duration_seconds
        if 'avg_hr' in body.model_fields_set:
            if body.avg_hr is not None and not (20 <= body.avg_hr <= 250):
                raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")
            workout.avg_hr = body.avg_hr
        if 'max_hr' in body.model_fields_set:
            if body.max_hr is not None and not (20 <= body.max_hr <= 250):
                raise HTTPException(status_code=422, detail="max_hr must be between 20 and 250")
            workout.max_hr = body.max_hr
        if 'elevation_m' in body.model_fields_set:
            workout.elevation_m = body.elevation_m
        if 'zone2_minutes' in body.model_fields_set:
            if body.zone2_minutes is not None and not (0 <= body.zone2_minutes <= 600):
                raise HTTPException(status_code=422, detail="zone2_minutes must be between 0 and 600")
            workout.zone2_minutes = body.zone2_minutes
        if 'source' in body.model_fields_set:
            if body.source is not None and body.source not in _VALID_SOURCES:
                raise HTTPException(status_code=422, detail="source must be one of: " + ", ".join(sorted(_VALID_SOURCES)))
            workout.source = body.source
        if 'strava_activity_url' in body.model_fields_set:
            workout.strava_activity_url = body.strava_activity_url
        session.commit()
        exercises = (
            session.query(WorkoutExercise)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order)
            .all()
        )
        session.refresh(workout)
        try:
            daily_update(str(workout.user_id), workout.workout_date)
        except Exception as _exc:
            _logging.getLogger(__name__).warning(
                "daily_update failed for user %s date %s: %s", workout.user_id, workout.workout_date, _exc, exc_info=True
            )
        return JSONResponse(_workout_dict(workout, exercises))


@app.delete("/api/workouts/{workout_id}", status_code=204)
def delete_workout(workout_id: str, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        session.delete(workout)
        session.commit()
    return Response(status_code=204)


@app.post("/api/workouts/{workout_id}/exercises/reorder", status_code=200)
def reorder_exercises(workout_id: str, body: ExerciseReorderIn, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        for order, eid_str in enumerate(body.ordered_ids):
            try:
                eid = _uuid.UUID(eid_str)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid exercise id: {eid_str}")
            ex = session.get(WorkoutExercise, eid)
            if ex is None or ex.workout_id != wid:
                raise HTTPException(status_code=404, detail=f"Exercise {eid_str} not found in this workout")
            ex.display_order = order
        session.commit()
        exercises = (
            session.query(WorkoutExercise)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order)
            .all()
        )
        session.refresh(workout)
        return JSONResponse(_workout_dict(workout, exercises))


@app.post("/api/workouts/{workout_id}/exercises", status_code=201)
def append_exercise(workout_id: str, body: ExerciseIn, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    _validate_exercise(body)
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        max_order = (
            session.query(WorkoutExercise.display_order)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order is not None else 0
        ex = WorkoutExercise(
            workout_id=wid,
            display_order=next_order,
            name=body.name.strip(),
            sets=body.sets,
            reps=body.reps,
            weight_kg=body.weight_kg,
            duration=body.duration,
            rpe=body.rpe,
            distance_km=body.distance_km,
            duration_seconds=body.duration_seconds,
            avg_hr=body.avg_hr,
        )
        session.add(ex)
        session.commit()
        session.refresh(ex)
        return JSONResponse(status_code=201, content=_exercise_dict(ex))


@app.patch("/api/workouts/{workout_id}/exercises/{exercise_id}")
def patch_exercise(workout_id: str, exercise_id: str, body: ExercisePatchIn, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
        eid = _uuid.UUID(exercise_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id or exercise_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        ex = session.get(WorkoutExercise, eid)
        if ex is None or ex.workout_id != wid:
            raise HTTPException(status_code=404, detail="Exercise not found in this workout")
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="Exercise name is required")
            ex.name = name
        if body.sets is not None:
            if body.sets <= 0:
                raise HTTPException(status_code=422, detail="sets must be > 0")
            ex.sets = body.sets
        if body.reps is not None:
            ex.reps = body.reps
        if body.weight_kg is not None:
            ex.weight_kg = body.weight_kg
        if body.duration is not None:
            ex.duration = body.duration
        if body.rpe is not None:
            if not (1 <= body.rpe <= 10):
                raise HTTPException(status_code=422, detail="rpe must be between 1 and 10")
            ex.rpe = body.rpe
        if body.distance_km is not None:
            if body.distance_km < 0:
                raise HTTPException(status_code=422, detail="distance_km must be >= 0")
            ex.distance_km = body.distance_km
        if body.duration_seconds is not None:
            if body.duration_seconds < 0:
                raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
            ex.duration_seconds = body.duration_seconds
        if body.avg_hr is not None:
            if not (20 <= body.avg_hr <= 250):
                raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")
            ex.avg_hr = body.avg_hr
        session.commit()
        session.refresh(ex)
        return JSONResponse(_exercise_dict(ex))


@app.delete("/api/workouts/{workout_id}/exercises/{exercise_id}", status_code=204)
def delete_exercise(workout_id: str, exercise_id: str, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
        eid = _uuid.UUID(exercise_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id or exercise_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        ex = session.get(WorkoutExercise, eid)
        if ex is None or ex.workout_id != wid:
            raise HTTPException(status_code=404, detail="Exercise not found in this workout")
        session.delete(ex)
        session.commit()
    return Response(status_code=204)


# ── Workout template endpoints ────────────────────────────────────────────────

class WorkoutTemplateIn(BaseModel):
    name: str
    exercises: list


def _template_dict(t: WorkoutTemplate) -> dict:
    return {
        "id": str(t.id),
        "user_id": str(t.user_id),
        "name": t.name,
        "exercises": t.exercises,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@app.get("/api/workout-templates")
def get_workout_templates(user: User = Depends(resolve_user)):
    with Session(engine) as session:
        templates = (
            session.query(WorkoutTemplate)
            .filter(WorkoutTemplate.user_id == user.id)
            .order_by(WorkoutTemplate.created_at.desc())
            .all()
        )
        return JSONResponse([_template_dict(t) for t in templates])


@app.post("/api/workout-templates", status_code=201)
def post_workout_template(body: WorkoutTemplateIn, user: User = Depends(resolve_user)):
    name = body.name.strip() if body.name else ""
    if not name:
        raise HTTPException(status_code=422, detail="Template name is required")
    if not body.exercises:
        raise HTTPException(status_code=422, detail="Template must have at least one exercise")
    exercises = [
        {
            "name": str(ex.get("name", "")).strip(),
            "sets": ex.get("sets"),
            "reps": ex.get("reps"),
            "weight_kg": ex.get("weight_kg"),
            "duration": ex.get("duration"),
            "rpe": ex.get("rpe"),
        }
        for ex in body.exercises
        if isinstance(ex, dict) and str(ex.get("name", "")).strip()
    ]
    if not exercises:
        raise HTTPException(status_code=422, detail="Template must have at least one named exercise")
    with Session(engine) as session:
        tmpl = WorkoutTemplate(user_id=user.id, name=name, exercises=exercises)
        session.add(tmpl)
        session.commit()
        session.refresh(tmpl)
        return JSONResponse(status_code=201, content=_template_dict(tmpl))


# ── Workout splits endpoints ──────────────────────────────────────────────────

class SplitIn(BaseModel):
    split_index: int
    distance_km: float
    duration_seconds: int
    avg_hr: Optional[int] = None


class SplitsIn(BaseModel):
    splits: list[SplitIn]


def _split_dict(s: WorkoutSplit) -> dict:
    return {
        "id": str(s.id),
        "workout_id": str(s.workout_id),
        "split_index": s.split_index,
        "distance_km": str(s.distance_km),
        "duration_seconds": s.duration_seconds,
        "avg_hr": s.avg_hr,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@app.get("/api/workouts/{workout_id}/splits")
def get_splits(workout_id: str, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        splits = (
            session.query(WorkoutSplit)
            .filter(WorkoutSplit.workout_id == wid)
            .order_by(WorkoutSplit.split_index)
            .all()
        )
        return JSONResponse([_split_dict(s) for s in splits])


@app.post("/api/workouts/{workout_id}/splits", status_code=201)
def replace_splits(workout_id: str, body: SplitsIn, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    for s in body.splits:
        if s.distance_km < 0:
            raise HTTPException(status_code=422, detail="distance_km must be >= 0")
        if s.duration_seconds < 0:
            raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
        if s.avg_hr is not None and not (20 <= s.avg_hr <= 250):
            raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        session.query(WorkoutSplit).filter(WorkoutSplit.workout_id == wid).delete()
        new_splits = []
        for s in body.splits:
            split = WorkoutSplit(
                workout_id=wid,
                split_index=s.split_index,
                distance_km=s.distance_km,
                duration_seconds=s.duration_seconds,
                avg_hr=s.avg_hr,
            )
            session.add(split)
            new_splits.append(split)
        session.commit()
        for split in new_splits:
            session.refresh(split)
        new_splits.sort(key=lambda x: x.split_index)
        return JSONResponse(status_code=201, content=[_split_dict(s) for s in new_splits])


@app.delete("/api/workouts/{workout_id}/splits", status_code=204)
def delete_splits(workout_id: str, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        session.query(WorkoutSplit).filter(WorkoutSplit.workout_id == wid).delete()
        session.commit()
    return Response(status_code=204)


# ── Daily metrics endpoints ────────────────────────────────────────────────────

class DailyMetricIn(BaseModel):
    user_id: Optional[str] = None
    metric_date: str  # YYYY-MM-DD
    resting_hr: Optional[int] = None
    hrv: Optional[int] = None
    sleep_hours: Optional[float] = None
    sleep_quality: Optional[int] = None
    energy: Optional[int] = None
    mood: Optional[int] = None
    notes: Optional[str] = None


class DailyMetricBody(BaseModel):
    resting_hr: Optional[int] = None
    hrv: Optional[int] = None
    sleep_hours: Optional[float] = None
    sleep_quality: Optional[int] = None
    energy: Optional[int] = None
    mood: Optional[int] = None
    notes: Optional[str] = None


def _validate_metric_fields(
    resting_hr: Optional[int] = None,
    hrv: Optional[int] = None,
    sleep_hours: Optional[float] = None,
    sleep_quality: Optional[int] = None,
    energy: Optional[int] = None,
    mood: Optional[int] = None,
) -> None:
    if resting_hr is not None and not (20 <= resting_hr <= 200):
        raise HTTPException(status_code=422, detail={"field": "resting_hr", "error": "resting_hr must be between 20 and 200"})
    if hrv is not None and not (0 <= hrv <= 300):
        raise HTTPException(status_code=422, detail={"field": "hrv", "error": "hrv must be between 0 and 300"})
    if sleep_hours is not None and not (0 <= sleep_hours <= 24):
        raise HTTPException(status_code=422, detail={"field": "sleep_hours", "error": "sleep_hours must be between 0 and 24"})
    if sleep_quality is not None and not (1 <= sleep_quality <= 5):
        raise HTTPException(status_code=422, detail={"field": "sleep_quality", "error": "sleep_quality must be between 1 and 5"})
    if energy is not None and not (1 <= energy <= 5):
        raise HTTPException(status_code=422, detail={"field": "energy", "error": "energy must be between 1 and 5"})
    if mood is not None and not (1 <= mood <= 5):
        raise HTTPException(status_code=422, detail={"field": "mood", "error": "mood must be between 1 and 5"})


def _daily_metric_dict(m: DailyMetric) -> dict:
    return {
        "id": str(m.id),
        "user_id": str(m.user_id),
        "metric_date": str(m.metric_date),
        "resting_hr": m.resting_hr,
        "hrv": m.hrv,
        "sleep_hours": float(m.sleep_hours) if m.sleep_hours is not None else None,
        "sleep_quality": m.sleep_quality,
        "energy": m.energy,
        "mood": m.mood,
        "notes": m.notes,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@app.get("/api/daily-metrics")
def list_daily_metrics(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    user: User = Depends(resolve_user),
):
    from datetime import timedelta
    today = _date.today()
    if from_date is None and to_date is None:
        from_d = today - timedelta(days=29)
        to_d = today
    else:
        try:
            from_d = _date.fromisoformat(from_date) if from_date else today - timedelta(days=29)
            to_d = _date.fromisoformat(to_date) if to_date else today
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    with Session(engine) as session:
        rows = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == user.id,
                DailyMetric.metric_date >= from_d,
                DailyMetric.metric_date <= to_d,
            )
            .order_by(DailyMetric.metric_date.desc())
            .all()
        )
        return JSONResponse([_daily_metric_dict(r) for r in rows])


@app.get("/api/daily-metrics/{uid}/{metric_date}")
def get_daily_metric(uid: str, metric_date: str, user: User = Depends(resolve_user)):
    try:
        uid = _uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if uid != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        md = _date.fromisoformat(metric_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid metric_date; use YYYY-MM-DD")
    with Session(engine) as session:
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == md)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Daily metric not found")
        return JSONResponse(_daily_metric_dict(row))


@app.post("/api/daily-metrics", status_code=201)
def create_daily_metric(body: DailyMetricIn, user: User = Depends(resolve_user)):
    try:
        md = _date.fromisoformat(body.metric_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid metric_date; use YYYY-MM-DD")
    if md > _date.today():
        raise HTTPException(status_code=422, detail="metric_date cannot be in the future")
    _validate_metric_fields(
        resting_hr=body.resting_hr,
        hrv=body.hrv,
        sleep_hours=body.sleep_hours,
        sleep_quality=body.sleep_quality,
        energy=body.energy,
        mood=body.mood,
    )
    with Session(engine) as session:
        row = DailyMetric(
            user_id=user.id,
            metric_date=md,
            resting_hr=body.resting_hr,
            hrv=body.hrv,
            sleep_hours=body.sleep_hours,
            sleep_quality=body.sleep_quality,
            energy=body.energy,
            mood=body.mood,
            notes=body.notes,
        )
        session.add(row)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "A daily metric already exists for this user on this date; use PATCH to update it"},
            )
        session.refresh(row)
        return JSONResponse(status_code=201, content=_daily_metric_dict(row))


@app.patch("/api/daily-metrics/{uid}/{metric_date}")
def patch_daily_metric(uid: str, metric_date: str, body: DailyMetricBody, user: User = Depends(resolve_user)):
    try:
        uid = _uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if uid != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        md = _date.fromisoformat(metric_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid metric_date; use YYYY-MM-DD")
    if md > _date.today():
        raise HTTPException(status_code=422, detail="metric_date cannot be in the future")
    _validate_metric_fields(
        resting_hr=body.resting_hr,
        hrv=body.hrv,
        sleep_hours=body.sleep_hours,
        sleep_quality=body.sleep_quality,
        energy=body.energy,
        mood=body.mood,
    )
    with Session(engine) as session:
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == md)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Daily metric not found; use POST to create it")
        if body.resting_hr is not None:
            row.resting_hr = body.resting_hr
        if body.hrv is not None:
            row.hrv = body.hrv
        if body.sleep_hours is not None:
            row.sleep_hours = body.sleep_hours
        if body.sleep_quality is not None:
            row.sleep_quality = body.sleep_quality
        if body.energy is not None:
            row.energy = body.energy
        if body.mood is not None:
            row.mood = body.mood
        if body.notes is not None:
            row.notes = body.notes
        session.commit()
        session.refresh(row)
        return JSONResponse(_daily_metric_dict(row))


@app.put("/api/daily-metrics/{uid}/{metric_date}")
def upsert_daily_metric(uid: str, metric_date: str, body: DailyMetricBody, user: User = Depends(resolve_user)):
    try:
        uid = _uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if uid != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        md = _date.fromisoformat(metric_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid metric_date; use YYYY-MM-DD")
    if md > _date.today():
        raise HTTPException(status_code=422, detail="metric_date cannot be in the future")
    _validate_metric_fields(
        resting_hr=body.resting_hr,
        hrv=body.hrv,
        sleep_hours=body.sleep_hours,
        sleep_quality=body.sleep_quality,
        energy=body.energy,
        mood=body.mood,
    )
    with Session(engine) as session:
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == md)
            .first()
        )
        if row is None:
            row = DailyMetric(
                user_id=uid,
                metric_date=md,
                resting_hr=body.resting_hr,
                hrv=body.hrv,
                sleep_hours=body.sleep_hours,
                sleep_quality=body.sleep_quality,
                energy=body.energy,
                mood=body.mood,
                notes=body.notes,
            )
            session.add(row)
        else:
            row.resting_hr = body.resting_hr
            row.hrv = body.hrv
            row.sleep_hours = body.sleep_hours
            row.sleep_quality = body.sleep_quality
            row.energy = body.energy
            row.mood = body.mood
            row.notes = body.notes
        session.commit()
        session.refresh(row)
        return JSONResponse(_daily_metric_dict(row))


@app.get("/api/daily-metrics/trend")
def get_daily_metrics_trend(
    days: int = Query(default=7, ge=1, le=90),
    user: User = Depends(resolve_user),
):
    from datetime import timedelta
    uid = user.id

    today = _date.today()
    window_start = today - timedelta(days=days - 1)

    with Session(engine) as session:
        rows = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= window_start,
                DailyMetric.metric_date <= today,
            )
            .all()
        )
        by_date = {str(r.metric_date): r for r in rows}

        result = []
        for i in range(days):
            d = window_start + timedelta(days=i)
            d_str = str(d)
            r = by_date.get(d_str)
            result.append({
                "date": d_str,
                "sleep_hours": float(r.sleep_hours) if r and r.sleep_hours is not None else None,
                "energy": r.energy if r else None,
                "mood": r.mood if r else None,
            })

        return JSONResponse(result)


@app.delete("/api/daily-metrics/{uid}/{metric_date}", status_code=204)
def delete_daily_metric(uid: str, metric_date: str, user: User = Depends(resolve_user)):
    try:
        uid = _uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if uid != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        md = _date.fromisoformat(metric_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid metric_date; use YYYY-MM-DD")
    with Session(engine) as session:
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == md)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Daily metric not found")
        session.delete(row)
        session.commit()
    return Response(status_code=204)


# ── Exports ────────────────────────────────────────────────────────────────────

@app.get("/api/exports/daily-metrics")
def export_daily_metrics_csv(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    user: User = Depends(resolve_user),
):
    uid = user.id

    from_d: Optional[_date] = None
    to_d: Optional[_date] = None
    if from_date is not None:
        try:
            from_d = _date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'from' date")
    if to_date is not None:
        try:
            to_d = _date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'to' date")
    if from_d is not None and to_d is not None and from_d > to_d:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")

    with Session(engine) as session:
        q = session.query(DailyMetric, WeightEntry).outerjoin(
            WeightEntry,
            (WeightEntry.user_id == DailyMetric.user_id)
            & (WeightEntry.recorded_date == DailyMetric.metric_date),
        ).filter(DailyMetric.user_id == uid)
        if from_d is not None:
            q = q.filter(DailyMetric.metric_date >= from_d)
        if to_d is not None:
            q = q.filter(DailyMetric.metric_date <= to_d)
        rows = q.order_by(DailyMetric.metric_date.asc()).all()

    buf = _io.StringIO()
    writer = _csv.writer(buf, quoting=_csv.QUOTE_MINIMAL)
    writer.writerow(["metric_date", "rhr", "hrv", "sleep_hours", "energy", "mood", "weight_kg", "notes"])
    for m, w in rows:
        writer.writerow([
            str(m.metric_date),
            m.resting_hr if m.resting_hr is not None else "",
            m.hrv if m.hrv is not None else "",
            float(m.sleep_hours) if m.sleep_hours is not None else "",
            m.energy if m.energy is not None else "",
            m.mood if m.mood is not None else "",
            float(w.weight_kg) if w is not None and w.weight_kg is not None else "",
            m.notes if m.notes is not None else "",
        ])

    if from_d is not None and to_d is not None:
        filename = f"daily-metrics-{from_d}-to-{to_d}.csv"
    else:
        filename = "daily-metrics-all.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/exports/workouts")
def export_workouts_csv(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    types: Optional[str] = Query(default=None),
    user: User = Depends(resolve_user),
):
    uid = user.id

    from_d: Optional[_date] = None
    to_d: Optional[_date] = None
    if from_date is not None:
        try:
            from_d = _date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'from' date")
    if to_date is not None:
        try:
            to_d = _date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'to' date")
    if from_d is not None and to_d is not None and from_d > to_d:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")

    type_filter = [t.strip() for t in types.split(",")] if types else None

    with Session(engine) as session:
        q = session.query(Workout).filter(Workout.user_id == uid)
        if from_d is not None:
            q = q.filter(Workout.workout_date >= from_d)
        if to_d is not None:
            q = q.filter(Workout.workout_date <= to_d)
        if type_filter:
            q = q.filter(Workout.workout_type.in_(type_filter))
        rows = q.order_by(Workout.workout_date.asc()).all()

    _desired_cols = ["workout_date", "workout_type", "name", "distance_km", "duration_seconds", "avg_hr", "tss", "source", "remarks"]
    _model_col_keys = {c.key for c in Workout.__table__.columns}
    headers = [c for c in _desired_cols if c in _model_col_keys]

    buf = _io.StringIO()
    writer = _csv.writer(buf, quoting=_csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for w in rows:
        row = []
        for col in headers:
            val = getattr(w, col)
            if val is None:
                row.append("")
            elif col == "workout_date":
                row.append(str(val))
            else:
                row.append(val)
        writer.writerow(row)

    if from_d is not None and to_d is not None:
        filename = f"workouts-{from_d}-to-{to_d}.csv"
    else:
        filename = "workouts-all.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/exports/weight-entries")
def export_weight_entries_csv(
    user_id: str = Query(...),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    from_d: Optional[_date] = None
    to_d: Optional[_date] = None
    if from_date is not None:
        try:
            from_d = _date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'from' date")
    if to_date is not None:
        try:
            to_d = _date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'to' date")
    if from_d is not None and to_d is not None and from_d > to_d:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")

    from sqlalchemy import nullslast
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        q = session.query(WeightEntry).filter(WeightEntry.user_id == uid)
        if from_d is not None:
            q = q.filter(WeightEntry.entry_date >= from_d)
        if to_d is not None:
            q = q.filter(WeightEntry.entry_date <= to_d)
        rows = q.order_by(
            WeightEntry.entry_date.asc(),
            nullslast(WeightEntry.entry_time.asc()),
        ).all()

    buf = _io.StringIO()
    writer = _csv.writer(buf, quoting=_csv.QUOTE_MINIMAL)
    writer.writerow(["entry_date", "entry_time", "weight_kg", "notes", "source"])
    for r in rows:
        writer.writerow([
            str(r.entry_date),
            str(r.entry_time) if r.entry_time is not None else "",
            float(r.weight_kg),
            r.notes if r.notes is not None else "",
            r.source if r.source is not None else "",
        ])

    if from_d is not None and to_d is not None:
        filename = f"weight-entries-{from_d}-to-{to_d}.csv"
    else:
        filename = "weight-entries-all.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/exports/weight-targets")
def export_weight_targets_csv(
    user_id: str = Query(...),
    status: Optional[str] = Query(default=None),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        q = session.query(WeightTarget).filter(WeightTarget.user_id == uid)
        if status is not None:
            q = q.filter(WeightTarget.status == status)
        rows = q.order_by(WeightTarget.start_date.asc()).all()

    buf = _io.StringIO()
    writer = _csv.writer(buf, quoting=_csv.QUOTE_MINIMAL)
    writer.writerow([
        "start_date", "target_date", "ended_at", "status",
        "start_weight_kg", "target_weight_kg", "end_weight_kg",
        "achieved_pct", "duration_days", "notes",
    ])
    for t in rows:
        start_date = t.start_date if isinstance(t.start_date, _date) else _date.fromisoformat(str(t.start_date))
        end_weight = float(t.end_weight_kg) if t.end_weight_kg is not None else None
        total_kg = float(t.start_weight_kg) - float(t.target_weight_kg)
        if end_weight is not None and total_kg != 0:
            achieved_kg = float(t.start_weight_kg) - end_weight
            achieved_pct = round(min(achieved_kg / total_kg * 100, 100), 2)
        else:
            achieved_pct = None
        if t.ended_at:
            ended_date = t.ended_at.date() if hasattr(t.ended_at, "date") else t.ended_at
            duration_days = (ended_date - start_date).days
            ended_at_str = t.ended_at.isoformat()
        else:
            duration_days = None
            ended_at_str = ""
        writer.writerow([
            str(t.start_date),
            str(t.target_date),
            ended_at_str,
            t.status,
            float(t.start_weight_kg),
            float(t.target_weight_kg),
            end_weight if end_weight is not None else "",
            achieved_pct if achieved_pct is not None else "",
            duration_days if duration_days is not None else "",
            t.notes if t.notes is not None else "",
        ])

    filename = f"weight-targets-{status}.csv" if status else "weight-targets-all.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Trends summary endpoint ────────────────────────────────────────────────────

def _compute_readiness(hrv, resting_hr, sleep_hours, sleep_quality, energy, mood):
    """0-100 readiness score computed from available daily metric fields."""
    components = []
    if hrv is not None:
        # HRV: typical 20-100 ms → map to 0-100
        components.append(min(100.0, max(0.0, (float(hrv) - 20.0) / 80.0 * 100.0)))
    if resting_hr is not None:
        # RHR: lower is better; 40 bpm → 100, 90 bpm → 0
        components.append(max(0.0, min(100.0, (90.0 - float(resting_hr)) * 2.0)))
    if sleep_hours is not None:
        # sleep: 4 h → 0, 9 h → 100
        components.append(max(0.0, min(100.0, (float(sleep_hours) - 4.0) / 5.0 * 100.0)))
    if sleep_quality is not None:
        components.append((float(sleep_quality) - 1.0) / 4.0 * 100.0)
    if energy is not None:
        components.append((float(energy) - 1.0) / 4.0 * 100.0)
    if mood is not None:
        components.append((float(mood) - 1.0) / 4.0 * 100.0)
    if not components:
        return None
    return round(sum(components) / len(components))


def _agg_stats(values):
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None, None, None
    return round(sum(non_null) / len(non_null), 1), min(non_null), max(non_null)


def _delta_int(curr, prev):
    if curr is None or prev is None:
        return None
    diff = round(curr - prev)
    return f"+{diff}" if diff >= 0 else str(diff)


def _delta_hours(curr, prev):
    if curr is None or prev is None:
        return None
    diff = curr - prev
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.1f}h"


def _delta_decimal(curr, prev, places=1):
    if curr is None or prev is None:
        return None
    diff = curr - prev
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.{places}f}"


def _delta_pct(curr, prev):
    if curr is None or prev is None or prev == 0:
        return None
    pct = round((curr - prev) / prev * 100)
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


@app.get("/trends/summary")
def get_trends_summary(
    range_preset: Optional[str] = Query(default=None, alias="range"),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    user: User = Depends(resolve_user),
):
    from datetime import timedelta

    uid = user.id

    today = _date.today()

    if from_date and to_date:
        try:
            from_d = _date.fromisoformat(from_date)
            to_d = _date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
        if from_d > to_d:
            raise HTTPException(status_code=400, detail="from must be before to")
    elif range_preset:
        if range_preset not in ("7d", "30d", "90d"):
            raise HTTPException(status_code=400, detail="range must be 7d, 30d, or 90d")
        n = int(range_preset[:-1])
        to_d = today
        from_d = today - timedelta(days=n - 1)
    else:
        to_d = today
        from_d = today - timedelta(days=29)

    days_count = (to_d - from_d).days + 1
    prev_to_d = from_d - timedelta(days=1)
    prev_from_d = prev_to_d - timedelta(days=days_count - 1)

    with Session(engine) as session:
        metrics = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= from_d,
                DailyMetric.metric_date <= to_d,
            )
            .all()
        )
        by_date = {str(m.metric_date): m for m in metrics}

        prev_metrics = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= prev_from_d,
                DailyMetric.metric_date <= prev_to_d,
            )
            .all()
        )
        prev_by_date = {str(m.metric_date): m for m in prev_metrics}

        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
                Workout.tss.isnot(None),
            )
            .all()
        )
        tss_by_date: dict = {}
        for w in workouts:
            d = str(w.workout_date)
            tss_by_date[d] = tss_by_date.get(d, 0.0) + (w.tss or 0.0)

        prev_workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= prev_from_d,
                Workout.workout_date <= prev_to_d,
                Workout.tss.isnot(None),
            )
            .all()
        )
        prev_tss_by_date: dict = {}
        for w in prev_workouts:
            d = str(w.workout_date)
            prev_tss_by_date[d] = prev_tss_by_date.get(d, 0.0) + (w.tss or 0.0)

        baseline_from_d = to_d - timedelta(days=29)
        baseline_metrics = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= baseline_from_d,
                DailyMetric.metric_date <= to_d,
            )
            .all()
        )

    baseline_hrv_vals = [float(m.hrv) for m in baseline_metrics if m.hrv is not None]
    baseline_rhr_vals = [float(m.resting_hr) for m in baseline_metrics if m.resting_hr is not None]

    def _baseline_stats(vals):
        if not vals:
            return None, None
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        return round(mean, 1), round(sd, 1)

    hrv_baseline_mean, hrv_baseline_sd = _baseline_stats(baseline_hrv_vals)
    rhr_baseline_mean, rhr_baseline_sd = _baseline_stats(baseline_rhr_vals)
    hrv_is_approx = len(baseline_hrv_vals) < 30
    rhr_is_approx = len(baseline_rhr_vals) < 30

    def _date_range(start, end):
        dates = []
        cur = start
        while cur <= end:
            dates.append(str(cur))
            cur += timedelta(days=1)
        return dates

    all_dates = _date_range(from_d, to_d)
    prev_dates = _date_range(prev_from_d, prev_to_d)

    readiness_series, hrv_series, rhr_series, sleep_series, energy_series, mood_series, tss_series = [], [], [], [], [], [], []

    for d in all_dates:
        m = by_date.get(d)
        sh = float(m.sleep_hours) if m and m.sleep_hours is not None else None
        readiness_series.append({"date": d, "score": _compute_readiness(
            m.hrv if m else None, m.resting_hr if m else None, sh,
            m.sleep_quality if m else None, m.energy if m else None, m.mood if m else None,
        )})
        hrv_series.append({"date": d, "value": m.hrv if m else None})
        rhr_series.append({"date": d, "value": m.resting_hr if m else None})
        sleep_series.append({"date": d, "hours": sh, "quality": m.sleep_quality if m else None})
        energy_series.append({"date": d, "value": m.energy if m else None})
        mood_series.append({"date": d, "value": m.mood if m else None})
        tss_val = tss_by_date.get(d)
        tss_series.append({"date": d, "value": round(tss_val, 1) if tss_val is not None else None})

    r_avg, r_min, r_max = _agg_stats([s["score"] for s in readiness_series])
    hrv_avg, hrv_min, hrv_max = _agg_stats([s["value"] for s in hrv_series])
    rhr_avg, rhr_min, rhr_max = _agg_stats([s["value"] for s in rhr_series])
    sleep_avg, sleep_min, sleep_max = _agg_stats([s["hours"] for s in sleep_series])
    energy_avg, energy_min, energy_max = _agg_stats([s["value"] for s in energy_series])
    mood_avg, mood_min, mood_max = _agg_stats([s["value"] for s in mood_series])
    tss_vals = [s["value"] for s in tss_series if s["value"] is not None]
    tss_avg = round(sum(tss_vals) / len(tss_vals), 1) if tss_vals else None
    tss_total = round(sum(tss_vals), 1) if tss_vals else None

    def _prev_metric_avg(field):
        vals = [float(getattr(m, field)) for d in prev_dates if (m := prev_by_date.get(d)) and getattr(m, field) is not None]
        return sum(vals) / len(vals) if vals else None

    def _prev_readiness_avg():
        vals = []
        for d in prev_dates:
            m = prev_by_date.get(d)
            if not m:
                continue
            sh = float(m.sleep_hours) if m.sleep_hours is not None else None
            r = _compute_readiness(m.hrv, m.resting_hr, sh, m.sleep_quality, m.energy, m.mood)
            if r is not None:
                vals.append(r)
        return sum(vals) / len(vals) if vals else None

    prev_tss_vals = [prev_tss_by_date[d] for d in prev_dates if d in prev_tss_by_date]
    prev_tss_avg = sum(prev_tss_vals) / len(prev_tss_vals) if prev_tss_vals else None

    prev_r_avg = _prev_readiness_avg()

    return JSONResponse({
        "range": {"from": str(from_d), "to": str(to_d), "days": days_count},
        "readiness": {"series": readiness_series, "avg": r_avg, "min": r_min, "max": r_max},
        "hrv": {"series": hrv_series, "avg": hrv_avg, "min": hrv_min, "max": hrv_max,
                "baseline_mean": hrv_baseline_mean, "baseline_sd": hrv_baseline_sd, "is_approximate": hrv_is_approx},
        "rhr": {"series": rhr_series, "avg": rhr_avg, "min": rhr_min, "max": rhr_max,
                "baseline_mean": rhr_baseline_mean, "baseline_sd": rhr_baseline_sd, "is_approximate": rhr_is_approx},
        "sleep": {"series": sleep_series, "avg_hours": sleep_avg, "min_hours": sleep_min, "max_hours": sleep_max},
        "energy": {"series": energy_series, "avg": energy_avg, "min": energy_min, "max": energy_max},
        "mood": {"series": mood_series, "avg": mood_avg, "min": mood_min, "max": mood_max},
        "tss": {"series": tss_series, "avg": tss_avg, "total": tss_total},
        "deltas": {
            "readiness": _delta_int(r_avg, prev_r_avg),
            "hrv": _delta_int(hrv_avg, _prev_metric_avg("hrv")),
            "rhr": _delta_int(rhr_avg, _prev_metric_avg("resting_hr")),
            "sleep": _delta_hours(sleep_avg, _prev_metric_avg("sleep_hours")),
            "energy": _delta_decimal(energy_avg, _prev_metric_avg("energy")),
            "mood": _delta_decimal(mood_avg, _prev_metric_avg("mood")),
            "tss": _delta_pct(tss_avg, prev_tss_avg),
        },
    })


# ── Readiness compute endpoint ────────────────────────────────────────────────

@app.post("/api/readiness/compute", status_code=200)
def compute_readiness_score(
    date: Optional[str] = Query(default=None),
    user: User = Depends(resolve_user),
):
    """
    Trigger readiness computation for a user on a given date (defaults to today).
    Idempotent: existing rows are upserted with freshly computed values.
    """
    uid = user.id
    target_date = _date.today()
    if date is not None:
        try:
            target_date = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")

    from services.readiness.job import compute_and_store
    row = compute_and_store(str(uid), target_date)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No daily_metrics row found for this user on this date",
        )
    return JSONResponse(row)


# ── Readiness GET endpoints ───────────────────────────────────────────────────

@app.get("/api/readiness/today")
def get_readiness_today(user: User = Depends(resolve_user)):
    """
    Return today's readiness record for a user.

    Response shape:
      { date, score, missing_data: { hrv, rhr, sleep, energy },
        hrv_contribution, rhr_contribution, sleep_contribution, energy_contribution }

    Returns 404 when no readiness row exists for today (card falls back to mock data).
    """
    uid = user.id

    today = _date.today()
    from sqlalchemy import text as _text
    with Session(engine) as session:
        row = session.execute(
            _text(
                "SELECT dr.date, dr.score, dr.components, "
                "       dm.hrv, dm.resting_hr, dm.sleep_quality, dm.energy "
                "FROM daily_readiness dr "
                "LEFT JOIN daily_metrics dm ON dm.id = dr.daily_metric_id "
                "WHERE dr.user_id = :uid AND dr.date = :d"
            ),
            {"uid": str(uid), "d": str(today)},
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="No readiness record for today")

    comp = row.components or {}
    return JSONResponse({
        "date": str(row.date),
        "score": float(row.score),
        "hrv_contribution": comp.get("hrv_contribution"),
        "rhr_contribution": comp.get("rhr_contribution"),
        "sleep_contribution": comp.get("sleep_contribution"),
        "energy_contribution": comp.get("energy_contribution"),
        "missing_data": {
            "hrv": row.hrv is None,
            "rhr": row.resting_hr is None,
            "sleep": row.sleep_quality is None,
            "energy": row.energy is None,
        },
    })


@app.get("/api/readiness")
def get_readiness_range(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    user: User = Depends(resolve_user),
):
    """
    Return daily readiness scores for a date range (one entry per day, null if missing).

    Response: list of { date, score } or null per day in [from, to].
    """
    uid = user.id

    try:
        d_from = _date.fromisoformat(from_date)
        d_to = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")

    if d_from > d_to:
        raise HTTPException(status_code=400, detail="from must be <= to")

    from sqlalchemy import text as _text
    with Session(engine) as session:
        rows = session.execute(
            _text(
                "SELECT date, score FROM daily_readiness "
                "WHERE user_id = :uid AND date >= :from_d AND date <= :to_d "
                "ORDER BY date"
            ),
            {"uid": str(uid), "from_d": str(d_from), "to_d": str(d_to)},
        ).fetchall()

    by_date = {str(r.date): float(r.score) for r in rows}

    result = []
    d = d_from
    from datetime import timedelta
    while d <= d_to:
        ds = str(d)
        if ds in by_date:
            result.append({"date": ds, "score": by_date[ds]})
        else:
            result.append(None)
        d += timedelta(days=1)

    return JSONResponse(result)


# ── Training Log endpoint ─────────────────────────────────────────────────────

def _week_key_and_bounds(date_obj):
    from datetime import timedelta
    dow = date_obj.weekday()  # 0=Mon
    mon = date_obj - timedelta(days=dow)
    sun = mon + timedelta(days=6)
    return str(mon), str(sun)


def _week_label(mon_key: str) -> str:
    from datetime import date as _d2, timedelta
    today = _d2.today()
    this_mon = today - timedelta(days=today.weekday())
    mon = _d2.fromisoformat(mon_key)
    if mon == this_mon:
        return "This week"
    sun = mon + timedelta(days=6)
    return mon.strftime("%b %-d") + "–" + str(sun.day)


def _metric_has_data(m: DailyMetric) -> bool:
    return any(
        v is not None
        for v in (m.energy, m.mood, m.resting_hr, m.hrv, m.sleep_hours, m.sleep_quality, m.notes)
    )


def _pace(workout_type: str, duration_seconds, distance_km) -> float | None:
    """Return seconds-per-km pace for run/bike workouts; None otherwise."""
    if workout_type not in ("run", "bike"):
        return None
    if duration_seconds is None or distance_km is None or float(distance_km) == 0:
        return None
    return round(duration_seconds / float(distance_km), 2)


@app.get("/api/training-log")
def get_training_log(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    types: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    include_rest: bool = Query(default=False),
    user: User = Depends(resolve_user),
):
    from datetime import timedelta
    today = _date.today()

    uid = user.id

    from_d = today - timedelta(days=29) if from_date is None else None
    if from_date is not None:
        try:
            from_d = _date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from date; use YYYY-MM-DD")

    to_d = today if to_date is None else None
    if to_date is not None:
        try:
            to_d = _date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to date; use YYYY-MM-DD")

    with Session(engine) as session:
        from sqlalchemy import or_, func as _func
        q = session.query(Workout).filter(
            Workout.workout_date >= from_d,
            Workout.workout_date <= to_d,
            Workout.user_id == uid,
        )
        if types and types != "all":
            type_list = [t.strip().lower() for t in types.split(",") if t.strip()]
            q = q.filter(_func.lower(Workout.workout_type).in_(type_list))
        if search:
            like = f"%{search}%"
            q = q.filter(or_(Workout.name.ilike(like), Workout.remarks.ilike(like)))
        workouts = q.order_by(Workout.workout_date.desc(), Workout.created_at.desc()).all()

        workout_dates = {str(w.workout_date) for w in workouts}

        rest_entries: list = []
        if include_rest and (not types or types == "all") and not search:
            mq = session.query(DailyMetric).filter(
                DailyMetric.metric_date >= from_d,
                DailyMetric.metric_date <= to_d,
                DailyMetric.user_id == uid,
            )
            metrics = mq.all()
            for m in metrics:
                if str(m.metric_date) not in workout_dates and _metric_has_data(m):
                    rest_entries.append({
                        "date": str(m.metric_date),
                        "type": "rest",
                        "sleep_hours": float(m.sleep_hours) if m.sleep_hours is not None else None,
                        "energy": m.energy,
                        "mood": m.mood,
                        "resting_hr": m.resting_hr,
                        "metrics": {
                            "energy": m.energy,
                            "mood": m.mood,
                            "sleep_quality": m.sleep_quality,
                            "sleep_hours": float(m.sleep_hours) if m.sleep_hours is not None else None,
                            "resting_hr": m.resting_hr,
                            "hrv": m.hrv,
                            "notes": m.notes,
                        },
                    })

        total_workout_days = (
            session.query(Workout.workout_date)
            .filter(Workout.user_id == uid)
            .distinct()
            .count()
        )
        today_snap = None
        if total_workout_days >= 7:
            today_snap = session.query(TrainingLoadSnapshot).filter(
                TrainingLoadSnapshot.user_id == uid,
                TrainingLoadSnapshot.snapshot_date == today,
            ).first()

    workout_entries = [
        {
            "date": str(w.workout_date),
            "type": w.workout_type,
            "id": str(w.id),
            "title": w.name,
            "duration_seconds": w.duration_seconds,
            "duration_minutes": round(w.duration_seconds / 60, 2) if w.duration_seconds is not None else None,
            "distance_km": float(w.distance_km) if w.distance_km is not None else None,
            "avg_hr": w.avg_hr,
            "elevation_m": w.elevation_m,
            "average_pace_seconds_per_km": _pace(w.workout_type, w.duration_seconds, w.distance_km),
            "tss": float(w.tss) if w.tss is not None else None,
            "source": w.source or w.tss_source or "manual",
            "is_stryd_synced": w.stryd_activity_pk is not None,
            "notes": w.remarks or "",
            "weight_context": w.remarks,
        }
        for w in workouts
    ]

    all_entries = workout_entries + rest_entries
    all_entries.sort(key=lambda e: e["date"], reverse=True)

    weeks_map: dict = {}
    week_order: list = []

    for entry in all_entries:
        d_obj = _date.fromisoformat(entry["date"])
        mon_key, sun_key = _week_key_and_bounds(d_obj)
        if mon_key not in weeks_map:
            weeks_map[mon_key] = {
                "week_start": mon_key,
                "week_end": sun_key,
                "label": _week_label(mon_key),
                "entries": [],
                "workouts": [],
            }
            week_order.append(mon_key)
        weeks_map[mon_key]["entries"].append(entry)
        if entry["type"] != "rest":
            weeks_map[mon_key]["workouts"].append(entry)

    week_order.sort(reverse=True)

    weeks = []
    for key in week_order:
        wk = weeks_map[key]
        ws = wk["workouts"]
        weeks.append({
            "week_start": wk["week_start"],
            "week_end": wk["week_end"],
            "label": wk["label"],
            "entries": wk["entries"],
            "workouts": ws,
            "summary": {
                "workout_count": len(ws),
                "total_distance_km": sum((w.get("distance_km") or 0) for w in ws),
                "total_tss": sum((w.get("tss") or 0) for w in ws),
                "total_time_minutes": sum((w.get("duration_minutes") or 0) for w in ws),
            },
        })

    load_context = None
    if total_workout_days >= 7:
        if today_snap is not None:
            lc_ctl = round(today_snap.ctl, 1)
            lc_atl = round(today_snap.atl, 1)
            lc_tsb = round(today_snap.tsb, 1)
        else:
            _load = current_load(str(uid), as_of=today)
            lc_ctl = round(_load["ctl"], 1)
            lc_atl = round(_load["atl"], 1)
            lc_tsb = round(_load["tsb"], 1)
        load_context = {
            "ctl": lc_ctl,
            "atl": lc_atl,
            "tsb": lc_tsb,
            "interpretation": _load_interpretation(lc_ctl, lc_atl, lc_tsb),
            "as_of": today.isoformat(),
        }

    return JSONResponse({"weeks": weeks, "load_context": load_context})


# ── Personal records endpoints ────────────────────────────────────────────────

VALID_TRACK_TYPES = {"time", "weight"}

CANONICAL_TRACKS = [
    {"track_key": "half_marathon", "track_name": "Half Marathon", "track_type": "time", "category": "running"},
    {"track_key": "10k", "track_name": "10K", "track_type": "time", "category": "running"},
    {"track_key": "5k", "track_name": "5K", "track_type": "time", "category": "running"},
    {"track_key": "marathon", "track_name": "Marathon", "track_type": "time", "category": "running"},
    {"track_key": "squat_1rm", "track_name": "Squat 1RM", "track_type": "weight", "category": "strength"},
    {"track_key": "deadlift_1rm", "track_name": "Deadlift 1RM", "track_type": "weight", "category": "strength"},
    {"track_key": "bench_1rm", "track_name": "Bench Press 1RM", "track_type": "weight", "category": "strength"},
    {"track_key": "ohp_1rm", "track_name": "Overhead Press 1RM", "track_type": "weight", "category": "strength"},
]
_CANONICAL_TRACK_MAP = {t["track_key"]: t for t in CANONICAL_TRACKS}


def _format_time_seconds(seconds: float) -> str:
    total = int(abs(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _improvement_time(current_seconds: float, prev_seconds: float) -> dict:
    delta = current_seconds - prev_seconds  # positive = slower, negative = faster
    sign = "+" if delta >= 0 else "−"
    return {"seconds": delta, "formatted": f"{sign}{_format_time_seconds(delta)}"}


def _improvement_weight(current_kg: float, prev_kg: float) -> dict:
    delta = current_kg - prev_kg
    sign = "+" if delta >= 0 else "−"
    abs_delta = abs(delta)
    formatted_val = int(abs_delta) if abs_delta == int(abs_delta) else abs_delta
    return {"kg": delta, "formatted": f"{sign}{formatted_val} kg"}


def _format_value(value: float, track_type: str) -> str:
    if track_type == "time":
        return _format_time_seconds(value)
    abs_v = abs(value)
    formatted_val = int(abs_v) if abs_v == int(abs_v) else abs_v
    return f"{formatted_val} kg"


class PersonalRecordIn(BaseModel):
    user_id: str
    track_key: str
    track_name: str
    track_type: str
    value_numeric: float
    achieved_on: str  # YYYY-MM-DD
    source: Optional[str] = None


class PersonalRecordPatch(BaseModel):
    track_key: Optional[str] = None
    track_name: Optional[str] = None
    track_type: Optional[str] = None
    value_numeric: Optional[float] = None
    achieved_on: Optional[str] = None
    source: Optional[str] = None


def _pr_dict(pr: PersonalRecord) -> dict:
    return {
        "id": str(pr.id),
        "user_id": str(pr.user_id),
        "track_key": pr.track_key,
        "track_name": pr.track_name,
        "track_type": pr.track_type,
        "value_numeric": float(pr.value_numeric),
        "achieved_on": str(pr.achieved_on),
        "source": pr.source,
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
    }


@app.get("/api/personal-records")
def list_personal_records(user: User = Depends(resolve_user)):
    with Session(engine) as session:
        rows = (
            session.query(PersonalRecord)
            .filter(PersonalRecord.user_id == user.id)
            .order_by(PersonalRecord.achieved_on.desc())
            .all()
        )
        return JSONResponse([_pr_dict(r) for r in rows])


@app.post("/api/personal-records", status_code=201)
def create_personal_record(body: PersonalRecordIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if body.track_type not in VALID_TRACK_TYPES:
        raise HTTPException(status_code=422, detail="track_type must be 'time' or 'weight'")
    if body.value_numeric <= 0:
        raise HTTPException(status_code=422, detail="value_numeric must be > 0")
    try:
        achieved = _date.fromisoformat(body.achieved_on)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid achieved_on; use YYYY-MM-DD")
    if achieved > _date.today():
        raise HTTPException(status_code=422, detail="achieved_on cannot be in the future")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        pr = PersonalRecord(
            user_id=uid,
            track_key=body.track_key.strip(),
            track_name=body.track_name.strip(),
            track_type=body.track_type,
            value_numeric=body.value_numeric,
            achieved_on=achieved,
            source=body.source,
        )
        session.add(pr)
        session.commit()
        session.refresh(pr)
        return JSONResponse(status_code=201, content=_pr_dict(pr))


@app.patch("/api/personal-records/{record_id}")
def patch_personal_record(record_id: str, body: PersonalRecordPatch):
    try:
        rid = _uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid record_id")
    with Session(engine) as session:
        pr = session.get(PersonalRecord, rid)
        if pr is None:
            raise HTTPException(status_code=404, detail="Personal record not found")
        if body.track_type is not None:
            if body.track_type not in VALID_TRACK_TYPES:
                raise HTTPException(status_code=422, detail="track_type must be 'time' or 'weight'")
            pr.track_type = body.track_type
        if body.value_numeric is not None:
            if body.value_numeric <= 0:
                raise HTTPException(status_code=422, detail="value_numeric must be > 0")
            pr.value_numeric = body.value_numeric
        if body.achieved_on is not None:
            try:
                achieved = _date.fromisoformat(body.achieved_on)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid achieved_on; use YYYY-MM-DD")
            if achieved > _date.today():
                raise HTTPException(status_code=422, detail="achieved_on cannot be in the future")
            pr.achieved_on = achieved
        if body.track_key is not None:
            pr.track_key = body.track_key.strip()
        if body.track_name is not None:
            pr.track_name = body.track_name.strip()
        if "source" in body.model_fields_set:
            pr.source = body.source
        from sqlalchemy.sql import func as _func
        pr.updated_at = _func.now()
        session.commit()
        session.refresh(pr)
        return JSONResponse(_pr_dict(pr))


@app.delete("/api/personal-records/{record_id}", status_code=204)
def delete_personal_record(record_id: str):
    try:
        rid = _uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid record_id")
    with Session(engine) as session:
        pr = session.get(PersonalRecord, rid)
        if pr is None:
            raise HTTPException(status_code=404, detail="Personal record not found")
        session.delete(pr)
        session.commit()
    return Response(status_code=204)


# ── Personal Records — Tracks / History / Bulk (issue #359) ──────────────────

@app.get("/api/personal-records/tracks")
def list_personal_record_tracks():
    return JSONResponse({"tracks": CANONICAL_TRACKS})


class _BulkRecordItem(BaseModel):
    track_key: str
    value_numeric: float
    achieved_on: str  # YYYY-MM-DD
    source: Optional[str] = None


class _BulkInsertIn(BaseModel):
    user_id: str
    records: list[_BulkRecordItem]


@app.get("/api/personal-records/history")
def personal_record_history(user_id: str, track_key: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid user_id")
    with Session(engine) as session:
        rows = (
            session.query(PersonalRecord)
            .filter(
                PersonalRecord.user_id == uid,
                PersonalRecord.track_key == track_key,
            )
            .order_by(PersonalRecord.achieved_on.desc())
            .all()
        )
        if not rows:
            return JSONResponse({"track_key": track_key, "history": []})

        track_type = rows[0].track_type

        history = []
        for i, pr in enumerate(rows):
            if i == 0:
                improvement = None
            else:
                prev = rows[i - 1]  # newer record (DESC order)
                cur_val = float(pr.value_numeric)
                prev_val = float(prev.value_numeric)
                if track_type == "time":
                    improvement = _improvement_time(cur_val, prev_val)
                else:
                    improvement = _improvement_weight(cur_val, prev_val)

            history.append({
                "id": str(pr.id),
                "value_numeric": float(pr.value_numeric),
                "value_formatted": _format_value(float(pr.value_numeric), track_type),
                "achieved_on": str(pr.achieved_on),
                "source": pr.source,
                "improvement_from_prev": improvement,
            })

        return JSONResponse({"track_key": track_key, "history": history})


@app.post("/api/personal-records/bulk", status_code=201)
def bulk_create_personal_records(body: _BulkInsertIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid user_id")
    if not body.records:
        raise HTTPException(status_code=422, detail="records must contain at least 1 item")

    errors = []
    validated = []
    for idx, item in enumerate(body.records):
        rec_errors = []
        if item.value_numeric <= 0:
            rec_errors.append("value_numeric must be > 0")
        try:
            achieved = _date.fromisoformat(item.achieved_on)
        except ValueError:
            rec_errors.append("Invalid achieved_on; use YYYY-MM-DD")
            achieved = None
        if achieved and achieved > _date.today():
            rec_errors.append("achieved_on cannot be in the future")
        if not item.track_key or not item.track_key.strip():
            rec_errors.append("track_key is required")
        if rec_errors:
            errors.append({"index": idx, "track_key": item.track_key, "errors": rec_errors})
        else:
            track_info = _CANONICAL_TRACK_MAP.get(item.track_key.strip())
            track_type = track_info["track_type"] if track_info else "weight"
            track_name = track_info["track_name"] if track_info else item.track_key.strip()
            validated.append((item, achieved, track_type, track_name))

    if errors:
        raise HTTPException(status_code=422, detail={"message": "Validation failed", "errors": errors})

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        created_ids = []
        for item, achieved, track_type, track_name in validated:
            pr = PersonalRecord(
                user_id=uid,
                track_key=item.track_key.strip(),
                track_name=track_name,
                track_type=track_type,
                value_numeric=item.value_numeric,
                achieved_on=achieved,
                source=item.source,
            )
            session.add(pr)
            session.flush()
            created_ids.append(str(pr.id))
        session.commit()

    return JSONResponse(status_code=201, content={"created": len(created_ids), "ids": created_ids})


# ── Strava OAuth ──────────────────────────────────────────────────────────────

_VALID_STRAVA_SCOPES = {"read", "activity:read", "activity:read_all"}
_STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
_STATE_TOKEN_MAX_AGE = 600  # 10 minutes


def _make_strava_state_token(user_id: str, secret: str) -> str:
    """Return a signed state token encoding {user_id, ts, nonce}."""
    payload = {"user_id": user_id, "ts": int(time.time()), "nonce": _secrets.token_hex(8)}
    payload_b64 = _base64.urlsafe_b64encode(_json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = _hmac.new(secret.encode(), payload_b64.encode(), _hashlib.sha256).digest()
    sig_b64 = _base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{payload_b64}.{sig_b64}"


def _verify_strava_state_token(token: str, secret: str, max_age: int = _STATE_TOKEN_MAX_AGE) -> dict:
    """Decode and verify a state token. Raises ValueError on bad signature or expiry."""
    parts = token.split(".", 1)
    if len(parts) != 2:
        raise ValueError("Invalid token format")
    payload_b64, sig_b64 = parts
    expected_sig = _hmac.new(secret.encode(), payload_b64.encode(), _hashlib.sha256).digest()
    expected_b64 = _base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()
    if not _hmac.compare_digest(sig_b64, expected_b64):
        raise ValueError("Invalid signature")
    pad = (4 - len(payload_b64) % 4) % 4
    payload = _json.loads(_base64.urlsafe_b64decode(payload_b64 + "=" * pad))
    if time.time() - payload["ts"] > max_age:
        raise ValueError("Token expired")
    return payload


@app.get("/api/strava/connect")
def strava_connect(scope: str = Query(default="activity:read_all"), user: User = Depends(resolve_user)):
    """Initiate Strava OAuth flow for the authenticated user."""
    if scope not in _VALID_STRAVA_SCOPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scope '{scope}'. Must be one of: read, activity:read, activity:read_all",
        )

    client_id = os.getenv("STRAVA_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="STRAVA_CLIENT_ID is not configured")

    if not os.getenv("STRAVA_CLIENT_SECRET"):
        raise HTTPException(status_code=500, detail="STRAVA_CLIENT_SECRET is not configured")

    state_secret = os.getenv("STRAVA_STATE_SECRET")
    if not state_secret:
        raise HTTPException(status_code=500, detail="STRAVA_STATE_SECRET is not configured")

    redirect_uri = os.getenv("STRAVA_REDIRECT_URI", "http://localhost:9001/api/strava/callback")

    user_id = str(user.id)

    state = _make_strava_state_token(user_id, state_secret)
    authorize_url = _STRAVA_AUTH_URL + "?" + _urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": scope,
        "state": state,
    })
    return JSONResponse({"authorize_url": authorize_url})


def _exchange_strava_code(code: str, client_id: str, client_secret: str) -> dict:
    """POST to Strava token endpoint and return parsed JSON. Raises HTTP 502 on Strava 4xx."""
    data = _urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    }).encode()
    req = _urllib_request.Request("https://www.strava.com/oauth/token", data=data, method="POST")
    try:
        with _urllib_request.urlopen(req) as resp:
            return _json.loads(resp.read())
    except _urllib_error.HTTPError as exc:
        if 400 <= exc.code < 500:
            raise HTTPException(status_code=502, detail="Strava token exchange failed, please try again")
        raise


def _upsert_strava_token(
    user_id: str,
    athlete_id: int,
    access_token: str,
    refresh_token: str,
    expires_at: _datetime,
    scope: Optional[str],
    athlete_data: dict,
) -> None:
    now = _datetime.now(tz=_timezone.utc)
    with Session(engine) as session:
        stmt = (
            _pg_insert(StravaToken)
            .values(
                user_id=user_id,
                athlete_id=athlete_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=scope,
                athlete_data=athlete_data,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "athlete_id": athlete_id,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                    "scope": scope,
                    "athlete_data": athlete_data,
                    "updated_at": now,
                },
            )
        )
        session.execute(stmt)
        session.commit()


_STRAVA_CALLBACK_HTML = """<!DOCTYPE html>
<html>
<body>
<script>
if (window.opener) {
  window.opener.postMessage({type: 'strava_connected'}, '*');
}
window.close();
</script>
</body>
</html>"""


@app.get("/api/strava/callback")
def strava_callback(
    code: str = Query(...),
    scope: str = Query(default=""),
    state: str = Query(...),
):
    state_secret = os.getenv("STRAVA_STATE_SECRET")
    if not state_secret:
        raise HTTPException(status_code=500, detail="STRAVA_STATE_SECRET is not configured")

    try:
        payload = _verify_strava_state_token(state, state_secret)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Authorization state expired or invalid, please reconnect",
        )

    user_id = payload["user_id"]
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")

    token_resp = _exchange_strava_code(code, client_id, client_secret)

    access_token = token_resp["access_token"]
    refresh_token = token_resp["refresh_token"]
    expires_at = _datetime.fromtimestamp(token_resp["expires_at"], tz=_timezone.utc)
    athlete = token_resp.get("athlete", {})
    athlete_id = athlete.get("id", 0)

    _upsert_strava_token(
        user_id=user_id,
        athlete_id=athlete_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scope=scope or None,
        athlete_data=athlete,
    )

    return Response(content=_STRAVA_CALLBACK_HTML, media_type="text/html")


# ── Stryd ──────────────────────────────────────────────────────────────────────

from backend.services.stryd import _call_stryd_signin as _stryd_signin  # noqa: E402
from backend.services.crypto import encrypt_value as _encrypt_value  # noqa: E402
from backend.services.strava import refresh_token_if_needed  # noqa: E402
from backend.services.stryd import refresh_stryd_session_if_needed  # noqa: E402


class _StrydConnectIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1)


def _upsert_stryd_credentials(
    user_id: str,
    stryd_email: str,
    password_encrypted: str,
    session_token: str,
    session_token_expires_at: _datetime,
    athlete_id: int,
) -> None:
    now = _datetime.now(tz=_timezone.utc)
    with Session(engine) as db_session:
        stmt = (
            _pg_insert(StrydCredentials)
            .values(
                user_id=user_id,
                stryd_email=stryd_email,
                stryd_password_encrypted=password_encrypted,
                session_token=session_token,
                session_token_expires_at=session_token_expires_at,
                athlete_id=athlete_id,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "stryd_email": stryd_email,
                    "stryd_password_encrypted": password_encrypted,
                    "session_token": session_token,
                    "session_token_expires_at": session_token_expires_at,
                    "athlete_id": athlete_id,
                    "updated_at": now,
                },
            )
        )
        db_session.execute(stmt)
        db_session.commit()


@app.post("/api/stryd/connect")
def stryd_connect(body: _StrydConnectIn, user: User = Depends(resolve_user)):
    """Authenticate against Stryd, encrypt and store credentials, return connection status."""
    resp = _stryd_signin(body.email, body.password)

    password_encrypted = _encrypt_value(body.password)
    now = _datetime.now(tz=_timezone.utc)
    session_token_expires_at = now + _timedelta(days=25)
    athlete_id = int(resp.get("id") or resp.get("athlete_id") or 0)
    session_token = str(resp.get("token") or resp.get("session_token") or "")
    user_id = str(user.id)

    _upsert_stryd_credentials(
        user_id=user_id,
        stryd_email=body.email,
        password_encrypted=password_encrypted,
        session_token=session_token,
        session_token_expires_at=session_token_expires_at,
        athlete_id=athlete_id,
    )

    return JSONResponse({
        "connected": True,
        "athlete_id": athlete_id,
        "stryd_user_email": body.email,
    })


# ── Strava / Stryd status and disconnect endpoints ────────────────────────────

def _get_default_user_id() -> str:
    """Return user_id for the default (first by name) user, or raise 500 if none."""
    with Session(engine) as session:
        user = session.query(User).order_by(User.name).first()
        if user is None:
            raise HTTPException(status_code=500, detail="No users found in database")
        return str(user.id)


@app.get("/api/strava/status")
def strava_status(user: User = Depends(resolve_user)):
    """Return Strava connection status; refresh token if near expiry."""
    _null_response = {"connected": False, "athlete_name": None, "scope": None, "expires_at": None}
    user_id = str(user.id)

    with Session(engine) as session:
        token_row = session.query(StravaToken).filter(StravaToken.user_id == user_id).first()
        if token_row is None:
            return JSONResponse(_null_response)
        scope = token_row.scope
        expires_at = token_row.expires_at
        athlete_data = token_row.athlete_data or {}

    athlete_name = None
    first = athlete_data.get("firstname") or ""
    last = athlete_data.get("lastname") or ""
    full = (first + " " + last).strip()
    if full:
        athlete_name = full

    try:
        refresh_token_if_needed(user_id)
    except Exception:
        return JSONResponse(_null_response)

    with Session(engine) as session:
        token_row = session.query(StravaToken).filter(StravaToken.user_id == user_id).first()
        if token_row is None:
            return JSONResponse(_null_response)
        expires_at = token_row.expires_at

    return JSONResponse({
        "connected": True,
        "athlete_name": athlete_name,
        "scope": scope,
        "expires_at": expires_at.isoformat() if expires_at else None,
    })


@app.delete("/api/strava/disconnect")
def strava_disconnect(user: User = Depends(resolve_user)):
    """Delete Strava token row and optionally deauthorize with Strava API."""
    user_id = str(user.id)

    with Session(engine) as session:
        token_row = session.query(StravaToken).filter(StravaToken.user_id == user_id).first()
        if token_row is not None:
            access_token = token_row.access_token
            session.delete(token_row)
            session.commit()

            try:
                deauth_data = _urlencode({"access_token": access_token}).encode()
                deauth_req = _urllib_request.Request(
                    "https://www.strava.com/oauth/deauthorize",
                    data=deauth_data,
                    method="POST",
                )
                _urllib_request.urlopen(deauth_req)
            except Exception:
                pass

    return JSONResponse({"disconnected": True})


@app.get("/api/stryd/status")
def stryd_status(user: User = Depends(resolve_user)):
    """Return Stryd connection status; refresh session if near expiry. Deletes broken credentials."""
    _null_response = {"connected": False, "athlete_id": None, "stryd_email": None, "session_expires_at": None}
    user_id = str(user.id)

    with Session(engine) as session:
        cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == user_id).first()
        if cred is None:
            return JSONResponse(_null_response)
        athlete_id = cred.athlete_id
        stryd_email = cred.stryd_email
        session_expires_at = cred.session_token_expires_at

    try:
        refresh_stryd_session_if_needed(user_id)
    except Exception:
        with Session(engine) as session:
            cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == user_id).first()
            if cred is not None:
                session.delete(cred)
                session.commit()
        return JSONResponse(_null_response)

    with Session(engine) as session:
        cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == user_id).first()
        if cred is None:
            return JSONResponse(_null_response)
        session_expires_at = cred.session_token_expires_at

    return JSONResponse({
        "connected": True,
        "athlete_id": athlete_id,
        "stryd_email": stryd_email,
        "session_expires_at": session_expires_at.isoformat() if session_expires_at else None,
    })


@app.delete("/api/stryd/disconnect")
def stryd_disconnect(user: User = Depends(resolve_user)):
    """Delete Stryd credentials row."""
    user_id = str(user.id)

    with Session(engine) as session:
        cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == user_id).first()
        if cred is not None:
            session.delete(cred)
            session.commit()

    return JSONResponse({"disconnected": True})


@app.get("/api/strava/configured")
def strava_configured():
    """Return whether Strava OAuth env vars are all present."""
    configured = bool(
        os.getenv("STRAVA_CLIENT_ID")
        and os.getenv("STRAVA_CLIENT_SECRET")
        and os.getenv("STRAVA_STATE_SECRET")
    )
    return JSONResponse({"configured": configured})


@app.get("/api/stryd/configured")
def stryd_configured():
    """Return whether Stryd encryption env var is present."""
    return JSONResponse({"configured": bool(os.getenv("STRYD_FERNET_KEY"))})


_STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
_STRAVA_SYNC_PER_PAGE = 100


def _strava_sync_worker(user_id: str, since_date: Optional[str] = None) -> None:
    """Background daemon thread: pull Strava activities (optionally since since_date) and upsert."""
    import calendar as _calendar
    from datetime import date as _date_cls
    uid = _uuid.UUID(user_id)
    since_epoch: Optional[int] = None
    if since_date:
        try:
            d = _date_cls.fromisoformat(since_date)
            since_epoch = int(_calendar.timegm(_datetime(d.year, d.month, d.day, tzinfo=_timezone.utc).timetuple()))
        except ValueError:
            pass
    try:
        _sync_jobs.set_phase(uid, "pulling_strava")

        access_token = refresh_token_if_needed(user_id)
        if access_token is None:
            _sync_jobs.mark_error(uid, "Strava account not connected")
            return

        page = 1
        while True:
            if _sync_jobs.is_cancel_requested(uid):
                _sync_jobs.mark_error(uid, "cancelled")
                return

            params: dict = {"per_page": _STRAVA_SYNC_PER_PAGE, "page": page}
            if since_epoch is not None:
                params["after"] = since_epoch
            url = _STRAVA_ACTIVITIES_URL + "?" + _urlencode(params)
            req = _urllib_request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
            try:
                with _urllib_request.urlopen(req) as resp:
                    batch = _json.loads(resp.read())
            except _urllib_error.HTTPError as exc:
                _sync_jobs.mark_error(uid, f"Strava API error: {exc.code}")
                return

            if not batch:
                break

            now = _datetime.now(tz=_timezone.utc)
            rows = []
            for act in batch:
                if _sync_jobs.is_cancel_requested(uid):
                    _sync_jobs.mark_error(uid, "cancelled")
                    return
                start_dt = _datetime.strptime(act["start_date"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=_timezone.utc
                )
                rows.append({
                    "user_id": user_id,
                    "strava_activity_id": int(act["id"]),
                    "start_time": start_dt,
                    "activity_type": act.get("type") or act.get("sport_type") or "Unknown",
                    "name": act.get("name") or "Untitled",
                    "distance_km": round(float(act["distance"]) / 1000, 3) if act.get("distance") else None,
                    "duration_seconds": int(act["moving_time"]) if act.get("moving_time") else None,
                    "avg_hr": int(act["average_heartrate"]) if act.get("average_heartrate") else None,
                    "max_hr": int(act["max_heartrate"]) if act.get("max_heartrate") else None,
                    "elevation_m": int(act["total_elevation_gain"]) if act.get("total_elevation_gain") else None,
                    "avg_power_w": int(act["average_watts"]) if act.get("average_watts") else None,
                    "max_power_w": int(act["max_watts"]) if act.get("max_watts") else None,
                    "device_name": act.get("device_name"),
                    "external_id": act.get("external_id"),
                    "is_stryd_synced": False,
                    "raw_payload": act,
                    "synced_at": now,
                })

            with Session(engine) as session:
                ins = _pg_insert(StravaActivity).values(rows)
                stmt = ins.on_conflict_do_update(
                    index_elements=["strava_activity_id"],
                    set_={
                        "name": ins.excluded.name,
                        "activity_type": ins.excluded.activity_type,
                        "raw_payload": ins.excluded.raw_payload,
                        "synced_at": now,
                    },
                )
                session.execute(stmt)
                session.commit()

            _sync_jobs.increment(uid, current=len(rows), items_synced=len(rows))

            if len(batch) < _STRAVA_SYNC_PER_PAGE:
                break
            page += 1

        _reconcile.reconcile_workouts(uid, uid)
        _sync_jobs.mark_success(uid)
    except Exception as exc:  # noqa: BLE001
        _sync_jobs.mark_error(uid, str(exc))


class _StravaSyncBody(BaseModel):
    since_date: Optional[str] = None


@app.post("/api/strava/sync")
def strava_sync(body: _StravaSyncBody = Body(default=None), user: User = Depends(resolve_user)):
    """Start an async Strava pull; returns 202 immediately. Optional since_date (YYYY-MM-DD)."""
    uid = user.id
    since = None
    if body is not None:
        since = body.since_date
    try:
        _sync_jobs.start(uid, "strava")
    except _sync_jobs.SyncInProgress:
        raise HTTPException(status_code=409, detail="Sync already in progress")

    t = _threading.Thread(target=_strava_sync_worker, args=(str(uid), since), daemon=True)
    t.start()
    return JSONResponse({"started": True}, status_code=202)


class _SyncStravaTriggerBody(BaseModel):
    since_date: Optional[str] = None
    force_full: bool = False


@app.post("/api/sync/strava")
async def post_sync_strava(
    background_tasks: BackgroundTasks,
    body: _SyncStravaTriggerBody = Body(default=None),
    user: User = Depends(resolve_user),
):
    """Trigger a Strava sync; returns 202 immediately. Sync runs via BackgroundTasks.
    Falls back to synchronous execution if BackgroundTasks is unavailable.
    """
    from backend.services.strava_sync import sync_strava_activities as _strava_bg_sync

    uid = user.id

    with Session(engine) as session:
        token = session.execute(
            select(StravaToken).where(StravaToken.user_id == uid)
        ).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=422, detail="Connect Strava first")

    with Session(engine) as session:
        active_job = session.execute(
            select(SyncJob)
            .where(SyncJob.user_id == uid)
            .where(SyncJob.source == "strava")
            .where(SyncJob.status.in_(["pending", "running"]))
            .order_by(SyncJob.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if active_job is not None:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "A sync is already in progress; wait for it to complete",
                "job_id": str(active_job.id),
            },
        )

    parsed_since: Optional[_date] = None
    if body is not None and body.since_date is not None:
        try:
            parsed_since = _date.fromisoformat(body.since_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="since_date must be ISO format YYYY-MM-DD")
        cutoff = _date.today() - _timedelta(days=365)
        if parsed_since < cutoff:
            raise HTTPException(status_code=422, detail="since_date cannot be more than 1 year in the past")

    with Session(engine) as session:
        has_activities = session.execute(
            select(StravaActivity.id).where(StravaActivity.user_id == uid).limit(1)
        ).scalar_one_or_none()
    job_type = "initial_backfill" if has_activities is None else "manual_trigger"

    with Session(engine) as session:
        job = SyncJob(
            user_id=uid,
            source="strava",
            job_type=job_type,
            status="pending",
            since_date=parsed_since,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = str(job.id)

    background_tasks.add_task(_strava_bg_sync, user_id=str(uid), since_date=parsed_since, job_id=job_id)

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "running",
            "polling_url": f"/api/sync/strava/status?job_id={job_id}",
        },
    )


@app.post("/api/sync/strava/reconcile")
def strava_reconcile(user_id: _uuid.UUID = Query(...)):
    """Reconcile unlinked strava_activities into workouts. Returns counts."""
    result = _workout_reconcile.reconcile_strava_to_workouts(user_id)
    return JSONResponse(result)


@app.get("/api/sync/strava/dry-run")
def strava_sync_dry_run(
    user_id: Optional[_uuid.UUID] = Query(None),
    since_date: Optional[str] = Query(None),
    limit: int = Query(20),
):
    """Read-only preview of what a Strava reconcile would produce. No DB writes."""
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id is required")
    if limit > 50:
        raise HTTPException(status_code=400, detail="limit cannot exceed 50")
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be at least 1")
    parsed_since: Optional[_date] = None
    if since_date is not None:
        try:
            parsed_since = _date.fromisoformat(since_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="since_date must be ISO format YYYY-MM-DD")
    result = _workout_reconcile.strava_activities_dry_run(
        user_id=user_id,
        since_date=parsed_since,
        limit=limit,
    )
    return JSONResponse(result)


@app.get("/api/sync/strava/status")
def get_strava_sync_status(
    job_id: _uuid.UUID = Query(...),
    user: User = Depends(resolve_user),
):
    """Return full SyncJob row for the given job_id."""
    with Session(engine) as session:
        job = session.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse({
        "id": str(job.id),
        "user_id": str(job.user_id),
        "source": job.source,
        "job_type": job.job_type,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "activities_fetched": job.activities_fetched,
        "activities_created": job.activities_created,
        "activities_updated": job.activities_updated,
        "activities_skipped": job.activities_skipped,
        "error_message": job.error_message,
        "since_date": job.since_date.isoformat() if job.since_date else None,
    })


@app.get("/api/sync/strava/latest")
def strava_sync_latest(
    user: User = Depends(resolve_user),
    user_id: Optional[_uuid.UUID] = Query(None),
):
    """Return info about the most recent Strava sync.

    With user_id query param: returns full SyncJob dict (any status) for that user; 404 if none.
    Without user_id: returns legacy summary dict for session user (backwards-compatible).
    """
    from sqlalchemy import func, select

    if user_id is not None:
        # New path: full SyncJob dict, any status
        with Session(engine) as session:
            job = session.execute(
                select(SyncJob)
                .where(SyncJob.user_id == user_id)
                .where(SyncJob.source == "strava")
                .order_by(SyncJob.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="No sync jobs found for this user")
        return JSONResponse({
            "id": str(job.id),
            "user_id": str(job.user_id),
            "source": job.source,
            "job_type": job.job_type,
            "status": job.status,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "activities_fetched": job.activities_fetched,
            "activities_created": job.activities_created,
            "activities_updated": job.activities_updated,
            "activities_skipped": job.activities_skipped,
            "error_message": job.error_message,
            "since_date": job.since_date.isoformat() if job.since_date else None,
        })

    # Legacy path: session user, completed-only summary
    uid = user.id
    with Session(engine) as session:
        # Prefer SyncJob table (written by strava_sync service)
        job = session.execute(
            select(SyncJob)
            .where(SyncJob.user_id == uid)
            .where(SyncJob.source == "strava")
            .where(SyncJob.status == "completed")
            .order_by(SyncJob.completed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if job is not None:
            return JSONResponse({
                "synced_at": job.completed_at.isoformat() if job.completed_at else None,
                "activities_synced": (job.activities_created or 0) + (job.activities_updated or 0),
                "new_workouts": job.activities_created or 0,
            })
        # Fall back to strava_activities table (written by old sync worker)
        latest_synced = session.execute(
            select(func.max(StravaActivity.synced_at))
            .where(StravaActivity.user_id == uid)
        ).scalar()
        if latest_synced is None:
            return JSONResponse({"synced_at": None, "activities_synced": 0, "new_workouts": 0})
        # Count activities synced in that batch (within 1 minute of max synced_at)
        window = latest_synced - _timedelta(minutes=1)
        batch_count = session.execute(
            select(func.count(StravaActivity.id))
            .where(StravaActivity.user_id == uid)
            .where(StravaActivity.synced_at >= window)
        ).scalar() or 0
        # Count strava-sourced workouts as a proxy for new_workouts
        new_workouts = session.execute(
            select(func.count(Workout.id))
            .where(Workout.user_id == uid)
            .where(Workout.source.in_(["strava", "both", "strava,stryd", "stryd,strava"]))
        ).scalar() or 0
        return JSONResponse({
            "synced_at": latest_synced.isoformat(),
            "activities_synced": batch_count,
            "new_workouts": new_workouts,
        })


@app.get("/api/sync/strava/data-quality")
def strava_data_quality(user_id: Optional[_uuid.UUID] = Query(None)):
    """Return data quality counts for a user's Strava/workout sync state."""
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id is required")
    uid = user_id
    with Session(engine) as session:
        from sqlalchemy import func as _func, select as _sel, text as _text
        strava_count = session.execute(
            _sel(_func.count(StravaActivity.id)).where(StravaActivity.user_id == uid)
        ).scalar() or 0

        w_strava_count = session.execute(
            _sel(_func.count(Workout.id))
            .where(Workout.user_id == uid)
            .where(Workout.source.in_(["strava", "both", "strava,stryd", "stryd,strava"]))
        ).scalar() or 0

        w_no_source_count = session.execute(
            _sel(_func.count(Workout.id))
            .where(Workout.user_id == uid)
            .where((Workout.source == None) | (Workout.source == ""))
        ).scalar() or 0

        stryd_synced_count = session.execute(
            _sel(_func.count(Workout.id))
            .where(Workout.user_id == uid)
            .where(Workout.stryd_activity_pk != None)
        ).scalar() or 0

        # Count workouts whose start_time is within 5 minutes of another workout for the same user
        dupe_sql = _text("""
            SELECT COUNT(DISTINCT w1.id)
            FROM workouts w1
            JOIN workouts w2 ON w2.user_id = w1.user_id
              AND w2.id <> w1.id
              AND w1.start_time IS NOT NULL
              AND w2.start_time IS NOT NULL
              AND ABS(EXTRACT(EPOCH FROM (w1.start_time - w2.start_time))) < 300
            WHERE w1.user_id = :uid
        """)
        potential_dupes = session.execute(dupe_sql, {"uid": str(uid)}).scalar() or 0

    return JSONResponse({
        "strava_activities_count": int(strava_count),
        "workouts_with_strava_source_count": int(w_strava_count),
        "workouts_without_source_count": int(w_no_source_count),
        "is_stryd_synced_count": int(stryd_synced_count),
        "potential_dupes_count": int(potential_dupes),
    })


# ── App config (persistent key-value settings) ────────────────────────────────

_APP_CONFIG_GOOGLE_LOGIN = "google_login_enabled"


def _get_app_config(key: str, default: str = "") -> str:
    with Session(engine) as session:
        row = session.get(AppConfig, key)
        return row.value if row else default


def _set_app_config(key: str, value: str) -> None:
    with Session(engine) as session:
        stmt = (
            _pg_insert(AppConfig)
            .values(key=key, value=value, updated_at=_datetime.now(tz=_timezone.utc))
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": value, "updated_at": _datetime.now(tz=_timezone.utc)},
            )
        )
        session.execute(stmt)
        session.commit()


def _google_credentials_present() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID")) and bool(os.getenv("GOOGLE_CLIENT_SECRET"))


def _google_login_active() -> bool:
    """True when env flag is set, DB toggle is not disabled, and credentials are present."""
    if os.getenv("GOOGLE_LOGIN_ENABLED", "").lower() != "true":
        return False
    if _get_app_config(_APP_CONFIG_GOOGLE_LOGIN, "true").lower() == "false":
        return False
    return _google_credentials_present()


# ── Google OAuth ───────────────────────────────────────────────────────────────

_GOOGLE_SCOPE_DEFAULT = "openid email profile"
_GOOGLE_SCOPE_FITNESS = "openid email profile https://www.googleapis.com/auth/fitness.activity.read"
_VALID_GOOGLE_SCOPES = {_GOOGLE_SCOPE_DEFAULT, _GOOGLE_SCOPE_FITNESS}
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def _make_google_state_token(user_id: str, secret: str) -> str:
    """Return a signed state token encoding {user_id, ts, nonce}."""
    payload = {"user_id": user_id, "ts": int(time.time()), "nonce": _secrets.token_hex(8)}
    payload_b64 = _base64.urlsafe_b64encode(_json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = _hmac.new(secret.encode(), payload_b64.encode(), _hashlib.sha256).digest()
    sig_b64 = _base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{payload_b64}.{sig_b64}"


def _verify_google_state_token(token: str, secret: str, max_age: int = _STATE_TOKEN_MAX_AGE) -> dict:
    """Decode and verify a state token. Raises ValueError on bad signature or expiry."""
    parts = token.split(".", 1)
    if len(parts) != 2:
        raise ValueError("Invalid token format")
    payload_b64, sig_b64 = parts
    expected_sig = _hmac.new(secret.encode(), payload_b64.encode(), _hashlib.sha256).digest()
    expected_b64 = _base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()
    if not _hmac.compare_digest(sig_b64, expected_b64):
        raise ValueError("Invalid signature")
    pad = (4 - len(payload_b64) % 4) % 4
    payload = _json.loads(_base64.urlsafe_b64decode(payload_b64 + "=" * pad))
    if time.time() - payload["ts"] > max_age:
        raise ValueError("Token expired")
    return payload


_GOOGLE_SIGNIN_ERROR_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Sign-in failed</title></head>
<body>
<p>Google sign-in failed: {reason}. <a href="/login">Return to login</a>.</p>
</body>
</html>"""


@app.get("/auth/google")
def google_signin_initiate():
    if not _google_login_active():
        raise HTTPException(status_code=404, detail="Not Found")
    state_secret = os.getenv("GOOGLE_STATE_SECRET")
    if not state_secret:
        raise HTTPException(status_code=500, detail="GOOGLE_STATE_SECRET is not configured")
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    redirect_uri = os.getenv("GOOGLE_SIGNIN_REDIRECT_URI", "http://localhost:9001/auth/google/callback")
    state = _make_google_state_token("signin", state_secret)
    authorize_url = _GOOGLE_AUTH_URL + "?" + _urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _GOOGLE_SCOPE_DEFAULT,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return RedirectResponse(url=authorize_url, status_code=302)


@app.get("/auth/google/callback")
def google_signin_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    if not _google_login_active():
        raise HTTPException(status_code=404, detail="Not Found")
    state_secret = os.getenv("GOOGLE_STATE_SECRET")
    if not state_secret:
        raise HTTPException(status_code=500, detail="GOOGLE_STATE_SECRET is not configured")
    try:
        state_payload = _verify_google_state_token(state, state_secret)
    except ValueError:
        return Response(
            content=_GOOGLE_SIGNIN_ERROR_HTML.format(reason="state expired or invalid"),
            media_type="text/html",
            status_code=400,
        )
    if state_payload.get("user_id") != "signin":
        return Response(
            content=_GOOGLE_SIGNIN_ERROR_HTML.format(reason="invalid state"),
            media_type="text/html",
            status_code=400,
        )
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_SIGNIN_REDIRECT_URI", "http://localhost:9001/auth/google/callback")
    token_resp = _exchange_google_code(code, client_id, client_secret, redirect_uri)
    id_token = token_resp.get("id_token", "")
    id_token_payload = _decode_id_token_payload(id_token)
    google_sub = id_token_payload.get("sub", "")
    if not google_sub:
        return Response(
            content=_GOOGLE_SIGNIN_ERROR_HTML.format(reason="could not read Google account"),
            media_type="text/html",
            status_code=502,
        )
    with Session(engine) as session:
        creds = session.query(GoogleOAuthCredentials).filter(
            GoogleOAuthCredentials.google_sub == google_sub
        ).first()
        if creds is None:
            return Response(
                content=_GOOGLE_SIGNIN_ERROR_HTML.format(reason="no account linked to this Google identity"),
                media_type="text/html",
                status_code=403,
            )
        user = session.get(User, creds.user_id)
        if user is None or not getattr(user, "is_active", True):
            return Response(
                content=_GOOGLE_SIGNIN_ERROR_HTML.format(reason="account not found or disabled"),
                media_type="text/html",
                status_code=403,
            )
        user_id = str(user.id)
    resp = RedirectResponse(url="/home", status_code=302)
    set_session(resp, user_id)
    return resp


@app.get("/api/auth/google-status")
def google_status():
    env_enabled = os.getenv("GOOGLE_LOGIN_ENABLED", "").lower() == "true"
    creds_ok = _google_credentials_present()
    toggle_enabled = _get_app_config(_APP_CONFIG_GOOGLE_LOGIN, "true").lower() != "false"
    return JSONResponse({
        "enabled": env_enabled and creds_ok and toggle_enabled,
    })


@app.get("/api/google/connect")
def google_connect(scope: str = Query(default=_GOOGLE_SCOPE_DEFAULT), user: User = Depends(resolve_user)):
    """Initiate Google OAuth flow for the authenticated user.

    Returns authorize_url as JSON; does not redirect.
    Valid scopes: 'openid email profile' (default) or the same plus the fitness
    activity read scope.
    """
    if scope not in _VALID_GOOGLE_SCOPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid scope '{scope}'. Must be one of: "
                f"'{_GOOGLE_SCOPE_DEFAULT}' or '{_GOOGLE_SCOPE_FITNESS}'"
            ),
        )

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID is not configured")

    if not os.getenv("GOOGLE_CLIENT_SECRET"):
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_SECRET is not configured")

    state_secret = os.getenv("GOOGLE_STATE_SECRET")
    if not state_secret:
        raise HTTPException(status_code=500, detail="GOOGLE_STATE_SECRET is not configured")

    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:9001/api/google/callback")

    user_id = str(user.id)

    state = _make_google_state_token(user_id, state_secret)
    authorize_url = _GOOGLE_AUTH_URL + "?" + _urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return JSONResponse({"authorize_url": authorize_url})


_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_GOOGLE_CALLBACK_HTML = """<!DOCTYPE html>
<html>
<body>
<script>
if (window.opener) {
  window.opener.postMessage({type: 'google_connected'}, '*');
}
window.close();
</script>
</body>
</html>"""


def _exchange_google_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """POST auth code to Google token endpoint and return parsed response."""
    data = _urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = _urllib_request.Request(_GOOGLE_TOKEN_URL, data=data, method="POST")
    try:
        with _urllib_request.urlopen(req) as resp:
            return _json.loads(resp.read())
    except _urllib_error.HTTPError as exc:
        if 400 <= exc.code < 500:
            raise HTTPException(
                status_code=502,
                detail="Google token exchange failed, please try again",
            )
        raise


def _decode_id_token_payload(id_token: str) -> dict:
    """Base64-decode the payload segment of a JWT without signature verification."""
    parts = id_token.split(".")
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    # Add padding
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    try:
        return _json.loads(_base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def _upsert_google_credentials(
    *,
    user_id: str,
    google_sub: str,
    email: str,
    email_verified: bool,
    access_token: str,
    refresh_token: Optional[str],
    expires_at: _datetime,
    id_token_payload: dict,
) -> None:
    now = _datetime.now(tz=_timezone.utc)
    with Session(engine) as session:
        set_values: dict = {
            "google_sub": google_sub,
            "email": email,
            "email_verified": email_verified,
            "access_token": access_token,
            "expires_at": expires_at,
            "id_token_payload": id_token_payload,
            "updated_at": now,
        }
        if refresh_token is not None:
            set_values["refresh_token"] = refresh_token

        insert_values = {
            "user_id": user_id,
            "google_sub": google_sub,
            "email": email,
            "email_verified": email_verified,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "id_token_payload": id_token_payload,
        }

        stmt = (
            _pg_insert(GoogleOAuthCredentials)
            .values(**insert_values)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_=set_values,
            )
        )
        session.execute(stmt)
        session.commit()


@app.get("/api/google/callback")
def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    scope: str = Query(default=""),
):
    state_secret = os.getenv("GOOGLE_STATE_SECRET")
    if not state_secret:
        raise HTTPException(status_code=500, detail="GOOGLE_STATE_SECRET is not configured")

    try:
        state_payload = _verify_google_state_token(state, state_secret)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Authorization state expired or invalid, please reconnect",
        )

    user_id = state_payload["user_id"]
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:9001/api/google/callback")

    token_resp = _exchange_google_code(code, client_id, client_secret, redirect_uri)

    access_token = token_resp["access_token"]
    refresh_token = token_resp.get("refresh_token")
    expires_in = token_resp.get("expires_in", 3600)
    expires_at = _datetime.now(tz=_timezone.utc) + _timedelta(seconds=expires_in)

    id_token = token_resp.get("id_token", "")
    id_token_payload = _decode_id_token_payload(id_token)

    google_sub = id_token_payload.get("sub", "")
    email = id_token_payload.get("email", "")
    email_verified = bool(id_token_payload.get("email_verified", False))

    _upsert_google_credentials(
        user_id=user_id,
        google_sub=google_sub,
        email=email,
        email_verified=email_verified,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        id_token_payload=id_token_payload,
    )

    return Response(content=_GOOGLE_CALLBACK_HTML, media_type="text/html")


# ── Imports ───────────────────────────────────────────────────────────────────

class _SleepImportBody(BaseModel):
    user_id: str
    import_date: str
    source: str
    data: dict


@app.post("/api/imports/sleep")
def post_sleep_import(body: _SleepImportBody):
    try:
        parsed_date = _date.fromisoformat(body.import_date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"field": "import_date", "error": "import_date must be a valid YYYY-MM-DD date"},
        )

    if body.source != "manual_json":
        raise HTTPException(
            status_code=422,
            detail={"field": "source", "error": "source must be 'manual_json'"},
        )

    if not body.data:
        raise HTTPException(
            status_code=422,
            detail={"field": "data", "error": "data must contain at least one key"},
        )

    for field in ("sleep_duration_minutes", "deep_sleep_minutes", "rem_sleep_minutes", "light_sleep_minutes", "awake_minutes"):
        val = body.data.get(field)
        if val is not None and not (0 <= val <= 1440):
            raise HTTPException(
                status_code=422,
                detail={"field": field, "error": f"{field} must be between 0 and 1440"},
            )

    sleep_score = body.data.get("sleep_score")
    if sleep_score is not None and not (0 <= sleep_score <= 100):
        raise HTTPException(
            status_code=422,
            detail={"field": "sleep_score", "error": "sleep_score must be between 0 and 100"},
        )

    raw_start = body.data.get("sleep_start_time")
    raw_end = body.data.get("sleep_end_time")
    raw_duration = body.data.get("sleep_duration_minutes")

    parsed_start = None
    parsed_end = None

    if raw_start is not None:
        try:
            parsed_start = _datetime.fromisoformat(f"2000-01-01T{raw_start}").time()
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail={"field": "sleep_start_time", "error": "sleep_start_time must be HH:MM or HH:MM:SS"},
            )

    if raw_end is not None:
        try:
            parsed_end = _datetime.fromisoformat(f"2000-01-01T{raw_end}").time()
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail={"field": "sleep_end_time", "error": "sleep_end_time must be HH:MM or HH:MM:SS"},
            )

    if parsed_start is not None and parsed_end is not None:
        if parsed_end <= parsed_start:
            raise HTTPException(
                status_code=422,
                detail={"field": "sleep_end_time", "error": "sleep_end_time must be after sleep_start_time"},
            )
        if raw_duration is not None:
            start_dt = _datetime.combine(_date(2000, 1, 1), parsed_start)
            end_dt = _datetime.combine(_date(2000, 1, 1), parsed_end)
            computed = (end_dt - start_dt).total_seconds() / 60
            if abs(raw_duration - computed) > 5:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "field": "sleep_duration_minutes",
                        "error": (
                            f"sleep_duration_minutes ({raw_duration}) differs from computed"
                            f" end-start ({computed:.0f} min) by more than 5 minutes"
                        ),
                    },
                )

    try:
        parsed_user_id = _uuid.UUID(body.user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid user_id format")

    with Session(engine) as session:
        user = session.query(User).filter(User.id == parsed_user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")

        source_identifier = _hashlib.sha256(
            _json.dumps(body.data, sort_keys=True).encode()
        ).hexdigest()

        record = SleepImport(
            user_id=parsed_user_id,
            source=body.source,
            source_identifier=source_identifier,
            import_date=parsed_date,
            raw_data=body.model_dump(),
            parsed_data=body.model_dump(),
            import_status="parsed",
        )
        session.add(record)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            existing = (
                session.query(SleepImport)
                .filter(
                    SleepImport.user_id == parsed_user_id,
                    SleepImport.source == body.source,
                    SleepImport.source_identifier == source_identifier,
                )
                .first()
            )
            if existing:
                return JSONResponse(
                    status_code=409,
                    content={
                        "error_code": "duplicate",
                        "message": "This data has already been imported",
                        "existing_id": str(existing.id),
                    },
                )
            raise

        return JSONResponse(
            status_code=201,
            content={
                "id": str(record.id),
                "import_date": body.import_date,
                "source": "manual_json",
                "status": "parsed",
            },
        )


@app.get("/api/imports/sleep")
def get_sleep_imports(
    user_id: str = Query(...),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    try:
        parsed_user_id = _uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid user_id format")

    from_date = None
    to_date = None
    if from_ is not None:
        try:
            from_date = _date.fromisoformat(from_)
        except ValueError:
            raise HTTPException(status_code=422, detail={"field": "from", "error": "from must be a valid YYYY-MM-DD date"})
    if to is not None:
        try:
            to_date = _date.fromisoformat(to)
        except ValueError:
            raise HTTPException(status_code=422, detail={"field": "to", "error": "to must be a valid YYYY-MM-DD date"})

    valid_statuses = {"pending", "parsed", "merged", "rejected", "failed"}
    if status is not None and status not in valid_statuses:
        raise HTTPException(status_code=422, detail={"field": "status", "error": f"status must be one of {sorted(valid_statuses)}"})

    with Session(engine) as session:
        user = session.query(User).filter(User.id == parsed_user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")

        q = session.query(SleepImport).filter(SleepImport.user_id == parsed_user_id)
        if from_date is not None:
            q = q.filter(SleepImport.import_date >= from_date)
        if to_date is not None:
            q = q.filter(SleepImport.import_date <= to_date)
        if status is not None:
            q = q.filter(SleepImport.import_status == status)
        rows = q.order_by(SleepImport.created_at.desc()).all()

        by_status: dict = {}
        earliest = None
        latest = None
        for r in rows:
            s = r.import_status
            by_status[s] = by_status.get(s, 0) + 1
            d = r.import_date.isoformat() if r.import_date else None
            if d is not None:
                if earliest is None or d < earliest:
                    earliest = d
                if latest is None or d > latest:
                    latest = d

        imports = [
            {
                "id": str(r.id),
                "source": r.source,
                "source_identifier": r.source_identifier,
                "import_date": r.import_date.isoformat() if r.import_date else None,
                "import_status": r.import_status,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

        return JSONResponse(
            status_code=200,
            content={
                "imports": imports,
                "count": len(imports),
                "summary": {
                    "total": len(imports),
                    "by_status": by_status,
                    "date_range": {"earliest": earliest, "latest": latest},
                },
            },
        )


# ── Feel entries ──────────────────────────────────────────────────────────────

class _FeelBody(BaseModel):
    user_id: Optional[str] = None
    feel_date: str
    workout_id: Optional[str] = None
    rpe_1_to_10: Optional[int] = None
    notes: Optional[str] = None


class _FeelPatchBody(BaseModel):
    workout_id: Optional[str] = None
    rpe_1_to_10: Optional[int] = None
    notes: Optional[str] = None
    feel_date: Optional[str] = None
    user_id: Optional[str] = None


def _feel_dict(row) -> dict:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "feel_date": row.feel_date.isoformat(),
        "workout_id": str(row.workout_id) if row.workout_id else None,
        "rpe_1_to_10": row.rpe_1_to_10,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@app.get("/api/feel")
def get_feel(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    workout_id: Optional[str] = None,
    has_rpe: Optional[bool] = None,
    user: User = Depends(resolve_user),
):
    parsed_from = None
    if from_date is not None:
        try:
            parsed_from = _date.fromisoformat(from_date)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail={"field": "from", "error": "from must be a valid YYYY-MM-DD date"})

    parsed_to = None
    if to_date is not None:
        try:
            parsed_to = _date.fromisoformat(to_date)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail={"field": "to", "error": "to must be a valid YYYY-MM-DD date"})

    parsed_workout_id = None
    if workout_id is not None:
        try:
            parsed_workout_id = _uuid.UUID(workout_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="invalid workout_id format")

    with Session(engine) as session:
        q = session.query(WorkoutFeel).filter(WorkoutFeel.user_id == user.id)
        if parsed_from is not None:
            q = q.filter(WorkoutFeel.feel_date >= parsed_from)
        if parsed_to is not None:
            q = q.filter(WorkoutFeel.feel_date <= parsed_to)
        if parsed_workout_id is not None:
            q = q.filter(WorkoutFeel.workout_id == parsed_workout_id)
        if has_rpe is True:
            q = q.filter(WorkoutFeel.rpe_1_to_10.isnot(None))

        rows = q.order_by(WorkoutFeel.feel_date.desc(), WorkoutFeel.created_at.desc()).all()
        return JSONResponse({"entries": [_feel_dict(r) for r in rows], "count": len(rows)})


@app.patch("/api/feel/{feel_id}")
def patch_feel(feel_id: str, body: _FeelPatchBody, user: User = Depends(resolve_user)):
    if body.feel_date is not None or body.user_id is not None:
        raise HTTPException(
            status_code=422,
            detail={"field": "feel_date" if body.feel_date is not None else "user_id", "error": "field is immutable"},
        )

    try:
        fid = _uuid.UUID(feel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feel_id")

    if body.rpe_1_to_10 is not None and not (1 <= body.rpe_1_to_10 <= 10):
        raise HTTPException(
            status_code=422,
            detail={"field": "rpe_1_to_10", "error": "rpe_1_to_10 must be an integer between 1 and 10"},
        )

    if body.notes is not None and len(body.notes) > 10_000:
        raise HTTPException(
            status_code=422,
            detail={"field": "notes", "error": "notes must not exceed 10,000 characters"},
        )

    parsed_workout_id = None
    _update_workout_id = False
    if body.workout_id is not None:
        _update_workout_id = True
        try:
            parsed_workout_id = _uuid.UUID(body.workout_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="invalid workout_id format")

    with Session(engine) as session:
        row = session.get(WorkoutFeel, fid)
        if row is None:
            raise HTTPException(status_code=404, detail="feel entry not found")
        if row.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")

        if _update_workout_id:
            workout = session.query(Workout).filter(Workout.id == parsed_workout_id).first()
            if workout is None or workout.user_id != row.user_id:
                raise HTTPException(status_code=404, detail="workout not found")
            row.workout_id = parsed_workout_id
        if body.rpe_1_to_10 is not None:
            row.rpe_1_to_10 = body.rpe_1_to_10
        if body.notes is not None:
            row.notes = body.notes

        from datetime import datetime, timezone as _tz
        row.updated_at = datetime.now(_tz.utc)
        session.commit()
        session.refresh(row)
        return JSONResponse(_feel_dict(row))


@app.delete("/api/feel/{feel_id}", status_code=204)
def delete_feel(feel_id: str, user: User = Depends(resolve_user)):
    try:
        fid = _uuid.UUID(feel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feel_id")
    with Session(engine) as session:
        row = session.get(WorkoutFeel, fid)
        if row is None:
            raise HTTPException(status_code=404, detail="feel entry not found")
        if row.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        session.delete(row)
        session.commit()
    return Response(status_code=204)


@app.post("/api/feel", status_code=201)
def post_feel(body: _FeelBody, user: User = Depends(resolve_user)):
    try:
        feel_date = _date.fromisoformat(body.feel_date)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={"field": "feel_date", "error": "feel_date must be a valid YYYY-MM-DD date"},
        )

    today = _date.today()
    tomorrow = today + _timedelta(days=1)
    if feel_date > tomorrow:
        raise HTTPException(
            status_code=422,
            detail={"field": "feel_date", "error": "feel_date cannot be in the future"},
        )

    if body.rpe_1_to_10 is not None and not (1 <= body.rpe_1_to_10 <= 10):
        raise HTTPException(
            status_code=422,
            detail={"field": "rpe_1_to_10", "error": "rpe_1_to_10 must be an integer between 1 and 10"},
        )

    if body.rpe_1_to_10 is None and not body.notes:
        raise HTTPException(
            status_code=422,
            detail={"field": "rpe_1_to_10", "error": "At least one of rpe_1_to_10 or notes is required"},
        )

    if body.notes is not None and len(body.notes) > 10_000:
        raise HTTPException(
            status_code=422,
            detail={"field": "notes", "error": "notes must not exceed 10,000 characters"},
        )

    parsed_workout_id = None
    if body.workout_id is not None:
        try:
            parsed_workout_id = _uuid.UUID(body.workout_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="invalid workout_id format")

    with Session(engine) as session:
        if parsed_workout_id is not None:
            workout = session.query(Workout).filter(Workout.id == parsed_workout_id).first()
            if workout is None or workout.user_id != user.id:
                raise HTTPException(status_code=404, detail="workout not found")

        row = WorkoutFeel(
            user_id=user.id,
            feel_date=feel_date,
            workout_id=parsed_workout_id,
            rpe_1_to_10=body.rpe_1_to_10,
            notes=body.notes,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        if parsed_workout_id is None:
            try:
                auto_link_feel_entries(user.id, feel_date)
                session.refresh(row)
            except Exception as exc:
                _logging.getLogger(__name__).warning("auto_link_feel_entries failed: %s", exc)

        return JSONResponse(status_code=201, content=_feel_dict(row))


@app.post("/api/feel/auto-link")
def post_feel_auto_link(feel_date: str, user: User = Depends(resolve_user)):
    try:
        parsed_date = _date.fromisoformat(feel_date)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail={"field": "feel_date", "error": "feel_date must be YYYY-MM-DD"})
    linked = auto_link_feel_entries(user.id, parsed_date)
    return JSONResponse({"linked": linked})


@app.get("/api/feel/summary")
def get_feel_summary(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: User = Depends(resolve_user),
):
    from sqlalchemy import func as _func

    parsed_from = None
    if from_date is not None:
        try:
            parsed_from = _date.fromisoformat(from_date)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail={"field": "from", "error": "from must be a valid YYYY-MM-DD date"})

    parsed_to = None
    if to_date is not None:
        try:
            parsed_to = _date.fromisoformat(to_date)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail={"field": "to", "error": "to must be a valid YYYY-MM-DD date"})

    with Session(engine) as session:
        q = session.query(WorkoutFeel).filter(WorkoutFeel.user_id == user.id)
        if parsed_from is not None:
            q = q.filter(WorkoutFeel.feel_date >= parsed_from)
        if parsed_to is not None:
            q = q.filter(WorkoutFeel.feel_date <= parsed_to)

        rows = q.all()
        total = len(rows)

        if total == 0:
            return JSONResponse({
                "total_entries": 0,
                "linked_to_workouts": 0,
                "standalone": 0,
                "avg_rpe": None,
                "min_rpe": None,
                "max_rpe": None,
                "rpe_distribution": {},
                "entries_with_notes": 0,
                "avg_notes_length_chars": None,
                "date_range": {"first": None, "last": None},
            })

        linked = sum(1 for r in rows if r.workout_id is not None)
        standalone = total - linked
        rpe_rows = [r.rpe_1_to_10 for r in rows if r.rpe_1_to_10 is not None]
        avg_rpe = round(sum(rpe_rows) / len(rpe_rows), 2) if rpe_rows else None
        min_rpe = min(rpe_rows) if rpe_rows else None
        max_rpe = max(rpe_rows) if rpe_rows else None
        rpe_dist: dict = {}
        for v in rpe_rows:
            rpe_dist[str(v)] = rpe_dist.get(str(v), 0) + 1

        notes_rows = [r.notes for r in rows if r.notes]
        entries_with_notes = len(notes_rows)
        avg_notes_len = round(sum(len(n) for n in notes_rows) / len(notes_rows), 2) if notes_rows else None

        dates = [r.feel_date for r in rows]
        first_date = min(dates).isoformat()
        last_date = max(dates).isoformat()

        return JSONResponse({
            "total_entries": total,
            "linked_to_workouts": linked,
            "standalone": standalone,
            "avg_rpe": avg_rpe,
            "min_rpe": min_rpe,
            "max_rpe": max_rpe,
            "rpe_distribution": rpe_dist,
            "entries_with_notes": entries_with_notes,
            "avg_notes_length_chars": avg_notes_len,
            "date_range": {"first": first_date, "last": last_date},
        })


def _make_preview(notes: str, query: str, window: int = 80) -> str:
    lower = notes.lower()
    idx = lower.find(query.lower())
    if idx == -1:
        return notes[:window * 2]
    start = max(0, idx - window // 2)
    end = min(len(notes), idx + len(query) + window // 2)
    snippet = notes[start:end]
    # replace match within snippet (case-preserving)
    snip_lower = snippet.lower()
    rel = idx - start
    matched_text = snippet[rel: rel + len(query)]
    preview = snippet[:rel] + f"**{matched_text}**" + snippet[rel + len(query):]
    if start > 0:
        preview = "..." + preview
    if end < len(notes):
        preview = preview + "..."
    return preview


@app.get("/api/feel/search")
def get_feel_search(
    q: str,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: User = Depends(resolve_user),
):
    if len(q) < 2:
        raise HTTPException(status_code=422, detail={"field": "q", "error": "q must be at least 2 characters"})

    parsed_from = None
    if from_date is not None:
        try:
            parsed_from = _date.fromisoformat(from_date)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail={"field": "from", "error": "from must be a valid YYYY-MM-DD date"})

    parsed_to = None
    if to_date is not None:
        try:
            parsed_to = _date.fromisoformat(to_date)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail={"field": "to", "error": "to must be a valid YYYY-MM-DD date"})

    with Session(engine) as session:
        query_obj = session.query(WorkoutFeel).filter(
            WorkoutFeel.user_id == user.id,
            WorkoutFeel.notes.ilike(f"%{q}%"),
        )
        if parsed_from is not None:
            query_obj = query_obj.filter(WorkoutFeel.feel_date >= parsed_from)
        if parsed_to is not None:
            query_obj = query_obj.filter(WorkoutFeel.feel_date <= parsed_to)

        rows = (
            query_obj
            .order_by(WorkoutFeel.feel_date.desc(), WorkoutFeel.created_at.desc())
            .limit(50)
            .all()
        )

        results = []
        for r in rows:
            entry = _feel_dict(r)
            entry["preview"] = _make_preview(r.notes, q) if r.notes else ""
            results.append(entry)

        return JSONResponse({"results": results, "count": len(results)})


# ── Training Load (CTL / ATL / TSB) ──────────────────────────────────────────


def _load_interpretation(ctl: float, atl: float, tsb: float) -> str:
    # inclusive thresholds per #259 TSB interpretation spec
    if tsb >= 5:
        label = "Fresh"
    elif tsb >= -5:
        label = "Neutral"
    elif tsb >= -15:
        label = "Productive (high load)"
    else:
        label = "Overreached (high risk)"

    if ctl > 60:
        return f"{label}, well-trained"
    elif ctl < 30:
        return f"{label}, undertrained"
    return label


@app.get("/api/training-load/current")
def get_training_load_current(
    user_id: str,
    as_of: Optional[str] = Query(default=None),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    try:
        as_of_date = _date.fromisoformat(as_of) if as_of else _date.today()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid as_of date; use YYYY-MM-DD")

    with Session(engine) as session:
        if session.query(User).filter(User.id == uid).first() is None:
            raise HTTPException(status_code=404, detail="User not found")

    load = current_load(str(uid), as_of=as_of_date)
    ctl = round(load["ctl"], 1)
    atl = round(load["atl"], 1)
    tsb = round(load["tsb"], 1)

    return JSONResponse({
        "date": load["date"].isoformat(),
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "interpretation": _load_interpretation(ctl, atl, tsb),
    })


@app.get("/api/training-load")
def get_training_load(
    user_id: str,
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = _date.today()
    try:
        from_d = _date.fromisoformat(from_date) if from_date else today - _timedelta(days=90)
        to_d = _date.fromisoformat(to_date) if to_date else today
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format; use YYYY-MM-DD")

    if from_d > to_d:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")

    if (to_d - from_d).days > 365:
        raise HTTPException(status_code=422, detail="Date range must not exceed 365 days")

    with Session(engine) as session:
        if session.query(User).filter(User.id == uid).first() is None:
            raise HTTPException(status_code=404, detail="User not found")

        snaps = (
            session.query(TrainingLoadSnapshot)
            .filter(
                TrainingLoadSnapshot.user_id == uid,
                TrainingLoadSnapshot.snapshot_date >= from_d,
                TrainingLoadSnapshot.snapshot_date <= to_d,
            )
            .order_by(TrainingLoadSnapshot.snapshot_date)
            .all()
        )

    snap_map = {s.snapshot_date: s for s in snaps}
    all_dates = [from_d + _timedelta(days=i) for i in range((to_d - from_d).days + 1)]
    missing_dates = [d for d in all_dates if d not in snap_map]

    tss_map: dict = {}
    if missing_dates:
        hist_missing = [d for d in missing_dates if d <= today]
        if hist_missing:
            tss_series = daily_tss_series(str(uid), min(hist_missing), max(hist_missing))
            tss_map = {d: t for d, t in tss_series}

    ctl_alpha = _ewma_alpha(42)
    atl_alpha = _ewma_alpha(7)
    ctl, atl = 0.0, 0.0
    curves_out = []

    for d in all_dates:
        if d in snap_map:
            s = snap_map[d]
            ctl = s.ctl
            atl = s.atl
            tsb = ctl - atl
            curves_out.append({
                "date": d.isoformat(),
                "tss": s.tss_for_day,
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(tsb, 1),
            })
        else:
            tss = tss_map.get(d, 0)
            ctl = ctl + (tss - ctl) * ctl_alpha
            atl = atl + (tss - atl) * atl_alpha
            tsb = ctl - atl
            curves_out.append({
                "date": d.isoformat(),
                "tss": tss,
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(tsb, 1),
            })

    return JSONResponse({
        "curves": curves_out,
        "current": curves_out[-1] if curves_out else None,
        "as_of": to_d.isoformat(),
    })


@app.post("/api/training-load/recompute")
def recompute_training_load(
    user_id: str,
    from_date: str = Query(alias="from"),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    try:
        from_d = _date.fromisoformat(from_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid from date; use YYYY-MM-DD")

    today = _date.today()
    if from_d > today:
        raise HTTPException(status_code=422, detail="'from' must not be in the future")

    with Session(engine) as session:
        if session.query(User).filter(User.id == uid).first() is None:
            raise HTTPException(status_code=404, detail="User not found")

        seed_snap = (
            session.query(TrainingLoadSnapshot)
            .filter(
                TrainingLoadSnapshot.user_id == uid,
                TrainingLoadSnapshot.snapshot_date == from_d - _timedelta(days=1),
            )
            .first()
        )

    seed_ctl = float(seed_snap.ctl) if seed_snap else 0.0
    seed_atl = float(seed_snap.atl) if seed_snap else 0.0

    tss_series = daily_tss_series(str(uid), from_d, today)
    tss_map = {d: t for d, t in tss_series}

    ctl_alpha = _ewma_alpha(42)
    atl_alpha = _ewma_alpha(7)
    ctl, atl = seed_ctl, seed_atl
    rows = []
    current = from_d
    while current <= today:
        tss = tss_map.get(current, 0)
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        tsb = ctl - atl
        rows.append({
            "user_id": uid,
            "snapshot_date": current,
            "tss_for_day": tss,
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(tsb, 2),
        })
        current += _timedelta(days=1)

    if rows:
        insert_stmt = _pg_insert(TrainingLoadSnapshot).values(rows)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["user_id", "snapshot_date"],
            set_={
                "tss_for_day": insert_stmt.excluded.tss_for_day,
                "ctl": insert_stmt.excluded.ctl,
                "atl": insert_stmt.excluded.atl,
                "tsb": insert_stmt.excluded.tsb,
                "computed_at": _datetime.now(tz=_timezone.utc),
            },
        )
        with Session(engine) as session:
            session.execute(upsert_stmt)
            session.commit()

    return JSONResponse({
        "recomputed": len(rows),
        "from": from_d.isoformat(),
        "to": today.isoformat(),
    })


@app.post("/api/training-load/refresh")
def refresh_training_load(
    user_id: str,
    target_date: Optional[str] = Query(default=None, alias="date"),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = _date.today()
    try:
        target = _date.fromisoformat(target_date) if target_date else today
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date; use YYYY-MM-DD")

    if target > today:
        raise HTTPException(status_code=422, detail="date cannot be in the future")

    with Session(engine) as session:
        if session.query(User).filter(User.id == uid).first() is None:
            raise HTTPException(status_code=404, detail="User not found")

    result = daily_update(str(uid), target)
    return JSONResponse({
        "date": result["date"].isoformat(),
        "tss": result["tss"],
        "ctl": result["ctl"],
        "atl": result["atl"],
        "tsb": result["tsb"],
    })


@app.post("/api/training-load/backfill")
def backfill_training_load(
    user_id: str,
    from_date: str = Query(alias="from"),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    try:
        from_d = _date.fromisoformat(from_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid from date; use YYYY-MM-DD")

    today = _date.today()
    if from_d > today:
        raise HTTPException(status_code=422, detail="'from' must not be in the future")

    with Session(engine) as session:
        if session.query(User).filter(User.id == uid).first() is None:
            raise HTTPException(status_code=404, detail="User not found")

        seed_snap = (
            session.query(TrainingLoadSnapshot)
            .filter(
                TrainingLoadSnapshot.user_id == uid,
                TrainingLoadSnapshot.snapshot_date == from_d - _timedelta(days=1),
            )
            .first()
        )

    seed_ctl = float(seed_snap.ctl) if seed_snap else 0.0
    seed_atl = float(seed_snap.atl) if seed_snap else 0.0

    tss_series = daily_tss_series(str(uid), from_d, today)
    tss_map = {d: t for d, t in tss_series}

    ctl_alpha = _ewma_alpha(42)
    atl_alpha = _ewma_alpha(7)
    ctl, atl = seed_ctl, seed_atl
    rows = []
    current = from_d
    while current <= today:
        tss = tss_map.get(current, 0)
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        tsb = ctl - atl
        rows.append({
            "user_id": uid,
            "snapshot_date": current,
            "tss_for_day": tss,
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(tsb, 2),
        })
        current += _timedelta(days=1)

    if rows:
        insert_stmt = _pg_insert(TrainingLoadSnapshot).values(rows)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["user_id", "snapshot_date"],
            set_={
                "tss_for_day": insert_stmt.excluded.tss_for_day,
                "ctl": insert_stmt.excluded.ctl,
                "atl": insert_stmt.excluded.atl,
                "tsb": insert_stmt.excluded.tsb,
                "computed_at": _datetime.now(tz=_timezone.utc),
            },
        )
        with Session(engine) as session:
            session.execute(upsert_stmt)
            session.commit()

    return JSONResponse({
        "backfilled": len(rows),
        "from": from_d.isoformat(),
        "to": today.isoformat(),
    })


# ── Admin gate ────────────────────────────────────────────────────────────────

class AdminLoginIn(BaseModel):
    secret: str


@app.get("/admin", include_in_schema=False)
def admin_entry(request: Request):
    """Entry point for the admin area.

    - No ADMIN_SECRET_* env var set → 403 (admin disabled).
    - No valid admin cookie → serve login form.
    - Valid admin cookie → serve admin dashboard.
    """
    secret = get_admin_secret()
    if not secret:
        raise HTTPException(status_code=403, detail="Admin access is disabled on this instance")
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if token:
        try:
            read_admin_cookie(token)
            return FileResponse(str(_static_root / "frontend" / "pages" / "admin.html"))
        except ValueError:
            pass
    return FileResponse(str(_static_root / "frontend" / "pages" / "admin-login.html"))


@app.post("/api/admin/login")
def admin_login(body: AdminLoginIn, request: Request):
    ip = request.client.host if request.client else "unknown"
    admin_lockout_check(ip)

    admin_secret = get_admin_secret()
    if not admin_secret:
        raise HTTPException(status_code=403, detail="Admin access is disabled")

    if not _hmac.compare_digest(body.secret.encode(), admin_secret.encode()):
        admin_lockout_record(ip)
        raise HTTPException(status_code=401, detail="Invalid admin secret")

    admin_lockout_clear(ip)
    resp = JSONResponse({"ok": True})
    set_admin_cookie(resp)
    return resp


@app.post("/api/admin/logout", status_code=204)
def admin_logout():
    resp = Response(status_code=204)
    clear_admin_cookie(resp)
    return resp


# ── Admin user management endpoints ──────────────────────────────────────────

class AdminUserCreateIn(BaseModel):
    username: str
    password: str
    is_admin: bool = False


@app.post("/api/admin/users", status_code=201, dependencies=[Depends(require_admin)])
def admin_create_user(body: AdminUserCreateIn):
    username = body.username.strip()
    if not (1 <= len(username) <= 100):
        raise HTTPException(status_code=422, detail="username must be 1–100 characters")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    pw_hash = hash_password(body.password)
    with Session(engine) as session:
        user = User(name=username, password_hash=pw_hash, is_admin=body.is_admin)
        session.add(user)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail=f"Username '{username}' already exists")
        session.refresh(user)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(user.id),
                "username": user.name,
                "is_admin": bool(user.is_admin),
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
        )


@app.get("/api/admin/users", dependencies=[Depends(require_admin)])
def admin_list_users():
    from sqlalchemy import func, select
    with Session(engine) as session:
        strava_sub = select(StravaToken.user_id).subquery()
        google_sub = select(GoogleOAuthCredentials.user_id).subquery()
        stryd_sub = select(StrydCredentials.user_id).subquery()

        rows = (
            session.query(
                User,
                strava_sub.c.user_id.isnot(None).label("has_strava"),
                google_sub.c.user_id.isnot(None).label("has_google"),
                stryd_sub.c.user_id.isnot(None).label("has_stryd"),
            )
            .outerjoin(strava_sub, User.id == strava_sub.c.user_id)
            .outerjoin(google_sub, User.id == google_sub.c.user_id)
            .outerjoin(stryd_sub, User.id == stryd_sub.c.user_id)
            .order_by(User.name)
            .all()
        )
        return JSONResponse([
            {
                "id": str(u.id),
                "username": u.name,
                "is_admin": bool(u.is_admin),
                "is_active": bool(getattr(u, "is_active", True)),
                "integration_count": int(bool(has_strava)) + int(bool(has_google)) + int(bool(has_stryd)),
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u, has_strava, has_google, has_stryd in rows
        ])


class AdminResetPasswordIn(BaseModel):
    new_password: str


@app.post("/api/admin/users/{user_id}/reset-password", dependencies=[Depends(require_admin)])
def admin_reset_password(user_id: str, body: AdminResetPasswordIn):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.password_hash = hash_password(body.new_password)
        session.commit()
    return JSONResponse({"ok": True})


@app.post("/api/admin/users/{user_id}/toggle-admin", dependencies=[Depends(require_admin)])
def admin_toggle_admin(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.is_admin:
            admin_count = session.query(User).filter(User.is_admin.is_(True)).count()
            if admin_count <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot remove admin: at least one admin must remain",
                )
        user.is_admin = not user.is_admin
        session.commit()
        session.refresh(user)
    return JSONResponse({"id": str(user.id), "is_admin": bool(user.is_admin)})


@app.post("/api/admin/users/{user_id}/disable", dependencies=[Depends(require_admin)])
def admin_disable_user(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_active = False
        session.commit()
    return JSONResponse({"id": str(uid), "is_active": False})


@app.post("/api/admin/users/{user_id}/enable", dependencies=[Depends(require_admin)])
def admin_enable_user(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_active = True
        session.commit()
    return JSONResponse({"id": str(uid), "is_active": True})


@app.delete("/api/admin/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)])
def admin_delete_user(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.is_admin:
            admin_count = session.query(User).filter(User.is_admin.is_(True)).count()
            if admin_count <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot delete the last admin account",
                )
        session.delete(user)
        session.commit()
    return Response(status_code=204)


# ── Admin: Google login config ────────────────────────────────────────────────

class AdminGoogleLoginToggleIn(BaseModel):
    enabled: bool


@app.get("/api/admin/config/google-login", dependencies=[Depends(require_admin)])
def admin_get_google_login_config():
    env_enabled = os.getenv("GOOGLE_LOGIN_ENABLED", "").lower() == "true"
    creds_present = _google_credentials_present()
    toggle_enabled = _get_app_config(_APP_CONFIG_GOOGLE_LOGIN, "true").lower() != "false"
    active = env_enabled and creds_present and toggle_enabled
    warning = None
    if env_enabled and not creds_present:
        warning = "GOOGLE_LOGIN_ENABLED is true but GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET is missing"
    return JSONResponse({
        "env_enabled": env_enabled,
        "credentials_present": creds_present,
        "toggle_enabled": toggle_enabled,
        "active": active,
        "warning": warning,
    })


@app.post("/api/admin/config/google-login", dependencies=[Depends(require_admin)])
def admin_set_google_login_config(body: AdminGoogleLoginToggleIn):
    _set_app_config(_APP_CONFIG_GOOGLE_LOGIN, "true" if body.enabled else "false")
    return JSONResponse({"toggle_enabled": body.enabled})


# ── Sync status endpoint ───────────────────────────────────────────────────────

@app.get("/api/sync/status")
async def get_sync_status(user: User = Depends(resolve_user)):
    job = _sync_jobs.snapshot(user.id)
    if job is None:
        return JSONResponse({"status": "idle"})
    serialized = {
        **job,
        "started_at": job["started_at"].isoformat() if job["started_at"] else None,
        "finished_at": job["finished_at"].isoformat() if job["finished_at"] else None,
    }
    return JSONResponse(serialized)


@app.get("/api/sync/history")
def get_sync_history(
    user: User = Depends(resolve_user),
    user_id: Optional[_uuid.UUID] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(20),
):
    """Return paginated SyncJob history. Requires auth; 403 if requesting another user without admin."""
    from sqlalchemy import select as _sel

    if limit > 100:
        raise HTTPException(status_code=400, detail="limit cannot exceed 100")

    target_uid = user_id if user_id is not None else user.id
    if target_uid != user.id and not bool(user.is_admin):
        raise HTTPException(status_code=403, detail="Forbidden")

    with Session(engine) as session:
        q = _sel(SyncJob).where(SyncJob.user_id == target_uid)
        if source is not None:
            q = q.where(SyncJob.source == source)
        q = q.order_by(SyncJob.started_at.desc()).limit(limit)
        rows = session.execute(q).scalars().all()

    def _job_dict(job: SyncJob) -> dict:
        finished = job.completed_at
        started = job.started_at
        duration = (
            (finished - started).total_seconds()
            if finished is not None and started is not None
            else None
        )
        return {
            "id": str(job.id),
            "user_id": str(job.user_id),
            "source": job.source,
            "job_type": job.job_type,
            "status": job.status,
            "started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
            "completed_at": finished.isoformat() if finished else None,
            "duration_seconds": duration,
            "activities_fetched": job.activities_fetched,
            "activities_created": job.activities_created,
            "activities_updated": job.activities_updated,
            "activities_skipped": job.activities_skipped,
            "error_message": job.error_message,
            "since_date": job.since_date.isoformat() if job.since_date else None,
        }

    return JSONResponse([_job_dict(r) for r in rows])


# ── User Preferences endpoints ─────────────────────────────────────────────────

_PREFS_DEFAULTS = {
    "ftp_w": 280,
    "threshold_hr": 170,
    "threshold_pace_seconds_per_km": 270,
}

_PREFS_EDITABLE = {"ftp_w", "threshold_hr", "threshold_pace_seconds_per_km", "display_name", "week_start_day", "timezone"}
_PREFS_NON_EDITABLE = {"preferred_units", "date_format"}


def _prefs_row_dict(prefs: UserPreferences) -> dict:
    return {
        "user_id": str(prefs.user_id),
        "ftp_w": prefs.ftp_w,
        "threshold_hr": prefs.threshold_hr,
        "threshold_pace_seconds_per_km": prefs.threshold_pace_seconds_per_km,
        "display_name": prefs.display_name,
        "week_start_day": prefs.week_start_day,
        "timezone": prefs.timezone,
    }


@app.get("/api/user-preferences")
def get_user_preferences(user: User = Depends(resolve_user)):
    uid = user.id
    with Session(engine) as session:
        db_user = session.get(User, uid)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        prefs = session.query(UserPreferences).filter(UserPreferences.user_id == uid).first()
        if prefs is None:
            prefs = UserPreferences(user_id=uid)
            session.add(prefs)
            session.commit()
            session.refresh(prefs)
        row = _prefs_row_dict(prefs)
        row["user_name"] = db_user.name
        row["user_email"] = db_user.email
        return JSONResponse({
            "row": row,
            "defaults": _PREFS_DEFAULTS,
        })


_PREFS_SENTINEL = object()


@app.patch("/api/user-preferences")
async def patch_user_preferences(request: Request, user: User = Depends(resolve_user)):
    import zoneinfo as _zoneinfo

    uid = user.id

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    # Reject non-editable fields
    non_editable_sent = _PREFS_NON_EDITABLE & set(body.keys())
    if non_editable_sent:
        field = next(iter(non_editable_sent))
        raise HTTPException(status_code=422, detail=f"Field '{field}' is not editable")

    # Validate fields
    ftp_w = body.get("ftp_w", _PREFS_SENTINEL)
    threshold_hr = body.get("threshold_hr", _PREFS_SENTINEL)
    threshold_pace = body.get("threshold_pace_seconds_per_km", _PREFS_SENTINEL)
    display_name = body.get("display_name", _PREFS_SENTINEL)
    week_start_day = body.get("week_start_day", _PREFS_SENTINEL)
    timezone = body.get("timezone", _PREFS_SENTINEL)

    errors = []
    if ftp_w is not _PREFS_SENTINEL and ftp_w is not None:
        if not isinstance(ftp_w, int) or not (50 <= ftp_w <= 600):
            errors.append({"field": "ftp_w", "msg": "ftp_w must be between 50 and 600"})
    if threshold_hr is not _PREFS_SENTINEL and threshold_hr is not None:
        if not isinstance(threshold_hr, int) or not (100 <= threshold_hr <= 220):
            errors.append({"field": "threshold_hr", "msg": "threshold_hr must be between 100 and 220"})
    if threshold_pace is not _PREFS_SENTINEL and threshold_pace is not None:
        if not isinstance(threshold_pace, int) or not (180 <= threshold_pace <= 540):
            errors.append({"field": "threshold_pace_seconds_per_km", "msg": "threshold_pace_seconds_per_km must be between 180 and 540"})
    if display_name is not _PREFS_SENTINEL and display_name is not None:
        if not isinstance(display_name, str) or len(display_name) > 100:
            errors.append({"field": "display_name", "msg": "display_name must be ≤ 100 characters"})
    if week_start_day is not _PREFS_SENTINEL and week_start_day is not None:
        if not isinstance(week_start_day, int) or not (1 <= week_start_day <= 7):
            errors.append({"field": "week_start_day", "msg": "week_start_day must be between 1 and 7"})
    if timezone is not _PREFS_SENTINEL and timezone is not None:
        try:
            _zoneinfo.ZoneInfo(timezone)
        except (KeyError, _zoneinfo.ZoneInfoNotFoundError):
            errors.append({"field": "timezone", "msg": f"Unknown IANA timezone: {timezone}"})

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    with Session(engine) as session:
        prefs = session.query(UserPreferences).filter(UserPreferences.user_id == uid).first()
        if prefs is None:
            prefs = UserPreferences(user_id=uid)
            session.add(prefs)

        if ftp_w is not _PREFS_SENTINEL:
            prefs.ftp_w = ftp_w
        if threshold_hr is not _PREFS_SENTINEL:
            prefs.threshold_hr = threshold_hr
        if threshold_pace is not _PREFS_SENTINEL:
            prefs.threshold_pace_seconds_per_km = threshold_pace
        if display_name is not _PREFS_SENTINEL:
            prefs.display_name = display_name
        if week_start_day is not _PREFS_SENTINEL:
            prefs.week_start_day = week_start_day
        if timezone is not _PREFS_SENTINEL:
            prefs.timezone = timezone

        prefs.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(prefs)
        return JSONResponse(_prefs_row_dict(prefs))
