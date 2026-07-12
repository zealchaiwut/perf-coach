"""Weekly cut review: compares actual EWMA loss rate against the active plan (issue #1355).
Lean-mass guard added in issue #1359.

Exposes:
  compute_cut_recommendation(**kwargs) -> dict   — pure function, unit-tested
  compute_losing_lean_mass_flag(readings) -> bool — pure: two bf readings ≥14d apart,
                                                    lean fell >0.3 kg and weight also fell
  get_weekly_review(user_id, as_of_date, db)     — DB-backed computation for the endpoint

The recommendation enum (first match wins):
  insufficient_data | slow_down | on_track | check_logging |
  recalibrate_maintenance | increase_deficit | ease_off
"""
from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.db import engine
from backend.services.body_modifier import compute_body_modifier_guardrail
from backend.services.fuel import (
    DEFICIT_KCAL_MAX,
    compute_budget,
    compute_food_totals,
    get_or_create_settings,
    settings_to_dict,
    training_burn_kcal,
)
from backend.services.weight_ewma import compute_ewma
from backend.services.weight_ewma_rate import compute_weekly_pct_bw_rate_of_change

# ── Thresholds ────────────────────────────────────────────────────────────────

ON_TRACK_TOLERANCE_KG: float = 0.10
EASE_OFF_THRESHOLD_KG: float = 0.15
MIN_ADHERENCE_PCT: float = 70.0
MIN_WEIGH_INS_14D: int = 4
AT_BUDGET_TOLERANCE_KCAL: float = 100.0
RECALIBRATE_WEEKS_THRESHOLD: int = 3
DEFICIT_STEP_KCAL: int = 100

# Lean-mass guard threshold (issue #1359)
LEAN_MASS_LOSS_THRESHOLD_KG: float = 0.3
LEAN_MASS_MIN_DAYS_APART: int = 14


# ── Lean-mass guard (issue #1359) ─────────────────────────────────────────────

def compute_losing_lean_mass_flag(readings: list) -> bool:
    """Return True when two body-fat readings ≥14 days apart show lean mass
    falling >0.3 kg while total weight also fell.

    readings: list of dicts with keys 'date' (datetime.date), 'body_fat_pct'
              (float, as a percentage 0–100), 'weight_kg' (float).
    Returns False when there are fewer than two readings or no pair is ≥14 days apart.
    """
    if len(readings) < 2:
        return False

    sorted_readings = sorted(readings, key=lambda r: r["date"])
    older = sorted_readings[0]
    newer = sorted_readings[-1]

    days_apart = (newer["date"] - older["date"]).days
    if days_apart < LEAN_MASS_MIN_DAYS_APART:
        return False

    bf_older = float(older["body_fat_pct"])
    bf_newer = float(newer["body_fat_pct"])
    w_older = float(older["weight_kg"])
    w_newer = float(newer["weight_kg"])

    lean_older = w_older * (1.0 - bf_older / 100.0)
    lean_newer = w_newer * (1.0 - bf_newer / 100.0)

    lean_loss = lean_older - lean_newer
    weight_fell = w_newer < w_older

    return lean_loss > LEAN_MASS_LOSS_THRESHOLD_KG and weight_fell


# ── Pure recommendation function ──────────────────────────────────────────────

def compute_cut_recommendation(
    *,
    weigh_in_count_14d: int,
    has_active_plan: bool,
    actual_rate_kg_per_week: float,
    plan_rate_kg_per_week: float,
    weekly_pct_bw_rate: float,
    ea_proxy: float,
    logging_adherence_pct: float,
    avg_intake_vs_budget_kcal: float,
    consecutive_weeks_behind: int,
    pct_logged_days_at_or_under_budget: float,
    current_deficit_kcal: int,
    losing_lean_mass: bool = False,
) -> dict:
    """Return recommendation, action text, optional deficit step, and losing_lean_mass flag.

    Parameters
    ----------
    actual_rate_kg_per_week:
        Signed: negative = losing weight.
    plan_rate_kg_per_week:
        Signed: negative = losing weight.
    weekly_pct_bw_rate:
        Signed: negative = losing (%BW/wk).
    ea_proxy:
        Energy-availability proxy in [0, 1] from daily_metrics.energy.
    losing_lean_mass:
        True when the lean-mass guard (issue #1359) detects falling lean mass
        alongside falling total weight — appended to the payload as a warning
        flag; does not change recommendation precedence.
    """
    # 1. Insufficient data
    if weigh_in_count_14d < MIN_WEIGH_INS_14D or not has_active_plan:
        return {
            "recommendation": "insufficient_data",
            "action": (
                "Log at least 4 weigh-ins over 14 days and set an active plan "
                "to get a weekly review."
            ),
            "suggested_deficit_delta_kcal": None,
            "losing_lean_mass": losing_lean_mass,
        }

    # 2. Slow down — guardrail takes absolute priority
    guardrail = compute_body_modifier_guardrail(
        weekly_pct_bw_rate=weekly_pct_bw_rate,
        ea_proxy=ea_proxy,
    )
    if guardrail["guardrail_state"] == "warn":
        return {
            "recommendation": "slow_down",
            "action": (
                "Reduce your deficit by 100–200 kcal — losing at this pace "
                "risks muscle loss and performance."
            ),
            "suggested_deficit_delta_kcal": -DEFICIT_STEP_KCAL,
            "losing_lean_mass": losing_lean_mass,
        }

    # 3. On track
    if abs(actual_rate_kg_per_week - plan_rate_kg_per_week) <= ON_TRACK_TOLERANCE_KG:
        return {
            "recommendation": "on_track",
            "action": "Keep going — your loss rate is matching the plan.",
            "suggested_deficit_delta_kcal": None,
            "losing_lean_mass": losing_lean_mass,
        }

    behind = actual_rate_kg_per_week > plan_rate_kg_per_week
    ahead = actual_rate_kg_per_week < plan_rate_kg_per_week

    # 4. Check logging
    if behind and logging_adherence_pct < MIN_ADHERENCE_PCT:
        return {
            "recommendation": "check_logging",
            "action": (
                "Log your food more consistently (aim for 5+ days/week) "
                "to diagnose the gap."
            ),
            "suggested_deficit_delta_kcal": None,
            "losing_lean_mass": losing_lean_mass,
        }

    # 5. Recalibrate maintenance
    if (
        behind
        and consecutive_weeks_behind >= RECALIBRATE_WEEKS_THRESHOLD
        and pct_logged_days_at_or_under_budget >= MIN_ADHERENCE_PCT
    ):
        return {
            "recommendation": "recalibrate_maintenance",
            "action": (
                "Your maintenance may be higher than estimated. "
                "Use 'Calibrate from history' in Fuel settings."
            ),
            "suggested_deficit_delta_kcal": None,
            "losing_lean_mass": losing_lean_mass,
        }

    # 6. Increase deficit
    if behind:
        at_budget = avg_intake_vs_budget_kcal >= -AT_BUDGET_TOLERANCE_KCAL
        if at_budget:
            new_deficit = current_deficit_kcal + DEFICIT_STEP_KCAL
            clamped = min(new_deficit, DEFICIT_KCAL_MAX)
            if clamped > current_deficit_kcal:
                return {
                    "recommendation": "increase_deficit",
                    "action": (
                        f"Increase your deficit by {DEFICIT_STEP_KCAL} kcal "
                        f"(to {clamped} kcal/day)."
                    ),
                    "suggested_deficit_delta_kcal": DEFICIT_STEP_KCAL,
                    "losing_lean_mass": losing_lean_mass,
                }

    # 7. Ease off
    if ahead and (plan_rate_kg_per_week - actual_rate_kg_per_week) > EASE_OFF_THRESHOLD_KG:
        return {
            "recommendation": "ease_off",
            "action": (
                f"Reduce your deficit by {DEFICIT_STEP_KCAL} kcal to slow the pace."
            ),
            "suggested_deficit_delta_kcal": -DEFICIT_STEP_KCAL,
            "losing_lean_mass": losing_lean_mass,
        }

    # Fallback
    return {
        "recommendation": "on_track",
        "action": "Keep going — your loss rate is close to plan.",
        "suggested_deficit_delta_kcal": None,
        "losing_lean_mass": losing_lean_mass,
    }


# ── DB-backed computation ─────────────────────────────────────────────────────

def get_weekly_review(
    user_id,
    as_of_date: Optional[_date] = None,
    db: Optional[Session] = None,
) -> dict:
    """Fetch trailing 7 / 21 day data from the DB and compute the weekly review."""
    from backend.models import BodyMeasurement, FuelEntry, WeightEntry, WeightPlan
    from sqlalchemy import text

    today = as_of_date or _date.today()
    window_7d_start = today - timedelta(days=7)
    window_14d_start = today - timedelta(days=14)
    window_21d_start = today - timedelta(days=21)
    window_60d_start = today - timedelta(days=60)

    owns_db = db is None
    db = db or Session(engine)
    try:
        # ── Active plan ───────────────────────────────────────────────────────
        plan = (
            db.query(WeightPlan)
            .filter(WeightPlan.user_id == user_id, WeightPlan.active.is_(True))
            .first()
        )
        has_plan = plan is not None
        plan_rate = float(plan.target_rate_kg_per_week) if (plan and plan.target_rate_kg_per_week is not None) else None
        current_deficit_kcal = 0

        settings_row = get_or_create_settings(user_id, db=db)
        settings = settings_to_dict(settings_row)
        current_deficit_kcal = settings["deficit_kcal"]

        # ── Weight entries (21-day window for EWMA + 3-week check) ────────────
        weight_rows = (
            db.query(WeightEntry)
            .filter(
                WeightEntry.user_id == user_id,
                WeightEntry.entry_date >= window_21d_start,
                WeightEntry.entry_date <= today,
            )
            .order_by(WeightEntry.entry_date.asc())
            .all()
        )

        by_day: dict = {}
        for w in weight_rows:
            by_day[w.entry_date] = float(w.weight_kg)
        sorted_entries = sorted(by_day.items())

        weigh_in_count_14d = sum(1 for d, _ in sorted_entries if d >= window_14d_start)

        ewma_entries = [{"date": d, "weight_kg": w} for d, w in sorted_entries]
        ewma_values = compute_ewma(ewma_entries) if ewma_entries else []

        pct_rate_7d: Optional[float] = None
        actual_rate_kg_per_week: Optional[float] = None
        weekly_pct_bw_rate: float = 0.0

        if len(ewma_values) >= 2:
            pct_rate_7d = compute_weekly_pct_bw_rate_of_change(ewma_values)
            if pct_rate_7d is not None:
                weekly_pct_bw_rate = pct_rate_7d
                actual_rate_kg_per_week = (pct_rate_7d / 100.0) * ewma_entries[0]["weight_kg"]

        # ── 3-week consecutive behind check ───────────────────────────────────
        consecutive_weeks_behind = 0
        if plan_rate is not None and actual_rate_kg_per_week is not None:
            week_buckets = [
                (today - timedelta(days=7), today),
                (today - timedelta(days=14), today - timedelta(days=7)),
                (today - timedelta(days=21), today - timedelta(days=14)),
            ]
            streak = 0
            for w_start, w_end in week_buckets:
                week_entries = [
                    {"date": d, "weight_kg": w}
                    for d, w in sorted_entries
                    if w_start <= d <= w_end
                ]
                if len(week_entries) < 2:
                    break
                week_ewma = compute_ewma(week_entries)
                week_pct = compute_weekly_pct_bw_rate_of_change(week_ewma)
                if week_pct is None:
                    break
                week_rate_kg = (week_pct / 100.0) * week_entries[0]["weight_kg"]
                if week_rate_kg > plan_rate:
                    streak += 1
                else:
                    break
            consecutive_weeks_behind = streak

        # ── Fuel entries (7-day window) ───────────────────────────────────────
        fuel_rows = (
            db.query(FuelEntry)
            .filter(
                FuelEntry.user_id == user_id,
                FuelEntry.entry_date > window_7d_start,
                FuelEntry.entry_date <= today,
            )
            .all()
        )

        logged_day_intakes = []
        logged_day_budgets = []
        for fe in fuel_rows:
            totals = compute_food_totals(fe)
            burn_info = training_burn_kcal(
                user_id, fe.entry_date,
                settings["weight_kg"], settings["run_kcal_per_kg_per_km"],
                today=today, db=db,
            )
            budget_info = compute_budget(settings, burn_info["burn"])
            logged_day_intakes.append(totals["kcal"])
            logged_day_budgets.append(budget_info["budget"])

        logging_adherence_pct = len(fuel_rows) / 7.0 * 100.0

        avg_intake_vs_budget_kcal: Optional[float] = None
        pct_at_or_under: float = 0.0
        if logged_day_intakes:
            diffs = [i - b for i, b in zip(logged_day_intakes, logged_day_budgets)]
            avg_intake_vs_budget_kcal = sum(diffs) / len(diffs)
            at_or_under = sum(1 for d in diffs if d <= 0)
            pct_at_or_under = at_or_under / len(diffs) * 100.0

        # ── EA proxy from daily_metrics.energy ───────────────────────────────
        energy_sql = text(
            """
            SELECT energy
            FROM daily_metrics
            WHERE user_id = :uid
              AND metric_date > :from_date
              AND metric_date <= :to_date
              AND energy IS NOT NULL
            """
        )
        energy_rows = db.execute(
            energy_sql,
            {"uid": str(user_id), "from_date": window_7d_start, "to_date": today},
        ).fetchall()

        ea_proxy: float = 1.0
        if energy_rows:
            avg_energy = sum(float(r[0]) for r in energy_rows) / len(energy_rows)
            ea_proxy = (avg_energy - 1.0) / 4.0

        # ── Lean-mass guard (issue #1359) ────────────────────────────────────
        # Fetch body-fat readings within 60 days; pair oldest + newest in window
        # to check for lean mass loss during a cut.
        bf_rows = (
            db.query(BodyMeasurement)
            .filter(
                BodyMeasurement.user_id == user_id,
                BodyMeasurement.measure_date >= window_60d_start,
                BodyMeasurement.measure_date <= today,
                BodyMeasurement.body_fat_pct.isnot(None),
            )
            .order_by(BodyMeasurement.measure_date.asc())
            .all()
        )

        all_weight_rows_60d = (
            db.query(WeightEntry)
            .filter(
                WeightEntry.user_id == user_id,
                WeightEntry.entry_date >= window_60d_start,
                WeightEntry.entry_date <= today,
            )
            .order_by(WeightEntry.entry_date.asc())
            .all()
        )
        weight_by_day_60d: dict = {}
        for w in all_weight_rows_60d:
            weight_by_day_60d[w.entry_date] = float(w.weight_kg)

        bf_readings_for_guard = []
        for row in bf_rows:
            w = weight_by_day_60d.get(row.measure_date)
            if w is not None:
                bf_readings_for_guard.append({
                    "date": row.measure_date,
                    "body_fat_pct": float(row.body_fat_pct),
                    "weight_kg": w,
                })

        losing_lean_mass = compute_losing_lean_mass_flag(bf_readings_for_guard)

        # ── Build recommendation ──────────────────────────────────────────────
        rec = compute_cut_recommendation(
            weigh_in_count_14d=weigh_in_count_14d,
            has_active_plan=has_plan and plan_rate is not None,
            actual_rate_kg_per_week=actual_rate_kg_per_week if actual_rate_kg_per_week is not None else 0.0,
            plan_rate_kg_per_week=plan_rate if plan_rate is not None else 0.0,
            weekly_pct_bw_rate=weekly_pct_bw_rate,
            ea_proxy=ea_proxy,
            logging_adherence_pct=logging_adherence_pct,
            avg_intake_vs_budget_kcal=avg_intake_vs_budget_kcal if avg_intake_vs_budget_kcal is not None else 0.0,
            consecutive_weeks_behind=consecutive_weeks_behind,
            pct_logged_days_at_or_under_budget=pct_at_or_under,
            current_deficit_kcal=current_deficit_kcal,
            losing_lean_mass=losing_lean_mass,
        )

        return {
            "actual_rate_kg_per_week": (
                round(actual_rate_kg_per_week, 3) if actual_rate_kg_per_week is not None else None
            ),
            "plan_rate_kg_per_week": round(plan_rate, 3) if plan_rate is not None else None,
            "logging_adherence_pct": round(logging_adherence_pct, 1),
            "avg_intake_vs_budget_kcal": (
                round(avg_intake_vs_budget_kcal, 1) if avg_intake_vs_budget_kcal is not None else None
            ),
            "recommendation": rec["recommendation"],
            "action": rec["action"],
            "suggested_deficit_delta_kcal": rec["suggested_deficit_delta_kcal"],
            "losing_lean_mass": rec["losing_lean_mass"],
        }

    finally:
        if owns_db:
            db.close()
