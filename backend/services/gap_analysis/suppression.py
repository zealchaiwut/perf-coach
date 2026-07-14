"""Suppression logic for gap-analysis findings (issue #1377).

classify_finding() decides whether a finding is visible or suppressed based on:
- Dismissed: 28-day window from dismissed_at; severity-rise override
- Accepted: same-week → show with check state; subsequent weeks → suppress if evidence unchanged
"""
from __future__ import annotations

import datetime
import hashlib
import json

SUPPRESSION_DAYS = 28


def evidence_hash(evidence: list) -> str:
    """Stable SHA-256 hash of an evidence list (sorted by metric for determinism)."""
    canonical = json.dumps(
        sorted(evidence, key=lambda x: x.get("metric", "")),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def classify_finding(
    *,
    code: str,
    current_severity: int,
    current_week_status: str,
    recent_dismissed: dict | None,
    recent_accepted: dict | None,
    current_evidence_hash: str,
) -> dict:
    """Classify one finding as visible or suppressed.

    Parameters
    ----------
    code                  Gap rule code (for context in result).
    current_severity      Severity from this week's engine run.
    current_week_status   status column of this week's gap_findings row.
    recent_dismissed      Most recent dismissed row within SUPPRESSION_DAYS, or None.
                          Keys: dismissed_at (datetime), dismissed_severity (int).
    recent_accepted       Most recent accepted row, or None.
                          Keys: accepted_evidence_hash (str), is_current_week (bool).
    current_evidence_hash SHA-256 hash of this week's engine evidence.

    Returns
    -------
    dict with at minimum:
      suppressed   bool
      status       str — "active" | "accepted" | "dismissed"
      severity_rose  bool (True when severity rose above dismissed level)
      reactivated    bool (True when evidence changed → acceptance expired)
      reason       str | None — "dismissed" | "accepted" | None
    """
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    # ── Dismissal check ───────────────────────────────────────────────────────
    if recent_dismissed:
        dismissed_at = recent_dismissed["dismissed_at"]
        dismissed_severity = recent_dismissed["dismissed_severity"]
        # Ensure timezone-aware comparison
        if dismissed_at.tzinfo is None:
            dismissed_at = dismissed_at.replace(tzinfo=datetime.timezone.utc)
        age_days = (now - dismissed_at).total_seconds() / 86400
        within_window = age_days < SUPPRESSION_DAYS
        severity_rose = current_severity > dismissed_severity

        if within_window and not severity_rose:
            return {
                "suppressed": True,
                "status": "dismissed",
                "severity_rose": False,
                "reactivated": False,
                "reason": "dismissed",
            }
        return {
            "suppressed": False,
            "status": "active",
            "severity_rose": severity_rose,
            "reactivated": False,
            "reason": None,
        }

    # ── Accepted check ────────────────────────────────────────────────────────
    if current_week_status == "accepted":
        return {
            "suppressed": False,
            "status": "accepted",
            "severity_rose": False,
            "reactivated": False,
            "reason": None,
        }

    if recent_accepted:
        is_current_week = recent_accepted.get("is_current_week", False)
        if is_current_week:
            return {
                "suppressed": False,
                "status": "accepted",
                "severity_rose": False,
                "reactivated": False,
                "reason": None,
            }
        accepted_hash = recent_accepted["accepted_evidence_hash"]
        if accepted_hash and accepted_hash == current_evidence_hash:
            return {
                "suppressed": True,
                "status": "accepted",
                "severity_rose": False,
                "reactivated": False,
                "reason": "accepted",
            }
        # Evidence changed — reactivate
        return {
            "suppressed": False,
            "status": "active",
            "severity_rose": False,
            "reactivated": True,
            "reason": None,
        }

    # ── Active ────────────────────────────────────────────────────────────────
    return {
        "suppressed": False,
        "status": current_week_status or "active",
        "severity_rose": False,
        "reactivated": False,
        "reason": None,
    }


def apply_suppression(db, user_id, week_start: datetime.date, findings: list[dict]) -> dict:
    """Partition findings into visible and muted lists.

    Queries DB for suppression context (dismissed/accepted history) and applies
    classify_finding() to each finding in the current week's enriched list.

    Returns {"findings": [...visible...], "muted": [...suppressed...]}
    Each item in both lists is the enriched finding dict extended with "status".
    """
    from sqlalchemy import text

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    suppression_cutoff = now - datetime.timedelta(days=SUPPRESSION_DAYS)

    visible = []
    muted = []

    for f in findings:
        code = f["code"]
        severity = f["severity"]
        ev_hash = evidence_hash(f.get("evidence") or [])

        # Most recent dismissed row within suppression window (any week)
        row_d = db.execute(
            text("""
                SELECT dismissed_at, dismissed_severity
                FROM gap_findings
                WHERE user_id = :uid
                  AND code = :code
                  AND status = 'dismissed'
                  AND dismissed_at IS NOT NULL
                  AND dismissed_at >= :cutoff
                ORDER BY dismissed_at DESC
                LIMIT 1
            """),
            {"uid": str(user_id), "code": code, "cutoff": suppression_cutoff},
        ).fetchone()
        recent_dismissed = None
        if row_d:
            recent_dismissed = {
                "dismissed_at": row_d[0],
                "dismissed_severity": row_d[1],
            }

        # Current week's DB row status
        row_cur = db.execute(
            text("""
                SELECT status
                FROM gap_findings
                WHERE user_id = :uid AND week_start = :ws AND code = :code
            """),
            {"uid": str(user_id), "ws": week_start.isoformat(), "code": code},
        ).fetchone()
        current_week_status = row_cur[0] if row_cur else "active"

        # Most recent accepted row (any week)
        row_a = db.execute(
            text("""
                SELECT week_start, accepted_evidence_hash
                FROM gap_findings
                WHERE user_id = :uid
                  AND code = :code
                  AND status = 'accepted'
                  AND accepted_evidence_hash IS NOT NULL
                ORDER BY week_start DESC
                LIMIT 1
            """),
            {"uid": str(user_id), "code": code},
        ).fetchone()
        recent_accepted = None
        if row_a:
            accepted_week = row_a[0]
            if hasattr(accepted_week, "isoformat"):
                accepted_week = accepted_week.isoformat() if not isinstance(accepted_week, str) else accepted_week
            else:
                accepted_week = str(accepted_week)
            is_current_week = accepted_week == week_start.isoformat()
            recent_accepted = {
                "accepted_evidence_hash": row_a[1],
                "is_current_week": is_current_week,
            }

        result = classify_finding(
            code=code,
            current_severity=severity,
            current_week_status=current_week_status,
            recent_dismissed=recent_dismissed,
            recent_accepted=recent_accepted,
            current_evidence_hash=ev_hash,
        )

        enriched = {**f, "status": result["status"]}

        if result["suppressed"]:
            muted.append(enriched)
        else:
            visible.append(enriched)

    return {"findings": visible, "muted": muted}
