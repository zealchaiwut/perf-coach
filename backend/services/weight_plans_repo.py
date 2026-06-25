"""Repository layer for WeightPlan: all DB access for the weight-plans CRUD API (issue #864)."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import WeightPlan


def get_active_plan(session: Session, user_id: uuid.UUID) -> Optional[WeightPlan]:
    return (
        session.query(WeightPlan)
        .filter(WeightPlan.user_id == user_id, WeightPlan.active.is_(True))
        .first()
    )


def get_plan_by_id(session: Session, plan_id: uuid.UUID) -> Optional[WeightPlan]:
    return session.get(WeightPlan, plan_id)


def deactivate_all_for_user(session: Session, user_id: uuid.UUID) -> None:
    """Set active=False on every plan owned by this user (called before creating a new one)."""
    session.query(WeightPlan).filter(
        WeightPlan.user_id == user_id, WeightPlan.active.is_(True)
    ).update({"active": False}, synchronize_session="fetch")


def create_plan(
    session: Session,
    *,
    user_id: uuid.UUID,
    start_date,
    start_weight_kg,
    goal_weight_kg,
    goal_date=None,
    target_rate_kg_per_week=None,
    phase: str = "cut",
) -> WeightPlan:
    deactivate_all_for_user(session, user_id)
    plan = WeightPlan(
        user_id=user_id,
        start_date=start_date,
        start_weight_kg=start_weight_kg,
        goal_weight_kg=goal_weight_kg,
        goal_date=goal_date,
        target_rate_kg_per_week=target_rate_kg_per_week,
        phase=phase,
        active=True,
    )
    session.add(plan)
    session.flush()
    session.refresh(plan)
    return plan


def update_plan(session: Session, plan: WeightPlan, fields: dict) -> WeightPlan:
    for key, value in fields.items():
        setattr(plan, key, value)
    session.flush()
    session.refresh(plan)
    return plan


def deactivate_plan(session: Session, plan: WeightPlan) -> WeightPlan:
    plan.active = False
    session.flush()
    session.refresh(plan)
    return plan
