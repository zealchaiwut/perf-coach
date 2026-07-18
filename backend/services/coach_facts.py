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


def _enrich_weight_plan_position(user_id, today: date, weight: dict, db) -> None:
    """Attach current vs plan-today + next milestone onto weight facts (in place)."""
    try:
        from backend.models import WeightTarget
        from backend.services.weight_plan import compute_gap, generate_milestones

        target = (
            db.query(WeightTarget)
            .filter(WeightTarget.user_id == user_id, WeightTarget.status == "active")
            .first()
        )
        if target is None:
            return
        gap = compute_gap(target, db, today)
        if gap.get("current_basis_kg") is not None:
            weight["current_kg"] = gap["current_basis_kg"]
        if gap.get("plan_today_kg") is not None:
            weight["plan_today_kg"] = gap["plan_today_kg"]
        if gap.get("gap_kg") is not None:
            weight["gap_to_plan_kg"] = gap["gap_kg"]
        if gap.get("gap_direction"):
            weight["gap_direction"] = gap["gap_direction"]
        weight["goal_kg"] = float(target.target_weight_kg)
        weight["goal_date"] = _iso(getattr(target, "target_date", None))
        stones = generate_milestones(target, today) or []
        today_s = today.isoformat()
        nxt = next(
            (
                m
                for m in stones
                if m.get("kind") not in ("today",)
                and str(m.get("date") or "") > today_s
            ),
            None,
        )
        if nxt is None:
            nxt = next((m for m in stones if m.get("kind") == "goal"), None)
        if nxt:
            weight["next_milestone_date"] = str(nxt.get("date") or "")[:10]
            weight["next_milestone_kg"] = nxt.get("plan_kg")
    except Exception as exc:
        _log.warning("weight plan position unavailable: %s", exc)


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
    if load.get("deload_week"):
        upsert(
            "respect_deload",
            95,
            "Respect this deload week",
            load.get("deload_rationale")
            or "This is a planned deload — keep volume easy; do not pile TSS back on.",
            None,
        )
    elif load.get("ramp_caution"):
        upsert(
            "ramp_caution",
            90,
            "Ramp gently — load ceiling",
            load.get("ramp_caution_text")
            or "Respect the moving-average load ceiling; do not spike TSS after a quiet week.",
            None,
        )
    elif load_state == "locked":
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
            "ACWR productive — safe to resume a progressive ramp (5%/week, no heroics).",
            None,
        )

    phase = weight.get("phase")
    logged = weight.get("logged_days")
    gap_kg = weight.get("gap_kg")
    payoff = weight.get("payoff_label")
    if phase == "measurement":
        rationale = "Build 12/14 weigh-in days before a deficit."
        if payoff and gap_kg:
            rationale = (
                f"Weigh-ins first — then a cut. Rough payoff: −{min(6, float(gap_kg)):.0f} kg "
                f"→ ~{payoff} on the A-race (heuristic). Measurement unlocks that lever."
            )
        upsert(
            "weight_measurement",
            99 if (gap_kg or 0) > 0 else 88,
            "Weight measurement consistency",
            rationale,
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
    already_doing_longs = not volume_mix.get("missing_long", True)
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
            tl = text.lower()
            if "long run" in tl or "durability" in tl or "decoupling" in tl:
                matched = gap_score["long_run"]
            elif "interval" in tl or "speed" in tl:
                matched = gap_score["speed"]
            elif "tempo" in tl or "threshold" in tl:
                matched = gap_score["tempo"]
            elif "plyo" in tl:
                matched = gap_score["plyo"]
            elif "strength" in tl:
                matched = gap_score["strength"]
        if not matched:
            continue
        lid, base, label = matched
        # Durability gap ≠ missing long run. If longs are already on the books,
        # reframe as fueling / late-fade quality — never "you need a long run".
        if lid == "long_run" and already_doing_longs:
            longs = volume_mix.get("recent_longs") or []
            evidence = ""
            if longs:
                bits = ", ".join(
                    f"{x.get('mins')} min on {x.get('date')}" for x in longs[:2]
                )
                evidence = f" Recent longs: {bits}."
            upsert(
                "long_run_fueling",
                58 + bump,
                "Long-run fueling (late fade)",
                (
                    "You're already doing the long runs — the gap is late-run efficiency "
                    "(aerobic decoupling), not missing the session. Keep one easy long "
                    "and practise fueling so November is automatic."
                    + evidence
                )[:220],
                None,
            )
            continue
        upsert(lid, base + bump, label, text[:180] or label, None)

    if volume_mix.get("missing_long"):
        upsert(
            "long_run",
            max(candidates.get("long_run", {}).get("score") or 0, 76),
            "Long-run durability",
            "No qualifying long run in the recent window.",
            None,
        )
    if volume_mix.get("missing_quality"):
        # Soft: don't nag hard if praise shows recent incline intervals
        upsert(
            "quality_intervals",
            max(candidates.get("quality_intervals", {}).get("score") or 0, 62),
            "Speed / intervals",
            "Quality / interval stimulus thin recently — keep the incline work in the mix.",
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

        start = today - timedelta(days=21)
        with Session(engine) as db:
            rows = (
                db.query(Workout)
                .filter(
                    Workout.user_id == user_id,
                    Workout.workout_date >= start,
                    Workout.workout_date <= today,
                )
                .order_by(Workout.workout_date.desc())
                .all()
            )
        has_long = False
        has_quality = False
        recent_longs: list[dict] = []
        for w in rows:
            dist = float(getattr(w, "distance_km", 0) or 0)
            dur = int(getattr(w, "duration_seconds", 0) or 0)
            name = (getattr(w, "name", None) or "").lower()
            wtype = (getattr(w, "workout_type", None) or "").lower()
            mins = dur // 60 if dur else 0
            is_long = dist >= 14 or mins >= 90 or "long" in name
            if is_long:
                has_long = True
                recent_longs.append({
                    "date": _iso(getattr(w, "workout_date", None)),
                    "mins": mins,
                    "duration_min": mins,
                    "distance_km": dist if dist else None,
                    "name": getattr(w, "name", None),
                    "decoupling_percent": (
                        float(w.decoupling_percent)
                        if getattr(w, "decoupling_percent", None) is not None
                        else None
                    ),
                })
            if any(k in name or k in wtype for k in ("interval", "tempo", "threshold", "speed", "incline")):
                has_quality = True
        latest = recent_longs[0] if recent_longs else None
        return {
            "missing_long": not has_long,
            "long_volume_ok": has_long,
            "latest_long_mins": (latest or {}).get("mins"),
            "latest_long_date": (latest or {}).get("date"),
            "missing_quality": not has_quality,
            "workout_count_14d": len([r for r in rows if (getattr(r, "workout_date", today) or today) >= today - timedelta(days=14)]),
            "recent_longs": recent_longs[:4],
        }
    except Exception as exc:
        _log.warning("volume_mix unavailable: %s", exc)
        return {}


def _enrich_load_context(user_id, today: date, load: dict, db) -> dict:
    """Deload / ACWR history / moving-ceiling caution for consultative Now."""
    out = dict(load)
    try:
        from backend.models import TrainingPlan, TrainingLoadSnapshot, Race
        from backend.services.training_load import daily_tss_series
        from backend.services.load_plan import compute_load_plan, ACWR_CEILING_MULT
        from backend.services.guardrail import get_guardrail_result
        from backend.services.weekly_coach_message import _TARGET_CTL

        this_week_start = today - timedelta(days=today.weekday())
        last_week_start = this_week_start - timedelta(days=7)
        last_week_end = this_week_start - timedelta(days=1)
        prev_week_start = last_week_start - timedelta(days=7)
        prev_week_end = last_week_start - timedelta(days=1)

        def _week_tss(a: date, b: date) -> float:
            series = daily_tss_series(str(user_id), a, b)
            return float(sum(v for _, v in series))

        tss_this = _week_tss(this_week_start, today)
        tss_last = _week_tss(last_week_start, last_week_end)
        tss_prev = _week_tss(prev_week_start, prev_week_end)
        out["week_tss"] = round(tss_this, 0)
        out["last_week_tss"] = round(tss_last, 0)
        out["prior_week_tss"] = round(tss_prev, 0)

        # Recent ACWR peak (was the athlete over the guardrail lately?)
        peak_acwr = None
        rows = (
            db.query(TrainingLoadSnapshot)
            .filter(
                TrainingLoadSnapshot.user_id == user_id,
                TrainingLoadSnapshot.snapshot_date >= today - timedelta(days=21),
                TrainingLoadSnapshot.snapshot_date <= today,
            )
            .all()
        )
        for r in rows:
            v = getattr(r, "acwr", None)
            if v is None:
                continue
            fv = float(v)
            if peak_acwr is None or fv > peak_acwr:
                peak_acwr = fv
        out["acwr_peak_21d"] = round(peak_acwr, 2) if peak_acwr is not None else None

        # Display ACWR = current_load() (Banister series), same family as the
        # readiness API. Home tile may still show "—" when the *client* TSS
        # series is <28d; brief may only cite acwr_display when non-null.
        try:
            from backend.services.training_load import current_load

            cl = current_load(str(user_id), as_of=today) or {}
            if cl.get("acwr") is not None:
                out["acwr_display"] = round(float(cl["acwr"]), 2)
                out["acwr"] = out["acwr_display"]
        except Exception as exc:
            _log.warning("acwr_display via current_load failed: %s", exc)

        try:
            gr = get_guardrail_result(str(user_id), as_of_date=today) or {}
            out["guardrail_state"] = gr.get("guardrail_state")
            out["guardrail_message"] = gr.get("guardrail_message") or ""
            out["acwr_state"] = gr.get("acwr_state")
        except Exception:
            pass

        plan = (
            db.query(TrainingPlan)
            .filter(TrainingPlan.user_id == user_id)
            .order_by(TrainingPlan.updated_at.desc().nullslast())
            .first()
        )
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
        deload_planned = False
        ceiling_tss = None
        trailing_28d_avg = None
        if plan is not None and a_race is not None and a_race.race_date:
            race_week_start = a_race.race_date - timedelta(days=a_race.race_date.weekday())
            weeks_to_race = ((race_week_start - this_week_start).days // 7) + 1
            start_28 = today - timedelta(days=27)
            series_28 = daily_tss_series(str(user_id), start_28, today)
            total_28d = float(sum(v for _, v in series_28))
            trailing_28d_avg = round(total_28d / 4.0, 1)
            out["trailing_28d_weekly_avg"] = trailing_28d_avg
            ceiling_tss = (
                round(ACWR_CEILING_MULT * trailing_28d_avg, 0) if trailing_28d_avg else None
            )
            out["load_ceiling_tss"] = ceiling_tss
            ramp_rate = float(plan.ramp_rate) if plan.ramp_rate is not None else 0.05
            result = compute_load_plan(
                baseline=tss_last or trailing_28d_avg or 0,
                ramp_rate=ramp_rate,
                hold_weeks=int(plan.hold_weeks or 4),
                taper_weeks=int(round(float(plan.taper_length or 3))),
                weeks_to_race=max(1, weeks_to_race),
                trailing_28d_avg=trailing_28d_avg,
                deload_enabled=bool(plan.deload_enabled),
                deload_start_week=int(plan.deload_start_week or 4),
            )
            week1 = next(
                (w for w in result.get("weeks") or [] if w.get("week_index") == 1),
                None,
            )
            if week1 and week1.get("deload"):
                deload_planned = True
                out["deload_target_tss"] = week1.get("target_tss")

        wow_drop = bool(tss_last > 0 and tss_this < tss_last * 0.75)
        deload_week = bool(
            deload_planned or (wow_drop and plan is not None and plan.deload_enabled)
        )
        out["deload_week"] = deload_week
        if deload_week:
            out["deload_rationale"] = (
                f"Deload week — load is down "
                f"({int(tss_this)} TSS so far vs {int(tss_last)} last week). "
                "That is the point. Do not add TSS to 'catch up'."
            )

        was_high = peak_acwr is not None and peak_acwr > 1.30
        if deload_week or was_high or (ceiling_tss and tss_last > ceiling_tss * 0.95):
            out["ramp_caution"] = True
            peak_s = (
                f" ACWR peaked at {peak_acwr:.2f} in the last 3 weeks."
                if was_high
                else ""
            )
            ceil_s = (
                f" Moving-average load ceiling is ~{int(ceiling_tss)} TSS/week — "
                "stay under it when you resume the ramp."
                if ceiling_tss
                else ""
            )
            out["ramp_caution_text"] = (
                "Do not dump volume back on after this quiet week."
                + peak_s
                + ceil_s
                + " Stick to ~5%/week — no heroics."
            ).strip()

        dist_label = "marathon"
        if a_race is not None and a_race.distance_km is not None:
            dk = float(a_race.distance_km)
            if dk >= 40:
                dist_label = "marathon"
            elif dk >= 20:
                dist_label = "half"
            elif dk >= 9:
                dist_label = "10k"
            else:
                dist_label = "5k"
        target_ctl = _TARGET_CTL.get(dist_label, 70.0)
        ctl = out.get("ctl")
        if ctl is not None and target_ctl:
            out["ctl_gap_to_target"] = round(max(0.0, float(target_ctl) - float(ctl)), 1)
            out["target_ctl"] = target_ctl
    except Exception as exc:
        _log.warning("load context enrich failed: %s", exc)
    return out


def _praise_highlights(user_id, today: date) -> list[dict]:
    """Recent quality / strength work worth naming in Reflection."""
    try:
        from sqlalchemy.orm import Session
        from backend.db import engine
        from backend.models import Workout, PlannedSession

        start = today - timedelta(days=21)
        praise: list[dict] = []
        with Session(engine) as db:
            rows = (
                db.query(Workout)
                .filter(
                    Workout.user_id == user_id,
                    Workout.workout_date >= start,
                    Workout.workout_date <= today,
                )
                .order_by(Workout.workout_date.desc())
                .all()
            )
            for w in rows:
                name = getattr(w, "name", None) or ""
                nl = name.lower()
                wtype = (getattr(w, "workout_type", None) or "").lower()
                kind = None
                if "incline" in nl or ("interval" in nl and "incline" in nl):
                    kind = "incline_intervals"
                elif "interval" in nl or "interval" in wtype:
                    kind = "intervals"
                elif wtype == "strength" or "strength" in nl or "workout" in nl and wtype != "run":
                    if wtype == "strength" or "deadlift" in nl or "posterior" in nl:
                        kind = "strength"
                elif wtype == "plyo" or "plyo" in nl or "explosive" in nl:
                    kind = "plyo"
                if kind:
                    praise.append({
                        "date": _iso(w.workout_date),
                        "name": name,
                        "kind": kind,
                        "mins": int((w.duration_seconds or 0) // 60) or None,
                    })
            # Upcoming strength on the plan (praise the plan, not just past)
            upcoming = (
                db.query(PlannedSession)
                .filter(
                    PlannedSession.user_id == user_id,
                    PlannedSession.planned_date >= today,
                    PlannedSession.planned_date <= today + timedelta(days=7),
                    PlannedSession.session_type.in_(("strength", "plyo")),
                )
                .order_by(PlannedSession.planned_date.asc())
                .limit(3)
                .all()
            )
            for p in upcoming:
                praise.append({
                    "date": _iso(p.planned_date),
                    "name": p.name,
                    "kind": f"planned_{p.session_type}",
                    "mins": None,
                })
        # de-dupe by name+date, keep ≤5
        seen = set()
        out = []
        for p in praise:
            key = (p.get("date"), p.get("name"))
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
            if len(out) >= 5:
                break
        return out
    except Exception as exc:
        _log.warning("praise highlights unavailable: %s", exc)
        return []


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


def _active_gap_findings(user_id, today: date, db, limit: int = 8) -> list[dict]:
    """Active GapFinding rows for this ISO week (for session presets)."""
    try:
        from backend.models import GapFinding

        week_start = today - timedelta(days=today.weekday())
        rows = (
            db.query(GapFinding)
            .filter(
                GapFinding.user_id == user_id,
                GapFinding.week_start == week_start,
                GapFinding.status == "active",
            )
            .order_by(GapFinding.severity.desc(), GapFinding.computed_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "code": r.code,
                "severity": r.severity,
                "status": r.status,
                "recommendation": r.recommendation,
                "target": r.target,
            }
            for r in rows
        ]
    except Exception as exc:
        _log.warning("active gap findings unavailable: %s", exc)
        return []


def _session_checkin(user_id, today: date, db) -> list[dict]:
    """This week's planned + completed sessions for Coach check-in."""
    try:
        from backend.models import PlannedSession

        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        rows = (
            db.query(PlannedSession)
            .filter(
                PlannedSession.user_id == user_id,
                PlannedSession.planned_date >= week_start,
                PlannedSession.planned_date <= week_end,
            )
            .order_by(PlannedSession.planned_date.asc())
            .all()
        )
        out = []
        for r in rows:
            if (r.session_type or "") == "rest":
                continue
            structure = r.structure if isinstance(r.structure, dict) else {}
            out.append({
                "id": str(r.id),
                "date": _iso(r.planned_date),
                "name": r.name,
                "session_type": r.session_type,
                "status": r.status or "planned",
                "preset_code": structure.get("_preset_code") or structure.get("_gap_code"),
                "target_tss": structure.get("target_tss"),
                "duration_min": structure.get("duration_min"),
                "adjust_url": f"/log#plan?date={_iso(r.planned_date)}&session={r.id}",
            })
        return out
    except Exception as exc:
        _log.warning("session_checkin unavailable: %s", exc)
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


def _pick_dream_milestones(dream: dict, projection: dict) -> list[dict]:
    """Curate 1–2 near-term checkpoints + A-race estimate (not every race).

    Preference: next half-or-longer B/C race before A-race; else next B; skip
    short tune-ups when a better distance sits a few weeks later.
    """
    out: list[dict] = []
    a_race = dream.get("a_race") or {}
    races = list(dream.get("b_races") or [])

    def _is_half_plus(r: dict) -> bool:
        dk = r.get("distance_km")
        return dk is not None and float(dk) >= 20.0

    # Prefer first half-or-longer before A-race; else first upcoming
    pick = next((r for r in races if _is_half_plus(r)), None)
    if pick is None and races:
        pick = races[0]
    if pick:
        out.append({
            "kind": "b_race" if pick.get("priority") == "B" else "checkpoint_race",
            "name": pick.get("name"),
            "date": pick.get("date"),
            "distance_km": pick.get("distance_km"),
            "goal_time_label": pick.get("goal_time_label"),
            "est_label": pick.get("est_label"),
            "why": "Near-term progress check toward the A-race.",
        })

    # Optional second: longest mid-distance C/B between pick and A (e.g. 32k)
    if pick and a_race.get("date"):
        later = [
            r for r in races
            if r.get("date")
            and pick.get("date")
            and r["date"] > pick["date"]
            and r["date"] < a_race["date"]
            and (r.get("distance_km") or 0) >= 25
        ]
        if later:
            mid = max(later, key=lambda r: float(r.get("distance_km") or 0))
            out.append({
                "kind": "volume_checkpoint",
                "name": mid.get("name"),
                "date": mid.get("date"),
                "distance_km": mid.get("distance_km"),
                "goal_time_label": mid.get("goal_time_label"),
                "est_label": mid.get("est_label"),
                "why": "Longer checkpoint before the marathon.",
            })

    if a_race.get("name"):
        out.append({
            "kind": "a_race",
            "name": a_race.get("name"),
            "date": a_race.get("date"),
            "distance_km": a_race.get("distance_km"),
            "goal_time_label": a_race.get("goal_time_label"),
            "est_label": projection.get("current_trend_label")
            if not projection.get("unavailable")
            else None,
            "uncertainty_min": projection.get("uncertainty_min"),
            "why": "A-race goal.",
        })
    return out


def _block_delta_28d(trend: list, trend_dates: list) -> int | None:
    """Mirror frontend _hpfBlockDelta / Performance card ~28d block delta."""
    if not isinstance(trend, list) or len(trend) < 2:
        return None
    try:
        last = float(trend[-1])
    except (TypeError, ValueError):
        return None
    base = None
    if isinstance(trend_dates, list) and len(trend_dates) == len(trend):
        try:
            last_d = date.fromisoformat(str(trend_dates[-1])[:10])
            cutoff = last_d - timedelta(days=28)
            for i in range(len(trend) - 1, -1, -1):
                d = date.fromisoformat(str(trend_dates[i])[:10])
                if d <= cutoff:
                    base = float(trend[i])
                    break
        except (TypeError, ValueError):
            base = None
    if base is None:
        try:
            base = float(trend[0])
        except (TypeError, ValueError):
            return None
    return int(round(last - base))


def _performance_scores(user_id, db) -> dict | None:
    """Endurance / Speed from Performance-tab SummaryCache (SoT)."""
    try:
        from backend.services.race_finish_estimate import _endurance_speed_from_cache
        from backend.models import SummaryCache

        end_f, spd_f = _endurance_speed_from_cache(db, user_id)
        if end_f is None and spd_f is None:
            return None
        out: dict[str, Any] = {
            "endurance": round(end_f, 1) if end_f is not None else None,
            "speed": round(spd_f, 1) if spd_f is not None else None,
            "source": "performance_cache",
        }
        row = (
            db.query(SummaryCache)
            .filter(
                SummaryCache.user_id == user_id,
                SummaryCache.cache_key == "performance",
            )
            .first()
        )
        if row and isinstance(row.payload, dict):
            # Canonical direction = ~28d block delta (same as Performance card
            # pill via block_delta / _hpfBlockDelta). Cache "direction" can be a
            # shorter window and contradicted the card ("declining" vs ↑ +5).
            for key, dir_alias, delta_alias in (
                ("endurance", "endurance_direction", "endurance_block_delta"),
                ("speed", "speed_direction", "speed_block_delta"),
            ):
                block = row.payload.get(key) or {}
                delta = block.get("block_delta")
                if delta is None:
                    trend = block.get("trend") or []
                    dates = block.get("trend_dates") or []
                    delta = _block_delta_28d(trend, dates)
                if delta is not None:
                    try:
                        d_i = int(round(float(delta)))
                        out[delta_alias] = d_i
                        out[dir_alias] = (
                            "improving" if d_i > 0 else ("declining" if d_i < 0 else "flat")
                        )
                    except (TypeError, ValueError):
                        pass
                elif block.get("direction"):
                    out[dir_alias] = block.get("direction")
                # Short hint kept for diagnostics only
                trend = block.get("trend") or []
                if isinstance(trend, list) and len(trend) >= 4:
                    try:
                        hint = float(trend[-1]) - float(trend[-4])
                        out[f"{key}_delta_hint"] = round(hint, 1)
                    except (TypeError, ValueError):
                        pass
        return out
    except Exception as exc:
        _log.warning("performance scores unavailable: %s", exc)
        return None


def _dream_block(user_id, today: date, projection: dict, weight: dict) -> dict:
    """Phase 3: A-race + B-race benchmarks + checkpoints + weight scenario."""
    dream: dict[str, Any] = {
        "a_race": None,
        "b_races": [],
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

            # Upcoming B/C races — keep the raw list; narrative picks a subset.
            bc_rows = (
                db.query(Race)
                .filter(
                    Race.user_id == user_id,
                    Race.priority.in_(("B", "C")),
                    Race.status.in_(("planned", "active")),
                    Race.race_date >= today,
                )
                .order_by(Race.race_date.asc())
                .limit(6)
                .all()
            )
            for br in bc_rows:
                gsec = getattr(br, "goal_time_seconds", None)
                entry = {
                    "name": br.name,
                    "date": _iso(br.race_date),
                    "distance_km": float(br.distance_km) if br.distance_km is not None else None,
                    "goal_time_label": _fmt_hms(gsec),
                    "goal_time_sec": int(gsec) if gsec is not None else None,
                    "priority": br.priority,
                    "role": "benchmark_toward_a_race",
                    "id": str(br.id),
                }
                # Attach latest Performance-tab estimate when present
                try:
                    from backend.services.race_finish_estimate import (
                        _latest_shown_prediction,
                    )
                    shown = _latest_shown_prediction(db, br.id)
                    if shown and shown.get("est_sec"):
                        entry["est_sec"] = shown["est_sec"]
                        entry["est_label"] = _fmt_hms(shown["est_sec"])
                        entry["est_band_sec"] = shown.get("band_sec")
                except Exception:
                    pass
                dream["b_races"].append(entry)
    except Exception as exc:
        _log.warning("dream race/checkpoints unavailable: %s", exc)

    dream["milestones"] = _pick_dream_milestones(dream, projection)

    if projection:
        dream["scenarios"].append({
            "id": "plan_compliance",
            "label": "If you hit the plan",
            "finish_label": projection.get("full_compliance_label")
            or projection.get("goal_label"),
            "method": "performance_goal_target",
            "caveat": "Assumes plan compliance; band widens with sparse data.",
        })
        if projection.get("current_trend_label") and not projection.get("unavailable"):
            dream["scenarios"].append({
                "id": "current_trend",
                "label": "Performance estimate (race day)",
                "finish_label": projection.get("current_trend_label"),
                "method": projection.get("source") or "performance_time_curve",
                "caveat": (
                    f"±{projection.get('uncertainty_min', 0)} min band"
                    if projection.get("uncertainty_min")
                    else "Same engine as the Performance tab race card."
                ),
            })

    gap_kg = weight.get("gap_kg")
    base_sec = None
    try:
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
        improved = int(round(base_sec * (1.0 - 0.008 * cut_kg)))
        year_end = date(today.year, 12, 31)
        payoff_label = _fmt_hms(improved)
        weight["payoff_label"] = payoff_label
        weight["payoff_cut_kg"] = cut_kg
        dream["scenarios"].append({
            "id": "weight_cut",
            "label": f"If −{cut_kg:.0f} kg by {year_end.isoformat()}",
            "finish_label": payoff_label,
            "method": "0.8pct_per_kg_riegel_heuristic",
            "caveat": (
                "Heuristic only (~0.8% / kg); not a guarantee — fitness and "
                "fueling must hold while cutting."
            ),
            "cut_kg": cut_kg,
            "by_date": year_end.isoformat(),
            "sell": (
                f"Lose ~{cut_kg:.0f} kg and the same fitness projects closer to "
                f"{payoff_label} — that's why measurement is the gate."
            ),
        })

    # Prefer curated milestones for the Dream sell line
    milestones = dream.get("milestones") or []
    near = next((m for m in milestones if m.get("kind") != "a_race"), None)
    if near:
        dream["sell_line_facts"] = {
            "next_checkpoint_date": near.get("date"),
            "next_checkpoint_label": near.get("name"),
            "next_checkpoint_target": near.get("goal_time_label"),
            "next_checkpoint_est": near.get("est_label"),
            "role": "b_race_benchmark",
            "toward_a_race": (dream.get("a_race") or {}).get("name"),
            "toward_a_goal": (dream.get("a_race") or {}).get("goal_time_label"),
        }
    else:
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


def _focus_for_session(focus_ranked: list[dict], name: str | None, session_type: str | None) -> tuple[int, str] | None:
    """Map a planned session to the best matching Focus rank (1-based)."""
    blob = f"{name or ''} {session_type or ''}".lower()
    prefer: list[str] = []
    if any(k in blob for k in ("long", "aerobic", "easy")):
        prefer.extend(["long_run_fueling", "long_run"])
    if any(k in blob for k in ("interval", "speed", "track", "reps", "incline")):
        prefer.append("quality_intervals")
    if "tempo" in blob or "threshold" in blob:
        prefer.append("tempo")
    if "plyo" in blob or "explosive" in blob:
        prefer.append("plyo")
    if "strength" in blob or "gym" in blob or "deadlift" in blob:
        prefer.append("strength")
    if "weigh" in blob or "weight" in blob:
        prefer.extend(["weight_measurement", "weight_deficit"])
    if "deload" in blob or "easy" in blob:
        prefer.append("respect_deload")

    by_id = {r["id"]: r for r in (focus_ranked or []) if r.get("id")}
    for pid in prefer:
        if pid in by_id:
            r = by_id[pid]
            return int(r.get("rank") or 1), r.get("id") or pid
    # No match → None. Do NOT fall through to Focus #1 (that caused
    # "long run serves weight measurement" when prefer missed).
    return None


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
            name = row[2] or "Session"
            stype = row[3]
            matched = _focus_for_session(focus_ranked, name, stype)
            serves_rank = None
            serves_id = None
            if matched:
                serves_rank, serves_id = matched
                why = f"Serves focus rank {serves_rank} ({serves_id})"
            else:
                why = "Next planned session"
            reflection["next_session"] = {
                "id": str(row[0]),
                "date": _iso(row[1]),
                "name": name,
                "type": stype,
                "why_focus": why,
                "serves_focus_rank": serves_rank,
                "serves_focus_id": serves_id,
            }
    except Exception as exc:
        _log.warning("next_session unavailable: %s", exc)

    return reflection


def build_coach_facts(user_id, today: date | None = None, db=None) -> dict | None:
    """Return coach_facts dict, or None when no A-race / PerformanceGoal exists."""
    from backend.services.coach_plan import build_plan_state
    from backend.services.weekly_coach_message import (
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
        load = _enrich_load_context(user_id, today, load, db)

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
            "current_kg": (weight_status or {}).get("current_kg"),
            "goal_kg": (weight_status or {}).get("goal_kg"),
            "advisory_text": None,
            "recommended_deficit_kcal": weight_raw.get("recommended_deficit_kcal"),
        }
        _enrich_weight_plan_position(user_id, today, weight, db)
        # Precompute weight payoff so Focus ranking can sell it
        try:
            gap = float(weight.get("gap_kg") or 0)
            tsec = int(getattr(goal, "target_time", 0) or 0)
            if gap >= 2 and tsec > 0:
                cut = min(6.0, gap)
                weight["payoff_cut_kg"] = cut
                weight["payoff_label"] = _format_hms(
                    int(round(tsec * (1.0 - 0.008 * cut)))
                )
        except Exception:
            pass

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

        # Performance-tab SoT finish estimate (never CTL-ratio invent)
        race_est = _estimate_for_a_race(user_id, today, db)
        if race_est.get("goal_time_sec"):
            target_sec = int(race_est["goal_time_sec"])
            race_date = race_est.get("race_date") or race_date
            # Refresh payoff off A-race goal if richer
            try:
                gap = float(weight.get("gap_kg") or 0)
                if gap >= 2 and target_sec > 0:
                    cut = min(6.0, gap)
                    weight["payoff_cut_kg"] = cut
                    weight["payoff_label"] = _format_hms(
                        int(round(target_sec * (1.0 - 0.008 * cut)))
                    )
            except Exception:
                pass

        trend_sec = race_est.get("est_sec")
        trend_label = race_est.get("est_label")
        projection = {
            "goal_label": _format_hms(target_sec) if target_sec else None,
            "full_compliance_label": _format_hms(target_sec) if target_sec else None,
            "full_compliance_sec": target_sec or None,
            "current_trend_label": trend_label,
            "current_trend_sec": trend_sec,
            "uncertainty_min": race_est.get("uncertainty_min"),
            "distance_label": race_est.get("distance_label")
            or getattr(goal, "race_distance", None),
            "target_date": _iso(race_date),
            "source": race_est.get("source") or "none",
            "unavailable": bool(race_est.get("unavailable")),
        }

        gaps_top = _gaps_top(user_id, today)
        volume_mix = _volume_mix_hint(user_id, today)
        praise = _praise_highlights(user_id, today)
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
        if praise:
            reflection["praise"] = praise
        performance = _performance_scores(user_id, db)

        gap_findings = _active_gap_findings(user_id, today, db)
        from backend.services.gap_analysis.session_presets import (
            presets_from_findings,
        )
        active_presets = presets_from_findings(gap_findings)
        session_checkin = _session_checkin(user_id, today, db)
        reflection["session_checkin"] = session_checkin

        goal_block = {
            "distance": getattr(goal, "race_distance", None),
            "target_time_sec": target_sec or None,
            "target_time_label": _format_hms(target_sec) if target_sec else None,
            "race_date": _iso(race_date),
            "source": getattr(goal, "source", None) or "performance_goal",
        }
        if getattr(goal, "name", None):
            goal_block["name"] = goal.name
        if getattr(goal, "distance_km", None) is not None:
            goal_block["distance_km"] = float(goal.distance_km)
        # Bridge: when Plan A-race exists, prefer its date/time labels for goal display
        a_race = (dream.get("a_race") if isinstance(dream, dict) else None) or {}
        if a_race.get("date") or a_race.get("goal_time_sec"):
            if a_race.get("goal_time_sec"):
                goal_block["target_time_sec"] = a_race["goal_time_sec"]
                goal_block["target_time_label"] = a_race.get("goal_time_label")
            if a_race.get("date"):
                goal_block["race_date"] = a_race["date"]
            if a_race.get("distance_km") is not None:
                goal_block["distance_km"] = a_race["distance_km"]
            goal_block["name"] = a_race.get("name")
            goal_block["source"] = "a_race"

        # Default chosen preset = highest-priority active preset (Claude may override)
        chosen_preset = active_presets[0] if active_presets else None

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
            "gap_findings": gap_findings,
            "active_presets": active_presets,
            "chosen_preset": chosen_preset,
            "habits": habits,
            "focus_ranked": focus_ranked,
            "focus_noise": focus_noise,
            "volume_mix": volume_mix,
            "praise": praise,
            "performance": performance,
            "dream": dream,
            "reflection": reflection,
            "plan_state": plan_state,
        }
        facts["required_numerals"] = collect_required_numerals(facts)
        # Per-section fact subsets + today chips (brief v4)
        from backend.services.coach_brief_map import collect_section_facts
        from backend.services.coach_brief import derive_today_chips

        facts["section_facts"] = collect_section_facts(facts)
        facts["today_chips"] = derive_today_chips(facts)
        # Hermes / actions nudge payload — prefer chosen preset
        focus1 = focus_ranked[0] if focus_ranked else None
        next_s = (reflection or {}).get("next_session")
        if chosen_preset:
            next_action = (
                f"{chosen_preset.get('name') or chosen_preset.get('kind')} "
                f"({chosen_preset.get('summary')})"
            )
            why = chosen_preset.get("notes") or (
                focus1.get("label") if focus1 else None
            )
            facts["nudge"] = {
                "focus_id": chosen_preset.get("code"),
                "focus_label": chosen_preset.get("name") or chosen_preset.get("kind"),
                "next_action": next_action,
                "why": why,
                "preset_code": chosen_preset.get("code"),
            }
        else:
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


def _estimate_for_a_race(user_id, today: date, db) -> dict:
    """Load A-race and return Performance SoT estimate fields for projection."""
    from backend.models import Race
    from backend.services.race_finish_estimate import estimate_race_finish

    out: dict[str, Any] = {
        "unavailable": True,
        "source": "none",
        "est_sec": None,
        "est_label": None,
        "uncertainty_min": None,
    }
    try:
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
        if a_race is None:
            return out

        goal_sec = getattr(a_race, "goal_time_seconds", None)
        out["goal_time_sec"] = int(goal_sec) if goal_sec else None
        out["race_date"] = a_race.race_date
        dist_km = float(a_race.distance_km) if a_race.distance_km is not None else None
        if dist_km is not None:
            if dist_km >= 40:
                out["distance_label"] = "marathon"
            elif dist_km >= 20:
                out["distance_label"] = "HM"
            elif dist_km >= 9:
                out["distance_label"] = "10k"
            else:
                out["distance_label"] = "5k"

        est = estimate_race_finish(user_id, a_race, today=today, db=db)
        out.update(est)
        if out.get("unavailable"):
            out["est_sec"] = None
            out["est_label"] = None
            out["uncertainty_min"] = None
        return out
    except Exception as exc:
        _log.warning("A-race estimate unavailable: %s", exc)
        return out
