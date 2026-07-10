"""Race calibration — the real recalibrate-from-race loop.

projection._recalibrate_from_race was a NotImplementedError stub and the
Performance tab's "last recalibrated" card just echoed the last done race's
updated_at — finished races never actually taught the model anything beyond
the 90-day race-anchor ceiling (which silently expires). This module closes
the loop:

  1. When a race is finished (status done + actual_time_seconds), compare
     what the RAW model would have predicted on race eve (a deterministic
     backcast from data as-of that date) against the actual result, and
     persist one ``race_calibrations`` row: predicted, actual, and
     ``correction = actual / predicted`` (UNclamped in storage).
  2. Every future finish estimate is multiplied by the weighted blend of
     those corrections — recency-weighted (half-life
     ``RECENCY_HALF_LIFE_DAYS``) AND distance-similarity-weighted (a race at
     2× / ½× the target distance counts half), combined as a weighted
     geometric mean and clamped to ``CORRECTION_CLAMP`` so one anomalous
     race can never hijack the model.

Corrections always measure the UNCORRECTED estimate chain (backcast without
any prior correction applied) — each calibration is an independent sample of
raw-model bias, and the applied correction is their blend. Persisted
``race_predictions`` rows (what was actually shown to the athlete, correction
included) are kept as honest residual history for a future learned band, not
consumed by the correction math. Unlike the 90-day anchor/floor, the blended
correction never expires — it only fades by being averaged with newer races.

Pure functions where possible; DB access is confined to the thin wrappers at
the bottom. See docs/calculations/projection.md §3.
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any, Optional

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
# Clamp on the APPLIED (blended) correction — a single race can legitimately
# run ±10% off the model (weather, course, pacing error); anything beyond
# that applied blindly would let one anomaly hijack every future estimate.
CORRECTION_CLAMP: tuple[float, float] = (0.90, 1.10)
# Recency: a calibration this many days old carries half the weight of one
# from today.
RECENCY_HALF_LIFE_DAYS: float = 180.0
# Distance similarity: weight = exp(-|ln(d_target / d_race)|) — a race at 2×
# or ½× the target distance carries weight 0.5; same distance carries 1.0.
# (ln-ratio symmetric, so 10k→half and half→10k weigh the same.)
_TIME_CURVE_CEILING_TSB: float = 20.0  # mirrors main._TIME_CURVE_CEILING_TSB
_BACKCAST_WARMUP_DAYS: int = 180
_ANCHOR_WINDOW_DAYS: int = 90


# ── Pure: weighting + blend ──────────────────────────────────────────────────

def calibration_weight(
    cal_race_date: date,
    cal_distance_km: float,
    target_distance_km: Optional[float],
    today: date,
) -> float:
    """Combined recency × distance-similarity weight for one calibration."""
    age_days = max(0, (today - cal_race_date).days)
    recency_w = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
    if not target_distance_km or not cal_distance_km or cal_distance_km <= 0 or target_distance_km <= 0:
        distance_w = 1.0
    else:
        distance_w = math.exp(-abs(math.log(float(target_distance_km) / float(cal_distance_km))))
    return recency_w * distance_w


def combined_correction(
    calibrations: list[dict],
    target_distance_km: Optional[float],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Blend stored calibrations into one applied correction factor.

    calibrations: [{"race_date": date, "distance_km": float, "correction": float}]
    Returns {"correction": float (clamped, 1.0 when no data), "n": int,
             "raw_correction": float|None (unclamped blend)}.

    Weighted GEOMETRIC mean — corrections are multiplicative factors, so the
    arithmetic mean of e.g. 0.5 and 2.0 (1.25) would claim a bias that isn't
    there; the geometric mean (1.0) doesn't.
    """
    today = today or date.today()
    num = 0.0
    den = 0.0
    n = 0
    for c in calibrations:
        corr = c.get("correction")
        if not isinstance(corr, (int, float)) or corr <= 0:
            continue
        w = calibration_weight(c["race_date"], float(c.get("distance_km") or 0), target_distance_km, today)
        if w <= 0:
            continue
        num += w * math.log(float(corr))
        den += w
        n += 1
    if n == 0 or den <= 0:
        return {"correction": 1.0, "n": 0, "raw_correction": None}
    raw = math.exp(num / den)
    lo, hi = CORRECTION_CLAMP
    return {"correction": max(lo, min(hi, raw)), "n": n, "raw_correction": round(raw, 4)}


# ── Backcast: what the raw model predicted on race eve ──────────────────────

def backcast_prediction(user_id: str, race, db) -> Optional[int]:
    """Deterministically recompute the RAW model's race-eve finish estimate
    for ``race``, using only data dated before the race: load curves as-of
    the eve, race-anchor ceiling / Riegel floor from OTHER races finished in
    the 90 days before it, expressible-score TSB factor — the same chain
    _race_readiness_impl runs, minus any calibration correction (see module
    docstring). Returns predicted seconds, or None when it can't be formed
    (no distance, no load history, estimator returns nothing).

    Uses TODAY's threshold_pace preference — historical preference values
    aren't versioned; documented approximation.
    """
    from backend.models import Race, UserPreferences
    from backend.services.training_load import (
        daily_tss_series,
        compute_load_curves,
        resolve_user_ewma_days,
    )
    from backend.services.score_ceiling import (
        ceiling_from_b_race_result,
        projected_ctl_to_score_ceiling,
    )
    from backend.services.projection import compute_expressible_score
    from backend.services.race_finish_estimator import score_to_estimated_finish_time
    from backend.services.riegel import riegel_project

    if race.distance_km is None or race.race_date is None:
        return None
    distance = float(race.distance_km)
    eve = race.race_date - timedelta(days=1)

    prefs = (
        db.query(UserPreferences)
        .filter(UserPreferences.user_id == race.user_id)
        .first()
    )
    threshold_pace = prefs.threshold_pace_seconds_per_km if prefs else None

    series = daily_tss_series(str(user_id), eve - timedelta(days=_BACKCAST_WARMUP_DAYS), eve)
    if not series:
        return None
    ctl_days, atl_days = resolve_user_ewma_days(str(user_id))
    curves = compute_load_curves(series, ctl_days=ctl_days, atl_days=atl_days)
    rows = [r for r in curves if r["date"] <= eve]
    if not rows:
        return None
    eve_row = rows[-1]

    prior_races = (
        db.query(Race)
        .filter(
            Race.user_id == race.user_id,
            Race.id != race.id,
            Race.status == "done",
            Race.actual_time_seconds.isnot(None),
            Race.distance_km.isnot(None),
            Race.race_date >= eve - timedelta(days=_ANCHOR_WINDOW_DAYS),
            Race.race_date <= eve,
        )
        .all()
    )

    anchor = None
    if threshold_pace and float(threshold_pace) > 0:
        for pr in prior_races:
            c = ceiling_from_b_race_result(
                pr.actual_time_seconds, float(pr.distance_km), float(threshold_pace)
            )
            ec = c.get("endurance_ceiling")
            if ec is not None and (anchor is None or ec > anchor):
                anchor = ec
    if anchor is not None:
        base = anchor
    else:
        base = projected_ctl_to_score_ceiling(eve_row["ctl"], reference_date=eve)["endurance_ceiling"]

    expressible = compute_expressible_score(base, eve_row["tsb"], _TIME_CURVE_CEILING_TSB)
    est = score_to_estimated_finish_time(
        expressible, {"threshold_pace_seconds_per_km": threshold_pace}, distance
    )
    seconds = est.get("estimated_finish_seconds")
    if seconds is None:
        return None

    # Riegel floor from the same prior races — part of the raw model.
    caps = [
        riegel_project(pr.actual_time_seconds, float(pr.distance_km), distance)
        for pr in prior_races
    ]
    caps = [c for c in caps if c is not None]
    if caps:
        seconds = min(seconds, min(caps))
    return int(seconds)


# ── DB wrappers ──────────────────────────────────────────────────────────────

def recalibrate_race(user_id: str, race, db) -> Optional[dict]:
    """Compute + upsert the ``race_calibrations`` row for one finished race.
    Returns the calibration dict, or None when a prediction can't be formed."""
    from sqlalchemy.dialects.postgresql import insert as _pg_insert
    from backend.models import RaceCalibration

    if race.actual_time_seconds is None or race.status != "done":
        return None
    predicted = backcast_prediction(user_id, race, db)
    if predicted is None or predicted <= 0:
        return None
    correction = round(float(race.actual_time_seconds) / float(predicted), 4)

    values = {
        "user_id": race.user_id,
        "race_id": race.id,
        "race_date": race.race_date,
        "distance_km": race.distance_km,
        "predicted_seconds": int(predicted),
        "actual_seconds": int(race.actual_time_seconds),
        "correction": correction,
        "source": "backcast",
    }
    stmt = (
        _pg_insert(RaceCalibration)
        .values(**values)
        .on_conflict_do_update(index_elements=["race_id"], set_={
            k: v for k, v in values.items() if k not in ("user_id", "race_id")
        })
    )
    db.execute(stmt)
    db.commit()
    return {
        "race_id": str(race.id),
        "race_date": race.race_date.isoformat(),
        "predicted_seconds": int(predicted),
        "actual_seconds": int(race.actual_time_seconds),
        "correction": correction,
    }


def ensure_calibrations(user_id: str, db) -> int:
    """Lazily create calibrations for every finished race that lacks one —
    the single choke point (called from the plan bundle) that makes the loop
    self-healing regardless of which endpoint marked the race done. Returns
    how many rows were created."""
    from backend.models import Race, RaceCalibration

    done = (
        db.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "done",
            Race.actual_time_seconds.isnot(None),
            Race.distance_km.isnot(None),
        )
        .all()
    )
    if not done:
        return 0
    have = {
        row.race_id
        for row in db.query(RaceCalibration.race_id)
        .filter(RaceCalibration.race_id.in_([r.id for r in done]))
        .all()
    }
    created = 0
    for race in done:
        if race.id in have:
            continue
        try:
            if recalibrate_race(user_id, race, db) is not None:
                created += 1
        except Exception:
            _log.warning("recalibrate_race failed for race %s", race.id, exc_info=True)
            db.rollback()
    return created


def load_calibrations(user_id: str, db) -> list[dict]:
    """All stored calibrations for a user, shaped for combined_correction."""
    from backend.models import RaceCalibration

    rows = (
        db.query(RaceCalibration)
        .filter(RaceCalibration.user_id == user_id)
        .order_by(RaceCalibration.race_date.desc())
        .all()
    )
    return [
        {
            "race_id": str(r.race_id),
            "race_date": r.race_date,
            "distance_km": float(r.distance_km),
            "correction": float(r.correction),
            "predicted_seconds": r.predicted_seconds,
            "actual_seconds": r.actual_seconds,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def record_prediction(user_id: str, race_id, predicted_seconds: int, band_seconds, db) -> None:
    """Upsert today's shown prediction for a race (one row per race per day).
    Honest residual history for a future learned band — never consumed by
    the correction math (see module docstring). Best-effort: failures log
    and never break the caller."""
    from sqlalchemy.dialects.postgresql import insert as _pg_insert
    from backend.models import RacePrediction

    try:
        stmt = (
            _pg_insert(RacePrediction)
            .values(
                user_id=user_id,
                race_id=race_id,
                prediction_date=date.today(),
                predicted_seconds=int(predicted_seconds),
                band_seconds=int(band_seconds) if band_seconds is not None else None,
            )
            .on_conflict_do_update(
                index_elements=["race_id", "prediction_date"],
                set_={
                    "predicted_seconds": int(predicted_seconds),
                    "band_seconds": int(band_seconds) if band_seconds is not None else None,
                },
            )
        )
        db.execute(stmt)
        db.commit()
    except Exception:
        _log.warning("record_prediction failed for race %s", race_id, exc_info=True)
        db.rollback()
