"""Races-and-projections card for the Performance page (revamp P4-10).

One payload from one projection call: calibration tiles, the projection chain
(endurance pace -> speed pace -> blended pace -> model correction -> projected
finish) and the time-scaled chart. The UI renders it; it never multiplies.

Sources (nothing new is modelled here):

- estimate and band .... ``race_finish_estimate.estimate_race_finish`` — the
  same call the hero uses, so the chain final, the hero and the chart tip are
  the same number by construction (and ``check_invariants`` asserts it).
- stage paces .......... ``race_finish_estimator.blended_scores_estimate`` basis
- model correction ..... ``race_calibration.combined_correction`` over
  ``load_calibrations`` (pb / a_race only — see ``race_roles``)
- calibration tiles .... ``main._compute_calibration_status`` (pure helper)
- history line ......... ``race_predictions`` rows for the race (what was shown)

The chain's final stage also carries the taper/form factor and the
demonstrated-race (Riegel) cap that ``estimate_race_finish`` folds in; they are
not separate stages because they are not separate numbers in the estimate.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from backend.services.perf_a_race import next_a_race
from backend.services.race_finish_estimate import _fmt_hms, estimate_race_finish
from backend.services.race_roles import RECALIBRATING_ROLES, race_role
from backend.utils.log import get_logger

_log = get_logger(__name__)
_UNSET = object()

NOT_AVAILABLE = "not available"
DEFAULT_HISTORY_DAYS = 84
GOAL_PROVISIONAL = "provisional"
GOAL_LOCKED = "locked"


def _pace(sec: Optional[int], km: Optional[float]) -> Optional[int]:
    if sec is None or not km:
        return None
    from backend.models import compute_goal_pace

    pace, _ = compute_goal_pace(sec, km)
    return pace


def _na(**extra: Any) -> dict[str, Any]:
    return {"available": False, "reason": NOT_AVAILABLE, **extra}


# ── Calibration tiles ────────────────────────────────────────────────────────

def correction_reading(pct: Optional[float]) -> Optional[str]:
    """Model ran pessimistic when races came in faster than predicted (< 0%)."""
    if pct is None:
        return None
    if pct < 0:
        return "ran pessimistic"
    if pct > 0:
        return "ran optimistic"
    return "on target"


def build_tiles(status: Optional[dict], cal_rows: list[dict], last_race_name: Optional[str],
                blend: Optional[dict]) -> dict[str, Any]:
    """Pure: every tile reads from the calibration services; no source -> not available."""
    status = status or {}
    last_date = status.get("last_calibration_date")
    sufficiency = status.get("data_sufficiency")
    confidence = status.get("band_confidence")
    tiles: dict[str, Any] = {
        "last_recalibrated": (
            {"available": True, "date": last_date, "race_name": last_race_name}
            if last_date else _na()
        ),
        "data_sufficiency": {"available": True, "value": sufficiency} if sufficiency else _na(),
        "band_confidence": {"available": True, "value": confidence} if confidence else _na(),
        "model_correction": _na(),
    }
    n = (blend or {}).get("n")
    factor = (blend or {}).get("correction")
    if n and factor:
        pct = round((float(factor) - 1.0) * 100.0, 1)
        tiles["model_correction"] = {
            "available": True,
            "factor": float(factor),
            "pct": pct,
            "n_races": int(n),
            "reading": correction_reading(pct),
        }
    return tiles


def _calibration_tiles(session, user_id: uuid.UUID, today: date, cal_rows: list[dict],
                       blend: dict) -> dict[str, Any]:
    try:
        from backend.main import (  # pure helper + its window constants
            _CALIB_WINDOW_42, _CALIB_WINDOW_90, _compute_calibration_status,
        )
        from backend.models import Race, TrainingLoadSnapshot

        def _count(days: int) -> int:
            return (
                session.query(TrainingLoadSnapshot)
                .filter(
                    TrainingLoadSnapshot.user_id == user_id,
                    TrainingLoadSnapshot.snapshot_date >= today - timedelta(days=days),
                )
                .count()
            )

        race_count_90 = sum(1 for c in cal_rows if c["race_date"] >= today - timedelta(days=_CALIB_WINDOW_90))
        status = _compute_calibration_status(None, _count(_CALIB_WINDOW_90), _count(_CALIB_WINDOW_42), race_count_90)
        latest = cal_rows[0] if cal_rows else None
        status["last_calibration_date"] = latest["race_date"].isoformat() if latest else None
        name = None
        if latest:
            race = session.get(Race, uuid.UUID(latest["race_id"]))
            name = race.name if race else None
        return build_tiles(status, cal_rows, name, blend)
    except Exception:
        _log.warning("calibration tiles unavailable", exc_info=True)
        return build_tiles(None, [], None, None)


# ── Chain ────────────────────────────────────────────────────────────────────

def _fmt_factor(factor: Optional[float]) -> Optional[str]:
    if factor is None:
        return None
    return f"×{float(factor):.3f}"


def next_upcoming_race(session, user_id: uuid.UUID, today: date):
    """Soonest planned race on or after today (any role). Falls back to the A race."""
    from backend.models import Race

    row = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "planned",
            Race.race_date >= today,
        )
        .order_by(Race.race_date.asc())
        .first()
    )
    return row if row is not None else next_a_race(session, user_id, today)


def build_chain(est: dict[str, Any], basis: Optional[dict], blend: Optional[dict],
                distance_km: Optional[float], goal: dict[str, Any], race_name: str) -> dict[str, Any]:
    """Pure: stage values come from the estimate, blend basis and correction blend."""
    basis = basis or {}

    def _stage_score(name: str) -> dict[str, Any]:
        pace = basis.get(f"{name}_pace_seconds_per_km")
        score = basis.get(f"{name}_score")
        if pace is None:
            return _na(score=score)
        return {"available": True, "score": score, "pace_seconds_per_km": pace}

    blended_pace = basis.get("blended_pace_seconds_per_km")
    blended = (
        {
            "available": True,
            "pace_seconds_per_km": blended_pace,
            "speed_weight_pct": round(float(basis["speed_weight"]) * 100),
        }
        if blended_pace is not None and basis.get("speed_weight") is not None else _na()
    )
    n = (blend or {}).get("n")
    factor = (blend or {}).get("correction")
    if n and factor:
        pct = round((float(factor) - 1.0) * 100.0, 1)
        correction = {"available": True, "factor": float(factor), "pct": pct, "n_races": int(n)}
    else:
        correction = _na()

    if est.get("unavailable") or est.get("est_sec") is None:
        final = _na(race_name=race_name, goal=goal)
        vs_goal = None
        est_sec = None
    else:
        est_sec = int(est["est_sec"])
        band = est.get("band_sec")
        goal_sec = (goal or {}).get("time_sec")
        vs_goal = None
        if goal_sec is not None:
            vs_goal = "faster" if est_sec <= int(goal_sec) else "slower"
        final = {
            "available": True,
            "race_name": race_name,
            "est_sec": est_sec,
            "pace_seconds_per_km": _pace(est_sec, distance_km),
            "band_sec": int(band) if band is not None else None,
            "goal": goal,
            "vs_goal": vs_goal,
        }
    form_factor = est.get("form_factor")
    corr_factor = (blend or {}).get("correction") if blend else None
    if corr_factor is None:
        corr_factor = est.get("correction")
    fitness = (
        {"available": True, "factor": float(form_factor), "formatted": _fmt_factor(form_factor),
         "projected_ctl": est.get("projected_ctl")}
        if form_factor is not None else _na()
    )
    if correction.get("available") and correction.get("factor") is not None:
        correction["formatted"] = _fmt_factor(correction["factor"])
    steps = [
        {"key": "endurance", "label": "Endurance", **{k: _stage_score("endurance").get(k) for k in ("available", "score", "pace_seconds_per_km")}},
        {"key": "speed", "label": "Speed", **{k: _stage_score("speed").get(k) for k in ("available", "score", "pace_seconds_per_km")}},
        {"key": "blend", "label": "Blend", **blended},
        {"key": "fitness", "label": "Race-day fitness", **fitness},
        {"key": "correction", "label": "Model correction", **correction},
        {"key": "final", "label": race_name or "Finish", **final},
    ]
    pre = est.get("pre_correction_sec")
    product = est.get("post_correction_sec")
    if product is None and pre is not None and corr_factor is not None:
        product = int(round(float(pre) * float(corr_factor)))
    return {
        "endurance": _stage_score("endurance"),
        "speed": _stage_score("speed"),
        "blended": blended,
        "fitness": fitness,
        "correction": correction,
        "final": final,
        "steps": steps,
        "pre_correction_sec": pre,
        "product_sec": product,
    }


# ── Goal state ───────────────────────────────────────────────────────────────

def goal_state(session, user_id: uuid.UUID, race) -> dict[str, Any]:
    """Provisional until the last pb race before the A race has a result.

    With no pb race scheduled before the A race there is nothing to wait for the
    goal on, so it stays provisional. Always editable.
    """
    from backend.models import Race

    pbs = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.race_date < race.race_date, Race.status != "abandoned")
        .order_by(Race.race_date.desc())
        .all()
    )
    pbs = [r for r in pbs if race_role(r) == "pb"]
    goal_sec = int(race.goal_time_seconds) if race.goal_time_seconds is not None else None
    state, reason = GOAL_PROVISIONAL, "no pb race before the A race"
    if pbs:
        last = pbs[0]
        if last.status == "done" and last.actual_time_seconds is not None:
            state, reason = GOAL_LOCKED, f"{last.name} has a result"
        else:
            reason = f"waiting on a result for {last.name}"
    return {
        "time_sec": goal_sec,
        "pace_seconds_per_km": _pace(goal_sec, float(race.distance_km) if race.distance_km else None),
        "state": state,
        "reason": reason,
        "editable": True,
    }


# ── Chart ────────────────────────────────────────────────────────────────────

def _assign_tag_lanes(marks: list[dict[str, Any]], *, min_dx: float = 0.08) -> None:
    """Offset overlapping race-name tags (two races ~6 days apart on an 84-day window)."""
    ordered = sorted(marks, key=lambda m: float(m.get("x") or 0.0))
    prev_x: Optional[float] = None
    lane = 0
    for m in ordered:
        x = float(m.get("x") or 0.0)
        if prev_x is not None and abs(x - prev_x) < min_dx:
            lane = 1 - lane
        else:
            lane = 0
        m["tag_lane"] = lane
        prev_x = x


def _x_frac(d: date, start: date, end: date) -> float:
    span = (end - start).days
    if span <= 0:
        return 1.0
    return round(max(0.0, min(1.0, (d - start).days / span)), 4)


def build_chart_history_window(
    *,
    start: date,
    end: date,
    today: date,
    label: str,
    history: list[tuple[date, int]],
    goal_sec: Optional[int],
    recalibrations: list[dict],
    ticks: list[dict],
    pending: list[dict],
) -> dict[str, Any]:
    """History-only chart when there is no upcoming A race (x runs start→today)."""
    base: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "today": today.isoformat(),
        "now_x": _x_frac(today, start, end),
        "race_name": label,
        "history_only": True,
    }
    hist = [
        {"date": d.isoformat(), "x": _x_frac(d, start, end), "est_sec": s}
        for d, s in history
        if start <= d <= end
    ]
    if not hist:
        return {**base, "available": False, "reason": NOT_AVAILABLE}
    ys = [h["est_sec"] for h in hist]
    if goal_sec is not None:
        ys.append(goal_sec)

    def _mark(m: dict) -> dict:
        d = m["date"]
        return {**m, "date": d.isoformat() if hasattr(d, "isoformat") else d, "x": _x_frac(d, start, end)}

    recal_m = [_mark(m) for m in recalibrations]
    tick_m = [_mark(m) for m in ticks]
    pend_m = [_mark(m) for m in pending]
    _assign_tag_lanes(recal_m + tick_m + pend_m)
    return {
        **base,
        "available": True,
        "history": hist,
        "projection": None,
        "band": None,
        "goal_sec": goal_sec,
        "goal_label": _fmt_hms(goal_sec) if goal_sec is not None else None,
        "recalibrations": recal_m,
        "ticks": tick_m,
        "pending": pend_m,
        "y_min_sec": min(ys),
        "y_max_sec": max(ys),
    }


def build_chart(*, start: date, today: date, race, est: dict[str, Any], goal_sec: Optional[int],
                history: list[tuple[date, int]], recalibrations: list[dict], ticks: list[dict],
                pending: list[dict]) -> dict[str, Any]:
    """Pure chart payload. x is real dates (``x`` is the 0..1 position from block
    start to race day); y is seconds. Band labels are estimate -/+ band, exactly."""
    end = race.race_date
    base: dict[str, Any] = {
        "start": start.isoformat(), "end": end.isoformat(), "today": today.isoformat(),
        "now_x": _x_frac(today, start, end), "race_name": race.name,
    }
    if est.get("unavailable") or est.get("est_sec") is None:
        return {**base, "available": False, "reason": NOT_AVAILABLE}

    est_sec = int(est["est_sec"])
    band = est.get("band_sec")
    band_sec = int(band) if band is not None else None
    low = est_sec - band_sec if band_sec is not None else None
    high = est_sec + band_sec if band_sec is not None else None
    hist = [
        {"date": d.isoformat(), "x": _x_frac(d, start, end), "est_sec": s}
        for d, s in history if start <= d <= today
    ]
    ys = [est_sec] + [h["est_sec"] for h in hist]
    for v in (low, high, goal_sec):
        if v is not None:
            ys.append(v)
    def _mark(m: dict) -> dict:
        d = m["date"]
        return {**m, "date": d.isoformat(), "x": _x_frac(d, start, end)}
    recal_m = [_mark(m) for m in recalibrations]
    tick_m = [_mark(m) for m in ticks]
    pend_m = [_mark(m) for m in pending]
    _assign_tag_lanes(recal_m + tick_m + pend_m)
    return {
        **base,
        "available": True,
        "history": hist,
        "projection": {
            "from_x": base["now_x"], "to_x": 1.0, "est_sec": est_sec,
            "est_label": _fmt_hms(est_sec),
        },
        "band": (
            {
                "x": 1.0, "low_sec": low, "high_sec": high, "band_sec": band_sec,
                "low_label": _fmt_hms(low), "high_label": _fmt_hms(high),
            } if band_sec is not None else None
        ),
        "goal_sec": goal_sec,
        "goal_label": _fmt_hms(goal_sec),
        "recalibrations": recal_m,
        "ticks": tick_m,
        "pending": pend_m,
        "y_min_sec": min(ys),
        "y_max_sec": max(ys),
    }


# ── Invariants ───────────────────────────────────────────────────────────────

def check_invariants(payload: dict[str, Any], hero_est_sec: Optional[int] = None) -> list[str]:
    """Return violations (empty when both invariants hold).

    1. chain final est == estimate shown on the hero (and the race list).
    2. chart band labels == estimate -/+ band, and the chart tip == the estimate.
    """
    problems: list[str] = []
    final = (payload.get("chain") or {}).get("final") or {}
    est_sec = final.get("est_sec") if final.get("available") else None
    if hero_est_sec is not None and est_sec != hero_est_sec:
        problems.append(f"chain final {est_sec} != hero estimate {hero_est_sec}")
    chart = payload.get("chart") or {}
    if chart.get("available") and est_sec is not None:
        if chart["projection"]["est_sec"] != est_sec:
            problems.append("chart projection != chain final")
        band = chart.get("band")
        if band is not None:
            if band["low_sec"] != est_sec - band["band_sec"] or band["high_sec"] != est_sec + band["band_sec"]:
                problems.append("band seconds != estimate -/+ band")
            if band["low_label"] != _fmt_hms(est_sec - band["band_sec"]) or \
                    band["high_label"] != _fmt_hms(est_sec + band["band_sec"]):
                problems.append("band labels != estimate -/+ band")
    return problems


# ── Fetch + assemble ─────────────────────────────────────────────────────────

def _reference_race_for_history(session, user_id: uuid.UUID, cal_rows: list[dict]):
    """Race whose stored prediction history best represents the trend line."""
    from backend.models import Race, RacePrediction

    if cal_rows:
        try:
            race = session.get(Race, uuid.UUID(cal_rows[0]["race_id"]))
            if race is not None:
                return race
        except (ValueError, TypeError):
            pass
    row = (
        session.query(Race)
        .join(RacePrediction, RacePrediction.race_id == Race.id)
        .filter(Race.user_id == user_id)
        .order_by(RacePrediction.prediction_date.desc())
        .first()
    )
    return row


def _history(session, race_id) -> list[tuple[date, int]]:
    from backend.models import RacePrediction

    rows = (
        session.query(RacePrediction)
        .filter(RacePrediction.race_id == race_id)
        .order_by(RacePrediction.prediction_date.asc())
        .all()
    )
    return [(r.prediction_date, int(r.predicted_seconds)) for r in rows if r.predicted_seconds]


def _block_start(session, user_id: uuid.UUID, race, today: date) -> date:
    from backend.services import revamp_load_plan, revamp_plan_settings

    try:
        ctx = revamp_plan_settings.plan_context(session, user_id, today=today)
        if ctx is not None and ctx["race"].id == race.id:
            return ctx["block_start"]
    except Exception:
        _log.warning("plan_context failed for block start", exc_info=True)
    try:
        return revamp_load_plan.block_start_for_race(race.race_date)
    except Exception:
        return today - timedelta(days=DEFAULT_HISTORY_DAYS)


def build_built_from(
    session,
    user_id: uuid.UUID,
    today: date,
    cal_rows: list[dict],
) -> dict[str, Any]:
    """Race + time the model learned from most recently, and CP on file (P6-5)."""
    from backend.models import Race
    from backend.services.cp_staleness import get_cp_status

    out: dict[str, Any] = {
        "available": False,
        "race_name": None,
        "race_time_sec": None,
        "race_date": None,
        "cp_w": None,
        "cp_stale": False,
    }
    if cal_rows:
        latest = cal_rows[0]
        out["available"] = True
        out["race_date"] = latest["race_date"].isoformat() if hasattr(latest["race_date"], "isoformat") else latest["race_date"]
        out["race_time_sec"] = latest.get("actual_seconds")
        try:
            race = session.get(Race, uuid.UUID(latest["race_id"]))
            if race:
                out["race_name"] = race.name
        except (ValueError, TypeError):
            pass
    try:
        cp = get_cp_status(session, user_id, today)
        out["cp_w"] = cp.get("current_cp_w")
        out["cp_stale"] = bool(cp.get("stale"))
    except Exception:
        _log.warning("cp status unavailable for projection", exc_info=True)
    if out["cp_w"] is not None:
        out["available"] = True
    return out


def _markers(session, user_id: uuid.UUID, race, start: date, today: date):
    """Recalibration markers (pb / a_race with a calibration row), grey ticks
    (other done races with a result) and pending (past, no result)."""
    from backend.models import Race, RaceCalibration

    cal_race_ids = {
        r.race_id for r in session.query(RaceCalibration.race_id).filter(RaceCalibration.user_id == user_id).all()
    }
    races = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.race_date >= start, Race.race_date <= today, Race.id != race.id)
        .order_by(Race.race_date.asc())
        .all()
    )
    recal, ticks, pending = [], [], []
    for r in races:
        role = race_role(r)
        m = {"date": r.race_date, "race_id": str(r.id), "name": r.name, "role": role}
        if r.status == "done" and r.actual_time_seconds is not None:
            if role in RECALIBRATING_ROLES and r.id in cal_race_ids:
                recal.append(m)
            elif role not in RECALIBRATING_ROLES:
                ticks.append(m)
        elif r.status == "planned" and r.race_date < today:
            pending.append(m)
    return recal, ticks, pending


def build_projection(
    session,
    user_id: uuid.UUID,
    today: date,
    *,
    race: Any = _UNSET,
    overall: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from backend.models import UserPreferences
    from backend.services.race_calibration import (
        combined_correction,
        load_calibrations,
    )
    from backend.services.race_finish_estimator import blended_scores_estimate
    from backend.services.score_reader import get_scores

    if race is _UNSET:
        race = next_upcoming_race(session, user_id, today)

    def _overall() -> dict[str, Any]:
        nonlocal overall
        if overall is None:
            overall = get_scores(user_id, as_of=today)["overall"]
        return overall
    try:
        cal_rows = load_calibrations(str(user_id), session)
    except Exception:
        _log.warning("load_calibrations failed", exc_info=True)
        cal_rows = []
    distance = float(race.distance_km) if race is not None and race.distance_km is not None else None
    blend = combined_correction(cal_rows, distance, today=today)
    payload: dict[str, Any] = {
        "tiles": _calibration_tiles(session, user_id, today, cal_rows, blend),
        "built_from": build_built_from(session, user_id, today, cal_rows),
        "race": None, "goal": None, "chain": None, "chart": None,
        "invariants": {"ok": True, "violations": []},
    }
    if race is None:
        from backend.models import UserPreferences
        from backend.services.axis_spec import MARATHON_DISTANCE_KM
        from backend.services.race_finish_estimator import blended_scores_estimate

        distance = MARATHON_DISTANCE_KM
        try:
            scores = _overall()
            prefs = session.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
            thresholds = {"threshold_pace_seconds_per_km": prefs.threshold_pace_seconds_per_km if prefs else None}
            basis = blended_scores_estimate(
                (scores.get("endurance") or {}).get("score"),
                (scores.get("speed") or {}).get("score"),
                distance,
                thresholds,
            ).get("basis")
            na_est = {"unavailable": True, "est_sec": None, "band_sec": None}
            na_goal: dict[str, Any] = {"time_sec": None, "state": "provisional", "editable": True}
            payload["chain"] = build_chain(na_est, basis, blend, distance, na_goal, "")
        except Exception:
            _log.warning("partial projection chain unavailable", exc_info=True)
        ref = _reference_race_for_history(session, user_id, cal_rows)
        if ref is not None:
            start = max(today - timedelta(days=DEFAULT_HISTORY_DAYS), _block_start(session, user_id, ref, today))
            end = max(today, ref.race_date)
            recal, ticks, pending = _markers(session, user_id, ref, start, today)
            goal_sec = int(ref.goal_time_seconds) if ref.goal_time_seconds is not None else None
            payload["chart"] = build_chart_history_window(
                start=start,
                end=end,
                today=today,
                label=ref.name,
                history=_history(session, ref.id),
                goal_sec=goal_sec,
                recalibrations=recal,
                ticks=ticks,
                pending=pending,
            )
        return payload

    est = estimate_race_finish(user_id, race, today=today, db=session)
    goal = goal_state(session, user_id, race)
    basis = None
    try:
        scores = _overall()
        prefs = session.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
        thresholds = {"threshold_pace_seconds_per_km": prefs.threshold_pace_seconds_per_km if prefs else None}
        basis = blended_scores_estimate(
            (scores.get("endurance") or {}).get("score"),
            (scores.get("speed") or {}).get("score"),
            distance, thresholds,
        ).get("basis")
    except Exception:
        _log.warning("projection basis unavailable", exc_info=True)

    start = _block_start(session, user_id, race, today)
    recal, ticks, pending = _markers(session, user_id, race, start, today)
    payload["race"] = {
        "id": str(race.id), "name": race.name, "race_date": race.race_date.isoformat(),
        "distance_km": distance, "role": race_role(race),
    }
    payload["goal"] = goal
    payload["chain"] = build_chain(est, basis, blend, distance, goal, race.name)
    payload["chart"] = build_chart(
        start=start, today=today, race=race, est=est, goal_sec=goal["time_sec"],
        history=_history(session, race.id), recalibrations=recal, ticks=ticks, pending=pending,
    )
    violations = check_invariants(payload, hero_est_sec=est.get("est_sec") if not est.get("unavailable") else None)
    if violations:
        _log.error("projection invariants violated: %s", violations)
    payload["invariants"] = {"ok": not violations, "violations": violations}
    return payload
