"""Revamp block load plan (P3-1): phases, weekly targets, snapshots.

Extends the load-plan concepts in ``load_plan.py`` with the mock's phase names
and compounding build/rebuild ramps. Legacy ``compute_load_plan`` stays for the
classic Plan tab until cutover.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import LoadPlanWeekSnapshot, Race
from backend.utils.time import today_bangkok
from backend.services.weekly_rollup import normalize_week_start

# P3-12 will persist these on the user; until then one named defaults block.
REVAMP_PLAN_DEFAULTS: dict[str, Any] = {
    "ramp_pct": 0.05,
    "build_weeks": 8,
    "peak_hold_weeks": 4,
    "taper_factors": [0.75, 0.55],
    "race_week_factor": 0.40,
    "recover_weeks": 1,
    "rebuild_weeks": 4,
}

REVAMP_PHASES = frozenset(
    {"build", "peak_hold", "taper", "race_week", "recover", "rebuild"}
)

_SNAPSHOT_UNSET = object()


class LoadPlanLayoutError(ValueError):
    """Raised when phase lengths cannot fit the weeks to the A race (P3-11)."""


def _settings_fingerprint(settings: dict[str, Any]) -> str:
    payload = json.dumps(settings, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def compute_revamp_block_series(
    *,
    chronic_baseline: float,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Pure series from block baseline through rebuild (no calendar dates)."""
    s = {**REVAMP_PLAN_DEFAULTS, **(settings or {})}
    ramp = float(s["ramp_pct"])
    build_w = int(s["build_weeks"])
    hold_w = int(s["peak_hold_weeks"])
    taper = list(s["taper_factors"])
    race_f = float(s["race_week_factor"])
    recover_w = int(s["recover_weeks"])
    rebuild_w = int(s["rebuild_weeks"])

    peak_override = s.get("peak_tss")
    if peak_override is not None and str(peak_override).strip() != "":
        peak_tss = max(0.0, float(peak_override))
        baseline = (
            peak_tss / ((1.0 + ramp) ** build_w) if build_w > 0 else peak_tss
        )
    else:
        baseline = max(0.0, float(chronic_baseline))
        peak_tss = baseline * ((1.0 + ramp) ** build_w) if build_w > 0 else baseline

    weeks: list[dict[str, Any]] = []
    for w in range(1, build_w + 1):
        weeks.append(
            {"week_index": len(weeks) + 1, "phase": "build", "target_tss": round(baseline * ((1.0 + ramp) ** w), 1)}
        )
    for _ in range(hold_w):
        weeks.append({"week_index": len(weeks) + 1, "phase": "peak_hold", "target_tss": round(peak_tss, 1)})
    for frac in taper:
        weeks.append(
            {"week_index": len(weeks) + 1, "phase": "taper", "target_tss": round(peak_tss * float(frac), 1)}
        )
    weeks.append(
        {"week_index": len(weeks) + 1, "phase": "race_week", "target_tss": round(peak_tss * race_f, 1)}
    )
    for _ in range(recover_w):
        weeks.append(
            {"week_index": len(weeks) + 1, "phase": "recover", "target_tss": round(peak_tss * race_f, 1)}
        )
    rebuild_base = peak_tss * race_f
    for w in range(1, rebuild_w + 1):
        weeks.append(
            {
                "week_index": len(weeks) + 1,
                "phase": "rebuild",
                "target_tss": round(rebuild_base * ((1.0 + ramp) ** w), 1),
            }
        )
    return round(peak_tss, 1), weeks


def weeks_from_block_start_to_race(block_start: date, race_date: date) -> int:
    """Whole Monday weeks from block_start Monday through the race week Monday."""
    bs = normalize_week_start(block_start)
    race_ws = normalize_week_start(race_date)
    if race_ws < bs:
        raise LoadPlanLayoutError("race falls before block start")
    return ((race_ws - bs).days // 7) + 1


def validate_block_layout(
    *,
    chronic_baseline: float,
    block_start: date,
    race_date: date,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Return (peak_tss, weeks) or raise LoadPlanLayoutError — never silent trim."""
    _peak, series = compute_revamp_block_series(chronic_baseline=chronic_baseline, settings=settings)
    need = weeks_from_block_start_to_race(block_start, race_date)
    have = len(series)
    if have != need:
        raise LoadPlanLayoutError(
            f"phase layout is {have} weeks but block needs {need} weeks to the A race"
        )
    return _peak, series


def _resolve_a_race(session: Session, user_id: uuid.UUID, today: date) -> Optional[Race]:
    return (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.race_date > today,
            Race.status == "planned",
            Race.priority == "A",
        )
        .order_by(Race.race_date)
        .first()
    )


def block_start_for_race(race_date: date, settings: Optional[dict[str, Any]] = None) -> date:
    """Block start Monday: enough weeks back for the configured phase layout."""
    s = {**REVAMP_PLAN_DEFAULTS, **(settings or {})}
    n = (
        int(s["build_weeks"])
        + int(s["peak_hold_weeks"])
        + len(s["taper_factors"])
        + 1
        + int(s["recover_weeks"])
        + int(s["rebuild_weeks"])
    )
    race_ws = normalize_week_start(race_date)
    return race_ws - timedelta(weeks=n - 1)


def week_starts_in_block(block_start: date, race_date: date) -> list[date]:
    bs = normalize_week_start(block_start)
    re = normalize_week_start(race_date)
    out: list[date] = []
    cursor = bs
    while cursor <= re:
        out.append(cursor)
        cursor += timedelta(days=7)
    return out


def _invalidate_future_snapshots(session: Session, user_id: uuid.UUID, from_week: date) -> None:
    session.query(LoadPlanWeekSnapshot).filter(
        LoadPlanWeekSnapshot.user_id == user_id,
        LoadPlanWeekSnapshot.week_start >= from_week,
    ).delete(synchronize_session=False)


def ensure_snapshots(
    session: Session,
    user_id: uuid.UUID,
    *,
    block_start: date,
    race_date: date,
    chronic_baseline: float,
    settings: Optional[dict[str, Any]] = None,
    today: Optional[date] = None,
) -> None:
    """Snapshot targets for started weeks; future weeks stay live-derived."""
    today = today or today_bangkok()
    current_ws = normalize_week_start(today)
    fp = _settings_fingerprint(settings or REVAMP_PLAN_DEFAULTS)
    _peak, series = validate_block_layout(
        chronic_baseline=chronic_baseline,
        block_start=block_start,
        race_date=race_date,
        settings=settings,
    )
    week_dates = week_starts_in_block(block_start, race_date)
    if len(week_dates) != len(series):
        raise LoadPlanLayoutError("week calendar does not match series length")

    # settings change: drop current+future snapshots so they re-derive
    _invalidate_future_snapshots(session, user_id, current_ws)

    for ws, spec in zip(week_dates, series):
        if ws > current_ws:
            continue
        existing = (
            session.query(LoadPlanWeekSnapshot)
            .filter(
                LoadPlanWeekSnapshot.user_id == user_id,
                LoadPlanWeekSnapshot.week_start == ws,
            )
            .first()
        )
        if existing is not None:
            if ws < current_ws:
                continue
            if existing.settings_fingerprint == fp:
                continue
            existing.target_tss = spec["target_tss"]
            existing.phase = spec["phase"]
            existing.peak_tss = _peak
            existing.settings_fingerprint = fp
        else:
            session.add(
                LoadPlanWeekSnapshot(
                    user_id=user_id,
                    week_start=ws,
                    target_tss=spec["target_tss"],
                    phase=spec["phase"],
                    peak_tss=_peak,
                    settings_fingerprint=fp,
                )
            )


def _live_week_target(
    *,
    block_start: date,
    race_date: date,
    week_start: date,
    chronic_baseline: float,
    settings: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Derive target/phase from the current series without writing snapshots."""
    _peak, series = validate_block_layout(
        chronic_baseline=chronic_baseline,
        block_start=block_start,
        race_date=race_date,
        settings=settings,
    )
    week_dates = week_starts_in_block(block_start, race_date)
    try:
        idx = week_dates.index(week_start)
    except ValueError:
        return None
    spec = series[idx]
    return {"target_tss": spec["target_tss"], "phase": spec["phase"], "peak_tss": _peak}


def ensure_snapshots_for_users(
    *,
    today: Optional[date] = None,
    user_id: Optional[uuid.UUID] = None,
) -> dict[str, str]:
    """Commit started-week snapshots for active users (weekly worker job)."""
    from backend.models import User
    from backend.services.revamp_plan_settings import plan_context

    today = today or today_bangkok()
    results: dict[str, str] = {}
    with Session(engine) as session:
        q = session.query(User.id).filter(User.is_active.is_(True))
        if user_id is not None:
            q = q.filter(User.id == user_id)
        ids = [r[0] for r in q.all()]
    for uid in ids:
        key = str(uid)
        try:
            with Session(engine) as session:
                ctx = plan_context(session, uid, today=today)
                if ctx is None:
                    results[key] = "skip_no_plan"
                    continue
                ensure_snapshots(
                    session,
                    uid,
                    block_start=ctx["block_start"],
                    race_date=ctx["race"].race_date,
                    chronic_baseline=ctx["chronic_baseline"],
                    settings=ctx["settings"],
                    today=today,
                )
                session.commit()
                results[key] = "ok"
        except Exception as exc:
            results[key] = f"error:{exc}"
    return results


def week_target_and_phase(
    user_id: uuid.UUID | str,
    week_start: date,
    *,
    session: Optional[Session] = None,
    chronic_baseline: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
    today: Optional[date] = None,
    ctx: Optional[dict[str, Any]] = None,
    snapshot: Any = _SNAPSHOT_UNSET,
) -> Optional[dict[str, Any]]:
    """Return target_tss + phase for a week inside the A-race block, else None.

    ``ctx`` / ``snapshot`` skip the per-week plan_context and snapshot queries
    used by batched ``weekly_rollups()``. Pass ``snapshot=None`` when the batch
    already looked up the row and missed — that live-derives without a write.
    """
    uid = uuid.UUID(str(user_id))
    ws = normalize_week_start(week_start)
    today = today or today_bangkok()
    if snapshot is not _SNAPSHOT_UNSET and snapshot is not None:
        return {
            "target_tss": float(snapshot.target_tss),
            "phase": snapshot.phase,
            "peak_tss": snapshot.peak_tss,
        }
    prefetched_miss = snapshot is not _SNAPSHOT_UNSET and snapshot is None
    own = session is None
    if own:
        session = Session(engine)
    try:
        from backend.services import revamp_plan_settings as _rps

        if ctx is None:
            ctx = _rps.plan_context(session, uid, today=today)
        if ctx is None:
            return None
        race = ctx["race"]
        block_start = ctx["block_start"]
        if settings is None:
            settings = ctx["settings"]
        if chronic_baseline is None:
            chronic_baseline = ctx["chronic_baseline"]
        if ws < normalize_week_start(block_start) or ws > normalize_week_start(race.race_date):
            return None

        current_ws = normalize_week_start(today)
        if chronic_baseline is None:
            chronic_baseline = 300.0  # fallback for tests without DB context

        if ws <= current_ws and not prefetched_miss:
            row = (
                session.query(LoadPlanWeekSnapshot)
                .filter(
                    LoadPlanWeekSnapshot.user_id == uid,
                    LoadPlanWeekSnapshot.week_start == ws,
                )
                .first()
            )
            if row is not None:
                return {
                    "target_tss": float(row.target_tss),
                    "phase": row.phase,
                    "peak_tss": row.peak_tss,
                }
            # Missing snapshot: live-derive. GETs must not write (#1924).

        return _live_week_target(
            block_start=block_start,
            race_date=race.race_date,
            week_start=ws,
            chronic_baseline=chronic_baseline,
            settings=settings,
        )
    finally:
        if own:
            session.close()


def chronic_weekly_tss(session: Session, user_id: uuid.UUID, today: date) -> float:
    from datetime import timedelta

    from backend.services.training_load import daily_tss_series

    start_28 = today - timedelta(days=27)
    series = daily_tss_series(str(user_id), start_28, today)
    total = float(sum(v for _, v in series))
    return round(total / 4.0, 1) if total > 0 else 300.0


def phase_overrun_summary(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mean percent over target for peak_hold and taper phases (P3-3)."""
    from collections import defaultdict

    buckets: dict[str, list[float]] = defaultdict(list)
    for col in columns:
        if col.get("state") != "done":
            continue
        target = col.get("target_tss")
        actual = col.get("actual_tss")
        phase = col.get("phase")
        if not target or actual is None or not phase:
            continue
        if actual > target * 1.05:
            buckets[phase].append((actual - target) / target * 100.0)
    out = []
    for phase, vals in buckets.items():
        if phase in ("peak_hold", "taper") and vals:
            out.append({"phase": phase, "mean_over_pct": round(sum(vals) / len(vals), 1)})
    return out


def _chart_column(
    *,
    ws: date,
    current_ws: date,
    rollup: dict[str, Any],
    target: Any,
    phase: Any,
) -> dict[str, Any]:
    actual = rollup.get("tss_total")
    if ws < current_ws:
        state = "done"
    elif ws == current_ws:
        state = "current"
    else:
        state = "future"
    over = False
    if state == "done" and target and actual is not None and actual > target * 1.05:
        over = True
    return {
        "week_start": ws.isoformat(),
        "phase": phase,
        "target_tss": target,
        "actual_tss": actual if state == "done" else None,
        "planned_tss": rollup.get("planned_tss_training") if state != "done" else None,
        "race_tss": rollup.get("race_planned_tss"),
        "race_items": rollup.get("race_items") or [],
        "state": state,
        "over_target": over,
        "on_target": bool(target and actual is not None and actual <= target * 1.05),
    }


def empty_generic_road(chronic: Optional[float] = None) -> dict[str, Any]:
    """No-A-race Plan payload: no history columns, no weekly_rollup (#1932)."""
    target = round(chronic, 1) if chronic is not None else None
    subtitle = (
        f"Reference {target:.0f} TSS/wk from your 28-day chronic"
        if target is not None
        else "Add a planned A race to unlock the road-to-race chart."
    )
    return {
        "mode": "generic",
        "title": "Recent training load",
        "subtitle": subtitle,
        "chronic_baseline": chronic,
        "plan_hint": "Add a planned A race in Settings → Plan to unlock the full road-to-race chart.",
        "columns": [],
        "phase_overruns": [],
    }


def generic_road_chart(
    user_id: uuid.UUID,
    *,
    session: Session,
    today: Optional[date] = None,
    span_weeks: int = 14,
    chronic: Optional[float] = None,
) -> dict[str, Any]:
    """Rolling weekly load when no A-race plan context (still shows real logged/planned TSS)."""
    from backend.services.weekly_rollup import weekly_rollups

    uid = uuid.UUID(str(user_id))
    today = today or today_bangkok()
    ws = normalize_week_start(today)
    if chronic is None:
        chronic = chronic_weekly_tss(session, uid, today)
    target = round(chronic, 1)
    oldest = ws - timedelta(weeks=max(span_weeks, 1) - 1)
    rolls = weekly_rollups(
        uid,
        oldest,
        ws,
        session=session,
        today=today,
        plan_ctx={"chronic_baseline": chronic},
    )
    by_start = {r["week_start"]: r for r in rolls}
    columns: list[dict[str, Any]] = []
    for i in range(span_weeks - 1, -1, -1):
        w = ws - timedelta(weeks=i)
        rollup = by_start.get(w.isoformat()) or {}
        logged = float(rollup.get("tss_total") or 0)
        col = _chart_column(
            ws=w,
            current_ws=ws,
            rollup=rollup,
            target=target,
            phase="this week" if w == ws else None,
        )
        # Generic chart used chronic as the target; keep on_target vs logged.
        if col["state"] == "done":
            col["on_target"] = bool(logged <= target * 1.05)
            col["over_target"] = bool(target and logged > target * 1.05)
        columns.append(col)
    return {
        "mode": "generic",
        "title": "Recent training load",
        "subtitle": f"Reference {target:.0f} TSS/wk from your 28-day chronic",
        "chronic_baseline": chronic,
        "plan_hint": "Add a planned A race in Settings → Plan to unlock the full road-to-race chart.",
        "columns": columns,
        "phase_overruns": [],
    }


def generic_week_load(
    user_id: uuid.UUID,
    week_start: date,
    *,
    session: Session,
    today: Optional[date] = None,
    chronic: Optional[float] = None,
) -> dict[str, Any]:
    """This-week load card without an A-race block — uses chronic as the training target."""
    from backend.services.load_plan import ACWR_CEILING_MULT
    from backend.services.weekly_rollup import weekly_rollup

    uid = uuid.UUID(str(user_id))
    today = today or today_bangkok()
    ws = normalize_week_start(week_start)
    if chronic is None:
        chronic = chronic_weekly_tss(session, uid, today)
    target = round(chronic, 1)
    rollup = weekly_rollup(uid, ws, session=session, today=today)
    ceiling = round(ACWR_CEILING_MULT * chronic, 1)
    logged = float(rollup.get("tss_total") or 0)
    planned = float(rollup.get("planned_tss_training") or 0)
    race_note = None
    if rollup.get("race_items"):
        rt = rollup.get("race_planned_tss") or 0
        race_note = f"Training target excludes race-day load; race adds about {int(rt)} TSS."
    headroom = target - (logged + planned)
    total = logged + planned
    if total > ceiling:
        headroom_state = "over_ceiling"
    elif total > target:
        headroom_state = "over_target"
    else:
        headroom_state = "under_target"
    return {
        "mode": "generic",
        "week_start": ws.isoformat(),
        "baseline_tss": target,
        "phase": "general",
        "phase_factor_pct": 100.0,
        "target_tss": target,
        "acwr_ceiling": ceiling,
        "trailing_28d_avg": chronic,
        "logged_tss": round(logged, 1),
        "planned_tss": round(planned, 1),
        "race_note": race_note,
        "headroom_tss": round(headroom, 1),
        "headroom_state": headroom_state,
        "plan_hint": "Add a planned A race to unlock phase targets, taper, and the road chart.",
    }


def road_to_chart(
    user_id: uuid.UUID,
    *,
    session: Optional[Session] = None,
    today: Optional[date] = None,
    ctx: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Block weeks with target/actual/planned/race stacks for the revamp chart."""
    from backend.services.weekly_rollup import weekly_rollups

    uid = uuid.UUID(str(user_id))
    today = today or today_bangkok()
    current_ws = normalize_week_start(today)
    own = session is None
    if own:
        session = Session(engine)
    try:
        from backend.services import revamp_plan_settings as _rps

        if ctx is None:
            ctx = _rps.plan_context(session, uid, today=today)
        if ctx is None:
            return None
        race = ctx["race"]
        block_start = ctx["block_start"]
        settings = ctx["settings"]
        weeks = week_starts_in_block(block_start, race.race_date)
        if not weeks:
            rolls: list[dict[str, Any]] = []
        else:
            rolls = weekly_rollups(
                uid, weeks[0], weeks[-1], session=session, today=today, plan_ctx=ctx
            )
        by_start = {r["week_start"]: r for r in rolls}
        columns: list[dict[str, Any]] = []
        for ws in weeks:
            rollup = by_start.get(ws.isoformat()) or {}
            columns.append(
                _chart_column(
                    ws=ws,
                    current_ws=current_ws,
                    rollup=rollup,
                    target=rollup.get("target_tss"),
                    phase=rollup.get("phase"),
                )
            )
        return {
            "race_name": race.name,
            "race_date": str(race.race_date),
            "block_start": block_start.isoformat(),
            "defaults": REVAMP_PLAN_DEFAULTS,
            "settings": settings,
            "columns": columns,
            "phase_overruns": phase_overrun_summary(columns),
        }
    finally:
        if own:
            session.close()


def revamp_week_load(
    user_id: uuid.UUID,
    week_start: date,
    *,
    session: Optional[Session] = None,
    today: Optional[date] = None,
    ctx: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """This-week load card payload (P3-4)."""
    from backend.services.load_plan import ACWR_CEILING_MULT
    from backend.services.weekly_rollup import weekly_rollup

    uid = uuid.UUID(str(user_id))
    today = today or today_bangkok()
    ws = normalize_week_start(week_start)
    own = session is None
    if own:
        session = Session(engine)
    try:
        from backend.services import revamp_plan_settings as _rps

        if ctx is None:
            ctx = _rps.plan_context(session, uid, today=today)
        if ctx is None:
            return None
        chronic = ctx["chronic_baseline"]
        meta = week_target_and_phase(
            uid,
            ws,
            session=session,
            chronic_baseline=chronic,
            settings=ctx["settings"],
            today=today,
            ctx=ctx,
        )
        if not meta:
            return None
        rollup = weekly_rollup(uid, ws, session=session, today=today)
        target = meta["target_tss"]
        peak = meta.get("peak_tss") or target
        phase = meta.get("phase") or "build"
        baseline = peak if phase in ("peak_hold", "taper", "race_week", "recover") else target
        factor = round((target / baseline) * 100, 1) if baseline else 100.0
        ceiling = round(ACWR_CEILING_MULT * chronic, 1)
        logged = rollup.get("tss_total") or 0
        planned = rollup.get("planned_tss_training") or 0
        race_note = None
        if rollup.get("race_items"):
            rt = rollup.get("race_planned_tss") or 0
            race_note = (
                f"Training target excludes race-day load; race adds about {int(rt)} TSS."
            )
        headroom = target - (logged + planned)
        if logged + planned > ceiling:
            headroom_state = "over_ceiling"
        elif logged + planned > target:
            headroom_state = "over_target"
        else:
            headroom_state = "under_target"
        return {
            "week_start": ws.isoformat(),
            "baseline_tss": round(baseline, 1),
            "phase": phase,
            "phase_factor_pct": factor,
            "target_tss": target,
            "acwr_ceiling": ceiling,
            "trailing_28d_avg": chronic,
            "logged_tss": round(logged, 1),
            "planned_tss": round(planned, 1),
            "race_note": race_note,
            "headroom_tss": round(headroom, 1),
            "headroom_state": headroom_state,
        }
    finally:
        if own:
            session.close()