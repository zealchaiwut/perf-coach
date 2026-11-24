"""Session version snapshots for strength editor history (P2-4)."""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import SessionVersion


def _set_count(exercises: list[dict[str, Any]]) -> int:
    total = 0
    for ex in exercises or []:
        sets = ex.get("sets") or []
        if isinstance(sets, list):
            total += len(sets)
    return total


def summary_line(
    prev: Optional[dict[str, Any]],
    *,
    exercises: list[dict[str, Any]],
    duration_seconds: Optional[int],
    session_effort: Optional[int],
) -> str:
    """One-line human summary for a new version."""
    if prev is None:
        n_ex = len(exercises)
        return f"Initial save ({n_ex} exercises, {_set_count(exercises)} sets)"

    parts: list[str] = []
    prev_ex = prev.get("exercises_json") or []
    if len(exercises) != len(prev_ex):
        parts.append(f"{len(exercises)} exercises (was {len(prev_ex)})")
    prev_sets = _set_count(prev_ex if isinstance(prev_ex, list) else [])
    new_sets = _set_count(exercises)
    if new_sets != prev_sets:
        parts.append(f"{new_sets} sets (was {prev_sets})")
    if duration_seconds != prev.get("duration_seconds"):
        parts.append("duration changed")
    if session_effort != prev.get("session_effort"):
        parts.append("effort changed")
    if not parts:
        parts.append("exercise detail updated")
    return "; ".join(parts)


def snapshot_version(
    session: Session,
    workout_id,
    *,
    exercises: list[dict[str, Any]],
    duration_seconds: Optional[int],
    session_effort: Optional[int],
    tss: Optional[float],
) -> SessionVersion:
    prev = (
        session.query(SessionVersion)
        .filter(SessionVersion.workout_id == workout_id)
        .order_by(SessionVersion.saved_at.desc())
        .first()
    )
    prev_payload = None
    if prev is not None:
        prev_payload = {
            "exercises_json": prev.exercises_json,
            "duration_seconds": prev.duration_seconds,
            "session_effort": prev.session_effort,
        }
    line = summary_line(
        prev_payload,
        exercises=exercises,
        duration_seconds=duration_seconds,
        session_effort=session_effort,
    )
    row = SessionVersion(
        workout_id=workout_id,
        exercises_json=exercises,
        duration_seconds=duration_seconds,
        session_effort=session_effort,
        tss=tss,
        summary_line=line,
    )
    session.add(row)
    session.flush()
    return row


def list_versions(session: Session, workout_id) -> list[dict[str, Any]]:
    rows = (
        session.query(SessionVersion)
        .filter(SessionVersion.workout_id == workout_id)
        .order_by(SessionVersion.saved_at.desc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": str(r.id),
                "saved_at": r.saved_at.isoformat() if r.saved_at else None,
                "duration_seconds": r.duration_seconds,
                "session_effort": r.session_effort,
                "tss": int(r.tss) if r.tss is not None else None,
                "summary_line": r.summary_line,
                "exercises_json": r.exercises_json,
            }
        )
    return out