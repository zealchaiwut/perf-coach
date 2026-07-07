import base64 as _base64
import csv as _csv
import hashlib as _hashlib
import hmac as _hmac
import io as _io
import json as _json
import logging as _logging
import os
import secrets as _secrets
import threading as _threading
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
import time
import uuid as _uuid
from datetime import date as _date, datetime as _datetime, timezone as _timezone, timedelta as _timedelta
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlencode as _urlencode
import urllib.request as _urllib_request
import urllib.error as _urllib_error

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import cast as _sa_cast, exc as sa_exc, func, or_, select
from sqlalchemy.types import DateTime as _sa_DateTime
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session, joinedload, load_only, selectinload
from zoneinfo import ZoneInfo

from backend.auth import require_admin
from backend.db import check_db, engine, environment
from backend.models import AppConfig, DailyMetric, DriveSleepConnection, EconomyCeilingSnapshot, GoogleOAuthCredentials, Habit, HabitLog, PersonalRecord, Race, RaceCheckpoint, RemovedActivity, SleepImport, StravaActivity, StravaToken, StrydActivity, StrydCredentials, SyncJob, TAPER_SHAPE_VALUES, TrainingLoadSnapshot, TrainingPlan, User, UserPreferences, WeightEntry, WeightPlan, WeightTarget, Workout, WorkoutExercise, WorkoutFeel, WorkoutSplit, WorkoutTemplate, StrengthSession, PlyoSession, SummaryCache, PlannedSession
from backend.models import compute_goal_pace as _compute_goal_pace_tuple, RACE_TYPE_VALUES as _RACE_TYPE_VALUES
from backend.services.workout_merge import compute_best_values
from backend.services.tss import compute_running_tss as _compute_running_tss
from backend.services.tss import compute_strength_tss as _compute_strength_tss
from backend.services.tss import STRENGTH_TSS_SCALE as _STRENGTH_TSS_SCALE, STRENGTH_TSS_MAX as _STRENGTH_TSS_MAX
from backend.services.tss import persist_running_tss as _persist_running_tss
from backend.services.tss import recompute_user_running_tss as _recompute_user_running_tss
from backend.services.training_load import (
    _ewma_alpha,
    current_load,
    daily_tss_series,
    daily_update,
    compute_load_curves,
    compute_fitness_series,
    readiness_label as training_readiness_label,
    project_form,
    resolve_user_ewma_days,
    taper_recommendation,
    peak_tracking,
    compute_calibration_suggestions,
    FORM_BURIED_CEILING,
    FORM_FRESH_FLOOR,
    DEFAULT_TAPER_DAYS,
    TARGET_FORM_LOWER,
    PEAK_TRACKING_TOLERANCE,
    CTL_DAYS,
    ATL_DAYS,
    TIMING_TOLERANCE_WEEKS,
    CTL_ADJUSTMENT_DAYS_PER_WEEK,
    MIN_CTL_DAYS,
    MAX_CTL_DAYS,
    BASELINE_WINDOW_DAYS,
    BASELINE_MIN_WORKOUT_DAYS,
    get_weekly_volume as _get_weekly_volume,
)
from backend.services.specificity_progress import specificity_progress as _specificity_progress
from backend.services.daily_load import daily_load_series as _daily_load_series
from backend.services.feel_link import auto_link_feel_entries
from backend.services.weight_status import compute_status_label as _compute_status_label
from backend.services.weight_ewma import compute_ewma as _compute_ewma, DEFAULT_SPAN as _EWMA_DEFAULT_SPAN
from backend.services.weight_plan import compute_gap as _compute_weight_gap, generate_milestones as _generate_weight_milestones, plan_at as _weight_plan_at, project_hit_date as _project_hit_date
from backend.services import weight_plans_repo as _wp_repo
from backend.services import sync_jobs as _sync_jobs
from backend.services import reconcile as _reconcile
from backend.services import sync_runner as _sync_runner
from backend.services import workout_reconcile as _workout_reconcile
from backend.services.habit_autofill import recompute_autofill_for_week as _recompute_autofill
from backend.services.habit_streak import compute_streak
from backend.services.habit_consistency import compute_consistency
from backend.services.checkpoint_detector import evaluate_checkpoint as _evaluate_checkpoint, is_run_workout as _is_run_workout
from backend.services.riegel import riegel_half_equivalent as _riegel_half_equivalent
from backend.services.duration_curve_best_effort import get_athlete_duration_curve as _get_athlete_duration_curve
from backend.services.lap_recompute import rebuild_athlete_duration_curve as _rebuild_athlete_duration_curve
from backend.services.session_profile_caller import get_session_profile_for_workout as _get_session_profile
from backend.services.aerobic_decoupling import compute_decoupling as _compute_decoupling
from backend.services.heat_correction import (
    compute_heat_correction_factor as _compute_heat_correction_factor,
    apply_heat_correction_to_decoupling as _apply_heat_correction,
)
from backend.services.goal_arrival_caller import resolve_arrival_projection as _resolve_arrival_projection
from backend.services.performance_constants import NEEDS_THRESHOLDS_REASON as _NEEDS_THRESHOLDS_REASON
from backend.services.backfill_performance import backfill_performance_for_athlete as _backfill_performance_for_athlete
from backend.services.projection import project_fitness as _project_fitness, compute_expressible_score as _compute_expressible_score
from backend.services.score_ceiling import projected_ctl_to_score_ceiling as _projected_ctl_to_score_ceiling
from backend.services.economy_stimulus import compute_economy_stimulus as _compute_economy_stimulus
from backend.services.ceiling_bonus import compute_ceiling_bonus as _compute_ceiling_bonus, LAG_WINDOW_DAYS as _LAG_WINDOW_DAYS, LAG_PEAK_DAYS as _LAG_PEAK_DAYS
from backend.services.race_finish_estimator import score_to_estimated_finish_time as _score_to_estimated_finish_time
from backend.routers.projection import router as _plan_router
from backend.routers.strength_sessions import router as _strength_sessions_router
from backend.services.guardrail import get_guardrail_result
from backend.services.body_modifier import get_body_modifier_guardrail_for_user
from backend.services.lap_classify import aggregate_intensity_zones as _agg_zones
from backend.services.polarized_split import check_polarized_split as _check_polarized_split, _DEFAULT_BOUNDS as _POLARIZED_BOUNDS
from backend.services.lap_classify import classify_laps as _classify_laps
from backend.services.intensity_distribution import compute_polarized_check as _compute_polarized_check
from backend.services import worker_client as _worker_client

# Ceiling TSB used when computing expressible scores from historical/projected TSB.
# 20.0 matches the representative value established in issue #1107.
_TIME_CURVE_CEILING_TSB: float = 20.0


def _derive_goal_pace(goal_time_seconds, distance_km):
    """Thin wrapper around compute_goal_pace that returns the pace int (or None)."""
    pace, _ = _compute_goal_pace_tuple(goal_time_seconds, distance_km)
    return pace


_start_time = time.monotonic()
_log = _logging.getLogger(__name__)

app = FastAPI()
app.include_router(_plan_router)
app.include_router(_strength_sessions_router)


def _today_bkk() -> _date:
    """Return today's date in Asia/Bangkok (UTC+7) timezone."""
    return _datetime.now(ZoneInfo("Asia/Bangkok")).date()


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

# Authentication entry points are CSRF-exempt: login authenticates with
# username + password and *establishes* the session, so it has no pre-existing
# authenticated state to protect. A stale/leftover `session` cookie (e.g. from a
# prior deploy) must never lock a user out of re-authenticating.
_CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login"})


@app.middleware("http")
async def _csrf_protect(request: Request, call_next):
    """Require X-CSRF-Token header on all mutating requests that carry a session cookie."""
    if request.method not in _CSRF_SAFE_METHODS and request.url.path not in _CSRF_EXEMPT_PATHS:
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


@app.get("/api/healthz")
def healthz():
    """Render health check ping. Returns {ok, version, env}."""
    return JSONResponse({
        "ok": True,
        "version": os.getenv("GIT_SHA", "unset"),
        "env": environment,
    })


@app.get("/api/env")
def get_env():
    from urllib.parse import urlparse as _urlparse
    from backend.db import engine as _db_engine
    db_host = _urlparse(str(_db_engine.url)).hostname or "unknown"
    return JSONResponse({"environment": environment, "db_host": db_host})


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


@app.get("/api/users", dependencies=[Depends(require_admin)])
def get_users():
    try:
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


@app.post("/api/users", status_code=201, dependencies=[Depends(require_admin)])
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


@app.patch("/api/users/{user_id}", dependencies=[Depends(require_admin)])
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


@app.delete("/api/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)])
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
    resolve_user,
    set_admin_cookie,
    set_csrf_cookie,
    set_session,
    verify_password,
)

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
            if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
                _record_failure(body.username, ip)
                raise HTTPException(status_code=401, detail="Invalid credentials")
            _clear_lockout(body.username, ip)
            if not getattr(user, "is_active", True):
                raise HTTPException(status_code=403, detail="Account disabled")
            user_id, user_name, user_is_admin = str(user.id), user.name, bool(user.is_admin)
            # Stamp the successful login (best-effort; never blocks login).
            try:
                user.last_login_at = _datetime.now(_timezone.utc)
                session.commit()
            except sa_exc.SQLAlchemyError:
                session.rollback()
    except HTTPException:
        raise
    except sa_exc.SQLAlchemyError:
        raise HTTPException(status_code=500, detail="Database error")
    resp = JSONResponse({"id": user_id, "name": user_name, "is_admin": user_is_admin})
    set_session(resp, user_id)
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
    resp = JSONResponse(_user_dict(user))
    # Sessions created before CSRF middleware may lack csrf-token; issue one on
    # the next authenticated read so mutating requests stop failing with 403.
    if not request.cookies.get(CSRF_COOKIE_NAME):
        set_csrf_cookie(resp, generate_csrf_token())
    return resp


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

# ── Weight entries CRUD endpoints ─────────────────────────────────────────────

class WeightEntriesCreateIn(BaseModel):
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
def create_weight_entry(body: WeightEntriesCreateIn, user: User = Depends(resolve_user)):
    uid = user.id

    if not (20 <= body.weight_kg <= 300):
        raise HTTPException(status_code=422, detail="weight_kg must be between 20 and 300")
    if body.notes is not None and len(body.notes) > 500:
        raise HTTPException(status_code=422, detail="notes must not exceed 500 characters")

    try:
        entry_date = _date.fromisoformat(body.entry_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid entry_date; use YYYY-MM-DD")
    if entry_date > _today_bkk() + _timedelta(days=1):
        raise HTTPException(status_code=422, detail="entry_date cannot be more than 1 day in the future")

    entry_time = _parse_entry_time(body.entry_time) if body.entry_time is not None else None

    with Session(engine) as session:
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
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    user: User = Depends(resolve_user),
):
    uid = user.id

    today = _today_bkk()
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


class WeightEntryByDateIn(BaseModel):
    entry_date: str  # YYYY-MM-DD
    weight_kg: float
    notes: Optional[str] = None


@app.put("/api/weight-entries/by-date")
def upsert_weight_entry_by_date(body: WeightEntryByDateIn, user: User = Depends(resolve_user)):
    """Upsert a daily bodyweight entry for a given date (atomic).

    Uses INSERT ... ON CONFLICT DO UPDATE against the partial unique index
    ix_weight_entries_user_date_null_time so concurrent requests are handled
    safely by the DB with no SELECT-then-INSERT race window.
    """
    uid = user.id

    if not (20 <= body.weight_kg <= 300):
        raise HTTPException(status_code=422, detail="weight_kg must be between 20 and 300")
    if body.notes is not None and len(body.notes) > 500:
        raise HTTPException(status_code=422, detail="notes must not exceed 500 characters")

    try:
        entry_date = _date.fromisoformat(body.entry_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid entry_date; use YYYY-MM-DD")
    if entry_date > _today_bkk() + _timedelta(days=1):
        raise HTTPException(status_code=422, detail="entry_date cannot be more than 1 day in the future")

    conflict_updates = {
        "weight_kg": body.weight_kg,
        "updated_at": _datetime.now(_timezone.utc),
    }
    if body.notes is not None:
        conflict_updates["notes"] = body.notes

    with Session(engine) as session:
        stmt = (
            _pg_insert(WeightEntry)
            .values(
                user_id=uid,
                entry_date=entry_date,
                entry_time=None,
                weight_kg=body.weight_kg,
                notes=body.notes,
                source="manual",
            )
            .on_conflict_do_update(
                index_elements=["user_id", "entry_date"],
                index_where=WeightEntry.entry_time.is_(None),
                set_=conflict_updates,
            )
            .returning(WeightEntry.__table__.c.id)
        )
        row_id = session.execute(stmt).scalar_one()
        session.commit()
        entry = session.get(WeightEntry, row_id)
        return JSONResponse(_weight_entry_dict(entry))


@app.patch("/api/weight-entries/{entry_id}")
def patch_weight_entry(entry_id: str, body: WeightEntriesPatchIn, user: User = Depends(resolve_user)):
    if "user_id" in body.model_fields_set or "entry_date" in body.model_fields_set:
        raise HTTPException(status_code=422, detail="user_id and entry_date cannot be changed")

    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id")

    with Session(engine) as session:
        entry = session.get(WeightEntry, eid)
        if entry is None or entry.user_id != user.id:
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
def delete_weight_entry(entry_id: str, user: User = Depends(resolve_user)):
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id")

    with Session(engine) as session:
        entry = session.get(WeightEntry, eid)
        if entry is None or entry.user_id != user.id:
            raise HTTPException(status_code=404, detail="Entry not found")
        session.delete(entry)
        session.commit()
    return JSONResponse({"deleted": True})


# ── Weight target endpoints ───────────────────────────────────────────────────

class WeightTargetCreateIn(BaseModel):
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

    # Current weight basis: use the same value the gap calc and the YOU stat use
    # (7-day average by entry_date, latest within 14 days otherwise). The earlier
    # `created_at >= t.created_at` filter wrongly excluded weigh-ins logged before
    # the target was set, falling back to start_weight and reporting 0% progress.
    gap_data = _compute_weight_gap(t, session, today)
    current_basis_kg = gap_data.get("current_basis_kg")
    current_avg_kg = current_basis_kg
    current_weight = current_basis_kg if current_basis_kg is not None else float(t.start_weight_kg)

    kg_lost = float(t.start_weight_kg) - current_weight
    kg_to_go = current_weight - float(t.target_weight_kg)

    if total_kg != 0:
        progress_pct = round(min(max(kg_lost / total_kg * 100, 0), 100), 2)
    else:
        progress_pct = 100.0

    weeks_remaining = days_remaining / 7.0
    required_pace = round(kg_to_go / weeks_remaining, 4) if weeks_remaining > 0 else None

    # Current pace from last 14 days of weight entries logged since target creation
    cutoff_14 = today - _timedelta(days=14)
    entries_14 = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == t.user_id,
            WeightEntry.entry_date >= cutoff_14,
            WeightEntry.created_at >= t.created_at,
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

    milestones = _generate_weight_milestones(t, today)
    hit_date = _project_hit_date(t, session, today)

    base.update({
        "progress_pct": progress_pct,
        "kg_to_go": round(kg_to_go, 2),
        "days_remaining": days_remaining,
        "required_pace_kg_per_week": required_pace,
        "current_pace_kg_per_week": current_pace,
        "projected_end_date": projected_end_date,
        "status_label": status_label,
        "plan_today_kg": gap_data["plan_today_kg"],
        "gap_kg": gap_data["gap_kg"],
        "gap_direction": gap_data["gap_direction"],
        "gap_basis": gap_data["basis"],
        "projected_hit_date": hit_date.isoformat() if hit_date is not None else None,
        "milestones": milestones,
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
def create_weight_target(body: WeightTargetCreateIn, user: User = Depends(resolve_user)):
    uid = user.id

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
def get_active_weight_target(user: User = Depends(resolve_user)):
    uid = user.id
    with Session(engine) as session:
        target = (
            session.query(WeightTarget)
            .filter(WeightTarget.user_id == uid, WeightTarget.status == "active")
            .first()
        )
        if target is None:
            return JSONResponse({"target": None})

        return JSONResponse({"target": _compute_weight_target_active(target, session)})


@app.get("/api/weight-targets/arrival-projection")
def get_weight_target_arrival_projection(user: User = Depends(resolve_user)):
    """Return projected arrival date and rate for the user's active weight plan and goal."""
    with Session(engine) as session:
        result = _resolve_arrival_projection(user.id, session)
    return JSONResponse(result)


@app.get("/api/weight-targets/history")
def get_weight_target_history(
    status: Optional[str] = Query(default=None),
    user: User = Depends(resolve_user),
):
    uid = user.id
    with Session(engine) as session:
        q = session.query(WeightTarget).filter(
            WeightTarget.user_id == uid,
            WeightTarget.status != "active",
        )
        if status is not None:
            q = q.filter(WeightTarget.status == status)
        targets = q.order_by(WeightTarget.ended_at.desc()).all()

        return JSONResponse({"targets": [_weight_target_history_dict(t) for t in targets]})


@app.get("/api/weight-targets/history-summary")
def get_weight_target_history_summary(user: User = Depends(resolve_user)):
    """All-time stats, past attempts comparison, completed target rows, and total entry count."""
    uid = user.id
    with Session(engine) as session:

        completed_targets = (
            session.query(WeightTarget)
            .filter(WeightTarget.user_id == uid, WeightTarget.status != "active")
            .order_by(WeightTarget.ended_at.desc())
            .all()
        )

        active_target = (
            session.query(WeightTarget)
            .filter(WeightTarget.user_id == uid, WeightTarget.status == "active")
            .first()
        )

        total_entries = (
            session.query(func.count(WeightEntry.id))
            .filter(WeightEntry.user_id == uid)
            .scalar()
        ) or 0

        achieved = [t for t in completed_targets if t.status == "achieved"]
        all_count = len(completed_targets)
        achieved_count = len(achieved)
        success_pct = round(achieved_count / all_count * 100, 1) if all_count > 0 else 0.0

        total_kg_lost = 0.0
        for t in completed_targets:
            if t.end_weight_kg is not None:
                lost = float(t.start_weight_kg) - float(t.end_weight_kg)
                if lost > 0:
                    total_kg_lost += lost
        total_kg_lost = round(total_kg_lost, 2)

        avg_pace_kg_per_week = None
        paces = []
        for t in achieved:
            if t.end_weight_kg is not None and t.ended_at is not None:
                s_date = t.start_date if isinstance(t.start_date, _date) else _date.fromisoformat(str(t.start_date))
                e_date = t.ended_at.date() if hasattr(t.ended_at, "date") else t.ended_at
                days = (e_date - s_date).days
                if days > 0:
                    kg_lost = float(t.start_weight_kg) - float(t.end_weight_kg)
                    paces.append(kg_lost / (days / 7))
        if paces:
            avg_pace_kg_per_week = round(sum(paces) / len(paces), 2)

        current_day_count = None
        if active_target:
            s_date = active_target.start_date if isinstance(active_target.start_date, _date) else _date.fromisoformat(str(active_target.start_date))
            current_day_count = (_date.today() - s_date).days + 1

        past_attempts = []
        for t in achieved:
            if t.end_weight_kg is not None and t.ended_at is not None:
                s_date = t.start_date if isinstance(t.start_date, _date) else _date.fromisoformat(str(t.start_date))
                e_date = t.ended_at.date() if hasattr(t.ended_at, "date") else t.ended_at
                days = (e_date - s_date).days
                kg_lost = float(t.start_weight_kg) - float(t.end_weight_kg)
                pace = round(kg_lost / (days / 7), 2) if days > 0 else None
                past_attempts.append({
                    "day_count": days,
                    "kg_lost": round(kg_lost, 2),
                    "pace_kg_per_week": pace,
                })

        target_rows = []
        for t in completed_targets:
            s_date = t.start_date if isinstance(t.start_date, _date) else _date.fromisoformat(str(t.start_date))
            result_weight = float(t.end_weight_kg) if t.end_weight_kg is not None else None
            delta_kg = round(result_weight - float(t.start_weight_kg), 2) if result_weight is not None else None
            if t.ended_at:
                e_date = t.ended_at.date() if hasattr(t.ended_at, "date") else t.ended_at
                days = (e_date - s_date).days
                end_date_str = str(e_date)
            else:
                days = None
                end_date_str = None
            target_rows.append({
                "id": str(t.id),
                "status": t.status,
                "start_weight_kg": float(t.start_weight_kg),
                "target_weight_kg": float(t.target_weight_kg),
                "start_date": str(s_date),
                "end_date": end_date_str,
                "days": days,
                "result_weight_kg": result_weight,
                "delta_kg": delta_kg,
            })

        # "Targets set" is the total ever created — include the active one, else a
        # user with only a current (unfinished) target sees 0 and it looks broken.
        # success_pct / achieved stay relative to FINISHED targets only.
        targets_set = all_count + (1 if active_target else 0)

        return JSONResponse({
            "stats": {
                "targets_set": targets_set,
                "targets_achieved": achieved_count,
                "success_pct": success_pct,
                "total_kg_lost": total_kg_lost,
                "avg_pace_kg_per_week": avg_pace_kg_per_week,
                "current_day_count": current_day_count,
            },
            "past_attempts": past_attempts,
            "targets": target_rows,
            "total_entries": total_entries,
        })


@app.patch("/api/weight-targets/{target_id}")
def patch_weight_target(target_id: str, body: WeightTargetPatchIn, user: User = Depends(resolve_user)):
    if "start_weight_kg" in body.model_fields_set or "start_date" in body.model_fields_set:
        raise HTTPException(status_code=422, detail="start_weight_kg and start_date cannot be changed")

    try:
        tid = _uuid.UUID(target_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target_id")

    with Session(engine) as session:
        target = session.get(WeightTarget, tid)
        if target is None or target.user_id != user.id:
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
def end_weight_target(target_id: str, body: WeightTargetEndIn, user: User = Depends(resolve_user)):
    if body.status not in ("achieved", "abandoned"):
        raise HTTPException(status_code=422, detail="status must be 'achieved' or 'abandoned'")

    try:
        tid = _uuid.UUID(target_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target_id")

    with Session(engine) as session:
        target = session.get(WeightTarget, tid)
        if target is None or target.user_id != user.id:
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


# ── Weight target what-if simulation ──────────────────────────────────────────

class WeightTargetWhatIfIn(BaseModel):
    assumed_rate: float


@app.post("/api/weight-targets/{goal_id}/what-if")
def weight_target_what_if(goal_id: str, body: WeightTargetWhatIfIn, user: User = Depends(resolve_user)):
    import math as _math
    from backend.services.weight_what_if import simulate_what_if as _simulate_what_if

    try:
        gid = _uuid.UUID(goal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid goal_id")

    with Session(engine) as session:
        goal = session.get(WeightTarget, gid)
        if goal is None or goal.user_id != user.id or goal.status != "active":
            raise HTTPException(status_code=404, detail="No active goal found for the given goal_id")

        assumed_rate = body.assumed_rate

        if not _math.isfinite(assumed_rate):
            raise HTTPException(status_code=422, detail="assumed_rate must be a finite number")
        if assumed_rate == 0:
            raise HTTPException(status_code=422, detail="assumed_rate must be non-zero; a zero rate would never reach the goal")

        # Direction validation: rate must progress toward the target
        total_kg_signed = float(goal.target_weight_kg) - float(goal.start_weight_kg)
        if total_kg_signed == 0:
            raise HTTPException(status_code=422, detail="Goal has no direction (start and target weights are identical)")
        required_positive = total_kg_signed > 0
        if required_positive and assumed_rate < 0:
            raise HTTPException(
                status_code=422,
                detail="assumed_rate direction is invalid: goal requires a positive rate (weight gain) but a negative rate was provided",
            )
        if not required_positive and assumed_rate > 0:
            raise HTTPException(
                status_code=422,
                detail="assumed_rate direction is invalid: goal requires a negative rate (weight loss) but a positive rate was provided",
            )

        # Magnitude validation: cap at 10× implied goal rate or 20 kg/week hard cap
        total_weeks = max(1.0, abs((goal.target_date - goal.start_date).days) / 7.0)
        implied_rate = abs(total_kg_signed) / total_weeks
        magnitude_cap = min(implied_rate * 10, 20.0)
        if abs(assumed_rate) > magnitude_cap:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"assumed_rate magnitude ({abs(assumed_rate):.4g} kg/week) exceeds the allowed bound "
                    f"({magnitude_cap:.4g} kg/week); provide a more realistic rate"
                ),
            )

        # Fetch the most recent weight entry to anchor the simulation
        today = _date.today()
        latest_entry = (
            session.query(WeightEntry)
            .filter(WeightEntry.user_id == user.id, WeightEntry.entry_date <= today)
            .order_by(WeightEntry.entry_date.desc())
            .first()
        )
        if latest_entry is None:
            raise HTTPException(status_code=422, detail="No weight entries available to anchor the simulation; log a weight first")

        actual_trend = {today: float(latest_entry.weight_kg)}
        goal_weight_kg = float(goal.target_weight_kg)

    # All DB work is done — no further DB access below this line
    result = _simulate_what_if(
        actual_trend=actual_trend,
        goal_weight_kg=goal_weight_kg,
        assumed_rate_kg_per_week=assumed_rate,
        today=today,
    )

    if not result.get("projected_line"):
        reason = result.get("reason", "Simulation could not be completed")
        raise HTTPException(status_code=422, detail=reason)

    simulated_line = [
        {"date": str(pt["date"]), "weight": pt["weight"]}
        for pt in result["projected_line"]
    ]
    arrival_date = str(result["arrival_date"]) if result["arrival_date"] else None

    return JSONResponse({"simulated_line": simulated_line, "arrival_date": arrival_date})


# ── Weight plan endpoints (issue #864) ────────────────────────────────────────

class WeightPlanCreateIn(BaseModel):
    start_weight: float
    goal_weight: float
    start_date: str          # YYYY-MM-DD
    goal_date: Optional[str] = None   # YYYY-MM-DD; may be omitted when rate is given
    rate: Optional[float] = None      # target_rate_kg_per_week; may be omitted when goal_date is given
    phase: Optional[str] = "cut"      # "cut" | "bulk" | "maintain"


class WeightPlanPatchIn(BaseModel):
    goal_weight: Optional[float] = None
    goal_date: Optional[str] = None
    rate: Optional[float] = None
    phase: Optional[str] = None


def _weight_plan_dict(p: WeightPlan) -> dict:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "start_date": str(p.start_date),
        "start_weight": float(p.start_weight_kg),
        "goal_weight": float(p.goal_weight_kg),
        "goal_date": str(p.goal_date) if p.goal_date is not None else None,
        "rate": float(p.target_rate_kg_per_week) if p.target_rate_kg_per_week is not None else None,
        "phase": p.phase,
        "active": p.active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _validate_weight_plan_fields(
    start_weight: Optional[float],
    goal_weight: Optional[float],
    rate: Optional[float],
    start_date_str: Optional[str],
    goal_date_str: Optional[str],
    phase: Optional[str],
) -> None:
    """Raise HTTPException 422 with a field-specific message if validation fails."""
    if start_weight is not None and start_weight <= 0:
        raise HTTPException(status_code=422, detail={"field": "start_weight", "msg": "start_weight must be positive"})
    if goal_weight is not None and goal_weight <= 0:
        raise HTTPException(status_code=422, detail={"field": "goal_weight", "msg": "goal_weight must be positive"})
    if rate is not None and rate <= 0:
        raise HTTPException(status_code=422, detail={"field": "rate", "msg": "rate must be positive"})

    start_date = None
    if start_date_str is not None:
        try:
            start_date = _date.fromisoformat(start_date_str)
        except ValueError:
            raise HTTPException(status_code=422, detail={"field": "start_date", "msg": "start_date must be YYYY-MM-DD"})

    goal_date = None
    if goal_date_str is not None:
        try:
            goal_date = _date.fromisoformat(goal_date_str)
        except ValueError:
            raise HTTPException(status_code=422, detail={"field": "goal_date", "msg": "goal_date must be YYYY-MM-DD"})

    if start_date is not None and goal_date is not None and start_date >= goal_date:
        raise HTTPException(status_code=422, detail={"field": "start_date", "msg": "start_date must be before goal_date"})

    if phase is not None and start_weight is not None and goal_weight is not None:
        if phase == "cut" and goal_weight >= start_weight:
            raise HTTPException(
                status_code=422,
                detail={"field": "goal_weight", "msg": "cut phase requires goal_weight < start_weight"},
            )
        if phase == "bulk" and goal_weight <= start_weight:
            raise HTTPException(
                status_code=422,
                detail={"field": "goal_weight", "msg": "bulk phase requires goal_weight > start_weight"},
            )


@app.post("/api/weight-plans", status_code=201)
def create_weight_plan(body: WeightPlanCreateIn, user: User = Depends(resolve_user)):
    _validate_weight_plan_fields(
        start_weight=body.start_weight,
        goal_weight=body.goal_weight,
        rate=body.rate,
        start_date_str=body.start_date,
        goal_date_str=body.goal_date,
        phase=body.phase,
    )
    start_date = _date.fromisoformat(body.start_date)
    goal_date = _date.fromisoformat(body.goal_date) if body.goal_date else None

    with Session(engine) as session:
        plan = _wp_repo.create_plan(
            session,
            user_id=user.id,
            start_date=start_date,
            start_weight_kg=body.start_weight,
            goal_weight_kg=body.goal_weight,
            goal_date=goal_date,
            target_rate_kg_per_week=body.rate,
            phase=body.phase or "cut",
        )
        session.commit()
        session.refresh(plan)
        return JSONResponse(status_code=201, content=_weight_plan_dict(plan))


@app.get("/api/weight-plans/active")
def get_active_weight_plan(user: User = Depends(resolve_user)):
    with Session(engine) as session:
        plan = _wp_repo.get_active_plan(session, user.id)
        if plan is None:
            raise HTTPException(status_code=404, detail="No active weight plan")
        return JSONResponse(_weight_plan_dict(plan))


@app.patch("/api/weight-plans/{plan_id}")
def patch_weight_plan(plan_id: str, body: WeightPlanPatchIn, user: User = Depends(resolve_user)):
    try:
        pid = _uuid.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan_id")

    with Session(engine) as session:
        plan = _wp_repo.get_plan_by_id(session, pid)
        if plan is None:
            raise HTTPException(status_code=404, detail="Weight plan not found")
        if plan.user_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Resolve effective values after potential update for direction validation
        new_goal_weight = body.goal_weight if body.goal_weight is not None else float(plan.goal_weight_kg)
        new_start_weight = float(plan.start_weight_kg)
        new_phase = body.phase if body.phase is not None else plan.phase
        new_goal_date = body.goal_date  # may stay None
        new_rate = body.rate

        _validate_weight_plan_fields(
            start_weight=new_start_weight,
            goal_weight=new_goal_weight,
            rate=new_rate,
            start_date_str=None,
            goal_date_str=new_goal_date,
            phase=new_phase,
        )

        fields: dict = {}
        if body.goal_weight is not None:
            fields["goal_weight_kg"] = body.goal_weight
        if body.goal_date is not None:
            fields["goal_date"] = _date.fromisoformat(body.goal_date)
        if body.rate is not None:
            fields["target_rate_kg_per_week"] = body.rate
        if body.phase is not None:
            fields["phase"] = body.phase

        plan = _wp_repo.update_plan(session, plan, fields)
        session.commit()
        session.refresh(plan)
        return JSONResponse(_weight_plan_dict(plan))


@app.delete("/api/weight-plans/{plan_id}")
def delete_weight_plan(plan_id: str, user: User = Depends(resolve_user)):
    try:
        pid = _uuid.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan_id")

    with Session(engine) as session:
        plan = _wp_repo.get_plan_by_id(session, pid)
        if plan is None:
            raise HTTPException(status_code=404, detail="Weight plan not found")
        if plan.user_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        plan = _wp_repo.deactivate_plan(session, plan)
        session.commit()
        session.refresh(plan)
        return JSONResponse(_weight_plan_dict(plan))


# ── Training plan endpoints (issue #1101) ──────────────────────────────────────

class TrainingPlanCreateIn(BaseModel):
    name: str
    ramp_rate: Optional[float] = None
    taper_start: Optional[float] = None
    taper_length: Optional[float] = None
    taper_shape: Optional[str] = None


class TrainingPlanPatchIn(BaseModel):
    name: Optional[str] = None
    ramp_rate: Optional[float] = None
    taper_start: Optional[float] = None
    taper_length: Optional[float] = None
    taper_shape: Optional[str] = None


def _training_plan_dict(p: TrainingPlan) -> dict:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "name": p.name,
        "ramp_rate": float(p.ramp_rate) if p.ramp_rate is not None else None,
        "taper_start": float(p.taper_start) if p.taper_start is not None else None,
        "taper_length": float(p.taper_length) if p.taper_length is not None else None,
        "taper_shape": p.taper_shape,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _validate_taper_shape(taper_shape: Optional[str]) -> None:
    if taper_shape is not None and taper_shape not in TAPER_SHAPE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"taper_shape must be one of {list(TAPER_SHAPE_VALUES)} or null",
        )


def _validate_ramp_rate(ramp_rate: Optional[float]) -> None:
    if ramp_rate is not None and ramp_rate < 0:
        raise HTTPException(status_code=422, detail="ramp_rate must be >= 0")


def _validate_taper_length(taper_length: Optional[float]) -> None:
    if taper_length is not None and taper_length < 0:
        raise HTTPException(status_code=422, detail="taper_length must be >= 0")


@app.get("/api/plans")
def list_training_plans(user: User = Depends(resolve_user)):
    with Session(engine) as session:
        plans = session.query(TrainingPlan).filter(TrainingPlan.user_id == user.id).all()
        return JSONResponse([_training_plan_dict(p) for p in plans])


@app.post("/api/plans", status_code=201)
def create_training_plan(body: TrainingPlanCreateIn, user: User = Depends(resolve_user)):
    _validate_taper_shape(body.taper_shape)
    _validate_ramp_rate(body.ramp_rate)
    _validate_taper_length(body.taper_length)
    with Session(engine) as session:
        plan = TrainingPlan(
            user_id=user.id,
            name=body.name,
            ramp_rate=body.ramp_rate,
            taper_start=body.taper_start,
            taper_length=body.taper_length,
            taper_shape=body.taper_shape,
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        return JSONResponse(status_code=201, content=_training_plan_dict(plan))


@app.get("/api/plans/{plan_id}")
def get_training_plan(plan_id: str, user: User = Depends(resolve_user)):
    try:
        pid = _uuid.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan_id")
    with Session(engine) as session:
        plan = session.get(TrainingPlan, pid)
        if plan is None:
            raise HTTPException(status_code=404, detail="Training plan not found")
        if plan.user_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        return JSONResponse(_training_plan_dict(plan))


@app.patch("/api/plans/{plan_id}")
def patch_training_plan(plan_id: str, body: TrainingPlanPatchIn, user: User = Depends(resolve_user)):
    try:
        pid = _uuid.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan_id")
    _validate_taper_shape(body.taper_shape)
    _validate_ramp_rate(body.ramp_rate)
    _validate_taper_length(body.taper_length)
    with Session(engine) as session:
        plan = session.get(TrainingPlan, pid)
        if plan is None:
            raise HTTPException(status_code=404, detail="Training plan not found")
        if plan.user_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        if body.name is not None:
            plan.name = body.name
        if body.ramp_rate is not None:
            plan.ramp_rate = body.ramp_rate
        if body.taper_start is not None:
            plan.taper_start = body.taper_start
        if body.taper_length is not None:
            plan.taper_length = body.taper_length
        if body.taper_shape is not None:
            plan.taper_shape = body.taper_shape
        session.commit()
        session.refresh(plan)
        return JSONResponse(_training_plan_dict(plan))


# ── Body-modifier guardrail endpoint (issue #1161) ────────────────────────────

@app.get("/api/body-modifier/guardrail")
def get_body_modifier_guardrail(user: User = Depends(resolve_user)):
    """Return the body-modifier guardrail warning state for the authenticated user.

    Warns when weight-loss velocity is excessive or energy availability (EA) falls
    into the penalty region.  The result is framed as a performance/health risk
    and auto-clears when both conditions return to safe bounds.

    Response keys:
      guardrail_state   — "warn" or "ok"
      guardrail_message — plain-English risk message (empty string when "ok")
      in_penalty_loss   — True when loss rate exceeds the penalty-zone threshold
      in_penalty_ea     — True when EA proxy is below the penalty-region boundary
    """
    result = get_body_modifier_guardrail_for_user(user.id)
    return JSONResponse(result)


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
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    include_target: bool = Query(default=True),
    range_token: Optional[str] = Query(default=None, alias="range"),
    include_future_zone: bool = Query(default=False),
    user: User = Depends(resolve_user),
):
    uid = user.id

    # Day offsets for each range token use (N-1) so that both from_d and to_d
    # are included in the range (inclusive semantics): e.g. "7D" spans 7 days
    # from (today - 6) through today inclusive.  "ALL" is omitted because its
    # from_d is resolved dynamically from the earliest entry date.
    RANGE_OFFSETS = {
        "7D": 6,    # 7 days inclusive
        "30D": 29,  # 30 days inclusive
        "90D": 89,  # 90 days inclusive
        "6M": 183,  # ~6 calendar months inclusive
        "1Y": 364,  # 365 days inclusive
    }
    _VALID_RANGE_TOKENS = {*RANGE_OFFSETS, "ALL"}
    today = _today_bkk()
    if range_token is not None:
        if range_token not in _VALID_RANGE_TOKENS:
            raise HTTPException(
                status_code=422,
                detail=f"range must be one of: {', '.join(sorted(_VALID_RANGE_TOKENS))}",
            )
        to_d = today
        if range_token in RANGE_OFFSETS:
            from_d = today - _timedelta(days=RANGE_OFFSETS[range_token])
        else:  # ALL — from_d resolved inside session after earliest-entry lookup
            from_d = None
    elif from_date is None and to_date is None:
        from_d = today - _timedelta(days=89)
        to_d = today
    else:
        try:
            from_d = _date.fromisoformat(from_date) if from_date else today - _timedelta(days=89)
            to_d = _date.fromisoformat(to_date) if to_date else today
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format; use YYYY-MM-DD")

    # 365-day cap applies only for explicit from/to params; range tokens have predefined lengths
    if range_token is None and (to_d - from_d).days > 365:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 365 days")

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Resolve ALL range token: from_d = earliest entry date (or 90-day fallback)
        if range_token == "ALL":
            _earliest = (
                session.query(WeightEntry)
                .filter(WeightEntry.user_id == uid)
                .order_by(WeightEntry.entry_date.asc())
                .first()
            )
            if _earliest is not None:
                from_d = (
                    _earliest.entry_date
                    if isinstance(_earliest.entry_date, _date)
                    else _date.fromisoformat(str(_earliest.entry_date))
                )
            else:
                from_d = today - _timedelta(days=89)

        # Fetch entries wide enough for trend MA (6 days before from) and delta stats (36 days before to).
        # Always extend upper bound to today so logged_today / today_marker are always accurate.
        fetch_start = min(from_d - _timedelta(days=6), to_d - _timedelta(days=36))
        fetch_end = max(to_d, today)
        all_entries = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date >= fetch_start,
                WeightEntry.entry_date <= fetch_end,
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
            if d < from_d or d > to_d:
                continue
            actuals.append({"date": str(d), "weight_kg": float(e.weight_kg), "entry_id": str(e.id)})

        # Trend: dense, one point per day in [from_d, to_d]; null when window is empty
        num_days = (to_d - from_d).days + 1
        trend = []
        for i in range(num_days):
            day = from_d + _timedelta(days=i)
            trend.append({"date": str(day), "weight_kg": _ma_for_day(day)})

        # EWMA series: compute on ALL fetched entries (includes warmup before from_d for
        # convergence) then build a dense daily series for [from_d, to_d] carrying the
        # last EWMA value forward on days without entries.
        _ewma_input = [
            {
                "date": (e.entry_date if isinstance(e.entry_date, _date) else _date.fromisoformat(str(e.entry_date))),
                "weight_kg": float(e.weight_kg),
            }
            for e in all_entries
        ]
        _ewma_raw_values = _compute_ewma(_ewma_input)
        _ewma_by_date: dict = {e["date"]: v for e, v in zip(_ewma_input, _ewma_raw_values)}
        ewma_series = []
        _last_ewma: float | None = None
        for i in range(num_days):
            day = from_d + _timedelta(days=i)
            if day in _ewma_by_date:
                _last_ewma = round(_ewma_by_date[day], 4)
            ewma_series.append({"date": str(day), "weight_kg": _last_ewma})

        # Weekly rate derived from EWMA slope: ewma at to_d minus ewma 7 days earlier.
        # This reflects trend momentum, not a raw entry-to-entry delta.
        _ewma_non_null = [(i, p["weight_kg"]) for i, p in enumerate(ewma_series) if p["weight_kg"] is not None]
        weekly_rate_ewma_kg: float | None = None
        if len(_ewma_non_null) >= 2:
            _last_ewma_idx, _last_ewma_val = _ewma_non_null[-1]
            _target_earlier_idx = _last_ewma_idx - 7
            _earlier_candidates = [(i, v) for i, v in _ewma_non_null if i <= max(_target_earlier_idx, 0)]
            if _earlier_candidates and _target_earlier_idx >= 0:
                _, _earlier_ewma_val = _earlier_candidates[-1]
                weekly_rate_ewma_kg = round(_last_ewma_val - _earlier_ewma_val, 3)

        # Stats
        in_range = [e for e in all_entries if (
            from_d
            <= (e.entry_date if isinstance(e.entry_date, _date) else _date.fromisoformat(str(e.entry_date)))
            <= to_d
        )]
        current_weight_kg = float(in_range[-1].weight_kg) if in_range else None

        current_avg_kg = None
        for t in reversed(trend):
            if t["weight_kg"] is not None:
                current_avg_kg = t["weight_kg"]
                break

        # delta: compare current weight to most recent entry on/before the pivot date
        pivot_7d = to_d - _timedelta(days=7)
        pivot_30d = to_d - _timedelta(days=30)
        entry_at_7d = None
        entry_at_30d = None
        for e in reversed(all_entries):
            ed = e.entry_date if isinstance(e.entry_date, _date) else _date.fromisoformat(str(e.entry_date))
            if entry_at_7d is None and ed <= pivot_7d:
                entry_at_7d = e
            if entry_at_30d is None and ed <= pivot_30d:
                entry_at_30d = e
            if entry_at_7d is not None and entry_at_30d is not None:
                break

        delta_7d_kg = (
            round(current_weight_kg - float(entry_at_7d.weight_kg), 2)
            if current_weight_kg is not None and entry_at_7d is not None
            else None
        )
        delta_30d_kg = (
            round(current_weight_kg - float(entry_at_30d.weight_kg), 2)
            if current_weight_kg is not None and entry_at_30d is not None
            else None
        )

        stats = {
            "current_weight_kg": current_weight_kg,
            "current_avg_kg": current_avg_kg,
            "delta_7d_kg": delta_7d_kg,
            "delta_30d_kg": delta_30d_kg,
            "weekly_rate_ewma_kg": weekly_rate_ewma_kg,
            "ewma_alpha": round(2.0 / (_EWMA_DEFAULT_SPAN + 1), 4),
        }

        # Always fetch active target (needed for plan_series / milestones / today_marker)
        active_target = (
            session.query(WeightTarget)
            .filter(WeightTarget.user_id == uid, WeightTarget.status == "active")
            .first()
        )

        # ── Plan series (one point per day from plan inception; omitted when no target) ─────
        # Starts from max(from_d, plan_start_date) so pre-plan dates are excluded.
        if active_target is not None:
            _ps_start = (
                active_target.start_date
                if isinstance(active_target.start_date, _date)
                else _date.fromisoformat(str(active_target.start_date))
            )
            _ps_from = max(from_d, _ps_start)
            _ps_days = (to_d - _ps_from).days + 1
            plan_series = [
                {
                    "date": str(_ps_from + _timedelta(days=i)),
                    "plan_kg": float(round(_weight_plan_at(active_target, _ps_from + _timedelta(days=i)), 2)),
                }
                for i in range(max(0, _ps_days))
            ]

        # ── Future milestones (always an array; exclude today row) ───────────────
        if active_target is not None:
            future_milestones = [
                m for m in _generate_weight_milestones(active_target, today)
                if m["kind"] != "today"
            ]
        else:
            future_milestones = []

        # ── Today marker ──────────────────────────────────────────────────────
        today_vals = date_weights.get(today, [])
        today_actual_kg = round(sum(today_vals) / len(today_vals), 2) if today_vals else None
        if active_target is not None:
            gap_data = _compute_weight_gap(active_target, session, today)
            today_marker = {
                "date": str(today),
                "actual_kg": today_actual_kg,
                "trend_kg": _ma_for_day(today),
                "plan_kg": gap_data["plan_today_kg"],
                "gap_kg": gap_data["gap_kg"],
                "gap_direction": gap_data["gap_direction"],
            }
        else:
            today_marker = {
                "date": str(today),
                "actual_kg": today_actual_kg,
                "trend_kg": _ma_for_day(today),
                "plan_kg": None,
                "gap_kg": None,
                "gap_direction": None,
            }

        # ── Logged today / today delta ─────────────────────────────────────────
        logged_today = today in date_weights
        yesterday = today - _timedelta(days=1)
        yesterday_vals = date_weights.get(yesterday, [])
        if today_vals and yesterday_vals:
            today_delta_kg = round(
                sum(today_vals) / len(today_vals) - sum(yesterday_vals) / len(yesterday_vals), 2
            )
        else:
            today_delta_kg = None

        # ── Past actuals: every weigh-in strictly before from_d (the "past" zone) ──
        # Greyed historical context. Downsampled to keep the payload bounded;
        # empty when there is no earlier history (e.g. the ALL range).
        _past_rows = (
            session.query(WeightEntry)
            .filter(WeightEntry.user_id == uid, WeightEntry.entry_date < from_d)
            .order_by(WeightEntry.entry_date.asc(), WeightEntry.entry_time.asc())
            .all()
        )
        _PAST_MAX = 150
        if len(_past_rows) > _PAST_MAX:
            _stride = len(_past_rows) / _PAST_MAX
            _past_rows = [_past_rows[int(i * _stride)] for i in range(_PAST_MAX)]
        past_actuals = [
            {
                "date": str(
                    e.entry_date if isinstance(e.entry_date, _date)
                    else _date.fromisoformat(str(e.entry_date))
                ),
                "weight_kg": float(e.weight_kg),
            }
            for e in _past_rows
        ]

        # plan_series is omitted (key absent) when no active target
        result = {
            "range": {"from": str(from_d), "to": str(to_d)},
            "actuals": actuals,
            "past_actuals": past_actuals,
            "trend": trend,
            "ewma": ewma_series,
            "stats": stats,
            "future_milestones": future_milestones,
            "today_marker": today_marker,
            "logged_today": logged_today,
            "today_delta_kg": today_delta_kg,
            "include_future_zone": include_future_zone,
        }
        if active_target is not None:
            result["plan_series"] = plan_series

        if include_target:
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

                start_date_d = (
                    active_target.start_date
                    if isinstance(active_target.start_date, _date)
                    else _date.fromisoformat(str(active_target.start_date))
                )
                target_block = {
                    "target_weight_kg": target_weight,
                    "target_date": str(target_date),
                    "start_weight_kg": float(active_target.start_weight_kg),
                    "start_date": str(start_date_d),
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

    # sparkline: last 7 days of actual daily average weights (non-null days only)
    sparkline = []
    for i in range(7):
        day = today - _timedelta(days=6 - i)
        if day in date_weights:
            vals = date_weights[day]
            sparkline.append({"date": str(day), "value": round(sum(vals) / len(vals), 2)})

    # gap_kg and status_label at top level
    top_status_label: Optional[str] = None
    gap_kg: Optional[float] = None

    target_info = None
    if active_target:
        status_label = _compute_status_label(active_target, avg_7d, today)
        top_status_label = status_label
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
        sd = active_target.start_date if isinstance(active_target.start_date, _date) else _date.fromisoformat(str(active_target.start_date))
        total_days = (td - sd).days

        # Compute gap_kg: avg_7d vs expected trajectory at today
        if avg_7d is not None and total_days > 0:
            elapsed = (today - sd).days
            t_frac = elapsed / total_days
            expected_today = start_w + (target_w - start_w) * t_frac
            gap_kg = round(avg_7d - expected_today, 2)

        # plan: 7-day expected trajectory points for the sparkline window
        plan = []
        if total_days > 0:
            for i in range(7):
                day = today - _timedelta(days=6 - i)
                elapsed_i = (day - sd).days
                t_i = elapsed_i / total_days
                expected_i = start_w + (target_w - start_w) * t_i
                plan.append({"date": str(day), "value": round(expected_i, 2)})
        else:
            plan = []

        # kg_to_go: abs(current_weight - target_weight_kg)
        kg_to_go = round(abs((current_weight if current_weight is not None else start_w) - target_w), 2)

        target_info = {
            "direction": direction,
            "target_weight_kg": target_w,
            "target_date": str(td),
            "progress_pct": progress_pct,
            "status_label": status_label,
            "kg_to_go": kg_to_go,
        }
    else:
        plan = []

    return JSONResponse({
        "current_weight": current_weight,
        "last_entry_kg": current_weight,
        "avg_7d": avg_7d,
        "delta_week": delta_week,
        "weekly_rate_kg": delta_week,
        "delta_month": delta_month,
        "status_label": top_status_label,
        "gap_kg": gap_kg,
        "sparkline": sparkline,
        "plan": plan,
        "target": target_info,
        "ma30": ma30,
    })


# ── Home recent-workouts endpoint ─────────────────────────────────────────────

@app.get("/api/home/recent-workouts")
def get_home_recent_workouts(
    limit: int = Query(default=5, ge=1, le=10),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

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
        try:
            d["zone2_minutes"] = int(w.zone2_minutes) if w.zone2_minutes is not None else None
        except Exception:
            d["zone2_minutes"] = None
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
    tracks: str = Query(default=None),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

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

        # All-time best value
        if track_type == "time":
            pb_rec = min(recs, key=lambda r: float(r.value_numeric))
        else:
            pb_rec = max(recs, key=lambda r: float(r.value_numeric))
        pb_value = float(pb_rec.value_numeric)
        pb_formatted = _format_pr_time(pb_value) if track_type == "time" else _format_pr_weight(pb_value)
        pb_date = pb_rec.achieved_on.isoformat() if pb_rec.achieved_on else None

        # Improvement delta: only when latest entry IS the all-time best and a prior entry exists
        delta_formatted = None
        is_pr_improvement = False
        if pb_rec.id == recs[0].id and len(recs) >= 2:
            prev_val = float(recs[1].value_numeric)
            if track_type == "time":
                delta_secs = prev_val - pb_value
                if delta_secs > 0:
                    delta_formatted = "−" + _format_pr_time(delta_secs)
                    is_pr_improvement = True
            else:
                delta_diff = pb_value - prev_val
                if delta_diff > 0:
                    delta_formatted = "+" + _format_pr_weight(delta_diff)
                    is_pr_improvement = True

        result.append({
            "track_key": tk,
            "track_name": latest.track_name,
            "track_type": track_type,
            "current_value": current_value,
            "current_value_formatted": formatted,
            "achieved_on": latest.achieved_on.isoformat() if latest.achieved_on else None,
            "pb_value": pb_value,
            "pb_value_formatted": pb_formatted,
            "pb_date": pb_date,
            "delta_formatted": delta_formatted,
            "is_pr_improvement": is_pr_improvement,
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
    date: Optional[str] = Query(default=None),
    current_user: User = Depends(resolve_user),
):
    # Score formula: sleep_hours 30%, hrv 25%, rhr 20%, mood 15%, energy 10%
    # Per-factor: sleep/HRV/RHR compare vs 7d rolling avg; mood/energy: raw value × 20
    uid = current_user.id

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

    factors_for_explanation = [
        {"factor": "sleep_hours", "value": float(metrics.sleep_hours) if metrics.sleep_hours is not None else None,
         "score": sleep_score, "impact": _impact(sleep_score)},
        {"factor": "hrv", "value": float(metrics.hrv) if metrics.hrv is not None else None,
         "score": hrv_score, "impact": _impact(hrv_score)},
        {"factor": "rhr", "value": float(metrics.resting_hr) if metrics.resting_hr is not None else None,
         "score": rhr_score, "impact": _impact(rhr_score)},
        {"factor": "mood", "value": float(metrics.mood) if metrics.mood is not None else None,
         "score": mood_score, "impact": _impact(mood_score)},
        {"factor": "energy", "value": float(metrics.energy) if metrics.energy is not None else None,
         "score": energy_score, "impact": _impact(energy_score)},
    ]
    explanation_facts = {
        "score": score,
        "label": _readiness_score_label(score),
        "sleep_hours": float(metrics.sleep_hours) if metrics.sleep_hours is not None else None,
        "hrv": float(metrics.hrv) if metrics.hrv is not None else None,
        "rhr": float(metrics.resting_hr) if metrics.resting_hr is not None else None,
        "sleep_quality": float(metrics.sleep_quality) if metrics.sleep_quality is not None else None,
        "energy": float(metrics.energy) if metrics.energy is not None else None,
        "mood": float(metrics.mood) if metrics.mood is not None else None,
        "sleep_hours_baseline": rolling_baseline["sleep_7d_avg_hours"],
        "hrv_baseline": rolling_baseline["hrv_7d_avg"],
        "rhr_baseline": rolling_baseline["rhr_7d_avg"],
    }
    from backend.services.readiness_explanation import get_readiness_explanation
    explanation = get_readiness_explanation(
        user_id=str(uid),
        target_date=query_date.isoformat(),
        facts=explanation_facts,
        fallback_factors=factors_for_explanation,
    )

    return JSONResponse({
        "date": query_date.isoformat(),
        "score": score,
        "score_label": _readiness_score_label(score),
        "contributors": contributors,
        "rolling_baseline": rolling_baseline,
        "explanation": explanation,
    })


# ── Home weekly-summary endpoint ──────────────────────────────────────────────

_WK_TYPE_BUCKETS = ("run", "lift", "wod", "bike")


@app.get("/api/home/weekly-summary")
def get_home_weekly_summary(
    week_start: Optional[str] = Query(default=None),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

    if week_start is None:
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


# ── Weekly summary narrative endpoint (issue #1314) ──────────────────────────

@app.get("/api/weekly-summary")
def get_weekly_summary(
    week: Optional[str] = Query(default=None),
    current_user: User = Depends(resolve_user),
):
    """Return a coach-style weekly narrative + key facts.

    week: ISO date of the week's Monday (defaults to current week start).
    Response: {week_start, facts, narrative, source: "llm"|"fallback"}
    """
    from datetime import date as _date_cls, timedelta as _td
    from backend.services.weekly_summary import (
        assemble_facts,
        get_narrative,
        build_response,
    )
    from backend.services.guardrail import get_guardrail_result
    from backend.services.training_load import current_load

    uid = current_user.id

    if week is None:
        _bkk = ZoneInfo("Asia/Bangkok")
        today_bkk = _datetime.now(_bkk).date()
        week_start = today_bkk - _timedelta(days=today_bkk.weekday())
    else:
        try:
            week_start = _date_cls.fromisoformat(week)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid week format; use YYYY-MM-DD")

    week_end = week_start + _timedelta(days=6)
    prev_week_start = week_start - _timedelta(days=7)
    prev_week_end = week_start - _timedelta(days=1)

    with Session(engine) as session:
        from backend.models import PersonalRecord

        curr_workouts_orm = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= week_start,
                Workout.workout_date <= week_end,
            )
            .all()
        )
        prev_workouts_orm = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= prev_week_start,
                Workout.workout_date <= prev_week_end,
            )
            .all()
        )
        prs_orm = (
            session.query(PersonalRecord)
            .filter(
                PersonalRecord.user_id == uid,
                PersonalRecord.achieved_on >= week_start,
                PersonalRecord.achieved_on <= week_end,
            )
            .all()
        )

        def _w_dict(w):
            return {
                "workout_date": w.workout_date.isoformat() if w.workout_date else None,
                "tss": float(w.tss) if w.tss is not None else None,
                "distance_km": float(w.distance_km) if w.distance_km is not None else None,
                "duration_seconds": w.duration_seconds,
                "workout_type": w.workout_type or "",
            }

        curr_workouts = [_w_dict(w) for w in curr_workouts_orm]
        prev_workouts = [_w_dict(w) for w in prev_workouts_orm]
        prs = [
            {
                "track_name": pr.track_name,
                "track_key": pr.track_key,
                "value_numeric": str(pr.value_numeric),
                "achieved_on": pr.achieved_on.isoformat() if pr.achieved_on else None,
            }
            for pr in prs_orm
        ]

    # CTL/ATL/TSB at week start and end
    load_start = current_load(str(uid), as_of=prev_week_end)
    load_end = current_load(str(uid), as_of=week_end)

    # Guardrail flags for the current week
    guardrail = get_guardrail_result(str(uid), as_of_date=week_end)

    facts = assemble_facts(
        week_start=week_start,
        current_workouts=curr_workouts,
        prev_workouts=prev_workouts,
        ctl_start=load_start["ctl"],
        ctl_end=load_end["ctl"],
        atl_start=load_start["atl"],
        atl_end=load_end["atl"],
        tsb_start=load_start["tsb"],
        tsb_end=load_end["tsb"],
        guardrail=guardrail,
        prs=prs,
    )

    narrative, source = get_narrative(user_id=str(uid), week_start=week_start.isoformat(), facts=facts)
    return JSONResponse(build_response(
        week_start=week_start.isoformat(),
        facts=facts,
        narrative=narrative,
        source=source,
    ))


# ── Home summary aggregator endpoint (issue #437) ────────────────────────────

_HOME_SUMMARY_LOG = _logging.getLogger(__name__)
_HOME_SUMMARY_TOP_N = 5


def _build_habits_block(uid, today_bkk, ws):
    """Return the habits block for the home summary, or None on any error."""
    week_dates = [ws + _timedelta(days=i) for i in range(7)]

    with Session(engine) as session:
        active_habits = (
            session.query(Habit)
            .filter(Habit.user_id == uid, Habit.is_archived.is_(False))
            .order_by(Habit.sort_order)
            .all()
        )
        all_logs = (
            session.query(HabitLog)
            .filter(HabitLog.user_id == uid, HabitLog.log_week_start == ws)
            .all()
        )

    if not active_habits:
        return None

    logs_by_habit: dict = {}
    for log in all_logs:
        logs_by_habit.setdefault(log.habit_id, []).append(log)

    daily_habits = [h for h in active_habits if h.tracking_type == "daily_checkmark"]

    # Compute day_scores for wheel
    num_daily = len(daily_habits)
    day_scores = []
    for d in week_dates:
        done = sum(
            1 for h in daily_habits
            if any(log.log_date == d for log in logs_by_habit.get(h.id, []))
        )
        day_scores.append({"date": d.isoformat(), "done": done, "of": num_daily})

    # Build wheel
    wheel = []
    for i, d in enumerate(week_dates):
        if d == today_bkk:
            state = "today"
        elif d > today_bkk:
            state = "future"
        else:
            ds = day_scores[i]
            if num_daily > 0 and ds["done"] == num_daily:
                state = "full"
            elif ds["done"] > 0:
                state = "partial"
            else:
                state = "zero"
        wheel.append({"date": d.isoformat(), "state": state})

    # Week totals
    elapsed_days = 0
    done_in_elapsed = 0
    done_total = 0
    for i, d in enumerate(week_dates):
        ds = day_scores[i]
        done_total += ds["done"]
        if d <= today_bkk:
            elapsed_days += 1
            done_in_elapsed += ds["done"]

    max_elapsed = num_daily * elapsed_days
    pct_elapsed = round(
        (done_in_elapsed / max_elapsed * 100.0) if max_elapsed > 0 else 0.0, 2
    )
    week_totals = {
        "daily_done": done_total,
        "daily_habits_count": num_daily,
        "pct_elapsed": pct_elapsed,
    }

    # Compute streaks for daily habits (one extra query, capped 365 days)
    from backend.services.habit_stats import _current_streak_from_dates as _cs
    streak_logs_by_habit: dict = {}
    if daily_habits:
        streak_lookback = today_bkk - _timedelta(days=365)
        with Session(engine) as _streak_session:
            streak_rows = (
                _streak_session.query(HabitLog)
                .filter(
                    HabitLog.user_id == uid,
                    HabitLog.habit_id.in_([h.id for h in daily_habits]),
                    HabitLog.log_date >= streak_lookback,
                    HabitLog.log_date <= today_bkk,
                )
                .all()
            )
        for lg in streak_rows:
            streak_logs_by_habit.setdefault(lg.habit_id, set()).add(lg.log_date)

    # Build daily_habits list with today_checked, week_count, streak, auto_fill_source
    daily_habits_data = []
    for h in daily_habits:
        habit_logs = logs_by_habit.get(h.id, [])
        logged_dates = {log.log_date for log in habit_logs}
        today_checked = today_bkk in logged_dates
        week_count = sum(1 for d in week_dates if d in logged_dates and d <= today_bkk)
        streak = _cs(today_bkk, streak_logs_by_habit.get(h.id, set()))
        daily_habits_data.append({
            "id": str(h.id),
            "name": h.name,
            "icon": h.icon,
            "color": h.color,
            "today_checked": today_checked,
            "week_count": week_count,
            "streak": streak,
            "auto_fill_source": h.auto_fill_source,
        })

    top_habits = daily_habits_data[:_HOME_SUMMARY_TOP_N]
    remaining_count = max(0, len(daily_habits_data) - _HOME_SUMMARY_TOP_N)

    return {
        "wheel": wheel,
        "pct_elapsed": pct_elapsed,
        "daily_habits": daily_habits_data,
        "week_totals": week_totals,
        "top_habits": top_habits,
        "remaining_count": remaining_count,
    }


def _build_weight_block(uid, today_bkk):
    """Return the weight block, or None when no active target exists."""
    fetch_from = today_bkk - _timedelta(days=36)

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
            .filter(WeightTarget.user_id == uid, WeightTarget.status == "active")
            .first()
        )

    if active_target is None:
        return None

    date_weights: dict = {}
    for e in entries:
        d = e.entry_date if isinstance(e.entry_date, _date) else _date.fromisoformat(str(e.entry_date))
        date_weights.setdefault(d, []).append(float(e.weight_kg))

    def _ma(day):
        vals = []
        for offset in range(7):
            di = day - _timedelta(days=6 - offset)
            if di in date_weights:
                vals.extend(date_weights[di])
        return round(sum(vals) / len(vals), 2) if vals else None

    logged_today = today_bkk in date_weights
    last_entry_kg = float(entries[-1].weight_kg) if entries else None
    current_kg = last_entry_kg

    seven_day_avg = _ma(today_bkk)
    ma_7d_ago = _ma(today_bkk - _timedelta(days=7))
    weekly_rate_kg = round(seven_day_avg - ma_7d_ago, 2) if (seven_day_avg is not None and ma_7d_ago is not None) else None

    # 14-point sparkline (recent trend)
    sparkline = []
    for i in range(14):
        day = today_bkk - _timedelta(days=13 - i)
        sparkline.append({"date": str(day), "value": _ma(day)})

    # 7-day plan sparkline
    plan_sparkline = []
    week_start = today_bkk - _timedelta(days=today_bkk.weekday())
    for i in range(7):
        day = week_start + _timedelta(days=i)
        plan_sparkline.append({
            "date": str(day),
            "plan_kg": float(round(_weight_plan_at(active_target, day), 2)),
        })

    # Gap analysis (inline to avoid extra DB session for compute_gap)
    target_w = float(active_target.target_weight_kg)
    start_w = float(active_target.start_weight_kg)
    basis_kg = seven_day_avg if seven_day_avg is not None else current_kg

    gap_kg = None
    gap_direction = "no_data"
    if basis_kg is not None:
        plan_today = float(round(_weight_plan_at(active_target, today_bkk), 2))
        raw_gap = round(basis_kg - plan_today, 2)
        gap_kg = raw_gap
        is_loss = target_w < start_w
        if abs(raw_gap) <= 0.2:
            gap_direction = "on_plan"
        elif is_loss:
            gap_direction = "behind" if raw_gap > 0 else "ahead"
        else:
            gap_direction = "ahead" if raw_gap > 0 else "behind"

    # Progress toward target
    total_kg = abs(start_w - target_w)
    if total_kg != 0 and current_kg is not None:
        kg_changed = abs(start_w - current_kg)
        progress_pct = round(min(max(kg_changed / total_kg * 100, 0), 100), 2)
    else:
        progress_pct = 100.0 if total_kg == 0 else None

    target_date = active_target.target_date if isinstance(active_target.target_date, _date) \
        else _date.fromisoformat(str(active_target.target_date))
    kg_to_go = round(abs(target_w - current_kg), 2) if current_kg is not None else None

    return {
        "current_kg": current_kg,
        "basis_kg": basis_kg,
        "gap_kg": gap_kg,
        "gap_direction": gap_direction,
        "sparkline": sparkline,
        "plan_sparkline": plan_sparkline,
        "seven_day_avg": seven_day_avg,
        "weekly_rate_kg": weekly_rate_kg,
        "progress_pct": progress_pct,
        "target_kg": target_w,
        "target_date": str(target_date),
        "kg_to_go": kg_to_go,
        "logged_today": logged_today,
        "last_entry_kg": last_entry_kg,
    }


def _build_readiness_block(uid, today_bkk):
    """Return readiness block for today, or {"logged": false} when no metrics exist."""
    baseline_end = today_bkk - _timedelta(days=1)
    baseline_start = today_bkk - _timedelta(days=7)

    with Session(engine) as session:
        metrics = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == today_bkk)
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

    if metrics is None:
        return {"logged": False}

    def _avg(vals):
        non_null = [v for v in vals if v is not None]
        return round(sum(non_null) / len(non_null), 2) if non_null else None

    hrv_7d_avg = _avg([float(r.hrv) for r in baseline_rows if r.hrv is not None])
    rhr_7d_avg = _avg([float(r.resting_hr) for r in baseline_rows if r.resting_hr is not None])
    sleep_7d_avg = _avg([float(r.sleep_hours) for r in baseline_rows if r.sleep_hours is not None])

    def _bscore(value, baseline, higher_is_better):
        if value is None:
            return 50.0
        v = float(value)
        if baseline is None or baseline == 0:
            return 50.0
        delta_pct = (v - float(baseline)) / float(baseline) * 100.0
        raw = 50.0 + delta_pct if higher_is_better else 50.0 - delta_pct
        return min(100.0, max(0.0, raw))

    sleep_score = _bscore(metrics.sleep_hours, sleep_7d_avg, True)
    hrv_score = _bscore(metrics.hrv, hrv_7d_avg, True)
    rhr_score = _bscore(metrics.resting_hr, rhr_7d_avg, False)
    mood_score = float(metrics.mood) * 20.0 if metrics.mood is not None else 50.0
    energy_score = float(metrics.energy) * 20.0 if metrics.energy is not None else 50.0

    total = sleep_score * 0.30 + hrv_score * 0.25 + rhr_score * 0.20 + mood_score * 0.15 + energy_score * 0.10
    score = int(round(min(100.0, max(0.0, total))))

    factors = [
        {"factor": "sleep_hours", "value": float(metrics.sleep_hours) if metrics.sleep_hours is not None else None,
         "impact": "positive" if sleep_score > 50 else ("negative" if sleep_score < 50 else "neutral"), "score": sleep_score},
        {"factor": "hrv", "value": float(metrics.hrv) if metrics.hrv is not None else None,
         "impact": "positive" if hrv_score > 50 else ("negative" if hrv_score < 50 else "neutral"), "score": hrv_score},
        {"factor": "rhr", "value": float(metrics.resting_hr) if metrics.resting_hr is not None else None,
         "impact": "positive" if rhr_score > 50 else ("negative" if rhr_score < 50 else "neutral"), "score": rhr_score},
        {"factor": "mood", "value": float(metrics.mood) if metrics.mood is not None else None,
         "impact": "positive" if mood_score > 50 else ("negative" if mood_score < 50 else "neutral"), "score": mood_score},
        {"factor": "energy", "value": float(metrics.energy) if metrics.energy is not None else None,
         "impact": "positive" if energy_score > 50 else ("negative" if energy_score < 50 else "neutral"), "score": energy_score},
    ]
    # Top factors by absolute deviation from 50
    top_factors = sorted(factors, key=lambda f: abs(f["score"] - 50), reverse=True)[:3]
    top_factors_clean = [{"factor": f["factor"], "value": f["value"], "impact": f["impact"]} for f in top_factors]

    explanation_facts = {
        "score": score,
        "label": _readiness_score_label(score),
        "sleep_hours": float(metrics.sleep_hours) if metrics.sleep_hours is not None else None,
        "hrv": float(metrics.hrv) if metrics.hrv is not None else None,
        "rhr": float(metrics.resting_hr) if metrics.resting_hr is not None else None,
        "sleep_quality": float(metrics.sleep_quality) if metrics.sleep_quality is not None else None,
        "energy": float(metrics.energy) if metrics.energy is not None else None,
        "mood": float(metrics.mood) if metrics.mood is not None else None,
        "sleep_hours_baseline": sleep_7d_avg,
        "hrv_baseline": hrv_7d_avg,
        "rhr_baseline": rhr_7d_avg,
    }
    from backend.services.readiness_explanation import get_readiness_explanation
    explanation = get_readiness_explanation(
        user_id=str(uid),
        target_date=str(today_bkk),
        facts=explanation_facts,
        fallback_factors=factors,
    )

    return {
        "logged": True,
        "score": score,
        "label": _readiness_score_label(score),
        "top_factors": top_factors_clean,
        "explanation": explanation,
    }


def _build_training_week_block(uid, today_bkk, ws):
    """Return training_week block with 7-day daily_load array."""
    we = ws + _timedelta(days=6)
    prev_ws = ws - _timedelta(days=7)
    prev_we = ws - _timedelta(days=1)

    with Session(engine) as session:
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

    def _sf(val):
        try:
            return float(val) if val is not None else None
        except Exception:
            return None

    def _si(val):
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

    distance_km = _sum_attr(current_week, "distance_km", _sf)
    if distance_km is not None:
        distance_km = round(distance_km, 3)

    zone2_minutes = _sum_attr(current_week, "zone2_minutes", _si)

    prev_distance = _sum_attr(prev_week, "distance_km", _sf) or 0.0
    prev_zone2 = _sum_attr(prev_week, "zone2_minutes", _si) or 0

    vs_last_week = {
        "workouts_count": len(current_week) - len(prev_week),
        "distance_km": round(
            (distance_km if distance_km is not None else 0.0) - prev_distance, 3
        ),
        "zone2_minutes": (zone2_minutes if zone2_minutes is not None else 0) - prev_zone2,
    }

    # daily_load: exactly 7 entries, one per day of current Bangkok week
    daily_load = []
    workout_dates = {w.workout_date for w in current_week}
    for i in range(7):
        day = ws + _timedelta(days=i)
        day_workouts = [w for w in current_week if w.workout_date == day]
        day_tss_vals = [_sf(getattr(w, "tss", None)) for w in day_workouts if getattr(w, "tss", None) is not None]
        day_tss = round(sum(day_tss_vals), 2) if day_tss_vals else None
        day_z2 = _sum_attr(day_workouts, "zone2_minutes", _si)
        daily_load.append({
            "date": day.isoformat(),
            "tss": day_tss,
            "zone2_minutes": day_z2,
            "is_rest": day not in workout_dates,
        })

    return {
        "workouts_count": len(current_week),
        "distance_km": distance_km,
        "zone2_minutes": zone2_minutes,
        "vs_last_week": vs_last_week,
        "daily_load": daily_load,
    }


def _build_performance_block(uid):
    """Return top-3 PR tracks, or None when no records exist."""
    with Session(engine) as session:
        all_records = (
            session.query(PersonalRecord)
            .filter(
                PersonalRecord.user_id == uid,
                PersonalRecord.track_key.in_(_PR_DEFAULT_TRACKS),
            )
            .order_by(PersonalRecord.track_key, PersonalRecord.achieved_on.desc())
            .all()
        )

    grouped: dict = {}
    for r in all_records:
        grouped.setdefault(r.track_key, []).append(r)

    result = []
    for tk in _PR_DEFAULT_TRACKS:
        recs = grouped.get(tk, [])
        if not recs:
            continue
        meta = _PR_TRACK_META.get(tk, {})
        track_type = recs[0].track_type

        # PB: best-ever record (min time for time tracks, max value for weight tracks)
        if track_type == "time":
            pb_rec = min(recs, key=lambda r: float(r.value_numeric))
        else:
            pb_rec = max(recs, key=lambda r: float(r.value_numeric))

        pb_val = float(pb_rec.value_numeric)
        pb_fmt = _format_pr_time(pb_val) if track_type == "time" else _format_pr_weight(pb_val)

        most_recent = recs[0]  # ordered by achieved_on desc
        mr_val = float(most_recent.value_numeric)
        mr_fmt = _format_pr_time(mr_val) if track_type == "time" else _format_pr_weight(mr_val)

        # improvement vs pb
        if mr_val == pb_val:
            improvement = "—"
        elif track_type == "time":
            pct = (pb_val - mr_val) / pb_val * 100
            improvement = f"{pct:+.1f}%" if pct != 0 else "—"
        else:
            pct = (mr_val - pb_val) / pb_val * 100
            improvement = f"{pct:+.1f}%" if pct != 0 else "—"

        result.append({
            "name": recs[0].track_name,
            "track_meta": {"track_type": track_type, **meta},
            "pb_value_formatted": pb_fmt,
            "pb_date": pb_rec.achieved_on.isoformat() if pb_rec.achieved_on else None,
            "most_recent_formatted": mr_fmt,
            "improvement_vs_pb": improvement,
        })

    return result if result else None


def _build_recent_workouts_block(uid, today_bkk):
    """Return the most recent workouts (up to 12), or empty list when none exist.

    The Home "Next + Recent" card sizes itself to its grid track and backfills
    with recent workouts to fill the space (see loadRecentWorkoutsCard), so it
    needs more than the old fixed 3 to work with; the frontend caps how many it
    actually shows based on available card height.
    """
    with Session(engine) as session:
        rows = (
            session.query(Workout)
            .filter(Workout.user_id == uid)
            .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
            .limit(12)
            .all()
        )

    def _rel(d):
        delta = (today_bkk - d).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Yesterday"
        if delta < 7:
            return f"{delta} days ago"
        return d.isoformat()

    def _summary(w):
        parts = []
        try:
            if w.distance_km is not None:
                parts.append(f"{float(w.distance_km):.1f} km")
        except Exception:
            pass
        try:
            if w.duration_seconds is not None:
                mins = int(w.duration_seconds) // 60
                parts.append(f"{mins} min")
        except Exception:
            pass
        return " · ".join(parts) if parts else ""

    result = []
    for w in rows:
        try:
            z2 = int(w.zone2_minutes) if getattr(w, "zone2_minutes", None) is not None else None
        except Exception:
            z2 = None
        result.append({
            "name": getattr(w, "name", None) or getattr(w, "workout_type", "Workout"),
            "workout_type": getattr(w, "workout_type", None),
            "relative_day": _rel(w.workout_date),
            "summary": _summary(w),
            "zone2_minutes": z2,
        })
    return result


def _build_sleep_block(uid, today_bkk):
    """Return last-night sleep data, or {"logged": false} when not logged."""
    with Session(engine) as session:
        metrics = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == today_bkk)
            .first()
        )

    if metrics is None or metrics.sleep_hours is None:
        return {"logged": False}

    return {
        "logged": True,
        "hours": float(metrics.sleep_hours),
        "quality": int(metrics.sleep_quality) if metrics.sleep_quality is not None else None,
    }


@app.get("/api/home/summary")
def get_home_summary(current_user: User = Depends(resolve_user)):
    """Aggregated home-page summary: all seven data blocks in one request.

    Each block is computed independently; a failure in one block returns null
    for that block without affecting the rest. All date/time boundaries use
    Asia/Bangkok (UTC+7).
    """
    uid = current_user.id

    _BKK = ZoneInfo("Asia/Bangkok")
    today_bkk: _date = _datetime.now(_BKK).date()
    ws = _week_start_bangkok(today_bkk)

    with Session(engine) as session:
        user = session.get(User, uid)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    habits_block = None
    try:
        habits_block = _build_habits_block(uid, today_bkk, ws)
    except Exception as _e:
        _HOME_SUMMARY_LOG.error("home/summary habits block error for user %s: %s", uid, _e)

    weight_block = None
    try:
        weight_block = _build_weight_block(uid, today_bkk)
    except Exception as _e:
        _HOME_SUMMARY_LOG.error("home/summary weight block error for user %s: %s", uid, _e)

    readiness_block = None
    try:
        readiness_block = _build_readiness_block(uid, today_bkk)
    except Exception as _e:
        _HOME_SUMMARY_LOG.error("home/summary readiness block error for user %s: %s", uid, _e)

    training_week_block = None
    try:
        training_week_block = _build_training_week_block(uid, today_bkk, ws)
    except Exception as _e:
        _HOME_SUMMARY_LOG.error("home/summary training_week block error for user %s: %s", uid, _e)

    performance_block = None
    try:
        performance_block = _build_performance_block(uid)
    except Exception as _e:
        _HOME_SUMMARY_LOG.error("home/summary performance block error for user %s: %s", uid, _e)

    recent_workouts_block = None
    try:
        recent_workouts_block = _build_recent_workouts_block(uid, today_bkk)
    except Exception as _e:
        _HOME_SUMMARY_LOG.error("home/summary recent_workouts block error for user %s: %s", uid, _e)

    sleep_block = None
    try:
        sleep_block = _build_sleep_block(uid, today_bkk)
    except Exception as _e:
        _HOME_SUMMARY_LOG.error("home/summary sleep block error for user %s: %s", uid, _e)

    return JSONResponse({
        "habits": habits_block,
        "weight": weight_block,
        "readiness": readiness_block,
        "training_week": training_week_block,
        "performance": performance_block,
        "recent_workouts": recent_workouts_block,
        "sleep": sleep_block,
    })


# ── Habit endpoints ───────────────────────────────────────────────────────────
from backend.services import habits_repo as _habits_repo  # noqa: E402

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


def _habit_dict_v2(h: Habit) -> dict:
    """Return a habit dict that includes both v2 fields and legacy fields."""
    try:
        tv = float(h.target_value) if h.target_value is not None else None
    except (TypeError, ValueError):
        tv = None
    try:
        wt = float(h.weekly_target) if h.weekly_target is not None else None
    except (TypeError, ValueError):
        wt = None
    return {
        "id": str(h.id),
        "user_id": str(h.user_id),
        "name": h.name,
        # v2 fields
        "habit_type": str(h.habit_type) if h.habit_type is not None else None,
        "schedule_type": str(h.schedule_type) if h.schedule_type is not None else None,
        "target_value": tv,
        "unit": h.unit,
        "active": bool(h.active),
        "display_order": h.display_order,
        # legacy fields retained for backward compat
        "tracking_type": h.tracking_type,
        "weekly_target": wt,
        "sort_order": h.sort_order,
        "is_archived": h.is_archived,
        "description": h.description,
        "icon": h.icon,
        "color": h.color,
        "auto_fill_source": h.auto_fill_source,
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
    }


def _habit_log_dict_v2(log: HabitLog) -> dict:
    """Return a habit log dict for the v2 API surface."""
    try:
        value = float(log.value) if log.value is not None else None
    except (TypeError, ValueError):
        value = None
    return {
        "id": str(log.id),
        "habit_id": str(log.habit_id),
        "user_id": str(log.user_id),
        "log_date": log.log_date.isoformat() if log.log_date else None,
        "value": value,
        "note": log.note,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "updated_at": log.updated_at.isoformat() if log.updated_at else None,
    }


def _validate_habit_business_rules(
    tracking_type: Optional[str],
    weekly_target: Optional[float],
    auto_fill_source: Optional[str],
    habit_type: Optional[str] = None,
    schedule_type: Optional[str] = None,
    target_value: Optional[float] = None,
) -> None:
    # v2 enum validations
    if habit_type is not None and habit_type not in _habits_repo.HABIT_TYPE_VALUES:
        raise HTTPException(
            status_code=422,
            detail={"error": f"habit_type must be one of {sorted(_habits_repo.HABIT_TYPE_VALUES)}", "details": ""},
        )
    if schedule_type is not None and schedule_type not in _habits_repo.SCHEDULE_TYPE_VALUES:
        raise HTTPException(
            status_code=422,
            detail={"error": f"schedule_type must be one of {sorted(_habits_repo.SCHEDULE_TYPE_VALUES)}", "details": ""},
        )
    if target_value is not None and target_value <= 0:
        raise HTTPException(
            status_code=422,
            detail={"error": "target_value must be positive", "details": ""},
        )
    # legacy validations
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
    tracking_type: Optional[str] = None  # legacy (formerly required)
    habit_type: Optional[str] = None     # v2
    schedule_type: Optional[str] = None  # v2
    target_value: Optional[float] = None  # v2
    description: Optional[str] = None
    weekly_target: Optional[float] = None
    unit: Optional[str] = None
    auto_fill_source: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class HabitPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    habit_type: Optional[str] = None    # v2
    schedule_type: Optional[str] = None  # v2
    target_value: Optional[float] = None  # v2
    active: Optional[bool] = None        # v2
    display_order: Optional[int] = None  # v2
    description: Optional[str] = None
    weekly_target: Optional[float] = None
    unit: Optional[str] = None
    auto_fill_source: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None
    is_archived: Optional[bool] = None


class HabitReorderIn(BaseModel):
    sort_order: int


class HabitLogIn(BaseModel):
    habit_id: str
    user_id: Optional[str] = None
    logged_date: str  # YYYY-MM-DD


class HabitLogUpsertIn(BaseModel):
    habit_id: str
    log_date: str  # YYYY-MM-DD
    value: float
    note: Optional[str] = None


@app.get("/api/habits/summary")
def get_habits_summary(user: User = Depends(resolve_user)):
    """Return each active habit with streak and 30-day consistency stats."""
    from datetime import date as _date_cls, timedelta as _td
    today = _date_cls.today()
    window_start = today - _td(days=29)

    with Session(engine) as session:
        active_habits = (
            session.query(Habit)
            .filter(
                Habit.user_id == user.id,
                Habit.is_archived.is_(False),
                Habit.active.is_(True),
            )
            .order_by(Habit.sort_order)
            .all()
        )

        if not active_habits:
            return JSONResponse({"habits": [], "reason": "No active habits found"})

        habit_ids = [h.id for h in active_habits]
        all_logs = (
            session.query(HabitLog)
            .filter(
                HabitLog.habit_id.in_(habit_ids),
                HabitLog.user_id == user.id,
            )
            .all()
        )

    logs_by_habit: dict = {}
    for log in all_logs:
        logs_by_habit.setdefault(log.habit_id, []).append(log)

    result = []
    for habit in active_habits:
        habit_logs = logs_by_habit.get(habit.id, [])
        streak_data = compute_streak(habit, habit_logs, today)
        consistency_data = compute_consistency(habit, habit_logs, window_start, today)
        entry = _habit_dict(habit)
        entry["current_streak"] = streak_data["current_streak"]
        entry["longest_streak"] = streak_data["longest_streak"]
        entry["consistency_percent"] = consistency_data["consistency_percent"]
        result.append(entry)

    return JSONResponse({"habits": result})


@app.get("/api/habits")
def get_habits(
    include_archived: bool = False,
    active: Optional[bool] = Query(None),
    user: User = Depends(resolve_user),
):
    with Session(engine) as session:
        q = session.query(Habit).filter(Habit.user_id == user.id)
        if active is not None:
            # v2: filter by active field
            q = q.filter(Habit.active == active)
        elif not include_archived:
            # legacy: exclude is_archived habits
            q = q.filter(Habit.is_archived.is_(False))
        rows = q.order_by(Habit.sort_order).all()
        return JSONResponse([_habit_dict(r) for r in rows])


@app.post("/api/habits", status_code=201)
def post_habit(body: HabitIn, user: User = Depends(resolve_user)):
    if not body.tracking_type and not body.habit_type:
        return JSONResponse(
            status_code=422,
            content={"error": "Either tracking_type or habit_type must be provided", "details": ""},
        )
    _validate_habit_business_rules(
        tracking_type=body.tracking_type,
        weekly_target=body.weekly_target,
        auto_fill_source=body.auto_fill_source,
        habit_type=body.habit_type,
        schedule_type=body.schedule_type,
        target_value=body.target_value,
    )
    with Session(engine) as session:
        if body.auto_fill_source is not None:
            existing = (
                session.query(Habit)
                .filter(
                    Habit.user_id == user.id,
                    Habit.auto_fill_source == body.auto_fill_source,
                    Habit.is_archived.is_(False),
                )
                .first()
            )
            if existing is not None:
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": "A habit with this auto_fill_source already exists",
                        "existing_habit_id": str(existing.id),
                    },
                )
        habit = _habits_repo.create_habit(session, user.id, body.model_dump())
        return JSONResponse(status_code=201, content=_habit_dict_v2(habit))


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
    # v2 + legacy validations
    _validate_habit_business_rules(
        tracking_type=None,
        weekly_target=None,
        auto_fill_source=body.auto_fill_source,
        habit_type=body.habit_type,
        schedule_type=body.schedule_type,
        target_value=body.target_value,
    )
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    with Session(engine) as session:
        habit = _habits_repo.update_habit(session, hid, user.id, body.model_dump(exclude_none=True))
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        return JSONResponse(_habit_dict_v2(habit))


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
            session.commit()
            return JSONResponse({"ok": True})
        else:
            habit = _habits_repo.archive_habit(session, hid, user.id)
            return JSONResponse(_habit_dict_v2(habit))


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


# ── Habit log + progress endpoints (issue #388) ───────────────────────────────

def _bangkok_today() -> _date:
    return _datetime.now(ZoneInfo("Asia/Bangkok")).date()


def _week_start_bangkok(d: _date) -> _date:
    """Monday of the week containing d."""
    return d - _timedelta(days=d.weekday())


def _habit_log_dict(log: HabitLog) -> dict:
    return {
        "id": str(log.id),
        "habit_id": str(log.habit_id),
        "user_id": str(log.user_id),
        "log_date": log.log_date.isoformat(),
        "log_week_start": log.log_week_start.isoformat(),
        "value": float(log.value) if log.value is not None else None,
        "notes": log.notes,
        "source": log.source,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "updated_at": log.updated_at.isoformat() if log.updated_at else None,
    }


class HabitLogCreateIn(BaseModel):
    log_date: Optional[_date] = None
    value: Optional[float] = None
    notes: Optional[str] = None
    mode: str = "set"  # "set" or "add"


def _validate_backfill_window(log_date: _date) -> None:
    """Raise 422 if log_date is outside the current Bangkok week (Mon–today)."""
    today = _bangkok_today()
    week_monday = _week_start_bangkok(today)
    if log_date > today:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "future_date"},
        )
    if log_date < week_monday:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "past_week_locked", "message": "Past weeks are read-only"},
        )


def _validated_backfill_date(date: str = Query(...)) -> _date:
    """FastAPI dependency: parse a date query param and validate it against the backfill window.

    Raises 400 for unparseable strings; delegates window checks to _validate_backfill_window.
    Reusable by any endpoint that receives a date as a query string and needs backfill enforcement.
    """
    try:
        log_date = _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    _validate_backfill_window(log_date)
    return log_date


def _get_computed_logs_from_workouts(workouts: list, auto_fill_source: str) -> list:
    """Compute autofill log entries from a pre-loaded workout list (pure, no DB).

    Used by both the per-habit progress endpoint (after DB query) and the week
    batch endpoint (after a single bulk workout fetch).
    """
    from collections import defaultdict
    date_values: dict = defaultdict(float)

    if auto_fill_source == "workout.zone2_minutes":
        for w in workouts:
            if w.zone2_minutes:
                date_values[w.workout_date.isoformat()] += float(w.zone2_minutes)
    elif auto_fill_source == "workout.run_count":
        for w in workouts:
            if "run" in (w.workout_type or "").lower():
                date_values[w.workout_date.isoformat()] += 1.0
    elif auto_fill_source == "workout.lift_count":
        for w in workouts:
            if "lift" in (w.workout_type or "").lower():
                date_values[w.workout_date.isoformat()] += 1.0
    elif auto_fill_source == "workout.total_duration_minutes":
        for w in workouts:
            if w.duration_seconds:
                date_values[w.workout_date.isoformat()] += w.duration_seconds / 60.0
    elif auto_fill_source == "workout.distance_km":
        for w in workouts:
            if w.distance_km:
                date_values[w.workout_date.isoformat()] += float(w.distance_km)

    return [
        {"date": d, "value": v, "source": auto_fill_source}
        for d, v in sorted(date_values.items())
    ]


def _get_computed_logs(
    session,
    user_id,
    week_start: _date,
    week_end: _date,
    auto_fill_source: str,
) -> list:
    """Derive per-date computed log entries from workouts for the given week."""
    base_q = session.query(Workout).filter(
        Workout.user_id == user_id,
        Workout.workout_date >= week_start,
        Workout.workout_date <= week_end,
    )

    if auto_fill_source == "workout.zone2_minutes":
        workouts = base_q.filter(Workout.zone2_minutes > 0).all()
    elif auto_fill_source == "workout.run_count":
        workouts = base_q.filter(Workout.workout_type.ilike("%run%")).all()
    elif auto_fill_source == "workout.lift_count":
        workouts = base_q.filter(Workout.workout_type.ilike("%lift%")).all()
    elif auto_fill_source == "workout.total_duration_minutes":
        workouts = base_q.filter(Workout.duration_seconds.isnot(None)).all()
    elif auto_fill_source == "workout.distance_km":
        workouts = base_q.filter(Workout.distance_km.isnot(None)).all()
    else:
        return []

    return _get_computed_logs_from_workouts(workouts, auto_fill_source)


def _aggregate_weekly_progress(manual_log_rows: list, computed_logs: list, weekly_target) -> dict:
    """Shared math: aggregate weekly progress from pre-loaded log data (no DB).

    Applies manual_override precedence: a log with source='manual_override' on
    a date that also has computed contributions replaces (not adds to) those
    computed values for that date only.

    Returns dict with keys: current_value, target, pct, is_complete.
    """
    manual_by_date: dict = {}
    for log in manual_log_rows:
        # workout_autofill rows are persisted only to drive the daily grid; the
        # live computed_logs already represents those workout values, so counting
        # the stored rows here too would double-count (issue: zone-2 172 vs ~100).
        if getattr(log, "source", None) == "workout_autofill":
            continue
        d = log.log_date.isoformat()
        if d not in manual_by_date:
            manual_by_date[d] = {"value": 0.0, "has_override": False}
        manual_by_date[d]["value"] += float(log.value)
        if log.source == "manual_override":
            manual_by_date[d]["has_override"] = True

    computed_by_date: dict = {}
    for entry in computed_logs:
        d = entry["date"]
        computed_by_date[d] = computed_by_date.get(d, 0.0) + entry["value"]

    current_value = 0.0
    for d in set(manual_by_date) | set(computed_by_date):
        m = manual_by_date.get(d, {"value": 0.0, "has_override": False})
        c = computed_by_date.get(d, 0.0)
        if m["has_override"]:
            current_value += m["value"]
        else:
            current_value += m["value"] + c

    target = float(weekly_target) if weekly_target is not None else None
    pct = None
    if target is not None and target > 0:
        pct = min(100.0, max(0.0, (current_value / target) * 100.0))
    is_complete = (current_value >= target) if target is not None else False

    return {
        "current_value": current_value,
        "target": target,
        "pct": pct,
        "is_complete": is_complete,
    }


@app.post("/api/habits/{habit_id}/log", status_code=201)
def post_habit_log_entry(
    habit_id: str,
    body: HabitLogCreateIn,
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
        log_date = body.log_date if body.log_date is not None else _bangkok_today()
        _validate_backfill_window(log_date)
        is_checkmark = habit.tracking_type == "daily_checkmark"
        submitted_value = body.value if body.value is not None else 1.0
        log_week_start = _week_start_bangkok(log_date)
        existing = (
            session.query(HabitLog)
            .filter(HabitLog.habit_id == hid, HabitLog.log_date == log_date)
            .first()
        )
        if existing is not None:
            if is_checkmark:
                new_value = 1.0
            elif body.mode == "add":
                new_value = float(existing.value or 0) + submitted_value
            else:
                new_value = submitted_value
            if not is_checkmark and not (0 < new_value <= 10000):
                raise HTTPException(status_code=422, detail={"error_code": "value_out_of_range"})
            existing.value = new_value
            existing.notes = body.notes
            existing.updated_at = _datetime.now(_timezone.utc)
            session.commit()
            session.refresh(existing)
            saved_log = existing
        else:
            value = 1.0 if is_checkmark else submitted_value
            if not is_checkmark and not (0 < value <= 10000):
                raise HTTPException(status_code=422, detail={"error_code": "value_out_of_range"})
            log = HabitLog(
                habit_id=hid,
                user_id=user.id,
                log_date=log_date,
                log_week_start=log_week_start,
                value=value,
                notes=body.notes,
                source="manual",
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            saved_log = log
        current_week_start = _week_start_bangkok(_bangkok_today())
        week_logs = (
            session.query(HabitLog)
            .filter(
                HabitLog.habit_id == hid,
                HabitLog.log_week_start == current_week_start,
            )
            .all()
        )
        week_current_value = sum(
            float(lg.value) for lg in week_logs if lg.value is not None
        )
        result = _habit_log_dict(saved_log)
        result["week_current_value"] = week_current_value
        return JSONResponse(status_code=201, content=result)


@app.delete("/api/habits/{habit_id}/log", status_code=204)
def delete_habit_log_entry(
    habit_id: str,
    log_date: _date = Depends(_validated_backfill_date),
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
        log = (
            session.query(HabitLog)
            .filter(HabitLog.habit_id == hid, HabitLog.log_date == log_date)
            .first()
        )
        if log is None:
            raise HTTPException(status_code=404, detail="Log entry not found")
        session.delete(log)
        session.commit()
    return Response(status_code=204)


@app.get("/api/habits/{habit_id}/progress")
def get_habit_progress(
    habit_id: str,
    week_start: Optional[str] = Query(None),
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
        if week_start is not None:
            try:
                ws = _date.fromisoformat(week_start)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid week_start format")
        else:
            ws = _week_start_bangkok(_bangkok_today())
        we = ws + _timedelta(days=6)
        manual_log_rows = (
            session.query(HabitLog)
            .filter(HabitLog.habit_id == hid, HabitLog.log_week_start == ws)
            .all()
        )
        manual_logs = [
            {
                "date": log.log_date.isoformat(),
                "value": float(log.value),
                "notes": log.notes or "",
            }
            for log in manual_log_rows
        ]
        computed_logs: list = []
        if habit.auto_fill_source:
            computed_logs = _get_computed_logs(session, user.id, ws, we, habit.auto_fill_source)
        progress = _aggregate_weekly_progress(manual_log_rows, computed_logs, habit.weekly_target)
        return JSONResponse({
            "habit": _habit_dict(habit),
            "week_start": ws.isoformat(),
            "week_end": we.isoformat(),
            "target": progress["target"],
            "current_value": progress["current_value"],
            "percentage": progress["pct"],
            "manual_logs": manual_logs,
            "computed_logs": computed_logs,
            "is_complete": progress["is_complete"],
        })


# ── Per-habit detail summary endpoint (issue #831) ───────────────────────────

@app.get("/api/habits/{habit_id}/summary")
def get_habit_summary(
    habit_id: str,
    user: User = Depends(resolve_user),
):
    """Return per-habit stats for the detail panel.

    Includes current streak, longest streak, and consistency pct
    for the last 30 days."""
    from backend.services.habit_stats import (
        _current_streak_from_dates,
        _best_streak_from_dates,
    )
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")

    today = _date.today()
    lookback_30 = today - _timedelta(days=29)
    lookback_365 = today - _timedelta(days=365)

    with Session(engine) as session:
        habit = session.get(Habit, hid)
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        if habit.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")

        all_logs = (
            session.query(HabitLog)
            .filter(
                HabitLog.habit_id == hid,
                HabitLog.user_id == user.id,
                HabitLog.log_date >= lookback_365,
                HabitLog.log_date <= today,
            )
            .all()
        )

    all_dates = {lg.log_date for lg in all_logs}
    sorted_dates = sorted(all_dates)

    if habit.tracking_type == "daily_checkmark":
        current_streak = _current_streak_from_dates(today, all_dates)
        longest_streak = _best_streak_from_dates(sorted_dates)
    else:
        current_streak = 0
        longest_streak = 0

    days_in_window = (today - lookback_30).days + 1  # 30 days
    days_checked = len([d for d in all_dates if lookback_30 <= d <= today])
    consistency_pct = (
        round(days_checked / days_in_window * 100.0, 1)
        if days_in_window > 0 else 0.0
    )

    return JSONResponse({
        "habit": _habit_dict(habit),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "consistency_pct": consistency_pct,
        "days_checked": days_checked,
        "days_total": days_in_window,
    })


# ── Habits week-view batch endpoint (issue #429) ─────────────────────────────

@app.get("/api/habits/week")
def get_habits_week(
    week_start: Optional[str] = Query(None),
    user: User = Depends(resolve_user),
):
    """Return a single response covering the full habits week view.

    week_start defaults to the current Monday in Asia/Bangkok timezone.
    Non-Monday week_start values are rejected with 422.
    """
    _BANGKOK = ZoneInfo("Asia/Bangkok")
    today_bkk: _date = _datetime.now(_BANGKOK).date()

    if week_start is not None:
        try:
            ws = _date.fromisoformat(week_start)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid week_start; use YYYY-MM-DD")
        if ws.weekday() != 0:  # 0 = Monday
            raise HTTPException(
                status_code=422,
                detail="week_start must be a Monday (ISO weekday 0); received a non-Monday date",
            )
    else:
        ws = _week_start_bangkok(today_bkk)

    we = ws + _timedelta(days=6)
    is_current_week = (ws == _week_start_bangkok(today_bkk))
    week_dates = [ws + _timedelta(days=i) for i in range(7)]

    with Session(engine) as session:
        # Active habits ordered by sort_order
        active_habits = (
            session.query(Habit)
            .filter(Habit.user_id == user.id, Habit.is_archived.is_(False))
            .order_by(Habit.sort_order)
            .all()
        )
        # Archived habits that still have logs this week (show in history)
        archived_with_logs = (
            session.query(Habit)
            .join(HabitLog, HabitLog.habit_id == Habit.id)
            .filter(
                Habit.user_id == user.id,
                Habit.is_archived.is_(True),
                HabitLog.log_week_start == ws,
            )
            .distinct()
            .all()
        )
        all_habits = active_habits + archived_with_logs

        daily_habits = [h for h in all_habits if h.tracking_type == "daily_checkmark"]
        weekly_habits_list = [h for h in all_habits if h.tracking_type != "daily_checkmark"]

        # Bulk-load all logs for the week (single query)
        all_logs = (
            session.query(HabitLog)
            .filter(HabitLog.user_id == user.id, HabitLog.log_week_start == ws)
            .all()
        )
        logs_by_habit: dict = {}
        for log in all_logs:
            logs_by_habit.setdefault(log.habit_id, []).append(log)

        # Load workouts only when needed for autofill habits (single query)
        autofill_needed = [h for h in weekly_habits_list if h.auto_fill_source]
        if autofill_needed:
            week_workouts = (
                session.query(Workout)
                .filter(
                    Workout.user_id == user.id,
                    Workout.workout_date >= ws,
                    Workout.workout_date <= we,
                )
                .all()
            )
        else:
            week_workouts = []

        # Build daily_habits data
        daily_habits_data = []
        for habit in daily_habits:
            habit_logs = logs_by_habit.get(habit.id, [])
            logged_dates = {log.log_date for log in habit_logs}
            days = []
            for d in week_dates:
                if d in logged_dates:
                    state = "done"
                elif d > today_bkk:
                    state = "future"
                elif d == today_bkk:
                    state = "today_pending"
                else:
                    state = "missed"
                days.append({"date": d.isoformat(), "state": state})
            done_count = sum(1 for day in days if day["state"] == "done")
            target_val = float(habit.weekly_target) if habit.weekly_target is not None else 7.0
            daily_habits_data.append({
                "id": str(habit.id),
                "name": habit.name,
                "description": habit.description,
                "icon": habit.icon,
                "color": habit.color,
                "sort_order": habit.sort_order,
                "tracking_type": habit.tracking_type,
                "days": days,
                "total": {"done": done_count, "target": target_val},
            })

        # Build weekly_habits data
        autofill_cache: dict = {}  # memoize per unique auto_fill_source within this request
        weekly_habits_data = []
        for habit in weekly_habits_list:
            habit_logs = logs_by_habit.get(habit.id, [])
            computed_logs_w: list = []
            if habit.auto_fill_source:
                if habit.auto_fill_source not in autofill_cache:
                    autofill_cache[habit.auto_fill_source] = _get_computed_logs_from_workouts(
                        week_workouts, habit.auto_fill_source
                    )
                computed_logs_w = autofill_cache[habit.auto_fill_source]
            progress = _aggregate_weekly_progress(habit_logs, computed_logs_w, habit.weekly_target)

            # daily_breakdown: dates with any contribution (manual or autofill).
            # Skip stored workout_autofill rows — computed_logs_w below is their
            # live source of truth (counting both double-counts the value).
            breakdown: dict = {}
            for log in habit_logs:
                if getattr(log, "source", None) == "workout_autofill":
                    continue
                d = log.log_date.isoformat()
                breakdown.setdefault(d, {"date": d, "value": 0.0})
                breakdown[d]["value"] += float(log.value)
            for entry in computed_logs_w:
                d = entry["date"]
                breakdown.setdefault(d, {"date": d, "value": 0.0})
                breakdown[d]["value"] += entry["value"]
            daily_breakdown = sorted(breakdown.values(), key=lambda x: x["date"])

            tgt = progress["target"]
            cur = progress["current_value"]
            remaining = max(0.0, tgt - cur) if tgt is not None else None

            weekly_habits_data.append({
                "id": str(habit.id),
                "name": habit.name,
                "description": habit.description,
                "icon": habit.icon,
                "color": habit.color,
                "sort_order": habit.sort_order,
                "tracking_type": habit.tracking_type,
                "unit": habit.unit,
                "auto_fill_source": habit.auto_fill_source,
                "target": tgt,
                "current_value": cur,
                "pct": progress["pct"],
                "remaining": remaining,
                "is_complete": progress["is_complete"],
                "daily_breakdown": daily_breakdown,
            })

        # Build day_scores — denominator uses only daily_checkmark habits
        num_daily = len(daily_habits)
        day_scores = []
        for d in week_dates:
            done = sum(
                1 for h in daily_habits
                if any(log.log_date == d for log in logs_by_habit.get(h.id, []))
            )
            day_scores.append({"date": d.isoformat(), "done": done, "of": num_daily})

        # Build week_totals
        elapsed_days = 0
        done_in_elapsed = 0
        done_total = 0
        for i, d in enumerate(week_dates):
            ds = day_scores[i]
            done_total += ds["done"]
            if d <= today_bkk:
                elapsed_days += 1
                done_in_elapsed += ds["done"]

        max_elapsed = num_daily * elapsed_days
        pct_elapsed = round(
            (done_in_elapsed / max_elapsed * 100.0) if max_elapsed > 0 else 0.0, 2
        )
        max_full = num_daily * 7
        pct_full_week = round(
            (done_total / max_full * 100.0) if max_full > 0 else 0.0, 2
        )

        week_totals = {
            "daily_done": done_total,
            "daily_habits_count": num_daily,
            "elapsed_days": elapsed_days,
            "pct_elapsed": pct_elapsed,
            "pct_full_week": pct_full_week,
        }

        # Build wheel — today is always "today", future always "future"
        wheel = []
        for i, d in enumerate(week_dates):
            if d == today_bkk:
                state = "today"
            elif d > today_bkk:
                state = "future"
            else:
                ds = day_scores[i]
                if num_daily > 0 and ds["done"] == num_daily:
                    state = "full"
                elif ds["done"] > 0:
                    state = "partial"
                else:
                    state = "zero"
            wheel.append({"date": d.isoformat(), "state": state})

        # ── Streaks (batch: one extra query for all daily habits) ────────────
        from backend.services.habit_stats import compute_habit_streaks, week_summary as _week_summary
        streak_logs_by_habit: dict = {}
        if daily_habits:
            streak_lookback = today_bkk - _timedelta(days=365)
            streak_log_rows = (
                session.query(HabitLog)
                .filter(
                    HabitLog.user_id == user.id,
                    HabitLog.habit_id.in_([h.id for h in daily_habits]),
                    HabitLog.log_date >= streak_lookback,
                    HabitLog.log_date <= today_bkk,
                )
                .all()
            )
            for lg in streak_log_rows:
                streak_logs_by_habit.setdefault(lg.habit_id, set()).add(lg.log_date)
        streaks = compute_habit_streaks(daily_habits, streak_logs_by_habit, today_bkk)

        # ── Last-week summary ─────────────────────────────────────────────────
        last_week_ws = ws - _timedelta(days=7)
        last_week = _week_summary(user.id, last_week_ws, session=session)

        return JSONResponse({
            "week_start": ws.isoformat(),
            "week_end": we.isoformat(),
            "is_current_week": is_current_week,
            "daily_habits": daily_habits_data,
            "weekly_habits": weekly_habits_data,
            "day_scores": day_scores,
            "week_totals": week_totals,
            "wheel": wheel,
            "streaks": streaks,
            "last_week": last_week,
        })


@app.get("/api/habits/logs")
def get_habit_logs(
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    habit_id: Optional[str] = Query(default=None),
    user: User = Depends(resolve_user),
):
    try:
        from_d = _date.fromisoformat(from_date)
        to_d = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    hid_filter = None
    if habit_id is not None:
        try:
            hid_filter = _uuid.UUID(habit_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid habit_id")
    with Session(engine) as session:
        q = session.query(HabitLog).filter(
            HabitLog.user_id == user.id,
            HabitLog.log_date >= from_d,
            HabitLog.log_date <= to_d,
        )
        if hid_filter is not None:
            q = q.filter(HabitLog.habit_id == hid_filter)
        rows = q.order_by(HabitLog.log_date.desc()).all()
        return JSONResponse([
            {
                "id": str(r.id),
                "habit_id": str(r.habit_id),
                "user_id": str(r.user_id),
                "logged_date": str(r.log_date),
                "value": float(r.value) if r.value is not None else None,
                "notes": r.notes,
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
        try:
            log_date = _date.fromisoformat(body.logged_date)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
        log_week_start = _week_start_bangkok(log_date)
        log = HabitLog(
            habit_id=hid,
            user_id=user.id,
            log_date=log_date,
            log_week_start=log_week_start,
        )
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
                "logged_date": str(log.log_date),
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
        session.query(HabitLog.log_date)
        .filter(HabitLog.habit_id == hid, HabitLog.user_id == uid)
        .all()
    )
    all_dates = {row.log_date for row in all_logs}
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
                    session.query(HabitLog.log_date)
                    .filter(
                        HabitLog.habit_id == hid,
                        HabitLog.user_id == uid,
                        HabitLog.log_date >= window_start,
                        HabitLog.log_date <= today,
                    )
                    .all()
                )
                window_dates = {row.log_date for row in window_logs}
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
            session.query(HabitLog.log_date)
            .filter(
                HabitLog.habit_id == hid,
                HabitLog.user_id == uid,
                HabitLog.log_date >= window_start,
                HabitLog.log_date <= today,
            )
            .all()
        )
        window_dates = {row.log_date for row in window_logs}
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


# ── Habit adherence and nudges endpoint ───────────────────────────────────────

from backend.services.habit_adherence import (  # noqa: E402
    build_adherence_payload as _build_adherence_payload,
)


@app.get("/api/habits/adherence")
def get_habits_adherence(user: User = Depends(resolve_user)):
    """Return per-habit adherence, trend, best/worst day, and nudge copy.

    Response always has exactly three top-level keys:
    ``building`` (bool), ``reason`` (str or null), ``habits`` (list).
    HTTP status is always 200.
    """
    uid = user.id
    today = _date.today()

    with Session(engine) as session:
        active_habits = (
            session.query(Habit)
            .filter(
                Habit.user_id == uid,
                Habit.is_archived.is_(False),
                Habit.active.is_(True),
            )
            .order_by(Habit.sort_order)
            .all()
        )

        habit_ids = [h.id for h in active_habits]

        logs_by_habit: dict = {}
        if habit_ids:
            all_logs = (
                session.query(HabitLog)
                .filter(
                    HabitLog.habit_id.in_(habit_ids),
                    HabitLog.user_id == uid,
                )
                .all()
            )
            for log in all_logs:
                logs_by_habit.setdefault(str(log.habit_id), []).append(log)

    payload = _build_adherence_payload(
        habits=active_habits,
        logs_by_habit=logs_by_habit,
        today=today,
    )
    return JSONResponse(payload)


# ── Habit insights endpoint ────────────────────────────────────────────────────

from backend.services.habit_insights import (  # noqa: E402
    build_insights as _build_insights,
    apply_llm_insights as _apply_llm_insights,
    OUTCOME_FIELDS as _INSIGHT_OUTCOME_FIELDS,
)


@app.get("/api/habits/insights")
def get_habit_insights(user: User = Depends(resolve_user)):
    """Return statistically confident habit-outcome correlation insights.

    Response always has exactly three top-level keys:
    ``insights`` (list), ``building`` (bool), ``reason`` (str or null).
    HTTP status is always 200.
    """
    uid = user.id

    with Session(engine) as session:
        active_habits = (
            session.query(Habit)
            .filter(
                Habit.user_id == uid,
                Habit.is_archived.is_(False),
                Habit.active.is_(True),
            )
            .order_by(Habit.sort_order)
            .all()
        )

        habit_ids = [h.id for h in active_habits]

        # Fetch all habit logs for active habits; convert value to float
        habit_logs_by_habit: dict = {}
        if habit_ids:
            all_logs = (
                session.query(HabitLog)
                .filter(
                    HabitLog.habit_id.in_(habit_ids),
                    HabitLog.user_id == uid,
                )
                .all()
            )
            for log in all_logs:
                key = str(log.habit_id)
                date_str = log.log_date.isoformat()
                habit_logs_by_habit.setdefault(key, {})[date_str] = (
                    float(log.value) if log.value is not None else 0.0
                )

        # Fetch outcome series from daily_metrics
        outcome_series_by_name: dict = {f: {} for f in _INSIGHT_OUTCOME_FIELDS}
        daily_rows = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid)
            .all()
        )
        for row in daily_rows:
            date_str = row.metric_date.isoformat()
            for field in _INSIGHT_OUTCOME_FIELDS:
                val = getattr(row, field, None)
                if val is not None:
                    outcome_series_by_name[field][date_str] = float(val)

    insights, building, reason = _build_insights(
        habits=active_habits,
        habit_logs_by_habit=habit_logs_by_habit,
        outcome_series_by_name=outcome_series_by_name,
    )

    if not building and insights:
        insights = _apply_llm_insights(insights, user_id=str(uid))

    return JSONResponse({
        "insights": insights,
        "building": building,
        "reason": reason,
    })


# ── Adherence & nudges endpoint ───────────────────────────────────────────────

from backend.services.habit_adherence import (  # noqa: E402
    compute_adherence_breakdown as _compute_adherence_breakdown,
    detect_slipping_habits as _detect_slipping_habits,
)
from backend.services.habit_nudges import build_nudges as _build_nudges, apply_llm_nudges as _apply_llm_nudges  # noqa: E402


@app.get("/api/adherence-nudges")
def get_adherence_nudges(user: User = Depends(resolve_user)):
    """Return per-habit adherence breakdowns, slipping-habit flags, and coaching nudges.

    Response always has four top-level keys:
    ``per_habit`` (list), ``slipping_habits`` (list), ``nudges`` (list),
    ``building_state`` ({active, reason}).  HTTP status is always 200.
    All computation is delegated to compute_adherence_breakdown,
    detect_slipping_habits, and build_nudges.
    """
    from datetime import date as _date_cls, timedelta as _td

    uid = user.id
    today = _date_cls.today()
    current_start = today - _td(days=29)
    prev_start = today - _td(days=59)
    prev_end = today - _td(days=30)

    with Session(engine) as session:
        active_habits = (
            session.query(Habit)
            .filter(
                Habit.user_id == uid,
                Habit.is_archived.is_(False),
                Habit.active.is_(True),
            )
            .order_by(Habit.sort_order)
            .all()
        )

        habit_ids = [h.id for h in active_habits]

        logs_by_habit: dict = {}
        if habit_ids:
            all_logs = (
                session.query(HabitLog)
                .filter(
                    HabitLog.habit_id.in_(habit_ids),
                    HabitLog.user_id == uid,
                )
                .all()
            )
            for log in all_logs:
                logs_by_habit.setdefault(str(log.habit_id), []).append(log)

    current_result = _compute_adherence_breakdown(
        active_habits, logs_by_habit, current_start, today
    )

    building_state = current_result["building_state"]

    if building_state["active"]:
        return JSONResponse({
            "per_habit": [],
            "slipping_habits": [],
            "nudges": [],
            "building_state": building_state,
        })

    current_per_habit = current_result["per_habit"]

    prev_result = _compute_adherence_breakdown(
        active_habits, logs_by_habit, prev_start, prev_end
    )
    prev_per_habit = prev_result["per_habit"]

    slipping_habits = _detect_slipping_habits(current_per_habit, prev_per_habit)

    adherence_breakdowns_by_name = {
        entry["name"]: {
            "weekday_pct": entry["weekday_pct"],
            "overall_avg": entry["overall_avg"],
        }
        for entry in current_per_habit
    }
    nudge_result = _build_nudges(adherence_breakdowns_by_name, slipping_habits)
    nudge_result = _apply_llm_nudges(
        nudge_result,
        adherence_breakdowns_by_name,
        slipping_habits,
        user_id=str(uid),
    )

    return JSONResponse({
        "per_habit": current_per_habit,
        "slipping_habits": slipping_habits,
        "nudges": nudge_result["nudges"],
        "building_state": building_state,
    })


# ── Habit v2 CRUD — GET by id, PUT habit-logs upsert, GET habit-logs ──────────

@app.get("/api/habits/{habit_id}")
def get_habit_by_id(habit_id: str, user: User = Depends(resolve_user)):
    """Return a single habit (including archived) or 404.
    MUST be registered after all static /api/habits/* routes."""
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    with Session(engine) as session:
        habit = _habits_repo.get_habit(session, hid, user.id)
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        return JSONResponse(_habit_dict_v2(habit))


@app.put("/api/habit-logs")
def put_habit_log(body: HabitLogUpsertIn, user: User = Depends(resolve_user)):
    """Upsert a habit log for (habit_id, log_date); 422 if log_date is in the future."""
    try:
        hid = _uuid.UUID(body.habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    try:
        log_date = _date.fromisoformat(body.log_date)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid log_date; use YYYY-MM-DD")
    utc_today = _datetime.now(_timezone.utc).date()
    if log_date > utc_today:
        return JSONResponse(
            status_code=422,
            content={"error": "log_date cannot be in the future", "details": ""},
        )
    with Session(engine) as session:
        habit = _habits_repo.get_habit(session, hid, user.id)
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        log, was_inserted = _habits_repo.upsert_habit_log(
            session, hid, user.id, log_date, body.value, body.note
        )
        status = 201 if was_inserted else 200
        return JSONResponse(status_code=status, content=_habit_log_dict_v2(log))


@app.get("/api/habit-logs")
def get_habit_logs_v2(
    habit_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: User = Depends(resolve_user),
):
    """Return logs for a habit within an inclusive date range; 400 if dates missing."""
    if from_date is None or to_date is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Both 'from' and 'to' query parameters are required", "details": ""},
        )
    if habit_id is None:
        return JSONResponse(
            status_code=400,
            content={"error": "habit_id query parameter is required", "details": ""},
        )
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    try:
        from_d = _date.fromisoformat(from_date)
        to_d = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    with Session(engine) as session:
        logs = _habits_repo.get_habit_logs(session, hid, user.id, from_d, to_d)
        return JSONResponse([_habit_log_dict_v2(lg) for lg in logs])



@app.get("/api/stats/active-streak")
def get_active_streak(current_user: User = Depends(resolve_user)):
    uid = current_user.id

    from datetime import timedelta
    from sqlalchemy import text as _sql_text
    today = _date.today()

    with Session(engine) as session:
        rows = session.execute(
            _sql_text("""
                SELECT DISTINCT d FROM (
                    SELECT entry_date AS d FROM weight_entries WHERE user_id = :uid
                    UNION
                    SELECT log_date AS d FROM habit_logs WHERE user_id = :uid
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
    "calendar": "calendar.html",
    "log": "training-log.html",
    "training": "training.html",
    "trends": "trends.html",
    "settings": "settings.html",
    "run-view": "run-view.html",
    "run-builder": "run-builder.html",
    "strength-view": "strength-view.html",
    "sessions": "sessions.html",
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


def _serve_dev_mobile():
    """Local/UAT mobile preview frame (Chrome DevTools–style device width)."""
    env = os.getenv("ENVIRONMENT", "local").lower()
    if env not in ("uat", "local"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(_static_root / "frontend" / "pages" / "dev-mobile.html"))


app.add_api_route("/dev/mobile", _serve_dev_mobile, include_in_schema=False)


def _serve_weight_targets():
    return RedirectResponse(url="/weight", status_code=302)

app.add_api_route("/weight/targets", _serve_weight_targets, include_in_schema=False)


def _serve_projection_redirect():
    # Projection was merged into the Training → Projection sub-tab
    # (issue #1226; tab renamed Plan → Projection in feature/performance-tab-rework).
    return RedirectResponse(url="/log#projection", status_code=302)

app.add_api_route("/projection", _serve_projection_redirect, include_in_schema=False)
app.add_api_route("/projection.html", _serve_projection_redirect, include_in_schema=False)


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
    from datetime import date as _date
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
                WeightEntry.entry_date >= from_d,
                WeightEntry.entry_date <= to_d,
            )
            .all()
        )
        weight_by_date = {str(w.entry_date): float(w.weight_kg) for w in weight_rows}

        # Habit log counts per date
        log_rows = (
            session.query(HabitLog.log_date)
            .filter(
                HabitLog.user_id == uid,
                HabitLog.log_date >= from_d,
                HabitLog.log_date <= to_d,
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
    sets_json: Optional[str] = None  # JSON array of per-set detail (strength)


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
    # Stryd workout-level aggregates (Run Builder SYNC fields)
    avg_power: Optional[int] = None
    max_power: Optional[int] = None
    np: Optional[int] = None
    avg_cadence_spm: Optional[int] = None
    avg_stride_m: Optional[float] = None
    # Environmental conditions for heat/humidity normalization (issue #1168)
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None


class WorkoutPatch(BaseModel):
    name: Optional[str] = None
    workout_date: Optional[str] = None
    workout_type: Optional[str] = None
    run_subtype: Optional[str] = None
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
    # Stryd workout-level aggregates (Run Builder SYNC fields)
    avg_power: Optional[int] = None
    max_power: Optional[int] = None
    np: Optional[int] = None
    avg_cadence_spm: Optional[int] = None
    avg_stride_m: Optional[float] = None
    # Environmental conditions for heat/humidity normalization (issue #1168)
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    # Self-reported effort feeling (issue #1241): 'hard' | 'ok' | 'easy' | null.
    feeling: Optional[str] = None


class WorkoutDuplicateIn(BaseModel):
    workout_date: str  # YYYY-MM-DD — the date the copy should land on


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
    if ex.sets_json is not None:
        if len(ex.sets_json) > 8000:
            raise HTTPException(status_code=422, detail="sets_json too large")
        try:
            parsed = _json.loads(ex.sets_json)
        except Exception:
            raise HTTPException(status_code=422, detail="sets_json must be valid JSON")
        if not isinstance(parsed, list):
            raise HTTPException(status_code=422, detail="sets_json must be a JSON array")


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
        "sets_json": e.sets_json,
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


def _normalize_workout_type(t: str | None) -> str | None:
    """Canonicalize run type casing on write ('Run'/'Running' → 'run').

    Runs must be stored as lowercase 'run' so run-scoped queries (scoring,
    guardrail) match. Other types are passed through trimmed, unchanged.
    Run subtypes (interval/longrun/easy/tempo) are a SEPARATE column
    (``run_subtype``) — workout_type stays 'run' so the row keeps the full run
    pipeline (detail layout, decoupling, PRs, run counts).
    """
    if t is None:
        return None
    t = t.strip()
    if t.lower() in ("run", "running"):
        return "run"
    return t


# Allowed run-subtype values (issue: run subtype as its own column). None clears it.
_RUN_SUBTYPE_VALUES = {"interval", "longrun", "easy", "tempo"}
# Self-reported effort feeling (issue #1241).
_FEELING_VALUES = frozenset({"hard", "ok", "easy"})


def _workout_signal_scores(session, workout) -> dict:
    """Per-session endurance/speed scores for the signal card.

    Returns the athlete's score as of this workout's date (``*_current``) and
    the delta that date contributed (current minus the score as of the day
    before) as ``*_delta``. Any value is None when it can't be computed
    (non-run, no prefs, insufficient data). Multiple runs on the same date are
    attributed together (delta ≈ that day's contribution).
    """
    from backend.services.running_performance import (
        compute_endurance_score,
        compute_speed_score,
    )
    from backend.services.zone_constants import make_zone_constants
    from backend.services.lap_classify import classify_laps

    if (workout.workout_type or "").lower() != "run" or workout.workout_date is None:
        return {}

    prefs_row = (
        session.query(UserPreferences)
        .filter(UserPreferences.user_id == workout.user_id)
        .first()
    )
    prefs_dict = {}
    if prefs_row is not None:
        prefs_dict = {
            "ftp_w": prefs_row.ftp_w,
            "threshold_hr": prefs_row.threshold_hr,
            "threshold_pace_seconds_per_km": prefs_row.threshold_pace_seconds_per_km,
            "aerobic_decoupling_threshold": getattr(prefs_row, "aerobic_decoupling_threshold", None),
            "duration_curve_bests": None,
        }
    zone_constants = make_zone_constants()
    try:
        compute_decoupling = _compute_decoupling
    except Exception:
        compute_decoupling = None

    _today = _date.today()
    _window_start = _today - _timedelta(days=89)
    run_workouts = (
        session.query(Workout)
        .options(load_only(
            Workout.id, Workout.user_id, Workout.workout_date, Workout.start_time,
            Workout.workout_type, Workout.duration_seconds, Workout.distance_km,
            Workout.tss, Workout.avg_hr, Workout.avg_power, Workout.name,
            Workout.speed_signal, Workout.speed_signal_basis,
            Workout.speed_signal_window_seconds,
        ))
        .filter(
            Workout.user_id == workout.user_id,
            Workout.workout_type == "run",
            Workout.workout_date >= _window_start,
        )
        .order_by(Workout.workout_date.asc(), Workout.start_time.asc().nulls_last())
        .all()
    )
    # Batch all splits in one query to avoid N+1 across the athlete's runs.
    wids = [wk.id for wk in run_workouts]
    splits_by_wk: dict = {}
    if wids:
        for s in (
            session.query(WorkoutSplit)
            .options(load_only(
                WorkoutSplit.workout_id, WorkoutSplit.split_index,
                WorkoutSplit.avg_power, WorkoutSplit.avg_hr,
                WorkoutSplit.distance_km, WorkoutSplit.duration_seconds,
                WorkoutSplit.intensity_band,
            ))
            .filter(WorkoutSplit.workout_id.in_(wids))
            .order_by(WorkoutSplit.split_index)
            .all()
        ):
            splits_by_wk.setdefault(s.workout_id, []).append(s)

    def _build(max_date, before_date=None):
        runs = []
        for wk in run_workouts:
            if wk.workout_date > max_date:
                continue
            if before_date is not None and wk.workout_date >= before_date:
                continue
            splits = splits_by_wk.get(wk.id, [])
            laps = [
                {
                    "band": cls.get("band"),
                    "avg_power": s.avg_power,
                    "avg_hr": s.avg_hr,
                    "distance_km": float(s.distance_km) if s.distance_km is not None else None,
                    "duration_seconds": s.duration_seconds,
                }
                for s, cls in zip(splits, classify_laps(splits, prefs_dict))
            ]
            dpct = None
            if compute_decoupling is not None:
                try:
                    # Correct signature (workout, splits, threshold) → tuple,
                    # matching get_athlete_performance so the scores reconcile.
                    # (The old swapped-arg call silently produced dpct=None here,
                    #  making this path's endurance disagree with Performance.)
                    dres, _ = compute_decoupling(
                        {"workout_type": wk.workout_type},
                        [
                            {
                                "split_index": s.split_index,
                                "duration_seconds": s.duration_seconds,
                                "avg_hr": s.avg_hr,
                                "avg_power": s.avg_power,
                                "distance_km": float(s.distance_km) if s.distance_km is not None else None,
                            }
                            for s in splits
                        ],
                        (prefs_dict or {}).get("aerobic_decoupling_threshold"),
                    )
                    dpct = dres.get("decoupling_pct") if dres else None
                except Exception:
                    _log.warning(
                        "compute_decoupling failed for workout %s", wk.id, exc_info=True
                    )
                    dpct = None
            runs.append(
                {
                    "run_id": str(wk.id),
                    "workout_date": wk.workout_date.isoformat() if wk.workout_date else "",
                    "laps": laps,
                    "decoupling_pct": dpct,
                    "avg_power": wk.avg_power,
                    "avg_hr": wk.avg_hr,
                    "distance_km": float(wk.distance_km) if wk.distance_km is not None else None,
                    "duration_seconds": wk.duration_seconds,
                    "speed_signal": wk.speed_signal,
                    "speed_signal_basis": wk.speed_signal_basis,
                    "speed_signal_window_seconds": wk.speed_signal_window_seconds,
                    "ftp_w": (prefs_dict or {}).get("ftp_w"),
                }
            )
        return runs

    d = workout.workout_date

    def _score(fn, runs, race_perf):
        r = fn(runs, prefs_dict or None, zone_constants, race_perf=race_perf)
        s = r.get("score") if isinstance(r, dict) else None
        return s if isinstance(s, (int, float)) and not isinstance(s, bool) else None

    # "One score everywhere": *_current is the athlete's score AS OF TODAY —
    # identical to the Performance tab and identical on every workout card. The
    # per-session distinction lives entirely in *_delta = the contribution this
    # session's DATE made (score as-of-that-date minus score as-of the day
    # before). Race VDOT floor is taken at the matching date for each.
    _race_today = _latest_race_perf(session, workout.user_id, as_of=_today)
    _race_asof = _latest_race_perf(session, workout.user_id, as_of=d)
    _race_prev = _latest_race_perf(session, workout.user_id, as_of=(d - _timedelta(days=1)) if d else None)

    today_runs = _build(_today)
    e_cur = _score(compute_endurance_score, today_runs, _race_today)
    s_cur = _score(compute_speed_score, today_runs, _race_today)

    asof = _build(d)
    prev = _build(d, before_date=d)
    e_asof = _score(compute_endurance_score, asof, _race_asof)
    s_asof = _score(compute_speed_score, asof, _race_asof)
    e_prev = _score(compute_endurance_score, prev, _race_prev)
    s_prev = _score(compute_speed_score, prev, _race_prev)
    return {
        "endurance_score_current": round(e_cur, 1) if e_cur is not None else None,
        "endurance_score_delta": round(e_asof - e_prev, 1) if e_asof is not None and e_prev is not None else None,
        "speed_score_current": round(s_cur, 1) if s_cur is not None else None,
        "speed_score_delta": round(s_asof - s_prev, 1) if s_asof is not None and s_prev is not None else None,
    }


def _athlete_scores_as_of(session, user_id, as_of_date) -> dict:
    """Endurance/speed score for the athlete AS OF ``as_of_date``.

    Uses the SAME machinery as ``_workout_signal_scores`` (the numbers shown on
    the workout-detail/log card) — all run workouts with ``workout_date <=
    as_of_date`` scored via compute_endurance_score / compute_speed_score. This
    is deliberately the athlete-scale score, not a pace inversion, so a
    completed race's demonstrated score matches the log for that date.

    Returns ``{"endurance": float|None, "speed": float|None}``.
    """
    from backend.services.running_performance import (
        compute_endurance_score,
        compute_speed_score,
    )
    from backend.services.zone_constants import make_zone_constants
    from backend.services.lap_classify import classify_laps

    if as_of_date is None:
        return {"endurance": None, "speed": None}

    prefs_row = (
        session.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )
    prefs_dict = {}
    if prefs_row is not None:
        prefs_dict = {
            "ftp_w": prefs_row.ftp_w,
            "threshold_hr": prefs_row.threshold_hr,
            "threshold_pace_seconds_per_km": prefs_row.threshold_pace_seconds_per_km,
            "aerobic_decoupling_threshold": getattr(prefs_row, "aerobic_decoupling_threshold", None),
            "duration_curve_bests": None,
        }
    zone_constants = make_zone_constants()
    try:
        compute_decoupling = _compute_decoupling
    except Exception:
        compute_decoupling = None

    _window_start = as_of_date - _timedelta(days=89)
    run_workouts = (
        session.query(Workout)
        .options(load_only(
            Workout.id, Workout.user_id, Workout.workout_date, Workout.start_time,
            Workout.workout_type, Workout.duration_seconds, Workout.distance_km,
            Workout.tss, Workout.avg_hr, Workout.avg_power, Workout.name,
            Workout.speed_signal, Workout.speed_signal_basis,
            Workout.speed_signal_window_seconds,
        ))
        .filter(
            Workout.user_id == user_id,
            Workout.workout_type == "run",
            Workout.workout_date >= _window_start,
            Workout.workout_date <= as_of_date,
        )
        .order_by(Workout.workout_date.asc(), Workout.start_time.asc().nulls_last())
        .all()
    )
    wids = [wk.id for wk in run_workouts]
    splits_by_wk: dict = {}
    if wids:
        for s in (
            session.query(WorkoutSplit)
            .options(load_only(
                WorkoutSplit.workout_id, WorkoutSplit.split_index,
                WorkoutSplit.avg_power, WorkoutSplit.avg_hr,
                WorkoutSplit.distance_km, WorkoutSplit.duration_seconds,
                WorkoutSplit.intensity_band,
            ))
            .filter(WorkoutSplit.workout_id.in_(wids))
            .order_by(WorkoutSplit.split_index)
            .all()
        ):
            splits_by_wk.setdefault(s.workout_id, []).append(s)

    runs = []
    for wk in run_workouts:
        if wk.workout_date is None or wk.workout_date > as_of_date:
            continue
        splits = splits_by_wk.get(wk.id, [])
        laps = [
            {
                "band": cls.get("band"),
                "avg_power": s.avg_power,
                "avg_hr": s.avg_hr,
                "distance_km": float(s.distance_km) if s.distance_km is not None else None,
                "duration_seconds": s.duration_seconds,
            }
            for s, cls in zip(splits, classify_laps(splits, prefs_dict))
        ]
        dpct = None
        if compute_decoupling is not None:
            try:
                # Correct signature (workout, splits, threshold) → tuple, matching
                # get_athlete_performance so the as-of scores reconcile with it.
                dres, _ = compute_decoupling(
                    {"workout_type": wk.workout_type},
                    [
                        {
                            "split_index": s.split_index,
                            "duration_seconds": s.duration_seconds,
                            "avg_hr": s.avg_hr,
                            "avg_power": s.avg_power,
                            "distance_km": float(s.distance_km) if s.distance_km is not None else None,
                        }
                        for s in splits
                    ],
                    (prefs_dict or {}).get("aerobic_decoupling_threshold"),
                )
                dpct = dres.get("decoupling_pct") if dres else None
            except Exception:
                _log.warning(
                    "compute_decoupling failed for workout %s", wk.id, exc_info=True
                )
                dpct = None
        runs.append(
            {
                "run_id": str(wk.id),
                "workout_date": wk.workout_date.isoformat() if wk.workout_date else "",
                "laps": laps,
                "decoupling_pct": dpct,
                "avg_power": wk.avg_power,
                "avg_hr": wk.avg_hr,
                "distance_km": float(wk.distance_km) if wk.distance_km is not None else None,
                "duration_seconds": wk.duration_seconds,
                "speed_signal": wk.speed_signal,
                "speed_signal_basis": wk.speed_signal_basis,
                "speed_signal_window_seconds": wk.speed_signal_window_seconds,
                "ftp_w": (prefs_dict or {}).get("ftp_w"),
            }
        )

    _race_perf = _latest_race_perf(session, user_id, as_of=as_of_date)

    def _score(fn):
        r = fn(runs, prefs_dict or None, zone_constants, race_perf=_race_perf)
        s = r.get("score") if isinstance(r, dict) else None
        return s if isinstance(s, (int, float)) and not isinstance(s, bool) else None

    e = _score(compute_endurance_score)
    s = _score(compute_speed_score)
    return {
        "endurance": round(e, 1) if e is not None else None,
        "speed": round(s, 1) if s is not None else None,
    }


def _compute_session_signals(w: Workout) -> dict:
    """Derive display-ready signal fields for a workout.

    Returns the 5 flat keys required by issue #1052:
    endurance_signal, endurance_signal_note, speed_signal, speed_signal_note,
    contributes_to.
    """
    es = w.endurance_signal
    ss = w.speed_signal

    dur = w.duration_seconds or 0
    if es is None:
        if dur <= 40 * 60:
            endurance_note = "— run under 40 min"
        else:
            endurance_note = "— insufficient data"
    else:
        endurance_note = None

    speed_note = "— no hard effort" if ss is None else None

    has_endurance = es is not None
    has_speed = ss is not None
    if has_endurance and has_speed:
        hint = "feeds both endurance and speed training signals."
    elif has_endurance:
        hint = "feeds endurance through low drift, nothing to speed — expected for an easy run."
    elif has_speed:
        hint = "feeds speed, not endurance — short or high-intensity effort."
    else:
        hint = "No signal recorded for this session."

    return {
        "endurance_signal": float(es) if es is not None else None,
        "endurance_signal_note": endurance_note,
        "speed_signal": float(ss) if ss is not None else None,
        "speed_signal_note": speed_note,
        "contributes_to": hint,
    }


def _workout_dict(w: Workout, exercises: list) -> dict:
    strava_act = getattr(w, "strava_activity", None)
    return {
        "id": str(w.id),
        "user_id": str(w.user_id),
        "name": w.name,
        "workout_date": str(w.workout_date),
        "workout_type": w.workout_type,
        "run_subtype": w.run_subtype,
        "remarks": w.remarks,
        "tss": int(w.tss) if w.tss is not None else None,
        "tss_source": w.tss_source,
        "tss_method": w.tss_method,
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
        # Workout-level Stryd aggregates (null → render "—").
        "avg_power": w.avg_power,
        "max_power": w.max_power,
        "np": w.np,
        "avg_cadence_spm": w.avg_cadence_spm,
        "avg_stride_m": float(w.avg_stride_m) if w.avg_stride_m is not None else None,
        "temperature_c": w.temperature_c,
        "humidity_pct": w.humidity_pct,
        "flat_equivalent_pace": float(w.flat_equivalent_pace) if w.flat_equivalent_pace is not None else None,
        "feeling": w.feeling,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "exercises": [_exercise_dict(e) for e in exercises],
        **_best_values_dict(w),
        **_compute_session_signals(w),
    }


def _strava_source_dict(sa, prebuilt_streams: dict | None = None) -> dict | None:
    """Full Strava capture for a workout: promoted columns + everything inside the
    detail_payload (laps, per-km splits, best efforts, GPS polyline) and the raw
    per-point streams. Nothing dropped — the union endpoint surfaces all of it.

    When ``prebuilt_streams`` is supplied (from the activity_streams table, already
    downsampled to ≤1 Hz), it is used directly and ``sa.streams_payload`` is never
    accessed, avoiding a 1-5 MB JSONB load per request (issue #1295).
    """
    if sa is None:
        return None
    detail = sa.detail_payload or {}
    raw = sa.raw_payload or {}
    if prebuilt_streams is not None:
        streams = prebuilt_streams
    else:
        streams = sa.streams_payload if isinstance(sa.streams_payload, dict) else {}
    map_obj = detail.get("map") or raw.get("map") or {}
    return {
        "strava_activity_id": sa.strava_activity_id,
        "name": sa.name,
        "activity_type": sa.activity_type,
        "start_time": sa.start_time.isoformat() if sa.start_time else None,
        "distance_km": float(sa.distance_km) if sa.distance_km is not None else None,
        "duration_seconds": sa.duration_seconds,
        "avg_hr": sa.avg_hr,
        "max_hr": sa.max_hr,
        "elevation_m": sa.elevation_m,
        "avg_power_w": sa.avg_power_w,
        "max_power_w": sa.max_power_w,
        "avg_cadence": float(sa.avg_cadence) if sa.avg_cadence is not None else None,
        "suffer_score": sa.suffer_score,
        "device_name": sa.device_name,
        "external_id": sa.external_id,
        "is_stryd_synced": sa.is_stryd_synced,
        # full nested capture (Tier 2 detail)
        "laps": detail.get("laps") or [],
        "splits_metric": detail.get("splits_metric") or [],
        "best_efforts": detail.get("best_efforts") or [],
        "segment_efforts": detail.get("segment_efforts") or [],
        "calories": detail.get("calories"),
        "description": detail.get("description"),
        "gear": detail.get("gear"),
        "map_polyline": map_obj.get("polyline") or map_obj.get("summary_polyline"),
        # Tier 3 streams
        "stream_types": sorted(streams.keys()),
        "streams": streams,
    }


def _stryd_source_dict(sta) -> dict | None:
    """Full Stryd capture: power-based TSS + running dynamics Strava cannot give."""
    if sta is None:
        return None
    # Use pre-computed laps persisted at sync-time (issue #1295).  Avoids
    # materialising the full streams_payload (can be several MB) on every request.
    # Falls back to computing from streams_payload for rows synced before this change.
    manual_laps = getattr(sta, "manual_laps", None)
    if manual_laps is not None:
        laps = manual_laps
    else:
        from backend.services.stryd_laps import compute_manual_laps
        streams = sta.streams_payload if isinstance(sta.streams_payload, dict) else {}
        laps = compute_manual_laps(streams) or ((sta.raw_payload or {}).get("laps") or [])
    return {
        "stryd_activity_id": sta.stryd_activity_id,
        "name": sta.name,
        "start_time": sta.start_time.isoformat() if sta.start_time else None,
        "distance_km": float(sta.distance_km) if sta.distance_km is not None else None,
        "duration_seconds": sta.duration_seconds,
        "avg_power_w": sta.avg_power_w,
        "avg_hr": sta.avg_hr,
        "tss": sta.tss,
        "form_metrics": sta.form_metrics or {},
        "power_zones": sta.power_zones or {},
        "splits": sta.splits or [],
        "laps": laps,
    }


def _unified_workout_dict(w: Workout, strava: dict | None, stryd: dict | None) -> dict:
    """Best-of union across sources — one merged running view with provenance.

    Precedence: workout row (already best-merged by reconcile) wins for core
    fields; Stryd wins for power/TSS/dynamics; Strava wins for laps/GPS/effort.
    """
    def _pick(*vals):
        for v in vals:
            if v is not None:
                return v
        return None

    laps = strava["laps"] if strava else []
    # Per-distance splits: prefer Stryd power splits, else Strava per-km splits.
    splits = (stryd["splits"] if stryd and stryd["splits"] else (strava["splits_metric"] if strava else []))
    return {
        "distance_km": float(w.distance_km) if w.distance_km is not None else _pick(
            stryd and stryd["distance_km"], strava and strava["distance_km"]),
        "duration_seconds": _pick(w.duration_seconds, stryd and stryd["duration_seconds"], strava and strava["duration_seconds"]),
        "avg_hr": _pick(w.avg_hr, stryd and stryd["avg_hr"], strava and strava["avg_hr"]),
        "max_hr": _pick(w.max_hr, strava and strava["max_hr"]),
        "avg_power_w": _pick(stryd and stryd["avg_power_w"], strava and strava["avg_power_w"]),
        "max_power_w": _pick(strava and strava["max_power_w"]),
        "avg_cadence": _pick(strava and strava["avg_cadence"]),
        "elevation_m": _pick(w.elevation_m, strava and strava["elevation_m"]),
        "calories": _pick(strava and strava["calories"]),
        "tss": _pick(w.tss, stryd and stryd["tss"]),
        "tss_source": _pick(w.tss_source, "stryd" if (stryd and stryd["tss"] is not None) else None),
        "relative_effort": _pick(strava and strava["suffer_score"]),
        "laps": laps,
        "splits": splits,
        "gps_polyline": _pick(strava and strava["map_polyline"]),
        "has_gps_stream": bool(strava and "latlng" in strava["stream_types"]),
        "dynamics": stryd["form_metrics"] if stryd else {},
        "power_zones": stryd["power_zones"] if stryd else {},
        "best_efforts": strava["best_efforts"] if strava else [],
    }


def _downsample_streams(streams: dict, mode: str, target: int = 120) -> dict:
    """Shrink raw per-point streams for transport.

    mode='none' → {} ; 'full' → untouched ; 'summary' (default) → each series
    downsampled to ~target points plus min/max/avg (latlng/bool series keep
    points only). Keeps /full chart-ready without shipping thousands of points.
    """
    if not isinstance(streams, dict) or mode == "none":
        return {}
    if mode == "full":
        return streams
    out: dict = {}
    for k, v in streams.items():
        data = v.get("data") if isinstance(v, dict) else None
        if not isinstance(data, list) or not data:
            out[k] = {"n": 0, "data": []}
            continue
        n = len(data)
        step = max(1, n // target)
        entry = {"n": n, "data": data[::step]}
        if k != "latlng":
            nums = [x for x in data if isinstance(x, (int, float)) and not isinstance(x, bool)]
            if nums:
                entry["min"] = min(nums)
                entry["max"] = max(nums)
                entry["avg"] = round(sum(nums) / len(nums), 2)
        out[k] = entry
    return out


def _compute_derived(strava: dict | None, stryd: dict | None) -> dict:
    """Server-derived running metrics from the raw streams + sources.

    Assumptions are explicit in `_assumptions`: NP/IF treat the power stream as
    ~1 Hz and IF uses Stryd critical power when present. All keys omitted when
    their input stream is absent — never fabricated.
    """
    out: dict = {}
    streams = (strava or {}).get("streams") or {}

    def _series(name):
        v = streams.get(name)
        data = v.get("data") if isinstance(v, dict) else None
        return [x for x in data if isinstance(x, (int, float)) and not isinstance(x, bool)] if isinstance(data, list) else []

    watts = _series("watts")
    if watts:
        avg = sum(watts) / len(watts)
        win = min(30, len(watts))
        roll = [sum(watts[i:i + win]) / win for i in range(0, max(1, len(watts) - win + 1))]
        np_ = round((sum(p ** 4 for p in roll) / len(roll)) ** 0.25, 1) if roll else None
        out["normalized_power_w"] = np_
        out["avg_power_w"] = round(avg, 1)
        if np_ and avg:
            out["variability_index"] = round(np_ / avg, 3)
        cp = ((stryd or {}).get("power_zones") or {}).get("critical_power_w")
        if np_ and cp:
            out["intensity_factor"] = round(np_ / cp, 3)

    hr = _series("heartrate")
    vel = _series("velocity_smooth")
    if hr and vel and len(hr) == len(vel) and len(hr) >= 4:
        half = len(hr) // 2

        def _ratio(hs, vs):
            vv = [x for x in vs if x > 0]
            if not hs or not vv:
                return None
            return (sum(hs) / len(hs)) / (sum(vv) / len(vv))

        r1 = _ratio(hr[:half], vel[:half])
        r2 = _ratio(hr[half:], vel[half:])
        if r1 and r2:
            out["hr_decoupling_pct"] = round((r2 / r1 - 1) * 100, 1)

    pz = {k: v for k, v in ((stryd or {}).get("power_zones") or {}).items() if str(k).startswith("z")}
    if pz:
        out["time_in_power_zone_s"] = pz

    if out:
        out["_assumptions"] = "NP/IF assume ~1Hz power stream; IF uses Stryd critical power."
    return out


def _workout_list_dict(w: Workout, exercise_count: int) -> dict:
    src = w.source or ""
    return {
        "id": str(w.id),
        "workout_date": str(w.workout_date),
        "name": w.name,
        "workout_type": w.workout_type,
        "run_subtype": w.run_subtype,
        "remarks": w.remarks,
        "tss": w.tss,
        "tss_source": w.tss_source,
        "source": w.source,
        "has_strava": "strava" in src or w.strava_activity_pk is not None,
        "has_stryd": "stryd" in src or w.stryd_activity_pk is not None,
        "strava_activity_url": w.strava_activity_url,
        "distance_km": float(w.distance_km) if w.distance_km is not None else None,
        "duration_seconds": w.duration_seconds,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "elevation_m": w.elevation_m,
        "zone2_minutes": w.zone2_minutes,
        "exercise_count": exercise_count,
        "feeling": w.feeling,
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
            .options(
                joinedload(Workout.strava_activity),
                joinedload(Workout.stryd_activity),
            )
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
            )
            .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
            .all()
        )
        workout_ids = [w.id for w in workouts]
        exercise_counts: dict = {}
        if workout_ids:
            rows = (
                session.query(
                    WorkoutExercise.workout_id,
                    func.count().label("cnt"),
                )
                .filter(WorkoutExercise.workout_id.in_(workout_ids))
                .group_by(WorkoutExercise.workout_id)
                .all()
            )
            exercise_counts = {row.workout_id: row.cnt for row in rows}
        result = [
            _workout_list_dict(w, exercise_counts.get(w.id, 0))
            for w in workouts
        ]
        return JSONResponse(result)


def _recent_workout_dict(w) -> dict:
    """Compact recent-workout row for the 24h attach/override picker (issue #1242)."""
    dist = float(w.distance_km) if w.distance_km is not None else None
    dur_min = round(w.duration_seconds / 60) if w.duration_seconds else None
    bits = []
    if dur_min:
        bits.append(str(dur_min) + "min")
    if dist:
        bits.append(("%.1f" % dist) + " km")
    if w.tss is not None:
        bits.append(str(round(float(w.tss))) + " TSS")
    return {
        "id": str(w.id),
        "name": w.name,
        "workout_type": w.workout_type,
        "run_subtype": w.run_subtype,
        "source": w.source,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "start_time": w.start_time.isoformat() if w.start_time else None,
        "duration_seconds": w.duration_seconds,
        "distance_km": dist,
        "meta": " · ".join(bits),
    }


@app.get("/api/workouts/recent")
def get_recent_workouts(
    hours: int = Query(24, ge=1, le=168),
    user: User = Depends(resolve_user),
):
    """Workouts logged/synced in the last ``hours`` (default 24) for the user.

    Ordered newest-first by created_at (when it was logged or synced — catches a
    just-synced run and a just-entered manual workout alike). Includes manual
    entries (source='manual'). Powers the Plan card's attach/override picker.
    """
    cutoff = _datetime.now(_timezone.utc) - _timedelta(hours=hours)
    with Session(engine) as session:
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == user.id,
                Workout.created_at >= cutoff,
            )
            .order_by(Workout.created_at.desc())
            .all()
        )
        return JSONResponse([_recent_workout_dict(w) for w in workouts])


@app.get("/api/workouts/recent-type")
def get_recent_workout_type(user: User = Depends(resolve_user)):
    """Most recently logged workout_type for the session user (issue #525).

    Powers the quick-add form's default Type: the form pre-selects whatever the
    user logged last so they don't re-pick their usual type on every quick log.
    Returns ``{"workout_type": null}`` when the user has no workout history (the
    form then keeps its built-in default).

    The default is derived from the user's own workout history and scoped to the
    session user via ``resolve_user`` — so it is persisted per user, not per
    browser session, and never leaks across users.

    Registered before ``/api/workouts/{workout_id}`` so the literal path is not
    captured as a workout id.
    """
    with Session(engine) as session:
        row = (
            session.query(Workout.workout_type)
            .filter(Workout.user_id == user.id)
            .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
            .first()
        )
    workout_type = row[0] if row and row[0] and row[0].strip() else None
    return JSONResponse({"workout_type": workout_type})


@app.get("/api/exercises/names")
def get_exercise_names(user: User = Depends(resolve_user)):
    """Distinct exercise names for the session user, for autocomplete (issue #531).

    Replaces the ~10 full workout-detail fetches loadSuggestions used to fire
    just to populate the exercise-name datalist — one query, names only.
    """
    with Session(engine) as session:
        rows = (
            session.query(WorkoutExercise.name)
            .join(Workout, WorkoutExercise.workout_id == Workout.id)
            .filter(
                Workout.user_id == user.id,
                WorkoutExercise.name.isnot(None),
            )
            .distinct()
            .order_by(WorkoutExercise.name)
            .all()
        )
        names = [r[0] for r in rows if r[0] and r[0].strip()]
        return JSONResponse(names)


# ── Intensity distribution chart data ───────────────────────────────────────
# Declared BEFORE /api/workouts/{workout_id} so the literal path isn't parsed as an id.


def _accumulate_intensity_window(workouts, prefs_dict):
    """Duration-weighted rolling-window aggregation shared by intensity-distribution
    and polarized-check endpoints.

    Each Workout in *workouts* must have its .splits already loaded (e.g. via
    selectinload) so this function issues no additional DB queries.

    Returns:
        sessions_out   list of per-workout dicts (date, workout_id, name,
                       duration_seconds, low_pct, moderate_pct, high_pct)
        rolling_window dict with low_pct / moderate_pct / high_pct, all None
                       when no workouts have classifiable band data.
    """
    sessions_out = []
    total_dur = 0.0
    total_low = 0.0
    total_mod = 0.0
    total_high = 0.0

    for w in workouts:
        zones = _agg_zones(w.splits, prefs_dict)
        dur = w.duration_seconds or 0

        if zones["low_pct"] is not None and dur > 0:
            total_dur += dur
            total_low  += dur * zones["low_pct"]
            total_mod  += dur * zones["moderate_pct"]
            total_high += dur * zones["high_pct"]

        sessions_out.append({
            "date":             w.workout_date.isoformat(),
            "workout_id":       str(w.id),
            "name":             w.name,
            "duration_seconds": dur or None,
            "low_pct":          zones["low_pct"],
            "moderate_pct":     zones["moderate_pct"],
            "high_pct":         zones["high_pct"],
        })

    if total_dur == 0:
        rolling_window = {"low_pct": None, "moderate_pct": None, "high_pct": None}
    else:
        rolling_window = {
            "low_pct":      round(total_low  / total_dur, 2),
            "moderate_pct": round(total_mod  / total_dur, 2),
            "high_pct":     round(total_high / total_dur, 2),
        }

    return sessions_out, rolling_window


@app.get("/api/workouts/intensity-distribution")
def get_intensity_distribution(
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    user: User = Depends(resolve_user),
):
    """Per-session and rolling-window intensity distribution for the chart (issue #1133).

    Returns one entry per workout in the date range with low/moderate/high
    percentage breakdown derived from lap band data, plus a duration-weighted
    aggregate across all sessions (rolling_window).
    """
    uid = user.id
    try:
        from_d = _date.fromisoformat(from_date)
        to_d = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")

    with Session(engine) as session:
        prefs = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == uid)
            .first()
        )
        prefs_dict = {
            "ftp_w": prefs.ftp_w if prefs is not None else None,
            "threshold_hr": prefs.threshold_hr if prefs is not None else None,
            "threshold_pace_seconds_per_km": (
                prefs.threshold_pace_seconds_per_km if prefs is not None else None
            ),
        }

        workouts = (
            session.query(Workout)
            .options(
                load_only(
                    Workout.id, Workout.workout_date, Workout.name,
                    Workout.duration_seconds, Workout.workout_type, Workout.created_at,
                ),
                selectinload(Workout.splits).options(load_only(
                    WorkoutSplit.workout_id, WorkoutSplit.split_index,
                    WorkoutSplit.avg_power, WorkoutSplit.avg_hr,
                    WorkoutSplit.distance_km, WorkoutSplit.duration_seconds,
                    WorkoutSplit.intensity_band,
                )),
            )
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
            )
            .order_by(Workout.workout_date.asc(), Workout.created_at.asc())
            .all()
        )

        sessions_out, rolling_window = _accumulate_intensity_window(workouts, prefs_dict)

    return JSONResponse({"sessions": sessions_out, "rolling_window": rolling_window})


@app.get("/api/workouts/polarized-check")
def get_polarized_check(
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    user: User = Depends(resolve_user),
):
    """Polarized-split on-target vs grey-zone verdict for the date window (issue #1134).

    Computes the duration-weighted rolling window split (same logic as
    /api/workouts/intensity-distribution) and runs check_polarized_split to
    produce an authoritative verdict field.  The frontend indicator reads
    'verdict' directly — no client-side recalculation.

    Returns:
        verdict:    "on-target" | "grey-zone" | null (null when no band data)
        actual:     {low, moderate, high} percentage values | null
        targets:    {low, moderate, high} each a [lo, hi] list
        deviations: list of {band, direction} for off-target bands
        grey_zone:  bool — True when moderate band exceeds its upper bound
    """
    uid = user.id
    try:
        from_d = _date.fromisoformat(from_date)
        to_d = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")

    with Session(engine) as session:
        prefs = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == uid)
            .first()
        )
        prefs_dict = {
            "ftp_w": prefs.ftp_w if prefs is not None else None,
            "threshold_hr": prefs.threshold_hr if prefs is not None else None,
            "threshold_pace_seconds_per_km": (
                prefs.threshold_pace_seconds_per_km if prefs is not None else None
            ),
        }

        workouts = (
            session.query(Workout)
            .options(selectinload(Workout.splits))
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
            )
            .order_by(Workout.workout_date.asc(), Workout.created_at.asc())
            .all()
        )

        _, rolling_window = _accumulate_intensity_window(workouts, prefs_dict)

    targets = {k: list(v) for k, v in _POLARIZED_BOUNDS.items()}

    if rolling_window["low_pct"] is None:
        return JSONResponse({
            "verdict":    None,
            "actual":     None,
            "targets":    targets,
            "deviations": [],
            "grey_zone":  False,
        })

    actual_low  = rolling_window["low_pct"]
    actual_mod  = rolling_window["moderate_pct"]
    actual_high = rolling_window["high_pct"]

    check = _check_polarized_split(actual_low, actual_mod, actual_high)

    verdict = "on-target" if check["on_target"] else "grey-zone"

    return JSONResponse({
        "verdict":    verdict,
        "actual":     {"low": actual_low, "moderate": actual_mod, "high": actual_high},
        "targets":    targets,
        "deviations": check["deviations"],
        "grey_zone":  check["grey_zone"],
    })


# ── Removed (tombstoned) synced workouts ────────────────────────────────────
# Declared BEFORE /api/workouts/{workout_id} so "removed" isn't parsed as an id.

@app.get("/api/workouts/removed")
def list_removed_workouts(user: User = Depends(resolve_user)):
    """List synced activities the user removed from their log (restorable)."""
    with Session(engine) as session:
        rows = (
            session.query(RemovedActivity)
            .filter(RemovedActivity.user_id == user.id)
            .order_by(RemovedActivity.removed_at.desc())
            .all()
        )
        return JSONResponse([
            {
                "id": str(r.id),
                "source": r.source,
                "external_id": r.external_id,
                "name": r.workout_name,
                "workout_date": r.workout_date.isoformat() if r.workout_date else None,
                "removed_at": r.removed_at.isoformat() if r.removed_at else None,
            }
            for r in rows
        ])


@app.post("/api/workouts/removed/{removed_id}/restore", status_code=200)
def restore_removed_workout(removed_id: str, user: User = Depends(resolve_user)):
    """Clear a tombstone and rebuild the workout from the cached activity.

    Deletes the removed-activity row, then runs reconcile so the workout
    reappears (rebuilt from the still-cached Strava/Stryd activity).
    """
    try:
        rid = _uuid.UUID(removed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid removed_id")
    with Session(engine) as session:
        row = session.get(RemovedActivity, rid)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Removed workout not found")
        session.delete(row)
        session.commit()
    try:
        _reconcile.reconcile_workouts(user.id, user.id)
    except Exception as _rc_exc:
        _logging.getLogger(__name__).warning(
            "reconcile after restore failed for user %s: %s", user.id, _rc_exc
        )
    return JSONResponse({"restored": True})


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
        data = _workout_dict(workout, exercises)
        data.update(_workout_signal_scores(session, workout))
        return JSONResponse(data)


@app.get("/api/workouts/{workout_id}/full")
def get_workout_full(
    workout_id: str,
    streams: str = Query("summary"),
    user: User = Depends(resolve_user),
):
    """Maximal union of a workout across every source.

    Returns the core workout, per-source blocks (full Strava detail+streams,
    full Stryd dynamics), a best-of merged `unified` view, a server-`computed`
    metrics block (Normalized Power, IF, HR decoupling, …), and `field_coverage`
    showing which source(s) supplied each metric. This is the read model the
    running-log detail UI will draw from — capture is complete; what to surface
    is a frontend decision.

    `streams` controls per-point payload size: `summary` (default, downsampled +
    min/max/avg), `full` (every point), or `none`.
    """
    if streams not in ("summary", "full", "none"):
        raise HTTPException(status_code=422, detail="streams must be one of: summary, full, none")
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = (
            session.query(Workout)
            .options(
                joinedload(Workout.strava_activity),
                joinedload(Workout.stryd_activity),
            )
            .filter(Workout.id == wid)
            .one_or_none()
        )
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
        split_rows = (
            session.query(WorkoutSplit)
            .filter(WorkoutSplit.workout_id == wid)
            .order_by(WorkoutSplit.split_index)
            .all()
        )
        prefs = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == workout.user_id)
            .first()
        )
        tss_result = _compute_running_tss(workout, split_rows, prefs or UserPreferences())
        from backend.models import ActivityStream as _ActivityStream
        from backend.services.activity_streams import activity_streams_to_strava_dict as _as_to_strava
        _stream_row = session.get(_ActivityStream, workout.id)
        _prebuilt_streams = _as_to_strava(_stream_row) if _stream_row else None
        strava = _strava_source_dict(getattr(workout, "strava_activity", None), prebuilt_streams=_prebuilt_streams)
        stryd = _stryd_source_dict(getattr(workout, "stryd_activity", None))
        unified = _unified_workout_dict(workout, strava, stryd)
        # Derive metrics from the full streams BEFORE downsampling for transport.
        computed = _compute_derived(strava, stryd)
        # Compute aerobic decoupling from full streams (before downsampling).
        _decoupling_threshold = getattr(prefs, "aerobic_decoupling_threshold", None) if prefs else None
        _workout_dict_plain = {
            "workout_type": workout.workout_type,
            "duration_seconds": workout.duration_seconds,
            "avg_hr": workout.avg_hr,
        }
        _raw_streams = (strava or {}).get("streams") or {} if strava else {}
        _splits_plain = [
            {
                "split_index": s.split_index,
                "duration_seconds": s.duration_seconds,
                "avg_hr": s.avg_hr,
                "avg_power": s.avg_power,
                "distance_km": float(s.distance_km) if s.distance_km is not None else None,
            }
            for s in split_rows
        ]
        _decoupling_input = _raw_streams if _raw_streams else (_splits_plain or None)
        _aerobic_result, _aerobic_reason = _compute_decoupling(
            _workout_dict_plain, _decoupling_input, _decoupling_threshold
        )
        # Apply heat/humidity correction when environmental data is present (AC4).
        if _aerobic_result is not None:
            _heat_factor, _heat_active = _compute_heat_correction_factor(
                temperature_c=getattr(workout, "temperature_c", None),
                humidity_pct=getattr(workout, "humidity_pct", None),
            )
            if _heat_active:
                _aerobic_result = _apply_heat_correction(
                    _aerobic_result, _heat_factor, _decoupling_threshold
                )
        if strava is not None:
            strava["streams"] = _downsample_streams(strava.get("streams") or {}, streams)
        coverage = {
            "strava": bool(strava),
            "stryd": bool(stryd),
            "has_laps": bool(unified["laps"]),
            "has_splits": bool(unified["splits"]),
            "has_gps": bool(unified["gps_polyline"]) or unified["has_gps_stream"],
            "has_streams": bool(strava and strava["stream_types"]),
            "has_dynamics": bool(unified["dynamics"]),
            "has_power": unified["avg_power_w"] is not None,
            "has_tss": unified["tss"] is not None,
        }
        # Authoritative TSS: manual entry wins; fall back to freshly-computed value.
        authoritative_tss = int(workout.tss) if workout.tss is not None else tss_result["tss"]
        # Manual lap presses expose real interval reps that stored 1 km splits hide;
        # pass them so detection/pairing runs on them.  Use the persisted manual_laps
        # column (issue #1295) to avoid re-materialising streams_payload.
        _manual_laps_for_profile = None
        try:
            _sta = getattr(workout, "stryd_activity", None)
            if _sta is not None:
                _persisted = getattr(_sta, "manual_laps", None)
                if _persisted is not None:
                    _mlaps = _persisted
                else:
                    _streams = _sta.streams_payload if isinstance(_sta.streams_payload, dict) else None
                    from backend.services.stryd_laps import compute_manual_laps as _cml
                    _mlaps = _cml(_streams) if _streams else []
            else:
                _mlaps = []
            if _mlaps:
                from types import SimpleNamespace as _SNS
                _manual_laps_for_profile = [
                    _SNS(
                        split_index=_i + 1,
                        duration_seconds=_l.get("duration_seconds"),
                        distance_km=_l.get("distance_km"),
                        avg_power=_l.get("avg_power"),
                        avg_hr=_l.get("avg_hr"),
                        lap_type="manual",
                    )
                    for _i, _l in enumerate(_mlaps)
                ]
        except Exception:
            _manual_laps_for_profile = None
        detected_profile = _get_session_profile(
            workout, split_rows, prefs, manual_laps=_manual_laps_for_profile
        )
        _prefs_dict_for_zones = {
            "ftp_w": prefs.ftp_w if prefs is not None else None,
            "threshold_hr": prefs.threshold_hr if prefs is not None else None,
            "threshold_pace_seconds_per_km": (
                prefs.threshold_pace_seconds_per_km if prefs is not None else None
            ),
        }
        intensity_zones = _agg_zones(split_rows, _prefs_dict_for_zones)
        _workout_block = _workout_dict(workout, exercises)
        _workout_block.update(_workout_signal_scores(session, workout))
        response_body: dict = {
            "workout": _workout_block,
            "splits": [_split_dict(s) for s in split_rows],
            "sources": {"strava": strava, "stryd": stryd},
            "unified": unified,
            "computed": computed,
            "field_coverage": coverage,
            "tss": authoritative_tss,
            "tss_method": tss_result["method"],
            "tss_partial": tss_result["partial"],
            "computed_tss": tss_result["tss"],
            "detected_profile": detected_profile,
            "aerobic_decoupling": _aerobic_result,
            "intensity_zones": intensity_zones,
        }
        if _aerobic_reason is not None:
            response_body["aerobic_decoupling_reason"] = _aerobic_reason
        return JSONResponse(response_body)


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
    if body.strava_activity_url is not None and body.strava_activity_url != "":
        if not body.strava_activity_url.startswith("https://"):
            raise HTTPException(status_code=422, detail="strava_activity_url must use the https scheme")
    for ex in body.exercises:
        _validate_exercise(ex)
    with Session(engine) as session:
        workout = Workout(
            user_id=uid,
            name=name,
            workout_date=workout_date,
            workout_type=_normalize_workout_type(body.workout_type),
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
            avg_power=body.avg_power,
            max_power=body.max_power,
            np=body.np,
            avg_cadence_spm=body.avg_cadence_spm,
            avg_stride_m=body.avg_stride_m,
            temperature_c=body.temperature_c,
            humidity_pct=body.humidity_pct,
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
                sets_json=ex.sets_json,
            )
            session.add(e)
            exercises.append(e)
        session.commit()
        session.refresh(workout)
        for e in exercises:
            session.refresh(e)
        try:
            _persist_running_tss(workout.id, session)
            session.commit()
            session.refresh(workout)
        except Exception as _tss_exc:
            _logging.getLogger(__name__).warning(
                "persist_running_tss failed for workout %s: %s", workout.id, _tss_exc, exc_info=True
            )
        try:
            daily_update(str(uid), workout_date)
        except Exception as _exc:
            _logging.getLogger(__name__).warning(
                "daily_update failed for user %s date %s: %s", uid, workout_date, _exc, exc_info=True
            )
        try:
            _recompute_autofill(uid, _week_start_bangkok(workout_date))
        except Exception as _af_exc:
            _logging.getLogger(__name__).warning(
                "autofill recompute failed for user %s week %s: %s", uid, workout_date, _af_exc
            )
        try:
            _run_checkpoint_autodetection(workout)
        except Exception as _cd_exc:
            _logging.getLogger(__name__).warning(
                "checkpoint autodetection failed for workout %s: %s", workout.id, _cd_exc, exc_info=True
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
        _old_workout_date = workout.workout_date
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
            workout.workout_type = _normalize_workout_type(t)
        if 'run_subtype' in body.model_fields_set:
            # None/empty clears it; otherwise must be one of the allowed values.
            rs = body.run_subtype
            if rs is None or (isinstance(rs, str) and rs.strip() == ""):
                workout.run_subtype = None
            else:
                rs = rs.strip().lower()
                if rs not in _RUN_SUBTYPE_VALUES:
                    raise HTTPException(
                        status_code=422,
                        detail="run_subtype must be one of: " + ", ".join(sorted(_RUN_SUBTYPE_VALUES)),
                    )
                workout.run_subtype = rs
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
            if body.strava_activity_url is not None and body.strava_activity_url != "":
                if not body.strava_activity_url.startswith("https://"):
                    raise HTTPException(status_code=422, detail="strava_activity_url must use the https scheme")
            workout.strava_activity_url = body.strava_activity_url
        if 'avg_power' in body.model_fields_set:
            workout.avg_power = body.avg_power
        if 'max_power' in body.model_fields_set:
            workout.max_power = body.max_power
        if 'np' in body.model_fields_set:
            workout.np = body.np
        if 'avg_cadence_spm' in body.model_fields_set:
            workout.avg_cadence_spm = body.avg_cadence_spm
        if 'avg_stride_m' in body.model_fields_set:
            workout.avg_stride_m = body.avg_stride_m
        if 'temperature_c' in body.model_fields_set:
            workout.temperature_c = body.temperature_c
        if 'humidity_pct' in body.model_fields_set:
            workout.humidity_pct = body.humidity_pct
        if 'feeling' in body.model_fields_set:
            # None/empty clears it; otherwise must be one of the allowed values.
            fl = body.feeling
            if fl is None or (isinstance(fl, str) and fl.strip() == ""):
                workout.feeling = None
            else:
                fl = fl.strip().lower()
                if fl not in _FEELING_VALUES:
                    raise HTTPException(
                        status_code=422,
                        detail="feeling must be one of: " + ", ".join(sorted(_FEELING_VALUES)),
                    )
                workout.feeling = fl
        # Stamp updated_at so edits (e.g. marking a run as an interval) change the
        # workout-set fingerprint — the summary/performance cache signature
        # includes MAX(updated_at), so a type edit busts the cache and the
        # Performance Speed feed refreshes without waiting for a new sync.
        workout.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        exercises = (
            session.query(WorkoutExercise)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order)
            .all()
        )
        session.refresh(workout)
        try:
            _persist_running_tss(wid, session)
            session.commit()
            session.refresh(workout)
        except Exception as _tss_exc:
            _logging.getLogger(__name__).warning(
                "persist_running_tss failed for workout %s: %s", wid, _tss_exc, exc_info=True
            )
        try:
            daily_update(str(workout.user_id), workout.workout_date)
        except Exception as _exc:
            _logging.getLogger(__name__).warning(
                "daily_update failed for user %s date %s: %s", workout.user_id, workout.workout_date, _exc, exc_info=True
            )
        try:
            for _ws in {_week_start_bangkok(_old_workout_date), _week_start_bangkok(workout.workout_date)}:
                _recompute_autofill(workout.user_id, _ws)
        except Exception as _af_exc:
            _logging.getLogger(__name__).warning(
                "autofill recompute failed for user %s: %s", workout.user_id, _af_exc
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
        _del_date = workout.workout_date
        _del_uid = workout.user_id
        # Tombstone any linked synced activities so the next sync/reconcile does
        # NOT recreate this workout. Snapshot name/date for the Removed list.
        _tombstone_links = []
        if workout.strava_activity_pk is not None:
            sa_row = session.get(StravaActivity, workout.strava_activity_pk)
            if sa_row is not None:
                _tombstone_links.append(("strava", str(sa_row.strava_activity_id)))
        if workout.stryd_activity_pk is not None:
            st_row = session.get(StrydActivity, workout.stryd_activity_pk)
            if st_row is not None:
                _tombstone_links.append(("stryd", str(st_row.stryd_activity_id)))
        for _src, _ext in _tombstone_links:
            exists = (
                session.query(RemovedActivity.id)
                .filter(
                    RemovedActivity.user_id == _del_uid,
                    RemovedActivity.source == _src,
                    RemovedActivity.external_id == _ext,
                )
                .first()
            )
            if exists is None:
                session.add(RemovedActivity(
                    user_id=_del_uid,
                    source=_src,
                    external_id=_ext,
                    workout_name=workout.name,
                    workout_date=workout.workout_date,
                ))
        session.delete(workout)
        session.commit()
    try:
        _recompute_autofill(_del_uid, _week_start_bangkok(_del_date))
    except Exception as _af_exc:
        _logging.getLogger(__name__).warning(
            "autofill recompute failed for user %s week %s: %s", _del_uid, _del_date, _af_exc
        )
    return Response(status_code=204)


# ── Planned sessions (new Plan tab — weekly training schedule) ────────────────
# Distinct from Projection's ramp/taper load model (TrainingPlan/PlannedLoad).
# Link-only: matched_workout_id → workouts.id; Log tab unchanged.

_PLANNED_SESSION_TYPES = {"run", "strength", "plyo", "rest"}
_PLANNED_STATUSES = {"planned", "missed", "needs_review", "done_auto", "done_manual"}


class PlannedSessionIn(BaseModel):
    planned_date: str
    session_type: str
    name: Optional[str] = None
    structure: Optional[dict] = None
    notes: Optional[str] = None


class PlannedSessionPatch(BaseModel):
    planned_date: Optional[str] = None
    session_type: Optional[str] = None
    name: Optional[str] = None
    structure: Optional[dict] = None
    notes: Optional[str] = None


class PlannedSessionMatchIn(BaseModel):
    workout_id: str


def _validate_planned_type(t: str) -> str:
    t = (t or "").strip().lower()
    if t not in _PLANNED_SESSION_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"field": "session_type", "error": "must be one of: " + ", ".join(sorted(_PLANNED_SESSION_TYPES))},
        )
    return t


def _validate_planned_date(s: str) -> _date:
    try:
        return _date.fromisoformat((s or "").strip())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"field": "planned_date", "error": "must be ISO YYYY-MM-DD"},
        )


def _workout_actual_summary(w) -> dict:
    """Compact actual-workout summary attached to a matched planned session."""
    dist = float(w.distance_km) if w.distance_km is not None else None
    dur_min = round(w.duration_seconds / 60) if w.duration_seconds else None
    bits = []
    if dur_min:
        bits.append(str(dur_min) + "min")
    if w.tss is not None:
        bits.append(str(round(float(w.tss))) + " TSS")
    elif dist:
        bits.append(("%.1f" % dist) + " km")
    return {
        "id": str(w.id),
        "name": w.name,
        "workout_type": w.workout_type,
        "run_subtype": w.run_subtype,
        "date": str(w.workout_date),
        "distance_km": dist,
        "duration_seconds": w.duration_seconds,
        "tss": float(w.tss) if w.tss is not None else None,
        "feeling": w.feeling,
        "meta": " · ".join(bits),
    }


def _planned_session_dict(p, matched=None) -> dict:
    return {
        "id": str(p.id),
        "planned_date": str(p.planned_date),
        "session_type": p.session_type,
        "name": p.name,
        "structure": p.structure,
        "notes": p.notes,
        "status": p.status,
        "matched_workout_id": str(p.matched_workout_id) if p.matched_workout_id else None,
        "actual": _workout_actual_summary(matched) if matched is not None else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _ghost_workout_dict(w) -> dict:
    dist = float(w.distance_km) if w.distance_km is not None else None
    dur_min = round(w.duration_seconds / 60) if w.duration_seconds else None
    bits = []
    if dur_min:
        bits.append(str(dur_min) + "min")
    if dist:
        bits.append(("%.1f" % dist) + " km")
    return {
        "id": str(w.id),
        "name": w.name,
        "workout_type": w.workout_type,
        "run_subtype": w.run_subtype,
        "date": str(w.workout_date),
        "meta": " · ".join(bits) or "—",
    }


def _get_planned_session_or_404(session, ps_id: str, user: User):
    try:
        pid = _uuid.UUID(ps_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid planned_session id")
    row = session.get(PlannedSession, pid)
    if row is None:
        raise HTTPException(status_code=404, detail="Planned session not found")
    if row.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return row


@app.get("/api/planned-sessions")
def get_planned_sessions(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    user: User = Depends(resolve_user),
):
    """Week bundle: planned sessions (each with status + matched actual summary)
    plus unplanned/ghost workouts, grouped by day for the Plan tab.

    Shape:
      {"from","to","days":[{"date","dow","planned":[<session dict>...],
        "unplanned":[<ghost dict>...]}]}
    """
    from datetime import timedelta as _td
    from backend.services import plan_matching as _pm

    today = _date.today()
    # Default to the current Monday–Sunday ISO week.
    if from_date:
        start = _validate_planned_date(from_date)
    else:
        start = today - _td(days=today.weekday())
    if to_date:
        end = _validate_planned_date(to_date)
    else:
        end = start + _td(days=6)
    if end < start:
        raise HTTPException(status_code=422, detail={"field": "to", "error": "to must be >= from"})

    uid = user.id
    with Session(engine) as session:
        rows = (
            session.query(PlannedSession)
            .filter(
                PlannedSession.user_id == uid,
                PlannedSession.planned_date >= start,
                PlannedSession.planned_date <= end,
            )
            .order_by(PlannedSession.planned_date, PlannedSession.created_at)
            .all()
        )
        matched_map = {}
        wanted = [r.matched_workout_id for r in rows if r.matched_workout_id is not None]
        if wanted:
            for w in session.query(Workout).filter(Workout.id.in_(wanted)).all():
                matched_map[w.id] = w

        ghost_ids = _pm.unplanned_workout_ids(session, uid, start, end)
        ghost_map = {}
        if ghost_ids:
            for w in session.query(Workout).filter(Workout.id.in_(list(ghost_ids))).all():
                ghost_map[w.id] = w

        # Group by day across the full range (empty days included → Rest day UI).
        _DOW = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        by_day = {}
        d = start
        while d <= end:
            by_day[d] = {"date": str(d), "dow": _DOW[d.weekday()], "planned": [], "unplanned": []}
            d += _td(days=1)
        for r in rows:
            bucket = by_day.get(r.planned_date)
            if bucket is None:
                continue
            matched = matched_map.get(r.matched_workout_id) if r.matched_workout_id else None
            d = _planned_session_dict(r, matched)
            # Attach the ±1-day candidate pool so the UI can offer a confirm list
            # for a needs_review session even when the candidate is on an
            # adjacent day (ghosts only surface same-day workouts).
            if r.status == "needs_review":
                d["candidates"] = [_ghost_workout_dict(w) for w in _pm.review_candidates(session, uid, r)]
            bucket["planned"].append(d)
        for wid, w in ghost_map.items():
            bucket = by_day.get(w.workout_date)
            if bucket is not None:
                bucket["unplanned"].append(_ghost_workout_dict(w))

        days = [by_day[k] for k in sorted(by_day.keys())]
        return JSONResponse({"from": str(start), "to": str(end), "days": days})


@app.post("/api/planned-sessions", status_code=201)
def create_planned_session(body: PlannedSessionIn, user: User = Depends(resolve_user)):
    ptype = _validate_planned_type(body.session_type)
    pdate = _validate_planned_date(body.planned_date)
    with Session(engine) as session:
        row = PlannedSession(
            user_id=user.id,
            planned_date=pdate,
            session_type=ptype,
            name=(body.name or None),
            structure=body.structure,
            notes=(body.notes.strip() if body.notes else None),
            status="planned",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return JSONResponse(status_code=201, content=_planned_session_dict(row))


@app.post("/api/planned-sessions/bulk", status_code=201)
def create_planned_sessions_bulk(body: list[PlannedSessionIn], user: User = Depends(resolve_user)):
    if not isinstance(body, list) or not body:
        raise HTTPException(status_code=422, detail="Expected a non-empty array of sessions")
    created = []
    with Session(engine) as session:
        for item in body:
            ptype = _validate_planned_type(item.session_type)
            pdate = _validate_planned_date(item.planned_date)
            row = PlannedSession(
                user_id=user.id,
                planned_date=pdate,
                session_type=ptype,
                name=(item.name or None),
                structure=item.structure,
                notes=(item.notes.strip() if item.notes else None),
                status="planned",
            )
            session.add(row)
            created.append(row)
        session.commit()
        for row in created:
            session.refresh(row)
        return JSONResponse(status_code=201, content=[_planned_session_dict(r) for r in created])


@app.patch("/api/planned-sessions/{ps_id}")
def patch_planned_session(ps_id: str, body: PlannedSessionPatch, user: User = Depends(resolve_user)):
    with Session(engine) as session:
        row = _get_planned_session_or_404(session, ps_id, user)
        if body.planned_date is not None:
            new_date = _validate_planned_date(body.planned_date)
            # Rescheduling a missed session resets it to planned (mock behavior).
            if row.status == "missed" and new_date != row.planned_date:
                row.status = "planned"
            row.planned_date = new_date
        if body.session_type is not None:
            row.session_type = _validate_planned_type(body.session_type)
        if body.name is not None:
            row.name = body.name or None
        if "structure" in body.model_fields_set:
            row.structure = body.structure
        if body.notes is not None:
            row.notes = body.notes.strip() or None
        row.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(row)
        matched = session.get(Workout, row.matched_workout_id) if row.matched_workout_id else None
        return JSONResponse(_planned_session_dict(row, matched))


@app.delete("/api/planned-sessions/{ps_id}", status_code=204)
def delete_planned_session(ps_id: str, user: User = Depends(resolve_user)):
    with Session(engine) as session:
        row = _get_planned_session_or_404(session, ps_id, user)
        session.delete(row)
        session.commit()
    return Response(status_code=204)


@app.post("/api/planned-sessions/{ps_id}/match")
def match_planned_session(ps_id: str, body: PlannedSessionMatchIn, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(body.workout_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        row = _get_planned_session_or_404(session, ps_id, user)
        workout = session.get(Workout, wid)
        if workout is None or workout.user_id != user.id:
            raise HTTPException(status_code=404, detail="Workout not found")
        row.matched_workout_id = wid
        row.status = "done_manual"
        row.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(row)
        return JSONResponse(_planned_session_dict(row, workout))


@app.post("/api/planned-sessions/{ps_id}/unmatch")
def unmatch_planned_session(ps_id: str, user: User = Depends(resolve_user)):
    with Session(engine) as session:
        row = _get_planned_session_or_404(session, ps_id, user)
        row.matched_workout_id = None
        row.status = "planned"
        row.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(row)
        return JSONResponse(_planned_session_dict(row))


@app.post("/api/planned-sessions/{ps_id}/miss")
def miss_planned_session(ps_id: str, user: User = Depends(resolve_user)):
    with Session(engine) as session:
        row = _get_planned_session_or_404(session, ps_id, user)
        row.matched_workout_id = None
        row.status = "missed"
        row.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(row)
        return JSONResponse(_planned_session_dict(row))


@app.post("/api/planned-sessions/{ps_id}/mark-done")
def mark_done_planned_session(ps_id: str, user: User = Depends(resolve_user)):
    """Manually mark a session complete with no linked workout data — for when
    sync never captured it (e.g. the watch wasn't started). Distinct from
    /match, which always links a real Workout row."""
    with Session(engine) as session:
        row = _get_planned_session_or_404(session, ps_id, user)
        row.matched_workout_id = None
        row.status = "done_manual"
        row.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(row)
        return JSONResponse(_planned_session_dict(row))


@app.post("/api/planned-sessions/reconcile")
def reconcile_planned_sessions(user: User = Depends(resolve_user)):
    """Run the planned-session matcher on demand for the current user."""
    from backend.services import plan_matching as _pm
    with Session(engine) as session:
        result = _pm.reconcile_user(session, user.id)
    return JSONResponse(result)


@app.post("/api/workouts/{workout_id}/duplicate", status_code=201)
def duplicate_workout(workout_id: str, body: WorkoutDuplicateIn, user: User = Depends(resolve_user)):
    """Create a full, independent copy of an existing workout on a new date.

    The copy carries over the workout's manual fields and every exercise
    (sets/reps/weights/etc.). It is recorded as a fresh manual entry: source is
    cleared and any Strava/Stryd links are dropped so the copy is independently
    editable and not subject to sync reconciliation (issue #524).
    """
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    try:
        new_date = _date.fromisoformat(body.workout_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid workout_date; use YYYY-MM-DD")
    if new_date > _date.today():
        raise HTTPException(status_code=422, detail="workout_date cannot be in the future")

    with Session(engine) as session:
        src = session.get(Workout, wid)
        if src is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if src.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")

        src_exercises = (
            session.query(WorkoutExercise)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order)
            .all()
        )

        src_splits = (
            session.query(WorkoutSplit)
            .filter(WorkoutSplit.workout_id == wid)
            .order_by(WorkoutSplit.split_index)
            .all()
        )

        copy = Workout(
            user_id=user.id,
            name=src.name,
            workout_date=new_date,
            workout_type=src.workout_type,
            remarks=src.remarks,
            tss=src.tss,
            tss_source='manual' if src.tss is not None else None,
            distance_km=src.distance_km,
            duration_seconds=src.duration_seconds,
            avg_hr=src.avg_hr,
            max_hr=src.max_hr,
            elevation_m=src.elevation_m,
            zone2_minutes=src.zone2_minutes,
            source='manual',
        )
        session.add(copy)
        session.flush()

        new_exercises = []
        for ex in src_exercises:
            e = WorkoutExercise(
                workout_id=copy.id,
                display_order=ex.display_order,
                name=ex.name,
                sets=ex.sets,
                reps=ex.reps,
                weight_kg=ex.weight_kg,
                duration=ex.duration,
                rpe=ex.rpe,
                distance_km=ex.distance_km,
                duration_seconds=ex.duration_seconds,
                avg_hr=ex.avg_hr,
                sets_json=ex.sets_json,
            )
            session.add(e)
            new_exercises.append(e)

        for sp in src_splits:
            session.add(WorkoutSplit(
                workout_id=copy.id,
                split_index=sp.split_index,
                distance_km=sp.distance_km,
                duration_seconds=sp.duration_seconds,
                avg_hr=sp.avg_hr,
                avg_power=sp.avg_power,
                cadence_spm=sp.cadence_spm,
                stride_length_m=sp.stride_length_m,
                lap_type=sp.lap_type,
                intensity_band=sp.intensity_band,
            ))

        session.commit()
        session.refresh(copy)
        for e in new_exercises:
            session.refresh(e)

        try:
            daily_update(str(user.id), new_date)
        except Exception as _exc:
            _logging.getLogger(__name__).warning(
                "daily_update failed for user %s date %s: %s", user.id, new_date, _exc, exc_info=True
            )
        try:
            _recompute_autofill(user.id, _week_start_bangkok(new_date))
        except Exception as _af_exc:
            _logging.getLogger(__name__).warning(
                "autofill recompute failed for user %s week %s: %s", user.id, new_date, _af_exc, exc_info=True
            )
        return JSONResponse(status_code=201, content=_workout_dict(copy, new_exercises))


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


class ExercisesReplaceIn(BaseModel):
    exercises: list[ExerciseIn]


@app.post("/api/workouts/{workout_id}/exercises/replace", status_code=200)
def replace_exercises(workout_id: str, body: ExercisesReplaceIn, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    for ex in body.exercises:
        _validate_exercise(ex)
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if workout.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        session.query(WorkoutExercise).filter(WorkoutExercise.workout_id == wid).delete()
        new_exercises = []
        for i, ex in enumerate(body.exercises):
            new_ex = WorkoutExercise(
                workout_id=wid,
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
                sets_json=ex.sets_json,
            )
            session.add(new_ex)
            new_exercises.append(new_ex)
        session.commit()
        for ex in new_exercises:
            session.refresh(ex)
        session.refresh(workout)
        return JSONResponse(_workout_dict(workout, new_exercises))


class ComputeTSSIn(BaseModel):
    session_rpe: Optional[int] = None  # 1-10; if provided, overrides workout.session_rpe


@app.post("/api/workouts/{workout_id}/compute-tss", status_code=200)
def compute_workout_tss(workout_id: str, body: ComputeTSSIn, user: User = Depends(resolve_user)):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    if body.session_rpe is not None and not (1 <= body.session_rpe <= 10):
        raise HTTPException(status_code=422, detail="session_rpe must be between 1 and 10")
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
        prefs = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == workout.user_id)
            .first()
        ) or UserPreferences()

        # Build lightweight proxies so compute_strength_tss can do dict/attr access.
        # Apply module-level defaults for scale/max when user prefs are unset.
        class _WorkoutProxy:
            def __init__(self, w, rpe_override):
                self.duration_seconds = w.duration_seconds
                self.session_rpe = rpe_override if rpe_override is not None else getattr(w, 'session_rpe', None)
            def __getitem__(self, k):
                return getattr(self, k)

        class _PrefsProxy:
            def __init__(self, p):
                self.strength_tss_scale = getattr(p, 'strength_tss_scale', None) or _STRENGTH_TSS_SCALE
                self.strength_tss_max = getattr(p, 'strength_tss_max', None) or _STRENGTH_TSS_MAX
            def __getitem__(self, k):
                return getattr(self, k)

        proxy = _WorkoutProxy(workout, body.session_rpe)
        prefs_proxy = _PrefsProxy(prefs)
        result = _compute_strength_tss(proxy, exercises, prefs_proxy)

        if result["tss"] is None:
            raise HTTPException(
                status_code=422,
                detail="Cannot compute TSS: " + result.get("debug", {}).get("reason", "missing inputs")
            )

        workout.tss = result["tss"]
        workout.tss_source = "calculated"
        workout.tss_method = result["method"]
        session.commit()
        session.refresh(workout)
        return JSONResponse({
            **_workout_dict(workout, exercises),
            "tss_debug": result.get("debug"),
        })


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
            # Run-segment templates carry distance/duration/HR (run builder)
            "distance_km": ex.get("distance_km"),
            "duration_seconds": ex.get("duration_seconds"),
            "avg_hr": ex.get("avg_hr"),
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


@app.delete("/api/workout-templates/{template_id}", status_code=204)
def delete_workout_template(template_id: str, user: User = Depends(resolve_user)):
    try:
        tid = _uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid template_id")
    with Session(engine) as session:
        tmpl = session.get(WorkoutTemplate, tid)
        if tmpl is None:
            raise HTTPException(status_code=404, detail="Template not found")
        if tmpl.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        session.delete(tmpl)
        session.commit()
    return Response(status_code=204)


# ── Workout splits endpoints ──────────────────────────────────────────────────

class SplitIn(BaseModel):
    split_index: int
    distance_km: float
    duration_seconds: int
    avg_hr: Optional[int] = None
    avg_power: Optional[int] = None
    cadence_spm: Optional[int] = None
    stride_length_m: Optional[float] = None
    lap_type: Optional[str] = "auto"


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
        "avg_power": s.avg_power,
        "cadence_spm": s.cadence_spm,
        "stride_length_m": float(s.stride_length_m) if s.stride_length_m is not None else None,
        "lap_type": s.lap_type if s.lap_type is not None else "auto",
        "intensity_band": s.intensity_band,
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
        if s.lap_type is not None and s.lap_type not in ("auto", "manual"):
            raise HTTPException(status_code=422, detail="lap_type must be 'auto' or 'manual'")
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
                avg_power=s.avg_power,
                cadence_spm=s.cadence_spm,
                stride_length_m=s.stride_length_m,
                lap_type=s.lap_type if s.lap_type is not None else "auto",
            )
            session.add(split)
            new_splits.append(split)
        session.commit()
        for split in new_splits:
            session.refresh(split)
        new_splits.sort(key=lambda x: x.split_index)
        # Classify each lap by intensity band and persist to DB.
        try:
            from backend.services.lap_classify import classify_laps as _classify_laps_for_splits
            prefs_row = (
                session.query(UserPreferences)
                .filter(UserPreferences.user_id == workout.user_id)
                .first()
            )
            prefs_dict = {
                "ftp_w": prefs_row.ftp_w if prefs_row is not None else None,
                "threshold_hr": prefs_row.threshold_hr if prefs_row is not None else None,
                "threshold_pace_seconds_per_km": (
                    prefs_row.threshold_pace_seconds_per_km if prefs_row is not None else None
                ),
            }
            classifications = _classify_laps_for_splits(new_splits, prefs_dict)
            for split, clf in zip(new_splits, classifications):
                split.intensity_band = clf.get("band")
            session.commit()
        except Exception as _band_exc:
            _logging.getLogger(__name__).warning(
                "lap intensity band classification failed for workout %s: %s",
                wid, _band_exc, exc_info=True,
            )
        try:
            _persist_running_tss(wid, session)
            session.commit()
        except Exception as _tss_exc:
            _logging.getLogger(__name__).warning(
                "persist_running_tss failed for workout %s: %s", wid, _tss_exc, exc_info=True
            )
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
    kcal_intake: Optional[int] = None


class DailyMetricBody(BaseModel):
    resting_hr: Optional[int] = None
    hrv: Optional[int] = None
    sleep_hours: Optional[float] = None
    sleep_quality: Optional[int] = None
    energy: Optional[int] = None
    mood: Optional[int] = None
    notes: Optional[str] = None
    kcal_intake: Optional[int] = None


def _validate_metric_fields(
    resting_hr: Optional[int] = None,
    hrv: Optional[int] = None,
    sleep_hours: Optional[float] = None,
    sleep_quality: Optional[int] = None,
    energy: Optional[int] = None,
    mood: Optional[int] = None,
    kcal_intake: Optional[int] = None,
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
    if kcal_intake is not None and kcal_intake <= 0:
        raise HTTPException(status_code=422, detail={"field": "kcal_intake", "error": "kcal_intake must be a positive integer"})


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
        "kcal_intake": m.kcal_intake,
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
        kcal_intake=body.kcal_intake,
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
            kcal_intake=body.kcal_intake,
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
        kcal_intake=body.kcal_intake,
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
        if body.kcal_intake is not None:
            row.kcal_intake = body.kcal_intake
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
        kcal_intake=body.kcal_intake,
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
                kcal_intake=body.kcal_intake,
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
            row.kcal_intake = body.kcal_intake
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
            & (WeightEntry.entry_date == DailyMetric.metric_date),
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

    from sqlalchemy import nullslast
    with Session(engine) as session:
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
    status: Optional[str] = Query(default=None),
    user: User = Depends(resolve_user),
):
    uid = user.id
    with Session(engine) as session:
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
def get_readiness(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    user: User = Depends(resolve_user),
):
    """
    Training-load readiness endpoint with backward-compatible wellness score range.

    Without params: returns CTL, ATL, TSB, readiness_label, series, and
    building_baseline for today's training state. Uses compute_fitness_series to
    derive all metric values; no raw query is present in this branch.

    With both 'from' and 'to' params: returns the legacy wellness readiness score
    range — a list of { date, score } objects (or null) per day in [from, to].
    """
    if from_date is not None or to_date is not None:
        # ── Legacy wellness score range ──────────────────────────────────────────
        if from_date is None:
            raise HTTPException(status_code=400, detail="'from' date is required when 'to' is provided")
        if to_date is None:
            raise HTTPException(status_code=400, detail="'to' date is required when 'from' is provided")

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
                {"uid": str(user.id), "from_d": str(d_from), "to_d": str(d_to)},
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

    # ── Training-load readiness (CTL / ATL / TSB) ────────────────────────────────
    today = _date.today()
    warmup_start = today - _timedelta(days=180)
    series = compute_fitness_series(str(user.id), warmup_start, today)

    window_start = today - _timedelta(days=BASELINE_WINDOW_DAYS)
    workout_days_in_window = sum(
        1 for row in series
        if row["tss"] > 0 and row["date"] >= window_start
    )
    building_baseline = workout_days_in_window < BASELINE_MIN_WORKOUT_DAYS

    if building_baseline:
        return JSONResponse({
            "building_baseline": True,
            "ctl": None,
            "atl": None,
            "tsb": None,
            "readiness_label": None,
            "series": [],
        })

    last = series[-1]
    ctl = round(last["ctl"], 1)
    atl = round(last["atl"], 1)
    tsb = round(last["tsb"], 1)

    series_start = today - _timedelta(days=89)
    chart_series = [
        {
            "date": str(row["date"]),
            "ctl": row["ctl"],
            "atl": row["atl"],
            "tsb": row["tsb"],
        }
        for row in series
        if row["date"] >= series_start
    ]

    return JSONResponse({
        "building_baseline": False,
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "readiness_label": training_readiness_label(tsb),
        "series": chart_series,
    })


@app.get("/api/readiness/current")
def get_readiness_current(user: User = Depends(resolve_user)):
    """Return current fitness state (CTL, ATL, TSB) and building_baseline flag.

    Used by the Readiness widget on the Training > Log sub-tab.

    Response when building_baseline=False:
      { building_baseline: false, ctl, atl, tsb, recovery_hint }
    Response when building_baseline=True:
      { building_baseline: true }
    """
    today = _date.today()
    warmup_start = today - _timedelta(days=180)
    tss_series = daily_tss_series(str(user.id), warmup_start, today)
    _ctl_days, _atl_days = resolve_user_ewma_days(str(user.id))
    load_curves = compute_load_curves(tss_series, ctl_days=_ctl_days, atl_days=_atl_days)

    # Require at least 7 workout days with non-zero TSS in the last 42 days.
    history_window_start = today - _timedelta(days=42)
    workout_days_in_window = sum(
        1 for d, tss in tss_series
        if tss > 0 and d >= history_window_start
    )
    building_baseline = workout_days_in_window < 7

    if building_baseline:
        return JSONResponse({"building_baseline": True})

    last_row = load_curves[-1]
    ctl = round(last_row["ctl"], 1)
    atl = round(last_row["atl"], 1)
    tsb = round(last_row["tsb"], 1)

    return JSONResponse({
        "building_baseline": False,
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "recovery_hint": _load_interpretation(ctl, atl, tsb),
    })


# ── Performance chart endpoint ────────────────────────────────────────────────

@app.get("/api/performance/chart")
def get_performance_chart(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    current_user: User = Depends(resolve_user),
):
    """Return aligned CTL/ATL/TSB/endurance/speed time series for a performance chart.

    Accepts athlete_id, start_date (YYYY-MM-DD), and end_date (YYYY-MM-DD) as
    query parameters.  All error cases return HTTP 200 with empty series arrays
    and a machine-readable reason field instead of raising HTTP errors.

    Empty-payload reasons:
        athlete_not_found   — athlete_id missing or does not match any user
        invalid_date_range  — dates missing, unparseable, or start > end
        no_data_in_range    — athlete exists but no load data falls in range

    Response (normal):
        {
          "dates": ["2026-01-01", ...],
          "ctl": [12.5, ...],
          "atl": [10.0, ...],
          "tsb": [2.5, ...],
          "endurance_score": [null, 45.5, ...],
          "speed_score": [null, 60.0, ...],
          "building_baseline": false,
          "reason": ""
        }
    """
    from backend.services.performance_chart import compute_performance_chart
    from backend.services.daily_load import daily_load_series as _perf_daily_load_series
    from backend.services.lap_classify import classify_laps as _classify_laps
    from backend.services.zone_constants import make_zone_constants as _make_zone_constants
    from backend.services.fitness_model import CTL_TIME_CONSTANT as _CTL_TC

    def _empty_response(reason: str):
        return JSONResponse({
            "dates": [], "ctl": [], "atl": [], "tsb": [],
            "endurance_score": [], "speed_score": [],
            "building_baseline": False,
            "reason": reason,
        })

    # Athlete is the authenticated session user.
    # AC7: both dates are required; missing → invalid_date_range
    if not start_date or not end_date:
        return _empty_response("invalid_date_range")

    # AC7: parse and validate dates
    try:
        d_start = _date.fromisoformat(start_date)
        d_end = _date.fromisoformat(end_date)
    except ValueError:
        return _empty_response("invalid_date_range")

    if d_start > d_end:
        return _empty_response("invalid_date_range")

    # Athlete (user) is the authenticated session user.
    uid = current_user.id

    with Session(engine) as session:
        user_row = session.get(User, uid)
        if user_row is None:
            return _empty_response("athlete_not_found")

        # Fetch workouts with a warmup window so the EWMA can converge
        warmup_start = d_start - _timedelta(days=_CTL_TC * 2)
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= warmup_start,
                Workout.workout_date <= d_end,
            )
            .order_by(Workout.workout_date)
            .all()
        )

        # Build the daily load series for fitness model input
        workout_dicts = [
            {
                "id": str(w.id),
                "date": str(w.workout_date),
                "tss": float(w.tss) if w.tss is not None else None,
            }
            for w in workouts
        ]
        load_series = _perf_daily_load_series(workout_dicts, str(warmup_start), str(d_end))
        if isinstance(load_series, dict):
            # Validation failure from daily_load_series
            return _empty_response("no_data_in_range")

        # Build classified run data for endurance/speed score computation
        run_workouts = [w for w in workouts if w.workout_type.lower() == "run"]

        prefs_row = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == uid)
            .first()
        )
        prefs_dict: dict = {}
        if prefs_row is not None:
            prefs_dict = {
                "ftp_w": prefs_row.ftp_w,
                "threshold_hr": prefs_row.threshold_hr,
                "threshold_pace_seconds_per_km": prefs_row.threshold_pace_seconds_per_km,
            }

        zc = _make_zone_constants(preferences=prefs_dict)

        runs: list[dict] = []
        for w in run_workouts:
            splits = (
                session.query(WorkoutSplit)
                .filter(WorkoutSplit.workout_id == w.id)
                .order_by(WorkoutSplit.split_index)
                .all()
            )
            if not splits:
                continue

            classifications = _classify_laps(splits, prefs_dict)
            laps = []
            for split, clf in zip(splits, classifications):
                laps.append({
                    "band": clf.get("band"),
                    "avg_hr": float(split.avg_hr) if split.avg_hr is not None else None,
                    "avg_power": float(split.avg_power) if split.avg_power is not None else None,
                    "distance_km": float(split.distance_km) if split.distance_km is not None else None,
                    "duration_seconds": float(split.duration_seconds) if split.duration_seconds is not None else None,
                })

            runs.append({
                "run_id": str(w.id),
                "run_date": str(w.workout_date),
                "laps": laps,
                "decoupling_pct": None,
            })

    # Derive body modifier for this user so scores reflect power-to-weight state.
    from backend.services.body_modifier import get_body_modifier_for_user as _get_body_modifier
    _body_modifier = _get_body_modifier(uid)

    # Delegate to the pure computation function
    result = compute_performance_chart(
        daily_load_series=load_series,
        runs=runs,
        preferences=prefs_dict if prefs_dict else {},
        zone_constants=zc,
        start_date=start_date,
        end_date=end_date,
        body_modifier=_body_modifier,
    )

    return JSONResponse(result)


@app.post("/api/performance/backfill")
def post_performance_backfill(user: User = Depends(resolve_user)):
    """Trigger the full performance backfill pipeline for the authenticated athlete.

    Delegated to the compute worker when WORKER_BASE_URL is configured.
    Returns 202 {"worker_delegated": true} when the worker accepts the job.
    Returns 503 when the worker is unreachable and ROUTE_BACKFILL_FALLBACK_TO_INPROCESS
    is not set to "1".

    When WORKER_BASE_URL is not set (local dev / no worker configured), falls back
    to the synchronous in-process pipeline and returns 200 with the summary dict.
    """
    uid = user.id
    worker_base_url = _worker_client.get_worker_base_url()
    if worker_base_url:
        try:
            _worker_client.delegate_backfill(str(uid))
            return JSONResponse({"worker_delegated": True, "started": True}, status_code=202)
        except _worker_client.WorkerUnavailable as exc:
            if os.getenv("ROUTE_BACKFILL_FALLBACK_TO_INPROCESS", "0") != "1":
                raise HTTPException(
                    status_code=503,
                    detail=f"Compute worker unavailable — cannot run backfill: {exc}",
                )
            _logging.getLogger(__name__).warning(
                "Worker unavailable for backfill (user %s); falling back to in-process: %s",
                uid, exc,
            )
    with Session(engine) as session:
        result = _backfill_performance_for_athlete(uid, session)
    return JSONResponse(result)


def _trigger_performance_backfill_background(user_id) -> None:
    """Fire-and-forget: trigger the full performance backfill pipeline.

    Called after threshold saves so TSS and the duration curve are consistent
    with the new thresholds without blocking the HTTP response.  Errors are
    logged but do not propagate.

    When WORKER_BASE_URL is configured, delegates to the compute worker instead
    of spawning a daemon thread in the web process.  Falls back to a daemon
    thread only when the worker is not configured (WORKER_BASE_URL unset).
    """
    _backfill_log = _logging.getLogger(__name__)

    if _worker_client.get_worker_base_url():
        try:
            _worker_client.delegate_backfill(str(user_id))
            return
        except _worker_client.WorkerUnavailable as _exc:
            _backfill_log.warning(
                "Worker unavailable for background backfill (user %s): %s — skipping (not falling back in-process)",
                user_id, _exc,
            )
            return

    def _run():
        try:
            from sqlalchemy.orm import Session as _Session
            with _Session(engine) as _db:
                _backfill_performance_for_athlete(user_id, _db)
        except Exception as _exc:
            _backfill_log.warning(
                "background performance backfill failed for user %s: %s",
                user_id, _exc, exc_info=True,
            )
        try:
            from sqlalchemy.orm import Session as _Session
            from backend.services.backfill_signals import backfill_signals_for_athlete as _backfill_signals
            with _Session(engine) as _db:
                _sig_result = _backfill_signals(user_id, _db)
            if _sig_result.get("reason") is not None:
                _backfill_log.error(
                    "background signal backfill commit failed for user %s: %s",
                    user_id, _sig_result["reason"],
                )
        except Exception as _exc:
            _backfill_log.error(
                "background signal backfill failed for user %s: %s",
                user_id, _exc, exc_info=True,
            )

    t = _threading.Thread(target=_run, daemon=True)
    t.start()


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
    """Return seconds-per-km pace for run/bike workouts; None otherwise.

    Accepts the editor's free-text type values ("Running", "Race") as well as
    the canonical sync values ("run", "bike").
    """
    t = (workout_type or "").lower().strip()
    if not (t in ("run", "running", "race") or t.startswith(("bike", "ride", "cycl"))):
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
    include_load_context: bool = Query(default=False),
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
        q = session.query(Workout).filter(
            Workout.workout_date >= from_d,
            Workout.workout_date <= to_d,
            Workout.user_id == uid,
        )
        if types and types != "all":
            type_list = [t.strip().lower() for t in types.split(",") if t.strip()]
            q = q.filter(func.lower(Workout.workout_type).in_(type_list))
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

        total_workout_days = 0
        today_snap = None
        if include_load_context:
            total_workout_days = (
                session.query(Workout.workout_date)
                .filter(Workout.user_id == uid)
                .distinct()
                .count()
            )
            if total_workout_days >= 7:
                today_snap = session.query(TrainingLoadSnapshot).filter(
                    TrainingLoadSnapshot.user_id == uid,
                    TrainingLoadSnapshot.snapshot_date == today,
                ).first()

    workout_entries = [
        {
            "date": str(w.workout_date),
            "type": w.workout_type,
            "run_subtype": w.run_subtype,
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
            "strava_activity_url": w.strava_activity_url,  # issue #530: list/detail source parity
            "is_stryd_synced": w.stryd_activity_pk is not None,
            "has_strava": "strava" in (w.source or "") or w.strava_activity_pk is not None,
            "has_stryd": "stryd" in (w.source or "") or w.stryd_activity_pk is not None,
            "notes": w.remarks or "",
            "feeling": w.feeling,
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

    response: dict = {"weeks": weeks}
    if include_load_context:
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
        response["load_context"] = load_context

    return JSONResponse(response)


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
def create_personal_record(body: PersonalRecordIn, current_user: User = Depends(resolve_user)):
    uid = current_user.id
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
def patch_personal_record(record_id: str, body: PersonalRecordPatch, current_user: User = Depends(resolve_user)):
    try:
        rid = _uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid record_id")
    with Session(engine) as session:
        pr = session.get(PersonalRecord, rid)
        if pr is None or pr.user_id != current_user.id:
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
        pr.updated_at = func.now()
        session.commit()
        session.refresh(pr)
        return JSONResponse(_pr_dict(pr))


@app.delete("/api/personal-records/{record_id}", status_code=204)
def delete_personal_record(record_id: str, current_user: User = Depends(resolve_user)):
    try:
        rid = _uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid record_id")
    with Session(engine) as session:
        pr = session.get(PersonalRecord, rid)
        if pr is None or pr.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Personal record not found")
        session.delete(pr)
        session.commit()
    return Response(status_code=204)


# ── Personal Records — Tracks / History / Bulk (issue #359) ──────────────────

@app.get("/api/personal-records/tracks")
def list_personal_record_tracks(current_user: User = Depends(resolve_user)):
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
def personal_record_history(track_key: str, current_user: User = Depends(resolve_user)):
    uid = current_user.id
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
def bulk_create_personal_records(body: _BulkInsertIn, current_user: User = Depends(resolve_user)):
    uid = current_user.id
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
<head><meta charset="utf-8"><title>Strava connected</title></head>
<body>
<script>
window.location.replace('/settings?strava=connected#integrations');
</script>
<p>Strava connected — <a href="/settings?strava=connected#integrations">return to Settings</a>.</p>
</body>
</html>"""

_STRAVA_CALLBACK_ERROR_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Strava connection failed</title></head>
<body>
<script>
window.location.replace('/settings?strava=error#integrations');
</script>
<p>Connection failed — <a href="/settings?strava=error#integrations">return to Settings</a>.</p>
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
        return Response(content=_STRAVA_CALLBACK_ERROR_HTML, media_type="text/html", status_code=400)

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
    athlete_id: str | None,
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
    # Stryd athlete id is a UUID string (not numeric) — store as-is, no int cast.
    athlete_id = resp.get("id") or resp.get("athlete_id") or None
    athlete_id = str(athlete_id) if athlete_id is not None else None
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
    _null_response = {
        "connected": False,
        "athlete_name": None,
        "athlete_id": None,
        "profile": None,
        "scope": None,
        "expires_at": None,
    }
    user_id = str(user.id)

    with Session(engine) as session:
        token_row = session.query(StravaToken).filter(StravaToken.user_id == user_id).first()
        if token_row is None:
            return JSONResponse(_null_response)
        scope = token_row.scope
        expires_at = token_row.expires_at
        athlete_data = token_row.athlete_data or {}
        athlete_id = token_row.athlete_id

    athlete_name = None
    first = athlete_data.get("firstname") or ""
    last = athlete_data.get("lastname") or ""
    full = (first + " " + last).strip()
    if full:
        athlete_name = full
    # Strava athlete profile avatar (medium); used for the debug/identity row.
    profile = athlete_data.get("profile_medium") or athlete_data.get("profile") or None

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
        "athlete_id": athlete_id,
        "profile": profile,
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


# Caps concurrent background syncs — prevents a burst of requests from spawning
# unlimited threads and exhausting memory.
_sync_pool = _ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync")


class _InMemoryRecorder:
    """Adapter satisfying sync_runner.SyncRecorder by delegating to the
    module-level functions in backend.services.sync_jobs."""

    set_phase = staticmethod(_sync_jobs.set_phase)
    increment = staticmethod(_sync_jobs.increment)
    mark_success = staticmethod(_sync_jobs.mark_success)
    mark_error = staticmethod(_sync_jobs.mark_error)


_sync_recorder = _InMemoryRecorder()


def _default_strava_since_date(user_id: _uuid.UUID) -> str:
    """Return YYYY-MM-DD lower bound for incremental Strava pulls."""
    return _sync_runner.default_strava_since_date(user_id)


def _run_plan_matcher(uid) -> None:
    """Post-sync pass: match planned_sessions against the freshly reconciled
    workouts. Runs after reconcile_workouts, before mark_success. Failures never
    fail the sync — the on-demand /api/planned-sessions/reconcile is the backstop.
    """
    _sync_runner.run_plan_matcher(uid)


def _strava_sync_worker(user_id: str, since_date: Optional[str] = None, *, full: bool = False) -> None:
    """Background daemon thread: pull Strava activities (optionally since since_date) and upsert."""
    _sync_runner.run_strava_sync(user_id, since_date, full=full, recorder=_sync_recorder)


class _StravaSyncBody(BaseModel):
    since_date: Optional[str] = None
    full: bool = False


@app.post("/api/strava/sync")
def strava_sync(body: _StravaSyncBody = Body(default=None), user: User = Depends(resolve_user)):
    """Start an async Strava pull; returns 202 immediately.

    Default (incremental): since last synced activity minus 1 day, or 90-day
    lookback on first sync. Pass full=true to fetch entire Strava history.
    Optional since_date (YYYY-MM-DD) overrides the incremental window.

    full=true: delegated to the compute worker (/internal/sync/run).
    Returns 503 if the worker is unreachable and ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS
    is not set to "1".
    """
    uid = user.id
    since = None
    full = False
    if body is not None:
        since = body.since_date
        full = body.full

    if full:
        try:
            result = _worker_client.delegate_sync(str(uid), sources=["strava"], full=True)
            return JSONResponse({"started": True, "worker_delegated": True, **result}, status_code=202)
        except _worker_client.WorkerUnavailable as exc:
            if os.getenv("ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS", "0") != "1":
                raise HTTPException(
                    status_code=503,
                    detail=f"Compute worker unavailable — cannot run full sync: {exc}",
                )
            _logging.getLogger(__name__).warning(
                "Worker unavailable for full Strava sync (user %s); falling back to in-process: %s",
                uid, exc,
            )

    try:
        _sync_jobs.start(uid, "strava")
    except _sync_jobs.SyncInProgress:
        raise HTTPException(status_code=409, detail="Sync already in progress")

    _sync_pool.submit(_strava_sync_worker, str(uid), since, full=full)
    return JSONResponse({"started": True}, status_code=202)


def _stryd_sync_worker(user_id: str, since_date: Optional[str] = None, *, full: bool = False) -> None:
    """Background daemon thread: pull Stryd activities, upsert, then reconcile."""
    _sync_runner.run_stryd_sync(user_id, since_date, full=full, recorder=_sync_recorder)


class _StrydSyncBody(BaseModel):
    since_date: Optional[str] = None
    full: bool = False


@app.post("/api/stryd/sync")
def stryd_sync(body: _StrydSyncBody = Body(default=None), user: User = Depends(resolve_user)):
    """Start an async Stryd pull; returns 202 immediately.

    Default (incremental): since last completed sync minus 1 day, or 90-day
    lookback on first sync. Pass full=true for a multi-year history pull.
    Optional since_date (YYYY-MM-DD) overrides the incremental window.

    full=true: delegated to the compute worker (/internal/sync/run).
    Returns 503 if the worker is unreachable and ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS
    is not set to "1".
    """
    uid = user.id
    with Session(engine) as session:
        cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == uid).one_or_none()
    if cred is None:
        raise HTTPException(status_code=422, detail="Connect Stryd first")
    since = None
    full = False
    if body is not None:
        since = body.since_date
        full = body.full

    if full:
        try:
            result = _worker_client.delegate_sync(str(uid), sources=["stryd"], full=True)
            return JSONResponse({"started": True, "worker_delegated": True, **result}, status_code=202)
        except _worker_client.WorkerUnavailable as exc:
            if os.getenv("ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS", "0") != "1":
                raise HTTPException(
                    status_code=503,
                    detail=f"Compute worker unavailable — cannot run full sync: {exc}",
                )
            _logging.getLogger(__name__).warning(
                "Worker unavailable for full Stryd sync (user %s); falling back to in-process: %s",
                uid, exc,
            )

    try:
        _sync_jobs.start(uid, "stryd")
    except _sync_jobs.SyncInProgress:
        raise HTTPException(status_code=409, detail="Sync already in progress")
    _sync_pool.submit(_stryd_sync_worker, str(uid), since, full=full)
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
    """Legacy Strava sync endpoint (BackgroundTasks path).

    Disabled by default (returns 410 Gone). Enable by setting
    LEGACY_SYNC_STRAVA_ENABLED=1. Use POST /api/strava/sync instead.
    """
    if os.getenv("LEGACY_SYNC_STRAVA_ENABLED", "0") != "1":
        raise HTTPException(
            status_code=410,
            detail="This endpoint is disabled. Use POST /api/strava/sync instead.",
        )

    from backend.services.strava_sync import sync_strava_activities as _strava_bg_sync
    from sqlalchemy import select

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
def strava_reconcile(current_user: User = Depends(resolve_user)):
    """Reconcile unlinked strava_activities into workouts. Returns counts."""
    result = _workout_reconcile.reconcile_strava_to_workouts(current_user.id)
    return JSONResponse(result)


@app.get("/api/sync/strava/dry-run")
def strava_sync_dry_run(
    since_date: Optional[str] = Query(None),
    limit: int = Query(20),
    current_user: User = Depends(resolve_user),
):
    """Read-only preview of what a Strava reconcile would produce. No DB writes."""
    user_id = current_user.id
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
    if job is None or job.user_id != user.id:
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
def strava_data_quality(current_user: User = Depends(resolve_user)):
    """Return data quality counts for a user's Strava/workout sync state."""
    uid = current_user.id
    with Session(engine) as session:
        from sqlalchemy import text as _text
        strava_count = session.execute(
            select(func.count(StravaActivity.id)).where(StravaActivity.user_id == uid)
        ).scalar() or 0

        w_strava_count = session.execute(
            select(func.count(Workout.id))
            .where(Workout.user_id == uid)
            .where(Workout.source.in_(["strava", "both", "strava,stryd", "stryd,strava"]))
        ).scalar() or 0

        w_no_source_count = session.execute(
            select(func.count(Workout.id))
            .where(Workout.user_id == uid)
            .where((Workout.source.is_(None)) | (Workout.source == ""))
        ).scalar() or 0

        stryd_synced_count = session.execute(
            select(func.count(Workout.id))
            .where(Workout.user_id == uid)
            .where(Workout.stryd_activity_pk.isnot(None))
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


@app.get("/api/sync/stryd/latest")
def stryd_sync_latest(
    user: User = Depends(resolve_user),
    user_id: Optional[_uuid.UUID] = Query(None),
):
    """Most recent Stryd sync. With user_id: full latest SyncJob (any status);
    without: completed-only summary for the session user."""
    from sqlalchemy import select
    target = user_id if user_id is not None else user.id
    with Session(engine) as session:
        if user_id is not None:
            job = session.execute(
                select(SyncJob).where(SyncJob.user_id == target)
                .where(SyncJob.source == "stryd")
                .order_by(SyncJob.created_at.desc()).limit(1)
            ).scalar_one_or_none()
            if job is None:
                raise HTTPException(status_code=404, detail="No sync jobs found for this user")
            return JSONResponse({
                "id": str(job.id), "status": job.status, "job_type": job.job_type,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "activities_fetched": job.activities_fetched,
                "activities_created": job.activities_created,
                "activities_updated": job.activities_updated,
                "error_message": job.error_message,
            })
        job = session.execute(
            select(SyncJob).where(SyncJob.user_id == target)
            .where(SyncJob.source == "stryd").where(SyncJob.status == "completed")
            .order_by(SyncJob.completed_at.desc()).limit(1)
        ).scalar_one_or_none()
    if job is None:
        return JSONResponse({"synced_at": None, "activities_synced": 0, "new_workouts": 0})
    return JSONResponse({
        "synced_at": job.completed_at.isoformat() if job.completed_at else None,
        "activities_synced": (job.activities_created or 0) + (job.activities_updated or 0),
        "new_workouts": job.activities_created or 0,
    })


@app.get("/api/sync/stryd/data-quality")
def stryd_data_quality(current_user: User = Depends(resolve_user)):
    """Data-quality counts for a user's Stryd/workout sync state."""
    uid = current_user.id
    with Session(engine) as session:
        stryd_count = session.execute(
            select(func.count(StrydActivity.id)).where(StrydActivity.user_id == uid)
        ).scalar() or 0
        w_stryd_count = session.execute(
            select(func.count(Workout.id)).where(Workout.user_id == uid)
            .where(Workout.stryd_activity_pk.isnot(None))
        ).scalar() or 0
        w_strava_synced = session.execute(
            select(func.count(Workout.id)).where(Workout.user_id == uid)
            .where(Workout.strava_activity_pk.isnot(None))
        ).scalar() or 0
        w_both = session.execute(
            select(func.count(Workout.id)).where(Workout.user_id == uid)
            .where(Workout.stryd_activity_pk.isnot(None))
            .where(Workout.strava_activity_pk.isnot(None))
        ).scalar() or 0
        w_tss = session.execute(
            select(func.count(Workout.id)).where(Workout.user_id == uid)
            .where(Workout.tss.isnot(None))
        ).scalar() or 0
    return JSONResponse({
        "stryd_activities_count": int(stryd_count),
        "workouts_with_stryd_source_count": int(w_stryd_count),
        "workouts_with_strava_source_count": int(w_strava_synced),
        "workouts_with_both_count": int(w_both),
        "workouts_with_tss_count": int(w_tss),
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

    # Check before upsert so we know whether this is the very first connect.
    is_first_connect = _get_google_creds_for_user(user_id) is None

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

    if is_first_connect:
        _trigger_drive_sleep_backfill_background(user_id)

    return Response(content=_GOOGLE_CALLBACK_HTML, media_type="text/html")


def _get_google_creds_for_user(user_id) -> Optional[GoogleOAuthCredentials]:
    """Return the GoogleOAuthCredentials row for user_id, or None if not connected."""
    with Session(engine) as session:
        return (
            session.query(GoogleOAuthCredentials)
            .filter(GoogleOAuthCredentials.user_id == user_id)
            .one_or_none()
        )


def _trigger_drive_sleep_backfill_background(user_id: str) -> None:
    """Fire-and-forget: run the Drive sleep backfill in a daemon thread.

    Called once after first Google connect so all pre-existing sleep files
    are imported without blocking the callback response.  Errors are logged.
    """
    _bg_log = _logging.getLogger(__name__)

    def _run():
        try:
            from backend.services import drive_sleep_sync as _dss
            _dss.backfill_drive_sleep_for_user(user_id)
        except Exception as _exc:
            _bg_log.warning(
                "drive_sleep_sync backfill failed for user %s: %s",
                user_id, _exc, exc_info=True,
            )

    t = _threading.Thread(target=_run, daemon=True)
    t.start()


# ── Drive sleep sync ──────────────────────────────────────────────────────────

@app.post("/api/integrations/drive-sleep/sync")
def post_drive_sleep_sync(user: User = Depends(resolve_user)):
    """Trigger an immediate Drive/Health Sync sleep file import for the authenticated user.

    Returns 200 JSON with flat keys: files_seen, rows_imported, rows_updated, rows_skipped.
    Returns 422 if the user has no connected Google Drive / Health Sync integration.
    """
    from backend.services import drive_sleep_sync as _dss

    creds = _get_google_creds_for_user(user.id)
    if creds is None:
        raise HTTPException(
            status_code=422,
            detail="No Google Drive / Health Sync integration connected. Connect Google first.",
        )

    result = _dss.sync_drive_sleep_for_user(str(user.id))
    return JSONResponse({
        "files_seen": result["files_seen"],
        "rows_imported": result["rows_imported"],
        "rows_updated": result["rows_updated"],
        "rows_skipped": result["rows_skipped"],
    })


# ── Google Drive Sleep Connection ─────────────────────────────────────────────

_DRIVE_SLEEP_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

_DRIVE_SLEEP_CALLBACK_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Google Drive connected</title></head>
<body>
<script>
window.location.replace('/settings?drive_sleep=connected#integrations');
</script>
<p>Google Drive connected — <a href="/settings?drive_sleep=connected#integrations">return to Settings</a>.</p>
</body>
</html>"""

_DRIVE_SLEEP_CALLBACK_ERROR_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Google Drive connection failed</title></head>
<body>
<script>
window.location.replace('/settings?drive_sleep=error#integrations');
</script>
<p>Connection failed — <a href="/settings?drive_sleep=error#integrations">return to Settings</a>.</p>
</body>
</html>"""


def _upsert_drive_sleep_connection(
    *,
    user_id: str,
    refresh_token_encrypted: Optional[str] = None,
    status: str,
    folder_id: Optional[str] = None,
) -> None:
    now = _datetime.now(tz=_timezone.utc)
    with Session(engine) as session:
        row = session.query(DriveSleepConnection).filter(
            DriveSleepConnection.user_id == user_id
        ).first()
        if row is None:
            row = DriveSleepConnection(
                user_id=user_id,
                status=status,
                refresh_token_encrypted=refresh_token_encrypted,
                folder_id=folder_id,
                updated_at=now,
            )
            session.add(row)
        else:
            row.status = status
            row.updated_at = now
            if refresh_token_encrypted is not None:
                row.refresh_token_encrypted = refresh_token_encrypted
            if folder_id is not None:
                row.folder_id = folder_id
        session.commit()


@app.get("/api/drive-sleep/connect")
def drive_sleep_connect(user: User = Depends(resolve_user)):
    """Initiate Google OAuth for read-only Drive access (sleep CSV folder)."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID is not configured")

    if not os.getenv("GOOGLE_CLIENT_SECRET"):
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_SECRET is not configured")

    state_secret = os.getenv("GOOGLE_STATE_SECRET")
    if not state_secret:
        raise HTTPException(status_code=500, detail="GOOGLE_STATE_SECRET is not configured")

    redirect_uri = os.getenv(
        "GOOGLE_DRIVE_REDIRECT_URI",
        "http://localhost:9001/api/drive-sleep/callback",
    )
    user_id = str(user.id)
    state = _make_google_state_token(user_id, state_secret)
    authorize_url = _GOOGLE_AUTH_URL + "?" + _urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _DRIVE_SLEEP_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return JSONResponse({"authorize_url": authorize_url})


@app.get("/api/drive-sleep/callback")
def drive_sleep_callback(
    state: str = Query(...),
    code: str = Query(default=""),
    error: str = Query(default=""),
):
    """Handle Google OAuth callback for Drive sleep connection."""
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

    if error:
        _logging.getLogger(__name__).error(
            "Drive sleep OAuth error for user %s: %s", user_id, error
        )
        _upsert_drive_sleep_connection(user_id=user_id, status="error")
        return Response(content=_DRIVE_SLEEP_CALLBACK_ERROR_HTML, media_type="text/html")

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv(
        "GOOGLE_DRIVE_REDIRECT_URI",
        "http://localhost:9001/api/drive-sleep/callback",
    )

    token_resp = _exchange_google_code(code, client_id, client_secret, redirect_uri)
    refresh_token = token_resp.get("refresh_token")

    if not refresh_token:
        _logging.getLogger(__name__).error(
            "Drive sleep OAuth: no refresh_token returned for user %s", user_id
        )
        _upsert_drive_sleep_connection(user_id=user_id, status="error")
        return Response(content=_DRIVE_SLEEP_CALLBACK_ERROR_HTML, media_type="text/html")

    refresh_token_encrypted = _encrypt_value(refresh_token)
    _upsert_drive_sleep_connection(
        user_id=user_id,
        refresh_token_encrypted=refresh_token_encrypted,
        status="connected",
    )
    return Response(content=_DRIVE_SLEEP_CALLBACK_HTML, media_type="text/html")


@app.get("/api/drive-sleep/status")
def drive_sleep_status(user: User = Depends(resolve_user)):
    """Return Drive sleep connection status — never exposes the refresh token."""
    _null = {"status": "not_connected", "folder_id": None, "last_sync_at": None}
    user_id = str(user.id)
    with Session(engine) as session:
        row = session.query(DriveSleepConnection).filter(
            DriveSleepConnection.user_id == user_id
        ).first()
        if row is None:
            return JSONResponse(_null)
        return JSONResponse({
            "status": row.status,
            "folder_id": row.folder_id,
            "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        })


class _DriveSleepFolderBody(BaseModel):
    folder_id: str


@app.post("/api/drive-sleep/folder")
def drive_sleep_set_folder(
    body: _DriveSleepFolderBody,
    user: User = Depends(resolve_user),
):
    """Persist the folder ID for the Drive sleep connection."""
    user_id = str(user.id)
    now = _datetime.now(tz=_timezone.utc)
    with Session(engine) as session:
        row = session.query(DriveSleepConnection).filter(
            DriveSleepConnection.user_id == user_id
        ).first()
        if row is None or row.status == "not_connected":
            raise HTTPException(
                status_code=400,
                detail="Not connected to Google Drive — connect first",
            )
        row.folder_id = body.folder_id
        row.updated_at = now
        session.commit()
        return JSONResponse({"status": row.status, "folder_id": row.folder_id})


@app.delete("/api/drive-sleep/disconnect")
def drive_sleep_disconnect(user: User = Depends(resolve_user)):
    """Clear the Drive sleep connection: wipe encrypted token, set status to not_connected."""
    user_id = str(user.id)
    now = _datetime.now(tz=_timezone.utc)
    with Session(engine) as session:
        row = session.query(DriveSleepConnection).filter(
            DriveSleepConnection.user_id == user_id
        ).first()
        if row is not None:
            row.refresh_token_encrypted = None
            row.status = "not_connected"
            row.updated_at = now
            session.commit()
    return JSONResponse({"disconnected": True})


# ── Imports ───────────────────────────────────────────────────────────────────

class _SleepImportBody(BaseModel):
    user_id: str
    import_date: str
    source: str
    data: dict


@app.post("/api/imports/sleep")
def post_sleep_import(body: _SleepImportBody, current_user: User = Depends(resolve_user)):
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

    parsed_user_id = current_user.id

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
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: User = Depends(resolve_user),
):
    parsed_user_id = current_user.id

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
    as_of: Optional[str] = Query(default=None),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

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
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

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


@app.get("/api/training-load/weekly")
def get_training_load_weekly(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    current_user: User = Depends(resolve_user),
):
    """Return weekly TSS/distance aggregates for the volume chart.

    Each week bucket contains only run_tss, strength_tss, total_tss, and
    total_distance_km — no per-workout serialization.  Week boundaries are
    Monday-to-Sunday (ISO week semantics).
    """
    import re as _re

    uid = current_user.id
    today = _date.today()

    try:
        from_d = _date.fromisoformat(from_date) if from_date else today - _timedelta(days=90)
        to_d = _date.fromisoformat(to_date) if to_date else today
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format; use YYYY-MM-DD")

    if from_d > to_d:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")

    if (to_d - from_d).days > 365:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 365 days")

    _RUN_RE = _re.compile(r"^run(ning)?$|^race$|^(bike|ride|cycl)", _re.IGNORECASE)
    _LIFT_RE = _re.compile(r"^(lift|strength|wod|crossfit)", _re.IGNORECASE)

    with Session(engine) as session:
        # SQL-side GROUP BY (week_monday, workout_type) so we aggregate TSS and
        # distance in the database rather than loading every Workout row.
        week_monday = func.date_trunc(
            "week", _sa_cast(Workout.workout_date, _sa_DateTime),
        )
        rows = (
            session.query(
                week_monday.label("week_mon"),
                Workout.workout_type,
                func.coalesce(func.sum(Workout.tss), 0).label("sum_tss"),
                func.coalesce(func.sum(Workout.distance_km), 0).label("sum_dist"),
            )
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
            )
            .group_by(week_monday, Workout.workout_type)
            .all()
        )

    weeks_map: dict = {}
    for row in rows:
        # date_trunc returns a datetime; convert to ISO date string (Monday)
        wm = row.week_mon
        if hasattr(wm, "date"):
            mon_key = wm.date().isoformat()
        else:
            mon_key = str(wm)[:10]
        if mon_key not in weeks_map:
            weeks_map[mon_key] = {"run_tss": 0.0, "strength_tss": 0.0, "total_distance_km": 0.0}
        tss = float(row.sum_tss or 0)
        dist = float(row.sum_dist or 0)
        wt = (row.workout_type or "").strip()
        if _RUN_RE.match(wt):
            weeks_map[mon_key]["run_tss"] += tss
        elif _LIFT_RE.match(wt):
            weeks_map[mon_key]["strength_tss"] += tss
        elif dist > 0:
            weeks_map[mon_key]["run_tss"] += tss
        else:
            weeks_map[mon_key]["strength_tss"] += tss
        weeks_map[mon_key]["total_distance_km"] += dist

    weeks = []
    for mon_key in sorted(weeks_map):
        agg = weeks_map[mon_key]
        run_tss = round(agg["run_tss"], 2)
        strength_tss = round(agg["strength_tss"], 2)
        weeks.append({
            "week_start": mon_key,
            "run_tss": run_tss,
            "strength_tss": strength_tss,
            "total_tss": round(run_tss + strength_tss, 2),
            "total_distance_km": round(agg["total_distance_km"], 2),
        })

    return JSONResponse({"weeks": weeks})


@app.post("/api/training-load/recompute")
def recompute_training_load(
    from_date: str = Query(alias="from"),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

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
    target_date: Optional[str] = Query(default=None, alias="date"),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

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
    from_date: str = Query(alias="from"),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

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


# ── Daily load series ─────────────────────────────────────────────────────────

@app.get("/api/training/daily-load")
def get_training_daily_load(
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    current_user: User = Depends(resolve_user),
):
    uid = current_user.id

    if start is None or end is None:
        missing = []
        if start is None:
            missing.append("start")
        if end is None:
            missing.append("end")
        reason = f"Missing required query parameter(s): {', '.join(missing)}"
        return JSONResponse(status_code=400, content={"results": [], "reason": reason})

    try:
        start_d = _date.fromisoformat(start)
    except ValueError:
        return JSONResponse(status_code=400, content={"results": [], "reason": f"start is not a valid ISO-8601 date: {start!r}"})

    try:
        end_d = _date.fromisoformat(end)
    except ValueError:
        return JSONResponse(status_code=400, content={"results": [], "reason": f"end is not a valid ISO-8601 date: {end!r}"})

    if start_d > end_d:
        reason = f"start ({start}) must not be after end ({end})"
        return JSONResponse(status_code=400, content={"results": [], "reason": reason})

    with Session(engine) as session:
        rows = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= start_d,
                Workout.workout_date <= end_d,
            )
            .order_by(Workout.workout_date)
            .all()
        )
        workouts = [
            {
                "id": str(r.id),
                "date": r.workout_date.isoformat(),
                "tss": float(r.tss) if r.tss is not None else None,
            }
            for r in rows
        ]

    result = _daily_load_series(workouts, start, end)
    return JSONResponse(result)


@app.get("/api/athletes/{athlete_id}/daily-load")
def get_athlete_daily_load(
    athlete_id: str,
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    current_user: User = Depends(resolve_user),
):
    """Return per-day training load aggregates for an athlete.

    Validates date params first (400 on failure), then checks athlete
    exists (404 if not), then delegates computation to daily_load_series.
    """
    try:
        if _uuid.UUID(athlete_id) != current_user.id:
            raise HTTPException(status_code=404, detail="Athlete not found")
    except ValueError:
        raise HTTPException(status_code=404, detail="Athlete not found")
    if start_date is None or end_date is None:
        missing = []
        if start_date is None:
            missing.append("start_date")
        if end_date is None:
            missing.append("end_date")
        raise HTTPException(
            status_code=400,
            detail=f"Missing required query parameter(s): {', '.join(missing)}",
        )

    try:
        start_d = _date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"start_date is not a valid ISO-8601 date: {start_date!r}",
        )

    try:
        end_d = _date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"end_date is not a valid ISO-8601 date: {end_date!r}",
        )

    if start_d > end_d:
        raise HTTPException(
            status_code=400,
            detail=f"start_date ({start_date}) must not be after end_date ({end_date})",
        )

    uid = current_user.id

    with Session(engine) as session:
        athlete = session.get(User, uid)
        if athlete is None:
            raise HTTPException(status_code=404, detail="Athlete not found")

        rows = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= start_d,
                Workout.workout_date <= end_d,
            )
            .order_by(Workout.workout_date)
            .all()
        )
        workouts = [
            {
                "id": str(r.id),
                "date": r.workout_date.isoformat(),
                "tss": float(r.tss) if r.tss is not None else None,
            }
            for r in rows
        ]

    result = _daily_load_series(workouts, start_date, end_date)
    return JSONResponse(result)


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
    with Session(engine) as session:
        strava_sub = select(StravaToken.user_id).subquery()
        google_sub = select(GoogleOAuthCredentials.user_id).subquery()
        stryd_sub = select(StrydCredentials.user_id).subquery()
        wc_sub = (
            select(Workout.user_id.label("user_id"), func.count().label("wc"))
            .group_by(Workout.user_id)
            .subquery()
        )

        rows = (
            session.query(
                User,
                strava_sub.c.user_id.isnot(None).label("has_strava"),
                google_sub.c.user_id.isnot(None).label("has_google"),
                stryd_sub.c.user_id.isnot(None).label("has_stryd"),
                func.coalesce(wc_sub.c.wc, 0).label("workout_count"),
            )
            .outerjoin(strava_sub, User.id == strava_sub.c.user_id)
            .outerjoin(google_sub, User.id == google_sub.c.user_id)
            .outerjoin(stryd_sub, User.id == stryd_sub.c.user_id)
            .outerjoin(wc_sub, User.id == wc_sub.c.user_id)
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
                "last_login_at": u.last_login_at.isoformat() if getattr(u, "last_login_at", None) else None,
                "workout_count": int(workout_count or 0),
            }
            for u, has_strava, has_google, has_stryd, workout_count in rows
        ])


@app.get("/api/admin/users/{user_id}/recent-activities", dependencies=[Depends(require_admin)])
def admin_user_recent_activities(user_id: str):
    """Last 3 workouts for a user (admin user-detail modal): when + what."""
    try:
        uid = _uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid user id")
    with Session(engine) as session:
        workouts = (
            session.query(Workout)
            .filter(Workout.user_id == uid)
            .order_by(Workout.workout_date.desc(), Workout.start_time.desc().nullslast())
            .limit(3)
            .all()
        )
        return JSONResponse([
            {
                "id": str(w.id),
                "date": w.workout_date.isoformat() if w.workout_date else None,
                "name": w.name,
                "type": w.workout_type,
                "run_subtype": w.run_subtype,
                "distance_km": float(w.distance_km) if w.distance_km is not None else None,
                "duration_seconds": int(w.duration_seconds) if w.duration_seconds is not None else None,
            }
            for w in workouts
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


class AdminCopyUserIn(BaseModel):
    identifier: str  # PRD user name or UUID
    overwrite: bool = False


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


# ── Admin: DB backup + user copy ────────────────────────────────────────────────

@app.get("/api/admin/db/backup", dependencies=[Depends(require_admin)])
def admin_db_backup():
    """Stream a pg_dump (custom format) of the current environment's database.

    Restore is intentionally NOT exposed here — use scripts/db_restore.py.
    """
    import tempfile
    from backend.db import database_url, environment
    from backend.services.db_backup import BackupError, default_backup_name, make_backup
    from starlette.background import BackgroundTask

    if not database_url:
        raise HTTPException(status_code=500, detail="No database_url configured")

    filename = default_backup_name(environment)
    tmp = tempfile.NamedTemporaryFile(prefix="pcbackup-", suffix=".dump", delete=False)
    tmp.close()
    try:
        make_backup(database_url, tmp.name)
    except BackupError as exc:
        os.remove(tmp.name)
        raise HTTPException(status_code=500, detail=str(exc))

    return FileResponse(
        tmp.name,
        media_type="application/octet-stream",
        filename=filename,
        background=BackgroundTask(os.remove, tmp.name),
    )


@app.get("/api/admin/prd-users", dependencies=[Depends(require_admin)])
def admin_list_prd_users():
    """List users in the PRD database, for the copy-to-UAT picker."""
    from backend.services.user_copy import UserCopyError, list_prd_users

    try:
        users = list_prd_users()
    except UserCopyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(
        {
            "users": [
                {
                    "id": str(u["id"]),
                    "name": u["name"],
                    "is_active": bool(u["is_active"]),
                    "is_admin": bool(u["is_admin"]),
                }
                for u in users
            ]
        }
    )


@app.post("/api/admin/users/copy-to-uat", dependencies=[Depends(require_admin)])
def admin_copy_user_to_uat(body: AdminCopyUserIn):
    """Copy one PRD user's full data graph into UAT. Direction is hard-locked."""
    from backend.services.user_copy import UserCopyError, copy_user_to_uat

    try:
        result = copy_user_to_uat(body.identifier, overwrite=bool(body.overwrite))
    except UserCopyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(result)


# ── Sync status endpoint ───────────────────────────────────────────────────────

@app.get("/api/sync/status")
async def get_sync_status(user: User = Depends(resolve_user)):
    job = _sync_jobs.snapshot(user.id)
    if job is not None:
        serialized = {
            **job,
            "started_at": job["started_at"].isoformat() if job["started_at"] else None,
            "finished_at": job["finished_at"].isoformat() if job["finished_at"] else None,
        }
        return JSONResponse(serialized)

    # No in-process job — check worker_job_runs for a delegated job.
    from backend.models import WorkerJobRun as _WorkerJobRun
    from sqlalchemy import select as _sel, or_ as _or
    from datetime import datetime, timezone as _tz, timedelta as _td
    _cutoff = datetime.now(_tz.utc) - _td(minutes=10)
    try:
        with Session(engine) as _db:
            wjr = _db.execute(
                _sel(_WorkerJobRun)
                .where(_WorkerJobRun.user_id == user.id)
                .where(
                    _or(
                        _WorkerJobRun.status == "running",
                        _WorkerJobRun.started_at >= _cutoff,
                    )
                )
                .order_by(_WorkerJobRun.started_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        if wjr is not None:
            return JSONResponse({
                "status": wjr.status,
                "phase": wjr.phase,
                "source": "worker",
                "job_type": wjr.job_type,
                "items_synced": wjr.items_synced,
                "error": wjr.error,
                "started_at": wjr.started_at.isoformat() if wjr.started_at else None,
                "finished_at": wjr.finished_at.isoformat() if wjr.finished_at else None,
            })
    except Exception:
        pass

    return JSONResponse({"status": "idle"})


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
    "max_hr": 190,
    "zone2_hr_min": 130,
    "zone2_hr_max": 155,
    "weekly_zone2_target_min": 150,
}

_PREFS_EDITABLE = {"ftp_w", "threshold_hr", "threshold_pace_seconds_per_km", "display_name", "week_start_day", "timezone"}
_PREFS_NON_EDITABLE = {"preferred_units", "date_format"}


def _prefs_row_dict(prefs: UserPreferences) -> dict:
    def _isoformat(dt):
        return dt.isoformat() if dt is not None else None

    return {
        "user_id": str(prefs.user_id),
        "ftp_w": prefs.ftp_w,
        "ftp_w_updated_at": _isoformat(getattr(prefs, "ftp_w_updated_at", None)),
        "threshold_hr": prefs.threshold_hr,
        "threshold_hr_updated_at": _isoformat(getattr(prefs, "threshold_hr_updated_at", None)),
        "threshold_pace_seconds_per_km": prefs.threshold_pace_seconds_per_km,
        "threshold_pace_seconds_per_km_updated_at": _isoformat(
            getattr(prefs, "threshold_pace_seconds_per_km_updated_at", None)
        ),
        "max_hr": prefs.max_hr,
        "zone2_hr_min": prefs.zone2_hr_min,
        "zone2_hr_min_updated_at": _isoformat(getattr(prefs, "zone2_hr_min_updated_at", None)),
        "zone2_hr_max": prefs.zone2_hr_max,
        "zone2_hr_max_updated_at": _isoformat(getattr(prefs, "zone2_hr_max_updated_at", None)),
        "weekly_zone2_target_min": prefs.weekly_zone2_target_min,
        "display_name": prefs.display_name,
        "week_start_day": prefs.week_start_day,
        "timezone": prefs.timezone,
        "ctl_days": prefs.ctl_days,
        "atl_days": prefs.atl_days,
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
        row["user_id"] = str(db_user.id)
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
    max_hr = body.get("max_hr", _PREFS_SENTINEL)
    zone2_hr_min = body.get("zone2_hr_min", _PREFS_SENTINEL)
    zone2_hr_max = body.get("zone2_hr_max", _PREFS_SENTINEL)
    weekly_zone2_target = body.get("weekly_zone2_target_min", _PREFS_SENTINEL)
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
    if max_hr is not _PREFS_SENTINEL and max_hr is not None:
        if not isinstance(max_hr, int) or not (120 <= max_hr <= 230):
            errors.append({"field": "max_hr", "msg": "max_hr must be between 120 and 230"})
    if zone2_hr_min is not _PREFS_SENTINEL and zone2_hr_min is not None:
        if not isinstance(zone2_hr_min, int) or not (80 <= zone2_hr_min <= 200):
            errors.append({"field": "zone2_hr_min", "msg": "zone2_hr_min must be between 80 and 200"})
    if zone2_hr_max is not _PREFS_SENTINEL and zone2_hr_max is not None:
        if not isinstance(zone2_hr_max, int) or not (80 <= zone2_hr_max <= 210):
            errors.append({"field": "zone2_hr_max", "msg": "zone2_hr_max must be between 80 and 210"})
    if weekly_zone2_target is not _PREFS_SENTINEL and weekly_zone2_target is not None:
        if not isinstance(weekly_zone2_target, int) or not (0 <= weekly_zone2_target <= 2000):
            errors.append({"field": "weekly_zone2_target_min", "msg": "weekly_zone2_target_min must be between 0 and 2000"})
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

        _now = _datetime.now(_timezone.utc)
        if ftp_w is not _PREFS_SENTINEL:
            prefs.ftp_w = ftp_w
            prefs.ftp_w_updated_at = _now
        if threshold_hr is not _PREFS_SENTINEL:
            prefs.threshold_hr = threshold_hr
            prefs.threshold_hr_updated_at = _now
        if threshold_pace is not _PREFS_SENTINEL:
            prefs.threshold_pace_seconds_per_km = threshold_pace
            prefs.threshold_pace_seconds_per_km_updated_at = _now
        if max_hr is not _PREFS_SENTINEL:
            prefs.max_hr = max_hr
        if zone2_hr_min is not _PREFS_SENTINEL:
            prefs.zone2_hr_min = zone2_hr_min
            prefs.zone2_hr_min_updated_at = _now
        if zone2_hr_max is not _PREFS_SENTINEL:
            prefs.zone2_hr_max = zone2_hr_max
            prefs.zone2_hr_max_updated_at = _now
        if weekly_zone2_target is not _PREFS_SENTINEL:
            prefs.weekly_zone2_target_min = weekly_zone2_target
        if display_name is not _PREFS_SENTINEL:
            prefs.display_name = display_name
        if week_start_day is not _PREFS_SENTINEL:
            prefs.week_start_day = week_start_day
        if timezone is not _PREFS_SENTINEL:
            prefs.timezone = timezone

        prefs.updated_at = _datetime.now(_timezone.utc)
        _threshold_fields_changed = any(
            f is not _PREFS_SENTINEL for f in (ftp_w, threshold_hr, threshold_pace)
        )
        session.commit()
        session.refresh(prefs)
        if _threshold_fields_changed:
            try:
                _recompute_user_running_tss(uid, session)
                session.commit()
            except Exception as _tss_exc:
                _logging.getLogger(__name__).warning(
                    "recompute_user_running_tss failed for user %s: %s", uid, _tss_exc, exc_info=True
                )
            # Run the full performance backfill (TSS + duration curve) in the
            # background so scores and the fitness chart reflect new thresholds
            # without blocking the HTTP response.  Idempotent; safe to re-run.
            _trigger_performance_backfill_background(uid)
        return JSONResponse(_prefs_row_dict(prefs))


# ── Races ─────────────────────────────────────────────────────────────────────

class _RaceCreateBody(BaseModel):
    # ``date`` is the canonical field name (issue #708); ``race_date`` is kept
    # for backward-compatibility with clients that were built against issue #605.
    date: Optional[str] = None
    race_date: Optional[str] = None
    distance_km: float
    goal_time_seconds: Optional[int] = None
    name: Optional[str] = None
    priority: Optional[Literal["A", "B", "C"]] = None
    status: Optional[Literal["planned", "done", "abandoned"]] = None
    race_type: Optional[str] = None


class _RaceUpdateBody(BaseModel):
    # Same dual-field convention as _RaceCreateBody.
    date: Optional[str] = None
    race_date: Optional[str] = None
    distance_km: Optional[float] = None
    goal_time_seconds: Optional[int] = None
    name: Optional[str] = None
    priority: Optional[Literal["A", "B", "C"]] = None
    status: Optional[Literal["planned", "done", "abandoned"]] = None
    race_type: Optional[str] = None


def _race_met_status(race: Race) -> str:
    """Derive met_status from race date and status for display in the Plan tab."""
    if race.status == "done":
        return "met"
    today = _date.today()
    if race.race_date < today:
        return "missed"
    return "upcoming"


def _race_dict(race: Race) -> dict:
    return {
        "id": str(race.id),
        "user_id": str(race.user_id),
        "name": race.name,
        "race_date": str(race.race_date),
        "distance_km": float(race.distance_km),
        "goal_time_seconds": race.goal_time_seconds,
        "goal_pace_seconds_per_km": race.goal_pace_seconds_per_km,
        "actual_time_seconds": race.actual_time_seconds,
        "half_marathon_equivalent_seconds": _riegel_half_equivalent(
            race.actual_time_seconds, float(race.distance_km)
        ),
        "priority": race.priority,
        "status": race.status,
        "race_type": race.race_type if race.race_type else "race",
        "met_status": _race_met_status(race),
        "created_at": race.created_at.isoformat() if race.created_at else None,
        "updated_at": race.updated_at.isoformat() if race.updated_at else None,
    }


def _validate_race_date(race_date_str: str) -> _date:
    """Validate race date string; raises 422 (legacy behaviour for race_date field)."""
    try:
        return _date.fromisoformat(race_date_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={"field": "race_date", "error": "race_date must be a valid YYYY-MM-DD date"},
        )


def _validate_race_date_400(date_str: str) -> _date:
    """Validate race date string; raises 400 (canonical behaviour for date field, issue #708)."""
    try:
        return _date.fromisoformat(date_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail={"field": "date", "error": "date must be a valid YYYY-MM-DD calendar date"},
        )


def _validate_distance_km(distance_km: float, status_code: int = 422) -> None:
    if distance_km <= 0:
        raise HTTPException(
            status_code=status_code,
            detail={"field": "distance_km", "error": "distance_km must be a positive number (> 0)"},
        )


@app.post("/api/races", status_code=201)
def create_race(body: _RaceCreateBody, user: User = Depends(resolve_user)):
    # ``date`` takes precedence; fall back to legacy ``race_date``.
    if body.date is not None:
        race_date = _validate_race_date_400(body.date)
        _validate_distance_km(body.distance_km, status_code=400)
    elif body.race_date is not None:
        race_date = _validate_race_date(body.race_date)
        _validate_distance_km(body.distance_km)
    else:
        raise HTTPException(status_code=400, detail={"field": "date", "error": "date is required"})

    pace = _derive_goal_pace(body.goal_time_seconds, body.distance_km)

    with Session(engine) as session:
        race_type_val = body.race_type if body.race_type in _RACE_TYPE_VALUES else "race"
        race_kwargs: dict = dict(
            user_id=user.id,
            name=body.name if body.name is not None else "",
            race_date=race_date,
            distance_km=body.distance_km,
            goal_time_seconds=body.goal_time_seconds,
            race_type=race_type_val,
        )
        if body.priority is not None:
            race_kwargs["priority"] = body.priority
        if body.status is not None:
            race_kwargs["status"] = body.status
        race = Race(**race_kwargs)
        race.goal_pace_seconds_per_km = pace
        session.add(race)
        session.commit()
        session.refresh(race)
        return JSONResponse(status_code=201, content=_race_dict(race))


@app.get("/api/races")
def list_races(user: User = Depends(resolve_user)):
    with Session(engine) as session:
        rows = (
            session.query(Race)
            .filter(Race.user_id == user.id)
            .order_by(Race.race_date)
            .all()
        )
        return JSONResponse([_race_dict(r) for r in rows])


@app.get("/api/athletes/{athlete_id}/races")
def list_athlete_races(athlete_id: str, user: User = Depends(resolve_user)):
    try:
        aid = _uuid.UUID(athlete_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid athlete_id")
    if aid != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    with Session(engine) as session:
        rows = (
            session.query(Race)
            .filter(Race.user_id == aid)
            .order_by(Race.race_date)
            .all()
        )
        return JSONResponse([_race_dict(r) for r in rows])


@app.get("/api/races/{race_id}")
def get_race(race_id: str, user: User = Depends(resolve_user)):
    try:
        rid = _uuid.UUID(race_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid race_id")
    with Session(engine) as session:
        race = session.get(Race, rid)
        if race is None or race.user_id != user.id:
            raise HTTPException(status_code=404, detail="race not found")
        return JSONResponse(_race_dict(race))


@app.put("/api/races/{race_id}")
def update_race(race_id: str, body: _RaceUpdateBody, user: User = Depends(resolve_user)):
    try:
        rid = _uuid.UUID(race_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid race_id")

    if body.race_date is not None:
        _validate_race_date(body.race_date)
    if body.distance_km is not None:
        _validate_distance_km(body.distance_km)

    with Session(engine) as session:
        race = session.get(Race, rid)
        if race is None or race.user_id != user.id:
            raise HTTPException(status_code=404, detail="race not found")

        if body.race_date is not None:
            race.race_date = _date.fromisoformat(body.race_date)
        if body.distance_km is not None:
            race.distance_km = body.distance_km
        if "goal_time_seconds" in body.model_fields_set:
            race.goal_time_seconds = body.goal_time_seconds
        if body.name is not None:
            race.name = body.name
        if body.priority is not None:
            race.priority = body.priority
        if body.status is not None:
            race.status = body.status
        if body.race_type is not None and body.race_type in _RACE_TYPE_VALUES:
            race.race_type = body.race_type

        race.goal_pace_seconds_per_km = _derive_goal_pace(
            race.goal_time_seconds,
            float(race.distance_km) if race.distance_km is not None else None,
        )
        race.updated_at = _datetime.now(_timezone.utc)

        session.commit()
        session.refresh(race)
        return JSONResponse(_race_dict(race))


@app.patch("/api/races/{race_id}")
def patch_race(race_id: str, body: _RaceUpdateBody, user: User = Depends(resolve_user)):
    """PATCH /api/races/:id — update any subset of mutable race fields (issue #708)."""
    try:
        rid = _uuid.UUID(race_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid race_id")

    # Resolve and validate the date field (``date`` preferred over ``race_date``)
    raw_date = body.date if body.date is not None else body.race_date
    if raw_date is not None:
        if body.date is not None:
            _validate_race_date_400(body.date)
        else:
            _validate_race_date(body.race_date)
    if body.distance_km is not None:
        _validate_distance_km(body.distance_km, status_code=400)

    with Session(engine) as session:
        race = session.get(Race, rid)
        if race is None or race.user_id != user.id:
            raise HTTPException(status_code=404, detail="race not found")

        if raw_date is not None:
            race.race_date = _date.fromisoformat(raw_date)
        if body.distance_km is not None:
            race.distance_km = body.distance_km
        if "goal_time_seconds" in body.model_fields_set:
            race.goal_time_seconds = body.goal_time_seconds
        if body.name is not None:
            race.name = body.name
        if body.priority is not None:
            race.priority = body.priority
        if body.status is not None:
            race.status = body.status
        if body.race_type is not None and body.race_type in _RACE_TYPE_VALUES:
            race.race_type = body.race_type

        race.goal_pace_seconds_per_km = _derive_goal_pace(
            race.goal_time_seconds,
            float(race.distance_km) if race.distance_km is not None else None,
        )
        race.updated_at = _datetime.now(_timezone.utc)

        session.commit()
        session.refresh(race)
        return JSONResponse(_race_dict(race))


@app.delete("/api/races/{race_id}", status_code=204)
def delete_race(race_id: str, user: User = Depends(resolve_user)):
    try:
        rid = _uuid.UUID(race_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid race_id")
    with Session(engine) as session:
        race = session.get(Race, rid)
        if race is None or race.user_id != user.id:
            raise HTTPException(status_code=404, detail="race not found")
        session.delete(race)
        session.commit()


# ── Race calibration ───────────────────────────────────────────────────────────

_CALIBRATION_TRAINING_BLOCK_WEEKS = 16


def _population_constants_dict() -> dict:
    return {
        "ctl_days": CTL_DAYS,
        "atl_days": ATL_DAYS,
        "timing_tolerance_weeks": TIMING_TOLERANCE_WEEKS,
        "ctl_adjustment_days_per_week": CTL_ADJUSTMENT_DAYS_PER_WEEK,
        "min_ctl_days": MIN_CTL_DAYS,
        "max_ctl_days": MAX_CTL_DAYS,
    }


def _derive_peak_weeks(session, user_id, race_date) -> tuple[int, int]:
    """Compute predicted and actual peak weeks from training-load snapshots.

    Both values are expressed as week numbers within the training block
    (0 = first week, CALIBRATION_TRAINING_BLOCK_WEEKS = race week).

    Predicted peak week = the week in the training block where TSB was
    highest assuming the model was run forward correctly (approximated as
    the race week itself, since a proper taper is designed to peak on race
    day; deviations show up in the actual_peak_week comparison).

    Actual peak week = the week in the training block where TSB was
    highest according to training_load_snapshots.
    """
    block_start = race_date - _timedelta(weeks=_CALIBRATION_TRAINING_BLOCK_WEEKS)

    from sqlalchemy import text as _text_cal
    rows = session.execute(
        _text_cal(
            """
            SELECT snapshot_date, tsb
            FROM training_load_snapshots
            WHERE user_id = :uid
              AND snapshot_date BETWEEN :start AND :end
            ORDER BY snapshot_date
            """
        ),
        {"uid": str(user_id), "start": block_start, "end": race_date},
    ).fetchall()

    if not rows:
        return _CALIBRATION_TRAINING_BLOCK_WEEKS, _CALIBRATION_TRAINING_BLOCK_WEEKS

    # Find the snapshot date with the highest TSB = actual peak
    best_row = max(rows, key=lambda r: r[1])
    best_date = best_row[0]
    if hasattr(best_date, "date"):
        best_date = best_date.date()

    days_from_start = (best_date - block_start).days
    actual_peak_week = days_from_start // 7

    # Predicted peak = race week (the model targets peak on race day)
    predicted_peak_week = _CALIBRATION_TRAINING_BLOCK_WEEKS

    return predicted_peak_week, actual_peak_week


class _CalibrateRaceBody(BaseModel):
    actual_time_seconds: int


class _AcceptCalibrationBody(BaseModel):
    ctl_days: Optional[int] = None
    atl_days: Optional[int] = None


@app.post("/api/races/{race_id}/calibrate")
def calibrate_race(
    race_id: str,
    body: _CalibrateRaceBody,
    user: User = Depends(resolve_user),
):
    """Log actual race result and return fitness-constant calibration suggestions.

    Thin caller for compute_calibration_suggestions.  Writes ``status='done'``
    and ``actual_time_seconds`` to the race row, then calls the pure function
    with peak-timing data derived from training_load_snapshots.  Never writes
    suggested constants to the user record.
    """
    try:
        rid = _uuid.UUID(race_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid race_id")

    with Session(engine) as session:
        race = session.get(Race, rid)
        if race is None or race.user_id != user.id:
            raise HTTPException(status_code=404, detail="race not found")

        if race.goal_time_seconds is None:
            raise HTTPException(
                status_code=422,
                detail={"field": "goal_time_seconds", "error": "race has no goal time; cannot calibrate"},
            )

        # Write actual result and mark race as done
        race.actual_time_seconds = body.actual_time_seconds
        race.status = "done"
        race.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(race)

        # Load user preferences for current personal constants
        prefs = session.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
        user_ctl = prefs.ctl_days if prefs else None
        user_atl = prefs.atl_days if prefs else None

        # Derive peak timing from training-load snapshots
        predicted_peak_week, actual_peak_week = _derive_peak_weeks(session, user.id, race.race_date)

        user_constants = {
            "ctl_days": user_ctl,
            "atl_days": user_atl,
            "predicted_peak_week": predicted_peak_week,
            "actual_peak_week": actual_peak_week,
            "goal_time_seconds": race.goal_time_seconds,
        }

        suggestions = compute_calibration_suggestions(
            str(race.id),
            body.actual_time_seconds,
            user_constants,
            _population_constants_dict(),
        )

    return JSONResponse({
        "race": _race_dict(race),
        "suggestions": suggestions,
    })


@app.post("/api/races/{race_id}/calibrate/accept")
def accept_calibration(
    race_id: str,
    body: _AcceptCalibrationBody,
    user: User = Depends(resolve_user),
):
    """Accept calibration suggestions and write new constants to user preferences.

    This is the explicit accept action (AC4).  Constants are only written when
    the user explicitly calls this endpoint — no automatic overwrite ever occurs.
    """
    try:
        rid = _uuid.UUID(race_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid race_id")

    with Session(engine) as session:
        race = session.get(Race, rid)
        if race is None or race.user_id != user.id:
            raise HTTPException(status_code=404, detail="race not found")

        prefs = session.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
        if prefs is None:
            prefs = UserPreferences(user_id=user.id)
            session.add(prefs)

        if body.ctl_days is not None:
            prefs.ctl_days = body.ctl_days
        if body.atl_days is not None:
            prefs.atl_days = body.atl_days
        prefs.updated_at = _datetime.now(_timezone.utc)

        session.commit()
        session.refresh(prefs)

        return JSONResponse({
            "ctl_days": prefs.ctl_days,
            "atl_days": prefs.atl_days,
            "message": "Fitness constants accepted and saved to your profile.",
        })


# ── Calibration status ────────────────────────────────────────────────────────

# Thresholds derived from the CTL model time constant so they scale with the
# underlying model rather than being bare magic numbers.
_CALIB_WINDOW_90: int = CTL_DAYS * 2 + 6   # 90-day sufficiency window
_CALIB_WINDOW_42: int = CTL_DAYS            # one CTL period = confidence window
_CALIB_SUFFICIENCY_HIGH: int = CTL_DAYS * 2  # ≥84 snapshots in 90 days → Sufficient
_CALIB_SUFFICIENCY_LOW: int = CTL_DAYS       # ≥42 → Low
_CALIB_BAND_HIGH: int = int(CTL_DAYS * 5 / 6)  # ≥35 snapshots in 42 days → High
_CALIB_BAND_MEDIUM: int = CTL_DAYS // 2         # ≥21 → Medium


def _compute_calibration_status(
    last_calibrated_race,
    snapshot_count_90: int,
    snapshot_count_42: int,
    race_count_90: int = 0,
) -> dict:
    """Derive calibration status from pre-fetched DB values.

    Pure function — no DB access. The calling endpoint fetches the necessary
    values and passes them in so this function is independently testable.

    Parameters
    ----------
    last_calibrated_race:
        The most recent Race with status='done' and actual_time_seconds set,
        or None if the user has never calibrated.
    snapshot_count_90:
        Number of TrainingLoadSnapshot rows for this user in the past 90 days.
    snapshot_count_42:
        Number of TrainingLoadSnapshot rows for this user in the past 42 days
        (one CTL period).

    Returns
    -------
    dict with keys:
        last_calibration_date — ISO date string or None
        data_sufficiency      — 'Sufficient', 'Low', or 'Insufficient'
        band_confidence       — 'High', 'Medium', or 'Low'
        calibrated            — bool
    """
    last_calibration_date = None
    if last_calibrated_race is not None:
        ts = getattr(last_calibrated_race, "updated_at", None)
        if ts is not None:
            last_calibration_date = ts.date().isoformat()
        else:
            # Older done races may have no updated_at; fall back to the race date.
            rd = getattr(last_calibrated_race, "race_date", None)
            if rd is not None:
                last_calibration_date = rd.isoformat()

    # Snapshot density gives the baseline; recent finished races (a real result
    # within the 90-day window) are strong calibration evidence and raise the
    # sufficiency/confidence floor: ≥2 races → Sufficient/High, 1 → Low/Medium.
    if snapshot_count_90 >= _CALIB_SUFFICIENCY_HIGH:
        data_sufficiency = "Sufficient"
    elif snapshot_count_90 >= _CALIB_SUFFICIENCY_LOW:
        data_sufficiency = "Low"
    else:
        data_sufficiency = "Insufficient"

    if snapshot_count_42 >= _CALIB_BAND_HIGH:
        band_confidence = "High"
    elif snapshot_count_42 >= _CALIB_BAND_MEDIUM:
        band_confidence = "Medium"
    else:
        band_confidence = "Low"

    _rank = {"Insufficient": 0, "Low": 1, "Sufficient": 2}
    _band_rank = {"Low": 0, "Medium": 1, "High": 2}
    if race_count_90 >= 2:
        race_suff, race_band = "Sufficient", "High"
    elif race_count_90 == 1:
        race_suff, race_band = "Low", "Medium"
    else:
        race_suff, race_band = "Insufficient", "Low"
    if _rank[race_suff] > _rank[data_sufficiency]:
        data_sufficiency = race_suff
    if _band_rank[race_band] > _band_rank[band_confidence]:
        band_confidence = race_band

    return {
        "last_calibration_date": last_calibration_date,
        "data_sufficiency": data_sufficiency,
        "band_confidence": band_confidence,
        "calibrated": last_calibration_date is not None,
    }


@app.get("/api/calibration/status")
def get_calibration_status(user: User = Depends(resolve_user)):
    """Return calibration status for the current user (issue #1165).

    Surfaces three model-level indicators so users can assess the trustworthiness
    of model outputs and know when a recalibration may be needed:

    - last_calibration_date: date of the most recent race marked as done with
      an actual result (i.e. the last time calibrate_race was called).
    - data_sufficiency: quality label based on training snapshot density in the
      past 90 days ('Sufficient', 'Low', or 'Insufficient').
    - band_confidence: confidence label based on training snapshot density in
      the past 42 days (one CTL period) — 'High', 'Medium', or 'Low'.
    - calibrated: boolean, false when the user has never calibrated.

    All values are derived from model constants (CTL_DAYS) and live DB state —
    nothing is hardcoded.
    """
    today = _date.today()
    window_90 = today - _timedelta(days=_CALIB_WINDOW_90)
    window_42 = today - _timedelta(days=_CALIB_WINDOW_42)

    with Session(engine) as db:
        last_race = (
            db.query(Race)
            .filter(
                Race.user_id == user.id,
                Race.status == "done",
                Race.actual_time_seconds.isnot(None),
            )
            .order_by(Race.updated_at.desc())
            .first()
        )

        count_90 = (
            db.query(TrainingLoadSnapshot)
            .filter(
                TrainingLoadSnapshot.user_id == user.id,
                TrainingLoadSnapshot.snapshot_date >= window_90,
            )
            .count()
        )

        count_42 = (
            db.query(TrainingLoadSnapshot)
            .filter(
                TrainingLoadSnapshot.user_id == user.id,
                TrainingLoadSnapshot.snapshot_date >= window_42,
            )
            .count()
        )

        # Finished races (real result) within the 90-day window count as
        # calibration records (issue #1226).
        race_count_90 = (
            db.query(Race)
            .filter(
                Race.user_id == user.id,
                Race.status == "done",
                Race.actual_time_seconds.isnot(None),
                Race.race_date >= window_90,
            )
            .count()
        )

    return JSONResponse(
        _compute_calibration_status(last_race, count_90, count_42, race_count_90)
    )


# ── Race Checkpoints ──────────────────────────────────────────────────────────


def _run_checkpoint_autodetection(workout: Workout) -> None:
    """Evaluate and update unmet/non-overridden checkpoints after a run is ingested.

    This is the thin caller that loads checkpoints from the DB and delegates
    the pure evaluation logic to ``evaluate_checkpoint`` from
    ``backend.services.checkpoint_detector``.
    """
    if not _is_run_workout(workout.workout_type or ""):
        return

    run_distance = float(workout.distance_km) if workout.distance_km is not None else None
    run_duration = workout.duration_seconds

    with Session(engine) as session:
        checkpoints = (
            session.query(RaceCheckpoint)
            .filter(
                RaceCheckpoint.user_id == workout.user_id,
                RaceCheckpoint.met == False,  # noqa: E712
                RaceCheckpoint.met_override == False,  # noqa: E712
            )
            .all()
        )
        updated = False
        for cp in checkpoints:
            if _evaluate_checkpoint(cp, run_distance, run_duration):
                cp.met = True
                cp.met_workout_id = workout.id
                cp.updated_at = _datetime.now(_timezone.utc)
                updated = True
        if updated:
            session.commit()


class _CheckpointCreateBody(BaseModel):
    name: Optional[str] = None
    target_distance_km: Optional[float] = None
    target_pace_seconds_per_km: Optional[int] = None
    target_duration_seconds: Optional[int] = None


class _CheckpointUpdateBody(BaseModel):
    name: Optional[str] = None
    target_distance_km: Optional[float] = None
    target_pace_seconds_per_km: Optional[int] = None
    target_duration_seconds: Optional[int] = None
    met: Optional[bool] = None


def _checkpoint_dict(cp: RaceCheckpoint) -> dict:
    return {
        "id": str(cp.id),
        "race_id": str(cp.race_id),
        "user_id": str(cp.user_id),
        "name": cp.label,
        "target_distance_km": float(cp.target_distance_km) if cp.target_distance_km is not None else None,
        "target_pace_seconds_per_km": cp.target_pace_seconds_per_km,
        "target_duration_seconds": cp.target_duration_seconds,
        "half_marathon_equivalent_seconds": _riegel_half_equivalent(
            cp.target_duration_seconds,
            float(cp.target_distance_km) if cp.target_distance_km is not None else None,
        ),
        "met": cp.met,
        "met_override": cp.met_override,
        "met_workout_id": str(cp.met_workout_id) if cp.met_workout_id is not None else None,
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
        "updated_at": cp.updated_at.isoformat() if cp.updated_at else None,
    }


def _resolve_race_for_user(race_id_str: str, user: "User", session: "Session") -> Race:
    """Load a race by id, raising 404 if not found or not owned by user."""
    try:
        rid = _uuid.UUID(race_id_str)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid race_id")
    race = session.get(Race, rid)
    if race is None or race.user_id != user.id:
        raise HTTPException(status_code=404, detail="race not found")
    return race


@app.post("/api/races/{race_id}/checkpoints", status_code=201)
def create_checkpoint(
    race_id: str, body: _CheckpointCreateBody, user: User = Depends(resolve_user)
):
    """Create a checkpoint for a race (issue #708)."""
    if not body.name or not body.name.strip():
        raise HTTPException(
            status_code=400,
            detail={"field": "name", "error": "name is required"},
        )
    has_target = (
        body.target_distance_km is not None
        or body.target_pace_seconds_per_km is not None
        or body.target_duration_seconds is not None
    )
    if not has_target:
        raise HTTPException(
            status_code=400,
            detail={
                "error": (
                    "At least one of target_distance_km, target_pace_seconds_per_km, "
                    "or target_duration_seconds is required"
                )
            },
        )

    with Session(engine) as session:
        race = _resolve_race_for_user(race_id, user, session)
        cp = RaceCheckpoint(
            race_id=race.id,
            user_id=user.id,
            label=body.name.strip(),
            target_date=race.race_date,
            target_distance_km=body.target_distance_km,
            target_pace_seconds_per_km=body.target_pace_seconds_per_km,
            target_duration_seconds=body.target_duration_seconds,
        )
        session.add(cp)
        session.commit()
        session.refresh(cp)
        return JSONResponse(status_code=201, content=_checkpoint_dict(cp))


@app.get("/api/races/{race_id}/checkpoints")
def list_checkpoints(race_id: str, user: User = Depends(resolve_user)):
    """List all checkpoints for a race (issue #708)."""
    with Session(engine) as session:
        _resolve_race_for_user(race_id, user, session)
        rows = (
            session.query(RaceCheckpoint)
            .filter(RaceCheckpoint.race_id == _uuid.UUID(race_id))
            .order_by(RaceCheckpoint.created_at)
            .all()
        )
        return JSONResponse([_checkpoint_dict(cp) for cp in rows])


@app.get("/api/races/{race_id}/checkpoints/{checkpoint_id}")
def get_checkpoint(race_id: str, checkpoint_id: str, user: User = Depends(resolve_user)):
    """Return a single checkpoint (issue #708)."""
    try:
        cp_id = _uuid.UUID(checkpoint_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid checkpoint_id")

    with Session(engine) as session:
        _resolve_race_for_user(race_id, user, session)
        cp = session.get(RaceCheckpoint, cp_id)
        if cp is None or str(cp.race_id) != race_id:
            raise HTTPException(status_code=404, detail="checkpoint not found")
        return JSONResponse(_checkpoint_dict(cp))


@app.patch("/api/races/{race_id}/checkpoints/{checkpoint_id}")
def patch_checkpoint(
    race_id: str,
    checkpoint_id: str,
    body: _CheckpointUpdateBody,
    user: User = Depends(resolve_user),
):
    """Update mutable fields on a checkpoint (issue #708).

    Setting ``met`` to any value sets ``met_override = True`` so subsequent
    auto-detection will not overwrite the manually chosen state.
    """
    try:
        cp_id = _uuid.UUID(checkpoint_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid checkpoint_id")

    with Session(engine) as session:
        _resolve_race_for_user(race_id, user, session)
        cp = session.get(RaceCheckpoint, cp_id)
        if cp is None or str(cp.race_id) != race_id:
            raise HTTPException(status_code=404, detail="checkpoint not found")

        if body.name is not None:
            cp.label = body.name.strip()
        if body.target_distance_km is not None:
            cp.target_distance_km = body.target_distance_km
        if body.target_pace_seconds_per_km is not None:
            cp.target_pace_seconds_per_km = body.target_pace_seconds_per_km
        if body.target_duration_seconds is not None:
            cp.target_duration_seconds = body.target_duration_seconds
        if "met" in body.model_fields_set and body.met is not None:
            cp.met = body.met
            cp.met_override = True

        cp.updated_at = _datetime.now(_timezone.utc)
        session.commit()
        session.refresh(cp)
        return JSONResponse(_checkpoint_dict(cp))


@app.delete("/api/races/{race_id}/checkpoints/{checkpoint_id}", status_code=204)
def delete_checkpoint(race_id: str, checkpoint_id: str, user: User = Depends(resolve_user)):
    """Delete a checkpoint (issue #708)."""
    try:
        cp_id = _uuid.UUID(checkpoint_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid checkpoint_id")

    with Session(engine) as session:
        _resolve_race_for_user(race_id, user, session)
        cp = session.get(RaceCheckpoint, cp_id)
        if cp is None or str(cp.race_id) != race_id:
            raise HTTPException(status_code=404, detail="checkpoint not found")
        session.delete(cp)
        session.commit()


# ── Race readiness config keys ────────────────────────────────────────────────
# These AppConfig keys control the thresholds used by GET /api/races/{id}/readiness.
# Absent keys fall back to the named constants from training_load.
_RDNS_CFG_BURIED_CEILING = "readiness.form_buried_ceiling"
_RDNS_CFG_FRESH_FLOOR = "readiness.form_fresh_floor"
_RDNS_CFG_MIN_HISTORY_WEEKS = "readiness.min_history_weeks"
_RDNS_CFG_PEAK_TOLERANCE = "readiness.peak_tracking_tolerance"

# How many distinct workout days per minimum-history week are required on average
# before a projection is considered meaningful.  At 1.0, the athlete must have
# logged at least one workout for every week in the minimum-history window.
_RDNS_MIN_WORKOUT_DAYS_PER_WEEK = 1


def _rdns_cfg_float(key: str, default: float) -> float:
    """Read a float from AppConfig; return default if absent or unparseable."""
    val = _get_app_config(key, "")
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _rdns_cfg_int(key: str, default: int) -> int:
    """Read an int from AppConfig; return default if absent or unparseable."""
    val = _get_app_config(key, "")
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _rdns_classify_zone(tsb: float, buried_ceiling: float, fresh_floor: float) -> str:
    """Classify a TSB value into a zone using configurable thresholds.

    Uses the canonical zone vocabulary defined in backend/services/training_load.py
    (_classify_zone / performance_curve): buried / neutral / fresh.

    Zones:
        buried  — TSB is below buried_ceiling (athlete is over-reached)
        fresh   — TSB is at or above fresh_floor (athlete is well-rested)
        neutral — TSB is between the two thresholds
    """
    if tsb < buried_ceiling:
        return "buried"
    if tsb >= fresh_floor:
        return "fresh"
    return "neutral"


_RACE_READINESS_UNSET = object()


@app.get("/api/races/{race_id}/readiness")
def get_race_readiness(race_id: str, user: User = Depends(resolve_user)):
    """Return combined race-readiness data for the given race.

    Aggregates form_curve, projected_form, taper_recommendation, on_track, and
    specificity_progress in a single response.  All thresholds are read from
    AppConfig; no numeric constant is hardcoded in this function body.

    Returns:
        200 with readiness dict on success.
        403 when the race belongs to a different user.
        404 when the race_id does not exist or is invalid.
    """
    return _race_readiness_impl(race_id, user)


def _race_readiness_impl(
    race_id: str,
    user: User,
    _shared_load_curves=None,
    _shared_threshold_pace=_RACE_READINESS_UNSET,
):
    """Core of get_race_readiness(), extracted so callers computing readiness
    for multiple races of the same user in one request (e.g. the Plan bundle)
    can pass in the shared 180-day TSS/EWMA series and threshold_pace instead
    of each race re-querying/recomputing identical per-user data."""
    # ── 1. Parse and resolve race ─────────────────────────────────────────────
    try:
        rid = _uuid.UUID(race_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid race id format: {race_id!r}")

    with Session(engine) as db:
        race = db.get(Race, rid)

    if race is None:
        raise HTTPException(status_code=404, detail="race not found")
    if race.user_id != user.id:
        raise HTTPException(status_code=404, detail="race not found")

    # ── 2. Read all thresholds from configuration ─────────────────────────────
    buried_ceiling = _rdns_cfg_float(_RDNS_CFG_BURIED_CEILING, FORM_BURIED_CEILING)
    fresh_floor = _rdns_cfg_float(_RDNS_CFG_FRESH_FLOOR, FORM_FRESH_FLOOR)
    min_history_weeks = _rdns_cfg_int(_RDNS_CFG_MIN_HISTORY_WEEKS, 8)
    peak_tolerance = _rdns_cfg_float(_RDNS_CFG_PEAK_TOLERANCE, PEAK_TRACKING_TOLERANCE)

    today = _date.today()

    # ── 3. Load historical TSS series for form_curve (6-month warmup window) ──
    warmup_start = today - _timedelta(days=180)
    if _shared_load_curves is not None:
        tss_series, load_curves = _shared_load_curves
    else:
        tss_series = daily_tss_series(str(user.id), warmup_start, today)
        _ctl_days, _atl_days = resolve_user_ewma_days(str(user.id))
        load_curves = compute_load_curves(tss_series, ctl_days=_ctl_days, atl_days=_atl_days)

    # ── 4. Build form_curve with configurable zone labels ─────────────────────
    form_curve = [
        {
            "date": row["date"].isoformat(),
            "form": row["tsb"],
            "zone": _rdns_classify_zone(row["tsb"], buried_ceiling, fresh_floor),
        }
        for row in load_curves
    ]

    # ── 5. Determine building_baseline ───────────────────────────────────────
    # Count distinct days with non-zero TSS within the minimum-history window.
    # If fewer than (min_history_weeks * _RDNS_MIN_WORKOUT_DAYS_PER_WEEK) days
    # have workouts, there is not enough history to project meaningfully.
    history_window_start = today - _timedelta(days=min_history_weeks * 7)
    workout_days_in_window = sum(
        1 for d, tss in tss_series
        if tss > 0 and d >= history_window_start
    )
    required_workout_days = min_history_weeks * _RDNS_MIN_WORKOUT_DAYS_PER_WEEK
    building_baseline = workout_days_in_window < required_workout_days

    # ── 6. Today's fitness state (CTL, ATL, TSB) from end of load curves ─────
    last_row = load_curves[-1]
    fitness_state = {
        "ctl": last_row["ctl"],
        "atl": last_row["atl"],
        "date": last_row["date"],
    }
    current_tsb = last_row["tsb"]

    # ── 7. projected_form and taper_recommendation (only when sufficient history) ──
    projected_form: Optional[dict] = None
    taper_rec: Optional[dict] = None

    if not building_baseline:
        race_date = race.race_date
        proj = project_form(fitness_state, 0.0, race_date)
        if not proj["reason"]:
            projected_form = {
                day["date"].isoformat(): day["form"]
                for day in proj["days"]
            }

        taper_raw = taper_recommendation(fitness_state, race_date, TARGET_FORM_LOWER)
        if not taper_raw["reason"]:
            taper_rec = {
                "taper_start_date": taper_raw["taper_start_date"].isoformat()
                if taper_raw["taper_start_date"] else None,
                "message": taper_raw["message"],
                "achievable": taper_raw["achievable"],
            }

    # ── 8. on_track via peak_tracking ────────────────────────────────────────
    # Derive the projected form for today from the taper plan.
    # The plan: taper started DEFAULT_TAPER_DAYS before race_date at whatever
    # fitness state the athlete had on that date.
    # If we are within the taper window (today >= taper_start) and history is
    # sufficient, compute the planned form for today by projecting from the
    # fitness state at taper_start with zero load.
    on_track_result = peak_tracking(None, None)  # default: insufficient data
    taper_start = race.race_date - _timedelta(days=DEFAULT_TAPER_DAYS)

    if not building_baseline and today >= taper_start:
        # Compute fitness state at taper_start by running load curves up to that date
        taper_start_series = daily_tss_series(str(user.id), warmup_start, taper_start)
        _ctl_days, _atl_days = resolve_user_ewma_days(str(user.id))
        taper_start_curves = compute_load_curves(taper_start_series, ctl_days=_ctl_days, atl_days=_atl_days)
        taper_start_state = {
            "ctl": taper_start_curves[-1]["ctl"],
            "atl": taper_start_curves[-1]["atl"],
            "date": taper_start_curves[-1]["date"],
        }
        # Project forward from taper_start to today with zero load (taper assumption)
        plan_proj = project_form(taper_start_state, 0.0, today)
        if not plan_proj["reason"] and plan_proj["days"]:
            projected_today = plan_proj["days"][-1]["form"]
            on_track_result = peak_tracking(current_tsb, projected_today, tolerance=peak_tolerance)

    on_track_status = on_track_result.get("status")
    on_track_bool = on_track_status in ("on track", "ahead") if on_track_status else None

    # ── 9. specificity_progress, timeline_markers, and user thresholds ──────────
    # Fetch recent runs (last 90 days), B/C-race + checkpoint markers, and user
    # preferences (for threshold_pace) in one DB session so the route handler
    # owns all data access.
    run_window_start = today - _timedelta(days=90)
    with Session(engine) as db:
        from sqlalchemy import text as _text
        recent_runs_rows = db.execute(
            _text(
                """
                SELECT distance_km, duration_seconds
                FROM workouts
                WHERE user_id = :uid
                  AND workout_date >= :since
                  AND workout_type IN ('run', 'running', 'race')
                  AND distance_km IS NOT NULL
                  AND duration_seconds IS NOT NULL
                ORDER BY workout_date DESC
                """
            ),
            {"uid": str(user.id), "since": run_window_start},
        ).fetchall()

        marker_rows = db.execute(
            _text(
                """
                SELECT race_date, race_type, priority, name
                FROM races
                WHERE user_id = :uid
                  AND id != :race_id
                  AND race_date > :today
                  AND race_date < :race_date
                  AND (
                    (race_type = 'race' AND priority IN ('B', 'C'))
                    OR race_type = 'checkpoint'
                  )
                ORDER BY race_date ASC
                """
            ),
            {
                "uid": str(user.id),
                "race_id": str(race.id),
                "today": today,
                "race_date": race.race_date,
            },
        ).fetchall()

        if _shared_threshold_pace is not _RACE_READINESS_UNSET:
            threshold_pace = _shared_threshold_pace
        else:
            user_prefs_row = db.query(UserPreferences).filter(
                UserPreferences.user_id == user.id
            ).first()
            threshold_pace = (
                user_prefs_row.threshold_pace_seconds_per_km
                if user_prefs_row else None
            )

        # Fetch per-user stimulus history for the economy ceiling bonus.
        _snap_rows = (
            db.query(EconomyCeilingSnapshot)
            .filter(EconomyCeilingSnapshot.user_id == user.id)
            .order_by(EconomyCeilingSnapshot.snapshot_date.asc())
            .all()
        )
        _stimulus_history = [
            (row.snapshot_date, row.economy_stimulus) for row in _snap_rows
        ]

    import types as _types

    recent_runs = [
        _types.SimpleNamespace(
            distance_km=float(r[0]),
            duration_seconds=int(r[1]),
        )
        for r in recent_runs_rows
        if r[0] and r[1]
    ]

    spec_result = _specificity_progress(race, recent_runs)

    timeline_markers = []
    for row in marker_rows:
        r_date, r_type, r_priority, r_name = row[0], row[1], row[2], row[3]
        marker_type = "checkpoint" if r_type == "checkpoint" else f"{r_priority}-race"
        timeline_markers.append({
            "date": r_date.isoformat(),
            "type": marker_type,
            "label": r_name,
        })

    # ── 10. Compute time_curve (historical + projected estimated finish times) ───
    # The time curve maps TSB-derived expressible scores to estimated race finish
    # times, giving a view of how the projected race performance evolves over time.
    # Confidence bands (from projection.py) are included for projected entries.
    _tc_thresholds = {"threshold_pace_seconds_per_km": threshold_pace}
    _tc_distance = float(race.distance_km) if race.distance_km else None

    # Anchor the estimate on DEMONSTRATED fitness: invert the best finished race
    # within 90 days into an endurance ceiling and use it as the estimate
    # baseline, instead of the CTL-derived score which discards race results
    # (issue #1226). Falls back to the CTL ceiling when no recent race exists.
    _race_anchor_ceiling = None
    if threshold_pace and float(threshold_pace) > 0:
        from backend.services.score_ceiling import (
            ceiling_from_b_race_result as _ceiling_from_race,
        )
        _anchor_cut = today - _timedelta(days=90)
        _done_races = (
            db.query(Race)
            .filter(
                Race.user_id == user.id,
                Race.status == "done",
                Race.actual_time_seconds.isnot(None),
                Race.distance_km.isnot(None),
                Race.race_date >= _anchor_cut,
            )
            .all()
        )
        for _dr in _done_races:
            _c = _ceiling_from_race(
                _dr.actual_time_seconds, float(_dr.distance_km), float(threshold_pace)
            )
            _ec = _c.get("endurance_ceiling")
            if _ec is not None and (
                _race_anchor_ceiling is None or _ec > _race_anchor_ceiling
            ):
                _race_anchor_ceiling = _ec

    def _base_ceiling(ctl_value):
        if _race_anchor_ceiling is not None:
            return _race_anchor_ceiling
        return _projected_ctl_to_score_ceiling(
            ctl_value,
            stimulus_history=_stimulus_history,
            reference_date=today,
        )["endurance_ceiling"]

    # History: last 90 days of load_curves → expressible score → estimated finish time
    _tc_history_cutoff = today - _timedelta(days=90)
    time_curve_history = []
    for _row in load_curves:
        if _row["date"] < _tc_history_cutoff:
            continue
        _base = _base_ceiling(_row["ctl"])
        _expr = _compute_expressible_score(_base, _row["tsb"], _TIME_CURVE_CEILING_TSB)
        _est = _score_to_estimated_finish_time(_expr, _tc_thresholds, _tc_distance)
        if _est["estimated_finish_seconds"] is not None:
            time_curve_history.append({
                "date": _row["date"].isoformat(),
                "estimated_finish_seconds": _est["estimated_finish_seconds"],
                "estimated_finish_time": _est["estimated_finish_time"],
            })

    # Projection: from today to race_date with zero load (taper assumption) + confidence band
    time_curve_projection = []
    if not building_baseline:
        _days_to_race = (race.race_date - today).days
        if _days_to_race > 0:
            _planned = [0.0] * _days_to_race
            _proj_series = _project_fitness(
                planned_load=_planned,
                start_ctl=last_row["ctl"],
                start_atl=last_row["atl"],
                start_date=today,
            )
            for _day, _day_data in sorted(_proj_series.items()):
                _base = _base_ceiling(_day_data["ctl"])
                _expr = _compute_expressible_score(_base, _day_data["tsb"], _TIME_CURVE_CEILING_TSB)
                _est = _score_to_estimated_finish_time(_expr, _tc_thresholds, _tc_distance)
                if _est["estimated_finish_seconds"] is None:
                    continue
                # Treat confidence_band_days as a percentage of estimated finish time.
                # band(7) ≈ 1.3%, band(90) ≈ 4.7% — a realistic uncertainty envelope.
                _cb_pct = _day_data["confidence_band"]
                _band_sec = int(_est["estimated_finish_seconds"] * _cb_pct / 100.0)
                time_curve_projection.append({
                    "date": _day.isoformat(),
                    "estimated_finish_seconds": _est["estimated_finish_seconds"],
                    "estimated_finish_time": _est["estimated_finish_time"],
                    "confidence_band_seconds": _band_sec,
                    "upper_seconds": _est["estimated_finish_seconds"] + _band_sec,
                    "lower_seconds": max(0, _est["estimated_finish_seconds"] - _band_sec),
                })

    # Goal finish time
    _goal_secs = race.goal_time_seconds if race.goal_time_seconds else None
    _goal_str: Optional[str] = None
    if _goal_secs:
        _gh = _goal_secs // 3600
        _gm = (_goal_secs % 3600) // 60
        _gs = _goal_secs % 60
        _goal_str = f"{_gh}:{_gm:02d}:{_gs:02d}"

    # ── 11. Assemble response ─────────────────────────────────────────────────
    response: dict = {
        "race_id": str(race.id),
        "building_baseline": building_baseline,
        "form_curve": form_curve,
        "on_track": {
            "on_track": on_track_bool,
            "status_summary": on_track_status or on_track_result.get("reason") or "insufficient data",
            "gap": on_track_result.get("gap"),
        },
        "specificity_progress": spec_result,
        "timeline_markers": timeline_markers,
        "time_curve": {
            "history": time_curve_history,
            "projection": time_curve_projection,
            "goal_finish_seconds": _goal_secs,
            "goal_finish_time": _goal_str,
        },
    }

    if not building_baseline:
        if projected_form is not None:
            response["projected_form"] = projected_form
        if taper_rec is not None:
            response["taper_recommendation"] = taper_rec  # kept for backward compatibility
            response["taper"] = taper_rec  # canonical key per issue #713

    return JSONResponse(response)


# ── Threshold suggestions ──────────────────────────────────────────────────────

_SUGGESTION_KEYS = ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km")

# Standard power durations (seconds) used when building the user's power curve.
_POWER_DURATION_LADDER = [300, 600, 1200, 1800, 3600]


def _build_user_power_curve(session, user_id) -> dict:
    """Return a {duration_seconds: best_avg_power_watts} dict for the user.

    For each duration D the value is the highest workout-level avg_power found
    across all workouts whose total duration is at least D seconds.  Splits with
    a shorter individual duration than the full workout can also contribute
    (same ≥ D rule applied to split.duration_seconds).
    """

    curve: dict = {}
    for d in _POWER_DURATION_LADDER:
        # Workout-level aggregate power
        w_best = (
            session.query(func.max(Workout.avg_power))
            .filter(
                Workout.user_id == user_id,
                Workout.duration_seconds >= d,
                Workout.avg_power.isnot(None),
            )
            .scalar()
        )
        # Split-level power (can be higher than workout average)
        s_best = (
            session.query(func.max(WorkoutSplit.avg_power))
            .join(Workout, WorkoutSplit.workout_id == Workout.id)
            .filter(
                Workout.user_id == user_id,
                WorkoutSplit.duration_seconds >= d,
                WorkoutSplit.avg_power.isnot(None),
            )
            .scalar()
        )
        candidates = [v for v in (w_best, s_best) if v is not None]
        if candidates:
            curve[d] = float(max(candidates))
    return curve


def _build_user_recent_runs(session, user_id, limit: int = 30) -> list:
    """Return a list of run dicts for the user's most recent runs.

    Each dict has ``duration_seconds``, ``avg_pace_seconds_per_km``, and
    ``avg_hr_bpm``.  Only runs with both distance and duration set are included.
    """
    workouts = (
        session.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_type == "run",
            Workout.duration_seconds.isnot(None),
            Workout.distance_km.isnot(None),
        )
        .order_by(Workout.workout_date.desc())
        .limit(limit)
        .all()
    )
    runs = []
    for w in workouts:
        if w.distance_km and float(w.distance_km) > 0:
            runs.append({
                "duration_seconds": w.duration_seconds,
                "avg_pace_seconds_per_km": w.duration_seconds / float(w.distance_km),
                "avg_hr_bpm": w.avg_hr,
            })
    return runs


def _pending_suggestions(session, user_id) -> dict:
    """Compute suggestions and filter out already-accepted ones.

    Returns a dict of ``{key: {"value": ..., "high_confidence": ..., "formula": ...}}``
    for threshold keys that are not yet marked ``source = "user_accepted"`` in
    ``user_preferences``.  The ``formula`` key carries a human-readable description
    of how the suggestion was derived (e.g. "best 20-minute power multiplied by 0.95").
    """
    from backend.services.threshold_suggestions import suggest_thresholds

    duration_curve = _build_user_power_curve(session, user_id)
    recent_runs = _build_user_recent_runs(session, user_id)
    result = suggest_thresholds(duration_curve, recent_runs)

    # Insufficient-data sentinel: the service returns {"suggestions": {}, "reason": ...}
    if "suggestions" in result:
        return {}

    debug = result.get("debug", {})

    prefs = (
        session.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )

    pending = {}
    for key in _SUGGESTION_KEYS:
        if key not in result:
            continue
        source_attr = f"{key}_source"
        existing_source = getattr(prefs, source_attr, None) if prefs else None
        if existing_source != "user_accepted":
            entry = dict(result[key])
            entry["formula"] = (debug.get(key) or {}).get("formula", "")
            pending[key] = entry
    return pending


@app.get("/api/thresholds/suggestions")
def get_threshold_suggestions(user: User = Depends(resolve_user)):
    """Return pending threshold suggestions for the authenticated user.

    A suggestion is pending when ``suggest_thresholds`` returns a value for
    that key and the user has not yet accepted it (``source != "user_accepted"``
    in ``user_preferences``).  Returns HTTP 200 with an empty list when no
    suggestions exist — never 404 or 500 for the no-suggestions state.
    """
    with Session(engine) as session:
        pending = _pending_suggestions(session, user.id)
        return JSONResponse({"pending": pending})


@app.post("/api/thresholds/suggestions/accept")
async def accept_threshold_suggestions(
    request: Request,
    user: User = Depends(resolve_user),
):
    """Accept a subset of suggested threshold values and persist them.

    Payload: ``{"keys": ["ftp_w", "threshold_hr", ...]}``

    Only the keys listed in ``keys`` are written to ``user_preferences``.
    Threshold values that exist in ``user_preferences`` with any source are
    not overwritten unless the caller explicitly includes that key in the
    payload.  Each written record gets ``source = "user_accepted"``.

    Returns ``{"written": {key: value, ...}, "skipped": [key, ...]}`` — a
    structured confirmation of which keys were persisted and their new values.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    keys_to_accept = body.get("keys", [])
    if not isinstance(keys_to_accept, list):
        raise HTTPException(status_code=422, detail="'keys' must be a list")

    # Validate requested keys are recognised threshold keys
    unknown = [k for k in keys_to_accept if k not in _SUGGESTION_KEYS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown threshold keys: {unknown}. Valid keys: {list(_SUGGESTION_KEYS)}",
        )

    with Session(engine) as session:
        # Use _pending_suggestions to get only keys not yet accepted.
        pending = _pending_suggestions(session, user.id)

        # AC7: every requested key must have a pending suggestion; error otherwise.
        if keys_to_accept:
            missing = [k for k in keys_to_accept if k not in pending]
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"No pending suggestion for key(s): {missing}. "
                        f"Pending suggestions available for: {list(pending.keys())}"
                    ),
                )

        if not keys_to_accept:
            return JSONResponse({"written": {}, "skipped": []})

        # Get or create user preferences row
        prefs = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == user.id)
            .first()
        )
        if prefs is None:
            prefs = UserPreferences(user_id=user.id)
            session.add(prefs)

        _now = _datetime.now(_timezone.utc)
        written: dict = {}
        for key in keys_to_accept:
            value = pending[key]["value"]
            setattr(prefs, key, value)
            setattr(prefs, f"{key}_source", "user_accepted")
            _ts_attr = f"{key}_updated_at"
            if hasattr(prefs, _ts_attr):
                setattr(prefs, _ts_attr, _now)
            written[key] = value

        prefs.updated_at = _now
        session.commit()
        # Run the full performance backfill in background so scores and the
        # fitness chart reflect the newly accepted thresholds without blocking
        # the HTTP response.  Idempotent; safe to re-run.
        _trigger_performance_backfill_background(user.id)
        return JSONResponse({"written": written, "skipped": []})


@app.get("/api/thresholds/device-zones")
def get_device_zones(user: User = Depends(resolve_user)):
    """Return device-sourced power zones for the authenticated user (read-only).

    Pulls the most recent Stryd activity that contains ``power_zones`` data and
    returns the zone breakdown and critical power value from the device.  The
    response intentionally carries no edit surface — these values come from the
    device and can only change via a Stryd sync.

    Returns ``{"source": "stryd", "critical_power_w": <int|null>,
    "zones": {...}}`` when data is available, or ``{"source": null, "zones": {}}``
    when the user has no Stryd activity with power zone data.
    """
    with Session(engine) as session:
        from sqlalchemy import desc as _sa_desc

        latest = (
            session.query(StrydActivity)
            .filter(
                StrydActivity.user_id == user.id,
                StrydActivity.power_zones.isnot(None),
            )
            .order_by(_sa_desc(StrydActivity.start_time))
            .first()
        )

        if latest is None or not latest.power_zones:
            return JSONResponse({"source": None, "critical_power_w": None, "zones": {}})

        pz = latest.power_zones or {}
        critical_power = pz.get("critical_power_w")

        # Extract per-zone values (keys starting with "z")
        zones = {k: v for k, v in pz.items() if str(k).startswith("z")}

        return JSONResponse({
            "source": "stryd",
            "critical_power_w": critical_power,
            "zones": zones,
            "activity_date": latest.start_time.date().isoformat() if latest.start_time else None,
        })


# ── Athlete duration curve ────────────────────────────────────────────────────

@app.get("/api/athletes/{athlete_id}/duration-curve")
def get_athlete_duration_curve(athlete_id: str, current_user: User = Depends(resolve_user)):
    """Return the per-athlete best-effort duration curve across all run workouts.

    Returns 200 with an empty curve and a ``reason`` field when the athlete exists
    but has no runs on record. The athlete is always the authenticated session user.

    Each curve entry includes duration, best_value, source_workout_id, source_date,
    and a debug object identifying the source workout.
    """
    try:
        if _uuid.UUID(athlete_id) != current_user.id:
            raise HTTPException(status_code=404, detail="Athlete not found")
    except ValueError:
        raise HTTPException(status_code=404, detail="Athlete not found")
    uid = current_user.id

    with Session(engine) as session:
        athlete = session.get(User, uid)
        if athlete is None:
            raise HTTPException(status_code=404, detail="Athlete not found")

        curve_data = _get_athlete_duration_curve(uid, session)

        if not curve_data:
            return JSONResponse({
                "athleteId": str(uid),
                "curve": [],
                "debug": [],
                "reason": "No runs found for athlete",
            })

        # Batch-load workout names for debug labels
        workout_ids = set()
        for entry in curve_data.values():
            wid = entry.get("workout_id")
            if wid:
                try:
                    workout_ids.add(_uuid.UUID(wid))
                except (ValueError, AttributeError):
                    pass

        workout_names: dict = {}
        if workout_ids:
            rows = (
                session.query(Workout.id, Workout.name)
                .filter(Workout.id.in_(workout_ids))
                .all()
            )
            workout_names = {str(r.id): r.name for r in rows}

    curve_entries = sorted(
        [
            {
                "duration": int(dur),
                "best_value": entry["best_value"],
                "source_workout_id": entry["workout_id"],
                "source_date": entry.get("date"),
                "debug": {
                    "workout_label": workout_names.get(entry["workout_id"])
                    or entry["workout_id"],
                    "confidence": entry.get("confidence"),
                },
            }
            for dur, entry in curve_data.items()
        ],
        key=lambda e: e["duration"],
    )

    return JSONResponse({
        "athleteId": str(uid),
        "curve": curve_entries,
        "debug": [e["debug"] for e in curve_entries],
    })


# ── Athlete detected personal records ─────────────────────────────────────────

@app.get("/api/athletes/{athlete_id}/detected-prs")
def get_athlete_detected_prs(athlete_id: str, user: User = Depends(resolve_user)):
    """Return automatically detected personal records for the authenticated athlete.

    Computes speed, power, and volume records on the fly from run history and
    the stored best-effort duration curve.  No manual PR entry is required.

    Speed records: fastest estimated time at each standard distance (1 km, 1 mile,
    5 km, 10 km, half marathon, marathon).
    Power records: highest mean power at standard durations (1 min, 5 min, 20 min).
    Volume records: longest run by distance, longest by duration, best weekly totals.

    Returns 200 with ``speedRecords``, ``powerRecords``, and ``volumeRecords`` keys.
    """
    try:
        if _uuid.UUID(athlete_id) != user.id:
            raise HTTPException(status_code=404, detail="Athlete not found")
    except ValueError:
        raise HTTPException(status_code=404, detail="Athlete not found")
    from backend.services.pr_detection import fetch_and_detect_records

    uid = user.id

    with Session(engine) as session:
        athlete = session.get(User, uid)
        if athlete is None:
            raise HTTPException(status_code=404, detail="Athlete not found")

        records = fetch_and_detect_records(uid, session)

    return JSONResponse(records)


def _trigger_curve_rebuild_background(user_id) -> None:
    """Fire-and-forget: rebuild the athlete's duration curve in a daemon thread.

    Used after threshold saves so the duration curve reflects the latest data
    without blocking the HTTP response.  Errors are logged but do not propagate.
    """
    _curve_log = _logging.getLogger(__name__)

    def _rebuild():
        try:
            from sqlalchemy.orm import Session as _Session
            with _Session(engine) as _db:
                _rebuild_athlete_duration_curve(user_id, _db)
        except Exception as _exc:
            _curve_log.warning(
                "background curve rebuild failed for user %s: %s",
                user_id, _exc, exc_info=True,
            )

    t = _threading.Thread(target=_rebuild, daemon=True)
    t.start()


# ── Athlete performance scores ────────────────────────────────────────────────

_performance_log = _logging.getLogger(__name__)


def _latest_race_perf(session, user_id, as_of=None) -> dict | None:
    """Race VDOT-band perf point for the score re-anchor (proposal §4.3).

    Latest finished race (status='done' AND actual_time_seconds NOT NULL, most
    recently updated). Returns ``{"perf": float, "date": "YYYY-MM-DD"}`` on the
    universal VDOT band, or None when there is no usable race. When ``as_of`` is
    given, only races on/before that date are considered (for the as-of helper).
    """
    from backend.services.vdot import vdot_from_pace_duration, rescale_to_score

    q = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "done",
            Race.actual_time_seconds.isnot(None),
            Race.distance_km.isnot(None),
        )
    )
    if as_of is not None:
        q = q.filter(Race.race_date <= as_of)
    race = q.order_by(Race.updated_at.desc()).first()
    if race is None:
        return None
    try:
        dist_km = float(race.distance_km)
        secs = int(race.actual_time_seconds)
    except (TypeError, ValueError):
        return None
    if dist_km <= 0 or secs <= 0:
        return None
    velocity_m_per_min = (dist_km * 1000.0) / (secs / 60.0)
    duration_min = secs / 60.0
    perf = rescale_to_score(vdot_from_pace_duration(velocity_m_per_min, duration_min))
    return {"perf": perf, "date": race.race_date.isoformat() if race.race_date else None}


def _check_needs_thresholds(preferences) -> bool:
    """Return True when none of the three threshold values are set in preferences.

    Checks ftp_w, threshold_hr, and threshold_pace_seconds_per_km. Returns True
    when preferences is None or all three keys are absent or None.
    """
    if preferences is None:
        return True
    return not any(
        preferences.get(k) is not None
        for k in ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km")
    )


def _determine_performance_top_level_state(endurance_result, speed_result) -> str:
    """Return the top-level state string from both score results (issue #1020).

    Returns 'building_baseline' if either score signals it; returns 'scored'
    when both carry a numeric score field.  Caller is responsible for the
    'needs_thresholds' early-return and the 'error' try/except wrapping.
    """
    endurance_state = endurance_result.get("state") if isinstance(endurance_result, dict) else None
    speed_state = speed_result.get("state") if isinstance(speed_result, dict) else None

    if endurance_state == "building_baseline" or speed_state == "building_baseline":
        return "building_baseline"

    endurance_score = endurance_result.get("score") if isinstance(endurance_result, dict) else None
    speed_score = speed_result.get("score") if isinstance(speed_result, dict) else None
    if isinstance(endurance_score, (int, float)) and isinstance(speed_score, (int, float)):
        return "scored"

    # Unexpected shape (e.g. score: None from missing input) — treat as building_baseline
    return "building_baseline"


def _build_performance_response(
    state: str,
    endurance,
    speed,
    generated_at: str,
    reason: str | None = None,
) -> dict:
    """Assemble the canonical top-level performance response dict (issue #1020).

    Always includes state, endurance, speed, and generated_at.  The optional
    reason field is only included for state='error'.
    """
    body: dict = {
        "state": state,
        "endurance": endurance,
        "speed": speed,
        "generated_at": generated_at,
    }
    if reason is not None:
        body["reason"] = reason
    return body


def _build_performance_log_entry(
    preferences,
    runs,
    endurance,
    speed,
):
    """Assemble a structured log dict for the performance endpoint.

    All field access is guarded — this function must never raise even when
    preferences is None, runs is empty, or score dicts are missing keys.
    """
    user_preferences_found = preferences is not None

    if preferences is not None:
        ftp_w_present = bool(preferences.get("ftp_w") is not None)
        threshold_hr_present = bool(preferences.get("threshold_hr") is not None)
        threshold_pace_present = bool(preferences.get("threshold_pace_seconds_per_km") is not None)
    else:
        ftp_w_present = None
        threshold_hr_present = None
        threshold_pace_present = None

    runs_assembled_count = len(runs) if runs else 0
    laps_with_band_count = 0
    total_laps_count = 0
    for run in (runs or []):
        laps = run.get("laps") or [] if isinstance(run, dict) else []
        total_laps_count += len(laps)
        laps_with_band_count += sum(1 for lap in laps if lap.get("band") is not None)

    def _score_shape(result):
        if not isinstance(result, dict):
            return "null"
        if result.get("state") == "needs_thresholds":
            return "needs_thresholds"
        if result.get("state") == "building_baseline":
            return "building_baseline"
        score = result.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            return "numeric"
        reason = result.get("reason") or ""
        if isinstance(reason, str) and reason.startswith("missing:"):
            return "missing-input"
        return "null"

    return {
        "event": "performance_score_computed",
        "user_preferences_found": user_preferences_found,
        "ftp_w_present": ftp_w_present,
        "threshold_hr_present": threshold_hr_present,
        "threshold_pace_seconds_per_km_present": threshold_pace_present,
        "runs_assembled_count": runs_assembled_count,
        "laps_with_band_count": laps_with_band_count,
        "total_laps_count": total_laps_count,
        "endurance_result_shape": _score_shape(endurance),
        "speed_result_shape": _score_shape(speed),
    }


def _build_performance_diagnostic(preferences, runs):
    """Return the 8 flat diagnostic keys required by issue #1018.

    Unconditionally safe — never raises even when preferences is None or runs is empty.
    Called at INFO level on every request to GET /api/athletes/{id}/performance so
    the values are always visible in UAT logs without requiring DEBUG log level.
    """
    _runs = runs or []

    runs_considered = len(_runs)
    runs_with_laps = sum(1 for r in _runs if r.get("laps"))
    laps_total = sum(len(r.get("laps") or []) for r in _runs)
    laps_with_band = sum(
        1 for r in _runs
        for lap in (r.get("laps") or [])
        if lap.get("band") is not None
    )

    if preferences is not None:
        thresholds_present = any(
            preferences.get(k) is not None
            for k in ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km")
        )
        ftp_present = preferences.get("ftp_w") is not None
        threshold_hr_present = preferences.get("threshold_hr") is not None
        threshold_pace_present = preferences.get("threshold_pace_seconds_per_km") is not None
    else:
        thresholds_present = False
        ftp_present = False
        threshold_hr_present = False
        threshold_pace_present = False

    return {
        "runs_considered": runs_considered,
        "runs_with_laps": runs_with_laps,
        "laps_total": laps_total,
        "laps_with_band": laps_with_band,
        "thresholds_present": thresholds_present,
        "ftp_present": ftp_present,
        "threshold_hr_present": threshold_hr_present,
        "threshold_pace_present": threshold_pace_present,
    }


@app.get("/api/athletes/{athlete_id}/performance")
def get_athlete_performance(athlete_id: str, user: User = Depends(resolve_user)):
    """Return endurance and speed performance scores for an athlete (issue #1020).

    Every response includes exactly these top-level keys: state, endurance, speed,
    generated_at.  The state field is always one of: scored, needs_thresholds,
    building_baseline, error.

    HTTP 200 for scored, needs_thresholds, and building_baseline.
    HTTP 500 for unexpected server-side failures (state='error').
    HTTP 404 when the athlete ID does not exist — body uses _build_performance_response
    so the canonical shape (including state key) is always present (issue #1027).
    """
    generated_at = _datetime.now(_timezone.utc).isoformat()

    try:
        if _uuid.UUID(athlete_id) != user.id:
            return JSONResponse(
                status_code=404,
                content=_build_performance_response(
                    state="error",
                    endurance=None,
                    speed=None,
                    generated_at=generated_at,
                    reason="athlete not found",
                ),
            )
    except ValueError:
        return JSONResponse(
            status_code=404,
            content=_build_performance_response(
                state="error",
                endurance=None,
                speed=None,
                generated_at=generated_at,
                reason="athlete not found",
            ),
        )
    from backend.services.running_performance import compute_endurance_score, compute_speed_score
    from backend.services.zone_constants import make_zone_constants
    from backend.services.lap_classify import classify_laps

    try:
        from backend.services.aerobic_decoupling import compute_decoupling
    except ImportError:
        compute_decoupling = None

    uid = user.id

    try:
        with Session(engine) as session:
            athlete = session.get(User, uid)
            if athlete is None:
                return JSONResponse(
                    status_code=404,
                    content=_build_performance_response(
                        state="error",
                        endurance=None,
                        speed=None,
                        generated_at=generated_at,
                        reason="athlete not found",
                    ),
                )

            # Load user preferences; None means preferences row absent
            prefs_row = (
                session.query(UserPreferences)
                .filter(UserPreferences.user_id == uid)
                .first()
            )
            if prefs_row is not None:
                preferences = {
                    "ftp_w": prefs_row.ftp_w,
                    "threshold_hr": prefs_row.threshold_hr,
                    "threshold_pace_seconds_per_km": prefs_row.threshold_pace_seconds_per_km,
                    # aerobic_decoupling_threshold added by migration d915ffcb4c0c
                    "aerobic_decoupling_threshold": getattr(prefs_row, "aerobic_decoupling_threshold", None),
                    "duration_curve_bests": None,
                }
            else:
                preferences = None

            # Load duration-curve bests so speed score can reference them
            curve_data = _get_athlete_duration_curve(uid, session)
            if preferences is not None:
                preferences["duration_curve_bests"] = curve_data or {}

            # Performance-score cache (issue: cacheable scores, same model as the
            # weekly/monthly summaries). Recompute only when a new workout is
            # synced (signature changes) or a threshold/preference input the
            # score depends on changes — not on every page load.
            _perf_sig = _performance_signature(session, uid, prefs_row)
            _perf_cached = _summary_cache_get(uid, "performance", _perf_sig)
            if _perf_cached is not None:
                _performance_log.info("performance cache hit for %s", uid)
                return JSONResponse(_perf_cached)

            # Load all run workouts in chronological order (oldest first)
            run_workouts = (
                session.query(Workout)
                .filter(Workout.user_id == uid, Workout.workout_type == "run")
                .order_by(Workout.workout_date.asc(), Workout.start_time.asc().nulls_last())
                .all()
            )

            prefs_dict = preferences or {}

            runs = []
            for workout in run_workouts:
                # Load per-lap splits ordered by split_index
                splits = (
                    session.query(WorkoutSplit)
                    .filter(WorkoutSplit.workout_id == workout.id)
                    .order_by(WorkoutSplit.split_index)
                    .all()
                )

                # Classify lap intensity bands using user thresholds
                classifications = classify_laps(splits, prefs_dict)

                # Build lap dicts with classification bands
                laps = []
                for split, cls in zip(splits, classifications):
                    laps.append({
                        "band": cls.get("band"),
                        "avg_power": split.avg_power,
                        "avg_hr": split.avg_hr,
                        "distance_km": float(split.distance_km) if split.distance_km is not None else None,
                        "duration_seconds": split.duration_seconds,
                    })

                # Compute aerobic decoupling for this run (back-half vs front-half
                # efficiency) using plain dicts so compute_decoupling stays pure
                decoupling_pct = None
                if compute_decoupling is not None:
                    split_dicts = [
                        {
                            "split_index": s.split_index,
                            "duration_seconds": s.duration_seconds,
                            "avg_hr": s.avg_hr,
                            "avg_power": s.avg_power,
                            "distance_km": float(s.distance_km) if s.distance_km is not None else None,
                        }
                        for s in splits
                    ]
                    decoupling_result, _ = compute_decoupling(
                        {"workout_type": workout.workout_type},
                        split_dicts,
                        prefs_dict.get("aerobic_decoupling_threshold"),
                    )
                    decoupling_pct = (
                        decoupling_result.get("decoupling_pct")
                        if decoupling_result
                        else None
                    )

                runs.append({
                    "run_id": str(workout.id),
                    "workout_date": workout.workout_date.isoformat() if workout.workout_date else "",
                    "laps": laps,
                    "decoupling_pct": decoupling_pct,
                    "avg_power": workout.avg_power,
                    "avg_hr": workout.avg_hr,
                    "distance_km": float(workout.distance_km) if workout.distance_km is not None else None,
                    "duration_seconds": workout.duration_seconds,
                    # Pre-computed speed signal (issue #1048): the best hard-effort
                    # intensity ratio + its basis/window, used by compute_speed_score
                    # to derive the effort pace when the reps aren't in the splits.
                    "speed_signal": workout.speed_signal,
                    "speed_signal_basis": workout.speed_signal_basis,
                    "speed_signal_window_seconds": workout.speed_signal_window_seconds,
                    "ftp_w": (prefs_dict or {}).get("ftp_w"),
                })

        # All DB access is finished above.  The pure functions below perform no I/O.

        # AC #1018: unconditional INFO-level diagnostic log — fires on every request so
        # UAT logs always contain the 8 flat keys needed to diagnose scoring failures.
        _performance_log.info(
            "performance diagnostic",
            extra=_build_performance_diagnostic(preferences=preferences, runs=runs),
        )

        # AC #912 / #1020: check for missing thresholds; return top-level state field.
        if _check_needs_thresholds(preferences):
            _needs_thresholds_obj = {
                "state": "needs_thresholds",
                "reason": _NEEDS_THRESHOLDS_REASON,
            }
            if _performance_log.isEnabledFor(_logging.DEBUG):
                log_entry = _build_performance_log_entry(
                    preferences=preferences,
                    runs=runs,
                    endurance=_needs_thresholds_obj,
                    speed=_needs_thresholds_obj,
                )
                _performance_log.debug("performance score request", extra=log_entry)
            return JSONResponse(
                _build_performance_response(
                    state="needs_thresholds",
                    endurance=None,
                    speed=None,
                    generated_at=generated_at,
                )
            )

        zone_constants = make_zone_constants()
        # Race VDOT-band perf point (pool point + decayed floor) — score re-anchor.
        with Session(engine) as _race_session:
            _race_perf = _latest_race_perf(_race_session, uid)
        from backend.services.body_modifier import get_body_modifier_for_user as _get_bm
        _bm = _get_bm(uid)
        endurance = compute_endurance_score(runs, preferences, zone_constants, race_perf=_race_perf, body_modifier=_bm)
        speed = compute_speed_score(runs, preferences, zone_constants, race_perf=_race_perf, body_modifier=_bm)

        if _performance_log.isEnabledFor(_logging.DEBUG):
            log_entry = _build_performance_log_entry(
                preferences=preferences,
                runs=runs,
                endurance=endurance,
                speed=speed,
            )
            _performance_log.debug("performance score request", extra=log_entry)

        # Endurance requires threshold_hr (HR extrapolation); surface its
        # needs_thresholds sub-state as the top-level state.
        if isinstance(endurance, dict) and endurance.get("state") == "needs_thresholds":
            return JSONResponse(
                _build_performance_response(
                    state="needs_thresholds",
                    endurance=None,
                    speed=None,
                    generated_at=generated_at,
                )
            )

        top_state = _determine_performance_top_level_state(endurance, speed)

        if top_state == "building_baseline":
            return JSONResponse(
                _build_performance_response(
                    state="building_baseline",
                    endurance=None,
                    speed=None,
                    generated_at=generated_at,
                )
            )

        _scored_payload = _build_performance_response(
            state="scored",
            endurance=endurance,
            speed=speed,
            generated_at=generated_at,
        )
        # Cache the computed scored payload; the signature invalidates it when a
        # sync inserts/updates workouts or a relevant threshold changes.
        _summary_cache_put(uid, "performance", _perf_sig, _scored_payload)
        _performance_log.info("performance cache miss (computed) for %s", uid)
        return JSONResponse(_scored_payload)

    except HTTPException:
        raise
    except Exception:
        _performance_log.exception("unexpected error in performance endpoint")
        return JSONResponse(
            status_code=500,
            content=_build_performance_response(
                state="error",
                endurance=None,
                speed=None,
                generated_at=generated_at,
                reason="unexpected server error",
            ),
        )


# ── Athlete weekly summary (issue #1055) ─────────────────────────────────────────


def _generate_weekly_note(
    session_count: int,
    distance_km,
    total_tss,
    form_tsb_change,
    workout_types: list,
) -> str:
    """Generate a short human-readable summary string for the week."""
    if session_count == 0:
        return ""

    parts = []

    type_counts: dict = {}
    for wt in workout_types:
        key = (wt or "").lower()
        type_counts[key] = type_counts.get(key, 0) + 1

    if type_counts.get("run", 0) > 0:
        run_count = type_counts["run"]
        parts.append(f"{run_count} run{'s' if run_count > 1 else ''}")

    if type_counts.get("strength", 0) > 0 or type_counts.get("lift", 0) > 0:
        parts.append("strength work")

    if distance_km and distance_km > 0:
        parts.append(f"{distance_km:.1f} km covered")

    if total_tss and total_tss > 0:
        parts.append(f"{total_tss:.0f} TSS")

    if isinstance(form_tsb_change, (int, float)):
        if form_tsb_change > 1:
            parts.append("form improving")
        elif form_tsb_change < -1:
            parts.append("building load")

    return ", ".join(parts) if parts else f"{session_count} session{'s' if session_count > 1 else ''} logged"


# In-process cache for the log-tab summaries: recompute only when new workouts
# arrive (a sync) or the period rolls over — otherwise reuse the last result
# (summary was recomputed every load). Signature-invalidation like the plan
# cache; in-memory (re-warms after a restart, which is fine — idempotent).
_SUMMARY_CACHE: dict = {}


def _summary_signature(session, user_id) -> str:
    row = (
        session.query(
            func.max(Workout.created_at),
            func.count(Workout.id),
            func.max(Workout.updated_at),
        )
        .filter(Workout.user_id == user_id)
        .one()
    )
    # Include MAX(updated_at) so an in-place edit (e.g. marking a run as an
    # interval) — which changes updated_at but not created_at/count — still
    # busts the cache and refreshes the derived scores/feeds.
    return "%s|%s|%s" % (row[0], row[1], row[2])


def _summary_cache_get(user_id, key, sig):
    """Two-level cache read: in-memory L1, then durable Neon L2.

    L1 (``_SUMMARY_CACHE``) is the fast per-process path. On an L1 miss (e.g. the
    first request after a restart wiped L1) fall back to the ``summary_cache``
    table: if a row exists whose stored signature matches, hydrate L1 and return
    it — no recompute. Any DB error degrades gracefully to a miss (recompute).
    """
    ent = _SUMMARY_CACHE.get((str(user_id), key))
    if ent and ent[0] == sig:
        return ent[1]

    # L2: durable Neon-backed cache. A restart clears L1 but not this table.
    try:
        with Session(engine) as _s:
            row = (
                _s.query(SummaryCache.signature, SummaryCache.payload)
                .filter(
                    SummaryCache.user_id == user_id,
                    SummaryCache.cache_key == key,
                )
                .first()
            )
        if row is not None and row[0] == sig:
            payload = row[1]
            _SUMMARY_CACHE[(str(user_id), key)] = (sig, payload)  # hydrate L1
            return payload
    except Exception:
        _performance_log.exception("summary_cache L2 read failed for %s/%s", user_id, key)
    return None


def _summary_cache_put(user_id, key, sig, payload):
    """Two-level cache write: set L1, then UPSERT the durable L2 row.

    A DB failure on the L2 write must not break the request — L1 still serves
    within the process; the durable row simply refreshes on the next compute.
    """
    _SUMMARY_CACHE[(str(user_id), key)] = (sig, payload)
    try:
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        stmt = _pg_insert(SummaryCache.__table__).values(
            user_id=user_id,
            cache_key=key,
            signature=sig,
            payload=payload,
            updated_at=_datetime.now(_timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "cache_key"],
            set_={
                "signature": stmt.excluded.signature,
                "payload": stmt.excluded.payload,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with Session(engine) as _s:
            _s.execute(stmt)
            _s.commit()
    except Exception:
        _performance_log.exception("summary_cache L2 write failed for %s/%s", user_id, key)


def _performance_signature(session, user_id, prefs_row) -> str:
    """Cache signature for the Endurance/Speed performance scores.

    Combines the workout-set signature (MAX(created_at) + count for the athlete —
    a sync that inserts/updates any workout bumps created_at) with the
    threshold/preference inputs the score compute depends on (FTP, threshold HR,
    threshold pace, aerobic-decoupling threshold). Any of these changing
    recomputes the scores; otherwise repeat loads reuse the cached payload.
    """
    # Bump this token whenever the score FORMULA changes so the durable Neon
    # summary_cache busts. v2 = VDOT re-anchor (was relative min/max + EWMA);
    # v3 = recreational band recalibration (15/58) + endurance HR-extrapolation
    # exponent; v4 = one-score-everywhere (*_current = today) + feed contributions.
    _FORMULA_VERSION = "vdot-v4"
    base = _summary_signature(session, user_id)
    if prefs_row is not None:
        prefs_part = "%s|%s|%s|%s" % (
            getattr(prefs_row, "ftp_w", None),
            getattr(prefs_row, "threshold_hr", None),
            getattr(prefs_row, "threshold_pace_seconds_per_km", None),
            getattr(prefs_row, "aerobic_decoupling_threshold", None),
        )
    else:
        prefs_part = "no-prefs"
    return base + "|" + prefs_part + "|" + _FORMULA_VERSION


@app.get("/api/athletes/{athlete_id}/summary/weekly")
def get_athlete_weekly_summary(
    athlete_id: str,
    user: User = Depends(resolve_user),
    week: Optional[str] = Query(default=None),
):
    """Return a flat weekly summary for an ISO week.

    Aggregates volume (distance_km, total_tss, session_count), fitness signal
    changes (endurance_score_change, speed_score_change), load form
    (form_tsb_change, readiness_next_week), and weight trend (weight_change_kg)
    into a single response keyed to a Monday–Sunday ISO week.

    Query params:
        week: optional YYYY-MM-DD date inside the target week (normalized to
              that week's Monday). Defaults to the current ISO week.

    Returns 200 for any valid authenticated athlete.  Returns zeros for
    numeric fields and null for weight when no data exists.  Returns 404
    when the session user does not exist in the database.
    """
    try:
        if _uuid.UUID(athlete_id) != user.id:
            raise HTTPException(status_code=404, detail="Athlete not found")
    except ValueError:
        raise HTTPException(status_code=404, detail="Athlete not found")

    from backend.services.running_performance import compute_endurance_score, compute_speed_score
    from backend.services.zone_constants import make_zone_constants
    from backend.services.lap_classify import classify_laps

    uid = user.id

    with Session(engine) as session:
        athlete = session.get(User, uid)
        if athlete is None:
            raise HTTPException(status_code=404, detail="Athlete not found")

        _bkk = ZoneInfo("Asia/Bangkok")
        today = _datetime.now(_bkk).date()
        if week is not None:
            try:
                ref = _date.fromisoformat(week)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"week must be in YYYY-MM-DD format, got {week!r}",
                )
            ws = ref - _timedelta(days=ref.weekday())   # Monday of that ISO week
        else:
            ws = today - _timedelta(days=today.weekday())   # Monday
        we = ws + _timedelta(days=6)                     # Sunday
        # Cap the load series end at today — daily_tss_series rejects future dates.
        load_end = min(we, today)

        _sig = _summary_signature(session, uid) + "|" + ws.isoformat()
        _cached = _summary_cache_get(uid, "weekly", _sig)
        if _cached is not None:
            return JSONResponse(_cached)

        # ── Weekly volume (AC8) ───────────────────────────────────────────────
        _volume = _get_weekly_volume(str(uid), ws, we)
        session_count = _volume["session_count"]
        distance_km = _volume["distance_km"]
        total_tss = _volume["total_tss"]
        workout_types = _volume["workout_types"]

        # ── TSB / load (AC5, AC9) ─────────────────────────────────────────────
        warmup_start = ws - _timedelta(days=180)
        load_series = compute_fitness_series(str(uid), warmup_start, load_end)

        def _tsb_at(target_date):
            for row in reversed(load_series):
                if row["date"] <= target_date:
                    return row["tsb"]
            return 0.0

        tsb_start = _tsb_at(ws)
        tsb_end = _tsb_at(load_end)
        form_tsb_change = round(tsb_end - tsb_start, 2)
        readiness_next_week = training_readiness_label(tsb_end) if load_series else None

        # ── Endurance / speed score change (AC4) ──────────────────────────────
        prefs_row = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == uid)
            .first()
        )
        if prefs_row is not None:
            preferences = {
                "ftp_w": prefs_row.ftp_w,
                "threshold_hr": prefs_row.threshold_hr,
                "threshold_pace_seconds_per_km": prefs_row.threshold_pace_seconds_per_km,
                "aerobic_decoupling_threshold": getattr(prefs_row, "aerobic_decoupling_threshold", None),
                "duration_curve_bests": None,
            }
        else:
            preferences = None

        run_workouts = (
            session.query(Workout)
            .filter(Workout.user_id == uid, Workout.workout_type == "run")
            .order_by(Workout.workout_date.asc(), Workout.start_time.asc().nulls_last())
            .all()
        )

        prefs_dict = preferences or {}
        zone_constants = make_zone_constants()

        try:
            compute_decoupling = _compute_decoupling
        except Exception:
            compute_decoupling = None

        def _build_run_list(max_date):
            runs = []
            for workout in run_workouts:
                if workout.workout_date > max_date:
                    continue
                splits = (
                    session.query(WorkoutSplit)
                    .filter(WorkoutSplit.workout_id == workout.id)
                    .order_by(WorkoutSplit.split_index)
                    .all()
                )
                classifications = classify_laps(splits, prefs_dict)
                laps = []
                for split, cls in zip(splits, classifications):
                    laps.append({
                        "band": cls.get("band"),
                        "avg_power": split.avg_power,
                        "avg_hr": split.avg_hr,
                        "distance_km": float(split.distance_km) if split.distance_km is not None else None,
                        "duration_seconds": split.duration_seconds,
                    })

                decoupling_pct = None
                if compute_decoupling is not None:
                    split_dicts = [
                        {
                            "split_index": s.split_index,
                            "duration_seconds": s.duration_seconds,
                            "avg_hr": s.avg_hr,
                            "avg_power": s.avg_power,
                            "distance_km": float(s.distance_km) if s.distance_km is not None else None,
                        }
                        for s in splits
                    ]
                    try:
                        decoupling_result, _ = compute_decoupling(
                            {"workout_type": workout.workout_type},
                            split_dicts,
                            prefs_dict.get("aerobic_decoupling_threshold"),
                        )
                        decoupling_pct = (
                            decoupling_result.get("decoupling_pct")
                            if decoupling_result
                            else None
                        )
                    except Exception:
                        decoupling_pct = None

                runs.append({
                    "run_id": str(workout.id),
                    "workout_date": workout.workout_date.isoformat() if workout.workout_date else "",
                    "laps": laps,
                    "decoupling_pct": decoupling_pct,
                    "avg_power": workout.avg_power,
                    "avg_hr": workout.avg_hr,
                    "distance_km": float(workout.distance_km) if workout.distance_km is not None else None,
                    "duration_seconds": workout.duration_seconds,
                    "speed_signal": workout.speed_signal,
                })
            return runs

        def _extract_score(result):
            if not isinstance(result, dict):
                return None
            score = result.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                return score
            return None

        from backend.services.body_modifier import get_body_modifier_for_user as _get_bm_weekly
        _bm_weekly = _get_bm_weekly(uid)

        runs_at_start = _build_run_list(ws)
        endurance_start = _extract_score(compute_endurance_score(runs_at_start, preferences, zone_constants, body_modifier=_bm_weekly))
        speed_start = _extract_score(compute_speed_score(runs_at_start, preferences, zone_constants, body_modifier=_bm_weekly))

        runs_at_end = _build_run_list(load_end)
        endurance_end = _extract_score(compute_endurance_score(runs_at_end, preferences, zone_constants, body_modifier=_bm_weekly))
        speed_end = _extract_score(compute_speed_score(runs_at_end, preferences, zone_constants, body_modifier=_bm_weekly))

        if endurance_start is not None and endurance_end is not None:
            endurance_score_change = round(endurance_end - endurance_start, 2)
        else:
            endurance_score_change = 0.0

        if speed_start is not None and speed_end is not None:
            speed_score_change = round(speed_end - speed_start, 2)
        else:
            speed_score_change = 0.0

        # ── Weight change (AC6) ────────────────────────────────────────────────
        weight_entries = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date >= ws,
                WeightEntry.entry_date <= we,
            )
            .order_by(WeightEntry.entry_date.asc())
            .all()
        )

        if len(weight_entries) >= 2:
            earliest_kg = float(weight_entries[0].weight_kg)
            latest_kg = float(weight_entries[-1].weight_kg)
            weight_change_kg = round(latest_kg - earliest_kg, 2)
        else:
            weight_change_kg = None

    note = _generate_weekly_note(
        session_count=session_count,
        distance_km=distance_km,
        total_tss=total_tss,
        form_tsb_change=form_tsb_change,
        workout_types=workout_types,
    )

    guardrail = get_guardrail_result(uid)

    _payload = {
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "distance_km": distance_km,
        "total_tss": total_tss,
        "session_count": session_count,
        "endurance_score_change": endurance_score_change,
        "speed_score_change": speed_score_change,
        "weight_change_kg": weight_change_kg,
        "form_tsb_change": form_tsb_change,
        "note": note,
        "readiness_next_week": readiness_next_week,
        "guardrail_state": guardrail["guardrail_state"],
        "guardrail_message": guardrail["guardrail_message"],
    }
    _summary_cache_put(uid, "weekly", _sig, _payload)
    return JSONResponse(_payload)


# ── Athlete run personal records ───────────────────────────────────────────────

_run_pr_log = _logging.getLogger(__name__)


_SPEED_DISTANCE_LABELS = ("1km", "1mile", "5km", "10km", "half_marathon", "marathon")
_POWER_DURATION_LABELS = ("best1Min", "best5Min", "best20Min")
_VOLUME_LABELS = ("longestByDistance", "longestByDuration", "weeklyDistanceRecord", "weeklyLoadRecord")

_VOLUME_MISSING_REASONS = {
    "longestByDistance":    "insufficient data: no GPS distance measurements found in run history",
    "longestByDuration":    "insufficient data: no run duration measurements found in run history",
    "weeklyDistanceRecord": "insufficient data: no GPS distance measurements found in run history",
    "weeklyLoadRecord":     "insufficient data: no training load (TSS) values found in run history",
}


def _enrich_run_pr_reasons(raw: dict) -> None:
    """Add explicit per-slot reason strings for uncomputable record categories.

    Mutates ``raw`` in-place.  When pr_detection returns a top-level reason-only
    dict for speedRecords or powerRecords the individual expected slots are absent;
    this function populates each missing slot with a reason string that identifies
    the specific missing data type (power measurements vs. GPS pace data).  For
    volumeRecords, sub-category keys that are simply absent from the output dict
    receive per-key reasons distinguishing distance data from TSS data.

    Computed slots (those that already carry ``value``, ``date``, and
    ``sourceWorkout``) are never modified.
    """
    speed = raw.get("speedRecords")
    if isinstance(speed, dict):
        top_level_failure = "reason" in speed and not any(k in speed for k in _SPEED_DISTANCE_LABELS)
        if top_level_failure:
            for label in _SPEED_DISTANCE_LABELS:
                if label not in speed:
                    speed[label] = {"reason": "insufficient data: no GPS pace data available for this athlete"}

    power = raw.get("powerRecords")
    if isinstance(power, dict):
        top_level_failure = "reason" in power and not any(k in power for k in _POWER_DURATION_LABELS)
        if top_level_failure:
            for label in _POWER_DURATION_LABELS:
                if label not in power:
                    power[label] = {"reason": "insufficient data: no power measurements found for this athlete"}

    volume = raw.get("volumeRecords")
    if isinstance(volume, dict):
        top_level_failure = "reason" in volume and not any(k in volume for k in _VOLUME_LABELS)
        if top_level_failure:
            for label in _VOLUME_LABELS:
                if label not in volume:
                    volume[label] = {"reason": "insufficient data: no completed runs found"}
        else:
            for label, reason in _VOLUME_MISSING_REASONS.items():
                if label not in volume:
                    volume[label] = {"reason": reason}


def _build_run_pr_log_entry(meta, records):
    """Assemble a structured log dict for the run personal records endpoint.

    All field access is guarded — never raises even when meta or records is None
    or malformed.
    """
    duration_curve_populated = bool((meta or {}).get("duration_curve_populated", False))
    runs_considered = int((meta or {}).get("runs_considered", 0))

    def _count_detected(result_dict):
        if not isinstance(result_dict, dict):
            return 0
        if "reason" in result_dict and len(result_dict) == 1:
            return 0
        return sum(
            1
            for k, v in result_dict.items()
            if k not in ("debug", "reason")
            and isinstance(v, dict)
            and "value" in v
        )

    rec = records or {}
    speed_count = _count_detected(rec.get("speedRecords", {}))
    power_count = _count_detected(rec.get("powerRecords", {}))
    volume_count = _count_detected(rec.get("volumeRecords", {}))

    return {
        "event": "run_pr_detected",
        "duration_curve_populated": duration_curve_populated,
        "runs_considered": runs_considered,
        "records_returned": speed_count + power_count + volume_count,
        "speed_records_count": speed_count,
        "power_records_count": power_count,
        "volume_records_count": volume_count,
    }


def _build_run_pr_pre_detection_log_entry(duration_curve_populated, runs_considered):
    """Assemble the pre-detection structured log dict for the run personal records endpoint.

    Called before fetch_and_detect_records so the inputs are observable even when
    detection raises.  All field access is guarded — never raises.
    """
    return {
        "event": "pr_detection_input",
        "duration_curve_populated": bool(duration_curve_populated) if duration_curve_populated is not None else False,
        "runs_considered": int(runs_considered) if runs_considered is not None else 0,
    }


@app.get("/api/athletes/{athlete_id}/run-personal-records")
def get_athlete_run_personal_records(athlete_id: str, user: User = Depends(resolve_user)):
    """Return auto-detected personal records from the athlete's run history.

    Reads completed run workouts and the stored best-effort duration curve,
    then delegates detection to the three pure functions in
    ``backend.services.pr_detection``.  Each record dict contains ``value``,
    ``date``, and ``sourceWorkout``; missing records carry a ``reason`` string
    so the client can display an honest message rather than a blank.

    Returns 200 with keys ``speedRecords``, ``powerRecords``, ``volumeRecords``.
    """
    try:
        if _uuid.UUID(athlete_id) != user.id:
            raise HTTPException(status_code=404, detail="Athlete not found")
    except ValueError:
        raise HTTPException(status_code=404, detail="Athlete not found")
    from backend.services.pr_detection import fetch_and_detect_records
    from backend.models import AthleteDurationCurve as _AthleteDurationCurve

    uid = user.id

    with Session(engine) as session:
        run_count = (
            session.query(Workout)
            .filter(Workout.user_id == uid, Workout.workout_type.ilike("%run%"))
            .count()
        )
        curve_populated = session.get(_AthleteDurationCurve, uid) is not None

        # If no curve row exists yet the athlete has runs, build it now so that
        # fetch_and_detect_records can read it.  This is a one-time cost: once the
        # row exists (even with empty curve_data for non-power athletes) we skip it.
        # Thresholds are driven by _DEFAULT_DURATION_LADDER from duration_curve.py
        # via fetch_and_compute_curves — no values are hardcoded here.
        if not curve_populated:
            _rebuild_athlete_duration_curve(uid, session)
            curve_populated = session.get(_AthleteDurationCurve, uid) is not None

        _run_pr_log.info(
            "pr_detection_input",
            extra=_build_run_pr_pre_detection_log_entry(curve_populated, run_count),
        )

        raw = fetch_and_detect_records(uid, session)

    raw.pop("_meta", {})
    _enrich_run_pr_reasons(raw)
    _run_pr_log.info(
        "pr_detection_output",
        extra={"event": "pr_detection_output", "raw_output": raw},
    )

    return JSONResponse(raw)


# ── Plan computed cache (collapses ~10 Plan-tab calls into 1) ─────────────────

def _plan_signature(session, user_id, plan) -> str:
    """Cheap fingerprint of everything the Plan bundle depends on.

    Hash of: MAX(workouts.updated_at), MAX(workouts.created_at)+COUNT,
    MAX(races.updated_at), MAX(race_checkpoints.updated_at),
    user_preferences.threshold_pace_seconds_per_km_updated_at (falls back to the
    prefs row's own updated_at), and the plan's updated_at. New training sync
    bumps workouts (created_at+count); editing an existing workout's fields
    bumps workouts.updated_at; target/race edits bump races; checkpoint edits
    bump race_checkpoints; ramp/taper edits bump the plan — so any of those
    changes the signature and forces a recompute.
    """

    # MAX(created_at)+COUNT catches new synced rows; MAX(updated_at) catches
    # in-place edits to an existing workout (e.g. PATCH /api/workouts/{id}),
    # which created_at+count alone would miss. Single SELECT with scalar
    # subqueries instead of round trips per signal.
    row = session.query(
        session.query(func.max(Workout.created_at))
        .filter(Workout.user_id == user_id)
        .scalar_subquery()
        .label("max_wo"),
        session.query(func.count(Workout.id))
        .filter(Workout.user_id == user_id)
        .scalar_subquery()
        .label("wo_count"),
        session.query(func.max(Workout.updated_at))
        .filter(Workout.user_id == user_id)
        .scalar_subquery()
        .label("max_wo_updated"),
        session.query(func.max(Race.updated_at))
        .filter(Race.user_id == user_id)
        .scalar_subquery()
        .label("max_race"),
        session.query(func.max(Race.created_at))
        .filter(Race.user_id == user_id)
        .scalar_subquery()
        .label("max_race_created"),
        session.query(func.max(RaceCheckpoint.updated_at))
        .filter(RaceCheckpoint.user_id == user_id)
        .scalar_subquery()
        .label("max_checkpoint_updated"),
        session.query(UserPreferences.threshold_pace_seconds_per_km_updated_at)
        .filter(UserPreferences.user_id == user_id)
        .scalar_subquery()
        .label("prefs_pace_stamp"),
        session.query(UserPreferences.updated_at)
        .filter(UserPreferences.user_id == user_id)
        .scalar_subquery()
        .label("prefs_updated_at"),
    ).one()
    (
        max_wo, wo_count, max_wo_updated,
        max_race, max_race_created, max_checkpoint_updated,
        prefs_pace_stamp, prefs_updated_at,
    ) = row
    prefs_stamp = prefs_pace_stamp or prefs_updated_at
    # Bundle-shape version: bump when the cached bundle gains/changes a key so
    # existing computed_cache rows (old shape) invalidate on deploy instead of
    # being served stale. bundle-v2 = folded in the primary race's `readiness`.
    _BUNDLE_VERSION = "bundle-v2"
    parts = [
        _BUNDLE_VERSION,
        str(max_wo), str(wo_count), str(max_wo_updated),
        str(max_race), str(max_race_created), str(max_checkpoint_updated),
        str(prefs_stamp),
        str(getattr(plan, "updated_at", None)),
    ]
    return _hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# NOTE: required-/demonstrated-score distance weighting below is a FIRST-PASS
# tunable heuristic (reference 21.1 km; required-gap split slope 0.18). The
# demonstrated (completed) score is the athlete-scale score AS OF the race date
# (matches the log) — no pace inversion. Operator may recalibrate later.
def _plan_race_scores(session, user_id, race, race_dict, readiness, current_scores, tp):
    """Per-race End/Spd for the bundle.

    Completed race → demonstrated athlete score as of the race date.
    Upcoming race  → required End/Spd for its goal + delta from current, using
                     the readiness estimate. None when inputs are missing.
    """
    import math as _math

    status = race_dict.get("status")
    dist = race_dict.get("distance")
    if status == "done" and race_dict.get("actual_time_seconds") is not None:
        s = _athlete_scores_as_of(session, user_id, race.race_date)
        if s.get("endurance") is None and s.get("speed") is None:
            return None
        return {
            "kind": "demonstrated",
            "end": round(s["endurance"]) if s.get("endurance") is not None else None,
            "spd": round(s["speed"]) if s.get("speed") is not None else None,
        }

    # Upcoming: required scores need goal, distance, estimate, current, tp.
    goal = race_dict.get("goal_time_seconds")
    cE = current_scores.get("endurance")
    cS = current_scores.get("speed")
    if (
        not goal or not dist or dist <= 0 or not tp or tp <= 0
        or not isinstance(cE, (int, float)) or not isinstance(cS, (int, float))
    ):
        return None
    est = None
    if readiness and readiness.get("time_curve"):
        proj = readiness["time_curve"].get("projection") or []
        hist = readiness["time_curve"].get("history") or []
        if proj:
            est = proj[0].get("estimated_finish_seconds")
        elif hist:
            est = hist[-1].get("estimated_finish_seconds")
    if est is None:
        return None

    goal_pace = goal / dist
    est_pace = est / dist
    gap = (est_pace - goal_pace) / tp * 100.0
    le = _math.log(dist / 21.1)
    speed_weight = max(0.15, min(0.85, 0.5 - 0.18 * le))
    end_weight = 1 - speed_weight
    d_end = round(gap * end_weight)
    d_spd = round(gap * speed_weight)
    req_end = max(0, min(100, round(cE + d_end)))
    req_spd = max(0, min(100, round(cS + d_spd)))
    return {
        "kind": "required",
        "end": req_end, "spd": req_spd,
        "d_end": d_end, "d_spd": d_spd,
    }


def _compute_plan_bundle(user) -> dict:
    """Compute the full Plan-tab bundle by calling the existing endpoints
    in-process (no HTTP) and decoding their JSON, then attaching per-race
    computed scores/estimates. Reused by GET /api/plan/computed and
    POST /api/plan/recompute."""
    from backend.services.projection_service import race_to_dict as _race_to_dict

    def _decode(resp):
        try:
            return _json.loads(resp.body)
        except Exception:
            return None

    # Current athlete scores.
    try:
        perf = _decode(get_athlete_performance(str(user.id), user=user)) or {}
    except HTTPException:
        perf = {}
    p_state = perf.get("state")
    cur_end = (perf.get("endurance") or {}).get("score") if p_state == "scored" else None
    cur_spd = (perf.get("speed") or {}).get("score") if p_state == "scored" else None
    current_scores = {
        "endurance": cur_end,
        "speed": cur_spd,
        "endurance_dir": (perf.get("endurance") or {}).get("direction"),
        "speed_dir": (perf.get("speed") or {}).get("direction"),
        "state": p_state,
    }

    # Calibration.
    try:
        calibration = _decode(get_calibration_status(user=user)) or {}
    except HTTPException:
        calibration = {}

    # Projection (form curve, markers, projected-now for the primary race).
    try:
        projection = _decode(get_projection(user=user)) or {}
    except HTTPException:
        projection = {}

    with Session(engine) as session:
        prefs_row = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == user.id)
            .first()
        )
        tp = prefs_row.threshold_pace_seconds_per_km if prefs_row else None

        races = (
            session.query(Race)
            .filter(Race.user_id == user.id)
            .order_by(Race.race_date)
            .all()
        )
        today = _date.today()

        # Shared per-user 180-day TSS/EWMA series: every upcoming race's
        # get_race_readiness() call would otherwise recompute this identically.
        _warmup_start = today - _timedelta(days=180)
        _shared_tss_series = daily_tss_series(str(user.id), _warmup_start, today)
        _shared_ctl_days, _shared_atl_days = resolve_user_ewma_days(str(user.id))
        _shared_load_curves = compute_load_curves(
            _shared_tss_series, ctl_days=_shared_ctl_days, atl_days=_shared_atl_days
        )
        # Primary A race drives the time-curve chart; capture its readiness
        # time_curve for the frontend "Projected now" readout + chart.
        primary_race = next(
            (r for r in races if r.race_type == "race" and r.priority == "A"),
            next((r for r in races if r.race_type == "race"), None),
        )
        primary_time_curve = None
        # Full readiness of the primary race, captured from the same
        # _race_readiness_impl call the estimate loop already makes (reused, not
        # recomputed) and folded into the bundle under "readiness" so the
        # Projection tab renders time/form curves + on-track + specificity from
        # ONE cached call instead of a separate ~1.5s /api/races/{id}/readiness.
        primary_readiness = None
        primary_race_id = str(primary_race.id) if primary_race else None
        race_out = []
        for race in races:
            rd = _race_to_dict(race)
            is_done = rd.get("status") == "done" and rd.get("actual_time_seconds") is not None
            readiness = None
            estimate = None
            if not is_done and str(race.race_date) >= str(today):
                try:
                    readiness = _decode(
                        _race_readiness_impl(
                            str(race.id),
                            user,
                            _shared_load_curves=(_shared_tss_series, _shared_load_curves),
                            _shared_threshold_pace=tp,
                        )
                    )
                except HTTPException:
                    readiness = None
                if (
                    primary_race is not None
                    and race.id == primary_race.id
                    and readiness
                ):
                    primary_time_curve = readiness.get("time_curve")
                    primary_readiness = readiness
                if readiness and readiness.get("time_curve"):
                    proj = readiness["time_curve"].get("projection") or []
                    hist = readiness["time_curve"].get("history") or []
                    e = None
                    band = None
                    if proj:
                        e = proj[0].get("estimated_finish_seconds")
                        band = proj[0].get("confidence_band_seconds")
                    elif hist:
                        e = hist[-1].get("estimated_finish_seconds")
                    if e is not None:
                        estimate = {"est": e, "band": band}
            scores = _plan_race_scores(
                session, user.id, race, rd, readiness, current_scores, tp
            )
            rd["computed"] = {"estimate": estimate, "scores": scores}
            race_out.append(rd)

    return {
        "generated_at": _datetime.now(_timezone.utc).isoformat(),
        "current_scores": current_scores,
        "prefs": {"threshold_pace": tp},
        "calibration": {
            "last_calibration_date": calibration.get("last_calibration_date"),
            "data_sufficiency": calibration.get("data_sufficiency"),
            "band_confidence": calibration.get("band_confidence"),
            "calibrated": calibration.get("calibrated"),
        },
        "projection": {
            "form_curve": projection.get("form_curve"),
            "projected_form": projection.get("projected_form"),
            "race_markers": projection.get("race_markers"),
            "b_race_recalibration_date": projection.get("b_race_recalibration_date"),
            "building_baseline": projection.get("building_baseline"),
            "primary_race_id": primary_race_id,
            "time_curve": primary_time_curve,
        },
        # Full primary-race readiness (time_curve, form_curve, on_track,
        # specificity_progress, building_baseline, projected_form) so the
        # Projection tab renders everything from this one cached bundle. Null
        # when there is no upcoming primary race.
        "readiness": primary_readiness,
        "races": race_out,
    }


def _resolve_or_create_plan(session, user_id):
    """Return the user's TrainingPlan, creating a default one if none exists."""
    plan = (
        session.query(TrainingPlan)
        .filter(TrainingPlan.user_id == user_id)
        .order_by(TrainingPlan.created_at.asc())
        .first()
    )
    if plan is None:
        plan = TrainingPlan(user_id=user_id, name="Training Plan")
        session.add(plan)
        session.commit()
        session.refresh(plan)
    return plan


@app.get("/api/plan/computed")
def get_plan_computed(user: User = Depends(resolve_user)):
    """Single Plan-tab data call, backed by a plan-level cache.

    Returns the cached bundle when the data signature is unchanged
    (``cached: true``); otherwise recomputes, stores cache+signature, and
    returns it (``cached: false``).
    """
    with Session(engine) as session:
        plan = _resolve_or_create_plan(session, user.id)
        sig = _plan_signature(session, user.id, plan)
        if plan.computed_signature == sig and plan.computed_cache:
            bundle = dict(plan.computed_cache)
            bundle["cached"] = True
            return JSONResponse(bundle)

    bundle = _compute_plan_bundle(user)
    with Session(engine) as session:
        plan = _resolve_or_create_plan(session, user.id)
        plan.computed_cache = bundle
        plan.computed_signature = _plan_signature(session, user.id, plan)
        session.commit()
    out = dict(bundle)
    out["cached"] = False
    return JSONResponse(out)


@app.post("/api/plan/recompute")
def post_plan_recompute(user: User = Depends(resolve_user)):
    """Force a fresh Plan-tab bundle compute, store it, and return it."""
    bundle = _compute_plan_bundle(user)
    with Session(engine) as session:
        plan = _resolve_or_create_plan(session, user.id)
        plan.computed_cache = bundle
        plan.computed_signature = _plan_signature(session, user.id, plan)
        session.commit()
    out = dict(bundle)
    out["cached"] = False
    return JSONResponse(out)


# ── Projection screen endpoint ────────────────────────────────────────────────

@app.get("/api/projection")
def get_projection(user: User = Depends(resolve_user)):
    """Return aggregated projection data for the projection screen (issue #1114).

    Combines:
    - Form curve (historical TSB) and projected form toward the A-race
    - Race markers for A, B, and C priority races, with recalibrates_here
      flag on the earliest upcoming B-race
    - Endurance and Speed scores from the running performance module

    Returns:
        200 with projection dict.
        401 for unauthenticated requests (via resolve_user).
    """
    from backend.services.running_performance import compute_endurance_score, compute_speed_score
    from backend.services.zone_constants import make_zone_constants
    from backend.services.lap_classify import classify_laps

    today = _date.today()
    warmup_start = today - _timedelta(days=180)

    with Session(engine) as db:
        # Load all user races, sorted by date
        races = (
            db.query(Race)
            .filter(Race.user_id == user.id, Race.race_type == "race")
            .order_by(Race.race_date)
            .all()
        )

        # Build race markers for A, B, C priority races
        race_markers = []
        a_race = None
        b_race_recalibration_date = None

        for race in races:
            marker = {
                "id": str(race.id),
                "date": str(race.race_date),
                "priority": race.priority,
                "name": race.name,
                "distance_km": float(race.distance_km),
                "recalibrates_here": False,
            }
            race_markers.append(marker)

            if race.priority == "A" and a_race is None:
                a_race = race
            # The earliest upcoming B-race is the recalibration anchor
            if (race.priority == "B" and b_race_recalibration_date is None
                    and race.race_date >= today):
                b_race_recalibration_date = str(race.race_date)
                marker["recalibrates_here"] = True

        # Compute form curve from training load history
        tss_series = daily_tss_series(str(user.id), warmup_start, today)
        _ctl_days, _atl_days = resolve_user_ewma_days(str(user.id))
        load_curves = compute_load_curves(tss_series, ctl_days=_ctl_days, atl_days=_atl_days)

        buried_ceiling = _rdns_cfg_float(_RDNS_CFG_BURIED_CEILING, FORM_BURIED_CEILING)
        fresh_floor = _rdns_cfg_float(_RDNS_CFG_FRESH_FLOOR, FORM_FRESH_FLOOR)
        min_history_weeks = _rdns_cfg_int(_RDNS_CFG_MIN_HISTORY_WEEKS, 8)

        form_curve = [
            {
                "date": row["date"].isoformat(),
                "form": row["tsb"],
                "zone": _rdns_classify_zone(row["tsb"], buried_ceiling, fresh_floor),
            }
            for row in load_curves
        ]

        # Determine building_baseline
        history_window_start = today - _timedelta(days=min_history_weeks * 7)
        workout_days_in_window = sum(
            1 for d, tss in tss_series
            if tss > 0 and d >= history_window_start
        )
        required_workout_days = min_history_weeks * _RDNS_MIN_WORKOUT_DAYS_PER_WEEK
        building_baseline = workout_days_in_window < required_workout_days

        # Projected form toward A-race
        projected_form = None
        if not building_baseline and a_race is not None:
            last_row = load_curves[-1]
            fitness_state = {
                "ctl": last_row["ctl"],
                "atl": last_row["atl"],
                "date": last_row["date"],
            }
            proj = project_form(fitness_state, 0.0, a_race.race_date)
            if not proj["reason"]:
                projected_form = {
                    day["date"].isoformat(): day["form"]
                    for day in proj["days"]
                }

        # Load endurance and speed scores
        endurance_score = None
        speed_score = None
        score_state = "building_baseline"

        try:
            prefs_row = (
                db.query(UserPreferences)
                .filter(UserPreferences.user_id == user.id)
                .first()
            )
            if prefs_row is None:
                score_state = "needs_thresholds"
            else:
                preferences = {
                    "ftp_w": prefs_row.ftp_w,
                    "threshold_hr": prefs_row.threshold_hr,
                    "threshold_pace_seconds_per_km": prefs_row.threshold_pace_seconds_per_km,
                    "aerobic_decoupling_threshold": getattr(prefs_row, "aerobic_decoupling_threshold", None),
                    "duration_curve_bests": None,
                }
                if _check_needs_thresholds(preferences):
                    score_state = "needs_thresholds"
                else:
                    curve_data = _get_athlete_duration_curve(user.id, db)
                    preferences["duration_curve_bests"] = curve_data or {}

                    zone_constants = make_zone_constants(preferences)

                    run_workouts = (
                        db.query(Workout)
                        .filter(Workout.user_id == user.id, Workout.workout_type == "run")
                        .order_by(Workout.workout_date.asc(), Workout.start_time.asc().nulls_last())
                        .all()
                    )

                    runs = []
                    for workout in run_workouts:
                        splits = (
                            db.query(WorkoutSplit)
                            .filter(WorkoutSplit.workout_id == workout.id)
                            .order_by(WorkoutSplit.split_index)
                            .all()
                        )
                        classifications = classify_laps(splits, preferences)
                        laps = []
                        for split, cls in zip(splits, classifications):
                            laps.append({
                                "band": cls.get("band"),
                                "avg_power": split.avg_power,
                                "avg_hr": split.avg_hr,
                                "duration_seconds": split.duration_seconds,
                                "distance_km": split.distance_km,
                                "avg_pace_seconds_per_km": split.avg_pace_seconds_per_km,
                            })
                        runs.append({
                            "workout_date": str(workout.workout_date),
                            "distance_km": float(workout.distance_km) if workout.distance_km else None,
                            "duration_seconds": workout.duration_seconds,
                            "avg_hr": workout.avg_hr,
                            "laps": laps,
                        })

                    from backend.services.body_modifier import get_body_modifier_for_user as _get_bm_proj
                    _bm_proj = _get_bm_proj(user.id)
                    endurance_result = compute_endurance_score(runs, preferences, zone_constants, body_modifier=_bm_proj)
                    speed_result = compute_speed_score(runs, preferences, zone_constants, body_modifier=_bm_proj)

                    if isinstance(endurance_result, dict):
                        endurance_score = endurance_result.get("score")
                    if isinstance(speed_result, dict):
                        speed_score = speed_result.get("score")

                    score_state = _determine_performance_top_level_state(
                        endurance_result, speed_result
                    )
        except Exception:
            score_state = "error"

        # ── Economy contribution (issue #1150) ────────────────────────────────
        # Query strength and plyo sessions within the lag window and compute the
        # lagged economy ceiling bonus so we can surface it in the UI.
        economy_contribution = 0.0
        try:
            lag_start = today - _timedelta(days=_LAG_WINDOW_DAYS)
            strength_rows = (
                db.query(StrengthSession)
                .filter(
                    StrengthSession.user_id == user.id,
                    StrengthSession.session_date >= lag_start,
                    StrengthSession.session_date <= today,
                )
                .all()
            )
            plyo_rows = (
                db.query(PlyoSession)
                .filter(
                    PlyoSession.user_id == user.id,
                    PlyoSession.session_date >= lag_start,
                    PlyoSession.session_date <= today,
                )
                .all()
            )

            # Aggregate load and contacts per day
            from collections import defaultdict as _defaultdict
            day_strength: dict = _defaultdict(float)
            day_plyo: dict = _defaultdict(float)

            for s in strength_rows:
                sets = s.sets or 0
                reps = s.reps or 0
                load = float(s.load or 0)
                load_unit = s.load_unit or "kg"
                load_kg = load * 0.453592 if load_unit == "lbs" else load
                if sets > 0 and reps > 0 and load_kg > 0:
                    day_strength[s.session_date] += sets * reps * load_kg
                elif (s.session_rpe or 0) > 0 and (s.duration_minutes or 0) > 0:
                    # RPE-based fallback: scale to same order as volume-load
                    day_strength[s.session_date] += (s.session_rpe or 0) * (s.duration_minutes or 0) * 10.0

            for p in plyo_rows:
                day_plyo[p.session_date] += float(p.foot_contacts)

            # Current CTL as fitness proxy; default 50 if no history yet
            current_ctl = load_curves[-1]["ctl"] if load_curves else 50.0
            default_speed_kmh = 10.0  # representative easy-run speed for weighting

            all_session_dates = set(day_strength.keys()) | set(day_plyo.keys())
            stimulus_history = []
            for d in sorted(all_session_dates):
                sl = day_strength.get(d, 0.0)
                pc = day_plyo.get(d, 0.0)
                stim = _compute_economy_stimulus(sl, pc, default_speed_kmh, current_ctl)
                if stim > 0.0:
                    stimulus_history.append((d, stim))

            economy_contribution = round(_compute_ceiling_bonus(stimulus_history, today), 2)
        except Exception:
            economy_contribution = 0.0

    return JSONResponse({
        "building_baseline": building_baseline,
        "form_curve": form_curve,
        "projected_form": projected_form,
        "race_markers": race_markers,
        "b_race_recalibration_date": b_race_recalibration_date,
        "endurance_score": endurance_score,
        "speed_score": speed_score,
        "score_state": score_state,
        "economy_contribution": economy_contribution,
        "lag_peak_days": _LAG_PEAK_DAYS,
        "lag_window_days": _LAG_WINDOW_DAYS,
    })


# ── Monthly summary with supercompensation detection (issue #1056) ────────────

_MONTHLY_SUMMARY_SAFE_LEAN_DOWN_KEY = "monthly_summary.safe_lean_down_pct_per_week"
_MONTHLY_SUMMARY_FORM_RECOVERY_THRESHOLD = 0.0
_MONTHLY_SUMMARY_SCORE_DELTA_THRESHOLD = 0.05


def _monthly_score_delta(workouts: list) -> tuple:
    """Compute endurance and speed score changes from per-workout signals.

    Compares the average signal from the first half of the workout list
    against the second half.  Returns (endurance_change, speed_change) as
    floats, or (None, None) when insufficient data.
    """
    signals_with_data = [
        (w.endurance_signal, w.speed_signal)
        for w in workouts
        if w.endurance_signal is not None or w.speed_signal is not None
    ]
    if len(signals_with_data) < 2:
        return None, None

    mid = len(signals_with_data) // 2
    first_half = signals_with_data[:mid]
    second_half = signals_with_data[mid:]

    def _avg(items, idx):
        vals = [x[idx] for x in items if x[idx] is not None]
        return sum(vals) / len(vals) if vals else None

    e_start = _avg(first_half, 0)
    e_end = _avg(second_half, 0)
    s_start = _avg(first_half, 1)
    s_end = _avg(second_half, 1)

    e_delta = round(e_end - e_start, 3) if (e_start is not None and e_end is not None) else None
    s_delta = round(s_end - s_start, 3) if (s_start is not None and s_end is not None) else None
    return e_delta, s_delta


def _compute_supercompensation_state(
    endurance_delta,
    speed_delta,
    form_recovered: bool,
    threshold: float = _MONTHLY_SUMMARY_SCORE_DELTA_THRESHOLD,
) -> str:
    """Classify the athlete's adaptive state for the month.

    Logic:
    - "working"  — at least one score rose (> threshold) AND form recovered
    - "digging"  — scores flat or down AND form NOT recovered
    - "flat"     — everything else (scores flat with form recovered, or mixed)
    """
    scores_rose = (
        (endurance_delta is not None and endurance_delta > threshold)
        or (speed_delta is not None and speed_delta > threshold)
    )
    if scores_rose and form_recovered:
        return "working"
    if not form_recovered:
        return "digging"
    return "flat"


def _compute_call_to_action(
    supercompensation_state: str,
    weight_rate_pct_per_week,
    safe_lean_down_rate: float,
) -> str:
    """Return a single short imperative call-to-action string."""
    if (
        weight_rate_pct_per_week is not None
        and abs(weight_rate_pct_per_week) > safe_lean_down_rate
        and weight_rate_pct_per_week < 0
    ):
        return "Ease the deficit and hold load"

    if supercompensation_state == "working":
        return "Advance plyo to single-leg phase"
    if supercompensation_state == "digging":
        return "Reduce volume and prioritize sleep"
    return "Maintain load and monitor recovery"


@app.get("/api/athletes/{athlete_id}/summary/monthly")
def get_athlete_monthly_summary(
    athlete_id: str,
    current_user: User = Depends(resolve_user),
    month: Optional[str] = Query(default=None),
):
    """Return a monthly training summary with supercompensation detection (issue #1056).

    Query params:
        month: YYYY-MM string selecting the target month (default: current month).

    Returns a flat JSON object with exactly 14 keys.
    Returns HTTP 424 when no training sessions found for the requested month.
    """
    import calendar as _calendar

    try:
        uid = _uuid.UUID(athlete_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"invalid athlete_id: {athlete_id!r}")

    if uid != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # ── Resolve month boundaries ───────────────────────────────────────────────
    if month is not None:
        try:
            parsed = _date.fromisoformat(f"{month}-01")
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"month must be in YYYY-MM format, got {month!r}",
            )
        month_start = parsed
    else:
        _bkk = ZoneInfo("Asia/Bangkok")
        today_bkk = _datetime.now(_bkk).date()
        month_start = today_bkk.replace(day=1)

    last_day = _calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = month_start.replace(day=last_day)

    # ── Fetch workouts, weight entries, and races ──────────────────────────────
    with Session(engine) as session:
        athlete = session.get(User, uid)
        if athlete is None:
            raise HTTPException(status_code=404, detail="Athlete not found")

        _mkey = "monthly:" + month_start.isoformat()
        _msig = _summary_signature(session, uid)
        _mcached = _summary_cache_get(uid, _mkey, _msig)
        if _mcached is not None:
            return JSONResponse(_mcached)

        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= month_start,
                Workout.workout_date <= month_end,
            )
            .order_by(Workout.workout_date)
            .all()
        )

        weight_entries = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date >= month_start,
                WeightEntry.entry_date <= month_end,
            )
            .order_by(WeightEntry.entry_date)
            .all()
        )

        # Only retrieve checkpoint-type races for next_checkpoint
        races = (
            session.query(Race)
            .filter(
                Race.user_id == uid,
                Race.race_type == "checkpoint",
                Race.race_date > _date.today(),
            )
            .order_by(Race.race_date)
            .all()
        )

    # ── Guard — 424 when no training sessions for this month ──────────────────
    if not workouts:
        raise HTTPException(
            status_code=424,
            detail=f"No training sessions found for {month_start.strftime('%B %Y')}.",
        )

    # ── Training aggregate fields ─────────────────────────────────────────────
    session_count = len(workouts)

    def _safe_sum(items, attr):
        vals = []
        for item in items:
            v = getattr(item, attr, None)
            if v is not None:
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    pass
        return round(sum(vals), 3) if vals else 0.0

    distance_km = _safe_sum(workouts, "distance_km")
    total_tss = _safe_sum(workouts, "tss")

    # ── Score change (endurance / speed signals) ───────────────────────────────
    endurance_score_change, speed_score_change = _monthly_score_delta(workouts)

    # ── Weight metrics ─────────────────────────────────────────────────────────
    weight_change_kg = None
    weight_rate_percent_per_week = None

    if len(weight_entries) >= 2:
        first_w = float(weight_entries[0].weight_kg)
        last_w = float(weight_entries[-1].weight_kg)
        weight_change_kg = round(last_w - first_w, 3)

        span_days = (weight_entries[-1].entry_date - weight_entries[0].entry_date).days
        if span_days > 0 and first_w > 0:
            weeks = span_days / 7.0
            rate_pct = (weight_change_kg / first_w) * 100.0 / weeks
            weight_rate_percent_per_week = round(rate_pct, 3)

    # ── Fitness / form metrics (CTL/ATL/TSB) ──────────────────────────────────
    lookback_start = month_start - _timedelta(days=180)
    fitness_curve = compute_fitness_series(str(uid), lookback_start, month_end)

    # Extract month-specific data points from the full curve
    month_entries = [
        entry for entry in fitness_curve
        if month_start <= entry["date"] <= month_end
    ] if fitness_curve else []

    if month_entries:
        ctl_at_start = month_entries[0]["ctl"]
        ctl_at_end = month_entries[-1]["ctl"]
        tsb_at_end = month_entries[-1]["tsb"]
    elif fitness_curve:
        last = fitness_curve[-1]
        ctl_at_start = last["ctl"]
        ctl_at_end = last["ctl"]
        tsb_at_end = last["tsb"]
    else:
        ctl_at_start = 0.0
        ctl_at_end = 0.0
        tsb_at_end = 0.0

    fitness_ctl_change = round(ctl_at_end - ctl_at_start, 2)
    form_recovered = tsb_at_end >= _MONTHLY_SUMMARY_FORM_RECOVERY_THRESHOLD

    # ── Supercompensation state ────────────────────────────────────────────────
    supercompensation_state = _compute_supercompensation_state(
        endurance_score_change, speed_score_change, form_recovered
    )

    # ── Call to action ─────────────────────────────────────────────────────────
    raw_safe_rate = _get_app_config(_MONTHLY_SUMMARY_SAFE_LEAN_DOWN_KEY, "1.0")
    try:
        safe_lean_down_rate = float(raw_safe_rate)
    except (TypeError, ValueError):
        safe_lean_down_rate = 1.0

    call_to_action = _compute_call_to_action(
        supercompensation_state, weight_rate_percent_per_week, safe_lean_down_rate
    )

    # ── Next checkpoint ────────────────────────────────────────────────────────
    next_checkpoint = None
    today = _date.today()
    upcoming = [r for r in races if r.race_date > today and r.race_type == "checkpoint"]
    if upcoming:
        nearest = min(upcoming, key=lambda r: r.race_date)
        next_checkpoint = {
            "name": nearest.name,
            "date": nearest.race_date.isoformat(),
        }

    guardrail = get_guardrail_result(uid)

    _mpayload = {
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "distance_km": distance_km,
        "total_tss": total_tss,
        "session_count": session_count,
        "endurance_score_change": endurance_score_change,
        "speed_score_change": speed_score_change,
        "weight_change_kg": weight_change_kg,
        "weight_rate_percent_per_week": weight_rate_percent_per_week,
        "fitness_ctl_change": fitness_ctl_change,
        "form_recovered": form_recovered,
        "supercompensation_state": supercompensation_state,
        "call_to_action": call_to_action,
        "next_checkpoint": next_checkpoint,
        "guardrail_state": guardrail["guardrail_state"],
        "guardrail_message": guardrail["guardrail_message"],
    }
    _summary_cache_put(uid, _mkey, _msig, _mpayload)
    return JSONResponse(_mpayload)


# ── Intensity Distribution ───────────────────────────────────────────────────

_LOW_BANDS = {"easy", "steady"}
_MODERATE_BANDS = {"tempo"}
_HIGH_BANDS = {"threshold", "hard"}


@app.get("/api/sessions/{session_id}/intensity-distribution")
def get_session_intensity_distribution(session_id: str, user: User = Depends(resolve_user)):
    """Return per-session intensity distribution and polarized-training verdict.

    Path parameter:
        session_id: UUID of the workout/session.

    Response fields:
        session_id           str       — echoed back
        low                  float|null — % of classified session time in low intensity (easy + steady)
        moderate             float|null — % of classified session time in moderate intensity (tempo)
        high                 float|null — % of classified session time in high intensity (threshold + hard)
        polarized_check      str       — "pass" | "borderline" | "fail" | "insufficient_data"
        lap_count            int       — total number of laps/splits
        classified_lap_count int       — laps with a resolved intensity band
    """
    try:
        wid = _uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    with Session(engine) as db:
        workout = db.get(Workout, wid)
        if workout is None or workout.user_id != user.id:
            raise HTTPException(status_code=404, detail="Session not found")

        splits = (
            db.query(WorkoutSplit)
            .filter(WorkoutSplit.workout_id == wid)
            .order_by(WorkoutSplit.split_index)
            .all()
        )
        prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
        prefs_dict = {
            "ftp_w": prefs.ftp_w if prefs is not None else None,
            "threshold_hr": prefs.threshold_hr if prefs is not None else None,
            "threshold_pace_seconds_per_km": (
                prefs.threshold_pace_seconds_per_km if prefs is not None else None
            ),
        }

        zones = _agg_zones(splits, prefs_dict)
        low_pct = zones["low_pct"]
        moderate_pct = zones["moderate_pct"]
        high_pct = zones["high_pct"]
        polarized_check = _compute_polarized_check(low_pct, moderate_pct, high_pct)
        classified_count = sum(1 for s in splits if s.intensity_band is not None)

        return JSONResponse({
            "session_id": session_id,
            "low": low_pct,
            "moderate": moderate_pct,
            "high": high_pct,
            "polarized_check": polarized_check,
            "lap_count": len(splits),
            "classified_lap_count": classified_count,
        })


@app.get("/api/intensity-distribution/rolling")
def get_rolling_intensity_distribution(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: User = Depends(resolve_user),
):
    """Return intensity distribution aggregated across workouts in a date window.

    Query parameters:
        from  str|null — window start date YYYY-MM-DD (default: 28 days ago)
        to    str|null — window end date YYYY-MM-DD (default: today)

    Response fields:
        from            str       — actual start date used
        to              str       — actual end date used
        low             float|null — aggregate % of classified time in low intensity
        moderate        float|null — aggregate % of classified time in moderate intensity
        high            float|null — aggregate % of classified time in high intensity
        polarized_check str       — "pass" | "borderline" | "fail" | "insufficient_data"
        session_count   int       — number of workouts in the date range
    """
    from datetime import date as _date_cls, timedelta as _timedelta_cls
    today = _date_cls.today()

    if from_date is None:
        start = today - _timedelta_cls(days=27)
    else:
        try:
            start = _date_cls.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'from' date; use YYYY-MM-DD")

    if to_date is None:
        end = today
    else:
        try:
            end = _date_cls.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'to' date; use YYYY-MM-DD")

    if start > end:
        raise HTTPException(status_code=422, detail="'from' date must not be after 'to' date")

    with Session(engine) as db:
        workouts = (
            db.query(Workout)
            .filter(Workout.user_id == user.id)
            .filter(Workout.workout_date >= start)
            .filter(Workout.workout_date <= end)
            .all()
        )
        prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
        prefs_dict = {
            "ftp_w": prefs.ftp_w if prefs is not None else None,
            "threshold_hr": prefs.threshold_hr if prefs is not None else None,
            "threshold_pace_seconds_per_km": (
                prefs.threshold_pace_seconds_per_km if prefs is not None else None
            ),
        }

        total_low_s = 0.0
        total_mod_s = 0.0
        total_high_s = 0.0

        for workout in workouts:
            splits = (
                db.query(WorkoutSplit)
                .filter(WorkoutSplit.workout_id == workout.id)
                .all()
            )
            classifications = _classify_laps(splits, prefs_dict)
            for lap, cls in zip(splits, classifications):
                band = cls.get("band")
                if band is None:
                    continue
                dur = lap.duration_seconds or 0
                if band in _LOW_BANDS:
                    total_low_s += dur
                elif band in _MODERATE_BANDS:
                    total_mod_s += dur
                elif band in _HIGH_BANDS:
                    total_high_s += dur

        total_s = total_low_s + total_mod_s + total_high_s
        if total_s > 0:
            agg_low = round(total_low_s / total_s * 100, 2)
            agg_moderate = round(total_mod_s / total_s * 100, 2)
            agg_high = round(total_high_s / total_s * 100, 2)
        else:
            agg_low = agg_moderate = agg_high = None

        polarized_check = _compute_polarized_check(agg_low, agg_moderate, agg_high)

        return JSONResponse({
            "from": start.isoformat(),
            "to": end.isoformat(),
            "low": agg_low,
            "moderate": agg_moderate,
            "high": agg_high,
            "polarized_check": polarized_check,
            "session_count": len(workouts),
        })


# ── Sleep sync scheduler ──────────────────────────────────────────────────────

def _sleep_sync_scheduler_loop() -> None:
    """Background daemon thread: run Drive sleep sync for all users every hour."""
    import logging as _sched_log
    from backend.services import drive_sleep_sync as _dss

    _log = _sched_log.getLogger("backend.sleep_sync_scheduler")
    _log.info("Sleep sync scheduler started (interval=%ds)", _dss.SLEEP_SYNC_INTERVAL_SECONDS)

    while True:
        time.sleep(_dss.SLEEP_SYNC_INTERVAL_SECONDS)
        try:
            _dss.run_scheduled_sleep_sync()
        except Exception as exc:
            _log.error("Sleep sync scheduler: unhandled error: %s", exc, exc_info=True)


_sleep_sync_thread = _threading.Thread(
    target=_sleep_sync_scheduler_loop,
    daemon=True,
    name="sleep-sync-scheduler",
)
_sleep_sync_thread.start()


# ── Banister refit scheduler ─────────────────────────────────────────────────

_BANISTER_REFIT_INTERVAL_SECONDS: int = 7 * 24 * 3600  # weekly


def _banister_refit_scheduler_loop() -> None:
    """Background daemon: weekly Banister parameter refit for all users."""
    import logging as _br_log
    from sqlalchemy.orm import Session as _OrmSession
    from backend.db import engine as _br_engine
    from backend.models import User as _User
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    _log = _br_log.getLogger("backend.banister_refit_scheduler")
    _log.info(
        "Banister refit scheduler started (interval=%ds)",
        _BANISTER_REFIT_INTERVAL_SECONDS,
    )

    while True:
        time.sleep(_BANISTER_REFIT_INTERVAL_SECONDS)
        try:
            with _OrmSession(_br_engine) as _sess:
                _user_ids = [
                    str(r.id)
                    for r in _sess.query(_User.id)
                    .filter(_User.is_active.is_(True))
                    .all()
                ]
            _log.info(
                "banister_refit_scheduler: starting batch for %d user(s)",
                len(_user_ids)
            )
            results = run_banister_refit_pipeline(_user_ids)
            ok_count = sum(1 for v in results.values() if v == "ok")
            skip_count = len(results) - ok_count
            _log.info(
                "banister_refit_scheduler: batch complete — %d ok, %d skipped",
                ok_count,
                skip_count,
            )
        except Exception as exc:
            _log.error(
                "banister_refit_scheduler: unhandled error: %s",
                exc, exc_info=True
            )


if os.environ.get("BANISTER_REFIT_ENABLED", "1") != "0":
    _banister_refit_thread = _threading.Thread(
        target=_banister_refit_scheduler_loop,
        daemon=True,
        name="banister-refit-scheduler",
    )
    _banister_refit_thread.start()
else:
    _logging.getLogger(__name__).info(
        "Banister refit scheduler disabled (BANISTER_REFIT_ENABLED=0)"
    )
