"""Worker-driven precompute: warm durable caches so the web request never pays a
heavy recompute.

Warms:
- training-load snapshots (today + yesterday + extra dates) — 180-day EWMA
- performance scores (``summary_cache`` key ``performance``)
- weekly summary (this week + last week)
- monthly summary (this month + last month)
- plan computed bundle overlay (performance + PRs on the stored JSON)

Dashboard GETs read those rows and do not recompute when a row exists.
POST /api/plan/recompute remains the force-refresh for race projections.

Kept **worker-importable**: never imports ``backend.main``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
import uuid as _uuid

from backend.services import training_load
from backend.utils.log import get_logger
from backend.utils.time import today_bangkok

_log = get_logger(__name__)


def _coerce_date(value: Any) -> Optional[date]:
    """Accept a date, a datetime, or an ISO 'YYYY-MM-DD' string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _monday_on_or_before(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _prev_month_start(d: date) -> date:
    first = _month_start(d)
    return (first - timedelta(days=1)).replace(day=1)


def _warm_load_snapshots(user_id: str, dates: Optional[Iterable[Any]], end: date) -> dict:
    targets = {end, end - timedelta(days=1)}
    for d in dates or []:
        cd = _coerce_date(d)
        if cd is not None:
            targets.add(cd)

    warmed: dict[str, dict] = {}
    for d in sorted(targets):
        r = training_load.daily_update(user_id, target_date=d)
        warmed[d.isoformat()] = {"ctl": r["ctl"], "atl": r["atl"], "tsb": r["tsb"]}
    return warmed


def _warm_performance(user_id: str) -> str:
    from backend.services.performance_scores import get_performance_payload

    payload = get_performance_payload(_uuid.UUID(str(user_id)), force=True)
    return str(payload.get("state") or "unknown")


def _warm_summaries(user_id: str, today: date) -> dict:
    from backend.services.athlete_summaries import (
        NoMonthlySessions,
        compute_monthly_summary,
        compute_weekly_summary,
    )

    this_monday = _monday_on_or_before(today)
    last_monday = this_monday - timedelta(days=7)
    weeks = []
    for ws in (this_monday, last_monday):
        try:
            compute_weekly_summary(user_id, ws)
            weeks.append(ws.isoformat())
        except Exception:
            _log.exception("precompute weekly summary failed for %s week %s", user_id, ws)

    months = []
    for ms in (_month_start(today), _prev_month_start(today)):
        try:
            compute_monthly_summary(user_id, ms)
            months.append(ms.isoformat())
        except NoMonthlySessions:
            months.append(ms.isoformat() + ":empty")
        except Exception:
            _log.exception("precompute monthly summary failed for %s month %s", user_id, ms)

    return {"weeks": weeks, "months": months}


def _warm_plan_bundle(user_id: str) -> str:
    """Refresh performance + PRs on the stored plan bundle without importing main.

    Race-readiness estimates stay as last Recalculate/first-compute left them;
    GET /api/plan/computed serves the stored JSON regardless of signature.
    """
    from sqlalchemy.orm import Session

    from backend.db import engine
    from backend.models import TrainingPlan, User
    from backend.services.performance_scores import get_performance_payload
    from backend.services.pr_detection import fetch_and_detect_records

    uid = _uuid.UUID(str(user_id))
    perf = get_performance_payload(uid)  # cache already forced above; this is a hit
    p_state = perf.get("state")
    current_scores = {
        "endurance": (perf.get("endurance") or {}).get("score") if p_state == "scored" else None,
        "speed": (perf.get("speed") or {}).get("score") if p_state == "scored" else None,
        "endurance_dir": (perf.get("endurance") or {}).get("direction"),
        "speed_dir": (perf.get("speed") or {}).get("direction"),
        "state": p_state,
    }

    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            return "no-user"
        raw = fetch_and_detect_records(uid, session)
        raw.pop("_meta", None)
        plan = (
            session.query(TrainingPlan)
            .filter(TrainingPlan.user_id == uid)
            .order_by(TrainingPlan.created_at.asc())
            .first()
        )
        if plan is None:
            plan = TrainingPlan(user_id=uid, name="Training Plan")
            session.add(plan)
            session.flush()
        bundle = dict(plan.computed_cache or {})
        bundle["generated_at"] = datetime.now(timezone.utc).isoformat()
        bundle["performance"] = perf
        bundle["prs"] = raw
        bundle["current_scores"] = current_scores
        plan.computed_cache = bundle
        session.commit()
    return "overlayed" if bundle.get("races") else "seeded"


def precompute_user(
    user_id: str,
    *,
    dates: Optional[Iterable[Any]] = None,
    as_of: Optional[date] = None,
) -> dict:
    """Warm load snapshots and dashboard caches for ``user_id``.

    Always warms today and yesterday (what ``current_load()`` reads on the hot
    path). Any extra ``dates`` (e.g. the date of an edited/deleted workout) are
    warmed too. Then refreshes performance scores, weekly/monthly summaries,
    and the plan-bundle overlay so the next page load is a cache hit.

    Idempotent — snapshot and summary_cache upserts are ON CONFLICT DO UPDATE.
    """
    end = as_of or today_bangkok()
    out: dict = {"user_id": str(user_id)}

    out["warmed"] = _warm_load_snapshots(user_id, dates, end)
    _log.info("precompute warmed load snapshots for %s: %s", user_id, list(out["warmed"]))

    try:
        out["performance"] = _warm_performance(user_id)
    except Exception:
        _log.exception("precompute performance failed for %s", user_id)
        out["performance"] = "error"

    try:
        out["summaries"] = _warm_summaries(user_id, end)
    except Exception:
        _log.exception("precompute summaries failed for %s", user_id)
        out["summaries"] = "error"

    try:
        out["plan_bundle"] = _warm_plan_bundle(user_id)
    except Exception:
        _log.exception("precompute plan bundle failed for %s", user_id)
        out["plan_bundle"] = "error"

    return out
