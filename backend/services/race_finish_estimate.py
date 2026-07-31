"""Race-day finish estimate for Coach — Performance-tab source of truth.

Matches the tip of ``_race_readiness_impl`` time_curve.projection[-1]
(estimated_finish_seconds on race day under zero-load taper), without
importing ``backend.main`` (worker-safe).

Preference order:
1. Latest ``RacePrediction`` row for the race (what the Plan/Performance
   bundle last *showed*).
2. Live recompute: End/Spd blend (or CTL/race-anchor ceiling) × capped TSB
   form factor → score_to_estimated_finish_time → calibration × Riegel floor.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.utils.log import get_logger
from backend.utils.time import today_bangkok

_log = get_logger(__name__)

_TIME_CURVE_CEILING_TSB = 20.0
_WARMUP_DAYS = 180


def _fmt_hms(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}" if s else f"{h}:{m:02d}"
    return f"{m}:{s:02d}"


def _endurance_speed_from_cache(db, user_id) -> tuple[float | None, float | None]:
    """Best-effort End/Spd from durable performance cache (may be slightly stale)."""
    try:
        from backend.models import SummaryCache

        row = (
            db.query(SummaryCache)
            .filter(
                SummaryCache.user_id == user_id,
                SummaryCache.cache_key == "performance",
            )
            .first()
        )
        if not row or not isinstance(row.payload, dict):
            return None, None
        if row.payload.get("state") != "scored":
            return None, None
        end = (row.payload.get("endurance") or {}).get("score")
        spd = (row.payload.get("speed") or {}).get("score")
        end_f = float(end) if end is not None else None
        spd_f = float(spd) if spd is not None else None
        return end_f, spd_f
    except Exception:
        return None, None


def _latest_shown_prediction(db, race_id) -> dict | None:
    """Most recent RacePrediction for this race (Performance/Plan shown estimate)."""
    try:
        from backend.models import RacePrediction

        row = (
            db.query(RacePrediction)
            .filter(RacePrediction.race_id == race_id)
            .order_by(RacePrediction.prediction_date.desc())
            .first()
        )
        if row is None or row.predicted_seconds is None:
            return None
        band = row.band_seconds
        return {
            "est_sec": int(row.predicted_seconds),
            "band_sec": int(band) if band is not None else None,
            "source": "race_prediction",
            "as_of": row.prediction_date.isoformat() if row.prediction_date else None,
        }
    except Exception as exc:
        _log.warning("RacePrediction lookup failed: %s", exc)
        return None


def _compute_race_day_estimate(
    db,
    user_id,
    race,
    today: date,
) -> dict[str, Any]:
    """Live recompute of race-day tip (same chain as readiness time_curve)."""
    from backend.models import Race, UserPreferences, EconomyCeilingSnapshot
    from backend.services.training_load import (
        daily_tss_series,
        compute_load_curves,
        resolve_user_ewma_days,
    )
    from backend.services.projection import project_fitness, capped_form_factor
    from backend.services.score_ceiling import (
        ceiling_from_b_race_result,
        projected_ctl_to_score_ceiling,
    )
    from backend.services.race_finish_estimator import (
        score_to_estimated_finish_time,
        speed_weight_for_distance,
    )
    from backend.services.race_calibration import load_calibrations, combined_correction
    from backend.services.riegel import riegel_project

    if race.distance_km is None or race.race_date is None:
        return {"unavailable": True, "reason": "race missing distance or date"}
    if race.race_date <= today:
        return {"unavailable": True, "reason": "race date not in the future"}

    distance_km = float(race.distance_km)
    prefs = (
        db.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )
    threshold_pace = prefs.threshold_pace_seconds_per_km if prefs else None
    thresholds = {"threshold_pace_seconds_per_km": threshold_pace}

    warmup_start = today - timedelta(days=_WARMUP_DAYS)
    tss_series = daily_tss_series(str(user_id), warmup_start, today)
    if not tss_series:
        return {"unavailable": True, "reason": "no training-load history"}
    ctl_days, atl_days = resolve_user_ewma_days(str(user_id))
    load_curves = compute_load_curves(tss_series, ctl_days=ctl_days, atl_days=atl_days)
    if not load_curves:
        return {"unavailable": True, "reason": "empty load curves"}
    last_row = load_curves[-1]

    days_to_race = (race.race_date - today).days
    if days_to_race <= 0:
        return {"unavailable": True, "reason": "race date not in the future"}

    proj_series = project_fitness(
        planned_load=[0.0] * days_to_race,
        start_ctl=float(last_row["ctl"]),
        start_atl=float(last_row["atl"]),
        start_date=today,
    )
    if not proj_series:
        return {"unavailable": True, "reason": "fitness projection empty"}
    race_day = max(proj_series.keys())
    day_data = proj_series[race_day]

    # Base score: End/Spd blend (Performance scores) → race-anchor → CTL ceiling
    end_score, spd_score = _endurance_speed_from_cache(db, user_id)
    blend_base: float | None = None
    if end_score is not None:
        w_s = speed_weight_for_distance(distance_km) if spd_score is not None else 0.0
        blend_base = w_s * (spd_score or 0.0) + (1.0 - w_s) * end_score

    race_anchor: float | None = None
    if threshold_pace and float(threshold_pace) > 0:
        anchor_cut = today - timedelta(days=90)
        done = (
            db.query(Race)
            .filter(
                Race.user_id == user_id,
                Race.status == "done",
                Race.actual_time_seconds.isnot(None),
                Race.distance_km.isnot(None),
                Race.race_date >= anchor_cut,
            )
            .all()
        )
        for dr in done:
            c = ceiling_from_b_race_result(
                dr.actual_time_seconds,
                float(dr.distance_km),
                float(threshold_pace),
            )
            ec = c.get("endurance_ceiling")
            if ec is not None and (race_anchor is None or ec > race_anchor):
                race_anchor = ec

    snap_rows = (
        db.query(EconomyCeilingSnapshot)
        .filter(EconomyCeilingSnapshot.user_id == user_id)
        .order_by(EconomyCeilingSnapshot.snapshot_date.asc())
        .all()
    )
    stimulus_history = [(r.snapshot_date, r.economy_stimulus) for r in snap_rows]

    if blend_base is not None:
        base = blend_base
    elif race_anchor is not None:
        base = race_anchor
    else:
        base = projected_ctl_to_score_ceiling(
            float(day_data["ctl"]),
            stimulus_history=stimulus_history,
            reference_date=today,
        )["endurance_ceiling"]

    expressible = base * capped_form_factor(
        float(day_data["tsb"]), _TIME_CURVE_CEILING_TSB
    )
    raw = score_to_estimated_finish_time(expressible, thresholds, distance_km)
    seconds = raw.get("estimated_finish_seconds")
    if seconds is None:
        return {"unavailable": True, "reason": "estimator returned no finish time"}

    cal_rows = load_calibrations(str(user_id), db)
    correction = combined_correction(cal_rows, distance_km, today=today).get("correction") or 1.0
    seconds = int(round(float(seconds) * float(correction)))

    # Riegel floor from demonstrated races in last 90d
    anchor_cut = today - timedelta(days=90)
    done_races = (
        db.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "done",
            Race.actual_time_seconds.isnot(None),
            Race.distance_km.isnot(None),
            Race.race_date >= anchor_cut,
            Race.race_date <= race_day,
        )
        .all()
    )
    caps = []
    for dr in done_races:
        eq = riegel_project(dr.actual_time_seconds, float(dr.distance_km), distance_km)
        if eq is not None:
            caps.append(int(eq))
    if caps:
        seconds = min(seconds, min(caps))

    cb_pct = float(day_data.get("confidence_band") or 0)
    band_sec = int(seconds * cb_pct / 100.0) if cb_pct else None

    return {
        "unavailable": False,
        "est_sec": int(seconds),
        "band_sec": band_sec,
        "source": "performance_time_curve",
        "as_of": today.isoformat(),
        "race_day": race_day.isoformat() if hasattr(race_day, "isoformat") else str(race_day),
    }


def estimate_race_finish(
    user_id,
    race,
    today: date | None = None,
    db=None,
) -> dict[str, Any]:
    """Return race-day finish estimate for Coach Dream / projection facts.

    Shape::
        {
          "unavailable": bool,
          "est_sec": int | None,
          "est_label": str | None,
          "band_sec": int | None,
          "uncertainty_min": int | None,
          "source": str,
          "reason": str | None,
        }
    """
    from sqlalchemy.orm import Session
    from backend.db import engine

    today = today or today_bangkok()
    _own = db is None
    if _own:
        db = Session(engine)

    try:
        shown = _latest_shown_prediction(db, race.id)
        # Prefer a fresh shown prediction (today or yesterday) — exact SoT.
        if shown and shown.get("as_of"):
            try:
                as_of = date.fromisoformat(str(shown["as_of"])[:10])
                if (today - as_of).days <= 7:
                    est = shown["est_sec"]
                    band = shown.get("band_sec")
                    return {
                        "unavailable": False,
                        "est_sec": est,
                        "est_label": _fmt_hms(est),
                        "band_sec": band,
                        "uncertainty_min": int(round(band / 60)) if band else None,
                        "source": shown["source"],
                        "reason": None,
                    }
            except (TypeError, ValueError):
                pass

        live = _compute_race_day_estimate(db, user_id, race, today)
        if live.get("unavailable"):
            # Stale shown prediction still better than inventing CTL-ratio times
            if shown and shown.get("est_sec"):
                est = shown["est_sec"]
                band = shown.get("band_sec")
                return {
                    "unavailable": False,
                    "est_sec": est,
                    "est_label": _fmt_hms(est),
                    "band_sec": band,
                    "uncertainty_min": int(round(band / 60)) if band else None,
                    "source": "race_prediction_stale",
                    "reason": live.get("reason"),
                }
            return {
                "unavailable": True,
                "est_sec": None,
                "est_label": None,
                "band_sec": None,
                "uncertainty_min": None,
                "source": "none",
                "reason": live.get("reason") or "unavailable",
            }

        est = live["est_sec"]
        band = live.get("band_sec")
        return {
            "unavailable": False,
            "est_sec": est,
            "est_label": _fmt_hms(est),
            "band_sec": band,
            "uncertainty_min": int(round(band / 60)) if band else None,
            "source": live.get("source") or "performance_time_curve",
            "reason": None,
        }
    except Exception as exc:
        _log.warning("estimate_race_finish failed: %s", exc, exc_info=True)
        return {
            "unavailable": True,
            "est_sec": None,
            "est_label": None,
            "band_sec": None,
            "uncertainty_min": None,
            "source": "error",
            "reason": str(exc),
        }
    finally:
        if _own:
            db.close()
