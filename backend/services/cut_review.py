"""Weekly cut review: compares actual EWMA loss rate against the active plan (issue #1355).

Exposes:
  compute_cut_recommendation(**kwargs) -> dict   — pure function, unit-tested
  get_weekly_review(user_id, as_of_date, db)     — DB-backed computation for the endpoint

The recommendation enum (first match wins):
  insufficient_data | insufficient_coverage | slow_down | plateau | on_track | check_logging |
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
from backend.services.weight_stats import (
    MIN_N_DAYS as _WEIGHT_STATS_MIN_DAYS,
    weight_stats,
)
from backend.utils.time import today_bangkok

# ── Thresholds ────────────────────────────────────────────────────────────────

# kg/wk tolerance for on_track: |actual − plan| <= this → on_track
ON_TRACK_TOLERANCE_KG: float = 0.10

# kg/wk lead beyond which the user is going too fast — recommend ease_off
EASE_OFF_THRESHOLD_KG: float = 0.15

# Fuel-logging adherence floor; below this we can't diagnose intake vs deficit.
# Only consulted in "managed" mode — see DEFICIT_MODE_STRUCTURAL below.
MIN_ADHERENCE_PCT: float = 70.0

# ── Deficit mode (lean program, spec §7) ─────────────────────────────────────
# The deficit that failed five times was MANAGED: a daily budget, daily
# decisions, daily chances to quit. The lean program's deficit is STRUCTURAL —
# set once (two swaps, calorie cycling, protein at every meal) and verified
# weekly by the weight trend, with no daily food logging at all.
#
# That makes every fuel-log gate below a permanent dead end in structural mode:
# a non-logger has 0% adherence forever, so `check_logging` fires forever and
# the review never says anything useful. In structural mode the diagnosis runs
# off the WEIGHT TREND alone, and `check_logging` keys on weigh-in coverage —
# the one input the athlete actually provides — instead of food logs.
DEFICIT_MODE_STRUCTURAL = "structural"
DEFICIT_MODE_MANAGED = "managed"

# Weigh-ins in the trailing 14 days below which the trend can't be trusted, in
# structural mode. Above MIN_WEIGH_INS_14D but sparse enough that a rate claim
# would be noise.
STRUCTURAL_MIN_WEIGH_INS_14D: int = 6

# Minimum weigh-ins in the last 14 days to produce a reliable recommendation
MIN_WEIGH_INS_14D: int = 4

# "Eating at budget" tolerance: avg intake within this many kcal below budget
AT_BUDGET_TOLERANCE_KCAL: float = 100.0

# Consecutive weeks behind plan needed to suggest recalibrate_maintenance
RECALIBRATE_WEEKS_THRESHOLD: int = 3

# kcal step for increase / ease suggestions
DEFICIT_STEP_KCAL: int = 100

# Plateau detection: rate > this threshold (not losing) for >= 21 consecutive days
PLATEAU_RATE_THRESHOLD_KG: float = -0.1   # rate > this value = not losing
PLATEAU_MIN_DAYS: int = 21


# ── Pure recommendation function ──────────────────────────────────────────────

# Guardrail-triggered copy. Held to deficit_guard's tone contract — "eat more",
# never "try harder" — and checked at import so a drifted string fails here
# rather than in front of the athlete. Only the GUARDRAIL message is bound by
# this: `ease_off` below is a pace adjustment, not a guardrail trip, and is
# deliberately outside the contract.
SLOW_DOWN_COPY = (
    "Eat more — add back 100-200 kcal. Losing at this pace risks muscle "
    "loss and performance."
)

try:  # pragma: no cover - import-time contract check
    from backend.services.deficit_guard import assert_eat_more_copy as _assert_eat_more

    _assert_eat_more(SLOW_DOWN_COPY)
except ImportError:  # deficit_guard is optional at import time in some contexts
    pass


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
    plateau_days: int = 0,
    pct_at_or_under_budget_21d: float = 0.0,
    deficit_mode: str = DEFICIT_MODE_STRUCTURAL,
) -> dict:
    """Return recommendation, action text, and optional deficit step.

    Parameters
    ----------
    actual_rate_kg_per_week:
        Signed: negative = losing weight (matches WeightTarget.target_rate_kg_per_week
        convention — this column lived on a separate weight_plans table before #1604
        merged it onto WeightTarget).
    plan_rate_kg_per_week:
        Signed: negative = losing weight (from WeightTarget.target_rate_kg_per_week).
    weekly_pct_bw_rate:
        Signed: negative = losing (%BW/wk), same convention as body_modifier inputs.
    ea_proxy:
        Energy-availability proxy in [0, 1] from daily_metrics.energy.
    logging_adherence_pct:
        Days with a fuel entry in the trailing 7 days / 7 × 100.
    avg_intake_vs_budget_kcal:
        Average of (eaten_kcal − budget_kcal) over logged days in trailing 7 days.
        Negative = eating under budget.
    consecutive_weeks_behind:
        Count of most-recent consecutive weeks where actual loss rate < plan rate.
    pct_logged_days_at_or_under_budget:
        % of logged days (last 7d) where eaten_kcal <= budget_kcal.
    current_deficit_kcal:
        The user's current deficit setting (used to clamp increase suggestions).
    plateau_days:
        Consecutive days where EWMA weekly rate > PLATEAU_RATE_THRESHOLD_KG (-0.1 kg/wk).
        0 = no plateau. >= PLATEAU_MIN_DAYS (21) + adherence >= 70% triggers plateau.
    pct_at_or_under_budget_21d:
        % of logged days in the trailing 21-day window where eaten_kcal <= budget.
    deficit_mode:
        ``"structural"`` (default) diagnoses from the weight trend alone and
        ignores every fuel-log gate — the lean program's deficit is set once and
        never logged, so demanding food logs returns `check_logging` forever.
        ``"managed"`` keeps the original daily-budget behaviour.
    """
    structural = deficit_mode == DEFICIT_MODE_STRUCTURAL

    # 1. Insufficient data — no reliable recommendation possible.
    #
    # Structural mode does NOT require an active plan. It used to, and that
    # made this the only verdict a lean-program athlete could ever see (issue
    # #1600): `structural` was computed on the line above and then ignored
    # here, so the gate demanded an active plan regardless of mode. At the
    # time "a plan" meant a separate weight_plans row that no UI ever created
    # (`grep -rn "weight-plans" frontend/` returned nothing) — that table was
    # later merged onto WeightTarget (#1604), so "a plan" now means an active
    # WeightTarget, which the real Weight-page flow does create. The
    # structural-mode carve-out below stays regardless, since a WeightTarget
    # still doesn't guarantee target_rate_kg_per_week is set (nothing in the
    # UI sets it either) and structural mode must not depend on that field.
    #
    # That last part is why this could not be fixed by "just set a plan": a hard
    # target weight is precisely the concept weight_hypothesis.py and
    # body_composition.py were built to eliminate ("no target, no goal line").
    # The single documented way to unblock the weekly verdict reintroduced the
    # framing the rest of the feature set exists to remove.
    #
    # The weight trend is sufficient on its own, which is the whole premise of
    # structural mode.
    needs_active_plan = not structural
    if weigh_in_count_14d < MIN_WEIGH_INS_14D or (needs_active_plan and not has_active_plan):
        action = (
            f"Log at least {MIN_WEIGH_INS_14D} weigh-ins over 14 days to get a "
            "weekly review."
        )
        if needs_active_plan and not has_active_plan:
            action = (
                f"Log at least {MIN_WEIGH_INS_14D} weigh-ins over 14 days and set "
                "an active plan to get a weekly review."
            )
        return {
            "recommendation": "insufficient_data",
            "action": action,
            "suggested_deficit_delta_kcal": None,
            "plateau_days": None,
        }

    # 2. Slow down — guardrail takes absolute priority over all deficit logic
    guardrail = compute_body_modifier_guardrail(
        weekly_pct_bw_rate=weekly_pct_bw_rate,
        ea_proxy=ea_proxy,
    )
    if guardrail["guardrail_state"] == "warn":
        return {
            "recommendation": "slow_down",
            # Guardrail-triggered, so it obeys the same tone contract as
            # deficit_guard.PAUSE_COPY: say EAT MORE, blame nobody (#1608).
            # This is the same advice a deficit pause gives; it read in a
            # different voice only because it lived in a different module and
            # sat outside assert_eat_more_copy's coverage.
            "action": SLOW_DOWN_COPY,
            "suggested_deficit_delta_kcal": -DEFICIT_STEP_KCAL,
            "plateau_days": None,
        }

    # 2.5. Plateau — stalled >= 21 days despite staying within budget
    # Structural mode has no budget adherence to check — a 21-day stall in the
    # trend IS the finding, and the swaps either held or they didn't.
    if plateau_days >= PLATEAU_MIN_DAYS and (
        structural or pct_at_or_under_budget_21d >= MIN_ADHERENCE_PCT
    ):
        stalled_because = (
            "with the swaps in place"
            if structural
            else "despite logging within budget"
        )
        return {
            "recommendation": "plateau",
            "action": (
                f"Weight has stalled for {plateau_days} days {stalled_because}. "
                "Consider recalibrating your maintenance estimate "
                "(Fuel: Calibrate from history) "
                "or take a 14-day diet break: set deficit to 0 kcal for 14 days."
            ),
            "suggested_deficit_delta_kcal": None,
            "plateau_days": plateau_days,
        }

    # 3. On track — within tolerance of the plan rate
    if abs(actual_rate_kg_per_week - plan_rate_kg_per_week) <= ON_TRACK_TOLERANCE_KG:
        return {
            "recommendation": "on_track",
            "action": "Keep going — your loss rate is matching the plan.",
            "suggested_deficit_delta_kcal": None,
            "plateau_days": None,
        }

    # Determine direction relative to plan
    # behind = losing less than planned (actual is less negative than plan)
    behind = actual_rate_kg_per_week > plan_rate_kg_per_week
    # ahead = losing more than planned (actual is more negative than plan)
    ahead = actual_rate_kg_per_week < plan_rate_kg_per_week

    # 4. Check logging — the gap can't be diagnosed without enough input.
    # In structural mode the missing input is WEIGH-INS, not food logs: the
    # weight trend is the only measurement this program asks for, so that is the
    # only one it can ask for more of.
    if structural:
        if behind and weigh_in_count_14d < STRUCTURAL_MIN_WEIGH_INS_14D:
            return {
                "recommendation": "check_logging",
                "action": (
                    "Step on the scale most mornings for a week — the trend is "
                    "too sparse to tell whether the swaps are working."
                ),
                "suggested_deficit_delta_kcal": None,
                "plateau_days": None,
            }
    elif behind and logging_adherence_pct < MIN_ADHERENCE_PCT:
        return {
            "recommendation": "check_logging",
            "action": (
                "Log your food more consistently (aim for 5+ days/week) "
                "to diagnose the gap."
            ),
            "suggested_deficit_delta_kcal": None,
            "plateau_days": None,
        }

    # 5. Recalibrate maintenance — persistently behind despite eating at budget
    # Structurally, "same swaps for three weeks and still behind" IS the
    # evidence that the maintenance estimate is wrong — there is no intake log
    # to corroborate it with, and demanding one blocks the finding forever.
    if (
        behind
        and consecutive_weeks_behind >= RECALIBRATE_WEEKS_THRESHOLD
        and (structural or pct_logged_days_at_or_under_budget >= MIN_ADHERENCE_PCT)
    ):
        return {
            "recommendation": "recalibrate_maintenance",
            "action": (
                "Your maintenance may be higher than estimated. "
                "Use 'Calibrate from history' in Fuel settings."
            ),
            "suggested_deficit_delta_kcal": None,
            "plateau_days": None,
        }

    # 6. Increase deficit — behind plan, adherence OK, eating at budget
    if behind:
        # Without food logs there is no intake-vs-budget comparison to make; the
        # trend being behind is itself the signal that the structure needs more.
        at_budget = structural or (
            avg_intake_vs_budget_kcal >= -AT_BUDGET_TOLERANCE_KCAL
        )
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
                    "plateau_days": None,
                }

    # 7. Ease off — ahead of plan by more than the threshold
    if ahead and (
        plan_rate_kg_per_week - actual_rate_kg_per_week
    ) > EASE_OFF_THRESHOLD_KG:
        return {
            "recommendation": "ease_off",
            "action": (
                f"Reduce your deficit by {DEFICIT_STEP_KCAL} kcal to slow the pace."
            ),
            "suggested_deficit_delta_kcal": -DEFICIT_STEP_KCAL,
            "plateau_days": None,
        }

    # Fallback (ahead by <= 0.15, or increase capped at 750)
    return {
        "recommendation": "on_track",
        "action": "Keep going — your loss rate is close to plan.",
        "suggested_deficit_delta_kcal": None,
        "plateau_days": None,
    }


# ── DB-backed computation ─────────────────────────────────────────────────────

def get_weekly_review(
    user_id,
    as_of_date: Optional[_date] = None,
    db: Optional[Session] = None,
) -> dict:
    """Fetch trailing 7 / 21 day data from the DB and compute the weekly review.

    Returns a dict suitable for direct JSON serialisation.
    """
    from backend.models import FuelEntry, WeightEntry, WeightTarget
    from sqlalchemy import text

    today = as_of_date or today_bangkok()
    window_7d_start = today - timedelta(days=7)
    window_14d_start = today - timedelta(days=14)
    window_21d_start = today - timedelta(days=21)

    owns_db = db is None
    db = db or Session(engine)
    try:
        # ── Active plan ───────────────────────────────────────────────────────
        # weight_plans was merged into weight_targets (#1604); "the active
        # plan" is now the user's active WeightTarget, read for its
        # phase/target_rate_kg_per_week columns.
        plan = (
            db.query(WeightTarget)
            .filter(WeightTarget.user_id == user_id, WeightTarget.status == "active")
            .first()
        )
        has_plan = plan is not None
        plan_rate = float(plan.target_rate_kg_per_week) if (plan and plan.target_rate_kg_per_week is not None) else None
        current_deficit_kcal = 0

        settings_row = get_or_create_settings(user_id, db=db)
        settings = settings_to_dict(settings_row)
        current_deficit_kcal = settings["deficit_kcal"]

        # ── Weight entries (enough history for canonical rate) ────────────────
        weight_rows = (
            db.query(WeightEntry)
            .filter(
                WeightEntry.user_id == user_id,
                WeightEntry.entry_date <= today,
            )
            .order_by(WeightEntry.entry_date.asc())
            .all()
        )

        # Deduplicate to one entry per date (latest if multiple)
        by_day: dict = {}
        for w in weight_rows:
            by_day[w.entry_date] = float(w.weight_kg)
        sorted_entries = sorted(by_day.items())

        # Weigh-in count for last 14 days
        weigh_in_count_14d = sum(
            1 for d, _ in sorted_entries if d >= window_14d_start
        )

        # ── Canonical OLS-on-EWMA rate (same source as weight-chart stats) ───
        # Always use the same 30-day window / gates as the weight tab so cut
        # review cannot unlock a rate the Rate card still considers unreadable.
        rate_stats = weight_stats(
            db,
            user_id,
            window_days=30,
            as_of=today,
            needed_rate_kg_wk=plan_rate,
        )
        actual_rate_kg_per_week: Optional[float] = rate_stats["rate_kg_wk"]
        weekly_pct_bw_rate: float = 0.0
        if actual_rate_kg_per_week is not None and sorted_entries:
            ref_weight = sorted_entries[-1][1]
            if ref_weight > 0:
                weekly_pct_bw_rate = (actual_rate_kg_per_week / ref_weight) * 100.0

        if not rate_stats["readable"]:
            days_needed = max(
                0,
                rate_stats.get("days_needed")
                or (_WEIGHT_STATS_MIN_DAYS - rate_stats["entries_used"]),
            )
            # Locked means not computed — no rate, no verdict prose, no plateau.
            return {
                "gated": True,
                "gate_reason": "insufficient_coverage",
                "actual_rate_kg_per_week": None,
                "plan_rate_kg_per_week": None,
                "logging_adherence_pct": None,
                "avg_intake_vs_budget_kcal": None,
                "recommendation": "insufficient_coverage",
                "action": None,
                "suggested_deficit_delta_kcal": None,
                "plateau_days": None,
                "coverage_pct": rate_stats["coverage_pct"],
                "days_needed": days_needed or _WEIGHT_STATS_MIN_DAYS,
            }

        # ── 3-week consecutive behind check ───────────────────────────────────
        consecutive_weeks_behind = 0
        if plan_rate is not None and actual_rate_kg_per_week is not None:
            # Split 21d into 3 non-overlapping 7-day buckets (newest first)
            week_buckets = [
                (today - timedelta(days=7), today),           # last 7d
                (today - timedelta(days=14), today - timedelta(days=7)),
                (today - timedelta(days=21), today - timedelta(days=14)),
            ]
            streak = 0
            for w_start, w_end in week_buckets:
                week_rate = weight_stats(
                    db,
                    user_id,
                    window_days=7,
                    as_of=w_end,
                    needed_rate_kg_wk=plan_rate,
                )
                week_rate_kg = week_rate["rate_kg_wk"]
                if week_rate_kg is None:
                    break
                # behind = losing less than planned (actual less negative than plan)
                if week_rate_kg > plan_rate:
                    streak += 1
                else:
                    break
            consecutive_weeks_behind = streak

        # ── Fuel entries (7-day window for adherence and intake vs budget) ────
        fuel_rows = (
            db.query(FuelEntry)
            .filter(
                FuelEntry.user_id == user_id,
                FuelEntry.entry_date > window_7d_start,
                FuelEntry.entry_date <= today,
            )
            .all()
        )

        # Compute budget per logged day (base + burn − deficit)
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

        # ── Fuel entries (21-day window) for plateau adherence gate ───────────
        fuel_rows_21d = (
            db.query(FuelEntry)
            .filter(
                FuelEntry.user_id == user_id,
                FuelEntry.entry_date >= window_21d_start,
                FuelEntry.entry_date <= today,
            )
            .all()
        )

        pct_at_or_under_21d: float = 0.0
        if fuel_rows_21d:
            at_under_21d = 0
            for fe in fuel_rows_21d:
                totals = compute_food_totals(fe)
                burn_info = training_burn_kcal(
                    user_id, fe.entry_date,
                    settings["weight_kg"], settings["run_kcal_per_kg_per_km"],
                    today=today, db=db,
                )
                budget_info = compute_budget(settings, burn_info["burn"])
                if totals["kcal"] <= budget_info["budget"]:
                    at_under_21d += 1
            pct_at_or_under_21d = at_under_21d / len(fuel_rows_21d) * 100.0

        # ── Plateau detection ─────────────────────────────────────────────────
        plateau_days: int = 0
        if actual_rate_kg_per_week is not None and len(sorted_entries) >= 2:
            if actual_rate_kg_per_week > PLATEAU_RATE_THRESHOLD_KG:
                span_days = (
                    sorted_entries[-1][0] - sorted_entries[0][0]
                ).days + 1
                plateau_days = min(span_days, 21)

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

        # ── Build recommendation ──────────────────────────────────────────────
        rec = compute_cut_recommendation(
            weigh_in_count_14d=weigh_in_count_14d,
            has_active_plan=has_plan and plan_rate is not None,
            actual_rate_kg_per_week=(
                actual_rate_kg_per_week if actual_rate_kg_per_week is not None else 0.0
            ),
            plan_rate_kg_per_week=plan_rate if plan_rate is not None else 0.0,
            weekly_pct_bw_rate=weekly_pct_bw_rate,
            ea_proxy=ea_proxy,
            logging_adherence_pct=logging_adherence_pct,
            avg_intake_vs_budget_kcal=(
                avg_intake_vs_budget_kcal
                if avg_intake_vs_budget_kcal is not None else 0.0
            ),
            consecutive_weeks_behind=consecutive_weeks_behind,
            pct_logged_days_at_or_under_budget=pct_at_or_under,
            current_deficit_kcal=current_deficit_kcal,
            plateau_days=plateau_days,
            pct_at_or_under_budget_21d=pct_at_or_under_21d,
        )

        return {
            "gated": False,
            "gate_reason": None,
            "actual_rate_kg_per_week": (
                round(actual_rate_kg_per_week, 3)
                if actual_rate_kg_per_week is not None else None
            ),
            "plan_rate_kg_per_week": (
                round(plan_rate, 3) if plan_rate is not None else None
            ),
            "logging_adherence_pct": round(logging_adherence_pct, 1),
            "avg_intake_vs_budget_kcal": (
                round(avg_intake_vs_budget_kcal, 1)
                if avg_intake_vs_budget_kcal is not None else None
            ),
            "recommendation": rec["recommendation"],
            "action": rec["action"],
            "suggested_deficit_delta_kcal": rec["suggested_deficit_delta_kcal"],
            "plateau_days": rec["plateau_days"],
            "coverage_pct": rate_stats["coverage_pct"],
            "days_needed": 0,
        }

    finally:
        if owns_db:
            db.close()
