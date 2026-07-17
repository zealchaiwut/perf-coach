"""Assemble deterministic coach_facts for the weekly Head Coach narrative.

Specialist engines (coach_plan, weight, gaps, habits, projection, checkpoints,
plan adherence) produce facts only — no LLM imports. The LangGraph synthesizer
narrates from this JSON; validators reject numerals not present here.

See docs/calculations/coach-narrative.md.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any

from backend.utils.log import get_logger

_log = get_logger(__name__)

SECTION_KEYS = ("now", "focus", "dream", "reflection")


def _iso(d: Any) -> str | None:
    if d is None:
        return None
    if isinstance(d, date):
        return d.isoformat()
    if isinstance(d, str):
        return d[:10]
    return None


def _fmt_hms(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}" if s else f"{h}:{m:02d}"
    return f"{m}:{s:02d}"


def _add_numeral(bucket: set[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, date):
        bucket.add(value.isoformat())
        bucket.add(value.strftime("%-d %b"))
        bucket.add(value.strftime("%d %b"))
        bucket.add(value.strftime("%b"))
        return
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return
        bucket.add(str(int(round(value))))
        bucket.add(f"{value:.1f}")
        bucket.add(f"{value:.2f}")
        return
    if isinstance(value, int):
        bucket.add(str(value))
        return
    s = str(value).strip()
    if not s:
        return
    bucket.add(s)
    for m in re.finditer(r"\d+(?:\.\d+)?", s):
        bucket.add(m.group(0))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            _add_numeral(bucket, date.fromisoformat(s))
        except ValueError:
            pass


def collect_required_numerals(facts: dict) -> list[str]:
    """Flatten allowlisted numeral/date strings from facts for validators."""
    bucket: set[str] = set()

    def walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("rationale", "advisory_text", "text", "caveat", "method",
                         "why_focus", "detail", "label", "directive", "reason",
                         "streak_or_adherence_summary", "highlights"):
                    _add_numeral(bucket, v)
                    continue
                walk(v)
            return
        if isinstance(obj, (list, tuple)):
            for i in obj:
                walk(i)
            return
        if isinstance(obj, (int, float, date)):
            _add_numeral(bucket, obj)
            return
        if isinstance(obj, str) and (
            re.search(r"\d", obj) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", obj)
        ):
            _add_numeral(bucket, obj)

    walk(facts)
    # Always allow common separators appearing next to numbers
    bucket.update({"0", "1", "2", "5", "7", "12", "14"})
    return sorted(bucket)


def _weight_phase(weight_lever: dict) -> str:
    state = (weight_lever or {}).get("state") or "unavailable"
    if state == "active (measurement)":
        return "measurement"
    if state == "active (deficit)":
        return "deficit"
    return "none"


def _thin_focus_from_ranking(plan_state: dict, weight: dict, load: dict) -> list[dict]:
    """Phase-1 stub ranker from lever_ranking only (Phase 2 replaces)."""
    ranking = plan_state.get("lever_ranking") or {}
    bigger = ranking.get("bigger_lever") or "load"
    tractable = ranking.get("more_tractable") or "weight"
    rationale = ranking.get("rationale") or ""
    out: list[dict] = []

    load_state = load.get("state")
    if load_state == "locked":
        out.append({
            "id": "hold_load",
            "rank": 1 if tractable != "weight" else 2,
            "label": "Hold training load",
            "rationale": load.get("reason") or "ACWR elevated — hold TSS.",
            "tracking": {
                "current": None,
                "target": None,
                "unit": "acwr_unlock",
                "unlock_date": _iso(load.get("unlock_date")),
            },
            "score": 90,
        })
    elif load_state == "available":
        out.append({
            "id": "ramp_load",
            "rank": 1 if bigger == "load" else 2,
            "label": "Resume load ramp",
            "rationale": "Load lever available — progressive ramp is safe.",
            "tracking": None,
            "score": 70,
        })

    phase = weight.get("phase")
    logged = weight.get("logged_days")
    window = weight.get("window_days") or 14
    if phase == "measurement":
        out.append({
            "id": "weight_measurement",
            "rank": 1 if tractable == "weight" else 2,
            "label": "Weight measurement consistency",
            "rationale": "Log weigh-ins honestly before targeting a deficit.",
            "tracking": {
                "current": logged,
                "target": 12,
                "unit": "weigh_ins_14d",
            },
            "score": 95 if tractable == "weight" else 60,
        })
    elif phase == "deficit":
        out.append({
            "id": "weight_deficit",
            "rank": 1 if bigger == "weight" else 2,
            "label": "Modest calorie deficit",
            "rationale": "Measurement consistent — modest deficit is available.",
            "tracking": {
                "current": logged,
                "target": window,
                "unit": "weigh_ins_14d",
            },
            "score": 75,
        })

    out.sort(key=lambda x: (-(x.get("score") or 0), x.get("id") or ""))
    for i, row in enumerate(out, start=1):
        row["rank"] = i
    return out[:4]


def rank_focus_levers(
    *,
    plan_state: dict,
    weight: dict,
    load: dict,
    gaps_top: list[dict],
    volume_mix: dict | None = None,
) -> tuple[list[dict], list[str]]:
    """Score multi-lever Focus list (Phase 2). Returns (ranked, noise_ids)."""
    volume_mix = volume_mix or {}
    candidates: dict[str, dict] = {}

    def upsert(lever_id: str, score: float, label: str, rationale: str, tracking=None):
        prev = candidates.get(lever_id)
        if prev and (prev.get("score") or 0) >= score:
            return
        candidates[lever_id] = {
            "id": lever_id,
            "label": label,
            "rationale": rationale,
            "tracking": tracking,
            "score": score,
        }

    load_state = load.get("state")
    if load_state == "locked":
        upsert(
            "hold_load",
            100,
            "Hold training load",
            load.get("reason") or "ACWR elevated — hold TSS until unlock.",
            {
                "current": None,
                "target": None,
                "unit": "acwr_unlock",
                "unlock_date": _iso(load.get("unlock_date")),
            },
        )
    elif load_state == "available":
        upsert(
            "ramp_load",
            72,
            "Resume load ramp",
            "ACWR productive — safe to resume a progressive ramp.",
            None,
        )

    phase = weight.get("phase")
    logged = weight.get("logged_days")
    gap_kg = weight.get("gap_kg")
    if phase == "measurement":
        upsert(
            "weight_measurement",
            98 if (gap_kg or 0) > 0 else 88,
            "Weight measurement consistency",
            "Build 12/14 weigh-in days before a deficit.",
            {"current": logged, "target": 12, "unit": "weigh_ins_14d"},
        )
    elif phase == "deficit" and load_state != "locked":
        upsert(
            "weight_deficit",
            80,
            "Modest calorie deficit",
            "Logging is consistent and load is not locked — modest deficit OK.",
            {"current": logged, "target": 14, "unit": "weigh_ins_14d"},
        )

    gap_score = {
        "plyo": ("plyo", 55, "Plyometric stimulus"),
        "no_recent_plyo": ("plyo", 55, "Plyometric stimulus"),
        "strength": ("strength", 50, "Strength maintenance"),
        "strength_lapsed": ("strength", 50, "Strength maintenance"),
        "aerobic": ("long_run", 78, "Long-run durability"),
        "long_run": ("long_run", 78, "Long-run durability"),
        "aerobic_durability": ("long_run", 78, "Long-run durability"),
        "speed": ("quality_intervals", 70, "Speed / intervals"),
        "interval": ("quality_intervals", 70, "Speed / intervals"),
        "tempo": ("tempo", 65, "Tempo / threshold"),
        "base": ("long_run", 60, "Aerobic base"),
    }
    for g in gaps_top or []:
        code = (g.get("code") or "").lower()
        text = g.get("text") or ""
        sev = g.get("severity") or "info"
        bump = 10 if sev == "warn" else 0
        matched = None
        for key, meta in gap_score.items():
            if key in code:
                matched = meta
                break
        if not matched:
            # keyword fallback on text
            tl = text.lower()
            if "long run" in tl or "durability" in tl:
                matched = gap_score["long_run"]
            elif "interval" in tl or "speed" in tl:
                matched = gap_score["speed"]
            elif "tempo" in tl or "threshold" in tl:
                matched = gap_score["tempo"]
            elif "plyo" in tl:
                matched = gap_score["plyo"]
            elif "strength" in tl:
                matched = gap_score["strength"]
        if matched:
            lid, base, label = matched
            upsert(lid, base + bump, label, text[:180] or label, None)

    # Volume mix hints
    if volume_mix.get("missing_long"):
        upsert(
            "long_run",
            max(candidates.get("long_run", {}).get("score") or 0, 76),
            "Long-run durability",
            "No qualifying long run in the recent window.",
            None,
        )
    if volume_mix.get("missing_quality"):
        upsert(
            "quality_intervals",
            max(candidates.get("quality_intervals", {}).get("score") or 0, 68),
            "Speed / intervals",
            "Quality / interval stimulus missing recently.",
            None,
        )

    ranked = sorted(candidates.values(), key=lambda x: (-(x["score"] or 0), x["id"]))
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    top_ids = {r["id"] for r in ranked[:2]}
    noise = [r["id"] for r in ranked[2:] if r["id"] not in top_ids]
    return ranked[:6], noise


def _volume_mix_hint(user_id, today: date) -> dict:
    """Cheap recent-workout mix flags for Focus ranking."""
    try:
        from sqlalchemy.orm import Session
        from backend.db import engine
        from backend.models import Workout

        start = today - timedelta(days=14)
        with Session(engine) as db:
            rows = (
                db.query(Workout)
                .filter(
                    Workout.user_id == user_id,
                    Workout.workout_date >= start,
                    Workout.workout_date <= today,
                )
                .all()
            )
        has_long = False
        has_quality = False
        for w in rows:
            dist = float(getattr(w, "distance_km", 0) or 0)
            name = (getattr(w, "name", None) or "").lower()
            wtype = (getattr(w, "workout_type", None) or "").lower()
            if dist >= 14 or "long" in name:
                has_long = True
            if any(k in name or k in wtype for k in ("interval", "tempo", "threshold", "speed")):
                has_quality = True
        return {
            "missing_long": not has_long,
            "missing_quality": not has_quality,
            "workout_count_14d": len(rows),
        }
    except Exception as exc:
        _log.warning("volume_mix unavailable: %s", exc)
        return {}


def _gaps_top(user_id, today: date, limit: int = 3) -> list[dict]:
    try:
        from backend.services.daily_brief import _assemble_advisories, _assemble_weight

        weight = _assemble_weight(user_id, today)
        advisories = _assemble_advisories(user_id, today, weight) or []
        out = []
        for a in advisories[:limit]:
            out.append({
                "code": a.get("key") or a.get("code") or "advisory",
                "severity": a.get("severity") or "info",
                "text": a.get("text") or "",
            })
        return out
    except Exception as exc:
        _log.warning("gaps_top unavailable: %s", exc)
        return []


def _habits_summary(user_id, today: date) -> dict | None:
    try:
        from sqlalchemy.orm import Session
        from backend.db import engine
        from backend.models import Habit, HabitLog

        start = today - timedelta(days=6)
        with Session(engine) as db:
            habits = (
                db.query(Habit)
                .filter(Habit.user_id == user_id, Habit.is_active.is_(True))
                .all()
            )
            if not habits:
                return None
            ids = [h.id for h in habits]
            logs = (
                db.query(HabitLog)
                .filter(
                    HabitLog.user_id == user_id,
                    HabitLog.habit_id.in_(ids),
                    HabitLog.log_date >= start,
                    HabitLog.log_date <= today,
                )
                .all()
            )
        possible = len(habits) * 7
        done = len(logs)
        pct = round(100.0 * done / possible, 0) if possible else 0
        return {
            "streak_or_adherence_summary": f"Habits {int(done)}/{possible} logs this week (~{int(pct)}%)",
            "logged": done,
            "possible": possible,
        }
    except Exception as exc:
        _log.warning("habits summary unavailable: %s", exc)
        return None


def _dream_block(user_id, today: date, projection: dict, weight: dict) -> dict:
    """Phase 3: A-race + checkpoints + optional weight scenario."""
    dream: dict[str, Any] = {
        "a_race": None,
        "performance_goal": None,
        "checkpoints": [],
        "scenarios": [],
        "sell_line_facts": {},
    }
    try:
        from sqlalchemy.orm import Session
        from backend.db import engine
        from backend.models import Race, RaceCheckpoint

        with Session(engine) as db:
            a_race = (
                db.query(Race)
                .filter(
                    Race.user_id == user_id,
                    Race.priority == "A",
                    Race.status.in_(("planned", "active")),
                )
                .order_by(Race.race_date.asc().nullslast())
                .first()
            )
            if a_race is None:
                a_race = (
                    db.query(Race)
                    .filter(Race.user_id == user_id, Race.status.in_(("planned", "active")))
                    .order_by(Race.race_date.asc().nullslast())
                    .first()
                )
            if a_race is not None:
                goal_sec = getattr(a_race, "goal_time_seconds", None)
                dream["a_race"] = {
                    "name": a_race.name,
                    "date": _iso(a_race.race_date),
                    "distance_km": float(a_race.distance_km) if a_race.distance_km is not None else None,
                    "goal_time_label": _fmt_hms(goal_sec),
                    "goal_time_sec": int(goal_sec) if goal_sec is not None else None,
                }
                cps = (
                    db.query(RaceCheckpoint)
                    .filter(
                        RaceCheckpoint.user_id == user_id,
                        RaceCheckpoint.race_id == a_race.id,
                    )
                    .order_by(RaceCheckpoint.target_date.asc())
                    .all()
                )
                for cp in cps:
                    dream["checkpoints"].append({
                        "label": cp.label,
                        "date": _iso(cp.target_date),
                        "target_time_label": _fmt_hms(cp.target_duration_seconds),
                        "projected_time_label": None,
                        "met": bool(cp.met or cp.met_override),
                    })
    except Exception as exc:
        _log.warning("dream race/checkpoints unavailable: %s", exc)

    # PerformanceGoal summary already in facts["goal"] — mirror for clarity
    if projection:
        dream["scenarios"].append({
            "id": "plan_compliance",
            "label": "If you hit the plan",
            "finish_label": projection.get("full_compliance_label")
            or projection.get("goal_label"),
            "method": "performance_goal_target",
            "caveat": "Assumes plan compliance; band widens with sparse data.",
        })
        if projection.get("current_trend_label"):
            dream["scenarios"].append({
                "id": "current_trend",
                "label": "Current trend",
                "finish_label": projection.get("current_trend_label"),
                "method": "ctl_ratio_trend",
                "caveat": f"±{projection.get('uncertainty_min', 0)} min uncertainty.",
            })

    # Weight-cut scenario: documented Riegel-ish ~1% per kg heuristic, only if gap known
    gap_kg = weight.get("gap_kg")
    base_sec = None
    if projection.get("full_compliance_label"):
        # prefer numeric from goal elsewhere; use trend seconds if passed
        pass
    try:
        # Use current trend seconds when available via companion field
        if isinstance(projection.get("full_compliance_sec"), int):
            base_sec = projection["full_compliance_sec"]
        elif isinstance(projection.get("current_trend_sec"), int):
            base_sec = projection["current_trend_sec"]
    except Exception:
        base_sec = None

    cut_kg = None
    if gap_kg is not None and float(gap_kg) > 0:
        cut_kg = min(6.0, float(gap_kg))
    if base_sec and cut_kg and cut_kg >= 2:
        # ~0.8% finish-time improvement per kg lost (conservative heuristic)
        improved = int(round(base_sec * (1.0 - 0.008 * cut_kg)))
        year_end = date(today.year, 12, 31)
        dream["scenarios"].append({
            "id": "weight_cut",
            "label": f"If −{cut_kg:.0f} kg by {year_end.isoformat()}",
            "finish_label": _fmt_hms(improved),
            "method": "0.8pct_per_kg_riegel_heuristic",
            "caveat": (
                "Heuristic only (~0.8% / kg); not a guarantee — fitness and "
                "fueling must hold while cutting."
            ),
            "cut_kg": cut_kg,
            "by_date": year_end.isoformat(),
        })

    upcoming = next(
        (c for c in dream["checkpoints"] if not c.get("met") and c.get("date")),
        None,
    )
    if upcoming:
        dream["sell_line_facts"] = {
            "next_checkpoint_date": upcoming["date"],
            "next_checkpoint_label": upcoming["label"],
            "next_checkpoint_target": upcoming.get("target_time_label"),
        }
    elif dream.get("a_race"):
        dream["sell_line_facts"] = {
            "next_checkpoint_date": dream["a_race"].get("date"),
            "next_checkpoint_label": dream["a_race"].get("name") or "A-race",
            "next_checkpoint_target": dream["a_race"].get("goal_time_label"),
        }

    return dream


def _reflection_block(
    user_id,
    today: date,
    focus_ranked: list[dict],
) -> dict:
    """Phase 4: adherence + benchmarks + next session."""
    reflection: dict[str, Any] = {
        "week_start": None,
        "sessions_planned": 0,
        "sessions_completed": 0,
        "adherence_pct": None,
        "missed": [],
        "highlights": [],
        "benchmarks": [],
        "next_session": None,
    }
    try:
        from backend.services.daily_brief import _assemble_recent_wrap

        wrap = _assemble_recent_wrap(user_id, today)
        planned = int(wrap.get("sessions_planned") or 0)
        completed = int(wrap.get("sessions_completed") or 0)
        adh = wrap.get("adherence")
        reflection.update({
            "week_start": _iso(today - timedelta(days=6)),
            "sessions_planned": planned,
            "sessions_completed": completed,
            "adherence_pct": int(round(100 * float(adh))) if adh is not None else None,
            "highlights": (
                [wrap["highlights_md"]] if wrap.get("highlights_md") else []
            ),
        })
    except Exception as exc:
        _log.warning("reflection recent_wrap unavailable: %s", exc)

    focus1 = (focus_ranked[0]["id"] if focus_ranked else None)
    # Benchmarks from focus + weigh-ins
    for fr in (focus_ranked or [])[:2]:
        tr = fr.get("tracking") or {}
        detail = fr.get("rationale") or fr.get("label")
        met = None
        if tr.get("current") is not None and tr.get("target") is not None:
            try:
                met = float(tr["current"]) >= float(tr["target"])
                detail = f"{tr['current']}/{tr['target']} {tr.get('unit') or ''}".strip()
            except (TypeError, ValueError):
                met = None
        reflection["benchmarks"].append({
            "id": fr["id"],
            "met": met,
            "detail": detail,
        })

    # Next planned session
    try:
        from sqlalchemy.orm import Session
        from sqlalchemy import text
        from backend.db import engine

        with Session(engine) as db:
            row = db.execute(
                text(
                    "SELECT id, planned_date, name, session_type FROM planned_sessions "
                    "WHERE user_id = :uid AND planned_date >= :d "
                    "  AND session_type IS DISTINCT FROM 'rest' "
                    "  AND coalesce(status, 'planned') NOT IN "
                    "      ('done_auto', 'done_manual', 'skipped') "
                    "ORDER BY planned_date ASC LIMIT 1"
                ),
                {"uid": str(user_id), "d": today},
            ).fetchone()
        if row:
            reflection["next_session"] = {
                "id": str(row[0]),
                "date": _iso(row[1]),
                "name": row[2] or "Session",
                "type": row[3],
                "why_focus": f"Serves Focus #1: {focus1}" if focus1 else "Next planned session",
            }
    except Exception as exc:
        _log.warning("next_session unavailable: %s", exc)

    return reflection


def build_coach_facts(user_id, today: date | None = None, db=None) -> dict | None:
    """Return coach_facts dict, or None when no active PerformanceGoal exists."""
    from backend.services.coach_plan import build_plan_state
    from backend.services.weekly_coach_message import (
        _build_projection_info,
        _load_inputs_for_user,
        _format_hms,
    )

    today = today or date.today()
    _own = db is None
    if _own:
        from sqlalchemy.orm import Session
        from backend.db import engine
        db = Session(engine)

    try:
        goal, snapshot, weight_status, log_consistency = _load_inputs_for_user(
            user_id, db, today
        )
        if goal is None:
            return None

        acwr_val = float(getattr(snapshot, "acwr", 0) or 0) if snapshot else 0.0
        acwr_state = "high_risk" if acwr_val > 1.30 else "productive"
        plan_state = build_plan_state(
            goal=goal,
            training_load_snapshot=snapshot,
            acwr_state=acwr_state,
            guardrail_state="ok",
            weight_status=weight_status,
            log_consistency=log_consistency,
            _today=today,
        )
        projection_info = _build_projection_info(goal, snapshot, today)

        load_raw = (plan_state.get("levers") or {}).get("load") or {}
        weight_raw = (plan_state.get("levers") or {}).get("weight") or {}

        hold_tss = None
        reason = load_raw.get("reason") or ""
        m = re.search(r"~(\d+)\s*TSS", reason)
        if m:
            hold_tss = int(m.group(1))
        elif snapshot is not None:
            daily = float(getattr(snapshot, "tss_for_day", 0) or 0)
            hold_tss = int(round(daily * 7))

        load = {
            "ctl": float(getattr(snapshot, "ctl", 0) or 0) if snapshot else None,
            "atl": float(getattr(snapshot, "atl", 0) or 0) if snapshot else None,
            "acwr": round(acwr_val, 2) if snapshot else None,
            "state": load_raw.get("state") or "unavailable",
            "hold_tss": hold_tss,
            "unlock_date": _iso(load_raw.get("unlock_date")),
            "reason": reason,
        }

        logged = weight_raw.get("logged_days")
        if logged is None and isinstance(log_consistency, dict):
            logged = log_consistency.get("logged_days")
        weight = {
            "phase": _weight_phase(weight_raw),
            "logged_days": logged,
            "window_days": int(
                weight_raw.get("threshold")
                or (log_consistency or {}).get("total_days")
                or 14
            ) if isinstance(log_consistency, dict) or weight_raw.get("threshold") else 14,
            "gap_kg": float((weight_status or {}).get("gap_kg") or 0)
            if weight_status else None,
            "advisory_text": None,
            "recommended_deficit_kcal": weight_raw.get("recommended_deficit_kcal"),
        }

        timeline = []
        for phase in plan_state.get("timeline") or []:
            timeline.append({
                "date": _iso(phase.get("start_date")),
                "end_date": _iso(phase.get("end_date")),
                "phase": phase.get("name"),
                "directive": phase.get("directive"),
            })

        target_sec = int(getattr(goal, "target_time", 0) or 0)
        race_date = getattr(goal, "race_date", None)
        projection = {
            "goal_label": _format_hms(target_sec) if target_sec else None,
            "full_compliance_label": _format_hms(
                projection_info.get("full_compliance_time_seconds") or target_sec
            ),
            "full_compliance_sec": int(
                projection_info.get("full_compliance_time_seconds") or target_sec or 0
            ) or None,
            "current_trend_label": _format_hms(
                projection_info.get("current_trend_time_seconds") or 0
            ),
            "current_trend_sec": int(
                projection_info.get("current_trend_time_seconds") or 0
            ) or None,
            "uncertainty_min": int(projection_info.get("uncertainty_minutes") or 0),
            "distance_label": projection_info.get("distance_label"),
            "target_date": _iso(projection_info.get("target_date") or race_date),
        }

        gaps_top = _gaps_top(user_id, today)
        volume_mix = _volume_mix_hint(user_id, today)
        focus_ranked, focus_noise = rank_focus_levers(
            plan_state=plan_state,
            weight=weight,
            load=load,
            gaps_top=gaps_top,
            volume_mix=volume_mix,
        )
        if not focus_ranked:
            focus_ranked = _thin_focus_from_ranking(plan_state, weight, load)
            focus_noise = []

        habits = _habits_summary(user_id, today)
        dream = _dream_block(user_id, today, projection, weight)
        reflection = _reflection_block(user_id, today, focus_ranked)

        goal_block = {
            "distance": getattr(goal, "race_distance", None),
            "target_time_sec": target_sec or None,
            "target_time_label": _format_hms(target_sec) if target_sec else None,
            "race_date": _iso(race_date),
        }

        facts = {
            "as_of": today.isoformat(),
            "goal": goal_block,
            "load": load,
            "weight": weight,
            "timeline": timeline,
            "constraints": list(plan_state.get("constraints") or []),
            "lever_ranking": plan_state.get("lever_ranking") or {},
            "projection": projection,
            "gaps_top": gaps_top,
            "habits": habits,
            "focus_ranked": focus_ranked,
            "focus_noise": focus_noise,
            "volume_mix": volume_mix,
            "dream": dream,
            "reflection": reflection,
            "plan_state": plan_state,
        }
        facts["required_numerals"] = collect_required_numerals(facts)
        # Hermes / actions nudge payload
        focus1 = focus_ranked[0] if focus_ranked else None
        next_s = (reflection or {}).get("next_session")
        facts["nudge"] = {
            "focus_id": focus1.get("id") if focus1 else None,
            "focus_label": focus1.get("label") if focus1 else None,
            "next_action": (
                f"{next_s.get('name')} on {next_s.get('date')}"
                if next_s else (focus1.get("label") if focus1 else None)
            ),
            "why": next_s.get("why_focus") if next_s else None,
        }
        return facts
    finally:
        if _own:
            db.close()
