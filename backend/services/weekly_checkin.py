"""Weekly check-in model, snapshot, and week resolution (revamp P6-12)."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import Decision, PlannedSession, Race, WeeklyCheckIn, Workout
from backend.services.a_race_readiness_checklist import _fuel_run_ok, _run_workouts
from backend.services.body_log import seven_day_avg, weekly_rate_kg
from backend.services.body_log_store import body_log_week_rollup, _weight_rows
from backend.services.checkpoint_detector import is_run_workout
from backend.services.perf_a_race import next_a_race
from backend.services.checkin_changes import PROMPT_VERSION_WEEKLY, changes_to_raw_text, parse_changes_block
from backend.services.race_roles import compute_role_result, race_role
from backend.services.weekly_rollup import normalize_week_start, session_local_date, weekly_rollup
from backend.utils.time import today_bangkok, to_bangkok

NA = "not_available"
CARRIED_STATUSES = frozenset({"done", "partly", "not_yet"})
_MOTIVATION = frozenset({"low", "ok", "high"})
_BED_BUCKETS = frozenset({"0-2", "3-4", "5-7"})
_LINE = re.compile(r"^\s*([A-Za-z]+)\s*:\s*(.+)\S\s*$")
_CHANGE_TYPES = frozenset({"lessons", "skeleton", "goal", "review", "habits", "prefs"})


def na_val(value: Any, *, unit: str | None = None) -> dict[str, Any]:
    if value is None:
        return {"status": NA, "value": None, "unit": unit}
    return {"status": "ok", "value": value, "unit": unit}


def target_checkin_week_start(today: date) -> date:
    if today.weekday() == 6:
        return today - timedelta(days=6)
    return today - timedelta(days=today.weekday() + 7)


def checkin_open_for_week(today: date, week_start: date) -> bool:
    return today >= week_start + timedelta(days=6)


def _bed_bucket_from_count(n: int) -> str:
    if n <= 2:
        return "0-2"
    if n <= 4:
        return "3-4"
    return "5-7"


def _nights_before_half_past_midnight(session: Session, user_id: uuid.UUID, ws: date, we: date) -> Optional[int]:
    from backend.models import SleepRecord

    rows = (
        session.query(SleepRecord)
        .filter(SleepRecord.user_id == user_id, SleepRecord.sleep_date >= ws, SleepRecord.sleep_date <= we)
        .all()
    )
    if not rows:
        return None
    count = 0
    for row in rows:
        try:
            local = to_bangkok(row.start_at)
        except (ValueError, TypeError):
            continue
        t = (local.hour, local.minute)
        if t < (0, 30) or t >= (18, 0):
            count += 1
    return count


def _weight_block(session: Session, user_id: uuid.UUID, as_of: date) -> dict[str, Any]:
    rows = _weight_rows(session, user_id, as_of - timedelta(days=21), as_of)
    return {
        "avg_7d_kg": na_val(seven_day_avg(rows, as_of), unit="kg"),
        "weekly_rate_kg": na_val(weekly_rate_kg(rows, as_of), unit="kg"),
    }


def _longest_run(session: Session, user_id: uuid.UUID, ws: date, we: date) -> dict[str, Any]:
    workouts = (
        session.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= ws - timedelta(days=1),
            Workout.workout_date <= we + timedelta(days=1),
        )
        .all()
    )
    best_sec = None
    for w in workouts:
        if not is_run_workout(w.workout_type or ""):
            continue
        ld = session_local_date(w)
        if ws <= ld <= we and w.duration_seconds is not None:
            dur = int(w.duration_seconds)
            best_sec = dur if best_sec is None or dur > best_sec else best_sec
    target_sec = None
    for p in (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= ws,
            PlannedSession.planned_date <= we,
            PlannedSession.session_type == "run",
        )
        .all()
    ):
        dur = getattr(p, "duration_minutes", None) or (p.structure or {}).get("duration_minutes")
        if dur is not None:
            sec = int(float(dur) * 60)
            target_sec = sec if target_sec is None or sec > target_sec else target_sec
    return {
        "longest_run_seconds": na_val(best_sec, unit="seconds"),
        "longest_run_target_seconds": na_val(target_sec, unit="seconds"),
    }


def _fuel_rehearsals(session: Session, user_id: uuid.UUID, ws: date, we: date) -> dict[str, Any]:
    done = sum(1 for w in _run_workouts(session, user_id, ws, we) if _fuel_run_ok(w))
    due = 2 if next_a_race(session, user_id, we) is not None else None
    return {"fuel_rehearsals_done": na_val(done), "fuel_rehearsals_due": na_val(due)}


def _foot_blocks(session: Session, user_id: uuid.UUID, ws: date, we: date, run_count: int) -> dict[str, Any]:
    mobility_done = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= ws,
            PlannedSession.planned_date <= we,
            PlannedSession.session_type == "mobility",
            PlannedSession.status.in_(("done_auto", "done_manual")),
        )
        .count()
    )
    return {
        "foot_blocks_done": na_val(mobility_done if run_count or mobility_done else None),
        "runs_in_week": na_val(run_count),
    }


def _body_metrics(session: Session, user_id: uuid.UUID, ws: date) -> dict[str, Any]:
    roll = body_log_week_rollup(session, user_id, ws)
    lunch_n = roll.get("lunch_rule_yes_count")
    lunch_d = roll.get("lunch_rule_logged_days")
    return {
        "lunch_rule_yes_count": na_val(lunch_n if lunch_d else None),
        "lunch_rule_days_logged": na_val(lunch_d if lunch_d else None),
        "steps_avg": na_val(roll.get("steps_avg")),
        "feet_max": na_val(roll.get("feet_max")),
    }


def _races_in_week(session: Session, user_id: uuid.UUID, ws: date, we: date) -> list[dict[str, Any]]:
    rows = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.race_date >= ws, Race.race_date <= we)
        .order_by(Race.race_date.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for race in rows:
        main_w = session.query(Workout).filter(Workout.id == race.linked_workout_id).first() if race.linked_workout_id else None
        addon_w = session.query(Workout).filter(Workout.id == race.addon_workout_id).first() if race.addon_workout_id else None
        out.append(
            {
                "id": str(race.id),
                "name": race.name,
                "race_date": race.race_date.isoformat(),
                "role": race_role(race),
                "role_result": compute_role_result(race, main_w, addon_w),
            }
        )
    return out


def build_week_snapshot(session: Session, user_id: uuid.UUID, week_start: date, today: date) -> dict[str, Any]:
    ws = normalize_week_start(week_start)
    we = ws + timedelta(days=6)
    rollup = weekly_rollup(user_id, ws, session=session, today=today)
    planned_count = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= ws,
            PlannedSession.planned_date <= we,
            PlannedSession.session_type != "mobility",
        )
        .count()
    )
    run_count = int(rollup.get("runs") or 0)
    return {
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "sessions_done": na_val(int(rollup.get("session_count") or 0)),
        "sessions_planned": na_val(planned_count),
        "week_tss": na_val(rollup.get("tss_total")),
        **_longest_run(session, user_id, ws, we),
        **_weight_block(session, user_id, we),
        **_body_metrics(session, user_id, ws),
        **_fuel_rehearsals(session, user_id, ws, we),
        **_foot_blocks(session, user_id, ws, we, run_count),
        "races": _races_in_week(session, user_id, ws, we),
        "bed_nights_prefill": na_val(_nights_before_half_past_midnight(session, user_id, ws, we)),
    }


def _lines_from_changes(raw_text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in raw_text.splitlines():
        if line.strip().upper() == "CHANGES TO APPLY":
            continue
        m = _LINE.match(line)
        if m:
            out.append((m.group(1).lower(), m.group(2)))
    return out


def _parse_change_items(raw_text: str, *, decision_id: str | None = None, decided_on: date | None = None) -> list[dict[str, Any]]:
    items = parse_changes_block(raw_text, decided_on=decided_on)
    for item in items:
        if decision_id:
            item["source_decision_id"] = decision_id
    return items


def seed_carried_changes(session: Session, user_id: uuid.UUID, week_start: date) -> list[dict[str, Any]]:
    prev = (
        session.query(WeeklyCheckIn)
        .filter(WeeklyCheckIn.user_id == user_id, WeeklyCheckIn.week_start == week_start - timedelta(days=7))
        .first()
    )
    if prev and isinstance(prev.carried_changes, list):
        out = [
            {
                "id": item.get("id") or uuid.uuid4().hex,
                "change_type": item.get("change_type") or "goal",
                "text": item.get("text"),
                "status": "not_yet",
                "source_decision_id": item.get("source_decision_id"),
            }
            for item in prev.carried_changes
            if isinstance(item, dict) and item.get("text")
        ]
        if out:
            return out
    decision = (
        session.query(Decision)
        .filter(Decision.user_id == user_id, Decision.decided_on <= week_start - timedelta(days=1))
        .order_by(Decision.decided_on.desc(), Decision.created_at.desc())
        .first()
    )
    return [] if decision is None else _parse_change_items(decision.raw_text, decision_id=str(decision.id))


def get_or_create_checkin(session: Session, user_id: uuid.UUID, today: date) -> tuple[WeeklyCheckIn, dict[str, Any]]:
    week_start = target_checkin_week_start(today)
    row = session.query(WeeklyCheckIn).filter(WeeklyCheckIn.user_id == user_id, WeeklyCheckIn.week_start == week_start).first()
    if row is None:
        row = WeeklyCheckIn(user_id=user_id, week_start=week_start, carried_changes=seed_carried_changes(session, user_id, week_start))
        session.add(row)
        session.flush()
    row.snapshot = build_week_snapshot(session, user_id, week_start, today)
    meta = {
        "week_start": week_start.isoformat(),
        "available": checkin_open_for_week(today, week_start),
        "completed": row.completed_at is not None,
        "streak_days_to_a_race": _days_to_a_race(session, user_id, today),
    }
    return row, meta


def _days_to_a_race(session: Session, user_id: uuid.UUID, today: date) -> Optional[int]:
    race = next_a_race(session, user_id, today)
    return None if race is None else (race.race_date - today).days


def refresh_snapshot(session: Session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    row, meta = get_or_create_checkin(session, user_id, today)
    return checkin_payload(session, row, meta, today)


def checkin_payload(session: Session, row: WeeklyCheckIn, meta: dict[str, Any], today: date) -> dict[str, Any]:
    snap = row.snapshot if isinstance(row.snapshot, dict) else {}
    carried = row.carried_changes if isinstance(row.carried_changes, list) else []
    prefill_bed = None
    bed_field = snap.get("bed_nights_prefill")
    if isinstance(bed_field, dict) and bed_field.get("status") == "ok" and bed_field.get("value") is not None:
        prefill_bed = _bed_bucket_from_count(int(bed_field["value"]))
    return {
        **meta,
        "id": str(row.id),
        "snapshot": snap,
        "carried_changes": carried,
        "self_report": {
            "feet": row.feet,
            "bed_bucket": row.bed_bucket or prefill_bed,
            "motivation": row.motivation,
            "note": row.note,
        },
        "prompt_preview": build_prompt_preview_stub(session, row.user_id, snap, carried, row, today),
        "paste_back_href": "/coach#paste",
    }


def build_prompt_preview_stub(
    session: Session,
    user_id: uuid.UUID,
    snapshot: dict[str, Any],
    carried: list[dict[str, Any]],
    row: WeeklyCheckIn,
    today: date,
) -> str:
    lines = [f"prompt_version: {PROMPT_VERSION_WEEKLY}", "", "RULES: Canonical values are not recomputed.", "", "WEEK"]
    tss = snapshot.get("week_tss", {})
    lines.append(f"  TSS: {tss.get('value')}" if tss.get("status") == "ok" else "  TSS: not_available")
    sd, sp = snapshot.get("sessions_done", {}), snapshot.get("sessions_planned", {})
    if sd.get("status") == "ok" and sp.get("status") == "ok":
        lines.append(f"  Sessions: {sd.get('value')} / {sp.get('value')}")
    if carried:
        lines.extend(["", "LAST WEEK'S CHANGES"])
        for c in carried:
            lines.append(f"  [{c.get('status', 'not_yet')}] {c.get('change_type')}: {c.get('text')}")
    lines.extend(["", "End with CHANGES TO APPLY (paste back on /coach)."])
    return "\n".join(lines)


def apply_paste_back(
    session: Session,
    user_id: uuid.UUID,
    row: WeeklyCheckIn,
    raw_text: str,
    today: date,
    *,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parsed = items if items is not None else parse_changes_block(raw_text, decided_on=today)
    if not parsed:
        raise ValueError("no changes parsed")
    raw_store = raw_text.strip() if raw_text and "CHANGES TO APPLY" in raw_text.upper() else changes_to_raw_text(parsed)
    review_on = today + timedelta(days=7)
    for it in parsed:
        if it.get("change_type") == "review" and it.get("review_on"):
            try:
                review_on = date.fromisoformat(str(it["review_on"]))
            except ValueError:
                pass
            break
    decision = Decision(
        user_id=user_id,
        decided_on=today,
        source="weekly_checkin",
        raw_text=raw_store,
        applied=True,
        review_on=review_on,
    )
    session.add(decision)
    next_week = row.week_start + timedelta(days=7)
    nxt = session.query(WeeklyCheckIn).filter(WeeklyCheckIn.user_id == user_id, WeeklyCheckIn.week_start == next_week).first()
    carry = [{**it, "status": "not_yet", "source_decision_id": str(decision.id)} for it in parsed]
    if nxt is None:
        session.add(WeeklyCheckIn(user_id=user_id, week_start=next_week, carried_changes=carry))
    else:
        nxt.carried_changes = carry
    session.flush()
    return {"decision_id": str(decision.id), "parsed": parsed, "next_week_start": next_week.isoformat()}


def save_self_report(session: Session, row: WeeklyCheckIn, **fields: Any) -> None:
    if "feet" in fields:
        feet = fields["feet"]
        if feet is not None and (feet < 0 or feet > 3):
            raise ValueError("feet must be 0–3")
        row.feet = feet
    if "bed_bucket" in fields:
        bed = fields["bed_bucket"]
        if bed is not None and bed not in _BED_BUCKETS:
            raise ValueError("invalid bed_bucket")
        row.bed_bucket = bed
    if "motivation" in fields:
        mot = fields["motivation"]
        if mot is not None and mot not in _MOTIVATION:
            raise ValueError("invalid motivation")
        row.motivation = mot
    if "note" in fields:
        note = fields["note"]
        row.note = (note.strip() or None) if isinstance(note, str) else None
    row.updated_at = datetime.now(timezone.utc)


def save_carried_statuses(session: Session, row: WeeklyCheckIn, updates: list[dict[str, Any]]) -> None:
    by_id = {str(u.get("id")): u.get("status") for u in updates if u.get("id")}
    new_list = []
    for item in row.carried_changes or []:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id"))
        if iid in by_id:
            st = by_id[iid]
            if st not in CARRIED_STATUSES:
                raise ValueError(f"invalid status for {iid}")
            item = {**item, "status": st}
        new_list.append(item)
    row.carried_changes = new_list
    row.updated_at = datetime.now(timezone.utc)


def mark_complete(session: Session, row: WeeklyCheckIn) -> None:
    if row.completed_at is None:
        row.completed_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)


def is_week_checkin_done(session: Session, user_id: uuid.UUID, week_start: date) -> bool:
    row = session.query(WeeklyCheckIn).filter(WeeklyCheckIn.user_id == user_id, WeeklyCheckIn.week_start == week_start).first()
    return row is not None and row.completed_at is not None
