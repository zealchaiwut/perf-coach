"""Rebuild status for weekly checklist UI (WC-13)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session


def plan_build_status(db: Session, user_id, *, week_start: date | None = None) -> dict:
    """Return updating | up_to_date with last_built timestamp."""
    from backend.models import PlanDraft
    from backend.services import job_queue as jq
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    ws = week_start or (today - __import__("datetime").timedelta(days=today.weekday()))

    pending = jq.list_for_user(str(user_id), statuses=("queued", "running"), limit=5)
    plan_jobs = [j for j in pending if j.get("job_type") == "plan_draft"]
    state = "updating" if plan_jobs else "up_to_date"

    draft = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == ws)
        .first()
    )
    last_built: str | None = None
    if draft and draft.updated_at:
        last_built = draft.updated_at.astimezone(timezone.utc).isoformat()

    return {
        "state": state,
        "status": state,
        "week_start": ws.isoformat(),
        "last_built": last_built,
        "last_built_at": last_built,
        "draft_status": draft.status if draft else None,
        "pending_job_id": str(plan_jobs[0]["id"]) if plan_jobs else None,
    }


def enqueue_week_rebuild(
    user_id,
    week_start: date | None = None,
    *,
    remaining_days_only: bool = False,
    enqueued_by: str = "web",
) -> str | None:
    """Enqueue a plan_draft job (full week or remaining days partial)."""
    from backend.services.plan_draft import enqueue_plan_draft, pipeline_enabled
    from backend.utils.time import today_bangkok

    if not pipeline_enabled():
        return None
    today = today_bangkok()
    ws = week_start or (today - __import__("datetime").timedelta(days=today.weekday()))
    _ = remaining_days_only  # full-week regen; apply_draft skips past days
    return enqueue_plan_draft(user_id, ws, enqueued_by=enqueued_by)
