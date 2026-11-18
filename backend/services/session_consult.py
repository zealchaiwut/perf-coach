"""Session-scoped consult prompts for race debrief (clipboard export).

Assembles a self-contained text prompt from persisted session/race/load data.
Never calls an LLM; mirrors coach_export.build_consult_blob style.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from backend.models import (
    PerformanceScoreHistory,
    PlannedSession,
    Race,
    RacePrediction,
    TrainingLoadSnapshot,
    UserPreferences,
    Workout,
    WorkoutFeel,
    WorkoutSplit,
    StrydActivity,
)
from backend.services.lap_classify import aggregate_intensity_zones
from backend.services.performance_scores import (
    _PERF_FORMULA_VERSION,
    _latest_race_perf,
)
from backend.services.race_auto_complete import _distance_ok
from backend.services.training_load import _FORMULA_VERSION as _LOAD_FORMULA_VERSION
from backend.utils.time import today_bangkok

PROMPT_VERSION_RACE = "race-debrief-v1"
PROMPT_VERSION_SESSION = "session-review-v1"
NOT_AVAILABLE = "not available"
MAX_PROMPT_CHARS = 20_000
LAP_ROW_COLLAPSE_THRESHOLD = 60
TIMEZONE_LABEL = "Asia/Bangkok"

RACE_INSTRUCTIONS = """\
You are my running coach doing a race debrief. Talk to me, ask me things,
and end with a short change list.

Rules — these override anything you infer:
1. Scores, CTL/ATL/TSB, estimates and TSS in this prompt are canonical. Don't recompute them.
2. Anything marked "derived" was computed for this prompt — you may question it.
3. If the data contradicts itself, say so plainly. That's a bug I need to know about.
4. If something is "not available", don't guess it. Ask me if it matters.

What to do:
1. Verdict — three sentences: how the race went against goal and estimate, and why.
2. Pacing — read the laps. Where did I lose time, and was it fitness, pacing, fuel, heat or a stop?
3. Compare with my previous races listed below. What's better, what's the same problem again?
4. Ask me two or three questions you actually need answered. Then wait.

After I answer, produce:

CHANGES TO APPLY
lessons:  <1–3 one-line lessons for future races>
skeleton: <change to training, if any>
goal:     <race goal changes, if any>
review:   <what to check, and when>

Style: short sentences, no preamble, no bullet walls. If the race was fine, say it was fine.
"""

SESSION_INSTRUCTIONS = """\
You are my running coach reviewing a single training session. Talk to me, ask me things,
and end with a short change list when warranted.

Rules — these override anything you infer:
1. Scores, CTL/ATL/TSB, and TSS in this prompt are canonical. Don't recompute them.
2. Anything marked "derived" was computed for this prompt — you may question it.
3. If the data contradicts itself, say so plainly.
4. If something is "not available", don't guess it. Ask me if it matters.

What to do:
1. Review this session against what it was meant to be (planned session block if present).
2. Call out load, execution, and signals that matter for the next week.
3. Ask me one or two questions you actually need answered. Then wait.

After I answer, produce:

CHANGES TO APPLY
lessons:  <optional one-line lessons>
skeleton: <change to training, if any>
goal:     <goal changes, if any>
review:   <what to check, and when>

Style: short sentences, no preamble, no bullet walls.
"""


@dataclass
class ConsultPrompt:
    kind: str
    prompt: str
    chars: int
    missing: list[str]
    notes: list[str]


ScoreReader = Callable[[Session, uuid.UUID, date], dict]


def _default_score_reader(session: Session, user_id: uuid.UUID, as_of: date) -> dict:
    """Read scores through the canonical reader (revamp P0-5)."""
    from backend.services.score_reader import consult_score_reader

    return consult_score_reader(session, user_id, as_of)


def _na(value, *, suffix: str = "") -> str:
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return NOT_AVAILABLE
    if isinstance(value, str) and not value.strip():
        return NOT_AVAILABLE
    if suffix:
        return f"{value}{suffix}"
    return str(value)


def _fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None or seconds < 0:
        return NOT_AVAILABLE
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_pace(sec_per_km: Optional[float]) -> str:
    if sec_per_km is None or sec_per_km <= 0:
        return NOT_AVAILABLE
    sec = int(round(sec_per_km))
    return f"{sec // 60}:{sec % 60:02d}/km"


def _pace_from_split(distance_km: float, duration_seconds: int) -> Optional[float]:
    if distance_km <= 0 or duration_seconds <= 0:
        return None
    return duration_seconds / distance_km


def _find_linked_race(session: Session, workout: Workout) -> tuple[Optional[Race], bool]:
    """Return (race, inferred_by_date_distance)."""
    if workout.workout_date is None or workout.distance_km is None:
        return None, False
    run_dist = float(workout.distance_km)
    races = (
        session.query(Race)
        .filter(
            Race.user_id == workout.user_id,
            Race.race_type == "race",
            Race.race_date == workout.workout_date,
        )
        .all()
    )
    if not races:
        return None, False
    matches = [
        r
        for r in races
        if r.distance_km is not None and _distance_ok(float(r.distance_km), run_dist)
    ]
    if not matches:
        return None, False
    matches.sort(key=lambda r: abs(float(r.distance_km) - run_dist))
    return matches[0], True


def _race_prediction_block(
    session: Session,
    race: Race,
    workout_date: date,
    missing: list[str],
    notes: list[str],
) -> tuple[str, str, str, Optional[int]]:
    pre = (
        session.query(RacePrediction)
        .filter(
            RacePrediction.race_id == race.id,
            RacePrediction.prediction_date < workout_date,
        )
        .order_by(RacePrediction.prediction_date.desc())
        .first()
    )
    if pre:
        est = _fmt_duration(pre.predicted_seconds)
        band = _na(pre.band_seconds, suffix=" s band") if pre.band_seconds else NOT_AVAILABLE
        label = f"pre-race snapshot ({pre.prediction_date.isoformat()})"
        return est, band, label, pre.predicted_seconds
    cur = (
        session.query(RacePrediction)
        .filter(RacePrediction.race_id == race.id)
        .order_by(RacePrediction.prediction_date.desc())
        .first()
    )
    if cur:
        notes.append("pre-race estimate uses latest stored snapshot (none before race day)")
        est = _fmt_duration(cur.predicted_seconds)
        band = _na(cur.band_seconds, suffix=" s band") if cur.band_seconds else NOT_AVAILABLE
        return est, band, f"current ({cur.prediction_date.isoformat()})", cur.predicted_seconds
    missing.extend(["pre-race estimate", "estimate band"])
    return NOT_AVAILABLE, NOT_AVAILABLE, NOT_AVAILABLE, None


def _load_snapshots_weekly(
    session: Session, user_id: uuid.UUID, end_date: date, weeks: int = 8
) -> list[str]:
    lines: list[str] = []
    monday = end_date - timedelta(days=end_date.weekday())
    for i in range(weeks):
        ws = monday - timedelta(weeks=i)
        we = ws + timedelta(days=6)
        rows = (
            session.query(TrainingLoadSnapshot)
            .filter(
                TrainingLoadSnapshot.user_id == user_id,
                TrainingLoadSnapshot.snapshot_date >= ws,
                TrainingLoadSnapshot.snapshot_date <= we,
                TrainingLoadSnapshot.formula_version == _LOAD_FORMULA_VERSION,
            )
            .all()
        )
        week_tss = sum(r.tss_for_day for r in rows) if rows else None
        tag = "taper" if i < 2 else "build"
        lines.append(
            f"  week {ws.isoformat()}–{we.isoformat()} ({tag}): "
            f"{_na(week_tss, suffix=' TSS') if week_tss is not None else NOT_AVAILABLE}"
        )
    return lines


def _load_ctl_block(session: Session, user_id: uuid.UUID, as_of: date, missing: list[str]) -> str:
    snap = (
        session.query(TrainingLoadSnapshot)
        .filter(
            TrainingLoadSnapshot.user_id == user_id,
            TrainingLoadSnapshot.snapshot_date <= as_of,
            TrainingLoadSnapshot.formula_version == _LOAD_FORMULA_VERSION,
        )
        .order_by(TrainingLoadSnapshot.snapshot_date.desc())
        .first()
    )
    if snap is None:
        missing.append("CTL/ATL/TSB")
        return (
            f"CTL: {NOT_AVAILABLE}  ATL: {NOT_AVAILABLE}  TSB: {NOT_AVAILABLE} "
            f"(as of {as_of.isoformat()})"
        )
    return (
        f"CTL: {round(snap.ctl, 1)}  ATL: {round(snap.atl, 1)}  TSB: {round(snap.tsb, 1)} "
        f"(snapshot {snap.snapshot_date.isoformat()})"
    )


def _lap_rows_from_splits(splits: Sequence[WorkoutSplit]) -> list[dict]:
    rows = []
    for sp in splits:
        pace = _pace_from_split(float(sp.distance_km), sp.duration_seconds)
        rows.append(
            {
                "lap": sp.split_index,
                "distance_km": float(sp.distance_km),
                "duration_seconds": sp.duration_seconds,
                "pace": _fmt_pace(pace),
                "gap": NOT_AVAILABLE,
                "avg_power": _na(sp.avg_power, suffix=" W"),
                "avg_hr": _na(sp.avg_hr, suffix=" bpm"),
                "cadence": _na(sp.cadence_spm, suffix=" spm"),
                "elevation": NOT_AVAILABLE,
            }
        )
    return rows


def collapse_lap_rows(rows: list[dict], *, force_per_km: bool = False) -> list[dict]:
    if not force_per_km and len(rows) <= LAP_ROW_COLLAPSE_THRESHOLD:
        return rows
    by_km: dict[int, dict] = {}
    for row in rows:
        km = max(1, int(math.floor(row.get("distance_km") or 0) + 1e-9))
        if km not in by_km:
            by_km[km] = {
                "lap": km,
                "distance_km": 0.0,
                "duration_seconds": 0,
                "powers": [],
                "hrs": [],
                "cadences": [],
            }
        bucket = by_km[km]
        bucket["distance_km"] += row.get("distance_km") or 0
        bucket["duration_seconds"] += row.get("duration_seconds") or 0
        if row.get("avg_power") and row["avg_power"] != NOT_AVAILABLE:
            try:
                bucket["powers"].append(int(str(row["avg_power"]).split()[0]))
            except ValueError:
                pass
        if row.get("avg_hr") and row["avg_hr"] != NOT_AVAILABLE:
            try:
                bucket["hrs"].append(int(str(row["avg_hr"]).split()[0]))
            except ValueError:
                pass
        if row.get("cadence") and row["cadence"] != NOT_AVAILABLE:
            try:
                bucket["cadences"].append(int(str(row["cadence"]).split()[0]))
            except ValueError:
                pass
    out: list[dict] = []
    for km in sorted(by_km):
        b = by_km[km]
        pace = _pace_from_split(b["distance_km"], b["duration_seconds"])
        out.append(
            {
                "lap": km,
                "distance_km": round(b["distance_km"], 3),
                "duration_seconds": b["duration_seconds"],
                "pace": _fmt_pace(pace),
                "gap": NOT_AVAILABLE,
                "avg_power": _na(round(sum(b["powers"]) / len(b["powers"])) if b["powers"] else None, suffix=" W"),
                "avg_hr": _na(round(sum(b["hrs"]) / len(b["hrs"])) if b["hrs"] else None, suffix=" bpm"),
                "cadence": _na(round(sum(b["cadences"]) / len(b["cadences"])) if b["cadences"] else None, suffix=" spm"),
                "elevation": NOT_AVAILABLE,
            }
        )
    return out


def _lap_table_markdown(
    rows: list[dict],
    *,
    include_gap: bool = True,
    include_cadence: bool = True,
) -> str:
    headers = ["lap", "dist", "time", "pace"]
    if include_gap:
        headers.append("GAP")
    headers.extend(["pwr", "HR"])
    if include_cadence:
        headers.append("cad")
    headers.append("elev")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        cells = [
            str(r["lap"]),
            f"{r['distance_km']:.2f}" if isinstance(r.get("distance_km"), (int, float)) else NOT_AVAILABLE,
            _fmt_duration(r.get("duration_seconds")),
            r.get("pace", NOT_AVAILABLE),
        ]
        if include_gap:
            cells.append(r.get("gap", NOT_AVAILABLE))
        cells.extend([r.get("avg_power", NOT_AVAILABLE), r.get("avg_hr", NOT_AVAILABLE)])
        if include_cadence:
            cells.append(r.get("cadence", NOT_AVAILABLE))
        cells.append(r.get("elevation", NOT_AVAILABLE))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _derive_block(rows: list[dict], workout: Workout) -> str:
    if len(rows) < 2:
        return "derived for this prompt, not canonical: insufficient laps for splits"
    half = len(rows) // 2
    first, second = rows[:half], rows[half:]

    def _avg_pace(group):
        secs = sum(r.get("duration_seconds") or 0 for r in group)
        dist = sum(r.get("distance_km") or 0 for r in group)
        return _pace_from_split(dist, secs) if dist > 0 and secs > 0 else None

    p1, p2 = _avg_pace(first), _avg_pace(second)
    fade = None
    if p1 and p2 and p1 > 0:
        fade = round((p2 - p1) / p1 * 100.0, 1)
    fastest = min(rows, key=lambda r: _pace_from_split(r.get("distance_km", 0), r.get("duration_seconds") or 0) or 1e9)
    def _pace_sec(r):
        return _pace_from_split(r.get("distance_km", 0), r.get("duration_seconds") or 0) or 0

    slowest = max(rows, key=_pace_sec)
    stopped = NOT_AVAILABLE
    if workout.duration_seconds is not None:
        moving = workout.duration_seconds
        stopped = _fmt_duration(max(0, moving - sum(r.get("duration_seconds") or 0 for r in rows)))
    decoupling = _na(workout.decoupling_percent, suffix="%")
    return "\n".join(
        [
            "derived for this prompt, not canonical:",
            f"  first half pace: {_fmt_pace(p1)}  | second half: {_fmt_pace(p2)}",
            f"  pace fade %: {_na(fade)}",
            f"  HR drift (decoupling on file): {decoupling}",
            f"  fastest km: lap {fastest.get('lap')} @ {fastest.get('pace')}",
            f"  slowest km: lap {slowest.get('lap')} @ {slowest.get('pace')}",
            f"  stopped time (approx): {stopped}",
        ]
    )


def select_previous_races(
    session: Session, user_id: uuid.UUID, target_distance_km: Optional[float], exclude_race_id: Optional[uuid.UUID], limit: int = 5
) -> list[Race]:
    done = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.race_type == "race",
            Race.status == "done",
            Race.actual_time_seconds.isnot(None),
            Race.distance_km.isnot(None),
        )
        .order_by(Race.race_date.desc())
        .all()
    )
    if exclude_race_id:
        done = [r for r in done if r.id != exclude_race_id]
    if not done:
        return []
    if target_distance_km is None:
        return done[:limit]

    same = [r for r in done if _distance_ok(float(r.distance_km), float(target_distance_km))]
    if len(same) >= 3:
        return same[:limit]
    def _dist_key(r: Race):
        return abs(float(r.distance_km) - float(target_distance_km))
    done.sort(key=lambda r: (_dist_key(r), r.race_date or date.min), reverse=False)
    return done[:limit]


def _previous_race_lines(session: Session, races: Iterable[Race]) -> list[str]:
    lines = []
    for r in races:
        pace = _fmt_pace(
            _pace_from_split(float(r.distance_km), int(r.actual_time_seconds))
            if r.distance_km and r.actual_time_seconds
            else None
        )
        w = (
            session.query(Workout)
            .filter(
                Workout.user_id == r.user_id,
                Workout.workout_date == r.race_date,
            )
            .order_by(Workout.duration_seconds.desc().nulls_last())
            .first()
        )
        avg_hr = _na(w.avg_hr if w else None, suffix=" bpm")
        avg_pwr = _na(w.avg_power if w else None, suffix=" W")
        lines.append(
            f"  - {r.race_date.isoformat()} {_na(float(r.distance_km), suffix=' km')}: "
            f"time {_fmt_duration(r.actual_time_seconds)} pace {pace} "
            f"HR {avg_hr} power {avg_pwr} lessons: none recorded"
        )
    return lines


def _tss_lines(workout: Workout, stryd: Optional[StrydActivity], missing: list[str]) -> str:
    from backend.services.session_tss import session_tss

    counted = session_tss(
        workout,
        stryd_tss=stryd.tss if stryd else None,
    )
    app_tss = counted.get("tss")
    app_method = counted.get("method") or workout.tss_method or workout.tss_source
    stryd_tss = stryd.tss if stryd else None
    canonical = _na(int(app_tss) if app_tss is not None else None)
    parts = [f"app counts: {canonical} ({_na(app_method)})"]
    if stryd_tss is not None and (app_tss is None or int(stryd_tss) != int(round(app_tss))):
        parts.append(f"Stryd file TSS: {stryd_tss}")
    elif stryd_tss is None:
        missing.append("Stryd TSS")
    return "  ".join(parts)


def _trim_prompt_size(
    prompt: str,
    lap_section: str,
    rows: list[dict],
    notes: list[str],
) -> tuple[str, list[dict]]:
    """Drop GAP/cadence columns, then thin lap rows if still too long."""
    if len(prompt) <= MAX_PROMPT_CHARS:
        return prompt, rows
    current = lap_section
    include_gap, include_cadence = True, True
    working = rows
    for step in range(5):
        if len(prompt) <= MAX_PROMPT_CHARS:
            break
        if step == 0:
            include_gap = False
            notes.append("prompt trimmed: dropped GAP column")
        elif step == 1:
            include_cadence = False
            notes.append("prompt trimmed: dropped cadence column")
        elif step == 2:
            working = working[::2]
            notes.append("prompt trimmed: lap rows every 2 km")
        elif step == 3:
            working = working[:40]
            notes.append("prompt trimmed: lap row cap")
        else:
            working = working[:20]
            notes.append("prompt trimmed: lap row hard cap")
        new_section = _lap_table_markdown(
            working, include_gap=include_gap, include_cadence=include_cadence
        )
        prompt = prompt.replace(current, new_section)
        current = new_section
    return prompt, working


def build_session_consult(
    session_id: uuid.UUID,
    *,
    now: datetime | None = None,
    score_reader: ScoreReader | None = None,
    db: Session | None = None,
    user_id: uuid.UUID | None = None,
) -> ConsultPrompt:
    """Build consult prompt for a workout session. Opens DB when db is None."""
    reader = score_reader or _default_score_reader
    generated = now or datetime.now(timezone.utc)
    missing: list[str] = []
    notes: list[str] = []

    from backend.db import engine
    from sqlalchemy.orm import Session as OrmSession

    def _build(session: Session, uid: uuid.UUID) -> ConsultPrompt:
        missing.clear()
        notes.clear()
        workout = session.get(Workout, session_id)
        if workout is None or workout.user_id != uid:
            raise ValueError("session_not_found")
        splits = (
            session.query(WorkoutSplit)
            .filter(WorkoutSplit.workout_id == workout.id)
            .order_by(WorkoutSplit.split_index)
            .all()
        )
        prefs = (
            session.query(UserPreferences).filter(UserPreferences.user_id == uid).first()
        )
        stryd = (
            session.get(StrydActivity, workout.stryd_activity_pk)
            if workout.stryd_activity_pk
            else None
        )
        feel = (
            session.query(WorkoutFeel)
            .filter(WorkoutFeel.workout_id == workout.id)
            .order_by(WorkoutFeel.created_at.desc())
            .first()
        )
        race, race_inferred = _find_linked_race(session, workout)
        kind = "race" if race is not None else "session"
        if race_inferred and race is not None:
            notes.append(
                f"race linked by date+distance (no explicit workout link) — {race.name}"
            )

        lap_rows = collapse_lap_rows(_lap_rows_from_splits(splits), force_per_km=len(splits) > LAP_ROW_COLLAPSE_THRESHOLD)
        lap_section = _lap_table_markdown(lap_rows)
        if not splits:
            missing.extend(["laps", "HR", "splits"])

        zones = aggregate_intensity_zones(
            splits,
            {
                "ftp_w": prefs.ftp_w if prefs else None,
                "threshold_hr": prefs.threshold_hr if prefs else None,
                "threshold_pace_seconds_per_km": (
                    prefs.threshold_pace_seconds_per_km if prefs else None
                ),
            },
        )
        vi = NOT_AVAILABLE
        if workout.np and workout.avg_power and workout.avg_power > 0:
            vi = round(workout.np / workout.avg_power, 2)

        scores = reader(session, uid, workout.workout_date or today_bangkok())
        ctl_block = _load_ctl_block(session, uid, workout.workout_date or today_bangkok(), missing)
        weekly = _load_snapshots_weekly(session, uid, workout.workout_date or today_bangkok())

        header = [
            f"prompt_version: {PROMPT_VERSION_RACE if kind == 'race' else PROMPT_VERSION_SESSION}",
            f"generated_at: {generated.isoformat()}",
            f"timezone: {TIMEZONE_LABEL}",
            f"session_id: {workout.id}",
            "",
            RACE_INSTRUCTIONS if kind == "race" else SESSION_INSTRUCTIONS,
            "",
            "## Header",
        ]

        body: list[str] = header

        if kind == "race" and race is not None:
            est, band, est_label, pred_secs = _race_prediction_block(
                session, race, workout.workout_date, missing, notes
            )
            goal_pace = _fmt_pace(
                float(race.goal_pace_seconds_per_km) if race.goal_pace_seconds_per_km else None
            )
            actual = race.actual_time_seconds or workout.duration_seconds
            gap_goal = NOT_AVAILABLE
            gap_est = NOT_AVAILABLE
            if race.goal_time_seconds and actual:
                gap_goal = f"{actual - race.goal_time_seconds:+d} s"
            if pred_secs and actual:
                gap_est = f"{int(actual) - int(pred_secs):+d} s"
            body.extend(
                [
                    "",
                    "## Race",
                    f"race_link: {'inferred (date+distance)' if race_inferred else 'explicit'}",
                    f"name: {race.name}",
                    f"priority: {race.priority}",
                    f"distance_km: {_na(float(race.distance_km) if race.distance_km is not None else None)}",
                    f"date: {race.race_date.isoformat()}",
                    f"goal_time: {_fmt_duration(race.goal_time_seconds)}",
                    f"goal_pace: {goal_pace}",
                    f"pre-race estimate ({est_label}): {est}",
                    f"estimate band: {band}",
                    f"actual_time: {_fmt_duration(actual)}",
                    f"gap_to_goal: {gap_goal}",
                    f"gap_to_estimate: {gap_est}",
                    f"race_endurance_score: {_na(scores.get('endurance'))}",
                    f"race_speed_score: {_na(scores.get('speed'))}",
                ]
            )
            prev = select_previous_races(
                session, uid, float(race.distance_km) if race.distance_km else None, race.id
            )
            prev_lines = _previous_race_lines(session, prev)
            body.extend(
                ["", "## Previous races", *(prev_lines if prev_lines else [NOT_AVAILABLE])]
            )

        body.extend(
            [
                "",
                "## Session summary",
                f"distance_km: {_na(float(workout.distance_km) if workout.distance_km is not None else None)}",
                f"moving_time: {_fmt_duration(workout.duration_seconds)}",
                f"elapsed_time: {NOT_AVAILABLE}",
                f"avg_pace: {_fmt_pace(_pace_from_split(float(workout.distance_km), workout.duration_seconds or 0) if workout.distance_km and workout.duration_seconds else None)}",
                f"avg_power: {_na(workout.avg_power, suffix=' W')}",
                f"normalized_power: {_na(workout.np, suffix=' W')}",
                f"variability_index: {_na(vi)}",
                f"avg_hr: {_na(workout.avg_hr, suffix=' bpm')}",
                f"max_hr: {_na(workout.max_hr, suffix=' bpm')}",
                f"cadence: {_na(workout.avg_cadence_spm, suffix=' spm')}",
                f"stride: {_na(workout.avg_stride_m, suffix=' m')}",
                f"elevation_gain: {_na(workout.elevation_m, suffix=' m')}",
                f"elevation_loss: {NOT_AVAILABLE}",
                f"temperature_c: {_na(workout.temperature_c)}",
                f"zone2_minutes: {_na(workout.zone2_minutes)}",
                f"power_zones (ftp {_na(prefs.ftp_w if prefs else None, suffix=' W')}): {zones or NOT_AVAILABLE}",
                f"TSS: {_tss_lines(workout, stryd, missing)}",
                "",
                "## Laps",
                lap_section,
                "",
                "## Derived",
                _derive_block(lap_rows, workout),
                "",
                "## Athlete context",
                f"endurance_score: {_na(scores.get('endurance'))} (as of {scores.get('as_of_date')})",
                f"speed_score: {_na(scores.get('speed'))} (as of {scores.get('as_of_date')})",
                f"score_anchor_date: {scores.get('anchor_date')}",
                f"score_anchor_effort: {scores.get('anchor_effort')}",
                ctl_block,
                "## Weekly TSS (8 weeks, Mon–Sun)",
                *weekly,
                "",
                "## What I logged",
                f"feeling: {_na(workout.feeling)}",
                f"fuel: {_na(workout.fuelled)}",
                f"fuel_detail (gels/first-at/stomach): {NOT_AVAILABLE}",
                f"feel_notes: {_na(feel.notes if feel else None)}",
                f"remarks: {_na(workout.remarks)}",
            ]
        )

        if kind == "session":
            planned = (
                session.query(PlannedSession)
                .filter(PlannedSession.matched_workout_id == workout.id)
                .first()
            )
            tss_plan = NOT_AVAILABLE
            coach = NOT_AVAILABLE
            pname = NOT_AVAILABLE
            if planned:
                pname = _na(planned.name)
                struct = planned.structure if isinstance(planned.structure, dict) else {}
                tss_plan = _na(struct.get("target_tss"))
                coach = _na(planned.notes)
            else:
                missing.append("planned session match")
            body.extend(
                [
                    "",
                    "## Planned session",
                    f"name: {pname}",
                    f"planned_tss: {tss_plan}",
                    f"coach/support: {coach}",
                ]
            )

        prompt = "\n".join(body)
        prompt, _ = _trim_prompt_size(prompt, lap_section, lap_rows, notes)
        return ConsultPrompt(
            kind=kind,
            prompt=prompt,
            chars=len(prompt),
            missing=sorted(set(missing)),
            notes=sorted(set(notes)),
        )

    if db is not None:
        if user_id is None:
            raise ValueError("user_id required when db is provided")
        return _build(db, user_id)

    with OrmSession(engine) as session:
        if user_id is None:
            w = session.get(Workout, session_id)
            if w is None:
                raise ValueError("session_not_found")
            user_id = w.user_id
        return _build(session, user_id)