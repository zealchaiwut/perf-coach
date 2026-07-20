"""Gap analyzer engine (issue #1370).

Entry point: run_gap_analysis(db, user_id, today) → payload dict

Gathers inputs from existing services, runs every registered rule, upserts
findings into gap_findings (preserving status on conflict), and returns the
full payload including skipped_rules for transparency.
"""
from __future__ import annotations

import datetime
import logging
import uuid

from sqlalchemy import bindparam, text

from backend.services.gap_analysis.registry import RuleRegistry
from backend.services.gap_analysis.schemas import GapAnalysisFinding  # re-export

_log = logging.getLogger(__name__)

_REGISTRY = RuleRegistry()

# Canonical run-matching predicate used by every gather query in this module.
# Using lower(workout_type) LIKE '%run%' instead of exact match so that subtypes
# ('trail_run', 'long_run') and mixed-case variants ('Run') are all counted.
_RUN_FILTER = "lower(workout_type) LIKE '%run%'"

__all__ = ["GapAnalysisFinding", "run_gap_analysis", "_REGISTRY", "_RUN_FILTER"]


# ── Input gathering ───────────────────────────────────────────────────────────

def _gather_form_metrics(db, user_id: uuid.UUID, today: datetime.date) -> dict:
    """Query run_form_metrics and partition into recent (0-28d), prior (28-56d),
    and long_baseline (56-180d) windows.

    Returns a dict with keys:
      recent_runs       — list of row dicts for the last 28 days
      prior_runs        — list of row dicts for days 29-56
      long_baseline_runs — list of row dicts for days 57-180
    """
    cutoff_recent = today - datetime.timedelta(days=28)
    cutoff_prior = today - datetime.timedelta(days=56)
    cutoff_long = today - datetime.timedelta(days=180)

    rows = db.execute(
        text("""
            SELECT run_date,
                   CAST(lss_kn_m AS double precision),
                   CAST(gct_ms AS double precision),
                   CAST(cadence_spm AS double precision),
                   CAST(power_w AS double precision)
            FROM run_form_metrics
            WHERE user_id = :uid
              AND run_date >= :cutoff_long
              AND run_date <= :today
            ORDER BY run_date DESC
        """),
        {"uid": str(user_id), "cutoff_long": cutoff_long.isoformat(), "today": today.isoformat()},
    ).fetchall()

    recent_runs = []
    prior_runs = []
    long_baseline_runs = []

    for run_date, lss, gct, cad, pw in rows:
        entry = {
            "run_date": run_date.isoformat() if hasattr(run_date, "isoformat") else str(run_date),
            "lss_kn_m": lss,
            "gct_ms": gct,
            "cadence_spm": cad,
            "power_w": pw,
        }
        if run_date > cutoff_recent:
            recent_runs.append(entry)
        elif run_date > cutoff_prior:
            prior_runs.append(entry)
        else:
            long_baseline_runs.append(entry)

    return {
        "recent_runs": recent_runs,
        "prior_runs": prior_runs,
        "long_baseline_runs": long_baseline_runs,
    }


def _gather_intensity_4w(db, user_id: uuid.UUID, today: datetime.date) -> dict | None:
    """Aggregate 4-week intensity distribution from stored split bands.

    Uses the intensity_band column persisted on workout_splits at classification
    time.  Returns None when no classifiable split data exists in the window.
    """
    from_date = today - datetime.timedelta(days=28)

    rows = db.execute(
        text("""
            SELECT ws.duration_seconds, ws.intensity_band
            FROM workout_splits ws
            JOIN workouts w ON ws.workout_id = w.id
            WHERE w.user_id = :uid
              AND w.workout_date >= :from_date
              AND w.workout_date <= :today
              AND lower(w.workout_type) LIKE '%run%'
              AND ws.intensity_band IS NOT NULL
              AND ws.duration_seconds IS NOT NULL
              AND ws.duration_seconds > 0
        """),
        {"uid": str(user_id), "from_date": from_date.isoformat(), "today": today.isoformat()},
    ).fetchall()

    if not rows:
        return None

    _LOW = {"easy", "steady"}
    _MOD = {"tempo"}
    _HIGH = {"threshold", "hard"}

    low_s = moderate_s = high_s = 0.0
    for dur, band in rows:
        d = float(dur)
        if band in _LOW:
            low_s += d
        elif band in _MOD:
            moderate_s += d
        elif band in _HIGH:
            high_s += d

    total = low_s + moderate_s + high_s
    if total == 0:
        return None

    return {
        "low_pct": round(low_s / total * 100, 2),
        "moderate_pct": round(moderate_s / total * 100, 2),
        "high_pct": round(high_s / total * 100, 2),
    }


def _gather_long_run_decoupling_4w(db, user_id: uuid.UUID, today: datetime.date) -> dict:
    """Gather average aerobic decoupling for long runs over the past 4 weeks.

    Long runs are those with duration_seconds > LONG_RUN_MIN_SECONDS (40 min).
    Uses the stored decoupling_percent column on workouts.
    """
    from backend.services.gap_analysis.rules.load_mix import LONG_RUN_MIN_SECONDS

    from_date = today - datetime.timedelta(days=28)

    rows = db.execute(
        text("""
            SELECT decoupling_percent
            FROM workouts
            WHERE user_id = :uid
              AND workout_date >= :from_date
              AND workout_date <= :today
              AND lower(workout_type) LIKE '%run%'
              AND duration_seconds > :min_secs
              AND decoupling_percent IS NOT NULL
        """),
        {
            "uid": str(user_id),
            "from_date": from_date.isoformat(),
            "today": today.isoformat(),
            "min_secs": LONG_RUN_MIN_SECONDS,
        },
    ).fetchall()

    count = len(rows)
    if count == 0:
        return {"avg_decoupling_pct": None, "count": 0}

    avg = sum(float(r[0]) for r in rows) / count
    return {"avg_decoupling_pct": round(avg, 2), "count": count}


def _gather_speed_score_8w(db, user_id: uuid.UUID, today: datetime.date) -> dict | None:
    """Gather speed score start/end values over the past 8 weeks using the
    latest formula_version from performance_score_history.

    Returns None when < 2 score rows exist in the window.
    """
    from_date = today - datetime.timedelta(days=56)

    latest_version = db.execute(
        text("""
            SELECT formula_version
            FROM performance_score_history
            WHERE user_id = :uid
            ORDER BY score_date DESC
            LIMIT 1
        """),
        {"uid": str(user_id)},
    ).scalar()

    if latest_version is None:
        return None

    rows = db.execute(
        text("""
            SELECT score_date, speed
            FROM performance_score_history
            WHERE user_id = :uid
              AND formula_version = :fv
              AND score_date >= :from_date
              AND score_date <= :today
              AND speed IS NOT NULL
            ORDER BY score_date ASC
        """),
        {
            "uid": str(user_id),
            "fv": latest_version,
            "from_date": from_date.isoformat(),
            "today": today.isoformat(),
        },
    ).fetchall()

    if len(rows) < 2:
        return None

    return {
        "oldest_speed": float(rows[0][1]),
        "newest_speed": float(rows[-1][1]),
        "oldest_date": rows[0][0].isoformat() if hasattr(rows[0][0], "isoformat") else str(rows[0][0]),
        "newest_date": rows[-1][0].isoformat() if hasattr(rows[-1][0], "isoformat") else str(rows[-1][0]),
        "formula_version": latest_version,
        "count": len(rows),
    }


def _gather_quality_sessions_3w(db, user_id: uuid.UUID, today: datetime.date) -> dict:
    """Count quality run sessions (speed_signal IS NOT NULL) over the past 3 weeks."""
    from_date = today - datetime.timedelta(days=21)

    count = db.execute(
        text("""
            SELECT COUNT(*)
            FROM workouts
            WHERE user_id = :uid
              AND workout_date >= :from_date
              AND workout_date <= :today
              AND lower(workout_type) LIKE '%run%'
              AND speed_signal IS NOT NULL
        """),
        {
            "uid": str(user_id),
            "from_date": from_date.isoformat(),
            "today": today.isoformat(),
        },
    ).scalar() or 0

    return {"count": int(count), "window_weeks": 3}


def _gather_endurance_score_8w(db, user_id: uuid.UUID, today: datetime.date) -> dict | None:
    """Gather endurance score start/end values over the past 8 weeks using the
    latest formula_version from performance_score_history.

    Mirrors _gather_speed_score_8w but reads the endurance column.
    Returns None when < 2 score rows exist in the window.
    """
    from_date = today - datetime.timedelta(days=56)

    latest_version = db.execute(
        text("""
            SELECT formula_version
            FROM performance_score_history
            WHERE user_id = :uid
            ORDER BY score_date DESC
            LIMIT 1
        """),
        {"uid": str(user_id)},
    ).scalar()

    if latest_version is None:
        return None

    rows = db.execute(
        text("""
            SELECT score_date, endurance
            FROM performance_score_history
            WHERE user_id = :uid
              AND formula_version = :fv
              AND score_date >= :from_date
              AND score_date <= :today
              AND endurance IS NOT NULL
            ORDER BY score_date ASC
        """),
        {
            "uid": str(user_id),
            "fv": latest_version,
            "from_date": from_date.isoformat(),
            "today": today.isoformat(),
        },
    ).fetchall()

    if len(rows) < 2:
        return None

    return {
        "oldest_endurance": float(rows[0][1]),
        "newest_endurance": float(rows[-1][1]),
        "oldest_date": rows[0][0].isoformat() if hasattr(rows[0][0], "isoformat") else str(rows[0][0]),
        "newest_date": rows[-1][0].isoformat() if hasattr(rows[-1][0], "isoformat") else str(rows[-1][0]),
        "formula_version": latest_version,
        "count": len(rows),
    }


def _gather_easy_runs_3w(db, user_id: uuid.UUID, today: datetime.date) -> dict:
    """Count easy-volume run sessions (speed_signal IS NULL) over the past 3 weeks.

    Easy/aerobic runs are those without a quality speed signal — the volume
    complement to quality_sessions_3w.  Used as volume evidence for base_neglected.
    """
    from_date = today - datetime.timedelta(days=21)

    count = db.execute(
        text("""
            SELECT COUNT(*)
            FROM workouts
            WHERE user_id = :uid
              AND workout_date >= :from_date
              AND workout_date <= :today
              AND lower(workout_type) LIKE '%run%'
              AND speed_signal IS NULL
        """),
        {
            "uid": str(user_id),
            "from_date": from_date.isoformat(),
            "today": today.isoformat(),
        },
    ).scalar() or 0

    return {"count": int(count), "window_weeks": 3}


def _gather_muscle_load_ledger(user_id: uuid.UUID, today: datetime.date) -> dict | None:
    """Build the muscle_load_ledger input for muscle-balance rules (issue #1381).

    Calls muscle_load_acwr.compute() (which uses its own DB session) and enriches
    each group with:
      trending_up     — True when this week's load exceeds the prior week
      weeks_untrained — consecutive recent weeks with near-zero weekly load

    Returns None when there are fewer than 4 weeks with any muscle-load data
    (insufficient history → rules will be skipped and reported as such).
    """
    from backend.services.muscle_load_acwr import (
        compute as _ml_compute,
        CHRONIC_FLOOR as _CHRONIC_FLOOR,
    )

    data = _ml_compute(user_id, today, weeks=8)
    weekly_series = data["weekly_series"]  # list of {week_start, week_end, groups}, oldest first

    # Count weeks with any meaningful load data across all groups
    weeks_with_data = sum(
        1 for entry in weekly_series
        if any(v > 0 for v in entry["groups"].values())
    )
    if weeks_with_data < 4:
        return None

    groups = data["groups"]
    result_groups: dict = {}
    for group, gdata in groups.items():
        last_load = weekly_series[-1]["groups"].get(group, 0.0)
        prior_load = weekly_series[-2]["groups"].get(group, 0.0) if len(weekly_series) >= 2 else 0.0
        trending_up = last_load > prior_load

        weeks_untrained = 0
        for entry in reversed(weekly_series):
            week_load = entry["groups"].get(group, 0.0)
            if week_load < _CHRONIC_FLOOR:
                weeks_untrained += 1
            else:
                break

        result_groups[group] = {
            **gdata,
            "trending_up": trending_up,
            "weeks_untrained": weeks_untrained,
        }

    return {
        "groups": result_groups,
        "history_weeks": len(weekly_series),
    }


def _gather_training_verdict(user_id: uuid.UUID, today: datetime.date) -> str | None:
    """Return the current training verdict ("back_off" / "hold" / "build").

    Uses training_load.current_load (which reads from its own engine/session)
    and training_verdict.compute_verdict.  Returns None on any failure so that
    rules default to their nominal severity when verdict data is unavailable.
    """
    try:
        from backend.services.training_load import current_load
        from backend.services.training_verdict import compute_verdict
        snap = current_load(str(user_id), today)
        return compute_verdict(snap)["verdict"]
    except Exception:
        _log.warning("training_verdict unavailable for gap analysis", exc_info=True)
        return None


def _gather_injury_log(db, user_id: uuid.UUID, today: datetime.date) -> list[dict]:
    """Query injury_log entries for the last 90 days (window for recurrent_niggle_area)."""
    cutoff = today - datetime.timedelta(days=90)
    rows = db.execute(
        text("""
            SELECT body_area, severity, started_on, ended_on
            FROM injury_log
            WHERE user_id = :uid
              AND started_on >= :cutoff
            ORDER BY started_on DESC
        """),
        {"uid": str(user_id), "cutoff": cutoff.isoformat()},
    ).fetchall()
    result = []
    for body_area, severity, started_on, ended_on in rows:
        result.append({
            "body_area": body_area,
            "severity": severity,
            "started_on": started_on.isoformat() if hasattr(started_on, "isoformat") else str(started_on),
            "ended_on": ended_on.isoformat() if ended_on and hasattr(ended_on, "isoformat") else (str(ended_on) if ended_on else None),
        })
    return result


def _gather_muscle_volume(db, user_id: uuid.UUID, today: datetime.date) -> list[dict]:
    """Query muscle_load_daily grouped by week and muscle_group for the last 8 weeks."""
    cutoff = today - datetime.timedelta(weeks=8)
    rows = db.execute(
        text("""
            SELECT
                DATE_TRUNC('week', load_date)::date AS week_start,
                muscle_group,
                SUM(CAST(load AS double precision)) AS weekly_load
            FROM muscle_load_daily
            WHERE user_id = :uid
              AND load_date >= :cutoff
            GROUP BY DATE_TRUNC('week', load_date)::date, muscle_group
            ORDER BY week_start, muscle_group
        """),
        {"uid": str(user_id), "cutoff": cutoff.isoformat()},
    ).fetchall()
    result = []
    for ws, muscle_group, weekly_load in rows:
        result.append({
            "week_start": ws.isoformat() if hasattr(ws, "isoformat") else str(ws),
            "muscle_group": muscle_group,
            "weekly_load": float(weekly_load) if weekly_load is not None else 0.0,
        })
    return result


def _gather_training_load(db, user_id: uuid.UUID, today: datetime.date) -> dict:
    """Query weekly running TSS for the last 8 weeks from workouts table."""
    cutoff = today - datetime.timedelta(weeks=8)
    rows = db.execute(
        text("""
            SELECT
                DATE_TRUNC('week', workout_date)::date AS week_start,
                SUM(COALESCE(tss, 0)) AS running_tss
            FROM workouts
            WHERE user_id = :uid
              AND lower(workout_type) LIKE '%run%'
              AND workout_date >= :cutoff
            GROUP BY DATE_TRUNC('week', workout_date)::date
            ORDER BY week_start
        """),
        {"uid": str(user_id), "cutoff": cutoff.isoformat()},
    ).fetchall()
    weekly = [
        {
            "week_start": ws.isoformat() if hasattr(ws, "isoformat") else str(ws),
            "running_tss": float(tss) if tss is not None else 0.0,
        }
        for ws, tss in rows
    ]
    return {"weekly": weekly}


def _gather_inputs(db, user_id: uuid.UUID, today: datetime.date, week_start: datetime.date) -> dict:
    """Collect available inputs for the rules engine.

    Each input gathered independently; failures omit the key so rules that
    require it are skipped gracefully.
    """
    inputs: dict = {"week_start": week_start}

    # structural_dose (issue #1369): last_plyo_days_ago, last_strength_days_ago, weekly breakdown
    try:
        from backend.services.structural_dose import compute_structural_dose
        inputs["structural_dose"] = compute_structural_dose(db, user_id, today, weeks=8)
    except Exception:
        _log.warning("structural_dose unavailable for gap analysis", exc_info=True)

    # form_metrics (issue #1368): per-run GCT, LSS, cadence, power — partitioned by window
    try:
        inputs["form_metrics"] = _gather_form_metrics(db, user_id, today)
    except Exception:
        _log.warning("form_metrics unavailable for gap analysis", exc_info=True)

    # training_verdict (issue #1372): back_off / hold / build guardrail
    try:
        inputs["training_verdict"] = _gather_training_verdict(user_id, today)
    except Exception:
        _log.warning("training_verdict unavailable for gap analysis", exc_info=True)

    # intensity_4w (issue #1372): 4-week duration-weighted intensity distribution
    try:
        inputs["intensity_4w"] = _gather_intensity_4w(db, user_id, today)
    except Exception:
        _log.warning("intensity_4w unavailable for gap analysis", exc_info=True)

    # long_run_decoupling_4w (issue #1372): avg decoupling on long runs over 4 weeks
    try:
        inputs["long_run_decoupling_4w"] = _gather_long_run_decoupling_4w(db, user_id, today)
    except Exception:
        _log.warning("long_run_decoupling_4w unavailable for gap analysis", exc_info=True)

    # speed_score_history_8w (issue #1372): speed score series over 8 weeks
    try:
        result = _gather_speed_score_8w(db, user_id, today)
        if result is not None:
            inputs["speed_score_history_8w"] = result
    except Exception:
        _log.warning("speed_score_history_8w unavailable for gap analysis", exc_info=True)

    # quality_sessions_3w (issue #1372): quality run session count over 3 weeks
    try:
        inputs["quality_sessions_3w"] = _gather_quality_sessions_3w(db, user_id, today)
    except Exception:
        _log.warning("quality_sessions_3w unavailable for gap analysis", exc_info=True)

    # endurance_score_history_8w (issue #1464): endurance score series over 8 weeks
    try:
        result = _gather_endurance_score_8w(db, user_id, today)
        if result is not None:
            inputs["endurance_score_history_8w"] = result
    except Exception:
        _log.warning("endurance_score_history_8w unavailable for gap analysis", exc_info=True)

    # easy_runs_3w (issue #1464): easy-volume run count over 3 weeks
    try:
        inputs["easy_runs_3w"] = _gather_easy_runs_3w(db, user_id, today)
    except Exception:
        _log.warning("easy_runs_3w unavailable for gap analysis", exc_info=True)

    # injury_log (issue #1373): recent niggle/injury entries for structural rules
    try:
        inputs["injury_log"] = _gather_injury_log(db, user_id, today)
    except Exception:
        _log.warning("injury_log unavailable for gap analysis", exc_info=True)

    # muscle_volume (issue #1373): weekly strength volume by muscle group
    try:
        inputs["muscle_volume"] = _gather_muscle_volume(db, user_id, today)
    except Exception:
        _log.warning("muscle_volume unavailable for gap analysis", exc_info=True)

    # training_load (issue #1373): weekly running TSS for ramp detection
    try:
        inputs["training_load"] = _gather_training_load(db, user_id, today)
    except Exception:
        _log.warning("training_load unavailable for gap analysis", exc_info=True)

    # muscle_load_ledger (issue #1381): per-group ACWR, classification, trend and history
    try:
        ledger = _gather_muscle_load_ledger(user_id, today)
        if ledger is not None:
            inputs["muscle_load_ledger"] = ledger
    except Exception:
        _log.warning("muscle_load_ledger unavailable for gap analysis", exc_info=True)

    return inputs


# ── Upsert helper ─────────────────────────────────────────────────────────────

def _upsert_finding(
    db,
    user_id: uuid.UUID,
    week_start: datetime.date,
    finding: GapAnalysisFinding,
    now: datetime.datetime,
) -> None:
    """Upsert one finding row. On conflict refresh evidence/rec/computed_at; preserve status."""
    import json

    db.execute(
        text("""
            INSERT INTO gap_findings
                (id, user_id, week_start, code, severity, recommendation, evidence,
                 target, computed_at, status, created_at)
            VALUES
                (gen_random_uuid(), :uid, :ws, :code, :severity, :rec, CAST(:ev AS jsonb),
                 :target, :cat, 'active', now())
            ON CONFLICT (user_id, week_start, code) DO UPDATE
               SET severity       = EXCLUDED.severity,
                   recommendation = EXCLUDED.recommendation,
                   evidence       = EXCLUDED.evidence,
                   target         = EXCLUDED.target,
                   computed_at    = EXCLUDED.computed_at
        """),
        {
            "uid": str(user_id),
            "ws": week_start.isoformat(),
            "code": finding.code,
            "severity": finding.severity,
            "rec": finding.recommendation,
            "ev": json.dumps(finding.evidence),
            "target": finding.target,
            "cat": now.isoformat(),
        },
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_gap_analysis(db, user_id: uuid.UUID, today: datetime.date) -> dict:
    """Compute gap findings for the user's current ISO week.

    Upserts to gap_findings preserving status. Returns:
    {
      "week_start": "YYYY-MM-DD",
      "computed_at": "ISO datetime",
      "findings": [...],
      "skipped_rules": [...],
    }
    """
    week_start = today - datetime.timedelta(days=today.weekday())
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    inputs = _gather_inputs(db, user_id, today, week_start)
    result = _REGISTRY.run_all(inputs=inputs, week_start=week_start)

    findings: list[GapAnalysisFinding] = result["findings"]
    skipped_rules: list[str] = result["skipped_rules"]

    for f in findings:
        try:
            _upsert_finding(db, user_id, week_start, f, now)
        except Exception:
            _log.error("Failed to upsert finding %s for user %s", f.code, user_id, exc_info=True)

    # Delete active rows whose code no longer fires this week (issue #1462).
    # Only active rows are removed; accepted/dismissed rows are preserved.
    firing_codes = [f.code for f in findings]
    try:
        if firing_codes:
            db.execute(
                text("""
                    DELETE FROM gap_findings
                    WHERE user_id = :uid
                      AND week_start = :ws
                      AND status = 'active'
                      AND code NOT IN :codes
                """).bindparams(bindparam("codes", expanding=True)),
                {"uid": str(user_id), "ws": week_start.isoformat(), "codes": firing_codes},
            )
        else:
            db.execute(
                text("""
                    DELETE FROM gap_findings
                    WHERE user_id = :uid
                      AND week_start = :ws
                      AND status = 'active'
                """),
                {"uid": str(user_id), "ws": week_start.isoformat()},
            )
    except Exception:
        _log.error("Failed to deactivate stale gap findings for user %s", user_id, exc_info=True)
    db.commit()

    return {
        "week_start": week_start.isoformat(),
        "computed_at": now.isoformat(),
        "findings": [
            {
                "code": f.code,
                "severity": f.severity,
                "recommendation": f.recommendation,
                "evidence": f.evidence,
                "target": f.target,
            }
            for f in findings
        ],
        "skipped_rules": skipped_rules,
    }


# ── Register built-in rules (deferred import avoids circular dependency) ──────

def _register_builtin_rules() -> None:
    from backend.services.gap_analysis.rules.no_recent_plyo import no_recent_plyo
    _REGISTRY.register(requires=["structural_dose"])(no_recent_plyo)

    from backend.services.gap_analysis.rules.plyo_deficit import plyo_deficit
    _REGISTRY.register(requires=["form_metrics", "structural_dose"])(plyo_deficit)

    from backend.services.gap_analysis.rules.gct_lengthening import gct_lengthening
    _REGISTRY.register(requires=["form_metrics"])(gct_lengthening)

    from backend.services.gap_analysis.rules.cadence_drift import cadence_drift
    _REGISTRY.register(requires=["form_metrics"])(cadence_drift)

    # Load-mix rules (issue #1372, #1464)
    from backend.services.gap_analysis.rules.load_mix import (
        intensity_too_hard,
        aerobic_durability_gap,
        speed_neglected,
        base_neglected,
    )
    _REGISTRY.register(requires=["intensity_4w"])(intensity_too_hard)
    _REGISTRY.register(requires=["long_run_decoupling_4w"])(aerobic_durability_gap)
    _REGISTRY.register(requires=["speed_score_history_8w", "quality_sessions_3w"])(speed_neglected)
    _REGISTRY.register(requires=["endurance_score_history_8w", "easy_runs_3w"])(base_neglected)

    # issue #1373: structural rules — registered after run-economy rules so that
    # strength_lapsed (severity 1) sees the higher-severity findings first
    from backend.services.gap_analysis.rules.recurrent_niggle_area import recurrent_niggle_area
    _REGISTRY.register(requires=["injury_log"])(recurrent_niggle_area)

    from backend.services.gap_analysis.rules.undertrained_area_under_ramp import undertrained_area_under_ramp
    _REGISTRY.register(requires=["muscle_volume", "training_load"])(undertrained_area_under_ramp)

    # strength_lapsed registered last among pack C rules so it sees prior findings
    from backend.services.gap_analysis.rules.strength_lapsed import strength_lapsed
    _REGISTRY.register(requires=["structural_dose"])(strength_lapsed)

    # Muscle-balance rules (issue #1381) — registered after pack C so that
    # recurrent_niggle_area can claim groups before these run.
    from backend.services.gap_analysis.rules.muscle_balance import (
        muscle_overused,
        muscle_untrained,
    )
    _REGISTRY.register(requires=["muscle_load_ledger"])(muscle_overused)
    _REGISTRY.register(requires=["muscle_load_ledger"])(muscle_untrained)


_register_builtin_rules()
