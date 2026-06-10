"""Weight plan math: interpolation, gap analysis, milestone generation (issue #420)."""
from __future__ import annotations

import calendar
import datetime
from decimal import Decimal
from typing import Optional


def plan_at(target, on_date: datetime.date) -> Decimal:
    """Linear interpolation between start and target weight; clamped at both ends."""
    start_d = _as_date(target.start_date)
    target_d = _as_date(target.target_date)
    start_w = Decimal(str(target.start_weight_kg))
    target_w = Decimal(str(target.target_weight_kg))

    if on_date <= start_d:
        return start_w
    if on_date >= target_d:
        return target_w

    total_days = (target_d - start_d).days
    elapsed = (on_date - start_d).days
    t = Decimal(elapsed) / Decimal(total_days)
    return start_w + (target_w - start_w) * t


def compute_gap(target, session, as_of_date: datetime.date) -> dict:
    """Return gap analysis dict for the given target and date.

    Shape: {plan_today_kg, current_basis_kg, basis, gap_kg, gap_direction}
    basis: 'avg_7d' | 'latest_entry' | None
    gap_direction: 'behind' | 'ahead' | 'on_plan' | 'no_data'
    """
    from backend.models import WeightEntry  # local import to avoid circular dep

    plan_today = plan_at(target, as_of_date)

    window_7_start = as_of_date - datetime.timedelta(days=6)
    window_14_start = as_of_date - datetime.timedelta(days=13)

    entries_7d = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == target.user_id,
            WeightEntry.entry_date >= window_7_start,
            WeightEntry.entry_date <= as_of_date,
        )
        .order_by(WeightEntry.entry_date.desc())
        .all()
    )

    current_basis: Optional[Decimal] = None
    basis_label: Optional[str] = None

    if len(entries_7d) >= 3:
        avg = sum(Decimal(str(e.weight_kg)) for e in entries_7d) / len(entries_7d)
        current_basis = avg
        basis_label = "avg_7d"
    else:
        # Try latest single entry within 14 days
        entries_14d = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == target.user_id,
                WeightEntry.entry_date >= window_14_start,
                WeightEntry.entry_date <= as_of_date,
            )
            .order_by(WeightEntry.entry_date.desc())
            .all()
        )
        if entries_14d:
            current_basis = Decimal(str(entries_14d[0].weight_kg))
            basis_label = "latest_entry"

    if current_basis is None:
        return {
            "plan_today_kg": float(round(plan_today, 1)),
            "current_basis_kg": None,
            "basis": None,
            "gap_kg": None,
            "gap_direction": "no_data",
        }

    gap = current_basis - plan_today
    gap_direction = _gap_direction(gap, target)

    return {
        "plan_today_kg": float(round(plan_today, 1)),
        "current_basis_kg": float(round(current_basis, 2)),
        "basis": basis_label,
        "gap_kg": float(round(gap, 2)),
        "gap_direction": gap_direction,
    }


def generate_milestones(target, as_of_date: datetime.date) -> list:
    """Return milestone list: today + 0-2 intermediate stones + goal.

    Each stone: {date, plan_kg, kind}
    Intermediate stones are at 1/3 and 2/3 of remaining days, rounded to 1st of nearest month.
    Collisions are deduped.
    """
    target_d = _as_date(target.target_date)
    remaining_days = (target_d - as_of_date).days

    today_stone = {
        "date": str(as_of_date),
        "plan_kg": float(round(plan_at(target, as_of_date), 1)),
        "kind": "today",
    }
    goal_stone = {
        "date": str(target_d),
        "plan_kg": float(round(Decimal(str(target.target_weight_kg)), 1)),
        "kind": "goal",
    }

    if remaining_days <= 0:
        return [today_stone, goal_stone]

    # Intermediate stones at 1/3 and 2/3 of remaining days
    d1 = as_of_date + datetime.timedelta(days=remaining_days // 3)
    d2 = as_of_date + datetime.timedelta(days=remaining_days * 2 // 3)

    m1 = _snap_to_month_start(d1)
    m2 = _snap_to_month_start(d2)

    seen_dates = {str(as_of_date), str(target_d)}
    intermediates = []
    for ms in [m1, m2]:
        key = str(ms)
        if key in seen_dates:
            continue
        seen_dates.add(key)
        intermediates.append({
            "date": key,
            "plan_kg": float(round(plan_at(target, ms), 1)),
            "kind": "intermediate",
        })

    return [today_stone] + intermediates + [goal_stone]


# ── private helpers ───────────────────────────────────────────────────────────

def _as_date(d) -> datetime.date:
    if isinstance(d, datetime.date):
        return d
    return datetime.date.fromisoformat(str(d))


def _gap_direction(gap: Decimal, target) -> str:
    """Determine gap direction accounting for target type (loss vs gain)."""
    is_loss = Decimal(str(target.target_weight_kg)) < Decimal(str(target.start_weight_kg))
    if abs(gap) <= Decimal("0.2"):
        return "on_plan"
    if is_loss:
        return "behind" if gap > 0 else "ahead"
    return "ahead" if gap > 0 else "behind"


def _snap_to_month_start(d: datetime.date) -> datetime.date:
    """Round date to nearest 1st-of-month."""
    # First of current month
    first_this = d.replace(day=1)
    # First of next month
    if d.month == 12:
        first_next = datetime.date(d.year + 1, 1, 1)
    else:
        first_next = datetime.date(d.year, d.month + 1, 1)

    days_to_this = abs((d - first_this).days)
    days_to_next = abs((first_next - d).days)

    return first_this if days_to_this <= days_to_next else first_next
