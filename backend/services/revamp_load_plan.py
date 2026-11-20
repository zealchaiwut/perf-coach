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


def week_target_and_phase(
    user_id: uuid.UUID | str,
    week_start: date,
    *,
    session: Optional[Session] = None,
    chronic_baseline: Optional[float] = None,
    settings: Optional[dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """Return target_tss + phase for a week inside the A-race block, else None."""
    uid = uuid.UUID(str(user_id))
    ws = normalize_week_start(week_start)
    today = today or today_bangkok()
    own = session is None
    if own:
        session = Session(engine)
    try:
        race = _resolve_a_race(session, uid, today)
        if race is None:
            return None
        block_start = block_start_for_race(race.race_date, settings)
        if ws < normalize_week_start(block_start) or ws > normalize_week_start(race.race_date):
            return None

        current_ws = normalize_week_start(today)
        if chronic_baseline is None:
            chronic_baseline = 300.0  # caller should pass CTL-derived chronic; tests patch this

        if ws <= current_ws:
            row = (
                session.query(LoadPlanWeekSnapshot)
                .filter(
                    LoadPlanWeekSnapshot.user_id == uid,
                    LoadPlanWeekSnapshot.week_start == ws,
                )
                .first()
            )
            if row is None:
                ensure_snapshots(
                    session,
                    uid,
                    block_start=block_start,
                    race_date=race.race_date,
                    chronic_baseline=chronic_baseline,
                    settings=settings,
                    today=today,
                )
                session.flush()
                row = (
                    session.query(LoadPlanWeekSnapshot)
                    .filter(
                        LoadPlanWeekSnapshot.user_id == uid,
                        LoadPlanWeekSnapshot.week_start == ws,
                    )
                    .first()
                )
            if row:
                return {"target_tss": float(row.target_tss), "phase": row.phase, "peak_tss": row.peak_tss}
            return None

        _peak, series = validate_block_layout(
            chronic_baseline=chronic_baseline,
            block_start=block_start,
            race_date=race.race_date,
            settings=settings,
        )
        week_dates = week_starts_in_block(block_start, race.race_date)
        try:
            idx = week_dates.index(ws)
        except ValueError:
            return None
        spec = series[idx]
        return {"target_tss": spec["target_tss"], "phase": spec["phase"], "peak_tss": _peak}
    finally:
        if own:
            session.close()