"""Coach block for the Performance page (revamp P4-12).

Copy check-in, the review-due card, evidence chips and the decision history.
No model call anywhere: review lines and summaries are read straight out of the
stored ``raw_text`` (``CHANGES TO APPLY`` lines look like ``review:  <text>``),
and evidence chips are a small fixed phrase -> reader mapping.

Weekly check-in (P6-13): done/due reads ``weekly_check_ins.completed_at``
for the target week. A pasted decision is no longer treated as the check-in.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any, Iterable, Optional

from backend.services.checkpoint_detector import is_run_workout
from backend.services.goal_habits import LONG_RUN_MIN_MINUTES

SUMMARY_MAX_CHARS = 140
HISTORY_LIMIT = 12
CHECKIN_LINK = "/v2/performance/check-in"
PASTE_LINK = "/coach#paste"

STATUS_OPEN = "open"
STATUS_KEPT = "kept"
STATUS_SKIPPED = "skipped"
STATUS_LABELS = {STATUS_OPEN: "Open", STATUS_KEPT: "Worked or kept", STATUS_SKIPPED: "Skipped"}

_LINE = re.compile(r"^\s*([A-Za-z]+)\s*:\s*(.*\S)\s*$")


def _lines(raw_text: str) -> list[tuple[str, str]]:
    out = []
    for line in (raw_text or "").splitlines():
        m = _LINE.match(line)
        if m:
            out.append((m.group(1).lower(), m.group(2)))
    return out


def review_lines(raw_text: str) -> list[str]:
    """The ``review:`` lines of a stored change list (the review question)."""
    return [text for key, text in _lines(raw_text) if key == "review"]


def summary_line(raw_text: str) -> str:
    """First ``skeleton:`` or ``goal:`` line; else the first non-heading line."""
    for key, text in _lines(raw_text):
        if key in ("skeleton", "goal"):
            return _clip(f"{key}: {text}")
    for line in (raw_text or "").splitlines():
        s = line.strip()
        if s and s.upper() != "CHANGES TO APPLY":
            return _clip(s)
    return ""


def _clip(text: str) -> str:
    return text if len(text) <= SUMMARY_MAX_CHARS else text[: SUMMARY_MAX_CHARS - 1].rstrip() + "\u2026"


# ── Due logic and status ─────────────────────────────────────────────────────

def is_due(review_on: Optional[date], outcome_note: Optional[str], applied: bool, today: date) -> bool:
    """Due on its review date and every day after, until an outcome is recorded.
    A decision marked not applied has nothing to review, so it is never due."""
    if review_on is None or not applied:
        return False
    return review_on <= today and not (outcome_note or "").strip()


def status_of(outcome_note: Optional[str], applied: bool) -> str:
    if not applied:
        return STATUS_SKIPPED
    return STATUS_KEPT if (outcome_note or "").strip() else STATUS_OPEN


def newest_due(decisions: Iterable[Any], today: date) -> Optional[Any]:
    """Newest decision (by decided_on, then created_at) that is due for review."""
    due = [d for d in decisions if is_due(d.review_on, d.outcome_note, bool(d.applied), today)]
    if not due:
        return None
    return max(due, key=lambda d: (d.decided_on, d.created_at.isoformat() if getattr(d, "created_at", None) else ""))


# ── Evidence chips: fixed phrase -> reader mapping ───────────────────────────

_LONG_RUN_PHRASE = re.compile(r"\blong[\s-]?runs?\b", re.I)
_GEL_PHRASE = re.compile(r"\b(?:first[\s-]?gel|gels?|fuel(?:l?ing)?)\b", re.I)


def _is_long_run(w) -> bool:
    secs = getattr(w, "duration_seconds", None)
    return (
        secs is not None
        and is_run_workout(getattr(w, "workout_type", "") or "")
        and secs >= LONG_RUN_MIN_MINUTES * 60
    )


def evidence_chips(review: list[str], workouts: Iterable[Any], since: date, today: date) -> list[dict[str, Any]]:
    """Chips for phrases found in the review lines; a miss is silently absent.

    - "long run(s)"  -> number of long runs (>= LONG_RUN_MIN_MINUTES) since the decision.
    - "gel" / "fuel" -> first-gel minute of the most recent long run that logged one
      (``workouts.first_gel_minute``).
    """
    text = " ".join(review)
    chips: list[dict[str, Any]] = []
    runs = [
        w for w in workouts
        if _is_long_run(w) and w.workout_date is not None and since <= w.workout_date <= today
    ]
    if _LONG_RUN_PHRASE.search(text):
        chips.append({
            "key": "long_runs",
            "label": f"Long runs since {since.isoformat()}",
            "value": len(runs),
        })
    if _GEL_PHRASE.search(text):
        logged = [w for w in runs if getattr(w, "first_gel_minute", None) is not None]
        if logged:
            latest = max(logged, key=lambda w: w.workout_date)
            chips.append({
                "key": "first_gel",
                "label": f"First gel, {latest.workout_date.isoformat()}",
                "value": int(latest.first_gel_minute),
                "unit": "min",
            })
    return chips


# ── Weekly check-in entry ────────────────────────────────────────────────────

def week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def checkin_state(
    decisions: Iterable[Any],
    today: date,
    *,
    session=None,
    user_id=None,
) -> dict[str, Any]:
    start, _end = week_bounds(today)
    done = False
    if session is not None and user_id is not None:
        try:
            from backend.services.weekly_checkin import is_week_checkin_done, target_checkin_week_start

            done = is_week_checkin_done(session, user_id, target_checkin_week_start(today))
        except Exception:
            done = False
    return {
        "week_start": start.isoformat(),
        "state": "done" if done else "due",
        "link": CHECKIN_LINK,
    }


# ── Assembly ─────────────────────────────────────────────────────────────────

def _decision_row(d) -> dict[str, Any]:
    status = status_of(d.outcome_note, bool(d.applied))
    return {
        "id": str(d.id),
        "decided_on": d.decided_on.isoformat(),
        "summary": summary_line(d.raw_text),
        "status": status,
        "status_label": STATUS_LABELS[status],
        "outcome_note": d.outcome_note,
        "review_on": d.review_on.isoformat() if d.review_on else None,
    }


def build_coach_block(
    decisions: list[Any],
    workouts: list[Any],
    today: date,
    *,
    session=None,
    user_id=None,
) -> dict[str, Any]:
    """Pure assembly from already-fetched decisions (newest first) and workouts."""
    due = newest_due(decisions, today)
    review = None
    if due is not None:
        lines = review_lines(due.raw_text)
        review = {
            "id": str(due.id),
            "decided_on": due.decided_on.isoformat(),
            "review_on": due.review_on.isoformat(),
            "review_lines": lines,
            "chips": evidence_chips(lines, workouts, due.decided_on, today),
        }
    return {
        "checkin": checkin_state(decisions, today, session=session, user_id=user_id),
        "review_due": review,
        "history": [_decision_row(d) for d in decisions[:HISTORY_LIMIT]],
        "paste_link": PASTE_LINK,
    }


def fetch_coach_block(session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    from backend.models import Decision, Workout

    decisions = (
        session.query(Decision)
        .filter(Decision.user_id == user_id)
        .order_by(Decision.decided_on.desc(), Decision.created_at.desc())
        .all()
    )
    due = newest_due(decisions, today)
    workouts: list = []
    if due is not None:
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date >= due.decided_on,
                Workout.workout_date <= today,
                Workout.duration_seconds.isnot(None),
            )
            .all()
        )
    return build_coach_block(decisions, workouts, today, session=session, user_id=user_id)
