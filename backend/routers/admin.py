"""admin.py — the full admin surface: /admin*, /api/admin/*, and the legacy
/api/users CRUD (also require_admin-gated).

Extracted out of backend/main.py so it can be mounted in BOTH this app
(backend/main.py, the webapp) and backend/worker_app.py (the compute worker),
without worker_app.py importing backend.main (forbidden — see worker_app.py's
own docstring). Route paths, request/response shapes, and behavior are
UNCHANGED from the pre-extraction code; this is a pure move.
"""
from __future__ import annotations

import hmac as _hmac
import os
import uuid as _uuid
from datetime import datetime as _datetime, timezone as _timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import exc as sa_exc, func, select
from sqlalchemy.orm import Session

from backend.auth import (
    ADMIN_COOKIE_NAME,
    admin_lockout_check,
    admin_lockout_clear,
    admin_lockout_record,
    clear_admin_cookie,
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    get_admin_secret,
    get_client_ip,
    hash_password,
    MIN_PASSWORD_LENGTH,
    read_admin_cookie,
    require_admin,
    set_admin_cookie,
    set_csrf_cookie,
)
from backend.db import engine
from backend.models import (
    GoogleOAuthCredentials, Habit, HabitLog, StravaToken, StrydCredentials,
    User, WeightEntry, Workout,
)
from backend.services.app_config import (
    APP_CONFIG_GOOGLE_LOGIN as _APP_CONFIG_GOOGLE_LOGIN,
    get_app_config as _get_app_config,
    set_app_config as _set_app_config,
    google_credentials_present as _google_credentials_present,
)

# perf-coach root (same directory _static_root resolves to in main.py) — this
# file lives at backend/routers/admin.py, one level deeper than backend/main.py.
_static_root = Path(__file__).parent.parent.parent

router = APIRouter()

@router.get("/api/users", dependencies=[Depends(require_admin)])
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


@router.post("/api/users", status_code=201, dependencies=[Depends(require_admin)])
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


@router.patch("/api/users/{user_id}", dependencies=[Depends(require_admin)])
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


@router.delete("/api/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)])
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

# ── Admin gate ────────────────────────────────────────────────────────────────

class AdminLoginIn(BaseModel):
    secret: str


@router.get("/admin", include_in_schema=False)
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


@router.get("/admin/exercises", include_in_schema=False)
@router.get("/admin/plan-library", include_in_schema=False)
def admin_plan_library_page(request: Request):
    """Plan library — patterns + exercise pool for pattern fill. Same admin cookie gate as /admin."""
    secret = get_admin_secret()
    if not secret:
        raise HTTPException(status_code=403, detail="Admin access is disabled on this instance")
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if token:
        try:
            read_admin_cookie(token)
            return FileResponse(str(_static_root / "frontend" / "pages" / "admin-plan-library.html"))
        except ValueError:
            pass
    return FileResponse(str(_static_root / "frontend" / "pages" / "admin-login.html"))


@router.post("/api/admin/login")
def admin_login(body: AdminLoginIn, request: Request):
    ip = get_client_ip(request)
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
    set_csrf_cookie(resp, generate_csrf_token())
    return resp


@router.post("/api/admin/logout", status_code=204)
def admin_logout():
    resp = Response(status_code=204)
    clear_admin_cookie(resp)
    resp.delete_cookie(key=CSRF_COOKIE_NAME, path="/")
    return resp


# ── Admin user management endpoints ──────────────────────────────────────────

class AdminUserCreateIn(BaseModel):
    username: str
    password: str
    is_admin: bool = False


@router.post("/api/admin/users", status_code=201, dependencies=[Depends(require_admin)])
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


@router.get("/api/admin/users", dependencies=[Depends(require_admin)])
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


@router.get("/api/admin/users/{user_id}/recent-activities", dependencies=[Depends(require_admin)])
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


@router.post("/api/admin/users/{user_id}/reset-password", dependencies=[Depends(require_admin)])
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


@router.post("/api/admin/users/{user_id}/toggle-admin", dependencies=[Depends(require_admin)])
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


@router.post("/api/admin/users/{user_id}/disable", dependencies=[Depends(require_admin)])
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


@router.post("/api/admin/users/{user_id}/enable", dependencies=[Depends(require_admin)])
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


@router.delete("/api/admin/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)])
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


@router.get("/api/admin/config/google-login", dependencies=[Depends(require_admin)])
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


@router.post("/api/admin/config/google-login", dependencies=[Depends(require_admin)])
def admin_set_google_login_config(body: AdminGoogleLoginToggleIn):
    _set_app_config(_APP_CONFIG_GOOGLE_LOGIN, "true" if body.enabled else "false")
    return JSONResponse({"toggle_enabled": body.enabled})


# ── Admin: DB backup + user copy ────────────────────────────────────────────────

@router.get("/api/admin/db/backup", dependencies=[Depends(require_admin)])
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


@router.get("/api/admin/prd-users", dependencies=[Depends(require_admin)])
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


@router.post("/api/admin/users/copy-to-uat", dependencies=[Depends(require_admin)])
def admin_copy_user_to_uat(body: AdminCopyUserIn):
    """Copy one PRD user's full data graph into UAT. Direction is hard-locked."""
    from backend.services.user_copy import UserCopyError, copy_user_to_uat

    try:
        result = copy_user_to_uat(body.identifier, overwrite=bool(body.overwrite))
    except UserCopyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(result)


# ── Admin: plan patterns / exercises ──────────────────────────────────────────

class AdminPlanPatternIn(BaseModel):
    kind: str
    subtype: str
    duration_min_lo: int = 0
    duration_min_hi: int = 120
    name: str
    priority: int = 10
    recipe: dict
    active: bool = True


class AdminPlanExerciseIn(BaseModel):
    name: str
    groups: list = []
    focus_tags: list = []
    body_parts: list = []
    tss_weight: float = 1.0
    default_sets: Optional[int] = None
    default_reps: Optional[str] = None
    default_load: Optional[str] = None
    active: bool = True


def _pattern_dict(r) -> dict:
    return {
        "id": str(r.id),
        "kind": r.kind,
        "subtype": r.subtype,
        "duration_min_lo": r.duration_min_lo,
        "duration_min_hi": r.duration_min_hi,
        "name": r.name,
        "priority": r.priority,
        "recipe": r.recipe or {},
        "active": bool(r.active),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _exercise_dict(r) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "groups": r.groups or [],
        "focus_tags": r.focus_tags or [],
        "body_parts": r.body_parts or [],
        "tss_weight": float(r.tss_weight or 1.0),
        "default_sets": r.default_sets,
        "default_reps": r.default_reps,
        "default_load": r.default_load,
        "active": bool(r.active),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/api/admin/plan-patterns", dependencies=[Depends(require_admin)])
def admin_list_plan_patterns(kind: Optional[str] = None, subtype: Optional[str] = None):
    from backend.models import PlanPattern

    with Session(engine) as db:
        q = db.query(PlanPattern)
        if kind:
            q = q.filter(PlanPattern.kind == kind)
        if subtype:
            q = q.filter(PlanPattern.subtype == subtype)
        rows = q.order_by(PlanPattern.kind, PlanPattern.subtype, PlanPattern.priority.desc()).all()
        return JSONResponse({"patterns": [_pattern_dict(r) for r in rows]})


@router.post("/api/admin/plan-patterns", status_code=201, dependencies=[Depends(require_admin)])
def admin_create_plan_pattern(body: AdminPlanPatternIn):
    from backend.models import PlanPattern
    from datetime import datetime, timezone

    if body.kind not in ("run", "strength"):
        raise HTTPException(status_code=422, detail="kind must be run or strength")
    with Session(engine) as db:
        row = PlanPattern(
            kind=body.kind,
            subtype=body.subtype.strip(),
            duration_min_lo=body.duration_min_lo,
            duration_min_hi=body.duration_min_hi,
            name=body.name.strip(),
            priority=body.priority,
            recipe=body.recipe,
            active=body.active,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return JSONResponse(status_code=201, content=_pattern_dict(row))


@router.patch("/api/admin/plan-patterns/{pattern_id}", dependencies=[Depends(require_admin)])
def admin_patch_plan_pattern(pattern_id: str, body: AdminPlanPatternIn):
    from backend.models import PlanPattern
    from datetime import datetime, timezone
    from uuid import UUID

    with Session(engine) as db:
        row = db.query(PlanPattern).filter(PlanPattern.id == UUID(pattern_id)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="pattern not found")
        if body.kind not in ("run", "strength"):
            raise HTTPException(status_code=422, detail="kind must be run or strength")
        row.kind = body.kind
        row.subtype = body.subtype.strip()
        row.duration_min_lo = body.duration_min_lo
        row.duration_min_hi = body.duration_min_hi
        row.name = body.name.strip()
        row.priority = body.priority
        row.recipe = body.recipe
        row.active = body.active
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return JSONResponse(_pattern_dict(row))


@router.delete("/api/admin/plan-patterns/{pattern_id}", status_code=204, dependencies=[Depends(require_admin)])
def admin_delete_plan_pattern(pattern_id: str):
    from backend.models import PlanPattern
    from uuid import UUID

    with Session(engine) as db:
        row = db.query(PlanPattern).filter(PlanPattern.id == UUID(pattern_id)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="pattern not found")
        db.delete(row)
        db.commit()
    return Response(status_code=204)


@router.get("/api/admin/plan-exercises", dependencies=[Depends(require_admin)])
def admin_list_plan_exercises():
    from backend.models import PlanExercise

    with Session(engine) as db:
        rows = db.query(PlanExercise).order_by(PlanExercise.name).all()
        return JSONResponse({"exercises": [_exercise_dict(r) for r in rows]})


@router.post("/api/admin/plan-exercises", status_code=201, dependencies=[Depends(require_admin)])
def admin_create_plan_exercise(body: AdminPlanExerciseIn):
    from backend.models import PlanExercise
    from backend.services.plan_body_parts import normalize_body_parts_list
    from datetime import datetime, timezone
    from sqlalchemy.exc import IntegrityError

    cleaned, bp_err = normalize_body_parts_list(body.body_parts or [])
    if bp_err:
        raise HTTPException(status_code=422, detail=bp_err)

    with Session(engine) as db:
        row = PlanExercise(
            name=body.name.strip(),
            groups=body.groups or [],
            focus_tags=body.focus_tags or [],
            body_parts=cleaned or [],
            tss_weight=body.tss_weight,
            default_sets=body.default_sets,
            default_reps=body.default_reps,
            default_load=body.default_load,
            active=body.active,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"Exercise '{body.name}' already exists")
        db.refresh(row)
        return JSONResponse(status_code=201, content=_exercise_dict(row))


@router.patch("/api/admin/plan-exercises/{exercise_id}", dependencies=[Depends(require_admin)])
def admin_patch_plan_exercise(exercise_id: str, body: AdminPlanExerciseIn):
    from backend.models import PlanExercise
    from backend.services.plan_body_parts import normalize_body_parts_list
    from datetime import datetime, timezone
    from uuid import UUID

    cleaned, bp_err = normalize_body_parts_list(body.body_parts or [])
    if bp_err:
        raise HTTPException(status_code=422, detail=bp_err)

    with Session(engine) as db:
        row = db.query(PlanExercise).filter(PlanExercise.id == UUID(exercise_id)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="exercise not found")
        row.name = body.name.strip()
        row.groups = body.groups or []
        row.focus_tags = body.focus_tags or []
        row.body_parts = cleaned or []
        row.tss_weight = body.tss_weight
        row.default_sets = body.default_sets
        row.default_reps = body.default_reps
        row.default_load = body.default_load
        row.active = body.active
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return JSONResponse(_exercise_dict(row))


@router.delete("/api/admin/plan-exercises/{exercise_id}", status_code=204, dependencies=[Depends(require_admin)])
def admin_delete_plan_exercise(exercise_id: str):
    from backend.models import PlanExercise
    from uuid import UUID

    with Session(engine) as db:
        row = db.query(PlanExercise).filter(PlanExercise.id == UUID(exercise_id)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="exercise not found")
        db.delete(row)
        db.commit()
    return Response(status_code=204)


class AdminPlanExercisePreviewIn(BaseModel):
    subtype: str = "strength_light"
    duration_minutes: int = 45
    target_tss: float = 40
    # None → fresh random each Preview click so you can see shuffle.
    seed: int | None = None


_RUN_PREVIEW_SUBTYPES = frozenset({
    "easy_run", "easy", "tempo", "intervals", "long_run",
})


@router.post("/api/admin/plan-exercises/preview", dependencies=[Depends(require_admin)])
def admin_preview_plan_exercise_fill(body: AdminPlanExercisePreviewIn):
    """Dry-run pattern fill for one strength or run subtype."""
    import random
    import time

    from backend.services.plan_pattern_fill import (
        compute_pool_counts,
        fill_slot,
        select_pattern,
        _load_exercise_pool,
    )
    from backend.services.plan_slot import normalize_slot_subtype

    raw_sub = (body.subtype or "").strip()
    if raw_sub in _RUN_PREVIEW_SUBTYPES:
        wt = "run"
        subtype = normalize_slot_subtype("run", raw_sub) or raw_sub
    else:
        wt = "strength"
        subtype = normalize_slot_subtype("strength", raw_sub) or "strength_light"

    slot = {
        "day_offset": 0,
        "workout_type": wt,
        "target_tss": float(body.target_tss),
        "duration_minutes": int(body.duration_minutes),
        "subtype": subtype,
        "structure_hints": {},
        "locked": False,
    }
    seed = body.seed if body.seed is not None else (time.time_ns() & 0xFFFFFFFF)
    with Session(engine) as db:
        content = fill_slot(
            slot,
            db=db,
            week_ctx={"skeleton_slots": [slot]},
            rng=random.Random(seed),
        )
        pattern = select_pattern(
            db,
            workout_type=wt,
            subtype=subtype,
            duration_min=int(body.duration_minutes),
        )
        pool_counts = None
        if pattern and wt == "strength":
            pool_counts = compute_pool_counts(
                pattern,
                _load_exercise_pool(db),
                duration_min=int(body.duration_minutes),
            )
            pool_counts["pattern_id"] = pattern.get("id")
    fill_log = content.get("fill_log") or {}
    footprint = content.get("_muscle_footprint") or {}
    muscle_summary = [
        {"part": p, "tss": round(float(v), 2)}
        for p, v in sorted(footprint.items(), key=lambda kv: -float(kv[1]))
        if float(v) > 0
    ]
    return JSONResponse({
        "subtype": subtype,
        "workout_type": wt,
        "intent": content.get("intent"),
        "notes": content.get("notes"),
        "exercises": content.get("exercises") or [],
        "blocks": content.get("blocks") or [],
        "source": content.get("source"),
        "pattern_name": content.get("pattern_name"),
        "pattern_id": (pattern or {}).get("id") if pattern else None,
        "fill_log": fill_log,
        "budget_trace": fill_log.get("budget_trace") or [],
        "pool_counts": pool_counts,
        "muscle_footprint": footprint,
        "muscle_summary": muscle_summary,
        "duration_minutes": int(body.duration_minutes),
        "target_tss": float(body.target_tss),
        "seed": seed,
    })


@router.get("/api/admin/plan-patterns/{pattern_id}/pool-counts", dependencies=[Depends(require_admin)])
def admin_plan_pattern_pool_counts(pattern_id: str, duration_min: int = 60):
    """Matched exercise counts per recipe group (same tag matcher as fill)."""
    from uuid import UUID

    from backend.models import PlanPattern
    from backend.services.plan_pattern_fill import _load_exercise_pool, compute_pool_counts

    with Session(engine) as db:
        row = db.query(PlanPattern).filter(PlanPattern.id == UUID(pattern_id)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="pattern not found")
        pattern = {
            "id": str(row.id),
            "kind": row.kind,
            "subtype": row.subtype,
            "name": row.name,
            "recipe": row.recipe or {},
            "duration_min_lo": row.duration_min_lo,
            "duration_min_hi": row.duration_min_hi,
            "priority": row.priority,
            "active": bool(row.active),
        }
        counts = compute_pool_counts(
            pattern,
            _load_exercise_pool(db),
            duration_min=int(duration_min),
        )
        counts["pattern_id"] = str(row.id)
        return JSONResponse(counts)


@router.get("/api/admin/plan-library/pool-counts", dependencies=[Depends(require_admin)])
def admin_plan_library_pool_counts(subtype: str, duration_min: int = 60):
    """Resolve pattern by subtype + duration, then return pool counts (Preview strip)."""
    from backend.services.plan_pattern_fill import (
        _load_exercise_pool,
        compute_pool_counts,
        select_pattern,
    )
    from backend.services.plan_slot import normalize_slot_subtype

    raw = (subtype or "").strip()
    if raw in _RUN_PREVIEW_SUBTYPES:
        wt = "run"
        sub = normalize_slot_subtype("run", raw) or raw
    else:
        wt = "strength"
        sub = normalize_slot_subtype("strength", raw) or raw

    with Session(engine) as db:
        pattern = select_pattern(
            db, workout_type=wt, subtype=sub, duration_min=int(duration_min),
        )
        if pattern is None:
            raise HTTPException(status_code=404, detail="no matching pattern")
        if wt == "run":
            return JSONResponse({
                "pattern_id": pattern.get("id"),
                "pattern_name": pattern.get("name"),
                "subtype": pattern.get("subtype"),
                "duration_min": int(duration_min),
                "matched_total": 0,
                "blocks": [],
                "thin_blocks": [],
                "kind": "run",
                "note": "run patterns scale phases — no exercise pool",
            })
        counts = compute_pool_counts(
            pattern,
            _load_exercise_pool(db),
            duration_min=int(duration_min),
        )
        counts["pattern_id"] = pattern.get("id")
        return JSONResponse(counts)

@router.post("/api/admin/plan-patterns/seed", dependencies=[Depends(require_admin)])
def admin_seed_plan_patterns(reset: bool = False):
    """Idempotent upsert of ship-default patterns and exercises."""
    from backend.services.plan_pattern_fill import seed_defaults

    with Session(engine) as db:
        result = seed_defaults(db, reset=reset)
        db.commit()
        return JSONResponse(result)


class AdminPlanLibraryImportIn(BaseModel):
    """Bulk create/upsert from Claude-authored (or downloaded) catalog JSON.

    Clients send ``exercises`` and/or ``patterns`` as lists of row objects
    (the admin UI also accepts a bare array or a single object and normalizes
    client-side). ``mode=upsert`` updates by name (exercises) or
    kind+subtype+name (patterns); ``mode=create`` skips existing rows.
    """
    exercises: list[dict] = []
    patterns: list[dict] = []
    mode: str = "upsert"  # upsert | create


# Catalog allow-lists — keep groups/focus in sync with frontend/js/admin-plan-library.js
_PLAN_EXERCISE_GROUPS = frozenset({
    "warmup", "heavy_compound", "superset", "standalone", "accessories",
    "cooldown", "bodyweight", "plyo", "isometric", "emom",
})
_PLAN_FOCUS_TAGS = frozenset({"lower", "upper", "full", "core"})
_PLAN_RUN_PHASES = frozenset({"warmup", "main", "cooldown", "mp"})


def _validate_plan_exercise_import(raw: dict) -> str | None:
    """Return an error detail string, or None if the exercise row is ok.

    Normalizes body_parts in-place (plurals → canonical keys) on success.
    """
    from backend.services.plan_body_parts import normalize_body_parts_list

    name = str(raw.get("name") or "").strip()
    if not name:
        return "name required"
    groups = raw.get("groups")
    if not isinstance(groups, list) or not groups:
        return "groups must be a non-empty list"
    bad_g = [g for g in groups if not isinstance(g, str) or g not in _PLAN_EXERCISE_GROUPS]
    if bad_g:
        return f"invalid groups: {bad_g!r} (allowed: {sorted(_PLAN_EXERCISE_GROUPS)})"
    focus_tags = raw.get("focus_tags")
    if not isinstance(focus_tags, list) or not focus_tags:
        return "focus_tags must be a non-empty list"
    bad_f = [f for f in focus_tags if not isinstance(f, str) or f not in _PLAN_FOCUS_TAGS]
    if bad_f:
        return f"invalid focus_tags: {bad_f!r} (allowed: {sorted(_PLAN_FOCUS_TAGS)})"
    cleaned, bp_err = normalize_body_parts_list(raw.get("body_parts"))
    if bp_err:
        return bp_err
    raw["body_parts"] = cleaned
    try:
        tss_weight = float(raw.get("tss_weight") if raw.get("tss_weight") is not None else 1.0)
    except (TypeError, ValueError):
        return "bad tss_weight"
    if not (0 < tss_weight <= 3):
        return "tss_weight must be 0 < n ≤ 3"
    if raw.get("default_sets") is not None:
        try:
            sets = int(raw.get("default_sets"))
        except (TypeError, ValueError):
            return "bad default_sets"
        if sets < 1 or sets > 12:
            return "default_sets must be 1–12"
    return None


def _validate_strength_pick_group(g: dict) -> str | None:
    if not isinstance(g, dict):
        return "strength group must be an object"
    if not str(g.get("key") or "").strip():
        return "strength group.key required"
    pick = g.get("pick")
    if not isinstance(pick, dict):
        return "strength group.pick required"
    try:
        n = int(pick.get("n"))
    except (TypeError, ValueError):
        return "strength group.pick.n must be an integer"
    if n < 1:
        return "strength group.pick.n must be ≥ 1"
    tags = pick.get("from_tags")
    if not isinstance(tags, list) or not tags:
        return "strength group.pick.from_tags must be a non-empty list"
    bad = [t for t in tags if not isinstance(t, str) or t not in _PLAN_EXERCISE_GROUPS]
    if bad:
        return f"invalid from_tags: {bad!r} (allowed groups: {sorted(_PLAN_EXERCISE_GROUPS)})"
    return None


def _validate_plan_pattern_import(raw: dict) -> str | None:
    """Return an error detail string, or None if the pattern row is ok."""
    kind = str(raw.get("kind") or "").strip()
    subtype = str(raw.get("subtype") or "").strip()
    name = str(raw.get("name") or "").strip()
    if kind not in ("run", "strength"):
        return "kind must be run or strength"
    if not subtype or not name:
        return "subtype and name required"
    recipe = raw.get("recipe")
    if not isinstance(recipe, dict):
        return "recipe must be an object"
    if not str(recipe.get("intent_template") or "").strip():
        return "recipe.intent_template required"
    if kind == "run":
        blocks = recipe.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            return "run recipe.blocks must be a non-empty list"
        share_sum = 0.0
        for b in blocks:
            if not isinstance(b, dict):
                return "run blocks must be objects"
            phase = b.get("phase")
            if phase not in _PLAN_RUN_PHASES:
                return f"invalid block.phase: {phase!r} (allowed: {sorted(_PLAN_RUN_PHASES)})"
            try:
                share = float(b.get("duration_share"))
            except (TypeError, ValueError):
                return "block.duration_share must be a number"
            if share <= 0:
                return "block.duration_share must be > 0"
            share_sum += share
        if abs(share_sum - 1.0) > 0.05:
            return f"block duration_share must sum ≈ 1.0 (got {share_sum:.2f})"
    else:
        groups = recipe.get("groups") if isinstance(recipe.get("groups"), list) else []
        bands = recipe.get("bands") if isinstance(recipe.get("bands"), list) else []
        if not groups and not bands:
            return "strength recipe needs groups and/or bands"
        for g in groups:
            err = _validate_strength_pick_group(g)
            if err:
                return err
        for band in bands:
            if not isinstance(band, dict):
                return "band must be an object"
            bg = band.get("groups")
            if not isinstance(bg, list) or not bg:
                return "band.groups must be a non-empty list"
            for g in bg:
                err = _validate_strength_pick_group(g)
                if err:
                    return err
        bias = recipe.get("focus_bias")
        if bias is not None:
            if not isinstance(bias, dict):
                return "recipe.focus_bias must be an object"
            primary_tag = bias.get("primary_tag")
            if primary_tag not in _PLAN_FOCUS_TAGS:
                return (
                    f"invalid focus_bias.primary_tag: {primary_tag!r} "
                    f"(allowed: {sorted(_PLAN_FOCUS_TAGS)})"
                )
    return None


def _export_exercise_row(r) -> dict:
    return {
        "name": r.name,
        "groups": r.groups or [],
        "focus_tags": r.focus_tags or [],
        "body_parts": r.body_parts or [],
        "tss_weight": float(r.tss_weight or 1.0),
        "default_sets": r.default_sets,
        "default_reps": r.default_reps,
        "default_load": r.default_load,
        "active": bool(r.active),
    }


def _export_pattern_row(r) -> dict:
    return {
        "kind": r.kind,
        "subtype": r.subtype,
        "duration_min_lo": r.duration_min_lo,
        "duration_min_hi": r.duration_min_hi,
        "name": r.name,
        "priority": r.priority,
        "recipe": r.recipe or {},
        "active": bool(r.active),
    }


@router.get("/api/admin/plan-library/export", dependencies=[Depends(require_admin)])
def admin_export_plan_library():
    """Downloadable catalog (no ids) for Claude edit → bulk import."""
    from backend.models import PlanExercise, PlanPattern
    from datetime import datetime, timezone

    with Session(engine) as db:
        exercises = [
            _export_exercise_row(r)
            for r in db.query(PlanExercise).order_by(PlanExercise.name).all()
        ]
        patterns = [
            _export_pattern_row(r)
            for r in db.query(PlanPattern).order_by(
                PlanPattern.kind, PlanPattern.subtype, PlanPattern.priority.desc()
            ).all()
        ]
    return JSONResponse({
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exercises": exercises,
        "patterns": patterns,
    })


@router.get("/api/admin/plan-library/body-parts", dependencies=[Depends(require_admin)])
def admin_plan_library_body_parts():
    """Known body-part keys, colors, and accepted aliases (plural/singular)."""
    from backend.services.plan_body_parts import catalog_payload
    return JSONResponse(catalog_payload())


@router.post("/api/admin/plan-library/normalize-body-parts", dependencies=[Depends(require_admin)])
def admin_normalize_plan_body_parts():
    """Rewrite stored exercise body_parts through the alias map (glutes→glute, …)."""
    from backend.models import PlanExercise
    from backend.services.plan_body_parts import normalize_body_parts_list
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    updated = 0
    skipped = 0
    errors = []
    with Session(engine) as db:
        rows = db.query(PlanExercise).all()
        for row in rows:
            cleaned, err = normalize_body_parts_list(row.body_parts or [])
            if err or cleaned is None:
                skipped += 1
                errors.append({"name": row.name, "detail": err or "empty"})
                continue
            if cleaned == (row.body_parts or []):
                skipped += 1
                continue
            row.body_parts = cleaned
            row.updated_at = now
            updated += 1
        db.commit()
    return JSONResponse({"updated": updated, "skipped": skipped, "errors": errors[:20]})


@router.post("/api/admin/plan-library/import", dependencies=[Depends(require_admin)])
def admin_import_plan_library(body: AdminPlanLibraryImportIn):
    """Bulk create / upsert exercises and patterns from catalog JSON."""
    from backend.models import PlanExercise, PlanPattern
    from datetime import datetime, timezone

    mode = (body.mode or "upsert").strip().lower()
    if mode not in ("upsert", "create"):
        raise HTTPException(status_code=422, detail="mode must be upsert or create")

    now = datetime.now(timezone.utc)
    summary = {
        "mode": mode,
        "exercises": {"created": 0, "updated": 0, "skipped": 0, "errors": []},
        "patterns": {"created": 0, "updated": 0, "skipped": 0, "errors": []},
    }

    with Session(engine) as db:
        for i, raw in enumerate(body.exercises or []):
            if not isinstance(raw, dict):
                summary["exercises"]["errors"].append({"index": i, "detail": "not an object"})
                continue
            name = str(raw.get("name") or "").strip()
            verr = _validate_plan_exercise_import(raw)
            if verr:
                summary["exercises"]["errors"].append({
                    "index": i, "name": name, "detail": verr,
                })
                continue
            try:
                tss_weight = float(raw.get("tss_weight") if raw.get("tss_weight") is not None else 1.0)
            except (TypeError, ValueError):
                summary["exercises"]["errors"].append({"index": i, "name": name, "detail": "bad tss_weight"})
                continue
            groups = list(raw.get("groups") or [])
            focus_tags = list(raw.get("focus_tags") or [])
            body_parts = list(raw.get("body_parts") or [])
            default_sets = raw.get("default_sets")
            if default_sets is not None:
                try:
                    default_sets = int(default_sets)
                except (TypeError, ValueError):
                    summary["exercises"]["errors"].append({"index": i, "name": name, "detail": "bad default_sets"})
                    continue
            active = bool(raw.get("active", True))
            row = db.query(PlanExercise).filter_by(name=name).first()
            if row is None:
                db.add(PlanExercise(
                    name=name,
                    groups=groups,
                    focus_tags=focus_tags,
                    body_parts=body_parts,
                    tss_weight=tss_weight,
                    default_sets=default_sets,
                    default_reps=raw.get("default_reps"),
                    default_load=raw.get("default_load"),
                    active=active,
                    updated_at=now,
                ))
                summary["exercises"]["created"] += 1
            elif mode == "create":
                summary["exercises"]["skipped"] += 1
            else:
                row.groups = groups
                row.focus_tags = focus_tags
                row.body_parts = body_parts
                row.tss_weight = tss_weight
                row.default_sets = default_sets
                row.default_reps = raw.get("default_reps")
                row.default_load = raw.get("default_load")
                row.active = active
                row.updated_at = now
                summary["exercises"]["updated"] += 1

        for i, raw in enumerate(body.patterns or []):
            if not isinstance(raw, dict):
                summary["patterns"]["errors"].append({"index": i, "detail": "not an object"})
                continue
            kind = str(raw.get("kind") or "").strip()
            subtype = str(raw.get("subtype") or "").strip()
            name = str(raw.get("name") or "").strip()
            verr = _validate_plan_pattern_import(raw)
            if verr:
                summary["patterns"]["errors"].append({
                    "index": i, "name": name, "detail": verr,
                })
                continue
            recipe = raw.get("recipe")
            try:
                duration_min_lo = int(raw.get("duration_min_lo") if raw.get("duration_min_lo") is not None else 0)
                duration_min_hi = int(raw.get("duration_min_hi") if raw.get("duration_min_hi") is not None else 120)
                priority = int(raw.get("priority") if raw.get("priority") is not None else 10)
            except (TypeError, ValueError):
                summary["patterns"]["errors"].append({
                    "index": i, "name": name, "detail": "bad duration/priority ints",
                })
                continue
            active = bool(raw.get("active", True))
            row = (
                db.query(PlanPattern)
                .filter_by(kind=kind, subtype=subtype, name=name)
                .first()
            )
            if row is None:
                db.add(PlanPattern(
                    kind=kind,
                    subtype=subtype,
                    duration_min_lo=duration_min_lo,
                    duration_min_hi=duration_min_hi,
                    name=name,
                    priority=priority,
                    recipe=recipe,
                    active=active,
                    updated_at=now,
                ))
                summary["patterns"]["created"] += 1
            elif mode == "create":
                summary["patterns"]["skipped"] += 1
            else:
                row.duration_min_lo = duration_min_lo
                row.duration_min_hi = duration_min_hi
                row.priority = priority
                row.recipe = recipe
                row.active = active
                row.updated_at = now
                summary["patterns"]["updated"] += 1

        db.commit()

    return JSONResponse(summary)
