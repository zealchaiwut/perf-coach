"""Daily-brief assembly service.

Single source of truth for building the SCHEMA_VERSION 2 Hermes coaching
brief. Both the CLI exporter (scripts/export_brief.py) and any future API
endpoint should call build_brief() from here instead of duplicating logic.

No HTTP calls — plan data comes from PlannedSession model directly; weight
status from backend.services.weight_plan.compute_weight_status.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.db import engine
from backend.services.guardrail import get_guardrail_result
from backend.services.training_load import current_load, get_snapshot_series
from backend.services.weight_plan import compute_weight_status

SCHEMA_VERSION = 3
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
DEFAULT_WINDOW_DAYS = 14

_NULL_WEIGHT_BLOCK: dict = {
    "current_kg": None,
    "trend_7d": None,
    "trend_28d": None,
    "target_kg": None,
    "target_date": None,
    "pace_kg_per_week": None,
    "on_track": None,
    "projection_date": None,
}


# ── Plan helpers ──────────────────────────────────────────────────────────────

def extract_session_target(structure: dict | None) -> dict:
    """Extract distance_km, duration_min, intensity from a planned_sessions structure blob.

    Tries top-level keys first, then the first block in structure["blocks"].
    Returns nulls for any field not found.

    Shared between worker_app.py (Hermes read API) and this module so a schema
    change only has to be applied once. Formerly duplicated as ``_extract_target``
    in both files; issue #1601 moved it here as the canonical home.
    """
    out: dict = {"distance_km": None, "duration_min": None, "intensity": None}
    if not structure or not isinstance(structure, dict):
        return out
    for key in out:
        val = structure.get(key)
        if val is None:
            for block in structure.get("blocks", []):
                if isinstance(block, dict) and block.get(key) is not None:
                    val = block[key]
                    break
        out[key] = val
    return out


# Backward-compat alias; internal callers use the public name.
_extract_target = extract_session_target


def _session_row_to_dict(row) -> dict:
    return {
        "session_type": row.session_type,
        "name": row.name,
        "target": extract_session_target(row.structure),
        "note": row.notes,
        "status": row.status,
    }


def _get_plan_for_date(user_id, for_date: date) -> dict:
    """Query PlannedSession model directly — no HTTP call.

    Returns an empty-plan dict for any non-UUID user_id so callers that pass
    synthetic test IDs (e.g. "user-id-1") get a graceful no-sessions response
    instead of a ValueError.
    """
    import uuid as _uuid

    from backend.models import PlannedSession

    try:
        uid = _uuid.UUID(str(user_id))
    except (ValueError, AttributeError):
        return {"plan_date": for_date.isoformat(), "planned": False, "sessions": []}

    with Session(engine) as s:
        rows = (
            s.query(PlannedSession)
            .filter(
                PlannedSession.user_id == uid,
                PlannedSession.planned_date == for_date,
            )
            .all()
        )

    return {
        "plan_date": for_date.isoformat(),
        "planned": len(rows) > 0,
        "sessions": [_session_row_to_dict(r) for r in rows],
    }


def _get_plans_for_date_range(user_id, start_date: date, end_date: date) -> dict:
    """Fetch all PlannedSession rows for [start_date, end_date] in one query.

    Returns a dict mapping each date in the range to its plan dict (same shape
    as _get_plan_for_date).  Non-UUID user_id returns empty-plan dicts without
    touching the DB.
    """
    import uuid as _uuid

    from backend.models import PlannedSession

    num_days = (end_date - start_date).days + 1
    dates = [start_date + timedelta(days=i) for i in range(num_days)]
    empty = {d: {"plan_date": d.isoformat(), "planned": False, "sessions": []} for d in dates}

    try:
        uid = _uuid.UUID(str(user_id))
    except (ValueError, AttributeError):
        return empty

    with Session(engine) as s:
        rows = (
            s.query(PlannedSession)
            .filter(
                PlannedSession.user_id == uid,
                PlannedSession.planned_date >= start_date,
                PlannedSession.planned_date <= end_date,
            )
            .all()
        )

    result = empty
    for row in rows:
        d = row.planned_date
        if d in result:
            result[d]["sessions"].append(_session_row_to_dict(row))
            result[d]["planned"] = True
    return result


def _plan_to_session(plan_resp: dict, for_date: date) -> dict:
    """Convert a plan response dict into a brief session object."""
    sessions = plan_resp.get("sessions") or []
    planned = plan_resp.get("planned", False)

    if sessions:
        s = sessions[0]
        target = s.get("target") or {}
        return {
            "date": for_date.isoformat(),
            "session_type": s.get("session_type"),
            "planned": planned,
            "intensity": target.get("intensity"),
            "duration_min": target.get("duration_min"),
            "notes": s.get("note"),
        }

    return {
        "date": for_date.isoformat(),
        "session_type": None,
        "planned": planned,
        "intensity": None,
        "duration_min": None,
        "notes": None,
    }


# ── Load interpretation ───────────────────────────────────────────────────────

def _load_interpretation(ctl: float, _atl: float, tsb: float) -> str:  # noqa: ARG001
    if tsb >= 5:
        label = "Fresh"
    elif tsb >= -5:
        label = "Neutral"
    elif tsb >= -15:
        label = "Productive (high load)"
    else:
        label = "Overreached (high risk)"

    if ctl > 60:
        return f"{label}, well-trained"
    if ctl < 30:
        return f"{label}, undertrained"
    return label


# ── Assembly helpers ──────────────────────────────────────────────────────────

def _assemble_form(user_id, for_date: date) -> dict:
    load = current_load(user_id, as_of=for_date)
    ctl = round(float(load["ctl"]), 2)
    atl = round(float(load["atl"]), 2)
    tsb = round(float(load["tsb"]), 2)

    acwr_raw = load.get("acwr")
    acwr = round(float(acwr_raw), 4) if acwr_raw is not None else None

    past_date = for_date - timedelta(days=7)
    series = get_snapshot_series(user_id, past_date, for_date)
    if len(series) >= 2:
        ramp = round(float(series[-1]["ctl"]) - float(series[0]["ctl"]), 2)
    else:
        ramp = 0.0

    guardrail = get_guardrail_result(user_id, as_of_date=for_date)
    flags = {
        "guardrail_state": guardrail.get("guardrail_state"),
        "acwr_state": guardrail.get("acwr_state"),
        "stressors_ramping": guardrail.get("stressors_ramping"),
    }

    return {
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "acwr": acwr,
        "ramp": ramp,
        "flags": flags,
        "interpretation": _load_interpretation(ctl, atl, tsb),
    }


def _build_highlights_md(user_id, for_date: date) -> str:
    import uuid as _uuid

    from backend.models import Workout
    from backend.services.training_verdict import compute_verdict
    # From weekly_summary_facts, not weekly_summary: these two are pure, but
    # their old home imports an LLM client at module level and this function is
    # on the worker's daily_coach path (coach_facts -> daily_brief).
    from backend.services.weekly_summary_facts import (
        assemble_facts,
        build_fallback_narrative,
    )

    week_start = for_date - timedelta(days=for_date.weekday())
    week_end = for_date
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start - timedelta(days=1)

    def _w_dict(w) -> dict:
        return {
            "workout_date": w.workout_date.isoformat() if w.workout_date else None,
            "tss": float(w.tss) if w.tss is not None else None,
            "distance_km": float(w.distance_km) if w.distance_km is not None else None,
            "duration_seconds": w.duration_seconds,
            "workout_type": w.workout_type or "",
        }

    try:
        uid = _uuid.UUID(str(user_id))
    except (ValueError, AttributeError):
        return ""

    with Session(engine) as s:
        curr_workouts = [_w_dict(w) for w in s.query(Workout).filter(
            Workout.user_id == uid,
            Workout.workout_date >= week_start,
            Workout.workout_date <= week_end,
        ).all()]
        prev_workouts = [_w_dict(w) for w in s.query(Workout).filter(
            Workout.user_id == uid,
            Workout.workout_date >= prev_week_start,
            Workout.workout_date <= prev_week_end,
        ).all()]

    load_start = current_load(user_id, as_of=prev_week_end)
    load_end = current_load(user_id, as_of=week_end)
    guardrail = get_guardrail_result(user_id, as_of_date=week_end)
    snap = {
        "ctl": load_end["ctl"],
        "atl": load_end["atl"],
        "tsb": load_end["tsb"],
        "acwr": load_end.get("acwr"),
    }
    verdict = compute_verdict(snap)

    facts = assemble_facts(
        week_start=week_start,
        current_workouts=curr_workouts,
        prev_workouts=prev_workouts,
        prs=[],
        ctl_start=float(load_start["ctl"]),
        ctl_end=float(load_end["ctl"]),
        atl_start=float(load_start["atl"]),
        atl_end=float(load_end["atl"]),
        tsb_start=float(load_start["tsb"]),
        tsb_end=float(load_end["tsb"]),
        guardrail=guardrail,
        verdict=dict(verdict),
    )
    return build_fallback_narrative(facts)


def _assemble_recent_wrap(
    user_id,
    for_date: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    from sqlalchemy import text

    window_start = for_date - timedelta(days=window_days - 1)

    with Session(engine) as s:
        rows = s.execute(
            text(
                "SELECT status FROM planned_sessions "
                "WHERE user_id = :uid "
                "  AND planned_date BETWEEN :start AND :end"
            ),
            {"uid": str(user_id), "start": window_start, "end": for_date},
        ).fetchall()

    sessions_planned = len(rows)
    done_statuses = {"done_auto", "done_manual"}
    sessions_completed = sum(1 for r in rows if r[0] in done_statuses)
    adherence = sessions_completed / sessions_planned if sessions_planned > 0 else 0.0

    prev_week_date = for_date - timedelta(days=7)
    curr_load = current_load(user_id, as_of=for_date)
    prev_load = current_load(user_id, as_of=prev_week_date)
    load_trend = round(float(curr_load["ctl"]) - float(prev_load["ctl"]), 2)

    highlights_md = _build_highlights_md(user_id, for_date)

    return {
        "window_days": window_days,
        "sessions_planned": sessions_planned,
        "sessions_completed": sessions_completed,
        "adherence": round(adherence, 3),
        "load_trend": load_trend,
        "highlights_md": highlights_md,
    }


def _assemble_weight(user_id, for_date: date) -> dict:
    """Retrieve weight status via compute_weight_status — no HTTP call."""
    import uuid as _uuid
    import sys

    try:
        uid = _uuid.UUID(str(user_id))
        with Session(engine) as s:
            return compute_weight_status(s, uid, for_date)
    except Exception as exc:
        print(f"WARNING: weight status unavailable: {exc}", file=sys.stderr)
        return dict(_NULL_WEIGHT_BLOCK)


def _compute_weight_advisory(weight: dict, verdict: str | None) -> dict | None:
    """Rule-computed weight advisory cross-referenced against training verdict."""
    if not weight or weight.get("target_kg") is None:
        return None

    on_track = weight.get("on_track")
    if on_track is None:
        return None

    if verdict == "build":
        if on_track:
            text = (
                "You're on pace toward your weight target, but you're entering "
                "a build block — hold intake here rather than pushing the "
                "deficit further."
            )
        else:
            text = (
                "You're behind pace on your weight target, but you're entering "
                "a build block — hold intake here rather than adding a deficit "
                "on top of rising training load. Tighten up once the block eases."
            )
        return {"key": "weight_hold_intake_build", "severity": "info", "text": text}

    if on_track is False:
        return {
            "key": "weight_pace_behind_tighten_up",
            "severity": "warn",
            "text": (
                "Pace is behind your weight target and training load isn't "
                "ramping — tighten up intake this week."
            ),
        }

    return None


def _assemble_advisories(user_id, for_date: date, weight: dict) -> list[dict]:
    """Gap-analysis findings + training verdict + weight advisory."""
    import sys
    import uuid as _uuid

    advisories: list[dict] = []

    try:
        from sqlalchemy.orm import Session

        from backend.db import engine
        from backend.services.gap_analysis.engine import run_gap_analysis

        uid = _uuid.UUID(str(user_id))
        with Session(engine) as db:
            result = run_gap_analysis(db, uid, for_date)

        for f in result.get("findings", []):
            severity_int = f.get("severity", 1)
            severity = "warn" if severity_int >= 2 else "info"
            advisories.append({
                "key": f.get("code", ""),
                "severity": severity,
                "text": f.get("recommendation", ""),
            })
    except Exception as exc:
        print(f"WARNING: gap analysis unavailable: {exc}", file=sys.stderr)
        advisories.append({
            "key": "gap_analysis_error",
            "severity": "error",
            "text": "Gap analysis temporarily unavailable.",
        })

    verdict_str: str | None = None
    try:
        from backend.services.gap_analysis.engine import _gather_training_verdict

        uid = _uuid.UUID(str(user_id))
        verdict_str = _gather_training_verdict(uid, for_date)
        if verdict_str and verdict_str != "build":
            advisories.append({
                "key": f"verdict_{verdict_str}",
                "severity": "warn",
                "text": f"Training verdict: {verdict_str.replace('_', ' ')}. Adjust load accordingly.",
            })
    except Exception as exc:
        print(f"WARNING: training verdict unavailable: {exc}", file=sys.stderr)
        advisories.append({
            "key": "training_verdict_error",
            "severity": "error",
            "text": "Training verdict temporarily unavailable.",
        })

    try:
        weight_advisory = _compute_weight_advisory(weight, verdict_str)
        if weight_advisory is not None:
            advisories.append(weight_advisory)
    except Exception as exc:
        print(f"WARNING: weight advisory computation failed: {exc}", file=sys.stderr)

    return advisories


# ── Week plan ─────────────────────────────────────────────────────────────────

def _assemble_week_plan(user_id, for_date: date, plan_cache: dict | None = None) -> list[dict]:
    """Return remaining days this Bangkok week after tomorrow.

    Covers tomorrow through the Sunday of for_date's week (Monday=0 … Sunday=6).
    Returns [] when tomorrow falls on a weekend (Sat/Sun) or is past this week's
    Sunday (i.e. today is Sunday and tomorrow is already next week's Monday).

    plan_cache: optional dict[date, plan_dict] from _get_plans_for_date_range.
    When provided, no additional DB queries are issued.
    """
    tomorrow = for_date + timedelta(days=1)
    days_until_sunday = 6 - for_date.weekday()
    sunday = for_date + timedelta(days=days_until_sunday)

    if tomorrow.weekday() >= 5 or tomorrow > sunday:
        return []

    result: list[dict] = []
    current = tomorrow
    while current <= sunday:
        if plan_cache is not None:
            plan = plan_cache.get(current, {
                "plan_date": current.isoformat(),
                "planned": False,
                "sessions": [],
            })
        else:
            plan = _get_plan_for_date(user_id, current)
        session = _plan_to_session(plan, current)
        result.append({
            "date": current.isoformat(),
            "day": current.strftime("%a"),
            "session_type": session["session_type"],
            "intensity": session["intensity"],
            "duration_min": session["duration_min"],
            "planned": bool(session["planned"]),
        })
        current += timedelta(days=1)

    return result


# ── Coach block ───────────────────────────────────────────────────────────────

def _assemble_coach(user_id, for_date: date) -> dict | None:
    """Assemble the coach block for the daily brief.

    Calls get_coach_payload_for_user from weekly_coach_message — the same
    source-of-truth used by the Home page coach strip.  Returns None on any
    error or when no payload is available so callers can omit the key cleanly.
    """
    import sys
    import uuid as _uuid

    try:
        from sqlalchemy.orm import Session as _Session

        from backend.db import engine
        from backend.services.weekly_coach_message import get_coach_payload_for_user

        uid = user_id
        try:
            _uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            from backend.models import User
            with _Session(engine) as db:
                u = db.query(User).filter(
                    User.name == str(user_id), User.is_active.is_(True)
                ).first()
            if u is None:
                return None
            uid = u.id

        with _Session(engine) as db:
            payload = get_coach_payload_for_user(uid, today=for_date, db=db)
        if not payload:
            return None

        sections = payload.get("sections") or {}
        nudge = payload.get("nudge") or {}
        chosen = payload.get("chosen_preset")

        out: dict = {
            "as_of": payload.get("as_of"),
            "source": payload.get("source"),
            "sections": sections,
            "text": payload.get("text") or "",
            "directive": (sections.get("now") or "").split("\n\n")[0][:400],
            "projection": (sections.get("dream") or "").split("\n\n")[0][:400],
            "levers": [],
        }
        if isinstance(nudge, dict) and (nudge.get("focus_label") or nudge.get("next_action")):
            out.update({
                "focus_id": nudge.get("focus_id"),
                "focus_label": nudge.get("focus_label"),
                "next_action": nudge.get("next_action"),
                "why": nudge.get("why"),
            })
        if chosen:
            out["chosen_preset"] = chosen
        return out
    except Exception as exc:
        print(f"WARNING: coach block unavailable: {exc}", file=sys.stderr)
        return None


# ── Core assembly ─────────────────────────────────────────────────────────────

def _build_brief(for_date: date, worker_url=None, user_id=None, username=None) -> dict:
    """Assemble and return the complete brief payload.

    worker_url and username are accepted for backward compatibility with callers
    that still pass the old four-argument signature; they are not used.
    """
    tomorrow = for_date + timedelta(days=1)
    days_until_sunday = 6 - for_date.weekday()
    sunday = for_date + timedelta(days=days_until_sunday)

    # Single query covers today, tomorrow, and the rest of the week.
    plan_cache = _get_plans_for_date_range(user_id, for_date, sunday)

    today_plan = plan_cache.get(for_date, {
        "plan_date": for_date.isoformat(), "planned": False, "sessions": [],
    })
    tomorrow_plan = plan_cache.get(tomorrow, {
        "plan_date": tomorrow.isoformat(), "planned": False, "sessions": [],
    })

    today_session = _plan_to_session(today_plan, for_date)
    tomorrow_session = _plan_to_session(tomorrow_plan, tomorrow)

    form = _assemble_form(user_id, for_date)
    recent_wrap = _assemble_recent_wrap(user_id, for_date)
    weight = _assemble_weight(user_id, for_date)
    advisories = _assemble_advisories(user_id, for_date, weight)
    week_plan = _assemble_week_plan(user_id, for_date, plan_cache=plan_cache)
    coach = _assemble_coach(user_id, for_date)
    advisories_degraded = any(a.get("severity") == "error" for a in advisories)

    generated_at = datetime.now(BANGKOK_TZ).isoformat()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "for_date": for_date.isoformat(),
        "generated_at": generated_at,
        "today": today_session,
        "tomorrow": tomorrow_session,
        "form": form,
        "recent_wrap": recent_wrap,
        "weight": weight,
        "advisories": advisories,
        "advisories_degraded": advisories_degraded,
        "actions": [],
        "week_plan": week_plan,
    }
    if coach is not None:
        payload["coach"] = coach
    return payload


def build_brief(user_id, for_date: date) -> dict:
    """Public API: assemble the SCHEMA_VERSION 2 Hermes brief for a user and date."""
    return _build_brief(for_date, user_id=user_id)
