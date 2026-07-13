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


_register_builtin_rules()
