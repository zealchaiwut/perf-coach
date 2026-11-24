"""Revamp plan settings — load + save + preview (P3-12)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import Race, RevampLoadSettings
from backend.services.pref_catalog import get_field, set_field
from backend.services.revamp_load_plan import (
    MIN_BLOCK_WEEKS,
    MIN_BUILD_WEEKS,
    REVAMP_PLAN_DEFAULTS,
    LoadPlanLayoutError,
    _resolve_a_race,
    block_start_for_race,
    chronic_weekly_tss,
    compute_revamp_block_series,
    ensure_snapshots,
    next_monday,
    pre_race_week_count,
    taper_preset,
    validate_block_layout,
    week_starts_in_block,
    weeks_from_block_start_to_race,
)
from backend.services.training_prefs import ensure_active, write_version
from backend.utils.time import today_bangkok
from backend.services.weekly_rollup import normalize_week_start

_PHASE_KEYS = (
    "ramp_pct",
    "build_weeks",
    "peak_hold_weeks",
    "taper_factors",
    "race_week_factor",
    "recover_weeks",
    "rebuild_weeks",
)


def _phase_dict(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    out = {**REVAMP_PLAN_DEFAULTS}
    if not raw:
        return out
    for k in _PHASE_KEYS:
        if k in raw and raw[k] is not None:
            out[k] = raw[k]
    if out.get("peak_tss") is None and raw.get("peak_tss") is not None:
        out["peak_tss"] = raw["peak_tss"]
    return out


def get_row(session: Session, user_id: uuid.UUID) -> Optional[RevampLoadSettings]:
    return session.get(RevampLoadSettings, user_id)


def merged_phase_settings(
    row: Optional[RevampLoadSettings],
    *,
    draft: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    base = _phase_dict(row.phase if row and isinstance(row.phase, dict) else None)
    if row and row.peak_tss is not None:
        base["peak_tss"] = float(row.peak_tss)
    if draft:
        for k in _PHASE_KEYS:
            if k in draft and draft[k] is not None:
                base[k] = draft[k]
        if "peak_tss" in draft:
            base["peak_tss"] = draft["peak_tss"]
    return base


def resolve_a_race(
    session: Session,
    user_id: uuid.UUID,
    today: date,
    *,
    a_race_id: Optional[uuid.UUID] = None,
) -> Optional[Race]:
    if a_race_id:
        race = session.get(Race, a_race_id)
        if (
            race is not None
            and race.user_id == user_id
            and race.race_date > today
            and race.status == "planned"
        ):
            return race
    return _resolve_a_race(session, user_id, today)


def resolve_block_start(
    race_date: date,
    settings: dict[str, Any],
    *,
    block_start_override: Optional[date] = None,
) -> date:
    if block_start_override is not None:
        return normalize_week_start(block_start_override)
    return block_start_for_race(race_date, settings)


def plan_context(
    session: Session,
    user_id: uuid.UUID,
    *,
    today: Optional[date] = None,
    draft: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Resolved race, block, settings, and chronic baseline for revamp load views."""
    today = today or today_bangkok()
    row = get_row(session, user_id)
    a_race_id = None
    block_start_override = None
    max_consecutive = None
    if draft:
        if draft.get("a_race_id"):
            a_race_id = uuid.UUID(str(draft["a_race_id"]))
        if draft.get("block_start"):
            block_start_override = date.fromisoformat(str(draft["block_start"])[:10])
        if draft.get("max_consecutive_days") is not None:
            max_consecutive = int(draft["max_consecutive_days"])
    elif row:
        a_race_id = row.a_race_id
        block_start_override = row.block_start
        max_consecutive = row.max_consecutive_days

    race = resolve_a_race(session, user_id, today, a_race_id=a_race_id)
    if race is None:
        return None
    settings = merged_phase_settings(row, draft=draft)
    block_start = resolve_block_start(
        race.race_date, settings, block_start_override=block_start_override
    )
    chronic = chronic_weekly_tss(session, user_id, today)
    return {
        "race": race,
        "block_start": block_start,
        "settings": settings,
        "chronic_baseline": chronic,
        "max_consecutive_days": max_consecutive,
        "row": row,
    }


def _upcoming_races(session: Session, user_id: uuid.UUID, today: date) -> list[dict[str, Any]]:
    rows = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.race_date > today,
            Race.status == "planned",
        )
        .order_by(Race.race_date)
        .all()
    )
    start = next_monday(today)
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            weeks = weeks_from_block_start_to_race(start, r.race_date)
        except LoadPlanLayoutError:
            weeks = 0
        too_short = weeks < MIN_BLOCK_WEEKS
        out.append(
            {
                "id": str(r.id),
                "name": r.name,
                "race_date": r.race_date.isoformat(),
                "distance_km": float(r.distance_km) if r.distance_km is not None else None,
                "goal_time_seconds": r.goal_time_seconds,
                "priority": r.priority,
                "role": r.role,
                "weeks_away": weeks,
                "too_short": too_short,
                "disabled_reason": (
                    f"Only {weeks} week{'s' if weeks != 1 else ''} away. Too short for a build block."
                    if too_short
                    else None
                ),
            }
        )
    return out


def _upcoming_a_races(session: Session, user_id: uuid.UUID, today: date) -> list[dict[str, Any]]:
    return [r for r in _upcoming_races(session, user_id, today) if r.get("priority") == "A"]


def fit_phases(
    weeks_available: int,
    shape: str = "standard",
    taper_weeks: int = 2,
    overrides: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Fit build / peak-hold / taper / race week into ``weeks_available``.

    Recover and rebuild sit after race day and are not part of this sum.
    """
    weeks_available = int(weeks_available)
    if weeks_available < MIN_BLOCK_WEEKS:
        raise LoadPlanLayoutError(
            f"Need at least {MIN_BLOCK_WEEKS} weeks to the race for a build block."
        )
    shape = (shape or "standard").strip().lower()
    taper_n = max(1, int(taper_weeks or 2))
    race_week = 1
    if shape == "custom":
        o = overrides or {}
        build = int(o.get("build_weeks") or 0)
        peak = int(o.get("peak_hold_weeks") or 0)
        taper_n = int(o.get("taper_weeks") or taper_n)
        total = build + peak + taper_n + race_week
        if total != weeks_available:
            raise LoadPlanLayoutError(
                f"Custom phases sum to {total} weeks but the block has {weeks_available}."
            )
        if build < MIN_BUILD_WEEKS:
            raise LoadPlanLayoutError(
                f"Build would be {build} weeks; keep at least {MIN_BUILD_WEEKS}."
            )
        return {
            "build_weeks": build,
            "peak_hold_weeks": peak,
            "taper_weeks": taper_n,
            "race_week": race_week,
            "taper_factors": taper_preset(taper_n),
            "shape": "custom",
        }

    peak = 0 if shape == "short" else 2
    remaining = weeks_available - race_week - taper_n - peak
    while remaining < MIN_BUILD_WEEKS and peak > 0:
        peak -= 1
        remaining += 1
    if remaining < MIN_BUILD_WEEKS:
        raise LoadPlanLayoutError(
            f"Build would be {remaining} weeks; keep at least {MIN_BUILD_WEEKS}."
        )
    return {
        "build_weeks": remaining,
        "peak_hold_weeks": peak,
        "taper_weeks": taper_n,
        "race_week": race_week,
        "taper_factors": taper_preset(taper_n),
        "shape": "short" if peak == 0 and shape == "short" else ("short" if peak == 0 else shape),
    }


def _prefs_rest_days(session: Session, user_id: uuid.UUID) -> list[int]:
    row = ensure_active(session, user_id)
    days = get_field(row.payload, "rest_days") or []
    return sorted({int(d) for d in days if 0 <= int(d) <= 6})


def settings_payload(session: Session, user_id: uuid.UUID, *, today: Optional[date] = None) -> dict[str, Any]:
    today = today or today_bangkok()
    row = get_row(session, user_id)
    ctx = plan_context(session, user_id, today=today)
    phase = merged_phase_settings(row)
    chronic = chronic_weekly_tss(session, user_id, today) if ctx is None else ctx["chronic_baseline"]
    peak_val, series = compute_revamp_block_series(chronic_baseline=chronic, settings=phase)
    suggested_peak = peak_val
    if ctx:
        for w in series:
            if w["phase"] == "peak_hold":
                suggested_peak = w["target_tss"]
                break
    return {
        "a_race_id": str(row.a_race_id) if row and row.a_race_id else (str(ctx["race"].id) if ctx else None),
        "block_start": (
            row.block_start.isoformat()
            if row and row.block_start
            else (ctx["block_start"].isoformat() if ctx else None)
        ),
        "ramp_pct": phase["ramp_pct"],
        "build_weeks": phase["build_weeks"],
        "peak_hold_weeks": phase["peak_hold_weeks"],
        "peak_tss": row.peak_tss if row and row.peak_tss is not None else phase.get("peak_tss"),
        "taper_factors": phase["taper_factors"],
        "race_week_factor": phase["race_week_factor"],
        "recover_weeks": phase["recover_weeks"],
        "rebuild_weeks": phase["rebuild_weeks"],
        "rest_days": _prefs_rest_days(session, user_id),
        "max_consecutive_days": row.max_consecutive_days if row else None,
        "upcoming_races": _upcoming_races(session, user_id, today),
        "chronic_weekly_tss": chronic,
        "suggested_peak_tss": round(float(suggested_peak), 1),
        "defaults": REVAMP_PLAN_DEFAULTS,
        "has_row": row is not None,
        "next_monday": next_monday(today).isoformat(),
        "min_block_weeks": MIN_BLOCK_WEEKS,
        "race_name": ctx["race"].name if ctx else None,
        "race_date": ctx["race"].race_date.isoformat() if ctx else None,
    }


def validate_draft(session: Session, user_id: uuid.UUID, draft: dict[str, Any], *, today: date) -> None:
    if draft.get("a_race_id"):
        rid = uuid.UUID(str(draft["a_race_id"]))
        race = session.get(Race, rid)
        if race is None or race.user_id != user_id:
            raise ValueError("a_race_id not found")
        if race.priority != "A":
            raise ValueError("a_race must be priority A")
    if draft.get("ramp_pct") is not None:
        ramp = float(draft["ramp_pct"])
        if ramp <= 0 or ramp > 0.25:
            raise ValueError("ramp_pct out of range")
    taper = draft.get("taper_factors")
    if taper is not None:
        if not isinstance(taper, list) or not taper or not all(0 < float(x) <= 1 for x in taper):
            raise ValueError("taper_factors invalid")
    mcd = draft.get("max_consecutive_days")
    if mcd is not None and (int(mcd) < 1 or int(mcd) > 14):
        raise ValueError("max_consecutive_days out of range")


def _draft_race_date(draft: dict[str, Any]) -> Optional[date]:
    raw = draft.get("race_date")
    if not raw:
        return None
    return date.fromisoformat(str(raw)[:10])


def _settings_from_draft(row: Optional[RevampLoadSettings], draft: dict[str, Any]) -> dict[str, Any]:
    settings = merged_phase_settings(row, draft=draft)
    shape = (draft.get("shape") or "").strip().lower()
    if shape in ("standard", "short", "custom") and draft.get("weeks_available"):
        fitted = fit_phases(
            int(draft["weeks_available"]),
            shape,
            taper_weeks=int(draft.get("taper_weeks") or len(settings.get("taper_factors") or [0, 0])),
            overrides=draft,
        )
        settings["build_weeks"] = fitted["build_weeks"]
        settings["peak_hold_weeks"] = fitted["peak_hold_weeks"]
        settings["taper_factors"] = fitted["taper_factors"]
    elif draft.get("taper_weeks") and "taper_factors" not in draft:
        settings["taper_factors"] = taper_preset(int(draft["taper_weeks"]))
    return settings


def _peak_by_ramp(chronic: float, build_weeks: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for pct in (3, 5, 7):
        ramp = pct / 100.0
        peak = chronic * ((1.0 + ramp) ** build_weeks) if build_weeks > 0 else chronic
        out[str(pct)] = round(float(peak), 1)
    return out


def _weeks_payload(
    *,
    week_dates: list[date],
    series: list[dict[str, Any]],
    chronic: float,
    old_series: Optional[list[dict[str, Any]]] = None,
    current_ws: Optional[date] = None,
) -> list[dict[str, Any]]:
    from backend.services.load_plan import ACWR_CEILING_MULT

    ceiling = round(ACWR_CEILING_MULT * float(chronic or 0), 1)
    weeks_out: list[dict[str, Any]] = []
    for i, ws in enumerate(week_dates):
        if current_ws is not None and ws < current_ws:
            continue
        spec = series[i] if i < len(series) else {}
        old = (old_series[i] if old_series and i < len(old_series) else None)
        target = round(float(spec.get("target_tss") or 0), 1)
        before = round(float(old["target_tss"]), 1) if old else None
        weeks_out.append(
            {
                "week_start": ws.isoformat(),
                "phase": spec.get("phase"),
                "target_tss": target,
                "ceiling_tss": ceiling,
                "over_ceiling": bool(ceiling and target > ceiling),
                "before_target_tss": before,
                "after_target_tss": target,
                "changes": before is not None and before != target,
            }
        )
    return weeks_out


def preview_settings_change(
    session: Session,
    user_id: uuid.UUID,
    draft: dict[str, Any],
    *,
    today: Optional[date] = None,
) -> dict[str, Any]:
    from backend.services.plan_warnings import layout_error

    today = today or today_bangkok()
    validate_draft(session, user_id, draft, today=today)
    row = get_row(session, user_id)
    try:
        settings = _settings_from_draft(row, draft)
    except LoadPlanLayoutError as exc:
        return {"allowed": False, "layout_error": {"code": "layout_mismatch", "message": str(exc)}, "weeks": []}
    race_date = _draft_race_date(draft)
    ctx_old = plan_context(session, user_id, today=today)
    ctx_new = plan_context(session, user_id, today=today, draft=draft)

    if ctx_new is None and race_date is None:
        return {"allowed": False, "layout_error": {"code": "no_race", "message": "No A race"}, "weeks": []}

    if ctx_new is not None:
        block_start = ctx_new["block_start"]
        race_date = ctx_new["race"].race_date
        chronic = ctx_new["chronic_baseline"]
        settings = ctx_new["settings"]
        err = layout_error(session, user_id, settings, ctx=ctx_new)
        if err:
            return {"allowed": False, "layout_error": err, "weeks": []}
    else:
        assert race_date is not None
        chronic = chronic_weekly_tss(session, user_id, today)
        if draft.get("block_start"):
            block_start = normalize_week_start(date.fromisoformat(str(draft["block_start"])[:10]))
        else:
            block_start = next_monday(today)
        try:
            weeks_n = weeks_from_block_start_to_race(block_start, race_date)
        except LoadPlanLayoutError as exc:
            return {"allowed": False, "layout_error": {"code": "layout_mismatch", "message": str(exc)}, "weeks": []}
        if weeks_n < MIN_BLOCK_WEEKS:
            return {
                "allowed": False,
                "layout_error": {
                    "code": "too_short",
                    "message": f"Only {weeks_n} weeks away. Too short for a build block.",
                },
                "weeks": [],
            }

    try:
        new_peak, new_series = validate_block_layout(
            chronic_baseline=chronic,
            block_start=block_start,
            race_date=race_date,
            settings=settings,
        )
    except LoadPlanLayoutError as exc:
        return {"allowed": False, "layout_error": {"code": "layout_mismatch", "message": str(exc)}, "weeks": []}

    old_series: Optional[list[dict[str, Any]]] = None
    old_peak = None
    if ctx_old is not None:
        try:
            old_peak, old_series = validate_block_layout(
                chronic_baseline=ctx_old["chronic_baseline"],
                block_start=ctx_old["block_start"],
                race_date=ctx_old["race"].race_date,
                settings=ctx_old["settings"],
            )
        except LoadPlanLayoutError:
            old_series = None

    week_dates = week_starts_in_block(block_start, race_date)
    current_ws = normalize_week_start(today)
    # First-save / no-row drafts include the whole block, including the current week.
    skip_past = current_ws if ctx_old is not None else None
    weeks_out = _weeks_payload(
        week_dates=week_dates,
        series=new_series,
        chronic=chronic,
        old_series=old_series,
        current_ws=skip_past,
    )
    from backend.services.plan_rules_engine import typical_week_check

    rest_days = draft.get("rest_days")
    if rest_days is None:
        rest_days = _prefs_rest_days(session, user_id)
    max_consec = draft.get("max_consecutive_days")
    if max_consec is None and row is not None:
        max_consec = row.max_consecutive_days
    if max_consec is None:
        max_consec = 3

    return {
        "allowed": True,
        "peak_tss": round(new_peak, 1),
        "peak_tss_before": round(old_peak, 1) if old_peak is not None else None,
        "peak_tss_after": round(new_peak, 1),
        "peak_by_ramp": _peak_by_ramp(chronic, int(settings["build_weeks"])),
        "chronic_weekly_tss": round(float(chronic or 0), 1),
        "weeks": weeks_out,
        "block_start": block_start.isoformat(),
        "weeks_available": pre_race_week_count(settings),
        "week_check": typical_week_check(list(rest_days or []), int(max_consec)),
        "settings": {
            "build_weeks": settings["build_weeks"],
            "peak_hold_weeks": settings["peak_hold_weeks"],
            "taper_factors": settings["taper_factors"],
            "ramp_pct": settings["ramp_pct"],
            "recover_weeks": settings["recover_weeks"],
            "rebuild_weeks": settings["rebuild_weeks"],
        },
    }


def apply_settings(
    session: Session,
    user_id: uuid.UUID,
    draft: dict[str, Any],
    *,
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    validate_draft(session, user_id, draft, today=today)
    try:
        phase = _settings_from_draft(get_row(session, user_id), draft)
    except LoadPlanLayoutError:
        phase = merged_phase_settings(get_row(session, user_id), draft=draft)

    preview = preview_settings_change(session, user_id, draft, today=today)
    if not preview.get("allowed"):
        err = preview.get("layout_error") or {}
        raise LoadPlanLayoutError(err.get("message", "layout error"))

    ctx = plan_context(session, user_id, today=today, draft=draft)
    if ctx is None:
        raise LoadPlanLayoutError("No A race")

    row = get_row(session, user_id)
    if row is None:
        row = RevampLoadSettings(user_id=user_id)
        session.add(row)

    if draft.get("a_race_id") is not None:
        row.a_race_id = uuid.UUID(str(draft["a_race_id"])) if draft.get("a_race_id") else None
    if "block_start" in draft:
        raw = draft.get("block_start")
        row.block_start = date.fromisoformat(str(raw)[:10]) if raw else None

    stored_phase = {k: phase[k] for k in _PHASE_KEYS}
    row.phase = stored_phase
    peak = draft.get("peak_tss", phase.get("peak_tss"))
    row.peak_tss = float(peak) if peak is not None and str(peak).strip() != "" else None
    if "max_consecutive_days" in draft:
        mcd = draft.get("max_consecutive_days")
        row.max_consecutive_days = int(mcd) if mcd is not None else None

    if draft.get("rest_days") is not None:
        active = ensure_active(session, user_id)
        payload = dict(active.payload or {})
        set_field(payload, "rest_days", list(draft["rest_days"]))
        write_version(session, user_id, payload, source="user", confirm=True)

    ensure_snapshots(
        session,
        user_id,
        block_start=ctx["block_start"],
        race_date=ctx["race"].race_date,
        chronic_baseline=ctx["chronic_baseline"],
        settings=ctx["settings"],
        today=today,
    )

    return {"saved": True, "preview": preview, "settings": settings_payload(session, user_id, today=today)}