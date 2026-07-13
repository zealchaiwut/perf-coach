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

from sqlalchemy import text

from backend.services.gap_analysis.registry import RuleRegistry
from backend.services.gap_analysis.schemas import GapAnalysisFinding  # re-export

_log = logging.getLogger(__name__)

_REGISTRY = RuleRegistry()

__all__ = ["GapAnalysisFinding", "run_gap_analysis", "_REGISTRY"]


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

    # Load-mix rules (issue #1372)
    from backend.services.gap_analysis.rules.load_mix import (
        intensity_too_hard,
        aerobic_durability_gap,
        speed_neglected,
    )
    _REGISTRY.register(requires=["intensity_4w"])(intensity_too_hard)
    _REGISTRY.register(requires=["long_run_decoupling_4w"])(aerobic_durability_gap)
    _REGISTRY.register(requires=["speed_score_history_8w", "quality_sessions_3w"])(speed_neglected)


_register_builtin_rules()
