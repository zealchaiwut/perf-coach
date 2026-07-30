"""Coach export — one paste-ready blob (prompt template + payload) for a fresh chat.

What this is
------------
``build_export(user_id)`` assembles a single JSON payload describing where the
athlete actually is; ``build_paste_blob(export)`` prepends the versioned prompt
template and appends that payload in a fenced block. The result is copied to the
clipboard by the nav-bar button and pasted into a new Claude session, which then
writes the daily coach message.

Three rules govern this module — break them and the export becomes a second,
disagreeing source of truth:

1. **Pure assembly. No LLM call, no HTTP call, no writes.** It cannot fail at
   3am and it cannot cost anything.
2. **Never emit a number the app didn't compute.** Every metric is read from the
   service that owns it (``training_load``, the canonical performance compute,
   ``weight_trend_rate``, ``fuel``, ``load_plan``, the gap-analysis engine). If a
   field would have to be derived inline here, it belongs in a service first —
   ``weight_trend_rate`` exists because of exactly that rule. Formatting
   (pace from distance and duration, age from birth date) is not deriving.
3. **Conclusions with evidence, not raw material to re-derive.** ``fitness``,
   ``performance``, ``body`` and ``goal`` are canonical; ``training.sessions``
   are context that explains *why*, never a source for *what*. Rule 1 of the
   prompt template states this to the reader, because a fresh model that
   computes its own CTL or its own weight trend will contradict the app.

Degradation
-----------
Every block is assembled behind ``_safe``: a block whose source raises returns
its null shape and records the failure in ``meta.degraded``. A partial export is
still worth pasting; a 500 is not. The one thing never done is guessing a value
to fill a hole.

Versioning
----------
``SCHEMA_VERSION`` (payload) and ``PROMPT_VERSION`` (template) move together and
both appear in the blob. A template that references a field the payload no
longer carries is a bug, and ``tests/test_coach_export__blob.py`` catches it.
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.db import engine

_log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
PROMPT_VERSION = "coach-paste-v1"

DEFAULT_WINDOW_DAYS = 90
MAX_WINDOW_DAYS = 365
MIN_WINDOW_DAYS = 7
# Weekly rollups / fitness series length. 13 weeks ≈ a training block, and it is
# the span the season charts already show.
ROLLUP_WEEKS = 13
# Trailing window for athlete.weekly_hours_recent — "what I actually train",
# long enough to survive one quiet week.
RECENT_HOURS_WEEKS = 8
# Top-K anchors per score, matching running_performance's own TOP_K rows.
ANCHOR_ROWS = 3
ATHLETE_CONTEXT_MAX_CHARS = 200

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

_ACWR_NULL_NOTE = (
    "weekly_series[].acwr_end is null until a full 28-day chronic window exists "
    "inside the export window. A partial window yields ratios like 4.0 that read "
    "as a spike that never happened — treat null as 'not yet knowable', not zero."
)
_META_NOTE = (
    "fitness, performance, body and goal are canonical — computed by perf-coach. "
    "training.sessions are context: they explain why the canonical numbers moved, "
    "and are never a source for recomputing them."
)

_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ── Degradation helper ────────────────────────────────────────────────────────

def _safe(label: str, fn: Callable[[], Any], fallback: Any, degraded: list[str]) -> Any:
    """Run an assembly step; on failure record it and return the null shape.

    A block that raises must not take the whole export down — but it also must
    not silently look like real data, hence the ``degraded`` list surfacing in
    ``meta``.
    """
    try:
        return fn()
    except Exception as exc:  # pragma: no cover — exercised via degraded-path tests
        _log.warning("coach export block %s failed: %s", label, exc, exc_info=True)
        degraded.append(f"{label}: {exc.__class__.__name__}")
        return fallback


# ── Small formatters (formatting, not deriving) ───────────────────────────────

def _f(value, digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _i(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _mmss(seconds) -> Optional[str]:
    """Format seconds as M:SS (paces) — None-safe."""
    s = _i(seconds)
    if s is None or s <= 0:
        return None
    return f"{s // 60}:{s % 60:02d}"


def _hhmmss(seconds) -> Optional[str]:
    s = _i(seconds)
    if s is None or s <= 0:
        return None
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _pace_per_km(distance_km, duration_seconds) -> Optional[str]:
    """Average pace as M:SS/km. Pure formatting of two stored columns."""
    d = _f(distance_km, 3)
    t = _i(duration_seconds)
    if not d or not t or d <= 0:
        return None
    return _mmss(t / d)


def _age_from_birth_date(birth_date, today: _date) -> Optional[int]:
    if birth_date is None:
        return None
    had_birthday = (today.month, today.day) >= (birth_date.month, birth_date.day)
    return today.year - birth_date.year - (0 if had_birthday else 1)


def _week_start(d: _date) -> _date:
    return d - _timedelta(days=d.weekday())


# ── meta ─────────────────────────────────────────────────────────────────────

def _assemble_meta(
    db: Session,
    user,
    today: _date,
    window_days: int,
    generated_at: str,
) -> dict:
    from backend.models import WeightEntry, Workout

    last_workout = (
        db.query(Workout.workout_date)
        .filter(Workout.user_id == user.id)
        .order_by(Workout.workout_date.desc())
        .limit(1)
        .scalar()
    )
    last_weigh_in = (
        db.query(WeightEntry.entry_date)
        .filter(WeightEntry.user_id == user.id)
        .order_by(WeightEntry.entry_date.desc())
        .limit(1)
        .scalar()
    )
    prev_export = getattr(user, "last_coach_export_at", None)

    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "generated_at": generated_at,
        "timezone": "Asia/Bangkok",
        "window_days": window_days,
        "previous_export_date": (
            prev_export.date().isoformat() if prev_export is not None else None
        ),
        "data_freshness": {
            "last_workout_date": last_workout.isoformat() if last_workout else None,
            "last_weigh_in": last_weigh_in.isoformat() if last_weigh_in else None,
            "workout_days_stale": (today - last_workout).days if last_workout else None,
            "weigh_in_days_stale": (today - last_weigh_in).days if last_weigh_in else None,
        },
        "note": _META_NOTE,
        "acwr_null_note": _ACWR_NULL_NOTE,
        "degraded": [],
    }


# ── athlete ──────────────────────────────────────────────────────────────────

_NULL_ATHLETE = {
    "age": None,
    "height_cm": None,
    "mass_kg": None,
    "mass_source": None,
    "weekly_hours_recent": None,
    "context": None,
}


def _assemble_athlete(db: Session, user, today: _date, body: dict) -> dict:
    """Identity block. mass_kg is the weight TREND, never the last weigh-in."""
    from backend.models import Workout

    since = today - _timedelta(weeks=RECENT_HOURS_WEEKS)
    rows = (
        db.query(Workout.duration_seconds)
        .filter(
            Workout.user_id == user.id,
            Workout.workout_date >= since,
            Workout.workout_date <= today,
            Workout.duration_seconds.isnot(None),
        )
        .all()
    )
    total_seconds = sum(int(r[0]) for r in rows if r[0])
    weekly_hours = (
        round(total_seconds / 3600.0 / RECENT_HOURS_WEEKS, 1) if total_seconds else 0.0
    )

    trend_kg = body.get("trend_kg")
    context = getattr(user, "athlete_context", None)
    return {
        "age": _age_from_birth_date(getattr(user, "birth_date", None), today),
        "height_cm": _f(getattr(user, "height_cm", None), 1),
        "mass_kg": trend_kg,
        "mass_source": "weight_trend_ewma" if trend_kg is not None else None,
        "weekly_hours_recent": weekly_hours,
        "context": (context or None),
    }


# ── fitness ──────────────────────────────────────────────────────────────────

_NULL_FITNESS = {
    "as_of": None,
    "ctl": None,
    "atl": None,
    "tsb": None,
    "acwr": None,
    "chronic_weekly_tss": None,
    "ctl_target_for_goal": None,
    "ctl_gap": None,
    "weekly_series": [],
}


def _assemble_fitness(user_id, today: _date, goal_distance: Optional[str]) -> dict:
    """CTL/ATL/TSB/ACWR from the snapshot table — the sole source every other
    consumer (readiness card, season chart) reads. No independent recompute."""
    from backend.services.coach_plan import _TARGET_CTL
    from backend.services.training_load import current_load, get_snapshot_series

    load = current_load(str(user_id), as_of=today)
    ctl = _f(load.get("ctl"))
    atl = _f(load.get("atl"))
    tsb = _f(load.get("tsb"))
    acwr = _f(load.get("acwr"), 3)

    series_start = _week_start(today) - _timedelta(weeks=ROLLUP_WEEKS - 1)
    snaps = get_snapshot_series(str(user_id), series_start, today)

    by_date = {s["date"]: s for s in snaps}
    weekly_series: list[dict] = []
    for i in range(ROLLUP_WEEKS):
        ws = series_start + _timedelta(weeks=i)
        we = min(ws + _timedelta(days=6), today)
        if ws > today:
            break
        week_snaps = [
            by_date[ws + _timedelta(days=d)]
            for d in range((we - ws).days + 1)
            if (ws + _timedelta(days=d)) in by_date
        ]
        end_snap = week_snaps[-1] if week_snaps else None
        # ACWR needs a full 28-day chronic window; the snapshot layer already
        # returns None for days that don't have one (see acwr.py's _MIN_DAYS).
        weekly_series.append({
            "week_start": ws.isoformat(),
            "tss": _f(sum(float(s["tss"] or 0) for s in week_snaps), 1),
            "ctl_end": _f(end_snap["ctl"], 1) if end_snap else None,
            "atl_end": _f(end_snap["atl"], 1) if end_snap else None,
            "tsb_end": _f(end_snap["tsb"], 1) if end_snap else None,
            "acwr_end": _f(end_snap.get("acwr"), 3) if end_snap else None,
        })

    # Trailing 28-day mean weekly TSS — the chronic baseline the ACWR ceiling and
    # the load plan are both built on.
    chronic_start = today - _timedelta(days=27)
    chronic_snaps = [s for s in snaps if chronic_start <= s["date"] <= today]
    chronic_weekly = (
        _f(sum(float(s["tss"] or 0) for s in chronic_snaps) / 4.0, 1)
        if len(chronic_snaps) >= 28
        else None
    )

    target_ctl = _TARGET_CTL.get(goal_distance or "", None)
    ctl_gap = (
        _f(max(0.0, target_ctl - ctl), 1)
        if (target_ctl is not None and ctl is not None)
        else None
    )

    return {
        "as_of": today.isoformat(),
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "acwr": acwr,
        "chronic_weekly_tss": chronic_weekly,
        "ctl_target_for_goal": target_ctl,
        "ctl_gap": ctl_gap,
        "weekly_series": weekly_series,
    }


# ── performance ──────────────────────────────────────────────────────────────

_NULL_SCORE = {
    "score": None,
    "delta_28d": None,
    "direction": None,
    "decomposition": None,
    "anchors": [],
}
_NULL_PERFORMANCE = {
    "state": "unavailable",
    "endurance": dict(_NULL_SCORE),
    "speed": dict(_NULL_SCORE),
}


def _score_block(raw: Optional[dict]) -> dict:
    """Shape one score from the canonical compute's own output.

    ``decomposition`` is the app's assertion that ``score_then + decay + efforts
    + consistency == score_now``; it is copied, never recalculated. When the
    canonical compute refuses the breakdown (its residual check failed), the
    decomposition is None rather than a set of numbers that don't sum.
    """
    if not isinstance(raw, dict) or raw.get("score") is None:
        return dict(_NULL_SCORE)

    breakdown = raw.get("breakdown")
    decomposition = None
    anchors: list[dict] = []
    delta_28d = None

    if isinstance(breakdown, dict) and not breakdown.get("error"):
        decomposition = {
            "window_days": breakdown.get("window_days"),
            "score_then": breakdown.get("score_then"),
            "decay": breakdown.get("decay"),
            "efforts": breakdown.get("efforts"),
            "consistency": breakdown.get("consistency"),
            "score_now": breakdown.get("score_now"),
        }
        delta_28d = breakdown.get("delta")
        for a in (breakdown.get("anchors") or [])[:ANCHOR_ROWS]:
            anchors.append({
                # run_id is consumed by _title_anchors and removed there — it
                # resolves the session name and then has no business in a coach
                # payload.
                "run_id": a.get("run_id"),
                "date": a.get("date"),
                "raw_score": a.get("raw_score"),
                "age_weeks": a.get("age_weeks"),
                "current_contribution": a.get("current_contribution"),
                "is_stale": a.get("is_stale"),
                "title": None,  # filled from the session row on that date
            })

    return {
        "score": _f(raw.get("score"), 1),
        "delta_28d": delta_28d,
        "direction": raw.get("direction"),
        "decomposition": decomposition,
        "anchors": anchors,
    }


def _assemble_performance(user) -> dict:
    """Read the CANONICAL performance compute — the same cached call that serves
    the Performance tab and /api/performance/score-breakdown. Calling it here is
    what keeps the export's scores from ever disagreeing with the app."""
    from backend.main import get_athlete_performance

    payload = json.loads(get_athlete_performance(str(user.id), user=user).body)
    state = payload.get("state")
    if state != "scored":
        return {
            "state": state or "unavailable",
            "endurance": dict(_NULL_SCORE),
            "speed": dict(_NULL_SCORE),
        }
    return {
        "state": "scored",
        "endurance": _score_block(payload.get("endurance")),
        "speed": _score_block(payload.get("speed")),
    }


def _title_anchors(
    performance: dict,
    names_by_run_id: dict[str, str],
    names_by_date: dict[str, str],
) -> None:
    """Name each anchor with the session that produced it.

    An anchor row that says "48.2 from 3.1 weeks ago" is a number; one that says
    "Half-marathon pace 8 k" is evidence the athlete recognises.

    Resolved by ``run_id`` first — matching on date alone mis-titles the anchor
    whenever two sessions share a day (a morning run and an evening lift), and
    picks the wrong one silently. Date is the fallback for the race anchor point,
    which has no ``run_id`` at all. The ids themselves stay out of the payload;
    they cost ~45 chars a row and a coach message has no use for them.
    """
    for key in ("endurance", "speed"):
        for anchor in (performance.get(key) or {}).get("anchors") or []:
            run_id = anchor.pop("run_id", None)
            title = names_by_run_id.get(str(run_id)) if run_id else None
            anchor["title"] = title or names_by_date.get(anchor.get("date"))


# ── goal ─────────────────────────────────────────────────────────────────────

_NULL_GOAL = {
    "race": None,
    "body": None,
    "checkpoints": [],
}


def _race_estimate(db: Session, user, race_row, distance_km: Optional[float]) -> dict:
    """Current finish estimate for the goal race + its band, in minutes.

    Preferred source is the race-readiness compute behind the Performance tab
    (its projection series ends on race day, so the estimate accounts for the
    whole build and taper). For a PerformanceGoal with no Race row there is no
    projection to read, so fall back to ``blended_scores_estimate`` — the same
    engine, anchored on today's displayed End/Spd scores with no build modelled.
    """
    out = {"current_estimate": None, "estimate_band_min": None, "estimate_source": None}

    if race_row is not None:
        try:
            from backend.main import _race_readiness_impl

            readiness = json.loads(_race_readiness_impl(str(race_row.id), user).body)
            curve = readiness.get("time_curve") or {}
            samples = curve.get("projection") or curve.get("history") or []
            if samples:
                last = samples[-1]
                out["current_estimate"] = _hhmmss(last.get("estimated_finish_seconds"))
                band = last.get("confidence_band_seconds")
                out["estimate_band_min"] = (
                    round(band / 60.0, 1) if band is not None else None
                )
                out["estimate_source"] = "race_readiness_projection"
                return out
        except Exception as exc:
            _log.warning("race readiness estimate unavailable: %s", exc, exc_info=True)

    if distance_km:
        from backend.main import _athlete_scores_as_of
        from backend.models import UserPreferences
        from backend.services.coach_projection import _band_seconds
        from backend.services.race_finish_estimator import blended_scores_estimate

        prefs = (
            db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
        )
        thresholds = (
            {
                "threshold_pace_seconds_per_km": prefs.threshold_pace_seconds_per_km,
                "threshold_hr": prefs.threshold_hr,
                "ftp_w": prefs.ftp_w,
            }
            if prefs is not None
            else None
        )
        scores = _athlete_scores_as_of(db, user.id, _date.today())
        est = blended_scores_estimate(
            scores.get("endurance"), scores.get("speed"), distance_km, thresholds
        )
        seconds = est.get("estimated_finish_seconds")
        if seconds is not None:
            out["current_estimate"] = _hhmmss(seconds)
            out["estimate_band_min"] = round(
                _band_seconds(1, float(distance_km)) / 60.0, 1
            )
            out["estimate_source"] = "blended_scores_estimate"
    return out


def _assemble_goal(db: Session, user, today: _date, body: dict) -> dict:
    from backend.models import Race, RaceCheckpoint, WeightTarget
    from backend.services.goal_resolution import resolve_active_goal

    goal = resolve_active_goal(user.id, db)

    race_block = None
    race_row = None
    if goal is not None:
        distance_label = getattr(goal, "race_distance", None)
        race_date = getattr(goal, "race_date", None)
        # Prefer the real Race row when one exists — it carries the name, the
        # exact distance, and the id the readiness projection needs.
        race_row = (
            db.query(Race)
            .filter(
                Race.user_id == user.id,
                Race.race_date == race_date,
                Race.status.in_(("planned", "active")),
            )
            .order_by(Race.priority.asc())
            .first()
            if race_date is not None
            else None
        )
        distance_km = (
            float(race_row.distance_km)
            if race_row is not None and race_row.distance_km is not None
            else _DISTANCE_KM.get(distance_label or "")
        )
        estimate = _race_estimate(db, user, race_row, distance_km)
        race_block = {
            "name": race_row.name if race_row is not None else None,
            "distance": distance_label,
            "distance_km": _f(distance_km, 3),
            "date": race_date.isoformat() if race_date is not None else None,
            "weeks_out": (
                round((race_date - today).days / 7.0, 1)
                if race_date is not None
                else None
            ),
            "goal_time": _hhmmss(getattr(goal, "target_time", None)),
            **estimate,
        }

    target = (
        db.query(WeightTarget)
        .filter(WeightTarget.user_id == user.id, WeightTarget.status == "active")
        .first()
    )
    body_block = None
    if target is not None:
        body_block = {
            "target_kg": _f(target.target_weight_kg, 1),
            "target_date": str(target.target_date),
            "needed_rate_kg_per_week": body.get("needed_rate_kg_per_week"),
            "intent": (
                "lose"
                if float(target.target_weight_kg) < float(target.start_weight_kg)
                else "gain"
            ),
        }

    checkpoints: list[dict] = []
    if race_row is not None:
        for cp in (
            db.query(RaceCheckpoint)
            .filter(RaceCheckpoint.race_id == race_row.id)
            .order_by(RaceCheckpoint.target_date.asc())
            .all()
        ):
            checkpoints.append({
                "label": cp.label,
                "target_date": cp.target_date.isoformat(),
                "target_distance_km": _f(cp.target_distance_km, 3),
                "target_pace_per_km": _mmss(cp.target_pace_seconds_per_km),
                "target_duration": _hhmmss(cp.target_duration_seconds),
                "met": bool(cp.met or cp.met_override),
            })

    return {"race": race_block, "body": body_block, "checkpoints": checkpoints}


_DISTANCE_KM = {"5k": 5.0, "10k": 10.0, "half": 21.0975, "marathon": 42.195}


# ── constraints ──────────────────────────────────────────────────────────────

_NULL_CONSTRAINTS = {
    "acwr_ceiling_weekly_tss": None,
    "acwr_high_bound": None,
    "current_verdict": None,
    "verdict_reason": None,
    "max_weekly_ramp_pct": None,
    "ea_floor_kcal_rest_day": None,
    "max_deficit_kcal_per_day": None,
    "protein_g_per_day": None,
    "taper_window_days": None,
    "preferred_rest_days": [],
    "max_consecutive_training_days": None,
    "note": None,
}

_CONSTRAINTS_NOTE = (
    "These are hard bounds, not suggestions. Never propose a week whose total TSS "
    "exceeds acwr_ceiling_weekly_tss, and never propose intake below "
    "ea_floor_kcal_rest_day on a rest day — when the two conflict, the fuel floor "
    "wins and the training comes down."
)


def _max_consecutive_training_days(rest_days: list[int]) -> Optional[int]:
    """Longest run of non-rest weekdays implied by the rest-day preference.

    A consequence of a stored pref, computed cyclically (a Sunday rest bounds the
    following Monday). None when no rest days are set — there is then no stored
    preference to read a bound from, and inventing one would be exactly the kind
    of made-up number this module refuses to emit.
    """
    if not rest_days:
        return None
    rest = sorted(set(int(d) % 7 for d in rest_days))
    if len(rest) >= 7:
        return 0
    longest = 0
    for i, day in enumerate(rest):
        nxt = rest[(i + 1) % len(rest)]
        gap = (nxt - day - 1) % 7
        longest = max(longest, gap)
    return longest


def _assemble_constraints(db: Session, user, today: _date, fitness: dict) -> dict:
    from backend.models import TrainingPlan
    from backend.services import fuel as fuel_svc
    from backend.services.load_plan import ACWR_CEILING_MULT, TAPER_CURVE
    from backend.services.plan_prefs_accessor import get_plan_prefs
    from backend.services.plan_suggestions import ACWR_HIGH_BOUND
    from backend.services.training_load import current_load
    from backend.services.training_verdict import compute_verdict

    chronic = fitness.get("chronic_weekly_tss")
    ceiling = _f(ACWR_CEILING_MULT * chronic, 1) if chronic else None

    snap = current_load(str(user.id), as_of=today)
    verdict = compute_verdict(snap, chronic_weekly=chronic, today=today)

    prefs = get_plan_prefs(db=db, user_id=user.id)
    rest_days = list(prefs.get("preferred_rest_days") or [])

    plan_row = (
        db.query(TrainingPlan)
        .filter(TrainingPlan.user_id == user.id)
        .order_by(TrainingPlan.created_at.asc())
        .first()
    )
    ramp_rate = (
        float(plan_row.ramp_rate)
        if plan_row is not None and plan_row.ramp_rate is not None
        else None
    )
    taper_weeks = (
        int(round(float(plan_row.taper_length)))
        if plan_row is not None and plan_row.taper_length is not None
        else len(TAPER_CURVE)
    )

    # Rest-day EA floor: the fuel service's own floor with zero training burn.
    settings_row = fuel_svc.get_or_create_settings(user.id, db=db)
    settings = fuel_svc.settings_to_dict(settings_row)
    rest_budget = fuel_svc.compute_budget(settings, burn=0.0)
    lean = fuel_svc._fetch_lean_mass(user.id, settings_row, db)
    targets = fuel_svc.compute_targets(
        settings,
        rest_budget["budget"],
        lean_mass_kg=lean["lean_mass_kg"],
        lean_mass_source=lean["source"],
    )

    return {
        "acwr_ceiling_weekly_tss": ceiling,
        "acwr_high_bound": ACWR_HIGH_BOUND,
        "current_verdict": verdict["verdict"],
        "verdict_reason": verdict["reason"],
        "max_weekly_ramp_pct": round(ramp_rate * 100.0, 1) if ramp_rate else None,
        "ea_floor_kcal_rest_day": rest_budget["ea_floor_kcal"],
        "max_deficit_kcal_per_day": fuel_svc.DEFICIT_KCAL_MAX,
        "protein_g_per_day": targets["protein_g"],
        "taper_window_days": taper_weeks * 7,
        "preferred_rest_days": [_DOW[d] for d in rest_days if 0 <= d <= 6],
        "max_consecutive_training_days": _max_consecutive_training_days(rest_days),
        "note": _CONSTRAINTS_NOTE,
    }


# ── body ─────────────────────────────────────────────────────────────────────

_NULL_BODY = {
    "trend_kg": None,
    "last_weigh_in": None,
    "rate_kg_per_week": None,
    "ci_kg_per_week": None,
    "state": "unknown",
    "readable": False,
    "readable_note": "weight data unavailable",
    "coverage_pct_45d": 0.0,
    "needed_rate_kg_per_week": None,
    "weigh_ins": [],
}


def _assemble_body(db: Session, user, today: _date, window_days: int) -> dict:
    from backend.models import WeightEntry, WeightTarget
    from backend.services.weight_ewma import compute_ewma
    from backend.services.weight_plan import compute_required_pace_kg_per_week
    from backend.services.weight_trend_rate import (
        DEFAULT_WINDOW_DAYS as _RATE_WINDOW,
        compute_trend_rate,
    )

    # Smooth over the FULL history so the EWMA isn't re-bootstrapped inside the
    # rate window (see weight_trend_rate's ewma_values contract).
    rows = (
        db.query(WeightEntry)
        .filter(WeightEntry.user_id == user.id, WeightEntry.entry_date <= today)
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )
    entries = [{"date": r.entry_date, "weight_kg": float(r.weight_kg)} for r in rows]
    ewma = compute_ewma(entries) if entries else []

    rate = compute_trend_rate(entries, today, window_days=_RATE_WINDOW, ewma_values=ewma)

    target = (
        db.query(WeightTarget)
        .filter(WeightTarget.user_id == user.id, WeightTarget.status == "active")
        .first()
    )
    needed = (
        _f(compute_required_pace_kg_per_week(target, db, today), 3)
        if target is not None
        else None
    )

    window_start = today - _timedelta(days=window_days - 1)
    weigh_ins = [
        {
            "date": e["date"].isoformat(),
            "kg": round(e["weight_kg"], 1),
            "trend_kg": round(float(sm), 2),
        }
        for e, sm in zip(entries, ewma)
        if window_start <= e["date"] <= today
    ]

    return {
        "trend_kg": rate["trend_kg"],
        "last_weigh_in": rate["last_weigh_in"],
        "rate_kg_per_week": rate["rate_kg_per_week"],
        "ci_kg_per_week": rate["ci_kg_per_week"],
        "state": rate["state"],
        "readable": rate["readable"],
        "readable_note": rate["readable_note"],
        "coverage_pct_45d": rate["coverage_pct"],
        "needed_rate_kg_per_week": needed,
        "weigh_ins": weigh_ins,
    }


# ── training ─────────────────────────────────────────────────────────────────

_NULL_TRAINING = {"weekly_rollups": [], "skipped_planned": [], "sessions": []}

_SKIPPED_STATUSES = ("missed", "missed_auto", "missed_manual")


def _session_row(workout, exercise_counts: dict) -> dict:
    """One flat session object. No ``structure`` blob — it triples the payload
    and adds nothing a coach message can use."""
    row = {
        "date": workout.workout_date.isoformat(),
        "dow": _DOW[workout.workout_date.weekday()],
        "type": workout.workout_type,
        "name": workout.name,
        "duration_min": (
            round(workout.duration_seconds / 60.0)
            if workout.duration_seconds
            else None
        ),
        "tss": _f(workout.tss, 1),
    }
    if workout.run_subtype:
        row["subtype"] = workout.run_subtype

    is_run = (workout.workout_type or "").lower() == "run"
    if is_run or workout.distance_km is not None:
        row["distance_km"] = _f(workout.distance_km, 2)
        row["avg_pace_per_km"] = _pace_per_km(
            workout.distance_km, workout.duration_seconds
        )
    if workout.avg_hr is not None:
        row["avg_hr"] = workout.avg_hr
    if workout.avg_power is not None:
        row["avg_power"] = workout.avg_power
    if workout.zone2_minutes is not None:
        row["zone2_min"] = workout.zone2_minutes
    if workout.elevation_m is not None:
        row["elevation_m"] = workout.elevation_m
    if workout.decoupling_percent is not None:
        row["decoupling_pct"] = _f(workout.decoupling_percent, 1)
    if workout.feeling:
        row["feeling"] = workout.feeling

    count = exercise_counts.get(workout.id)
    if count:
        row["exercises"] = count
    return row


def _assemble_training(db: Session, user, today: _date, window_days: int) -> dict:
    from sqlalchemy import func

    from backend.models import PlannedSession, Workout, WorkoutExercise
    from backend.services.training_load import get_weekly_volume

    window_start = today - _timedelta(days=window_days - 1)

    workouts = (
        db.query(Workout)
        .filter(
            Workout.user_id == user.id,
            Workout.workout_date >= window_start,
            Workout.workout_date <= today,
        )
        .order_by(Workout.workout_date.asc(), Workout.start_time.asc().nullslast())
        .all()
    )
    workout_ids = [w.id for w in workouts]
    exercise_counts: dict = {}
    if workout_ids:
        for wid, count in (
            db.query(WorkoutExercise.workout_id, func.count(WorkoutExercise.id))
            .filter(WorkoutExercise.workout_id.in_(workout_ids))
            .group_by(WorkoutExercise.workout_id)
            .all()
        ):
            exercise_counts[wid] = int(count)

    sessions = [_session_row(w, exercise_counts) for w in workouts]

    rollup_start = _week_start(today) - _timedelta(weeks=ROLLUP_WEEKS - 1)
    weekly_rollups: list[dict] = []
    for i in range(ROLLUP_WEEKS):
        ws = rollup_start + _timedelta(weeks=i)
        if ws > today:
            break
        we = ws + _timedelta(days=6)
        # Clamp to today: a rollup must cover the same span as `sessions`, or the
        # two disagree the moment a workout is dated ahead (pre-logged session,
        # timezone edge) and the export contradicts itself.
        vol = get_weekly_volume(str(user.id), ws, min(we, today))
        types = [t for t in (vol.get("workout_types") or []) if t]
        weekly_rollups.append({
            "week_start": ws.isoformat(),
            "sessions": vol["session_count"],
            "tss": _f(vol["total_tss"], 1),
            "distance_km": _f(vol["distance_km"], 1),
            "hours": _f((vol["duration_seconds"] or 0) / 3600.0, 1),
            "runs": sum(1 for t in types if t.lower() == "run"),
            "strength": sum(1 for t in types if t.lower() in ("strength", "plyo")),
            "partial": we > today,
        })

    # ``skipped_planned`` reads the status plan_matching already assigned (a
    # planned session with no workout inside its ±1-day window is marked
    # missed*). The window is the matcher's business, not the exporter's.
    skipped = [
        {
            "date": p.planned_date.isoformat(),
            "dow": _DOW[p.planned_date.weekday()],
            "type": p.session_type,
            "name": p.name,
            "status": p.status,
        }
        for p in (
            db.query(PlannedSession)
            .filter(
                PlannedSession.user_id == user.id,
                PlannedSession.planned_date >= window_start,
                PlannedSession.planned_date < today,
                PlannedSession.status.in_(_SKIPPED_STATUSES),
            )
            .order_by(PlannedSession.planned_date.asc())
            .all()
        )
    ]

    # Not part of the payload — the lookup _title_anchors resolves anchors with.
    names_by_run_id = {str(w.id): w.name for w in workouts if w.name}
    names_by_date = {}
    for w in workouts:
        names_by_date.setdefault(w.workout_date.isoformat(), w.name)

    return {
        "weekly_rollups": weekly_rollups,
        "skipped_planned": skipped,
        "sessions": sessions,
        "_names_by_run_id": names_by_run_id,
        "_names_by_date": names_by_date,
    }


# ── races ────────────────────────────────────────────────────────────────────

_NULL_RACES = {"past": [], "upcoming": []}


def _assemble_races(db: Session, user, today: _date) -> dict:
    from backend.models import Race

    past: list[dict] = []
    upcoming: list[dict] = []
    for r in (
        db.query(Race)
        .filter(Race.user_id == user.id, Race.race_type == "race")
        .order_by(Race.race_date.asc())
        .all()
    ):
        row = {
            "name": r.name,
            "date": r.race_date.isoformat(),
            "distance_km": _f(r.distance_km, 3),
            "priority": r.priority,
            "goal_time": _hhmmss(r.goal_time_seconds),
        }
        if r.status == "done" or r.race_date < today:
            row["status"] = r.status
            row["actual_time"] = _hhmmss(r.actual_time_seconds)
            past.append(row)
        else:
            row["weeks_out"] = round((r.race_date - today).days / 7.0, 1)
            upcoming.append(row)
    return {"past": past, "upcoming": upcoming}


# ── habits ───────────────────────────────────────────────────────────────────

_NULL_HABITS = {"week_start": None, "items": [], "adherence_4w_pct": None}


def _assemble_habits(db: Session, user, today: _date) -> dict:
    from backend.models import Habit, HabitLog
    from backend.services.habit_adherence import build_adherence_payload

    habits = (
        db.query(Habit)
        .filter(
            Habit.user_id == user.id,
            Habit.is_archived.is_(False),
            Habit.active.is_(True),
        )
        .order_by(Habit.sort_order)
        .all()
    )
    if not habits:
        return {"week_start": _week_start(today).isoformat(), "items": [], "adherence_4w_pct": None}

    logs_by_habit: dict = {}
    for log in (
        db.query(HabitLog)
        .filter(HabitLog.habit_id.in_([h.id for h in habits]), HabitLog.user_id == user.id)
        .all()
    ):
        logs_by_habit.setdefault(str(log.habit_id), []).append(log)

    payload = build_adherence_payload(habits=habits, logs_by_habit=logs_by_habit, today=today)

    items: list[dict] = []
    pcts: list[float] = []
    for h in payload.get("habits") or []:
        pct = h.get("adherence_percent")
        items.append({
            "name": h.get("habit_name"),
            "adherence_pct": pct,
            "trend": h.get("trend"),
            "met_count": h.get("met_count"),
            "scheduled_count": h.get("scheduled_count"),
            "building": h.get("building"),
        })
        if isinstance(pct, (int, float)) and not h.get("building"):
            pcts.append(float(pct))

    return {
        "week_start": _week_start(today).isoformat(),
        "items": items,
        "adherence_4w_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
    }


# ── plan ─────────────────────────────────────────────────────────────────────

_NULL_PLAN = {
    "today": None,
    "week": [],
    "week_planned_tss": None,
    "week_logged_tss_so_far": None,
}


def _planned_row(p, for_date: _date) -> dict:
    structure = p.structure if isinstance(p.structure, dict) else {}
    blocks = structure.get("blocks") if isinstance(structure.get("blocks"), list) else []
    duration_min = None
    if blocks:
        total = sum(
            float(b.get("duration_min") or 0) * max(1, int(b.get("repeat") or 1))
            for b in blocks
            if isinstance(b, dict)
        )
        duration_min = round(total) or None
    elif structure.get("duration_min") is not None:
        duration_min = _i(structure.get("duration_min"))

    exercises = structure.get("exercises")
    row = {
        "date": for_date.isoformat(),
        "dow": _DOW[for_date.weekday()],
        "type": p.session_type,
        "name": p.name,
        "status": p.status,
        "duration_min": duration_min,
    }
    if isinstance(exercises, list) and exercises:
        row["exercises"] = len(exercises)
    if p.notes:
        row["notes"] = p.notes
    return row


def _assemble_plan(db: Session, user, today: _date) -> dict:
    from backend.models import PlannedSession
    from backend.services.training_load import (
        estimate_historical_pace_and_tss,
        estimate_planned_session_metrics,
        get_weekly_volume,
    )

    week_start = _week_start(today)
    week_end = week_start + _timedelta(days=6)

    rows = (
        db.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user.id,
            PlannedSession.planned_date >= week_start,
            PlannedSession.planned_date <= week_end,
        )
        .order_by(PlannedSession.planned_date.asc())
        .all()
    )
    by_date: dict[_date, list] = {}
    for p in rows:
        by_date.setdefault(p.planned_date, []).append(p)

    week: list[dict] = []
    for offset in range(7):
        d = week_start + _timedelta(days=offset)
        day_rows = by_date.get(d) or []
        if day_rows:
            week.extend(_planned_row(p, d) for p in day_rows)
        else:
            week.append({
                "date": d.isoformat(),
                "dow": _DOW[d.weekday()],
                "type": None,
                "name": None,
                "status": "unplanned",
                "duration_min": None,
            })

    # PlannedSession carries no TSS column; training_load owns the estimator that
    # scales the athlete's own recent TSS-per-minute by planned duration.
    baseline = estimate_historical_pace_and_tss(user.id, db=db)
    planned_tss = 0.0
    for p in rows:
        est = estimate_planned_session_metrics(baseline, p.session_type, p.structure)
        planned_tss += float(est.get("estimated_tss") or 0.0)

    # "so far" is literal — clamped to today, so a session dated later this week
    # doesn't get counted as already done.
    logged = get_weekly_volume(str(user.id), week_start, min(week_end, today))["total_tss"]

    today_rows = [r for r in week if r["date"] == today.isoformat() and r["type"]]
    return {
        "today": today_rows[0] if today_rows else None,
        "week": week,
        "week_planned_tss": _f(planned_tss, 1),
        "week_logged_tss_so_far": _f(logged, 1),
    }


# ── findings ─────────────────────────────────────────────────────────────────

def _assemble_findings(user) -> list[dict]:
    """Visible gap-analysis findings only — muted/suppressed items are excluded.

    A finding the athlete already dismissed, or one inside its suppression
    cooldown, is noise in a daily message; the app decided not to show it and the
    export honours that decision.
    """
    from backend.main import get_gap_analysis

    payload = json.loads(get_gap_analysis(user=user).body)
    findings: list[dict] = []
    for f in payload.get("findings") or []:
        findings.append({
            "code": f.get("code"),
            "severity": f.get("severity"),
            "evidence": f.get("evidence_text") or f.get("recommendation"),
            "load_adding": f.get("load_adding"),
        })
    return findings


# ── Public API ───────────────────────────────────────────────────────────────

def build_export(user_id, window_days: int = DEFAULT_WINDOW_DAYS, today: Optional[_date] = None) -> dict:
    """Assemble the complete coach-export payload for a user.

    Pure assembly: no LLM, no HTTP, no writes. Raises ValueError for an unknown
    user or an out-of-range window; individual blocks degrade to their null shape
    and are listed in ``meta.degraded`` rather than failing the whole export.
    """
    if not (MIN_WINDOW_DAYS <= window_days <= MAX_WINDOW_DAYS):
        raise ValueError(
            f"window_days must be between {MIN_WINDOW_DAYS} and {MAX_WINDOW_DAYS}, "
            f"got {window_days}"
        )

    from backend.models import User

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    now = _datetime.now(BANGKOK_TZ)
    today = today or now.date()
    degraded: list[str] = []

    with Session(engine) as db:
        user = db.get(User, uid)
        if user is None:
            raise ValueError(f"user {uid} not found")

        meta = _safe(
            "meta",
            lambda: _assemble_meta(db, user, today, window_days, now.isoformat()),
            {
                "schema_version": SCHEMA_VERSION,
                "prompt_version": PROMPT_VERSION,
                "generated_at": now.isoformat(),
                "timezone": "Asia/Bangkok",
                "window_days": window_days,
                "previous_export_date": None,
                "data_freshness": {},
                "note": _META_NOTE,
                "acwr_null_note": _ACWR_NULL_NOTE,
                "degraded": [],
            },
            degraded,
        )

        body = _safe(
            "body",
            lambda: _assemble_body(db, user, today, window_days),
            dict(_NULL_BODY),
            degraded,
        )
        athlete = _safe(
            "athlete",
            lambda: _assemble_athlete(db, user, today, body),
            dict(_NULL_ATHLETE),
            degraded,
        )
        goal = _safe(
            "goal", lambda: _assemble_goal(db, user, today, body), dict(_NULL_GOAL), degraded
        )
        goal_distance = ((goal.get("race") or {}) or {}).get("distance")
        fitness = _safe(
            "fitness",
            lambda: _assemble_fitness(user.id, today, goal_distance),
            dict(_NULL_FITNESS),
            degraded,
        )
        constraints = _safe(
            "constraints",
            lambda: _assemble_constraints(db, user, today, fitness),
            dict(_NULL_CONSTRAINTS),
            degraded,
        )
        performance = _safe(
            "performance", lambda: _assemble_performance(user), dict(_NULL_PERFORMANCE), degraded
        )
        training = _safe(
            "training",
            lambda: _assemble_training(db, user, today, window_days),
            dict(_NULL_TRAINING),
            degraded,
        )
        races = _safe("races", lambda: _assemble_races(db, user, today), dict(_NULL_RACES), degraded)
        habits = _safe(
            "habits", lambda: _assemble_habits(db, user, today), dict(_NULL_HABITS), degraded
        )
        plan = _safe("plan", lambda: _assemble_plan(db, user, today), dict(_NULL_PLAN), degraded)
        findings = _safe("findings", lambda: _assemble_findings(user), [], degraded)

    _safe(
        "anchor_titles",
        lambda: _title_anchors(
            performance,
            training.pop("_names_by_run_id", {}),
            training.pop("_names_by_date", {}),
        ),
        None,
        degraded,
    )
    # Drop the lookups even when titling failed — they are plumbing, not payload.
    training.pop("_names_by_run_id", None)
    training.pop("_names_by_date", None)

    meta["degraded"] = degraded
    return {
        "meta": meta,
        "athlete": athlete,
        "goal": goal,
        "constraints": constraints,
        "fitness": fitness,
        "performance": performance,
        "body": body,
        "training": training,
        "races": races,
        "habits": habits,
        "plan": plan,
        "findings": findings,
    }


# ── Prompt template ──────────────────────────────────────────────────────────
# Behaviour only — zero facts. Identity, numbers and constraints all live in the
# payload (athlete / goal / constraints), so the template never goes stale when
# the athlete's situation changes. Paired with SCHEMA_VERSION; bump both together.

PROMPT_TEMPLATE = f"""\
# Daily coach message — perf-coach export ({PROMPT_VERSION} / schema v{SCHEMA_VERSION})

You are my running and body-composition coach. Below my data is a JSON payload
from perf-coach, the app that tracks my training. Read these rules first, then
write me today's coach message.

## Rules

1. **The app's numbers are the truth.** `fitness`, `performance`, `body` and
   `goal` are canonical — perf-coach computed them. Do not recompute CTL, ACWR,
   a weight trend, a score, or a race estimate from the raw sessions, and never
   contradict a canonical value. `training.sessions` are context: they explain
   *why* a canonical number moved. They are never a source for *what* it is.
2. **Never invent a number.** If a field is `null`, it is unknown — say so
   plainly or leave it out. Do not fill a gap with a typical value, and do not
   present a rate whose `readable` flag is `false` as a fact.
3. **`constraints` are hard bounds.** No week above
   `constraints.acwr_ceiling_weekly_tss`, no rest-day intake below
   `constraints.ea_floor_kcal_rest_day`, no deficit above
   `constraints.max_deficit_kcal_per_day`. Respect
   `constraints.current_verdict` — if it says hold or back off, do not propose
   more load, whatever the goal says.
4. **Read who I am from the data.** Age, mass, history, race, target and
   context are in `athlete` and `goal`. Don't ask me for what's already there.
5. **Write a coach message, not an analysis report.** Talk to me directly, in
   plain language. One clear action per section. Name the evidence when it
   changes what I should do; skip it when it doesn't. No tables, no headers
   beyond the four below, no restating the payload back at me.

## Sections

Write exactly these four, in order, short:

- **Today** — what to do today and why, given `plan.today`, `fitness.tsb` and
  `constraints.current_verdict`.
- **This week** — how the rest of the week should go: `plan.week`,
  `plan.week_planned_tss` vs `plan.week_logged_tss_so_far`, and the ceiling.
- **Body** — where the weight trend actually is (`body.state`, and its CI), what
  it means for `goal.body`, and the one intake change worth making. If
  `body.readable` is `false`, say the data can't answer yet and tell me what to
  log.
- **Season check** — am I on line for `goal.race`? Compare
  `goal.race.current_estimate` to `goal.race.goal_time` and name the gap in
  `performance` or `fitness` that decides it. If `meta.previous_export_date` is
  recent and nothing material moved since, say so in one line and stop.

Then stop. No summary, no closing pep talk.

## My data
"""


# ── Payload rendering ────────────────────────────────────────────────────────

def _render_json(value: Any, indent: int = 0) -> str:
    """Serialise the payload with leaf objects on ONE line each.

    ``json.dumps(indent=2)`` renders every session row across ten lines, which
    triples the blob for zero readability gain; ``indent=None`` produces one
    unreadable line. This walks the structure and compacts any dict/list that
    contains no nested container — so a session row is exactly the one-line
    object the format calls for, while the block structure stays skimmable.
    """
    pad = " " * indent
    inner_pad = " " * (indent + 2)

    def _is_leaf(v: Any) -> bool:
        if isinstance(v, dict):
            return not any(isinstance(x, (dict, list)) for x in v.values())
        if isinstance(v, list):
            return not any(isinstance(x, (dict, list)) for x in v)
        return True

    if isinstance(value, dict):
        if not value:
            return "{}"
        if _is_leaf(value):
            return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
        parts = [
            f"{inner_pad}{json.dumps(k, ensure_ascii=False)}: "
            f"{_render_json(v, indent + 2)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(parts) + f"\n{pad}}}"

    if isinstance(value, list):
        if not value:
            return "[]"
        if _is_leaf(value):
            return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
        parts = [f"{inner_pad}{_render_json(v, indent + 2)}" for v in value]
        return "[\n" + ",\n".join(parts) + f"\n{pad}]"

    return json.dumps(value, ensure_ascii=False)


def build_paste_blob(export: dict) -> str:
    """Template first, data last — the instructions must be read before the payload."""
    return PROMPT_TEMPLATE + "\n```json\n" + _render_json(export) + "\n```\n"
