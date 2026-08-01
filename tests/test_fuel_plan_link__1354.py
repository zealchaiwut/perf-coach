"""Tests for fuel ↔ weight plan linkage (issue #1354).

Covers AC items:
  AC1 — implied_deficit_kcal() helper math, rounding, clamping
  AC2 — plan_linkage(): all three consistency states (aligned, mismatch, no_plan)
  AC3 — sync-deficit service logic and 409 guard when no plan
  AC4 — payload fields present in all three states

"The active plan" used to be a separate `weight_plans` row; #1604 (schema
consolidation) merged it onto `WeightTarget` (phase, target_rate_kg_per_week
columns). These tests were updated to create WeightTarget rows instead —
plan_linkage() itself is unchanged, since it only ever duck-typed on
`.target_rate_kg_per_week`.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import FuelSettings, User, WeightTarget
from backend.services import fuel, weight_plan as weight_plan_svc


# ── AC1: implied_deficit_kcal helper ─────────────────────────────────────────

def test_implied_deficit_half_kg_per_week():
    # 0.5 * 7700 / 7 = 550.0, round-to-10 = 550
    assert fuel.implied_deficit_kcal(0.5) == 550


def test_implied_deficit_negative_rate_uses_abs():
    # Cut plans carry negative rates; abs() should give the same result
    assert fuel.implied_deficit_kcal(-0.5) == 550


def test_implied_deficit_rounds_to_nearest_10_exact():
    # 0.3 * 7700 / 7 = 330.0 -> 330
    assert fuel.implied_deficit_kcal(0.3) == 330


def test_implied_deficit_zero_rate_gives_zero():
    assert fuel.implied_deficit_kcal(0.0) == 0


def test_implied_deficit_clamps_above_750():
    # 1.5 * 7700 / 7 = 1650 -> clamped to 750
    assert fuel.implied_deficit_kcal(1.5) == 750


def test_implied_deficit_does_not_exceed_750_for_any_rate():
    for rate in [0.7, 0.8, 1.0, 2.0, 10.0]:
        assert fuel.implied_deficit_kcal(rate) <= 750


def test_implied_deficit_at_1_tenth_kg():
    # 0.1 * 7700 / 7 = 110.0 -> 110
    assert fuel.implied_deficit_kcal(0.1) == 110


# ── AC2: plan_linkage pure function ──────────────────────────────────────────

class _FakePlan:
    def __init__(self, rate, active=True):
        self.target_rate_kg_per_week = rate
        self.active = active


def test_plan_linkage_no_plan_gives_no_plan_consistency():
    result = fuel.plan_linkage(None, 300)
    assert result["consistency"] == "no_plan"
    assert result["plan_rate_kg_per_week"] is None
    assert result["implied_deficit_kcal"] is None
    assert result["deficit_gap_kcal"] is None


def test_plan_linkage_no_rate_on_plan_gives_no_plan():
    result = fuel.plan_linkage(_FakePlan(rate=None), 300)
    assert result["consistency"] == "no_plan"


def test_plan_linkage_aligned_when_gap_le_100():
    # implied = 550, configured = 500, gap = 50 -> aligned
    result = fuel.plan_linkage(_FakePlan(rate=0.5), 500)
    assert result["consistency"] == "aligned"
    assert result["implied_deficit_kcal"] == 550
    assert result["deficit_gap_kcal"] == 50


def test_plan_linkage_mismatch_when_gap_gt_100():
    # implied = 550, configured = 300, gap = 250 -> mismatch
    result = fuel.plan_linkage(_FakePlan(rate=0.5), 300)
    assert result["consistency"] == "mismatch"
    assert result["deficit_gap_kcal"] == 250


def test_plan_linkage_aligned_at_exact_100_boundary():
    # gap == 100 -> aligned (<=100)
    result = fuel.plan_linkage(_FakePlan(rate=0.5), 450)
    assert result["implied_deficit_kcal"] == 550
    assert result["deficit_gap_kcal"] == 100
    assert result["consistency"] == "aligned"


def test_plan_linkage_mismatch_just_over_100_boundary():
    # gap == 101 -> mismatch
    result = fuel.plan_linkage(_FakePlan(rate=0.5), 449)
    assert result["deficit_gap_kcal"] == 101
    assert result["consistency"] == "mismatch"


def test_plan_linkage_negative_rate_produces_positive_implied_deficit():
    # Cut plan stores rate as negative; plan_rate passes through as-is
    result = fuel.plan_linkage(_FakePlan(rate=-0.5), 300)
    assert result["plan_rate_kg_per_week"] == -0.5
    assert result["implied_deficit_kcal"] == 550


# ── AC4: payload fields — all three states (DB-backed) ───────────────────────

@pytest.fixture()
def plan_link_user():
    with Session(engine) as db:
        uid = uuid.uuid4()
        db.add(User(id=uid, name=f"planlink_{uid.hex[:8]}", password_hash="x",
                    is_admin=False, is_active=True))
        db.commit()
        yield uid
        db.query(FuelSettings).filter(FuelSettings.user_id == uid).delete()
        db.query(WeightTarget).filter(WeightTarget.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def _build_payload(user_id, db):
    settings_row = fuel.get_or_create_settings(user_id, db=db)
    active_plan = weight_plan_svc.get_active_target(db, user_id)
    payload = fuel.settings_to_dict(settings_row)
    payload.update(fuel.plan_linkage(active_plan, settings_row.deficit_kcal))
    return payload


def test_settings_payload_no_plan_state(plan_link_user):
    with Session(engine) as db:
        payload = _build_payload(plan_link_user, db)
    assert "consistency" in payload
    assert "plan_rate_kg_per_week" in payload
    assert "implied_deficit_kcal" in payload
    assert "deficit_gap_kcal" in payload
    assert payload["consistency"] == "no_plan"
    assert payload["plan_rate_kg_per_week"] is None


def test_settings_payload_mismatch_state(plan_link_user):
    # Plan: 0.5 kg/wk -> implied 550; configured 300 -> gap 250 -> mismatch
    with Session(engine) as db:
        db.add(WeightTarget(
            user_id=plan_link_user,
            start_date=date(2026, 1, 1),
            start_weight_kg=80.0,
            target_date=date(2026, 6, 1),
            target_weight_kg=76.0,
            target_rate_kg_per_week=-0.5,
            status="active",
        ))
        db.commit()
        fuel.update_settings(plan_link_user, db=db, deficit_kcal=300)
        payload = _build_payload(plan_link_user, db)

    assert payload["consistency"] == "mismatch"
    assert payload["implied_deficit_kcal"] == 550
    assert payload["deficit_gap_kcal"] == 250
    assert payload["plan_rate_kg_per_week"] == -0.5


def test_settings_payload_aligned_state(plan_link_user):
    # Plan: 0.5 kg/wk -> implied 550; configured 550 -> gap 0 -> aligned
    with Session(engine) as db:
        db.add(WeightTarget(
            user_id=plan_link_user,
            start_date=date(2026, 1, 1),
            start_weight_kg=80.0,
            target_date=date(2026, 6, 1),
            target_weight_kg=76.0,
            target_rate_kg_per_week=-0.5,
            status="active",
        ))
        db.commit()
        fuel.update_settings(plan_link_user, db=db, deficit_kcal=550)
        payload = _build_payload(plan_link_user, db)

    assert payload["consistency"] == "aligned"
    assert payload["deficit_gap_kcal"] == 0


# ── AC3: sync-deficit logic ───────────────────────────────────────────────────

def test_sync_deficit_updates_deficit_to_implied_value(plan_link_user):
    with Session(engine) as db:
        db.add(WeightTarget(
            user_id=plan_link_user,
            start_date=date(2026, 1, 1),
            start_weight_kg=80.0,
            target_date=date(2026, 6, 1),
            target_weight_kg=76.0,
            target_rate_kg_per_week=-0.5,
            status="active",
        ))
        db.commit()
        fuel.update_settings(plan_link_user, db=db, deficit_kcal=300)

        active_plan = weight_plan_svc.get_active_target(db, plan_link_user)
        assert active_plan is not None
        new_deficit = fuel.implied_deficit_kcal(float(active_plan.target_rate_kg_per_week))
        fuel.update_settings(plan_link_user, db=db, deficit_kcal=new_deficit)

        row = fuel.get_or_create_settings(plan_link_user, db=db)
        assert row.deficit_kcal == 550


def test_sync_deficit_no_active_plan_returns_none(plan_link_user):
    """Route should 409 when get_active_plan returns None."""
    with Session(engine) as db:
        result = weight_plan_svc.get_active_target(db, plan_link_user)
    assert result is None
